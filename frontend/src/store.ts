import { create } from 'zustand';
import type { PlatformType } from './types';

let _toastCounter = 0;

interface Toast {
  id: string;
  message: string;
  type: 'info' | 'success' | 'error' | 'warning';
}

interface AppState {
  selectedRunId: string | null;
  setSelectedRunId: (id: string | null) => void;

  editBuffers: Record<string, Record<string, string>>;
  setEditBuffer: (runId: string, platform: string, content: string) => void;

  platformSelections: Record<string, Record<PlatformType, boolean>>;
  setPlatformSelection: (runId: string, platform: PlatformType, selected: boolean) => void;

  toasts: Toast[];
  addToast: (message: string, type: Toast['type']) => void;
  removeToast: (id: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  selectedRunId: null,
  setSelectedRunId: (id) => set({ selectedRunId: id }),

  editBuffers: {},
  setEditBuffer: (runId, platform, content) =>
    set((s) => ({
      editBuffers: {
        ...s.editBuffers,
        [runId]: { ...(s.editBuffers[runId] ?? {}), [platform]: content },
      },
    })),

  platformSelections: {},
  setPlatformSelection: (runId, platform, selected) =>
    set((s) => ({
      platformSelections: {
        ...s.platformSelections,
        [runId]: {
          ...(s.platformSelections[runId] ?? { facebook: true, instagram: true, linkedin: true }),
          [platform]: selected,
        },
      },
    })),

  toasts: [],
  addToast: (message, type) =>
    set((s) => ({
      toasts: [...s.toasts, { id: `toast-${++_toastCounter}`, message, type }],
    })),
  removeToast: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
