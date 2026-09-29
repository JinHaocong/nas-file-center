import React from 'react';
import {
  Alert,
  Button,
  Descriptions,
  Form,
  Input,
  Modal,
  Space,
  Tag,
  Typography,
  message,
} from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { scansApi } from '../../api/domain';
import { DedupeDiagnosticResponse } from '../../types/dedupe';
import { formatBytes } from '../../utils/format';
import { CodePath } from '../ui/CodePath';

interface DedupeDiagnosticModalProps {
  open: boolean;
  onClose: () => void;
  scanJobId?: number | null;
}

const diagnosisCopy: Record<
  DedupeDiagnosticResponse['diagnosis'],
  { title: string; type: 'success' | 'info' | 'warning' | 'error'; detail: string }
> = {
  EXACT_CONTENT_DUPLICATE: {
    title: '当前是两个独立的完全重复副本',
    type: 'success',
    detail: '文件大小和完整 SHA-256 均一致，并且不是同一个 device/inode。',
  },
  SAME_FILESYSTEM_ENTRY: {
    title: '两个路径指向同一个文件系统对象',
    type: 'info',
    detail: 'device/inode 相同，通常是 hardlink 或同一底层对象；不应当作两份独立可释放副本。',
  },
  DIFFERENT_SIZE: {
    title: '文件大小不同',
    type: 'warning',
    detail: '当前文件内容不可能完全一致，NAS File Center 不会把它们作为可执行重复副本。',
  },
  DIFFERENT_CONTENT: {
    title: '完整 SHA-256 不同',
    type: 'warning',
    detail: '当前内容不同，NAS File Center 的执行前校验会拒绝对这对文件做去重隔离。',
  },
  PATH_NOT_FOUND: {
    title: '至少一个路径当前不存在',
    type: 'warning',
    detail: '无法完成当前内容诊断；这也可能解释历史扫描与现在看到的结果不同。',
  },
  PATH_OUTSIDE_CONFIGURED_ROOTS: {
    title: '路径不在配置的安全根目录内',
    type: 'error',
    detail: '诊断不会读取白名单之外的文件。',
  },
  SYMLINK_UNSUPPORTED: {
    title: '检测到符号链接',
    type: 'warning',
    detail: '重复诊断和去重执行都不会把符号链接当作普通副本处理。',
  },
  NOT_REGULAR_FILE: {
    title: '至少一个路径不是普通文件',
    type: 'warning',
    detail: '目录或特殊文件不会进入普通重复文件处理链。',
  },
  INDETERMINATE: {
    title: '当前无法确定',
    type: 'warning',
    detail: '文件在读取哈希时发生变化或读取失败，请在文件稳定后重新诊断。',
  },
};

const reasonCopy: Record<string, string> = {
  PATH_OUTSIDE_SCAN_ROOTS: '不在该扫描的根目录内',
  QUARANTINE_EXCLUDED: '属于隔离区，扫描会排除',
  SYMLINK_EXCLUDED: '符号链接被排除',
  NON_REGULAR_FILE_EXCLUDED: '不是普通文件',
  NOT_IN_SNAPSHOT_FILTER_OR_SCAN_TIME_STATE: '未进入当时快照；扫描过滤条件或扫描时文件状态可能是原因',
  NOT_IN_SNAPSHOT_AT_SCAN_TIME: '当前路径没有出现在该扫描的重复快照中',
};

const PathFacts: React.FC<{
  label: string;
  item: DedupeDiagnosticResponse['paths'][number];
}> = ({ label, item }) => (
  <section className="nfc-dedupe-diagnostic-path">
    <div className="nfc-dedupe-diagnostic-path-heading">
      <strong>{label}</strong>
      {item.in_quarantine && <Tag>隔离区</Tag>}
      {item.is_symlink && <Tag color="orange">symlink</Tag>}
    </div>
    <CodePath value={item.requested_path} />
    <Descriptions
      size="small"
      column={2}
      items={[
        { key: 'exists', label: '存在', children: item.exists ? '是' : '否' },
        { key: 'regular', label: '普通文件', children: item.is_regular_file ? '是' : '否' },
        {
          key: 'size',
          label: '大小',
          children: item.size == null ? '—' : formatBytes(item.size),
        },
        {
          key: 'inode',
          label: 'Device / Inode',
          children:
            item.device == null || item.inode == null
              ? '—'
              : <span className="nfc-mono">{item.device} / {item.inode}</span>,
        },
        {
          key: 'mtime',
          label: 'mtime_ns',
          children: item.mtime_ns == null ? '—' : <span className="nfc-mono">{item.mtime_ns}</span>,
        },
        {
          key: 'hash',
          label: 'SHA-256',
          span: 2,
          children: item.sha256
            ? <Typography.Text className="nfc-mono" copyable={{ text: item.sha256 }}>{item.sha256}</Typography.Text>
            : <span className="nfc-table-meta">{item.hash_error || '—'}</span>,
        },
      ]}
    />
  </section>
);

export const DedupeDiagnosticModal: React.FC<DedupeDiagnosticModalProps> = ({
  open,
  onClose,
  scanJobId = null,
}) => {
  const [form] = Form.useForm();

  const mutation = useMutation({
    mutationFn: (values: { path_a: string; path_b: string }) =>
      scansApi.diagnosePair({
        path_a: values.path_a.trim(),
        path_b: values.path_b.trim(),
        scan_job_id: scanJobId ?? null,
      }),
    onError: (err: any) => {
      message.error(err.message || '重复诊断失败');
    },
  });

  const result = mutation.data;
  const diagnosis = result ? diagnosisCopy[result.diagnosis] : null;

  return (
    <Modal
      title="重复文件诊断"
      open={open}
      onCancel={onClose}
      footer={null}
      width={860}
      className="nfc-overlay-modal nfc-dedupe-diagnostic-modal"
      destroyOnClose
    >
      <div className="nfc-dedupe-diagnostic-stack">
        <Alert
          type="info"
          showIcon
          message="只读诊断"
          description={
            scanJobId
              ? `会比较当前文件内容，并解释它们在 Scan #${scanJobId} 快照中的状态；不会移动、隔离或删除文件。`
              : '会比较当前文件内容和文件系统身份；不会移动、隔离或删除文件。'
          }
        />

        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => mutation.mutate(values)}
        >
          <Form.Item
            name="path_a"
            label="文件 A"
            rules={[{ required: true, message: '请输入第一个完整文件路径' }]}
          >
            <Input placeholder="/data/..." />
          </Form.Item>
          <Form.Item
            name="path_b"
            label="文件 B"
            rules={[{ required: true, message: '请输入第二个完整文件路径' }]}
          >
            <Input placeholder="/data/..." />
          </Form.Item>
          <Space>
            <Button
              type="primary"
              htmlType="submit"
              icon={<SearchOutlined />}
              loading={mutation.isPending}
            >
              开始诊断
            </Button>
            {result && (
              <Button onClick={() => mutation.reset()}>
                清除结果
              </Button>
            )}
          </Space>
        </Form>

        {result && diagnosis && (
          <div className="nfc-dedupe-diagnostic-result">
            <Alert
              type={diagnosis.type}
              showIcon
              message={diagnosis.title}
              description={diagnosis.detail}
            />

            <div className="nfc-dedupe-diagnostic-path-grid">
              <PathFacts label="文件 A" item={result.paths[0]} />
              <PathFacts label="文件 B" item={result.paths[1]} />
            </div>

            <Descriptions
              bordered
              size="small"
              column={3}
              items={[
                {
                  key: 'same-entry',
                  label: '同一 inode',
                  children: result.same_filesystem_entry ? '是' : '否',
                },
                {
                  key: 'size-match',
                  label: '大小一致',
                  children: result.size_match == null ? '未知' : result.size_match ? '是' : '否',
                },
                {
                  key: 'hash-match',
                  label: 'SHA-256 一致',
                  children: result.sha256_match == null ? '未知' : result.sha256_match ? '是' : '否',
                },
              ]}
            />

            {result.scan && (
              <section className="nfc-dedupe-diagnostic-scan">
                <div className="nfc-dedupe-diagnostic-section-heading">
                  <div>
                    <strong>Scan #{result.scan.scan_job_id} 快照解释</strong>
                    <span>{result.scan.name}</span>
                  </div>
                  <Tag color={result.scan.same_duplicate_group ? 'green' : 'default'}>
                    {result.scan.same_duplicate_group ? '当时属于同一重复组' : '当时未记录为同一重复组'}
                  </Tag>
                </div>

                <div className="nfc-dedupe-diagnostic-scan-grid">
                  {result.scan.paths.map((pathInfo, index) => (
                    <div key={index} className="nfc-dedupe-diagnostic-scan-path">
                      <strong>文件 {index === 0 ? 'A' : 'B'}</strong>
                      <span>
                        快照成员：
                        {pathInfo.included_in_duplicate_snapshot ? '是' : '否'}
                      </span>
                      <span>
                        Scan Root：
                        {pathInfo.scan_root_index == null ? '—' : `#${pathInfo.scan_root_index}`}
                      </span>
                      {pathInfo.memberships.length > 0 && (
                        <span>
                          Group：
                          {pathInfo.memberships.map((entry) => `#${entry.group_id}`).join(', ')}
                        </span>
                      )}
                      {pathInfo.reasons.map((reason) => (
                        <span className="nfc-warning-text" key={reason}>
                          {reasonCopy[reason] || reason}
                        </span>
                      ))}
                    </div>
                  ))}
                </div>

                <div className="nfc-dedupe-diagnostic-filter-note">
                  <span>当时参数</span>
                  <span>min-size: {result.scan.fclones_args.min_size || '无'}</span>
                  <span>match-links: {result.scan.fclones_args.match_links ? '开启' : '关闭'}</span>
                  <span>
                    include patterns: {result.scan.fclones_args.name_patterns?.join(', ') || '无'}
                  </span>
                  <span>
                    exclude patterns: {result.scan.fclones_args.exclude_patterns?.join(', ') || '无'}
                  </span>
                </div>
              </section>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
};
