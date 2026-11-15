"""Makes a personalised PDF report for every account that trained in a period (the same report as
'Download my report' on the phone page). Run on the device, from the project folder:
  python tools/make_reports.py                          # last 7 days, up to today
  python tools/make_reports.py --days 30                # last 30 days
  python tools/make_reports.py --from 2026-11-01 --to 2026-11-30
  python tools/make_reports.py --days 30 --user Steve   # one account only
Files go to logs/reports/ (not uploaded to GitHub - they hold personal data):
  <user>_<from>_<to>.pdf. Accounts without a session in the period get no report. Guest sessions are left out."""

import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fitform.report import make_report  # noqa: E402
from fitform.session_logger import SessionLogger  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="PDF report for every account that trained in a period")
    p.add_argument("--days", type=int, default=7, help="the last N days up to today (default 7)")
    p.add_argument("--from", dest="start", help="first day, YYYY-MM-DD (instead of --days)")
    p.add_argument("--to", dest="end", help="last day, YYYY-MM-DD (default today)")
    p.add_argument("--user", help="only this account")
    p.add_argument("--out", default=None, help="folder for the PDFs (default logs/reports)")
    args = p.parse_args()

    today = date.today()
    end = date.fromisoformat(args.end) if args.end else today
    start = date.fromisoformat(args.start) if args.start else end - timedelta(days=max(1, args.days) - 1)
    if start > end:
        sys.exit("--from must be on or before --to")
    logger = SessionLogger()
    out = args.out or os.path.join(logger.dir, "reports")
    os.makedirs(out, exist_ok=True)

    users = sorted(logger._users())
    if args.user:
        name = logger.find_user(args.user)
        if name is None:
            sys.exit(f"No account called {args.user!r}. Accounts: {', '.join(users) or 'none'}")
        users = [name]
    print(f"Period {start} to {end} ({(end - start).days + 1} days), {len(users)} account(s)")
    made = 0
    for user in users:
        pdf = make_report(logger, user, start, end, today=today)
        if pdf is None:
            print(f"  {user}: no sessions - no report")
            continue
        path = os.path.join(out, f"{user}_{start.isoformat()}_{end.isoformat()}.pdf")
        with open(path, "wb") as f:
            f.write(pdf)
        made += 1
        print(f"  {user}: {path}")
    print(f"{made} report(s) made")


if __name__ == "__main__":
    main()
