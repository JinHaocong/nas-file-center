import { api } from './client';
import {
  TaskItem,
  TaskId,
  TaskDetail,
  PaginatedTasksResponse,
  PaginatedTaskEventsResponse,
  WorkerStatus,
  RetryTaskResponse,
  DeleteTaskResponse,
  ClearTaskHistoryResponse,
  OrganizerReportInventoryResponse,
  TerminalTaskStatus,
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
  /** Read a page of the smart organizer report inventory. */
  getOrganizerReports: (page: number, pageSize: number): Promise<OrganizerReportInventoryResponse> => {
    const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    return api.get<OrganizerReportInventoryResponse>(`/api/tasks/organizer-reports?${query}`);
  },

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

  getTaskDetail: (taskId: TaskId): Promise<TaskDetail> => {
    return api.get<TaskDetail>(`/api/tasks/${taskId}`);
  },

  getTaskLogs: (taskId: TaskId, params: ListTaskLogsParams = {}): Promise<PaginatedTaskEventsResponse> => {
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

  pauseTask: (taskId: TaskId): Promise<TaskItem> => {
    return api.post<TaskItem>(`/api/tasks/${taskId}/pause`);
  },

  resumeTask: (taskId: TaskId): Promise<TaskItem> => {
    return api.post<TaskItem>(`/api/tasks/${taskId}/resume`);
  },

  cancelTask: (taskId: TaskId): Promise<TaskItem> => {
    return api.post<TaskItem>(`/api/tasks/${taskId}/cancel`);
  },

  retryTask: (taskId: TaskId): Promise<RetryTaskResponse> => {
    return api.post<RetryTaskResponse>(`/api/tasks/${taskId}/retry`);
  },

  deleteTask: (taskId: TaskId): Promise<DeleteTaskResponse> => {
    return api.delete<DeleteTaskResponse>(`/api/tasks/${taskId}`);
  },

  clearTaskHistory: (statuses: TerminalTaskStatus[]): Promise<ClearTaskHistoryResponse> => {
    return api.post<ClearTaskHistoryResponse>('/api/tasks/clear-history', { statuses });
  },
};

