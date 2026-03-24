"""
Runtime helpers that isolate Modal-specific behavior away from routers.
"""

from __future__ import annotations

from config import settings


def is_running_in_modal() -> bool:
    """Check if execution is currently inside a Modal container."""
    try:
        import modal

        return modal.is_local() is False
    except ImportError:
        return False


def has_distributed_runtime() -> bool:
    """Whether Redis state + object storage are both available."""
    return settings.should_use_distributed_runtime()


def _should_sync_scope(scope: str) -> bool:
    """Decide whether a given shared-volume sync scope is still required."""
    if scope == "state":
        return not settings.should_use_redis_state()
    if scope == "artifact":
        return not settings.should_use_r2_object_store()
    if scope == "all":
        return _should_sync_scope("state") or _should_sync_scope("artifact")
    if scope == "upload_handoff":
        return not has_distributed_runtime()
    return True


def reload_data_volume(scope: str = "artifact") -> None:
    """Refresh Modal shared volume reads if still required for the given scope."""
    if not is_running_in_modal():
        return
    if not _should_sync_scope(scope):
        return

    try:
        from modal_app import data_volume

        data_volume.reload()
    except ImportError:
        pass


def commit_data_volume(scope: str = "artifact") -> None:
    """Commit Modal shared volume writes if still required for the given scope."""
    if not is_running_in_modal():
        return
    if not _should_sync_scope(scope):
        return

    try:
        from modal_app import data_volume

        data_volume.commit()
    except ImportError:
        pass


def spawn_process_case(case_id: str) -> bool:
    """Dispatch case processing to a Modal worker when available."""
    if not is_running_in_modal():
        return False

    from modal_app import process_case_modal

    process_case_modal.spawn(case_id)
    return True


def spawn_single_upload(case_id: str, source_ref: str, filename: str, source_kind: str = "local") -> bool:
    """Dispatch single-file upload processing to Modal when available."""
    if not is_running_in_modal():
        return False

    from modal_app import process_upload_modal

    process_upload_modal.spawn(case_id, source_ref, filename, source_kind)
    return True


def spawn_dicom_directory(
    case_id: str,
    source_ref: str | list[str],
    extra_metadata: dict | None,
    source_kind: str = "local_dir",
) -> bool:
    """Dispatch DICOM directory/object processing to Modal when available."""
    if not is_running_in_modal():
        return False

    if source_kind == "object_store_keys":
        from modal_app import process_dicom_objects_modal

        process_dicom_objects_modal.spawn(case_id, source_ref, extra_metadata)
        return True

    from modal_app import process_dicom_dir_modal

    process_dicom_dir_modal.spawn(case_id, source_ref, extra_metadata)
    return True
