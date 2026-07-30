"""Classify provider job outcomes without mistaking fallout for its cause."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from .model import object_mapping, required_string


@dataclass(frozen=True, slots=True)
class CIJob:
    """One validated provider job, including retry and dependency evidence."""

    name: str
    state: str
    required: bool
    soft_failed: bool
    exit_status: int | None
    retry_type: str | None
    depends_on: tuple[str, ...]

    @classmethod
    def from_object(cls, value: object) -> CIJob:
        job = object_mapping(value, description="CI job")
        name = required_string(job.get("name"), description="CI job name")
        state = required_string(job.get("state"), description="CI job state").lower()
        required = job.get("required", True)
        soft_failed = job.get("soft_failed", False)
        if not isinstance(required, bool) or not isinstance(soft_failed, bool):
            raise ValueError("CI job requirements must be boolean")

        exit_status = job.get("exit_status")
        if exit_status is not None and (
            isinstance(exit_status, bool) or not isinstance(exit_status, int)
        ):
            raise ValueError("CI job exit status must be an integer")
        retry_type = job.get("retry_type")
        if retry_type is not None:
            retry_type = required_string(retry_type, description="CI job retry type")

        values = job.get("depends_on", [])
        if not isinstance(values, list):
            raise ValueError("CI job dependencies must be a list")
        dependencies = tuple(
            required_string(item, description="CI job dependency")
            for item in cast(list[object], values)
        )
        return cls(
            name=name,
            state=state,
            required=required,
            soft_failed=soft_failed,
            exit_status=exit_status,
            retry_type=retry_type,
            depends_on=dependencies,
        )


@dataclass(frozen=True, slots=True)
class CIClassification:
    """Keep independent hard roots, dependency fallout, and soft jobs separate."""

    hard_failures: tuple[CIJob, ...]
    dependency_blocked: tuple[CIJob, ...]
    soft_failures: tuple[CIJob, ...]
    in_progress: tuple[CIJob, ...]
    automatically_retried: tuple[CIJob, ...]


_HARD_STATES = frozenset({"failed", "timed_out", "error", "errored", "expired"})
_BLOCKED_STATES = frozenset({"broken", "blocked"})
_CANCELED_STATES = frozenset({"canceled", "cancelled"})
_RUNNING_STATES = frozenset(
    {"created", "scheduled", "waiting", "pending", "running", "timing_out"}
)
_NEUTRAL_STATES = frozenset({"passed", "success", "skipped", "manual", "not_run"})


def classify_ci_jobs(value: object) -> CIClassification:
    """Classify every provider state; fail closed on unrecognized evidence."""

    if not isinstance(value, list):
        raise ValueError("CI jobs must be a list")
    jobs = tuple(CIJob.from_object(item) for item in cast(list[object], value))
    hard: list[CIJob] = []
    blocked: list[CIJob] = []
    soft: list[CIJob] = []
    running: list[CIJob] = []
    retried: list[CIJob] = []
    canceled: list[CIJob] = []

    for job in jobs:
        if job.state in _HARD_STATES:
            if job.soft_failed or not job.required:
                soft.append(job)
            elif job.retry_type == "automatic":
                retried.append(job)
            elif job.state == "failed" and job.exit_status == 0:
                raise ValueError("failed CI job cannot have a successful exit status")
            else:
                hard.append(job)
        elif job.state in _BLOCKED_STATES:
            blocked.append(job)
        elif job.state in _CANCELED_STATES:
            canceled.append(job)
        elif job.state in _RUNNING_STATES:
            running.append(job)
        elif job.state not in _NEUTRAL_STATES:
            raise ValueError(f"unsupported CI job state: {job.state}")

    for job in canceled:
        if job.soft_failed or not job.required:
            soft.append(job)
        elif job.depends_on or hard:
            blocked.append(job)
        else:
            hard.append(job)

    return CIClassification(
        hard_failures=tuple(hard),
        dependency_blocked=tuple(blocked),
        soft_failures=tuple(soft),
        in_progress=tuple(running),
        automatically_retried=tuple(retried),
    )
