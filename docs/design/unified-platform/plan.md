# Unified AMR Intelligence Platform — Integration Plan

> **Status:** Ready for implementation  
> **Generated:** 2026-03-07  
> **Source repositories:** `aiassist` + `site_commander`  
> **Target:** `unified_platform/`

---

## Executive Summary

Two complementary robotics software systems need to be merged into a single production-grade platform:

| Repository | Role | Core Strength |
|---|---|---|
| `aiassist` | AI/LLM intelligence engine | ROS bag log analysis, LLM-powered incident investigation, structured AI responses |
| `site_commander` | Fleet operations command center | Live site map visualization, robot topology, LiDAR map diff, operational UI |

These are **not competing** — they occupy different layers of the same problem domain. `site_commander` gives operators situational awareness; `aiassist` explains _why_ things went wrong. The integration goal is a single platform where operators can see their fleet, click on a problem, and immediately invoke AI-powered root cause analysis — all from one UI.

---

## 1. Repository Analysis

### 1.1 aiassist — Module Inventory

| Module | Type | Status |
|---|---|---|
| `backend/app/main.py` | FastAPI app factory | Stable |
| `backend/app/routes/health.py` | GET /api/v1/health | Stable |
| `backend/app/routes/upload.py` | POST /api/v1/upload/bag | Stable |
| `backend/app/routes/analysis.py` | POST /api/v1/bag/analyze-logs | Stable |
| `backend/app/routes/timeline.py` | GET /api/v1/bag/timeline | Stable |
| `backend/services/log_extractor.py` | ROSLogExtractor (rosbags) | Stable – handles both ROS1 + ROS2 |
| `backend/services/llm_service.py` | LLMService (Ollama/OpenAI-compat) | Stable – temperature=0.1, 5-section prompt |
| `backend/schemas/bag_analysis.py` | Pydantic v2 models | Stable |
| `backend/core/config.py` | Env-based settings | Stable |
| `backend/core/logging.py` | Structured stdout logger | Stable |
| `analyze_bag.py` (root) | CLI v1 (JST, older prompt) | Superseded — remove |
| `backend/analyze_bag.py` | CLI v2 (UTC, package-aware) | Keep as dev tool |
| `frontend/` | Next.js 16 + Tailwind v4 | Stable – LogVolumeChart, BagUpload, BagLogDebugger |
| `docs/design/amr-master-ai/agent.spec.md` | Planned system (FAISS, Slack, vision) | Input to Phase 4 |

### 1.2 site_commander — Module Inventory

| Module | Type | Status |
|---|---|---|
| `backend/main.py` | FastAPI app + all routes | Stable |
| `backend/data_loader.py` | SiteDataManager (maps, CSVs, JSON graphs) | Stable |
| `backend/data_processor.py` | DataProcessor utilities | Stable (unused in main.py currently) |
| `backend/file_manager.py` | FileManager (bag upload/storage) | Stable — overlaps with aiassist upload |
| `backend/map_processor.py` | LiDAR bag → map diff (IoU score) | Stable — unique capability |
| `backend/log_analyzer_engine.py` | LogAnalyzerEngine (rule-based + LLM prompt builder) | Stable — LLM call not wired |
| `backend/api_log_analyzer.py` | FastAPI router (POST /analyze-log) | Bug: not mounted in main.py |
| `backend/log_analyzer_router.py` | Empty placeholder | Remove |
| `backend/git_manager.py` | GitSyncEngine (shallow clone/pull) | Stable — gitpython missing from requirements |
| `frontend/app.py` | Streamlit UI (Live Ops, Map Doctor, Log Analyzer) | Stable – replace with Next.js |
| `docker-compose.yml` | Docker orchestration | Keep + extend |

### 1.3 External Integrations

| Integration | System | Production State |
|---|---|---|
| Ollama (local LLM) | aiassist | Wired + working |
| OpenAI/GPT-4o compatible | aiassist | Drop-in via env var swap |
| Slack Bot API | aiassist spec | Partially designed, not implemented |
| Grafana Loki | aiassist spec | Designed, not implemented |
| GitHub API | aiassist spec | Designed (version diff), not implemented |
| Git repo (site data) | site_commander | Working via gitpython |
| Filesystem (catkin_ws maps) | site_commander | Working via volume mount |

---

## 2. Feature Mapping

### 2.1 Overlapping Functionality

| Feature | aiassist | site_commander | Resolution |
|---|---|---|---|
| ROS bag file upload | `/api/v1/upload/bag` | `FileManager.save_bag()` + `/analyze-bag` | **Merge** into single upload service |
| ROS bag reading | `ROSLogExtractor` (rosbags, ROS1+2) | `map_processor.py` (rosbag1 only) | **aiassist wins** — handles both ROS versions |
| FastAPI backend | `:8001` | `:8000` | **Merge** into single FastAPI app on `:8000` |
| Health endpoint | `/api/v1/health` | `GET /` (partial) | **aiassist wins** — structured healthcheck |
| Structured logging | `core/logging.py` | No structured logging | **aiassist wins** |
| Log level analysis | `log_extractor.py` + LLMService | `LogAnalyzerEngine` + `_construct_llm_prompt()` | **Merge** — both bring unique value |
| Docker + deployment | Not present | `docker-compose.yml` | **site_commander wins** — extend it |

### 2.2 Unique Capabilities

**From aiassist (keep, carry forward):**
- `LLMService` — full LLM API integration producing 5 structured analysis sections (`log_timeline`, `node_analysis`, `error_analysis`, `pattern_analysis`, `technical_conclusion`)
- `ROSLogExtractor` — `AnyReader`-based parser supporting both ROS1 `.bag` and ROS2 `.db3`
- `LogVolumeChart.tsx` — SVG drag-to-select log histogram (unique, production-quality)
- `BagLogDebugger.tsx` — full analysis UI with stat cards, log table, LLM section renderers
- LLM window filtering + priority sorting
- 5-section structured prompt engineering
- Next.js + Tailwind v4 frontend (modern, extensible)

**From site_commander (keep, carry forward):**
- `SiteDataManager` — multi-site map/graph/spots asset loader with vendor-agnostic column normalisation
- `map_processor.py` — LiDAR bag → map diff with IoU scoring and colour-coded RGBA diff image
- `LogAnalyzerEngine` — rule-based anomaly detection (`TOPIC_DIED`, `LOW_RATE`), hypothesis generation from temporal event clustering, structured `llm_prompt` construction
- `DataProcessor` — coordinate transforms, heatmap generation, graph connectivity analysis
- `GitSyncEngine` — shallow-clone site data repo, production-safe directory clearing
- `docker-compose.yml` — working deployment baseline with volume mounts

### 2.3 Components to Remove

| Component | Reason |
|---|---|
| `aiassist/analyze_bag.py` (root-level) | Superseded by `backend/analyze_bag.py`; JST timezone, older LLM prompt |
| `site_commander/backend/log_analyzer_router.py` | Empty placeholder file |
| `site_commander/frontend/app.py` (Streamlit) | Replaced by unified Next.js frontend |
| `site_commander/frontend/Dockerfile` | Replaced |
| `site_commander/frontend/requirements.txt` | Replaced |
| `site_commander/backend/file_manager.py` | Merged into unified upload service |

---

## 3. System Architecture Design

### 3.1 Architecture Decision: Modular Monolith

**Decision: Single FastAPI backend, modular by domain, shared Next.js frontend**

Rationale:
- Both systems are small enough that microservices would add pure overhead (two engineers, one domain)
- The data flows are tightly coupled (bag upload → log extraction → LLM analysis → frontend display)
- A clean module boundary within a monolith (e.g., `services/sites/` vs `services/logs/`) gives the same isolation benefit without cross-service latency or deployment complexity
- Docker Compose already handles process isolation; add a Redis sidecar for job queuing when needed

**When to reassess:** If the LLM service becomes a bottleneck (GPU contention, multiple models), extract `ai_services/` as a standalone service behind an internal gRPC/HTTP boundary.

### 3.2 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Next.js Frontend (Port 3000)                     │
│  Dashboard │ Fleet Map │ Bag Analyzer │ Log Explorer │ AI Assistant  │
└─────────────────────────────┬───────────────────────────────────────┘
                              │ HTTPS / REST / SSE
┌─────────────────────────────▼───────────────────────────────────────┐
│                 FastAPI Unified Backend (Port 8000)                  │
│                                                                      │
│  /api/v1/health          /api/v1/sites/{id}/map                     │
│  /api/v1/sites           /api/v1/sites/{id}/data                    │
│  /api/v1/bags/upload     /api/v1/bags/timeline                      │
│  /api/v1/bags/analyze    /api/v1/bags/mapdiff                       │
│  /api/v1/investigate     /api/v1/ingest/slack                       │
│  /api/v1/incidents       /api/v1/incidents/stream (SSE)             │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                         Service Layer                                │
│                                                                      │
│  SiteDataManager    ROSLogExtractor    LLMService                   │
│  LogAnalyzerEngine  MapProcessor       GitSyncEngine                │
│  HistoricalMatcher  SlackIngestor      GrafanaParser                │
│  VisionParser       VersionDiffModule  DataProcessor                │
└──────────────┬─────────────────┬───────────────────┬───────────────┘
               │                 │                   │
    ┌──────────▼──────┐ ┌────────▼────────┐ ┌───────▼────────┐
    │  File Storage   │ │  FAISS (vectorDB│ │  Ollama / LLM  │
    │  (bags, maps)   │ │  persisted)     │ │  (localhost)   │
    └─────────────────┘ └─────────────────┘ └────────────────┘
```

### 3.3 Logging & Telemetry Architecture

- Unified structured logger (`core/logging.py` from aiassist, extended with context fields)
- Every request gets a `request_id` header (UUID, generated by middleware)
- All service calls log `{request_id, service, duration_ms, outcome}`
- Error events include `{traceback, bag_path, node_id}` for robotics context
- **Future (Phase 6):** OpenTelemetry traces exported to Jaeger sidecar; Prometheus metrics endpoint at `/metrics`

### 3.4 Database Design

Phase 1–4 use filesystem + FAISS only — no SQL needed yet.

| Store | Technology | Content |
|---|---|---|
| Bag file storage | Local filesystem (`data/bags/`) | Uploaded `.bag` / `.db3` files (UUID named) |
| Map assets | Git-synced filesystem (`data/sites/`) | PGM/PNG maps, YAML configs, CSV spots |
| Vector DB | FAISS (persisted to `data/faiss.index` + `data/metadata.json`) | Incident embeddings for historical similarity |
| Configuration | Environment variables + `.env` | All secrets and service URLs |

**Phase 5+ (if needed):** Add PostgreSQL for structured incident reports, robot health history, and multi-user auth.

---

## 4. Component Integration Plan

### 4.1 Keep As-Is (zero changes, move to new location)

| Component | Current Location | New Location |
|---|---|---|
| `ROSLogExtractor` | `aiassist/backend/services/log_extractor.py` | `backend/services/ros/log_extractor.py` |
| `LLMService` | `aiassist/backend/services/llm_service.py` | `backend/services/ai/llm_service.py` |
| `BagLogAnalysisRequest/Response/LogEntry` | `aiassist/backend/schemas/bag_analysis.py` | `backend/schemas/bag_analysis.py` |
| `SiteDataManager` | `site_commander/backend/data_loader.py` | `backend/services/sites/data_loader.py` |
| `DataProcessor` | `site_commander/backend/data_processor.py` | `backend/services/sites/data_processor.py` |
| `GitSyncEngine` | `site_commander/backend/git_manager.py` | `backend/services/sites/git_manager.py` |
| `map_processor.py` | `site_commander/backend/` | `backend/services/ros/map_processor.py` |
| `LogAnalyzerEngine` | `site_commander/backend/log_analyzer_engine.py` | `backend/services/ros/log_analyzer_engine.py` |
| `core/config.py` | `aiassist/backend/core/config.py` | `backend/core/config.py` (extend with site_commander env vars) |
| `core/logging.py` | `aiassist/backend/core/logging.py` | `backend/core/logging.py` |
| `LogVolumeChart.tsx` | `aiassist/frontend/components/` | `frontend/components/bag-analyzer/LogVolumeChart.tsx` |
| `BagUpload.tsx` | `aiassist/frontend/components/` | `frontend/components/bag-analyzer/BagUpload.tsx` |
| `BagLogDebugger.tsx` | `aiassist/frontend/components/` | `frontend/components/bag-analyzer/BagLogDebugger.tsx` |

### 4.2 Refactor

| Component | Change Required |
|---|---|
| `aiassist/backend/app/main.py` | Merge route registrations; add site_commander routes; add CORS for unified origins |
| `aiassist/backend/app/routes/upload.py` | Rename to `bags.py`; absorb `file_manager.py` logic; unify storage path to `data/bags/` |
| `site_commander/backend/api_log_analyzer.py` | Fix: mount router inside main app; merge into `routes/bags.py` |
| `site_commander/backend/log_analyzer_engine.py` | Wire actual LLM call using `LLMService` (currently builds prompt but never sends it) |
| `aiassist/backend/core/config.py` | Extend with: `SITES_ROOT`, `REPO_URL`, `SITE_SYNC_ENABLED`, `FAISS_PATH`, `META_PATH` |
| `docker-compose.yml` | Extend to include unified backend + Next.js frontend + Ollama sidecar |
| `frontend/app/page.tsx` | Replace single-page shell with multi-page routing (Dashboard, Bag Analyzer, Fleet Map, AI Assistant) |

### 4.3 Merge (two components become one)

| Source A | Source B | Merged Into | Notes |
|---|---|---|---|
| `aiassist routes/upload.py` | `site_commander/file_manager.py` | `routes/bags.py` (upload section) | Single upload endpoint, unified `data/bags/` dir |
| `aiassist routes/analysis.py` | `site_commander/api_log_analyzer.py` | `routes/bags.py` (analysis section) | Both live under `/api/v1/bags/`; aiassist's LLM pipeline is primary |
| `aiassist routes/health.py` | `site_commander GET /` | `routes/health.py` | Add `module_status` field from site_commander |
| `aiassist LLMService` | `site_commander LogAnalyzerEngine._construct_llm_prompt()` | `services/ai/llm_service.py` (extended) | Add `analyze_from_engine_prompt(engine_output)` method |

### 4.4 Remove

| Component | Reason |
|---|---|
| `aiassist/analyze_bag.py` (root) | Older CLI, replaced by `backend/analyze_bag.py` |
| `site_commander/backend/log_analyzer_router.py` | Empty file, no content |
| `site_commander/frontend/` (entire Streamlit frontend) | Replaced by unified Next.js frontend |
| `site_commander/backend/file_manager.py` | Functionality merged into `routes/bags.py` |
| Root-level duplicate imports / dead code in both `main.py` files | Dead code cleanup during merge |

---

## 5. AI System Design

### 5.1 LLM Orchestration

```
Request arrives at /api/v1/bags/analyze or /api/v1/investigate
                │
                ▼
     ┌─────────────────────┐
     │ ROSLogExtractor      │  ← rosbags AnyReader (ROS1 + ROS2)
     │ extract() → filter() │
     └──────────┬──────────┘
                │ raw logs
                ▼
     ┌─────────────────────┐
     │ LogAnalyzerEngine    │  ← rule-based: TOPIC_DIED, LOW_RATE
     │ _detect_anomalies()  │     temporal clustering → hypothesis
     │ _generate_hypothesis │
     └──────────┬──────────┘
                │ events + structured summary
                ▼
     ┌─────────────────────┐
     │ LLMService           │  ← OpenAI-compat API (Ollama or GPT-4o)
     │ generate_log_...()   │     5-section structured prompt
     │ temperature=0.1      │     max_tokens=3500
     └──────────┬──────────┘
                ▼
     BagLogAnalysisResponse (5 sections + log lists + stats)
```

### 5.2 Log Analysis Pipeline

The unified pipeline layers rule-based analysis under the LLM:

1. **Extraction** (`ROSLogExtractor`): Parse `/rosout` + `/rosout_agg` from ROS bag → sorted chronological list of `{timestamp, log_level, node_name, message}` entries.
2. **Window filtering** (`filter_window`): Trim to `incident_timestamp ± window_seconds`.
3. **Rule-based anomaly detection** (`LogAnalyzerEngine`): Per-topic stats, `TOPIC_DIED` events, `LOW_RATE` events, temporal clustering → hypothesis dict.
4. **Priority sorting** (`priority_logs`): FATAL → ERROR → WARN → INFO → DEBUG stable sort.
5. **LLM analysis** (`LLMService`): Inject both filtered logs (120-line cap) and rule-based hypothesis into system+user prompt → structured 5-section response.
6. **Response assembly**: Merge stats + logs + LLM sections + anomaly events into `BagLogAnalysisResponse`.

### 5.3 ROS Bag Analysis

Extended beyond current aiassist (5 new signal detectors from `agent.spec.md`):

| Detector | Topic | Signal |
|---|---|---|
| `detect_localization_jumps()` | `/odom` | Pose jump > 0.5m |
| `detect_scan_dropouts()` | `/scan` | Zero-range laser frames |
| `detect_velocity_spikes()` | `/cmd_vel` | Velocity > physical limit |
| `detect_battery_drop()` | `/battery_state` | Voltage drop > 0.5V in 1s |
| Map diff | `/scan` (full bag) | IoU score vs stored map (from site_commander) |

`detect_all()` aggregates to `{hardware_signals, log_correlation_strength, jumps_detected, scan_dropouts, velocity_spikes, battery_events, evidence}`.

### 5.4 Incident Investigation (Phase 4 — from agent.spec.md)

Full AMR Master AI Assist pipeline integrating both systems:

```
POST /api/v1/investigate
        │
        ├─► ROSLogExtractor + LogAnalyzerEngine + detect_all()
        ├─► GrafanaParser  (if grafana_link provided)
        ├─► SlackIngestor  (if slack_url provided)
        ├─► VisionParser   (if video attached)
        ├─► HistoricalMatcher (FAISS vector similarity)
        └─► InvestigationAIEngine (GPT-4o structured output)
                │
                ▼
        OrchestratorResponse {
            status, confidence_score, human_intervention_required,
            issue_summary, similar_cases, log_anomaly_summary,
            ranked_causes, ranked_solutions, safety_assessment
        }
```

Confidence score weighting (unchanged from spec):
```
Confidence = (0.40 × historical_similarity)
           + (0.30 × log_correlation_strength)
           + (0.15 × version_regression_risk)
           + (0.10 × config_impact)
           + (0.05 × hardware_signals)

< 60% → human_intervention_required = True
```

### 5.5 Knowledge Retrieval (FAISS + Historical Matcher)

- Persisted FAISS L2 index at `data/faiss.index` + JSON metadata at `data/metadata.json`
- Each ingested incident stores: thread text embedding, root cause, fix, timestamp, confidence score
- Similarity search returns top-k neighbours with similarity percentage
- Manual ingestion endpoint: `POST /api/v1/ingest/manual {text, root_cause, fix}`
- Slack auto-ingestion: `POST /api/v1/ingest/slack {channel_id, limit, root_cause, fix}`

---

## 6. Unified Feature Set

### 6.1 Feature Catalogue

| Feature | Source | Phase |
|---|---|---|
| Robot fleet monitoring (live map, nodes, spots) | site_commander | 3 |
| Site map viewer (occupancy + topology overlay) | site_commander | 3 |
| Map diff / LiDAR change detection (IoU) | site_commander | 3 |
| ROS bag upload (ROS1 + ROS2) | aiassist | 3 |
| ROS bag log timeline histogram | aiassist | 3 |
| Drag-to-select incident window | aiassist | 3 |
| AI log summarization (5 sections) | aiassist | 3 |
| Rule-based anomaly detection | site_commander (LogAnalyzerEngine) | 3 |
| Robot telemetry signal analysis (odom, scan, cmd_vel, battery) | spec | 4 |
| Incident investigation (structured root cause analysis) | spec | 4 |
| Historical incident matching (FAISS similarity) | spec | 4 |
| Slack knowledge base ingestion | spec | 4 |
| Grafana log correlation | spec | 4 |
| Video/vision analysis | spec | 4 |
| Autonomous debugging assistant (SSE streaming) | spec | 4 |
| Knowledge search | spec | 4 |
| AI assistant panel | spec+both | 5 |
| Multi-site fleet overview dashboard | both | 5 |
| Alert / incident badge system | new | 5 |
| Export investigation to PDF | spec | 5 |

---

## 7. UI/UX Consolidation

### 7.1 Single Next.js Application Structure

Replace Streamlit + Next.js split with one Next.js App Router application:

```
frontend/
  app/
    page.tsx                    ← Dashboard (fleet overview, recent incidents)
    fleet/
      page.tsx                  ← Fleet map viewer (replaces Streamlit Live Ops)
      [site_id]/
        page.tsx                ← Per-site detail
    bags/
      page.tsx                  ← Bag upload + timeline
      [bag_id]/
        analyze/page.tsx        ← Bag analysis results
        mapdiff/page.tsx        ← Map diff view (replaces Streamlit Map Doctor)
    investigate/
      page.tsx                  ← Incident investigation form
      [incident_id]/
        page.tsx                ← Investigation results
    knowledge/
      page.tsx                  ← Knowledge base / incident history
      ingest/page.tsx           ← Slack/manual ingestion UI
    assistant/
      page.tsx                  ← AI assistant chat panel
```

### 7.2 Component Design

| Component | Description | Feeds From |
|---|---|---|
| `FleetDashboard` | Site cards grid, robot count, alert badges | `GET /api/v1/sites` |
| `SiteMapViewer` | Plotly/Canvas map with nodes, spots, storage, topology edges overlaid | `GET /api/v1/sites/{id}/map` + `/data` |
| `MapDiffPanel` | Upload bag → diff vs stored map, RGBA diff image, IoU score gauge | `POST /api/v1/bags/mapdiff` |
| `BagUpload` | Drag-drop upload, progress bar, extension validation | `POST /api/v1/bags/upload` |
| `LogVolumeChart` | SVG drag-to-select histogram (existing, keep as-is) | `GET /api/v1/bags/timeline` |
| `BagLogDebugger` | Full analysis UI with stat cards + log table + 5 LLM panels (existing) | `POST /api/v1/bags/analyze` |
| `AnomalyEventTimeline` | Chronological event cards with severity badges | `LogAnalyzerEngine` events |
| `IncidentForm` | Multi-field form (bag upload, description, Grafana URL, Slack URL, video) | `POST /api/v1/investigate` |
| `ConfidenceGauge` | Radial gauge, colour-coded at 60/80 thresholds | `OrchestratorResponse.confidence_score` |
| `RankedCausesPanel` | Ranked causes/solutions list with confidence progress bars | `ranked_causes`, `ranked_solutions` |
| `SimilarCasesTable` | Past incidents with similarity %, root cause, fix | `similar_cases` |
| `HumanInterventionBanner` | Prominent alert when `human_intervention_required: true` | `OrchestratorResponse` |
| `KnowledgeBaseTable` | Paginated stored incidents | `GET /api/v1/incidents` |
| `AIAssistantPanel` | SSE-streaming investigation with live status updates | `GET /api/v1/investigate/stream` |

### 7.3 Design System

- **Framework:** Next.js 16 App Router + Tailwind v4
- **Theme:** Dark (`bg-slate-950`) consistent with existing aiassist frontend
- **Chart library:** Custom SVG (`LogVolumeChart`) + Plotly for maps (from site_commander pattern)
- **Layout:** Left sidebar navigation (fleet/bags/investigate/knowledge/assistant) + main content area

---

## 8. Final Repository Structure

```
unified_platform/
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py                   # FastAPI factory, CORS, router registration
│   │   └── routes/
│   │       ├── health.py             # GET /api/v1/health
│   │       ├── sites.py              # GET /api/v1/sites, /sites/{id}/map, /sites/{id}/data
│   │       ├── bags.py               # POST /api/v1/bags/upload, /bags/analyze, /bags/timeline, /bags/mapdiff
│   │       ├── investigation.py      # POST /api/v1/investigate, GET /api/v1/investigate/stream (SSE)
│   │       ├── knowledge.py          # POST /api/v1/ingest/slack|manual, GET /api/v1/incidents
│   │       └── fleet.py              # GET /api/v1/fleet/status (live aggregation)
│   ├── core/
│   │   ├── config.py                 # Unified settings (extends aiassist config)
│   │   ├── logging.py                # Structured logger with request_id context
│   │   └── middleware.py             # Request ID injection, timing
│   ├── schemas/
│   │   ├── bag_analysis.py           # From aiassist (stable)
│   │   ├── investigation.py          # OrchestratorResponse, SimilarCase, RankedItem (from spec)
│   │   ├── site_data.py              # Site, MapConfig, NodeData (from site_commander)
│   │   └── __init__.py
│   ├── services/
│   │   ├── ros/
│   │   │   ├── log_extractor.py      # ROSLogExtractor (from aiassist)
│   │   │   ├── log_analyzer_engine.py # LogAnalyzerEngine (from site_commander, LLM wired)
│   │   │   ├── map_processor.py      # LiDAR bag map diff (from site_commander)
│   │   │   └── ros_parser.py         # ROSAnomalyDetector with detect_all() (from spec)
│   │   ├── ai/
│   │   │   ├── llm_service.py        # LLMService (from aiassist, extended)
│   │   │   ├── vector_db.py          # HistoricalMatcher FAISS (persisted, from spec)
│   │   │   ├── investigation_engine.py # InvestigationAIEngine (structured output, from spec)
│   │   │   ├── grafana_parser.py     # GrafanaParser Loki integration (from spec)
│   │   │   ├── slack_ingestor.py     # SlackIngestor (from spec)
│   │   │   └── vision_parser.py      # VisionParser video frames (from spec)
│   │   └── sites/
│   │       ├── data_loader.py        # SiteDataManager (from site_commander)
│   │       ├── data_processor.py     # DataProcessor (from site_commander)
│   │       └── git_manager.py        # GitSyncEngine (from site_commander)
│   ├── data/
│   │   ├── bags/                     # Uploaded bag files
│   │   ├── sites/                    # Git-synced site assets (maps, CSVs, JSON)
│   │   ├── faiss.index               # Persisted FAISS vector index
│   │   └── metadata.json             # Incident metadata store
│   └── tests/
│       ├── test_ros_log_extractor.py
│       ├── test_log_analyzer_engine.py
│       ├── test_map_processor.py
│       └── test_llm_service.py
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── next.config.ts
│   ├── tsconfig.json
│   ├── postcss.config.mjs
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── globals.css
│   │   ├── page.tsx                  # Fleet dashboard
│   │   ├── fleet/page.tsx
│   │   ├── fleet/[site_id]/page.tsx
│   │   ├── bags/page.tsx
│   │   ├── bags/[bag_id]/analyze/page.tsx
│   │   ├── bags/[bag_id]/mapdiff/page.tsx
│   │   ├── investigate/page.tsx
│   │   ├── investigate/[id]/page.tsx
│   │   ├── knowledge/page.tsx
│   │   └── assistant/page.tsx
│   ├── components/
│   │   ├── layout/
│   │   │   ├── Sidebar.tsx
│   │   │   └── TopBar.tsx
│   │   ├── dashboard/
│   │   │   ├── FleetDashboard.tsx
│   │   │   └── SiteCard.tsx
│   │   ├── fleet/
│   │   │   ├── SiteMapViewer.tsx     # Plotly map with topology
│   │   │   └── NodeDetailPanel.tsx
│   │   ├── bag-analyzer/
│   │   │   ├── BagUpload.tsx         # From aiassist
│   │   │   ├── LogVolumeChart.tsx    # From aiassist
│   │   │   ├── BagLogDebugger.tsx    # From aiassist
│   │   │   ├── MapDiffPanel.tsx      # From site_commander Map Doctor
│   │   │   └── AnomalyEventTimeline.tsx
│   │   ├── investigation/
│   │   │   ├── IncidentForm.tsx
│   │   │   ├── ConfidenceGauge.tsx
│   │   │   ├── RankedCausesPanel.tsx
│   │   │   ├── SimilarCasesTable.tsx
│   │   │   └── HumanInterventionBanner.tsx
│   │   ├── knowledge/
│   │   │   ├── KnowledgeBaseTable.tsx
│   │   │   └── SlackIngestForm.tsx
│   │   └── assistant/
│   │       └── AIAssistantPanel.tsx  # SSE streaming chat
│   └── lib/
│       ├── api.ts                    # Axios client (extended)
│       └── types.ts                  # All TypeScript interfaces
│
├── infrastructure/
│   ├── docker-compose.yml            # backend + frontend + ollama
│   ├── docker-compose.dev.yml        # hot-reload overrides
│   ├── docker-compose.prod.yml       # resource limits, restart policies
│   └── nginx/
│       └── nginx.conf                # Reverse proxy (frontend :80 → Next.js; /api/ → backend)
│
├── scripts/
│   ├── migrate.sh                    # Copy files from old repos to new structure
│   ├── setup.sh                      # Install deps, create data dirs, seed .env
│   └── seed_faiss.py                 # Ingest existing incident history into vector DB
│
└── docs/
    └── design/
        └── unified-platform/
            └── plan.md               # This file
```

---

## 9. Tech Stack

### 9.1 Confirmed (keep existing)

| Technology | Role | Source |
|---|---|---|
| Python 3.9+ | Backend language | both |
| FastAPI | REST API framework | both |
| Uvicorn | ASGI server | both |
| Pydantic v2 | Data validation + schemas | aiassist |
| rosbags | ROS1 + ROS2 bag parsing | aiassist |
| OpenAI SDK | LLM client (Ollama-compat) | aiassist |
| OpenCV + NumPy | Image processing for map diff | site_commander |
| Pillow | Image encode/decode | site_commander |
| PyYAML | Map config parsing | site_commander |
| pandas | CSV loading for spot data | site_commander |
| gitpython | Site data sync | site_commander |
| Next.js 16 | Frontend framework | aiassist |
| React 19 | UI library | aiassist |
| Tailwind v4 | CSS framework | aiassist |
| Axios | HTTP client | aiassist |
| Docker + Docker Compose | Deployment | site_commander |

### 9.2 Add (new recommendations)

| Technology | Role | Justification |
|---|---|---|
| **FAISS** (`faiss-cpu`) | Vector DB for incident similarity | Required by spec; already architected in `vector_db.py` |
| **Plotly** (`plotly`, `plotly.js` for frontend) | Interactive map visualization | Required by site_commander port to Next.js; already in Streamlit version |
| **sentence-transformers** | Embedding generation for FAISS | Required for `HistoricalMatcher.ingest_thread()` |
| **python-multipart** | File upload parsing | Required by site_commander (already in FastAPI but not in aiassist requirements.txt) |
| **redis** | Job queue + cache | When LLM analysis takes > 2s, queue jobs and poll; cache site map images |
| **pytest + httpx** | Testing | aiassist already uses pytest; httpx enables async FastAPI test client |

### 9.3 Evaluate (post-MVP)

| Technology | Role | Trigger |
|---|---|---|
| **Kafka** | Event streaming for real-time robot telemetry | When live robot status polling is added |
| **OpenTelemetry + Jaeger** | Distributed tracing | When latency debugging becomes critical |
| **Grafana** | Operational dashboards | When Loki integration is live (Phase 4) |
| **LangChain** | LLM orchestration framework | If multi-step agent chains become complex; current single-call pattern may not need it |
| **PostgreSQL** | Structured incident storage | If FAISS + JSON metadata is insufficient for query patterns |

### 9.4 Drop

| Technology | Reason |
|---|---|
| **Streamlit** | Replaced by Next.js; Streamlit cannot support the interactive map + AI streaming UX needed |

---

## 10. Implementation Roadmap

### Phase 1 — Repository Analysis & Scaffold (1–2 days)

**Goal:** Create the target folder structure, migrate files, confirm imports resolve.

- [ ] **1.1** Create `unified_platform/` directory tree
- [ ] **1.2** Run `scripts/migrate.sh`: copy all "Keep As-Is" files to new locations
- [ ] **1.3** Merge `requirements.txt` files (resolve version conflicts; add `faiss-cpu`, `sentence-transformers`, `python-multipart`)
- [ ] **1.4** Merge `backend/core/config.py` — add `SITES_ROOT`, `REPO_URL`, `FAISS_PATH`, `META_PATH`
- [ ] **1.5** Write unified `backend/app/main.py` — mount all six routers
- [ ] **1.6** Verify all imports resolve: `python -c "from backend.services.ros.log_extractor import ROSLogExtractor"`
- [ ] **1.7** Create `backend/data/` directories and placeholder files

**Acceptance:** `uvicorn backend.app.main:app` starts without errors; `GET /api/v1/health` returns 200.

---

### Phase 2 — Backend Route Integration (2–3 days)

**Goal:** All existing endpoints from both systems respond correctly under unified routing.

- [ ] **2.1** Write `routes/health.py` — merge aiassist health + site_commander module status
- [ ] **2.2** Write `routes/sites.py` — port all `SiteDataManager`-backed routes from `site_commander/main.py`
- [ ] **2.3** Write `routes/bags.py`:
  - Merge `upload.py` logic (aiassist) + `FileManager` (site_commander) → single `POST /api/v1/bags/upload`
  - Port `analysis.py` → `POST /api/v1/bags/analyze`
  - Port `timeline.py` → `GET /api/v1/bags/timeline`
  - Port `map_processor.py` → `POST /api/v1/bags/mapdiff`
  - Fix: mount `api_log_analyzer.py` router content here (was never mounted in site_commander)
- [ ] **2.4** Wire `LLMService.generate_log_incident_summary()` into `LogAnalyzerEngine.analyze()` — replace the returned `llm_prompt` string with an actual LLM call
- [ ] **2.5** Write `backend/core/middleware.py` — `request_id` header injection
- [ ] **2.6** Write integration tests for all new routes using `httpx.AsyncClient`

**Acceptance:** All 9 endpoints respond; bag upload → timeline → analyze pipeline works end-to-end with a real `.bag` file.

---

### Phase 3 — Frontend Port (3–4 days)

**Goal:** Next.js app replaces Streamlit; all existing aiassist UI works; new site map viewer added.

- [ ] **3.1** Set up Next.js App Router page structure (8 routes listed in §8)
- [ ] **3.2** Move existing aiassist components to `components/bag-analyzer/` (zero code changes)
- [ ] **3.3** Write `Sidebar.tsx` + `TopBar.tsx` layout shell
- [ ] **3.4** Write `FleetDashboard.tsx` — fetch `/api/v1/sites`, render site cards grid
- [ ] **3.5** Write `SiteMapViewer.tsx` — Plotly Scattergl map (port from Streamlit `app.py`):
  - `to_px()` world → pixel coordinate transform
  - Topology edges (cyan), nodes (red), spots (gold), storage (green)
  - Click selection → `NodeDetailPanel.tsx`
- [ ] **3.6** Write `MapDiffPanel.tsx` — bag upload → `POST /api/v1/bags/mapdiff` → diff image + IoU gauge
- [ ] **3.7** Write `AnomalyEventTimeline.tsx` — render `LogAnalyzerEngine` events from `/api/v1/bags/analyze`
- [ ] **3.8** Update `frontend/lib/api.ts` — add all new endpoint calls
- [ ] **3.9** Update `frontend/lib/types.ts` — add `Site`, `MapConfig`, `SiteData`, `LogAnalysisResult` interfaces
- [ ] **3.10** Verify dark theme consistency across all new components

**Acceptance:** Fleet dashboard loads; site map renders; bag analysis end-to-end works; Streamlit dependency removed.

---

### Phase 4 — AI System Integration (4–5 days)

**Goal:** Full AMR Master AI Assist pipeline (from `agent.spec.md`) wired and working.

- [ ] **4.1** Implement `services/ros/ros_parser.py` — `ROSAnomalyDetector.detect_all()`:
  - `detect_localization_jumps()` from `/odom`
  - `detect_scan_dropouts()` from `/scan`
  - `detect_velocity_spikes()` from `/cmd_vel`
  - `detect_battery_drop()` from `/battery_state`
- [ ] **4.2** Implement `services/ai/vector_db.py` — persisted FAISS `HistoricalMatcher`:
  - On `__init__`: load existing index + metadata if files present
  - `ingest_thread(text, root_cause, fix)`: embed + add + persist
  - `search(query, k=5)`: embed + search → ranked list with similarity %
  - `list_incidents()`: return metadata store copy
- [ ] **4.3** Implement `services/ai/investigation_engine.py` — `InvestigationAIEngine`:
  - `generate_multimodal_analysis(...)` → structured JSON output mode
  - Returns `OrchestratorResponse` typed Pydantic model
  - Implements confidence score formula from §5.4
- [ ] **4.4** Implement `services/ai/grafana_parser.py` — `GrafanaParser`:
  - Query Loki `/loki/api/v1/query_range`
  - Return `{error_count, warn_count, top_errors, log_correlation_strength, evidence}`
  - Safe default on network failure
- [ ] **4.5** Wire `services/ai/slack_ingestor.py` — `SlackIngestor`:
  - `fetch_channel_history(channel_id, limit)` → list of thread dicts
  - Auto-ingestion if `slack_url` in incident report
- [ ] **4.6** Implement `routes/investigation.py`:
  - `POST /api/v1/investigate` — full pipeline (§5.4)
  - `GET /api/v1/investigate/stream` — SSE streaming progress events
- [ ] **4.7** Implement `routes/knowledge.py`:
  - `POST /api/v1/ingest/slack`
  - `POST /api/v1/ingest/manual`
  - `GET /api/v1/incidents`
- [ ] **4.8** Implement `schemas/investigation.py` — `OrchestratorResponse`, `SimilarCase`, `RankedItem`
- [ ] **4.9** Write tests: `test_investigation_engine.py` with mocked LLM + FAISS

**Acceptance:** `POST /api/v1/investigate` with a `.bag` file returns a structured `OrchestratorResponse` with confidence score; FAISS index persists across restarts.

---

### Phase 5 — UI Integration (3–4 days)

**Goal:** Full investigation UI built; AI assistant panel with SSE streaming.

- [ ] **5.1** Write `IncidentForm.tsx` — all incident report fields, file uploads, Grafana/Slack URL inputs
- [ ] **5.2** Write `ConfidenceGauge.tsx` — SVG radial gauge, red < 60, yellow 60–80, green > 80
- [ ] **5.3** Write `RankedCausesPanel.tsx` — ranked causes + solutions with confidence progress bars
- [ ] **5.4** Write `SimilarCasesTable.tsx` — similarity %, root cause, fix
- [ ] **5.5** Write `HumanInterventionBanner.tsx` — prominent red alert banner
- [ ] **5.6** Write `KnowledgeBaseTable.tsx` — paginated incident history, search filter
- [ ] **5.7** Write `SlackIngestForm.tsx` — channel ID + limit + root cause + fix form
- [ ] **5.8** Write `AIAssistantPanel.tsx` — SSE client consuming `/api/v1/investigate/stream`, live status events
- [ ] **5.9** Wire `investigate/page.tsx` — form + result display with all sub-components
- [ ] **5.10** Add "Export to PDF" (browser `window.print()` with print CSS)
- [ ] **5.11** Update `api.ts` with `investigateIncident()`, `streamInvestigation()` (EventSource), `getIncidents()`, `ingestSlack()`, `ingestManual()`

**Acceptance:** Full investigation form submits, confidence gauge renders, similar cases appear, AI panel streams live results.

---

### Phase 6 — Testing & Deployment (2–3 days)

**Goal:** Production-ready, containerised, CI-ready system.

- [ ] **6.1** Write `tests/test_ros_log_extractor.py` (port + extend from aiassist)
- [ ] **6.2** Write `tests/test_log_analyzer_engine.py` (new)
- [ ] **6.3** Write `tests/test_map_processor.py` (new)
- [ ] **6.4** Write `tests/test_llm_service.py` (port from aiassist, update field names)
- [ ] **6.5** Write `tests/test_investigation_engine.py` (mocked LLM + FAISS)
- [ ] **6.6** Write `tests/test_routes.py` (httpx AsyncClient integration)
- [ ] **6.7** Write `infrastructure/docker-compose.yml` — backend + frontend + ollama services
- [ ] **6.8** Write `infrastructure/docker-compose.prod.yml` — resource limits, restart=always, volume mounts
- [ ] **6.9** Write `infrastructure/nginx/nginx.conf` — reverse proxy
- [ ] **6.10** Write Dockerfile for backend (Python 3.11-slim, non-root user)
- [ ] **6.11** Write Dockerfile for frontend (multi-stage: node:20 build → nginx:alpine serve)
- [ ] **6.12** Write `.github/workflows/ci.yml` — lint + typecheck + pytest on PR, Docker build on merge
- [ ] **6.13** Write `scripts/setup.sh` — one-command dev environment setup

**Acceptance:** `docker compose up --build` starts all services; all pytest passes; `docker compose -f infrastructure/docker-compose.prod.yml up` runs cleanly.

---

## 11. Production Readiness

### 11.1 Scalability

- **Short-term:** Single container per service. LLM calls are synchronous but Ollama is already non-blocking per-request.
- **Medium-term bottleneck:** FAISS with thousands of incidents starts to slow. Mitigation: add `faiss.IndexIVFFlat` (quantised) when > 10k entries.
- **Bag upload:** Large `.bag` files (>400 MB) need streaming upload with `python-multipart` chunked mode.
- **Long-term scaling path:** Extract `ai_services/` into separate FastAPI process behind internal proxy; add Redis job queue for LLM calls; Kafka for real-time telemetry if needed.

### 11.2 Observability

- Structured JSON logging with `request_id`, `service`, `duration_ms` on every call
- `/api/v1/health` returns component-level status: `{llm_reachable, faiss_loaded, sites_synced}`
- Docker health checks on all services
- **Phase 6+ addition:** OpenTelemetry SDK (`opentelemetry-sdk`, `opentelemetry-exporter-otlp`) — instrument service layer with spans; export to Jaeger or Grafana Tempo

### 11.3 Error Handling

- All service calls wrapped in try/except; return safe defaults (noop analysis, empty lists)
- `ROSLogExtractor.extract()` already returns an error-marker entry on failure — preserve this pattern
- `GrafanaParser` safe defaults on network errors (from spec)
- FastAPI exception handlers for 400 (bad bag format), 404 (bag not found), 500 (LLM timeout)
- No bare `except Exception: pass` — always log with `logger.exception()` and re-raise as `HTTPException`

### 11.4 Security

- **CORS:** Restrict `allow_origins` to the frontend origin in production (not `["*"]`)
- **File uploads:** Validate extension AND file magic bytes (not just extension); enforce 400 MB max server-side
- **Path traversal:** All file paths constructed via `pathlib.Path` with `.resolve()` and `is_relative_to(UPLOAD_DIR)` check
- **Secrets:** All API keys in environment variables only; `.env` in `.gitignore`; Docker secrets or Kubernetes secrets in production
- **LLM prompt injection:** Sanitise bag path, site ID, and user-provided description fields before injecting into prompts (strip newlines, truncate to sane limits)
- **Input validation:** All inputs validated by Pydantic before reaching service layer

### 11.5 Logging

- Use `core/logging.py` `get_logger(name)` everywhere — no bare `print()` in service or route code
- Log levels: DEBUG in dev, INFO in prod
- Never log raw bag contents, LLM API keys, or user-uploaded file contents

### 11.6 CI/CD

```yaml
# .github/workflows/ci.yml (structure)
on: [push, pull_request]
jobs:
  backend:
    - pip install -r requirements.txt
    - ruff check backend/
    - mypy backend/ --ignore-missing-imports
    - pytest backend/tests/ --tb=short
  frontend:
    - npm ci
    - npm run lint
    - npm run build      # catches TypeScript errors
  docker:
    - docker compose build   # verify images build
    trigger: on merge to main only
```

---

## 12. Migration Strategy

### 12.1 Migration Steps

```bash
# 1. Create target structure
mkdir -p unified_platform/{backend,frontend,infrastructure,scripts,docs/design/unified-platform}
mkdir -p unified_platform/backend/{app/routes,core,schemas,services/{ros,ai,sites},data/{bags,sites},tests}
mkdir -p unified_platform/frontend/{app,components/{layout,dashboard,fleet,bag-analyzer,investigation,knowledge,assistant},lib,public}

# 2. Copy backend services (no code changes at this step)
cp aiassist/backend/services/log_extractor.py    unified_platform/backend/services/ros/
cp aiassist/backend/services/llm_service.py      unified_platform/backend/services/ai/
cp aiassist/backend/schemas/bag_analysis.py      unified_platform/backend/schemas/
cp aiassist/backend/core/config.py               unified_platform/backend/core/
cp aiassist/backend/core/logging.py              unified_platform/backend/core/
cp site_commander/backend/data_loader.py         unified_platform/backend/services/sites/
cp site_commander/backend/data_processor.py      unified_platform/backend/services/sites/
cp site_commander/backend/git_manager.py         unified_platform/backend/services/sites/
cp site_commander/backend/log_analyzer_engine.py unified_platform/backend/services/ros/
cp site_commander/backend/map_processor.py       unified_platform/backend/services/ros/

# 3. Copy frontend components (no code changes at this step)
cp aiassist/frontend/components/BagUpload.tsx        unified_platform/frontend/components/bag-analyzer/
cp aiassist/frontend/components/LogVolumeChart.tsx   unified_platform/frontend/components/bag-analyzer/
cp aiassist/frontend/components/BagLogDebugger.tsx   unified_platform/frontend/components/bag-analyzer/
cp aiassist/frontend/lib/api.ts                      unified_platform/frontend/lib/
cp aiassist/frontend/lib/types.ts                    unified_platform/frontend/lib/

# 4. Copy Docker config
cp site_commander/docker-compose.yml unified_platform/infrastructure/
```

### 12.2 Breaking Changes to Resolve Post-Copy

1. **Import paths:** All `from backend.services.log_extractor` → `from backend.services.ros.log_extractor` etc.
2. **Config keys:** `file_manager.py`'s `STORAGE_DIR` → `settings.bag_upload_dir` (already correct in aiassist).
3. **Port conflict:** Both backends ran on different ports (8000 vs 8001) — unified on 8000; update frontend `.env.local`.
4. **CORS origins:** site_commander had no explicit CORS; aiassist had `["*"]` — set to `["http://localhost:3000"]` in dev.
5. **Missing dependency:** `gitpython` missing from site_commander `requirements.txt` — add to unified requirements.
6. **Test schema drift:** `test_phase6_schemas_engine.py` references old field names (`issue_cause`, `recovery_action`) — update to current field names.

---

## 13. Architecture Diagram (Text)

```
                        ┌─────────────────────────────────────────────────────┐
                        │           UNIFIED AMR INTELLIGENCE PLATFORM          │
                        └─────────────────────────────────────────────────────┘

USER (Browser)
    │
    ▼
┌──────────────────────────┐
│   Next.js Frontend        │  Port: 3000 (dev) / 80 (prod via nginx)
│                           │
│  [Dashboard]              │  ← Fleet overview, site cards, recent incidents
│  [Fleet Map]              │  ← Plotly map + topology + node click
│  [Bag Analyzer]           │  ← Upload → Timeline → Analyze → LLM report
│  [Investigation]          │  ← Incident form → confidence gauge → ranked RCA
│  [Knowledge Base]         │  ← FAISS incident history, ingest UI
│  [AI Assistant]           │  ← SSE streaming investigation panel
└────────────┬─────────────┘
             │ REST / SSE
             ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    FastAPI Unified Backend                    Port: 8000      │
│                                                                               │
│  Routes:                                                                      │
│  /api/v1/health          ← Component-level healthcheck                       │
│  /api/v1/sites/*         ← SiteDataManager (maps, nodes, edges, spots)       │
│  /api/v1/bags/*          ← Upload + Timeline + Analyze + MapDiff             │
│  /api/v1/investigate     ← Full AI investigation pipeline                    │
│  /api/v1/investigate/stream ← SSE streaming analysis                        │
│  /api/v1/ingest/*        ← Slack/manual knowledge ingestion                 │
│  /api/v1/incidents       ← Historical incident listing                       │
│  /api/v1/fleet/status    ← Aggregated robot fleet status                    │
│                                                                               │
│  Middleware: request_id injection, CORS, structured logging                  │
└──────┬────────────┬─────────────────┬──────────────┬────────────────────────┘
       │            │                 │              │
       ▼            ▼                 ▼              ▼
┌────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐
│ ROS Services│ │ AI Services  │ │ Site Services│ │ File Storage         │
│            │ │              │ │              │ │                      │
│ ROSLog     │ │ LLMService   │ │SiteDataMgr   │ │ data/bags/           │
│ Extractor  │ │ (Ollama API) │ │GrafanaParser │ │ (uploaded bags)      │
│            │ │              │ │ (Loki)       │ │                      │
│ LogAnalyzer│ │Investigation │ │DataProcessor │ │ data/sites/          │
│ Engine     │ │ Engine       │ │              │ │ (git-synced maps)    │
│            │ │              │ │GitSyncEngine │ │                      │
│ ROSAnomaly │ │HistoricalMatcher│              │ │ data/faiss.index     │
│ Detector   │ │ (FAISS)      │ │              │ │ data/metadata.json   │
│            │ │              │ │              │ │                      │
│ MapProcessor│ │SlackIngestor │ │              │ └──────────────────────┘
│ (LiDAR diff)│ │VisionParser  │ │              │
└────────────┘ └──────┬───────┘ └──────────────┘
                      │
                      ▼
              ┌───────────────┐
              │  Ollama        │  Port: 11434 (Docker sidecar)
              │  (qwen2.5-    │  Swap: OLLAMA_BASE_URL → OpenAI for GPT-4o
              │   coder or    │
              │   GPT-4o)     │
              └───────────────┘
```

---

## Checkpoint for Review

Before proceeding to implementation, confirm:

1. **Architecture decision** — Modular monolith backend is correct (vs splitting ai_services as standalone)?
2. **Frontend framework** — Keep Next.js 16 + Tailwind v4? (Streamlit removal confirmed?)
3. **LLM target** — Ollama (local) in dev, GPT-4o in production? Or Ollama only?
4. **FAISS persistence** — Filesystem-based is acceptable? (vs. a proper vector DB like Qdrant/Weaviate?)
5. **Auth** — Phase 1–5 will have no authentication. Is this acceptable for initial deployment? (add JWT/OAuth2 in Phase 7+?)
6. **Site data source** — Still using `~/catkin_ws/src/sootballs_sites` volume mount + git sync? Or S3/object storage?

---

*Plan ready for handoff to implementer. Begin with Phase 1 — Repository Scaffold.*
