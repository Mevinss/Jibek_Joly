"""Export only Person 3 contracts; shared schemas remain owned by integration."""
import json
from pathlib import Path
from pydantic import TypeAdapter

from backend.analytics.router import CascadeRequest, WhatIfRequest
from backend.analytics.service import QualityIndexResult
from backend.analytics.what_if import WhatIfResult
from backend.connections.service import CascadingDelayResult, ConnectionGraph
from backend.eta.service import TrainETA, StationArrivalsResult
from .models import DispatchRunResult, CompareResult
from .router import CompareRequest


def main():
    folder = Path(__file__).parent / "contracts"
    folder.mkdir(exist_ok=True)
    for model in (DispatchRunResult, CompareResult, TrainETA, StationArrivalsResult, CascadingDelayResult,
                  QualityIndexResult, WhatIfResult, ConnectionGraph, CompareRequest, CascadeRequest, WhatIfRequest):
        schema = TypeAdapter(model).json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        (folder / (model.__name__ + ".schema.json")).write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
