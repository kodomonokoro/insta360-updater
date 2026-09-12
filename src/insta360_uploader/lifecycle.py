"""Serial task lifecycle and immutable UI snapshots. Nothing is persisted."""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Callable

STAGE_KEYS = ("copy", "stitch", "audio", "drive", "youtube")
TERMINAL = frozenset(("done", "failed", "skipped"))


def _succeeded(task: "TaskState") -> bool:
    """Whether a terminal task delivered the requested artifact.

    A pre-existing artifact is a successful outcome.  A skipped task caused
    by cancelling the run or by a failed dependency is not.
    """
    return task.state == "done" or (task.state == "skipped" and task.reason == "exists")


@dataclass(frozen=True)
class TaskState:
    key: str
    stage: str
    enabled: bool
    state: str = "pending"
    fraction: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class RunSnapshot:
    tasks: tuple[TaskState, ...]
    finished: bool = False

    @property
    def active(self) -> TaskState | None:
        return next((task for task in self.tasks if task.state == "current"), None)

    @property
    def total(self) -> int:
        return sum(task.enabled for task in self.tasks)

    @property
    def completed(self) -> int:
        return sum(task.enabled and task.state in TERMINAL for task in self.tasks)

    @property
    def fraction(self) -> float:
        active = self.active
        return (self.completed + (active.fraction if active else 0)) / self.total if self.total else 0.0

    @property
    def terminal_clips(self) -> int:
        return sum(
            all(t.state in TERMINAL for t in tasks)
            for tasks in self._enabled_tasks_by_clip().values()
        )

    @property
    def completed_clips(self) -> int:
        """Clips whose enabled stages all produced their required artifacts."""
        return sum(
            all(_succeeded(task) for task in tasks)
            for tasks in self._enabled_tasks_by_clip().values()
        )

    @property
    def failed_clips(self) -> int:
        return len({task.key for task in self.tasks if task.state == "failed"})

    @property
    def cancelled_clips(self) -> int:
        """Clips stopped by the user, excluding clips that already failed."""
        failed = {task.key for task in self.tasks if task.state == "failed"}
        return sum(
            key not in failed and any(task.reason == "cancelled" for task in tasks)
            for key, tasks in self._enabled_tasks_by_clip().items()
        )

    def _enabled_tasks_by_clip(self) -> dict[str, list[TaskState]]:
        clips: dict[str, list[TaskState]] = {}
        for task in self.tasks:
            if task.enabled:
                clips.setdefault(task.key, []).append(task)
        return clips

    def stage_state(self, stage: str) -> str:
        tasks = [t for t in self.tasks if t.stage == stage and t.enabled]
        if not tasks:
            return "excluded"
        if any(t.state == "current" for t in tasks):
            return "current"
        if any(t.state == "failed" for t in tasks):
            return "failed"
        if all(t.state in TERMINAL for t in tasks):
            if all(_succeeded(task) for task in tasks):
                return "done"
            if all(task.state == "skipped" for task in tasks) and not any(
                _succeeded(task) for task in tasks
            ):
                return "skipped"
            return "partial"
        return "pending"

    def stage_fraction(self, stage: str) -> float:
        tasks = [t for t in self.tasks if t.stage == stage and t.enabled]
        return sum(1 if t.state in TERMINAL else t.fraction for t in tasks) / len(tasks) if tasks else 0.0


SnapshotFn = Callable[[RunSnapshot], None]


def enabled_stages(
    *, camera: bool, drive: bool, stop_after_stitch: bool = False, skip_audio_drive: bool = False
) -> tuple[str, ...]:
    """`skip_audio_drive` deliberately skips audio/drive regardless of
    whether Drive is actually configured — the "①②⑤のみ実施" mode, for a
    run where audio backup just isn't wanted this time, distinct from
    Drive never being configured at all (which also skips these stages,
    but is otherwise required for any mode that does want them — see
    config.validate_for_run)."""
    stages = ("copy", "stitch") if camera else ()
    if not (camera and stop_after_stitch):
        stages += (("audio", "drive") if (drive and not skip_audio_drive) else ()) + ("youtube",)
    return stages


class SerialRun:
    def __init__(self, keys: list[str], stages: tuple[str, ...],
                 on_state: SnapshotFn | None = None, on_progress=None):
        self._tasks = {
            (key, stage): TaskState(key, stage, stage in stages,
                                   "pending" if stage in stages else "skipped",
                                   reason="" if stage in stages else "mode")
            for key in keys for stage in STAGE_KEYS
        }
        self.on_state = on_state
        self.on_progress = on_progress
        self.finished = False
        self.emit()

    def snapshot(self) -> RunSnapshot:
        return RunSnapshot(tuple(self._tasks.values()), self.finished)

    def emit(self):
        snapshot = self.snapshot()
        if self.on_state:
            self.on_state(snapshot)
        if self.on_progress:
            self.on_progress(snapshot.completed, snapshot.total,
                             snapshot.active.fraction if snapshot.active else 0.0)

    def fail_clip(self, key: str, stage: str, error: str):
        for identity, task in list(self._tasks.items()):
            if task.key == key and task.state not in TERMINAL:
                self._tasks[identity] = replace(
                    task, state="failed" if task.stage == stage else "skipped",
                    fraction=task.fraction if task.stage == stage else 0.0,
                    reason=error if task.stage == stage else "dependency",
                )
        self.emit()

    def perform(self, key: str, stage: str, operation) -> bool:
        identity = (key, stage)
        task = self._tasks[identity]
        if task.state != "pending":
            return False
        if self.snapshot().active is not None:
            raise RuntimeError("A serial operation is already active")
        self._tasks[identity] = replace(task, state="current")
        self.emit()
        skipped = False

        def progress(fraction):
            current = self._tasks[identity]
            if current.state != "current" or not isfinite(fraction):
                return
            # 100% means the operation returned successfully, not just that
            # ffmpeg/SDK finished producing frames before finalization.
            fraction = max(current.fraction, min(0.99, max(0.0, fraction)))
            self._tasks[identity] = replace(current, fraction=fraction)
            self.emit()

        def skip():
            nonlocal skipped
            skipped = True

        try:
            operation(progress, skip)
        except Exception as exc:
            self.fail_clip(key, stage, str(exc))
            return False
        self._tasks[identity] = replace(task, state="skipped" if skipped else "done",
                                         fraction=1.0, reason="exists" if skipped else "")
        self.emit()
        return True

    def cancel_remaining(self, reason: str = "cancelled"):
        """User-requested stop: every task that never got a chance to
        start becomes `skipped`/reason so `finish()` (which requires every
        task to be terminal) can still be called cleanly. Only touches
        `pending` tasks — never an in-flight `current` one, since this is
        always called between perform() calls, not during one; the
        already-running operation for this clip/stage always finishes
        naturally on its own before this runs (cooperative stop, not a
        forced kill)."""
        for identity, task in list(self._tasks.items()):
            if task.state == "pending":
                self._tasks[identity] = replace(task, state="skipped", reason=reason)
        self.emit()

    def finish(self):
        if any(t.state not in TERMINAL for t in self._tasks.values()):
            raise RuntimeError("Cannot finish a run with unresolved tasks")
        self.finished = True
        self.emit()
