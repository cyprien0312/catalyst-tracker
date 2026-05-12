import argparse
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

VALID_SEVERITIES = ("LOG", "MED", "HIGH", "CRITICAL")


@dataclass(frozen=True)
class Alert:
    catalyst: str
    severity: str
    subject: str
    body: str

    def __post_init__(self):
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(
                f"severity must be one of {VALID_SEVERITIES}, got {self.severity!r}"
            )


class CatalystBase(ABC):
    name: str = ""

    @abstractmethod
    def run(self) -> list[Alert]:
        ...


def _short_tag(description: str) -> str:
    """Extract 'c1', 'c2', ... from a description like 'Catalyst 1: ...'."""
    lo = description.lower()
    if lo.startswith("catalyst"):
        rest = lo[len("catalyst"):].strip()
        digits = ""
        for ch in rest:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            return f"c{digits}"
    return "catalyst"


def run_cli(
    catalyst_factory: Callable[[argparse.Namespace], CatalystBase],
    *,
    description: str,
    extra_args: Optional[Callable[[argparse.ArgumentParser], None]] = None,
    argv: list[str] | None = None,
) -> int:
    """Shared CLI entry point for catalyst modules.

    Parses --dry-run plus any catalyst-specific flags (via extra_args), runs
    the catalyst returned by catalyst_factory(args), and either prints or
    emails the alerts.
    """
    from lib.notify import send_alert

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--dry-run", action="store_true",
                        help="print alerts instead of emailing")
    if extra_args is not None:
        extra_args(parser)
    args = parser.parse_args(argv)

    tag = _short_tag(description)
    cat = catalyst_factory(args)
    alerts = cat.run()
    if not alerts:
        print(f"{tag}: no alerts")
        return 0
    for a in alerts:
        if args.dry_run:
            print("=" * 72)
            print(a.subject)
            print(a.body)
        else:
            send_alert(a.subject, a.body, severity=a.severity)
    print(f"{tag}: {len(alerts)} alert(s) {'printed' if args.dry_run else 'emailed'}")
    return 0
