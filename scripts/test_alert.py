"""Send a single test email to verify Gmail SMTP credentials.

Usage:
    GMAIL_USER=... GMAIL_APP_PASSWORD=... ALERT_TO=... \
        python scripts/test_alert.py
"""
import sys
import time

from lib.notify import send_alert
from lib.state import State


def main() -> int:
    st = State("smoke")
    body = f"catalyst-tracker smoke test at unix={int(time.time())}"
    ok = send_alert(
        "[OPS-TEST] catalyst-tracker SMTP smoke",
        body,
        severity="MED",
        state=st,
    )
    print("sent" if ok else "deduped")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
