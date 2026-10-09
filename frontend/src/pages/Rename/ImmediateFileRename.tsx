import React, { useRef, useState } from 'react';
import { Alert, Button, Checkbox, Empty, Form, Input, Radio, Table, message } from 'antd';
import { ArrowRightOutlined, EyeOutlined, ScheduleOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { batchApi, plansApi } from '../../api/domain';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { CodePath } from '../../components/ui/CodePath';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { StatusBadge } from '../../components/ui/StatusBadge';
import type { RenameProposal } from '../../types';

type Module = 'replace' | 'add';
type ReplaceTarget = 'name' | 'suffix';
type AddPosition = 'prefix' | 'suffix';

interface FileRenameForm {
  parent: string;
  find: string;
  value: string;
  preserve_extension: boolean;
}

export const ImmediateFileRename: React.FC = () => {
  const navigate = useNavigate();
  const [form] = Form.useForm<FileRenameForm>();
  const [module, setModule] = useState<Module>('replace');
  const [replaceTarget, setReplaceTarget] = useState<ReplaceTarget>('name');
  const [addPosition, setAddPosition] = useState<AddPosition>('prefix');
  const [proposals, setProposals] = useState<RenameProposal[] | null>(null);
  // Reject late Preview responses after a rule/path change.
  const activePreviewKey = useRef<string | null>(null);
  const clearPreview = () => {
    activePreviewKey.current = null;
    setProposals(null);
  };

  const previewMutation = useMutation({
    mutationFn: batchApi.previewImmediateFileRename,
    onSuccess: (response, variables) => {
      if (JSON.stringify(variables) !== activePreviewKey.current) return;
      setProposals(response.items);
      const conflicts = response.items.filter((item) => item.conflict).length;
      if (conflicts) {
        message.warning(`发现 ${conflicts} 项冲突，不能创建执行计划`);
      } else {
        message.success(`预览完成，${response.count} 个文件需要改名`);
      }
    },
    onError: (error: any, variables) => {
      if (JSON.stringify(variables) !== activePreviewKey.current) return;
      clearPreview();
      message.error(error.message || '文件重命名预览失败');
    },
  });

  const planMutation = useMutation({
    mutationFn: plansApi.createPlan,
    onSuccess: (result) => {
      message.success(`文件重命名计划 #${result.id} 已创建`);
      navigate(`/plans/${result.id}`);
    },
    onError: (error: any) => message.error(error.message || '创建重命名计划失败'),
  });

  const changeModule = (next: Module) => {
    setModule(next);
    clearPreview();
  };
  const changeReplaceTarget = (next: ReplaceTarget) => {
    setReplaceTarget(next);
    clearPreview();
  };
  const changeAddPosition = (next: AddPosition) => {
    setAddPosition(next);
    clearPreview();
  };

  const handlePreview = async () => {
    try {
      const values = await form.validateFields();
      const find = values.find || '';
      const value = values.value || '';
      if (module === 'replace' && !find) {
        message.error('请输入要查找的字面量文本');
        return;
      }
      if (module === 'add' && !value) {
        message.error('请输入要新增的文本');
        return;
      }
      const mode: 'replace_name' | 'replace_suffix' | 'add_prefix' | 'add_suffix' = module === 'replace'
        ? (replaceTarget === 'name' ? 'replace_name' : 'replace_suffix')
        : (addPosition === 'prefix' ? 'add_prefix' : 'add_suffix');
      const payload = { parent: values.parent, mode, find, value, preserve_extension: values.preserve_extension !== false };
      clearPreview();
      activePreviewKey.current = JSON.stringify(payload);
      previewMutation.mutate(payload);
    } catch {
      // Form handles invalid input.
    }
  };

  const hasConflicts = proposals?.some((item) => item.conflict) ?? false;
  const generatePlan = () => {
    if (!proposals?.length || hasConflicts) return;
    planMutation.mutate({
      name: '一级文件批量重命名',
      kind: 'rename',
      items: proposals.map(({ source, target }) => ({
        operation: 'rename', source, target,
      })),
    });
  };

  const columns = [
    {
      title: '原文件',
      dataIndex: 'source',
      key: 'source',
      render: (value: string) => <CodePath value={value} />,
    },
    {
      title: '新文件',
      dataIndex: 'target',
      key: 'target',
      render: (value: string, item: RenameProposal) => (
        <div className="nfc-target-path">
          <ArrowRightOutlined />
          <CodePath value={value} muted={item.conflict} />
        </div>
      ),
    },
    {
      title: '预览状态',
      key: 'conflict',
      width: 190,
      render: (_: unknown, item: RenameProposal) => (
        <StatusBadge
          status={item.conflict ? 'failed' : 'completed'}
          label={item.conflict ? item.conflict_reason || '命名冲突' : '安全'}
        />
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="一级文件批量重命名"
        description="只处理选中目录下的直接普通文件；不递归、不修改目录。按字面量操作，不使用正则。"
      />
      <DataPanel
        title="选择目录和命名规则"
        description="先生成只读预览，再生成 Rename Plan；需要经原有 Plan 校验和 Worker 执行。"
        className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench"
      >
        <Form<FileRenameForm>
          form={form}
          layout="vertical"
          initialValues={{ preserve_extension: true }}
          onValuesChange={clearPreview}
        >
          <Form.Item
            name="parent"
            label="当前目录"
            rules={[{ required: true, message: '请选择当前目录' }]}
            extra="只处理当前目录的直接普通文件；子文件夹内的文件不参与。"
          >
            <DirectoryPicker placeholder="选择需要批量重命名直接文件的目录" />
          </Form.Item>

          <Form.Item label="操作模块">
            <Radio.Group
              value={module}
              onChange={(event) => changeModule(event.target.value as Module)}
              optionType="button"
              buttonStyle="solid"
            >
              <Radio.Button value="replace">批量替换</Radio.Button>
              <Radio.Button value="add">新增内容</Radio.Button>
            </Radio.Group>
          </Form.Item>

          {module === 'replace' ? (
            <>
              <Form.Item label="替换范围">
                <Radio.Group
                  value={replaceTarget}
                  onChange={(event) => changeReplaceTarget(event.target.value as ReplaceTarget)}
                >
                  <Radio value="name">替换名称中的字面量</Radio>
                  <Radio value="suffix">替换文件主名末尾的字面量</Radio>
                </Radio.Group>
              </Form.Item>
              <Alert
                type="info"
                showIcon
                message={replaceTarget === 'name'
                  ? '名称替换会替换文件名中出现的全部完全匹配文本（区分大小写）'
                  : '末尾替换作用于当前处理范围的结尾：保留扩展名时为主名末尾，关闭时为整个文件名末尾'}
                className="nfc-page-alert"
              />
              <div className="nfc-form-grid">
                <Form.Item
                  name="find"
                  label="查找字面量"
                  rules={[{ required: true, message: '请输入查找文本' }]}
                >
                  <Input maxLength={255} placeholder={replaceTarget === 'name' ? '例如：旧名称' : '例如：_old'} />
                </Form.Item>
                <Form.Item name="value" label="替换为（可留空表示删除）">
                  <Input maxLength={255} placeholder="例如：新名称" />
                </Form.Item>
              </div>
            </>
          ) : (
            <>
              <Form.Item label="新增位置">
                <Radio.Group
                  value={addPosition}
                  onChange={(event) => changeAddPosition(event.target.value as AddPosition)}
                >
                  <Radio value="prefix">文件名前新增（前缀）</Radio>
                  <Radio value="suffix">文件名后新增（后缀）</Radio>
                </Radio.Group>
              </Form.Item>
              <Form.Item
                name="value"
                label={addPosition === 'prefix' ? '新增前缀' : '新增后缀'}
                rules={[{ required: true, message: '请输入新增文本' }]}
              >
                <Input maxLength={255} placeholder={addPosition === 'prefix' ? '例如：2026_' : '例如：_完成'} />
              </Form.Item>
            </>
          )}

          <Form.Item name="preserve_extension" valuePropName="checked"
            extra="开启时仅修改最后一个扩展名前的内容，例如 .jpg、.gz；关闭时会修改完整文件名。">
            <Checkbox>保留文件扩展名（推荐）</Checkbox>
          </Form.Item>

          <ActionBar className="nfc-file-tool-primary-actions">
            <Button type="primary" icon={<EyeOutlined />} onClick={handlePreview} loading={previewMutation.isPending}>
              生成一级文件 Preview
            </Button>
            {proposals !== null && proposals.length > 0 && (
              <Button icon={<ScheduleOutlined />} onClick={generatePlan}
                disabled={hasConflicts || previewMutation.isPending} loading={planMutation.isPending}>
                生成执行 Plan（{proposals.length} 项）
              </Button>
            )}
          </ActionBar>
        </Form>
      </DataPanel>

      {hasConflicts && (
        <Alert
          type="error"
          showIcon
          message="存在目标文件重名或不安全路径"
          description="请修改规则并重新预览。已有目录不会被覆盖；全部安全后才允许生成计划。"
          className="nfc-page-alert"
        />
      )}

      {proposals !== null && (
        <DataPanel
          title="一级子文件改名预览"
          description="仅显示名称会变化的一级子文件；无匹配项表示无需重命名。"
          action={<span className="nfc-panel-count">{proposals.length} 个文件</span>}
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
                locale={{ emptyText: <Empty description="没有需要重命名的一级文件" /> }}
              />
            }
            mobile={
              <div className="nfc-mobile-record-list">
                {proposals.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有需要重命名的一级文件" />
                ) : proposals.map((item) => (
                  <article className="nfc-rename-proposal-mobile-card" key={item.source}>
                    <div className="nfc-mobile-record-heading">
                      <span className="nfc-kind-badge">rename</span>
                      <StatusBadge status={item.conflict ? 'failed' : 'completed'} label={item.conflict ? '冲突' : '安全'} />
                    </div>
                    <CodePath value={item.source} />
                    <ArrowRightOutlined />
                    <CodePath value={item.target} muted={item.conflict} />
                    {item.conflict && <p className="nfc-mobile-record-error">{item.conflict_reason}</p>}
                  </article>
                ))}
              </div>
            }
          />
        </DataPanel>
      )}
    </>
  );
};
