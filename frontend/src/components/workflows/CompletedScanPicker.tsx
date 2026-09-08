import React, { useState } from "react";
import { Select, InputNumber, Space, Tag, Button } from "antd";
import { useQuery } from "@tanstack/react-query";
import { EditOutlined, UnorderedListOutlined } from "@ant-design/icons";
import { scansApi } from "../../api/domain";
import { ScanJob } from "../../types";
import { formatBytes } from "../../utils/format";

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

  const { data: scansData, isLoading } = useQuery({
    queryKey: ["completedScansList"],
    queryFn: async () => {
      const res = await scansApi.listScans(1, 50);
      return res.items || [];
    },
  });

  const completedScans = (scansData || []).filter(
    (s: ScanJob) => s.status === "completed"
  );

  const selectedScan = (scansData || []).find((s: ScanJob) => s.id === value);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {!manualMode ? (
          <Select<number>
            value={value}
            onChange={(val) => onChange(val)}
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
          <InputNumber
            value={value}
            onChange={(val) => onChange(val || undefined)}
            placeholder="输入 Scan Job ID"
            disabled={disabled}
            min={1}
            style={{ width: 220 }}
          />
        )}

        <Button
          type="link"
          size="small"
          icon={manualMode ? <UnorderedListOutlined /> : <EditOutlined />}
          onClick={() => setManualMode(!manualMode)}
          disabled={disabled}
        >
          {manualMode ? "切换为扫描列表" : "手动输入 ID"}
        </Button>
      </div>

      {selectedScan && (
        <div style={{ fontSize: 12, color: "#8c8c8c" }}>
          <Space wrap size={6}>
            <Tag color="green">已完成</Tag>
            <span>重复组: {selectedScan.total_groups}</span>
            <span>|</span>
            <span>文件总数: {selectedScan.total_files_in_groups}</span>
            <span>|</span>
            <span>根目录: {selectedScan.roots.join(", ")}</span>
          </Space>
        </div>
      )}
    </div>
  );
};
