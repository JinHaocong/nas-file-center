export const STATUS_MAP: Record<string, { label: string; color: string }> = {
  queued: { label: '排队中', color: 'default' },
  running: { label: '运行中', color: 'processing' },
  completed: { label: '已完成', color: 'success' },
  failed: { label: '失败', color: 'error' },
  draft: { label: '草稿', color: 'default' },
  frozen: { label: '已冻结', color: 'cyan' },
  validating: { label: '校验中', color: 'processing' },
  ready: { label: '可执行', color: 'success' },
  partial: { label: '部分完成', color: 'warning' },
  executing: { label: '执行中', color: 'processing' },
  planned: { label: '计划中', color: 'default' },
  validated: { label: '已校验', color: 'success' },
  skipped: { label: '已跳过', color: 'warning' },
};

export const POLICY_OPTIONS = [
  { value: 'balanced-roots', label: '多根目录均衡保留 (Balanced Roots)' },
  { value: 'keep-newest', label: '保留最新文件 (Keep Newest)' },
  { value: 'keep-oldest', label: '保留最旧文件 (Keep Oldest)' },
  { value: 'keep-first-root', label: '优先保留第一个根目录 (Keep First Root)' },
  { value: 'path-priority', label: '按完整路径优先级 (Path Priority)' },
  { value: 'relative-path-preference', label: '按相对路径优先级 (Relative Path Preference)' },
];
