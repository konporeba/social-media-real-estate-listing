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

  // Session auth
  token: string | null;
  role: 'admin' | 'reviewer' | null;
  setAuth: (token: string, role: 'admin' | 'reviewer') => void;
  clearAuth: () => void;
}

const _initToken = localStorage.getItem('session_token');
const _initRole = localStorage.getItem('session_role') as 'admin' | 'reviewer' | null;

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
      toasts: [...s.toasts.slice(-49), { id: `toast-${++_toastCounter}`, message, type }],
    })),
  removeToast: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  token: _initToken,
  role: _initRole,
  setAuth: (token, role) => {
    localStorage.setItem('session_token', token);
    localStorage.setItem('session_role', role);
    set({ token, role });
  },
  clearAuth: () => {
    localStorage.removeItem('session_token');
    localStorage.removeItem('session_role');
    set({ token: null, role: null });
  },
}));
