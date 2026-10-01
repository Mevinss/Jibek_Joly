"""Separate Person 3 API demonstration; not the shared live application.

Run: python -m backend.evaluation.demo_app; http://127.0.0.1:8003/docs
"""
from fastapi import FastAPI

from backend.analytics.router import create_analytics_router
from backend.planner.models import PlanningConfig
from backend.planner.service import build_fifo_plan
from .demo import short_route_demo
from .router import create_evaluation_router
from .service import compare_policies


def create_app():
    snapshot = short_route_demo()
    config = PlanningConfig(horizon_seconds=600, time_limit_seconds=1)
    plan = build_fifo_plan(snapshot, config=config)
    comparison = compare_policies(snapshot, config=config)
    app = FastAPI(title="Jibek Joly — Person 3 synthetic short-route API", description=(
        "Three shortened Kazakhstan demonstration journeys, not the full 28-train run. "
        "No operational data or railway control. Shared application is unchanged."))
    app.include_router(create_evaluation_router())
    app.include_router(create_analytics_router(lambda: snapshot, plan_provider=lambda: plan, run_provider=lambda: comparison.fifo))

    @app.get("/demo/input")
    def demo_input():
        return snapshot

    @app.get("/demo/compare")
    def demo_compare():
        return comparison.to_dict()

    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=8003)
