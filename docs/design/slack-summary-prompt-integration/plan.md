# Slack Summary Prompt Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Replace the hardcoded 488-token generic system prompt in `SlackInvestigationService` with the domain-specific `issue_summary.md` prompt, update the section parser and response schema to handle all 4 template outputs, and pass images to vision-capable LLMs.

**Architecture:** Load the markdown prompt file at module import time via a `load_prompt()` helper. Update `_split_markdown_sections()` to parse bold-heading output (`**Section Name**`). Add `assessment` field to the response schema. For images, convert existing `b64_image` data into OpenAI-compatible `image_url` content blocks so vision models (GPT-4o, Gemini) can analyze screenshots from Slack threads.

**Tech Stack:** Python/FastAPI, Pydantic, OpenAI-compatible chat API, markdown parsing, pytest

---

## Current State Analysis

### What works today
- `issue_summary.md` (system prompt) is complete with 4 templates: A (Simple), B (Standard), C (Deep-Dive), D (Non-Incident)
- `_split_markdown_sections()` already handles both `## Heading` and `**Bold Heading**` formats
- `_find_section()` does fuzzy substring matching on section keys
- Images are downloaded from Slack and stored as `b64_image` in `SlackThreadAttachment`
- `LLMService.chat()` accepts `messages: List[Dict[str, Any]]` (supports multimodal content blocks)

### What's broken / missing
1. **Hardcoded system prompt** (L568-592) uses old section names ("Issue Overview", "Key Observations", "Actions Taken / Suggested Fixes", "Current Status / Risks") — these are now BANNED in the new prompt
2. **Section extraction** (L704-710) looks for old section names — won't find "Issue Summary", "Findings", "Root Cause", "Recovery Action", "Assessment", "Thread Summary", "Key Points", "Decisions & Action Items"
3. **No `assessment` field** on the response — the new prompt outputs `**Assessment:** [verdict]` but the backend doesn't extract it
4. **Images not sent to LLM** — `b64_image` is stored but the user message to the LLM is plain text. Vision-capable models (GPT-4o, Gemini 2.0 Flash) can analyze images if sent as `image_url` content blocks
5. **`_infer_risk()` is generic** — could derive risk from the Assessment verdict instead of keyword scanning
6. **No `__init__.py`** in `prompts/` directory — no loader utility

### Image pipeline: what's possible

| Image source | Available as b64? | Can LLM see it? | After this plan |
|---|---|---|---|
| Uploaded file (📎 attachment) | ✅ Yes | ❌ No (text-only prompt) | ✅ Yes (vision content block) |
| Inline clipboard paste | ❌ Not fetched | ❌ No | ❌ No (Slack API limitation) |
| External URL in message | ❌ Not downloaded | ❌ No | ❌ No (out of scope) |

Vision support is provider-dependent:
- **GPT-4o, GPT-4.1** → full vision support via `image_url` content blocks
- **Gemini 2.0 Flash, 1.5 Pro** → full vision via same format (OpenAI-compatible)
- **Ollama (qwen2.5-coder)** → text-only, images silently ignored (no crash)

---

## Task 1: Prompt Loader Utility (SERIAL)

**Files:**
- Create: `explorer/backend/services/ai/prompts/__init__.py`
- Test: `explorer/backend/tests/test_prompt_loader.py`

**Step 1: Write the failing test**

```python
# explorer/backend/tests/test_prompt_loader.py
"""Tests for prompt file loader."""

from services.ai.prompts import load_prompt


def test_load_issue_summary_prompt() -> None:
    """load_prompt('issue_summary') returns non-empty string from the md file."""
    text = load_prompt("issue_summary")
    assert isinstance(text, str)
    assert len(text) > 500
    assert "TEMPLATE A" in text
    assert "TEMPLATE D" in text


def test_load_prompt_caches() -> None:
    """Subsequent calls return the same object (cached)."""
    a = load_prompt("issue_summary")
    b = load_prompt("issue_summary")
    assert a is b


def test_load_prompt_missing_raises() -> None:
    """Requesting a non-existent prompt raises FileNotFoundError."""
    import pytest
    with pytest.raises(FileNotFoundError):
        load_prompt("nonexistent_prompt_xyz")
```

**Step 2: Run test to verify it fails**

Run: `cd explorer/backend && python -m pytest tests/test_prompt_loader.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_prompt'`

**Step 3: Write implementation**

```python
# explorer/backend/services/ai/prompts/__init__.py
"""Prompt file loader — reads .md prompt files from this directory."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    """Load a prompt file by name (without extension).

    Raises FileNotFoundError if the file does not exist.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()
```

**Step 4: Run test to verify it passes**

Run: `cd explorer/backend && python -m pytest tests/test_prompt_loader.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add services/ai/prompts/__init__.py tests/test_prompt_loader.py
git commit -m "feat(prompts): add prompt file loader with caching"
```

---

## Task 2: Replace Hardcoded System Prompt (SERIAL — depends on Task 1)

**Files:**
- Modify: `explorer/backend/services/ai/slack_investigation_service.py:568-592` (the `system = (...)` block)
- Test: existing tests must still pass

**Step 1: Write the failing test**

```python
# Add to explorer/backend/tests/test_slack_investigation_service.py

def test_generate_summary_uses_loaded_prompt(monkeypatch) -> None:
    """_generate_summary should use the prompt from issue_summary.md, not hardcoded text."""
    from services.ai.slack_investigation_service import SlackInvestigationService
    from schemas.slack_investigation import SlackThreadInvestigationRequest

    captured_messages = []

    class FakeLLM:
        active_provider = {"type": "openai", "model": "gpt-4o"}
        model = "gpt-4o"
        last_usage = {}

        def chat(self, messages, **kwargs):
            captured_messages.extend(messages)
            return "**Issue Summary**\nTest.\n\n**Assessment:** AMR behavior is as designed.\n\n**Status:** Resolved\n**cc:** @test"

    svc = SlackInvestigationService(_llm_service=FakeLLM())
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123/p1234567890",
        description="Test issue",
    )
    from schemas.slack_investigation import SlackThreadMessage
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-01-01 00:00 UTC", user="alice", text="Robot stopped")]

    summary, model = svc._generate_summary(req, msgs, [])
    system_content = captured_messages[0]["content"]
    # Must contain new prompt markers, not old ones
    assert "TEMPLATE A" in system_content
    assert "THREAD ROUTING" in system_content
    # Must NOT contain old hardcoded markers
    assert "## Issue Overview" not in system_content
    assert "## Key Observations" not in system_content
```

**Step 2: Run to verify it fails**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py::test_generate_summary_uses_loaded_prompt -v`
Expected: FAIL — `"## Issue Overview"` IS in the system content (old prompt still hardcoded)

**Step 3: Replace the hardcoded prompt**

In `explorer/backend/services/ai/slack_investigation_service.py`, replace lines 568-592:

```python
# OLD (delete this entire block):
        system = (
            "You are a senior SRE producing a structured incident summary for a warehouse robotics team.\n"
            ...entire hardcoded string...
        )

# NEW (replace with):
        from services.ai.prompts import load_prompt
        system = load_prompt("issue_summary")
```

Move the import to the top of the file (with the other imports) for cleanliness:
```python
from services.ai.prompts import load_prompt
```

And at line ~568:
```python
        system = load_prompt("issue_summary")
```

**Step 4: Run all tests**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add services/ai/slack_investigation_service.py tests/test_slack_investigation_service.py
git commit -m "feat(slack): replace hardcoded system prompt with issue_summary.md"
```

---

## Task 3: Update Section Extraction for New Template Names (SERIAL — depends on Task 2)

**Files:**
- Modify: `explorer/backend/services/ai/slack_investigation_service.py:704-740` (the `_find_section` calls and summary assembly)
- Test: `explorer/backend/tests/test_slack_investigation_service.py`

**Step 1: Write failing tests for all 4 template outputs**

```python
# Add to explorer/backend/tests/test_slack_investigation_service.py

def test_section_extraction_template_a_simple() -> None:
    """Parser should extract sections from Template A (Simple) output."""
    md = (
        "**Issue Summary**\n"
        "AMR01 triggered BARCODE_TOPIC_CRITICAL due to USB disconnect.\n\n"
        "**Recovery Action**\n"
        "- Re-seat the USB connector.\n\n"
        "**Assessment:** Hardware fault — USB connector instability.\n\n"
        "**Status:** Monitoring\n"
        "**cc:** @keiko"
    )
    sections = _split_markdown_sections(md)
    assert "issue summary" in sections
    assert "recovery action" in sections
    # Assessment is an inline field, not a full section — handled separately


def test_section_extraction_template_b_standard() -> None:
    """Parser should extract sections from Template B (Standard) output."""
    md = (
        "**Issue Summary**\n"
        "Task assignment timing issue caused by network latency.\n\n"
        "**Findings**\n"
        "- Robots transitioned to AVAILABLE after unload.\n\n"
        "**Root Cause**\n"
        "Network latency → AVAILABLE → idle nav → task arrived mid-transit.\n\n"
        "**Recovery Action**\n"
        "- Monitor edge-server network.\n\n"
        "**Assessment:** AMR behavior is as designed.\n\n"
        "**Status:** Monitoring\n"
        "**cc:** @support"
    )
    sections = _split_markdown_sections(md)
    assert "issue summary" in sections
    assert "findings" in sections
    assert "root cause" in sections
    assert "recovery action" in sections


def test_section_extraction_template_d_general() -> None:
    """Parser should extract sections from Template D (Non-Incident) output."""
    md = (
        "**Thread Summary**\n"
        "Team discussed deployment timeline for v3.7.0.\n\n"
        "**Key Points**\n"
        "- Alice confirmed staging deploy on Monday.\n"
        "- Bob raised concern about DB migration.\n\n"
        "**Decisions & Action Items**\n"
        "- Deploy staging Monday — owner: Alice.\n"
        "- Bob to test migration script by Friday.\n\n"
        "**Status:** In Progress"
    )
    sections = _split_markdown_sections(md)
    assert "thread summary" in sections
    assert "key points" in sections
    assert "decisions & action items" in sections


def test_find_section_new_template_names() -> None:
    """_find_section should match new section names from all templates."""
    sections = {
        "issue summary": "Robot stopped",
        "findings": "Log analysis confirmed X",
        "root cause": "A → B → C",
        "recovery action": "Re-seat USB",
        "thread summary": "Team discussed deployment",
        "key points": "Alice confirmed staging",
        "decisions & action items": "Deploy Monday",
    }
    assert _find_section(sections, "issue summary", "issue") == "Robot stopped"
    assert _find_section(sections, "findings") == "Log analysis confirmed X"
    assert _find_section(sections, "root cause", "tentative root cause") == "A → B → C"
    assert _find_section(sections, "thread summary") == "Team discussed deployment"
    assert _find_section(sections, "key points") == "Alice confirmed staging"
    assert _find_section(sections, "decisions & action items", "decisions", "action items") == "Deploy Monday"
```

**Step 2: Run to verify they pass (parser already handles `**Bold**`)**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py -k "template_a or template_b or template_d or new_template" -v`
Expected: PASS (parser already handles bold headings)

**Step 3: Update section extraction in `investigate()` method**

Replace the section extraction block (~L704-740) to handle all template outputs:

```python
        sections = _split_markdown_sections(summary)

        # ── Extract Assessment (inline field, not a full section) ──
        assessment = ""
        assess_match = re.search(r"\*\*Assessment:\*\*\s*(.+?)(?:\n|$)", summary)
        if assess_match:
            assessment = assess_match.group(1).strip()

        # ── Incident templates (A/B/C) ──
        issue = _find_section(sections, "issue summary", "issue", "the issue", "problem", "incident")
        findings = _find_section(sections, "findings", "key observations", "observations", "important logs & errors", "important logs")
        root_cause = _find_section(sections, "root cause", "tentative root cause", "root cause analysis", "cause")
        recovery = _find_section(sections, "recovery action", "actions taken", "recommended actions", "actions taken / suggested fixes", "suggested fixes")
        conclusion = _find_section(sections, "conclusion")
        status_section = _find_section(sections, "status")

        # ── General template (D) ──
        thread_summary_section = _find_section(sections, "thread summary")
        key_points = _find_section(sections, "key points")
        decisions = _find_section(sections, "decisions & action items", "decisions", "action items")

        # ── Build thread_summary for the response ──
        summary_parts: List[str] = []

        if thread_summary_section:
            # Template D output
            summary_parts.append(f"**Thread Summary**\n{thread_summary_section}")
            if key_points:
                summary_parts.append(f"**Key Points**\n{key_points}")
            if decisions:
                summary_parts.append(f"**Decisions & Action Items**\n{decisions}")
        else:
            # Incident template output (A/B/C)
            if issue:
                summary_parts.append(f"**Issue Summary**\n{issue}")
            if findings:
                summary_parts.append(f"**Findings**\n{findings}")
            if root_cause:
                summary_parts.append(f"**Root Cause**\n{root_cause}")
            if recovery:
                summary_parts.append(f"**Recovery Action**\n{recovery}")
            if assessment:
                summary_parts.append(f"**Assessment:** {assessment}")
            if conclusion:
                summary_parts.append(f"**Conclusion**\n{conclusion}")

        thread_summary = "\n\n".join(summary_parts).strip() or summary[:2000]

        # ── Build key_findings list ──
        if thread_summary_section:
            # Template D: key_findings = key_points bullets
            findings_list = _as_bullets(key_points) if key_points else []
        else:
            # Incident: combine issue + findings + root_cause
            findings_list = _as_bullets(
                "\n".join(filter(None, [issue, findings, root_cause]))
            )
        findings_list = findings_list or [
            "Review raw analysis for detailed evidence extracted from messages and files."
        ]

        # ── Build recommended_actions list ──
        if thread_summary_section:
            actions = _as_bullets(decisions) if decisions else []
        else:
            actions = _as_bullets(
                "\n".join(filter(None, [recovery, conclusion, status_section]))
            )
        actions = actions or [
            "No explicit action items detected; assign owners to follow up on unresolved findings."
        ]
```

**Step 4: Run all tests**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add services/ai/slack_investigation_service.py tests/test_slack_investigation_service.py
git commit -m "feat(slack): update section extraction for all 4 template outputs"
```

---

## Task 4: Add `assessment` Field to Response Schema (SERIAL — depends on Task 3)

**Files:**
- Modify: `explorer/backend/schemas/slack_investigation.py` (add field)
- Modify: `explorer/backend/services/ai/slack_investigation_service.py` (populate field)
- Modify: `explorer/frontend/lib/types.ts` (add field)
- Test: `explorer/backend/tests/test_slack_investigation_service.py`

**Step 1: Write the failing test**

```python
# Add to explorer/backend/tests/test_slack_investigation_service.py

def test_assessment_extracted_from_summary() -> None:
    """Assessment verdict should be extracted from **Assessment:** line."""
    md = (
        "**Issue Summary**\nRobot stopped.\n\n"
        "**Assessment:** This is a hardware fault.\n\n"
        "**Status:** Resolved"
    )
    import re
    match = re.search(r"\*\*Assessment:\*\*\s*(.+?)(?:\n|$)", md)
    assert match is not None
    assert match.group(1).strip() == "This is a hardware fault."
```

**Step 2: Add `assessment` to Pydantic schema**

```python
# In explorer/backend/schemas/slack_investigation.py, add to SlackThreadInvestigationResponse:
    assessment: str = ""
```

**Step 3: Populate `assessment` in `investigate()` return**

```python
# In the return statement of investigate(), add:
            assessment=assessment,
```

**Step 4: Update `_infer_risk()` to use assessment verdict**

```python
    def _infer_risk(self, summary: str, assessment: str = "") -> str:
        # Prefer structured assessment verdict over keyword scanning
        if assessment:
            lowered = assessment.lower()
            if "hardware fault" in lowered or "software bug" in lowered:
                return "high"
            if "configuration error" in lowered or "environmental factor" in lowered:
                return "medium"
            if "as designed" in lowered:
                return "low"
            if "tentative" in lowered:
                return "medium"

        # Fallback: keyword scan on full summary
        lowered = summary.lower()
        if any(token in lowered for token in ["sev1", "critical", "safety", "production down", "data loss"]):
            return "high"
        if any(token in lowered for token in ["degraded", "intermittent", "warning", "retry"]):
            return "medium"
        return "low"
```

**Step 5: Add `assessment` to frontend types**

```typescript
// In explorer/frontend/lib/types.ts, add to SlackThreadInvestigationResponse:
  assessment?: string;
```

**Step 6: Run all tests**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py -v`
Expected: ALL PASS

**Step 7: Commit**

```bash
git add schemas/slack_investigation.py services/ai/slack_investigation_service.py
git add ../frontend/lib/types.ts
git commit -m "feat(slack): add assessment field to response schema"
```

---

## Task 5: Send Images to Vision-Capable LLMs (SERIAL — depends on Task 2)

**Files:**
- Modify: `explorer/backend/services/ai/slack_investigation_service.py` (in `_generate_summary`, build multimodal content blocks)
- Test: `explorer/backend/tests/test_slack_investigation_service.py`

### How it works

The OpenAI chat API accepts multimodal user messages:
```python
{"role": "user", "content": [
    {"type": "text", "text": "Analyze this thread..."},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR...", "detail": "low"}},
]}
```

This format works with GPT-4o, GPT-4.1, and Gemini (via OpenAI-compatible API). For Ollama text-only models, images are simply not included (no crash — Ollama ignores unknown content types).

**Step 1: Write the failing test**

```python
def test_generate_summary_includes_images_for_vision_model(monkeypatch) -> None:
    """When using a vision-capable model, images should be sent as content blocks."""
    from services.ai.slack_investigation_service import SlackInvestigationService
    from schemas.slack_investigation import (
        SlackThreadInvestigationRequest,
        SlackThreadMessage,
        SlackThreadAttachment,
    )

    captured = []

    class FakeLLM:
        active_provider = {"type": "openai", "model": "gpt-4o"}
        model = "gpt-4o"
        last_usage = {}

        def chat(self, messages, **kwargs):
            captured.extend(messages)
            return "**Issue Summary**\nTest.\n\n**Assessment:** Hardware fault.\n\n**Status:** Resolved\n**cc:** @test"

    svc = SlackInvestigationService(_llm_service=FakeLLM())
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123/p1234567890",
        description="Test issue",
    )
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-01-01", user="alice", text="See screenshot")]
    attachments = [SlackThreadAttachment(
        filename="error.png", filetype="image", extracted="[Image: error.png]",
        b64_image="iVBORw0KGgo=",  # tiny fake base64
    )]

    svc._generate_summary(req, msgs, attachments)

    user_msg = captured[1]
    # For vision models, content should be a list with text + image blocks
    assert isinstance(user_msg["content"], list)
    assert user_msg["content"][0]["type"] == "text"
    image_blocks = [b for b in user_msg["content"] if b["type"] == "image_url"]
    assert len(image_blocks) == 1
    assert "data:image/" in image_blocks[0]["image_url"]["url"]


def test_generate_summary_no_images_for_ollama(monkeypatch) -> None:
    """Ollama models should get plain text content, no image blocks."""
    from services.ai.slack_investigation_service import SlackInvestigationService
    from schemas.slack_investigation import (
        SlackThreadInvestigationRequest,
        SlackThreadMessage,
        SlackThreadAttachment,
    )

    captured = []

    class FakeLLM:
        active_provider = {"type": "ollama", "model": "qwen2.5-coder"}
        model = "qwen2.5-coder"
        last_usage = {}

        def chat(self, messages, **kwargs):
            captured.extend(messages)
            return "**Issue Summary**\nTest.\n\n**Assessment:** Software bug.\n\n**Status:** Resolved\n**cc:** @test"

    svc = SlackInvestigationService(_llm_service=FakeLLM())
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://test.slack.com/archives/C123/p1234567890",
        description="Test issue",
    )
    msgs = [SlackThreadMessage(ts="1.0", datetime="2026-01-01", user="alice", text="See screenshot")]
    attachments = [SlackThreadAttachment(
        filename="error.png", filetype="image", extracted="[Image: error.png]",
        b64_image="iVBORw0KGgo=",
    )]

    svc._generate_summary(req, msgs, attachments)

    user_msg = captured[1]
    # For Ollama, content should be plain string (no vision support)
    assert isinstance(user_msg["content"], str)
```

**Step 2: Run to verify it fails**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py::test_generate_summary_includes_images_for_vision_model -v`
Expected: FAIL — `user_msg["content"]` is `str`, not `list`

**Step 3: Implement multimodal content blocks**

In `_generate_summary()`, after building the `prompt` string and before constructing `chat`, add:

```python
        # ── Build user message (multimodal for vision models) ──
        is_vision = is_remote  # GPT-4o, GPT-4.1, Gemini all support vision
        image_attachments = [a for a in attachments if a.b64_image] if is_vision else []

        chat: List[Dict] = [{"role": "system", "content": system}]

        if image_attachments:
            # Multimodal: text + image content blocks
            content_blocks: List[Dict] = [{"type": "text", "text": prompt}]
            for att in image_attachments[:5]:  # cap at 5 images to limit tokens
                # Infer MIME from filename extension
                ext = att.filename.rsplit(".", 1)[-1].lower() if "." in att.filename else "png"
                mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}.get(ext, "png")
                content_blocks.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/{mime};base64,{att.b64_image}",
                        "detail": "low",  # 65 tokens per image — cost-efficient
                    },
                })
            chat.append({"role": "user", "content": content_blocks})
        else:
            chat.append({"role": "user", "content": prompt})
```

Key design decisions:
- **Cap at 5 images** — each `detail: low` image costs ~65 tokens. 5 images = ~325 tokens. Prevents token explosion.
- **`detail: low`** — 65 tokens vs 765+ for `detail: high`. Sufficient for screenshots of error dialogs, graphs, terminal output.
- **Only for remote providers** (`is_remote = True` for openai/gemini). Ollama text models get plain string.

**Step 4: Run all tests**

Run: `cd explorer/backend && python -m pytest tests/test_slack_investigation_service.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add services/ai/slack_investigation_service.py tests/test_slack_investigation_service.py
git commit -m "feat(slack): send images to vision-capable LLMs (GPT-4o, Gemini)"
```

---

## Task 6: Update Banned-Phrases Check in Prompt (PARALLEL with Task 5)

**Files:**
- Modify: `explorer/backend/services/ai/prompts/issue_summary.md`

The BANNED PHRASES list currently includes "Thread Summary" — but Template D uses `**Thread Summary**` as a valid section name. This is a contradiction.

**Step 1: Fix the contradiction**

Remove "Thread Summary" from the BANNED PHRASES line in `issue_summary.md`. The banned phrases list should only apply to incident templates.

Change:
```
BANNED PHRASES: "Current Status / Risks", "Actions Taken / Suggested Fixes", "Issue Overview", "Key Findings", "Key Observations", "Thread Summary", "Remaining risk", "Recommended follow-up"
```

To:
```
BANNED PHRASES (incident mode only): "Current Status / Risks", "Actions Taken / Suggested Fixes", "Issue Overview", "Key Findings", "Key Observations", "Remaining risk", "Recommended follow-up"
```

**Step 2: Commit**

```bash
git add services/ai/prompts/issue_summary.md
git commit -m "fix(prompts): remove Thread Summary from banned phrases (used by Template D)"
```

---

## Task 7: Frontend — Display Assessment Badge (SERIAL — depends on Task 4)

**Files:**
- Modify: `explorer/frontend/app/slack-investigation/page.tsx` (add assessment display to results)

**Step 1: Add assessment badge to the results section**

In the results panel where `thread_summary` and `key_findings` are displayed, add an assessment badge:

```tsx
{result.assessment && (
  <div className="mb-4 flex items-center gap-2">
    <span className="text-sm font-medium text-zinc-400">Assessment:</span>
    <span className={`inline-flex items-center rounded-full px-3 py-0.5 text-sm font-medium ${
      result.risk_level === "high" ? "bg-red-500/10 text-red-400 ring-1 ring-red-500/20" :
      result.risk_level === "medium" ? "bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/20" :
      "bg-emerald-500/10 text-emerald-400 ring-1 ring-emerald-500/20"
    }`}>
      {result.assessment}
    </span>
  </div>
)}
```

**Step 2: Verify in browser**

Run the dev server and test with a real Slack thread. Assessment should appear as a colored badge.

**Step 3: Commit**

```bash
git add ../frontend/app/slack-investigation/page.tsx
git commit -m "feat(frontend): display assessment badge in slack investigation results"
```

---

## Task Dependencies

```
Task 1 (Prompt Loader)
  └─→ Task 2 (Replace Hardcoded Prompt)
        └─→ Task 3 (Section Extraction)
              └─→ Task 4 (Assessment Field)
                    └─→ Task 7 (Frontend Badge)
        └─→ Task 5 (Vision/Images)
  Task 6 (Banned Phrases Fix) — PARALLEL with any task
```

- **PARALLEL tasks:** Task 6 can run anytime. Task 5 and Task 3 are independent after Task 2.
- **SERIAL tasks:** 1 → 2 → 3 → 4 → 7; and 1 → 2 → 5.

## Summary of Changes

| File | Action | What |
|---|---|---|
| `services/ai/prompts/__init__.py` | Create | `load_prompt()` utility with LRU cache |
| `services/ai/prompts/issue_summary.md` | Modify | Fix banned phrases contradiction |
| `services/ai/slack_investigation_service.py` | Modify | Replace hardcoded prompt, update section extraction, add vision content blocks, populate assessment |
| `schemas/slack_investigation.py` | Modify | Add `assessment: str = ""` field |
| `frontend/lib/types.ts` | Modify | Add `assessment?: string` |
| `frontend/app/slack-investigation/page.tsx` | Modify | Display assessment badge |
| `tests/test_prompt_loader.py` | Create | 3 tests for prompt loader |
| `tests/test_slack_investigation_service.py` | Modify | ~8 new tests for templates, assessment, vision |

## Token / Cost Impact

| Provider | Old prompt tokens | New prompt tokens | Δ | Cost/call Δ |
|---|---|---|---|---|
| Ollama (free) | ~120 | ~700 | +580 | $0 |
| GPT-4o | ~120 | ~700 + 325 (images) | +905 | +$0.002 |
| Gemini 2.0 Flash | ~120 | ~700 + 325 (images) | +905 | +$0.0001 |

The 5x larger prompt adds negligible cost (~$0.002/call on the most expensive provider).
