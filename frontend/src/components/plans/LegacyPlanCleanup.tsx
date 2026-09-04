import React from 'react';
import { Alert, Button, Popconfirm, Space, Typography, message } from 'antd';
import { DeleteOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { plansApi } from '../../api/domain';

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
        `已清理 ${res.deleted_count} 个旧版兼容计划，解锁 ${res.affected_scan_count} 个扫描记录`
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
          <Text strong>检测到旧版兼容计划数据 ({summary.plan_count} 个)</Text>
          <Popconfirm
            title="确认清理所有旧版兼容计划？"
            description="此操作将永久清理旧版计划与条目，并解锁关联扫描记录的删除权限。"
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
          发现 {summary.plan_count} 个旧版计划，包含 {summary.item_count} 个条目，阻塞了{' '}
          {summary.affected_scan_count} 个扫描记录的删除。这些旧记录不参与当前系统执行链路，清理后可安全恢复扫描记录的删除权限。
        </div>
      }
    />
  );
};
