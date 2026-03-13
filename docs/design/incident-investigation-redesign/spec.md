# Incident Investigation Page Redesign - Feature Spec

> Status: Proposed
> Date: 2026-03-13
> Scope: `explorer/frontend/app/investigate/page.tsx`, `explorer/frontend/components/investigation/*`, `explorer/frontend/lib/{api.ts,types.ts}`, `explorer/backend/schemas/investigation.py`, `explorer/backend/app/routes/investigation.py`

## 1. Problem Statement

The current Investigation page is functional but overloaded and visually inconsistent for incident triage:
- The page mixes input, system progress, and analysis outputs without strong information hierarchy.
- Incident Details include fields that are either redundant or confusing during real operations.
- The form asks for `title`, `bag_path`, `site_id`, and `sw_version` in the main Incident Details area, which slows down incident reporting and introduces low-quality input.

The requested redesign is a full structural rewrite of the page, with a cleaner IA and stronger visual system.

## 2. Goals

1. Redesign the Investigation page end-to-end with a clear, modern, operational layout.
2. Rebuild Incident Details so it does **not** include:
- `title`
- `bag_path`
- `site_id`
- `sw_version`
3. Preserve investigation pipeline behavior (SSE progress + final analysis tabs) while improving readability and workflow clarity.
4. Make the page responsive and usable on desktop and mobile.
5. Keep API behavior robust and backward compatible where practical.

## 3. Non-Goals

1. Replacing the core investigation engine logic.
2. Changing ranking/scoring algorithms for causes and solutions.
3. Redesigning other pages (`/bags`, `/assistant`, `/sitemap`).

## 4. UX Direction (Complete Redesign)

## 4.1 Information Architecture

New page structure:
1. Hero Header
- Incident workspace title
- Current run status badge (`Idle`, `Running`, `Completed`, `Failed`)
- Primary CTA (`Run Investigation`)

2. Left rail (sticky on desktop)
- `Incident Details` card (short, mandatory operator input)
- `Operational Context` card (optional metadata and toggles)
- `Run Controls` card (submit, clear, loading state)

3. Right workspace
- `Pipeline Timeline` card (SSE step-by-step progress)
- `Findings Overview` card (confidence and intervention status)
- `Analysis Tabs` card (`Root Causes`, `Solutions`, `Similar Cases`, `Raw Analysis`)

4. Mobile behavior
- Left rail cards stack above workspace cards
- Sticky submit bar at bottom while form is dirty or running

## 4.2 Incident Details (Required Change)

`Incident Details` must contain only high-signal incident narrative fields:
- `What happened?` (required textarea; replaces title+description split)
- `Observed impact` (required select/chips: `Mission blocked`, `Degraded`, `Intermittent`, `Unknown`)
- `When detected` (optional datetime-local)

Explicit removals from Incident Details:
- Remove `Title`
- Remove `Bag file path`
- Remove `Site ID`
- Remove `SW version`

## 4.3 Operational Context (Optional)

To avoid losing useful context while keeping Incident Details clean:
- `Grafana link` (optional)
- `Config/firmware changed recently` (boolean)
- Optional `Evidence attachment mode` (future-ready placeholder: bag upload picker, not raw path text)

This separates core incident reporting from optional enrichment.

## 4.4 Visual Design System

Use a distinct, intentional visual language (not a generic card stack):
- Typography:
- Headings: `Space Grotesk`
- Body: `Manrope`
- Technical values: `JetBrains Mono`
- Color direction:
- Deep slate base + teal/amber accents for operation state
- Success/info/warning/error semantic tokens in CSS variables
- Surfaces:
- Layered gradients with subtle noise and radial highlights
- Deliberate section dividers and sticky card rails
- Motion:
- Staggered entry for cards on load
- Progress bar transitions tied to SSE step changes
- Tab-content crossfade/slide (short duration)

## 5. Functional Requirements

## 5.1 Frontend Form Contract

Replace existing form contract:
- Current: `title`, `description`, `bag_path`, `site_id`, `grafana_link`, `sw_version`, `config_changed`
- New UI model:
- `incident_summary: string` (required)
- `observed_impact: "mission_blocked" | "degraded" | "intermittent" | "unknown"` (required)
- `detected_at?: string`
- `grafana_link?: string`
- `config_changed?: boolean`

Mapping rule for backend compatibility:
- `description = incident_summary`
- `title = generated short summary` (frontend or backend generated)

## 5.2 API and Schema Adjustments

Backend schema updates (`IncidentReportRequest`):
1. Make `title` optional.
2. Continue accepting `bag_path`, `site_id`, `sw_version` for backward compatibility, but do not require or surface in redesigned UI.
3. If `title` is missing, auto-generate from description (first sentence or first 80 chars).

SSE endpoint updates:
1. `title` query param becomes optional.
2. Keep support for existing clients that still send `title`.

## 5.3 Pipeline and Results

1. Keep current pipeline step model: `start`, `bag_analysis`, `similarity_search`, `llm_analysis`, `complete/error`.
2. Present progress as a timeline rail with clear active step and timestamp.
3. Results panel remains tabbed, but with stronger hierarchy:
- Summary first
- Actionable items second
- Raw analysis last

## 6. Component Plan

Frontend:
1. `explorer/frontend/app/investigate/page.tsx`
- Rebuild layout into rail + workspace architecture.
- Replace current form fields with new Incident Details and Operational Context grouping.

2. New components (proposed):
- `explorer/frontend/components/investigation/IncidentDetailsForm.tsx`
- `explorer/frontend/components/investigation/OperationalContextCard.tsx`
- `explorer/frontend/components/investigation/PipelineTimeline.tsx`
- `explorer/frontend/components/investigation/InvestigationHeader.tsx`

3. Existing components reused/refined:
- `ConfidenceGauge.tsx`
- `HumanInterventionBanner.tsx`
- `RankedCausesPanel.tsx`
- `SimilarCasesTable.tsx`

Shared types/API:
1. `explorer/frontend/lib/types.ts`
- Add new frontend-only input type for redesigned form.

2. `explorer/frontend/lib/api.ts`
- Update `streamInvestigation` and `investigate` payload typing to allow optional `title`.

Backend:
1. `explorer/backend/schemas/investigation.py`
- Update `IncidentReportRequest` title optionality.

2. `explorer/backend/app/routes/investigation.py`
- Handle missing title gracefully in both POST and SSE route flows.

## 7. Validation and Error Handling

1. Client validation:
- `incident_summary` required, min length 20.
- `observed_impact` required.

2. API error handling:
- Retain interceptor-based detail message behavior.
- Clear banner for SSE disconnect and retry action.

3. Empty states:
- Pre-run: guidance card with example incident narrative.
- Post-error: retry action and link to diagnostics.

## 8. Testing Strategy

Frontend:
1. Form validation tests for new required fields.
2. Snapshot/interaction tests for responsive rail/workspace layout.
3. SSE progress rendering tests (step transitions, completion state).
4. Regression tests for tabs and confidence/intervention cards.

Backend:
1. Unit tests for optional-title behavior and fallback title generation.
2. API tests for POST and SSE with and without title.
3. Backward compatibility tests with old payload shape.

## 9. Acceptance Criteria

1. Investigation page is structurally redesigned (new layout and visual hierarchy), not a minor style patch.
2. Incident Details section does not show or request:
- `title`
- `bag_path`
- `site_id`
- `sw_version`
3. User can still run an investigation end-to-end from UI.
4. SSE pipeline and final analysis tabs work as before.
5. Mobile layout remains functional and readable.
6. Existing clients posting old payloads remain supported.

## 10. Rollout Plan

1. Implement frontend redesign behind normal route update.
2. Deploy backend optional-title compatibility first or together with frontend.
3. Run smoke tests:
- fresh incident run from UI
- SSE interruption handling
- result tab rendering

## 11. Review Checkpoint (Mandatory)

Before implementation starts, review and approve:
1. New Incident Details field set (`incident_summary`, `observed_impact`, `detected_at`).
2. Decision to remove `title`, `bag_path`, `site_id`, `sw_version` from Incident Details UI.
3. Optional-title backend compatibility approach.
4. Visual direction (typography, color system, layout).
