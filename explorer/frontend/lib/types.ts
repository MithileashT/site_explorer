// ──────────────────────────────────────────────
// Health
// ──────────────────────────────────────────────
export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  model: string;
  faiss_entries: number;
  sites_loaded: number;
}

// ──────────────────────────────────────────────
// Bag Analysis
// ──────────────────────────────────────────────
export interface LogEntry {
  timestamp: number;
  datetime?: string;
  level: string;
  node: string;
  message: string;
}

export interface BagLogAnalysisResponse {
  bag_path: string;
  duration_secs: number;
  total_messages: number;
  error_count: number;
  warning_count: number;
  engine_hypothesis: string;
  llm_summary: string;
  log_entries: LogEntry[];
  actual_prompt_tokens?: number;
  actual_completion_tokens?: number;
  actual_total_tokens?: number;
  cost_usd?: number;
}

export interface TimelineBucket {
  t_start: number;
  t_end: number;
  count: number;
  error_count: number;
  warn_count: number;
}

export interface BagTimeline {
  bag_path: string;
  buckets: TimelineBucket[];
}

export interface MapDiffResponse {
  iou_score: number;
  diff_image_b64: string;
  message: string;
}

// ──────────────────────────────────────────────
// Investigation
// ──────────────────────────────────────────────
export interface RankedItem {
  description: string;
  confidence: number;
  evidence: string[];
}

export interface SimilarCase {
  id: string;
  title: string;
  description: string;
  similarity: number;
  resolution: string;
}

export interface OrchestratorResponse {
  status: string;
  confidence_score: number;
  human_intervention_required: boolean;
  issue_summary: string;
  ranked_causes: RankedItem[];
  ranked_solutions: RankedItem[];
  similar_cases: SimilarCase[];
  log_anomaly_summary: string;
  safety_assessment: string;
  raw_analysis: string;
}

export type IncidentImpact =
  | "mission_blocked"
  | "degraded"
  | "intermittent"
  | "unknown";

export interface InvestigationFormInput {
  incident_summary: string;
  observed_impact: IncidentImpact;
  detected_at?: string;
  grafana_link?: string;
  config_changed: boolean;
}

export interface SlackThreadMessage {
  ts: string;
  datetime: string;
  user: string;
  text: string;
}

export interface SlackThreadInvestigationRequest {
  slack_thread_url: string;
  description: string;
  site_id?: string;
  include_bots?: boolean;
  max_messages?: number;
  model_override?: string;
}

export interface SlackLLMStatusResponse {
  status: "online" | "offline";
  text_model: string;
  text_ready: boolean;
  installed: string[];
  fix?: string;
  providers?: AIProviderInfo[];
  active_provider?: AIProviderInfo;
}

// ──────────────────────────────────────────────
// AI Provider Configuration
// ──────────────────────────────────────────────
export interface AIProviderInfo {
  id: string;
  name: string;
  type: "ollama" | "openai" | "gemini";
}

export interface AIProvidersResponse {
  providers: AIProviderInfo[];
  active: AIProviderInfo;
}

// ──────────────────────────────────────────────
// AI Usage / Cost Dashboard
// ──────────────────────────────────────────────
export interface ModuleUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  request_count: number;
}

export interface AIUsageResponse {
  session_start: number;
  uptime_seconds: number;
  active_model: string;
  active_provider: string;
  modules: Record<string, ModuleUsage>;
  totals: ModuleUsage;
  pricing: Record<string, { input: number; output: number }>;
}

export interface SlackThreadInvestigationResponse {
  status: string;
  workspace?: string;
  channel_id: string;
  thread_ts: string;
  message_count: number;
  participants: string[];
  thread_summary: string;
  key_findings: string[];
  recommended_actions: string[];
  risk_level: "low" | "medium" | "high";
  model_used?: string;
  timeline: SlackThreadMessage[];
  raw_analysis: string;
  actual_prompt_tokens?: number;
  actual_completion_tokens?: number;
  actual_total_tokens?: number;
  cost_usd?: number;
}

// ──────────────────────────────────────────────
// Site / Fleet
// ──────────────────────────────────────────────
export interface SiteInfo {
  id: string;
  name: string;
  description?: string;
  robot_count?: number;
}

export interface NodeData {
  id: string;
  x: number;
  y: number;
  label?: string;
  type?: string;
}

export interface EdgeData {
  from: string;
  to: string;
  weight?: number;
}

export interface SiteData {
  nodes: NodeData[];
  edges: EdgeData[];
  spots?: Record<string, unknown>[];
  storage?: Record<string, unknown>[];
}

export interface MapConfig {
  resolution: number;
  origin: [number, number, number];
  width: number;
  height: number;
}

export interface FleetStatusResponse {
  site_id: string;
  online_robots: number;
  total_robots: number;
  active_missions: number;
  alerts: string[];
}

// ──────────────────────────────────────────────
// Site Map (sootballs_sites)
// ──────────────────────────────────────────────
export interface SiteMapMeta {
  resolution: number;
  origin: [number, number, number];
  width: number;
  height: number;
  b64: string;
}

export interface SiteMapSpot {
  _idx: number;   // unique per-array index, added client-side
  name: string;
  type: string;
  x: number;
  y: number;
  yaw: number;
  robot: string;
  color: string;
}

export interface SiteMapRack {
  section: string;
  row: string;
  label: string;
  x: number;
  y: number;
  orientation: number;
  direction: string;
}

export interface SiteMapRegion {
  type: string;
  id: string | number;
  name: string;
  polygon: [number, number][];
  color: string;
}

export interface SiteMapRobot {
  id: number;
  name: string;
}

export interface SiteMapNode {
  id: number;
  x: number;
  y: number;
  parkable: boolean;
  radius: number;
  meta_kind?: string;
  spin_mode?: number | null;
  spin_turn?: number | null;
}

export interface SiteMapEdge {
  id: number;
  node1: number;
  node2: number;
  directed: boolean;
  speed_scale_estimate?: string;
}

export interface SiteMapData {
  spots: SiteMapSpot[];
  racks: SiteMapRack[];
  regions: SiteMapRegion[];
  robots: SiteMapRobot[];
  nodes: SiteMapNode[];
  edges: SiteMapEdge[];
}

// ──────────────────────────────────────────────
// AR Markers
// ──────────────────────────────────────────────

/** A single AR fiducial marker in world (ROS map frame) coordinates. */
export interface SiteMapMarker {
  /** Aruco marker ID */
  id: number;
  /** World X position (metres) */
  x: number;
  /** World Y position (metres) */
  y: number;
  /** World Z position (metres, usually 0) */
  z: number;
  /** Yaw orientation (radians) */
  yaw: number;
}

export interface SiteMarkers {
  markers: SiteMapMarker[];
}

/** A marker entry that includes the originating site, returned by the all-sites endpoint. */
export interface AllSiteMarker extends SiteMapMarker {
  /** The site this marker belongs to, e.g. "actsgm001" */
  site_id: string;
}

export interface AllSiteMarkers {
  markers: AllSiteMarker[];
  /** Number of sites that had at least one marker */
  site_count: number;
  /** Total number of markers across all sites */
  total: number;
}

// ──────────────────────────────────────────────
// Git Branch Info
// ──────────────────────────────────────────────

export interface CommitInfo {
  hash: string;
  message: string;
  date: string;
}

export interface BranchInfo {
  /** short branch name e.g. "mncyok001" or "main" */
  branch: string;
  /** full remote ref e.g. "origin/mncyok001" */
  ref: string;
  /** true when the site has its own dedicated branch */
  is_site_specific: boolean;
  /** true when a manual override is active */
  is_override: boolean;
  last_commit: CommitInfo | null;
  available_branches: string[];
}

export interface BranchCleanupPlan {
  /** branches that will be kept (main + valid site names) */
  valid_branches: string[];
  /** local remote-tracking refs that would be removed */
  invalid_branches: string[];
  /** site IDs with no dedicated branch (will use main) */
  sites_without_own_branch: string[];
  /** total remote branches before cleanup */
  total_branches: number;
}

export interface BranchCleanupResult {
  /** branches whose local tracking ref was successfully deleted */
  removed: string[];
  /** branches that were kept */
  kept: string[];
  /** branches that failed to be removed */
  errors: string[];
}

// ──────────────────────────────────────────────
// SSE streaming
// ──────────────────────────────────────────────
export type SSEStepType =
  | "start"
  | "bag_analysis"
  | "similarity_search"
  | "llm_analysis"
  | "complete"
  | "error";

export interface SSEEvent {
  step: SSEStepType;
  message: string;
  data?: OrchestratorResponse;
  error?: string;
}

// ──────────────────────────────────────────────
// API error envelope
// ──────────────────────────────────────────────
export interface APIError {
  detail: string;
  status?: number;
}

// ──────────────────────────────────────────────
// Grafana Logs
// ──────────────────────────────────────────────
export interface GrafanaLogLine {
  timestamp_ms: number;
  labels: Record<string, string>;
  line: string;
}

export interface GrafanaLogsResponse {
  site: string;
  hostname: string;
  deployment: string | null;
  from_ms: number;
  to_ms: number;
  line_count: number;
  logs: GrafanaLogLine[];
}

export interface GrafanaStatusResponse {
  status: string;
  grafana_version: string | null;
  org_name: string | null;
  loki_datasources: string[];
  fix: string | null;
}

// ──────────────────────────────────────────────
// Combined Analyse (log + slack)
// ──────────────────────────────────────────────
export interface AnalyseLogEntry {
  timestamp_ms: number;
  level: string;
  hostname: string;
  deployment: string;
  message: string;
  labels: Record<string, string>;
}

export interface AnalyseRequest {
  logs: AnalyseLogEntry[];
  time_from?: string;
  time_to?: string;
  site_id?: string;
  env?: string;
  hostname?: string;
  deployment?: string;
  slack_thread_url?: string;
  issue_description: string;
  analysis_from_ms?: number;
  analysis_to_ms?: number;
}

export interface AnalyseResponse {
  model_used: string;
  has_images: boolean;
  slack_messages: number;
  log_count: number;
  summary: string;
  partial_analysis?: boolean;
  chunks_analysed?: number;
  estimated_tokens?: number;
  actual_prompt_tokens?: number;
  actual_completion_tokens?: number;
  actual_total_tokens?: number;
  cost_usd?: number;
}

// ──────────────────────────────────────────────
// Loki Log Query (new direct-Loki endpoints)
// ──────────────────────────────────────────────
export interface LokiLogLine {
  ts: string;
  line: string;
  labels: Record<string, string>;
}

export interface LokiQueryResponse {
  lines: LokiLogLine[];
  total_count: number;
  limit: number;
  from_ms: number;
  to_ms: number;
}

export interface LokiVolumeBucket {
  ts: number;
  count: number;
}

// ──────────────────────────────────────────────
// Bag Trajectory
// ──────────────────────────────────────────────
export interface TrajectoryPoint {
  x: number;         // world-frame metres
  y: number;         // world-frame metres
  yaw: number;       // radians
  timestamp: number; // Unix time (seconds)
}

export interface TrajectoryResponse {
  bag_path: string;
  site_id: string | null;
  topic: string;
  total_points: number;
  raw_count: number;
  points: TrajectoryPoint[];
  error: string | null;
  frame_id: string | null;  // "map" or "odom" — odom frame may not align with the map
  bag_start_time: number | null;  // true bag start (Unix seconds)
  bag_end_time: number | null;    // true bag end (Unix seconds)
}

export interface BagTopicInfo {
  topic: string;
  msgtype: string;
  count: number;
  is_pose: boolean;
  is_nav: boolean;
  nav_role: string;
  nav_description: string;
}

export interface BagTopicsResponse {
  bag_path: string;
  topics: BagTopicInfo[];
}

export interface NavTopicStatus {
  topic: string;
  role: string;
  description: string;
  available: boolean;
  msgtype: string;
  count: number;
}

export interface NavTopicsResponse {
  bag_path: string;
  nav_topics: NavTopicStatus[];
}

// ──────────────────────────────────────────────
// RIO Bag Fetch
// ──────────────────────────────────────────────
export interface RIOFetchRequest {
  shared_url?: string;
  device?: string;
  filename?: string;
  project_override?: string;
}

export interface RIOFetchResponse {
  bag_path: string;
  filename: string;
  size_mb: number;
  source: "shared_url" | "device_upload";
  extracted_bags?: string[] | null;
}

export interface RIOStatusResponse {
  configured: boolean;
  has_token: boolean;
  has_organization: boolean;
  has_project: boolean;
  rio_cli_available: boolean;
  organization: string;
  project: string;
}

// ──────────────────────────────────────────────
// RIO Device Upload
// ──────────────────────────────────────────────
export interface RIOProject {
  name: string;
  guid: string;
  organization_guid: string;
  org_name?: string;
}

export interface RIOProjectsResponse {
  projects: RIOProject[];
}

export interface RIODevicesRequest {
  project_guid: string;
}

export interface RIODevicesResponse {
  devices: string[];
  project_guid: string;
}

export interface RIOTriggerUploadRequest {
  project_guid: string;
  organization_guid: string;
  device_names: string[];
  start_time_epoch: number;
  end_time_epoch: number;
  max_upload_rate_mbps?: number;
  display_start?: string;    // e.g. "2026-03-22T10:00" (user's local TZ)
  display_end?: string;      // e.g. "2026-03-22T11:00"
  timezone_label?: string;   // e.g. "JST", "IST", "UTC+05:30"
  utc_offset_minutes?: number; // e.g. 540 for JST, -300 for EST
  site_code?: string;          // e.g. "ash-kki-001" — RIO project name
}

export interface RIODeviceUploadStatus {
  status: "uploading" | "error";
  message: string;
  filename?: string | null;
  url?: string | null;
  request_uuid?: string | null;
}

export interface RIOTriggerUploadResponse {
  results: Record<string, RIODeviceUploadStatus>;
}

export interface RIOUploadJobResponse {
  job_id: string;
}

export interface RIOUploadEvent {
  event: "link_ready" | "discovering" | "compressing" | "uploading" | "done" | "error" | "job_done";
  device?: string;
  message?: string;
  url?: string;
  filename?: string;
  request_uuid?: string;
}

// ── RIO Discover Bags Preview ─────────────────────────────
export interface RIODiscoverBagsRequest {
  project_guid: string;
  device_name: string;
  start_time_epoch: number;
  end_time_epoch: number;
}

export interface RIODiscoverBagsResponse {
  device_name: string;
  bags: string[];
  count: number;
}