"""Routes for Slack thread based investigations."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from core.logging import get_logger
from schemas.slack_investigation import (
    SlackLLMStatusResponse,
    SlackThreadInvestigationRequest,
    SlackThreadInvestigationResponse,
)
from services.ai.slack_investigation_service import SlackInvestigationService

logger = get_logger(__name__)
router = APIRouter()

_service: SlackInvestigationService | None = None


def register_singletons(llm_service) -> None:
    global _service
    _service = SlackInvestigationService(llm_service)


@router.get("/api/v1/slack/status", tags=["slack"], response_model=SlackLLMStatusResponse)
def slack_status() -> SlackLLMStatusResponse:
    if _service is None:
        raise HTTPException(503, "Slack investigation service unavailable.")
    try:
        return _service.llm_status()
    except Exception as exc:
        logger.error("Slack status check failed: %s", exc, exc_info=True)
        raise HTTPException(500, f"Slack status check failed: {exc}") from exc


@router.post("/api/v1/slack/investigate", tags=["slack"])
async def investigate_slack_thread(req: SlackThreadInvestigationRequest) -> SlackThreadInvestigationResponse:
    if _service is None:
        raise HTTPException(503, "Slack investigation service unavailable.")

    try:
        # Run blocking service call in thread pool to avoid blocking the event loop
        result = await asyncio.to_thread(_service.investigate, req)
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.error("Slack investigation failed: %s", exc, exc_info=True)
        raise HTTPException(500, f"Slack investigation failed: {exc}") from exc


@router.post("/api/v1/slack/investigate/stream", tags=["slack"])
async def investigate_slack_thread_stream(req: SlackThreadInvestigationRequest):
    """SSE streaming endpoint — yields summary text chunks as the LLM generates them,
    then emits a final 'result' event with the full structured response."""
    if _service is None:
        raise HTTPException(503, "Slack investigation service unavailable.")

    def event_generator():
        try:
            for event_type, data in _service.investigate_streaming(req):
                if event_type == "chunk":
                    yield f"data: {json.dumps({'type': 'chunk', 'text': data})}\n\n"
                elif event_type == "result":
                    yield f"data: {json.dumps({'type': 'result', 'data': data.model_dump(mode='json')})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except ValueError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        except RuntimeError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        except Exception as exc:
            logger.error("Streaming investigation failed: %s", exc, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/v1/slack/thread/summary", tags=["slack"], response_model=SlackThreadInvestigationResponse)
async def summarize_slack_thread(req: SlackThreadInvestigationRequest) -> SlackThreadInvestigationResponse:
    return await investigate_slack_thread(req)
