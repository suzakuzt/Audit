from pathlib import Path

from sqlalchemy import select


from audit_system.db.session import SessionLocal
from audit_system.models import AliasEntry, ExtractionRun, ExtractionRunDocument, ExtractionRunField, PromptEvolutionSample, RuleEntry, RulePatch
from services.run_store import apply_manual_confirmations, persist_extraction_run
from services.extractor_service import _apply_field_guardrails, _match_field_with_regex, _repair_contract_no_mapping
from audit_system.api.routes.document_compare import _collect_alias_candidates


class DummyResult:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self):
        return self._payload


SAMPLE_TEXT_PDF = b"""%PDF-1.1
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 97 >>
stream
BT
/F1 12 Tf
40 100 Td
(PROFORMA INVOICE - BM740/2025) Tj
0 -18 Td
(TOTAL US$ 156.750,00) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000010 00000 n 
0000000063 00000 n 
0000000122 00000 n 
0000000248 00000 n 
0000000396 00000 n 
trailer
<< /Root 1 0 R /Size 6 >>
startxref
466
%%EOF
"""


def test_compare_page(client, monkeypatch) -> None:
    prompt_path = Path("llm/prompts/extract_prompt_v1.txt")
    monkeypatch.setattr(
        "audit_system.api.routes.document_compare.list_prompt_versions",
        lambda: [prompt_path],
    )

    response = client.get("/")

    assert response.status_code == 200
    assert "批量核心字段提取验证器" in response.text
    assert "开始批量提取验证" in response.text


def test_document_foundation_rejects_non_pdf(client) -> None:
    response = client.post(
        "/api/v1/document-foundation/validate",
        files=[("files", ("a.txt", b"hello", "text/plain"))],
    )

    assert response.status_code == 400


def test_document_foundation_endpoint(client, monkeypatch) -> None:
    monkeypatch.setattr("audit_system.api.routes.document_compare.settings.llm_api_key", "fake-key")
    monkeypatch.setattr(
        "audit_system.api.routes.document_compare.extract_pdf_text",
        lambda file_name, content, ocr_config=None: DummyResult(
            {
                "file_name": file_name,
                "text": "Invoice No: INV-001\nTotal Amount: USD 1000",
                "page_count": 1,
                "extraction_method": "pdfplumber",
                "is_text_valid": True,
                "warnings": [],
            }
        ),
    )
    monkeypatch.setattr(
        "audit_system.api.routes.document_compare.extract_document_with_options",
        lambda **kwargs: DummyResult(
            {
                "file_name": kwargs["pdf_result"].model_dump()["file_name"],
                "raw_model_response": "{\"ok\": true}",
                "warnings": [],
                "structured_data": {
                    "doc_type": "invoice",
                    "mapped_fields": [
                        {
                            "standard_field": "contract_no",
                            "standard_label_cn": "合同号",
                            "source_field_name": "Invoice No",
                            "source_value": "INV-001",
                            "confidence": 0.92,
                            "uncertain": False,
                            "reason": "命中 invoice 编号语义",
                        },
                        {
                            "standard_field": "amount",
                            "standard_label_cn": "金额",
                            "source_field_name": "Total Amount",
                            "source_value": "USD 1000",
                            "confidence": 0.88,
                            "uncertain": True,
                            "reason": "金额字段仍需业务确认",
                        },
                    ],
                    "missing_fields": ["product_name"],
                    "uncertain_fields": ["amount"],
                    "raw_summary": "提炼出编号与金额字段",
                },
            }
        ),
    )
    monkeypatch.setattr(
        "audit_system.api.routes.document_compare.load_knowledge_file",
        lambda path: {
            "contract_no": ["Invoice No"],
            "amount": ["Amount"]
        } if path.name == "alias_active.json" else (
            [{"standard_field": "amount", "alias": "Total Amount", "source": "历史候选"}] if path.name == "alias_candidates.json" else (
                [{"name": "global_amount_rule", "field": "amount", "description": "金额字段判别规则"}] if path.name == "rule_active.json" else [{"name": "missing_product_rule", "field": "product_name", "description": "品名缺失规则"}]
            )
        ),
    )
    monkeypatch.setattr(
        "audit_system.api.routes.document_compare.list_prompt_versions",
        lambda: [Path("llm/prompts/extract_prompt_v1.txt")],
    )

    response = client.post(
        "/api/v1/document-foundation/validate",
        data={
            "prompt_text": "custom prompt",
            "llm_api_key": "front-key",
            "llm_base_url": "https://api.deepseek.com",
            "llm_model": "deepseek-chat",
            "ocr_model": "deepseek-chat",
            "llm_timeout": "180",
            "enable_ocr": "true",
            "force_ocr": "false",
            "prompt_file_name": "extract_prompt_v1.txt",
            "use_alias_active": "true",
            "use_rule_active": "true",
        },
        files=[("files", ("invoice.pdf", SAMPLE_TEXT_PDF, "application/pdf"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_options"]["prompt_file_name"] == "extract_prompt_v1.txt"
    assert payload["batch_summary"]["total_documents"] == 1
    assert payload["batch_summary"]["field_stats"][0]["field"] == "amount"
    assert payload["version_record"]["prompt_file_name"] == "extract_prompt_v1.txt"
    assert payload["experiment_record"]["run_dir"]
    assert "has_previous" in payload["comparison_summary"]
    assert payload["documents"][0]["doc_type"] == "invoice"
    assert payload["documents"][0]["alias_hits"][0]["alias"] == "Invoice No"
    assert payload["documents"][0]["rule_hits"][0]["name"] == "global_amount_rule"
    assert payload["documents"][0]["alias_candidates"][0]["alias"] == "Total Amount"
    assert payload["documents"][0]["rule_candidates"][0]["field"] == "product_name"

    assert payload["experiment_record"]["db_run_id"] > 0
    with SessionLocal() as db:
        assert db.scalar(select(ExtractionRun).where(ExtractionRun.id == payload["experiment_record"]["db_run_id"])) is not None
        assert db.scalar(select(ExtractionRunDocument)) is not None
        assert db.scalar(select(ExtractionRunField)) is not None
        assert db.scalar(select(AliasEntry)) is not None
        assert db.scalar(select(RuleEntry)) is not None


def test_document_foundation_evaluate_endpoint(client) -> None:
    response = client.post(
        "/api/v1/document-foundation/evaluate",
        json={
            "experiment_record": {"run_dir": "", "previous_run_dir": ""},
            "documents": [
                {
                    "filename": "invoice.pdf",
                    "manual_confirmation_rows": [
                        {"standard_field": "contract_no", "ai_value": "INV-001", "confirmed_value": "INV-001"},
                        {"standard_field": "amount", "ai_value": "USD 1000", "confirmed_value": "USD 900"},
                        {"standard_field": "product_name", "ai_value": "", "confirmed_value": "Fish Oil"},
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evaluation_summary"]["total_documents"] == 1
    assert payload["evaluation_summary"]["correct_fields"] == 1
    assert payload["evaluation_summary"]["wrong_fields"] == 1
    assert payload["evaluation_summary"]["missing_fields"] == 1
    assert payload["evaluation_comparison"]["has_previous"] is False
    assert payload["evaluation_record"]["duplicate_alias_count"] == 0
    assert payload["evolution_summary"]["created_samples"] >= 1
    assert payload["evolution_summary"]["created_patches"] >= 1

    with SessionLocal() as db:
        assert db.scalar(select(PromptEvolutionSample)) is not None
        assert db.scalar(select(RulePatch)) is not None





def test_document_foundation_evaluate_promotes_alias(client, monkeypatch) -> None:
    monkeypatch.setattr("audit_system.api.routes.document_compare.settings.llm_api_key", "fake-key")
    monkeypatch.setattr(
        "audit_system.api.routes.document_compare.extract_pdf_text",
        lambda file_name, content, ocr_config=None: DummyResult(
            {
                "file_name": file_name,
                "text": "Contract Ref: CN-7788",
                "page_count": 1,
                "extraction_method": "pdfplumber",
                "is_text_valid": True,
                "warnings": [],
            }
        ),
    )
    monkeypatch.setattr(
        "audit_system.api.routes.document_compare.extract_document_with_options",
        lambda **kwargs: DummyResult(
            {
                "file_name": kwargs["pdf_result"].model_dump()["file_name"],
                "raw_model_response": "{\"ok\": true}",
                "warnings": [],
                "structured_data": {
                    "doc_type": "contract",
                    "mapped_fields": [
                        {
                            "standard_field": "contract_no",
                            "standard_label_cn": "???",
                            "source_field_name": "Contract Ref",
                            "source_value": "CN-7788",
                            "confidence": 0.97,
                            "uncertain": False,
                            "reason": "????????",
                        }
                    ],
                    "missing_fields": [],
                    "uncertain_fields": [],
                    "raw_summary": "????????",
                },
            }
        ),
    )
    monkeypatch.setattr(
        "audit_system.api.routes.document_compare.load_knowledge_file",
        lambda path: {} if "alias" in path.name else [],
    )
    monkeypatch.setattr(
        "services.extractor_service.load_knowledge_file",
        lambda path: {} if "alias" in path.name else [],
    )
    monkeypatch.setattr(
        "audit_system.api.routes.document_compare.list_prompt_versions",
        lambda: [Path("llm/prompts/extract_prompt_v1.txt")],
    )

    validate = client.post(
        "/api/v1/document-foundation/validate",
        data={
            "prompt_text": "custom prompt",
            "llm_api_key": "front-key",
            "llm_base_url": "https://api.deepseek.com",
            "llm_model": "deepseek-chat",
            "ocr_model": "deepseek-chat",
            "llm_timeout": "180",
            "prompt_file_name": "extract_prompt_v1.txt",
            "use_alias_active": "true",
            "use_rule_active": "true",
        },
        files=[("files", ("contract.pdf", SAMPLE_TEXT_PDF, "application/pdf"))],
    )

    assert validate.status_code == 200
    payload = validate.json()
    documents = payload["documents"]
    documents[0]["manual_confirmation_rows"][0]["promote_alias"] = True
    evaluate = client.post(
        "/api/v1/document-foundation/evaluate",
        json={
            "experiment_record": payload["experiment_record"],
            "documents": documents,
        },
    )

    assert evaluate.status_code == 200
    evaluation_payload = evaluate.json()
    assert evaluation_payload["evaluation_record"]["updated_fields"] >= 1
    assert evaluation_payload["evaluation_record"]["promoted_aliases"] >= 0
    assert evaluation_payload["evaluation_record"]["duplicate_alias_count"] == 0

    with SessionLocal() as db:
        active_alias = db.scalar(
            select(AliasEntry).where(
                AliasEntry.standard_field == "contract_no",
                AliasEntry.alias_text == "Contract Ref",
                AliasEntry.status == "active",
            )
        )
        assert active_alias is not None



def test_persist_extraction_run_skips_duplicate_alias_candidates() -> None:
    documents = [
        {
            "filename": "invoice.pdf",
            "doc_type": "invoice",
            "raw_summary": "summary",
            "raw_model_response": "{}",
            "warnings": [],
            "raw_text_result": {
                "extraction_method": "pdfplumber",
                "page_count": 1,
                "is_text_valid": True,
            },
            "standard_mappings": [
                {
                    "standard_field": "contract_no",
                    "standard_label_cn": "???",
                    "source_field_name": "Contract Ref",
                    "source_value": "CN-001",
                    "confidence": 0.98,
                    "reason": "matched",
                }
            ],
            "missing_fields": [],
            "uncertain_fields": [],
            "manual_confirmation_rows": [
                {
                    "standard_field": "contract_no",
                    "standard_label_cn": "???",
                    "ai_value": "CN-001",
                    "confirmed_value": "CN-001",
                }
            ],
            "alias_candidates": [
                {"standard_field": "contract_no", "alias": "Contract Ref", "reason": "candidate 1"},
                {"standard_field": "contract_no", "alias": "  Contract   Ref  ", "reason": "candidate 2"},
            ],
            "rule_candidates": [],
        }
    ]

    persist_extraction_run(
        run_key="run-dup-alias-candidate-002",
        output_dir="outputs/test",
        batch_summary={"total_documents": 1, "text_valid_documents": 1, "document_coverage_rate": 1.0},
        version_record={"prompt_file_name": "extract_prompt_v1.txt", "model_name": "test-model"},
        documents=documents,
    )

    with SessionLocal() as db:
        rows = db.scalars(
            select(AliasEntry).where(
                AliasEntry.standard_field == "contract_no",
                AliasEntry.alias_text == "Contract Ref",
                AliasEntry.status == "candidate",
            )
        ).all()
        assert len(rows) == 1



def test_apply_manual_confirmations_skips_duplicate_active_alias() -> None:
    with SessionLocal() as db:
        run = ExtractionRun(
            run_key="run-dup-active-alias-002",
            output_dir="outputs/test",
            prompt_name="extract_prompt_v1.txt",
            model_name="test-model",
            use_alias_active=True,
            use_rule_active=True,
            ocr_enabled=False,
            force_ocr=False,
            total_documents=1,
            text_valid_documents=1,
        )
        db.add(run)
        db.flush()

        document = ExtractionRunDocument(
            run_id=run.id,
            filename="invoice.pdf",
            page_count=1,
            is_text_valid=True,
        )
        db.add(document)
        db.flush()

        field = ExtractionRunField(
            document_id=document.id,
            standard_field="contract_no",
            standard_label_cn="???",
            source_field_name="  Contract   Ref  ",
            source_value="CN-001",
            review_status="mapped",
        )
        db.add(field)
        db.flush()

        db.add(
            AliasEntry(
                standard_field="contract_no",
                alias_text="Contract Ref",
                status="active",
                source_type="manual_confirmed",
                alias_text_normalized="contract ref",
                extraction_run_field_id=field.id,
            )
        )
        db.commit()
        document_id = document.id
        field_id = field.id

        payload = [
            {
                "db_document_id": document_id,
                "filename": "invoice.pdf",
                "manual_confirmation_rows": [
                    {
                        "db_field_id": field_id,
                        "standard_field": "contract_no",
                        "ai_value": "CN-001",
                        "confirmed_value": "CN-001",
                        "promote_alias": True,
                    }
                ],
            }
        ]

    result = apply_manual_confirmations(payload)

    assert result["promoted_aliases"] == 0
    assert result["duplicate_alias_count"] == 1
    with SessionLocal() as db:
        rows = db.scalars(
            select(AliasEntry).where(
                AliasEntry.standard_field == "contract_no",
                AliasEntry.alias_text == "Contract Ref",
                AliasEntry.status == "active",
            )
        ).all()
        assert len(rows) == 1


def test_apply_manual_confirmations_uses_manual_alias_name_and_reports_duplicate(client) -> None:
    with SessionLocal() as db:
        run = ExtractionRun(
            run_key="run-manual-alias-sync-001",
            output_dir="outputs/test",
            prompt_name="extract_prompt_v1.txt",
            model_name="test-model",
            use_alias_active=True,
            use_rule_active=True,
            ocr_enabled=False,
            force_ocr=False,
            total_documents=1,
            text_valid_documents=1,
        )
        db.add(run)
        db.flush()

        document = ExtractionRunDocument(
            run_id=run.id,
            filename="invoice.pdf",
            page_count=1,
            is_text_valid=True,
        )
        db.add(document)
        db.flush()

        field = ExtractionRunField(
            document_id=document.id,
            standard_field="contract_no",
            standard_label_cn="???",
            source_field_name="Contract Ref",
            source_value="CN-001",
            review_status="mapped",
        )
        db.add(field)
        db.flush()

        db.add(
            AliasEntry(
                standard_field="contract_no",
                alias_text="Customer Contract No",
                alias_text_normalized="customer contract no",
                status="active",
                source_type="manual_confirmed",
                extraction_run_field_id=field.id,
            )
        )
        db.commit()
        document_id = document.id
        field_id = field.id

    result = apply_manual_confirmations([
        {
            "db_document_id": document_id,
            "filename": "invoice.pdf",
            "standard_mappings": [
                {
                    "standard_field": "contract_no",
                    "source_field_name": "Customer Contract No",
                    "source_value": "CN-001",
                    "confidence": 0.99,
                    "reason": "manual updated alias",
                }
            ],
            "manual_confirmation_rows": [
                {
                    "db_field_id": field_id,
                    "standard_field": "contract_no",
                    "ai_value": "CN-001",
                    "confirmed_value": "CN-001",
                    "promote_alias": True,
                }
            ],
        }
    ])

    assert result["promoted_aliases"] == 0
    assert result["duplicate_alias_count"] == 1
    assert result["duplicate_aliases"][0]["alias"] == "Customer Contract No"

    with SessionLocal() as db:
        refreshed_field = db.get(ExtractionRunField, field_id)
        assert refreshed_field is not None
        assert refreshed_field.source_field_name == "Customer Contract No"


def test_apply_manual_confirmations_promotes_candidate_alias_without_duplicate() -> None:
    with SessionLocal() as db:
        run = ExtractionRun(
            run_key="run-candidate-to-active-001",
            output_dir="outputs/test",
            prompt_name="extract_prompt_v1.txt",
            model_name="test-model",
            use_alias_active=True,
            use_rule_active=True,
            ocr_enabled=False,
            force_ocr=False,
            total_documents=1,
            text_valid_documents=1,
        )
        db.add(run)
        db.flush()

        document = ExtractionRunDocument(
            run_id=run.id,
            filename="invoice.pdf",
            page_count=1,
            is_text_valid=True,
        )
        db.add(document)
        db.flush()

        field = ExtractionRunField(
            document_id=document.id,
            standard_field="contract_no",
            standard_label_cn="???",
            source_field_name="Contract Ref",
            source_value="CN-001",
            review_status="mapped",
        )
        db.add(field)
        db.flush()

        db.add(
            AliasEntry(
                standard_field="contract_no",
                alias_text="Contract Ref",
                alias_text_normalized="contract ref",
                status="candidate",
                source_type="extraction_run",
                extraction_run_field_id=field.id,
            )
        )
        db.commit()
        document_id = document.id
        field_id = field.id

    result = apply_manual_confirmations([
        {
            "db_document_id": document_id,
            "filename": "invoice.pdf",
            "manual_confirmation_rows": [
                {
                    "db_field_id": field_id,
                    "standard_field": "contract_no",
                    "ai_value": "CN-001",
                    "confirmed_value": "CN-001",
                    "promote_alias": True,
                }
            ],
        }
    ])

    assert result["promoted_aliases"] == 1
    assert result["duplicate_alias_count"] == 0
    with SessionLocal() as db:
        active_rows = db.scalars(
            select(AliasEntry).where(
                AliasEntry.standard_field == "contract_no",
                AliasEntry.alias_text == "Contract Ref",
                AliasEntry.status == "active",
            )
        ).all()
        candidate_rows = db.scalars(
            select(AliasEntry).where(
                AliasEntry.standard_field == "contract_no",
                AliasEntry.alias_text == "Contract Ref",
                AliasEntry.status == "candidate",
            )
        ).all()
        assert len(active_rows) == 1
        assert len(candidate_rows) == 0



def test_contract_no_regex_matches_multiline_proforma_invoice_line() -> None:
    text = """Header
ADDRESS
PROFORMA INVOICE L5135
DATE 04/24/2025
"""

    result = _match_field_with_regex("contract_no", text)

    assert result is not None
    assert result["source_field_name"] == "PROFORMA INVOICE"
    assert result["source_value"] == "L5135"



def test_repair_contract_no_mapping_recovers_value_from_proforma_title_when_no_explicit_label_exists() -> None:
    text = """Proforma Invoice
ADDRESS
PROFORMA INVOICE L5135
DATE 04/24/2025
"""
    broken_item = {
        "standard_field": "contract_no",
        "standard_label_cn": "???",
        "source_field_name": "proforma invoice",
        "source_value": "",
        "confidence": 0.2,
        "uncertain": True,
        "reason": "AI picked the document title instead of a real field label.",
    }

    repaired = _repair_contract_no_mapping(broken_item, text, {})

    assert repaired is not None
    assert repaired["source_field_name"] == "PROFORMA INVOICE"
    assert repaired["source_value"] == "L5135"



def test_contract_no_regex_prefers_real_contract_label() -> None:
    text = """Header
Contract No.: R 251/2025
PROFORMA INVOICE L5135
"""

    result = _match_field_with_regex("contract_no", text)

    assert result is not None
    assert result["source_field_name"] == "Contract No"
    assert result["source_value"] == "R 251/2025"



def test_repair_contract_no_mapping_preserves_explicit_field_name() -> None:
    text = """Header
Contract No.: R 251/2025
PROFORMA INVOICE L5135
"""
    broken_item = {
        "standard_field": "contract_no",
        "standard_label_cn": "???",
        "source_field_name": "Contract No",
        "source_value": "",
        "confidence": 0.2,
        "uncertain": True,
        "reason": "OCR recognized the label but AI missed the value.",
    }

    repaired = _repair_contract_no_mapping(broken_item, text, {})

    assert repaired is not None
    assert repaired["source_field_name"] == "Contract No"
    assert repaired["source_value"] == "R 251/2025"



def test_alias_candidates_do_not_override_current_document_match_with_history_pool() -> None:
    mapped = [
        {
            "standard_field": "contract_no",
            "source_field_name": "Contract No",
            "source_value": "R 251/2025",
        }
    ]
    alias_active = {"contract_no": []}
    alias_pool = [
        {"standard_field": "contract_no", "alias": "PROFORMA INVOICE NUMBER", "reason": "????"}
    ]

    result = _collect_alias_candidates(mapped, [], [], alias_active, alias_pool)

    assert result == [
        {
            "standard_field": "contract_no",
            "alias": "Contract No",
            "reason": "????????????????????",
        }
    ]



def test_alias_candidates_ignore_history_pool_for_missing_rows_in_main_result() -> None:
    mapped = []
    alias_active = {"contract_no": []}
    alias_pool = [
        {"standard_field": "contract_no", "alias": "PROFORMA INVOICE NUMBER", "reason": "????"}
    ]

    result = _collect_alias_candidates(mapped, ["contract_no"], [], alias_active, alias_pool)

    assert result == []


def test_apply_field_guardrails_recovers_missing_contract_no_from_ocr_text() -> None:
    structured = {
        "mapped_fields": [],
        "missing_fields": ["contract_no"],
        "uncertain_fields": [],
    }

    class DummyPDFResult:
        text = "Header\nPROFORMA INVOICE - BM 740/2025\nFooter"

    guarded = _apply_field_guardrails(structured, DummyPDFResult(), {})

    mapping = next((item for item in guarded["mapped_fields"] if item.get("standard_field") == "contract_no"), None)
    assert mapping is not None
    assert mapping["source_field_name"] == "PROFORMA INVOICE"
    assert mapping["source_value"] == "BM 740/2025"
    assert "contract_no" not in guarded["missing_fields"]


def test_repair_contract_no_mapping_rejects_value_not_grounded_in_text() -> None:
    text = """Header
Contract No.: R 251/2025
Footer
"""
    broken_item = {
        "standard_field": "contract_no",
        "standard_label_cn": "???",
        "source_field_name": "Contract No",
        "source_value": "FAKE-9999",
        "confidence": 0.95,
        "uncertain": False,
        "reason": "AI hallucinated a value.",
    }

    repaired = _repair_contract_no_mapping(broken_item, text, {})

    assert repaired is not None
    assert repaired["source_field_name"] == "Contract No"
    assert repaired["source_value"] == "R 251/2025"


def test_apply_field_guardrails_drops_ungrounded_contract_no_value() -> None:
    structured = {
        "mapped_fields": [
            {
                "standard_field": "contract_no",
                "standard_label_cn": "???",
                "source_field_name": "Contract No",
                "source_value": "FAKE-9999",
                "confidence": 0.95,
                "uncertain": False,
                "reason": "AI hallucinated a value.",
            }
        ],
        "missing_fields": [],
        "uncertain_fields": [],
    }

    class DummyPDFResult:
        text = "Header\nFooter only\n"

    guarded = _apply_field_guardrails(structured, DummyPDFResult(), {})

    assert guarded["mapped_fields"] == []
    assert "contract_no" in guarded["missing_fields"]


def test_contract_no_regex_matches_prefixed_merged_proforma_invoice_line() -> None:
    text = """Header
ADDRESS PROFORMA INVOICEL5135
DATE 04/24/2025
"""

    result = _match_field_with_regex("contract_no", text)

    assert result is not None
    assert result["source_field_name"] == "PROFORMA INVOICE"
    assert result["source_value"] == "L5135"


def test_apply_field_guardrails_does_not_recover_missing_contract_no_from_loose_alias_scan() -> None:
    structured = {
        "mapped_fields": [],
        "missing_fields": ["contract_no"],
        "uncertain_fields": [],
    }

    class DummyPDFResult:
        text = "Header\nContract Ref\nL5135\nFooter"

    guarded = _apply_field_guardrails(structured, DummyPDFResult(), {"contract_no": ["Contract Ref"]})

    assert guarded["mapped_fields"] == []
    assert "contract_no" in guarded["missing_fields"]


def test_apply_manual_confirmations_only_promotes_field_name_alias_and_ignores_value_case() -> None:
    with SessionLocal() as db:
        run = ExtractionRun(
            run_key="run-alias-name-only-001",
            output_dir="outputs/test",
            prompt_name="extract_prompt_v1.txt",
            model_name="test-model",
            use_alias_active=True,
            use_rule_active=True,
            ocr_enabled=False,
            force_ocr=False,
            total_documents=1,
            text_valid_documents=1,
        )
        db.add(run)
        db.flush()

        document = ExtractionRunDocument(
            run_id=run.id,
            filename="invoice.pdf",
            page_count=1,
            is_text_valid=True,
        )
        db.add(document)
        db.flush()

        field = ExtractionRunField(
            document_id=document.id,
            standard_field="contract_no",
            standard_label_cn="???",
            source_field_name="PROFORMA INVOICE",
            source_value="BM 740/2025",
            review_status="mapped",
        )
        db.add(field)
        db.flush()

        db.add(
            AliasEntry(
                standard_field="contract_no",
                alias_text="proforma invoice",
                alias_text_normalized="proforma invoice",
                status="active",
                source_type="manual_confirmed",
                extraction_run_field_id=field.id,
            )
        )
        db.commit()
        document_id = document.id
        field_id = field.id

    result = apply_manual_confirmations([
        {
            "db_document_id": document_id,
            "filename": "invoice.pdf",
            "standard_mappings": [
                {
                    "standard_field": "contract_no",
                    "source_field_name": "PROFORMA INVOICE",
                    "source_value": "BM 740/2025",
                    "confidence": 0.98,
                    "reason": "manual updated alias",
                }
            ],
            "manual_confirmation_rows": [
                {
                    "db_field_id": field_id,
                    "standard_field": "contract_no",
                    "ai_value": "BM 740/2025",
                    "confirmed_value": "BM 740/2025",
                    "promote_alias": True,
                }
            ],
        }
    ])

    assert result["promoted_aliases"] == 0
    assert result["duplicate_alias_count"] == 1
    assert result["duplicate_aliases"][0]["alias"] == "PROFORMA INVOICE"

    with SessionLocal() as db:
        alias_rows = db.scalars(
            select(AliasEntry).where(AliasEntry.standard_field == "contract_no")
        ).all()
        assert len(alias_rows) == 1
        assert alias_rows[0].alias_text.lower() == "proforma invoice"
        assert all((row.alias_text or "") != "BM 740/2025" for row in alias_rows)


def test_build_visual_fallback_pages_uses_ocr_preview_images() -> None:
    from audit_system.api.routes.document_compare import _build_visual_fallback_pages

    pages = _build_visual_fallback_pages({
        'ocr_preview_images': [
            {
                'page_number': 1,
                'image_data_url': 'https://example.com/page-1.jpg',
                'page_width': 0,
                'page_height': 0,
                'words': [],
            }
        ]
    })

    assert len(pages) == 1
    assert pages[0]['image_data_url'] == 'https://example.com/page-1.jpg'


def test_merge_visual_pages_with_fallback_injects_ocr_blocks() -> None:
    from audit_system.api.routes.document_compare import _merge_visual_pages_with_fallback

    merged = _merge_visual_pages_with_fallback(
        [
            {
                'page_number': 1,
                'image_data_url': 'data:image/png;base64,local',
                'page_width': 595,
                'page_height': 842,
                'words': [],
                'blocks': [],
            }
        ],
        {
            'ocr_preview_images': [
                {
                    'page_number': 1,
                    'image_data_url': 'https://example.com/page-1.jpg',
                    'page_width': 1191,
                    'page_height': 1684,
                    'words': [],
                    'blocks': [
                        {
                            'text': 'Contract No.: R 251/2025',
                            'x0': 474,
                            'top': 143,
                            'x1': 716,
                            'bottom': 166,
                        }
                    ],
                }
            ]
        },
    )

    assert len(merged) == 1
    assert merged[0]['image_data_url'] == 'data:image/png;base64,local'
    assert merged[0]['page_width'] == 1191
    assert len(merged[0]['blocks']) == 1
    assert merged[0]['blocks'][0]['text'] == 'Contract No.: R 251/2025'


def test_merge_visual_pages_with_fallback_backfills_missing_image_url() -> None:
    from audit_system.api.routes.document_compare import _merge_visual_pages_with_fallback

    merged = _merge_visual_pages_with_fallback(
        [
            {
                'page_number': 1,
                'image_data_url': '',
                'page_width': 595,
                'page_height': 842,
                'words': [{'text': 'local-word'}],
                'blocks': [],
            }
        ],
        {
            'ocr_preview_images': [
                {
                    'page_number': 1,
                    'image_data_url': 'https://example.com/page-1.jpg',
                    'page_width': 1191,
                    'page_height': 1684,
                    'words': [],
                    'blocks': [],
                }
            ]
        },
    )

    assert len(merged) == 1
    assert merged[0]['image_data_url'] == 'https://example.com/page-1.jpg'
    assert merged[0]['words'][0]['text'] == 'local-word'


def test_process_uploaded_document_retries_with_ocr_when_focus_fields_are_missing(monkeypatch) -> None:
    from audit_system.api.routes.document_compare import _process_uploaded_document
    from llm.client import LLMRuntimeConfig

    pdf_calls = []

    def fake_extract_pdf_text(file_name, content, ocr_config=None):
        forced = bool(getattr(ocr_config, 'force_ocr', False))
        pdf_calls.append(forced)
        if forced:
            return DummyResult({
                'file_name': file_name,
                'text': 'Contract No: OCR-001',
                'page_count': 1,
                'extraction_method': 'pdfplumber+paddleocr',
                'is_text_valid': True,
                'warnings': [],
                'metadata': {'source_kind': 'scan_ocr', 'ocr_status': 'applied', 'ocr_engine': 'paddleocr'},
            })
        return DummyResult({
            'file_name': file_name,
            'text': 'Proforma Invoice header only',
            'page_count': 1,
            'extraction_method': 'pdfplumber',
            'is_text_valid': True,
            'warnings': [],
            'metadata': {'source_kind': 'digital_text', 'ocr_status': 'not_needed'},
        })

    def fake_extract_document_with_options(**kwargs):
        pdf_payload = kwargs['pdf_result'].model_dump()
        metadata = pdf_payload.get('metadata', {})
        if metadata.get('source_kind') == 'scan_ocr':
            return DummyResult({
                'file_name': pdf_payload['file_name'],
                'raw_model_response': '{"ok": true}',
                'warnings': [],
                'metadata': {'decision_mode': 'llm_full_path', 'identification_sequence': ['llm_identify']},
                'structured_data': {
                    'doc_type': 'contract',
                    'mapped_fields': [
                        {
                            'standard_field': 'contract_no',
                            'standard_label_cn': '???',
                            'source_field_name': 'Contract No',
                            'source_value': 'OCR-001',
                            'confidence': 0.99,
                            'uncertain': False,
                            'reason': 'ocr recovered value',
                        }
                    ],
                    'missing_fields': [],
                    'uncertain_fields': [],
                    'raw_summary': 'ocr improved result',
                },
            })
        return DummyResult({
            'file_name': pdf_payload['file_name'],
            'raw_model_response': '{"ok": true}',
            'warnings': [],
            'metadata': {'decision_mode': 'llm_full_path', 'identification_sequence': ['llm_identify']},
            'structured_data': {
                'doc_type': 'invoice',
                'mapped_fields': [],
                'missing_fields': ['contract_no'],
                'uncertain_fields': [],
                'raw_summary': 'base result missed contract number',
            },
        })

    monkeypatch.setattr('audit_system.api.routes.document_compare.extract_pdf_text', fake_extract_pdf_text)
    monkeypatch.setattr('audit_system.api.routes.document_compare.extract_document_with_options', fake_extract_document_with_options)
    monkeypatch.setattr('audit_system.api.routes.document_compare.build_pdf_visual_assets', lambda content, max_pages=3: [])

    document = _process_uploaded_document(
        file_name='invoice.pdf',
        content=SAMPLE_TEXT_PDF,
        runtime_config=LLMRuntimeConfig(api_key='test-key', base_url='https://example.com', model='deepseek-chat'),
        ocr_enabled=True,
        force_ocr_value=False,
        prompt_name='extract_prompt_v1.txt',
        prompt_override='prompt',
        use_alias=False,
        use_rule=False,
        alias_active={},
        rule_active=[],
        alias_candidates=[],
        rule_candidates=[],
        include_visuals=False,
        focus_field_list=['contract_no'],
        priority_field_list=[],
    )

    assert pdf_calls == [False, True]
    assert document['raw_text_result']['metadata']['source_kind'] == 'scan_ocr'
    assert document['standard_mappings'][0]['source_value'] == 'OCR-001'
    assert document['extraction_metadata']['ocr_retry']['selected'] is True
