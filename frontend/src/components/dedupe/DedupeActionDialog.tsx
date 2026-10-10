import React from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import type { DedupeStorageAction } from '../../types/dedupe';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';

export type DedupeNoticeKind =
  | 'generate' | 'preview_changed' | 'scan_not_found' | 'scan_not_completed' | 'empty_plan';

interface Props {
  kind: DedupeNoticeKind | null;
  storageAction: DedupeStorageAction;
  errorMessage?: string | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

/** Modal only requests confirmation; the page and backend retain all digest/lifecycle authority. */
export const DedupeActionDialog: React.FC<Props> = ({
  kind, storageAction, errorMessage, busy, onCancel, onConfirm,
}) => {
  const actionLabel = storageAction === 'quarantine'
    ? 'Quarantine' : storageAction === 'hardlink' ? 'Hardlink' : 'Reflink';
  const titles: Record<DedupeNoticeKind, string> = {
    generate: '确认生成 ' + actionLabel + ' 去重计划草案？',
    preview_changed: '预览校验失败 (PREVIEW_CHANGED)',
    scan_not_found: '扫描任务不存在 (DEDUPE_SCAN_NOT_FOUND)',
    scan_not_completed: '扫描任务尚未完成 (DEDUPE_SCAN_NOT_COMPLETED)',
    empty_plan: '无可用去重操作 (DEDUPE_EMPTY_PLAN)',
  };
  const confirmTexts: Record<DedupeNoticeKind, string> = {
    generate: '确认生成草案',
    preview_changed: '重新运行预览',
    scan_not_found: '返回扫描列表',
    scan_not_completed: '返回扫描详情',
    empty_plan: '确定',
  };
  return (
    <Dialog.Root open={kind !== null} onOpenChange={next => { if (!next && !busy) onCancel(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-advanced-dedupe-overlay" />
        <Dialog.Content className="nfc-overlay-modal nfc-v2-advanced-dedupe-dialog"
          onEscapeKeyDown={event => { if (busy) event.preventDefault(); }}
          onPointerDownOutside={event => event.preventDefault()}>
          <header className="nfc-v2-advanced-dedupe-dialog-header">
            <span className="nfc-v2-advanced-dedupe-dialog-icon">
              <ConsoleIcon name="shield-check" size={20} />
            </span>
            <Dialog.Title>{kind ? titles[kind] : '高级去重确认'}</Dialog.Title>
            <button type="button" aria-label="关闭高级去重确认窗口"
              disabled={busy} onClick={onCancel}>
              <ConsoleIcon name="x" size={18} />
            </button>
          </header>
          <Dialog.Description asChild>
            <div className="nfc-v2-advanced-dedupe-dialog-copy">
              {kind === 'generate' && (
                <>
                  <p>将提交当前权威预览摘要与 Storage Action（{actionLabel}），以原子方式创建执行计划草案。</p>
                  {storageAction === 'hardlink' && (
                    <p className="is-warning" role="note">
                      Hardlink 后两个路径共享同一个 inode，未来通过任一路径写入都会修改同一份文件内容。
                    </p>
                  )}
                  {storageAction === 'reflink' && (
                    <p className="is-info" role="note">
                      Reflink 使用独立 inode / Copy-on-Write，不是普通完整复制。
                    </p>
                  )}
                  <p>生成后仅创建 Draft 状态计划，不修改任何物理文件。
                    后续仍需完成 <strong>Freeze -&gt; Validate -&gt; Execute</strong> 流程。
                  </p>
                </>
              )}
              {kind === 'preview_changed' && (
                <p>检测到底层文件或打分状态已变化，权威摘要已失效。是否重新运行预览？</p>
              )}
              {kind === 'scan_not_found' && (
                <p>关联的底层扫描任务已不可用，当前去重计划草案无法生成。</p>
              )}
              {kind === 'scan_not_completed' && (
                <p>扫描任务当前未处于完成状态，请等待扫描完成后再生成去重计划。</p>
              )}
              {kind === 'empty_plan' && <p>当前配置下未产生任何可执行的去重操作。</p>}
              {kind !== 'generate' && errorMessage && (
                <p className="nfc-v2-advanced-dedupe-error" role="alert">{errorMessage}</p>
              )}
            </div>
          </Dialog.Description>
          <div className="nfc-v2-advanced-dedupe-dialog-actions">
            {kind !== 'empty_plan' && (
              <ConsoleButton disabled={busy} onClick={onCancel}>取消</ConsoleButton>
            )}
            <ConsoleButton variant="primary" disabled={!kind} loading={busy} onClick={onConfirm}>
              {kind ? confirmTexts[kind] : '确定'}
            </ConsoleButton>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
