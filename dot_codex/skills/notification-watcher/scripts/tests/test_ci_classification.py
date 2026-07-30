"""Exercise real provider-shaped hard, soft, retry, and dependent outcomes."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import patch

from codex_notification_watcher.ci import classify_ci_jobs
from codex_notification_watcher.cli import main


class CIClassificationTest(unittest.TestCase):
    def test_timeout_is_the_root_not_its_75_broken_dependents(self) -> None:
        jobs: list[object] = [
            {"name": "required tests", "state": "timed_out", "exit_status": -1},
            {"name": "quarantined tests", "state": "failed", "soft_failed": True,
             "exit_status": 90},
        ]
        jobs.extend(
            {"name": f"downstream {index}", "state": "broken",
             "depends_on": ["required tests"]}
            for index in range(75)
        )

        result = classify_ci_jobs(jobs)

        self.assertEqual([job.name for job in result.hard_failures], ["required tests"])
        self.assertEqual(len(result.dependency_blocked), 75)
        self.assertEqual([job.exit_status for job in result.soft_failures], [90])

    def test_automatic_retry_is_not_an_independent_failure(self) -> None:
        result = classify_ci_jobs(
            [{"name": "first attempt", "state": "failed", "exit_status": 1,
              "retry_type": "automatic"}]
        )

        self.assertFalse(result.hard_failures)
        self.assertEqual(len(result.automatically_retried), 1)

    def test_timing_out_has_not_yet_reached_a_terminal_state(self) -> None:
        result = classify_ci_jobs([{"name": "still running", "state": "timing_out"}])

        self.assertFalse(result.hard_failures)
        self.assertEqual([job.name for job in result.in_progress], ["still running"])

    def test_errors_and_expired_required_jobs_are_hard_failures(self) -> None:
        result = classify_ci_jobs(
            [{"name": state, "state": state} for state in ("error", "errored", "expired")]
        )

        self.assertEqual(
            [job.state for job in result.hard_failures], ["error", "errored", "expired"]
        )

    def test_independent_required_cancellation_is_not_lost(self) -> None:
        result = classify_ci_jobs([{"name": "required gate", "state": "canceled"}])

        self.assertEqual([job.name for job in result.hard_failures], ["required gate"])

    def test_cancellation_after_a_root_failure_is_dependency_fallout(self) -> None:
        result = classify_ci_jobs(
            [{"name": "root", "state": "timed_out"},
             {"name": "downstream", "state": "canceled", "depends_on": ["root"]}]
        )

        self.assertEqual([job.name for job in result.hard_failures], ["root"])
        self.assertEqual([job.name for job in result.dependency_blocked], ["downstream"])

    def test_unknown_state_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported CI job state"):
            _ = classify_ci_jobs([{"name": "ambiguous", "state": "mystery"}])

    def test_cli_classifies_without_opening_the_notification_database(self) -> None:
        stdin = StringIO(json.dumps([{"name": "required tests", "state": "timed_out"}]))
        output = StringIO()
        with patch("sys.stdin", stdin), redirect_stdout(output):
            result = main(["classify-ci"])

        self.assertEqual(result, 0)
        classification = json.loads(output.getvalue())
        self.assertEqual(classification["hard_failures"][0]["state"], "timed_out")
