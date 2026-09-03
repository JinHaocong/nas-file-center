from __future__ import annotations

import re
from typing import Any
import regex

# Allowed variables in rename_template
ALLOWED_RENAME_VARS = {
    "name",
    "index",
    "images",
    "videos",
    "files",
    "files_count",
    "folders",
    "size",
    "statistics",
    "parent",
    "extension",
}

# Allowed variables in statistics_template
ALLOWED_STATISTICS_VARS = {
    "images",
    "videos",
    "files",
    "folders",
    "size",
    "name",
    "files_count",
}

def _find_top_level_tokens(template: str) -> list[tuple[int, int, str]]:
    """
    Find top-level tokens like {var} or {?var: ...} with proper brace depth tracking.
    Returns a list of (start_idx, end_idx, token_content) where start_idx is '{' and end_idx is '}'.
    """
    tokens = []
    i = 0
    n = len(template)
    while i < n:
        if template[i] == "{":
            start = i
            depth = 1
            i += 1
            while i < n and depth > 0:
                if template[i] == "{":
                    depth += 1
                elif template[i] == "}":
                    depth -= 1
                i += 1
            if depth == 0:
                content = template[start + 1 : i - 1]
                tokens.append((start, i, content))
            else:
                # Unmatched opening brace
                break
        else:
            i += 1
    return tokens


def extract_template_vars(template: str) -> set[str]:
    """Extract all variable names referenced in the template, including conditionals."""
    found: set[str] = set()
    for _, _, content in _find_top_level_tokens(template):
        if content.startswith("?"):
            parts = content[1:].split(":", 1)
            var_name = parts[0].strip()
            found.add(var_name)
            if len(parts) > 1:
                found.update(extract_template_vars(parts[1]))
        else:
            var_name = content.split(":", 1)[0].strip()
            found.add(var_name)
    return found


def validate_template(template: str, allowed_vars: set[str]) -> list[str]:
    """Validate that template only uses variables from allowed_vars. Returns error strings."""
    errors: list[str] = []
    if not template or not template.strip():
        errors.append("模板不能为空")
        return errors

    open_count = template.count("{")
    close_count = template.count("}")
    if open_count != close_count:
        errors.append(f"模板括号不匹配: 找到 {open_count} 个 '{{' 和 {close_count} 个 '}}'")
        return errors

    referenced_vars = extract_template_vars(template)
    for var in sorted(referenced_vars):
        if var not in allowed_vars:
            errors.append(f"未知的模板变量 '{{{var}}}'，允许的变量为: {', '.join(sorted(allowed_vars))}")
    return errors


def render_template(template: str, context: dict[str, Any]) -> str:
    """
    Render template with context variables and conditional expressions.
    Supported:
    - {var}: simple substitution with context[var]
    - {?var: inner_template}: if context[var] > 0 / truthy, render inner_template, else omit
    """
    tokens = _find_top_level_tokens(template)
    if not tokens:
        return template

    result: list[str] = []
    last_idx = 0
    for start, end, content in tokens:
        result.append(template[last_idx:start])
        last_idx = end

        if content.startswith("?"):
            parts = content[1:].split(":", 1)
            var_name = parts[0].strip()
            inner = parts[1] if len(parts) > 1 else ""
            val = context.get(var_name)

            is_active = False
            if isinstance(val, (int, float)):
                is_active = val > 0
            elif isinstance(val, str):
                is_active = bool(val.strip()) and val.strip() != "0"
            elif val is not None:
                is_active = bool(val)

            if is_active:
                result.append(render_template(inner, context))
        else:
            var_name = content.split(":", 1)[0].strip()
            val = context.get(var_name, "")
            result.append(str(val))

    result.append(template[last_idx:])
    return "".join(result)


import signal

NESTED_QUANTIFIERS_RE = re.compile(r"\([^)]*([+*]|\{\d+,?\d*\})[^)]*\)([+*]|\{\d+,?\d*\})")


def validate_cleanup_patterns(patterns: list[str]) -> list[str]:
    """Validate regex cleanup patterns for security, ReDoS and correctness."""
    errors: list[str] = []
    if len(patterns) > 10:
        errors.append("清理规则数量不得超过 10 条")
    for idx, p in enumerate(patterns):
        if not p or not p.strip():
            errors.append(f"第 {idx + 1} 条清理规则不能为空")
            continue
        if len(p) > 200:
            errors.append(f"第 {idx + 1} 条清理规则长度过长（不得超过 200 字符）")
            continue
        if NESTED_QUANTIFIERS_RE.search(p):
            errors.append(f"第 {idx + 1} 条清理规则存在嵌套量词，可能引发 ReDoS 灾难性回溯: '{p}'")
            continue
        try:
            regex.compile(p, regex.IGNORECASE)
        except (regex.error, re.error) as exc:
            errors.append(f"第 {idx + 1} 条清理规则正则表达式无效: {exc}")
    return errors


def safe_apply_cleanup_pattern(name: str, pattern: str, repl: str = "") -> str:
    """
    Safely apply regex substitution with timeout protection and case-insensitivity.
    Uses `regex` library with per-execution timeout (0.05s) to guarantee termination
    even under catastrophic backtracking in threadpool workers.
    """
    if NESTED_QUANTIFIERS_RE.search(pattern):
        raise ValueError(f"清理规则存在嵌套量词，拒绝执行: {pattern}")

    try:
        compiled = regex.compile(pattern, regex.IGNORECASE)
        return compiled.sub(repl, name, timeout=0.05)
    except (TimeoutError, regex.error) as exc:
        if isinstance(exc, TimeoutError) or "timeout" in str(exc).lower():
            raise ValueError(f"清理规则执行超时 (ReDoS 防护已触发): {pattern}") from exc
        raise ValueError(f"清理规则无效: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"清理规则执行失败: {exc}") from exc


def validate_and_normalize_extensions(extensions: list[str] | None, field_name: str = "扩展名") -> list[str]:
    """
    Normalize extensions (.JPG -> jpg).
    Rejects invalid extensions (e.g. 'jpg/bad', 'mkv\\bad', 'a b') with ValueError.
    Preserves explicit empty list [].
    """
    if extensions is None:
        return []
    cleaned: list[str] = []
    for raw in extensions:
        if not isinstance(raw, str):
            raise ValueError(f"{field_name} 必须为字符串数组，收到: {type(raw).__name__}")
        e = raw.strip()
        if not e:
            continue
        e = e.lstrip(".")
        if not e or not re.match(r"^[a-zA-Z0-9]+$", e):
            raise ValueError(f"{field_name} 包含非法扩展名 '{raw}'，扩展名只能包含英文字母和数字")
        norm = e.lower()
        if norm not in cleaned:
            cleaned.append(norm)
    return cleaned


sanitize_extensions = validate_and_normalize_extensions
