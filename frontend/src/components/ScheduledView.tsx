import { useState } from 'react';
import type { RunDetail } from '../types';
import { useAppStore } from '../store';
import { usePublishNow, useCancelSchedule } from '../hooks/useRuns';
import { DraftReview } from './PostEditor';
import ActivityLog from './ActivityLog';

export default function ScheduledView({ run }: { run: RunDetail }) {
  const [showActivity, setShowActivity] = useState(false);
  const addToast = useAppStore((s) => s.addToast);

  const publishNowMutation      = usePublishNow();
  const cancelScheduleMutation  = useCancelSchedule();

  const handlePublishNow = async () => {
    try {
      await publishNowMutation.mutateAsync(run.id);
      addToast('Publishing started.', 'success');
    } catch (e) {
      addToast(`Publish failed: ${(e as Error).message}`, 'error');
    }
  };

  const handleCancelSchedule = async () => {
    try {
      await cancelScheduleMutation.mutateAsync(run.id);
      addToast('Schedule cancelled — back to review.', 'info');
    } catch (e) {
      addToast(`Cancel failed: ${(e as Error).message}`, 'error');
    }
  };

  return (
    <div className="flex flex-col flex-1 min-h-0 gap-4 md:gap-5 animate-fade-in">
      <div className="shrink-0 bg-white dark:bg-gray-900 rounded-2xl p-4 md:p-6 border border-amber-300/50 dark:border-amber-700/40 shadow-sm dark:shadow-xl flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
          <div>
            <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">Approved — publishing automatically Thursday at 5:00 PM</p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">You can publish now or cancel the schedule below.</p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={handleCancelSchedule}
            disabled={cancelScheduleMutation.isPending || publishNowMutation.isPending}
            className="px-3 md:px-4 py-2 rounded-xl text-sm text-red-500 dark:text-red-400 border border-red-200 dark:border-red-800/50 hover:bg-red-50 dark:hover:bg-red-950/40 hover:border-red-300 dark:hover:border-red-700/60 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
          >
            {cancelScheduleMutation.isPending ? 'Cancelling…' : 'Cancel Schedule'}
          </button>
          <button
            onClick={handlePublishNow}
            disabled={publishNowMutation.isPending || cancelScheduleMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-lg shadow-blue-600/20 hover:shadow-blue-600/30"
          >
            {publishNowMutation.isPending ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Publishing…
              </>
            ) : (
              'Publish Now'
            )}
          </button>
        </div>
      </div>

      {showActivity ? (
        <ActivityLog events={run.events} stageFilter={null} onClearFilter={() => setShowActivity(false)} />
      ) : (
        <DraftReview run={run} onClear={() => setShowActivity(true)} />
      )}
    </div>
  );
}
