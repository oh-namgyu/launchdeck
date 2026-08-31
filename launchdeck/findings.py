"""What ``ldm doctor`` produces: one Finding per observation, plus the Report.

Kept apart from the checks themselves so the output layer can render a report
without importing the check logic.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

SEVERITY_WARN = "warn"
SEVERITY_INFO = "info"

CHECK_CLUTTER = "clutter"
CHECK_PLIST = "plist"
CHECK_PROGRAM = "program"
CHECK_EXIT = "exit"
CHECK_UNLOADED = "unloaded"
CHECK_FOREIGN = "foreign"
CHECK_LOG_SIZE = "log-size"

# Check order and section titles, used for grouped output.
CHECK_TITLES: Tuple[Tuple[str, str], ...] = (
    (CHECK_CLUTTER, "leftover files in the LaunchAgents directory"),
    (CHECK_PLIST, "plists ldm could not read"),
    (CHECK_PROGRAM, "programs that are not where the plist says"),
    (CHECK_EXIT, "jobs whose last run did not end cleanly"),
    (CHECK_UNLOADED, "plists launchd has not loaded"),
    (CHECK_FOREIGN, "loaded jobs with no plist in your folder"),
    (CHECK_LOG_SIZE, "large log files"),
)


@dataclass
class Finding:
    """One thing doctor noticed, about one job or one file."""

    check: str
    severity: str
    subject: str
    message: str
    suggestion: str

    def to_dict(self) -> Dict[str, Any]:
        """Return the JSON contract shape for one finding."""
        return {
            "check": self.check,
            "severity": self.severity,
            "label_or_path": self.subject,
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass
class Report:
    """Everything doctor found in one run."""

    findings: List[Finding] = field(default_factory=list)

    @property
    def warnings(self) -> int:
        """How many findings are warn-severity."""
        return sum(1 for f in self.findings if f.severity == SEVERITY_WARN)

    @property
    def notices(self) -> int:
        """How many findings are info-severity."""
        return sum(1 for f in self.findings if f.severity == SEVERITY_INFO)

    @property
    def subjects(self) -> int:
        """How many distinct jobs or files the findings are about."""
        return len({f.subject for f in self.findings})

    def grouped(self) -> List[Tuple[str, List[Finding]]]:
        """Group findings by check, as ``(title, findings)``, empty ones dropped."""
        groups = []
        for name, title in CHECK_TITLES:
            hits = [f for f in self.findings if f.check == name]
            if hits:
                groups.append((title, hits))
        return groups

    def to_dict(self) -> Dict[str, Any]:
        """Return the ``findings`` + ``summary`` half of the JSON contract."""
        return {
            "findings": [f.to_dict() for f in self.findings],
            "summary": {"warnings": self.warnings, "notices": self.notices},
        }
