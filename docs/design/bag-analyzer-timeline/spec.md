# Bag Analyzer Chronological Timeline — Feature Spec

> Status: Proposed
> Date: 2026-03-12
> Scope: `frontend/app/bags/page.tsx`, `frontend/components/bags/*`, `frontend/lib/{api.ts,types.ts}`, `backend/app/routes/bags.py`, `backend/services/ros/log_extractor.py`, `backend/schemas/bag_analysis.py`

## 1. Problem Statement

Current `Bag Analyzer` behavior after upload:
- Shows volume buckets (`/api/v1/bags/timeline`) for macro distribution.
- Full log lines appear only after `Analyze Full Bag`.

Gap:
- Users cannot immediately inspect full rosbag logs in strict chronological order after upload.
- There is no dedicated timeline field for complete event browsing.
- UI readability and alignment for long log sessions need stronger structure and loading behavior.

## 2. Goals

1. Automatically extract timestamps from uploaded rosbag and display all logs in chronological timeline view.
2. Add a dedicated Timeline field/section in Bag Analyzer page immediately after upload.
3. Present logs with clear alignment and readable structure (`time`, `level`, `node`, `message`).
4. Keep loading smooth and execution efficient for large bags.
5. Preserve current bucket chart behavior while adding detailed timeline browsing.

## 3. Non-Goals

1. Replacing the existing AI analysis flow.
2. Adding realtime streaming from live ROS topics.
3. Full-text indexing of every bag in persistent DB (out of scope for this iteration).

## 4. User Experience (Target)

## 4.1 Page Flow

1. User uploads `.bag`/`.db3`.
2. Page shows:
- `Log Volume Timeline` (existing chart).
- New `Chronological Timeline` field (detailed event list).
3. Timeline field loads first page quickly with skeleton rows.
4. User scrolls for more entries (infinite pagination).
5. User filters by level/node/search without blocking UI.
6. User optionally selects a time window to pass into `Analyze` action.

## 4.2 Timeline Section Layout

1. Section header:
- Title: `3. Chronological Timeline`
- Summary badges: total logs, start time, end time, loaded count.
- Quick filters: level chips, node filter input, message search.

2. Timeline table/list body with fixed column alignment:
- Column 1: `Time` (monospace, fixed width)
- Column 2: `Level` (color-coded badge)
- Column 3: `Node` (fixed width, ellipsis)
- Column 4: `Message` (wrap/expand)

3. Structured row behavior:
- Alternating subtle row background for scanability.
- Group separators on significant time gaps (optional threshold, e.g. > 2s).
- Expand/collapse for long message text.

4. UX polish:
- Sticky column header.
- Empty state and error state.
- Skeleton loading rows on first fetch and page fetch.

## 5. Functional Requirements

## 5.1 Backend API

Add a dedicated endpoint for paginated chronological logs:

`GET /api/v1/bags/timeline/events`

Query params:
- `bag_path: str` (required)
- `offset: int = 0`
- `limit: int = 200` (max 1000)
- `level: str | None` (`DEBUG|INFO|WARN|ERROR|FATAL`)
- `node: str | None`
- `q: str | None` (message contains)
- `start_ts: float | None`
- `end_ts: float | None`

Response:
- `bag_path`
- `total_count` (matching current filters)
- `offset`
- `limit`
- `has_more`
- `entries: LogEntry[]` sorted ascending by timestamp
- `range: {start_ts, end_ts}` for matching entries

Notes:
- Keep existing `/api/v1/bags/timeline` bucket endpoint unchanged.
- Reuse `ROSLogExtractor.extract()` sorted output.

## 5.2 Data Models

Add schema/type:
- `BagTimelineEventsResponse`
- `TimelineQueryParams` (frontend helper type)

`LogEntry` already contains:
- `timestamp`
- `datetime`
- `level`
- `node`
- `message`

No breaking changes to current analysis response.

## 5.3 Frontend Behavior

1. On upload success:
- Fetch buckets (existing).
- Fetch first timeline events page (`offset=0, limit=200`).

2. Infinite pagination:
- Load next page when user nears list end.
- Append in-order entries only.
- Stop when `has_more=false`.

3. Filtering:
- Debounced node/message search (300ms).
- Reset `offset` and entries when filters change.
- Server-side filtering (avoid large client-side scans).

4. Analysis integration:
- Keep current `Analyze Full Bag` and bucket-click analysis.
- Add optional “Analyze Visible Range” button from timeline filter window.

## 6. Performance Plan

## 6.1 Backend Efficiency

1. Avoid repeated full bag decode per request:
- Add in-memory cache keyed by `bag_path + mtime` storing extracted logs.
- Cache TTL configurable (default 10 minutes).
- Invalidate on file mtime change.

2. Pagination done after filtering on cached logs.

3. Return only required fields (already minimal via `LogEntry`).

## 6.2 Frontend Efficiency

1. Render incremental pages, not full bag at once.
2. Cap DOM rows (windowed list strategy):
- Option A: use manual viewport windowing.
- Option B: add lightweight virtualization library if needed.

3. Use memoized row renderer and stable keys.
4. Use monospace + fixed grid widths to avoid layout thrash.

## 6.3 UX Smoothness Targets

1. First timeline paint within 1.5s for medium bags.
2. Scroll remains responsive (>= 50 FPS visual smoothness target).
3. Additional page fetch latency hidden behind skeleton placeholders.

## 7. UI Component Plan

1. New component: `frontend/components/bags/ChronologicalTimeline.tsx`
- Props: `bagPath`, optional callbacks for selected range.
- Handles pagination, filters, loading, and aligned rendering.

2. Existing updates:
- `frontend/app/bags/page.tsx`: insert timeline field after bucket section.
- `frontend/lib/api.ts`: add `fetchTimelineEvents(params)`.
- `frontend/lib/types.ts`: add response types.

3. Styling rules:
- Grid columns (example): `140px 90px 220px 1fr`
- `font-mono` for timestamps and node IDs.
- `max-height` with independent scroll container.
- Spacing scale consistent with existing `card` and `text-xs` styles.

## 8. LLM/Assistant Extensions (Optional in same milestone)

1. Add “Explain this timeline segment” action:
- User selects time range or specific rows.
- Backend reuses existing `/api/v1/bags/analyze` with `window_start/window_end`.

2. Suggested outputs:
- probable cause,
- affected nodes/topics,
- immediate checks,
- confidence score.

3. Local LLM support:
- Continue via existing `LLMService` backend abstraction.

## 9. API Contract Example

`GET /api/v1/bags/timeline/events?bag_path=/data/bags/a.bag&offset=0&limit=3`

```json
{
  "bag_path": "/data/bags/a.bag",
  "total_count": 18452,
  "offset": 0,
  "limit": 3,
  "has_more": true,
  "range": { "start_ts": 1710001000.123, "end_ts": 1710001302.882 },
  "entries": [
    {
      "timestamp": 1710001000.123,
      "datetime": "2026-03-12 10:32:11.123",
      "level": "INFO",
      "node": "/planner",
      "message": "Planner initialized"
    }
  ]
}
```

## 10. Testing Strategy

## 10.1 Backend

1. Unit tests:
- chronological sort order guaranteed.
- pagination correctness (`offset/limit/has_more`).
- filter correctness (`level/node/q/time range`).
- cache hit/miss behavior.

2. API tests:
- 404 for missing bag.
- empty response for valid but no matching logs.
- max-limit enforcement.

## 10.2 Frontend

1. Component tests (or integration tests):
- initial load state and skeletons.
- row alignment and sticky headers.
- infinite scroll fetch behavior.
- filter interactions reset and reload.

2. Manual QA:
- small bag (<1k logs), medium (~20k), large (>100k).
- verify chronological continuity across page boundaries.

## 11. Rollout Plan

1. Phase 1 (MVP):
- backend events endpoint + frontend timeline field with pagination + filters.

2. Phase 2:
- cache tuning + optional virtualization enhancements.

3. Phase 3:
- timeline-to-LLM range analysis shortcuts.

## 12. Acceptance Criteria

1. After upload, user can browse complete rosbag log stream in chronological order without running full analysis first.
2. Timeline rows are clearly aligned and readable across desktop/laptop widths.
3. Loading is smooth with progressive pagination and no UI freezes on medium/large bags.
4. Existing bucket chart and full analysis behavior remain intact.
5. Tests cover endpoint logic and timeline UI interactions.

## 13. Open Questions

1. Default page size: `200` vs `500` for best UX/performance tradeoff?
2. Do we need timezone toggle (UTC vs local) for timestamps in UI?
3. Should timeline include non-rosout topics in a future extension?
4. Should timeline state persist when switching between `logs` and `mapdiff` tabs?

## 14. Review Checkpoint (Required Before Implementation)

Product/Engineering sign-off checklist:
- [ ] API shape accepted (`/timeline/events` + pagination/filter contract)
- [ ] UI structure accepted (column layout + spacing + loading behavior)
- [ ] Performance approach accepted (cache + incremental rendering)
- [ ] Test coverage scope accepted
- [ ] Phase-1 deliverables locked
