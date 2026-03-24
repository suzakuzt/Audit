from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.document_structuring.canonical_json_builder import CanonicalJSONBuilder


router = APIRouter()
DEFAULT_DEBUG_DIR = Path("outputs") / "canonical_debug"


class CanonicalDebugRequest(BaseModel):
    raw_ocr_json: dict[str, Any] = Field(default_factory=dict)
    doc_id: str | None = None
    save_debug_files: bool = True
    debug_dir: str | None = None


class CanonicalDebugResponse(BaseModel):
    canonical_json: dict[str, Any]
    merged_blocks: list[dict[str, Any]]
    reading_order: list[dict[str, Any]]
    kv_candidates: list[dict[str, Any]]
    table_candidates: list[dict[str, Any]]
    deepseek_payload: dict[str, Any]
    debug_dir: str | None = None


@router.post("/debug/canonical-json", response_model=CanonicalDebugResponse)
def build_canonical_json_debug(payload: CanonicalDebugRequest) -> CanonicalDebugResponse:
    if not isinstance(payload.raw_ocr_json, dict) or not payload.raw_ocr_json:
        raise HTTPException(status_code=400, detail="raw_ocr_json is required.")

    builder = CanonicalJSONBuilder()
    build_result = builder.build_from_raw(payload.raw_ocr_json, doc_id=payload.doc_id)
    debug_payload = build_result.to_debug_payload()
    canonical = debug_payload["canonical"]
    deepseek_payload = builder.build_deepseek_payload(build_result.canonical)

    output_dir: Path | None = None
    if payload.save_debug_files:
        output_dir = _persist_debug_files(
            debug_payload=debug_payload,
            target_dir=Path(payload.debug_dir) if payload.debug_dir else DEFAULT_DEBUG_DIR,
            doc_id=canonical.get("doc_id", ""),
        )

    return CanonicalDebugResponse(
        canonical_json=canonical,
        merged_blocks=debug_payload["merged_blocks"],
        reading_order=debug_payload["reading_order"],
        kv_candidates=debug_payload["kv_candidates"],
        table_candidates=debug_payload["table_candidates"],
        deepseek_payload=deepseek_payload,
        debug_dir=str(output_dir) if output_dir else None,
    )


def _persist_debug_files(*, debug_payload: dict[str, Any], target_dir: Path, doc_id: str) -> Path:
    run_dir = target_dir / (doc_id or "canonical_debug")
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "merged_blocks.json", debug_payload.get("merged_blocks", []))
    _write_json(run_dir / "reading_order.json", debug_payload.get("reading_order", []))
    _write_json(run_dir / "kv_candidates.json", debug_payload.get("kv_candidates", []))
    _write_json(run_dir / "table_candidates.json", debug_payload.get("table_candidates", []))
    _write_json(run_dir / "canonical.json", debug_payload.get("canonical", {}))
    return run_dir


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

