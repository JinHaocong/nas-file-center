import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { tasksApi } from '../../api/tasks';
import type { TaskEvent, TaskLogLevel } from '../../types/task';
import { formatDateTime } from '../../utils/format';
import { sanitizeContext } from '../../utils/sanitize';
import { useResponsive } from '../../hooks/useResponsive';
import { TASK_LOG_LEVEL_MAP } from './task_utils';
import { ConsoleSelect } from '../ui/ConsoleSelect';
import { ConsolePagination } from '../ui/ConsolePagination';
import { ConsoleEmpty } from '../ui/ConsoleEmpty';

interface Props { taskId: number; }

const levels = [
  { label: '全部级别', value: 'all' },
  { label: 'INFO', value: 'info' },
  { label: 'WARN', value: 'warning' },
  { label: 'ERROR', value: 'error' },
  { label: 'DEBUG', value: 'debug' },
];

export const TaskLogTable: React.FC<Props> = ({ taskId }) => {
  const { isMobile } = useResponsive();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [level, setLevel] = useState('all');
  const [expandedRowKeys, setExpandedRowKeys] = useState<readonly number[]>([]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['taskLogs', taskId, page, pageSize, level],
    queryFn: () => tasksApi.getTaskLogs(taskId, {
      page, pageSize, level: level === 'all' ? undefined : level,
    }),
  });

  const handleLevelChange = (val: string) => {
    setLevel(val);
    setPage(1);
    setExpandedRowKeys([]);
  };
  const changePage = (nextPage: number, nextSize: number) => {
    setPage(nextSize === pageSize ? nextPage : 1);
    setPageSize(nextSize);
    setExpandedRowKeys([]);
  };
  const toggleExpanded = (id: number) => {
    setExpandedRowKeys(keys => keys.includes(id) ? keys.filter(key => key !== id) : [...keys, id]);
  };

  const items: TaskEvent[] = isError ? [] : data?.items || [];
  const pagination = !isError && !isLoading && (data?.total || 0) > 0 && (
    <ConsolePagination page={page} pageSize={pageSize} total={data?.total || 0}
      pageSizes={[20, 50, 100]} onChange={changePage} />
  );

  const levelBadge = (lvl: TaskLogLevel) => {
    const config = TASK_LOG_LEVEL_MAP[lvl] || { color: 'default', label: lvl };
    return <span className={'nfc-v2-log-level is-' + lvl}>{config.label}</span>;
  };

  return (
    <section className="nfc-task-log-panel nfc-v2-task-log-panel">
      <header className="nfc-embedded-section-header nfc-v2-log-header">
        <div>
          <div className="nfc-embedded-section-kicker">Event stream</div>
          <h3>事件日志</h3>
        </div>
        <ConsoleSelect id="nfc-task-log-level" label="级别" value={level}
          onChange={handleLevelChange} options={levels} />
      </header>
      {isError ? (
        <div className="nfc-inline-error" role="alert">
          加载日志失败: {error instanceof Error ? error.message : '网络异常'}
          <button type="button" onClick={() => refetch()}>重新加载</button>
        </div>
      ) : isLoading ? (
        <div className="nfc-v2-task-loading" role="status">正在加载事件日志…</div>
      ) : items.length === 0 ? (
        <ConsoleEmpty title={level === 'all' ? '暂无事件日志' : '当前级别无匹配日志'} />
      ) : isMobile ? (
        <div className="nfc-task-log-mobile-list">
          {items.map(record => {
            const context = sanitizeContext(record.context);
            const hasContext = Boolean(context && Object.keys(context).length > 0);
            return (
              <article className="nfc-task-log-mobile-card" key={record.id}>
                <div className="nfc-task-log-mobile-topline">
                  {levelBadge(record.level)}
                  <time>{formatDateTime(record.timestamp)}</time>
                </div>
                <div className="nfc-task-log-mobile-event">{record.event_type}</div>
                <p>{record.message || '—'}</p>
                {hasContext && (
                  <details className="nfc-log-context">
                    <summary>查看上下文</summary>
                    <pre className="nfc-code-block">{JSON.stringify(context, null, 2)}</pre>
                  </details>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <div className="nfc-v2-log-table-scroll">
          <table className="nfc-v2-log-table">
            <thead><tr>
              <th scope="col">时间</th>
              <th scope="col">级别</th>
              <th scope="col">事件类型</th>
              <th scope="col">消息内容</th>
              <th scope="col">上下文</th>
            </tr></thead>
            <tbody>{items.map(record => {
              const context = sanitizeContext(record.context);
              const hasContext = Boolean(context && Object.keys(context).length > 0);
              const expanded = expandedRowKeys.includes(record.id);
              return (
                <React.Fragment key={record.id}>
                  <tr>
                    <td className="nfc-v2-task-date">{formatDateTime(record.timestamp)}</td>
                    <td>{levelBadge(record.level)}</td>
                    <td><code>{record.event_type}</code></td>
                    <td className="nfc-v2-log-message">{record.message || '—'}</td>
                    <td>
                      {hasContext ? (
                        <button type="button" aria-expanded={expanded}
                          aria-controls={'nfc-log-context-' + record.id}
                          className="nfc-v2-log-expand" onClick={() => toggleExpanded(record.id)}>
                          {expanded ? '收起' : '查看'}
                        </button>
                      ) : '—'}
                    </td>
                  </tr>
                  {hasContext && expanded && (
                    <tr className="nfc-v2-log-context-row">
                      <td colSpan={5} id={'nfc-log-context-' + record.id}>
                        <pre className="nfc-code-block">{JSON.stringify(context, null, 2)}</pre>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}</tbody>
          </table>
        </div>
      )}
      {pagination}
    </section>
  );
};
