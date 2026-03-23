from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from llm.client import LLMClient, parse_json_with_fallback
from services.extractor_service import ExtractionRunResult
from services.pdf_text_service import PDFTextResult


PROMPT_PATH = Path("llm/prompts/compare_prompt.txt")
SYSTEM_PROMPT = "你是一个严格输出 JSON 的审单文档比对助手。"


class CompareRunResult(BaseModel):
    rendered_prompt: str
    raw_model_response: str
    repair_raw_response: str | None = None
    compare_data: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    prompt_path: str
    model_name: str


def compare_documents(
    left_pdf_result: PDFTextResult,
    right_pdf_result: PDFTextResult,
    left_extract_result: ExtractionRunResult,
    right_extract_result: ExtractionRunResult,
) -> CompareRunResult:
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    rendered_prompt = prompt_template.format(
        file_a_name=left_pdf_result.file_name,
        file_b_name=right_pdf_result.file_name,
        document_a_text=left_pdf_result.text or "[EMPTY]",
        document_b_text=right_pdf_result.text or "[EMPTY]",
        document_a_json=json.dumps(left_extract_result.structured_data, ensure_ascii=False, indent=2),
        document_b_json=json.dumps(right_extract_result.structured_data, ensure_ascii=False, indent=2),
    )

    warnings = [
        *left_pdf_result.warnings,
        *right_pdf_result.warnings,
        *left_extract_result.warnings,
        *right_extract_result.warnings,
    ]

    client = LLMClient()
    response = client.complete_json(SYSTEM_PROMPT, rendered_prompt)
    raw_model_response = response.text

    repair_raw_response: str | None = None
    try:
        compare_data = parse_json_with_fallback(raw_model_response)
    except Exception:
        repair_response = client.complete_json(
            "你是一个 JSON 修复助手，只能输出修复后的合法 JSON。",
            (
                "请把下面这段模型输出修复为合法 JSON。"
                "不要补造新字段，只允许在不改变原意的前提下修正格式错误。\n\n"
                f"{raw_model_response}"
            ),
        )
        repair_raw_response = repair_response.text
        compare_data = parse_json_with_fallback(repair_raw_response)
        warnings.append("对比结果 JSON 首次解析失败，已自动执行一次 JSON 修复重试。")

    return CompareRunResult(
        rendered_prompt=rendered_prompt,
        raw_model_response=raw_model_response,
        repair_raw_response=repair_raw_response,
        compare_data=compare_data,
        warnings=warnings,
        prompt_path=str(PROMPT_PATH),
        model_name=client.model,
    )
