import { api } from './client';

export type ZSpaceAuthorizationStatus = 'unconfigured' | 'needs_login' | 'authorized' | 'unavailable';

export interface ZSpaceAuthorizationAttempt {
  id: string;
  url: string;
  expires_in: number;
}

const endpoint = '/api/settings/zspace-authorization';

export const zspaceAuthorizationApi = {
  status: () => api.get<{ status: ZSpaceAuthorizationStatus }>(endpoint),
  start: () => api.post<ZSpaceAuthorizationAttempt>(endpoint + '/start', {}),
  complete: (id: string, code: string) =>
    api.post<{ status: 'authorized'; mapping_verified: boolean }>(endpoint + '/complete', { id, code }),
  cancel: (id: string) => api.delete<void>(endpoint + '/pending/' + encodeURIComponent(id)),
};
