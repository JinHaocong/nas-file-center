import React from 'react';
import { WorkflowMode } from '../../types/workflow';
import { WorkflowPreviewPanel as LegacyWorkflowPreviewPanel } from './WorkflowPreviewPanelLegacy';
import { UtilityWorkflowPreviewPanel } from './UtilityWorkflowPreviewPanel';

interface WorkflowPreviewPanelProps {
  workflowId: number;
  revision: number;
  mode?: WorkflowMode;
  isDirty: boolean;
  isArchived?: boolean;
  onGeneratePlanSuccess: (planId: number) => void;
}

export const WorkflowPreviewPanel: React.FC<WorkflowPreviewPanelProps> = (props) => {
  const isUtility = props.mode === 'utility';
  if (isUtility) {
    return <UtilityWorkflowPreviewPanel {...props} />;
  }
  return <LegacyWorkflowPreviewPanel {...props} />;
};
