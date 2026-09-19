import React, { useState } from 'react';
import {
  Button,
  Empty,
  Form,
  Input,
  Select,
  Table,
  message,
} from 'antd';
import { PlayCircleOutlined, ScheduleOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { batchApi, plansApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { splitLines } from '../../utils/format';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';

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
      let roots: string[] = [];
      if (Array.isArray(values.roots)) {
        roots = values.roots.filter(Boolean);
      } else if (typeof values.roots === 'string') {
        roots = splitLines(values.roots);
      }
      if (roots.length < 2) {
        message.error('路径匹配至少需要选择或输入 2 个根目录进行比对');
        return;
      }
      matchMutation.mutate({
        roots,
        mode: values.mode,
        normalize_pattern: values.normalize_pattern || null,
        normalize_replacement: values.normalize_replacement || '',
      });
    } catch {
      // AntD handles validation.
    }
  };

  const handleGeneratePlan = () => {
    if (!groups || groups.length === 0) return;
    const items: any[] = [];
    groups.forEach((g) => {
      if (g.members && g.members.length > 1) {
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
      title: '匹配键',
      dataIndex: 'key',
      key: 'key',
      width: 260,
      render: (key: string) => <span className="nfc-mono">{key}</span>,
    },
    {
      title: '匹配路径',
      dataIndex: 'members',
      key: 'members',
      render: (members: any[]) => (
        <div className="nfc-path-match-members">
          {(members || []).map((member, index) => (
            <div className="nfc-path-match-member" key={`${member.path}-${index}`}>
              <StatusBadge
                status={index === 0 ? 'completed' : 'paused'}
                label={index === 0 ? '保留首选' : `副本 #${index}`}
              />
              <span className="nfc-kind-badge">{member.root}</span>
              <CodePath value={member.path} />
            </div>
          ))}
        </div>
      ),
    },
  ];

  return (
    <div className="nfc-operations-page nfc-path-match-page">
      <PageHeader
        eyebrow="Path matching"
        title="跨目录路径匹配"
        description="按相对路径、basename、stem 或正则归一化跨根目录匹配；Preview 只读，生成 Plan 后仍需完整生命周期校验。"
      />

      <DataPanel
        title="匹配规则"
        description="至少选择两个根目录；路径必须位于 ALLOWED_ROOTS。"
        className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench"
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ mode: 'relative-path', normalize_replacement: '' }}
        >
          <Form.Item
            name="roots"
            label="比对根目录（至少 2 个）"
            rules={[{ required: true, message: '请至少选择 2 个比对根目录' }]}
          >
            <DirectoryPicker
              multiple
              placeholder="点击选择或添加待比对根目录 (至少2个)..."
            />
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
            <div className="nfc-form-grid">
              <Form.Item
                name="normalize_pattern"
                label="归一化正则查找"
                rules={[
                  {
                    required: true,
                    message: 'normalized 模式必须输入正则查找 Pattern',
                  },
                ]}
                tooltip="例如：\[\d+P\s*\d+V\] 或 _backup"
              >
                <Input placeholder="例如：\[\d+P.*?\]" />
              </Form.Item>
              <Form.Item
                name="normalize_replacement"
                label="正则替换内容"
                tooltip="默认为空，即直接清除匹配内容"
              >
                <Input placeholder="替换为（默认留空清除）" />
              </Form.Item>
            </div>
          )}

          <ActionBar className="nfc-file-tool-primary-actions">
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handlePreview}
              loading={matchMutation.isPending}
            >
              开始只读比对
            </Button>
            {groups && groups.length > 0 && (
              <Button
                icon={<ScheduleOutlined />}
                onClick={handleGeneratePlan}
                loading={planMutation.isPending}
              >
                生成去重 Plan ({groups.length} 组)
              </Button>
            )}
          </ActionBar>
        </Form>
      </DataPanel>

      {groups && (
        <DataPanel
          title="路径匹配 Preview"
          description="每组第一个成员作为 keep，后续成员作为 Quarantine Plan 候选；此处尚未修改文件。"
          action={<span className="nfc-panel-count">{groups.length} groups</span>}
          className="nfc-panel-flush nfc-file-tool-result-panel"
          variant="dense"
        >
          <ResponsiveDataView
            desktop={
              <Table
                dataSource={groups}
                columns={columns}
                rowKey="key"
                pagination={{ pageSize: 20 }}
              />
            }
            mobile={
              <div className="nfc-mobile-record-list">
                {groups.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未发现匹配组" />
                ) : (
                  groups.map((group) => (
                    <article className="nfc-path-match-mobile-card" key={group.key}>
                      <div className="nfc-mobile-record-heading">
                        <strong className="nfc-mobile-record-title nfc-mono">
                          {group.key}
                        </strong>
                        <span className="nfc-panel-count">
                          {group.members?.length || 0} members
                        </span>
                      </div>
                      <div className="nfc-path-match-members">
                        {(group.members || []).map((member: any, index: number) => (
                          <div
                            className="nfc-path-match-member"
                            key={`${member.path}-${index}`}
                          >
                            <StatusBadge
                              status={index === 0 ? 'completed' : 'paused'}
                              label={index === 0 ? '保留首选' : `副本 #${index}`}
                            />
                            <span className="nfc-kind-badge">{member.root}</span>
                            <CodePath value={member.path} />
                          </div>
                        ))}
                      </div>
                    </article>
                  ))
                )}
              </div>
            }
          />
        </DataPanel>
      )}
    </div>
  );
};
