import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

class ApiClient {
  private client: AxiosInstance;

  constructor(baseURL: string = API_BASE) {
    this.client = axios.create({
      baseURL,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    this.client.interceptors.request.use(
      (config: InternalAxiosRequestConfig) => {
        const token = localStorage.getItem('auth_token');
        if (token && config.headers) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (error: AxiosError) => Promise.reject(error)
    );

    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        if (error.response?.status === 401) {
          localStorage.removeItem('auth_token');
          window.location.href = '/login';
        }
        return Promise.reject(error);
      }
    );
  }

  async get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
    const response = await this.client.get<T>(url, { params });
    return response.data;
  }

  async post<T>(url: string, data?: unknown): Promise<T> {
    const response = await this.client.post<T>(url, data);
    return response.data;
  }

  async put<T>(url: string, data?: unknown): Promise<T> {
    const response = await this.client.put<T>(url, data);
    return response.data;
  }

  async patch<T>(url: string, data?: unknown): Promise<T> {
    const response = await this.client.patch<T>(url, data);
    return response.data;
  }

  async delete<T>(url: string): Promise<T> {
    const response = await this.client.delete<T>(url);
    return response.data;
  }
}

export const api = new ApiClient();

export interface ServiceNode {
  id: string;
  name: string;
  namespace?: string;
  criticality: string;
  slo_target?: number;
  current_slo?: number;
  error_budget_remaining?: number;
  incident_count_24h: number;
  deployment_count_24h: number;
}

export interface DependencyEdge {
  source: string;
  target: string;
  type: string;
  latency_p99?: number;
  error_rate?: number;
  request_volume?: number;
}

export interface DependencyGraph {
  nodes: ServiceNode[];
  edges: DependencyEdge[];
  updated_at: string;
}

export interface Incident {
  incident_id: string;
  title: string;
  severity: string;
  status: string;
  affected_service: string;
  detected_at: string;
  resolved_at?: string;
  root_cause_candidate?: string;
  confidence?: number;
  remediation_action?: string;
}

export interface IncidentsResponse {
  incidents: Incident[];
}

export interface RiskScore {
  service: string;
  namespace?: string;
  risk_score: number;
  risk_level: 'low' | 'medium' | 'high' | 'critical';
  factors: Record<string, number>;
  last_deployment?: string;
  last_deployment_time?: string;
  deployment_count_24h?: number;
  incident_count_24h?: number;
}

export interface RiskScoresResponse {
  scores: RiskScore[];
  updated_at: string;
}

export interface RiskHistoryEntry {
  timestamp: string;
  service: string;
  deployment_id?: string;
  risk_score: number;
  risk_level: string;
  factors: Record<string, number>;
}

export interface SLOBurnData {
  timestamp: string;
  service: string;
  slo_name: string;
  target: number;
  actual: number;
  burn_rate: number;
  error_budget_remaining: number;
}

export interface SLOStatus {
  services: Array<{
    name: string;
    namespace: string;
    slos: Array<{
      name: string;
      target: number;
      current: number;
      error_budget_remaining: number;
      burn_rate: number;
      status: string;
    }>;
  }>;
  updated_at: string;
}

export interface CorrelationAccuracy {
  period_start: string;
  period_end: string;
  total_incidents: number;
  precision_at_1: number;
  precision_at_3: number;
  recall: number;
  mean_time_to_detection_seconds: number;
  model_version: string;
}

export interface ChangeEvent {
  eventId: string;
  serviceName: string;
  changeType: string;
  source: string;
  timestamp: string;
  author?: string;
  description?: string;
  deploymentId?: string;
  newVersion?: string;
  pipelineName?: string;
  status?: string;
}

export interface ChangesResponse {
  changes: Record<string, unknown>[];
  count: number;
}

export interface BlastRadiusResponse {
  source_service: string;
  affected_services: string[];
  hop_count: number;
  total_affected: number;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  timestamp: string;
}

export interface ReadinessResponse {
  status: string;
}

export interface IncidentDetail {
  incident_id: string;
  title: string;
  severity: string;
  status: string;
  affected_service: string;
  affected_namespace: string;
  slo_name: string;
  error_budget_burn_rate: number;
  detected_at: string;
  started_at: string;
  resolved_at: string;
  candidates: Array<{
    change_event_id: string;
    service_name: string;
    change_type: string;
    source: string;
    timestamp: string;
    confidence_score: number;
    evidence: string;
  }>;
  root_cause_candidate: string;
  confidence: number;
  remediation_action: string;
  remediation_status: string;
}

export interface LoginResponse {
  token: string;
  user: {
    sub: string;
    user_id?: string;
    tenant_id?: string;
    email?: string;
    name: string;
    roles: string[];
  };
}

export const graphApi = {
  getDependencyGraph: (namespace?: string, includeMetrics = true) =>
    api.get<DependencyGraph>('/v1/graph/dependency', { namespace, include_metrics: includeMetrics }),

  getBlastRadius: (serviceName: string, namespace?: string, maxHops = 3) =>
    api.get<BlastRadiusResponse>(`/v1/graph/blast-radius/${serviceName}`, { namespace, max_hops: maxHops }),
};

export const incidentsApi = {
  getIncidents: (params?: {
    limit?: number;
    offset?: number;
    severity?: string;
    status?: string;
    service?: string;
    start_time?: string;
    end_time?: string;
  }) => api.get<Incident[]>('/v1/incidents', params),

  getIncidentDetail: (incidentId: string) =>
    api.get<IncidentDetail>(`/v1/incidents/${incidentId}`),

  updateStatus: (incidentId: string, status: string) =>
    api.patch<{ status: string; incident_id: string; new_status: string }>(`/v1/incidents/${incidentId}/status`, { status }),
};

export const sloApi = {
  getBurnRate: (params?: {
    service?: string;
    slo_name?: string;
    hours?: number;
    interval_minutes?: number;
  }) => api.get<SLOBurnData[]>('/v1/slo/burn-rate', params),

  getStatus: (service?: string) =>
    api.get<SLOStatus>('/v1/slo/status', { service }),
};

export const riskApi = {
  getHistory: (params?: {
    service?: string;
    hours?: number;
    limit?: number;
  }) => api.get<RiskHistoryEntry[]>('/v1/risk/history', params),

  getCurrent: (service?: string) =>
    api.get<RiskScoresResponse>('/v1/risk/current', { service }),
};

export const correlationApi = {
  getAccuracy: (days = 30) =>
    api.get<CorrelationAccuracy>('/v1/correlation/accuracy', { days }),

  getAccuracyHistory: (days = 90) =>
    api.get<{ history: Array<{
      date: string;
      total_incidents: number;
      precision_at_1: number;
      precision_at_3: number;
      recall: number;
      model_version: string;
    }> }>('/v1/correlation/accuracy/history', { days }),
};

export const changesApi = {
  getChanges: (params?: {
    service?: string;
    source?: string;
    change_type?: string;
    hours?: number;
    limit?: number;
  }) => api.get<ChangesResponse>('/v1/changes', params),
};

export const healthApi = {
  check: () => api.get<HealthResponse>('/health'),
  ready: () => api.get<ReadinessResponse>('/ready'),
};

export const authApi = {
  login: (email: string, password: string) =>
    api.post<LoginResponse>('/v1/auth/login', { email, password }),
  register: (email: string, password: string, name?: string) =>
    api.post<LoginResponse>('/v1/auth/register', { email, password, name }),
  loginWithTokenId: (tokenId: string, username?: string) =>
    api.post<LoginResponse>('/v1/auth/login', { token_id: tokenId, username }),
  updateMe: (name: string) =>
    api.patch<LoginResponse>('/v1/auth/me', { name }),
};

export interface SourceUrlsResponse {
  sources: Record<string, string>;
}

export interface SourceConfig {
  token?: string;
  has_token: boolean;
  repositories: string[];
  organizations: string[];
  webhook_secret: boolean;
  username: string;
  configured: boolean;
  base_url?: string;
  groups?: string[];
  projects?: string[];
  applications?: string[];
  app_projects?: string[];
  jobs?: string[];
  job_folders?: string[];
  organization?: string;
  workspaces?: string[];
  status?: string;
  last_successful_poll?: string | null;
  last_event_received?: string | null;
  events_last_24h?: number;
  last_error?: string | null;
}

export interface SourceConfigsResponse {
  sources: Record<string, SourceConfig>;
}

export interface GithubTestResult {
  ok: boolean;
  username?: string;
  repo_check?: string | null;
  error?: string;
}

export interface SourceTestResult {
  ok: boolean;
  kind?: string;
  username?: string;
  organization?: string;
  applications?: number;
  error?: string | null;
}

export interface ApiKeyResponse {
  tenant_id: string;
  client_id: string | null;
  api_key: string;
  usage: string;
}

export const settingsApi = {
  getSourceUrls: () => api.get<SourceUrlsResponse>('/v1/settings/source-urls'),
  updateSourceUrls: (sources: Record<string, string>) =>
    api.put<SourceUrlsResponse>('/v1/settings/source-urls', { sources }),
  getSourceConfigs: () => api.get<SourceConfigsResponse>('/v1/settings/sources'),
  updateGithubSource: (cfg: {
    token?: string;
    repositories?: string[];
    organizations?: string[];
    webhook_secret?: string;
    username?: string;
  }) => api.put<SourceConfigsResponse>('/v1/settings/sources/github', cfg),
  testGithub: (token: string, repo?: string) =>
    api.post<GithubTestResult>('/v1/settings/sources/github/test', { token, repo }),
  updateNativeSource: (kind: string, cfg: Record<string, unknown>) =>
    api.put<SourceConfigsResponse>(`/v1/settings/sources/${kind}`, cfg),
  deleteNativeSource: (kind: string) =>
    api.delete<SourceConfigsResponse>(`/v1/settings/sources/${kind}`),
  testNativeSource: (kind: string, cfg: Record<string, unknown>) =>
    api.post<SourceTestResult>(`/v1/settings/sources/${kind}/test`, cfg),
  getSourceHealthHistory: () =>
    api.get<{ history: Array<{ ts: string; state: string; events: number }>; statuses: Record<string, unknown> }>('/v1/settings/sources/health'),
  getApiKey: () => api.get<ApiKeyResponse>('/v1/settings/api-key'),
  rotateApiKey: () => api.post<ApiKeyResponse>('/v1/settings/api-key/rotate'),
};