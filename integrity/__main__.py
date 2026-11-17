import argparse
import asyncio
from datetime import datetime, timezone
import logging
import time

from .collector import collect, probe
from .config import DID, Settings
from .store import analyze_one, connect, migrate, purge

LOG = logging.getLogger(__name__)


def run_analysis(settings):
    last_purge = -3600
    while True:
        try:
            if time.monotonic() - last_purge > 3600:
                with connect(settings.database_url) as db:
                    purge(db, datetime.now(timezone.utc))
                last_purge = time.monotonic()
            with connect(settings.database_url) as db:
                worked = analyze_one(db, semantic_model=settings.semantic_model)
            if not worked:
                time.sleep(1)
        except Exception as exc:
            LOG.error("analysis_rollback reason=%s", type(exc).__name__)
            time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description="Community integrity pipeline")
    parser.add_argument("command", choices=["migrate", "collect", "analyze", "probe"])
    parser.add_argument("--did", help="Restrict the live protocol probe to one public DID")
    args = parser.parse_args()
    if args.did and not DID.fullmatch(args.did):
        parser.error("--did must be a valid AT Protocol DID")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    if args.command == "probe":
        asyncio.run(probe(settings, args.did))
        return
    migrate(settings.database_url)
    if args.command == "collect":
        if settings.mode != "bluesky":
            parser.error("Set INTEGRITY_MODE=bluesky to enable collection")
        asyncio.run(collect(settings))
    if args.command == "analyze":
        run_analysis(settings)


if __name__ == "__main__":
    main()
