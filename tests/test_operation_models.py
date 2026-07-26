from pathlib import Path

import pytest


def test_operation_lifecycle_rejects_stage_regression_and_terminal_resurrection(
    tmp_path: Path,
) -> None:
    from app.operation_models import (
        InvalidOperationTransition,
        OperationKind,
        OperationRecord,
        OperationStage,
        OperationStatus,
        transition_operation,
    )

    operation = OperationRecord.new(
        operation_id="operation-1",
        kind=OperationKind.FILE,
        source_asset_path=tmp_path / "source.wav",
        route={"transcription": {"provider": "mindtype_cloud", "model": "auto"}},
    )
    running = transition_operation(
        operation,
        status=OperationStatus.RUNNING,
        stage=OperationStage.UPLOAD,
    )

    with pytest.raises(InvalidOperationTransition):
        transition_operation(
            running,
            status=OperationStatus.RUNNING,
            stage=OperationStage.PERSIST,
        )

    cancelled = transition_operation(
        transition_operation(
            running,
            status=OperationStatus.CANCEL_REQUESTED,
        ),
        status=OperationStatus.CANCELLED,
    )
    with pytest.raises(InvalidOperationTransition):
        transition_operation(
            cancelled,
            status=OperationStatus.COMPLETED,
            stage=OperationStage.INSERT,
        )
