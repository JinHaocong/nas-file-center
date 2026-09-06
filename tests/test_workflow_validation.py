import pytest
from app.filters.schema import LeafNode, LogicalNode
from app.workflows.errors import WorkflowValidationError
from app.workflows.revisions import canonical_json_dumps, compute_definition_sha256
from app.workflows.schema import (
    FilterStep,
    MoveStep,
    OrganizeStep,
    QuarantineStep,
    RenameStep,
    ScanStep,
    TouchStep,
    WorkflowDefinition,
)
from app.workflows.validation import validate_raw_steps_types, validate_workflow_definition


def test_canonical_json_and_sha256():
    d1 = {"b": 2, "a": 1, "nested": {"z": 10, "y": 20}}
    d2 = {"a": 1, "nested": {"y": 20, "z": 10}, "b": 2}
    assert canonical_json_dumps(d1) == canonical_json_dumps(d2)
    assert compute_definition_sha256(d1) == compute_definition_sha256(d2)
    assert '{"a":1,"b":2,"nested":{"y":20,"z":10}}' == canonical_json_dumps(d1)


def test_unsupported_step_types():
    with pytest.raises(WorkflowValidationError) as exc:
        validate_raw_steps_types([{"id": "s1", "type": "scan"}, {"id": "s2", "type": "dedupe"}])
    assert exc.value.code == "UNSUPPORTED_STEP"

    with pytest.raises(WorkflowValidationError) as exc:
        validate_raw_steps_types([{"id": "s1", "type": "copy"}])
    assert exc.value.code == "UNSUPPORTED_STEP"

    with pytest.raises(WorkflowValidationError) as exc:
        validate_raw_steps_types([{"id": "s1", "type": "unknown_step"}])
    assert exc.value.code == "UNSUPPORTED_STEP"


def test_valid_file_workflow():
    wf = WorkflowDefinition(
        schema_version=1,
        mode="file",
        steps=[
            ScanStep(id="step_scan", type="scan", root_ids=[1]),
            FilterStep(id="step_filter", type="filter", filter=LeafNode(field="extension", operator="eq", value=".jpg")),
            RenameStep(id="step_rename", type="rename", pattern="old", replacement="new"),
            TouchStep(id="step_touch", type="touch", touch_now=True),
            QuarantineStep(id="step_quarantine", type="quarantine", reason="cleanup"),
        ],
    )
    validate_workflow_definition(wf)


def test_file_workflow_empty_steps():
    with pytest.raises(WorkflowValidationError) as exc:
        WorkflowDefinition(schema_version=1, mode="file", steps=[])
    # Also if empty list bypassed:
    with pytest.raises(WorkflowValidationError) as exc:
        validate_workflow_definition(WorkflowDefinition.model_construct(schema_version=1, mode="file", steps=[]))
    assert exc.value.code == "EMPTY_STEPS"


def test_file_workflow_duplicate_step_id():
    wf = WorkflowDefinition(
        schema_version=1,
        mode="file",
        steps=[
            ScanStep(id="dup_id", type="scan"),
            RenameStep(id="dup_id", type="rename", pattern="a", replacement="b"),
        ],
    )
    with pytest.raises(WorkflowValidationError) as exc:
        validate_workflow_definition(wf)
    assert exc.value.code == "DUPLICATE_STEP_ID"


def test_file_workflow_step_0_must_be_scan():
    wf = WorkflowDefinition(
        schema_version=1,
        mode="file",
        steps=[
            RenameStep(id="s1", type="rename", pattern="a", replacement="b"),
        ],
    )
    with pytest.raises(WorkflowValidationError) as exc:
        validate_workflow_definition(wf)
    assert exc.value.code == "INVALID_PIPELINE_STRUCTURE"


def test_file_workflow_filter_after_action():
    wf = WorkflowDefinition(
        schema_version=1,
        mode="file",
        steps=[
            ScanStep(id="s1", type="scan"),
            RenameStep(id="s2", type="rename", pattern="a", replacement="b"),
            FilterStep(id="s3", type="filter", filter=LeafNode(field="size", operator="gt", value=100)),
        ],
    )
    with pytest.raises(WorkflowValidationError) as exc:
        validate_workflow_definition(wf)
    assert exc.value.code == "INVALID_PIPELINE_STRUCTURE"


def test_file_workflow_organize_forbidden():
    wf = WorkflowDefinition(
        schema_version=1,
        mode="file",
        steps=[
            ScanStep(id="s1", type="scan"),
            OrganizeStep(id="s2", type="organize", profile_snapshot={"name": "test"}),
        ],
    )
    with pytest.raises(WorkflowValidationError) as exc:
        validate_workflow_definition(wf)
    assert exc.value.code == "INVALID_PIPELINE_STRUCTURE"


def test_file_workflow_quarantine_must_be_terminal():
    wf = WorkflowDefinition(
        schema_version=1,
        mode="file",
        steps=[
            ScanStep(id="s1", type="scan"),
            QuarantineStep(id="s2", type="quarantine", reason="bad"),
            RenameStep(id="s3", type="rename", pattern="a", replacement="b"),
        ],
    )
    with pytest.raises(WorkflowValidationError) as exc:
        validate_workflow_definition(wf)
    assert exc.value.code == "INVALID_PIPELINE_STRUCTURE"


def test_rename_step_validation():
    wf = WorkflowDefinition(
        schema_version=1,
        mode="file",
        steps=[
            ScanStep(id="s1", type="scan"),
            RenameStep(id="s2", type="rename", pattern="dir/name", replacement="b"),
        ],
    )
    with pytest.raises(WorkflowValidationError) as exc:
        validate_workflow_definition(wf)
    assert exc.value.code == "INVALID_RENAME_PATTERN"

    with pytest.raises(Exception) as exc:
        RenameStep.model_validate({"id": "s2", "type": "rename", "pattern": "a", "replacement": "b", "is_regex": True})


def test_valid_organizer_workflow():
    wf = WorkflowDefinition(
        schema_version=1,
        mode="organizer",
        steps=[
            ScanStep(id="s1", type="scan"),
            OrganizeStep(id="s2", type="organize", profile_snapshot={"name": "Photo Organize"}),
        ],
    )
    validate_workflow_definition(wf)


def test_organizer_workflow_invalid_structure():
    # 3 steps not allowed
    wf = WorkflowDefinition(
        schema_version=1,
        mode="organizer",
        steps=[
            ScanStep(id="s1", type="scan"),
            FilterStep(id="s2", type="filter", filter=LeafNode(field="extension", operator="eq", value=".jpg")),
            OrganizeStep(id="s3", type="organize", profile_snapshot={"name": "Photo Organize"}),
        ],
    )
    with pytest.raises(WorkflowValidationError) as exc:
        validate_workflow_definition(wf)
    assert exc.value.code == "INVALID_PIPELINE_STRUCTURE"
