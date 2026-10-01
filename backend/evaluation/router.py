"""Opt-in router: integration owner includes it; no global application changes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.planner.models import PlanningConfig
from .service import compare_policies
from .models import CompareResult


class CompareRequest(BaseModel):
    snapshot: dict
    config: dict = Field(default_factory=dict)
    human_plan: dict | None = None
    human_decisions: list[dict] = Field(default_factory=list)
    incident_id: str | None = None


def create_evaluation_router(**service_options):
    router = APIRouter(prefix="/api", tags=["runtime-evaluation"])

    @router.post("/compare", response_model=CompareResult)
    def compare(request: CompareRequest):
        try:
            return compare_policies(request.snapshot, config=PlanningConfig(**request.config),
                human_plan=request.human_plan, human_decisions=request.human_decisions,
                incident_id=request.incident_id, **service_options).to_dict()
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    return router
