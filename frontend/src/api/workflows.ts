import { api } from './client';
import {
  WorkflowListItem,
  WorkflowResponse,
  WorkflowRevisionResponse,
  WorkflowCreateRequest,
  WorkflowUpdateRequest,
  WorkflowRollbackRequest,
  WorkflowPreviewRequest,
  WorkflowPreviewResponse,
  WorkflowGeneratePlanRequest,
  WorkflowGeneratePlanResponse,
  PlanRebuildPreviewRequest,
  PlanRebuildPreviewResponse,
  PlanRebuildRequest,
  PlanRebuildResponse,
} from '../types/workflow';

export const workflowApi = {
  listWorkflows: async (includeArchived: boolean = false): Promise<WorkflowListItem[]> => {
    return api.get<WorkflowListItem[]>(`/api/workflows?include_archived=${includeArchived}`);
  },

  getWorkflow: async (id: number): Promise<WorkflowResponse> => {
    return api.get<WorkflowResponse>(`/api/workflows/${id}`);
  },

  getRevision: async (id: number, revision: number): Promise<WorkflowRevisionResponse> => {
    return api.get<WorkflowRevisionResponse>(`/api/workflows/${id}/revisions/${revision}`);
  },

  getWorkflowRevision: async (id: number, revision: number): Promise<WorkflowRevisionResponse> => {
    return api.get<WorkflowRevisionResponse>(`/api/workflows/${id}/revisions/${revision}`);
  },

  createWorkflow: async (data: WorkflowCreateRequest): Promise<WorkflowResponse> => {
    return api.post<WorkflowResponse>('/api/workflows', data);
  },

  updateWorkflow: async (id: number, data: WorkflowUpdateRequest): Promise<WorkflowResponse> => {
    return api.put<WorkflowResponse>(`/api/workflows/${id}`, data);
  },

  archiveWorkflow: async (
    id: number,
    expectedCurrentRevision: number
  ): Promise<{ status: string; archived: boolean }> => {
    return api.delete<{ status: string; archived: boolean }>(
      `/api/workflows/${id}?expected_current_revision=${expectedCurrentRevision}`
    );
  },

  rollbackWorkflow: async (
    id: number,
    data: WorkflowRollbackRequest
  ): Promise<WorkflowResponse> => {
    return api.post<WorkflowResponse>(`/api/workflows/${id}/rollback`, data);
  },

  listRevisions: async (id: number): Promise<WorkflowRevisionResponse[]> => {
    return api.get<WorkflowRevisionResponse[]>(`/api/workflows/${id}/revisions`);
  },

  previewWorkflow: async (
    id: number,
    data: WorkflowPreviewRequest
  ): Promise<WorkflowPreviewResponse> => {
    return api.post<WorkflowPreviewResponse>(`/api/workflows/${id}/preview`, data);
  },

  generatePlan: async (
    id: number,
    data: WorkflowGeneratePlanRequest
  ): Promise<WorkflowGeneratePlanResponse> => {
    return api.post<WorkflowGeneratePlanResponse>(`/api/workflows/${id}/generate-plan`, data);
  },

  rebuildPlanPreview: async (
    planId: number,
    data: PlanRebuildPreviewRequest = {}
  ): Promise<PlanRebuildPreviewResponse> => {
    return api.post<PlanRebuildPreviewResponse>(`/api/plans/${planId}/rebuild-preview`, data);
  },

  rebuildPlan: async (
    planId: number,
    data: PlanRebuildRequest
  ): Promise<PlanRebuildResponse> => {
    return api.post<PlanRebuildResponse>(`/api/plans/${planId}/rebuild`, data);
  },
};

export const getWorkflowRevision = workflowApi.getWorkflowRevision;
