import { useState } from 'react';
import { createPortal } from 'react-dom';
import { useStartRun } from '../hooks/useRuns';
import { useAppStore } from '../store';

export default function ManualTrigger() {
  const [url, setUrl] = useState('');
  const [open, setOpen] = useState(false);
  const { mutateAsync, isPending } = useStartRun();
  const addToast = useAppStore((s) => s.addToast);
  const setSelectedRunId = useAppStore((s) => s.setSelectedRunId);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await mutateAsync({
        triggered_by: 'manual',
        property_url: url.trim() || undefined,
      });
      addToast('Run started.', 'success');
      setSelectedRunId(res.run_id);
      setUrl('');
      setOpen(false);
    } catch (err) {
      addToast(`Failed to start run: ${(err as Error).message}`, 'error');
    }
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 rounded-lg font-medium transition-all shadow-lg shadow-blue-600/20 hover:shadow-blue-600/30"
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
        New Run
      </button>

      {open && createPortal(
        <div className="fixed inset-0 z-50 overflow-y-auto animate-fade-in">
          <div className="flex min-h-full items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <form
            onSubmit={handleSubmit}
            className="bg-gray-900 rounded-2xl border border-gray-700/60 p-6 w-96 shadow-2xl animate-slide-up"
          >
            <div className="flex items-center gap-3 mb-5">
              <div className="w-9 h-9 rounded-xl bg-blue-600/20 border border-blue-600/30 flex items-center justify-center shrink-0">
                <svg className="w-4 h-4 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <div>
                <h2 className="text-sm font-semibold text-gray-100">Trigger new run</h2>
                <p className="text-xs text-gray-500">Manually start the pipeline</p>
              </div>
            </div>

            <div className="mb-5">
              <label className="block text-xs font-medium text-gray-400 mb-1.5">
                Property URL
                <span className="text-gray-600 font-normal ml-1">(optional)</span>
              </label>
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://dprealestate.es/..."
                className="w-full bg-gray-800 rounded-xl px-3.5 py-2.5 text-sm text-gray-100 focus:outline-none focus:ring-1 focus:ring-blue-600/60 border border-gray-700/60 placeholder:text-gray-600 hover:border-gray-600/60 transition-colors"
              />
              <p className="text-[11px] text-gray-600 mt-1.5">Leave blank for auto-discovery</p>
            </div>

            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors rounded-xl hover:bg-gray-800"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isPending}
                className="flex items-center gap-2 px-5 py-2 text-sm text-white bg-blue-600 hover:bg-blue-500 rounded-xl disabled:opacity-50 font-medium transition-all shadow-lg shadow-blue-600/20"
              >
                {isPending ? (
                  <>
                    <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Starting…
                  </>
                ) : (
                  'Start run'
                )}
              </button>
            </div>
          </form>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
