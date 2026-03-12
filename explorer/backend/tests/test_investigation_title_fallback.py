"""Tests for optional investigation title fallback behavior."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.routes.investigation import _resolve_incident_title
from schemas.investigation import IncidentReportRequest


def test_resolve_incident_title_prefers_supplied_value():
    assert _resolve_incident_title("  Wheel encoder drift  ", "desc") == "Wheel encoder drift"


def test_resolve_incident_title_uses_first_sentence_when_missing():
    description = "Robot stopped near elevator lobby. Planner retries exceeded and watchdog tripped."
    resolved = _resolve_incident_title(None, description)
    assert resolved == "Robot stopped near elevator lobby"


def test_resolve_incident_title_uses_default_when_description_empty():
    assert _resolve_incident_title("", "   ") == "Untitled incident"


def test_incident_schema_accepts_missing_title():
    request = IncidentReportRequest(description="AMR stalled near loading zone")
    assert request.title is None
    assert request.description == "AMR stalled near loading zone"
