import { api } from './client';
import {
  TaskDetail,
  PaginatedTasksResponse,
  PaginatedTaskEventsResponse,
  WorkerStatus,
} from '../types/task';

export interface ListTasksParams {
  page?: number;
  pageSize?: number;
  status?: string;
  jobType?: string;
}

export interface ListTaskLogsParams {
  page?: number;
  pageSize?: number;
  level?: string;
}

export const tasksApi = {
  listTasks: (params: ListTasksParams = {}): Promise<PaginatedTasksResponse> => {
    const searchParams = new URLSearchParams();
    if (params.page !== undefined) {
      searchParams.set('page', String(params.page));
    }
    if (params.pageSize !== undefined) {
      searchParams.set('page_size', String(params.pageSize));
    }
    if (params.status && params.status !== 'all') {
      searchParams.set('status', params.status);
    }
    if (params.jobType && params.jobType !== 'all') {
      searchParams.set('job_type', params.jobType);
    }
    const qs = searchParams.toString();
    return api.get<PaginatedTasksResponse>(`/api/tasks${qs ? `?${qs}` : ''}`);
  },

  getTaskDetail: (taskId: number): Promise<TaskDetail> => {
    return api.get<TaskDetail>(`/api/tasks/${taskId}`);
  },

  getTaskLogs: (taskId: number, params: ListTaskLogsParams = {}): Promise<PaginatedTaskEventsResponse> => {
    const searchParams = new URLSearchParams();
    if (params.page !== undefined) {
      searchParams.set('page', String(params.page));
    }
    if (params.pageSize !== undefined) {
      searchParams.set('page_size', String(params.pageSize));
    }
    if (params.level && params.level !== 'all') {
      searchParams.set('level', params.level);
    }
    const qs = searchParams.toString();
    return api.get<PaginatedTaskEventsResponse>(`/api/tasks/${taskId}/logs${qs ? `?${qs}` : ''}`);
  },

  getWorkerStatus: (): Promise<WorkerStatus> => {
    return api.get<WorkerStatus>('/api/tasks/worker');
  },
};
