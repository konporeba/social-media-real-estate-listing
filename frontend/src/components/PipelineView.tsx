import React from 'react';
import type { RunDetail, RunStatus } from '../types';

const STAGES: { keys: RunStatus[]; label: string; filterKey: string }[] = [
  { keys: ['discovering'],                              label: 'Discover',  filterKey: 'discover' },
  { keys: ['generating', 'validating', 'regenerating'], label: 'Generate',  filterKey: 'generate' },
  { keys: ['awaiting_review', 'scheduled', 'rejected'], label: 'Review',    filterKey: 'review'   },
  { keys: ['publishing'],                               label: 'Publish',   filterKey: 'publish'  },
  { keys: ['completed', 'partial', 'failed'],           label: 'Done',      filterKey: 'done'     },
];

function stageIndex(status: RunStatus): number {
  for (let i = 0; i < STAGES.length; i++) {
    if (STAGES[i].keys.includes(status)) return i;
  }
  return -1;
}

const STATUS_BADGE: Partial<Record<RunStatus, string>> = {
  scheduled: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/25',
  completed: 'bg-green-500/15 text-green-600 dark:text-green-400 border-green-500/25',
  partial:   'bg-yellow-500/15 text-yellow-600 dark:text-yellow-400 border-yellow-500/25',
  rejected:  'bg-gray-500/15 text-gray-500 border-gray-500/25',
  failed:    'bg-red-500/15 text-red-500 dark:text-red-400 border-red-500/25',
};

function CheckIcon() {
  return (
    <svg className="w-3.5 h-3.5 md:w-4 md:h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  );
}

function XIcon() {
  return (
    <svg className="w-3.5 h-3.5 md:w-4 md:h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  );
}

interface Props {
  run: RunDetail;
  activeFilter: string | null;
  onStageClick: (stage: string | null) => void;
}

export default function PipelineView({ run, activeFilter, onStageClick }: Props) {
  const activeIdx  = stageIndex(run.status);
  const isTerminal = ['completed', 'partial', 'rejected', 'failed'].includes(run.status);
  const isFailed   = run.status === 'failed' || run.status === 'rejected';

  return (
    <div className="shrink-0 bg-white dark:bg-gray-900 rounded-2xl p-4 md:p-6 border border-gray-200 dark:border-gray-800/80 shadow-sm dark:shadow-xl">
      <div className="flex items-start justify-between mb-2 gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">Run</span>
          <span className="font-mono text-xs text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-md">
            {run.id.slice(0, 8)}
          </span>
          <span className="text-xs text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800/60 px-2 py-0.5 rounded-md">
            {run.triggered_by === 'schedule' ? '⏰ scheduled' : '◎ manual'}
          </span>
        </div>
        <span
          className={`text-xs px-3 py-1 rounded-full font-medium border shrink-0 ${
            STATUS_BADGE[run.status] ?? 'bg-blue-500/15 text-blue-400 border-blue-500/25'
          }`}
        >
          {run.status.replace(/_/g, ' ')}
        </span>
      </div>

      {activeFilter && (
        <p className="text-xs text-blue-400/70 mb-4">
          Showing activity for <span className="font-semibold capitalize">{activeFilter}</span> stage —{' '}
          <button onClick={() => onStageClick(null)} className="underline hover:text-blue-300 transition-colors">
            show all
          </button>
        </p>
      )}
      {!activeFilter && isTerminal && (
        <p className="text-xs text-gray-400 dark:text-gray-600 mb-4">Click a stage to filter the activity log</p>
      )}

      {/* py/my pair gives the ring-offset room to render */}
      <div className="py-2 -my-2">
      <div className="flex items-center">
        {STAGES.map((stage, i) => {
          const isActive      = i === activeIdx && !isTerminal;
          const isDone        = i < activeIdx || (isTerminal && !isFailed);
          const isStageFailed = isFailed && i === activeIdx;
          const isFiltered    = activeFilter === stage.filterKey;

          // Stage clicks only work on terminal runs to filter the activity log
          const isReachable = isTerminal && (isDone || isStageFailed);

          return (
            <React.Fragment key={i}>
              <div className="flex flex-col items-center gap-2 flex-1">
                <button
                  onClick={() => isReachable ? onStageClick(stage.filterKey) : undefined}
                  disabled={!isReachable}
                  title={isReachable ? `Filter by ${stage.label} stage` : `${stage.label} not reached yet`}
                  className={[
                    'w-7 h-7 md:w-9 md:h-9 rounded-full flex items-center justify-center text-sm font-medium transition-all duration-300',
                    isReachable ? 'cursor-pointer' : 'cursor-default',
                    isFiltered ? 'ring-2 ring-offset-2 ring-offset-white dark:ring-offset-gray-900 ring-blue-400 scale-110' : '',
                    isActive      ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/40 animate-pulse-ring' : '',
                    isDone        ? 'bg-green-600/25 text-green-400 border border-green-600/40 hover:bg-green-600/40 hover:border-green-500/60' : '',
                    isStageFailed ? 'bg-red-600/25 text-red-400 border border-red-600/40 hover:bg-red-600/40' : '',
                    !isActive && !isDone && !isStageFailed
                      ? 'bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 border border-gray-300/60 dark:border-gray-700/60'
                      : '',
                  ].filter(Boolean).join(' ')}
                >
                  {isDone ? <CheckIcon /> : isStageFailed ? <XIcon /> : <span className="text-xs">{i + 1}</span>}
                </button>

                <span className={`text-[10px] md:text-[11px] font-medium text-center transition-colors ${
                  isFiltered    ? 'text-blue-400' :
                  isActive      ? 'text-blue-400' :
                  isDone        ? 'text-green-500 dark:text-green-400/60' :
                  isStageFailed ? 'text-red-400/60' :
                  'text-gray-400 dark:text-gray-600'
                }`}>
                  {stage.label}
                </span>
              </div>

              {i < STAGES.length - 1 && (
                <div className="relative flex-1 mb-6 mx-1">
                  <div className="h-px bg-gray-200 dark:bg-gray-800 w-full" />
                  <div
                    className={`absolute inset-y-0 left-0 h-px transition-all duration-700 ${
                      i < activeIdx || (isTerminal && !isFailed) ? 'bg-green-600/50 w-full' : 'w-0'
                    }`}
                  />
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
      </div>

      {run.property_url && (
        <div className="mt-4">
          <a
            href={run.property_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-500/10 border border-blue-200 dark:border-blue-500/25 hover:bg-blue-100 dark:hover:bg-blue-500/20 hover:border-blue-300 dark:hover:border-blue-500/40 transition-colors"
          >
            <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
            View property
            <svg className="w-3 h-3 shrink-0 opacity-60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 19.5l15-15m0 0H8.25m11.25 0v11.25" />
            </svg>
          </a>
        </div>
      )}

      {run.error_message && (run.status === 'failed' || run.status === 'rejected') && (
        <div className="mt-4 text-xs text-red-500 dark:text-red-400 bg-red-50 dark:bg-red-950/30 rounded-xl p-3 font-mono break-all border border-red-200 dark:border-red-900/40">
          {run.error_message}
        </div>
      )}
    </div>
  );
}
