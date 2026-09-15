import pytest
from pydantic import ValidationError

from app.workflows.errors import WorkflowValidationError
from app.workflows.schema import (
    RenameStep,
    SingleChildWrapperCollapseStep,
    WorkflowDefinition,
)
from app.workflows.validation import validate_workflow_definition


def _utility(*, root_id: int = 1, subpath: str = "") -> WorkflowDefinition:
    return WorkflowDefinition(
        schema_version=1,
        mode="utility",
        steps=[
            SingleChildWrapperCollapseStep(
                id="collapse",
                type="single_child_wrapper_collapse",
                root_id=root_id,
                subpath=subpath,
            )
        ],
    )


def test_utility_mode_accepts_only_frozen_single_child_wrapper_shape():
    workflow = _utility(root_id=7, subpath="photos/set A")
    validate_workflow_definition(workflow)

    assert workflow.mode == "utility"
    step = workflow.steps[0]
    assert isinstance(step, SingleChildWrapperCollapseStep)
    assert step.root_id == 7
    assert step.subpath == "photos/set A"


def test_utility_mode_rejects_existing_file_stream_action_steps():
    workflow = WorkflowDefinition.model_construct(
        schema_version=1,
        mode="utility",
        steps=[RenameStep(id="rename", type="rename", pattern="a", replacement="b")],
    )

    with pytest.raises(WorkflowValidationError) as exc:
        validate_workflow_definition(workflow)

    assert exc.value.code == "INVALID_PIPELINE_STRUCTURE"


def test_single_child_wrapper_scope_requires_positive_managed_root_id():
    with pytest.raises((ValidationError, WorkflowValidationError)):
        _utility(root_id=0)

    with pytest.raises((ValidationError, WorkflowValidationError)):
        _utility(root_id=-1)


def test_single_child_wrapper_scope_subpath_must_be_relative_and_non_escaping():
    for unsafe in ("/absolute/path", "../escape", "foo/../bar", "\\absolute"):
        workflow = _utility(subpath=unsafe)
        with pytest.raises(WorkflowValidationError) as exc:
            validate_workflow_definition(workflow)
        assert exc.value.code == "INVALID_SUBPATH"


def test_utility_schema_forbids_arbitrary_absolute_path_field():
    with pytest.raises(ValidationError):
        SingleChildWrapperCollapseStep.model_validate(
            {
                "id": "collapse",
                "type": "single_child_wrapper_collapse",
                "root_id": 1,
                "subpath": "safe",
                "path": "/tmp/zfsv3/unsafe-direct-entry",
            }
        )
