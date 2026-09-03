import React, { useState } from 'react';
import { Card, Form, Input, Select, Button, Typography, Space, Table, Tag, Row, Col, message } from 'antd';
import { PlayCircleOutlined, ScheduleOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { batchApi, plansApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { splitLines } from '../../utils/format';

const { Title, Text } = Typography;
const { TextArea } = Input;

export const PathMatchPage: React.FC = () => {
  useTitle('路径匹配');
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const selectedMode = Form.useWatch('mode', form);
  const [groups, setGroups] = useState<any[] | null>(null);

  const matchMutation = useMutation({
    mutationFn: (payload: any) => batchApi.previewPathMatch(payload),
    onSuccess: (res) => {
      setGroups(res.groups);
      message.success(`匹配完成，发现 ${res.groups.length} 组匹配路径`);
    },
    onError: (err: any) => {
      message.error(err.message || '路径匹配失败');
    },
  });

  const planMutation = useMutation({
    mutationFn: (payload: any) => plansApi.createPlan(payload),
    onSuccess: (res) => {
      message.success(`已生成路径匹配处理计划 #${res.id}`);
      navigate(`/plans/${res.id}`);
    },
    onError: (err: any) => {
      message.error(err.message || '生成计划失败');
    },
  });

  const handlePreview = async () => {
    try {
      const values = await form.validateFields();
      const roots = splitLines(values.roots_text);
      if (roots.length < 2) {
        message.error('路径匹配至少需要输入 2 个根目录进行比对');
        return;
      }
      matchMutation.mutate({
        roots,
        mode: values.mode,
        normalize_pattern: values.normalize_pattern || null,
        normalize_replacement: values.normalize_replacement || '',
      });
    } catch {
      // Validation error
    }
  };

  const handleGeneratePlan = () => {
    if (!groups || groups.length === 0) return;
    const items: any[] = [];
    groups.forEach((g) => {
      if (g.members && g.members.length > 1) {
        // keep first path, quarantine rest
        const keep = g.members[0].path;
        for (let i = 1; i < g.members.length; i++) {
          items.push({
            operation: 'quarantine',
            source: g.members[i].path,
            keep: keep,
            expected_size: g.members[i].size || 0,
          });
        }
      }
    });
    if (items.length === 0) {
      message.warning('没有可生成去重计划的重复项');
      return;
    }
    planMutation.mutate({
      name: '路径匹配去重计划',
      kind: 'path-match-dedupe',
      items,
    });
  };

  const columns = [
    {
      title: '匹配键 (Key)',
      dataIndex: 'key',
      key: 'key',
      render: (key: string) => <Text strong>{key}</Text>,
    },
    {
      title: '匹配路径清单',
      dataIndex: 'members',
      key: 'members',
      render: (members: any[]) => (
        <Space direction="vertical" style={{ width: '100%' }}>
          {(members || []).map((m, idx) => (
            <div key={idx}>
              <Tag color={idx === 0 ? 'green' : 'orange'}>
                {idx === 0 ? '保留首选' : `副本 #${idx}`} ({m.root})
              </Tag>
              <Text code copyable>{m.path}</Text>
            </div>
          ))}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>
          跨目录路径匹配
        </Title>
        <Text type="secondary">按相对路径、文件名 (basename) 或正则归一化跨目录匹配同名文件</Text>
      </div>

      <Card bordered={false} style={{ borderRadius: 12, marginBottom: 16 }}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{ mode: 'relative-path', normalize_replacement: '' }}
        >
          <Form.Item
            name="roots_text"
            label="比对根目录（每行一个路径，至少 2 个）"
            rules={[{ required: true, message: '请输入比对根目录' }]}
          >
            <TextArea rows={3} placeholder="/data/NasA&#10;/data/NasB" />
          </Form.Item>

          <Form.Item name="mode" label="匹配模式">
            <Select
              options={[
                { value: 'relative-path', label: '相对路径完全匹配 (Relative Path)' },
                { value: 'basename', label: '文件名匹配 (Basename)' },
                { value: 'stem', label: '去除后缀主名匹配 (Stem)' },
                { value: 'normalized', label: '正则归一化路径匹配 (Normalized Regex)' },
              ]}
            />
          </Form.Item>

          {selectedMode === 'normalized' && (
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Form.Item
                  name="normalize_pattern"
                  label="归一化正则查找 (Pattern)"
                  rules={[{ required: true, message: 'normalized 模式必须输入正则查找 Pattern' }]}
                  tooltip="例如：\[\d+P\s*\d+V\] 或 _backup"
                >
                  <Input placeholder="例如：\[\d+P.*?\]" />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item
                  name="normalize_replacement"
                  label="正则替换内容 (Replacement)"
                  tooltip="默认为空，即直接清除匹配内容"
                >
                  <Input placeholder="替换为（默认留空清除）" />
                </Form.Item>
              </Col>
            </Row>
          )}

          <Space style={{ marginTop: 8 }}>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handlePreview}
              loading={matchMutation.isPending}
            >
              开始路径比对预览
            </Button>
            {groups && groups.length > 0 && (
              <Button
                icon={<ScheduleOutlined />}
                onClick={handleGeneratePlan}
                loading={planMutation.isPending}
              >
                生成隔离去重计划
              </Button>
            )}
          </Space>
        </Form>
      </Card>

      {groups && (
        <Card title={`匹配结果 (${groups.length} 组)`} bordered={false} style={{ borderRadius: 12 }}>
          <Table
            dataSource={groups}
            columns={columns}
            rowKey="key"
            pagination={{ pageSize: 20 }}
          />
        </Card>
      )}
    </div>
  );
};
