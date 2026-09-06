import React, { useMemo } from 'react';
import {
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
import { DirectoryPicker } from '../DirectoryPicker';
import { renderTemplate } from '../../utils/templateRenderer';
import { formatBytes } from '../../utils/format';

const { Text } = Typography;

export interface OrganizerProfileFieldsProps {
  includeRoot?: boolean;
  prefix?: (string | number)[];
}

export const OrganizerProfileFields: React.FC<OrganizerProfileFieldsProps> = ({
  includeRoot = true,
  prefix = [],
}) => {
  const form = Form.useFormInstance();

  const getName = (name: string | number) => (prefix.length > 0 ? [...prefix, name] : name);

  // Watch fields for live preview
  const renameTpl = Form.useWatch(getName('rename_template'), form) ?? '{name}';
  const statTpl = Form.useWatch(getName('statistics_template'), form) ?? '[{images}P {videos}V {size}]';
  const numberingMode = Form.useWatch(getName('numbering_mode'), form) || 'none';
  const numStart = Form.useWatch(getName('numbering_start'), form) ?? 1;
  const numPadding = Form.useWatch(getName('numbering_padding'), form) ?? 3;

  const previewExample = useMemo(() => {
    const mockImages = 120;
    const mockVideos = 3;
    const mockSize = formatBytes(9040842752);
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

  return (
    <Tabs
      defaultActiveKey="basic"
      items={[
        {
          key: 'basic',
          label: '基础配置',
          children: (
            <>
              <Form.Item
                name={getName('name')}
                label="方案/快照名称"
                rules={[{ required: true, message: '请输入方案名称' }]}
              >
                <Input placeholder="例如：相册归档整理 / 壁纸目录整理" />
              </Form.Item>

              <Form.Item name={getName('description')} label="描述说明">
                <Input.TextArea rows={2} placeholder="简要描述该整理规则的适用场景及规范..." />
              </Form.Item>

              {includeRoot && (
                <Form.Item
                  name={getName('root')}
                  label="默认整理根目录"
                  extra="可选。指定后进入该方案将默认载入此路径，必须在 ALLOWED_ROOTS 白名单内。"
                >
                  <DirectoryPicker multiple={false} placeholder="点击浏览或手动输入默认根目录..." />
                </Form.Item>
              )}

              <Form.Item name={getName('recursive')} label="递归处理子目录" valuePropName="checked">
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
                name={getName('statistics_template')}
                label="统计标签模板 (statistics_template)"
                rules={[{ required: true, message: '请输入统计标签模板' }]}
                extra="生成 {statistics} 占位符的内容。例如：[{images}P {videos}V {size}]"
              >
                <Input placeholder="[{images}P {videos}V {size}]" />
              </Form.Item>

              <Form.Item
                name={getName('rename_template')}
                label="目录重命名模板 (rename_template)"
                rules={[{ required: true, message: '请输入重命名模板' }]}
                extra="最终目录新名称。例如：{name} 或 {index} {name} {statistics}"
              >
                <Input placeholder="{name}" />
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
                name={getName('image_extensions')}
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
                name={getName('video_extensions')}
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
                name={getName('preserve_tags')}
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
                name={getName('cleanup_patterns')}
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
                  <Form.Item name={getName('numbering_mode')} label="编号模式">
                    <Select
                      options={[
                        { value: 'none', label: '不自动编号 (none)' },
                        { value: 'sequential', label: '连续自然编号 (sequential)' },
                      ]}
                    />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name={getName('numbering_start')} label="起始编号">
                    <InputNumber min={0} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name={getName('numbering_padding')} label="补零位数 (Padding)">
                    <InputNumber min={1} max={10} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>

              <Divider orientation="left" style={{ margin: '8px 0 16px' }}>
                时间戳 (mtime) 刷新规则
              </Divider>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name={getName('mtime_mode')} label="mtime 刷新模式">
                    <Select
                      options={[
                        { value: 'none', label: '不更新时间戳 (none)' },
                        { value: 'ordered', label: '按整理目标顺序刷新 (ordered)' },
                      ]}
                    />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name={getName('mtime_delay_seconds')} label="排序刷新间隔秒数">
                    <InputNumber min={0} max={60} step={0.5} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
            </>
          ),
        },
      ]}
    />
  );
};
