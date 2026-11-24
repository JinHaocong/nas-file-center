import { api } from './client';
import { DirectoryListResponse, FavoritePath, RecentPath, User } from '../types';

/** Directory history belongs to the signed-in account; each recent list also has its own limit. */
export function directoryHistoryKey(kind: 'favorites' | 'recent', userId: User['id'] | undefined, limit?: number) {
  const owner = ['filesystem', kind, userId ?? null] as const;
  return limit === undefined ? owner : [...owner, limit] as const;
}

export const filesystemApi = {
  listDirectory: (
    path?: string,
    directoriesOnly: boolean = true,
    page: number = 1,
    pageSize: number = 100,
    search?: string,
  ) => {
    const params = new URLSearchParams();
    if (path && path.trim()) {
      params.append('path', path);
    }
    params.append('directories_only', String(directoriesOnly));
    params.append('page', String(page));
    params.append('page_size', String(pageSize));
    if (search && search.trim()) {
      params.append('search', search.trim());
    }
    return api.get<DirectoryListResponse>(`/api/filesystem/list?${params.toString()}`);
  },

  listFavorites: () => {
    return api.get<{ items: FavoritePath[] }>('/api/filesystem/favorites');
  },

  addFavorite: (path: string, label?: string) => {
    return api.post<FavoritePath>('/api/filesystem/favorites', { path, label });
  },

  deleteFavorite: (id: number) => {
    return api.delete<{ status: string; deleted_id: number }>(`/api/filesystem/favorites/${id}`);
  },

  listRecent: (limit: number = 20) => {
    return api.get<{ items: RecentPath[] }>(`/api/filesystem/recent?limit=${limit}`);
  },

  recordRecent: (paths: string[]) => {
    return api.post<{ items: RecentPath[] }>('/api/filesystem/recent', { paths });
  },
};
