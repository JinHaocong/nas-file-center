import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { settingsApi } from '../api/domain';
import { ConsoleIcon } from './ui/ConsoleIcon';

export const SafeModeBadge: React.FC = () => {
  const { data: settings, isError } = useQuery({
    queryKey: ['settings'],
    queryFn: () => settingsApi.getSettings(),
    staleTime: 60000,
  });
  if (!settings) {
    return <span className="nfc-header-status-badge is-loading"
      title={isError ? '安全状态无法获取，请检查后端连接' : '正在读取后端安全配置'}
      role="status"><ConsoleIcon name="shield-check" size={14} /> 安全状态未知</span>;
  }
  if (settings.allow_delete) {
    return <span className="nfc-header-status-badge is-danger" role="status"
      title="危险：ALLOW_DELETE=true，允许永久删除文件，请务必谨慎操作！">
      <ConsoleIcon name="shield-check" size={14} /> 永久删除
    </span>;
  }
  if (settings.allow_mutation) {
    return <span className="nfc-header-status-badge is-warning" role="status"
      title="ALLOW_MUTATION=true，允许隔离、移动、重命名等文件变更操作">
      <ConsoleIcon name="shield-check" size={14} /> 隔离写入
    </span>;
  }
  return <span className="nfc-header-status-badge is-safe" role="status"
    title="ALLOW_MUTATION=false，只读安全保护模式生效，禁止任何修改和删除操作">
    <ConsoleIcon name="lock" size={14} /> 只读
  </span>;
};
