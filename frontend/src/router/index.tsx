import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { MainLayout } from '../layouts/MainLayout';
import { LoginPage } from '../pages/Login';
import { DashboardPage } from '../pages/Dashboard';
import { IndexesPage } from '../pages/Indexes';
import { ScansPage } from '../pages/Scans';
import { ScanDetailPage } from '../pages/Scans/ScanDetail';
import { PathMatchPage } from '../pages/PathMatch';
import { RenamePage } from '../pages/Rename';
import { BatchPage } from '../pages/Batch';
import { OrganizerPage } from '../pages/Organizer';
import { PlansPage } from '../pages/Plans';
import { PlanDetailPage } from '../pages/Plans/PlanDetail';
import { TasksPage } from '../pages/Tasks';
import { AuditPage } from '../pages/Audit';
import { SettingsPage } from '../pages/Settings';

export const AppRouter: React.FC = () => {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<MainLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="indexes" element={<IndexesPage />} />
        <Route path="scans" element={<ScansPage />} />
        <Route path="scans/:id" element={<ScanDetailPage />} />
        <Route path="path-match" element={<PathMatchPage />} />
        <Route path="rename" element={<RenamePage />} />
        <Route path="batch" element={<BatchPage />} />
        <Route path="organizer" element={<OrganizerPage />} />
        <Route path="plans" element={<PlansPage />} />
        <Route path="plans/:id" element={<PlanDetailPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
};
