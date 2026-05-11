from abc import ABC, abstractmethod
from dataclasses import dataclass

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
