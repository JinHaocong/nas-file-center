import React, { useEffect } from 'react';
import { Modal, Form } from 'antd';
import { OrganizerProfile } from '../../types';
import { OrganizerProfileFields } from '../../components/workflows/OrganizerProfileFields';
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
      if (editingProfile) {
        form.setFieldsValue({
          name: editingProfile.name,
          description: editingProfile.description || '',
          root: editingProfile.root || '',
          recursive: editingProfile.recursive || false,
          image_extensions: editingProfile.image_extensions || ['jpg', 'jpeg', 'png', 'webp'],
          video_extensions: editingProfile.video_extensions || ['mp4', 'mov', 'mkv'],
          rename_template: editingProfile.rename_template || '{name} {statistics}',
          statistics_template: editingProfile.statistics_template || '[{images}P{?videos: {videos}V} {size}]',
          preserve_tags: editingProfile.preserve_tags ?? [],
          cleanup_patterns: editingProfile.cleanup_patterns || [],
          numbering_mode: editingProfile.numbering_mode || 'none',
          numbering_start: editingProfile.numbering_start ?? 1,
          numbering_padding: editingProfile.numbering_padding ?? 3,
          mtime_mode: editingProfile.mtime_mode || 'none',
          mtime_delay_seconds: editingProfile.mtime_delay_seconds ?? 2.0,
        });
      } else {
        form.resetFields();
        form.setFieldsValue({
          name: '',
          description: '',
          root: '',
          recursive: false,
          image_extensions: ['jpg', 'jpeg', 'png', 'webp'],
          video_extensions: ['mp4', 'mkv', 'mov'],
          rename_template: '{name}',
          statistics_template: '[{images}P {videos}V {size}]',
          preserve_tags: [],
          cleanup_patterns: [],
          numbering_mode: 'none',
          numbering_start: 1,
          numbering_padding: 3,
          mtime_mode: 'none',
          mtime_delay_seconds: 2.0,
        });
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
