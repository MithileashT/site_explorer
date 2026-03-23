# Slack Fetch Optimization — Remove File Downloads, Text-Only Pipeline

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Eliminate all file download/processing from the Slack investigation pipeline so summary generation completes in <10 seconds (currently ~150s due to attachment downloads consuming 95% of wall time).

**Architecture:** Strip out the entire Phase 3 (attachment download/process) from `_fetch_thread_messages`. Keep only Slack API message fetch + user resolution + text/log extraction. Mention filenames in messages for context but never download content. Simplify the prompt builder to remove attachment sections. Bump cache schema version to invalidate stale entries.

**Tech Stack:** Python/FastAPI, slack_sdk, OpenAI gpt-4.1 (via LLMService), Pydantic schemas, pytest

---

## Current vs. Proposed Timing Breakdown

| Phase | Current | Proposed |
|-------|---------|----------|
| Phase 1: Slack messages API | ~1-2s | ~1-2s (unchanged) |
| Phase 2: User ID resolution | ~1-2s | ~1-2s (unchanged) |
| Phase 3: Attachment download + parse | **~130-150s** | **0s (removed)** |
| Phase 4: Assemble message objects | <0.1s | <0.1s (unchanged) |
| LLM call (gpt-4.1) | ~10s | ~8s (smaller prompt) |
| **Total** | **~150-165s** | **~10-14s** |

## Files Affected

| File | Action | Purpose |
|------|--------|---------|
| `explorer/backend/services/ai/slack_investigation_service.py` | Modify | Remove download/process methods, simplify fetch pipeline |
| `explorer/backend/services/ai/prompts/issue_summary.md` | Modify | Remove attachment references from prompt |
| `explorer/backend/schemas/slack_investigation.py` | Modify | Deprecate `SlackThreadAttachment.b64_image`, keep schema backward-compat |
| `explorer/backend/tests/test_slack_investigation_service.py` | Modify | Update/remove attachment tests, add text-only tests |
| `explorer/backend/app/routes/slack_investigation.py` | No change | Routes are already clean |
| `explorer/frontend/lib/types.ts` | No change | `attachment_count` is optional, will just be 0 |

---

## Pre-Implementation: Current Bottleneck Evidence

From production logs (23 March 2026):
```
Slack fetch completed: 152.17s (29 messages, 7 attachments)
Slack investigate timing: fetch=152.17s llm=9.90s total=162.07s
```

The LLM is already fast (9.9s). The entire bottleneck is `_fetch_thread_messages` Phase 3: downloading 7 attachments via Slack CDN.

---

## Task 1: Remove file download and processing methods (SERIAL)

**Files:**
- Modify: `explorer/backend/services/ai/slack_investigation_service.py`

**Step 1: Delete dead constants and imports**

Remove these constants (no longer needed):
```python
# DELETE these lines:
_MAX_ATTACHMENT_WORKERS = 16
_FILE_DOWNLOAD_TIMEOUT = 8
_ATTACHMENT_SECTION_CHAR_LIMIT = 3000
_MAX_ATTACHMENTS_PER_THREAD = 5
_MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024
_TOTAL_ATTACHMENT_BUDGET_SECONDS = 15
MAX_FILE_CHARS = 12_000
```

Remove these imports (no longer needed after method deletion):
```python
# DELETE if no longer referenced:
import base64
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
```

Keep `ThreadPoolExecutor` and `as_completed` — they are still used by Phase 2 (user resolution).

**Step 2: Delete file download/processing methods**

Remove these methods entirely from `SlackInvestigationService`:
- `_download_file(self, url)`
- `_proc_image(self, data, filename)`
- `_proc_pdf(self, data, filename)`
- `_proc_pptx(self, data, filename)`
- `_proc_text(self, data, filename, filetype)`
- `_process_attachment(self, slack_file)`

Also remove `self._http_session` attribute from `__init__` and the `_slack_headers` method (only used for file downloads; Slack API messages use `WebClient` with its own token).

Wait — `_slack_headers` is also used by `_download_file` only. Verify no other caller uses it before removing. If the `_require_client` pattern handles auth for WebClient, `_slack_headers` is dead code after download removal.

**Step 3: Bump cache schema version**

Change `_SUMMARY_CACHE_SCHEMA_VERSION = "v2"` → `"v3"` to invalidate cached summaries that were generated with attachment context.

**Step 4: Run syntax check**

Run: `python -c "import py_compile; py_compile.compile('services/ai/slack_investigation_service.py', doraise=True)"`
Expected: `Syntax OK`

**Step 5: Commit**

```bash
git add explorer/backend/services/ai/slack_investigation_service.py
git commit -m "perf: remove file download/processing methods from slack investigation"
```

---

## Task 2: Simplify `_fetch_thread_messages` — remove Phase 3 (SERIAL, depends on Task 1)

**Files:**
- Modify: `explorer/backend/services/ai/slack_investigation_service.py`

**Step 1: Rewrite `_fetch_thread_messages` to remove attachment download logic**

Replace the entire Phase 3 block (attachment collection, ThreadPoolExecutor download, budget timeout) and Phase 4 assembly with a simplified version:

Instead of downloading attachments, collect **only filenames** from `raw.get("files", [])` as lightweight metadata on each `SlackThreadMessage`. This preserves the information that files were shared (useful context for the LLM) without the download cost.

New Phase 3 becomes: "Assemble SlackThreadMessage objects with file mentions."

```python
def _fetch_thread_messages(
    self,
    ref: ParsedSlackThreadRef,
    include_bots: bool,
    max_messages: int,
) -> Tuple[List[SlackThreadMessage], List[SlackThreadAttachment]]:
    client = self._require_client()
    cursor = None
    _auto_joined = False
    t_phase_start = time.perf_counter()

    # ── Phase 1: Fetch raw Slack messages ────────────────────────
    raw_items: List[Dict] = []
    # ... (keep existing Phase 1 unchanged) ...

    t_messages = time.perf_counter()
    logger.info("Fetch phase 1 (messages): %.1fs (%d messages)",
                 t_messages - t_phase_start, len(raw_items))

    # ── Phase 2: Batch-resolve unique user IDs (parallel) ────────
    # ... (keep existing Phase 2 unchanged) ...

    t_users = time.perf_counter()
    logger.info("Fetch phase 2 (user resolve): %.1fs (%d users)",
                 t_users - t_messages, len(users_to_resolve))

    # ── Phase 3: Assemble SlackThreadMessage objects ─────────────
    # Note: File attachments are NOT downloaded. Filenames are recorded
    # as lightweight metadata so the LLM knows what was shared.
    messages: List[SlackThreadMessage] = []
    file_mentions: List[SlackThreadAttachment] = []
    for raw in raw_items:
        raw_text = raw.get("text") or ""
        clean_text, log_blocks = _extract_log_blocks(raw_text)

        # Collect file names without downloading
        msg_file_mentions: List[SlackThreadAttachment] = []
        for slack_file in raw.get("files", []) or []:
            fname = slack_file.get("name", "unknown")
            ftype = slack_file.get("filetype", "unknown")
            mention = SlackThreadAttachment(
                filename=fname,
                filetype=ftype,
                extracted=f"[File shared: {fname}]",
            )
            msg_file_mentions.append(mention)
            file_mentions.append(mention)

        if not clean_text and not log_blocks and not msg_file_mentions:
            continue

        ts = str(raw.get("ts", ""))
        try:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            dt = ts

        user_id = raw.get("user") or raw.get("bot_id")
        messages.append(
            SlackThreadMessage(
                ts=ts,
                datetime=dt,
                user=self._resolve_user(user_id),
                text=clean_text,
                log_blocks=log_blocks,
                attachments=msg_file_mentions,
            )
        )

    logger.info("Fetch phase 3 (assembly): %.1fs (%d messages, %d file mentions)",
                time.perf_counter() - t_users, len(messages), len(file_mentions))
    return messages, file_mentions
```

**Key change:** `all_attachments` now contains lightweight metadata-only objects (filename + filetype only), zero download I/O.

**Step 2: Run syntax check**

Run: `python -c "import py_compile; py_compile.compile('services/ai/slack_investigation_service.py', doraise=True)"`
Expected: `Syntax OK`

**Step 3: Commit**

```bash
git add explorer/backend/services/ai/slack_investigation_service.py
git commit -m "perf: remove attachment downloads from fetch pipeline — text-only"
```

---

## Task 3: Simplify `_build_prompt_messages` — remove attachment sections (SERIAL, depends on Task 2)

**Files:**
- Modify: `explorer/backend/services/ai/slack_investigation_service.py`

**Step 1: Strip attachment processing from prompt builder**

Current prompt builder has:
1. Thread lines with inline `[Attachment: filename (filetype)]` per message
2. A separate `ATTACHMENTS` section with extracted content
3. Image base64 embedding for multimodal models

After this change:
1. Thread lines include `[File shared: filename]` per message (lightweight)
2. **Remove** the separate `ATTACHMENTS` section entirely
3. **Remove** image base64 embedding (no images downloaded)

Modified `_build_prompt_messages`:
```python
def _build_prompt_messages(
    self,
    req: SlackThreadInvestigationRequest,
    messages: List[SlackThreadMessage],
    attachments: List[SlackThreadAttachment],
    model: str,
) -> Tuple[str, List[Dict], dict]:
    system = load_prompt("issue_summary")
    strategy = self._model_summary_strategy(model)

    selected_messages = messages[-strategy["prompt_message_limit"]:]

    thread_lines: List[str] = []
    for msg in selected_messages:
        clean_msg = _URL_RE.sub("", msg.text).strip()
        line = f"{msg.user}: {clean_msg}"
        for idx, block in enumerate(msg.log_blocks, 1):
            clean_block = _URL_RE.sub("", block[:2000]).strip()
            line += f"\n  [Log block {idx}]\n{clean_block}"
        for attachment in msg.attachments:
            line += f"\n  [File shared: {attachment.filename}]"
        thread_lines.append(line)

    prompt = (
        f"ISSUE NAME / DESCRIPTION:\n{req.description}\n\n"
        f"SITE: {req.site_id or 'N/A'}\n\n"
        f"SLACK THREAD ({len(selected_messages)} messages)\n"
        "--- MESSAGES ---\n\n"
        + "\n\n".join(thread_lines)
    )
    if req.custom_prompt:
        prompt += f"\n\nSPECIAL FOCUS: {req.custom_prompt}"

    max_prompt_chars = min(
        strategy["prompt_char_budget"],
        max(500, (settings.ollama_num_ctx - 800) * 3),
    )
    if len(prompt) > max_prompt_chars:
        prompt = prompt[:max_prompt_chars] + "\n\n[... thread truncated to fit context window ...]"

    chat: List[Dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    return system, chat, strategy
```

**Key removals:**
- `attachment_sections` list building
- `ATTACHMENTS` separator block
- `image_attachments` and multimodal `content_blocks` with base64
- `is_openai` / `is_remote` checks in this method (no longer needed for image routing)

**Step 2: Simplify `_model_summary_strategy`**

Remove the `attachment_char_limit` and `image_limit` keys from all strategy dicts — they are no longer used.

```python
@staticmethod
def _model_summary_strategy(model: str) -> dict:
    m = model.lower()
    if any(tag in m for tag in ("gpt-5", "gpt-4o", "gpt-4.1", "gpt-4-turbo", "gemini-2", "gemini-1.5-pro", "claude")):
        return {"max_tokens": 3200, "depth": "high", "prompt_char_budget": 12000, "prompt_message_limit": 120}
    if any(tag in m for tag in ("gpt-4o-mini", "gpt-3.5", "gemini-1.5-flash", "gemini-2.0-flash")):
        return {"max_tokens": 2400, "depth": "medium", "prompt_char_budget": 10000, "prompt_message_limit": 90}
    if any(tag in m for tag in ("70b", "72b", "llama3.1:70", "qwen2.5:72")):
        return {"max_tokens": 2400, "depth": "medium", "prompt_char_budget": 10000, "prompt_message_limit": 90}
    return {"max_tokens": 2000, "depth": "concise", "prompt_char_budget": 8000, "prompt_message_limit": 60}
```

**Step 3: Run syntax check**

Run: `python -c "import py_compile; py_compile.compile('services/ai/slack_investigation_service.py', doraise=True)"`
Expected: `Syntax OK`

**Step 4: Commit**

```bash
git add explorer/backend/services/ai/slack_investigation_service.py
git commit -m "perf: remove attachment sections from LLM prompt — text-only pipeline"
```

---

## Task 4: Clean up unused imports (SERIAL, depends on Task 3)

**Files:**
- Modify: `explorer/backend/services/ai/slack_investigation_service.py`

**Step 1: Remove dead imports**

After removing all file processing methods, these imports become unused:
```python
import base64    # was for _proc_image base64 encoding
import io        # was for BytesIO in _proc_pdf, _proc_pptx
```

Keep:
- `ThreadPoolExecutor, as_completed` — used by Phase 2 (user resolution)
- `requests` — used by `_ollama_ping`, `_ollama_models`, `_ollama_chat`, Ollama warm-up
- All other existing imports

**Step 2: Verify no dangling references**

Run: `grep -n "base64\|import io\|BytesIO\|pdfplumber\|python-pptx\|_proc_\|_download_file\|_http_session\|_slack_headers\|_process_attachment\|MAX_FILE_CHARS\|_ATTACHMENT_SECTION_CHAR_LIMIT\|_MAX_ATTACHMENT_WORKERS\|_FILE_DOWNLOAD_TIMEOUT\|_MAX_ATTACHMENT_SIZE\|_TOTAL_ATTACHMENT_BUDGET\|_MAX_ATTACHMENTS_PER_THREAD" services/ai/slack_investigation_service.py`

Expected: zero matches (all references removed).

**Step 3: Commit**

```bash
git add explorer/backend/services/ai/slack_investigation_service.py
git commit -m "chore: remove unused imports after attachment pipeline removal"
```

---

## Task 5: Update tests (SERIAL, depends on Task 4)

**Files:**
- Modify: `explorer/backend/tests/test_slack_investigation_service.py`

**Step 1: Remove/update attachment-specific tests**

Tests to **remove entirely** (test functionality that no longer exists):
- `test_attachment_workers_increased` — `_MAX_ATTACHMENT_WORKERS` deleted
- `test_attachment_processing_cap_for_latency` — `_MAX_ATTACHMENTS_PER_THREAD` deleted

Tests to **update** (still relevant but need adjustment):
- `test_attachment_text_included_in_prompt` — rename to `test_file_mention_included_in_prompt`, change expectation: prompt should contain `[File shared: robot.log]` instead of extracted file content
- `test_attachment_section_not_duplicated_in_prompt` — remove (no attachment section exists anymore)
- `test_attachment_section_truncated` — remove (no attachment section exists anymore)

Test imports to update: remove `_MAX_ATTACHMENT_WORKERS`, `_MAX_ATTACHMENTS_PER_THREAD` from the import block.

**Step 2: Write new test — file mentions appear in prompt without download**

```python
def test_file_mentions_in_prompt_without_download(monkeypatch) -> None:
    """File names should appear in the prompt as [File shared: ...] without downloading."""
    svc = SlackInvestigationService()
    captured: dict = {}

    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "## Issue Summary\n- test"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    att = SlackThreadAttachment(
        filename="crash_report.pdf", filetype="pdf",
        extracted="[File shared: crash_report.pdf]",
    )
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test file mention",
        max_messages=200,
    )
    msgs = [SlackThreadMessage(
        ts="1.0", datetime="2026-03-13 10:00 UTC", user="a",
        text="See attached report", attachments=[att],
    )]
    svc._generate_summary(req, msgs, [att])

    prompt = captured["messages"][1]["content"]
    assert "[File shared: crash_report.pdf]" in prompt
    # Verify NO base64 or extracted content sections
    assert "ATTACHMENTS" not in prompt
    assert "base64" not in prompt
```

**Step 3: Write new test — no multimodal image blocks in prompt**

```python
def test_no_multimodal_image_blocks(monkeypatch) -> None:
    """Image attachments should NOT produce multimodal content blocks."""
    svc = SlackInvestigationService()
    captured: dict = {}

    def spy_chat(msgs, model, **kw):
        captured["messages"] = msgs
        return "## Issue Summary\n- test"

    monkeypatch.setattr(svc, "_ollama_chat", spy_chat)
    monkeypatch.setattr(svc, "_ollama_models", lambda: [svc.text_model])

    att = SlackThreadAttachment(
        filename="screenshot.png", filetype="png",
        extracted="[File shared: screenshot.png]",
    )
    req = SlackThreadInvestigationRequest(
        slack_thread_url="https://example.slack.com/archives/C123ABC45/p1772691175223000",
        description="Test no images",
        max_messages=200,
    )
    msgs = [SlackThreadMessage(
        ts="1.0", datetime="2026-03-13 10:00 UTC", user="a",
        text="Screenshot attached", attachments=[att],
    )]
    svc._generate_summary(req, msgs, [att])

    user_msg = captured["messages"][1]
    # Content should be a plain string, NOT a list of content blocks
    assert isinstance(user_msg["content"], str)
```

**Step 4: Run full test suite**

Run: `python -m pytest tests/test_slack_investigation_service.py tests/test_slack_investigation_route.py -v --tb=short`
Expected: all tests PASS

**Step 5: Commit**

```bash
git add explorer/backend/tests/test_slack_investigation_service.py
git commit -m "test: update slack investigation tests for text-only pipeline"
```

---

## Task 6: Optimize the issue_summary prompt for speed (PARALLEL with Task 5)

**Files:**
- Modify: `explorer/backend/services/ai/prompts/issue_summary.md`

**Step 1: Remove attachment-related language from prompt**

Remove any mention of "attachments", "files", "images", "PDFs" from the prompt rules. The LLM should focus exclusively on message text and log blocks.

Update rule 4 (LOG EVIDENCE) — currently says:
```
4. LOG EVIDENCE: Describe meaning, never paste raw logs. Quote ≤15 words only for evidential value.
```
Keep as-is — still relevant for inline log blocks.

Update the output exclusion list at the top — currently says:
```
Exclude: ticket fields, Slack metadata, @mentions, URLs, rosbag filenames, JSON, raw log pastes, ROS topic dumps, conversational back-and-forth.
```
Add "file attachment listings" to excluded items:
```
Exclude: ticket fields, Slack metadata, @mentions, URLs, rosbag filenames, JSON, raw log pastes, ROS topic dumps, conversational back-and-forth, file attachment listings.
```

**Step 2: Add conciseness directive for speed**

The prompt is already 3678 chars (~919 tokens). No major trimming needed, but add a brief directive to encourage concise output (faster LLM generation = fewer output tokens):

After "THINK BEFORE YOU WRITE" section, before "THREAD ROUTING:", add:
```
CONCISENESS: Target 400-600 words. Every sentence must carry unique information. If evidence is thin, say so briefly rather than padding.
```

This reduces output token count → faster generation.

**Step 3: Commit**

```bash
git add explorer/backend/services/ai/prompts/issue_summary.md
git commit -m "perf: optimize issue_summary prompt — remove attachment refs, add conciseness"
```

---

## Task 7: Integration test — verify end-to-end timing (SERIAL, depends on Tasks 1-6)

**Files:**
- No new files

**Step 1: Restart backend**

```bash
cd explorer && docker compose restart backend
```

Wait 5 seconds, then verify health:
```bash
curl -s http://localhost:8000/api/v1/health | python3 -m json.tool
```
Expected: `"status": "ok"`, `"active_provider": { "model": "gpt-4.1" }`

**Step 2: Trigger a Slack investigation via the UI or curl**

Use the same thread that previously took 162 seconds. Check backend logs:
```bash
docker logs amr_backend --tail 30 | grep -iE "fetch phase|slack.*timing|fetch completed"
```

**Expected output:**
```
Fetch phase 1 (messages): ~1-2s (29 messages)
Fetch phase 2 (user resolve): ~1-2s (N users)
Fetch phase 3 (assembly): ~0.0s (29 messages, 7 file mentions)
Slack fetch completed: ~2-4s (29 messages, 7 attachments)
Slack investigate timing: fetch=~3s llm=~8s total=~11s
```

**Step 3: Verify output quality**

Confirm the generated summary:
- Still has ISSUE SUMMARY, Issue, Cause, Key Observations, Key Findings, Recovery Action, Conclusion sections
- Mentions file names (e.g., "A PDF report was shared") without extracted content
- Assessment and Status lines are present
- No degradation in analytical quality for text/log-heavy threads

**Step 4: Commit final**

```bash
git add -A
git commit -m "perf: verified slack investigation <10s after attachment removal"
```

---

## Comparison: Before vs After

| Aspect | Before (Current) | After (Proposed) |
|--------|-------------------|------------------|
| **Total time** | 150-165s | ~10-14s |
| **Fetch phase** | ~150s (dominated by downloads) | ~2-4s (API + user resolve only) |
| **LLM time** | ~10s | ~8s (smaller prompt) |
| **Prompt size** | ~8-12K chars (messages + attachment content) | ~4-7K chars (messages + file mentions only) |
| **Token usage** | ~3000-4000 input tokens | ~1500-2500 input tokens |
| **Dependencies** | pdfplumber, python-pptx, base64 | None (only slack_sdk, requests) |
| **File downloads** | Up to 5 files, 8s timeout each | Zero |
| **Streaming** | Available but slow due to fetch | Available, fast first-token |
| **Cache** | v2 schema (stale after this change) | v3 schema (clean invalidation) |
| **Output quality** | Full file content in analysis | Text/log focused analysis + file name mentions |

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Loss of file content analysis | File names still mentioned as `[File shared: X]`. LLM can infer context from filenames + surrounding discussion. For critical files, users can paste content into the description field. |
| Schema backward compatibility | `SlackThreadAttachment` schema kept intact. `attachment_count` will be count of file mentions (not downloads). Frontend uses this as optional display-only. |
| Cache invalidation | Bump to v3 ensures no stale results from old attachment-heavy summaries. |
| Test failures | Attachment-specific constants removed from imports. Tests updated to reflect new behavior. |

## Task Dependencies

```
Task 1 (remove methods)
  └─→ Task 2 (simplify fetch)
       └─→ Task 3 (simplify prompt builder)
            └─→ Task 4 (clean imports)
                 └─→ Task 5 (update tests) ──┐
                                              ├─→ Task 7 (integration verify)
     Task 6 (optimize prompt) ────────────────┘
```

- **SERIAL tasks**: 1 → 2 → 3 → 4 → 5, then 7
- **PARALLEL tasks**: Task 6 can run in parallel with Task 5
