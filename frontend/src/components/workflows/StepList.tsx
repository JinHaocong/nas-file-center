import React, { useEffect, useRef, useState } from 'react';

import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon, type ConsoleIconName } from '../ui/ConsoleIcon';
import { StepCard } from './StepCard';

import { createDefaultOrganizerSnapshot } from '../../utils/organizerDefaults';
import { createDefaultDedupeScorerConfig } from '../../utils/dedupeConfig';
import { getAllowedInsertions, canMoveStep, canDeleteStep } from '../../utils/workflowTopology';

import type { WorkflowStep, WorkflowMode } from '../../types/workflow';

interface StepListProps {
  steps: WorkflowStep[];
  mode: WorkflowMode;
  readOnly?: boolean;
  onChange: (steps: WorkflowStep[]) => void;
}

type StepChoice = { key: WorkflowStep['type']; icon: ConsoleIconName; label: string };
const fileChoices: StepChoice[] = [
  { key: 'filter', icon: 'sliders', label: '条件过滤' },
  { key: 'rename', icon: 'pencil', label: '字面量重命名' },
  { key: 'move', icon: 'folder', label: '路径移动' },
  { key: 'touch', icon: 'clock', label: '时间戳更新' },
  { key: 'quarantine', icon: 'shield-check', label: '隔离归档' },
];
/** 编辑单个步骤时，用步骤 ID 绑定展开状态，避免重排后打开另一项。 */
export const StepList: React.FC<StepListProps> = ({ steps, mode, readOnly = false, onChange }) => {
  const menuId = React.useId();
  const listRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);
  const focusLastOnOpen = useRef(false);
  const stepToFocus = useRef<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  // undefined 表示尚未操作，此时仅单步骤流程默认展开。
  const [expandedId, setExpandedId] = useState<string | null>();
  const visibleStepId = expandedId === undefined && steps.length === 1 ? steps[0].id : expandedId;

  const generateId = (prefix: string) => `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
  const allowedInsertions = getAllowedInsertions(steps, mode);
  const menuItems = fileChoices.filter(item => allowedInsertions.includes(item.key));
  const canOpenMenu = !readOnly && mode === 'file' && menuItems.length > 0;

  useEffect(() => {
    if (!canOpenMenu) setMenuOpen(false);
  }, [canOpenMenu]);

  useEffect(() => {
    if (stepToFocus.current === null) return;
    const toggles = listRef.current?.querySelectorAll<HTMLButtonElement>('button[data-step-id]');
    const target = Array.from(toggles ?? []).find(button => button.dataset.stepId === stepToFocus.current);
    stepToFocus.current = null;
    target?.focus();
  }, [steps]);

  useEffect(() => {
    if (!menuOpen) return;
    const enabled = menuRef.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');
    const target = focusLastOnOpen.current ? enabled?.[enabled.length - 1] : enabled?.[0];
    target?.focus();
    focusLastOnOpen.current = false;
  }, [menuOpen]);

  useEffect(() => {
    if (!menuOpen) return;
    const handleOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !surfaceRef.current?.contains(event.target)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('pointerdown', handleOutside);
    return () => document.removeEventListener('pointerdown', handleOutside);
  }, [menuOpen]);

  const handleAddStep = (type: WorkflowStep['type']) => {
    // Recheck current permissions and topology at the action boundary.
    if (readOnly || !getAllowedInsertions(steps, mode).includes(type)) return;
    let newStep: WorkflowStep;
    switch (type) {
      case 'scan': newStep = { id: generateId('scan'), type: 'scan', root_ids: [] }; break;
      case 'filter': newStep = { id: generateId('filter'), type: 'filter', filter: { field: 'extension', operator: 'eq', value: 'jpg', case_sensitive: false } }; break;
      case 'rename': newStep = { id: generateId('rename'), type: 'rename', pattern: 'draft', replacement: 'final' }; break;
      case 'move': newStep = { id: generateId('move'), type: 'move', destination_root_id: 1, destination_subpath: '' }; break;
      case 'touch': newStep = { id: generateId('touch'), type: 'touch', touch_now: true, mtime_ns: null }; break;
      case 'quarantine': newStep = { id: generateId('quarantine'), type: 'quarantine', reason: 'quarantine by workflow' }; break;
      case 'organize': newStep = { id: generateId('organize'), type: 'organize', profile_snapshot: createDefaultOrganizerSnapshot('默认整理快照') }; break;
      case 'dedupe': newStep = { id: generateId('dedupe'), type: 'dedupe', scorer_config: createDefaultDedupeScorerConfig() }; break;
      case 'single_child_wrapper_collapse':
        newStep = { id: generateId('utility-collapse'), type: 'single_child_wrapper_collapse', root_id: 0, subpath: '' };
        break;
    }
    setMenuOpen(false);
    setExpandedId(newStep.id);
    stepToFocus.current = newStep.id;
    onChange([...steps, newStep]);
  };

  const handleStepChange = (index: number, updated: WorkflowStep) => {
    if (readOnly || index < 0 || index >= steps.length) return;
    const nextSteps = [...steps];
    nextSteps[index] = updated;
    onChange(nextSteps);
  };
  const handleMove = (index: number, direction: 'up' | 'down') => {
    if (readOnly || !canMoveStep(steps, index, direction, mode)) return;
    const nextSteps = [...steps];
    const target = direction === 'up' ? index - 1 : index + 1;
    stepToFocus.current = steps[index].id;
    [nextSteps[index], nextSteps[target]] = [nextSteps[target], nextSteps[index]];
    onChange(nextSteps);
  };
  const handleDelete = (index: number) => {
    if (readOnly || !canDeleteStep(steps, index, mode)) return;
    setExpandedId(null);
    stepToFocus.current = (steps[index + 1] ?? steps[index - 1]).id;
    onChange(steps.filter((_, i) => i !== index));
  };

  const focusMenuItem = (key: string) => {
    const enabled = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? []);
    if (!enabled.length) return;
    const current = enabled.indexOf(document.activeElement as HTMLButtonElement);
    const target = key === 'Home' ? 0 : key === 'End' ? enabled.length - 1
      : key === 'ArrowDown' ? (current + 1) % enabled.length
      : current === -1 ? enabled.length - 1 : (current + enabled.length - 1) % enabled.length;
    enabled[target]?.focus();
  };

  const handleMenuKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      setMenuOpen(false);
      triggerRef.current?.focus();
    } else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      focusMenuItem(event.key);
    }
  };

  return (
    <div className="nfc-workflow-step-list" ref={listRef}>
      {steps.length === 0 ? (
        <div className="nfc-step-empty nfc-v2-step-empty" role="status">
          <ConsoleIcon name="list-checks" size={24} />
          <p>暂无工作流步骤，请从下方添加执行步骤</p>
        </div>
      ) : steps.map((step, idx) => (
        <StepCard key={step.id || idx} step={step} index={idx} mode={mode} readOnly={readOnly}
          expanded={visibleStepId === step.id}
          onToggle={() => setExpandedId(visibleStepId === step.id ? null : step.id)}
          canMoveUp={canMoveStep(steps, idx, 'up', mode)} canMoveDown={canMoveStep(steps, idx, 'down', mode)} canDelete={canDeleteStep(steps, idx, mode)}
          onChange={(updated) => handleStepChange(idx, updated)} onMoveUp={() => handleMove(idx, 'up')}
          onMoveDown={() => handleMove(idx, 'down')} onDelete={() => handleDelete(idx)} />
      ))}
      {!readOnly && mode === 'file' && (canOpenMenu ? (
        <div className="nfc-step-add-surface" ref={surfaceRef}>
          <div className="nfc-v2-step-menu-anchor">
            <ConsoleButton ref={triggerRef} className="nfc-step-add-button" variant="secondary"
              leadingIcon={<ConsoleIcon name="plus" size={16} />}
              aria-haspopup="menu" aria-expanded={menuOpen} aria-controls={menuOpen ? menuId : undefined}
              onClick={() => { focusLastOnOpen.current = false; setMenuOpen(open => !open); }}
              onKeyDown={(event) => {
                if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && canOpenMenu) {
                  event.preventDefault();
                  focusLastOnOpen.current = event.key === 'ArrowUp';
                  setMenuOpen(true);
                } else if (event.key === 'Escape' && menuOpen) {
                  event.preventDefault();
                  setMenuOpen(false);
                }
              }}>
              添加执行步骤
            </ConsoleButton>
            {menuOpen && canOpenMenu && (
              <div id={menuId} ref={menuRef} className="nfc-v2-step-menu" role="menu"
                aria-label="选择工作流步骤类型" onKeyDown={handleMenuKeyDown}
                onBlur={(event) => {
                  // Let native Tab/Shift+Tab move focus before closing the menu.
                  if (!event.currentTarget.contains(event.relatedTarget)) setMenuOpen(false);
                }}>
                {menuItems.map(item => (
                  <button key={item.key} type="button" role="menuitem"
                    className="nfc-v2-step-menu-item"
                    onClick={() => handleAddStep(item.key)}>
                    <ConsoleIcon name={item.icon} size={16} />
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        <p className="nfc-step-end-note">
          <ConsoleIcon name="shield-check" size={16} />
          隔离归档是最后一步
        </p>
      ))}
    </div>
  );
};
