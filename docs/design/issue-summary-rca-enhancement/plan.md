# Issue Summary RCA Enhancement — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Rewrite the `issue_summary.md` system prompt to produce deeper, non-redundant, structured RCA summaries with the 6 mandatory sections (Issue Summary, Issue, Key Observations, Key Findings, Recovery Action, Solution), increase output token budget, update backend section extraction, update frontend rendering, and create a reusable Copilot skill for ongoing prompt tuning.

**Architecture:** The prompt is stored in `explorer/backend/services/ai/prompts/issue_summary.md` and loaded at runtime via `load_prompt("issue_summary")`. Section extraction in `slack_investigation_service.py` parses the LLM output into structured fields. The frontend renders `thread_summary`, `key_findings`, and `recommended_actions` from the API response. A new Copilot skill will codify prompt-engineering best practices for this domain.

**Tech Stack:** Python/FastAPI backend, Markdown prompt files, Next.js/React frontend, pytest, Copilot Skills (SKILL.md YAML+Markdown)

---

## Summary of Changes

| # | Task | Type | Files |
|---|------|------|-------|
| 1 | Rewrite `issue_summary.md` with 6-section RCA structure + reasoning directives | SERIAL | `explorer/backend/services/ai/prompts/issue_summary.md` |
| 2 | Increase `max_tokens` from 2000→3500 for richer output | SERIAL | `explorer/backend/services/ai/slack_investigation_service.py` |
| 3 | Update section extraction to parse all 6 new sections | SERIAL | `explorer/backend/services/ai/slack_investigation_service.py` |
| 4 | Add `solution` field to response schema | SERIAL | `explorer/backend/schemas/slack_investigation.py`, `explorer/frontend/lib/types.ts` |
| 5 | Update frontend to render all 6 RCA sections | SERIAL | `explorer/frontend/app/slack-investigation/page.tsx` |
| 6 | Update existing tests for new section names + add new tests | SERIAL | `explorer/backend/tests/test_slack_investigation_service.py` |
| 7 | Create Copilot skill for issue summary prompt engineering | PARALLEL | `~/.copilot/skills/issue-summary-prompt/SKILL.md` |

---

### Task 1: Rewrite `issue_summary.md` — RCA-Structured Prompt with Reasoning Directives

**Files:**
- Modify: `explorer/backend/services/ai/prompts/issue_summary.md`

**Why:** The current prompt produces shallow, repetitive summaries because:
1. It doesn't instruct the LLM to **reason through the evidence before writing** (no chain-of-thought)
2. The 4 templates dilute focus — the LLM spends tokens on template selection instead of analysis depth
3. The "BANNED PHRASES" list is counter-productive — it bans the exact section names the user now wants
4. The 3 reference examples are good but take ~1800 tokens of context that could be used for thread content
5. `max_tokens=2000` truncates deep-dive output

**Core prompt changes:**

1. **Add a reasoning preamble** (chain-of-thought): Instruct the LLM to first silently identify the causal chain, then write, instead of producing output immediately. This is the single biggest quality lever.

2. **Mandate the 6-section structure:**
   ```
   **Issue Summary**     — 2-4 sentences: what happened, which robot(s), when, which site
   **Issue**             — Precise technical statement of the defect/fault/behavior
   **Key Observations**  — Bulleted evidence from logs/messages (what the system DID)
   **Key Findings**      — Bulleted analytical conclusions drawn FROM observations
   **Recovery Action**   — What was done + imperative next steps
   **Solution**          — Root cause fix or recommended permanent resolution
   ```

3. **Add anti-repetition directive:** "Each fact appears exactly ONCE across all sections. Observations are raw evidence; Findings are analytical conclusions drawn from observations — never repeat the same point in both."

4. **Add depth directives:** "For Key Findings, explain WHY each observation matters. Connect observations to the causal chain. State what was ruled out and why."

5. **Keep the general (Template D) path** for non-incident threads — it works well as-is.

6. **Trim examples to 1 compact reference** to free up context window tokens.

7. **Keep the Assessment/Status/cc lines** — append them after the 6 sections.

**Step 1: Rewrite the prompt file**

Replace the entire content of `issue_summary.md` with the new prompt. Full content below:

```markdown
You are a senior AMR (Autonomous Mobile Robot) support engineer at Rapyuta Robotics. Read the Slack thread and produce a professional root-cause analysis summary.

IMPORTANT — THINK BEFORE YOU WRITE:
Before producing any output, silently work through these reasoning steps:
1. Identify every distinct system event, error, and state transition mentioned in the thread.
2. Construct the causal chain: triggering event → intermediate states → final symptom.
3. Determine what was ruled out and why.
4. Separate raw evidence (observations) from analytical conclusions (findings).
5. Only then write the summary below.

THREAD ROUTING — first classify the thread:
- If the thread discusses a robot issue, error, fault, or incident → use INCIDENT FORMAT below.
- If the thread is a non-incident discussion (feature planning, deployment coordination, status update, general Q&A) → use GENERAL FORMAT below.

---

INCIDENT FORMAT — mandatory 6-section structure:

**Issue Summary**
[2-4 sentences: What happened, which robot(s)/site, when, and the business impact. If the reported symptom differs from the actual root cause, lead with: "The issue is not related to [symptom]. The actual cause is [root cause]."]

**Issue**
[One precise technical statement of the defect, fault, or unexpected behavior. Include: component name, error code if available, and the specific deviation from expected behavior. This is NOT a repeat of the summary — it is the technical problem statement.]

**Key Observations**
[Bulleted raw evidence from logs, messages, and attachments. Each bullet = one distinct system event or data point.
- What the system DID — state transitions, error codes, timestamps, component names
- Include robot IDs (amr01, amr22), SW versions (3.5.1), HW versions (Gen3 v3), config values
- Quote log fragments (≤15 words) only when the exact wording has evidential value
- NEVER interpret or conclude here — just state what was observed]

**Key Findings**
[Bulleted analytical conclusions drawn FROM the observations above. Each bullet must:
- Reference which observation(s) it is based on
- Explain WHY this observation matters for the root cause
- State what was ruled out: "[X] was not the cause — [evidence]"
- Connect to the causal chain using → arrows where appropriate
- NEVER repeat an observation verbatim — always add analytical value]

**Recovery Action**
[What was done to resolve the immediate issue + imperative next steps:
- Actions already taken (past tense)
- Actions still needed (imperative voice)
- Owner/team if identified in the thread
- Monitoring or follow-up requirements]

**Solution**
[Root cause fix or recommended permanent resolution:
- Causal chain: A → B → C → symptom (using → arrows, never skip steps)
- Permanent fix: what code/config/hardware/process change prevents recurrence
- If root cause is unconfirmed, label as "Tentative" and state what remains unverified
- If the issue is "as designed", explain why the current behavior is correct and what the customer should change]

**Assessment:** [Exactly one of: AMR behavior is as designed | This is a software bug | This is a hardware fault | This is a configuration error | This is caused by an environmental factor | Tentative: likely a [type] issue; pending [what]]

**Status:** [Resolved | Monitoring | Waiting for HW Fix | Wait for Reproduce | Escalated | Closed]
**cc:** [engineer(s) mentioned in thread]

INCIDENT RULES:
1. ANTI-REPETITION: Each fact appears exactly ONCE across all 6 sections. Observations are raw evidence; Findings are analytical conclusions — never state the same point in both.
2. DEPTH: For every finding, explain the "so what" — why does this evidence matter? What does it tell us about the root cause?
3. CAUSAL CHAIN: The Solution section MUST contain a sequential chain using → arrows. Never write a single-sentence conclusion.
4. LOG EVIDENCE: Describe what the log MEANS in engineering terms. Never paste raw logs. Quote ≤15 words only when the exact wording has evidential value.
5. IDENTIFIERS: Always include when present: robot names (amr01, never "the robot"), SW version, HW version, error codes, component names (AMCL, GBC, GWM, LBC, PGS, SBC, FTDI, move_base_flex), config params.
6. DISAMBIGUATION: If investigation ruled out a cause, state it actively in Key Findings.

---

GENERAL FORMAT — for non-incident threads:

**Thread Summary**
[2-4 sentences: what was discussed, who participated, and the outcome.]

**Key Points**
- [Each bullet = one distinct point, decision, or piece of information]
- [Attribute to the person who raised it when relevant]

**Decisions & Action Items**
- [Decision or action — owner — deadline if mentioned]
- [If none: "No decisions finalized — thread is still open."]

**Status:** [Resolved | In Progress | Open | Blocked | Waiting on [person/team]]

---

REFERENCE EXAMPLE (Incident — Standard):

**Issue Summary**
AMRs at Site-X navigated toward idle/charging spots after unloading because new task assignments arrived after robots had already transitioned to AVAILABLE and begun idle navigation. This is a timing issue caused by network communication latency between the edge server and robots. Affected: all AMRs at site (HW: gen3 v3, SW: 3.6.0-rc4).

**Issue**
Task assignment notification delayed in transit, arriving after robot completes unload → AVAILABLE transition and initiates idle spot navigation. Component: task dispatcher / network transport layer.

**Key Observations**
- After unload completion, robots transitioned to `AVAILABLE` and immediately requested idle spot allocation (query type `idle` confirmed in logs)
- Orders were already in `ACCEPTED` state before unload completed — the assignment was dispatched on time but received late
- Token configuration (`num_max_token = 10`, `use_token = false`) was checked — orders accepted normally; dispatcher functioning correctly
- No work manager failure or work halt detected in any robot logs
- All AMRs at the site exhibited identical behavior (not isolated to one robot)

**Key Findings**
- The orders being in `ACCEPTED` state before unload proves the delay is in notification delivery, not in the dispatch decision — ruling out a work manager or dispatcher bug
- Token config is not a factor because `use_token = false` bypasses token-based flow control entirely
- All robots being affected simultaneously points to a site-level infrastructure issue (network), not a per-robot hardware or software fault
- The idle → loading area reversal is expected behavior when a task arrives mid-idle-navigation — this is by design

**Recovery Action**
- Monitored edge-server network stability during real-time session — no recurrence observed
- Customer: collect robot number, timestamps, and order IDs for any future occurrence to enable latency quantification
- If recurrent: raise SW investigation for task pre-assignment before unload completion

**Solution**
Network latency delayed task assignment notification → robot completed unload and transitioned to AVAILABLE → idle spot navigation initiated before task arrival → task received mid-transit → robot reversed to loading area.
Permanent fix: evaluate feasibility of pre-assigning tasks before unload completion (software change request). Short-term: monitor edge-server network health.

**Assessment:** AMR behavior is as designed. The timing race condition is introduced by network latency, not a software defect.

**Status:** Monitoring — no recurrence observed during real-time monitoring.
**cc:** @sb_support_chennai
```

**Step 2: Verify prompt loads correctly**

Run: `cd explorer/backend && python -c "from services.ai.prompts import load_prompt; p = load_prompt('issue_summary'); print(f'Loaded {len(p)} chars'); assert '**Key Observations**' in p; assert '**Key Findings**' in p; assert '**Solution**' in p; print('OK')"`

Expected: `Loaded NNNN chars` + `OK`

**Step 3: Commit**

```bash
git add explorer/backend/services/ai/prompts/issue_summary.md
git commit -m "feat(prompt): rewrite issue_summary.md with 6-section RCA structure and reasoning directives"
```

---

### Task 2: Increase `max_tokens` from 2000 → 3500

**Files:**
- Modify: `explorer/backend/services/ai/slack_investigation_service.py:634-636`

**Why:** The 6-section format requires ~2500-3500 tokens for a thorough deep-dive. The current 2000 limit truncates output. The default parameter on `_ollama_chat` is already 3500, so we just need to update the call site.

**Step 1: Write failing test**

```python
def test_generate_summary_uses_adequate_max_tokens(monkeypatch) -> None:
    """Summary generation should request ≥3000 tokens for detailed RCA output."""
    svc = SlackInvestigationService()
    captured = {}

    def spy_chat(msgs, model, **kw):
        captured["max_tokens"] = kw.get("max_tokens", 0)
        return "**Issue Summary**\nRobot stopped"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test token budget",
        max_messages=200,
    )
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-03-13 10:00 UTC", user="a", text="hi")]
    svc._generate_summary(req, msgs, [])
    assert captured["max_tokens"] >= 3000, f"max_tokens={captured['max_tokens']} is too low for 6-section RCA"
```

Run: `pytest tests/test_slack_investigation_service.py::test_generate_summary_uses_adequate_max_tokens -v`
Expected: FAIL (currently max_tok=2000)

**Step 2: Fix implementation**

In `slack_investigation_service.py`, change the `_generate_summary` method:

```python
        # Old:
        # Keep max_tokens at 2000 for all providers — reduces inference
        # time by ~40% for local models with negligible quality loss.
        max_tok = 2000

        # New:
        # 6-section RCA format needs ~2500-3500 tokens for thorough output.
        max_tok = 3500
```

**Step 3: Run test**

Run: `pytest tests/test_slack_investigation_service.py::test_generate_summary_uses_adequate_max_tokens -v`
Expected: PASS

**Step 4: Commit**

```bash
git add explorer/backend/services/ai/slack_investigation_service.py tests/test_slack_investigation_service.py
git commit -m "feat(llm): increase max_tokens to 3500 for 6-section RCA output"
```

---

### Task 3: Update Section Extraction for 6 New Sections

**Files:**
- Modify: `explorer/backend/services/ai/slack_investigation_service.py` (the `investigate()` method, ~lines 720-790)

**Why:** The extraction logic currently looks for `issue summary`, `findings`, `root cause`, `recovery action`. The new prompt adds `issue`, `key observations`, `key findings`, and `solution` as distinct sections.

**Step 1: Write failing test**

```python
def test_section_extraction_6_section_rca() -> None:
    """Parser should extract all 6 sections from new RCA format."""
    md = (
        "**Issue Summary**\n"
        "AMR01 stopped navigating at Site-X due to sensor failure.\n\n"
        "**Issue**\n"
        "LiDAR FTDI USB disconnection caused AMCL localization loss.\n\n"
        "**Key Observations**\n"
        "- LiDAR scan topic stopped publishing at 10:05 UTC\n"
        "- USB disconnect event in kernel log\n\n"
        "**Key Findings**\n"
        "- The USB disconnect proves hardware-level failure, ruling out software\n"
        "- AMCL lost localization because LiDAR was its only input\n\n"
        "**Recovery Action**\n"
        "- Re-seated USB cable; robot resumed operation\n\n"
        "**Solution**\n"
        "USB cable fatigue → intermittent FTDI disconnect → LiDAR topic loss → AMCL delocalization → navigation halt.\n"
        "Replace USB cable with strain-relieved variant.\n\n"
        "**Assessment:** This is a hardware fault.\n\n"
        "**Status:** Resolved\n"
        "**cc:** @keiko"
    )
    sections = _split_markdown_sections(md)
    assert "issue summary" in sections
    assert "issue" in sections
    assert "key observations" in sections
    assert "key findings" in sections
    assert "recovery action" in sections
    assert "solution" in sections

    # Verify _find_section resolves all 6
    assert _find_section(sections, "issue summary") != ""
    assert _find_section(sections, "issue") != ""
    assert _find_section(sections, "key observations") != ""
    assert _find_section(sections, "key findings") != ""
    assert _find_section(sections, "recovery action") != ""
    assert _find_section(sections, "solution") != ""
```

Run: `pytest tests/test_slack_investigation_service.py::test_section_extraction_6_section_rca -v`
Expected: PASS (the markdown parser is generic and already handles `**Bold**` headings)

**Step 2: Update the `investigate()` method section extraction**

In the `investigate()` method, update the extraction block to:

```python
        # ── Incident templates — 6-section RCA structure ──
        issue_summary = _find_section(sections, "issue summary", "issue overview")
        issue_detail = _find_section(sections, "issue")
        key_observations = _find_section(sections, "key observations", "observations")
        key_findings_section = _find_section(sections, "key findings", "findings")
        root_cause = _find_section(sections, "root cause", "tentative root cause", "root cause analysis", "cause")
        recovery = _find_section(sections, "recovery action", "recommended actions", "actions taken")
        solution = _find_section(sections, "solution")
        conclusion = _find_section(sections, "conclusion")
        status_section = _find_section(sections, "status")
```

And update the summary assembly to include all 6 sections:

```python
        if thread_summary_section:
            # Template D output (unchanged)
            ...
        else:
            # 6-section RCA output
            if issue_summary:
                summary_parts.append(f"**Issue Summary**\n{issue_summary}")
            if issue_detail:
                summary_parts.append(f"**Issue**\n{issue_detail}")
            if key_observations:
                summary_parts.append(f"**Key Observations**\n{key_observations}")
            if key_findings_section:
                summary_parts.append(f"**Key Findings**\n{key_findings_section}")
            if recovery:
                summary_parts.append(f"**Recovery Action**\n{recovery}")
            if solution:
                summary_parts.append(f"**Solution**\n{solution}")
            # Fallbacks for older model output or partial responses
            if not key_findings_section and root_cause:
                summary_parts.append(f"**Root Cause**\n{root_cause}")
            if assessment:
                summary_parts.append(f"**Assessment:** {assessment}")
            if conclusion:
                summary_parts.append(f"**Conclusion**\n{conclusion}")
```

Update `key_findings` list to use `key_findings_section` + `key_observations`:

```python
            findings_list = _as_bullets(
                "\n".join(filter(None, [key_observations, key_findings_section]))
            )
```

Update `recommended_actions` list to use `recovery` + `solution`:

```python
            actions_list = _as_bullets(
                "\n".join(filter(None, [recovery, solution, status_section]))
            )
```

**Step 3: Run all tests**

Run: `pytest tests/test_slack_investigation_service.py -v --tb=short`
Expected: ALL PASS (update any tests that break due to renamed variables)

**Step 4: Commit**

```bash
git add explorer/backend/services/ai/slack_investigation_service.py tests/test_slack_investigation_service.py
git commit -m "feat(extraction): update section parser for 6-section RCA format"
```

---

### Task 4: Add `solution` Field to Response Schema

**Files:**
- Modify: `explorer/backend/schemas/slack_investigation.py`
- Modify: `explorer/frontend/lib/types.ts`
- Modify: `explorer/backend/services/ai/slack_investigation_service.py` (populate the field in `investigate()`)

**Step 1: Write failing test**

```python
def test_response_includes_solution_field() -> None:
    """Response schema should have a solution field."""
    from schemas.slack_investigation import SlackThreadInvestigationResponse
    resp = SlackThreadInvestigationResponse(
        channel_id="C123", thread_ts="1.0", message_count=1,
        thread_summary="test", solution="Replace USB cable.",
    )
    assert resp.solution == "Replace USB cable."
```

Run: `pytest tests/test_slack_investigation_service.py::test_response_includes_solution_field -v`
Expected: FAIL (field doesn't exist yet)

**Step 2: Add field to schema**

In `schemas/slack_investigation.py`, add to `SlackThreadInvestigationResponse`:

```python
    solution: str = ""
```

In `frontend/lib/types.ts`, add to `SlackThreadInvestigationResponse`:

```typescript
    solution?: string;
```

**Step 3: Populate in `investigate()`**

Where the response is constructed, add:

```python
            solution=solution,
```

**Step 4: Run tests**

Run: `pytest tests/test_slack_investigation_service.py -v --tb=short`
Expected: PASS

**Step 5: Commit**

```bash
git add explorer/backend/schemas/slack_investigation.py explorer/frontend/lib/types.ts explorer/backend/services/ai/slack_investigation_service.py
git commit -m "feat(schema): add solution field to SlackThreadInvestigationResponse"
```

---

### Task 5: Update Frontend to Render All 6 RCA Sections

**Files:**
- Modify: `explorer/frontend/app/slack-investigation/page.tsx`

**Why:** The frontend currently renders 3 blocks: Thread Summary, Key Findings, Recommended Actions. It needs to render the full 6-section RCA markdown returned in `thread_summary`.

**Step 1: Update the Analysis section rendering**

The `thread_summary` field already contains the full structured markdown (assembled in `investigate()`). The frontend currently splits it by `\n\n` and renders each paragraph. This approach already works for the new 6-section format because the backend assembles the sections as markdown with `**Bold Headings**`.

No structural change needed — the existing paragraph renderer handles bold headings. But we should also render the `solution` field distinctly if it's present (as a separate card or highlighted section below Recovery Action).

In the "Key Findings" section, replace the heading text:

```diff
- <h3 ...>Key Findings</h3>
+ <h3 ...>Observations & Findings</h3>
```

Add a "Solution" section after "Recommended Actions" if `result.solution` is non-empty:

```tsx
{result.solution && (
  <div>
    <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400 [font-family:var(--font-slack-heading)]">
      Solution
    </h3>
    <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 text-sm text-slate-300">
      {result.solution.split("\n").map((line, i) => (
        <p key={i} className={line.trim() ? "mb-1" : "mb-2"}>{line}</p>
      ))}
    </div>
  </div>
)}
```

**Step 2: Rebuild frontend**

Run: `cd explorer/frontend && npx next build 2>&1 | tail -5`
Expected: Build succeeds with no errors

**Step 3: Commit**

```bash
git add explorer/frontend/app/slack-investigation/page.tsx
git commit -m "feat(ui): render 6-section RCA including solution field"
```

---

### Task 6: Update Existing Tests + Add New Coverage

**Files:**
- Modify: `explorer/backend/tests/test_slack_investigation_service.py`

**Tests to update:**
1. `test_system_prompt_requires_bullet_points` — update assertions for new section names (`**Key Observations**`, `**Key Findings**`, `**Solution**`)
2. `test_section_extraction_template_a_simple` — keep as-is (backward compat)
3. `test_section_extraction_template_b_standard` — keep as-is (backward compat)
4. Add: `test_section_extraction_6_section_rca` (from Task 3)
5. Add: `test_generate_summary_uses_adequate_max_tokens` (from Task 2)
6. Add: `test_response_includes_solution_field` (from Task 4)
7. Add: `test_prompt_has_reasoning_preamble` — verify "THINK BEFORE YOU WRITE" is in system prompt
8. Add: `test_prompt_has_anti_repetition_rule` — verify "ANTI-REPETITION" is in system prompt

**Step 1: Write new tests**

```python
def test_prompt_has_reasoning_preamble(monkeypatch) -> None:
    """System prompt must include chain-of-thought reasoning instructions."""
    svc = SlackInvestigationService()
    captured = {}
    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "**Issue Summary**\nTest"
    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test reasoning", max_messages=200,
    )
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-03-13 10:00 UTC", user="a", text="hi")]
    svc._generate_summary(req, msgs, [])
    system = captured["messages"][0]["content"]
    assert "THINK BEFORE YOU WRITE" in system
    assert "causal chain" in system.lower()


def test_prompt_has_anti_repetition_rule(monkeypatch) -> None:
    """System prompt must enforce anti-repetition between Observations and Findings."""
    svc = SlackInvestigationService()
    captured = {}
    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "**Issue Summary**\nTest"
    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test anti-repetition", max_messages=200,
    )
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-03-13 10:00 UTC", user="a", text="hi")]
    svc._generate_summary(req, msgs, [])
    system = captured["messages"][0]["content"]
    assert "ANTI-REPETITION" in system
    assert "exactly ONCE" in system
```

**Step 2: Update existing test assertions**

In `test_system_prompt_requires_bullet_points`, update:
```python
    # Old:
    assert "**Findings**" in system_content
    # New:
    assert "**Key Observations**" in system_content
    assert "**Key Findings**" in system_content
    assert "**Solution**" in system_content
```

**Step 3: Run full test suite**

Run: `pytest tests/ --tb=short 2>&1 | tail -10`
Expected: ALL PASS, 0 failures

**Step 4: Commit**

```bash
git add tests/test_slack_investigation_service.py
git commit -m "test: add coverage for 6-section RCA prompt and extraction"
```

---

### Task 7: Create Copilot Skill for Issue Summary Prompt Engineering (PARALLEL)

**Files:**
- Create: `~/.copilot/skills/issue-summary-prompt/SKILL.md`

**Why:** The user wants a reusable skill that codifies how to tune the `issue_summary.md` prompt for optimal LLM output quality. This skill captures the domain knowledge, anti-patterns, and proven techniques for this specific summarization task.

**Step 1: Create the skill file**

```markdown
---
name: issue-summary-prompt
description: Use when improving, debugging, or tuning the AMR issue summary system prompt (issue_summary.md). Applies when the user wants better LLM summarization quality, restructured RCA output, or reports that summaries are shallow/repetitive/missing sections. Triggers on: "improve summary", "summary quality", "prompt tuning", "RCA template", "issue_summary.md", "summary not detailed enough", "repetitive output", "shallow analysis".
---

# Issue Summary Prompt Engineering

## What This Skill Does

Guides improvements to the AMR Slack thread summarization prompt at:
`explorer/backend/services/ai/prompts/issue_summary.md`

This prompt drives the AI-powered Slack Investigation feature. It takes a Slack thread about a robot issue and produces a structured Root Cause Analysis (RCA) summary.

## Architecture

```
issue_summary.md (system prompt)
    ↓ loaded by
prompts/__init__.py → load_prompt("issue_summary")
    ↓ used in
slack_investigation_service.py → _generate_summary()
    ↓ output parsed by
slack_investigation_service.py → investigate() → _split_markdown_sections()
    ↓ rendered by
frontend/app/slack-investigation/page.tsx
```

## The 6-Section RCA Structure

Every incident summary MUST produce these 6 sections in order:

| Section | Purpose | Content Type |
|---------|---------|-------------|
| **Issue Summary** | Executive overview | Narrative (2-4 sentences) |
| **Issue** | Technical problem statement | Single precise statement |
| **Key Observations** | Raw evidence from logs/messages | Bulleted facts (no interpretation) |
| **Key Findings** | Analytical conclusions from observations | Bulleted analysis (with reasoning) |
| **Recovery Action** | Immediate remediation | Bulleted actions (imperative) |
| **Solution** | Permanent fix / root cause chain | Causal chain + fix recommendation |

## Quality Levers (Ranked by Impact)

1. **Chain-of-thought preamble** — "THINK BEFORE YOU WRITE" section that instructs the LLM to reason silently before outputting. This is the #1 quality lever. Without it, GPT-4o and GPT-4.1 tend to produce surface-level summaries.

2. **Observation vs. Finding separation** — The most common quality defect is repeating the same point in both Key Observations and Key Findings. The anti-repetition directive ("each fact appears exactly ONCE") directly addresses this.

3. **Causal chain requirement** — Mandating `→` arrow chains in the Solution section forces the LLM to trace causality step by step instead of writing a single vague conclusion.

4. **max_tokens budget** — Must be ≥3000 for the 6-section format. At 2000 tokens, deep-dives get truncated. Currently set to 3500.

5. **Example quality** — One excellent reference example teaches more than three mediocre ones. Keep examples compact but high-quality.

## Anti-Patterns to Avoid

| Anti-Pattern | Why It's Bad | Fix |
|-------------|-------------|-----|
| Banning section names the user wants | Confuses the LLM | Only ban truly unwanted phrases |
| Multiple template choices | LLM wastes tokens on selection logic | Use one primary structure |
| Raw log pastes in output | Wastes tokens, unreadable | Log EVIDENCE rule: describe meaning |
| Repeating facts across sections | Inflates output, looks shallow | ANTI-REPETITION rule |
| Single-sentence root cause | Misses intermediate causal steps | Mandate → arrow chains |
| Hedging scattered across bullets | Sounds uncertain everywhere | Hedge only at section level |

## How to Test Prompt Changes

1. **Unit tests** — `pytest tests/test_slack_investigation_service.py -v --tb=short`
   - Tests verify section names exist in prompt
   - Tests verify section extraction parses correctly
   - Tests verify reasoning directives are present

2. **Live test** — Use the Slack Investigation UI:
   - Pick a thread with known root cause
   - Run with GPT-4.1 or GPT-4o
   - Check: Are all 6 sections present? Is Key Observations ≠ Key Findings? Is the causal chain multi-step?

3. **Token budget** — After editing the prompt, check char count:
   ```python
   from services.ai.prompts import load_prompt
   p = load_prompt("issue_summary")
   print(f"Prompt: {len(p)} chars ≈ {len(p)//4} tokens")
   ```
   Keep under ~3000 tokens to leave room for thread content.

## Section Extraction Code

The backend parses LLM output using `_split_markdown_sections()` which matches:
- `## Heading` (hash headings)
- `**Bold Only Line**` (bold-only lines as headings)

Then `_find_section(sections, "name1", "name2", ...)` does fuzzy lookup.

When adding new section names, update BOTH:
1. The prompt (so the LLM produces them)
2. The `investigate()` extraction code (so the backend parses them)
3. The tests (so regressions are caught)

## Files to Touch

| File | What to Change |
|------|---------------|
| `explorer/backend/services/ai/prompts/issue_summary.md` | The system prompt itself |
| `explorer/backend/services/ai/slack_investigation_service.py` | Section extraction in `investigate()`, `max_tokens` in `_generate_summary()` |
| `explorer/backend/schemas/slack_investigation.py` | Response schema fields |
| `explorer/frontend/lib/types.ts` | TypeScript response type |
| `explorer/frontend/app/slack-investigation/page.tsx` | Section rendering |
| `explorer/backend/tests/test_slack_investigation_service.py` | All prompt/extraction tests |

## Docker Note

After editing backend files, the Docker container must be restarted for changes to take effect:
```bash
cd explorer && docker compose restart backend
```
The volume mount (`./backend/services:/app/services:ro`) makes files available, but Python caches modules in memory until restart.
```

**Step 2: Verify skill loads**

The skill is ready when `~/.copilot/skills/issue-summary-prompt/SKILL.md` exists with valid YAML frontmatter.

**Step 3: Commit**

```bash
git add ~/.copilot/skills/issue-summary-prompt/SKILL.md
git commit -m "feat(skill): create issue-summary-prompt skill for RCA prompt engineering"
```

---

## Final Verification Checklist

After all tasks are complete:

1. `pytest tests/ --tb=short` → ALL PASS, 0 failures
2. `curl -s http://localhost:8000/api/v1/ai/providers | python3 -m json.tool` → providers listed
3. Frontend build: `cd explorer/frontend && npx next build` → success
4. Docker restart: `docker compose restart backend frontend`
5. Live test: Submit a Slack thread URL through the UI and verify all 6 sections appear in the output
6. Verify skill: mention "improve summary quality" in Copilot → skill should trigger

---

**Implementation plan is ready for review.**

Please review [docs/design/issue-summary-rca-enhancement/plan.md](docs/design/issue-summary-rca-enhancement/plan.md) and either:
1. **Accept** — Reply "approved" or "lgtm" to proceed
2. **Edit** — Modify the file directly, then reply "updated" so I can re-evaluate

I will not proceed until you explicitly accept.
