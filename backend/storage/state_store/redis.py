"""
Redis-backed state store.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import settings
from models.enums import CaseStatus

from .base import StateStore

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RedisStateStore(StateStore):
    """State store implementation using Redis hashes and JSON blobs."""

    def __init__(self, redis_url: str, key_prefix: str = ""):
        if redis is None:
            raise ImportError("redis package is required for RedisStateStore")

        self.client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.key_prefix = key_prefix.strip(":")

    def verify_connection(self) -> None:
        """Validate that the Redis backend is reachable."""
        self.client.ping()

    def _key(self, suffix: str) -> str:
        if self.key_prefix:
            return f"{self.key_prefix}:{suffix}"
        return suffix

    def _status_key(self, case_id: str) -> str:
        return self._key(f"case:{case_id}:status")

    def _pipeline_key(self, case_id: str) -> str:
        return self._key(f"case:{case_id}:pipeline")

    def _artifacts_key(self, case_id: str) -> str:
        return self._key(f"case:{case_id}:artifacts")

    def _batch_key(self, case_id: str) -> str:
        return self._key(f"batch:{case_id}")

    def _lock_key(self, case_id: str) -> str:
        return self._key(f"case:{case_id}:lock:processing")

    def initialize_case(self, case_id: str) -> None:
        now = _utc_now_iso()
        expires_at = datetime.now(timezone.utc).timestamp() + settings.CASE_RETENTION_SECONDS
        self.client.hset(
            self._status_key(case_id),
            mapping={
                "status": CaseStatus.PENDING.value,
                "created_at": now,
                "updated_at": now,
                "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
                "message": "",
                "current_stage": "",
                "progress_percent": "0.0",
            },
        )
        self.client.hset(
            self._pipeline_key(case_id),
            mapping={
                "load_volume": json.dumps({"status": "pending"}),
                "segmentation": json.dumps({"status": "pending"}),
                "sdf": json.dumps({"status": "pending"}),
                "mesh": json.dumps({"status": "pending"}),
                "started_at": "",
                "finished_at": "",
                "error": "",
            },
        )

    def delete_case(self, case_id: str) -> None:
        self.client.delete(
            self._status_key(case_id),
            self._pipeline_key(case_id),
            self._artifacts_key(case_id),
            self._batch_key(case_id),
            self._lock_key(case_id),
        )

    def update_case_status(
        self,
        case_id: str,
        status: str,
        message: Optional[str] = None,
        current_stage: Optional[str] = None,
        progress_percent: Optional[float] = None,
    ) -> Dict[str, Any]:
        current = self.get_case_status_info(case_id) or {"created_at": _utc_now_iso()}
        if not current.get("expires_at"):
            expires_at = datetime.now(timezone.utc).timestamp() + settings.CASE_RETENTION_SECONDS
            current["expires_at"] = datetime.fromtimestamp(expires_at, timezone.utc).isoformat()
        current["status"] = status
        current["updated_at"] = _utc_now_iso()
        if message is not None:
            current["message"] = message
        if current_stage is not None:
            current["current_stage"] = current_stage
        if progress_percent is not None:
            current["progress_percent"] = progress_percent

        mapping = {
            "status": current["status"],
            "created_at": current["created_at"],
            "updated_at": current["updated_at"],
            "expires_at": current.get("expires_at") or "",
            "message": current.get("message", "") or "",
            "current_stage": current.get("current_stage", "") or "",
            "progress_percent": str(current.get("progress_percent", 0.0)),
        }
        self.client.hset(self._status_key(case_id), mapping=mapping)
        return current

    def get_case_status(self, case_id: str) -> Optional[str]:
        value = self.client.hget(self._status_key(case_id), "status")
        return value or None

    def get_case_status_info(self, case_id: str) -> Optional[Dict[str, Any]]:
        payload = self.client.hgetall(self._status_key(case_id))
        if not payload:
            return None
        progress = payload.get("progress_percent", "0.0")
        return {
            "status": payload.get("status"),
            "message": payload.get("message") or None,
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
            "expires_at": payload.get("expires_at") or None,
            "current_stage": payload.get("current_stage") or None,
            "progress_percent": float(progress) if progress else 0.0,
        }

    def list_case_statuses(self) -> Dict[str, Dict[str, Any]]:
        pattern = self._key("case:*:status")
        statuses: Dict[str, Dict[str, Any]] = {}
        for key in self.client.scan_iter(match=pattern):
            case_id = key.split(":")[-2]
            payload = self.get_case_status_info(case_id)
            if payload:
                statuses[case_id] = payload
        return statuses

    def update_pipeline_stage(
        self,
        case_id: str,
        stage_name: str,
        status: str,
        duration_seconds: Optional[float] = None,
        message: Optional[str] = None,
        output_shape: Optional[tuple] = None,
    ) -> Dict[str, Any]:
        pipeline = self.get_pipeline_state(case_id)
        if not pipeline:
            self.initialize_case(case_id)
            pipeline = self.get_pipeline_state(case_id)

        if pipeline.get("started_at") in (None, "") and status == "running":
            pipeline["started_at"] = _utc_now_iso()
        if status in {"failed", "completed"}:
            pipeline["finished_at"] = _utc_now_iso()
        if status == "failed":
            pipeline["error"] = message

        stage_payload: Dict[str, Any] = {"status": status}
        if duration_seconds is not None:
            stage_payload["duration_seconds"] = duration_seconds
        if message:
            stage_payload["message"] = message
        if output_shape is not None:
            stage_payload["output_shape"] = list(output_shape)

        pipeline[stage_name] = stage_payload
        mapping = {
            "load_volume": json.dumps(pipeline.get("load_volume", {"status": "pending"})),
            "segmentation": json.dumps(pipeline.get("segmentation", {"status": "pending"})),
            "sdf": json.dumps(pipeline.get("sdf", {"status": "pending"})),
            "mesh": json.dumps(pipeline.get("mesh", {"status": "pending"})),
            "started_at": pipeline.get("started_at") or "",
            "finished_at": pipeline.get("finished_at") or "",
            "error": pipeline.get("error") or "",
        }
        self.client.hset(self._pipeline_key(case_id), mapping=mapping)
        return pipeline

    def get_pipeline_state(self, case_id: str) -> Dict[str, Any]:
        payload = self.client.hgetall(self._pipeline_key(case_id))
        if not payload:
            return {}

        def decode_stage(name: str) -> Dict[str, Any]:
            value = payload.get(name)
            return json.loads(value) if value else {"status": "pending"}

        return {
            "load_volume": decode_stage("load_volume"),
            "segmentation": decode_stage("segmentation"),
            "sdf": decode_stage("sdf"),
            "mesh": decode_stage("mesh"),
            "started_at": payload.get("started_at") or None,
            "finished_at": payload.get("finished_at") or None,
            "error": payload.get("error") or None,
        }

    def initialize_artifacts(self, case_id: str, artifacts: Dict[str, bool]) -> None:
        mapping = {name: json.dumps(bool(available)) for name, available in artifacts.items()}
        if mapping:
            self.client.hset(self._artifacts_key(case_id), mapping=mapping)

    def set_artifact(
        self,
        case_id: str,
        artifact_name: str,
        available: bool,
        object_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        mapping = {artifact_name: json.dumps(bool(available))}
        if object_key:
            mapping[f"{artifact_name}_key"] = object_key
        self.client.hset(self._artifacts_key(case_id), mapping=mapping)
        return self.get_artifacts(case_id) or {}

    def get_artifacts(self, case_id: str) -> Optional[Dict[str, Any]]:
        payload = self.client.hgetall(self._artifacts_key(case_id))
        if not payload:
            return None

        result: Dict[str, Any] = {}
        for key, value in payload.items():
            if key.endswith("_key"):
                result[key] = value
            else:
                result[key] = json.loads(value)
        return result

    def create_batch_session(self, case_id: str, payload: Dict[str, Any], ttl_seconds: int) -> Dict[str, Any]:
        key = self._batch_key(case_id)
        self.client.set(key, json.dumps(payload), ex=ttl_seconds)
        return payload

    def get_batch_session(self, case_id: str) -> Optional[Dict[str, Any]]:
        payload = self.client.get(self._batch_key(case_id))
        return json.loads(payload) if payload else None

    def update_batch_session(
        self,
        case_id: str,
        updates: Dict[str, Any],
        ttl_seconds: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        current = self.get_batch_session(case_id)
        if current is None:
            return None
        current.update(updates)
        key = self._batch_key(case_id)
        if ttl_seconds is None:
            ttl_seconds = self.client.ttl(key)
            if ttl_seconds is None or ttl_seconds < 0:
                ttl_seconds = 3600
        self.client.set(key, json.dumps(current), ex=ttl_seconds)
        return current

    def delete_batch_session(self, case_id: str) -> None:
        self.client.delete(self._batch_key(case_id))

    def acquire_processing_lock(self, case_id: str, ttl_seconds: int) -> bool:
        return bool(self.client.set(self._lock_key(case_id), "1", nx=True, ex=ttl_seconds))

    def release_processing_lock(self, case_id: str) -> None:
        self.client.delete(self._lock_key(case_id))
