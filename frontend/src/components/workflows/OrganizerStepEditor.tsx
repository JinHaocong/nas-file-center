import React, { useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { OrganizeStep, OrganizerProfileSnapshot } from '../../types/workflow';
import { OrganizerSnapshotFields } from './OrganizerSnapshotFields';
import { organizerProfilesApi } from '../../api/organizerProfiles';
import { getStructuredApiError } from '../../api/errors';
import { importProfileToSnapshot } from '../../utils/organizerDefaults';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { useConsoleToast } from '../ui/ConsoleToast';

interface Props {
  step: OrganizeStep;
  onChange: (updated: OrganizeStep) => void;
  readOnly?: boolean;
}

/** Imports a *fetched* immutable copy, not a live profile reference. */
export const OrganizerStepEditor: React.FC<Props> = ({
  step, onChange, readOnly = false,
}) => {
  const toast = useConsoleToast();
  const [isImporting, setIsImporting] = useState(false);
  const importInFlight = useRef(false);
  const readOnlyRef = useRef(readOnly);
  const stepRef = useRef(step);
  readOnlyRef.current = readOnly;
  stepRef.current = step;

  const { data: profilesData, isLoading: isLoadingProfiles, isError: profilesError } = useQuery({
    queryKey: ['organizerProfilesListForImport'],
    queryFn: () => organizerProfilesApi.listProfiles(1, 100),
    enabled: !readOnly,
  });
  const handleImportProfile = async (rawId: string) => {
    const profileId = Number(rawId);
    const knownIds = (profilesData?.items || []).map(p => p.id);
    if (readOnlyRef.current || importInFlight.current ||
      !Number.isSafeInteger(profileId) || !knownIds.includes(profileId)) return;
    importInFlight.current = true;
    setIsImporting(true);
    try {
      const fresh = await organizerProfilesApi.getProfile(profileId);
      if (readOnlyRef.current) return;
      const immutableSnapshot = importProfileToSnapshot(fresh);
      onChange({ ...stepRef.current, profile_snapshot: immutableSnapshot });
      toast.success(`已从「${fresh.name}」获取最新配置并导入为独立快照副本`);
    } catch (err: unknown) {
      toast.error(`导入配置失败: ${getStructuredApiError(err).message}`);
    } finally {
      importInFlight.current = false;
      setIsImporting(false);
    }
  };
  const handleValuesChange = (nextSnapshot: OrganizerProfileSnapshot) => {
    if (readOnlyRef.current || importInFlight.current) return;
    onChange({ ...stepRef.current, profile_snapshot: nextSnapshot });
  };
  return (
    <div className="nfc-organizer-step-editor nfc-v2-workflow-organizer">
      {!readOnly && (
        <div className="nfc-organizer-step-import nfc-v2-workflow-organizer-import">
          <div className="nfc-organizer-step-import-stack">
            <label className="nfc-organizer-step-import-row nfc-v2-workflow-organizer-import-row">
              <span className="nfc-v2-workflow-organizer-import-label">
                <ConsoleIcon name="copy" size={17} />
                从现有整理方案导入配置 (Import from Profile)
              </span>
              <select className="nfc-v2-workflow-organizer-import-select"
                disabled={isLoadingProfiles || isImporting}
                value="" aria-label="选择已有整理方案导入快照"
                onChange={event => { void handleImportProfile(event.target.value); }}>
                <option value="" disabled>选择已有方案导入快照...</option>
                {(profilesData?.items || []).map(profile => (
                  <option key={profile.id} value={profile.id}>
                    {profile.name} (ID: #{profile.id})
                  </option>
                ))}
              </select>
            </label>
            {profilesError && <span role="alert" className="nfc-v2-step-warning">
              无法读取方案列表；现有快照不会被清空。
            </span>}
            {isImporting && <span role="status" className="nfc-v2-organizer-help">
              正在获取最新方案并复制快照…
            </span>}
            <p className="nfc-form-safety-note">
              导入操作将把目标方案的配置复制为独立的不可变快照；后续原方案的修改不会影响本工作流。
            </p>
          </div>
        </div>
      )}
      <OrganizerSnapshotFields value={step.profile_snapshot}
        onChange={handleValuesChange} readOnly={readOnly || isImporting} />
    </div>
  );
};
