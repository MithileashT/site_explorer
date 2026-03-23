import axios from "axios";
import type {
  HealthResponse,
  BagLogAnalysisResponse,
  BagTimeline,
  MapDiffResponse,
  OrchestratorResponse,
  SiteInfo,
  SiteData,
  MapConfig,
  FleetStatusResponse,
  SSEEvent,
  SiteMapMeta,
  SiteMapData,
  SiteMarkers,
  AllSiteMarkers,
  BranchInfo,
  BranchCleanupPlan,
  BranchCleanupResult,
  IncidentImpact,
  SlackThreadInvestigationRequest,
  SlackThreadInvestigationResponse,
  SlackLLMStatusResponse,
  TrajectoryResponse,
  BagTopicsResponse,
  NavTopicsResponse,
  AIProvidersResponse,
  AIUsageResponse,
  RIOFetchRequest,
  RIOFetchResponse,
  RIOStatusResponse,
  RIOProjectsResponse,
  RIODevicesRequest,
  RIODevicesResponse,
  RIOTriggerUploadRequest,
  RIOUploadJobResponse,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const http = axios.create({
  baseURL: `${BASE}/api/v1`,
  timeout: 300_000,
  headers: { "Content-Type": "application/json" },
});

// Rewrite the Axios error message to the FastAPI `detail` string so every
// catch block automatically receives a human-readable message instead of the
// generic "Request failed with status code NNN".
http.interceptors.response.use(
  res => res,
  err => {
    const detail = err?.response?.data?.detail;
    if (detail && typeof detail === "string") {
      err.message = detail;
    }
    return Promise.reject(err);
  },
);

// ── Health ────────────────────────────────────────────────────────────────────

export async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await http.get<HealthResponse>("/health");
  return data;
}

// ── Sites ─────────────────────────────────────────────────────────────────────

export async function listSites(): Promise<SiteInfo[]> {
  const { data } = await http.get<SiteInfo[]>("/sites");
  return data;
}

// REVIEW: possibly unused — no callers found in app/ or components/
export async function getSiteConfig(siteId: string): Promise<MapConfig> {
  const { data } = await http.get<MapConfig>(`/sites/${siteId}/config`);
  return data;
}

// REVIEW: possibly unused — no callers found in app/ or components/
export async function getSiteMapB64(siteId: string, darkMode = true): Promise<string | null> {
  try {
    const { data } = await http.get<{ b64: string; width: number; height: number }>(
      `/sites/${siteId}/map?dark_mode=${darkMode}`
    );
    return data.b64 || null;
  } catch {
    return null;
  }
}

// REVIEW: possibly unused — no callers found in app/ or components/
export async function getSiteData(siteId: string): Promise<SiteData> {
  const { data } = await http.get<SiteData>(`/sites/${siteId}/data`);
  return data;
}

export async function getFleetStatus(siteId: string): Promise<FleetStatusResponse> {
  const { data } = await http.get<FleetStatusResponse>(`/fleet/status?site_id=${siteId}`);
  return data;
}

// ── Bags ──────────────────────────────────────────────────────────────────────

export async function uploadBag(file: File): Promise<{ bag_path: string; size_mb: number }> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await http.post<{ bag_path: string; size_mb: number }>(
    "/bags/upload",
    form,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return data;
}

export async function fetchTimeline(bagPath: string, nBuckets = 60): Promise<BagTimeline> {
  const { data } = await http.get<BagTimeline>(
    `/bags/timeline?bag_path=${encodeURIComponent(bagPath)}&n_buckets=${nBuckets}`
  );
  return data;
}

export async function analyzeBag(
  bagPath: string,
  windowStart?: number,
  windowEnd?: number,
  modelOverride?: string
): Promise<BagLogAnalysisResponse> {
  const { data } = await http.post<BagLogAnalysisResponse>("/bags/analyze", {
    bag_path: bagPath,
    window_start: windowStart,
    window_end: windowEnd,
    model_override: modelOverride,
  });
  return data;
}

export async function runMapDiff(
  bagPath: string,
  topicOverride?: string
): Promise<MapDiffResponse> {
  const { data } = await http.post<MapDiffResponse>("/bags/mapdiff", {
    bag_path: bagPath,
    topic_override: topicOverride,
  });
  return data;
}

export async function extractBagTrajectory(
  bagPath: string,
  siteId?: string,
  maxPoints = 4000,
  topicOverride?: string,
  smooth = true
): Promise<TrajectoryResponse> {
  const { data } = await http.post<TrajectoryResponse>("/bags/trajectory", {
    bag_path:       bagPath,
    site_id:        siteId ?? null,
    max_points:     maxPoints,
    topic_override: topicOverride ?? null,
    smooth,
  });
  return data;
}

export async function listBagTopics(
  bagPath: string
): Promise<BagTopicsResponse> {
  const { data } = await http.get<BagTopicsResponse>("/bags/topics", {
    params: { bag_path: bagPath },
  });
  return data;
}

export async function listNavTopics(
  bagPath: string
): Promise<NavTopicsResponse> {
  const { data } = await http.get<NavTopicsResponse>("/bags/nav-topics", {
    params: { bag_path: bagPath },
  });
  return data;
}

// ── RIO Bag Fetch ─────────────────────────────────────────────────────────────

export async function getRIOStatus(): Promise<RIOStatusResponse> {
  const { data } = await http.get<RIOStatusResponse>("/bags/rio/status");
  return data;
}

export async function fetchBagFromRIO(params: RIOFetchRequest): Promise<RIOFetchResponse> {
  const { data } = await http.post<RIOFetchResponse>("/bags/rio/fetch", params);
  return data;
}

// ── RIO Device Upload ─────────────────────────────────────────────────────────

export async function getRIOProjects(): Promise<RIOProjectsResponse> {
  const { data } = await http.get<RIOProjectsResponse>("/bags/rio/projects");
  return data;
}

export async function getRIODevices(req: RIODevicesRequest): Promise<RIODevicesResponse> {
  const { data } = await http.post<RIODevicesResponse>("/bags/rio/devices", req);
  return data;
}

export async function triggerRIOUpload(req: RIOTriggerUploadRequest): Promise<RIOUploadJobResponse> {
  const { data } = await http.post<RIOUploadJobResponse>("/bags/rio/trigger-upload", req);
  return data;
}

export async function discoverRIOBags(req: import("./types").RIODiscoverBagsRequest): Promise<import("./types").RIODiscoverBagsResponse> {
  const { data } = await http.post<import("./types").RIODiscoverBagsResponse>("/bags/rio/discover-bags", req);
  return data;
}

/**
 * Subscribe to SSE progress events for an upload job.
 * Returns the EventSource so callers can close it.
 */
export function subscribeUploadStatus(
  jobId: string,
  onEvent: (ev: import("./types").RIOUploadEvent) => void,
  onDone: () => void,
  onError?: (err: Event) => void,
): EventSource {
  const url = `${BASE}/api/v1/bags/rio/upload-status/${encodeURIComponent(jobId)}`;
  const es = new EventSource(url);
  es.onmessage = (msg) => {
    try {
      const parsed = JSON.parse(msg.data);
      onEvent(parsed);
      if (parsed.event === "job_done") {
        es.close();
        onDone();
      }
    } catch { /* ignore parse errors */ }
  };
  es.onerror = (err) => {
    es.close();
    onError?.(err);
    onDone();
  };
  return es;
}

// ── Investigation ─────────────────────────────────────────────────────────────

export async function investigate(payload: {
  title?: string;
  description: string;
  bag_path?: string;
  site_id?: string;
  grafana_link?: string;
  slack_url?: string;
  sw_version?: string;
  config_changed?: boolean;
  observed_impact?: IncidentImpact;
  detected_at?: string;
}): Promise<OrchestratorResponse> {
  const { data } = await http.post<OrchestratorResponse>("/investigate", payload);
  return data;
}

/**
 * Opens a native EventSource to the SSE investigation endpoint.
 * Returns an unsubscribe function.
 */
export function streamInvestigation(
  params: {
    title?: string;
    description: string;
    bag_path?: string;
    site_id?: string;
  },
  onEvent: (event: SSEEvent) => void,
  onError?: (err: Event) => void
): () => void {
  const qs = new URLSearchParams({
    ...(params.title ? { title: params.title } : {}),
    description: params.description,
    ...(params.bag_path ? { bag_path: params.bag_path } : {}),
    ...(params.site_id ? { site_id: params.site_id } : {}),
  });
  const es = new EventSource(`${BASE}/api/v1/investigate/stream?${qs}`);
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data) as SSEEvent);
    } catch {
      /* ignore malformed frames */
    }
  };
  if (onError) es.onerror = onError;
  return () => es.close();
}

// ── Site Map (sootballs_sites) ────────────────────────────────────────────────

export async function listSiteMapSites(): Promise<{ id: string; name: string }[]> {
  const { data } = await http.get("/sitemap/sites");
  return data;
}

export async function getSiteMapMeta(siteId: string, darkMode = true): Promise<SiteMapMeta> {
  const { data } = await http.get<SiteMapMeta>(`/sitemap/${siteId}/map?dark_mode=${darkMode}`);
  return data;
}

export async function getSiteMapData(siteId: string): Promise<SiteMapData> {
  const { data } = await http.get<SiteMapData>(`/sitemap/${siteId}/data`);
  data.nodes = data.nodes ?? [];
  data.edges = data.edges ?? [];
  // Stamp a unique index on every spot so duplicate names never cause key collisions
  data.spots = data.spots.map((s, i) => ({ ...s, _idx: i }));
  return data;
}

export async function getSiteMarkers(siteId: string): Promise<SiteMarkers> {
  const { data } = await http.get<SiteMarkers>(`/sitemap/${siteId}/markers`);
  return data;
}

export async function getAllSiteMarkers(): Promise<AllSiteMarkers> {
  const { data } = await http.get<AllSiteMarkers>(`/sitemap/markers`);
  return data;
}

// ── Sitemap — Git Branch ──────────────────────────────────────────────────────

export async function getSiteBranchInfo(siteId: string): Promise<BranchInfo> {
  const { data } = await http.get<BranchInfo>(`/sitemap/${siteId}/branch`);
  return data;
}

export async function setSiteBranch(siteId: string, branch: string): Promise<BranchInfo> {
  const { data } = await http.post<BranchInfo>(`/sitemap/${siteId}/branch`, { branch });
  return data;
}

export async function clearSiteBranch(siteId: string): Promise<BranchInfo> {
  const { data } = await http.delete<BranchInfo>(`/sitemap/${siteId}/branch`);
  return data;
}

export async function syncSiteRepo(): Promise<{ branches_found: number }> {
  const { data } = await http.post<{ branches_found: number }>("/sitemap/sync");
  return data;
}

export async function getBranchCleanupPlan(): Promise<BranchCleanupPlan> {
  const { data } = await http.get<BranchCleanupPlan>("/sitemap/cleanup/plan");
  return data;
}

export async function runBranchCleanup(): Promise<BranchCleanupResult> {
  const { data } = await http.post<BranchCleanupResult>("/sitemap/cleanup");
  return data;
}

// ── Slack Investigation ─────────────────────────────────────────────────────

export async function investigateSlackThread(
  payload: SlackThreadInvestigationRequest
): Promise<SlackThreadInvestigationResponse> {
  // LLM inference on CPU can take several minutes — use a dedicated long timeout.
  const { data } = await http.post<SlackThreadInvestigationResponse>(
    "/slack/investigate",
    payload,
    { timeout: 720_000 },  // 12 minutes
  );
  return data;
}

/**
 * Stream investigation summary via SSE.
 * Yields text chunks as the LLM generates them, then a structured result.
 * @param onChunk  called with each text fragment
 * @param onDone   called when the stream finishes
 * @param onError  called on stream error
 * @param onResult called with the full structured response when available
 * @returns an AbortController to cancel the stream
 */
export function investigateSlackThreadStream(
  payload: SlackThreadInvestigationRequest,
  onChunk: (text: string) => void,
  onDone: () => void,
  onError: (err: string) => void,
  onResult?: (result: SlackThreadInvestigationResponse) => void,
): AbortController {
  const controller = new AbortController();
  const url = `${BASE}/api/v1/slack/investigate/stream`;

  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok || !res.body) {
        onError(`Stream failed: ${res.status}`);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const evt = JSON.parse(line.slice(6));
          if (evt.type === "chunk") onChunk(evt.text);
          else if (evt.type === "result" && onResult) { onResult(evt.data as SlackThreadInvestigationResponse); }
          else if (evt.type === "done") { onDone(); return; }
          else if (evt.type === "error") { onError(evt.message); return; }
        }
      }
      onDone();
    })
    .catch((err) => {
      if (err.name !== "AbortError") onError(String(err));
    });

  return controller;
}

export async function getSlackLLMStatus(): Promise<SlackLLMStatusResponse> {
  const { data } = await http.get<SlackLLMStatusResponse>("/slack/status");
  return data;
}

// ── AI Provider Configuration ───────────────────────────────────────────────

export async function getAIProviders(): Promise<AIProvidersResponse> {
  const { data } = await http.get<AIProvidersResponse>("/ai/providers");
  return data;
}

export async function setAIProvider(providerId: string): Promise<AIProvidersResponse> {
  const { data } = await http.post<AIProvidersResponse>("/ai/provider", {
    provider_id: providerId,
  });
  return data;
}

export async function fetchAIUsage(): Promise<AIUsageResponse> {
  const { data } = await http.get<AIUsageResponse>("/ai/usage");
  return data;
}

export async function resetAIUsage(): Promise<void> {
  await http.post("/ai/usage/reset");
}

// ── Grafana ─────────────────────────────────────────────────────────────────

import type {
  GrafanaLogsResponse,
  GrafanaStatusResponse,
  AnalyseRequest,
  AnalyseResponse,
  LokiQueryResponse,
  LokiVolumeBucket,
} from "./types";

export async function getGrafanaStatus(): Promise<GrafanaStatusResponse> {
  const { data } = await http.get<GrafanaStatusResponse>("/grafana/status");
  return data;
}

export async function fetchGrafanaLogs(params: {
  site: string;
  hostname?: string;
  deployment?: string;
  filter?: string;
  from_ms?: number;
  to_ms?: number;
  max_lines?: number;
  datasource?: string;
}): Promise<GrafanaLogsResponse> {
  const { data } = await http.get<GrafanaLogsResponse>("/grafana/logs", { params });
  return data;
}

// ── Combined AI Analyse ─────────────────────────────────────────────────────

export async function analyseLogsAndSlack(payload: AnalyseRequest): Promise<AnalyseResponse> {
  const { data } = await http.post<AnalyseResponse>("/investigate/analyse", payload);
  return data;
}

// ── Log Viewer (Grafana-style) ──────────────────────────────────────────────

export async function fetchLogHostnames(
  env: string,
  site: string,
  datasource?: string,
): Promise<string[]> {
  const { data } = await http.get<string[]>("/logs/hostnames", {
    params: { env, site, datasource },
  });
  return data;
}

export async function fetchLogDeployments(
  env: string,
  site: string,
  hostname?: string,
  datasource?: string,
): Promise<string[]> {
  const { data } = await http.get<string[]>("/logs/deployments", {
    params: { env, site, hostname, datasource },
  });
  return data;
}

export async function fetchLogs(params: {
  env: string;
  site: string;
  hostname?: string;
  deployment?: string;
  search?: string;
  exclude?: string;
  from_ms?: number;
  to_ms?: number;
  max_lines?: number;
}): Promise<GrafanaLogsResponse> {
  const { data } = await http.get<GrafanaLogsResponse>("/logs", { params });
  return data;
}

// ── Loki Direct Endpoints (new) ─────────────────────────────────────────────

export async function fetchLogEnvironments(): Promise<string[]> {
  const { data } = await http.get<string[]>("/logs/environments");
  return data;
}

export async function fetchLogSites(env: string): Promise<string[]> {
  const { data } = await http.get<string[]>("/logs/sites", { params: { env } });
  return data;
}

export async function fetchLogHostnamesV2(
  env: string,
  site: string,
): Promise<string[]> {
  const { data } = await http.get<string[]>("/logs/hostnames", {
    params: { env, site },
  });
  return data;
}

export async function fetchLogDeploymentsV2(
  env: string,
  site: string,
  hostname: string,
): Promise<string[]> {
  const { data } = await http.get<string[]>("/logs/deployments", {
    params: { env, site, hostname },
  });
  return data;
}

export async function fetchLogVolume(params: {
  env: string;
  site: string;
  hostname?: string;
  deployment?: string;
  from?: number;
  to?: number;
}): Promise<LokiVolumeBucket[]> {
  const { data } = await http.get<LokiVolumeBucket[]>("/logs/volume", { params });
  return data;
}

export async function fetchLogQuery(params: {
  env: string;
  site: string;
  hostname?: string;
  deployment?: string;
  search?: string;
  exclude?: string;
  from?: number;
  to?: number;
  limit?: number;
}): Promise<LokiQueryResponse> {
  const { data } = await http.get<LokiQueryResponse>("/logs/query", { params });
  return data;
}
