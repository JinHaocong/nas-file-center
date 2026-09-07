from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Literal


RESERVED_FACTORS = frozenset({"resolution", "bitrate", "dimensions", "fps", "codec", "audio_channels"})
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
    if not isinstance(val, str):
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
    if isinstance(weight, bool):
        raise ValueError(f"Factor '{factor_name}' weight cannot be boolean; strict integer required")
    if not isinstance(weight, int):
        raise ValueError(f"Factor '{factor_name}' weight must be an integer, got {type(weight).__name__}")
    if weight < 0 or weight > 10_000:
        raise ValueError(f"Factor '{factor_name}' weight {weight} out of range [0, 10000]")
    return weight


@dataclass(frozen=True)
class PathPriorityRule:
    scope: Literal["absolute", "relative"]
    pattern: str

    def __post_init__(self):
        if self.scope not in {"absolute", "relative"}:
            raise ValueError(f"PathPriorityRule scope must be 'absolute' or 'relative', got {self.scope!r}")
        if not isinstance(self.pattern, str) or not self.pattern.strip():
            raise ValueError("PathPriorityRule pattern must be a non-empty string")
        if len(self.pattern) > MAX_PATTERN_LENGTH:
            raise ValueError(f"PathPriorityRule pattern exceeds maximum length of {MAX_PATTERN_LENGTH}")


@dataclass(frozen=True)
class PathPriorityFactor:
    enabled: bool = False
    weight: int = 0
    rules: list[PathPriorityRule] = field(default_factory=list)

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise ValueError("PathPriorityFactor enabled must be a boolean")
        _validate_weight(self.weight, "path_priority")
        if len(self.rules) > MAX_RULES_COUNT:
            raise ValueError(f"path_priority rules exceed maximum {MAX_RULES_COUNT} limit")


@dataclass(frozen=True)
class PreferredExtensionFactor:
    enabled: bool = False
    weight: int = 0
    extensions: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise ValueError("PreferredExtensionFactor enabled must be a boolean")
        _validate_weight(self.weight, "preferred_extension")
        if len(self.extensions) > MAX_EXTENSIONS_COUNT:
            raise ValueError(f"preferred_extension extensions exceed maximum {MAX_EXTENSIONS_COUNT} limit")


@dataclass(frozen=True)
class MtimeFactor:
    mode: Literal["none", "newest", "oldest"] = "none"
    weight: int = 0

    def __post_init__(self):
        if self.mode not in {"none", "newest", "oldest"}:
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
        if self.schema_version != 1:
            raise ValueError(f"Invalid schema_version {self.schema_version}, must be 1")
        if self.selection_mode not in {"weighted", "balanced_by_bytes"}:
            raise ValueError(f"Invalid selection_mode {self.selection_mode}, must be 'weighted' or 'balanced_by_bytes'")


def validate_and_canonicalize_config(raw: Any) -> AdvancedDedupeConfig:
    if isinstance(raw, AdvancedDedupeConfig):
        return raw

    if not isinstance(raw, dict):
        raise ValueError("Config must be a dictionary or AdvancedDedupeConfig instance")

    schema_version = raw.get("schema_version", 1)
    if schema_version != 1:
        raise ValueError(f"Invalid schema_version {schema_version}, must be 1")

    selection_mode = raw.get("selection_mode", "weighted")
    if selection_mode not in {"weighted", "balanced_by_bytes"}:
        raise ValueError(f"Invalid selection_mode {selection_mode}, must be 'weighted' or 'balanced_by_bytes'")

    raw_factors = raw.get("factors") or {}
    if not isinstance(raw_factors, dict):
        raise ValueError("factors must be a dictionary")

    # Check reserved factors
    for k in raw_factors:
        if k in RESERVED_FACTORS:
            raise ValueError(f"DEDUPE_FACTOR_UNAVAILABLE: factor '{k}' is reserved and not available in V1")

    # Path priority
    pp_raw = raw_factors.get("path_priority") or {}
    if not isinstance(pp_raw, dict):
        raise ValueError("factors.path_priority must be a dictionary")
    pp_enabled = bool(pp_raw.get("enabled", False))
    pp_weight = _validate_weight(pp_raw.get("weight", 0), "path_priority")
    pp_rules_raw = pp_raw.get("rules") or []
    if not isinstance(pp_rules_raw, list):
        raise ValueError("factors.path_priority.rules must be a list")
    if len(pp_rules_raw) > MAX_RULES_COUNT:
        raise ValueError(f"path_priority rules exceed maximum {MAX_RULES_COUNT} limit")
    pp_rules = []
    for r in pp_rules_raw:
        if isinstance(r, PathPriorityRule):
            pp_rules.append(r)
        elif isinstance(r, dict):
            scope = r.get("scope", "absolute")
            pattern = str(r.get("pattern", "")).strip()
            pp_rules.append(PathPriorityRule(scope=scope, pattern=pattern))
        else:
            raise ValueError("Path priority rule must be a dict or PathPriorityRule")

    path_priority = PathPriorityFactor(enabled=pp_enabled, weight=pp_weight, rules=pp_rules)

    # Preferred extension
    pe_raw = raw_factors.get("preferred_extension") or {}
    if not isinstance(pe_raw, dict):
        raise ValueError("factors.preferred_extension must be a dictionary")
    pe_enabled = bool(pe_raw.get("enabled", False))
    pe_weight = _validate_weight(pe_raw.get("weight", 0), "preferred_extension")
    pe_exts_raw = pe_raw.get("extensions") or []
    if not isinstance(pe_exts_raw, list):
        raise ValueError("factors.preferred_extension.extensions must be a list")
    if len(pe_exts_raw) > MAX_EXTENSIONS_COUNT:
        raise ValueError(f"preferred_extension extensions exceed maximum {MAX_EXTENSIONS_COUNT} limit")
    pe_exts = []
    for ext in pe_exts_raw:
        canon = canonicalize_extension(str(ext))
        if canon:
            if len(canon) > MAX_EXTENSION_LENGTH:
                raise ValueError(f"Extension '{canon}' exceeds maximum length of {MAX_EXTENSION_LENGTH}")
            pe_exts.append(canon)

    preferred_extension = PreferredExtensionFactor(enabled=pe_enabled, weight=pe_weight, extensions=pe_exts)

    # mtime
    mt_raw = raw_factors.get("mtime") or {}
    if not isinstance(mt_raw, dict):
        raise ValueError("factors.mtime must be a dictionary")
    mt_mode = mt_raw.get("mode", "none")
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
