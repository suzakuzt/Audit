from __future__ import annotations

import json

from llm.client import LLMResponse, LLMRuntimeConfig
from services.extractor_service import _fast_find_field, _match_field_with_regex, extract_document_with_options
from services.pdf_text_service import PDFTextResult


class DummyLLMClient:
    instances: list["DummyLLMClient"] = []

    def __init__(self, runtime_config=None, model=None) -> None:
        self.runtime_config = runtime_config
        self.model = model or (runtime_config.model if runtime_config else "dummy-model") or "dummy-model"
        self.prompts: list[tuple[str, str]] = []
        DummyLLMClient.instances.append(self)

    def complete_json(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        self.prompts.append((system_prompt, user_prompt))
        payload = {
            "doc_type": "Contract",
            "mapped_fields": [
                {
                    "standard_field": "contract_no",
                    "standard_label_cn": "???",
                    "source_field_name": "Contract No",
                    "source_value": "R 251/2025",
                    "confidence": 0.98,
                    "uncertain": False,
                    "reason": "matched",
                }
            ],
            "missing_fields": [],
            "uncertain_fields": [],
            "raw_summary": "ok",
        }
        return LLMResponse(text=json.dumps(payload, ensure_ascii=False), raw_payload={})

    def complete_text(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        raise AssertionError("repair path should not be used in this test")


class RepairingDummyLLMClient(DummyLLMClient):
    def complete_json(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        self.prompts.append((system_prompt, user_prompt))
        return LLMResponse(text="not-json", raw_payload={})

    def complete_text(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        payload = {
            "doc_type": "Contract",
            "mapped_fields": [],
            "missing_fields": ["contract_no"],
            "uncertain_fields": [],
            "raw_summary": "repaired",
        }
        return LLMResponse(text=json.dumps(payload, ensure_ascii=False), raw_payload={})


def test_extract_document_includes_ocr_context_in_prompt(monkeypatch) -> None:
    DummyLLMClient.instances.clear()
    monkeypatch.setattr("services.extractor_service.LLMClient", DummyLLMClient)

    pdf_result = PDFTextResult(
        file_name="scan.pdf",
        text="Contract No: R 251/2025\nExporter: BFC-USA LLC\nClient: Example Buyer",
        page_count=1,
        extraction_method="pdfplumber+paddleocr",
        is_text_valid=True,
        warnings=["Base PDF text extraction was weak; OCR will be used when enabled."],
        metadata={
            "source_kind": "scan_ocr",
            "ocr_status": "applied",
            "ocr_engine": "paddleocr",
            "ocr_model": "paddleocr-vl-remote",
            "ocr_transport": "http",
            "ocr_pages_used": 1,
            "pdfplumber_text_length": 0,
            "pypdf_text_length": 0,
        },
    )
    prompt = (
        "File: {file_name}\n"
        "Text:\n{document_text}\n\n"
        "Alias:\n{alias_active_json}\n\n"
        "Rule:\n{rule_active_json}\n\n"
        "Output JSON shape:\n{{\"doc_type\":\"\",\"mapped_fields\":[],\"missing_fields\":[],\"uncertain_fields\":[],\"raw_summary\":\"\"}}"
    )

    result = extract_document_with_options(
        pdf_result=pdf_result,
        prompt_file_name="unit-test.txt",
        prompt_text=prompt,
        use_alias_active=True,
        use_rule_active=True,
        alias_active_override={"contract_no": ["Contract No"]},
        rule_active_override=[{"field": "contract_no", "name": "must-extract-contract-no"}],
        llm_runtime_config=LLMRuntimeConfig(api_key="test-key", base_url="https://example.com", model="deepseek-chat"),
        focus_fields=["contract_no", "amount"],
    )

    client = DummyLLMClient.instances[-1]
    rendered_prompt = client.prompts[-1][1]
    assert "Document extraction context (OCR and text extraction summary)" in rendered_prompt
    assert "Alias precheck hints" in rendered_prompt
    assert "paddleocr-vl-remote" in rendered_prompt
    assert result.structured_data["mapped_fields"][0]["source_value"] == "R 251/2025"
    assert result.metadata["identification_sequence"][3] == "append_ocr_context"


def test_extract_document_includes_priority_field_note(monkeypatch) -> None:
    DummyLLMClient.instances.clear()
    monkeypatch.setattr("services.extractor_service.LLMClient", DummyLLMClient)

    pdf_result = PDFTextResult(
        file_name="scan.pdf",
        text="Plant No.: 2782\nContract No: R 251/2025",
        page_count=1,
        extraction_method="pdfplumber",
        is_text_valid=True,
        warnings=[],
        metadata={"source_kind": "digital_text", "ocr_status": "not_needed"},
    )

    extract_document_with_options(
        pdf_result=pdf_result,
        prompt_file_name="unit-test.txt",
        prompt_text="Text:\n{document_text}\nAlias:{alias_active_json}\nRule:{rule_active_json}",
        use_alias_active=False,
        use_rule_active=False,
        alias_active_override={},
        rule_active_override=[],
        llm_runtime_config=LLMRuntimeConfig(api_key="test-key", base_url="https://example.com", model="deepseek-chat"),
        focus_fields=["factory_no", "contract_no"],
        priority_fields=["factory_no"],
    )

    client = DummyLLMClient.instances[-1]
    rendered_prompt = client.prompts[-1][1]
    assert "Priority fields for this run" in rendered_prompt
    assert "factory_no" in rendered_prompt


def test_extract_document_repairs_json_once_when_needed(monkeypatch) -> None:
    RepairingDummyLLMClient.instances.clear()
    monkeypatch.setattr("services.extractor_service.LLMClient", RepairingDummyLLMClient)

    pdf_result = PDFTextResult(
        file_name="scan.pdf",
        text="Contract header only",
        page_count=1,
        extraction_method="paddleocr",
        is_text_valid=True,
        warnings=[],
        metadata={"source_kind": "scan_ocr", "ocr_status": "applied", "ocr_engine": "paddleocr"},
    )

    result = extract_document_with_options(
        pdf_result=pdf_result,
        prompt_file_name="unit-test.txt",
        prompt_text="Text:\n{document_text}\nAlias:{alias_active_json}\nRule:{rule_active_json}",
        use_alias_active=False,
        use_rule_active=False,
        alias_active_override={},
        rule_active_override=[],
        llm_runtime_config=LLMRuntimeConfig(api_key="test-key", base_url="https://example.com", model="deepseek-chat"),
        focus_fields=None,
    )

    assert result.repair_raw_response is not None
    assert "JSON" in result.warnings[-1]
    assert result.structured_data["missing_fields"] == ["contract_no"]


def test_extract_document_uses_alias_fast_path_when_all_focus_fields_match(monkeypatch) -> None:
    DummyLLMClient.instances.clear()
    monkeypatch.setattr("services.extractor_service.LLMClient", DummyLLMClient)

    pdf_result = PDFTextResult(
        file_name="scan.pdf",
        text="PROFORMA INVOICE: BM 740/2025",
        page_count=1,
        extraction_method="pdfplumber",
        is_text_valid=True,
        warnings=[],
        metadata={"source_kind": "digital_text", "ocr_status": "not_needed"},
    )

    result = extract_document_with_options(
        pdf_result=pdf_result,
        prompt_file_name="unit-test.txt",
        prompt_text="Text:\n{document_text}\nAlias:{alias_active_json}\nRule:{rule_active_json}",
        use_alias_active=True,
        use_rule_active=False,
        alias_active_override={"contract_no": ["PROFORMA INVOICE"]},
        rule_active_override=[],
        llm_runtime_config=LLMRuntimeConfig(api_key="test-key", base_url="https://example.com", model="deepseek-chat"),
        focus_fields=["contract_no"],
    )

    assert DummyLLMClient.instances == []
    assert result.metadata["decision_mode"] == "alias_fast_path"
    assert result.structured_data["mapped_fields"][0]["source_field_name"] == "PROFORMA INVOICE"
    assert result.structured_data["mapped_fields"][0]["source_value"] == "BM 740/2025"


def test_extract_document_keeps_llm_path_when_alias_match_is_incomplete(monkeypatch) -> None:
    DummyLLMClient.instances.clear()
    monkeypatch.setattr("services.extractor_service.LLMClient", DummyLLMClient)

    pdf_result = PDFTextResult(
        file_name="scan.pdf",
        text="Contract No: R 251/2025\nExporter: BFC-USA LLC\nClient: Example Buyer",
        page_count=1,
        extraction_method="pdfplumber",
        is_text_valid=True,
        warnings=[],
        metadata={"source_kind": "digital_text", "ocr_status": "not_needed"},
    )

    result = extract_document_with_options(
        pdf_result=pdf_result,
        prompt_file_name="unit-test.txt",
        prompt_text="Text:\n{document_text}\nAlias:{alias_active_json}\nRule:{rule_active_json}",
        use_alias_active=True,
        use_rule_active=False,
        alias_active_override={"contract_no": ["Contract No"]},
        rule_active_override=[],
        llm_runtime_config=LLMRuntimeConfig(api_key="test-key", base_url="https://example.com", model="deepseek-chat"),
        focus_fields=["contract_no", "amount"],
    )

    assert len(DummyLLMClient.instances) == 1
    assert result.metadata["decision_mode"] == "llm_full_path"


def test_match_field_with_regex_extracts_factory_number() -> None:
    result = _match_field_with_regex("factory_no", "Plant No.: 2782")

    assert result is not None
    assert result["standard_field"] == "factory_no"
    assert result["source_field_name"] == "Plant No"
    assert result["source_value"] == "2782"


def test_fast_find_field_extracts_payment_term_from_ocr_text() -> None:
    text = "PAYMENT TERMS: 40% IN ADVANCE AND 60% AGAINST SCAN OF ORIGINAL DOCUMENTS"

    result = _fast_find_field("payment_term", text, {})

    assert result is not None
    assert result["standard_field"] == "payment_term"
    assert result["source_value"] == "40% IN ADVANCE AND 60% AGAINST SCAN OF ORIGINAL DOCUMENTS"


def test_fast_find_field_extracts_multiline_beneficiary_bank() -> None:
    text = "\n".join(
        [
            "BENEFICIARY BANK:",
            "BANK OF CHINA SHANGHAI BRANCH",
            "SWIFT: BKCHCNBJ300",
            "PAYMENT TERMS: T/T",
        ]
    )

    result = _fast_find_field("beneficiary_bank", text, {})

    assert result is not None
    assert result["standard_field"] == "beneficiary_bank"
    assert result["source_value"] == "BANK OF CHINA SHANGHAI BRANCH | SWIFT: BKCHCNBJ300"


def test_fast_find_field_maps_client_block_to_party_address_standard_field() -> None:
    text = "\n".join(
        [
            "Client",
            "ABC FOODS LLC",
            "123 Market Street, Los Angeles, USA",
            "Tel: +1 555 0100",
            "Payment Terms: 40% IN ADVANCE",
        ]
    )

    result = _fast_find_field("consignee_name_address", text, {})

    assert result is not None
    assert result["standard_field"] == "consignee_name_address"
    assert result["source_field_name"] == "client"
    assert "ABC FOODS LLC" in result["source_value"]
    assert "123 Market Street" in result["source_value"]
