"""
main.py — FastAPI entrypoint (Phases 0-9).

- /health, /agent/*, /guard/*, /execute/*
- /eval/*, /cases/*, /webhooks/razorpay, /demo/replay
- /ui/batch, /ui/cases/{id}
- Phase 9: structured logs on boot; see docs/
"""

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes_agent import router as agent_router
from api.routes_cases import router as cases_router
from api.routes_demo import router as demo_router
from api.routes_eval import router as eval_router
from api.routes_execute import router as execute_router
from api.routes_guard import router as guard_router
from api.routes_ui import router as ui_router
from api.routes_webhooks import router as webhooks_router
from ledger.db import init_db
from logging_util import configure_logging, slog

_ROOT = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_db()
    slog("app_start", status="ok")
    yield


app = FastAPI(
    title="Recovery Agent",
    description="Razorpay /buildathon Track 03 — failed payment recovery",
    version="0.9.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(_ROOT / "static")), name="static")

app.include_router(agent_router)
app.include_router(guard_router)
app.include_router(execute_router)
app.include_router(eval_router)
app.include_router(cases_router)
app.include_router(webhooks_router)
app.include_router(demo_router)
app.include_router(ui_router)


@app.get("/health")
def health() -> dict[str, bool | str]:
    return {"ok": True, "phase": "9-hardening"}
