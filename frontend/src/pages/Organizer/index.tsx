import React, { useState } from 'react';
import { message } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTitle } from '../../hooks/useTitle';
import { OrganizerProfile } from '../../types';
import { organizerProfilesApi } from '../../api/organizerProfiles';
import { ProfileList } from './ProfileList';
import { ProfilePreview } from './ProfilePreview';
import { ProfileFormModal } from './ProfileFormModal';
import { PageHeader } from '../../components/ui/PageHeader';

export const OrganizerPage: React.FC = () => {
  useTitle('目录整理方案');
  const queryClient = useQueryClient();

  const [activeProfile, setActiveProfile] = useState<OrganizerProfile | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<OrganizerProfile | null>(null);

  const saveMutation = useMutation({
    mutationFn: async (values: Partial<OrganizerProfile>) => {
      if (editingProfile) {
        return organizerProfilesApi.updateProfile(editingProfile.id, values);
      }
      return organizerProfilesApi.createProfile(values);
    },
    onSuccess: (saved) => {
      message.success(`方案 "${saved.name}" 已成功保存！`);
      setModalOpen(false);
      setEditingProfile(null);
      queryClient.invalidateQueries({ queryKey: ['organizer-profiles'] });
    },
    onError: (err: any) => {
      message.error(err.message || '保存方案失败');
    },
  });

  const handleCreate = () => {
    setEditingProfile(null);
    setModalOpen(true);
  };

  const handleEdit = (profile: OrganizerProfile) => {
    setEditingProfile(profile);
    setModalOpen(true);
  };

  return (
    <div className="nfc-operations-page nfc-organizer-page nfc-page-layout-workbench">
      {!activeProfile ? (
        <>
          <PageHeader
            title="目录整理方案"
            description="管理可复用的目录整理方案。先选择或创建规则，再执行只读预览，确认冲突和变更后生成执行计划。"
          />
          <ProfileList
            onSelectProfile={setActiveProfile}
            onCreateProfile={handleCreate}
            onEditProfile={handleEdit}
          />
        </>
      ) : (
        <ProfilePreview
          profile={activeProfile}
          onBack={() => setActiveProfile(null)}
        />
      )}

      <ProfileFormModal
        open={modalOpen}
        editingProfile={editingProfile}
        onCancel={() => {
          setModalOpen(false);
          setEditingProfile(null);
        }}
        onSubmit={async (values) => {
          await saveMutation.mutateAsync(values);
        }}
        loading={saveMutation.isPending}
      />
    </div>
  );
};
