import { api } from './client';
import {
  OrganizerProfile,
  OrganizerProfileListResponse,
  OrganizerPreviewResponse,
} from '../types';

export const organizerProfilesApi = {
  listProfiles: (page: number = 1, pageSize: number = 50, search?: string) => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    if (search && search.trim()) {
      params.append('search', search.trim());
    }
    return api.get<OrganizerProfileListResponse>(`/api/organizer-profiles?${params.toString()}`);
  },

  getProfile: (id: number) => {
    return api.get<OrganizerProfile>(`/api/organizer-profiles/${id}`);
  },

  createProfile: (data: Partial<OrganizerProfile>) => {
    return api.post<OrganizerProfile>('/api/organizer-profiles', data);
  },

  updateProfile: (id: number, data: Partial<OrganizerProfile>) => {
    return api.put<OrganizerProfile>(`/api/organizer-profiles/${id}`, data);
  },

  deleteProfile: (id: number) => {
    return api.delete<{ success: boolean }>(`/api/organizer-profiles/${id}`);
  },

  cloneProfile: (id: number) => {
    return api.post<OrganizerProfile>(`/api/organizer-profiles/${id}/clone`);
  },

  exportProfile: (id: number) => {
    return api.get<{ schema_version: number; profile: any }>(`/api/organizer-profiles/${id}/export`);
  },

  importProfile: (data: { schema_version: number; profile: any }) => {
    return api.post<OrganizerProfile>('/api/organizer-profiles/import', data);
  },

  previewProfile: (
    id: number,
    data: {
      root?: string;
      page?: number;
      page_size?: number;
      only_changed?: boolean;
      only_conflicts?: boolean;
      snapshot_id?: string;
    }
  ) => {
    return api.post<OrganizerPreviewResponse>(`/api/organizer-profiles/${id}/preview`, data);
  },

  createPlan: (
    id: number,
    data: {
      root?: string;
      include_touch?: boolean;
    }
  ) => {
    return api.post<{ id: number; name: string; kind: string; status: string }>(
      `/api/organizer-profiles/${id}/plan`,
      data
    );
  },
};
