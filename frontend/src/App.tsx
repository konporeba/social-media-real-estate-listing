import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import ErrorBoundary from './components/ErrorBoundary';
import ManualTrigger from './components/ManualTrigger';
import RunHistory from './components/RunHistory';
import PipelineView from './components/PipelineView';
import PostEditor, { DraftReview } from './components/PostEditor';
import ActivityLog from './components/ActivityLog';
import ToastContainer from './components/Toast';
import { useAppStore } from './store';
import { useRun } from './hooks/useRuns';
import { useRunStream } from './hooks/useRunStream';

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
    <div className="flex flex-col flex-1 min-h-0 gap-5 animate-fade-in">
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

export default function App() {
  const selectedRunId = useAppStore((s) => s.selectedRunId);

  return (
    <ErrorBoundary>
      {/* h-screen + flex-col eliminates the body scrollbar entirely */}
      <div className="h-screen flex flex-col bg-gray-950 text-gray-100 overflow-hidden">
        <header className="flex-none border-b border-gray-800/80 px-6 py-3.5 flex items-center justify-between bg-gray-950/95 backdrop-blur-sm z-30">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center shadow-lg shadow-blue-900/40">
              <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <div>
              <h1 className="text-sm font-semibold tracking-tight text-gray-100 leading-none">Social Agent</h1>
              <p className="text-xs text-gray-600 leading-none mt-0.5">Real Estate Automation</p>
            </div>
          </div>
          <ManualTrigger />
        </header>

        {/* flex-1 min-h-0 lets this row shrink to fit the remaining viewport height */}
        <div className="flex flex-1 min-h-0">
          <aside className="w-72 border-r border-gray-800/80 overflow-y-auto shrink-0">
            <RunHistory />
          </aside>

          <main className="flex-1 min-h-0 overflow-hidden p-6 flex flex-col">
            {selectedRunId ? (
              <ErrorBoundary>
                <RunDetail key={selectedRunId} runId={selectedRunId} />
              </ErrorBoundary>
            ) : (
              <div className="flex flex-col items-center justify-center flex-1 gap-4 text-center animate-fade-in">
                <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center shadow-xl shadow-blue-900/40">
                  <svg className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                </div>
                <div>
                  <p className="text-gray-400 text-sm font-medium">No run selected</p>
                  <p className="text-gray-700 text-xs mt-1">Select a run from the sidebar or trigger a new one</p>
                </div>
              </div>
            )}
          </main>
        </div>

        <ToastContainer />
      </div>
    </ErrorBoundary>
  );
}
