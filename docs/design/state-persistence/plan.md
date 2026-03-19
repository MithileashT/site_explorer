# State Persistence Across Pages — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Persist user-facing state (search results, filters, fetched data, conversation history) across page navigations so nothing is lost when switching between pages.

**Architecture:** Introduce Zustand stores (one per page/domain) with `sessionStorage` persistence middleware and `partialize` to persist **only lightweight state** (filters, selections, metadata). Heavy data (log lines, map data, volume charts) lives in the store for cross-page retention but is **excluded from persistence** via `partialize` — it gets re-fetched on page reload. Each page component replaces its local `useState` calls with store selectors. Transient UI state (loading flags, dropdown visibility) remains as local `useState`. All stores use `version` for future-proof schema migration and `devtools` middleware in development.

**Tech Stack:** Zustand 5.x, Next.js 15 App Router, React 19, TypeScript

---

## Critical Rules (Read Before Implementing)

### Rule 1: No Functional Updaters on Store Setters

Zustand store setters returned via destructuring (`const { setX } = useStore()`) are **NOT** like React's `setState`. They do NOT accept functional updaters:

```typescript
// ❌ WRONG — will break silently
setMessages((prev) => [...prev, msg]);

// ✅ CORRECT — use store actions that call set() internally
addMessage(msg);
updateMessage(index, { content: newContent });
```

**During migration, audit EVERY `set*(prev => ...)` call.** If persisted state uses a functional updater, it MUST be replaced with a dedicated store action that uses `set((state) => ...)` internally.

### Rule 2: No Heavy Data in sessionStorage

`sessionStorage` limit is ~5-10 MB. Persisting large arrays (log lines, map data, trajectories) will cause silent failures or crashes.

**Persist only:** filters, query params, selections, metadata, small results.  
**Do NOT persist:** `allLines`, `volumeData`, `timeline`, `mapData`, `markers`, `trajectory`.

These heavy fields stay in the Zustand store (for in-memory cross-page retention) but are excluded from `sessionStorage` via `partialize`. On page reload, the page re-fetches them using the persisted filters.

### Rule 3: Store Versioning

All stores MUST include `version: 1` in the persist config. When the store shape changes in the future, bump the version — Zustand will discard stale data automatically instead of crashing.

### Rule 4: Auto-Reset on New Operations

Call `resetBags()` / `resetInvestigate()` etc. when a user starts a **new** operation (new upload, new investigation). This prevents stale results from a previous session bleeding into a fresh workflow.

---

## State Audit — What To Persist Per Page

### `/bags` → `BagsPage` (`explorer/frontend/app/bags/page.tsx`)

| State Variable | Type | In Store? | Persisted to sessionStorage? | Reason |
|---|---|---|---|---|
| `bagPath` | `string \| null` | ✅ | ✅ | User's uploaded bag reference |
| `tab` | `"logs" \| "mapdiff"` | ✅ | ✅ | User's active tab |
| `bagSource` | `"upload" \| "rio" \| "device"` | ✅ | ✅ | User's source choice |
| `timeline` | `BagTimeline \| null` | ✅ | ❌ (heavy) | In-memory only; re-fetched via `bagPath` on reload |
| `analysis` | `BagLogAnalysisResponse \| null` | ✅ | ❌ (heavy) | In-memory only; re-fetched via `bagPath` on reload |
| `timelineOpen` | `boolean` | ❌ | ❌ | Transient UI toggle |
| `showRawLLM` | `boolean` | ❌ | ❌ | Transient UI toggle |
| `analyzing` | `boolean` | ❌ | ❌ | Loading flag |
| `error` | `string` | ❌ | ❌ | Transient error |

### `/investigate` → `LogViewerPage` (`explorer/frontend/app/investigate/page.tsx`)

| State Variable | Type | In Store? | Persisted to sessionStorage? | Reason |
|---|---|---|---|---|
| `env` | `string` | ✅ | ✅ | Selected environment |
| `selectedSite` | `string` | ✅ | ✅ | Selected site |
| `selectedHostnames` | `string[]` | ✅ | ✅ | Selected hostnames |
| `selectedDeployments` | `string[]` | ✅ | ✅ | Selected deployments |
| `searchText` | `string` | ✅ | ✅ | Search query |
| `excludeText` | `string` | ✅ | ✅ | Exclude filter |
| `fromDate`, `fromTime` | `string` | ✅ | ✅ | Time range start |
| `toDate`, `toTime` | `string` | ✅ | ✅ | Time range end |
| `activeQuick` | `string` | ✅ | ✅ | Quick-range label |
| `issueDesc` | `string` | ✅ | ✅ | Issue description |
| `siteOptions` | `string[]` | ✅ | ✅ | Cascading dropdown options |
| `hostnameOptions` | `string[]` | ✅ | ✅ | Cascading dropdown options |
| `deploymentOptions` | `string[]` | ✅ | ✅ | Cascading dropdown options |
| `providers`, `activeProvider` | AI provider state | ✅ | ✅ | AI provider selection |
| `allLines` | `LokiLogLine[]` | ✅ | ❌ (heavy) | In-memory only; re-fetched using persisted filters on reload |
| `totalCount` | `number` | ✅ | ❌ (heavy) | In-memory only |
| `volumeData` | `array` | ✅ | ❌ (heavy) | In-memory only |
| `analysisResult` | `AnalyseResponse \| null` | ✅ | ❌ (heavy) | In-memory only |
| Loading flags, `expandedIdx`, brush state | various | ❌ | ❌ | Transient |

### `/assistant` → `AssistantPage` (`explorer/frontend/app/assistant/page.tsx`)

| State Variable | Type | In Store? | Persisted to sessionStorage? | Reason |
|---|---|---|---|---|
| `messages` | `Message[]` | ✅ | ✅ | Conversation history (typically small) |
| `input` | `string` | ✅ | ✅ | Draft input text |
| `busy` | `boolean` | ❌ | ❌ | Loading flag |
| `steps` | `string[]` | ❌ | ❌ | Transient progress |

> **⚠️ Functional Updater Audit:** This page has 5 instances of `setMessages((p) => ...)` that MUST be replaced with store actions (`addMessage`, `updateMessage`). See Task 9 for details.

### `/sitemap` → `SiteMapPage` (`explorer/frontend/app/sitemap/page.tsx`)

| State Variable | Type | In Store? | Persisted to sessionStorage? | Reason |
|---|---|---|---|---|
| `siteId` | `string` | ✅ | ✅ | Selected site |
| `searchQuery` | `string` | ✅ | ✅ | Committed search |
| `layers` | `Layers` | ✅ | ✅ | Layer visibility |
| `hiddenSpotTypes` | `string[]` | ✅ | ✅ | Hidden legend items (serialized from Set) |
| `hiddenRegionTypes` | `string[]` | ✅ | ✅ | Hidden legend items (serialized from Set) |
| `trajectoryBag` | `string` | ✅ | ✅ | Bag name |
| `meta` | `SiteMapMeta \| null` | ✅ | ❌ (heavy) | In-memory only; re-fetched via `siteId` on reload |
| `mapData` | `SiteMapData \| null` | ✅ | ❌ (heavy) | In-memory only; re-fetched via `siteId` on reload |
| `markers` | `SiteMapMarker[]` | ✅ | ❌ (heavy) | In-memory only; re-fetched via `siteId` on reload |
| `trajectory` | `TrajectoryPoint[]` | ✅ | ❌ (heavy) | In-memory only; cannot re-fetch (uploaded) |
| Playback state, dropdown visibility, loading | various | ❌ | ❌ | Transient |

### `/slack-investigation` → `SlackInvestigationPage` (`explorer/frontend/app/slack-investigation/page.tsx`)

| State Variable | Type | In Store? | Persisted to sessionStorage? | Reason |
|---|---|---|---|---|
| `result` | `SlackThreadInvestigationResponse \| null` | ✅ | ✅ | Investigation result (moderate size) |
| `sites` | `array` | ✅ | ✅ | Loaded site list (small) |
| `providers`, `activeProvider` | AI provider state | ✅ | ✅ | AI provider selection |
| `running`, `error`, `showRaw`, form state | various | ❌ | ❌ | Transient |

---

## Task Breakdown

### Task 1: Install Zustand (SERIAL — must complete first)

**Files:**
- Modify: `explorer/frontend/package.json`

**Step 1: Install zustand**

```bash
cd explorer/frontend && npm install zustand
```

**Step 2: Verify installation**

```bash
grep zustand explorer/frontend/package.json
```

Expected: `"zustand": "^5.x.x"` in dependencies

**Step 3: Commit**

```bash
git add explorer/frontend/package.json explorer/frontend/package-lock.json
git commit -m "chore: add zustand for global state management"
```

---

### Task 2: Create Bags Store (PARALLEL with Tasks 3-6)

**Files:**
- Create: `explorer/frontend/lib/stores/bags-store.ts`
- Test: verify import compiles

**Step 1: Create the store file**

```typescript
import { create } from "zustand";
import { persist, createJSONStorage, devtools } from "zustand/middleware";
import type { BagLogAnalysisResponse, BagTimeline } from "@/lib/types";

type Tab = "logs" | "mapdiff";
type BagSource = "upload" | "rio" | "device";

interface BagsState {
  // Persisted (lightweight)
  bagPath: string | null;
  tab: Tab;
  bagSource: BagSource;

  // In-memory only (heavy — excluded from sessionStorage via partialize)
  timeline: BagTimeline | null;
  analysis: BagLogAnalysisResponse | null;

  setBagPath: (p: string | null) => void;
  setTimeline: (t: BagTimeline | null) => void;
  setAnalysis: (a: BagLogAnalysisResponse | null) => void;
  setTab: (t: Tab) => void;
  setBagSource: (s: BagSource) => void;
  resetBags: () => void;
}

const initialState = {
  bagPath: null as string | null,
  timeline: null as BagTimeline | null,
  analysis: null as BagLogAnalysisResponse | null,
  tab: "logs" as Tab,
  bagSource: "upload" as BagSource,
};

export const useBagsStore = create<BagsState>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,
        setBagPath: (p) => set({ bagPath: p }),
        setTimeline: (t) => set({ timeline: t }),
        setAnalysis: (a) => set({ analysis: a }),
        setTab: (t) => set({ tab: t }),
        setBagSource: (s) => set({ bagSource: s }),
        resetBags: () => set(initialState),
      }),
      {
        name: "amr-bags-state",
        version: 1,
        storage: createJSONStorage(() => sessionStorage),
        partialize: (state) => ({
          bagPath: state.bagPath,
          tab: state.tab,
          bagSource: state.bagSource,
          // timeline and analysis deliberately excluded — too large for sessionStorage
        }),
      }
    ),
    { name: "BagsStore", enabled: process.env.NODE_ENV === "development" }
  )
);
```

**Step 2: Verify the file is valid TypeScript**

```bash
cd explorer/frontend && npx tsc --noEmit lib/stores/bags-store.ts 2>&1 | head -10
```

Expected: no errors or just unrelated warnings

**Step 3: Commit**

```bash
git add explorer/frontend/lib/stores/bags-store.ts
git commit -m "feat: add zustand store for bags page state"
```

---

### Task 3: Create Investigate Store (PARALLEL with Tasks 2, 4-6)

**Files:**
- Create: `explorer/frontend/lib/stores/investigate-store.ts`

**Step 1: Create the store file**

```typescript
import { create } from "zustand";
import { persist, createJSONStorage, devtools } from "zustand/middleware";
import type { LokiLogLine, AnalyseResponse, AIProviderInfo } from "@/lib/types";

interface InvestigateState {
  // Persisted (lightweight filters & selections)
  env: string;
  selectedSite: string;
  siteOptions: string[];
  hostnameOptions: string[];
  selectedHostnames: string[];
  deploymentOptions: string[];
  selectedDeployments: string[];
  searchText: string;
  excludeText: string;
  fromDate: string;
  fromTime: string;
  toDate: string;
  toTime: string;
  activeQuick: string;
  issueDesc: string;
  providers: AIProviderInfo[];
  activeProvider: AIProviderInfo | null;

  // In-memory only (heavy — excluded from sessionStorage via partialize)
  allLines: LokiLogLine[];
  totalCount: number;
  volumeData: { ts: number; label: string; count: number }[];
  analysisResult: AnalyseResponse | null;

  // Actions
  setEnv: (e: string) => void;
  setSelectedSite: (s: string) => void;
  setSiteOptions: (o: string[]) => void;
  setHostnameOptions: (o: string[]) => void;
  setSelectedHostnames: (h: string[]) => void;
  setDeploymentOptions: (o: string[]) => void;
  setSelectedDeployments: (d: string[]) => void;
  setSearchText: (t: string) => void;
  setExcludeText: (t: string) => void;
  setFromDate: (d: string) => void;
  setFromTime: (t: string) => void;
  setToDate: (d: string) => void;
  setToTime: (t: string) => void;
  setActiveQuick: (q: string) => void;
  setAllLines: (l: LokiLogLine[]) => void;
  setTotalCount: (c: number) => void;
  setVolumeData: (v: { ts: number; label: string; count: number }[]) => void;
  setIssueDesc: (d: string) => void;
  setAnalysisResult: (r: AnalyseResponse | null) => void;
  setProviders: (p: AIProviderInfo[]) => void;
  setActiveProvider: (p: AIProviderInfo | null) => void;
  resetInvestigate: () => void;
}

const now = Date.now();
function toDateStr(ms: number) { return new Date(ms).toISOString().slice(0, 10); }
function toTimeStr(ms: number) { return new Date(ms).toISOString().slice(11, 19); }

const initialState = {
  env: "sootballs-prod-logs-loki-US-latest",
  selectedSite: "",
  siteOptions: [] as string[],
  hostnameOptions: [] as string[],
  selectedHostnames: [] as string[],
  deploymentOptions: [] as string[],
  selectedDeployments: [] as string[],
  searchText: "",
  excludeText: "",
  fromDate: toDateStr(now - 15 * 60 * 1000),
  fromTime: toTimeStr(now - 15 * 60 * 1000),
  toDate: toDateStr(now),
  toTime: toTimeStr(now),
  activeQuick: "Last 15m",
  allLines: [] as LokiLogLine[],
  totalCount: 0,
  volumeData: [] as { ts: number; label: string; count: number }[],
  issueDesc: "",
  analysisResult: null as AnalyseResponse | null,
  providers: [] as AIProviderInfo[],
  activeProvider: null as AIProviderInfo | null,
};

export const useInvestigateStore = create<InvestigateState>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,
        setEnv: (e) => set({ env: e }),
        setSelectedSite: (s) => set({ selectedSite: s }),
        setSiteOptions: (o) => set({ siteOptions: o }),
        setHostnameOptions: (o) => set({ hostnameOptions: o }),
        setSelectedHostnames: (h) => set({ selectedHostnames: h }),
        setDeploymentOptions: (o) => set({ deploymentOptions: o }),
        setSelectedDeployments: (d) => set({ selectedDeployments: d }),
        setSearchText: (t) => set({ searchText: t }),
        setExcludeText: (t) => set({ excludeText: t }),
        setFromDate: (d) => set({ fromDate: d }),
        setFromTime: (t) => set({ fromTime: t }),
        setToDate: (d) => set({ toDate: d }),
        setToTime: (t) => set({ toTime: t }),
        setActiveQuick: (q) => set({ activeQuick: q }),
        setAllLines: (l) => set({ allLines: l }),
        setTotalCount: (c) => set({ totalCount: c }),
        setVolumeData: (v) => set({ volumeData: v }),
        setIssueDesc: (d) => set({ issueDesc: d }),
        setAnalysisResult: (r) => set({ analysisResult: r }),
        setProviders: (p) => set({ providers: p }),
        setActiveProvider: (p) => set({ activeProvider: p }),
        resetInvestigate: () => set(initialState),
      }),
      {
        name: "amr-investigate-state",
        version: 1,
        storage: createJSONStorage(() => sessionStorage),
        partialize: (state) => ({
          // Only persist lightweight filters & selections
          env: state.env,
          selectedSite: state.selectedSite,
          siteOptions: state.siteOptions,
          hostnameOptions: state.hostnameOptions,
          selectedHostnames: state.selectedHostnames,
          deploymentOptions: state.deploymentOptions,
          selectedDeployments: state.selectedDeployments,
          searchText: state.searchText,
          excludeText: state.excludeText,
          fromDate: state.fromDate,
          fromTime: state.fromTime,
          toDate: state.toDate,
          toTime: state.toTime,
          activeQuick: state.activeQuick,
          issueDesc: state.issueDesc,
          providers: state.providers,
          activeProvider: state.activeProvider,
          // Deliberately excluded (too large for sessionStorage):
          // allLines, totalCount, volumeData, analysisResult
        }),
      }
    ),
    { name: "InvestigateStore", enabled: process.env.NODE_ENV === "development" }
  )
);
```

**Step 2: Verify valid TypeScript**

```bash
cd explorer/frontend && npx tsc --noEmit lib/stores/investigate-store.ts 2>&1 | head -10
```

**Step 3: Commit**

```bash
git add explorer/frontend/lib/stores/investigate-store.ts
git commit -m "feat: add zustand store for investigate page state"
```

---

### Task 4: Create Assistant Store (PARALLEL with Tasks 2-3, 5-6)

**Files:**
- Create: `explorer/frontend/lib/stores/assistant-store.ts`

**Step 1: Create the store file**

```typescript
import { create } from "zustand";
import { persist, createJSONStorage, devtools } from "zustand/middleware";

interface Message {
  role: "user" | "assistant" | "system";
  content: string;
}

interface AssistantState {
  messages: Message[];
  input: string;

  setMessages: (m: Message[]) => void;
  addMessage: (m: Message) => void;
  updateMessage: (index: number, m: Partial<Message>) => void;
  setInput: (i: string) => void;
  resetAssistant: () => void;
}

const WELCOME: Message = {
  role: "system",
  content:
    "👋 **Welcome to the AMR AI Assistant.**\n\nDescribe an incident or ask me to investigate something. I'll use real-time FAISS similarity search + LLM analysis to diagnose issues, rank causes, and suggest solutions.",
};

const initialState = {
  messages: [WELCOME] as Message[],
  input: "",
};

export const useAssistantStore = create<AssistantState>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,
        setMessages: (m) => set({ messages: m }),
        // ✅ Use these instead of setMessages((prev) => ...) — Zustand setters don't support functional updaters
        addMessage: (m) =>
          set((state) => ({ messages: [...state.messages, m] })),
        updateMessage: (index, partial) =>
          set((state) => ({
            messages: state.messages.map((msg, i) =>
              i === index ? { ...msg, ...partial } : msg
            ),
          })),
        setInput: (i) => set({ input: i }),
        resetAssistant: () => set(initialState),
      }),
      {
        name: "amr-assistant-state",
        version: 1,
        storage: createJSONStorage(() => sessionStorage),
      }
    ),
    { name: "AssistantStore", enabled: process.env.NODE_ENV === "development" }
  )
);
```

**Step 2: Verify valid TypeScript**

```bash
cd explorer/frontend && npx tsc --noEmit lib/stores/assistant-store.ts 2>&1 | head -10
```

**Step 3: Commit**

```bash
git add explorer/frontend/lib/stores/assistant-store.ts
git commit -m "feat: add zustand store for assistant page state"
```

---

### Task 5: Create Sitemap Store (PARALLEL with Tasks 2-4, 6)

**Files:**
- Create: `explorer/frontend/lib/stores/sitemap-store.ts`

**Step 1: Create the store file**

```typescript
import { create } from "zustand";
import { persist, createJSONStorage, devtools } from "zustand/middleware";
import type {
  SiteMapMeta,
  SiteMapData,
  SiteMapMarker,
  TrajectoryPoint,
} from "@/lib/types";
import type { Layers } from "@/components/sitemap/SiteMapCanvas";

interface SitemapState {
  // Persisted (lightweight)
  siteId: string;
  searchQuery: string;
  layers: Layers;
  hiddenSpotTypes: string[];   // serialized as array, used as Set in component
  hiddenRegionTypes: string[]; // serialized as array, used as Set in component
  trajectoryBag: string;

  // In-memory only (heavy — excluded from sessionStorage via partialize)
  meta: SiteMapMeta | null;
  mapData: SiteMapData | null;
  markers: SiteMapMarker[];
  trajectory: TrajectoryPoint[];

  setSiteId: (id: string) => void;
  setMeta: (m: SiteMapMeta | null) => void;
  setMapData: (d: SiteMapData | null) => void;
  setMarkers: (m: SiteMapMarker[]) => void;
  setTrajectory: (t: TrajectoryPoint[]) => void;
  setTrajectoryBag: (b: string) => void;
  setSearchQuery: (q: string) => void;
  setLayers: (l: Layers) => void;
  setHiddenSpotTypes: (t: string[]) => void;
  setHiddenRegionTypes: (t: string[]) => void;
  resetSitemap: () => void;
}

const initialState = {
  siteId: "",
  meta: null as SiteMapMeta | null,
  mapData: null as SiteMapData | null,
  markers: [] as SiteMapMarker[],
  trajectory: [] as TrajectoryPoint[],
  trajectoryBag: "",
  searchQuery: "",
  layers: {
    spots: true,
    racks: true,
    regions: true,
    markers: true,
    nodes: true,
  },
  hiddenSpotTypes: [] as string[],
  hiddenRegionTypes: [] as string[],
};

export const useSitemapStore = create<SitemapState>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,
        setSiteId: (id) => set({ siteId: id }),
        setMeta: (m) => set({ meta: m }),
        setMapData: (d) => set({ mapData: d }),
        setMarkers: (m) => set({ markers: m }),
        setTrajectory: (t) => set({ trajectory: t }),
        setTrajectoryBag: (b) => set({ trajectoryBag: b }),
        setSearchQuery: (q) => set({ searchQuery: q }),
        setLayers: (l) => set({ layers: l }),
        setHiddenSpotTypes: (t) => set({ hiddenSpotTypes: t }),
        setHiddenRegionTypes: (t) => set({ hiddenRegionTypes: t }),
        resetSitemap: () => set(initialState),
      }),
      {
        name: "amr-sitemap-state",
        version: 1,
        storage: createJSONStorage(() => sessionStorage),
        partialize: (state) => ({
          // Only persist lightweight selections
          siteId: state.siteId,
          searchQuery: state.searchQuery,
          layers: state.layers,
          hiddenSpotTypes: state.hiddenSpotTypes,
          hiddenRegionTypes: state.hiddenRegionTypes,
          trajectoryBag: state.trajectoryBag,
          // Deliberately excluded (too large for sessionStorage):
          // meta, mapData, markers, trajectory
        }),
      }
    ),
    { name: "SitemapStore", enabled: process.env.NODE_ENV === "development" }
  )
);
```

**Note:** `Set<string>` is not JSON-serializable. The store uses `string[]` and the component must convert with `new Set(arr)` / `[...set]` at the boundary.

**Step 2: Verify valid TypeScript**

```bash
cd explorer/frontend && npx tsc --noEmit lib/stores/sitemap-store.ts 2>&1 | head -10
```

**Step 3: Commit**

```bash
git add explorer/frontend/lib/stores/sitemap-store.ts
git commit -m "feat: add zustand store for sitemap page state"
```

---

### Task 6: Create Slack Investigation Store (PARALLEL with Tasks 2-5)

**Files:**
- Create: `explorer/frontend/lib/stores/slack-investigation-store.ts`

**Step 1: Create the store file**

```typescript
import { create } from "zustand";
import { persist, createJSONStorage, devtools } from "zustand/middleware";
import type {
  SlackThreadInvestigationResponse,
  AIProviderInfo,
} from "@/lib/types";

interface SlackInvestigationState {
  result: SlackThreadInvestigationResponse | null;
  sites: { id: string; name: string }[];
  providers: AIProviderInfo[];
  activeProvider: AIProviderInfo | null;

  setResult: (r: SlackThreadInvestigationResponse | null) => void;
  setSites: (s: { id: string; name: string }[]) => void;
  setProviders: (p: AIProviderInfo[]) => void;
  setActiveProvider: (p: AIProviderInfo | null) => void;
  resetSlackInvestigation: () => void;
}

const initialState = {
  result: null as SlackThreadInvestigationResponse | null,
  sites: [] as { id: string; name: string }[],
  providers: [] as AIProviderInfo[],
  activeProvider: null as AIProviderInfo | null,
};

export const useSlackInvestigationStore = create<SlackInvestigationState>()(
  devtools(
    persist(
      (set) => ({
        ...initialState,
        setResult: (r) => set({ result: r }),
        setSites: (s) => set({ sites: s }),
        setProviders: (p) => set({ providers: p }),
        setActiveProvider: (p) => set({ activeProvider: p }),
        resetSlackInvestigation: () => set(initialState),
      }),
      {
        name: "amr-slack-investigation-state",
        version: 1,
        storage: createJSONStorage(() => sessionStorage),
      }
    ),
    { name: "SlackInvestigationStore", enabled: process.env.NODE_ENV === "development" }
  )
);
```

**Step 2: Verify valid TypeScript**

```bash
cd explorer/frontend && npx tsc --noEmit lib/stores/slack-investigation-store.ts 2>&1 | head -10
```

**Step 3: Commit**

```bash
git add explorer/frontend/lib/stores/slack-investigation-store.ts
git commit -m "feat: add zustand store for slack investigation page state"
```

---

### Task 7: Migrate Bags Page to Zustand (SERIAL — after Task 1-2)

**Files:**
- Modify: `explorer/frontend/app/bags/page.tsx`

**Step 1: Replace local useState with store selectors**

In `BagsPage`, replace the local state declarations:

```diff
- import { useState } from "react";
+ import { useState } from "react";
+ import { useBagsStore } from "@/lib/stores/bags-store";

  export default function BagsPage() {
-   const [bagPath, setBagPath] = useState<string | null>(null);
-   const [timeline, setTimeline] = useState<BagTimeline | null>(null);
-   const [analysis, setAnalysis] = useState<BagLogAnalysisResponse | null>(null);
-   const [analyzing, setAnalyzing] = useState(false);
-   const [error, setError] = useState("");
-   const [tab, setTab] = useState<Tab>("logs");
-   const [bagSource, setBagSource] = useState<BagSource>("upload");
-   const [timelineOpen, setTimelineOpen] = useState(true);
-   const [showRawLLM, setShowRawLLM] = useState(false);
+   // Persisted state from store
+   const { bagPath, setBagPath, timeline, setTimeline, analysis, setAnalysis, tab, setTab, bagSource, setBagSource } = useBagsStore();
+   // Transient local state — NOT persisted
+   const [analyzing, setAnalyzing] = useState(false);
+   const [error, setError] = useState("");
+   const [timelineOpen, setTimelineOpen] = useState(true);
+   const [showRawLLM, setShowRawLLM] = useState(false);
```

No other code changes needed — the setter function signatures are identical to `useState` setters.

**Step 2: Add auto-reset when a new upload starts**

In the `onUploaded` callback, call `resetBags()` before setting the new bag path to clear stale analysis/timeline from the previous bag:

```diff
+ const resetBags = useBagsStore((s) => s.resetBags);

  async function onUploaded(path: string) {
+   resetBags(); // Clear previous bag's data before loading new
    setBagPath(path);
-   setAnalysis(null);
-   setTimeline(null);
-   setError("");
+   setError("");
```

**Step 3: Add re-fetch on reload (timeline/analysis not persisted)**

Since `timeline` and `analysis` are excluded from `sessionStorage` via `partialize`, add a `useEffect` that re-fetches timeline when `bagPath` is present but `timeline` is null (i.e., after a page reload):

```typescript
useEffect(() => {
  if (bagPath && !timeline) {
    fetchTimeline(bagPath).then(setTimeline).catch(() => {});
  }
}, [bagPath, timeline]);
```

**Step 4: Build to verify no type errors**

```bash
cd explorer/frontend && npm run build 2>&1 | tail -20
```

Expected: successful build, no new errors

**Step 3: Manual verification**

1. Open `/bags`, upload a bag, see analysis results appear
2. Navigate to `/investigate` via sidebar
3. Navigate back to `/bags`
4. Verify: bag path, timeline, analysis, tab, and source are all preserved

**Step 4: Commit**

```bash
git add explorer/frontend/app/bags/page.tsx
git commit -m "feat: migrate bags page to zustand store for state persistence"
```

---

### Task 8: Migrate Investigate Page to Zustand (SERIAL — after Task 1, 3)

**Files:**
- Modify: `explorer/frontend/app/investigate/page.tsx`

**Step 1: Replace local useState with store selectors**

In the `LogViewerPage` component, replace the persisted state:

```diff
+ import { useInvestigateStore } from "@/lib/stores/investigate-store";

  export default function LogViewerPage() {
-   const [env, setEnv] = useState(ENVIRONMENTS[0]);
-   const [siteOptions, setSiteOptions] = useState<string[]>([]);
-   const [selectedSite, setSelectedSite] = useState("");
-   // ... all the other useState lines for persisted state ...
+   // Persisted state from store
+   const {
+     env, setEnv,
+     selectedSite, setSelectedSite,
+     siteOptions, setSiteOptions,
+     hostnameOptions, setHostnameOptions,
+     selectedHostnames, setSelectedHostnames,
+     deploymentOptions, setDeploymentOptions,
+     selectedDeployments, setSelectedDeployments,
+     searchText, setSearchText,
+     excludeText, setExcludeText,
+     fromDate, setFromDate, fromTime, setFromTime,
+     toDate, setToDate, toTime, setToTime,
+     activeQuick, setActiveQuick,
+     allLines, setAllLines,
+     totalCount, setTotalCount,
+     volumeData, setVolumeData,
+     issueDesc, setIssueDesc,
+     analysisResult, setAnalysisResult,
+     providers, setProviders,
+     activeProvider, setActiveProvider,
+   } = useInvestigateStore();
```

Keep these as local `useState` (transient):
- `loadingSites`, `loadingHosts`, `loadingDeps` — loading flags
- `loading`, `fetchError` — fetch state  
- `brushStart`, `brushEnd`, `selecting` — chart brush
- `logsOpen` — collapse toggle
- `analysing`, `analysisError` — analysis loading
- `useAnalysisRange`, `analysisFromDate`, `analysisFromTime`, `analysisToDate`, `analysisToTime` — analysis range (depends on current time)
- `providerSwitching` — transient UI
- `expandedIdx` — transient UI
- `analysisLines` — small UI preference

**Step 2: Handle cascading filter effects carefully**

The existing `useEffect` hooks that reset downstream state on env/site/hostname changes must now call store setters instead of local setters. Since the store setter signatures match `useState` setter signatures (they accept a value, not a function), the effects should work without changes — **but verify** that no effect uses the functional updater form (`setX(prev => ...)`) for persisted state.

> **Audit result:** Investigated page has NO functional updaters on persisted state — all `set*(prev => ...)` calls are on transient state like `setSteps`, `setTimelineOpen` etc. Safe to proceed.

**Step 3: Add re-fetch on reload (heavy data not persisted)**

Since `allLines`, `volumeData`, `totalCount`, and `analysisResult` are excluded from `sessionStorage`, add a `useEffect` that auto-fetches logs when the user returns to the page and persisted filters are present but log data is empty:

```typescript
// Re-fetch logs on reload if filters are present but data was lost
useEffect(() => {
  if (selectedSite && allLines.length === 0 && !loading) {
    doFetch();
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, []); // Run only on mount
```

**Step 4: Build to verify**

```bash
cd explorer/frontend && npm run build 2>&1 | tail -20
```

**Step 4: Manual verification**

1. Open `/investigate`, select a site, fetch logs
2. Navigate to `/bags`
3. Navigate back to `/investigate`
4. Verify: env, site, hostnames, time range, logs, and analysis result are preserved

**Step 5: Commit**

```bash
git add explorer/frontend/app/investigate/page.tsx
git commit -m "feat: migrate investigate page to zustand store for state persistence"
```

---

### Task 9: Migrate Assistant Page to Zustand (SERIAL — after Task 1, 4)

**Files:**
- Modify: `explorer/frontend/app/assistant/page.tsx`

**Step 1: Replace local useState with store selectors**

```diff
+ import { useAssistantStore } from "@/lib/stores/assistant-store";

  export default function AssistantPage() {
-   const [messages, setMessages] = useState<Message[]>([...]);
-   const [input, setInput] = useState("");
-   const [busy, setBusy] = useState(false);
-   const [steps, setSteps] = useState<string[]>([]);
+   // Persisted state from store
+   const { messages, setMessages, addMessage, updateMessage, input, setInput } = useAssistantStore();
+   // Transient local state
+   const [busy, setBusy] = useState(false);
+   const [steps, setSteps] = useState<string[]>([]);
```

**Step 2: Update ALL `setMessages` functional updater patterns (⚠️ CRITICAL — 5 instances)**

The current code uses functional updater form `setMessages((p) => [...p, msg])` in 5 places. Zustand store setters do NOT support functional updaters. Every instance MUST be replaced:

```diff
// Instance 1 (line ~59): Add user message
-   setMessages((p) => [...p, userMsg]);
+   addMessage(userMsg);

// Instance 2 (line ~64): Add empty assistant bubble
-   setMessages((p) => [...p, { role: "assistant", content: "" }]);
+   addMessage({ role: "assistant", content: "" });

// Instance 3 (line ~84): Update streaming content
-   setMessages((p) =>
-     p.map((m, i) => (i === placeholderIdx ? { ...m, content: accumulated } : m))
-   );
+   updateMessage(placeholderIdx, { content: accumulated });

// Instance 4 (line ~109): Set final result
-   setMessages((p) =>
-     p.map((m, i) =>
-       i === placeholderIdx ? { ...m, content: summary, result: r } : m
-     )
-   );
+   updateMessage(placeholderIdx, { content: summary, result: r });

// Instance 5 (line ~121): Set error message
-   setMessages((p) =>
-     p.map((m, i) =>
-       i === placeholderIdx ? { ...m, content: errorContent } : m
-     )
-   );
+   updateMessage(placeholderIdx, { content: errorContent });
```

> **Note:** `setSteps((p) => ...)` on line ~71 is safe — `steps` is local `useState`, not from the store.

**Step 3: Update `reset()` function**

```diff
+ const resetAssistant = useAssistantStore((s) => s.resetAssistant);

  function reset() {
    cancel();
-   setMessages([...]);
-   setInput("");
+   resetAssistant();
  }
```

**Step 4: Build to verify**

```bash
cd explorer/frontend && npm run build 2>&1 | tail -20
```

**Step 5: Manual verification**

1. Open `/assistant`, send a message, see response
2. Navigate to `/bags`
3. Navigate back to `/assistant`
4. Verify: conversation history and draft input are preserved

**Step 6: Commit**

```bash
git add explorer/frontend/app/assistant/page.tsx
git commit -m "feat: migrate assistant page to zustand store for state persistence"
```

---

### Task 10: Migrate Sitemap Page to Zustand (SERIAL — after Task 1, 5)

**Files:**
- Modify: `explorer/frontend/app/sitemap/page.tsx`

**Step 1: Replace local useState with store selectors**

```diff
+ import { useSitemapStore } from "@/lib/stores/sitemap-store";

  export default function SiteMapPage() {
-   const [sites, setSites] = useState<{ id: string; name: string }[]>([]);
-   const [siteId, setSiteId] = useState("");
-   const [meta, setMeta] = useState<SiteMapMeta | null>(null);
-   const [mapData, setMapData] = useState<SiteMapData | null>(null);
-   const [markers, setMarkers] = useState<SiteMapMarker[]>([]);
-   const [trajectory, setTrajectory] = useState<TrajectoryPoint[]>([]);
-   const [trajectoryBag, setTrajectoryBag] = useState("");
-   const [searchQuery, setSearchQuery] = useState("");
-   const [layers, setLayers] = useState<Layers>({...});
-   const [hiddenSpotTypes, setHiddenSpotTypes] = useState<Set<string>>(new Set());
-   const [hiddenRegionTypes, setHiddenRegionTypes] = useState<Set<string>>(new Set());
+   // Persisted state from store
+   const {
+     siteId, setSiteId: storeSiteId,
+     meta, setMeta,
+     mapData, setMapData,
+     markers, setMarkers,
+     trajectory, setTrajectory: storeSetTrajectory,
+     trajectoryBag, setTrajectoryBag,
+     searchQuery, setSearchQuery,
+     layers, setLayers,
+     hiddenSpotTypes: hiddenSpotTypesArr, setHiddenSpotTypes: storeSetHiddenSpots,
+     hiddenRegionTypes: hiddenRegionTypesArr, setHiddenRegionTypes: storeSetHiddenRegions,
+   } = useSitemapStore();
+
+   // Convert arrays ↔ Sets at the boundary
+   const hiddenSpotTypes = useMemo(() => new Set(hiddenSpotTypesArr), [hiddenSpotTypesArr]);
+   const hiddenRegionTypes = useMemo(() => new Set(hiddenRegionTypesArr), [hiddenRegionTypesArr]);
+   const setHiddenSpotTypes = useCallback((s: Set<string>) => storeSetHiddenSpots([...s]), [storeSetHiddenSpots]);
+   const setHiddenRegionTypes = useCallback((s: Set<string>) => storeSetHiddenRegions([...s]), [storeSetHiddenRegions]);
```

Keep local `useState` for: `sites` (loaded on mount), `loading`, `mapErr`, `trajectoryWarning`, playback state, UI dropdown states, `inputText`, `selectedSpot`.

**Step 2: Handle `sites` list — still fetch on mount, but use store `siteId` to restore selection**

The `sites` dropdown options should still be fetched fresh on mount (they may change server-side), but `siteId` from the store tells us what was previously selected. On mount, if `siteId` is non-empty and appears in the freshly loaded `sites`, auto-load that site.

**Step 3: Add re-fetch on reload (heavy data not persisted)**

Since `meta`, `mapData`, `markers` are excluded from `sessionStorage`, add a `useEffect` that re-fetches site data when `siteId` is persisted but `mapData` is null (i.e., after a page reload):

```typescript
// Re-load site data on reload if siteId is persisted but map data was lost
useEffect(() => {
  if (siteId && !mapData && !loading) {
    loadSite(siteId); // existing function that fetches meta + mapData + markers
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, []); // Run only on mount
```

> **Note:** `trajectory` (uploaded from a bag) cannot be re-fetched — it will be lost on page reload. This is acceptable since bag uploads are transient operations. The `trajectoryBag` name is still persisted so the user knows what was loaded.

**Step 4: Build to verify**

```bash
cd explorer/frontend && npm run build 2>&1 | tail -20
```

**Step 4: Manual verification**

1. Open `/sitemap`, select a site, see map render, toggle layers
2. Navigate to `/bags`
3. Navigate back to `/sitemap`
4. Verify: site, map, markers, layers, search, and trajectory are preserved

**Step 5: Commit**

```bash
git add explorer/frontend/app/sitemap/page.tsx
git commit -m "feat: migrate sitemap page to zustand store for state persistence"
```

---

### Task 11: Migrate Slack Investigation Page to Zustand (SERIAL — after Task 1, 6)

**Files:**
- Modify: `explorer/frontend/app/slack-investigation/page.tsx`

**Step 1: Replace local useState with store selectors**

```diff
+ import { useSlackInvestigationStore } from "@/lib/stores/slack-investigation-store";

  export default function SlackInvestigationPage() {
-   const [result, setResult] = useState<SlackThreadInvestigationResponse | null>(null);
-   const [sites, setSites] = useState<Array<{ id: string; name: string }>>([]);
-   const [providers, setProviders] = useState<AIProviderInfo[]>([]);
-   const [activeProvider, setActiveProvider] = useState<AIProviderInfo | null>(null);
+   const { result, setResult, sites, setSites, providers, setProviders, activeProvider, setActiveProvider } = useSlackInvestigationStore();
```

Keep local: `running`, `error`, `showRaw`, `sitesLoading`, `sitesError`, `llmStatus`, `selectedModel`, `providerSwitching`.

**Step 2: Build to verify**

```bash
cd explorer/frontend && npm run build 2>&1 | tail -20
```

**Step 3: Manual verification**

1. Open `/slack-investigation`, run an investigation, see results
2. Navigate to `/bags`
3. Navigate back to `/slack-investigation`
4. Verify: investigation result and site list are preserved

**Step 4: Commit**

```bash
git add explorer/frontend/app/slack-investigation/page.tsx
git commit -m "feat: migrate slack investigation page to zustand store for state persistence"
```

---

### Task 12: Handle SSR Hydration Mismatch (SERIAL — after Tasks 7-11)

**Files:**
- Create: `explorer/frontend/lib/stores/use-hydrated.ts`
- Modify: any page that shows store data on initial render

**Context:** Zustand `persist` with `sessionStorage` rehydrates on the client, but the server render always uses initial state. This causes a hydration mismatch. We need a small hook.

**Step 1: Create the hydration hook**

```typescript
import { useEffect, useState } from "react";

/**
 * Returns false on server and on first client render (before hydration),
 * then true after Zustand has rehydrated from sessionStorage.
 */
export function useHydrated(): boolean {
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  return hydrated;
}
```

**Step 2: Use in pages where initial content depends on store**

Use `visibility: hidden` instead of a loading skeleton to avoid layout flicker. This preserves the DOM layout during the single-frame hydration delay:

```tsx
const hydrated = useHydrated();

// Wrap the root div of the page return:
return (
  <div style={{ visibility: hydrated ? "visible" : "hidden" }}>
    {/* ... page content ... */}
  </div>
);
```

**Why `visibility: hidden` over `<LoadingSkeleton />`:**
- No layout shift — the page is already rendered at correct dimensions
- No visible flicker — content appears in a single frame
- Only guard pages that actually depend on persisted store data
- Pages that don't read store data on first render (e.g., dashboard) don't need this

**Step 3: Build and test**

```bash
cd explorer/frontend && npm run build 2>&1 | tail -20
```

Verify no hydration warnings in browser console.

**Step 4: Commit**

```bash
git add explorer/frontend/lib/stores/use-hydrated.ts explorer/frontend/app/bags/page.tsx explorer/frontend/app/investigate/page.tsx explorer/frontend/app/assistant/page.tsx explorer/frontend/app/sitemap/page.tsx explorer/frontend/app/slack-investigation/page.tsx
git commit -m "fix: add hydration guard to prevent SSR mismatch with zustand persist"
```

---

### Task 13: Final Integration Test (SERIAL — after Task 12)

**Step 1: Full build**

```bash
cd explorer/frontend && npm run build
```

Expected: successful build, zero errors

**Step 2: Manual end-to-end test**

Navigate through every page in order, entering data on each:

1. `/` → Dashboard loads, note site list
2. `/bags` → Upload a bag, run analysis, switch to mapdiff tab → Navigate away
3. `/investigate` → Select env/site/hostname, fetch logs, run analysis → Navigate away
4. `/assistant` → Send a message, get response → Navigate away
5. `/sitemap` → Select a site, toggle layers, upload trajectory → Navigate away
6. `/slack-investigation` → Run an investigation → Navigate away
7. **Return to each page in reverse order** — verify all data persists
8. **Refresh the browser** — verify all data persists (sessionStorage)
9. **Close tab, open new tab** — verify data is gone (sessionStorage clears)

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete state persistence across all pages using zustand"
```

---

## Task Dependencies

```
Task 1 (install zustand) ──→ Tasks 2-6 (create stores, PARALLEL)
                                │
                                ├──→ Task 7  (migrate bags)
                                ├──→ Task 8  (migrate investigate)
                                ├──→ Task 9  (migrate assistant)
                                ├──→ Task 10 (migrate sitemap)
                                └──→ Task 11 (migrate slack-investigation)
                                          │
                                          ▼
                                    Task 12 (hydration guard)
                                          │
                                          ▼
                                    Task 13 (final integration test)
```

- **PARALLEL tasks**: Tasks 2-6 (store files have no dependencies on each other)
- **SERIAL tasks**: Task 1 → [2-6] → [7-11] → 12 → 13
- Tasks 7-11 can technically be parallelized (each modifies a different page file), but are listed serial because each should be verified individually.

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **Zustand over Context API** | No provider wrapper needed in layout, simpler API, built-in persistence middleware |
| **sessionStorage over localStorage** | Data clears when tab closes — prevents stale data across sessions; user won't see 3-week-old search results |
| **One store per page** | Matches current page-based architecture; stores stay focused and small |
| **Transient state stays local** | Loading flags, error states, dropdown visibility are ephemeral — no point persisting |
| **`partialize` to exclude heavy data** | `allLines`, `volumeData`, `timeline`, `mapData`, `markers`, `trajectory` are too large for sessionStorage (~5-10 MB limit). They stay in-memory in the store for cross-page retention, but are NOT written to sessionStorage. On page reload, re-fetch using persisted filters |
| **`version: 1` on all stores** | Future-proof schema migration — when store shape changes, bump version and Zustand discards stale data automatically instead of crashing |
| **`devtools` middleware (dev only)** | Enables Zustand devtools inspection in development, zero cost in production |
| **No functional updaters on store setters** | Zustand setters ≠ React setState. Use dedicated actions (`addMessage`, `updateMessage`) that call `set((state) => ...)` internally |
| **Auto-reset on new operations** | `resetBags()` on new upload, `resetInvestigate()` on new query — prevents stale results bleeding into fresh workflow |
| **`visibility: hidden` hydration guard** | No layout flicker vs skeleton approach — page renders at correct dimensions, becomes visible in a single frame after Zustand rehydrates |
| **Set → Array serialization** | `Set` is not JSON-serializable; convert at the boundary |
| **Cross-tab: sessionStorage is per-tab** | Intentional — each tab is an independent workspace. No shared state across tabs |
