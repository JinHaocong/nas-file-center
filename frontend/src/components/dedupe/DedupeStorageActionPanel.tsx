import React from 'react';
import type {
  DedupeStorageAction, StorageOptimizationCapabilitiesResponse,
} from '../../types/dedupe';
import { CodePath } from '../ui/CodePath';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';

interface DiagnosticPair {
  keepPath: string;
  sourcePath: string;
  keepParent: string;
  sourceParent: string;
}

interface Props {
  value: DedupeStorageAction;
  onChange: (value: DedupeStorageAction) => void;
  disabled?: boolean;
  isAdmin: boolean;
  diagnosticPair?: DiagnosticPair | null;
  capabilityData?: StorageOptimizationCapabilitiesResponse | null;
  capabilityLoading?: boolean;
  capabilityError?: string | null;
  onProbeCapabilities: () => void;
}

const CapabilityBadge: React.FC<{ state?: string }> = ({ state }) => {
  const label = state === 'supported' ? 'SUPPORTED'
    : state === 'unsupported' ? 'UNSUPPORTED'
    : state === 'unknown' ? 'UNKNOWN' : 'NOT CHECKED';
  return (
    <span className={'nfc-v2-capability-badge is-' +
      (state === 'supported' || state === 'unsupported' || state === 'unknown' ? state : 'unchecked')}>
      {label}
    </span>
  );
};

const CapabilityFact: React.FC<{ label: string; children: React.ReactNode }> =
  ({ label, children }) => <div><dt>{label}</dt><dd>{children}</dd></div>;

/** Only an explicit click invokes onProbeCapabilities: Preview/Generate never probes. */
export const DedupeStorageActionPanel: React.FC<Props> = ({
  value, onChange, disabled = false, isAdmin, diagnosticPair,
  capabilityData, capabilityLoading = false, capabilityError, onProbeCapabilities,
}) => {
  const instanceId = React.useId();
  const selectedCapability =
    value === 'hardlink' || value === 'reflink' ? capabilityData?.[value] : undefined;
  const chooseAction = (next: DedupeStorageAction) => {
    if (disabled || (next !== 'quarantine' && !isAdmin)) return;
    onChange(next);
  };

  return (
    <section className="nfc-storage-action-panel nfc-v2-storage-action" aria-label="存储动作配置">
      <div className="nfc-storage-action-header">
        <div>
          <strong>存储动作 (Storage Action)</strong>
          <div className="nfc-table-meta">
            默认保持 Quarantine。Hardlink / Reflink 必须显式选择，并绑定到新的 Preview digest。
          </div>
        </div>
        <span className={'nfc-v2-storage-action-tag is-' + value}>{value.toUpperCase()}</span>
      </div>

      <fieldset className="nfc-storage-action-options nfc-v2-storage-action-options" disabled={disabled}>
        <legend className="nfc-v2-sr-only">选择存储动作</legend>
        {(['quarantine', 'hardlink', 'reflink'] as const).map(action => (
          <label key={action} className={'nfc-v2-storage-action-option' +
            (value === action ? ' is-selected' : '')}>
            <input type="radio" name={instanceId + '-storage-action'} value={action}
              checked={value === action} disabled={disabled || (action !== 'quarantine' && !isAdmin)}
              onChange={() => chooseAction(action)} />
            <span>{action === 'quarantine' ? 'Quarantine' : action === 'hardlink' ? 'Hardlink' : 'Reflink'}</span>
          </label>
        ))}
      </fieldset>

      {!isAdmin && (
        <div className="nfc-v2-storage-action-note" role="note">
          <ConsoleIcon name="shield-check" size={17} />
          <div>
            <strong>Hardlink / Reflink 仅管理员可生成、冻结、验证和执行</strong>
            <p>普通用户仍可使用现有 Quarantine 去重流程；优化动作不会自动启用。</p>
          </div>
        </div>
      )}

      {value === 'hardlink' && (
        <div className="nfc-v2-storage-action-note is-warning" role="note">
          <ConsoleIcon name="shield-check" size={17} />
          <div><strong>Hardlink 会改变未来写入语义</strong>
            <p>Hardlink 后两个路径共享同一个 inode，未来通过任一路径写入都会修改同一份文件内容。</p>
          </div>
        </div>
      )}

      {value === 'reflink' && (
        <div className="nfc-v2-storage-action-note" role="note">
          <ConsoleIcon name="file-check" size={17} />
          <div><strong>Reflink 是独立 inode 的 Copy-on-Write</strong>
            <p>Reflink 会创建独立 inode，并使用 Copy-on-Write（写时复制）；它不是普通完整复制。</p>
          </div>
        </div>
      )}

      {(value === 'hardlink' || value === 'reflink') && isAdmin && (
        <section className="nfc-storage-capability-diagnostics nfc-v2-storage-capability"
          aria-label="运行时能力诊断">
          <header className="nfc-storage-capability-heading">
            <div className="nfc-v2-storage-capability-title">
              <ConsoleIcon name="shield-check" size={17} />
              <strong>运行时能力诊断</strong>
              <CapabilityBadge state={selectedCapability?.capability} />
            </div>
            <ConsoleButton size="sm" leadingIcon={<ConsoleIcon name="search" size={16} />}
              onClick={() => {
                if (!disabled && !capabilityLoading && diagnosticPair) onProbeCapabilities();
              }}
              loading={capabilityLoading} disabled={disabled || !diagnosticPair || capabilityLoading}>
              显式探测当前路径对
            </ConsoleButton>
          </header>
          <p className="nfc-v2-storage-capability-warning">
            能力探测会创建并清理 NFC 私有 disposable probe 文件，因此不会在 Preview / Generate 中自动运行。
            Validate / Worker Execute 仍会对实际路径重新验证能力。
          </p>
          {diagnosticPair ? (
            <dl className="nfc-detail-descriptions nfc-v2-storage-capability-facts">
              <CapabilityFact label="KEEP parent (probe source)">
                <CodePath value={diagnosticPair.keepParent} />
              </CapabilityFact>
              <CapabilityFact label="SOURCE parent (publication destination)">
                <CodePath value={diagnosticPair.sourceParent} />
              </CapabilityFact>
              {selectedCapability && (
                <>
                  <CapabilityFact label="capability">
                    <CapabilityBadge state={selectedCapability.capability} />
                  </CapabilityFact>
                  <CapabilityFact label="reason"><code>{selectedCapability.reason}</code></CapabilityFact>
                  <CapabilityFact label="KEEP parent dev / inode">
                    <code>{selectedCapability.source_parent_device ?? '—'} / {selectedCapability.source_parent_inode ?? '—'}</code>
                  </CapabilityFact>
                  <CapabilityFact label="SOURCE parent dev / inode">
                    <code>{selectedCapability.parent_device ?? '—'} / {selectedCapability.parent_inode ?? '—'}</code>
                  </CapabilityFact>
                </>
              )}
            </dl>
          ) : (
            <div className="nfc-v2-storage-action-note" role="note">
              <ConsoleIcon name="file-search" size={17} />
              <div><strong>先运行所选 Storage Action 的 Preview</strong>
                <p>Preview 后会从当前候选中选择一个实际 KEEP-parent → SOURCE-parent 路径对用于显式诊断。</p>
              </div>
            </div>
          )}
          {capabilityError && (
            <div className="nfc-v2-storage-action-note is-error" role="alert">
              <ConsoleIcon name="x" size={17} />
              <div><strong>能力探测失败</strong><p>{capabilityError}</p></div>
            </div>
          )}
        </section>
      )}
    </section>
  );
};
