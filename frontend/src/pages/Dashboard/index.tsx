import React from 'react';
import { Row, Col, Card, Statistic, Table, Tag, Typography, Button, Space, Empty, Alert } from 'antd';
import {
  FileTextOutlined,
  ScanOutlined,
  DeleteOutlined,
  ScheduleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import ReactECharts from 'echarts-for-react';
import { dashboardApi, scansApi, tasksApi } from '../../api/domain';
import { useTheme } from '../../contexts/ThemeContext';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import { STATUS_MAP } from '../../utils/constants';

const { Title, Text } = Typography;

export const DashboardPage: React.FC = () => {
  useTitle('系统概览');
  const navigate = useNavigate();
  const { isDark } = useTheme();

  const { data: summary, isLoading: summaryLoading, refetch: refetchSummary } = useQuery({
    queryKey: ['dashboardSummary'],
    queryFn: () => dashboardApi.getSummary(),
    refetchInterval: 10000,
  });

  const { data: scansData, isLoading: scansLoading } = useQuery({
    queryKey: ['recentScans'],
    queryFn: () => scansApi.listScans(1, 5),
  });

  const { data: tasksData, isLoading: tasksLoading } = useQuery({
    queryKey: ['recentTasks'],
    queryFn: () => tasksApi.listJobs(1, 5),
    refetchInterval: 5000,
  });

  const chartOption = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} ({d}%)',
    },
    legend: {
      bottom: '5%',
      left: 'center',
      textStyle: { color: isDark ? '#ddd' : '#333' },
    },
    series: [
      {
        name: '文件与去重分布',
        type: 'pie',
        radius: ['45%', '70%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 8,
          borderColor: isDark ? '#141414' : '#fff',
          borderWidth: 2,
        },
        label: {
          show: false,
          position: 'center',
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 16,
            fontWeight: 'bold',
            color: isDark ? '#fff' : '#333',
          },
        },
        data: [
          { value: summary?.indexed_files || 0, name: '索引文件数', itemStyle: { color: '#1677ff' } },
          { value: summary?.indexed_folders || 0, name: '索引目录数', itemStyle: { color: '#52c41a' } },
          { value: summary?.duplicate_group_count || 0, name: '最新扫描重复组', itemStyle: { color: '#fa8c16' } },
          { value: summary?.plan_count || 0, name: '批处理计划', itemStyle: { color: '#722ed1' } },
        ],
      },
    ],
  };

  const scanColumns = [
    {
      title: '扫描名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: any) => (
        <a onClick={() => navigate(`/scans/${record.id}`)} style={{ fontWeight: 500 }}>
          {text}
        </a>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const item = STATUS_MAP[status] || { label: status, color: 'default' };
        return <Tag color={item.color}>{item.label}</Tag>;
      },
    },
    {
      title: '重复组',
      dataIndex: 'total_groups',
      key: 'total_groups',
    },
    {
      title: '可释放空间',
      dataIndex: 'reclaimable_bytes',
      key: 'reclaimable_bytes',
      render: (bytes: number) => (
        <Text type={bytes > 0 ? 'success' : undefined} strong={bytes > 0}>
          {formatBytes(bytes)}
        </Text>
      ),
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (val: string) => formatDateTime(val),
    },
  ];

  const taskColumns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 60,
    },
    {
      title: '任务类型',
      dataIndex: 'kind',
      key: 'kind',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const item = STATUS_MAP[status] || { label: status, color: 'default' };
        return <Tag color={item.color}>{item.label}</Tag>;
      },
    },
    {
      title: '进度',
      key: 'progress',
      render: (_: any, record: any) => {
        if (record.progress_total > 0) {
          const pct = Math.round((record.progress_current / record.progress_total) * 100);
          return `${record.progress_current}/${record.progress_total} (${pct}%)`;
        }
        return record.progress_current > 0 ? `${record.progress_current} 项` : '-';
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (val: string) => formatDateTime(val),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>
            系统概览
          </Title>
          <Text type="secondary">NAS 文件中心核心运行状态与数据指标</Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => refetchSummary()} loading={summaryLoading}>
          刷新
        </Button>
      </div>

      {/* Snapshot Semantics Notice */}
      <Alert
        type="info"
        showIcon
        message="扫描快照时效说明"
        description="系统概览中的重复组与可释放空间基于最近一次已完成扫描任务的快照结果；如需获取最新 NAS 去重状态，请前往扫描页面发起新任务。"
        style={{ marginBottom: 16, borderRadius: 10 }}
        closable
      />

      {/* Statistics Cards */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false} style={{ borderRadius: 12 }}>
            <Statistic
              title="已索引文件 / 目录"
              value={summary?.indexed_files || 0}
              suffix={`/ ${summary?.indexed_folders || 0}`}
              prefix={<FileTextOutlined style={{ color: '#1677ff' }} />}
            />
            <div style={{ marginTop: 6 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                已构建元数据索引库
              </Text>
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false} style={{ borderRadius: 12 }}>
            <Statistic
              title="最近一次扫描发现"
              value={summary?.latest_scan_id ? (summary?.duplicate_group_count || 0) : '—'}
              suffix={summary?.latest_scan_id ? '组' : undefined}
              prefix={<ScanOutlined style={{ color: '#fa8c16' }} />}
            />
            <div style={{ marginTop: 6 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {summary?.latest_scan_id
                  ? `基于: ${summary.latest_scan_name || `扫描 #${summary.latest_scan_id}`} (${summary.latest_scan_finished_at ? formatDateTime(summary.latest_scan_finished_at) : '已完成'})`
                  : '暂无已完成扫描'}
              </Text>
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false} style={{ borderRadius: 12 }}>
            <Statistic
              title="最近一次扫描预计可释放"
              value={summary?.latest_scan_id ? formatBytes(summary?.latest_reclaimable_bytes || 0) : '—'}
              prefix={<DeleteOutlined style={{ color: '#52c41a' }} />}
              valueStyle={{ color: summary?.latest_scan_id ? '#52c41a' : undefined }}
            />
            <div style={{ marginTop: 6 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {summary?.latest_scan_id
                  ? '单次扫描潜在释放量快照'
                  : '暂无已完成扫描'}
              </Text>
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card bordered={false} style={{ borderRadius: 12 }}>
            <Statistic
              title="批处理计划总数"
              value={summary?.plan_count || 0}
              prefix={<ScheduleOutlined style={{ color: '#722ed1' }} />}
            />
            <div style={{ marginTop: 6 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                去重与整理执行计划
              </Text>
            </div>
          </Card>
        </Col>
      </Row>

      {/* Charts & Summaries */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card
            title="系统数据概览"
            bordered={false}
            style={{ borderRadius: 12, minHeight: 340 }}
          >
            {summary && (summary.indexed_files > 0 || summary.duplicate_group_count > 0) ? (
              <ReactECharts option={chartOption} style={{ height: 260 }} />
            ) : (
              <Empty description="暂无索引或去重数据" style={{ marginTop: 40 }} />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card
            title="快速操作"
            bordered={false}
            style={{ borderRadius: 12, minHeight: 340 }}
          >
            <Space direction="vertical" style={{ width: '100%' }} size="middle">
              <Card
                type="inner"
                title="新建 fclones 精确扫描"
                extra={<Button type="link" onClick={() => navigate('/scans')}>前往扫描 &gt;</Button>}
              >
                基于 Rust fclones 快速发现重复文件组，安全隔离与清理。
              </Card>
              <Card
                type="inner"
                title="增量文件索引"
                extra={<Button type="link" onClick={() => navigate('/indexes')}>前往索引 &gt;</Button>}
              >
                针对几十 TB 目录建立增量索引，支持秒级路径查询与匹配。
              </Card>
              <Card
                type="inner"
                title="Organizer 目录整理"
                extra={<Button type="link" onClick={() => navigate('/organizer')}>整理 &gt;</Button>}
              >
                按真实照片/视频统计自动重命名并规范目录结构。
              </Card>
            </Space>
          </Card>
        </Col>
      </Row>

      {/* Recent Scans & Tasks */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card
            title="最近扫描任务"
            bordered={false}
            style={{ borderRadius: 12 }}
            extra={<Button type="link" onClick={() => navigate('/scans')}>全部扫描 &gt;</Button>}
          >
            <Table
              dataSource={scansData?.items || []}
              columns={scanColumns}
              rowKey="id"
              pagination={false}
              loading={scansLoading}
              size="small"
              locale={{ emptyText: <Empty description="暂无扫描任务" /> }}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card
            title="后台执行队列"
            bordered={false}
            style={{ borderRadius: 12 }}
            extra={<Button type="link" onClick={() => navigate('/tasks')}>全部任务 &gt;</Button>}
          >
            <Table
              dataSource={tasksData?.items || []}
              columns={taskColumns}
              rowKey="id"
              pagination={false}
              loading={tasksLoading}
              size="small"
              locale={{ emptyText: <Empty description="暂无执行中任务" /> }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
};
