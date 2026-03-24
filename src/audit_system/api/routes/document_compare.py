from __future__ import annotations

import asyncio
import json
import re
from uuid import uuid4
from html import escape
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from audit_system.config import settings
from schemas.document_schema import STANDARD_FIELD_LABELS, STANDARD_FIELD_LEVELS
from llm.client import LLMRuntimeConfig
from services.extractor_service import extract_document_with_options, list_prompt_versions, load_knowledge_file
from services.pdf_text_service import OCRRunConfig, build_pdf_visual_assets, extract_pdf_text
from services.run_store import apply_manual_confirmations, persist_extraction_run
from services.prompt_evolution_service import record_evolution_cycle
from utils.file_utils import create_run_output_dir, save_json
from utils.json_utils import normalize_text

router = APIRouter()
KNOWLEDGE_DIR = Path("knowledge")
BATCH_RUNS_DIR = Path("outputs") / "batch_runs"
VALIDATION_JOBS: dict[str, dict[str, Any]] = {}


def _build_visual_fallback_pages(metadata: Any) -> list[dict[str, Any]]:
    meta = metadata if isinstance(metadata, dict) else {}
    preview_pages = meta.get("ocr_preview_images") or []
    if not isinstance(preview_pages, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(preview_pages, start=1):
        if not isinstance(item, dict):
            continue
        image_url = str(item.get("image_data_url", "") or "").strip()
        if not image_url:
            continue
        normalized.append({
            "page_number": int(item.get("page_number", index) or index),
            "image_data_url": image_url,
            "page_width": int(item.get("page_width", 0) or 0),
            "page_height": int(item.get("page_height", 0) or 0),
            "words": item.get("words") if isinstance(item.get("words"), list) else [],
            "blocks": item.get("blocks") if isinstance(item.get("blocks"), list) else [],
        })
    return normalized


def _merge_visual_pages_with_fallback(visual_pages: list[dict[str, Any]], metadata: Any) -> list[dict[str, Any]]:
    fallback_pages = _build_visual_fallback_pages(metadata)
    if not fallback_pages:
        return visual_pages
    if not visual_pages:
        return fallback_pages

    fallback_by_page = {
        int(item.get("page_number", index + 1) or (index + 1)): item
        for index, item in enumerate(fallback_pages)
        if isinstance(item, dict)
    }
    merged: list[dict[str, Any]] = []
    for index, page in enumerate(visual_pages, start=1):
        if not isinstance(page, dict):
            merged.append(page)
            continue
        page_number = int(page.get("page_number", index) or index)
        fallback = fallback_by_page.get(page_number)
        if not fallback:
            merged.append(page)
            continue
        has_local_words = isinstance(page.get("words"), list) and bool(page.get("words"))
        has_local_blocks = isinstance(page.get("blocks"), list) and bool(page.get("blocks"))
        if has_local_words or has_local_blocks:
            merged.append(page)
            continue
        merged.append({
            **page,
            "page_width": int(fallback.get("page_width") or page.get("page_width") or 0),
            "page_height": int(fallback.get("page_height") or page.get("page_height") or 0),
            "words": fallback.get("words") if isinstance(fallback.get("words"), list) else [],
            "blocks": fallback.get("blocks") if isinstance(fallback.get("blocks"), list) else [],
        })
    return merged


def _sanitize_runtime_api_key(value: str | None) -> str:
    candidate = (value or "").strip()
    if not candidate:
        return ""
    if any(ord(ch) > 127 for ch in candidate):
        return ""
    lowered = candidate.lower()
    if "replace" in lowered or "deepseek_api_key" in lowered or "your" in lowered:
        return ""
    return candidate


def _parse_focus_fields(raw: str | None) -> list[str]:
    return [item.strip() for item in (raw or '').split(',') if item.strip()]


def _parse_priority_fields(raw: str | None) -> list[str]:
    return [item.strip() for item in (raw or '').split(',') if item.strip()]


def _process_uploaded_document(
    file_name: str,
    content: bytes,
    runtime_config: LLMRuntimeConfig,
    ocr_enabled: bool,
    force_ocr_value: bool,
    prompt_name: str,
    prompt_override: str | None,
    use_alias: bool,
    use_rule: bool,
    alias_active: Any,
    rule_active: list[dict[str, Any]],
    alias_candidates: list[dict[str, str]],
    rule_candidates: list[dict[str, str]],
    include_visuals: bool,
    focus_field_list: list[str],
    priority_field_list: list[str],
) -> dict[str, Any]:
    pdf_result = extract_pdf_text(
        file_name,
        content,
        ocr_config=OCRRunConfig(
            enabled=ocr_enabled,
            force_ocr=force_ocr_value,
            max_pages=settings.ocr_max_pages,
            llm_runtime_config=runtime_config,
            engine_preference=settings.ocr_engine_preference,
        ),
    )
    visual_pages = build_pdf_visual_assets(content, max_pages=3) if include_visuals else []
    if include_visuals:
        visual_pages = _merge_visual_pages_with_fallback(visual_pages, getattr(pdf_result, "metadata", {}))
    extraction = extract_document_with_options(
        pdf_result=pdf_result,
        prompt_file_name=prompt_name,
        prompt_text=prompt_override,
        use_alias_active=use_alias,
        use_rule_active=use_rule,
        alias_active_override=alias_active,
        rule_active_override=rule_active,
        llm_runtime_config=runtime_config,
        focus_fields=focus_field_list,
        priority_fields=priority_field_list,
    )
    pdf_result, extraction = _maybe_retry_document_with_ocr(
        file_name=file_name,
        content=content,
        base_pdf_result=pdf_result,
        base_extraction=extraction,
        runtime_config=runtime_config,
        ocr_enabled=ocr_enabled,
        force_ocr_value=force_ocr_value,
        prompt_name=prompt_name,
        prompt_override=prompt_override,
        use_alias=use_alias,
        use_rule=use_rule,
        alias_active=alias_active,
        rule_active=rule_active,
        focus_field_list=focus_field_list,
    )
    return _build_document_payload(
        pdf_result.model_dump(),
        extraction.model_dump(),
        alias_active,
        rule_active,
        alias_candidates,
        rule_candidates,
        visual_pages,
    )



def _payload_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dumped = getattr(value, 'model_dump', None)
    if callable(dumped):
        payload = dumped()
        return payload if isinstance(payload, dict) else {}
    return {}


def _payload_metadata(value: Any) -> dict[str, Any]:
    metadata = getattr(value, 'metadata', None)
    if isinstance(metadata, dict):
        return metadata
    return _payload_dict(value).get('metadata', {}) if isinstance(_payload_dict(value).get('metadata', {}), dict) else {}


def _payload_structured_data(value: Any) -> dict[str, Any]:
    structured = getattr(value, 'structured_data', None)
    if isinstance(structured, dict):
        return structured
    return _payload_dict(value).get('structured_data', {}) if isinstance(_payload_dict(value).get('structured_data', {}), dict) else {}

def _maybe_retry_document_with_ocr(
    *,
    file_name: str,
    content: bytes,
    base_pdf_result: Any,
    base_extraction: Any,
    runtime_config: LLMRuntimeConfig,
    ocr_enabled: bool,
    force_ocr_value: bool,
    prompt_name: str,
    prompt_override: str | None,
    use_alias: bool,
    use_rule: bool,
    alias_active: Any,
    rule_active: list[dict[str, Any]],
    focus_field_list: list[str],
):
    if not _should_retry_with_ocr(base_pdf_result, base_extraction, ocr_enabled, force_ocr_value, focus_field_list):
        return base_pdf_result, base_extraction

    retried_pdf_result = extract_pdf_text(
        file_name,
        content,
        ocr_config=OCRRunConfig(
            enabled=ocr_enabled,
            force_ocr=True,
            max_pages=settings.ocr_max_pages,
            llm_runtime_config=runtime_config,
            engine_preference=settings.ocr_engine_preference,
        ),
    )
    retried_extraction = extract_document_with_options(
        pdf_result=retried_pdf_result,
        prompt_file_name=prompt_name,
        prompt_text=prompt_override,
        use_alias_active=use_alias,
        use_rule_active=use_rule,
        alias_active_override=alias_active,
        rule_active_override=rule_active,
        llm_runtime_config=runtime_config,
        focus_fields=focus_field_list,
    )

    base_score = _extraction_quality_score(base_extraction)
    retried_score = _extraction_quality_score(retried_extraction)
    retry_applied = str(_payload_metadata(retried_pdf_result).get('ocr_status', '')) == 'applied'

    if retry_applied and retried_score > base_score:
        return _annotate_ocr_retry(
            retried_pdf_result,
            retried_extraction,
            attempted=True,
            selected=True,
            base_score=base_score,
            retried_score=retried_score,
            reason='Focused fields were still missing after standard text extraction, so OCR fallback was retried and produced a better result.',
        )

    return _annotate_ocr_retry(
        base_pdf_result,
        base_extraction,
        attempted=True,
        selected=False,
        base_score=base_score,
        retried_score=retried_score,
        reason='Focused fields were still missing after standard text extraction, so OCR fallback was retried but did not improve the result.',
    )


def _should_retry_with_ocr(
    pdf_result: Any,
    extraction: Any,
    ocr_enabled: bool,
    force_ocr_value: bool,
    focus_field_list: list[str],
) -> bool:
    if not ocr_enabled or force_ocr_value:
        return False
    metadata = _payload_metadata(pdf_result) if pdf_result is not None else {}
    if str(metadata.get('source_kind', '')) != 'digital_text':
        return False
    if str(metadata.get('ocr_status', '')) == 'applied':
        return False
    structured = _payload_structured_data(extraction) if extraction is not None else {}
    missing_fields = {str(item) for item in (structured.get('missing_fields', []) or []) if str(item).strip()}
    uncertain_fields = {str(item) for item in (structured.get('uncertain_fields', []) or []) if str(item).strip()}
    focus_fields = [str(item).strip() for item in (focus_field_list or []) if str(item).strip()]
    if focus_fields:
        return any(field in missing_fields or field in uncertain_fields for field in focus_fields)
    return bool(missing_fields or uncertain_fields)


def _extraction_quality_score(extraction: Any) -> tuple[int, int, int]:
    structured = _payload_structured_data(extraction) if extraction is not None else {}
    mapped_count = len(structured.get('mapped_fields', []) or [])
    missing_count = len(structured.get('missing_fields', []) or [])
    uncertain_count = len(structured.get('uncertain_fields', []) or [])
    return (mapped_count, -missing_count, -uncertain_count)


def _annotate_ocr_retry(
    pdf_result: Any,
    extraction: Any,
    *,
    attempted: bool,
    selected: bool,
    base_score: tuple[int, int, int],
    retried_score: tuple[int, int, int],
    reason: str,
):
    retry_note = {
        'attempted': attempted,
        'selected': selected,
        'base_score': list(base_score),
        'retried_score': list(retried_score),
        'reason': reason,
    }

    if hasattr(pdf_result, 'model_copy'):
        pdf_result = pdf_result.model_copy(deep=True)
        pdf_meta = getattr(pdf_result, 'metadata', None)
        if isinstance(pdf_meta, dict):
            pdf_meta['ocr_retry'] = retry_note
    elif hasattr(pdf_result, '_payload') and isinstance(getattr(pdf_result, '_payload', None), dict):
        pdf_result._payload.setdefault('metadata', {})['ocr_retry'] = retry_note

    if hasattr(extraction, 'model_copy'):
        extraction = extraction.model_copy(deep=True)
        extraction_meta = getattr(extraction, 'metadata', None)
        if isinstance(extraction_meta, dict):
            extraction_meta['ocr_retry'] = retry_note
            sequence = extraction_meta.get('identification_sequence')
            if isinstance(sequence, list):
                sequence.append('ocr_retry_selected' if selected else 'ocr_retry_not_selected')
        warnings = getattr(extraction, 'warnings', None)
        if isinstance(warnings, list):
            warnings.append(reason)
    elif hasattr(extraction, '_payload') and isinstance(getattr(extraction, '_payload', None), dict):
        extraction._payload.setdefault('metadata', {})['ocr_retry'] = retry_note
        sequence = extraction._payload['metadata'].get('identification_sequence')
        if isinstance(sequence, list):
            sequence.append('ocr_retry_selected' if selected else 'ocr_retry_not_selected')
        extraction._payload.setdefault('warnings', []).append(reason)
    return pdf_result, extraction


@router.get("/compare", response_class=HTMLResponse)
@router.get("/foundation", response_class=HTMLResponse)
def foundation_page() -> str:
    index_path = _frontend_index_path()
    if index_path.exists():
        return _decorate_frontend_html(index_path.read_text(encoding="utf-8"))
    return _frontend_placeholder_html()


@router.get("/document-foundation/ui-config")
def document_foundation_ui_config() -> dict[str, Any]:
    prompt_name, prompt_text = _default_prompt_context()
    default_focus_fields = [field for field, level in STANDARD_FIELD_LEVELS.items() if int(level or 2) == 1]
    return {
        "prompt_text": prompt_text,
        "prompt_file_name": prompt_name,
        "llm_base_url": settings.llm_base_url or "",
        "llm_model": "deepseek-chat",
        "ocr_model": settings.ocr_model or "deepseek-chat",
        "llm_timeout": settings.llm_timeout,
        "use_alias_active": False,
        "use_rule_active": True,
        "enable_ocr": True,
        "force_ocr": True,
        "focus_fields": default_focus_fields,
        "focus_labels": STANDARD_FIELD_LABELS,
        "field_levels": STANDARD_FIELD_LEVELS,
        "model_options": [
            {"value": "deepseek-chat", "label": "DeepSeek Chat"},
            {"value": "deepseek-reasoner", "label": "DeepSeek Reasoner"},
        ],
    }


def _frontend_index_path() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend_dist" / "index.html"


def _decorate_frontend_html(html: str) -> str:
    title = "\u6279\u91cf\u6838\u5fc3\u5b57\u6bb5\u63d0\u53d6\u9a8c\u8bc1\u5668"
    button = "\u5f00\u59cb\u6279\u91cf\u63d0\u53d6\u9a8c\u8bc1"
    loading = "\u6b63\u5728\u52a0\u8f7d\u9875\u9762..."
    html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", html, count=1, flags=re.S)
    html = re.sub(r"(<h1[^>]*>).*?(</h1>)", rf"\1{title}\2", html, count=1, flags=re.S)
    html = re.sub(r"(<p[^>]*>).*?(</p>)", rf"\1{loading}\2", html, count=1, flags=re.S)
    html = re.sub(r"(<button[^>]*>).*?(</button>)", rf"\1{button}\2", html, count=1, flags=re.S)
    marker = f"<!-- {title} | {button} -->"
    return marker + html


def _frontend_placeholder_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>批量核心字段提取验证器</title>
</head>
<body>
<main style="max-width:1180px;margin:0 auto;padding:28px 18px 48px;font-family:'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif">
<section style="background:#fffdf8;border:1px solid #d8cfc2;border-radius:24px;padding:24px">
<h1>批量核心字段提取验证器</h1>
<p>正在加载最新页面，请稍候...</p>
<button type="button">页面加载中</button>
</section>
</main>
</body>
</html>"""


@router.post("/document-foundation/validate")
async def document_foundation_validate(
    files: list[UploadFile] | None = File(default=None),
    prompt_text: str = Form(""),
    prompt_file_name: str = Form(""),
    llm_api_key: str = Form(""),
    llm_base_url: str = Form(""),
    llm_model: str = Form(""),
    ocr_model: str = Form(""),
    llm_timeout: str = Form(""),
    use_alias_active: str = Form("true"),
    use_rule_active: str = Form("true"),
    enable_ocr: str = Form("true"),
    force_ocr: str = Form("false"),
    focus_fields: str = Form(""),
    priority_fields: str = Form(""),
    include_visual_assets: str = Form("true"),
) -> JSONResponse:
    options = _build_validation_options(
        prompt_text=prompt_text,
        prompt_file_name=prompt_file_name,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        ocr_model=ocr_model,
        llm_timeout=llm_timeout,
        use_alias_active=use_alias_active,
        use_rule_active=use_rule_active,
        enable_ocr=enable_ocr,
        force_ocr=force_ocr,
        focus_fields=focus_fields,
        priority_fields=priority_fields,
        include_visual_assets=include_visual_assets,
    )
    uploads_with_content = await _read_uploaded_files(files or [])
    payload = await _run_validation_batch(uploads_with_content, options)
    return JSONResponse(payload)


@router.post("/document-foundation/validate-async")
async def document_foundation_validate_async(
    files: list[UploadFile] | None = File(default=None),
    prompt_text: str = Form(""),
    prompt_file_name: str = Form(""),
    llm_api_key: str = Form(""),
    llm_base_url: str = Form(""),
    llm_model: str = Form(""),
    ocr_model: str = Form(""),
    llm_timeout: str = Form(""),
    use_alias_active: str = Form("true"),
    use_rule_active: str = Form("true"),
    enable_ocr: str = Form("true"),
    force_ocr: str = Form("false"),
    focus_fields: str = Form(""),
    priority_fields: str = Form(""),
    include_visual_assets: str = Form("true"),
) -> JSONResponse:
    options = _build_validation_options(
        prompt_text=prompt_text,
        prompt_file_name=prompt_file_name,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        ocr_model=ocr_model,
        llm_timeout=llm_timeout,
        use_alias_active=use_alias_active,
        use_rule_active=use_rule_active,
        enable_ocr=enable_ocr,
        force_ocr=force_ocr,
        focus_fields=focus_fields,
        priority_fields=priority_fields,
        include_visual_assets=include_visual_assets,
    )
    uploads_with_content = await _read_uploaded_files(files or [])
    job_id = uuid4().hex
    VALIDATION_JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "created_at": __import__('time').time(),
        "options": options,
        "file_statuses": [{"filename": name, "status": "queued", "error": ""} for name, _ in uploads_with_content],
        "documents": [],
        "result": None,
        "error": "",
    }
    asyncio.create_task(_run_validation_job(job_id, uploads_with_content, options))
    return JSONResponse({
        "job_id": job_id,
        "status": "queued",
        "status_url": f"/api/v1/document-foundation/validate-status/{job_id}",
        "total_documents": len(uploads_with_content),
    })


@router.get("/document-foundation/validate-status/{job_id}")
async def document_foundation_validate_status(job_id: str) -> JSONResponse:
    job = VALIDATION_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="未找到对应的验证任务。")
    partial_documents = list(job.get("documents", []))
    partial_response = _build_partial_response(partial_documents, job.get("options", {})) if partial_documents else None
    return JSONResponse({
        "job_id": job_id,
        "status": job.get("status", "queued"),
        "file_statuses": job.get("file_statuses", []),
        "completed_documents": len(partial_documents),
        "total_documents": len(job.get("file_statuses", [])),
        "partial_response": partial_response,
        "result": job.get("result"),
        "error": job.get("error", ""),
    })


def _build_validation_options(
    prompt_text: str,
    prompt_file_name: str,
    llm_api_key: str,
    llm_base_url: str,
    llm_model: str,
    ocr_model: str,
    llm_timeout: str,
    use_alias_active: str,
    use_rule_active: str,
    enable_ocr: str,
    force_ocr: str,
    focus_fields: str,
    priority_fields: str,
    include_visual_assets: str,
) -> dict[str, Any]:
    timeout_value = int((llm_timeout or "").strip() or settings.llm_timeout)
    runtime_config = LLMRuntimeConfig(
        api_key=_sanitize_runtime_api_key((llm_api_key or "").strip()) or _sanitize_runtime_api_key(settings.llm_api_key),
        base_url=(llm_base_url or "").strip() or settings.llm_base_url,
        model=(llm_model or "").strip() or settings.llm_model,
        timeout=timeout_value,
        ocr_model=(ocr_model or "").strip() or settings.ocr_model or (llm_model or "").strip() or settings.llm_model,
    )
    if not (runtime_config.api_key or "").strip():
        raise HTTPException(status_code=400, detail="缺少可用的 DeepSeek API Key，请在页面填写或配置 AUDIT_LLM_API_KEY。")
    use_alias = _parse_bool(use_alias_active)
    use_rule = _parse_bool(use_rule_active)
    ocr_enabled = _parse_bool(enable_ocr)
    force_ocr_value = _parse_bool(force_ocr)
    focus_field_list = _parse_focus_fields(focus_fields)
    priority_field_list = _parse_priority_fields(priority_fields)
    include_visuals = _parse_bool(include_visual_assets) and bool(settings.validation_include_visual_assets)
    prompt_name = (prompt_file_name or "").strip() or _default_prompt_context()[0]
    prompt_override = prompt_text.strip() or None
    alias_active = load_knowledge_file(KNOWLEDGE_DIR / "alias_active.json") if use_alias else {}
    alias_candidates = _normalize_alias_candidates(load_knowledge_file(KNOWLEDGE_DIR / "alias_candidates.json"))
    rule_active = _normalize_rule_items(load_knowledge_file(KNOWLEDGE_DIR / "rule_active.json")) if use_rule else []
    rule_candidates = _normalize_rule_items(load_knowledge_file(KNOWLEDGE_DIR / "rule_candidates.json"))
    return {
        "runtime_config": runtime_config,
        "use_alias": use_alias,
        "use_rule": use_rule,
        "ocr_enabled": ocr_enabled,
        "force_ocr_value": force_ocr_value,
        "focus_field_list": focus_field_list,
        "priority_field_list": priority_field_list,
        "include_visuals": include_visuals,
        "prompt_name": prompt_name,
        "prompt_override": prompt_override,
        "alias_active": alias_active,
        "alias_candidates": alias_candidates,
        "rule_active": rule_active,
        "rule_candidates": rule_candidates,
    }


async def _read_uploaded_files(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个 PDF 文件。")
    uploads_with_content: list[tuple[str, bytes]] = []
    for upload in files:
        _validate_pdf_upload(upload)
        uploads_with_content.append((upload.filename or "document.pdf", await upload.read()))
    return uploads_with_content


async def _run_validation_job(job_id: str, uploads_with_content: list[tuple[str, bytes]], options: dict[str, Any]) -> None:
    job = VALIDATION_JOBS[job_id]
    job["status"] = "processing"
    try:
        result = await _run_validation_batch(uploads_with_content, options, progress_job_id=job_id)
        job["status"] = "completed"
        job["result"] = result
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)


async def _run_validation_batch(
    uploads_with_content: list[tuple[str, bytes]],
    options: dict[str, Any],
    progress_job_id: str | None = None,
) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(max(1, int(settings.validation_max_parallel or 1)))

    include_visuals_for_batch = bool(options["include_visuals"])

    async def run_single(index: int, file_name: str, content: bytes):
        if progress_job_id and progress_job_id in VALIDATION_JOBS:
            status_entry = VALIDATION_JOBS[progress_job_id]["file_statuses"][index]
            status_entry["status"] = "processing"
            status_entry["detail"] = "\u6b63\u5728\u63d0\u53d6\u6587\u672c\uff0c\u5e76\u4f18\u5148\u53c2\u8003\u5df2\u786e\u8ba4\u8fc7\u7684\u5e38\u7528\u5b57\u6bb5\u5199\u6cd5"
        try:
            document = await asyncio.to_thread(
                _process_uploaded_document,
                file_name,
                content,
                options["runtime_config"],
                options["ocr_enabled"],
                options["force_ocr_value"],
                options["prompt_name"],
                options["prompt_override"],
                options["use_alias"],
                options["use_rule"],
                options["alias_active"],
                options["rule_active"],
                options["alias_candidates"],
                options["rule_candidates"],
                include_visuals_for_batch,
                options["focus_field_list"],
                options["priority_field_list"],
            )
            return index, document, None
        except Exception as exc:
            return index, None, str(exc)

    tasks = []
    for index, (file_name, content) in enumerate(uploads_with_content):
        async def guarded(idx=index, name=file_name, blob=content):
            async with semaphore:
                return await run_single(idx, name, blob)
        tasks.append(asyncio.create_task(guarded()))

    documents_by_index: dict[int, dict[str, Any]] = {}
    errors: list[str] = []
    for task in asyncio.as_completed(tasks):
        index, document, error = await task
        file_name = uploads_with_content[index][0]
        if progress_job_id and progress_job_id in VALIDATION_JOBS:
            status_entry = VALIDATION_JOBS[progress_job_id]["file_statuses"][index]
            if error:
                status_entry["status"] = "failed"
                status_entry["error"] = error
                status_entry["detail"] = _describe_processing_failure(error)
            else:
                status_entry["status"] = "done"
                status_entry["detail"] = _describe_extraction_marker(document)
        if error:
            errors.append(f"{file_name}: {error}")
            continue
        documents_by_index[index] = document
        if progress_job_id and progress_job_id in VALIDATION_JOBS:
            ordered_partial = [documents_by_index[i] for i in sorted(documents_by_index)]
            VALIDATION_JOBS[progress_job_id]["documents"] = ordered_partial

    documents = [documents_by_index[i] for i in sorted(documents_by_index)]
    payload = _build_validation_payload(documents, options)
    if errors:
        payload["batch_summary"]["failed_documents"] = len(errors)
        payload["batch_summary"]["failed_items"] = errors
    return payload


def _describe_extraction_marker(document: dict[str, Any]) -> str:
    extraction_meta = document.get("extraction_metadata", {}) if isinstance(document, dict) else {}
    decision_mode = str(extraction_meta.get("decision_mode", "")) if isinstance(extraction_meta, dict) else ""
    raw = document.get("raw_text_result", {}) if isinstance(document, dict) else {}
    meta = raw.get("metadata", {}) if isinstance(raw, dict) else {}
    source_kind = str(meta.get("source_kind", ""))
    ocr_status = str(meta.get("ocr_status", ""))
    ocr_engine = str(meta.get("ocr_engine", ""))
    if source_kind == "scan_ocr" and ocr_status == "applied":
        if ocr_engine == "paddleocr":
            return "标准文本失败后转百度 PaddleOCR · alias 快速定位" if decision_mode == "alias_fast_path" else "标准文本失败后转百度 PaddleOCR"
        return "标准文本失败后转大模型 OCR · alias 快速定位" if decision_mode == "alias_fast_path" else "标准文本失败后转大模型 OCR"
    if source_kind == "scan_like" and ocr_status == "failed":
        return "OCR \u5931\u8d25"
    if decision_mode == "alias_fast_path":
        return "\u6807\u51c6\u6587\u672c\u63d0\u53d6 \u00b7 alias \u5feb\u901f\u5b9a\u4f4d"
    if source_kind == "scan_like":
        return "\u626b\u63cf\u4ef6 \u00b7 \u5f85OCR"
    return "\u6807\u51c6\u6587\u672c\u63d0\u53d6"


def _describe_processing_failure(error: str) -> str:
    message = str(error or "").strip()
    lowered = message.lower()
    if not message:
        return "\u5904\u7406\u5931\u8d25"
    if "ocr" in lowered:
        return "\u626b\u63cf\u4ef6 OCR \u672a\u6210\u529f"
    if "timeout" in lowered or "\u8d85\u65f6" in message:
        return "\u8bc6\u522b\u8d85\u65f6\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5"
    if "pdf" in lowered:
        return "PDF \u89e3\u6790\u5931\u8d25"
    return message[:60]


def _build_partial_response(documents: list[dict[str, Any]], options: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_options": {
            "prompt_file_name": options["prompt_name"],
            "use_alias_active": options["use_alias"],
            "use_rule_active": options["use_rule"],
            "enable_ocr": options["ocr_enabled"],
            "force_ocr": options["force_ocr_value"],
            "focus_fields": options["focus_field_list"],
            "priority_fields": options["priority_field_list"],
            "include_visual_assets": options["include_visuals"],
            "max_parallel": int(settings.validation_max_parallel or 1),
        },
        "knowledge_summary": {
            "active_alias_field_count": len(options["alias_active"]),
            "active_rule_count": len(options["rule_active"]),
            "candidate_alias_count": len(options["alias_candidates"]),
            "candidate_rule_count": len(options["rule_candidates"]),
        },
        "batch_summary": _build_batch_summary(documents),
        "version_record": _build_version_record(options["prompt_name"], options["use_alias"], options["use_rule"], options["alias_active"], options["rule_active"], options["runtime_config"], options["ocr_enabled"], options["force_ocr_value"]),
        "experiment_record": {"run_dir": "", "previous_run_dir": "", "db_run_id": 0},
        "comparison_summary": {"has_previous": False},
        "documents": documents,
    }


def _build_validation_payload(documents: list[dict[str, Any]], options: dict[str, Any]) -> dict[str, Any]:
    batch_summary = _build_batch_summary(documents)
    version_record = _build_version_record(options["prompt_name"], options["use_alias"], options["use_rule"], options["alias_active"], options["rule_active"], options["runtime_config"], options["ocr_enabled"], options["force_ocr_value"])
    experiment_record = _save_batch_run(batch_summary, version_record, documents)
    comparison_summary = _build_comparison_summary(batch_summary, experiment_record)
    return {
        "run_options": {
            "prompt_file_name": options["prompt_name"],
            "use_alias_active": options["use_alias"],
            "use_rule_active": options["use_rule"],
            "enable_ocr": options["ocr_enabled"],
            "force_ocr": options["force_ocr_value"],
            "focus_fields": options["focus_field_list"],
            "priority_fields": options["priority_field_list"],
            "include_visual_assets": options["include_visuals"],
            "max_parallel": int(settings.validation_max_parallel or 1),
        },
        "knowledge_summary": {
            "active_alias_field_count": len(options["alias_active"]),
            "active_rule_count": len(options["rule_active"]),
            "candidate_alias_count": len(options["alias_candidates"]),
            "candidate_rule_count": len(options["rule_candidates"]),
        },
        "batch_summary": batch_summary,
        "version_record": version_record,
        "experiment_record": experiment_record,
        "comparison_summary": comparison_summary,
        "documents": documents,
    }


@router.post("/document-foundation/evaluate")
async def document_foundation_evaluate(payload: dict[str, Any] = Body(...)) -> JSONResponse:
    documents = payload.get("documents", [])
    if not isinstance(documents, list) or not documents:
        raise HTTPException(status_code=400, detail="è¯·è³å°ä¸ä¼ ä¸ä¸ª PDF æä»¶ã")
    experiment_record = payload.get("experiment_record", {}) if isinstance(payload.get("experiment_record", {}), dict) else {}
    experiment_record["documents_payload"] = documents
    evaluation_summary = _build_evaluation_summary(documents)
    evaluation_record = _save_confirmed_evaluation(experiment_record, evaluation_summary)
    evolution_summary = record_evolution_cycle(
        documents=documents,
        experiment_record=experiment_record,
        evaluation_summary=evaluation_summary,
        evaluation_record=evaluation_record,
    )
    evaluation_comparison = _build_evaluation_comparison(evaluation_summary, evaluation_record)
    return JSONResponse({
        "evaluation_summary": evaluation_summary,
        "evaluation_record": evaluation_record,
        "evaluation_comparison": evaluation_comparison,
        "evolution_summary": evolution_summary,
    })


def _default_prompt_context() -> tuple[str, str]:
    prompt_refs = list_prompt_versions()
    preferred_order = ["extract_prompt_v1.txt", "extract_prompt.txt"]
    prompt_by_name = {prompt.name: prompt for prompt in prompt_refs}
    for name in preferred_order:
        prompt = prompt_by_name.get(name)
        if prompt:
            return prompt.name, prompt.read_text(encoding="utf-8")
    prompt = prompt_refs[0]
    return prompt.name, prompt.read_text(encoding="utf-8")


def _parse_bool(value: str | bool) -> bool:
    return value if isinstance(value, bool) else str(value).strip().lower() in {"1", "true", "yes", "on"}


def _validate_pdf_upload(upload: UploadFile) -> None:
    filename = upload.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail=f"{escape(filename)} is not a PDF file.")


def _normalize_alias_candidates(raw: Any) -> list[dict[str, str]]:
    if isinstance(raw, list):
        return [
            {
                "standard_field": str(item.get("standard_field", "")),
                "alias": str(item.get("alias", "")),
                "reason": str(item.get("source", item.get("reason", "\u5019\u9009 alias"))),
            }
            for item in raw
            if isinstance(item, dict)
        ]
    if isinstance(raw, dict):
        return [
            {
                "standard_field": str(field),
                "alias": str(alias),
                "reason": "\u5019\u9009 alias",
            }
            for field, aliases in raw.items()
            for alias in (aliases or [])
        ]
    return []

def _normalize_rule_items(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    return [{"name": str(i.get("name", "")), "field": str(i.get("field", i.get("applicable_field", ""))), "description": str(i.get("description", i.get("content", ""))), "rule_type": str(i.get("rule_type", i.get("type", "")))} for i in raw if isinstance(i, dict)]


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _build_document_payload(pdf_result: dict[str, Any], extraction: dict[str, Any], alias_active: dict[str, list[str]], active_rules: list[dict[str, str]], alias_pool: list[dict[str, str]], rule_pool: list[dict[str, str]], visual_pages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    structured = extraction.get("structured_data", {})
    mapped = structured.get("mapped_fields", [])
    missing = structured.get("missing_fields", [])
    uncertain = structured.get("uncertain_fields", [])
    return {
        "filename": pdf_result.get("file_name", extraction.get("file_name", "document.pdf")),
        "doc_type": structured.get("doc_type", ""),
        "raw_summary": structured.get("raw_summary", ""),
        "raw_model_response": extraction.get("raw_model_response", ""),
        "extraction_metadata": extraction.get("metadata", {}),
        "warnings": [*pdf_result.get("warnings", []), *extraction.get("warnings", [])],
        "raw_text_result": {"text": pdf_result.get("text", ""), "page_count": pdf_result.get("page_count", 0), "extraction_method": pdf_result.get("extraction_method", ""), "is_text_valid": pdf_result.get("is_text_valid", False), "metadata": pdf_result.get("metadata", {})},
        "core_field_count": len(mapped),
        "core_fields": [{"source_field_name": item.get("source_field_name") or item.get("standard_field") or "", "source_value": item.get("source_value") or "", "confidence": item.get("confidence", 0), "reason": item.get("reason", "")} for item in mapped],
        "standard_mappings": [{"standard_field": item.get("standard_field", ""), "standard_label_cn": item.get("standard_label_cn") or STANDARD_FIELD_LABELS.get(item.get("standard_field", ""), item.get("standard_field", "")), "source_field_name": item.get("source_field_name") or "", "source_value": item.get("source_value") or "", "confidence": item.get("confidence", 0), "reason": item.get("reason", ""), "uncertain": item.get("uncertain", False)} for item in mapped],
        "missing_fields": missing,
        "uncertain_fields": uncertain,
        "alias_hits": _collect_alias_hits(mapped, alias_active),
        "rule_hits": _collect_rule_hits(mapped, missing, uncertain, active_rules),
        "alias_candidates": _collect_alias_candidates(mapped, missing, uncertain, alias_active, alias_pool),
        "rule_candidates": _collect_rule_candidates(missing, uncertain, rule_pool),
        "manual_confirmation_rows": _build_manual_rows(mapped, missing, uncertain),
        "visual_pages": visual_pages or [],
    }


def _collect_alias_hits(mapped: list[dict[str, Any]], alias_active: dict[str, list[str]]) -> list[dict[str, str]]:
    hits = []
    for item in mapped:
        field_name = str(item.get("standard_field", ""))
        source_name = str(item.get("source_field_name", "") or "")
        if not field_name or not source_name:
            continue
        for alias in alias_active.get(field_name, []):
            if _normalize_text(alias) == _normalize_text(source_name):
                hits.append({"standard_field": field_name, "alias": alias, "source_field_name": source_name})
                break
    return hits


def _collect_rule_hits(mapped: list[dict[str, Any]], missing: list[str], uncertain: list[str], rules: list[dict[str, str]]) -> list[dict[str, str]]:
    fields = {str(item.get("standard_field", "")) for item in mapped if item.get("standard_field")}
    hits = []
    for rule in rules:
        field_name = rule.get("field", "")
        if field_name and field_name in fields:
            reason = "\u8be5\u5b57\u6bb5\u547d\u4e2d\u4e86\u751f\u6548\u89c4\u5219"
        elif field_name and field_name in missing:
            reason = "\u8be5\u5b57\u6bb5\u7f3a\u5931\uff0c\u5efa\u8bae\u8865\u5145\u89c4\u5219"
        elif field_name and field_name in uncertain:
            reason = "\u8be5\u5b57\u6bb5\u7ed3\u679c\u4e0d\u7a33\u5b9a\uff0c\u5efa\u8bae\u8865\u5145\u89c4\u5219"
        elif not field_name and (fields or missing or uncertain):
            reason = "\u5f53\u524d\u6587\u6863\u547d\u4e2d\u4e86\u5168\u5c40\u89c4\u5219"
        else:
            continue
        hits.append({"name": rule.get("name", ""), "field": field_name or "global", "reason": reason})
    return hits

def _collect_alias_candidates(mapped: list[dict[str, Any]], missing: list[str], uncertain: list[str], alias_active: dict[str, list[str]], alias_pool: list[dict[str, str]]) -> list[dict[str, str]]:
    results = []
    for item in mapped:
        field_name = str(item.get("standard_field", ""))
        source_name = str(item.get("source_field_name", "") or "")
        active_aliases = {_normalize_text(alias) for alias in alias_active.get(field_name, [])}
        if field_name and source_name and _normalize_text(source_name) not in active_aliases:
            results.append({
                "standard_field": field_name,
                "alias": source_name,
                "reason": "????????????????????",
            })
    return _dedupe(results, ("standard_field", "alias"))

def _collect_rule_candidates(missing: list[str], uncertain: list[str], rule_pool: list[dict[str, str]]) -> list[dict[str, str]]:
    results = [{"name": f"missing_{field}", "field": field, "reason": "\u8be5\u5b57\u6bb5\u7f3a\u5931\uff0c\u5efa\u8bae\u8865\u5145\u89c4\u5219"} for field in missing]
    results.extend([{"name": f"uncertain_{field}", "field": field, "reason": "\u8be5\u5b57\u6bb5\u7ed3\u679c\u4e0d\u7a33\u5b9a\uff0c\u5efa\u8bae\u8865\u5145\u89c4\u5219"} for field in uncertain])
    results.extend([{"name": item.get("name", ""), "field": item.get("field", "global"), "reason": item.get("description", "\u89c4\u5219\u5019\u9009") } for item in rule_pool if not item.get("field") or item.get("field") in (set(missing) | set(uncertain))])
    return _dedupe(results, ("name", "field"))

def _build_manual_rows(mapped: list[dict[str, Any]], missing: list[str], uncertain: list[str]) -> list[dict[str, str]]:
    rows, seen = [], set()
    for item in mapped:
        field_name = str(item.get("standard_field", ""))
        if not field_name or field_name in seen:
            continue
        seen.add(field_name)
        value = str(item.get("source_value", "") or "")
        rows.append({"standard_field": field_name, "standard_label_cn": item.get("standard_label_cn") or STANDARD_FIELD_LABELS.get(field_name, field_name), "ai_value": value, "confirmed_value": value, "promote_alias": False})
    for field_name in [*missing, *uncertain]:
        if field_name not in seen:
            seen.add(field_name)
            rows.append({"standard_field": field_name, "standard_label_cn": STANDARD_FIELD_LABELS.get(field_name, field_name), "ai_value": "", "confirmed_value": "", "promote_alias": False})
    return rows


def _build_batch_summary(documents: list[dict[str, Any]]) -> dict[str, Any]:
    total_documents = len(documents)
    text_valid_documents = sum(1 for doc in documents if doc.get("raw_text_result", {}).get("is_text_valid"))
    mapped_documents = sum(1 for doc in documents if doc.get("core_field_count", 0) > 0)
    total_mapped_fields = sum(doc.get("core_field_count", 0) for doc in documents)
    field_buckets: dict[str, dict[str, Any]] = {}
    doc_type_buckets: dict[str, dict[str, Any]] = {}
    extraction_buckets: dict[str, dict[str, Any]] = {}
    boundary_documents: list[dict[str, Any]] = []
    for doc in documents:
        mapped_fields = {item.get("standard_field", "") for item in doc.get("standard_mappings", []) if item.get("standard_field")}
        missing_fields = set(doc.get("missing_fields", []))
        uncertain_fields = set(doc.get("uncertain_fields", []))
        doc_type = doc.get("doc_type") or "unknown"
        extraction_method = doc.get("raw_text_result", {}).get("extraction_method") or "unknown"
        doc_type_bucket = doc_type_buckets.setdefault(doc_type, {"doc_type": doc_type, "documents": 0, "mapped_documents": 0, "avg_fields_per_document": 0.0})
        extraction_bucket = extraction_buckets.setdefault(extraction_method, {"extraction_method": extraction_method, "documents": 0, "text_valid_documents": 0, "avg_fields_per_document": 0.0})
        doc_type_bucket["documents"] += 1
        extraction_bucket["documents"] += 1
        if doc.get("core_field_count", 0) > 0:
            doc_type_bucket["mapped_documents"] += 1
        if doc.get("raw_text_result", {}).get("is_text_valid"):
            extraction_bucket["text_valid_documents"] += 1
        doc_type_bucket["avg_fields_per_document"] += doc.get("core_field_count", 0)
        extraction_bucket["avg_fields_per_document"] += doc.get("core_field_count", 0)
        if (not doc.get("raw_text_result", {}).get("is_text_valid")) or len(uncertain_fields) >= 2 or len(missing_fields) >= 3:
            boundary_documents.append({
                "filename": doc.get("filename", ""),
                "doc_type": doc_type,
                "extraction_method": extraction_method,
                "missing_count": len(missing_fields),
                "uncertain_count": len(uncertain_fields),
            })
        for field_name in mapped_fields | missing_fields | uncertain_fields:
            bucket = field_buckets.setdefault(field_name, {"field": field_name, "mapped_docs": 0, "missing_docs": 0, "uncertain_docs": 0, "coverage_rate": 0.0})
            if field_name in mapped_fields:
                bucket["mapped_docs"] += 1
            if field_name in missing_fields:
                bucket["missing_docs"] += 1
            if field_name in uncertain_fields:
                bucket["uncertain_docs"] += 1
    high_risk_field_count = 0
    for bucket in field_buckets.values():
        bucket["coverage_rate"] = round((bucket["mapped_docs"] / total_documents) * 100, 1) if total_documents else 0.0
        if bucket["missing_docs"] or bucket["uncertain_docs"]:
            high_risk_field_count += 1
    for bucket in doc_type_buckets.values():
        bucket["avg_fields_per_document"] = round(bucket["avg_fields_per_document"] / bucket["documents"], 2) if bucket["documents"] else 0.0
        bucket["coverage_rate"] = round((bucket["mapped_documents"] / bucket["documents"]) * 100, 1) if bucket["documents"] else 0.0
    for bucket in extraction_buckets.values():
        bucket["avg_fields_per_document"] = round(bucket["avg_fields_per_document"] / bucket["documents"], 2) if bucket["documents"] else 0.0
        bucket["text_valid_rate"] = round((bucket["text_valid_documents"] / bucket["documents"]) * 100, 1) if bucket["documents"] else 0.0
    field_stats = sorted(field_buckets.values(), key=lambda item: (-item["uncertain_docs"], -item["missing_docs"], item["field"]))
    doc_type_stats = sorted(doc_type_buckets.values(), key=lambda item: (-item["documents"], item["doc_type"]))
    extraction_stats = sorted(extraction_buckets.values(), key=lambda item: (-item["documents"], item["extraction_method"]))
    boundary_documents.sort(key=lambda item: (-item["uncertain_count"], -item["missing_count"], item["filename"]))
    return {
        "total_documents": total_documents,
        "text_valid_documents": text_valid_documents,
        "document_coverage_rate": round((mapped_documents / total_documents) * 100, 1) if total_documents else 0.0,
        "total_mapped_fields": total_mapped_fields,
        "avg_fields_per_document": round(total_mapped_fields / total_documents, 2) if total_documents else 0.0,
        "high_risk_field_count": high_risk_field_count,
        "field_stats": field_stats,
        "doc_type_stats": doc_type_stats,
        "extraction_stats": extraction_stats,
        "boundary_documents": boundary_documents[:12],
    }


def _build_version_record(prompt_name: str, use_alias: bool, use_rule: bool, alias_active: dict[str, list[str]], rule_active: list[dict[str, str]], runtime_config: LLMRuntimeConfig, ocr_enabled: bool, force_ocr: bool) -> dict[str, Any]:
    return {
        "prompt_file_name": prompt_name,
        "alias_source": "knowledge/alias_active.json" if use_alias else "disabled",
        "rule_source": "knowledge/rule_active.json" if use_rule else "disabled",
        "alias_field_count": len(alias_active),
        "rule_count": len(rule_active),
        "model_name": runtime_config.model,
        "llm_base_url": runtime_config.base_url,
        "timeout_seconds": runtime_config.timeout,
        "ocr_enabled": ocr_enabled,
        "force_ocr": force_ocr,
        "ocr_model": runtime_config.ocr_model or runtime_config.model,
    }


def _save_batch_run(batch_summary: dict[str, Any], version_record: dict[str, Any], documents: list[dict[str, Any]]) -> dict[str, Any]:
    run_dir = create_run_output_dir(BATCH_RUNS_DIR)
    payload = {
        "version_record": version_record,
        "batch_summary": batch_summary,
        "documents": documents,
    }
    save_json(run_dir / "batch_run_summary.json", payload)
    latest_pointer = BATCH_RUNS_DIR / "latest.json"
    previous_run_dir = ""
    if latest_pointer.exists():
        try:
            previous_run_dir = json.loads(latest_pointer.read_text(encoding="utf-8")).get("run_dir", "")
        except Exception:
            previous_run_dir = ""
    save_json(latest_pointer, {"run_dir": str(run_dir)})
    db_record = persist_extraction_run(run_dir.name, str(run_dir), batch_summary, version_record, documents)
    return {"run_dir": str(run_dir), "previous_run_dir": previous_run_dir, "version_record": version_record, **db_record}


def _build_comparison_summary(batch_summary: dict[str, Any], experiment_record: dict[str, Any]) -> dict[str, Any]:
    previous_dir = experiment_record.get("previous_run_dir", "")
    if not previous_dir:
        return {"has_previous": False}
    previous_summary_path = Path(previous_dir) / "batch_run_summary.json"
    if not previous_summary_path.exists():
        return {"has_previous": False}
    try:
        previous_payload = json.loads(previous_summary_path.read_text(encoding="utf-8"))
    except Exception:
        return {"has_previous": False}
    previous_batch = previous_payload.get("batch_summary", {})
    previous_fields = {item.get("field", ""): item for item in previous_batch.get("field_stats", [])}
    current_changes = []
    for item in batch_summary.get("field_stats", []):
        field_name = item.get("field", "")
        previous_item = previous_fields.get(field_name, {})
        current_changes.append(
            {
                "field": field_name,
                "coverage_rate_delta": round(item.get("coverage_rate", 0.0) - previous_item.get("coverage_rate", 0.0), 1),
                "uncertain_delta": int(item.get("uncertain_docs", 0) - previous_item.get("uncertain_docs", 0)),
                "missing_delta": int(item.get("missing_docs", 0) - previous_item.get("missing_docs", 0)),
            }
        )
    current_changes.sort(key=lambda item: (-abs(item["coverage_rate_delta"]), -abs(item["uncertain_delta"]), item["field"]))
    return {
        "has_previous": True,
        "previous_run_dir": previous_dir,
        "document_coverage_rate_delta": round(batch_summary.get("document_coverage_rate", 0.0) - previous_batch.get("document_coverage_rate", 0.0), 1),
        "avg_fields_per_document_delta": round(batch_summary.get("avg_fields_per_document", 0.0) - previous_batch.get("avg_fields_per_document", 0.0), 2),
        "high_risk_field_count_delta": int(batch_summary.get("high_risk_field_count", 0) - previous_batch.get("high_risk_field_count", 0)),
        "field_changes": current_changes[:12],
    }


def _dedupe(items: list[dict[str, str]], keys: tuple[str, ...]) -> list[dict[str, str]]:
    seen, result = set(), []
    for item in items:
        marker = tuple(str(item.get(key, "")) for key in keys)
        if marker not in seen:
            seen.add(marker)
            result.append(item)
    return result

def _build_evaluation_summary(documents: list[dict[str, Any]]) -> dict[str, Any]:
    total_fields = 0
    correct_fields = 0
    wrong_fields = 0
    missing_fields = 0
    empty_fields = 0
    field_buckets: dict[str, dict[str, Any]] = {}
    document_accuracy_stats: list[dict[str, Any]] = []
    for doc in documents:
        rows = doc.get("manual_confirmation_rows", []) or []
        doc_correct = 0
        doc_wrong = 0
        doc_missing = 0
        for row in rows:
            field_name = str(row.get("standard_field", ""))
            ai_norm = normalize_text(row.get("ai_value", ""))
            confirmed_norm = normalize_text(row.get("confirmed_value", ""))
            total_fields += 1
            bucket = field_buckets.setdefault(field_name, {"field": field_name, "correct_count": 0, "wrong_count": 0, "missing_count": 0, "empty_count": 0, "accuracy": 0.0})
            if not ai_norm and not confirmed_norm:
                empty_fields += 1
                bucket["empty_count"] += 1
                continue
            if confirmed_norm and not ai_norm:
                missing_fields += 1
                doc_missing += 1
                bucket["missing_count"] += 1
                continue
            if ai_norm == confirmed_norm:
                correct_fields += 1
                doc_correct += 1
                bucket["correct_count"] += 1
            else:
                wrong_fields += 1
                doc_wrong += 1
                bucket["wrong_count"] += 1
        row_count = len(rows)
        document_accuracy_stats.append({"filename": doc.get("filename", ""), "correct_fields": doc_correct, "wrong_fields": doc_wrong, "missing_fields": doc_missing, "accuracy": round((doc_correct / row_count) * 100, 1) if row_count else 0.0})
    for bucket in field_buckets.values():
        denominator = bucket["correct_count"] + bucket["wrong_count"] + bucket["missing_count"]
        bucket["accuracy"] = round((bucket["correct_count"] / denominator) * 100, 1) if denominator else 0.0
    field_accuracy_stats = sorted(field_buckets.values(), key=lambda item: (item["accuracy"], -item["wrong_count"], item["field"]))
    document_accuracy_stats.sort(key=lambda item: (item["accuracy"], -item["wrong_fields"], item["filename"]))
    denominator = correct_fields + wrong_fields + missing_fields
    return {"total_documents": len(documents), "total_fields": total_fields, "correct_fields": correct_fields, "wrong_fields": wrong_fields, "missing_fields": missing_fields, "empty_fields": empty_fields, "overall_accuracy": round((correct_fields / denominator) * 100, 1) if denominator else 0.0, "field_accuracy_stats": field_accuracy_stats, "document_accuracy_stats": document_accuracy_stats}


def _save_confirmed_evaluation(experiment_record: dict[str, Any], evaluation_summary: dict[str, Any]) -> dict[str, Any]:
    run_dir = experiment_record.get("run_dir", "")
    previous_run_dir = experiment_record.get("previous_run_dir", "")
    if run_dir:
        save_json(Path(run_dir) / "confirmed_evaluation.json", evaluation_summary)
    db_result = apply_manual_confirmations(documents=experiment_record.get("documents_payload", []), run_id=experiment_record.get("db_run_id")) if experiment_record.get("documents_payload") else {"updated_fields": 0, "promoted_aliases": 0, "duplicate_alias_count": 0, "duplicate_aliases": []}
    return {"run_dir": run_dir, "previous_run_dir": previous_run_dir, **db_result}


def _build_evaluation_comparison(evaluation_summary: dict[str, Any], evaluation_record: dict[str, Any]) -> dict[str, Any]:
    previous_run_dir = evaluation_record.get("previous_run_dir", "")
    if not previous_run_dir:
        return {"has_previous": False}
    previous_path = Path(previous_run_dir) / "confirmed_evaluation.json"
    if not previous_path.exists():
        return {"has_previous": False}
    try:
        previous_summary = json.loads(previous_path.read_text(encoding="utf-8"))
    except Exception:
        return {"has_previous": False}
    previous_fields = {item.get("field", ""): item for item in previous_summary.get("field_accuracy_stats", [])}
    field_changes = []
    for item in evaluation_summary.get("field_accuracy_stats", []):
        previous_item = previous_fields.get(item.get("field", ""), {})
        field_changes.append({"field": item.get("field", ""), "accuracy_delta": round(item.get("accuracy", 0.0) - previous_item.get("accuracy", 0.0), 1), "correct_delta": int(item.get("correct_count", 0) - previous_item.get("correct_count", 0)), "wrong_delta": int(item.get("wrong_count", 0) - previous_item.get("wrong_count", 0)), "missing_delta": int(item.get("missing_count", 0) - previous_item.get("missing_count", 0))})
    field_changes.sort(key=lambda item: (-abs(item["accuracy_delta"]), -abs(item["wrong_delta"]), item["field"]))
    return {"has_previous": True, "previous_run_dir": previous_run_dir, "overall_accuracy_delta": round(evaluation_summary.get("overall_accuracy", 0.0) - previous_summary.get("overall_accuracy", 0.0), 1), "correct_fields_delta": int(evaluation_summary.get("correct_fields", 0) - previous_summary.get("correct_fields", 0)), "wrong_fields_delta": int(evaluation_summary.get("wrong_fields", 0) - previous_summary.get("wrong_fields", 0)), "missing_fields_delta": int(evaluation_summary.get("missing_fields", 0) - previous_summary.get("missing_fields", 0)), "field_changes": field_changes[:12]}














