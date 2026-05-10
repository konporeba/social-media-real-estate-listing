import { useEffect } from 'react';
import { useAppStore } from '../store';

const TOAST_CONFIG: Record<string, { bg: string; icon: string }> = {
  info:    { bg: 'bg-gray-800 border-blue-600/30 text-blue-200',   icon: 'ℹ' },
  success: { bg: 'bg-gray-800 border-green-600/30 text-green-200', icon: '✓' },
  error:   { bg: 'bg-gray-800 border-red-600/30 text-red-200',     icon: '✕' },
  warning: { bg: 'bg-gray-800 border-yellow-600/30 text-yellow-200', icon: '⚠' },
};

function Toast({ id, message, type }: { id: string; message: string; type: string }) {
  const removeToast = useAppStore((s) => s.removeToast);
  const cfg = TOAST_CONFIG[type] ?? TOAST_CONFIG['info'];

  useEffect(() => {
    const t = setTimeout(() => removeToast(id), 5000);
    return () => clearTimeout(t);
  }, [id, removeToast]);

  return (
    <div className={`flex items-start gap-3 px-4 py-3 rounded-xl border text-sm shadow-2xl animate-slide-in-right ${cfg.bg}`}>
      <span className="text-base mt-0.5 opacity-60 shrink-0 font-mono leading-none">{cfg.icon}</span>
      <span className="flex-1 leading-snug">{message}</span>
      <button
        onClick={() => removeToast(id)}
        className="opacity-40 hover:opacity-80 transition-opacity text-xs mt-0.5 shrink-0 leading-none"
      >
        ✕
      </button>
    </div>
  );
}

export default function ToastContainer() {
  const toasts = useAppStore((s) => s.toasts);
  if (!toasts.length) return null;
  return (
    <div className="fixed bottom-5 right-5 flex flex-col gap-2 z-50 w-80">
      {toasts.map((t) => (
        <Toast key={t.id} {...t} />
      ))}
    </div>
  );
}
