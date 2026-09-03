import React from 'react';
import { Tag, Tooltip } from 'antd';
import { LockOutlined, WarningOutlined, AlertOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { settingsApi } from '../api/domain';

export const SafeModeBadge: React.FC = () => {
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => settingsApi.getSettings(),
    staleTime: 60000,
  });

  if (!settings) {
    return <Tag color="default">加载安全模式...</Tag>;
  }

  if (settings.allow_delete) {
    return (
      <Tooltip title="危险：ALLOW_DELETE=true，系统允许永久删除文件，请务必谨慎操作！">
        <Tag color="error" icon={<AlertOutlined />} style={{ fontWeight: 'bold', padding: '2px 8px' }}>
          永久删除已开启
        </Tag>
      </Tooltip>
    );
  }

  if (settings.allow_mutation) {
    return (
      <Tooltip title="ALLOW_MUTATION=true，允许隔离/移动/重命名等文件变更操作">
        <Tag color="warning" icon={<WarningOutlined />} style={{ fontWeight: 500, padding: '2px 8px' }}>
          允许文件修改 (隔离模式)
        </Tag>
      </Tooltip>
    );
  }

  return (
    <Tooltip title="ALLOW_MUTATION=false，只读安全保护模式生效中，禁止任何修改和删除操作">
      <Tag color="success" icon={<LockOutlined />} style={{ fontWeight: 500, padding: '2px 8px' }}>
        只读安全模式
      </Tag>
    </Tooltip>
  );
};
