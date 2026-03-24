from __future__ import annotations

import base64
import io
import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import pdfplumber
import requests
from pydantic import BaseModel, Field
from pypdf import PdfReader

from audit_system.config import settings
from llm.client import LLMRuntimeConfig


MIN_VALID_TEXT_LENGTH = 40
logger = logging.getLogger(__name__)
PADDLE_OCR_ASYNC_JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"


class PDFTextResult(BaseModel):
    file_name: str
    text: str
    page_count: int
    extraction_method: str
    is_text_valid: bool
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(slots=True)
class OCRRunConfig:
    enabled: bool = False
    force_ocr: bool = False
    max_pages: int = 3
    llm_runtime_config: LLMRuntimeConfig | None = None
    engine_preference: str = "paddle_only"


def build_pdf_visual_assets(content: bytes, max_pages: int = 3) -> list[dict[str, object]]:
    page_images = _render_pdf_page_images(content, max_pages=max_pages)
    page_words = _extract_pdf_word_boxes(content, max_pages=max_pages)
    assets: list[dict[str, object]] = []
    for page_number in sorted(set(page_images) | set(page_words)):
        page_meta = page_words.get(page_number, {})
        assets.append(
            {
                "page_number": page_number,
                "image_data_url": page_images.get(page_number, ""),
                "page_width": page_meta.get("page_width", 0),
                "page_height": page_meta.get("page_height", 0),
                "words": page_meta.get("words", []),
            }
        )
    return assets


def extract_pdf_text(file_name: str, content: bytes, ocr_config: OCRRunConfig | None = None) -> PDFTextResult:
    pdfplumber_text, pdfplumber_pages, pdfplumber_error = _extract_with_pdfplumber(content)
    pypdf_text = ""
    pypdf_pages = 0
    pypdf_error = None

    if _is_text_usable(pdfplumber_text):
        final_text = pdfplumber_text
        final_page_count = pdfplumber_pages
        extraction_method = "pdfplumber"
        warnings = [message for message in [pdfplumber_error] if message]
    else:
        pypdf_text, pypdf_pages, pypdf_error = _extract_with_pypdf(content)
        warnings = [message for message in [pdfplumber_error, pypdf_error] if message]
        final_text = _pick_longer_text(pdfplumber_text, pypdf_text)
        final_page_count = max(pdfplumber_pages, pypdf_pages)
        extraction_method = "pdfplumber" if len(pdfplumber_text) >= len(pypdf_text) else "pypdf"
        if not _is_text_usable(final_text):
            warnings.append("Base PDF text extraction was weak; system will try DeepSeek first, then fallback to OCR if needed.")

    resolved_ocr = ocr_config or OCRRunConfig()
    remote_ocr_forced = (
        bool(settings.force_remote_ocr_for_all_documents)
        and bool(settings.paddle_ocr_api_token)
    )
    text_was_usable_before_ocr = _is_text_usable(final_text)
    metadata: dict[str, Any] = {
        "fallback_used": not _is_text_usable(pdfplumber_text),
        "pdfplumber_text_length": len(pdfplumber_text.strip()),
        "pypdf_text_length": len(pypdf_text.strip()),
        "ocr_status": "pending" if (resolved_ocr.enabled or remote_ocr_forced) else ("not_needed" if text_was_usable_before_ocr else "suggested"),
        "ocr_engine_preference": "paddle_only",
        "source_kind": "digital_text" if text_was_usable_before_ocr else "scan_like",
        "remote_ocr_forced": remote_ocr_forced,
        "processing_order": ["base_text_extract"],
    }

    should_run_ocr = remote_ocr_forced or (resolved_ocr.enabled and resolved_ocr.force_ocr)
    if should_run_ocr:
        try:
            ocr_text, ocr_page_count, ocr_metadata = _extract_with_paddle_ocr(file_name, content, resolved_ocr)
            metadata.update(ocr_metadata)
            if not _is_text_usable(ocr_text):
                warnings.append("OCR extraction failed: paddleocr returned weak text")
                metadata["ocr_status"] = "failed"
                metadata["processing_order"] = ["base_text_extract", "paddleocr_async_failed"]
            else:
                # Keep digital text and OCR text together so downstream LLM extraction can
                # leverage both clean typed content and OCR-only fragments.
                final_text = _merge_text_sources(final_text, ocr_text)
                final_page_count = ocr_page_count
                extraction_method = (
                    f"{extraction_method}+paddleocr" if extraction_method in {"pdfplumber", "pypdf"} else "paddleocr"
                )
                metadata["ocr_status"] = "applied"
                metadata["ocr_engine"] = "paddleocr"
                metadata["source_kind"] = "scan_ocr"
                metadata["ocr_text_authoritative"] = False
                metadata["hybrid_text_fusion"] = True
                metadata["processing_order"] = ["base_text_extract", "paddleocr_async", "text_fusion"]
        except Exception as exc:
            warnings.append(f"OCR extraction failed: paddleocr failed: {exc}")
            metadata["ocr_status"] = "failed"
            metadata["processing_order"] = ["base_text_extract", "paddleocr_async_failed"]
    else:
        metadata["processing_order"] = ["base_text_extract", "llm_direct"]

    return PDFTextResult(
        file_name=file_name,
        text=final_text,
        page_count=final_page_count,
        extraction_method=extraction_method,
        is_text_valid=_is_text_usable(final_text),
        warnings=warnings,
        metadata=metadata,
    )

def _extract_with_paddle_ocr(file_name: str, content: bytes, ocr_config: OCRRunConfig) -> tuple[str, int, dict[str, Any]]:
    if not settings.paddle_ocr_api_token:
        raise RuntimeError("Remote PaddleOCR is required, but AUDIT_PADDLE_OCR_API_TOKEN is not configured.")
    return _extract_with_paddle_remote_ocr(content)


def _extract_with_paddle_remote_ocr(content: bytes) -> tuple[str, int, dict[str, Any]]:
    job_url = _resolve_paddle_ocr_job_url()
    headers = {"Authorization": f"bearer {settings.paddle_ocr_api_token}"}
    data = {
        "model": settings.paddle_ocr_model_name or "PaddleOCR-VL-1.5",
        "optionalPayload": json.dumps(
            {
                "useDocOrientationClassify": False,
                "useDocUnwarping": False,
                "useChartRecognition": False,
            }
        ),
    }
    logger.info(
        "Submitting async PaddleOCR job url=%s model=%s bytes=%s timeout=%s",
        job_url,
        data["model"],
        len(content),
        max(1, int(settings.paddle_ocr_api_timeout or 180)),
    )
    with io.BytesIO(content) as file_obj:
        response = requests.post(
            job_url,
            headers=headers,
            data=data,
            files={"file": ("document.pdf", file_obj, "application/pdf")},
            timeout=max(1, int(settings.paddle_ocr_api_timeout or 180)),
        )
    response_snippet = response.text[:500] if response.text else ""
    if response.status_code != 200:
        raise RuntimeError(
            f"Async PaddleOCR job submit failed with status {response.status_code}: {response_snippet}"
        )
    payload = response.json()
    job_data = payload.get("data") or {}
    job_id = str(job_data.get("jobId", "") or "")
    if not job_id:
        raise RuntimeError(f"Async PaddleOCR job submit returned no jobId: {payload}")
    deadline = time.monotonic() + max(5, int(settings.paddle_ocr_api_timeout or 180))
    poll_states: list[dict[str, Any]] = []
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        query_response = requests.get(
            f"{job_url}/{job_id}",
            headers=headers,
            timeout=max(1, int(settings.paddle_ocr_api_timeout or 180)),
        )
        query_response.raise_for_status()
        last_payload = query_response.json()
        query_data = last_payload.get("data") or {}
        state = str(query_data.get("state", "") or "")
        progress = query_data.get("extractProgress") or {}
        poll_states.append(
            {
                "state": state,
                "totalPages": progress.get("totalPages"),
                "extractedPages": progress.get("extractedPages"),
                "startTime": progress.get("startTime"),
                "endTime": progress.get("endTime"),
            }
        )
        if state == "done":
            result_url = query_data.get("resultUrl") or {}
            json_url = str(result_url.get("jsonUrl", "") or "")
            if not json_url:
                raise RuntimeError(f"Async PaddleOCR job completed without jsonUrl: {last_payload}")
            return _build_paddle_async_ocr_result(
                job_url=job_url,
                job_id=job_id,
                submit_status_code=response.status_code,
                submit_request_id=response.headers.get("x-request-id") or response.headers.get("request-id") or "",
                json_url=json_url,
                poll_states=poll_states,
            )
        if state == "failed":
            raise RuntimeError(str(query_data.get("errorMsg", "") or "Async PaddleOCR job failed."))
        time.sleep(max(1, int(settings.paddle_ocr_poll_interval_seconds or 5)))
    raise RuntimeError(f"Async PaddleOCR job polling timed out: {last_payload}")


def _resolve_paddle_ocr_job_url() -> str:
    configured = str(settings.paddle_ocr_job_url or settings.paddle_ocr_api_url or "").strip()
    if configured and "/api/v2/ocr/jobs" in configured:
        return configured
    return PADDLE_OCR_ASYNC_JOB_URL


def _build_paddle_async_ocr_result(
    *,
    job_url: str,
    job_id: str,
    submit_status_code: int,
    submit_request_id: str,
    json_url: str,
    poll_states: list[dict[str, Any]],
) -> tuple[str, int, dict[str, Any]]:
    json_response = requests.get(json_url, timeout=max(1, int(settings.paddle_ocr_api_timeout or 180)))
    json_response.raise_for_status()
    parsing_results: list[dict[str, Any]] = []
    for line in str(json_response.text or "").splitlines():
        raw_line = line.strip()
        if not raw_line:
            continue
        payload = json.loads(raw_line)
        result = payload.get("result") or {}
        for item in result.get("layoutParsingResults") or []:
            if isinstance(item, dict):
                parsing_results.append(item)
    combined_text, page_count, preview_images = _extract_layout_parsing_text_and_visuals(parsing_results)
    return combined_text, page_count, {
        "ocr_api_called": True,
        "ocr_api_mode": "aistudio_async_jobs",
        "ocr_api_url": job_url,
        "ocr_api_status_code": submit_status_code,
        "ocr_api_request_id": submit_request_id,
        "ocr_api_log_id": job_id,
        "ocr_api_job_id": job_id,
        "ocr_api_result_url": json_url,
        "ocr_api_poll_states": poll_states,
        "ocr_pages_used": page_count,
        "ocr_model": "paddleocr-vl-remote-async",
        "ocr_transport": "http-async",
        "ocr_preview_images": preview_images,
    }


def _extract_layout_parsing_text_and_visuals(parsing_results: list[dict[str, Any]]) -> tuple[str, int, list[dict[str, Any]]]:
    markdown_texts: list[str] = []
    preview_images: list[dict[str, Any]] = []
    for index, item in enumerate(parsing_results, start=1):
        markdown = item.get("markdown") or {}
        page_text = str(markdown.get("text", "") or "").strip()
        if page_text:
            markdown_texts.append(page_text)
        output_images = item.get("outputImages") or {}
        image_url = next((str(url or "").strip() for url in output_images.values() if str(url or "").strip()), "")
        pruned = item.get("prunedResult") or {}
        blocks: list[dict[str, Any]] = []
        for block in pruned.get("parsing_res_list") or []:
            if not isinstance(block, dict):
                continue
            block_text = str(block.get("block_content", "") or "").strip()
            bbox = block.get("block_bbox") or []
            if not block_text or not isinstance(bbox, list) or len(bbox) != 4:
                continue
            blocks.append(
                {
                    "text": block_text,
                    "x0": float(bbox[0] or 0),
                    "top": float(bbox[1] or 0),
                    "x1": float(bbox[2] or 0),
                    "bottom": float(bbox[3] or 0),
                    "label": str(block.get("block_label", "") or ""),
                }
            )
        if image_url:
            preview_images.append(
                {
                    "page_number": index,
                    "image_data_url": image_url,
                    "page_width": int(pruned.get("width", 0) or 0),
                    "page_height": int(pruned.get("height", 0) or 0),
                    "words": [],
                    "blocks": blocks,
                }
            )
    combined_text = "\n\n".join(markdown_texts).strip()
    page_count = len(parsing_results)
    if not combined_text:
        raise RuntimeError("Remote PaddleOCR returned no markdown text.")
    return combined_text, page_count, preview_images

def _resolve_pdftoppm_path() -> Path:
    if settings.pdftoppm_path.exists():
        return settings.pdftoppm_path
    sibling = settings.pdfinfo_path.with_name("pdftoppm.exe")
    if sibling.exists():
        return sibling
    raise FileNotFoundError("pdftoppm.exe was not found, so OCR page rendering could not start.")


def _resolve_pdftocairo_path() -> Path:
    sibling = settings.pdfinfo_path.with_name("pdftocairo.exe")
    if sibling.exists():
        return sibling
    fallback = Path(r"C:\Program Files\poppler\poppler-24.08.0\Library\bin\pdftocairo.exe")
    if fallback.exists():
        return fallback
    raise FileNotFoundError("pdftocairo.exe was not found for page rendering fallback.")


def _render_pdf_page_images_to_dir(content: bytes, temp_dir: Path, max_pages: int = 3) -> list[Path]:
    input_pdf = temp_dir / "input.pdf"
    input_pdf.write_bytes(content)
    output_prefix = temp_dir / "page"
    pages_limit = str(max(1, max_pages))
    pdftoppm_path = _resolve_pdftoppm_path()
    ppm_command = [
        str(pdftoppm_path),
        "-png",
        "-f",
        "1",
        "-l",
        pages_limit,
        str(input_pdf),
        str(output_prefix),
    ]
    try:
        # Avoid locale decode issues on Windows stderr/stdout that can silently break image rendering.
        subprocess.run(ppm_command, check=True, capture_output=True)
        image_paths = sorted(temp_dir.glob("page-*.png"))[: max(1, max_pages)]
        if image_paths:
            return image_paths
        raise RuntimeError("pdftoppm returned success but no PNG files were found.")
    except Exception as ppm_error:
        logger.warning("pdftoppm rendering failed, fallback to pdftocairo. error=%s", ppm_error)
        cairo_path = _resolve_pdftocairo_path()
        cairo_command = [
            str(cairo_path),
            "-png",
            "-f",
            "1",
            "-l",
            pages_limit,
            str(input_pdf),
            str(output_prefix),
        ]
        subprocess.run(cairo_command, check=True, capture_output=True)
        image_paths = sorted(temp_dir.glob("page-*.png"))[: max(1, max_pages)]
        if image_paths:
            return image_paths
        raise RuntimeError("No page images were rendered by pdftoppm/pdftocairo.")


def _image_path_to_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _render_pdf_page_images(content: bytes, max_pages: int = 3) -> dict[int, str]:
    temp_dir = settings.runtime_temp_dir / "visual_pages" / uuid4().hex
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        image_paths = _render_pdf_page_images_to_dir(content, temp_dir, max_pages=max_pages)
        return {
            index + 1: _image_path_to_data_url(image_path)
            for index, image_path in enumerate(image_paths)
        }
    except Exception:
        return {}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _extract_pdf_word_boxes(content: bytes, max_pages: int = 3) -> dict[int, dict[str, object]]:
    result: dict[int, dict[str, object]] = {}
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page_index, page in enumerate(pdf.pages[: max_pages], start=1):
                words = page.extract_words() or []
                result[page_index] = {
                    "page_width": page.width,
                    "page_height": page.height,
                    "words": [
                        {
                            "text": str(word.get("text", "")),
                            "x0": float(word.get("x0", 0) or 0),
                            "x1": float(word.get("x1", 0) or 0),
                            "top": float(word.get("top", 0) or 0),
                            "bottom": float(word.get("bottom", 0) or 0),
                        }
                        for word in words
                        if str(word.get("text", "")).strip()
                    ],
                }
    except Exception:
        return {}
    return result


def _extract_with_pdfplumber(content: bytes) -> tuple[str, int, str | None]:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
            return "\n\n".join(page.strip() for page in pages if page.strip()).strip(), len(pdf.pages), None
    except Exception as exc:
        return "", 0, f"pdfplumber failed: {exc}"


def _extract_with_pypdf(content: bytes) -> tuple[str, int, str | None]:
    try:
        reader = PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(page.strip() for page in pages if page.strip()).strip(), len(reader.pages), None
    except Exception as exc:
        return "", 0, f"pypdf failed: {exc}"


def _pick_longer_text(*candidates: str) -> str:
    normalized = [str(candidate or "") for candidate in candidates]
    return max(normalized, key=lambda item: len(item.strip()), default="")


def _merge_text_sources(base_text: str, ocr_text: str) -> str:
    base = str(base_text or "").strip()
    ocr = str(ocr_text or "").strip()
    if not base:
        return ocr
    if not ocr:
        return base
    if ocr in base:
        return base
    if base in ocr:
        return ocr
    return f"{base}\n\n--- OCR SUPPLEMENT ---\n\n{ocr}"


def _is_text_usable(text: str | None) -> bool:
    cleaned = str(text or "").strip()
    if len(cleaned) < MIN_VALID_TEXT_LENGTH:
        return False
    alpha_num_count = sum(1 for char in cleaned if char.isalnum())
    return alpha_num_count >= MIN_VALID_TEXT_LENGTH // 2
