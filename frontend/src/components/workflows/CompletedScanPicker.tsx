import React, { useEffect, useId, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { scansApi } from '../../api/domain';
import type { ScanJob } from '../../types';
import { formatBytes, formatDateTime } from '../../utils/format';
import { formatScanRootLabel } from '../../utils/dedupePreview';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { StatusBadge } from '../ui/StatusBadge';
import { useConsoleToast } from '../ui/ConsoleToast';
import { parseCompletedScanJobId, verifiedCompletedScanId, completedScanJobs } from '../../utils/completedScanSelection';

interface Props {
  value?: number;
  onChange: (scanJobId?: number) => void;
  disabled?: boolean;
}

/** An ID is eligible for dedupe only after a completed ScanJob is identified. */
export const isValidCompletedScanId = (value: string): boolean =>
  parseCompletedScanJobId(value) !== null;

export const CompletedScanPicker: React.FC<Props> = ({
  value, onChange, disabled = false,
}) => {
  const labelId = useId();
  const toast = useConsoleToast();
  const [manualMode, setManualMode] = useState(false);
  const [manualInputId, setManualInputId] = useState(value ? String(value) : '');
  const [scanSearch, setScanSearch] = useState('');
  const [verifying, setVerifying] = useState(false);
  const [manualScanDetail, setManualScanDetail] = useState<ScanJob | null>(null);
  const verificationGeneration = useRef(0);
  const verificationInFlight = useRef(false);

  useEffect(() => {
    verificationGeneration.current += 1;
    setManualScanDetail(current => current?.id === value ? current : null);
  }, [value, disabled]);

  const { data: scansData, isLoading, isError } = useQuery({
    queryKey: ['completedScansList'],
    queryFn: async () => {
      const res = await scansApi.listScans(1, 500);
      return res.items || [];
    },
  });

  const completedScans = completedScanJobs(scansData || []);
  const selectedScanFromList = completedScans.find((scan: ScanJob) => scan.id === value);
  const { data: valueScanDetail } = useQuery({
    queryKey: ['scanDetailPicker', value],
    queryFn: () => scansApi.getScanDetail(value!),
    enabled: Number.isSafeInteger(value) && Number(value) > 0 && !selectedScanFromList,
  });
  const activeScan = selectedScanFromList ||
    (manualScanDetail && manualScanDetail.id === value && manualScanDetail.status === 'completed'
      ? manualScanDetail : null) ||
    (valueScanDetail && valueScanDetail.id === value && valueScanDetail.status === 'completed'
      ? valueScanDetail : null);

  const filteredScans = completedScans.filter(scan =>
    ('#' + scan.id + ' ' + scan.name).toLowerCase().includes(scanSearch.trim().toLowerCase())
  );

  const handleVerifyAndApply = async () => {
    if (disabled || verificationInFlight.current) return;
    const requested = manualInputId.trim();
    const parsedId = parseCompletedScanJobId(requested);
    if (parsedId === null) {
      onChange(undefined);
      setManualScanDetail(null);
      toast.info('请输入有效的 Scan Job ID');
      return;
    }
    const id = parsedId;
    const generation = ++verificationGeneration.current;
    verificationInFlight.current = true;
    setVerifying(true);
    try {
      const detail = await scansApi.getScanDetail(id);
      if (generation !== verificationGeneration.current) return;
      if (verifiedCompletedScanId(id, detail) !== null) {
        setManualScanDetail(detail);
        onChange(detail.id);
        toast.success('已确认扫描任务 #' + detail.id + ' 处于已完成状态');
      } else {
        onChange(undefined);
        setManualScanDetail(null);
        toast.error(
          '扫描任务 #' + id + ' 状态为 ' + (detail?.status || '未知') +
          '，只有已完成 (completed) 的扫描才可进行去重'
        );
      }
    } catch {
      if (generation !== verificationGeneration.current) return;
      onChange(undefined);
      setManualScanDetail(null);
      toast.error('扫描任务 #' + id + ' 查询失败或不存在');
    } finally {
      verificationInFlight.current = false;
      setVerifying(false);
    }
  };

  const onSelect = (selectedId: string) => {
    if (disabled) return;
    const scan = completedScans.find(item => String(item.id) === selectedId);
    verificationGeneration.current += 1;
    setManualScanDetail(null);
    setManualInputId(scan ? String(scan.id) : '');
    onChange(scan?.id);
  };

  return (
    <div className="nfc-completed-scan-picker nfc-v2-completed-scan-picker">
      <div className="nfc-completed-scan-picker-controls">
        {!manualMode ? (
          <div className="nfc-v2-scan-choice">
            <label htmlFor={labelId + '-search'}>搜索已完成扫描</label>
            <input id={labelId + '-search'} type="search" value={scanSearch}
              placeholder="按任务名称或 ID 筛选"
              disabled={disabled || isLoading}
              onChange={event => setScanSearch(event.target.value)} />
            <label htmlFor={labelId + '-select'}>选择已完成的扫描任务</label>
            <select id={labelId + '-select'}
              value={value != null ? String(value) : ''} disabled={disabled || isLoading}
              className="nfc-completed-scan-select"
              onChange={event => onSelect(event.target.value)}>
              <option value="">请选择已完成的扫描任务...</option>
              {value != null && activeScan && !filteredScans.some(s => s.id === value) && (
                <option value={value}>
                  #{activeScan.id} - {activeScan.name}（当前已选择）
                </option>
              )}
              {filteredScans.map(scan => (
                <option key={scan.id} value={scan.id}>
                  #{scan.id} - {scan.name} ({scan.total_groups} 组重复, 可释放 {formatBytes(scan.reclaimable_bytes)})
                </option>
              ))}
            </select>
            {isLoading && <small role="status">正在读取已完成扫描…</small>}
            {isError && <small role="alert">扫描任务列表读取失败，可切换为手动 ID 验证。</small>}
          </div>
        ) : (
          <div className="nfc-completed-scan-manual">
            <label htmlFor={labelId + '-id'}>Scan Job ID</label>
            <input id={labelId + '-id'} type="text" inputMode="numeric"
              pattern="[1-9][0-9]*" autoComplete="off"
              className="nfc-completed-scan-id-input"
              value={manualInputId} disabled={disabled || verifying}
              placeholder="输入 Scan Job ID"
              onChange={event => {
                verificationGeneration.current += 1;
                setManualInputId(event.target.value);
                if (!event.target.value.trim()) {
                  onChange(undefined);
                  setManualScanDetail(null);
                }
              }}
              onKeyDown={event => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  void handleVerifyAndApply();
                }
              }} />
            <ConsoleButton variant="primary" size="sm"
              leadingIcon={<ConsoleIcon name="check" size={16} />}
              loading={verifying} disabled={disabled || !isValidCompletedScanId(manualInputId.trim())}
              onClick={() => { void handleVerifyAndApply(); }}>
              验证
            </ConsoleButton>
          </div>
        )}
        <ConsoleButton variant="ghost" size="sm"
          leadingIcon={<ConsoleIcon name={manualMode ? 'list-checks' : 'pencil'} size={16} />}
          onClick={() => {
            verificationGeneration.current += 1;
            setManualMode(!manualMode);
            setManualInputId(value ? String(value) : '');
          }}
          disabled={disabled || verifying}>
          {manualMode ? '切换为扫描列表' : '手动输入 ID'}
        </ConsoleButton>
      </div>

      {activeScan && (
        <div className="nfc-completed-scan-summary" aria-label="已选扫描任务信息">
          <StatusBadge status="completed" label={activeScan.status} />
          <span className="nfc-completed-scan-id">Scan #{activeScan.id}</span>
          <span>名称: {activeScan.name}</span>
          <span>完成时间: {formatDateTime(activeScan.finished_at)}</span>
          <span>重复组: {activeScan.total_groups}</span>
          <span>文件总数: {activeScan.total_files_in_groups}</span>
          {activeScan.roots?.map((root, index) => (
            <span className="nfc-v2-scan-root" key={index}>
              {formatScanRootLabel(index, root)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};
