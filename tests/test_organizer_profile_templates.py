from __future__ import annotations

import pytest

from app.organizers.templates import (
    ALLOWED_RENAME_VARS,
    ALLOWED_STATISTICS_VARS,
    extract_template_vars,
    render_template,
    sanitize_extensions,
    validate_cleanup_patterns,
    validate_template,
)


def test_extract_template_vars():
    template = "{name} {index} [{images}P{?videos: {videos}V} {size}]"
    vars_found = extract_template_vars(template)
    assert vars_found == {"name", "index", "images", "videos", "size"}


def test_validate_template_valid_and_invalid():
    # Valid rename template
    valid_rename = "{index} {name} {statistics}"
    assert validate_template(valid_rename, ALLOWED_RENAME_VARS) == []

    # Valid statistics template with conditional
    valid_stat = "[{images}P{?videos: {videos}V} {size}]"
    assert validate_template(valid_stat, ALLOWED_STATISTICS_VARS) == []

    # Unknown variable in template
    invalid_stat = "[{images}P {evil_var} {size}]"
    errors = validate_template(invalid_stat, ALLOWED_STATISTICS_VARS)
    assert len(errors) == 1
    assert "evil_var" in errors[0]

    # Unmatched braces
    broken = "{name} {size"
    errs = validate_template(broken, ALLOWED_RENAME_VARS)
    assert any("括号不匹配" in e for e in errs)

    # Empty template
    empty_errs = validate_template("", ALLOWED_RENAME_VARS)
    assert any("不能为空" in e for e in empty_errs)


def test_render_template_basic_and_conditional():
    ctx = {
        "name": "桜木",
        "index": "001",
        "images": 12,
        "videos": 2,
        "size": "1.5GB",
        "files": 14,
        "folders": 0,
    }
    # When videos > 0
    t = "[{images}P{?videos: {videos}V} {size}]"
    assert render_template(t, ctx) == "[12P 2V 1.5GB]"

    # When videos == 0
    ctx_no_video = dict(ctx, videos=0)
    assert render_template(t, ctx_no_video) == "[12P 1.5GB]"

    # When template does NOT use conditional and explicitly writes {videos}V
    t_fixed = "[{images}P {videos}V {size}]"
    assert render_template(t_fixed, ctx_no_video) == "[12P 0V 1.5GB]"


def test_validate_cleanup_patterns():
    # Valid regex patterns
    valid_patterns = [r"\s+\[\d+P\]$", r"\[old\]"]
    assert validate_cleanup_patterns(valid_patterns) == []

    # Invalid regex
    invalid_patterns = [r"(\d+"]
    errors = validate_cleanup_patterns(invalid_patterns)
    assert len(errors) == 1
    assert "正则表达式无效" in errors[0]

    # Overly long pattern
    long_patterns = ["a" * 201]
    errors_long = validate_cleanup_patterns(long_patterns)
    assert any("过长" in e for e in errors_long)

    # Too many patterns
    too_many = ["pat"] * 11
    errors_many = validate_cleanup_patterns(too_many)
    assert any("数量不得超过 10 条" in e for e in errors_many)


def test_sanitize_extensions():
    import pytest
    valid = [".JPG", "jpeg", " PNG ", "webp", "", ".gif"]
    clean = sanitize_extensions(valid)
    assert clean == ["jpg", "jpeg", "png", "webp", "gif"]

    # Invalid extensions must be rejected (Blocker 5)
    for bad in ["mp4/bad", "mkv\\bad", "a b"]:
        with pytest.raises(ValueError):
            sanitize_extensions([bad])
