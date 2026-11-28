const jobTypes: Record<string, string> = {
  'fclones-scan': '去重扫描',
  'index-root': '更新文件索引',
  'media-organizer-preview': '生成整理预览',
  'media-organizer-batch': '整理媒体',
  'media-analysis': '分析媒体',
  'media-integrity-verify': '校验媒体完整性',
  'download-verify-webdav': '核对下载文件',
  'cloud-copy': '云端复制到 NAS',
  'workflow-scheduled': '定时工作流',
  'plan-execute': '执行计划',
};

/** Keep the original job type visible when a newer Worker introduces a new operation. */
export function taskTypeLabel(type: string): string {
  return jobTypes[type] ?? type;
}
