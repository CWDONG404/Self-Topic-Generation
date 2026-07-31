import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';

const DashboardPage = lazy(() =>
  import('./pages/DashboardPage').then((module) => ({ default: module.DashboardPage })),
);
const GeneratePage = lazy(() =>
  import('./pages/GeneratePage').then((module) => ({ default: module.GeneratePage })),
);
const JobPage = lazy(() =>
  import('./pages/JobPage').then((module) => ({ default: module.JobPage })),
);
const KnowledgePage = lazy(() =>
  import('./pages/KnowledgePage').then((module) => ({ default: module.KnowledgePage })),
);
const NotFoundPage = lazy(() =>
  import('./pages/NotFoundPage').then((module) => ({ default: module.NotFoundPage })),
);
const PaperReviewPage = lazy(() =>
  import('./pages/PaperReviewPage').then((module) => ({ default: module.PaperReviewPage })),
);
const PapersPage = lazy(() =>
  import('./pages/PapersPage').then((module) => ({ default: module.PapersPage })),
);
const PracticePage = lazy(() =>
  import('./pages/PracticePage').then((module) => ({ default: module.PracticePage })),
);
const ResultsPage = lazy(() =>
  import('./pages/ResultsPage').then((module) => ({ default: module.ResultsPage })),
);
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((module) => ({ default: module.SettingsPage })),
);
const WrongAnswersPage = lazy(() =>
  import('./pages/WrongAnswersPage').then((module) => ({ default: module.WrongAnswersPage })),
);

export default function App() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-slate-500">正在加载页面…</div>}>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<DashboardPage />} />
          <Route path="knowledge" element={<KnowledgePage />} />
          <Route path="generate" element={<GeneratePage />} />
          <Route path="jobs/:jobId" element={<JobPage />} />
          <Route path="papers" element={<PapersPage />} />
          <Route path="papers/:paperId" element={<PaperReviewPage />} />
          <Route path="practice/:sessionId" element={<PracticePage />} />
          <Route path="results/:sessionId" element={<ResultsPage />} />
          <Route path="wrong-answers" element={<WrongAnswersPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="404" element={<NotFoundPage />} />
          <Route path="*" element={<Navigate to="/404" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
