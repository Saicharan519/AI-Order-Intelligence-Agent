"""Create the first admin account (or reset an account's password), interactively.

The password is typed into this terminal (hidden) and stored only as a scrypt hash; it is
never written to .env, printed, or logged. Run it yourself:

    python scripts/create_admin.py --email you@example.com --name "Your Name"
    python scripts/create_admin.py --email you@example.com --reset-password

Admins create invite links for everyone else from the web app's Admin page.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from orderintel.auth.crypto import normalise_email, password_problem
from orderintel.auth.store import AccountError, AccountStore


def ask_password(email: str) -> str:
    while True:
        first = getpass.getpass("Password (hidden): ")
        if problem := password_problem(first, email):
            print(f"  {problem}")
            continue
        if getpass.getpass("Repeat the password: ") != first:
            print("  The two passwords differ; try again.")
            continue
        return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Admin")
    parser.add_argument("--reset-password", action="store_true")
    args = parser.parse_args(argv)

    email = normalise_email(args.email)
    if not email:
        print("That is not a valid email address.", file=sys.stderr)
        return 2
    store = AccountStore()
    password = ask_password(email)
    try:
        if args.reset_password:
            if not store.set_password(email, password):
                print(f"No account for {email}.", file=sys.stderr)
                return 1
            print(f"Password changed for {email}; its other sign-ins were ended.")
            return 0
        user = store.create_user(email, args.name, password, role="admin")
    except AccountError as e:
        print(e.message, file=sys.stderr)
        return 1
    print(f"Admin account created: {user.email}. Sign in at the web app's /login page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
