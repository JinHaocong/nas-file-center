import { POLICY_OPTIONS } from '../../utils/constants';

export interface ClassicDedupeValues {
  policy: string;
  pathPriorityText: string;
  relativePathPriorityText: string;
}

export interface ClassicDedupePayload {
  policy: string;
  path_priority_patterns?: string[];
  relative_path_priority_patterns?: string[];
}

export const defaultClassicDedupeValues = (): ClassicDedupeValues => ({
  policy: 'balanced-roots',
  pathPriorityText: '',
  relativePathPriorityText: '',
});

export const splitPriorityPatterns = (input: string): string[] =>
  input.split(/\r?\n/).map(value => value.trim()).filter(Boolean);

/** Form-only validation. Plan safety authority remains on the backend. */
export function validateClassicDedupe(values: ClassicDedupeValues): string | null {
  if (!POLICY_OPTIONS.some(option => option.value === values.policy)) return '请选择保留策略';
  if (values.policy === 'path-priority' &&
      !splitPriorityPatterns(values.pathPriorityText).length) return '请输入路径优先级规则';
  if (values.policy === 'relative-path-preference' &&
      !splitPriorityPatterns(values.relativePathPriorityText).length) return '请输入相对路径优先级规则';
  return null;
}

export function toClassicDedupePayload(values: ClassicDedupeValues): ClassicDedupePayload {
  const payload: ClassicDedupePayload = { policy: values.policy };
  if (values.policy === 'path-priority') {
    payload.path_priority_patterns = splitPriorityPatterns(values.pathPriorityText);
  }
  if (values.policy === 'relative-path-preference') {
    payload.relative_path_priority_patterns = splitPriorityPatterns(values.relativePathPriorityText);
  }
  return payload;
}
