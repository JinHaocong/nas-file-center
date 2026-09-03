import React, { useEffect, useState, useMemo } from 'react';
import {
  Modal,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
  Space,
  Typography,
  Alert,
  Divider,
  Tabs,
  Tag,
  Card,
  Row,
  Col,
} from 'antd';
import { InfoCircleOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { OrganizerProfile } from '../../types';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { renderTemplate } from '../../utils/templateRenderer';

const { Text } = Typography;

interface ProfileFormModalProps {
  open: boolean;
  editingProfile: OrganizerProfile | null;
  onCancel: () => void;
  onSubmit: (values: Partial<OrganizerProfile>) => Promise<void>;
  loading?: boolean;
}

export const ProfileFormModal: React.FC<ProfileFormModalProps> = ({
  open,
  editingProfile,
  onCancel,
  onSubmit,
  loading = false,
}) => {
  const [form] = Form.useForm();
  const [renameTpl, setRenameTpl] = useState<string>('{name} {statistics}');
  const [statTpl, setStatTpl] = useState<string>('[{images}P{?videos: {videos}V} {size}]');
  const [numberingMode, setNumberingMode] = useState<string>('none');
  const [numStart, setNumStart] = useState<number>(1);
  const [numPadding, setNumPadding] = useState<number>(3);

  useEffect(() => {
    if (open) {
      if (editingProfile) {
        form.setFieldsValue({
          name: editingProfile.name,
          description: editingProfile.description || '',
          root: editingProfile.root || '',
          recursive: editingProfile.recursive || false,
          image_extensions: editingProfile.image_extensions || ['jpg', 'jpeg', 'png', 'webp'],
          video_extensions: editingProfile.video_extensions || ['mp4', 'mov', 'mkv'],
          rename_template: editingProfile.rename_template || '{name} {statistics}',
          statistics_template: editingProfile.statistics_template || '[{images}P{?videos: {videos}V} {size}]',
          preserve_tags: editingProfile.preserve_tags ?? [],
          cleanup_patterns: editingProfile.cleanup_patterns || [],
          numbering_mode: editingProfile.numbering_mode || 'none',
          numbering_start: editingProfile.numbering_start ?? 1,
          numbering_padding: editingProfile.numbering_padding ?? 3,
          mtime_mode: editingProfile.mtime_mode || 'none',
          mtime_delay_seconds: editingProfile.mtime_delay_seconds ?? 2.0,
        });
        setRenameTpl(editingProfile.rename_template || '{name} {statistics}');
        setStatTpl(editingProfile.statistics_template || '[{images}P{?videos: {videos}V} {size}]');
        setNumberingMode(editingProfile.numbering_mode || 'none');
        setNumStart(editingProfile.numbering_start ?? 1);
        setNumPadding(editingProfile.numbering_padding ?? 3);
      } else {
        form.resetFields();
        form.setFieldsValue({
          name: '',
          description: '',
          root: '',
          recursive: false,
          image_extensions: ['jpg', 'jpeg', 'png', 'webp'],
          video_extensions: ['mp4', 'mkv', 'mov'],
          rename_template: '{name}',
          statistics_template: '[{images}P {videos}V {size}]',
          preserve_tags: [],
          cleanup_patterns: [],
          numbering_mode: 'none',
          numbering_start: 1,
          numbering_padding: 3,
          mtime_mode: 'none',
          mtime_delay_seconds: 2.0,
        });
        setRenameTpl('{name}');
        setStatTpl('[{images}P {videos}V {size}]');
        setNumberingMode('none');
        setNumStart(1);
        setNumPadding(3);
      }
    }
  }, [open, editingProfile, form]);

  // Real-time client mock render of templates matching backend semantics
  const previewExample = useMemo(() => {
    const mockImages = 120;
    const mockVideos = 3;
    const mockSize = '8.42GB';
    const mockName = '示例目录名称';
    const mockFiles = 123;
    const mockFolders = 0;
    const mockIndex = numberingMode === 'sequential' ? String(numStart).padStart(numPadding, '0') : '';

    const statContext = {
      images: mockImages,
      videos: mockVideos,
      size: mockSize,
      files: mockFiles,
      files_count: mockFiles,
      folders: mockFolders,
      name: mockName,
    };
    const renderedStat = renderTemplate(statTpl, statContext);

    const renameContext = {
      name: mockName,
      index: mockIndex,
      statistics: renderedStat,
      images: mockImages,
      videos: mockVideos,
      size: mockSize,
      files: mockFiles,
      files_count: mockFiles,
      folders: mockFolders,
      parent: '父级目录',
      extension: '',
    };
    return renderTemplate(renameTpl, renameContext);
  }, [renameTpl, statTpl, numberingMode, numStart, numPadding]);

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      await onSubmit(values);
    } catch {
      // Form validation failed
    }
  };

  return (
    <Modal
      title={editingProfile ? `编辑方案: ${editingProfile.name}` : '新建整理方案'}
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      confirmLoading={loading}
      width={720}
      destroyOnClose
      okText="保存方案"
      cancelText="取消"
    >
      <Form
        form={form}
        layout="vertical"
        onValuesChange={(changed) => {
          if ('rename_template' in changed) setRenameTpl(changed.rename_template || '');
          if ('statistics_template' in changed) setStatTpl(changed.statistics_template || '');
          if ('numbering_mode' in changed) setNumberingMode(changed.numbering_mode);
          if ('numbering_start' in changed) setNumStart(changed.numbering_start ?? 1);
          if ('numbering_padding' in changed) setNumPadding(changed.numbering_padding ?? 3);
        }}
      >
        <Tabs
          defaultActiveKey="basic"
          items={[
            {
              key: 'basic',
              label: '基础配置',
              children: (
                <>
                  <Form.Item
                    name="name"
                    label="方案名称"
                    rules={[{ required: true, message: '请输入方案名称' }]}
                  >
                    <Input placeholder="例如：相册归档整理 / 壁纸目录整理" />
                  </Form.Item>

                  <Form.Item name="description" label="方案描述">
                    <Input.TextArea rows={2} placeholder="简要描述该方案的适用目录及规范规则..." />
                  </Form.Item>

                  <Form.Item
                    name="root"
                    label="默认整理根目录"
                    extra="可选。指定后进入该方案将默认载入此路径，必须在 ALLOWED_ROOTS 白名单内。"
                  >
                    <DirectoryPicker multiple={false} placeholder="点击浏览或手动输入默认根目录..." />
                  </Form.Item>

                  <Form.Item name="recursive" label="递归处理子目录" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                </>
              ),
            },
            {
              key: 'template',
              label: '命名模板',
              children: (
                <>
                  <Alert
                    message="模板可用变量说明"
                    description={
                      <div style={{ fontSize: 13, lineHeight: '22px' }}>
                        <div>
                          <Tag color="blue">{'{name}'}</Tag> 原目录名（已清理旧尾巴）&nbsp;
                          <Tag color="blue">{'{index}'}</Tag> 序列编号&nbsp;
                          <Tag color="blue">{'{statistics}'}</Tag> 统计标签字符串&nbsp;
                          <Tag color="blue">{'{size}'}</Tag> 容量统计（如 1.5GB）
                        </div>
                        <div style={{ marginTop: 4 }}>
                          <Tag color="cyan">{'{images}'}</Tag> 图片数 (P)&nbsp;
                          <Tag color="cyan">{'{videos}'}</Tag> 视频数 (V)&nbsp;
                          <Tag color="cyan">{'{files}'}</Tag> 文件总数&nbsp;
                          <Tag color="cyan">{'{folders}'}</Tag> 子文件夹数
                        </div>
                        <div style={{ marginTop: 4 }}>
                          <Tag color="purple">{'{?videos: {videos}V}'}</Tag> 条件语法（当视频数 &gt; 0 时显示，为 0 时自动省略）
                        </div>
                      </div>
                    }
                    type="info"
                    showIcon
                    icon={<InfoCircleOutlined />}
                    style={{ marginBottom: 16 }}
                  />

                  <Form.Item
                    name="statistics_template"
                    label="统计标签模板 (statistics_template)"
                    rules={[{ required: true, message: '请输入统计标签模板' }]}
                    extra="生成 {statistics} 占位符的内容。例如：[{images}P {videos}V {size}]"
                  >
                    <Input placeholder="[{images}P {videos}V {size}]" />
                  </Form.Item>

                  <Form.Item
                    name="rename_template"
                    label="目录重命名模板 (rename_template)"
                    rules={[{ required: true, message: '请输入重命名模板' }]}
                    extra="最终目录新名称。例如：{name} {statistics} 或 {index} {name} {statistics}"
                  >
                    <Input placeholder="{name} {statistics}" />
                  </Form.Item>

                  <Card
                    size="small"
                    title={
                      <Space>
                        <ThunderboltOutlined style={{ color: '#faad14' }} />
                        <span>实时命名渲染预览 (Live Preview)</span>
                      </Space>
                    }
                    style={{ background: '#f8fafc', borderColor: '#e2e8f0', marginBottom: 8 }}
                  >
                    <div style={{ padding: '4px 0' }}>
                      <Text type="secondary" style={{ marginRight: 8 }}>
                        目标名称示例：
                      </Text>
                      <Text code strong style={{ fontSize: 14, color: '#1677ff' }}>
                        {previewExample}
                      </Text>
                    </div>
                  </Card>
                </>
              ),
            },
            {
              key: 'rules',
              label: '媒体与清理规则',
              children: (
                <>
                  <Form.Item
                    name="image_extensions"
                    label="图片扩展名识别"
                    extra="匹配为图片的文件后缀，支持多选或直接输入回车添加"
                  >
                    <Select
                      mode="tags"
                      tokenSeparators={[',', ' ']}
                      placeholder="如 jpg, png, webp"
                    />
                  </Form.Item>

                  <Form.Item
                    name="video_extensions"
                    label="视频扩展名识别"
                    extra="匹配为视频的文件后缀，支持多选或直接输入回车添加"
                  >
                    <Select
                      mode="tags"
                      tokenSeparators={[',', ' ']}
                      placeholder="如 mp4, mov, mkv, mts"
                    />
                  </Form.Item>

                  <Form.Item
                    name="preserve_tags"
                    label="业务保留标签 (Preserve Tags)"
                    extra="原名称中若包含这些标签，重命名后必须继续保留，支持多个"
                  >
                    <Select
                      mode="tags"
                      tokenSeparators={[',', ' ']}
                      placeholder="例如：[精选], [待整理]"
                    />
                  </Form.Item>

                  <Form.Item
                    name="cleanup_patterns"
                    label="旧统计尾巴清理正则 (Cleanup Patterns)"
                    extra="用于在重新统计前剥离旧的后缀正则。支持最多 10 条有效正则"
                  >
                    <Select
                      mode="tags"
                      tokenSeparators={['\n']}
                      placeholder="输入正则表达式并回车"
                    />
                  </Form.Item>
                </>
              ),
            },
            {
              key: 'advanced',
              label: '编号与时间戳 (mtime)',
              children: (
                <>
                  <Divider orientation="left" style={{ margin: '8px 0 16px' }}>
                    序列编号设置
                  </Divider>
                  <Row gutter={16}>
                    <Col span={8}>
                      <Form.Item name="numbering_mode" label="编号模式">
                        <Select
                          options={[
                            { value: 'none', label: '不自动编号 (none)' },
                            { value: 'sequential', label: '连续自然编号 (sequential)' },
                          ]}
                        />
                      </Form.Item>
                    </Col>
                    <Col span={8}>
                      <Form.Item name="numbering_start" label="起始编号">
                        <InputNumber min={0} style={{ width: '100%' }} />
                      </Form.Item>
                    </Col>
                    <Col span={8}>
                      <Form.Item name="numbering_padding" label="补零位数 (Padding)">
                        <InputNumber min={1} max={10} style={{ width: '100%' }} />
                      </Form.Item>
                    </Col>
                  </Row>

                  <Divider orientation="left" style={{ margin: '8px 0 16px' }}>
                    时间戳 (mtime) 刷新规则
                  </Divider>
                  <Row gutter={16}>
                    <Col span={12}>
                      <Form.Item name="mtime_mode" label="mtime 刷新模式">
                        <Select
                          options={[
                            { value: 'none', label: '不更新时间戳 (none)' },
                            { value: 'ordered', label: '按整理目标顺序刷新 (ordered)' },
                          ]}
                        />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item name="mtime_delay_seconds" label="排序刷新间隔秒数">
                        <InputNumber min={0} max={60} step={0.5} style={{ width: '100%' }} />
                      </Form.Item>
                    </Col>
                  </Row>
                </>
              ),
            },
          ]}
        />
      </Form>
    </Modal>
  );
};
