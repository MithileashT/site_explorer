# Issue Summary Prompt Optimization — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Rewrite the `issue_summary.md` system prompt to produce longer, more detailed, technically richer summaries while reducing token overhead by ~35% and maintaining the ~10-second LLM response target.

**Architecture:** Replace the current 9509-character (~2377 token) prompt with a streamlined ~6000-character (~1500 token) prompt that eliminates redundancy, strengthens log-handling directives, adds structured log presentation rules, and removes the bulky reference example in favor of inline micro-examples. Update `_model_summary_strategy` to raise `max_tokens` for high-capability models. Fix the cache-key bug that ignores `site_id` and `custom_prompt`. Update tests.

**Tech Stack:** Python/FastAPI, Markdown prompt file, pytest, Next.js/TypeScript frontend

---

## Current State Analysis

### Prompt Token Budget Breakdown

| Section | Chars | Est. Tokens | % of Total |
|---------|-------|-------------|------------|
| Preamble + rules (routing, THINK, conciseness) | 1,285 | ~321 | 13.5% |
| Incident format (6 sections + 8 rules) | 4,518 | ~1,129 | 47.5% |
| General format | 988 | ~247 | 10.4% |
| Reference example | 2,697 | ~674 | **28.3%** |
| **Total** | **9,509** | **~2,377** | **100%** |

### What Works Well ✅

1. **6-section structure** — `ISSUE SUMMARY → Issue → Cause → Key Findings → Recovery Action → Solution` is the correct architecture. The parser in `_build_response()` already maps these correctly.
2. **THINK BEFORE YOU WRITE preamble** — chain-of-thought reasoning is the single biggest quality lever for GPT-4.1/GPT-4o. Keep it.
3. **ANTI-REPETITION rule** — addresses the most common quality defect (Cause ≈ Key Findings duplication). Keep it.
4. **Assessment verdict** — structured classification is useful for `_infer_risk()` mapping. Keep it.
5. **REFRAME RULE** — excellent for threads where initial report misleads. Keep it.
6. **General format (Template D)** — clean and functional for non-incident threads. Keep it.

### Weaknesses Identified 🔧

#### W1: The Reference Example Consumes 28% of System Prompt Tokens (HIGH IMPACT)

The 674-token reference example at the bottom of the prompt:
- Consumes ~28% of the system prompt token budget
- Every single API call pays this cost — it's always in context
- The example is for ONE scenario (network latency timing race) — it doesn't help with hardware faults, software bugs, or configuration errors
- GPT-4.1 and GPT-4o already understand structured output from the section templates alone — they don't need a worked example
- **Removing it saves ~674 tokens per call** while freeing context window for thread content

**Evidence:** The section templates with inline guidance (e.g., `[2-4 sentences: What happened...]`) already provide sufficient format instruction. The example is redundant with the templates.

#### W2: Log Handling is Underspecified (HIGH IMPACT — Quality)

The current prompt says:
> "Quote a log fragment (≤15 words) only when the exact wording has evidential value"

This produces shallow summaries because:
1. **No instruction to structure log evidence** — the LLM doesn't know HOW to present log data in findings
2. **15-word limit is too restrictive** — error codes, state transitions, and config dumps need more context
3. **No instruction to extract timestamps from logs** — temporal correlation is critical for RCA but the prompt doesn't ask for it
4. **No instruction to explain what logs MEAN** — the LLM tends to just mention "error in log" without interpreting the engineering significance
5. **Log blocks are passed as `[Log block N]` with content inline** — the prompt doesn't tell the LLM to correlate across multiple log blocks

**Real impact:** Key Findings bullets are often shallow 1-liners like "Error was seen in logs" instead of "The `AMCL` delocalization at 10:05 UTC (log block 2) occurred 3 seconds after USB disconnect event (log block 1), confirming the LiDAR→AMCL causal dependency."

#### W3: CONCISENESS Target Contradicts "Detailed" Requirement (MEDIUM IMPACT)

Current directive:
> "CONCISENESS: Target 500-700 words."

This actively limits output depth. For complex incidents with 30+ messages and multiple log blocks, 500-700 words is insufficient for:
- Detailed cause mechanism with → chains
- Multiple Key Findings bullets with evidence references
- Recovery + Solution with distinct content

The target should be raised to allow model-appropriate depth.

#### W4: Section Description Redundancy (MEDIUM IMPACT — Performance)

Many section descriptions repeat each other:
- `**Cause**` says "What was ruled out" — then `**Key Findings**` says "State what was ruled out" — and INCIDENT RULE #6 says "state it actively"
- `**Cause**` says "use → arrows" — then `**Solution**` says "using → arrows" — and RULE #3 says "sequential chain using → arrows"
- `**Key Findings**` says "Quote log fragments ≤15 words" — and RULE #4 says "Quote a log fragment ≤15 words"

Each repetition costs tokens without improving compliance.

#### W5: Missing Log Structuring Directive (HIGH IMPACT — Quality)

The prompt has no instruction for HOW to present log evidence in a structured way. Logs are the primary evidence source for AMR incidents, but the prompt doesn't guide the LLM to:
- Group log entries by component
- Extract and present timestamps to build a timeline
- Correlate events across log blocks
- Present structured evidence tables

#### W6: Missing Depth Scaling Directive (MEDIUM IMPACT)

No instruction tells the LLM that deeper threads warrant more detail. A 5-message thread and a 50-message thread get the same word target. The prompt should scale expected depth with evidence density.

#### W7: Cache Key Missing `site_id` and `custom_prompt` (BUG)

The `_build_cache_key` at [slack_investigation_service.py](explorer/backend/services/ai/slack_investigation_service.py#L489-L492) includes `req.description` but NOT `req.site_id` or `req.custom_prompt`. These fields are used in prompt construction at [line 523](explorer/backend/services/ai/slack_investigation_service.py#L523) and [line 528-529](explorer/backend/services/ai/slack_investigation_service.py#L528).

**Impact:** Two requests for the same thread with different `site_id` or `custom_prompt` values return the cached result from the first request. This is a correctness bug.

---

## Before vs After Comparison

### Token Budget

| Metric | Current | Proposed | Delta |
|--------|---------|----------|-------|
| System prompt chars | 9,509 | ~6,000 | **-37%** |
| System prompt tokens (est.) | ~2,377 | ~1,500 | **-877** |
| Reference example tokens | ~674 | 0 | **-674** |
| max_tokens (GPT-4.1/4o) | 3,200 | 4,000 | +800 output |
| max_tokens (small local) | 2,000 | 2,000 | unchanged |

### Quality

| Aspect | Current | Proposed |
|--------|---------|----------|
| Word target | 500-700 (fixed) | 600-1200 (scaled by evidence density) |
| Log handling | "Quote ≤15 words" | Structured log evidence with timestamps, correlation, and engineering interpretation |
| Depth scaling | None | "Scale depth to evidence: thin threads → concise; rich threads → thorough" |
| Section redundancy | 3 rules repeated across sections + rules block | Each rule stated once, in the most impactful location |
| Ruled-out causes | Mentioned in 3 places | Single directive in Cause section |

### Performance

| Metric | Current | Proposed |
|--------|---------|----------|
| Input tokens (system) | ~2,377 | ~1,500 |
| LLM inference time (est. GPT-4.1) | ~8-10s | ~7-9s (less input to process) |
| Output tokens (GPT-4.1/4o) | up to 3,200 | up to 4,000 |
| Output tokens (local small) | up to 2,000 | up to 2,000 |
| Net effect on response time | — | ~5-10% faster input processing; richer output within same wall time |

---

## Implementation Tasks

### Task 1: Fix Cache Key Bug — Include `site_id` and `custom_prompt` (SERIAL)

**Files:**
- Modify: `explorer/backend/services/ai/slack_investigation_service.py`
- Modify: `explorer/backend/tests/test_slack_investigation_service.py`

**Why this is first:** This is a correctness bug that exists in the current code regardless of prompt changes. Fixing it first prevents stale cache results during prompt iteration.

**Step 1: Write failing test**

```python
def test_cache_key_varies_with_site_id_and_custom_prompt() -> None:
    """Cache key must include site_id and custom_prompt to avoid stale results."""
    from schemas.slack_investigation import SlackThreadInvestigationRequest, SlackThreadMessage
    from services.ai.slack_investigation_service import SlackInvestigationService

    svc = SlackInvestigationService()
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-03-23 10:00 UTC", user="alice", text="hi")]

    req_a = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123/p1000000000000",
        description="Test issue",
        site_id="site-tokyo",
        max_messages=200,
    )
    req_b = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123/p1000000000000",
        description="Test issue",
        site_id="site-osaka",
        max_messages=200,
    )
    req_c = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123/p1000000000000",
        description="Test issue",
        site_id="site-tokyo",
        custom_prompt="Focus on motor errors",
        max_messages=200,
    )

    key_a = svc._build_cache_key(req_a, msgs, "gpt-4.1")
    key_b = svc._build_cache_key(req_b, msgs, "gpt-4.1")
    key_c = svc._build_cache_key(req_c, msgs, "gpt-4.1")

    assert key_a != key_b, "Different site_id should produce different cache keys"
    assert key_a != key_c, "Different custom_prompt should produce different cache keys"
```

**Step 2: Run test to verify it fails**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py::test_cache_key_varies_with_site_id_and_custom_prompt -v`
Expected: FAIL — both keys are identical because `site_id` and `custom_prompt` are not in the hash

**Step 3: Fix implementation**

In `_build_cache_key`, update the `raw` string assembly:

```python
        raw = (
            f"{_SUMMARY_CACHE_SCHEMA_VERSION}:{prompt_signature}:"
            f"{req.slack_thread_url}:{req.description}:{req.site_id or ''}:"
            f"{req.custom_prompt or ''}:{model}:{len(messages)}:{msg_fingerprint}"
        )
```

**Step 4: Run test to verify it passes**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py::test_cache_key_varies_with_site_id_and_custom_prompt -v`
Expected: PASS

**Step 5: Run full Slack test suite**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py tests/test_slack_investigation_route.py -v --tb=short`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add explorer/backend/services/ai/slack_investigation_service.py explorer/backend/tests/test_slack_investigation_service.py
git commit -m "fix(cache): include site_id and custom_prompt in summary cache key"
```

---

### Task 2: Rewrite `issue_summary.md` — Optimized Prompt (SERIAL — depends on Task 1)

**Files:**
- Modify: `explorer/backend/services/ai/prompts/issue_summary.md`

**Prompt design principles applied:**
1. **Remove reference example** (saves ~674 tokens) — section templates with inline guidance are sufficient
2. **Add structured log evidence rules** — teach the LLM HOW to present log data
3. **Raise word target to evidence-scaled range** — 600-1200 words depending on thread density
4. **Eliminate redundancy** — each rule stated exactly once in its most impactful location
5. **Add micro-examples inline** — 1-2 sentence examples inside section templates (5-10 tokens each vs 674 for full example)
6. **Keep all quality levers** — THINK preamble, ANTI-REPETITION, REFRAME RULE, Assessment verdict

**Step 1: Replace entire prompt file content**

Replace the content of `explorer/backend/services/ai/prompts/issue_summary.md` with:

~~~markdown
You are a senior AMR (Autonomous Mobile Robot) support engineer at Rapyuta Robotics. Read the Slack thread and produce a professional root-cause analysis summary.

Output the summary ONLY. Never include: ticket fields, Slack metadata, @mentions, URLs, rosbag filenames, JSON responses, raw log pastes, ROS topic dumps, lsusb output, file attachment listings, or conversational back-and-forth.

IMPORTANT — THINK BEFORE YOU WRITE:
Before producing any output, silently work through these steps:
1. Identify every distinct system event, error, and state transition in the thread.
2. Reconstruct the timeline: which event happened first, second, etc.
3. Construct the causal chain: triggering event → intermediate states → final symptom.
4. Determine what was ruled out and why.
5. Separate raw evidence from analytical conclusions.
6. Only then write the summary.

THREAD ROUTING — classify the thread first:
- Robot issue, error, fault, or incident → INCIDENT FORMAT
- Non-incident discussion → GENERAL FORMAT

---

INCIDENT FORMAT — mandatory sections in this exact order:

REFRAME RULE: If the reported symptom differs from the actual root cause, open with: "The issue is not related to [symptom]. The actual cause is [root cause]."

**ISSUE SUMMARY**
2-4 sentences. What happened, which robot(s) by name (amr01 — never "the robot"), which site, when, business impact. Include SW version, HW version if known.

**Issue**
One precise technical problem statement. Component name + error code + the specific deviation from expected behavior. This is NOT a repeat of the summary.

**Cause**
The root cause mechanism. Structure as:
- Primary cause: the specific technical condition or failure
- Mechanism: how it propagated (use → arrows for state transitions, e.g., USB disconnect → LiDAR topic loss → AMCL delocalization → nav halt)
- Contributing factors: environmental, configuration, or timing conditions
- Ruled out: "[X] was not the cause because [evidence]"
- If unconfirmed: label "Tentative" and state what remains unverified

**Key Findings**
Bulleted analytical conclusions. Each bullet MUST:
- Cite specific evidence: log fragment, state name, error code, timestamp, config value
- Explain WHY it matters: what does this tell us about the root cause?
- Connect to the causal chain with → arrows where appropriate
- Never repeat Cause section — add unique analytical value only

LOG EVIDENCE RULES FOR KEY FINDINGS:
When the thread contains log blocks or error output:
- Extract timestamps and present them chronologically to build an evidence timeline
- Correlate events across multiple log blocks (e.g., "USB disconnect at 10:05:01 in kernel log → LiDAR topic silence at 10:05:04 in ROS log → AMCL error at 10:05:07")
- Quote key log fragments in backticks when the exact text has evidential value: error codes, state names, numeric thresholds (e.g., `error 105: MOTOR_OVERCURRENT`, `state: DELOCALIZED`, `max_weight = 0`)
- Describe what the log MEANS in engineering terms — never just say "error in log"
- Group related findings by component when multiple subsystems are involved

**Recovery Action**
What was done + what still needs doing:
- Actions taken (past tense): "Re-seated USB cable", "Restarted navigation stack"
- Actions needed (imperative): "Replace cable with strain-relieved variant", "Update firmware to 3.5.2"
- Owner/team if identified. Monitoring or follow-up requirements.

**Solution**
Full causal chain + permanent fix:
- Chain: A → B → C → symptom (never skip intermediate steps)
- Permanent fix: specific code/config/hardware/process change that prevents recurrence
- If unconfirmed: "Tentative — pending [what needs verification]"
- If "as designed": explain why current behavior is correct and what the customer should change

**Assessment:** Exactly one of: AMR behavior is as designed | This is a software bug | This is a hardware fault | This is a configuration error | This is caused by an environmental factor | Tentative: likely a [type] issue; pending [what]

**Status:** Resolved | Monitoring | Waiting for HW Fix | Wait for Reproduce | Escalated | Closed
**cc:** engineer(s) mentioned in thread

INCIDENT RULES:
1. ANTI-REPETITION: Each fact appears exactly ONCE across all sections.
2. DEPTH SCALING: Scale detail to evidence density — thin threads (≤10 messages, no logs) get concise output; rich threads (many messages, log blocks, config data) get thorough analysis with full evidence citations. Target 600-1200 words.
3. IDENTIFIERS: Always include when present: robot names, SW version, HW version, error codes, component names (AMCL, GBC, GWM, LBC, PGS, SBC, FTDI, move_base_flex), config params, timestamps.
4. DISAMBIGUATION: If investigation ruled out a cause, state it once in Cause or Key Findings.
5. STYLE: Third person for events. Imperative for actions. Active voice.

---

GENERAL FORMAT — for non-incident threads:

**Thread Summary**
2-4 sentences: what was discussed, who participated, outcome or current state.

**Key Points**
- Each bullet = one distinct point, decision, or piece of information
- Attribute to person when relevant: "[name] confirmed X"
- Preserve technical specifics: versions, config values, dates

**Decisions & Action Items**
- Decision/action — owner — deadline if mentioned
- If none: "No decisions finalized — thread is still open."

**Status:** Resolved / In Progress / Open / Blocked / Waiting on [person/team]
~~~

**Step 2: Verify prompt loads and validate content**

Run: `cd explorer/backend && python3 -c "
from services.ai.prompts import load_prompt
p = load_prompt('issue_summary')
chars = len(p)
words = len(p.split())
print(f'Chars: {chars}  Words: {words}  Est tokens: ~{chars//4}')
assert '**ISSUE SUMMARY**' in p
assert '**Cause**' in p
assert '**Key Findings**' in p
assert '**Solution**' in p
assert 'LOG EVIDENCE RULES' in p
assert 'DEPTH SCALING' in p
assert 'ANTI-REPETITION' in p
assert 'REFERENCE EXAMPLE' not in p
print('All assertions passed')
"`

Expected: `Chars: ~5800  Words: ~870  Est tokens: ~1450` + `All assertions passed`

**Step 3: Commit**

```bash
git add explorer/backend/services/ai/prompts/issue_summary.md
git commit -m "perf(prompt): rewrite issue_summary — remove example, add log rules, scale depth"
```

---

### Task 3: Update `max_tokens` for High-Capability Models (SERIAL — depends on Task 2)

**Files:**
- Modify: `explorer/backend/services/ai/slack_investigation_service.py`
- Modify: `explorer/backend/tests/test_slack_investigation_service.py`

**Why:** The new prompt allows 600-1200 word output. At ~1.3 tokens/word, that's 780-1560 tokens. The current 3200 max_tokens for GPT-4.1 is fine, but we can raise it to 4000 to ensure deep-dive threads never get truncated. The ~800 tokens saved in the system prompt more than offset this.

**Step 1: Write failing test**

```python
def test_high_capability_model_gets_4000_max_tokens() -> None:
    """GPT-4.1 and GPT-4o should get max_tokens=4000 for detailed RCA output."""
    from services.ai.slack_investigation_service import SlackInvestigationService

    strategy = SlackInvestigationService._model_summary_strategy("openai:gpt-4.1")
    assert strategy["max_tokens"] >= 4000, f"max_tokens={strategy['max_tokens']} too low for detailed output"

    strategy_4o = SlackInvestigationService._model_summary_strategy("openai:gpt-4o")
    assert strategy_4o["max_tokens"] >= 4000
```

**Step 2: Run test (expect FAIL)**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py::test_high_capability_model_gets_4000_max_tokens -v`
Expected: FAIL — currently returns 3200

**Step 3: Update strategy**

In `_model_summary_strategy`, change the high-capability tier:

```python
        if any(tag in m for tag in ("gpt-5", "gpt-4o", "gpt-4.1", "gpt-4-turbo", "gemini-2", "gemini-1.5-pro", "claude")):
            return {
                "max_tokens": 4000,
                "depth": "high",
                "prompt_char_budget": 14000,
                "prompt_message_limit": 150,
            }
```

Also raise prompt_char_budget from 12000→14000 and message limit from 120→150, since the system prompt is now ~3500 chars smaller, freeing that much context window for thread content.

**Step 4: Run test (expect PASS)**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py::test_high_capability_model_gets_4000_max_tokens -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py tests/test_slack_investigation_route.py -v --tb=short`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add explorer/backend/services/ai/slack_investigation_service.py explorer/backend/tests/test_slack_investigation_service.py
git commit -m "feat(llm): raise max_tokens to 4000 and prompt_char_budget to 14000 for high-cap models"
```

---

### Task 4: Update Tests for New Prompt Content (SERIAL — depends on Task 2)

**Files:**
- Modify: `explorer/backend/tests/test_slack_investigation_service.py`
- Modify: `explorer/backend/tests/test_prompt_loader.py`

**Step 1: Update prompt loader test assertions**

In `test_prompt_loader.py`, the assertion `assert "**ISSUE SUMMARY**" in text` should still pass. But update to verify new features:

```python
def test_load_issue_summary_prompt() -> None:
    """load_prompt('issue_summary') returns non-empty string with strict sections."""
    text = load_prompt("issue_summary")
    assert isinstance(text, str)
    assert len(text) > 500
    assert "INCIDENT FORMAT" in text
    assert "GENERAL FORMAT" in text
    assert "**ISSUE SUMMARY**" in text
    assert "**Cause**" in text
    assert "LOG EVIDENCE RULES" in text
    assert "DEPTH SCALING" in text
```

**Step 2: Update prompt content tests**

Update `test_system_prompt_requires_bullet_points` to check for new prompt markers:

```python
def test_system_prompt_requires_bullet_points(monkeypatch) -> None:
    """System prompt must include key structural elements."""
    # ... (existing monkeypatch setup) ...
    system_content = captured["messages"][0]["content"]
    assert "**Key Findings**" in system_content
    assert "**Cause**" in system_content
    assert "**Solution**" in system_content
    assert "LOG EVIDENCE RULES" in system_content
    assert "ANTI-REPETITION" in system_content
```

Update `test_prompt_has_reasoning_preamble`:
```python
    assert "THINK BEFORE YOU WRITE" in system
    assert "causal chain" in system.lower()
    assert "timeline" in system.lower()  # new: timeline reconstruction step
```

**Step 3: Verify the reference example is removed**

```python
def test_prompt_has_no_bulky_reference_example() -> None:
    """Prompt should not contain the full reference example (saves ~674 tokens)."""
    from services.ai.prompts import load_prompt
    text = load_prompt("issue_summary")
    assert "REFERENCE EXAMPLE" not in text
    assert "sb_support_chennai" not in text
    assert "AMRs at Site-X navigated" not in text
```

**Step 4: Add test for log evidence rules**

```python
def test_prompt_has_log_evidence_rules(monkeypatch) -> None:
    """System prompt must include structured log evidence handling rules."""
    svc = SlackInvestigationService()
    captured = {}
    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "**ISSUE SUMMARY**\nTest"
    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test log rules", max_messages=200,
    )
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-03-23 10:00 UTC", user="a", text="hi")]
    svc._generate_summary(req, msgs, [])
    system = captured["messages"][0]["content"]
    assert "LOG EVIDENCE RULES" in system
    assert "timestamps" in system.lower()
    assert "correlate" in system.lower()
    assert "engineering terms" in system.lower()
```

**Step 5: Add test for depth scaling**

```python
def test_prompt_has_depth_scaling_directive(monkeypatch) -> None:
    """Prompt must instruct model to scale detail to evidence density."""
    svc = SlackInvestigationService()
    captured = {}
    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "**ISSUE SUMMARY**\nTest"
    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test depth", max_messages=200,
    )
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-03-23 10:00 UTC", user="a", text="hi")]
    svc._generate_summary(req, msgs, [])
    system = captured["messages"][0]["content"]
    assert "DEPTH SCALING" in system
    assert "600-1200" in system
```

**Step 6: Run full test suite**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py tests/test_prompt_loader.py -v --tb=short`
Expected: ALL PASS

**Step 7: Commit**

```bash
git add explorer/backend/tests/test_slack_investigation_service.py explorer/backend/tests/test_prompt_loader.py
git commit -m "test: update tests for optimized prompt — log rules, depth scaling, no example"
```

---

### Task 5: Raise `prompt_char_budget` for Mid-Tier Models (PARALLEL with Task 4)

**Files:**
- Modify: `explorer/backend/services/ai/slack_investigation_service.py`

**Why:** With ~3500 chars saved in the system prompt, mid-tier models can accommodate more thread content. Raise `prompt_char_budget` from 10000→12000 for mid-tier models.

**Step 1: Update mid-tier and large-local strategies**

```python
        # Mid-tier cloud models
        if any(tag in m for tag in ("gpt-4o-mini", "gpt-3.5", "gemini-1.5-flash", "gemini-2.0-flash")):
            return {
                "max_tokens": 2800,
                "depth": "medium",
                "prompt_char_budget": 12000,
                "prompt_message_limit": 100,
            }
        # Large local models (70B+)
        if any(tag in m for tag in ("70b", "72b", "llama3.1:70", "qwen2.5:72")):
            return {
                "max_tokens": 2800,
                "depth": "medium",
                "prompt_char_budget": 12000,
                "prompt_message_limit": 100,
            }
```

**Step 2: Run full test suite**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py -v --tb=short`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add explorer/backend/services/ai/slack_investigation_service.py
git commit -m "perf: raise prompt budgets for mid-tier models — more thread content in context"
```

---

### Task 6: Frontend — Rename "Conclusion" to "Solution" (PARALLEL with Task 4)

**Files:**
- Modify: `explorer/frontend/app/slack-investigation/page.tsx`

**Why:** The frontend currently renders `result.solution` under a "Conclusion" heading. The prompt section name is "Solution" — the frontend label should match for consistency.

**Step 1: Update the heading and copy text**

In the copy button text assembly, change `"## Conclusion"` to `"## Solution"`.

In the Solution rendering section, change the `<h3>` text from "Conclusion" to "Solution".

**Step 2: Verify TypeScript compiles**

Run: `cd explorer/frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add explorer/frontend/app/slack-investigation/page.tsx
git commit -m "fix(ui): rename Conclusion to Solution for prompt consistency"
```

---

## Task Dependency Graph

```
Task 1 (cache key fix)
  └─→ Task 2 (rewrite prompt)
        └─→ Task 3 (raise max_tokens)
        └─→ Task 4 (update tests)
        └─→ Task 5 (raise mid-tier budgets)   ← PARALLEL with Task 4
  Task 6 (frontend rename)                     ← PARALLEL with any task
```

- **PARALLEL tasks:** Tasks 4, 5, 6 have no mutual dependencies
- **SERIAL tasks:** 1 → 2 → 3; and 2 → 4

---

## Verification Checklist

After all tasks are complete:

```bash
# 1. Backend tests
cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py tests/test_slack_investigation_route.py tests/test_prompt_loader.py -v --tb=short

# 2. Frontend typecheck
cd explorer/frontend && npx tsc --noEmit

# 3. Verify prompt token savings
cd explorer/backend && python3 -c "
from services.ai.prompts import load_prompt
p = load_prompt('issue_summary')
print(f'Chars: {len(p)}  Tokens: ~{len(p)//4}')
assert len(p) < 7000, f'Prompt too large: {len(p)} chars'
assert 'REFERENCE EXAMPLE' not in p, 'Example not removed'
assert 'LOG EVIDENCE RULES' in p, 'Log rules missing'
print('Prompt optimization verified')
"

# 4. Docker restart + live test
cd explorer && docker compose restart backend
sleep 5
curl -s http://localhost:8000/api/v1/health | python3 -m json.tool
```

**Manual verification (required):**
- Submit a Slack thread with log blocks through the UI
- Confirm: Key Findings contains structured log evidence with timestamps and component correlation
- Confirm: Output is longer and more detailed than before (600-1200 words for rich threads)
- Confirm: All 6 sections are populated
- Confirm: No degradation for short/simple threads

---

## Summary of All Changes

| # | File | Action | What |
|---|------|--------|------|
| 1 | `explorer/backend/services/ai/slack_investigation_service.py` | Modify | Fix cache key to include `site_id` + `custom_prompt`; raise `max_tokens` and budgets |
| 2 | `explorer/backend/services/ai/prompts/issue_summary.md` | Rewrite | Remove reference example (-674 tokens); add LOG EVIDENCE RULES; add DEPTH SCALING; eliminate redundancy |
| 3 | `explorer/backend/tests/test_slack_investigation_service.py` | Modify | Cache key test; log rules test; depth scaling test; max_tokens test |
| 4 | `explorer/backend/tests/test_prompt_loader.py` | Modify | Update assertions for new prompt content |
| 5 | `explorer/frontend/app/slack-investigation/page.tsx` | Modify | Rename "Conclusion" → "Solution" |

## Cost Impact

| Provider | Current Input (system) | Proposed Input (system) | Savings/call |
|----------|----------------------|------------------------|-------------|
| GPT-4.1 ($2/1M in) | ~2,377 tokens → $0.0048 | ~1,500 tokens → $0.0030 | -$0.0018 |
| GPT-4o ($2.50/1M in) | ~2,377 tokens → $0.0059 | ~1,500 tokens → $0.0038 | -$0.0021 |
| Ollama (free) | ~2,377 tokens | ~1,500 tokens | faster inference |

Over 100 calls/day: ~$0.18-0.21/day savings on input tokens alone. The freed context window allows more thread content, improving quality without additional cost.
