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


def test_main_schedules_acknowledgement_without_running_it_on_gui_thread(
    monkeypatch,
):
    from app.main import MainWindow

    created = []

    class Signal:
        def connect(self, callback):
            self.callback = callback

    class FakeWorker:
        def __init__(self, operation_id, acknowledge):
            self.operation_id = operation_id
            self.acknowledge = acknowledge
            self.failed = Signal()
            self.finished = Signal()
            self.started = False
            created.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(
        "app.main.OperationAcknowledgementWorker",
        FakeWorker,
    )
    window = SimpleNamespace(
        _operation_coordinator=MagicMock(),
        _acknowledgement_workers=set(),
        _init_mindtype_cloud=MagicMock(),
        _cloud_executor=MagicMock(),
        _add_journal_entry=MagicMock(),
    )
    window._operation_coordinator.store.get.return_value = (
        SimpleNamespace(server_job_ids={"transcription": "job-1"})
    )

    MainWindow._acknowledge_completed_operation(window, "operation-4")

    assert len(created) == 1
    assert created[0].started is True
    assert created[0] in window._acknowledgement_workers
    window._init_mindtype_cloud.assert_called_once_with()

    created[0].acknowledge()

    window._init_mindtype_cloud.assert_called_once_with()
