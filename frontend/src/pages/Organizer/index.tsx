import React, { useState } from 'react';
import { Typography, message } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTitle } from '../../hooks/useTitle';
import { OrganizerProfile } from '../../types';
import { organizerProfilesApi } from '../../api/organizerProfiles';
import { ProfileList } from './ProfileList';
import { ProfilePreview } from './ProfilePreview';
import { ProfileFormModal } from './ProfileFormModal';

const { Title, Text } = Typography;

export const OrganizerPage: React.FC = () => {
  useTitle('Organizer 整理方案');
  const queryClient = useQueryClient();

  const [activeProfile, setActiveProfile] = useState<OrganizerProfile | null>(null);
  const [modalOpen, setModalOpen] = useState<boolean>(false);
  const [editingProfile, setEditingProfile] = useState<OrganizerProfile | null>(null);

  const saveMutation = useMutation({
    mutationFn: async (values: Partial<OrganizerProfile>) => {
      if (editingProfile) {
        return await organizerProfilesApi.updateProfile(editingProfile.id, values);
      } else {
        return await organizerProfilesApi.createProfile(values);
      }
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

  const handleSelectProfile = (profile: OrganizerProfile) => {
    setActiveProfile(profile);
  };

  return (
    <div>
      {!activeProfile ? (
        <>
          <div style={{ marginBottom: 20 }}>
            <Title level={4} style={{ margin: 0 }}>
              Organizer 智能整理方案
            </Title>
            <Text type="secondary">
              通过自定义 Profile 配置目录统计、命名、编号、标签与 mtime 整理规则。
            </Text>
          </div>

          <ProfileList
            onSelectProfile={handleSelectProfile}
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
