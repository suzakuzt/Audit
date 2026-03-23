from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from schemas.document_schema import STANDARD_FIELD_LABELS

from pydantic import BaseModel, Field

from llm.client import LLMClient, LLMRuntimeConfig, parse_json_with_fallback
from schemas.document_schema import DocumentExtractResult
from services.knowledge_store import get_prompt_text, list_prompt_version_refs, load_knowledge_payload, save_knowledge_payload
from services.pdf_text_service import PDFTextResult
from utils.json_utils import dump_json_text


PROMPTS_DIR = Path("llm/prompts")
KNOWLEDGE_DIR = Path("knowledge")
SYSTEM_PROMPT = "你是一个严格输出 JSON 的审单单据识别助手。你只基于输入文本、active alias 库和 active rule 库工作。"

PARTY_ADDRESS_FIELD_ALIASES = {
    "consignee_name_address": ["consignee", "consignee address", "consignee name", "consignee name & address", "delivery address", "deliver to"],
}


class ExtractionRunResult(BaseModel):
    file_name: str
    prompt_file: str
    rendered_prompt: str
    raw_model_response: str
    repair_raw_response: str | None = None
    structured_data: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def list_prompt_versions() -> list:
    prompt_refs = list_prompt_version_refs()
    if not prompt_refs:
        raise FileNotFoundError("未找到任何提示词版本。")
    return prompt_refs


def load_knowledge_file(path: Path) -> Any:
    return load_knowledge_payload(path)


def save_knowledge_file(path: Path, payload: Any) -> None:
    save_knowledge_payload(path, payload)


def extract_document(pdf_result: PDFTextResult, prompt_file_name: str) -> ExtractionRunResult:
    return extract_document_with_options(
        pdf_result=pdf_result,
        prompt_file_name=prompt_file_name,
        prompt_text=None,
        use_alias_active=True,
        use_rule_active=True,
        alias_active_override=None,
        rule_active_override=None,
        llm_runtime_config=None,
        priority_fields=None,
    )


def extract_document_with_options(
    pdf_result: PDFTextResult,
    prompt_file_name: str,
    prompt_text: str | None,
    use_alias_active: bool,
    use_rule_active: bool,
    alias_active_override: Any | None,
    rule_active_override: Any | None,
    llm_runtime_config: LLMRuntimeConfig | None,
    focus_fields: list[str] | None = None,
    priority_fields: list[str] | None = None,
) -> ExtractionRunResult:
    prompt_template = prompt_text if prompt_text is not None else get_prompt_text(prompt_file_name)
    alias_active = alias_active_override if alias_active_override is not None else load_knowledge_file(KNOWLEDGE_DIR / "alias_active.json")
    rule_active = rule_active_override if rule_active_override is not None else load_knowledge_file(KNOWLEDGE_DIR / "rule_active.json")
    focus_fields = [str(item).strip() for item in (focus_fields or []) if str(item).strip()]
    priority_fields = [str(item).strip() for item in (priority_fields or []) if str(item).strip()]
    if focus_fields:
        prompt_template = _narrow_prompt_to_focus_fields(prompt_template, focus_fields)
        alias_active = _filter_alias_active(alias_active, focus_fields)
        rule_active = _filter_rule_active(rule_active, focus_fields)
    if not use_alias_active:
        alias_active = {}
    if not use_rule_active:
        rule_active = []

    rendered_prompt = prompt_template.format(
        file_name=pdf_result.file_name,
        document_text=pdf_result.text or "[EMPTY]",
        alias_active_json=dump_json_text(alias_active),
        rule_active_json=dump_json_text(rule_active),
    )
    rendered_prompt += _build_ocr_context_note(pdf_result)
    if priority_fields:
        rendered_prompt += _build_priority_focus_note(priority_fields)

    warnings = list(pdf_result.warnings)
    if not pdf_result.is_text_valid:
        warnings.append("PDF text quality looks weak, so the result may still need a quick review.")

    alias_precheck = _try_fast_extract(pdf_result, focus_fields, alias_active)
    if alias_precheck is not None:
        rendered_prompt += _build_alias_precheck_note(alias_precheck)

    if _should_use_alias_fast_path(alias_precheck, focus_fields, pdf_result, use_alias_active):
        validated = DocumentExtractResult.model_validate(alias_precheck).model_dump()
        validated = _apply_field_guardrails(validated, pdf_result, alias_active)
        return ExtractionRunResult(
            file_name=pdf_result.file_name,
            prompt_file=prompt_file_name,
            rendered_prompt=rendered_prompt,
            raw_model_response="",
            repair_raw_response=None,
            structured_data=validated,
            warnings=warnings,
            metadata={
                "prompt_file": prompt_file_name,
                "prompt_path": str(PROMPTS_DIR / prompt_file_name),
                "model_name": None,
                "use_alias_active": use_alias_active,
                "use_rule_active": use_rule_active,
                "alias_active_version_size": len(alias_active),
                "rule_active_version_size": len(rule_active),
                "alias_active_used": alias_active,
                "rule_active_used": rule_active,
                "llm_base_url": llm_runtime_config.base_url if llm_runtime_config and llm_runtime_config.base_url is not None else None,
                "ocr_model": llm_runtime_config.ocr_model if llm_runtime_config else None,
                "storage_mode": "database_first",
                "focus_fields": focus_fields,
                "priority_fields": priority_fields,
                "decision_mode": "alias_fast_path",
                "identification_sequence": ["load_alias_active", "load_rule_active", "render_prompt", "append_ocr_context", "alias_precheck", "alias_fast_path_complete"],
                "alias_precheck_used": alias_precheck is not None,
                "alias_precheck_result": alias_precheck,
            },
        )

    client = LLMClient(runtime_config=llm_runtime_config)
    response = client.complete_json(SYSTEM_PROMPT, rendered_prompt)
    raw_model_response = response.text
    repair_raw_response: str | None = None
    try:
        structured_data = parse_json_with_fallback(raw_model_response)
    except Exception:
        repair_response = client.complete_text(
            "You are a JSON repair assistant. Return only valid JSON.",
            "Repair the following model output into valid JSON. Do not invent new fields; only fix the format.\n\n" + raw_model_response,
        )
        repair_raw_response = repair_response.text
        structured_data = parse_json_with_fallback(repair_raw_response)
        warnings.append("Initial JSON parsing failed, so one JSON repair retry was executed.")

    validated = DocumentExtractResult.model_validate(structured_data).model_dump()
    validated = _apply_field_guardrails(validated, pdf_result, alias_active)
    return ExtractionRunResult(
        file_name=pdf_result.file_name,
        prompt_file=prompt_file_name,
        rendered_prompt=rendered_prompt,
        raw_model_response=raw_model_response,
        repair_raw_response=repair_raw_response,
        structured_data=validated,
        warnings=warnings,
        metadata={
            "prompt_file": prompt_file_name,
            "prompt_path": str(PROMPTS_DIR / prompt_file_name),
            "model_name": client.model,
            "use_alias_active": use_alias_active,
            "use_rule_active": use_rule_active,
            "alias_active_version_size": len(alias_active),
            "rule_active_version_size": len(rule_active),
            "alias_active_used": alias_active,
            "rule_active_used": rule_active,
            "llm_base_url": llm_runtime_config.base_url if llm_runtime_config and llm_runtime_config.base_url is not None else None,
            "ocr_model": llm_runtime_config.ocr_model if llm_runtime_config else None,
            "storage_mode": "database_first",
            "focus_fields": focus_fields,
            "priority_fields": priority_fields,
            "decision_mode": "llm_full_path",
            "identification_sequence": ["load_alias_active", "load_rule_active", "render_prompt", "append_ocr_context", "alias_precheck", "llm_identify"],
            "alias_precheck_used": alias_precheck is not None,
            "alias_precheck_result": alias_precheck,
        },
    )


def _should_use_alias_fast_path(
    alias_precheck: dict[str, Any] | None,
    focus_fields: list[str] | None,
    pdf_result: PDFTextResult,
    use_alias_active: bool,
) -> bool:
    if not use_alias_active or alias_precheck is None:
        return False
    wanted = [str(item).strip() for item in (focus_fields or []) if str(item).strip()]
    if not wanted or len(wanted) > 3:
        return False
    if not pdf_result.is_text_valid:
        return False
    if alias_precheck.get("missing_fields") or alias_precheck.get("uncertain_fields"):
        return False
    mapped_fields = alias_precheck.get("mapped_fields") or []
    mapped_names = {
        str(item.get("standard_field", "") or "")
        for item in mapped_fields
        if isinstance(item, dict)
    }
    return all(field in mapped_names for field in wanted)


def _build_ocr_context_note(pdf_result: PDFTextResult) -> str:
    metadata = pdf_result.metadata if isinstance(pdf_result.metadata, dict) else {}
    ocr_summary = {
        "file_name": pdf_result.file_name,
        "page_count": pdf_result.page_count,
        "extraction_method": pdf_result.extraction_method,
        "is_text_valid": pdf_result.is_text_valid,
        "source_kind": metadata.get("source_kind"),
        "ocr_status": metadata.get("ocr_status"),
        "ocr_engine": metadata.get("ocr_engine"),
        "ocr_model": metadata.get("ocr_model"),
        "ocr_transport": metadata.get("ocr_transport"),
        "ocr_pages_used": metadata.get("ocr_pages_used"),
        "pdfplumber_text_length": metadata.get("pdfplumber_text_length"),
        "pypdf_text_length": metadata.get("pypdf_text_length"),
        "warnings": list(pdf_result.warnings),
    }
    return (
        "\n\nDocument extraction context (OCR and text extraction summary):\n"
        + dump_json_text(ocr_summary)
        + "\nUse this context to judge text reliability. Prefer grounded extraction from the document text, and be conservative when OCR quality looks weak.\n"
    )


def _filter_alias_active(alias_active: Any, focus_fields: list[str]) -> Any:
    if not isinstance(alias_active, dict):
        return alias_active
    wanted = set(focus_fields)
    return {key: value for key, value in alias_active.items() if str(key) in wanted}


def _filter_rule_active(rule_active: Any, focus_fields: list[str]) -> Any:
    if not isinstance(rule_active, list):
        return rule_active
    wanted = set(focus_fields)
    filtered = []
    for item in rule_active:
        if not isinstance(item, dict):
            continue
        field_name = str(item.get("field", "") or "")
        if not field_name or field_name in wanted:
            filtered.append(item)
    return filtered


def _narrow_prompt_to_focus_fields(prompt_template: str, focus_fields: list[str]) -> str:
    if not focus_fields:
        return prompt_template
    bullet_block = "\n".join(f"- {field}" for field in focus_fields)
    pattern = re.compile(r"(Target fields:\n)(.*?)(\n\nOutput JSON shape:)", re.S)
    if pattern.search(prompt_template):
        return pattern.sub(lambda m: f"{m.group(1)}{bullet_block}{m.group(3)}", prompt_template, count=1)
    return prompt_template + "\n\nCurrent validation focus fields:\n" + bullet_block


def _build_priority_focus_note(priority_fields: list[str]) -> str:
    labels = [STANDARD_FIELD_LABELS.get(field, field) for field in priority_fields]
    return (
        "\n\nPriority fields for this run (treat these as highest-focus targets during OCR grounding, alias matching, and semantic mapping):\n"
        + dump_json_text({"priority_fields": priority_fields, "priority_labels": labels})
        + "\nWhen evidence is limited, spend extra effort checking these fields before concluding they are missing.\n"
    )


def _build_alias_precheck_note(alias_precheck: dict[str, Any]) -> str:
    return (
        "\n\nAlias precheck hints (read first, then still use the full document text and prompt rules for AI judgment):\n"
        + dump_json_text(alias_precheck)
        + "\nPlease treat this as prior candidate evidence only. Do not skip full AI identification, and do not copy it mechanically if the document context conflicts.\n"
    )


def _try_fast_extract(pdf_result: PDFTextResult, focus_fields: list[str] | None, alias_active: Any) -> dict[str, Any] | None:
    wanted = [str(item).strip() for item in (focus_fields or []) if str(item).strip()]
    if not wanted or len(wanted) > 2:
        return None
    text = str(pdf_result.text or "")
    if not text.strip():
        return None
    mapped_fields: list[dict[str, Any]] = []
    missing_fields: list[str] = []
    for field_name in wanted:
        match = _fast_find_field(field_name, text, alias_active if isinstance(alias_active, dict) else {})
        if match is None:
            missing_fields.append(field_name)
            continue
        mapped_fields.append(match)
    if not mapped_fields:
        return None
    return {
        "doc_type": _infer_doc_type(text),
        "mapped_fields": mapped_fields,
        "missing_fields": missing_fields,
        "uncertain_fields": [],
        "raw_summary": "Fast candidate scan matched field labels; ready for alias confirmation.",
    }


def _fast_find_field(field_name: str, text: str, alias_active: dict[str, Any]) -> dict[str, Any] | None:
    aliases = _field_aliases(field_name, alias_active)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    line_match = _match_field_from_lines(field_name, aliases, lines)
    if line_match is not None:
        return line_match
    regex_match = _match_field_with_regex(field_name, text)
    if regex_match is not None:
        return regex_match
    return None


def _field_aliases(field_name: str, alias_active: dict[str, Any]) -> list[str]:
    aliases = []
    aliases.extend([STANDARD_FIELD_LABELS.get(field_name, ""), field_name])
    aliases.extend([str(item) for item in alias_active.get(field_name, []) or []])
    if field_name == "contract_no":
        aliases = [item for item in aliases if _normalize_simple(item) not in {"contract", "ref no", "proforma invoice"}]
        aliases.extend(["contract no", "contract number", "contract ref", "invoice no", "invoice number", "proforma invoice nr", "pi no"])
    if field_name == "factory_no":
        aliases.extend(["厂号", "工厂号", "工厂编号", "生产厂号", "加工厂号", "注册厂号", "plant no", "plant no.", "plant number", "establishment no", "establishment no.", "est no", "est. no.", "factory no", "factory no.", "packing plant no", "slaughterhouse no", "processing plant no"])
    if field_name in PARTY_ADDRESS_FIELD_ALIASES:
        aliases.extend(PARTY_ADDRESS_FIELD_ALIASES[field_name])
    deduped = []
    seen = set()
    for alias in aliases:
        cleaned = str(alias or "").strip()
        marker = _normalize_simple(cleaned)
        if cleaned and marker not in seen:
            seen.add(marker)
            deduped.append(cleaned)
    deduped.sort(key=len, reverse=True)
    return deduped


def _match_field_from_lines(field_name: str, aliases: list[str], lines: list[str]) -> dict[str, Any] | None:
    for line_index, line in enumerate(lines):
        normalized_line = _normalize_simple(line)
        for alias in aliases:
            normalized_alias = _normalize_simple(alias)
            if not normalized_alias or normalized_alias not in normalized_line:
                continue
            if field_name == "contract_no" and not _is_contract_label_line(line, alias):
                continue
            value = _extract_value_after_alias(line, alias)
            if not value and line_index + 1 < len(lines):
                next_line = lines[line_index + 1].strip()
                if next_line and len(next_line) < 80:
                    value = next_line
            if value:
                return {
                    "standard_field": field_name,
                    "standard_label_cn": STANDARD_FIELD_LABELS.get(field_name, field_name),
                    "source_field_name": alias,
                    "source_value": value,
                    "confidence": 0.97,
                    "uncertain": False,
                    "reason": "Fast candidate scan matched a field label with its nearby value.",
                }
    return None


def _is_contract_label_line(line: str, alias: str) -> bool:
    stripped = str(line or '').strip()
    lowered = stripped.lower()
    alias_lower = alias.lower()
    index = lowered.find(alias_lower)
    if index == -1:
        return False
    if index > 4:
        return False
    tail = stripped[index + len(alias):].strip()
    if not tail:
        return False
    if tail[:1] not in '-:?# ':
        return False
    return True


def _extract_value_after_alias(line: str, alias: str) -> str:
    lower_line = line.lower()
    lower_alias = alias.lower()
    index = lower_line.find(lower_alias)
    if index == -1:
        return ""
    tail = line[index + len(alias):].strip()
    tail = re.sub(r'^[\s:?#\-?_]+', '', tail).strip()
    if not tail:
        return ""
    if len(tail) > 120:
        tail = tail[:120].strip()
    return tail


def _match_field_with_regex(field_name: str, text: str) -> dict[str, Any] | None:
    if field_name == "contract_no":
        patterns = [
            (r'^[ \t]*((?:Invoice[ \t]*(?:No\.?|Number|NR\.?)?|Contract[ \t]*(?:No\.?|Number|Ref(?:erence)?)?))[ \t]*[:?#-]?[ \t]*([A-Z0-9][A-Z0-9 ./_-]{2,})[ \t]*$'),
            (r'^[ \t]*(?:[A-Z][A-Z ./_-]{0,24}[ \t]+)?(PROFORMA[ \t]+INVOICE(?:[ \t]+(?:NO|NUMBER|NR))?)[ \t]*[-:?]?[ \t]*([A-Z0-9][A-Z0-9 ./_-]{2,})[ \t]*$'),
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I | re.M)
            if match:
                source_name = _clean_field_label(match.group(1))
                value = match.group(2).strip()
                if not _looks_like_contract_number(value):
                    continue
                return {
                    "standard_field": field_name,
                    "standard_label_cn": STANDARD_FIELD_LABELS.get(field_name, field_name),
                    "source_field_name": source_name,
                    "source_value": value,
                    "confidence": 0.9,
                    "uncertain": False,
                    "reason": "Fast regex matched the contract number pattern.",
                }
        return None
    if field_name == "factory_no":
        patterns = [
            r'^[ \t]*((?:Plant|Factory|Establishment|Est\.?|Packing Plant|Slaughterhouse|Processing Plant)[ \t]*(?:No\.?|Number)?)[ \t]*[:?#-]?[ \t]*([A-Z0-9][A-Z0-9./_-]{1,})[ \t]*$',
            r'((?:Plant|Factory|Establishment|Est\.?|Packing Plant|Slaughterhouse|Processing Plant)[ \t]*(?:No\.?|Number)?)[ \t]*[:?#-]?[ \t]*([A-Z0-9][A-Z0-9./_-]{1,})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I | re.M)
            if not match:
                continue
            source_name = _clean_field_label(match.group(1))
            value = match.group(2).strip().rstrip(' .:;?#-')
            if not _looks_like_factory_number(value):
                continue
            return {
                "standard_field": field_name,
                "standard_label_cn": STANDARD_FIELD_LABELS.get(field_name, field_name),
                "source_field_name": source_name,
                "source_value": value,
                "confidence": 0.92,
                "uncertain": False,
                "reason": "Fast regex matched the factory number pattern.",
            }
    return None



def _looks_like_factory_number(value: str) -> bool:
    candidate = str(value or '').strip()
    if len(candidate) < 2 or len(candidate) > 40:
        return False
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9./_-]*', candidate, flags=re.I):
        return False
    alpha_num = sum(1 for ch in candidate if ch.isalnum())
    return alpha_num >= 2

def _infer_doc_type(text: str) -> str:
    lowered = text.lower()
    if 'proforma invoice' in lowered:
        return 'Proforma Invoice'
    if 'contract' in lowered:
        return 'Contract'
    return 'Unknown'


def _normalize_simple(value: str) -> str:
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).split())


def _clean_field_label(value: str) -> str:
    return str(value or '').strip().rstrip(' .:?#-')


def _is_explicit_contract_label(value: str) -> bool:
    label = _normalize_simple(value)
    if not label:
        return False
    if label in {"invoice", "contract", "proforma invoice"}:
        return False
    has_contract = "contract" in label
    has_invoice_no = ("invoice" in label and ("no" in label or "number" in label or "nr" in label))
    has_reference = "ref" in label
    has_short_pi = label in {"pi no", "pi number", "pi nr"}
    return has_contract or has_invoice_no or has_reference or has_short_pi


def _apply_field_guardrails(structured_data: dict[str, Any], pdf_result: PDFTextResult, alias_active: Any) -> dict[str, Any]:
    mapped = [dict(item) for item in structured_data.get("mapped_fields", []) if isinstance(item, dict)]
    missing = list(structured_data.get("missing_fields", []) or [])
    uncertain = list(structured_data.get("uncertain_fields", []) or [])
    alias_map = alias_active if isinstance(alias_active, dict) else {}
    updated: list[dict[str, Any]] = []
    contract_no_present = False
    for item in mapped:
        field_name = str(item.get("standard_field", "") or "")
        if field_name != "contract_no":
            updated.append(item)
            continue
        corrected = _repair_contract_no_mapping(item, pdf_result.text or "", alias_map)
        if corrected is None:
            if field_name not in missing:
                missing.append(field_name)
            continue
        contract_no_present = True
        updated.append(corrected)
    if not contract_no_present:
        recovered = _match_field_with_regex("contract_no", pdf_result.text or "")
        if recovered and _is_valid_contract_no_mapping(str(recovered.get("source_field_name", "") or ""), str(recovered.get("source_value", "") or ""), pdf_result.text or ""):
            updated.append(recovered)
            missing = [field for field in missing if field != "contract_no"]
            uncertain = [field for field in uncertain if field != "contract_no"]
    structured_data["mapped_fields"] = updated
    structured_data["missing_fields"] = _unique_list(missing)
    structured_data["uncertain_fields"] = _unique_list(uncertain)
    return structured_data


def _repair_contract_no_mapping(item: dict[str, Any], text: str, alias_active: dict[str, Any]) -> dict[str, Any] | None:
    source_name = str(item.get("source_field_name", "") or "")
    source_value = str(item.get("source_value", "") or "")
    if _is_valid_contract_no_mapping(source_name, source_value, text):
        return item
    fast_match = _fast_find_field("contract_no", text, alias_active)
    if fast_match and _is_valid_contract_no_mapping(str(fast_match.get("source_field_name", "")), str(fast_match.get("source_value", "")), text):
        repaired = dict(item)
        repaired["source_value"] = str(fast_match.get("source_value", "") or "")
        if _is_explicit_contract_label(source_name):
            repaired["source_field_name"] = _clean_field_label(source_name)
        else:
            repaired["source_field_name"] = str(fast_match.get("source_field_name", "") or "")
        repaired["confidence"] = max(float(fast_match.get("confidence", 0.0) or 0.0), float(item.get("confidence", 0.0) or 0.0), 0.9)
        repaired["reason"] = "Repaired contract number value from OCR text without changing the confirmed field meaning."
        return repaired
    return None


def _is_valid_contract_no_mapping(source_name: str, source_value: str, text: str = "") -> bool:
    label = _normalize_simple(source_name)
    value = str(source_value or "").strip()
    if not value or len(value) < 3:
        return False
    if not _looks_like_contract_number(value):
        return False
    if text and not _is_text_grounded_value(text, value):
        return False
    bad_tokens = {"address", "client", "consignee", "notify", "phone", "email", "bank", "beneficiary"}
    label_tokens = set(label.split())
    if label_tokens & bad_tokens:
        return False
    if len(label.split()) > 5:
        return False
    if _is_explicit_contract_label(source_name):
        return True
    if label == "proforma invoice":
        return True
    return False


def _is_text_grounded_value(text: str, value: str) -> bool:
    normalized_text = _normalize_simple(text)
    normalized_value = _normalize_simple(value)
    if not normalized_text or not normalized_value:
        return False
    return normalized_value in normalized_text


def _looks_like_contract_number(value: str) -> bool:
    candidate = str(value or "").strip()
    if len(candidate) < 3:
        return False
    normalized = _normalize_simple(candidate)
    if normalized in {"address", "invoice", "contract", "proforma invoice"}:
        return False
    has_digit = any(ch.isdigit() for ch in candidate)
    has_sep = any(ch in "-_/" for ch in candidate)
    return has_digit or has_sep


def _apply_contract_semantic_standardization(
    mapped_fields: list[dict[str, Any]],
    text: str,
    doc_type: str,
    uncertain_fields: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    if not _is_contract_like_doc(doc_type, text):
        return mapped_fields, uncertain_fields

    next_fields: list[dict[str, Any]] = []
    next_uncertain = list(uncertain_fields)
    semantic_blocks = _build_contract_semantic_blocks(text)
    for item in mapped_fields:
        annotated = dict(item)
        semantic = _infer_contract_semantic_signal(
            str(annotated.get("source_field_name", "") or ""),
            str(annotated.get("source_value", "") or ""),
            semantic_blocks,
        )
        annotated["semantic_block"] = semantic["semantic_block"]
        annotated["semantic_candidate_class"] = semantic["semantic_candidate_class"]
        annotated["candidate_standard_fields"] = semantic["candidate_standard_fields"]

        resolved = semantic.get("resolved_standard_field")
        if resolved and resolved != annotated.get("standard_field"):
            annotated["standard_field"] = resolved
            annotated["standard_label_cn"] = STANDARD_FIELD_LABELS.get(resolved, resolved)
            annotated["reason"] = (
                f"{annotated.get('reason', '').strip()} "
                f"Contract semantic block analysis suggests this content belongs to {STANDARD_FIELD_LABELS.get(resolved, resolved)}."
            ).strip()

        if semantic["semantic_candidate_class"] == "party_address_candidate" and len(semantic["candidate_standard_fields"]) > 1:
            annotated["uncertain"] = True
            if annotated["standard_field"] not in next_uncertain:
                next_uncertain.append(str(annotated["standard_field"]))
            annotated["reason"] = (
                f"{annotated.get('reason', '').strip()} "
                "This field label is unstable in contracts, so it was first grouped as a party/address candidate and kept for grouped confirmation."
            ).strip()

        next_fields.append(annotated)
    return next_fields, _unique_list(next_uncertain)


def _is_contract_like_doc(doc_type: str, text: str) -> bool:
    lowered = str(doc_type or "").lower()
    if "contract" in lowered:
        return True
    text_lower = str(text or "").lower()
    return any(token in text_lower for token in ("sales contract", "buyer", "seller", "trade term", "payment term"))


def _build_contract_semantic_blocks(text: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in str(text or "").splitlines()]
    blocks: list[dict[str, str]] = []
    current_label = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_label, current_lines
        if not current_label and not current_lines:
            return
        content = " ".join(line for line in current_lines if line).strip()
        blocks.append(
            {
                "label": current_label,
                "content": content,
                "semantic_block": _classify_contract_block(current_label, content),
            }
        )
        current_label = ""
        current_lines = []

    for raw in lines:
        if not raw:
            flush()
            continue
        if _looks_like_label_line(raw):
            flush()
            label, value = _split_label_value(raw)
            current_label = label
            if value:
                current_lines.append(value)
        else:
            current_lines.append(raw)
    flush()
    return blocks


def _classify_contract_block(label: str, content: str) -> str:
    normalized = _normalize_simple(f"{label} {content}")
    if _contains_phrase(normalized, "contract no", "invoice no", "reference no", "plant no", "factory no"):
        return "numbering_info_block"
    if _contains_phrase(normalized, "payment term", "prepayment", "payment", "deposit") or _contains_word(normalized, "tt", "lc"):
        return "payment_term_block"
    if _contains_phrase(normalized, "account no") or _contains_word(normalized, "bank", "swift", "beneficiary"):
        return "bank_info_block"
    if _contains_word(normalized, "port", "shipment", "delivery", "etd", "eta", "vessel"):
        return "logistics_block"
    if _contains_word(normalized, "product", "goods", "commodity", "description", "quantity", "weight"):
        return "goods_info_block"
    if _looks_like_party_address_content(content) or _contains_word(normalized, "buyer", "seller", "client", "consignee", "notify", "address", "shipper"):
        return "party_address_block"
    return "remark_block"


def _contains_phrase(text: str, *phrases: str) -> bool:
    return any(str(phrase or "").strip() and str(phrase).strip() in text for phrase in phrases)


def _contains_word(text: str, *tokens: str) -> bool:
    for token in tokens:
        marker = re.escape(str(token or "").strip())
        if marker and re.search(rf"\b{marker}\b", text):
            return True
    return False


def _looks_like_label_line(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped:
        return False
    return ":" in stripped or len(stripped.split()) <= 4


def _split_label_value(line: str) -> tuple[str, str]:
    stripped = str(line or "").strip()
    if ":" in stripped:
        label, value = stripped.split(":", 1)
        return label.strip(), value.strip()
    return stripped, ""


def _looks_like_party_address_content(content: str) -> bool:
    lowered = str(content or "").lower()
    company_markers = ("co.", "ltd", "llc", "corp", "company", "limited", "inc", "group")
    contact_markers = ("tel", "phone", "email", "@", "contact", "fax", "mobile")
    address_markers = ("road", "street", "ave", "avenue", "building", "room", "district", "city", "province", "china", "usa")
    return (
        any(token in lowered for token in company_markers)
        and any(token in lowered for token in address_markers)
    ) or any(token in lowered for token in contact_markers)


def _infer_contract_semantic_signal(
    source_field_name: str,
    source_value: str,
    semantic_blocks: list[dict[str, str]],
) -> dict[str, Any]:
    normalized_label = _normalize_simple(source_field_name)
    semantic_block = "remark_block"
    for block in semantic_blocks:
        if _normalize_simple(block.get("label", "")) == normalized_label and normalized_label:
            semantic_block = block.get("semantic_block", semantic_block)
            break
    if semantic_block == "remark_block" and _looks_like_party_address_content(source_value):
        semantic_block = "party_address_block"

    if semantic_block != "party_address_block":
        return {
            "semantic_block": semantic_block,
            "semantic_candidate_class": semantic_block,
            "candidate_standard_fields": [],
            "resolved_standard_field": None,
        }

    candidates: list[str] = []
    resolved: str | None = None
    for field_name, aliases in PARTY_ADDRESS_FIELD_ALIASES.items():
        if any(alias in normalized_label for alias in (_normalize_simple(item) for item in aliases)):
            candidates.append(field_name)
    if "address" in normalized_label and not candidates:
        candidates = list(PARTY_ADDRESS_FIELD_ALIASES.keys())

    if "buyer" in normalized_label or "client" in normalized_label or "customer" in normalized_label:
        resolved = "buyer_name_address"
    elif "consignee" in normalized_label or "deliver to" in normalized_label:
        resolved = "consignee_name_address"
    elif "notify" in normalized_label:
        resolved = "notify_party_name_address"
    elif "seller" in normalized_label or "shipper" in normalized_label or "exporter" in normalized_label:
        resolved = "shipper_name_address"

    if not candidates:
        candidates = [resolved] if resolved else list(PARTY_ADDRESS_FIELD_ALIASES.keys())
    if resolved and resolved not in candidates:
        candidates.insert(0, resolved)

    return {
        "semantic_block": "party_address_block",
        "semantic_candidate_class": "party_address_candidate",
        "candidate_standard_fields": _unique_list(candidates),
        "resolved_standard_field": resolved,
    }


def _unique_list(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        key = str(value or "")
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result

