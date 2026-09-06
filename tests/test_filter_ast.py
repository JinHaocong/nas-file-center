import pytest
from app.filters.schema import FilterExpression, LeafNode, LogicalNode
from app.filters.validation import validate_filter_ast, FilterValidationError
from app.filters.media_types import get_media_type, get_extensions_for_media_type

def test_valid_leaf_node():
    leaf = LeafNode(field="extension", operator="in", value=["JPG", ".png"])
    validated = validate_filter_ast(leaf)
    assert validated.field == "extension"
    assert validated.value == ["jpg", "png"]

def test_valid_logical_and_tree():
    tree = LogicalNode(
        op="and",
        children=[
            LeafNode(field="extension", operator="eq", value="mkv"),
            LeafNode(field="size", operator="gte", value=1024),
            LogicalNode(
                op="not",
                child=LeafNode(field="name", operator="contains", value="sample")
            )
        ]
    )
    validated = validate_filter_ast(tree)
    assert validated.op == "and"
    assert len(validated.children) == 3

def test_depth_limit_enforced():
    # Depth 5 should be accepted
    # 1: and -> 2: and -> 3: and -> 4: and -> 5: leaf
    curr = LeafNode(field="size", operator="gt", value=0)
    for _ in range(4):
        curr = LogicalNode(op="and", children=[curr])
    assert validate_filter_ast(curr) is not None

    # Depth 6 should be rejected
    curr = LogicalNode(op="and", children=[curr])
    with pytest.raises(FilterValidationError, match="exceeds maximum allowed depth of 5"):
        validate_filter_ast(curr)

def test_children_limit_enforced():
    children_50 = [LeafNode(field="size", operator="gt", value=i) for i in range(50)]
    node_50 = LogicalNode(op="or", children=children_50)
    assert validate_filter_ast(node_50) is not None

    children_51 = [LeafNode(field="size", operator="gt", value=i) for i in range(51)]
    node_51 = LogicalNode(op="or", children=children_51)
    with pytest.raises(FilterValidationError, match="exceeds maximum allowed children count of 50"):
        validate_filter_ast(node_51)

def test_empty_logical_nodes_rejected():
    with pytest.raises(FilterValidationError, match="Logical node 'and' must have at least one child"):
        validate_filter_ast(LogicalNode(op="and", children=[]))

    with pytest.raises(FilterValidationError, match="Logical node 'or' must have at least one child"):
        validate_filter_ast(LogicalNode(op="or", children=[]))

    with pytest.raises(FilterValidationError, match="Logical node 'not'"):
        validate_filter_ast(LogicalNode(op="not", children=[]))

def test_regex_and_matches_rejected():
    with pytest.raises(FilterValidationError, match="regex filtering is not supported in Gate5-A"):
        validate_filter_ast(LeafNode(field="regex", operator="matches", value=".*"))

    with pytest.raises(FilterValidationError, match="regex filtering is not supported in Gate5-A"):
        validate_filter_ast(LeafNode(field="name", operator="matches", value=".*"))

def test_unknown_field_or_operator_rejected():
    with pytest.raises(FilterValidationError, match="Unsupported field 'owner'"):
        validate_filter_ast(LeafNode(field="owner", operator="eq", value="root"))

    with pytest.raises(FilterValidationError, match="Unsupported operator 'like' for field 'name'"):
        validate_filter_ast(LeafNode(field="name", operator="like", value="foo"))

def test_size_validation():
    # Negative size rejected
    with pytest.raises(FilterValidationError, match="Size value must be an integer >= 0"):
        validate_filter_ast(LeafNode(field="size", operator="gte", value=-10))

    # Float size rejected
    with pytest.raises(FilterValidationError, match="Size value must be an integer >= 0"):
        validate_filter_ast(LeafNode(field="size", operator="gte", value=10.5))

    # Boolean size rejected
    with pytest.raises(FilterValidationError, match="Size value must be an integer >= 0"):
        validate_filter_ast(LeafNode(field="size", operator="gte", value=True))

def test_mtime_validation():
    # ISO-8601 string converted to mtime_ns integer
    iso_val = "2026-08-15T12:00:00Z"
    leaf = validate_filter_ast(LeafNode(field="mtime", operator="gte", value=iso_val))
    assert isinstance(leaf.value, int)
    assert leaf.value == 1786795200000000000

    # Unix epoch seconds int converted to mtime_ns
    leaf2 = validate_filter_ast(LeafNode(field="mtime", operator="gte", value=1786795200))
    assert leaf2.value == 1786795200000000000

    # Invalid timestamp string rejected
    with pytest.raises(FilterValidationError, match="Invalid mtime format"):
        validate_filter_ast(LeafNode(field="mtime", operator="gte", value="not-a-timestamp"))

def test_media_type_validation_and_mapping():
    assert get_media_type("mkv") == "video"
    assert get_media_type(".JPG") == "image"
    assert get_media_type("mp3") == "audio"
    assert get_media_type("pdf") == "document"
    assert get_media_type("zip") == "archive"
    assert get_media_type("xyz123") == "other"

    # Valid media_type filter
    leaf = validate_filter_ast(LeafNode(field="media_type", operator="eq", value="VIDEO"))
    assert leaf.value == "video"

    # Invalid media_type value rejected
    with pytest.raises(FilterValidationError, match="Invalid media_type 'unknown_type'"):
        validate_filter_ast(LeafNode(field="media_type", operator="eq", value="unknown_type"))

def test_ast_fail_closed_extra_fields():
    from pydantic import ValidationError
    from app.filters.schema import FilterPreviewRequest

    # Top-level typo in FilterPreviewRequest must raise ValidationError
    with pytest.raises(ValidationError):
        FilterPreviewRequest.model_validate({
            "roots": ["/data/media"],
            "filtter": {
                "field": "name",
                "operator": "eq",
                "value": "a.txt"
            }
        })

    # Leaf extra attribute must raise ValidationError
    with pytest.raises(ValidationError):
        LeafNode.model_validate({
            "field": "name",
            "operator": "eq",
            "value": "a.txt",
            "typo_extra": True
        })


def test_logical_node_strict_one_shape():
    # and / or with 'child' must be rejected
    with pytest.raises(FilterValidationError, match="Logical node 'and' only allows 'children'"):
        validate_filter_ast(LogicalNode(
            op="and",
            children=[LeafNode(field="name", operator="eq", value="a.txt")],
            child=LeafNode(field="name", operator="eq", value="b.txt")
        ))

    with pytest.raises(FilterValidationError, match="Logical node 'or' only allows 'children'"):
        validate_filter_ast(LogicalNode(
            op="or",
            children=[LeafNode(field="name", operator="eq", value="a.txt")],
            child=LeafNode(field="name", operator="eq", value="b.txt")
        ))

    # not with 'children' must be rejected
    with pytest.raises(FilterValidationError, match="Logical node 'not' only allows 'child'"):
        validate_filter_ast(LogicalNode(
            op="not",
            children=[LeafNode(field="name", operator="eq", value="a.txt")]
        ))

    # not with both child and children must be rejected
    with pytest.raises(FilterValidationError, match="Logical node 'not' only allows 'child'"):
        validate_filter_ast(LogicalNode(
            op="not",
            child=LeafNode(field="name", operator="eq", value="a.txt"),
            children=[LeafNode(field="name", operator="eq", value="b.txt")]
        ))


def test_mtime_strict_typing_and_timezone():
    # float mtime must be rejected
    with pytest.raises(FilterValidationError, match="float"):
        validate_filter_ast(LeafNode(field="mtime", operator="eq", value=1.5))

    with pytest.raises(FilterValidationError, match="float"):
        validate_filter_ast(LeafNode(field="mtime", operator="eq", value=1786795200.123))

    # boolean mtime must be rejected
    with pytest.raises(FilterValidationError, match="boolean"):
        validate_filter_ast(LeafNode(field="mtime", operator="eq", value=True))

    with pytest.raises(FilterValidationError, match="boolean"):
        validate_filter_ast(LeafNode(field="mtime", operator="eq", value=False))

    # timezone-naive ISO string must be rejected
    with pytest.raises(FilterValidationError, match="timezone"):
        validate_filter_ast(LeafNode(field="mtime", operator="eq", value="2026-09-06T10:00:00"))

    # timezone-aware UTC ISO string must be accepted
    leaf_utc = validate_filter_ast(LeafNode(field="mtime", operator="eq", value="2026-09-06T10:00:00Z"))
    assert leaf_utc.value == 1788688800000000000

    # timezone-aware offset ISO string must be accepted
    leaf_offset = validate_filter_ast(LeafNode(field="mtime", operator="eq", value="2026-09-06T18:00:00+08:00"))
    assert leaf_offset.value == 1788688800000000000

    # integer epoch seconds must be accepted
    leaf_int = validate_filter_ast(LeafNode(field="mtime", operator="eq", value=1788688800))
    assert leaf_int.value == 1788688800000000000

    # INT64_MAX boundary tests (P2-04)
    # MAX_EPOCH_SECONDS = 9223372036 (INT64_MAX // 1e9)
    leaf_max_int = validate_filter_ast(LeafNode(field="mtime", operator="eq", value=9223372036))
    assert leaf_max_int.value == 9223372036000000000

    # 9223372037 exceeds SQLite INT64_MAX when converted to ns -> must be rejected (422)
    with pytest.raises(FilterValidationError, match="range"):
        validate_filter_ast(LeafNode(field="mtime", operator="eq", value=9223372037))

    # negative int must be rejected
    with pytest.raises(FilterValidationError, match="range"):
        validate_filter_ast(LeafNode(field="mtime", operator="eq", value=-1))

    # ISO boundary: 2262-04-11T23:47:16Z is 9223372036s -> accepted
    leaf_max_iso = validate_filter_ast(LeafNode(field="mtime", operator="eq", value="2262-04-11T23:47:16Z"))
    assert leaf_max_iso.value == 9223372036000000000

    # ISO boundary: 2262-04-11T23:47:16.854775Z -> 9223372036854775000 ns <= INT64_MAX -> accepted
    leaf_max_iso_us = validate_filter_ast(LeafNode(field="mtime", operator="eq", value="2262-04-11T23:47:16.854775Z"))
    assert leaf_max_iso_us.value == 9223372036854775000

    # ISO boundary: 2262-04-11T23:47:16.854776Z -> 9223372036854776000 ns > INT64_MAX -> rejected (422)
    with pytest.raises(FilterValidationError, match="range"):
        validate_filter_ast(LeafNode(field="mtime", operator="eq", value="2262-04-11T23:47:16.854776Z"))

    # ISO boundary: 2262-04-12T00:00:00Z -> rejected (422)
    with pytest.raises(FilterValidationError, match="range"):
        validate_filter_ast(LeafNode(field="mtime", operator="eq", value="2262-04-12T00:00:00Z"))

    # Year 9999 ISO string must be rejected (422)
    with pytest.raises(FilterValidationError, match="range"):
        validate_filter_ast(LeafNode(field="mtime", operator="eq", value="9999-12-31T23:59:59Z"))

    # Pre-epoch ISO string (negative ns) must be rejected
    with pytest.raises(FilterValidationError, match="range"):
        validate_filter_ast(LeafNode(field="mtime", operator="eq", value="1969-12-31T23:59:59Z"))

    # integer nanoseconds or out-of-range must be rejected
    with pytest.raises(FilterValidationError, match="range"):
        validate_filter_ast(LeafNode(field="mtime", operator="eq", value=1788688800000000000))



def test_string_fields_strict_types():
    # in/nin non-string rejected
    for bad_val in [[123], [True], ["jpg", 1], "a,b,c", []]:
        with pytest.raises(FilterValidationError):
            validate_filter_ast(LeafNode(field="name", operator="in", value=bad_val))
        with pytest.raises(FilterValidationError):
            validate_filter_ast(LeafNode(field="path", operator="in", value=bad_val))
        with pytest.raises(FilterValidationError):
            validate_filter_ast(LeafNode(field="extension", operator="in", value=bad_val))
        with pytest.raises(FilterValidationError):
            validate_filter_ast(LeafNode(field="media_type", operator="in", value=bad_val))

    # single string operations non-string rejected
    for bad_scalar in [123, True, 1.5, None, ["a"]]:
        with pytest.raises(FilterValidationError):
            validate_filter_ast(LeafNode(field="name", operator="eq", value=bad_scalar))
        with pytest.raises(FilterValidationError):
            validate_filter_ast(LeafNode(field="path", operator="contains", value=bad_scalar))
        with pytest.raises(FilterValidationError):
            validate_filter_ast(LeafNode(field="extension", operator="eq", value=bad_scalar))
        with pytest.raises(FilterValidationError):
            validate_filter_ast(LeafNode(field="media_type", operator="eq", value=bad_scalar))
