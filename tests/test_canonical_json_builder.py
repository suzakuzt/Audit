import json
from pathlib import Path

from services.document_structuring.canonical_json_builder import CanonicalJSONBuilder


def _load_sample_payload() -> dict:
    return json.loads(Path("tests/fixtures/sample_paddle_vl_raw.json").read_text(encoding="utf-8"))


def test_canonical_json_builder_generates_structured_payload() -> None:
    payload = _load_sample_payload()
    builder = CanonicalJSONBuilder()

    result = builder.build_from_raw(payload, doc_id="ut_doc_001")
    canonical = result.canonical

    assert canonical.doc_id == "ut_doc_001"
    assert canonical.document_type_candidate in {"invoice", "contract", "unknown", "packing_list", "bill_of_lading"}
    assert canonical.pages == 1
    assert len(canonical.field_candidates) > 0
    assert len(canonical.table_candidates) >= 1
    assert len(canonical.raw_trace) > 0

    deepseek_payload = builder.build_deepseek_payload(canonical)
    assert deepseek_payload["constraints"]["must_select_from_candidates_only"] is True
    assert isinstance(deepseek_payload["candidate_pool"], list)


def test_debug_canonical_json_endpoint(client) -> None:
    payload = _load_sample_payload()
    response = client.post(
        "/api/v1/debug/canonical-json",
        json={
            "raw_ocr_json": payload,
            "doc_id": "api_doc_001",
            "save_debug_files": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["canonical_json"]["doc_id"] == "api_doc_001"
    assert "merged_blocks" in body
    assert "reading_order" in body
    assert "kv_candidates" in body
    assert "table_candidates" in body
    assert "deepseek_payload" in body

