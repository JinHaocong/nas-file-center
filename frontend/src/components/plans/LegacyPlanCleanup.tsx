import React from 'react';
import { Alert, Button, Popconfirm, Space, Typography, message } from 'antd';
import { DeleteOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { plansApi } from '../../api/domain';
import {
  formatLegacyClearSuccessMessage,
  formatLegacyAlertDescription,
  LEGACY_CLEANUP_CONFIRM_DESCRIPTION,
} from './plan_cleanup';

const { Text } = Typography;

export const LegacyPlanCleanup: React.FC = () => {
  const queryClient = useQueryClient();

  const { data: summary } = useQuery({
    queryKey: ['legacyPlanSummary'],
    queryFn: () => plansApi.getLegacySummary(),
  });

  const clearLegacyMutation = useMutation({
    mutationFn: () => plansApi.clearLegacyPlans(),
    onSuccess: async (res) => {
      message.success(
        formatLegacyClearSuccessMessage(res.deleted_count, res.affected_scan_count)
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['legacyPlanSummary'] }),
        queryClient.invalidateQueries({ queryKey: ['scansList'] }),
        queryClient.invalidateQueries({ queryKey: ['plansList'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] }),
      ]);
    },
    onError: (err: any) => {
      message.error(err.message || '清理旧版兼容计划失败');
    },
  });

  if (!summary || summary.plan_count === 0) {
    return null;
  }

  return (
    <Alert
      type="warning"
      showIcon
      icon={<InfoCircleOutlined />}
      style={{ marginBottom: 16, borderRadius: 8 }}
      message={
        <Space style={{ justifyContent: 'space-between', width: '100%' }}>
          <Text strong>检测到旧版计划记录 ({summary.plan_count} 个)</Text>
          <Popconfirm
            title="确认清理旧版计划记录？"
            description={LEGACY_CLEANUP_CONFIRM_DESCRIPTION}
            okText="确认清理"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => clearLegacyMutation.mutate()}
          >
            <Button
              danger
              type="primary"
              size="small"
              icon={<DeleteOutlined />}
              loading={clearLegacyMutation.isPending}
            >
              一键清理旧版计划
            </Button>
          </Popconfirm>
        </Space>
      }
      description={
        <div style={{ marginTop: 4 }}>
          {formatLegacyAlertDescription(summary)}
        </div>
      }
    />
  );
};
