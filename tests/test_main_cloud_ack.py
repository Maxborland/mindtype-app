from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock


def _context_for(operation):
    coordinator = MagicMock()
    coordinator.store.get.return_value = operation
    executor = MagicMock()
    factory = MagicMock(return_value=executor)
    return coordinator, executor, factory


def test_completed_cloud_transcription_acks_server_before_local_cleanup():
    from app.operation_ack import acknowledge_completed_operation

    coordinator, executor, factory = _context_for(
        SimpleNamespace(
            server_job_ids={"transcription": "server-job-1"},
        )
    )

    acknowledge_completed_operation(
        coordinator,
        "operation-1",
        cloud_executor_factory=factory,
    )

    factory.assert_called_once_with()
    executor.acknowledge_completed.assert_called_once_with("operation-1")
    coordinator.acknowledge_result.assert_not_called()


def test_completed_cloud_summary_only_operation_is_also_acked():
    from app.operation_ack import acknowledge_completed_operation

    coordinator, executor, factory = _context_for(
        SimpleNamespace(
            server_job_ids={"summary": "summary-job-1"},
        )
    )

    acknowledge_completed_operation(
        coordinator,
        "operation-2",
        cloud_executor_factory=factory,
    )

    executor.acknowledge_completed.assert_called_once_with("operation-2")


def test_completed_local_operation_cleans_up_without_cloud_session():
    from app.operation_ack import acknowledge_completed_operation

    coordinator, executor, factory = _context_for(
        SimpleNamespace(server_job_ids={})
    )

    acknowledge_completed_operation(
        coordinator,
        "operation-3",
        cloud_executor_factory=factory,
    )

    factory.assert_not_called()
    executor.acknowledge_completed.assert_not_called()
    coordinator.acknowledge_result.assert_called_once_with("operation-3")
