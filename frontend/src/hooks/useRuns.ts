import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Run, RunDetail } from '../types';

export function useRuns() {
  return useQuery<Run[]>({
    queryKey: ['runs'],
    queryFn: api.getRuns,
    refetchInterval: 10_000,
  });
}

export function useRun(id: string | null) {
  return useQuery<RunDetail>({
    queryKey: ['runs', id],
    queryFn: () => api.getRun(id!),
    enabled: id !== null,
    refetchInterval: 5_000,
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
