"""Sets a new password for a FitForm account (for a user who forgot theirs).
Passwords are stored hashed, so the old one cannot be shown - only replaced. Run it on the device itself:
  python tools/reset_password.py            # lists the accounts
  python tools/reset_password.py Steve      # asks for the new password twice"""

import getpass
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fitform import config                      # noqa: E402
from fitform.session_logger import SessionLogger  # noqa: E402


def main():
    logger = SessionLogger(log_dir=os.path.join(ROOT, config.LOG_DIR))
    if len(sys.argv) < 2:
        users = list(logger._users())
        print("Accounts:", ", ".join(users) if users else "(none)")
        print("Usage: python tools/reset_password.py <username>")
        return 0
    name = logger.find_user(sys.argv[1])
    if name is None:
        print(f"No account called {sys.argv[1]!r}")
        return 1
    pw = getpass.getpass(f"New password for {name}: ")
    if pw != getpass.getpass("Type it again: "):
        print("The two passwords are different - nothing changed")
        return 1
    err = logger.set_password(name, pw)
    if err:
        print(err)
        return 1
    print(f"Password changed for {name}. Log in on the phone with the new one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
