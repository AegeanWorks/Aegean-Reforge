"""Immutable values shared by Reforge's audit, repair, persistence and CLI layers."""

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass(frozen=True)
class CommitInfo:
    """One commit in the window Reforge is auditing."""

    sha: str
    subject: str
    author: str
    date: str


@dataclass(frozen=True)
class Finding:
    """An evidence-backed problem introduced by an audited commit."""

    code: str
    category: str
    severity: str
    path: str
    line: int
    message: str
    evidence: str
    commit: str
    symbol: str = ""
    introduced: bool = True
    reproducible: bool = False
    fixable: bool = False
    interaction: str = ""
    repaired: bool = False

    def key(self) -> Tuple[str, str, int, str]:
        """Stable identity for a finding inside one audit stage."""
        return (self.code, self.path, self.line, self.symbol)

    def as_dict(self) -> Dict[str, object]:
        return {
            "code": self.code,
            "category": self.category,
            "severity": self.severity,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "evidence": self.evidence,
            "commit": self.commit,
            "symbol": self.symbol,
            "introduced": self.introduced,
            "reproducible": self.reproducible,
            "fixable": self.fixable,
            "interaction": self.interaction,
            "repaired": self.repaired,
        }


@dataclass(frozen=True)
class Repair:
    """One repair Reforge made, or deliberately skipped, for a finding."""

    code: str
    path: str
    line: int
    summary: str
    test_name: str = ""
    applied: bool = False

    def as_dict(self) -> Dict[str, object]:
        return {
            "code": self.code,
            "path": self.path,
            "line": self.line,
            "summary": self.summary,
            "test_name": self.test_name,
            "applied": self.applied,
        }


@dataclass(frozen=True)
class StagePlan:
    """The progressive history window for one audit stage."""

    stage: int
    window: int
    commits: Tuple[CommitInfo, ...] = field(default_factory=tuple)
    new_shas: Tuple[str, ...] = field(default_factory=tuple)
    prior_shas: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_new_commits(self) -> bool:
        return bool(self.new_shas)

    def as_dict(self) -> Dict[str, object]:
        return {
            "stage": self.stage,
            "window": self.window,
            "commits": len(self.commits),
            "new_commits": list(self.new_shas),
            "prior_commits": list(self.prior_shas),
        }
