import React, { useEffect } from 'react';
import { Form, Select, Space, Typography, message } from 'antd';
import { ImportOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { OrganizeStep, OrganizerProfileSnapshot } from '../../types/workflow';
import { OrganizerProfileFields } from './OrganizerProfileFields';
import { organizerProfilesApi } from '../../api/organizerProfiles';
import { createDefaultOrganizerSnapshot, importProfileToSnapshot } from '../../utils/organizerDefaults';

const { Text } = Typography;

interface OrganizerStepEditorProps {
  step: OrganizeStep;
  onChange: (updated: OrganizeStep) => void;
  readOnly?: boolean;
}

export const OrganizerStepEditor: React.FC<OrganizerStepEditorProps> = ({ step, onChange, readOnly = false }) => {
  const [form] = Form.useForm();

  const { data: profilesData, isLoading: isLoadingProfiles } = useQuery({
    queryKey: ['organizerProfilesListForImport'],
    queryFn: () => organizerProfilesApi.listProfiles(1, 100),
  });

  useEffect(() => {
    const defaults = createDefaultOrganizerSnapshot();
    form.setFieldsValue({
      name: step.profile_snapshot.name || '',
      description: step.profile_snapshot.description || '',
      root: step.profile_snapshot.root || '',
      recursive: step.profile_snapshot.recursive ?? defaults.recursive,
      image_extensions: step.profile_snapshot.image_extensions ?? defaults.image_extensions,
      video_extensions: step.profile_snapshot.video_extensions ?? defaults.video_extensions,
      rename_template: step.profile_snapshot.rename_template ?? defaults.rename_template,
      statistics_template: step.profile_snapshot.statistics_template ?? defaults.statistics_template,
      preserve_tags: step.profile_snapshot.preserve_tags ?? defaults.preserve_tags,
      cleanup_patterns: step.profile_snapshot.cleanup_patterns ?? defaults.cleanup_patterns,
      numbering_mode: step.profile_snapshot.numbering_mode ?? defaults.numbering_mode,
      numbering_start: step.profile_snapshot.numbering_start ?? defaults.numbering_start,
      numbering_padding: step.profile_snapshot.numbering_padding ?? defaults.numbering_padding,
      mtime_mode: step.profile_snapshot.mtime_mode ?? defaults.mtime_mode,
      mtime_delay_seconds: step.profile_snapshot.mtime_delay_seconds ?? defaults.mtime_delay_seconds,
    });
  }, [step.profile_snapshot, form]);

  const handleImportProfile = (profileId: number) => {
    const target = (profilesData?.items || []).find((p) => p.id === profileId);
    if (!target) return;
    const immutableSnapshot = importProfileToSnapshot(target);
    onChange({
      ...step,
      profile_snapshot: immutableSnapshot,
    });
    message.success(`已从「${target.name}」导入配置快照（此为独立不可变副本）`);
  };

  const handleValuesChange = (_: any, allValues: any) => {
    const updatedSnapshot: OrganizerProfileSnapshot = {
      name: allValues.name,
      description: allValues.description || null,
      root: allValues.root || null,
      recursive: Boolean(allValues.recursive),
      image_extensions: allValues.image_extensions || [],
      video_extensions: allValues.video_extensions || [],
      rename_template: allValues.rename_template || '{name}',
      statistics_template: allValues.statistics_template || '[{images}P {videos}V {size}]',
      preserve_tags: allValues.preserve_tags || [],
      cleanup_patterns: allValues.cleanup_patterns || [],
      numbering_mode: allValues.numbering_mode || 'none',
      numbering_start: Number(allValues.numbering_start ?? 1),
      numbering_padding: Number(allValues.numbering_padding ?? 3),
      mtime_mode: allValues.mtime_mode || 'none',
      mtime_delay_seconds: Number(allValues.mtime_delay_seconds ?? 2.0),
    };
    onChange({
      ...step,
      profile_snapshot: updatedSnapshot,
    });
  };

  return (
    <div>
      {!readOnly && (
        <div
          style={{
            marginBottom: 16,
            padding: 12,
            background: '#f6ffed',
            border: '1px solid #b7eb8f',
            borderRadius: 8,
          }}
        >
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space align="center" style={{ width: '100%', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
              <Space>
                <ImportOutlined style={{ color: '#52c41a' }} />
                <Text strong>从现有整理方案导入配置 (Import from Profile)</Text>
              </Space>
              <Select
                placeholder="选择已有方案导入快照..."
                style={{ minWidth: 240 }}
                loading={isLoadingProfiles}
                value={undefined}
                onChange={handleImportProfile}
                options={(profilesData?.items || []).map((p) => ({
                  label: `${p.name} (ID: #${p.id})`,
                  value: p.id,
                }))}
              />
            </Space>
            <Text type="secondary" style={{ fontSize: 12 }}>
              说明：导入操作将把目标方案的配置复制为独立的不可变快照，后续原方案的修改不会影响本工作流。
            </Text>
          </Space>
        </div>
      )}

      <Form
        form={form}
        layout="vertical"
        disabled={readOnly}
        onValuesChange={handleValuesChange}
      >
        <OrganizerProfileFields includeRoot={false} />
      </Form>
    </div>
  );
};
