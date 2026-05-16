import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Run, RunDetail } from '../types';

export function useMode() {
  return useQuery<{ publish_mode: string }>({
    queryKey: ['mode'],
    queryFn: api.getMode,
    staleTime: Infinity,
  });
}

export function useRuns() {
  return useQuery<Run[]>({
    queryKey: ['runs'],
    queryFn: api.getRuns,
    refetchInterval: 10_000,
  });
}

const TERMINAL_STATUSES = new Set(['completed', 'partial', 'rejected', 'failed']);

export function useRun(id: string | null) {
  return useQuery<RunDetail>({
    queryKey: ['runs', id],
    queryFn: () => api.getRun(id!),
    enabled: id !== null,
    // Terminal runs never change — no polling needed.
    // Active runs are updated via SSE (useRunStream), with 5s polling as fallback.
    refetchInterval: (query) =>
      query.state.data && TERMINAL_STATUSES.has(query.state.data.status) ? false : 5_000,
  });
}

export function useStartRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { triggered_by: string; property_url?: string }) =>
      api.startRun(vars),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['runs'] }),
  });
}

export function useApproveRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      posts,
    }: {
      id: string;
      posts: { facebook: string; instagram: string; linkedin: string };
    }) => api.approveRun(id, posts),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['runs', vars.id] });
      qc.invalidateQueries({ queryKey: ['runs'] });
    },
  });
}

export function useRejectRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.rejectRun(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ['runs', id] });
      qc.invalidateQueries({ queryKey: ['runs'] });
    },
  });
}

export function useRetryPublish() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, platforms }: { id: string; platforms: string[] }) =>
      api.retryPublish(id, platforms),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['runs', vars.id] });
      qc.invalidateQueries({ queryKey: ['runs'] });
    },
  });
}

export function useDeleteRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteRun(id),
    onSuccess: (_data, id) => {
      qc.removeQueries({ queryKey: ['runs', id] });
      qc.invalidateQueries({ queryKey: ['runs'] });
    },
  });
}
