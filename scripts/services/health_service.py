from __future__ import annotations

"""Unified health model for the Stillmark control panel.

This module is deliberately UI-agnostic. It receives already-collected rows from
qt_backend and normalises them into one health report so Dashboard, Studio,
Publish and future tests do not each invent their own definition of “ready”.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_BLOCKING = {"error", "critical", "blocked", "blocker", "fail", "failed", "missing"}
_WARNING = {"warning", "warn", "needs attention", "review", "weak", "recoverable", "orphan-risk"}
_OK = {"ok", "ready", "clean", "pass", "passed", "healthy"}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalise_severity(value: Any, *, default: str = "info") -> str:
    text = str(value or "").strip().lower()
    if text in _BLOCKING:
        return "error"
    if text in _WARNING:
        return "warning"
    if text in _OK:
        return "ok"
    return default


@dataclass(slots=True)
class PortfolioHealthIssue:
    scope: str
    id: str
    message: str
    severity: str = "info"
    source: str = "health"
    action: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "scope": self.scope,
            "id": self.id,
            "message": self.message,
            "severity": self.severity,
            "source": self.source,
            "action": self.action,
        }


@dataclass(slots=True)
class PortfolioHealthReport:
    generated_at: str
    validation_rows: list[dict[str, Any]] = field(default_factory=list)
    source_rows: list[dict[str, Any]] = field(default_factory=list)
    metadata_rows: list[dict[str, Any]] = field(default_factory=list)
    series_rows: list[dict[str, Any]] = field(default_factory=list)
    release_rows: list[dict[str, Any]] = field(default_factory=list)
    issues: list[PortfolioHealthIssue] = field(default_factory=list)
    score: int = 100
    status: str = "ready"
    actions: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "status": self.status,
            "score": self.score,
            "actions": list(self.actions),
            "metrics": dict(self.metrics),
            "issues": [issue.as_dict() for issue in self.issues],
            "validation_rows": list(self.validation_rows),
            "source_rows": list(self.source_rows),
            "metadata_rows": list(self.metadata_rows),
            "series_rows": list(self.series_rows),
            "release_rows": list(self.release_rows),
            "readiness": {
                "score": self.score,
                "status": self.status,
                "actions": list(self.actions),
                "metrics": dict(self.metrics),
                "estimated": False,
            },
        }


def _validation_issues(rows: list[dict[str, Any]]) -> list[PortfolioHealthIssue]:
    issues: list[PortfolioHealthIssue] = []
    for row in rows:
        severity = normalise_severity(row.get("severity"), default="warning")
        issues.append(
            PortfolioHealthIssue(
                scope=str(row.get("scope") or "validation"),
                id=str(row.get("id") or ""),
                message=str(row.get("message") or row.get("detail") or "Validation issue"),
                severity=severity,
                source="validation",
                action="validation",
            )
        )
    return issues


def _source_issues(rows: list[dict[str, Any]]) -> list[PortfolioHealthIssue]:
    issues: list[PortfolioHealthIssue] = []
    for row in rows:
        status = str(row.get("status") or "").strip().lower()
        if status in {"", "ok", "healthy"}:
            continue
        severity = "error" if status in {"missing", "blocked", "error"} else "warning"
        detail = str(row.get("detail") or row.get("recovery") or "Original source image needs attention")
        issues.append(
            PortfolioHealthIssue(
                scope="source",
                id=str(row.get("id") or row.get("work_id") or ""),
                message=detail,
                severity=severity,
                source="source-assets",
                action="source_recovery",
            )
        )
    return issues


def _metadata_issues(rows: list[dict[str, Any]]) -> list[PortfolioHealthIssue]:
    issues: list[PortfolioHealthIssue] = []
    for row in rows:
        status = str(row.get("status") or "").strip().lower()
        score = row.get("score")
        if status in {"ok", "clean", "ready"} or (isinstance(score, int) and score >= 85):
            continue
        issues.append(
            PortfolioHealthIssue(
                scope="metadata",
                id=str(row.get("id") or row.get("work_id") or ""),
                message=str(row.get("issue") or row.get("detail") or "Work metadata needs improvement"),
                severity="warning",
                source="metadata-audit",
                action="works",
            )
        )
    return issues


def _series_issues(rows: list[dict[str, Any]]) -> list[PortfolioHealthIssue]:
    issues: list[PortfolioHealthIssue] = []
    for row in rows:
        try:
            score = int(row.get("score") or 0)
        except Exception:
            score = 0
        if score >= 75:
            continue
        issues.append(
            PortfolioHealthIssue(
                scope="series",
                id=str(row.get("slug") or row.get("id") or ""),
                message=str(row.get("detail") or f"Series completeness is {score}%"),
                severity="warning",
                source="series-completeness",
                action="series",
            )
        )
    return issues


def build_portfolio_health_report(
    *,
    validation_rows: list[dict[str, Any]] | None = None,
    source_rows: list[dict[str, Any]] | None = None,
    metadata_rows: list[dict[str, Any]] | None = None,
    series_rows: list[dict[str, Any]] | None = None,
    release_rows: list[dict[str, Any]] | None = None,
) -> PortfolioHealthReport:
    validation_rows = list(validation_rows or [])
    source_rows = list(source_rows or [])
    metadata_rows = list(metadata_rows or [])
    series_rows = list(series_rows or [])
    release_rows = list(release_rows or [])

    issues: list[PortfolioHealthIssue] = []
    issues.extend(_validation_issues(validation_rows))
    issues.extend(_source_issues(source_rows))
    issues.extend(_metadata_issues(metadata_rows))
    issues.extend(_series_issues(series_rows))

    validation_errors = sum(1 for issue in issues if issue.source == "validation" and issue.severity == "error")
    validation_warnings = sum(1 for issue in issues if issue.source == "validation" and issue.severity == "warning")
    source_blockers = sum(1 for issue in issues if issue.source == "source-assets" and issue.severity == "error")
    source_warnings = sum(1 for issue in issues if issue.source == "source-assets" and issue.severity == "warning")
    metadata_issues = sum(1 for issue in issues if issue.source == "metadata-audit")
    weak_series = sum(1 for issue in issues if issue.source == "series-completeness")
    release_errors = sum(1 for row in release_rows if normalise_severity(row.get("status"), default="info") == "error")
    release_warnings = sum(1 for row in release_rows if normalise_severity(row.get("status"), default="info") == "warning")

    penalty = 0
    penalty += min(45, validation_errors * 9)
    penalty += min(30, source_blockers * 7)
    penalty += min(15, source_warnings * 3)
    penalty += min(18, metadata_issues * 2)
    penalty += min(15, weak_series * 4)
    penalty += min(18, release_errors * 6)
    penalty += min(8, validation_warnings + release_warnings)
    score = max(0, min(100, 100 - penalty))

    if validation_errors or source_blockers or release_errors:
        status = "blocked"
    elif score >= 90:
        status = "ready"
    elif score >= 75:
        status = "review"
    else:
        status = "needs work"

    actions: list[dict[str, Any]] = []
    if validation_errors:
        actions.append({"label": "Fix blocking validation errors", "count": validation_errors, "target": "validation"})
    if source_blockers:
        actions.append({"label": "Relink missing original sources", "count": source_blockers, "target": "source_recovery"})
    if metadata_issues:
        actions.append({"label": "Complete weak work metadata", "count": metadata_issues, "target": "works"})
    if weak_series:
        actions.append({"label": "Improve series completeness", "count": weak_series, "target": "series"})
    if not actions:
        actions.append({"label": "Run release gate before publish", "count": 1, "target": "publish"})

    metrics = {
        "validation_errors": validation_errors,
        "validation_warnings": validation_warnings,
        "source_blockers": source_blockers,
        "source_warnings": source_warnings,
        "metadata_issues": metadata_issues,
        "series_below_75": weak_series,
        "release_errors": release_errors,
        "release_warnings": release_warnings,
        "total_issues": len(issues),
    }
    return PortfolioHealthReport(
        generated_at=utc_stamp(),
        validation_rows=validation_rows,
        source_rows=source_rows,
        metadata_rows=metadata_rows,
        series_rows=series_rows,
        release_rows=release_rows,
        issues=issues,
        score=score,
        status=status,
        actions=actions,
        metrics=metrics,
    )
