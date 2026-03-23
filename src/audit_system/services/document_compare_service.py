from __future__ import annotations

import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from audit_system.config import settings


PDFINFO_PATH = settings.pdfinfo_path
PDFTOTEXT_PATH = settings.pdftotext_path
RUNTIME_TEMP_DIR = settings.runtime_temp_dir

KEY_PATTERNS = {
    "invoice_no": [
        re.compile(r"invoice\s*(?:no|number)?\s*[:#-]?\s*([A-Z0-9./_-]+)", re.IGNORECASE),
        re.compile(r"proforma\s+invoice\s*[-:/]?\s*([A-Z0-9./_-]+)", re.IGNORECASE),
    ],
    "contract_no": [
        re.compile(r"contract\s*(?:no|number)?\s*[:#-]?\s*([A-Z0-9./_-]+)", re.IGNORECASE),
    ],
    "total_amount": [
        re.compile(r"total\s+[^.\n]{0,30}?us\$\s*([0-9.,]+)", re.IGNORECASE),
        re.compile(r"amount\s*[:#-]?\s*us\$\s*([0-9.,]+)", re.IGNORECASE),
    ],
    "buyer": [
        re.compile(r"client\s+([A-Z][A-Z0-9 ,.'&()-]{5,})", re.IGNORECASE),
        re.compile(r"consignee\s+([A-Z][A-Z0-9 ,.'&()-]{5,})", re.IGNORECASE),
    ],
}


@dataclass(slots=True)
class DocumentAnalysis:
    filename: str
    pages: int | None
    text_length: int
    extracted_text: str
    preview: str
    classification: str
    extraction_method: str
    engine_used: str
    extracted_fields: dict[str, str]
    errors: list[str]


@dataclass(slots=True)
class ComparisonResult:
    left: DocumentAnalysis
    right: DocumentAnalysis
    shared_fields: dict[str, str]
    differing_fields: dict[str, dict[str, str]]


def analyze_pdf_bytes(filename: str, content: bytes) -> DocumentAnalysis:
    errors: list[str] = []
    if not PDFINFO_PATH.exists() or not PDFTOTEXT_PATH.exists():
        errors.append("Poppler tools not found. Please install pdfinfo/pdftotext.")
        return DocumentAnalysis(
            filename=filename,
            pages=None,
            text_length=0,
            extracted_text="",
            preview="",
            classification="unavailable",
            extraction_method="unavailable",
            engine_used="Unavailable",
            extracted_fields={},
            errors=errors,
        )

    RUNTIME_TEMP_DIR.mkdir(exist_ok=True)
    pdf_path = RUNTIME_TEMP_DIR / f"{uuid.uuid4().hex}_{sanitize_filename(filename)}"

    try:
        pdf_path.write_bytes(content)
        pages = _read_pdf_pages(pdf_path, errors)
        extracted_text = _extract_text(pdf_path, errors)
    finally:
        pdf_path.unlink(missing_ok=True)

    preview = _build_preview(extracted_text)
    classification = _classify_document(extracted_text)
    extraction_method, engine_used = _resolve_extraction_details(classification)
    fields = _extract_fields(extracted_text)

    return DocumentAnalysis(
        filename=filename,
        pages=pages,
        text_length=len(extracted_text.strip()),
        extracted_text=extracted_text,
        preview=preview,
        classification=classification,
        extraction_method=extraction_method,
        engine_used=engine_used,
        extracted_fields=fields,
        errors=errors,
    )


def compare_documents(left: DocumentAnalysis, right: DocumentAnalysis) -> ComparisonResult:
    shared_fields: dict[str, str] = {}
    differing_fields: dict[str, dict[str, str]] = {}

    all_keys = set(left.extracted_fields) | set(right.extracted_fields)
    for key in sorted(all_keys):
        left_value = left.extracted_fields.get(key, "")
        right_value = right.extracted_fields.get(key, "")
        if not left_value or not right_value:
            continue
        if normalize_value(left_value) == normalize_value(right_value):
            shared_fields[key] = left_value
            continue
        differing_fields[key] = {"left": left_value, "right": right_value}

    return ComparisonResult(
        left=left,
        right=right,
        shared_fields=shared_fields,
        differing_fields=differing_fields,
    )


def sanitize_filename(filename: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    return safe_name or "upload.pdf"


def normalize_value(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _read_pdf_pages(pdf_path: Path, errors: list[str]) -> int | None:
    try:
        result = subprocess.run(
            [str(PDFINFO_PATH), str(pdf_path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except OSError as exc:
        errors.append(f"Failed to run pdfinfo: {exc}")
        return None

    if result.returncode != 0:
        errors.append(result.stderr.strip() or "pdfinfo failed")
        return None

    match = re.search(r"^Pages:\s+(\d+)$", result.stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def _extract_text(pdf_path: Path, errors: list[str]) -> str:
    try:
        result = subprocess.run(
            [str(PDFTOTEXT_PATH), "-layout", str(pdf_path), "-"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except OSError as exc:
        errors.append(f"Failed to run pdftotext: {exc}")
        return ""

    if result.returncode != 0:
        errors.append(result.stderr.strip() or "pdftotext failed")
        return ""

    return result.stdout.replace("\x0c", " ").strip()


def _build_preview(extracted_text: str, limit: int = 1200) -> str:
    compact = re.sub(r"\n{3,}", "\n\n", extracted_text).strip()
    return compact[:limit]


def _classify_document(extracted_text: str) -> str:
    if len(extracted_text.strip()) >= 80:
        return "text-pdf"
    if extracted_text.strip():
        return "low-text-pdf"
    return "image-or-scan-pdf"


def _resolve_extraction_details(classification: str) -> tuple[str, str]:
    if classification in {"text-pdf", "low-text-pdf"}:
        return "direct-text-extraction", "Poppler pdftotext"
    return "ocr-required-not-run", "None"


def _extract_fields(extracted_text: str) -> dict[str, str]:
    collapsed = re.sub(r"[ \t]+", " ", extracted_text)
    fields: dict[str, str] = {}
    for field_name, patterns in KEY_PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(collapsed)
            if match:
                fields[field_name] = match.group(1).strip(" .:-")
                break
    return fields
