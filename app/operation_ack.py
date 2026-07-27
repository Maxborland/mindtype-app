"""One acknowledgement boundary for local and MindType Cloud results."""

from __future__ import annotations

from typing import Any, Callable


def acknowledge_completed_operation(
    coordinator: Any,
    operation_id: str,
    *,
    cloud_executor_factory: Callable[[], Any],
) -> None:
    operation = coordinator.store.get(operation_id)
    if operation is None:
        raise KeyError(operation_id)
    if operation.server_job_ids:
        executor = cloud_executor_factory()
        if executor is None:
            raise RuntimeError("MindType Cloud ACK is unavailable")
        executor.acknowledge_completed(operation_id)
        return
    coordinator.acknowledge_result(operation_id)


__all__ = ["acknowledge_completed_operation"]
