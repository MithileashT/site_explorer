"""Routes for Slack thread based investigations."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.logging import get_logger
from schemas.slack_investigation import (
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


@router.post("/api/v1/slack/investigate", tags=["slack"])
def investigate_slack_thread(req: SlackThreadInvestigationRequest) -> SlackThreadInvestigationResponse:
    if _service is None:
        raise HTTPException(503, "Slack investigation service unavailable.")

    try:
        return _service.investigate(req)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.error("Slack investigation failed: %s", exc, exc_info=True)
        raise HTTPException(500, f"Slack investigation failed: {exc}") from exc
