from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

import audit_system.models  # noqa: F401
from audit_system.api.router import api_router
from audit_system.api.routes.document_compare import foundation_page
from audit_system.config import settings
from audit_system.db.base import Base
from audit_system.db.session import engine
from services.extractor_service import list_prompt_versions, load_knowledge_file

logger = logging.getLogger(__name__)

FRONTEND_DIST_DIR = Path(__file__).resolve().parent / "frontend_dist"


def _warm_up_reference_data() -> None:
    settings.runtime_temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        list_prompt_versions()
    except Exception as exc:
        logger.warning("Prompt version warm-up skipped: %s", exc)

    knowledge_dir = Path("knowledge")
    for file_name in (
        "alias_active.json",
        "alias_candidates.json",
        "rule_active.json",
        "rule_candidates.json",
    ):
        try:
            load_knowledge_file(knowledge_dir / file_name)
        except Exception as exc:
            logger.warning("Knowledge warm-up skipped for %s: %s", file_name, exc)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    _warm_up_reference_data()
    yield


app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(api_router, prefix="/api/v1")
if FRONTEND_DIST_DIR.exists():
    app.mount("/static/foundation", StaticFiles(directory=FRONTEND_DIST_DIR), name="foundation-static")


@app.get("/", response_class=HTMLResponse)
@app.get("/foundation", response_class=HTMLResponse)
@app.get("/compare", response_class=HTMLResponse)
def read_root() -> str:
    return foundation_page()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
