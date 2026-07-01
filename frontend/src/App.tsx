import { useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import ErrorBoundary from './components/ErrorBoundary';
import ManualTrigger from './components/ManualTrigger';
import RunHistory from './components/RunHistory';
import PipelineView from './components/PipelineView';
import PostEditor, { DraftReview } from './components/PostEditor';
import ActivityLog from './components/ActivityLog';
import ToastContainer from './components/Toast';
import LoginPage from './components/LoginPage';
import { useAppStore } from './store';
import { useRun } from './hooks/useRuns';
import { useRunStream } from './hooks/useRunStream';
import { useTheme } from './hooks/useTheme';

function SunIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
    </svg>
  );
}

function HamburgerIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  );
}

function RunDetail({ runId }: { runId: string }) {
  const { data: run } = useRun(runId);
  const qc = useQueryClient();
  const [stageFilter, setStageFilter] = useState<string | null>(null);

  useRunStream((e) => {
    if (e.run_id === runId) {
      qc.invalidateQueries({ queryKey: ['runs', runId] });
      qc.invalidateQueries({ queryKey: ['runs'] });
    }
  }, runId);

  if (!run) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm animate-fade-in">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
          Loading…
        </div>
      </div>
    );
  }

  const handleStageClick = (stage: string | null) => {
    setStageFilter((prev) => (prev === stage ? null : stage));
  };

  const showDraftReview = stageFilter === 'review'
    && run.draft_posts.length > 0
    && run.status !== 'awaiting_review';

  return (
    <div className="flex flex-col flex-1 min-h-0 gap-4 md:gap-5 animate-fade-in">
      <PipelineView run={run} activeFilter={stageFilter} onStageClick={handleStageClick} />
      {run.status === 'awaiting_review' ? (
        <PostEditor run={run} />
      ) : showDraftReview ? (
        <DraftReview run={run} onClear={() => setStageFilter(null)} />
      ) : (
        <ActivityLog events={run.events} stageFilter={stageFilter} onClearFilter={() => setStageFilter(null)} />
      )}
    </div>
  );
}

function LogoutIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
    </svg>
  );
}

export default function App() {
  const selectedRunId = useAppStore((s) => s.selectedRunId);
  const setSelectedRunId = useAppStore((s) => s.setSelectedRunId);
  const token = useAppStore((s) => s.token);
  const role = useAppStore((s) => s.role);
  const clearAuth = useAppStore((s) => s.clearAuth);
  const { isDark, toggle } = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [desktopSidebarOpen, setDesktopSidebarOpen] = useState(true);

  if (!token) return <LoginPage />;

  // When the user arrives via the "Review in Dashboard" email link the URL
  // carries ?run_id=<id>. Select that run once and clean up the URL so
  // refreshing doesn't re-select a stale run.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const runId = params.get('run_id');
    if (runId) {
      setSelectedRunId(runId);
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []);

  // Auto-close mobile drawer when a run is selected
  useEffect(() => {
    setSidebarOpen(false);
  }, [selectedRunId]);

  return (
    <ErrorBoundary>
      <div className="h-screen flex flex-col bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100 overflow-hidden">

        {/* Header */}
        <header className="sticky top-0 z-40 shrink-0 border-b border-gray-200 dark:border-gray-800/80 px-4 md:px-6 py-3 md:py-3.5 flex items-center justify-between bg-gray-50/95 dark:bg-gray-950/95 backdrop-blur-sm">
          <div className="flex items-center gap-2 md:gap-3">
            {/* Hamburger — mobile drawer toggle */}
            <button
              onClick={() => setSidebarOpen((o) => !o)}
              className="md:hidden p-2 -ml-1 rounded-lg text-gray-400 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
              aria-label={sidebarOpen ? 'Close run history' : 'Open run history'}
            >
              {sidebarOpen ? <CloseIcon /> : <HamburgerIcon />}
            </button>
            {/* Sidebar toggle — desktop only */}
            <button
              onClick={() => setDesktopSidebarOpen((o) => !o)}
              className="hidden md:flex p-2 -ml-1 rounded-lg text-gray-400 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
              aria-label={desktopSidebarOpen ? 'Hide run history' : 'Show run history'}
            >
              {desktopSidebarOpen ? <CloseIcon /> : <HamburgerIcon />}
            </button>

            <div className="w-7 h-7 md:w-8 md:h-8 rounded-lg bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center shadow-lg shadow-blue-900/40 shrink-0">
              <svg className="w-3.5 h-3.5 md:w-4 md:h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <div>
              <h1 className="text-sm font-semibold tracking-tight text-gray-900 dark:text-gray-100 leading-none">Real Estate Agent</h1>
              <p className="hidden sm:block text-xs text-gray-400 dark:text-gray-600 leading-none mt-0.5">Real Estate Automation</p>
            </div>
          </div>

          <div className="flex items-center gap-1.5 md:gap-2">
            {/* Role badge */}
            <span className="hidden sm:inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 border border-gray-200 dark:border-gray-700/60 select-none">
              {role === 'admin' ? 'Admin' : 'Reviewer'}
            </span>

            <button
              onClick={toggle}
              className="p-2 rounded-lg text-gray-400 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
              aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {isDark ? <SunIcon /> : <MoonIcon />}
            </button>

            {role === 'admin' && <ManualTrigger />}

            <button
              onClick={clearAuth}
              className="p-2 rounded-lg text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
              aria-label="Log out"
              title="Log out"
            >
              <LogoutIcon />
            </button>
          </div>
        </header>

        {/* Body */}
        <div className="relative flex flex-1 min-h-0">

          {/* Mobile backdrop */}
          <div
            className={`fixed inset-0 z-20 bg-black/50 backdrop-blur-sm md:hidden transition-opacity duration-200 ${sidebarOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
            onClick={() => setSidebarOpen(false)}
          />

          {/* Sidebar — drawer on mobile, static on desktop */}
          <aside className={`
            absolute md:static inset-y-0 left-0 z-30 w-72 shrink-0
            border-r border-gray-200 dark:border-gray-800/80
            overflow-y-auto
            bg-gray-50 dark:bg-gray-950
            transition-transform duration-200 ease-in-out
            ${sidebarOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full'}
            ${desktopSidebarOpen ? 'md:translate-x-0' : 'md:hidden'}
          `}>
            <RunHistory />
          </aside>

          {/* Main content */}
          <main className="p-4 md:p-6 flex-1 min-h-0 overflow-hidden flex flex-col">
            {selectedRunId ? (
              <ErrorBoundary>
                <RunDetail key={selectedRunId} runId={selectedRunId} />
              </ErrorBoundary>
            ) : (
              <div className="flex flex-col items-center justify-center flex-1 gap-4 text-center animate-fade-in px-4">
                <div className="w-14 h-14 md:w-16 md:h-16 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center shadow-xl shadow-blue-900/40">
                  <svg className="w-7 h-7 md:w-8 md:h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                </div>
                <div>
                  <p className="text-gray-500 dark:text-gray-400 text-sm font-medium">No run selected</p>
                  <p className="text-gray-400 dark:text-gray-700 text-xs mt-1">
                    <span className="md:hidden">Tap the menu to browse runs or </span>
                    <span className="hidden md:inline">Select a run from the sidebar or </span>
                    trigger a new one
                  </p>
                </div>
                {/* Mobile shortcut to open sidebar */}
                <button
                  onClick={() => setSidebarOpen(true)}
                  className="md:hidden flex items-center gap-2 px-4 py-2 text-sm text-gray-500 dark:text-gray-400 border border-gray-200 dark:border-gray-700 rounded-xl hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                >
                  <HamburgerIcon />
                  Browse runs
                </button>
              </div>
            )}
          </main>
        </div>

        <ToastContainer />
      </div>
    </ErrorBoundary>
  );
}
