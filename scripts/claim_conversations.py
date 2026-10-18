"""Give the conversations asked before accounts existed to one account.

Before invite-only accounts, every question came in with the operator key, so those
conversations belong to nobody (user_id NULL) and appear in no account's history. This moves
the API's question rows (config 'api') that have no owner to the account with this email.
Evaluation runs, tests and model-call rows are not touched.

    .venv/Scripts/python scripts/claim_conversations.py --email you@example.com          # shows
    .venv/Scripts/python scripts/claim_conversations.py --email you@example.com --apply  # moves
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from orderintel.auth.store import AccountStore  # noqa: E402
from orderintel.db.connect import connect_trace  # noqa: E402

WHERE = "kind = 'request' AND user_id IS NULL AND config_name = 'api'"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--email", required=True, help="the account that gets the conversations")
    ap.add_argument("--apply", action="store_true", help="move them (default: only show)")
    args = ap.parse_args()

    user = AccountStore().user_by_email(args.email)
    if user is None:
        print(f"No account with the email {args.email}.")
        return 1
    with connect_trace() as conn:
        questions, sessions = conn.execute(
            f"SELECT count(*), count(DISTINCT session_id) FROM trace.requests WHERE {WHERE}"  # noqa: S608  constant
        ).fetchone()
        print(f"Unowned: {questions} questions in {sessions} conversations.")
        if not args.apply:
            print(f"Nothing changed. Add --apply to give them to {user.email}.")
            return 0
        moved = conn.execute(
            f"UPDATE trace.requests SET user_id = %s WHERE {WHERE}",  # noqa: S608  constant
            (user.id,),
        ).rowcount
    print(f"Moved {moved} questions to {user.email}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
