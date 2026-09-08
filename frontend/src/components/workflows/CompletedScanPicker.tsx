import React, { useState } from "react";
import { Select, InputNumber, Space, Tag, Button, message } from "antd";
import { useQuery } from "@tanstack/react-query";
import { EditOutlined, UnorderedListOutlined, CheckOutlined } from "@ant-design/icons";
import { scansApi } from "../../api/domain";
import { ScanJob } from "../../types";
import { formatBytes, formatDateTime } from "../../utils/format";
import { formatScanRootLabel } from "../../utils/dedupePreview";

interface Props {
  value?: number;
  onChange: (scanJobId?: number) => void;
  disabled?: boolean;
}

export const CompletedScanPicker: React.FC<Props> = ({
  value,
  onChange,
  disabled = false,
}) => {
  const [manualMode, setManualMode] = useState(false);
  const [manualInputId, setManualInputId] = useState<number | undefined>(value);
  const [verifying, setVerifying] = useState(false);
  const [manualScanDetail, setManualScanDetail] = useState<ScanJob | null>(null);

  const { data: scansData, isLoading } = useQuery({
    queryKey: ["completedScansList"],
    queryFn: async () => {
      const res = await scansApi.listScans(1, 500);
      return res.items || [];
    },
  });

  const completedScans = (scansData || []).filter(
    (s: ScanJob) => s.status === "completed"
  );

  const selectedScanFromList = (scansData || []).find((s: ScanJob) => s.id === value);

  const { data: valueScanDetail } = useQuery({
    queryKey: ["scanDetailPicker", value],
    queryFn: () => scansApi.getScanDetail(value!),
    enabled: !!value && !selectedScanFromList,
  });

  const activeScan = selectedScanFromList || manualScanDetail || valueScanDetail;

  const handleVerifyAndApply = async (idToVerify?: number) => {
    const targetId = idToVerify ?? manualInputId;
    if (!targetId || targetId <= 0) {
      onChange(undefined);
      setManualScanDetail(null);
      message.warning("请输入有效的 Scan Job ID");
      return;
    }
    setVerifying(true);
    try {
      const detail = await scansApi.getScanDetail(targetId);
      if (detail && detail.status === "completed") {
        setManualScanDetail(detail);
        onChange(detail.id);
        message.success(`已确认扫描任务 #${detail.id} 处于已完成状态`);
      } else {
        onChange(undefined);
        setManualScanDetail(null);
        message.error(
          `扫描任务 #${targetId} 状态为 ${detail?.status || "未知"}，只有已完成 (completed) 的扫描才可进行去重`
        );
      }
    } catch (err: any) {
      onChange(undefined);
      setManualScanDetail(null);
      message.error(`扫描任务 #${targetId} 查询失败或不存在`);
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {!manualMode ? (
          <Select<number>
            value={value}
            onChange={(val) => {
              setManualInputId(val);
              onChange(val);
            }}
            placeholder="请选择已完成的扫描任务..."
            loading={isLoading}
            disabled={disabled}
            style={{ width: 380 }}
            allowClear
            showSearch
            filterOption={(input, option) =>
              (option?.label as unknown as string ?? "")
                .toLowerCase()
                .includes(input.toLowerCase())
            }
            options={completedScans.map((s) => ({
              value: s.id,
              label: `#${s.id} - ${s.name} (${s.total_groups} 组重复, 可释放 ${formatBytes(s.reclaimable_bytes)})`,
            }))}
          />
        ) : (
          <Space>
            <InputNumber
              value={manualInputId}
              onChange={(val) => {
                setManualInputId(val || undefined);
                if (!val) {
                  onChange(undefined);
                  setManualScanDetail(null);
                }
              }}
              onPressEnter={() => handleVerifyAndApply()}
              placeholder="输入 Scan Job ID"
              disabled={disabled || verifying}
              min={1}
              style={{ width: 180 }}
            />
            <Button
              type="primary"
              size="middle"
              icon={<CheckOutlined />}
              onClick={() => handleVerifyAndApply()}
              loading={verifying}
              disabled={disabled || !manualInputId}
            >
              验证
            </Button>
          </Space>
        )}

        <Button
          type="link"
          size="small"
          icon={manualMode ? <UnorderedListOutlined /> : <EditOutlined />}
          onClick={() => {
            setManualMode(!manualMode);
            setManualInputId(value);
          }}
          disabled={disabled}
        >
          {manualMode ? "切换为扫描列表" : "手动输入 ID"}
        </Button>
      </div>

      {activeScan && (
        <div style={{ fontSize: 12, color: "#8c8c8c" }}>
          <Space wrap size={6}>
            <Tag color={activeScan.status === "completed" ? "green" : "orange"}>
              {activeScan.status}
            </Tag>
            <span style={{ fontWeight: 500 }}>Scan #{activeScan.id}</span>
            <span>|</span>
            <span>名称: {activeScan.name}</span>
            <span>|</span>
            <span>完成时间: {formatDateTime(activeScan.finished_at)}</span>
            <span>|</span>
            <span>重复组: {activeScan.total_groups}</span>
            <span>|</span>
            <span>文件总数: {activeScan.total_files_in_groups}</span>
            <span>|</span>
            <span>根目录:</span>
            {activeScan.roots?.map((r, idx) => (
              <Tag key={idx} color="cyan">
                {formatScanRootLabel(idx, r)}
              </Tag>
            ))}
          </Space>
        </div>
      )}
    </div>
  );
};
