# Strict Issue Summary LLM Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Enforce a strict, RCA-ready incident summary format (`ISSUE SUMMARY` → `Issue` → `Cause` → `Key Findings` → `Recovery Action` → `Solution`) with deep technical reasoning and model-adaptive behavior based on the selected LLM.

**Architecture:** Keep prompt-authoring in `issue_summary.md`, add model-capability adaptation in `SlackInvestigationService._generate_summary()`, and harden parsing in `investigate()` so API fields are deterministic and non-duplicative. Frontend renders each section from structured fields rather than re-parsing mixed markdown blobs.

**Tech Stack:** FastAPI (Python), Pydantic, OpenAI-compatible chat interface, Ollama/OpenAI/Gemini providers, Next.js/TypeScript frontend, pytest.

---

## Summary of Work

| # | Task | Type | Files |
|---|------|------|-------|
| 1 | Add failing tests for strict section contract + anti-duplication | SERIAL | `explorer/backend/tests/test_slack_investigation_service.py`, `explorer/backend/tests/test_prompt_loader.py` |
| 2 | Rewrite prompt to strict output format and depth constraints | SERIAL | `explorer/backend/services/ai/prompts/issue_summary.md` |
| 3 | Implement model-adaptive summarization strategy | SERIAL | `explorer/backend/services/ai/slack_investigation_service.py` |
| 4 | Refactor parser + response mapping for strict fields | SERIAL | `explorer/backend/services/ai/slack_investigation_service.py`, `explorer/backend/schemas/slack_investigation.py` |
| 5 | Update frontend rendering to avoid duplicate findings | SERIAL | `explorer/frontend/lib/types.ts`, `explorer/frontend/app/slack-investigation/page.tsx` |
| 6 | Add end-to-end regression tests for strict format across providers | PARALLEL | `explorer/backend/tests/test_slack_investigation_service.py` |

---

### Task 1: Add Failing Tests for Strict Output Contract

**Files:**
- Modify: `explorer/backend/tests/test_slack_investigation_service.py`
- Modify: `explorer/backend/tests/test_prompt_loader.py`

**Step 1: Add failing test for strict prompt section names**

```python
def test_issue_summary_prompt_contains_strict_sections() -> None:
    text = load_prompt("issue_summary")
    assert "**ISSUE SUMMARY**" in text
    assert "**Issue:**" in text
    assert "**Cause:**" in text
    assert "**Key Findings:**" in text
    assert "**Recovery Action:**" in text
    assert "**Solution:**" in text
```

**Step 2: Add failing test for anti-duplication mapping**

```python
def test_investigate_does_not_duplicate_findings_in_thread_summary(monkeypatch):
    # Fake LLM returns strict sections
    # assert key-findings bullets appear in key_findings list
    # assert same bullets are NOT repeated inside thread_summary
```

**Step 3: Add failing test for provider-adaptive max_tokens**

```python
def test_generate_summary_uses_model_adaptive_token_budget(monkeypatch):
    # gpt-4o should get higher max_tokens than small local ollama models
```

**Step 4: Run targeted tests (expect FAIL)**

Run: `cd explorer/backend && python -m pytest tests/test_prompt_loader.py tests/test_slack_investigation_service.py -v --tb=short`

**Step 5: Commit tests-only**

```bash
git add explorer/backend/tests/test_prompt_loader.py explorer/backend/tests/test_slack_investigation_service.py
git commit -m "test(slack-investigation): add strict section contract and anti-duplication tests"
```

---

### Task 2: Rewrite Prompt to Strict Format + Depth Rules

**Files:**
- Modify: `explorer/backend/services/ai/prompts/issue_summary.md`

**Step 1: Replace incident output format with exact required headings**

Required incident headings (exact):
- `**ISSUE SUMMARY**`
- `**Issue:**`
- `**Cause:**`
- `**Key Findings:**`
- `**Recovery Action:**`
- `**Solution:**`

**Step 2: Add explicit depth constraints**

Include explicit instructions to:
- Interpret logs instead of repeating raw log text
- Correlate timeline and state transitions
- Use ROS/distributed-system domain reasoning where evidence supports it
- Preserve traceability `evidence -> finding -> cause -> solution`
- Avoid hallucination when data is missing

**Step 3: Add strict log/attachment usage rules**

- Use `log_blocks` as primary evidence source
- Use extracted attachment text for supporting evidence
- Treat images as placeholders unless textual extraction exists

**Step 4: Keep general-mode fallback for non-incident threads**

Keep non-incident template intact under separate routing path.

**Step 5: Run prompt loader tests (expect PASS)**

Run: `cd explorer/backend && python -m pytest tests/test_prompt_loader.py -v --tb=short`

**Step 6: Commit**

```bash
git add explorer/backend/services/ai/prompts/issue_summary.md explorer/backend/tests/test_prompt_loader.py
git commit -m "feat(prompt): enforce strict ISSUE SUMMARY/Cause/Findings output contract"
```

---

### Task 3: Implement Model-Adaptive Summarization Strategy

**Files:**
- Modify: `explorer/backend/services/ai/slack_investigation_service.py`

**Step 1: Add model strategy helper**

Add helper:

```python
def _model_summary_strategy(model: str) -> dict:
    # return token_budget, reasoning_depth, evidence_density, image_limit
```

Recommended behavior:
- `openai:gpt-4o`, `openai:gpt-4.1`: high depth, larger `max_tokens` (e.g. 3500-4500)
- `gemini:*`: high depth, similar budget
- `ollama:*` small models: constrained depth + lower budget (e.g. 2200-3000)

**Step 2: Inject model-adaptive addendum into user prompt**

Append short runtime hint block to prompt:
- selected model
- expected detail depth
- max evidence bullets

**Step 3: Use adaptive `max_tokens` in `_ollama_chat` call**

Replace fixed value with strategy-derived `max_tok`.

**Step 4: Run targeted tests**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py::test_generate_summary_uses_model_adaptive_token_budget -v --tb=short`

**Step 5: Commit**

```bash
git add explorer/backend/services/ai/slack_investigation_service.py explorer/backend/tests/test_slack_investigation_service.py
git commit -m "feat(slack-investigation): add model-adaptive summarization strategy"
```

---

### Task 4: Refactor Parser + Response Mapping for Strict Fields

**Files:**
- Modify: `explorer/backend/services/ai/slack_investigation_service.py`
- Modify: `explorer/backend/schemas/slack_investigation.py`

**Step 1: Add strict section extraction aliases**

Map headings to internal variables:
- `issue_summary_text` <- `ISSUE SUMMARY`
- `issue_detail` <- `Issue`
- `cause_text` <- `Cause`
- `key_findings_text` <- `Key Findings`
- `recovery_text` <- `Recovery Action`
- `solution_text` <- `Solution`

Support legacy aliases during transition (`root cause`, `findings`, etc.).

**Step 2: Eliminate duplication in payload assembly**

- `thread_summary`: include only `ISSUE SUMMARY` + `Issue` + optional `Cause` overview
- `key_findings`: include bullet findings only
- `recommended_actions`: include only recovery/action bullets
- `solution`: keep long-form permanent fix content

**Step 3: Add structured `cause` field to schema**

In `SlackThreadInvestigationResponse`:

```python
cause: str = ""
```

Populate in `investigate()` response assembly.

**Step 4: Run parser tests**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py -v --tb=short`

**Step 5: Commit**

```bash
git add explorer/backend/services/ai/slack_investigation_service.py explorer/backend/schemas/slack_investigation.py explorer/backend/tests/test_slack_investigation_service.py
 git commit -m "feat(slack-investigation): add strict cause field and non-duplicative section mapping"
```

---

### Task 5: Update Frontend Rendering to Match Structured Payload

**Files:**
- Modify: `explorer/frontend/lib/types.ts`
- Modify: `explorer/frontend/app/slack-investigation/page.tsx`

**Step 1: Add type support for `cause`**

In `SlackThreadInvestigationResponse` TS type:

```ts
cause?: string;
```

**Step 2: Render distinct cards with no overlap**

- Thread Summary card: render only `thread_summary`
- Cause card: render `cause`
- Key Findings card: render `key_findings`
- Recovery Action card: render `recommended_actions`
- Solution card: render `solution`

**Step 3: Update copy payload to mirror exact section order**

Ensure copied text sequence is:
1. ISSUE SUMMARY
2. Issue
3. Cause
4. Key Findings
5. Recovery Action
6. Solution

**Step 4: Run frontend checks**

Run:
- `cd explorer/frontend && npx tsc --noEmit`
- `cd explorer/frontend && npm run lint`

**Step 5: Commit**

```bash
git add explorer/frontend/lib/types.ts explorer/frontend/app/slack-investigation/page.tsx
 git commit -m "feat(frontend): render strict issue/cause/findings/recovery/solution sections without duplication"
```

---

### Task 6: End-to-End Regression Tests Across Providers (PARALLEL)

**Files:**
- Modify: `explorer/backend/tests/test_slack_investigation_service.py`

**Step 1: Add provider-parameterized tests**

Add test matrix for representative models:
- `openai:gpt-4o`
- `openai:gpt-4.1`
- `gemini:gemini-2.0-flash`
- `ollama:qwen2.5:7b`

Verify:
- strict sections parsed
- cause populated
- no duplicate findings between `thread_summary` and `key_findings`
- adaptive token budget differs by provider class

**Step 2: Run full backend test suite**

Run: `cd explorer/backend && python -m pytest tests/ --tb=short`

**Step 3: Commit**

```bash
git add explorer/backend/tests/test_slack_investigation_service.py
 git commit -m "test(slack-investigation): add provider-matrix regression tests for strict RCA output"
```

---

## Verification Checklist

Run all of the following after implementation:

1. `cd explorer/backend && python -m pytest tests/ --tb=short`
2. `cd explorer/backend && ruff check .`
3. `cd explorer/frontend && npx tsc --noEmit`
4. `cd explorer/frontend && npm run lint`
5. `cd explorer && docker compose restart backend frontend`

Manual UI verification (required):
- Run a known incident thread through Slack Investigation page
- Confirm output sections are exactly: ISSUE SUMMARY, Issue, Cause, Key Findings, Recovery Action, Solution
- Confirm no duplicated findings between Thread Summary card and Key Findings card
- Confirm richer reasoning when selecting GPT-4o/GPT-4.1 vs smaller local models

---

## Dependencies

- **SERIAL:** Tasks 1 -> 2 -> 3 -> 4 -> 5
- **PARALLEL:** Task 6 can run after Task 4 is complete (independent of frontend work)

---

**Implementation plan is ready for review.**

Please review `docs/design/strict-issue-summary-llm/plan.md` and either:
1. **Accept** - Reply "approved" or "lgtm" to proceed
2. **Edit** - Modify the file directly, then reply "updated" so I can re-evaluate

I will not proceed until you explicitly accept.
