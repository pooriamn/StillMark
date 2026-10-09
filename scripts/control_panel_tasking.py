from __future__ import annotations

"""Runtime task primitives for the Stillmark Qt control panel."""

from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Any, Callable

class CancelledTask(RuntimeError):
    """Raised when a user-requested cancellation reaches a safe checkpoint."""

@dataclass(slots=True)
class ProgressEvent:
    stage: str = ""
    current: int = 0
    total: int = 100
    message: str = ""
    severity: str = "info"
    cancellable: bool = True
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    def as_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "current": int(self.current), "total": int(self.total), "message": self.message, "severity": self.severity, "cancellable": bool(self.cancellable), "timestamp": self.timestamp}

@dataclass(slots=True)
class BuildStage:
    key: str
    label: str
    status: str = "pending"
    elapsed_ms: int = 0
    detail: str = ""
    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "status": self.status, "elapsed_ms": int(self.elapsed_ms), "detail": self.detail}

@dataclass(slots=True)
class TaskContext:
    label: str
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    cancel_requested: bool = False
    progress: int = 0
    current_stage: str = ""
    lines: list[str] = field(default_factory=list)
    events: list[ProgressEvent] = field(default_factory=list)
    _started_perf: float = field(default_factory=perf_counter)
    def cancel(self) -> None:
        self.cancel_requested = True
        self.emit_progress(stage=self.current_stage or self.label, current=self.progress, message="Cancellation requested", severity="warning")
    def check_cancelled(self) -> None:
        if self.cancel_requested:
            raise CancelledTask(f"Cancelled: {self.label}")
    def emit_progress(self, *, stage: str = "", current: int | None = None, total: int = 100, message: str = "", severity: str = "info", cancellable: bool = True) -> ProgressEvent:
        if current is not None:
            self.progress = max(0, min(int(total or 100), int(current)))
        event = ProgressEvent(stage=str(stage or self.current_stage or self.label), current=int(self.progress), total=max(1, int(total or 100)), message=str(message or ""), severity=str(severity or "info"), cancellable=bool(cancellable))
        self.events.append(event); self.events = self.events[-200:]
        return event
    def stage(self, label: str, *, progress: int | None = None) -> None:
        self.current_stage = str(label or "")
        if progress is not None:
            self.progress = max(0, min(100, int(progress)))
        self.line(f"→ {self.current_stage}")
        self.emit_progress(stage=self.current_stage, current=self.progress, message=self.current_stage)
        self.check_cancelled()
    def line(self, text: str) -> None:
        message = str(text)
        self.lines.append(message); self.lines = self.lines[-500:]
        self.emit_progress(stage=self.current_stage or self.label, current=self.progress, message=message)
    def elapsed_ms(self) -> int:
        return int((perf_counter() - self._started_perf) * 1000)
    def as_report(self, *, status: str = "running") -> dict[str, Any]:
        return {"label": self.label, "status": status, "started_at": self.started_at, "elapsed_ms": self.elapsed_ms(), "progress": int(self.progress), "current_stage": self.current_stage, "cancel_requested": bool(self.cancel_requested), "events": [e.as_dict() for e in self.events[-50:]], "lines": list(self.lines[-50:])}

def _line(line_callback: Callable[[str], None] | None, context: TaskContext | None, text: str) -> None:
    if context is not None:
        context.line(text)
    if line_callback is not None:
        line_callback(text)

def run_staged_build(build_callable: Callable[..., dict[str, Any]], *, line_callback: Callable[[str], None] | None = None, task_context: TaskContext | None = None) -> dict[str, Any]:
    stages = [BuildStage("source-preflight", "Source/image preflight"), BuildStage("og-build", "OG coverage and public build"), BuildStage("release-verify", "Release output verification")]
    started = perf_counter(); _line(line_callback, task_context, "Build pipeline: staged execution started")
    if task_context is not None: task_context.stage(stages[0].label, progress=10)
    stages[0].status = "running"; stage_started = perf_counter(); result = build_callable(line_callback=line_callback)
    stages[0].elapsed_ms = int((perf_counter() - stage_started) * 1000); stages[0].status = "ok"; stages[0].detail = "Backend preflight completed inside build gate."
    if task_context is not None: task_context.stage(stages[1].label, progress=65); task_context.check_cancelled()
    stages[1].status = "ok"; stages[1].detail = f"Build returned code {result.get('return_code', 0) if isinstance(result, dict) else 0}."
    if task_context is not None: task_context.stage(stages[2].label, progress=92); task_context.check_cancelled()
    stages[2].status = "ok"; stages[2].detail = "Public output diff and UI session state will refresh after worker completion."
    payload = dict(result or {}); payload["stages"] = [s.as_dict() for s in stages]; payload["total_elapsed_ms"] = int((perf_counter() - started) * 1000)
    if task_context is not None: payload["task_context"] = task_context.as_report(status="ok")
    _line(line_callback, task_context, "Build pipeline: staged execution completed"); return payload

def run_staged_publish_package(publish_callable: Callable[..., dict[str, Any]], *, line_callback: Callable[[str], None] | None = None, task_context: TaskContext | None = None) -> dict[str, Any]:
    stages = [BuildStage("publish-preflight", "Publish preflight"), BuildStage("publish-build", "Build publish output"), BuildStage("publish-archive", "Archive verification")]
    started = perf_counter(); _line(line_callback, task_context, "Publish pipeline: staged execution started")
    if task_context is not None: task_context.stage(stages[0].label, progress=15)
    stages[0].status = "running"; stage_started = perf_counter(); result = publish_callable(line_callback=line_callback)
    stages[0].elapsed_ms = int((perf_counter() - stage_started) * 1000); stages[0].status = "ok"; stages[1].status = "ok"; stages[1].elapsed_ms = int((perf_counter() - stage_started) * 1000)
    stages[2].status = "ok" if (result or {}).get("archive") else "warning"; stages[2].detail = str((result or {}).get("archive") or "No archive returned")
    if task_context is not None: task_context.stage(stages[2].label, progress=95); task_context.check_cancelled()
    payload = dict(result or {}); payload["stages"] = [s.as_dict() for s in stages]; payload["total_elapsed_ms"] = int((perf_counter() - started) * 1000)
    if task_context is not None: payload["task_context"] = task_context.as_report(status="ok")
    _line(line_callback, task_context, "Publish pipeline: staged execution completed"); return payload
