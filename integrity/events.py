from datetime import datetime, timedelta
import re
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import AwareDatetime, BaseModel, Field, ValidationError, model_validator

from .config import DID, Scope

POST = "app.bsky.feed.post"
COLLECTIONS = (POST, "app.bsky.feed.repost", "app.bsky.feed.like")
HTTP = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
TAG = re.compile(r"(?<!\w)#([\w-]+)")
AT_POST = re.compile(r"at://(did:[a-z0-9]+:[A-Za-z0-9.:%_-]{1,230})/app\.bsky\.feed\.post/([a-zA-Z0-9_.~:-]{1,128})\Z")
PREFIX = "network.bsky.jetstream.subscribeEvents"


def normalize_url(raw: str) -> str | None:
    if len(raw) > 2048 or any(c.isspace() or ord(c) < 32 for c in raw):
        return None
    try:
        url = urlsplit(raw)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username is not None:
            return None
        host = url.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        if not re.fullmatch(r"[a-z0-9.-]+", host):
            return None
        port = url.port
        if port is not None and (url.scheme, port) not in {("http", 80), ("https", 443)}:
            host = f"{host}:{port}"
        return urlunsplit((url.scheme, host, url.path or "/", url.query, ""))
    except (ValueError, UnicodeError):
        return None


class AccountStatus(BaseModel):
    active: bool


class Payload(BaseModel):
    type: Literal[
        "network.bsky.jetstream.subscribeEvents#commit",
        "network.bsky.jetstream.subscribeEvents#account",
    ] = Field(alias="$type")
    did: Annotated[str, Field(pattern=DID.pattern.replace(r"\Z", "$"))]
    seq: int = Field(ge=1, lt=10**15, strict=True)
    time: AwareDatetime
    witnessed_at: AwareDatetime | None = Field(default=None, alias="witnessedAt")
    operation: Literal["create", "update", "delete"] | None = None
    collection: Literal["app.bsky.feed.post", "app.bsky.feed.repost", "app.bsky.feed.like"] | None = None
    rkey: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.~:-]{1,128}$")] | None = None
    cid: Annotated[str, Field(max_length=256)] | None = None
    rev: Annotated[str, Field(max_length=128)] | None = None
    record: dict[str, Any] | None = None
    account: AccountStatus | None = None

    @model_validator(mode="after")
    def validate_commit(self):
        if self.type.endswith("#account"):
            if self.account is None:
                raise ValueError("Account event needs active status")
            return self
        if not self.operation or not self.collection or not self.rkey or self.rkey in {".", ".."}:
            raise ValueError("Incomplete record identifier")
        if self.operation != "delete" and (
            not self.cid or self.record is None or self.record.get("$type") != self.collection
        ):
            raise ValueError("Missing commit record or CID")
        return self


class Envelope(BaseModel):
    type: Literal["message"] = Field(alias="$type")
    payload: Payload


class Ref(BaseModel):
    uri: Annotated[str, Field(max_length=384)]


class Reply(BaseModel):
    parent: Ref
    root: Ref


class RecordFields(BaseModel):
    text: str = Field(default="", max_length=3000)
    created: Annotated[str, Field(max_length=80)] | None = Field(default=None, alias="createdAt")
    subject: Ref | None = None
    reply: Reply | None = None
    tags: list[Annotated[str, Field(max_length=128)]] = Field(default_factory=list, max_length=32)
    facets: list[dict] = Field(default_factory=list, max_length=64)
    embed: dict | None = None


class Record(BaseModel):
    uri: str
    did: str
    collection: str
    cid: str | None
    rev: str | None
    seq: int
    observed_at: AwareDatetime
    event_at: AwareDatetime
    time_source: Literal["record", "stream"]
    deleted: bool = False
    account_event: bool = False
    text: str = ""
    urls: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    refs: dict[str, str] = Field(default_factory=dict)


def normalize(payload: Payload) -> Record:
    observed = payload.witnessed_at or payload.time
    account_event = payload.type.endswith("#account")
    deleted = not payload.account.active if payload.account else payload.operation == "delete"
    fields = RecordFields.model_validate(payload.record or {})
    event_at = observed
    time_source = "stream"
    try:
        created = datetime.fromisoformat((fields.created or "").replace("Z", "+00:00"))
        if created.tzinfo and observed - timedelta(days=7) <= created <= observed + timedelta(minutes=5):
            event_at, time_source = created, "record"
    except ValueError:
        pass

    raw_urls = [m.rstrip(".,;!?)") for m in HTTP.findall(fields.text)]
    tags = set(fields.tags) | set(TAG.findall(fields.text))
    for facet in fields.facets:
        features = facet.get("features")
        for feature in features[:8] if isinstance(features, list) else []:
            if not isinstance(feature, dict):
                continue
            if feature.get("$type") == "app.bsky.richtext.facet#link" and isinstance(feature.get("uri"), str):
                raw_urls.append(feature["uri"])
            if feature.get("$type") == "app.bsky.richtext.facet#tag" and isinstance(feature.get("tag"), str):
                tags.add(feature["tag"][:128])
    refs = {}
    embed = fields.embed or {}
    if embed.get("$type") == "app.bsky.embed.recordWithMedia":
        quote = embed.get("record")
        media = embed.get("media")
        embed = media if isinstance(media, dict) else {}
    else:
        quote = embed
    if embed.get("$type") == "app.bsky.embed.external" and isinstance(embed.get("external"), dict):
        external = embed["external"].get("uri")
        if isinstance(external, str):
            raw_urls.append(external)
    if isinstance(quote, dict) and quote.get("$type") == "app.bsky.embed.record":
        ref = quote.get("record")
        if isinstance(ref, dict) and isinstance(ref.get("uri"), str):
            refs["quote"] = ref["uri"]
    if fields.reply:
        refs.update(reply=fields.reply.parent.uri, thread=fields.reply.root.uri)
    if fields.subject:
        refs["repost" if payload.collection == COLLECTIONS[1] else "like"] = fields.subject.uri
    urls = sorted({url for raw in raw_urls if (url := normalize_url(raw))})[:32]
    return Record(
        uri=payload.did if account_event else f"at://{payload.did}/{payload.collection}/{payload.rkey}",
        did=payload.did, collection=payload.collection or "account", cid=payload.cid, rev=payload.rev,
        seq=payload.seq, observed_at=observed, event_at=event_at, time_source=time_source, deleted=deleted,
        account_event=account_event, text=fields.text, urls=urls,
        domains=sorted({urlsplit(url).hostname for url in urls}),
        tags=sorted({tag.casefold() for tag in tags})[:32],
        refs={kind: uri for kind, uri in refs.items() if AT_POST.fullmatch(uri)},
    )


def match_record(record: Record, scope: Scope) -> bool:
    if scope.dids and record.did not in scope.dids:
        return False
    if scope.dids and (record.collection != POST or not scope.topical):
        return True
    if record.collection != POST:
        return False
    text = record.text.casefold()
    return (
        any(re.search(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", text) for keyword in scope.keywords)
        or bool(set(record.tags).intersection(scope.hashtags))
        or bool(set(record.urls).intersection(scope.urls))
        or any(host == domain or host.endswith("." + domain) for host in record.domains for domain in scope.domains)
    )


def decode(frame: str | bytes) -> tuple[Payload, Record | None]:
    payload = Envelope.model_validate_json(frame).payload
    try:
        return payload, normalize(payload)
    except ValidationError:
        return payload, None
