import React, { useEffect, useRef, useState } from 'react';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
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
  const toast = useConsoleToast();

  const [activeProfile, setActiveProfile] = useState<OrganizerProfile | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<OrganizerProfile | null>(null);
  const workspaceRef = useRef<HTMLElement>(null);
  const moveFocus = useRef(false);

  useEffect(() => {
    if (!moveFocus.current) return;
    moveFocus.current = false;
    workspaceRef.current?.focus({ preventScroll: true });
    workspaceRef.current?.scrollIntoView({ block: 'start', behavior: 'instant' });
  }, [activeProfile]);

  /** Place focus on the new workspace after entering or leaving a profile preview. */
  const openProfile = (profile: OrganizerProfile | null) => {
    moveFocus.current = true;
    setActiveProfile(profile);
  };

  const saveMutation = useMutation({
    mutationFn: async (values: Partial<OrganizerProfile>) => {
      if (editingProfile?.is_builtin) throw new Error('内置方案不可直接修改');
      if (editingProfile) {
        return organizerProfilesApi.updateProfile(editingProfile.id, values);
      }
      return organizerProfilesApi.createProfile(values);
    },
    onSuccess: (saved) => {
      toast.success(`方案 "${saved.name}" 已成功保存！`);
      setModalOpen(false);
      setEditingProfile(null);
      queryClient.invalidateQueries({ queryKey: ['organizer-profiles'] });
    },
    onError: (err: any) => {
      toast.error(err.message || '保存方案失败');
    },
  });

  const handleCreate = () => {
    setEditingProfile(null);
    setModalOpen(true);
  };

  const handleEdit = (profile: OrganizerProfile) => {
    if (profile.is_builtin) return;
    setEditingProfile(profile);
    setModalOpen(true);
  };

  return (
    <div className="nfc-operations-page nfc-organizer-page nfc-page-layout-workbench nfc-tool-workspace">
      <section ref={workspaceRef} key={activeProfile ? 'preview' : 'profiles'} tabIndex={-1}
        className="nfc-tool-profile-view" aria-label={activeProfile ? '方案预览' : '目录整理方案列表'}>
      {!activeProfile ? (
        <>
          <PageHeader
            title="目录整理方案"
            description="保存可复用的目录统计、命名、编号、标签与 mtime 规则；先只读 Preview，再生成 Plan。"
          />
          <ProfileList
            onSelectProfile={openProfile}
            onCreateProfile={handleCreate}
            onEditProfile={handleEdit}
          />
        </>
      ) : (
        <ProfilePreview
          profile={activeProfile}
          onBack={() => openProfile(null)}
        />
      )}
      </section>

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
