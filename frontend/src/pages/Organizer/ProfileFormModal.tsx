import React, { useEffect } from 'react';
import { Modal, Form } from 'antd';
import { OrganizerProfile } from '../../types';
import { OrganizerProfileFields } from '../../components/workflows/OrganizerProfileFields';
import { createDefaultOrganizerSnapshot } from '../../utils/organizerDefaults';
// DirectoryPicker is encapsulated and rendered via OrganizerProfileFields

interface ProfileFormModalProps {
  open: boolean;
  editingProfile: OrganizerProfile | null;
  onCancel: () => void;
  onSubmit: (values: Partial<OrganizerProfile>) => Promise<void>;
  loading?: boolean;
}

export const ProfileFormModal: React.FC<ProfileFormModalProps> = ({
  open,
  editingProfile,
  onCancel,
  onSubmit,
  loading = false,
}) => {
  const [form] = Form.useForm();

  useEffect(() => {
    if (open) {
      const defaults = createDefaultOrganizerSnapshot();
      if (editingProfile) {
        form.setFieldsValue({
          name: editingProfile.name,
          description: editingProfile.description || '',
          root: editingProfile.root || '',
          recursive: editingProfile.recursive ?? defaults.recursive,
          image_extensions: editingProfile.image_extensions ?? defaults.image_extensions,
          video_extensions: editingProfile.video_extensions ?? defaults.video_extensions,
          rename_template: editingProfile.rename_template ?? defaults.rename_template,
          statistics_template: editingProfile.statistics_template ?? defaults.statistics_template,
          preserve_tags: editingProfile.preserve_tags ?? defaults.preserve_tags,
          cleanup_patterns: editingProfile.cleanup_patterns ?? defaults.cleanup_patterns,
          numbering_mode: editingProfile.numbering_mode ?? defaults.numbering_mode,
          numbering_start: editingProfile.numbering_start ?? defaults.numbering_start,
          numbering_padding: editingProfile.numbering_padding ?? defaults.numbering_padding,
          mtime_mode: editingProfile.mtime_mode ?? defaults.mtime_mode,
          mtime_delay_seconds: editingProfile.mtime_delay_seconds ?? defaults.mtime_delay_seconds,
        });
      } else {
        form.resetFields();
        form.setFieldsValue(defaults);
      }
    }
  }, [open, editingProfile, form]);

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      await onSubmit(values);
    } catch {
      // Form validation failed
    }
  };

  return (
    <Modal
      title={editingProfile ? `编辑方案: ${editingProfile.name}` : '新建整理方案'}
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      confirmLoading={loading}
      width={720}
      destroyOnClose
      okText="保存方案"
      cancelText="取消"
    >
      <Form form={form} layout="vertical">
        <OrganizerProfileFields includeRoot={true} />
      </Form>
    </Modal>
  );
};
