import { api } from './client';
import {
  RecurrencePreview,
  ScheduleCreatePayload,
  ScheduleItem,
  ScheduleRun,
  ScheduleUpdatePayload,
} from '../types/scheduler';
import { PaginatedResponse } from '../types';

export const schedulerApi = {
  listSchedules: (page = 1, pageSize = 100, includeDisabled = true) =>
    api.get<PaginatedResponse<ScheduleItem>>(
      `/api/schedules?page=${page}&page_size=${pageSize}&include_disabled=${includeDisabled}`,
    ),

  getSchedule: (id: number) =>
    api.get<ScheduleItem>(`/api/schedules/${id}`),

  listRuns: (id: number, limit = 50) =>
    api.get<{ items: ScheduleRun[] }>(`/api/schedules/${id}/runs?limit=${limit}`),

  createSchedule: (payload: ScheduleCreatePayload) =>
    api.post<ScheduleItem>('/api/schedules', payload),

  updateSchedule: (id: number, payload: ScheduleUpdatePayload) =>
    api.put<ScheduleItem>(`/api/schedules/${id}`, payload),

  runNow: (id: number) =>
    api.post<ScheduleRun>(`/api/schedules/${id}/run-now`),

  previewRecurrence: (cronExpression: string, timezone: string, count = 5) =>
    api.post<RecurrencePreview>('/api/schedules/recurrence/preview', {
      cron_expression: cronExpression,
      timezone,
      count,
    }),
};
