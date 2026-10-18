"""DEV ONLY: delete the local user's trades and import batches so a tradebook can be imported again from scratch.

Run from backend/ with the dev database in ALTERFOLIO_DATABASE_URL:

    python scripts/reset_ledger.py            # dry run: prints what would be deleted, changes nothing
    python scripts/reset_ledger.py --yes      # deletes (the ledger is append-only inside the app; this is the one escape hatch)

Guards: the database host must be local (localhost, 127.0.0.1, ::1 or a unix socket), and only rows of the configured user
(ALTERFOLIO_USER_ID, default the single local user) are touched. The user row, document chunks and every other table are left alone.
Never wire this into the API.
"""

import argparse
import sys
from pathlib import Path
from uuid import UUID

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND)]

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db.session import make_session_factory  # noqa: E402
from app.models.import_batch import ImportBatch  # noqa: E402
from app.models.trade import Trade  # noqa: E402

LOCAL_HOSTS = {None, "", "localhost", "127.0.0.1", "::1"}


def refuse_non_local(database_url: str) -> None:
    host = make_url(database_url).host
    if host not in LOCAL_HOSTS and not str(host).startswith("/"):
        raise SystemExit(f"refusing to reset a non-local database (host {host!r}); this script is for the local dev database only")


def counts(session: Session, user_id: UUID) -> tuple[int, int]:
    trades = session.scalar(select(func.count()).select_from(Trade).where(Trade.user_id == user_id))
    batches = session.scalar(select(func.count()).select_from(ImportBatch).where(ImportBatch.user_id == user_id))
    return trades or 0, batches or 0


def reset_ledger(session: Session, user_id: UUID) -> tuple[int, int]:
    """Delete the user's trades, then their import batches (trades reference batches). Returns what was deleted."""
    before = counts(session, user_id)
    session.execute(delete(Trade).where(Trade.user_id == user_id))
    session.execute(delete(ImportBatch).where(ImportBatch.user_id == user_id))
    return before


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--yes", action="store_true", help="actually delete (default: dry run)")
    args = ap.parse_args(argv)
    settings = Settings()
    if not settings.database_url:
        raise SystemExit("ALTERFOLIO_DATABASE_URL is not set")
    refuse_non_local(settings.database_url)
    with make_session_factory(settings.database_url)() as session:
        if not args.yes:
            trades, batches = counts(session, settings.user_id)
            print(f"dry run: would delete {trades} trades and {batches} import batches of user {settings.user_id}. Re-run with --yes.")
            return 0
        trades, batches = reset_ledger(session, settings.user_id)
        session.commit()
        print(f"deleted {trades} trades and {batches} import batches of user {settings.user_id}. Upload your tradebooks again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
