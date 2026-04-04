"""
Retention cleanup service.

Deletes case data after the configured retention window elapses.
"""

from __future__ import annotations

import threading
from typing import List

from config import settings
from storage.repository import CaseRepository


class RetentionCleanupRunner:
    """Encapsulates one cleanup pass against the case repository."""

    def __init__(self, repo: CaseRepository):
        self.repo = repo

    def run(self) -> List[str]:
        self.repo.sync_for_read(scope="all")
        deleted_case_ids = self.repo.delete_expired_cases()
        if deleted_case_ids:
            print("[Retention] Deleted expired cases:", ", ".join(deleted_case_ids))
        return deleted_case_ids


class RetentionCleanupService:
    """Background janitor that deletes expired cases on a fixed interval."""

    def __init__(
        self,
        repo: CaseRepository,
        interval_seconds: int | None = None,
        runner: RetentionCleanupRunner | None = None,
    ):
        self.repo = repo
        self.interval_seconds = interval_seconds or settings.RETENTION_CLEANUP_INTERVAL_SECONDS
        self.runner = runner or RetentionCleanupRunner(repo)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return

        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="case-retention-cleanup",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_seconds: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout_seconds)
            if self._thread.is_alive():
                return
        self._thread = None

    def run_once(self) -> List[str]:
        return self.runner.run()

    def _run_loop(self) -> None:
        self.run_once()
        while not self._stop_event.wait(self.interval_seconds):
            try:
                self.run_once()
            except Exception as exc:  # pragma: no cover
                print(f"[Retention] Cleanup loop failed: {exc}")
