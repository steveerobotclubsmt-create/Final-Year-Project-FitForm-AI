"""Sets up the email account FitForm sends password-reset codes from. Run it on the device itself, from the
project folder (fitform_env active), and type the details yourself:
  python tools/setup_email.py
With Gmail: use the address and an APP PASSWORD, not your normal password (Google account -> Security ->
2-Step Verification -> App passwords; 2-Step Verification must be on). The details are stored in logs/mail.json
on this device only (not uploaded to GitHub, readable by the owner only). A test email is sent to check them.
Other providers: python tools/setup_email.py --host smtp.example.com --port 465"""

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fitform import config  # noqa: E402
from fitform.mailer import Mailer, save_settings  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Set up the email account for password-reset codes")
    ap.add_argument("--host", default="smtp.gmail.com")
    ap.add_argument("--port", type=int, default=465, help="SMTP over SSL port (default 465)")
    args = ap.parse_args()

    user = input("Email address FitForm sends from: ").strip()
    if "@" not in user:
        sys.exit("That is not an email address.")
    pw = getpass.getpass("App password (not shown while typing): ").replace(" ", "")
    if not pw:
        sys.exit("No password entered.")
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), config.LOG_DIR)
    path = save_settings(log_dir, user, pw, host=args.host, port=args.port)
    print(f"Saved to {path} (readable by you only). Sending a test email to {user} ...")
    try:
        Mailer(log_dir).send(user, "FitForm email test",
                             "This is a test from FitForm AI: password-reset codes can now be sent by email.")
    except Exception as e:
        sys.exit(f"The test email could not be sent: {e}\n"
                 "Check the address and the app password, and that the Pi is online, then run this again.")
    print("Test email sent - check the inbox. Password reset by email is now on.")


if __name__ == "__main__":
    main()
