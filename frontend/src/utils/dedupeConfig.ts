import {
  DedupeScorerConfig,
  DirectAdvancedDedupeGenerateRequest,
} from '../types/dedupe';

export const MAX_RULES_COUNT = 64;
export const MAX_EXTENSIONS_COUNT = 64;
export const MAX_PATTERN_LENGTH = 512;
export const MAX_EXTENSION_LENGTH = 64;
export const MAX_WEIGHT = 10000;

export function createDefaultDedupeScorerConfig(): DedupeScorerConfig {
  return {
    schema_version: 1,
    selection_mode: 'weighted',
    factors: {
      path_priority: {
        enabled: false,
        weight: 0,
        rules: [],
      },
      preferred_extension: {
        enabled: false,
        weight: 0,
        extensions: [],
      },
      mtime: {
        mode: 'none',
        weight: 0,
      },
    },
  };
}

export interface ConfigValidationResult {
  valid: boolean;
  errors: string[];
}

function isValidWeight(w: any): boolean {
  return typeof w === 'number' && Number.isInteger(w) && w >= 0 && w <= MAX_WEIGHT;
}

export function validateScorerConfigForm(config: DedupeScorerConfig): ConfigValidationResult {
  const errors: string[] = [];

  if (!config) {
    return { valid: false, errors: ['配置不可为空'] };
  }

  if (config.schema_version !== 1) {
    errors.push('schema_version 必须为 1');
  }

  if (config.selection_mode !== 'weighted' && config.selection_mode !== 'balanced_by_bytes') {
    errors.push('selection_mode 必须为 weighted 或 balanced_by_bytes');
  }

  const { path_priority, preferred_extension, mtime } = config.factors || {};

  if (!path_priority || typeof path_priority.enabled !== 'boolean') {
    errors.push('path_priority 因子配置不完整');
  } else {
    if (!isValidWeight(path_priority.weight)) {
      errors.push(`path_priority 权重必须为 0 到 ${MAX_WEIGHT} 之间的整数`);
    }
    if (!Array.isArray(path_priority.rules)) {
      errors.push('path_priority rules 必须为数组');
    } else if (path_priority.rules.length > MAX_RULES_COUNT) {
      errors.push(`path_priority 规则数量不能超过 ${MAX_RULES_COUNT} 条`);
    } else {
      path_priority.rules.forEach((r, idx) => {
        if (!r.pattern || !r.pattern.trim()) {
          errors.push(`path_priority 规则 #${idx + 1} 模式不能为空`);
        } else if (r.pattern.length > MAX_PATTERN_LENGTH) {
          errors.push(`path_priority 规则 #${idx + 1} 模式长度不能超过 ${MAX_PATTERN_LENGTH} 个字符`);
        }
        if (r.scope !== 'absolute' && r.scope !== 'relative') {
          errors.push(`path_priority 规则 #${idx + 1} scope 必须为 absolute 或 relative`);
        }
      });
    }
  }

  if (!preferred_extension || typeof preferred_extension.enabled !== 'boolean') {
    errors.push('preferred_extension 因子配置不完整');
  } else {
    if (!isValidWeight(preferred_extension.weight)) {
      errors.push(`preferred_extension 权重必须为 0 到 ${MAX_WEIGHT} 之间的整数`);
    }
    if (!Array.isArray(preferred_extension.extensions)) {
      errors.push('preferred_extension extensions 必须为数组');
    } else if (preferred_extension.extensions.length > MAX_EXTENSIONS_COUNT) {
      errors.push(`preferred_extension 扩展名数量不能超过 ${MAX_EXTENSIONS_COUNT} 个`);
    } else {
      preferred_extension.extensions.forEach((ext, idx) => {
        if (!ext || !ext.trim()) {
          errors.push(`preferred_extension 扩展名 #${idx + 1} 不能为空`);
        } else if (ext.length > MAX_EXTENSION_LENGTH) {
          errors.push(`preferred_extension 扩展名 #${idx + 1} 长度不能超过 ${MAX_EXTENSION_LENGTH} 个字符`);
        }
      });
    }
  }

  if (!mtime) {
    errors.push('mtime 因子配置不完整');
  } else {
    if (!isValidWeight(mtime.weight)) {
      errors.push(`mtime 权重必须为 0 到 ${MAX_WEIGHT} 之间的整数`);
    }
    if (mtime.mode !== 'none' && mtime.mode !== 'newest' && mtime.mode !== 'oldest') {
      errors.push('mtime 模式必须为 none, newest 或 oldest');
    }
  }

  return {
    valid: errors.length === 0,
    errors,
  };
}

export function isScorerConfigDirty(a: DedupeScorerConfig, b: DedupeScorerConfig): boolean {
  if (a === b) return false;
  return JSON.stringify(a) !== JSON.stringify(b);
}

export function buildDirectAdvancedGeneratePayload(
  config: DedupeScorerConfig,
  expectedPreviewDigest: string
): DirectAdvancedDedupeGenerateRequest {
  return {
    scorer_config: JSON.parse(JSON.stringify(config)),
    expected_preview_digest: expectedPreviewDigest,
  };
}

export function buildWorkflowGeneratePayload(
  expectedCompileDigest: string,
  scanJobId: number
): { expected_compile_digest: string; runtime_inputs: { scan_job_id: number } } {
  return {
    expected_compile_digest: expectedCompileDigest,
    runtime_inputs: {
      scan_job_id: scanJobId,
    },
  };
}
