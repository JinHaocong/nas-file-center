import React, { useEffect } from 'react';
import { Form } from 'antd';
import { OrganizeStep, OrganizerProfileSnapshot } from '../../types/workflow';
import { OrganizerProfileFields } from './OrganizerProfileFields';

interface OrganizerStepEditorProps {
  step: OrganizeStep;
  onChange: (updated: OrganizeStep) => void;
}

export const OrganizerStepEditor: React.FC<OrganizerStepEditorProps> = ({ step, onChange }) => {
  const [form] = Form.useForm();

  useEffect(() => {
    form.setFieldsValue({
      name: step.profile_snapshot.name || '',
      description: step.profile_snapshot.description || '',
      root: step.profile_snapshot.root || '',
      recursive: step.profile_snapshot.recursive ?? false,
      image_extensions: step.profile_snapshot.image_extensions || ['jpg', 'jpeg', 'png', 'webp'],
      video_extensions: step.profile_snapshot.video_extensions || ['mp4', 'mov', 'mkv'],
      rename_template: step.profile_snapshot.rename_template || '{name} {statistics}',
      statistics_template: step.profile_snapshot.statistics_template || '[{images}P{?videos: {videos}V} {size}]',
      preserve_tags: step.profile_snapshot.preserve_tags ?? [],
      cleanup_patterns: step.profile_snapshot.cleanup_patterns || [],
      numbering_mode: step.profile_snapshot.numbering_mode || 'none',
      numbering_start: step.profile_snapshot.numbering_start ?? 1,
      numbering_padding: step.profile_snapshot.numbering_padding ?? 3,
      mtime_mode: step.profile_snapshot.mtime_mode || 'none',
      mtime_delay_seconds: step.profile_snapshot.mtime_delay_seconds ?? 2.0,
    });
  }, [step.profile_snapshot, form]);

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
    <Form
      form={form}
      layout="vertical"
      onValuesChange={handleValuesChange}
    >
      <OrganizerProfileFields includeRoot={false} />
    </Form>
  );
};
