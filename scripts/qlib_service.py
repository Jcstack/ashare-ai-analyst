"""Qlib microservice — standalone FastAPI app wrapping qlib_worker commands.

Runs in a separate container with Python 3.11 + pyqlib installed.
The main application connects via HTTP instead of subprocess.

Endpoints mirror the CLI commands in qlib_worker.py:
  GET  /health          — Qlib availability and version
  POST /predict         — Run prediction for symbols
  POST /ic              — Get IC value for a symbol
  POST /alpha           — Get alpha factors for a symbol
"""

from __future__ import annotations

import math
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

# Reuse existing worker logic
from qlib_worker import (
    _ensure_init,
    cmd_alpha,
    cmd_health,
    cmd_ic,
    cmd_predict,
)

app = FastAPI(title="Qlib Service", version="1.0.0")


def _sanitize(obj: Any) -> Any:
    """Replace NaN/Inf with None for JSON serialization."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


class PredictRequest(BaseModel):
    symbols: list[str]
    horizon: int = 5


class ICRequest(BaseModel):
    symbol: str


class AlphaRequest(BaseModel):
    symbol: str


@app.get("/health")
async def health() -> dict[str, Any]:
    return _sanitize(cmd_health())


@app.post("/predict")
async def predict(req: PredictRequest) -> dict[str, Any]:
    _ensure_init()
    result = cmd_predict(req.symbols, req.horizon)
    return _sanitize(result)


@app.post("/ic")
async def ic(req: ICRequest) -> dict[str, Any]:
    _ensure_init()
    result = cmd_ic(req.symbol)
    return _sanitize(result)


@app.post("/alpha")
async def alpha(req: AlphaRequest) -> dict[str, Any]:
    _ensure_init()
    result = cmd_alpha(req.symbol)
    return _sanitize(result)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
