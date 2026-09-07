from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Literal


RESERVED_FACTORS = frozenset({"resolution", "bitrate", "dimensions", "fps", "codec", "audio_channels"})
ALLOWED_TOP_LEVEL_KEYS = frozenset({"schema_version", "selection_mode", "factors"})
ALLOWED_FACTOR_NAMES = frozenset({"path_priority", "preferred_extension", "mtime"})
ALLOWED_PATH_PRIORITY_KEYS = frozenset({"enabled", "weight", "rules"})
ALLOWED_PREFERRED_EXTENSION_KEYS = frozenset({"enabled", "weight", "extensions"})
ALLOWED_MTIME_KEYS = frozenset({"mode", "weight"})
ALLOWED_RULE_KEYS = frozenset({"scope", "pattern"})

MAX_RULES_COUNT = 64
MAX_EXTENSIONS_COUNT = 64
MAX_PATTERN_LENGTH = 512
MAX_EXTENSION_LENGTH = 64


def canonicalize_extension(val: str) -> str:
    """Canonicalize an extension or extract last extension from filename.

    Examples:
        '.JPG' -> 'jpg'
        'JPEG' -> 'jpeg'
        'archive.tar.gz' -> 'gz'
        '.bashrc' -> ''
    """
    if type(val) is not str:
        raise ValueError("Extension must be a string")
    s = val.strip()
    if not s:
        return ""
    # If it's a dotfile like .bashrc (starts with a dot and has no further dots)
    if s.startswith(".") and s.count(".") == 1:
        name_without_dot = s[1:]
        if name_without_dot.lower() in {"bashrc", "gitignore", "env", "profile", "zshrc"}:
            return ""
    p = Path(s)
    if p.suffix:
        return p.suffix.lstrip(".").lower()
    return s.lstrip(".").split(".")[-1].lower()


def extract_file_extension(path: str | Path) -> str:
    """Extract last extension from a file path.

    POSIX dotfiles without suffix (e.g. '.bashrc') have no extension.
    'archive.tar.gz' -> 'gz'
    'photo.JPG' -> 'jpg'
    """
    p = Path(path)
    suffix = p.suffix
    if not suffix:
        return ""
    return suffix.lstrip(".").lower()


def _validate_weight(weight: Any, factor_name: str) -> int:
    if type(weight) is not int or isinstance(weight, bool):
        raise ValueError(f"Factor '{factor_name}' weight cannot be boolean; strict integer required")
    if weight < 0 or weight > 10_000:
        raise ValueError(f"Factor '{factor_name}' weight {weight} out of range [0, 10000]")
    return weight


@dataclass(frozen=True)
class PathPriorityRule:
    scope: Literal["absolute", "relative"]
    pattern: str

    def __post_init__(self):
        if type(self.scope) is not str or self.scope not in {"absolute", "relative"}:
            raise ValueError(f"PathPriorityRule scope must be 'absolute' or 'relative', got {self.scope!r}")
        if type(self.pattern) is not str or not self.pattern.strip():
            raise ValueError("PathPriorityRule pattern must be a non-empty string")
        if len(self.pattern) > MAX_PATTERN_LENGTH:
            raise ValueError(f"PathPriorityRule pattern exceeds maximum length of {MAX_PATTERN_LENGTH}")


@dataclass(frozen=True)
class PathPriorityFactor:
    enabled: bool = False
    weight: int = 0
    rules: tuple[PathPriorityRule, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError("PathPriorityFactor enabled must be a boolean (True/False)")
        _validate_weight(self.weight, "path_priority")
        if not isinstance(self.rules, tuple):
            object.__setattr__(self, "rules", tuple(self.rules))
        if len(self.rules) > MAX_RULES_COUNT:
            raise ValueError(f"path_priority rules exceed maximum {MAX_RULES_COUNT} limit")


@dataclass(frozen=True)
class PreferredExtensionFactor:
    enabled: bool = False
    weight: int = 0
    extensions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError("PreferredExtensionFactor enabled must be a boolean (True/False)")
        _validate_weight(self.weight, "preferred_extension")
        if not isinstance(self.extensions, tuple):
            object.__setattr__(self, "extensions", tuple(self.extensions))
        if len(self.extensions) > MAX_EXTENSIONS_COUNT:
            raise ValueError(f"preferred_extension extensions exceed maximum {MAX_EXTENSIONS_COUNT} limit")


@dataclass(frozen=True)
class MtimeFactor:
    mode: Literal["none", "newest", "oldest"] = "none"
    weight: int = 0

    def __post_init__(self):
        if type(self.mode) is not str or self.mode not in {"none", "newest", "oldest"}:
            raise ValueError(f"MtimeFactor mode must be 'none', 'newest', or 'oldest', got {self.mode!r}")
        _validate_weight(self.weight, "mtime")


@dataclass(frozen=True)
class DedupeFactorsConfig:
    path_priority: PathPriorityFactor = field(default_factory=PathPriorityFactor)
    preferred_extension: PreferredExtensionFactor = field(default_factory=PreferredExtensionFactor)
    mtime: MtimeFactor = field(default_factory=MtimeFactor)


@dataclass(frozen=True)
class AdvancedDedupeConfig:
    schema_version: int = 1
    selection_mode: Literal["weighted", "balanced_by_bytes"] = "weighted"
    factors: DedupeFactorsConfig = field(default_factory=DedupeFactorsConfig)

    def __post_init__(self):
        if type(self.schema_version) is not int or isinstance(self.schema_version, bool) or self.schema_version != 1:
            raise ValueError(f"Invalid schema_version {self.schema_version}, must be integer 1")
        if type(self.selection_mode) is not str or self.selection_mode not in {"weighted", "balanced_by_bytes"}:
            raise ValueError(f"Invalid selection_mode {self.selection_mode}, must be 'weighted' or 'balanced_by_bytes'")


def validate_and_canonicalize_config(raw: Any) -> AdvancedDedupeConfig:
    if isinstance(raw, AdvancedDedupeConfig):
        return raw

    if type(raw) is not dict:
        raise ValueError("Config must be a dictionary or AdvancedDedupeConfig instance")

    # Strict check: unknown top-level keys
    for k in raw:
        if k not in ALLOWED_TOP_LEVEL_KEYS:
            raise ValueError(f"DEDUPE_INVALID_CONFIG: unknown top-level key '{k}'")

    schema_version = raw.get("schema_version", 1)
    if type(schema_version) is not int or isinstance(schema_version, bool) or schema_version != 1:
        raise ValueError(f"schema_version must be integer 1, got {schema_version!r}")

    selection_mode = raw.get("selection_mode", "weighted")
    if type(selection_mode) is not str or selection_mode not in {"weighted", "balanced_by_bytes"}:
        raise ValueError(f"Invalid selection_mode {selection_mode}, must be 'weighted' or 'balanced_by_bytes'")

    if "factors" in raw and raw["factors"] is None:
        raise ValueError("factors cannot be None; dict required")
    raw_factors = raw.get("factors")
    if raw_factors is None:
        raw_factors = {}
    elif type(raw_factors) is not dict:
        raise ValueError("factors must be a dict")

    # Strict check: factor keys
    for k in raw_factors:
        if k in RESERVED_FACTORS:
            raise ValueError(f"DEDUPE_FACTOR_UNAVAILABLE: factor '{k}' is reserved and not available in V1")
        if k not in ALLOWED_FACTOR_NAMES:
            raise ValueError(f"DEDUPE_INVALID_CONFIG: unknown factor '{k}'")

    # Path priority
    pp_raw = raw_factors.get("path_priority")
    if pp_raw is None:
        path_priority = PathPriorityFactor()
    else:
        if type(pp_raw) is not dict:
            raise ValueError("factors.path_priority must be a dict")
        for k in pp_raw:
            if k not in ALLOWED_PATH_PRIORITY_KEYS:
                raise ValueError(f"DEDUPE_INVALID_CONFIG: unknown field '{k}' in path_priority")

        pp_enabled_val = pp_raw.get("enabled", False)
        if type(pp_enabled_val) is not bool:
            raise ValueError("path_priority.enabled must be a boolean (True/False)")
        pp_weight = _validate_weight(pp_raw.get("weight", 0), "path_priority")

        pp_rules_raw = pp_raw.get("rules")
        if pp_rules_raw is None:
            pp_rules = ()
        else:
            if type(pp_rules_raw) is not list:
                raise ValueError("factors.path_priority.rules must be a list")
            if len(pp_rules_raw) > MAX_RULES_COUNT:
                raise ValueError(f"path_priority rules exceed maximum {MAX_RULES_COUNT} limit")
            rules_list = []
            for r in pp_rules_raw:
                if isinstance(r, PathPriorityRule):
                    rules_list.append(r)
                elif type(r) is dict:
                    for rk in r:
                        if rk not in ALLOWED_RULE_KEYS:
                            raise ValueError(f"DEDUPE_INVALID_CONFIG: unknown field '{rk}' in rule")
                    scope = r.get("scope", "absolute")
                    if type(scope) is not str:
                        raise ValueError("rule scope must be a string")
                    pattern = r.get("pattern")
                    if type(pattern) is not str or not pattern.strip():
                        raise ValueError("rule pattern must be a non-empty string")
                    # Preserve exact pattern characters without modifying trailing spaces
                    rules_list.append(PathPriorityRule(scope=scope, pattern=pattern))
                else:
                    raise ValueError("Path priority rule must be a dict or PathPriorityRule")
            pp_rules = tuple(rules_list)

        path_priority = PathPriorityFactor(enabled=pp_enabled_val, weight=pp_weight, rules=pp_rules)

    # Preferred extension
    pe_raw = raw_factors.get("preferred_extension")
    if pe_raw is None:
        preferred_extension = PreferredExtensionFactor()
    else:
        if type(pe_raw) is not dict:
            raise ValueError("factors.preferred_extension must be a dict")
        for k in pe_raw:
            if k not in ALLOWED_PREFERRED_EXTENSION_KEYS:
                raise ValueError(f"DEDUPE_INVALID_CONFIG: unknown field '{k}' in preferred_extension")

        pe_enabled_val = pe_raw.get("enabled", False)
        if type(pe_enabled_val) is not bool:
            raise ValueError("preferred_extension.enabled must be a boolean (True/False)")
        pe_weight = _validate_weight(pe_raw.get("weight", 0), "preferred_extension")

        pe_exts_raw = pe_raw.get("extensions")
        if pe_exts_raw is None:
            pe_exts = ()
        else:
            if type(pe_exts_raw) is not list:
                raise ValueError("factors.preferred_extension.extensions must be a list")
            if len(pe_exts_raw) > MAX_EXTENSIONS_COUNT:
                raise ValueError(f"preferred_extension extensions exceed maximum {MAX_EXTENSIONS_COUNT} limit")
            exts_list = []
            for ext in pe_exts_raw:
                if type(ext) is not str:
                    raise ValueError(f"extension must be a string, got {type(ext).__name__}")
                canon = canonicalize_extension(ext)
                if canon:
                    if len(canon) > MAX_EXTENSION_LENGTH:
                        raise ValueError(f"Extension '{canon}' exceeds maximum length of {MAX_EXTENSION_LENGTH}")
                    exts_list.append(canon)
            pe_exts = tuple(exts_list)

        preferred_extension = PreferredExtensionFactor(enabled=pe_enabled_val, weight=pe_weight, extensions=pe_exts)

    # mtime
    mt_raw = raw_factors.get("mtime")
    if mt_raw is None:
        mtime = MtimeFactor()
    else:
        if type(mt_raw) is not dict:
            raise ValueError("factors.mtime must be a dict")
        for k in mt_raw:
            if k not in ALLOWED_MTIME_KEYS:
                raise ValueError(f"DEDUPE_INVALID_CONFIG: unknown field '{k}' in mtime")

        mt_mode = mt_raw.get("mode", "none")
        if type(mt_mode) is not str:
            raise ValueError("mtime mode must be a string")
        mt_weight = _validate_weight(mt_raw.get("weight", 0), "mtime")
        mtime = MtimeFactor(mode=mt_mode, weight=mt_weight)

    factors = DedupeFactorsConfig(
        path_priority=path_priority,
        preferred_extension=preferred_extension,
        mtime=mtime,
    )

    return AdvancedDedupeConfig(
        schema_version=1,
        selection_mode=selection_mode,
        factors=factors,
    )


def canonical_config_dict(config: AdvancedDedupeConfig) -> dict[str, Any]:
    return {
        "schema_version": config.schema_version,
        "selection_mode": config.selection_mode,
        "factors": {
            "path_priority": {
                "enabled": config.factors.path_priority.enabled,
                "weight": config.factors.path_priority.weight,
                "rules": [
                    {"pattern": r.pattern, "scope": r.scope}
                    for r in config.factors.path_priority.rules
                ],
            },
            "preferred_extension": {
                "enabled": config.factors.preferred_extension.enabled,
                "weight": config.factors.preferred_extension.weight,
                "extensions": list(config.factors.preferred_extension.extensions),
            },
            "mtime": {
                "mode": config.factors.mtime.mode,
                "weight": config.factors.mtime.weight,
            },
        },
    }


def canonical_json_dumps(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_config_digest(config: AdvancedDedupeConfig) -> str:
    raw = canonical_json_dumps(canonical_config_dict(config))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
