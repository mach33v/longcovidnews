"""Normalized shape of an inspection record.

Every source adapter produces these, so the digest never has to know which
jurisdiction or portal a record came from.
"""

from dataclasses import dataclass, field, asdict
from datetime import date

# VDH classifies violations by how directly they cause foodborne illness.
# Priority > Priority Foundation > Core. Anything else sorts last.
SEVERITY_ORDER = {"priority": 0, "priority foundation": 1, "core": 2, "": 3}


@dataclass
class Violation:
    code: str = ""
    text: str = ""
    severity: str = ""          # "Priority" | "Priority Foundation" | "Core" | ""
    repeat: bool = False
    corrected_on_site: bool = False

    @property
    def rank(self) -> int:
        return SEVERITY_ORDER.get(self.severity.strip().lower(), 3)

    @property
    def is_priority(self) -> bool:
        return self.severity.strip().lower() in ("priority", "priority foundation")


@dataclass
class Inspection:
    id: str
    jurisdiction: str            # "Henrico County" | "Richmond City"
    establishment: str
    inspection_date: date
    address: str = ""
    inspection_type: str = ""    # "Routine", "Follow-up", "Complaint", ...
    url: str = ""
    violations: list[Violation] = field(default_factory=list)

    @property
    def priority_violations(self) -> list[Violation]:
        return [v for v in self.violations if v.is_priority]

    @property
    def repeat_violations(self) -> list[Violation]:
        return [v for v in self.violations if v.repeat]

    @property
    def is_clean(self) -> bool:
        return not self.violations

    def severity_key(self) -> tuple:
        """Sort key: worst inspections first."""
        return (
            -len(self.priority_violations),
            -len(self.repeat_violations),
            -len(self.violations),
            self.establishment.lower(),
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["inspection_date"] = self.inspection_date.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Inspection":
        d = dict(d)
        d["inspection_date"] = date.fromisoformat(d["inspection_date"])
        d["violations"] = [Violation(**v) for v in d.get("violations", [])]
        return cls(**d)
