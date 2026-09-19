import React, { useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  Empty,
  Form,
  Input,
  InputNumber,
  Table,
  message,
} from 'antd';
import {
  ArrowRightOutlined,
  EyeOutlined,
  ScheduleOutlined,
} from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { batchApi, plansApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { splitLines } from '../../utils/format';
import { RenameProposal } from '../../types';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';

export const RenamePage: React.FC = () => {
  useTitle('批量重命名');
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [proposals, setProposals] = useState<RenameProposal[] | null>(null);

  const previewMutation = useMutation({
    mutationFn: (payload: any) => batchApi.previewRename(payload),
    onSuccess: (res) => {
      setProposals(res.items);
      const conflictCount = res.items.filter((item) => item.conflict).length;
      if (conflictCount > 0) {
        message.warning(`预览完成，但发现 ${conflictCount} 处重命名冲突！`);
      } else {
        message.success(`预览完成，成功生成 ${res.items.length} 个重命名提议`);
      }
    },
    onError: (err: any) => {
      message.error(err.message || '重命名预览失败');
    },
  });

  const planMutation = useMutation({
    mutationFn: (payload: any) => plansApi.createPlan(payload),
    onSuccess: (res) => {
      message.success(`已生成批量重命名计划 #${res.id}`);
      navigate(`/plans/${res.id}`);
    },
    onError: (err: any) => {
      message.error(err.message || '生成计划失败');
    },
  });

  const handlePreview = async () => {
    try {
      const values = await form.validateFields();
      let paths: string[] = [];
      if (Array.isArray(values.paths)) {
        paths = values.paths.filter(Boolean);
      } else if (typeof values.paths === 'string') {
        paths = splitLines(values.paths);
      }
      if (paths.length === 0) {
        message.error('请至少选择或输入一个待重命名路径');
        return;
      }
      previewMutation.mutate({
        paths,
        regex_pattern: values.regex_pattern || null,
        regex_replacement: values.regex_replacement || '',
        prefix: values.prefix || '',
        suffix: values.suffix || '',
        number_start:
          values.number_start !== undefined ? values.number_start : null,
        number_width: values.number_width || 3,
        include_parent: values.include_parent || false,
        source_extension: values.source_extension || '',
        target_extension: values.target_extension || '',
      });
    } catch {
      // AntD handles validation.
    }
  };

  const handleGeneratePlan = () => {
    if (!proposals || proposals.length === 0) return;
    const hasConflict = proposals.some((item) => item.conflict);
    if (hasConflict) {
      message.error('存在命名冲突，禁止生成执行计划，请调整重命名规则！');
      return;
    }
    const items = proposals.map((proposal) => ({
      operation: 'rename',
      source: proposal.source,
      target: proposal.target,
    }));
    planMutation.mutate({
      name: '批量重命名计划',
      kind: 'rename',
      items,
    });
  };

  const hasConflicts = proposals?.some((proposal) => proposal.conflict);

  const columns = [
    {
      title: '原完整路径',
      dataIndex: 'source',
      key: 'source',
      render: (value: string) => <CodePath value={value} />,
    },
    {
      title: '重命名后目标路径',
      dataIndex: 'target',
      key: 'target',
      render: (value: string, record: RenameProposal) => (
        <div className="nfc-target-path">
          <ArrowRightOutlined />
          <CodePath value={value} muted={record.conflict} />
        </div>
      ),
    },
    {
      title: '状态',
      key: 'conflict',
      width: 160,
      render: (_: unknown, record: RenameProposal) => (
        <StatusBadge
          status={record.conflict ? 'failed' : 'completed'}
          label={
            record.conflict
              ? `冲突: ${record.conflict_reason || '目标已存在'}`
              : '安全'
          }
        />
      ),
    },
  ];

  return (
    <div className="nfc-operations-page nfc-rename-page">
      <PageHeader
        eyebrow="Rename workspace"
        title="批量重命名"
        description="组合正则、扩展名替换、前后缀、父目录名与编号规则；必须先 Preview，并在无冲突时生成 Rename Plan。"
      />

      <DataPanel
        title="重命名规则"
        description="Preview 只计算目标路径与冲突；不会直接修改任何文件名。"
        className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench"
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ number_width: 3, include_parent: false }}
        >
          <Form.Item
            name="paths"
            label="文件或目录绝对路径清单"
            rules={[{ required: true, message: '请选择或输入待重命名的路径' }]}
            extra="支持可视化选择目录或高级手动多行输入"
          >
            <DirectoryPicker
              multiple
              placeholder="点击选择或添加待重命名目录..."
            />
          </Form.Item>

          <div className="nfc-form-grid">
            <Form.Item name="regex_pattern" label="正则查找 (Regex Pattern)">
              <Input placeholder="例如：^DSC_(\d+)" />
            </Form.Item>
            <Form.Item name="regex_replacement" label="正则替换 (Replacement)">
              <Input placeholder="例如：Photo_$1" />
            </Form.Item>
          </div>

          <div className="nfc-form-grid">
            <Form.Item
              name="source_extension"
              label="原扩展名过滤"
              extra="可填写 webp 或 .webp；匹配不区分大小写"
            >
              <Input placeholder="例如：.webp" />
            </Form.Item>
            <Form.Item
              name="target_extension"
              label="目标扩展名"
              extra="必须与原扩展名过滤同时填写"
            >
              <Input placeholder="例如：.jpg" />
            </Form.Item>
          </div>

          <Alert
            type="info"
            showIcon
            message="扩展名替换仅执行重命名"
            description="只修改文件名后缀，不会转换图片格式，也不会进行 WebP → JPEG 转码。"
            className="nfc-page-alert"
          />

          <div className="nfc-form-grid">
            <Form.Item name="prefix" label="添加前缀 (Prefix)">
              <Input placeholder="例如：2026_" />
            </Form.Item>
            <Form.Item name="suffix" label="添加后缀 (Suffix)">
              <Input placeholder="例如：_backup" />
            </Form.Item>
          </div>

          <div className="nfc-form-grid">
            <Form.Item name="number_start" label="起始数字序号 (可选，如 1)">
              <InputNumber
                min={0}
                placeholder="留空不添加序号"
                className="nfc-full-width-control"
              />
            </Form.Item>
            <Form.Item name="number_width" label="序号补零宽度 (位数)">
              <InputNumber min={1} max={10} className="nfc-full-width-control" />
            </Form.Item>
          </div>

          <Form.Item name="include_parent" valuePropName="checked">
            <Checkbox>在文件名前拼入直接父文件夹名称</Checkbox>
          </Form.Item>

          <ActionBar className="nfc-file-tool-primary-actions">
            <Button
              type="primary"
              icon={<EyeOutlined />}
              onClick={handlePreview}
              loading={previewMutation.isPending}
            >
              生成重命名 Preview
            </Button>
            {proposals && proposals.length > 0 && (
              <Button
                icon={<ScheduleOutlined />}
                onClick={handleGeneratePlan}
                loading={planMutation.isPending}
                disabled={hasConflicts}
              >
                生成执行 Plan ({proposals.length} 项)
              </Button>
            )}
          </ActionBar>
        </Form>
      </DataPanel>

      {hasConflicts && (
        <Alert
          type="error"
          showIcon
          message="检测到重命名目标冲突"
          description="目标路径已存在或产生内部重名冲突；生成 Plan 已锁定，请修正规则并重新 Preview。"
          className="nfc-page-alert"
        />
      )}

      {proposals && (
        <DataPanel
          title="重命名 Preview"
          description="逐项检查 source → target 与冲突状态；只有全量安全时才能生成 Plan。"
          action={<span className="nfc-panel-count">{proposals.length} proposals</span>}
          className="nfc-panel-flush nfc-file-tool-result-panel"
          variant="dense"
        >
          <ResponsiveDataView
            desktop={
              <Table
                dataSource={proposals}
                columns={columns}
                rowKey="source"
                pagination={{ pageSize: 20 }}
              />
            }
            mobile={
              <div className="nfc-mobile-record-list">
                {proposals.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无重命名提议" />
                ) : (
                  proposals.map((proposal) => (
                    <article
                      className="nfc-rename-proposal-mobile-card"
                      key={proposal.source}
                    >
                      <div className="nfc-mobile-record-heading">
                        <span className="nfc-kind-badge">rename</span>
                        <StatusBadge
                          status={proposal.conflict ? 'failed' : 'completed'}
                          label={proposal.conflict ? '冲突' : '安全'}
                        />
                      </div>
                      <div className="nfc-plan-item-paths">
                        <div className="nfc-plan-item-path-row">
                          <span>源路径</span>
                          <CodePath value={proposal.source} />
                        </div>
                        <div className="nfc-plan-item-path-row">
                          <span>目标</span>
                          <CodePath
                            value={proposal.target}
                            muted={proposal.conflict}
                          />
                        </div>
                      </div>
                      {proposal.conflict && (
                        <p className="nfc-mobile-record-error">
                          {proposal.conflict_reason || '目标已存在'}
                        </p>
                      )}
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
