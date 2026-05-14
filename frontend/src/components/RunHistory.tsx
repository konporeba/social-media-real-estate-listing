import { useRuns, useRetryPublish, useDeleteRun } from '../hooks/useRuns';
import { useAppStore } from '../store';
import type { Run, RunStatus } from '../types';

const STATUS_CONFIG: Record<RunStatus, { dot: string; label: string; text: string }> = {
  pending:         { dot: 'bg-gray-500',                 label: 'pending',     text: 'text-gray-500'  },
  discovering:     { dot: 'bg-blue-400 animate-pulse',   label: 'discovering', text: 'text-blue-400'  },
  generating:      { dot: 'bg-blue-400 animate-pulse',   label: 'generating',  text: 'text-blue-400'  },
  validating:      { dot: 'bg-blue-400 animate-pulse',   label: 'validating',  text: 'text-blue-400'  },
  regenerating:    { dot: 'bg-blue-400 animate-pulse',   label: 'regenerating',text: 'text-blue-400'  },
  awaiting_review: { dot: 'bg-yellow-400 animate-pulse', label: 'review',      text: 'text-yellow-400'},
  publishing:      { dot: 'bg-green-400 animate-pulse',  label: 'publishing',  text: 'text-green-400' },
  completed:       { dot: 'bg-green-500',                label: 'done',        text: 'text-green-400' },
  partial:         { dot: 'bg-yellow-500',               label: 'partial',     text: 'text-yellow-400'},
  rejected:        { dot: 'bg-gray-600',                 label: 'rejected',    text: 'text-gray-500'  },
  failed:          { dot: 'bg-red-500',                  label: 'failed',      text: 'text-red-400'   },
};

// dprealestate.es URL parsing helpers
const TRANSACTION_MAP: Record<string, string> = {
  sprzedaz: 'Sprzedaż',
  wynajem:  'Wynajem',
};
const PROPERTY_TYPE_MAP: Record<string, string> = {
  mieszkanie: 'Mieszkanie',
  dom:        'Dom',
};

const SKIP_SEGMENTS = new Set(['en', 'es', 'pl', 'fr', 'de', 'pt', 'property', 'properties', 'listing', 'listings', 'sale', 'rent', 'buy', 'item', 'detail', 'details', 'view']);

function deriveRunTitle(run: Run): string {
  if (run.property_title) return run.property_title;
  if (!run.property_url) {
    return run.triggered_by === 'schedule' ? 'Scheduled scan' : 'Manual run';
  }
  try {
    const url  = new URL(run.property_url);
    const slug = url.pathname.split('/').filter(Boolean).pop() ?? '';

    // Parse dprealestate.es pattern: {type}-{transaction}-{location...}-{CODE}
    // e.g. mieszkanie-sprzedaz-barcelona-rambla-catalunya-OMS
    for (const [txSlug, txLabel] of Object.entries(TRANSACTION_MAP)) {
      const marker = `-${txSlug}-`;
      const idx    = slug.toLowerCase().indexOf(marker);
      if (idx === -1) continue;

      const typePart  = slug.slice(0, idx).toLowerCase();
      const typeLabel = PROPERTY_TYPE_MAP[typePart]
        ?? typePart.replace(/\b\w/g, (c) => c.toUpperCase());

      // Strip trailing 3-letter category code (OMS/ODS/OWM)
      const rest     = slug.slice(idx + marker.length).replace(/-[A-Za-z]{3}$/i, '');
      const location = rest
        .split('-')
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
        .join(' ');

      return `${typeLabel} | ${txLabel} | ${location}`;
    }

    // Fallback for other URL formats
    const segments = url.pathname
      .split('/')
      .filter(Boolean)
      .filter((s) => !SKIP_SEGMENTS.has(s.toLowerCase()));
    if (segments.length === 0) return url.hostname.replace('www.', '');
    const name = segments
      .slice(-2)
      .join(' ')
      .replace(/[-_]/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase())
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 40);
    return name || url.hostname.replace('www.', '');
  } catch {
    return run.property_url.slice(0, 40);
  }
}

function formatDate(iso: string): string {
  const d  = new Date(iso);
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const yyyy = d.getFullYear();
  const HH = String(d.getHours()).padStart(2, '0');
  const MM = String(d.getMinutes()).padStart(2, '0');
  return `${dd}/${mm}/${yyyy} ${HH}:${MM}`;
}

function formatDuration(startIso: string, endIso: string | null): string | null {
  const end = endIso ? new Date(endIso) : null;
  if (!end) return null;
  const secs = Math.max(0, Math.floor((end.getTime() - new Date(startIso).getTime()) / 1000));
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const rem  = secs % 60;
  if (mins < 60) return rem > 0 ? `${mins}m ${rem}s` : `${mins}m`;
  const hrs  = Math.floor(mins / 60);
  const remM = mins % 60;
  return remM > 0 ? `${hrs}h ${remM}m` : `${hrs}h`;
}

function RunRow({ run }: { run: Run }) {
  const selectedRunId    = useAppStore((s) => s.selectedRunId);
  const setSelectedRunId = useAppStore((s) => s.setSelectedRunId);
  const addToast         = useAppStore((s) => s.addToast);
  const retryMutation    = useRetryPublish();
  const deleteMutation   = useDeleteRun();
  const isSelected       = selectedRunId === run.id;
  const cfg              = STATUS_CONFIG[run.status];
  const title            = deriveRunTitle(run);
  const duration         = formatDuration(run.created_at, run.completed_at);

  const handleRetry = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await retryMutation.mutateAsync({ id: run.id, platforms: ['facebook', 'instagram', 'linkedin'] });
      addToast('Retry-publish started.', 'info');
    } catch (err) {
      addToast(`Retry failed: ${(err as Error).message}`, 'error');
    }
  };

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm('Delete this run? This cannot be undone.')) return;
    try {
      await deleteMutation.mutateAsync(run.id);
      if (selectedRunId === run.id) setSelectedRunId(null);
      addToast('Run deleted.', 'info');
    } catch (err) {
      addToast(`Delete failed: ${(err as Error).message}`, 'error');
    }
  };

  return (
    <div
      onClick={() => setSelectedRunId(isSelected ? null : run.id)}
      className={`group px-4 py-3.5 cursor-pointer border-b border-gray-200/40 dark:border-gray-800/40 transition-all duration-150 border-l-2 ${
        isSelected
          ? 'bg-blue-50 dark:bg-gray-800/50 border-l-blue-500'
          : 'border-l-transparent hover:bg-gray-100 dark:hover:bg-gray-800/25 hover:border-l-gray-200 dark:hover:border-l-gray-700'
      }`}
    >
      <div className="flex items-start justify-between gap-2 mb-0.5">
        <span className="text-xs font-medium text-gray-700 dark:text-gray-300 leading-tight line-clamp-2">{title}</span>
        <div className="flex items-center gap-1.5 shrink-0">
          <div className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
          <span className={`text-[10px] font-medium ${cfg.text}`}>{cfg.label}</span>
        </div>
      </div>
      <div className="flex items-center gap-1.5 mt-0.5">
        <span className="text-xs text-gray-500 dark:text-gray-400">{formatDate(run.created_at)}</span>
        {duration && (
          <>
            <span className="text-xs text-gray-400 dark:text-gray-500">·</span>
            <span className="text-xs text-gray-500 dark:text-gray-400">{duration}</span>
          </>
        )}
      </div>
      <div className="flex items-center mt-1.5">
        {(run.status === 'partial' || run.status === 'failed') && (
          <button
            onClick={handleRetry}
            disabled={retryMutation.isPending}
            className="text-[10px] text-yellow-500/70 hover:text-yellow-400 disabled:opacity-40 transition-colors"
          >
            {retryMutation.isPending ? 'Retrying…' : '↺ Retry publish'}
          </button>
        )}
        <button
          onClick={handleDelete}
          disabled={deleteMutation.isPending}
          className="ml-auto text-[10px] text-red-500/40 hover:text-red-400 disabled:opacity-40 transition-colors opacity-0 group-hover:opacity-100"
        >
          {deleteMutation.isPending ? '…' : '✕ Delete'}
        </button>
      </div>
    </div>
  );
}

export default function RunHistory() {
  const { data: runs, isLoading, error } = useRuns();

  return (
    <div>
      <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800/80 flex items-center justify-between">
        <span className="text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest">Run History</span>
        {!!runs?.length && (
          <span className="text-[10px] text-gray-600 dark:text-gray-400 bg-gray-200 dark:bg-gray-800 px-1.5 py-0.5 rounded-full">{runs.length}</span>
        )}
      </div>
      {isLoading && (
        <div className="p-4 text-xs text-gray-400 dark:text-gray-600 flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
          Loading…
        </div>
      )}
      {error && <div className="p-4 text-xs text-red-400/80">Failed to load runs.</div>}
      {runs?.map((run) => <RunRow key={run.id} run={run} />)}
      {!isLoading && !error && !runs?.length && (
        <div className="p-6 text-center text-xs text-gray-400 dark:text-gray-700">No runs yet.</div>
      )}
    </div>
  );
}
