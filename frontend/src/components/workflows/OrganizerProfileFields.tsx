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
  Collapse,
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
  const getPath = (...parts: (string | number)[]) => (prefix.length > 0 ? [...prefix, ...parts] : parts);
  const getAdvancedName = (rule: string, field: string) => getPath('advanced_rules', rule, field);

  // Watch fields for live preview
  const renameTpl = Form.useWatch(getName('rename_template'), form) ?? '{name}';
  const statTpl = Form.useWatch(getName('statistics_template'), form) ?? '[{images}P {videos}V {size}]';
  const numberingMode = Form.useWatch(getName('numbering_mode'), form) || 'none';
  const numStart = Form.useWatch(getName('numbering_start'), form) ?? 1;
  const numPadding = Form.useWatch(getName('numbering_padding'), form) ?? 3;
  const recursive = Form.useWatch(getName('recursive'), form) ?? false;
  const mtimeMode = Form.useWatch(getName('mtime_mode'), form) || 'none';
  const directoryDepthEnabled = Form.useWatch(getAdvancedName('directory_depth', 'enabled'), form) ?? false;
  const fileNumberingEnabled = Form.useWatch(getAdvancedName('file_numbering', 'enabled'), form) ?? false;
  const latestPrefixEnabled = Form.useWatch(getAdvancedName('latest_child_prefix', 'enabled'), form) ?? false;
  const wrapperCollapseEnabled = Form.useWatch(getAdvancedName('single_child_wrapper_collapse', 'enabled'), form) ?? false;
  const advancedRulesEnabled = directoryDepthEnabled || fileNumberingEnabled || latestPrefixEnabled || wrapperCollapseEnabled;

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
      className="nfc-organizer-profile-tabs"
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
                  <div className="nfc-organizer-template-help">
                    <div>
                      <Tag color="blue">{'{name}'}</Tag> 原目录名（已清理旧尾巴）&nbsp;
                      <Tag color="blue">{'{index}'}</Tag> 序列编号&nbsp;
                      <Tag color="blue">{'{statistics}'}</Tag> 统计标签字符串&nbsp;
                      <Tag color="blue">{'{size}'}</Tag> 容量统计（如 1.5GB）
                    </div>
                    <div className="nfc-organizer-template-help-row">
                      <Tag color="cyan">{'{images}'}</Tag> 图片数 (P)&nbsp;
                      <Tag color="cyan">{'{videos}'}</Tag> 视频数 (V)&nbsp;
                      <Tag color="cyan">{'{files}'}</Tag> 文件总数&nbsp;
                      <Tag color="cyan">{'{folders}'}</Tag> 子文件夹数
                    </div>
                    <div className="nfc-organizer-template-help-row">
                      <Tag color="purple">{'{?videos: {videos}V}'}</Tag> 条件语法（当视频数 &gt; 0 时显示，为 0 时自动省略）
                    </div>
                  </div>
                }
                type="info"
                showIcon
                icon={<InfoCircleOutlined />}
                className="nfc-organizer-template-alert"
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
                    <ThunderboltOutlined className="nfc-organizer-preview-icon" />
                    <span>实时命名渲染预览 (Live Preview)</span>
                  </Space>
                }
                className="nfc-organizer-live-preview"
              >
                <div className="nfc-organizer-live-preview-row">
                  <Text type="secondary" className="nfc-organizer-live-preview-label">
                    目标名称示例：
                  </Text>
                  <Text code strong className="nfc-organizer-live-preview-value">
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
              <Divider orientation="left" className="nfc-organizer-section-divider">
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
                    <InputNumber min={0} className="nfc-full-width-control" />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name={getName('numbering_padding')} label="补零位数 (Padding)">
                    <InputNumber min={1} max={10} className="nfc-full-width-control" />
                  </Form.Item>
                </Col>
              </Row>

              <Divider orientation="left" className="nfc-organizer-section-divider">
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
                    <InputNumber min={0} max={60} step={0.5} className="nfc-full-width-control" />
                  </Form.Item>
                </Col>
              </Row>
            </>
          ),
        },
        {
          key: 'advanced-rules',
          label: 'Advanced Rules',
          children: (
            <div className="nfc-organizer-advanced-rules">
              <Alert
                type="info"
                showIcon
                message="Advanced Rules 使用分阶段安全流程"
                description="高级规则默认关闭。启用后必须递归处理；Single-Child Wrapper Collapse 会先进入 Stage A 结构计划，完成后必须重新 Preview 才能生成 Stage B 重命名计划。"
                className="nfc-organizer-advanced-alert"
              />

              {advancedRulesEnabled && !recursive && (
                <Alert
                  type="error"
                  showIcon
                  message="启用 Advanced Rules 时必须开启递归处理子目录"
                  description="保存前请在“基础配置”中开启 recursive。后端也会 fail-closed 拒绝不一致配置。"
                  className="nfc-organizer-advanced-alert"
                />
              )}

              {latestPrefixEnabled && mtimeMode === 'ordered' && (
                <Alert
                  type="error"
                  showIcon
                  message="Latest-child prefix 与 ordered mtime 不兼容"
                  description="该组合会引入自诱导时间戳不稳定，V1 明确禁止。请关闭其中一项。"
                  className="nfc-organizer-advanced-alert"
                />
              )}

              <Collapse
                className="nfc-organizer-advanced-collapse"
                items={[
                  {
                    key: 'directory-depth',
                    label: 'Depth-aware directory rules',
                    children: (
                      <>
                        <Form.Item
                          name={getAdvancedName('directory_depth', 'enabled')}
                          label="从深层目录开始重命名"
                          valuePropName="checked"
                          rules={[{
                            validator: async (_, value) => {
                              if (value && !recursive) throw new Error('启用高级目录规则前必须开启 recursive');
                            },
                          }]}
                        >
                          <Switch />
                        </Form.Item>
                        <Form.Item
                          name={getAdvancedName('directory_depth', 'rename_from_depth')}
                          label="开始重命名深度"
                          extra="root=0，第一层目录=1；V1 保留 depth 1，最小值固定为 2。"
                        >
                          <InputNumber min={2} max={64} className="nfc-full-width-control" />
                        </Form.Item>
                      </>
                    ),
                  },
                  {
                    key: 'file-numbering',
                    label: 'Recursive file numbering',
                    children: (
                      <>
                        <Form.Item
                          name={getAdvancedName('file_numbering', 'enabled')}
                          label="递归文件编号"
                          valuePropName="checked"
                          rules={[{
                            validator: async (_, value) => {
                              if (value && !recursive) throw new Error('启用文件编号前必须开启 recursive');
                            },
                          }]}
                        >
                          <Switch />
                        </Form.Item>
                        <Row gutter={16}>
                          <Col xs={24} sm={12}>
                            <Form.Item name={getAdvancedName('file_numbering', 'start')} label="起始编号">
                              <InputNumber min={0} className="nfc-full-width-control" />
                            </Form.Item>
                          </Col>
                          <Col xs={24} sm={12}>
                            <Form.Item name={getAdvancedName('file_numbering', 'padding')} label="补零位数">
                              <InputNumber min={1} max={10} className="nfc-full-width-control" />
                            </Form.Item>
                          </Col>
                        </Row>
                        <Text type="secondary">V1 排序固定为 natural_name，扩展名大小写按原文件 preserve。</Text>
                      </>
                    ),
                  },
                  {
                    key: 'latest-prefix',
                    label: 'Latest-child prefix',
                    children: (
                      <>
                        <Form.Item
                          name={getAdvancedName('latest_child_prefix', 'enabled')}
                          label="为唯一最新子目录添加前缀"
                          valuePropName="checked"
                          rules={[{
                            validator: async (_, value) => {
                              if (value && !recursive) throw new Error('启用 latest-child prefix 前必须开启 recursive');
                              if (value && mtimeMode === 'ordered') throw new Error('latest-child prefix 与 ordered mtime 不能同时启用');
                            },
                          }]}
                        >
                          <Switch />
                        </Form.Item>
                        <Form.Item
                          name={getAdvancedName('latest_child_prefix', 'prefix')}
                          label="前缀"
                          rules={[{ required: latestPrefixEnabled, message: '请输入非空前缀' }]}
                          extra="时间权威固定为 mtime_ns；最高时间戳并列时 Preview 会产生阻塞冲突。"
                        >
                          <Input maxLength={64} placeholder="New " />
                        </Form.Item>
                      </>
                    ),
                  },
                  {
                    key: 'wrapper-collapse',
                    label: 'Collapse Single-Child Wrapper',
                    children: (
                      <>
                        <Form.Item
                          name={getAdvancedName('single_child_wrapper_collapse', 'enabled')}
                          label="折叠 depth 2 的单子目录 wrapper"
                          valuePropName="checked"
                          rules={[{
                            validator: async (_, value) => {
                              if (value && !recursive) throw new Error('启用 wrapper collapse 前必须开启 recursive');
                            },
                          }]}
                        >
                          <Switch />
                        </Form.Item>
                        <Alert
                          type="warning"
                          showIcon
                          message="结构变更仅通过 Stage A 执行"
                          description="只接受真实目录唯一子项；隐藏第二项、symlink、目标已存在或文件系统不支持都会阻塞。执行仍使用现有 MOVE → rmdir_empty 安全原语，不提供“立即执行”。"
                        />
                      </>
                    ),
                  },
                ]}
              />
            </div>
          ),
        },
      ]}
    />
  );
};
