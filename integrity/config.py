from dataclasses import dataclass
import json
import os
import re

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Annotated


DID = re.compile(r"did:[a-z0-9]+:[A-Za-z0-9.:%_-]{1,230}\Z")
DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}\Z")
ENDPOINT = "wss://jetstream.us-east.bsky.network/xrpc/network.bsky.jetstream.subscribeEvents"
ScopeItem = Annotated[str, Field(min_length=1, max_length=512)]


class Scope(BaseModel):
    dids: list[ScopeItem] = Field(default_factory=list, max_length=100)
    keywords: list[ScopeItem] = Field(default_factory=list, max_length=20)
    hashtags: list[ScopeItem] = Field(default_factory=list, max_length=20)
    domains: list[ScopeItem] = Field(default_factory=list, max_length=20)
    urls: list[ScopeItem] = Field(default_factory=list, max_length=20)

    @field_validator("keywords", "hashtags", "domains", "dids", "urls")
    @classmethod
    def clean_items(cls, items, info):
        values = [item.strip() for item in items]
        if info.field_name in {"keywords", "hashtags", "domains"}:
            values = [item.casefold().lstrip("#") for item in values]
        if any(not item for item in values):
            raise ValueError("Scope entries must contain a value")
        if info.field_name == "dids" and any(not DID.fullmatch(item) for item in values):
            raise ValueError("Use AT Protocol DIDs for public accounts")
        if info.field_name == "domains" and any(not DOMAIN.fullmatch(item) for item in values):
            raise ValueError("Use bare domains, such as example.org")
        if info.field_name == "urls":
            from .events import normalize_url

            values = [normalize_url(item) for item in values]
            if any(item is None for item in values):
                raise ValueError("Use absolute HTTP(S) URLs")
        return sorted(set(values))

    @model_validator(mode="after")
    def require_scope(self):
        if not any((self.dids, self.keywords, self.hashtags, self.domains, self.urls)):
            raise ValueError("Supply at least one watchlist filter")
        return self

    @property
    def topical(self):
        return any((self.keywords, self.hashtags, self.domains, self.urls))


class Policy(BaseModel):
    min_accounts: int = Field(default=3, ge=3, le=20)
    min_rounds: int = Field(default=2, ge=2, le=8)
    sync_seconds: int = Field(default=90, ge=10, le=300)
    max_per_minute: int = Field(default=120, ge=10, le=300)
    retention_days: int = Field(default=14, ge=1, le=30)


class NewWatchlist(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=80, pattern=r"\S")]
    scope: Scope
    policy: Policy = Field(default_factory=Policy)


@dataclass(frozen=True)
class Settings:
    database_url: str = "postgresql://integrity:integrity@localhost:5432/integrity"
    mode: str = "fixture"
    endpoint: str = ENDPOINT
    allow_topic_stream: bool = False
    reviewers: dict[str, str] | None = None
    semantic_model: str = ""
    evaluation_reviewers: tuple[str, ...] = ()

    @classmethod
    def from_env(cls):
        mode = os.getenv("INTEGRITY_MODE", "fixture")
        if mode not in {"fixture", "bluesky"}:
            raise ValueError("INTEGRITY_MODE must be fixture or bluesky")
        reviewers = json.loads(os.getenv("INTEGRITY_REVIEWERS", "{}"))
        if not isinstance(reviewers, dict) or any(
            not re.fullmatch(r"[A-Za-z0-9_.@-]{1,80}", key)
            or not isinstance(value, str) or len(value) < 24 or not value.isascii()
            for key, value in reviewers.items()
        ) or len(set(reviewers.values())) != len(reviewers):
            raise ValueError("Supply a unique ASCII token of at least 24 characters per reviewer")
        evaluation_reviewers = tuple(
            name.strip() for name in os.getenv("EVALUATION_REVIEWERS", "").split(",") if name.strip()
        )
        if set(evaluation_reviewers) - reviewers.keys():
            raise ValueError("EVALUATION_REVIEWERS must name configured reviewers")
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            mode=mode,
            allow_topic_stream=os.getenv("ALLOW_TOPIC_STREAM", "") == "1",
            reviewers=reviewers,
            semantic_model=os.getenv("SEMANTIC_MODEL", ""),
            evaluation_reviewers=evaluation_reviewers,
        )
