from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import pdfplumber
import requests
from pydantic import BaseModel, Field
from pypdf import PdfReader

from audit_system.config import settings
from llm.client import LLMClient, LLMRuntimeConfig


MIN_VALID_TEXT_LENGTH = 40
OCR_SYSTEM_PROMPT = "You are a precise OCR assistant. Transcribe all visible text from the document images. Preserve field labels, table headers, identifiers, amounts, dates, and page numbers. Return transcription only."
OCR_USER_PROMPT = "Transcribe all visible text in page order. Prefix each page with [PAGE n]. If a page is hard to read, still return the text you can recognize."


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
            warnings.append("Base PDF text extraction was weak; OCR will be used when enabled.")

    resolved_ocr = ocr_config or OCRRunConfig()
    text_was_usable_before_ocr = _is_text_usable(final_text)
    metadata: dict[str, Any] = {
        "fallback_used": not _is_text_usable(pdfplumber_text),
        "pdfplumber_text_length": len(pdfplumber_text.strip()),
        "pypdf_text_length": len(pypdf_text.strip()),
        "ocr_status": "not_needed" if text_was_usable_before_ocr else ("pending" if resolved_ocr.enabled else "suggested"),
        "ocr_engine_preference": resolved_ocr.engine_preference or settings.ocr_engine_preference,
        "source_kind": "digital_text" if text_was_usable_before_ocr else "scan_like",
    }

    should_run_ocr = resolved_ocr.enabled and (resolved_ocr.force_ocr or not text_was_usable_before_ocr)
    if should_run_ocr:
        errors: list[str] = []
        for engine in _ocr_engines_in_order(resolved_ocr.engine_preference):
            try:
                if engine == "paddleocr":
                    ocr_text, ocr_page_count, ocr_metadata = _extract_with_paddle_ocr(content, resolved_ocr)
                else:
                    ocr_text, ocr_page_count, ocr_metadata = _extract_with_llm_ocr(content, resolved_ocr)
                metadata.update(ocr_metadata)
                if not _is_text_usable(ocr_text):
                    errors.append(f"{engine} returned weak text")
                    continue
                final_text = ocr_text if resolved_ocr.force_ocr or len(ocr_text.strip()) >= len(final_text.strip()) else final_text
                final_page_count = max(final_page_count, ocr_page_count)
                extraction_method = engine if not extraction_method else f"{extraction_method}+{engine}"
                metadata["ocr_status"] = "applied"
                metadata["ocr_engine"] = engine
                metadata["source_kind"] = "scan_ocr"
                break
            except Exception as exc:
                errors.append(f"{engine} failed: {exc}")
        else:
            if errors:
                warnings.append("OCR extraction failed: " + " | ".join(errors))
            metadata["ocr_status"] = "failed" if errors else "weak_result"

    return PDFTextResult(
        file_name=file_name,
        text=final_text,
        page_count=final_page_count,
        extraction_method=extraction_method,
        is_text_valid=_is_text_usable(final_text),
        warnings=warnings,
        metadata=metadata,
    )


def _extract_with_llm_ocr(content: bytes, ocr_config: OCRRunConfig) -> tuple[str, int, dict[str, str | int | bool | None]]:
    temp_dir = settings.runtime_temp_dir / "ocr_pages" / uuid4().hex
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        image_paths = _render_pdf_page_images_to_dir(content, temp_dir, max_pages=ocr_config.max_pages)
        image_urls = [_image_path_to_data_url(path) for path in image_paths]
        ocr_model = None
        if ocr_config.llm_runtime_config:
            ocr_model = ocr_config.llm_runtime_config.ocr_model or ocr_config.llm_runtime_config.model
        client = LLMClient(runtime_config=ocr_config.llm_runtime_config, model=ocr_model)
        response = client.transcribe_images(OCR_SYSTEM_PROMPT, OCR_USER_PROMPT, image_urls)
        return response.text.strip(), len(image_paths), {
            "ocr_pages_used": len(image_paths),
            "ocr_model": client.model,
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _extract_with_paddle_ocr(content: bytes, ocr_config: OCRRunConfig) -> tuple[str, int, dict[str, str | int | bool | None]]:
    if settings.paddle_ocr_api_url and settings.paddle_ocr_api_token:
        return _extract_with_paddle_remote_ocr(content)

    paddle_python = settings.paddle_ocr_python_path
    if not paddle_python.exists():
        raise FileNotFoundError(f"PaddleOCR Python was not found: {paddle_python}")
    temp_dir = settings.runtime_temp_dir / "ocr_pages" / uuid4().hex
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        image_paths = _render_pdf_page_images_to_dir(content, temp_dir, max_pages=ocr_config.max_pages)
        runner_path = Path(__file__).resolve().with_name("paddle_ocr_runner.py")
        payload = json.dumps({
            "image_paths": [str(path) for path in image_paths],
            "lang": "en",
        }, ensure_ascii=False)
        paddle_cache = settings.runtime_temp_dir / "paddle_cache"
        paddle_cache.mkdir(parents=True, exist_ok=True)
        paddle_temp = paddle_cache / "temp"
        paddle_temp.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [str(paddle_python), str(runner_path)],
            input=payload,
            capture_output=True,
            text=True,
            check=True,
            env={
                **os.environ,
                "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
                "PADDLE_HOME": str(paddle_cache),
                "XDG_CACHE_HOME": str(paddle_cache),
                "HOME": str(paddle_cache),
                "USERPROFILE": str(paddle_cache),
                "LOCALAPPDATA": str(paddle_cache),
                "TEMP": str(paddle_temp),
                "TMP": str(paddle_temp),
                "TMPDIR": str(paddle_temp),
                "HF_HOME": str(paddle_cache / "hf_home"),
                "HUGGINGFACE_HUB_CACHE": str(paddle_cache / "hf_home" / "hub"),
                "MODELSCOPE_CACHE": str(paddle_cache / "modelscope"),
                "PADDLE_PDX_MODEL_SOURCE": "BOS",
            },
        )
        result = json.loads(completed.stdout or "{}")
        return str(result.get("text", "") or "").strip(), int(result.get("page_count", 0) or 0), {
            "ocr_pages_used": int(result.get("page_count", 0) or 0),
            "ocr_model": "paddleocr",
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _extract_with_paddle_remote_ocr(content: bytes) -> tuple[str, int, dict[str, Any]]:
    encoded_file = base64.b64encode(content).decode("ascii")
    payload = {
        "file": encoded_file,
        "fileType": 0,
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }
    headers = {
        "Authorization": f"token {settings.paddle_ocr_api_token}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        settings.paddle_ocr_api_url,
        json=payload,
        headers=headers,
        timeout=max(1, int(settings.paddle_ocr_api_timeout or 180)),
    )
    response.raise_for_status()
    data = response.json()
    result = data.get("result") or {}
    parsing_results = result.get("layoutParsingResults") or []
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
            blocks.append({
                "text": block_text,
                "x0": float(bbox[0] or 0),
                "top": float(bbox[1] or 0),
                "x1": float(bbox[2] or 0),
                "bottom": float(bbox[3] or 0),
                "label": str(block.get("block_label", "") or ""),
            })
        if image_url:
            preview_images.append({
                "page_number": index,
                "image_data_url": image_url,
                "page_width": int(pruned.get("width", 0) or 0),
                "page_height": int(pruned.get("height", 0) or 0),
                "words": [],
                "blocks": blocks,
            })
    combined_text = "\n\n".join(markdown_texts).strip()
    page_count = len(parsing_results)
    if not combined_text:
        raise RuntimeError("Remote PaddleOCR returned no markdown text.")
    return combined_text, page_count, {
        "ocr_pages_used": page_count,
        "ocr_model": "paddleocr-vl-remote",
        "ocr_transport": "http",
        "ocr_preview_images": preview_images,
    }


def _ocr_engines_in_order(preference: str) -> list[str]:
    normalized = str(preference or "").strip().lower()
    if normalized == "llm_first":
        return ["llm_ocr", "paddleocr"]
    if normalized == "paddle_first":
        return ["paddleocr", "llm_ocr"]
    if normalized == "llm_only":
        return ["llm_ocr"]
    return ["paddleocr"]


def _resolve_pdftoppm_path() -> Path:
    if settings.pdftoppm_path.exists():
        return settings.pdftoppm_path
    sibling = settings.pdfinfo_path.with_name("pdftoppm.exe")
    if sibling.exists():
        return sibling
    raise FileNotFoundError("pdftoppm.exe was not found, so OCR page rendering could not start.")


def _render_pdf_page_images_to_dir(content: bytes, temp_dir: Path, max_pages: int = 3) -> list[Path]:
    input_pdf = temp_dir / "input.pdf"
    input_pdf.write_bytes(content)
    output_prefix = temp_dir / "page"
    pdftoppm_path = _resolve_pdftoppm_path()
    command = [
        str(pdftoppm_path),
        "-png",
        "-f",
        "1",
        "-l",
        str(max(1, max_pages)),
        str(input_pdf),
        str(output_prefix),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    image_paths = sorted(temp_dir.glob("page-*.png"))[: max(1, max_pages)]
    if not image_paths:
        raise RuntimeError("No OCR page images were rendered.")
    return image_paths


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


def _is_text_usable(text: str | None) -> bool:
    cleaned = str(text or "").strip()
    if len(cleaned) < MIN_VALID_TEXT_LENGTH:
        return False
    alpha_num_count = sum(1 for char in cleaned if char.isalnum())
    return alpha_num_count >= MIN_VALID_TEXT_LENGTH // 2