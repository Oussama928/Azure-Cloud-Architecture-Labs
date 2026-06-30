import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';
import { 
  graphApi, incidentsApi, sloApi, riskApi, correlationApi, changesApi, healthApi, authApi, settingsApi,
  type DependencyGraph, type Incident, type SLOBurnData, type SLOStatus,
  type RiskScoresResponse, type RiskHistoryEntry, type CorrelationAccuracy,
  type ChangesResponse, type BlastRadiusResponse, type IncidentDetail,
  type HealthResponse, type ReadinessResponse, type SourceUrlsResponse, type SourceConfigsResponse, type ApiKeyResponse,
} from './client';

export function useDependencyGraph(namespace?: string, includeMetrics = true) {
  return useQuery<DependencyGraph>({
    queryKey: ['dependencyGraph', namespace, includeMetrics],
    queryFn: () => graphApi.getDependencyGraph(namespace, includeMetrics),
    refetchInterval: 30000,
    staleTime: 15000,
  });
}

export function useBlastRadius(serviceName: string, namespace?: string, maxHops = 3) {
  return useQuery<BlastRadiusResponse>({
    queryKey: ['blastRadius', serviceName, namespace, maxHops],
    queryFn: () => graphApi.getBlastRadius(serviceName, namespace, maxHops),
    enabled: !!serviceName,
    staleTime: 30000,
  });
}

export function useIncidents(params?: {
  limit?: number;
  offset?: number;
  severity?: string;
  status?: string;
  service?: string;
  start_time?: string;
  end_time?: string;
}) {
  return useQuery<Incident[]>({
    queryKey: ['incidents', params],
    queryFn: () => incidentsApi.getIncidents(params),
    refetchInterval: 30000,
    staleTime: 15000,
  });
}

export function useIncidentDetail(incidentId: string) {
  return useQuery<IncidentDetail>({
    queryKey: ['incident', incidentId],
    queryFn: () => incidentsApi.getIncidentDetail(incidentId),
    enabled: !!incidentId,
    staleTime: 30000,
  });
}

export function useUpdateIncidentStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ incidentId, status }: { incidentId: string; status: string }) =>
      incidentsApi.updateStatus(incidentId, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['incident'] });
      queryClient.invalidateQueries({ queryKey: ['incidents'] });
    },
  });
}

export function useSLOBurnRate(params?: {
  service?: string;
  slo_name?: string;
  hours?: number;
  interval_minutes?: number;
}) {
  return useQuery<SLOBurnData[]>({
    queryKey: ['sloBurnRate', params],
    queryFn: () => sloApi.getBurnRate(params),
    refetchInterval: 60000,
    staleTime: 30000,
  });
}

export function useSLOStatus(service?: string) {
  return useQuery<SLOStatus>({
    queryKey: ['sloStatus', service],
    queryFn: () => sloApi.getStatus(service),
    refetchInterval: 60000,
    staleTime: 30000,
  });
}

export function useRiskScores(service?: string) {
  return useQuery<RiskScoresResponse>({
    queryKey: ['riskScores', service],
    queryFn: () => riskApi.getCurrent(service),
    refetchInterval: 60000,
    staleTime: 30000,
  });
}

export function useRiskHistory(params?: {
  service?: string;
  hours?: number;
  limit?: number;
}) {
  return useQuery<RiskHistoryEntry[]>({
    queryKey: ['riskHistory', params],
    queryFn: () => riskApi.getHistory(params),
    staleTime: 60000,
  });
}

export function useCorrelationAccuracy(days = 30) {
  return useQuery<CorrelationAccuracy>({
    queryKey: ['correlationAccuracy', days],
    queryFn: () => correlationApi.getAccuracy(days),
    staleTime: 300000,
  });
}

export function useCorrelationAccuracyHistory(days = 90) {
  return useQuery<{
    history: Array<{
      date: string;
      total_incidents: number;
      precision_at_1: number;
      precision_at_3: number;
      recall: number;
      model_version: string;
    }>;
  }>({
    queryKey: ['correlationAccuracyHistory', days],
    queryFn: () => correlationApi.getAccuracyHistory(days),
    staleTime: 300000,
  });
}

export function useChanges(params?: {
  service?: string;
  source?: string;
  change_type?: string;
  hours?: number;
  limit?: number;
}) {
  return useQuery<ChangesResponse>({
    queryKey: ['changes', params],
    queryFn: () => changesApi.getChanges(params),
    refetchInterval: 30000,
    staleTime: 15000,
  });
}

export function useHealth() {
  return useQuery<HealthResponse>({
    queryKey: ['health'],
    queryFn: () => healthApi.check(),
    refetchInterval: 60000,
  });
}

export function useReadiness() {
  return useQuery<ReadinessResponse>({
    queryKey: ['readiness'],
    queryFn: () => healthApi.ready(),
    refetchInterval: 30000,
  });
}

export function useRefreshDashboard() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['dependencyGraph'] }),
        queryClient.invalidateQueries({ queryKey: ['incidents'] }),
        queryClient.invalidateQueries({ queryKey: ['riskScores'] }),
        queryClient.invalidateQueries({ queryKey: ['sloStatus'] }),
        queryClient.invalidateQueries({ queryKey: ['sloBurnRate'] }),
      ]);
    },
  });
}

export function useLogin() {
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      authApi.login(email, password),
  });
}

export function useRegister() {
  return useMutation({
    mutationFn: ({ email, password, name }: { email: string; password: string; name?: string }) =>
      authApi.register(email, password, name),
  });
}

export interface AuthUser {
  sub: string;
  user_id?: string;
  tenant_id?: string;
  email?: string;
  name: string;
  roles: string[];
}

export function useUpdateMe() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => authApi.updateMe(name),
    onSuccess: (data) => {
      localStorage.setItem('auth_token', data.token);
      localStorage.setItem('auth_user', JSON.stringify(data.user));
      queryClient.invalidateQueries({ queryKey: ['authUser'] });
    },
  });
}

export function useAuthUser(): AuthUser | null {
  const raw = localStorage.getItem('auth_user');
  return useMemo(() => {
    if (!raw) return null;
    try { return JSON.parse(raw); } catch { return null; }
  }, [raw]);
}

export function useSourceUrls() {
  return useQuery<SourceUrlsResponse>({
    queryKey: ['sourceUrls'],
    queryFn: () => settingsApi.getSourceUrls(),
    staleTime: 300000,
  });
}

export function useSourceConfigs() {
  return useQuery<SourceConfigsResponse>({
    queryKey: ['sourceConfigs'],
    queryFn: () => settingsApi.getSourceConfigs(),
    staleTime: 60000,
  });
}

export function useUpdateGithubSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (cfg: Parameters<typeof settingsApi.updateGithubSource>[0]) =>
      settingsApi.updateGithubSource(cfg),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sourceConfigs'] });
    },
  });
}

export function useTestGithub() {
  return useMutation({
    mutationFn: ({ token, repo }: { token: string; repo?: string }) =>
      settingsApi.testGithub(token, repo),
  });
}

export function useTestNativeSource() {
  return useMutation({
    mutationFn: ({ kind, cfg }: { kind: string; cfg: Record<string, unknown> }) =>
      settingsApi.testNativeSource(kind, cfg),
  });
}

export function useUpdateNativeSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, cfg }: { kind: string; cfg: Record<string, unknown> }) =>
      settingsApi.updateNativeSource(kind, cfg),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sourceConfigs'] });
    },
  });
}

export function useDeleteNativeSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (kind: string) => settingsApi.deleteNativeSource(kind),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sourceConfigs'] });
    },
  });
}

export function useSourceHealthHistory() {
  return useQuery({
    queryKey: ['sourceHealthHistory'],
    queryFn: () => settingsApi.getSourceHealthHistory(),
    refetchInterval: 30000,
  });
}

export function useUpdateSourceUrls() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sources: Record<string, string>) => settingsApi.updateSourceUrls(sources),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sourceUrls'] });
    },
  });
}

export function useApiKey() {
  return useQuery<ApiKeyResponse>({
    queryKey: ['apiKey'],
    queryFn: () => settingsApi.getApiKey(),
    staleTime: 300000,
  });
}

export function useRotateApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => settingsApi.rotateApiKey(),
    onSuccess: (data) => queryClient.setQueryData(['apiKey'], data),
  });
}