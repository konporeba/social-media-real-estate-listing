import type { Run, RunDetail } from '../types';

function getAuthHeader(): Record<string, string> {
  const token = localStorage.getItem('session_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...getAuthHeader(), ...init?.headers },
    ...init,
  });

  if (res.status === 401) {
    localStorage.removeItem('session_token');
    localStorage.removeItem('session_role');
    window.location.reload();
    return undefined as T;
  }

  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  login: (pin: string) =>
    request<{ token: string; role: 'admin' | 'reviewer' }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ pin }),
    }),

  getMode: () => request<{ publish_mode: string }>('/mode'),

  getRuns: () => request<Run[]>('/runs'),

  getRun: (id: string) => request<RunDetail>(`/runs/${id}`),

  startRun: (body: { triggered_by: string; property_url?: string }) =>
    request<{ run_id: string }>('/runs', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  approveRun: (
    id: string,
    body: { facebook: string; instagram: string; linkedin: string },
  ) =>
    request<{ status: string }>(`/runs/${id}/approve`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  rejectRun: (id: string) =>
    request<{ status: string }>(`/runs/${id}/reject`, { method: 'PATCH', body: '{}' }),

  retryPublish: (id: string, platforms: string[]) =>
    request<{ status: string }>(`/runs/${id}/retry-publish`, {
      method: 'POST',
      body: JSON.stringify({ platforms }),
    }),

  deleteRun: (id: string) =>
    request<void>(`/runs/${id}`, { method: 'DELETE' }),
};
