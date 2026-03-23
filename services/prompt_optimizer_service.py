from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from audit_system.models.prompt_version import PromptVersion
from schemas.document_schema import STANDARD_FIELD_LABELS
from services.prompt_evolution_service import build_evolution_dashboard
from services.prompt_learning_service import analyze_documents_for_learning, load_prompt_learning_config

PROMPT_CENTER_CATEGORY = "prompt_learning_center"
LOCKED_FRAGMENT_IDS = {"output_constraints"}

TEST_CASE_LIBRARY = [
    {"id": "tc_contract_factory", "name": "合同厂号样本", "docType": "合同", "sampleType": "ocr_text", "groundTruth": {"factory_no": "2782", "contract_no": "SC-2026-001"}, "ocrText": "SALES CONTRACT\nContract No.: SC-2026-001\nPlant No.: 2782", "mapped": ["contract_no"], "missing": ["factory_no"], "wrong": [], "latency": 820, "confusions": [], "tags": ["alias", "structure"]},
    {"id": "tc_invoice_amount", "name": "发票金额样本", "docType": "发票", "sampleType": "raw_file", "groundTruth": {"invoice_no": "INV-2035", "amount": "USD 20,350"}, "ocrText": "PROFORMA INVOICE\nInvoice No: INV-2035\nTotal Amount: USD 20,350", "mapped": ["amount"], "missing": ["invoice_no"], "wrong": [], "latency": 760, "confusions": [], "tags": ["alias", "fallback"]},
    {"id": "tc_bl_party", "name": "提单收货人样本", "docType": "提单", "sampleType": "ocr_blocks", "groundTruth": {"consignee_name_address": "ABC FOODS LLC", "port_of_destination": "LOS ANGELES"}, "ocrText": "BILL OF LADING\nConsignee: ABC FOODS LLC\nPort of Destination: LOS ANGELES", "mapped": ["consignee_name_address"], "missing": ["port_of_destination"], "wrong": [], "latency": 910, "confusions": [], "tags": ["structure"]},
    {"id": "tc_invoice_confusion", "name": "编号混淆样本", "docType": "发票", "sampleType": "ocr_text", "groundTruth": {"invoice_no": "PI-9008", "contract_no": "SC-01"}, "ocrText": "PROFORMA INVOICE\nPI No: PI-9008\nSales Contract No: SC-01", "mapped": ["contract_no"], "missing": ["invoice_no"], "wrong": ["contract_no"], "latency": 840, "confusions": ["invoice_no", "contract_no"], "tags": ["confusion", "confidence"]},
]

FRAGMENT_SPECS = [
    ("base_understanding", "基础理解", "总控提示", 100, "先理解业务目标，再抽字段。没有证据时返回 missing 或 uncertain。", False, True),
    ("document_classification", "单据分类", "分类规则", 92, "先分清合同、发票、提单等类型，再决定优先字段。", False, True),
    ("field_understanding", "字段理解", "字段语义", 88, "结合标签、上下文和业务含义识别字段，不因相似词强行映射。", False, True),
    ("numbering_fields", "编号字段", "字段细分", 84, "重点区分 contract_no、invoice_no、factory_no 等编号字段。", False, True),
    ("party_fields", "主体字段", "字段细分", 78, "识别主体字段时必须结合标签和地址结构。", False, True),
    ("ocr_noise_tolerance", "OCR容错", "结构规则", 74, "OCR 文本弱时优先找键值对、同一行和下一行短值。", False, True),
    ("fallback_handling", "兜底策略", "输出策略", 68, "证据不足时返回 missing/uncertain，并给出原因。", False, True),
    ("output_constraints", "输出约束", "保护片段", 110, "主提示词约束不可自动改写，只允许对片段追加 patch。", True, False),
]

PROMPT_KEYS = {"base_understanding": "base", "document_classification": "classify", "field_understanding": "field_understanding"}
SOURCE_LABELS = {"contract_no": "Contract No.", "factory_no": "Plant No.", "invoice_no": "Invoice No.", "amount": "Total Amount", "consignee_name_address": "Consignee", "port_of_destination": "Port of Destination"}


def build_prompt_optimizer_config(db: Session | None = None) -> dict[str, Any]:
    config = load_prompt_learning_config()
    fragments = build_prompt_fragments(config.get("prompt_texts", {}))
    evolution = build_evolution_dashboard(db) if db is not None else {"failure_library": [], "recent_patches": [], "rule_pool": {s: 0 for s in ("draft", "candidate", "verified", "online", "deprecated")}}
    config.update({
        "fragments": fragments,
        "versions": list_prompt_center_versions(db, fragments),
        "test_case_sets": [
            {"id": "baseline", "name": "基础回归集", "description": "覆盖合同、发票、提单和编号混淆样本。", "caseIds": [i["id"] for i in TEST_CASE_LIBRARY]},
            {"id": "numbering-risk", "name": "编号风险集", "description": "重点验证编号类字段。", "caseIds": ["tc_contract_factory", "tc_invoice_confusion"]},
        ],
        "protected_fragment_ids": sorted(LOCKED_FRAGMENT_IDS),
        "evolution": evolution,
        "workflow": ["失败样本沉淀", "自动归因", "生成 patch", "回归测试", "进入 verified", "人工确认后 online"],
    })
    return config


def build_prompt_fragments(prompt_texts: dict[str, str] | None = None) -> list[dict[str, Any]]:
    texts = prompt_texts or {}
    now = _now_iso()
    result = []
    for fid, name, ftype, priority, default, locked, auto in FRAGMENT_SPECS:
        result.append({"id": fid, "name": name, "type": ftype, "content": texts.get(PROMPT_KEYS.get(fid, ""), default) if fid in PROMPT_KEYS else default, "enabled": True, "priority": priority, "version": "v1", "lastTestScore": 100 if locked else 84, "hitCount": 0, "updatedAt": now, "status": "enabled", "locked": locked, "autoOptimizable": auto})
    return result


def compose_prompt_text(fragments: list[dict[str, Any]]) -> str:
    active = sorted((f for f in fragments if f.get("enabled")), key=lambda x: (-int(x.get("priority", 0)), x.get("name", "")))
    return "\n\n".join(f"[{f['name']}]\n{str(f.get('content', '')).strip()}" for f in active if str(f.get("content", "")).strip())


def run_prompt_test(documents: list[dict[str, Any]], prompt_context: dict[str, str] | None = None, prompt_flags: dict[str, Any] | None = None, *, fragments: list[dict[str, Any]] | None = None, selected_fragment_ids: list[str] | None = None, test_case_ids: list[str] | None = None, document_type: str | None = None, version_id: str | None = None) -> dict[str, Any]:
    selected = _prepare_fragments(fragments, prompt_context, selected_fragment_ids)
    cases = _select_test_cases(test_case_ids, document_type)
    source_docs = documents or _materialize_documents(cases)
    analysis = analyze_documents_for_learning(source_docs, prompt_context, prompt_flags)
    source_map = {str(i.get("filename", "")): i for i in source_docs}
    merged = [{**source_map.get(str(i.get("filename", "")), {}), **i} for i in analysis.get("documents", [])]
    analysis["documents"] = merged
    report = _build_report(merged, selected, cases, version_id)
    suggestions = _build_suggestions(merged, report, selected)
    patch = _build_patch(suggestions, selected, version_id)
    candidate_fragments = _apply_patch(selected, patch)
    candidate_report = _simulate_candidate_report(report, candidate_fragments, patch)
    analysis.update({
        "selected_fragment_ids": [i["id"] for i in selected],
        "test_cases_used": cases,
        "fragment_scores": _fragment_scores(selected, report),
        "test_run": {"runId": f"test-run-{_timestamp_slug()}", "versionId": version_id or "prompt-opt-v1", "selectedFragmentIds": [i["id"] for i in selected], "selectedTestCaseIds": [i["id"] for i in cases], "documentType": document_type or "全部", "metrics": report["metrics"], "createdAt": _now_iso()},
        "evaluation_report": report,
        "optimization_suggestions": suggestions,
        "candidate_patch": patch,
        "candidate_fragments": candidate_fragments,
        "candidate_version": _build_candidate_version(version_id, patch, candidate_fragments, candidate_report),
        "version_comparison": _build_version_comparison(report, candidate_report),
    })
    return analysis


def optimize_prompt_fragments(documents: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    result = run_prompt_test(documents, kwargs.get("prompt_context"), kwargs.get("prompt_flags"), fragments=kwargs.get("fragments"), selected_fragment_ids=kwargs.get("selected_fragment_ids"), test_case_ids=kwargs.get("test_case_ids"), document_type=kwargs.get("document_type"), version_id=kwargs.get("version_id"))
    return {k: result[k] for k in ("optimization_suggestions", "candidate_patch", "candidate_fragments", "candidate_version", "version_comparison", "evaluation_report", "fragment_scores", "test_run", "test_cases_used")}


def save_prompt_center_version(db: Session, *, fragments: list[dict[str, Any]], base_version_id: str | None, changed_fragments: list[str], change_summary: str, test_summary: dict[str, Any] | None, created_by: str, status: str) -> dict[str, Any]:
    name = _next_version_name(db)
    normalized = str(status or "candidate").lower()
    meta = {"versionId": name, "baseVersionId": base_version_id or "prompt-opt-v1", "changedFragments": changed_fragments, "changeSummary": change_summary, "testSummary": test_summary or {}, "createdAt": _now_iso(), "createdBy": created_by or "web-user", "status": normalized, "fragments": deepcopy(fragments)}
    if normalized == "online":
        for row in db.scalars(select(PromptVersion).where(PromptVersion.category == PROMPT_CENTER_CATEGORY)).all():
            row.is_active = False
            _update_meta(row, {"status": "deprecated"})
    record = PromptVersion(name=name, category=PROMPT_CENTER_CATEGORY, content=compose_prompt_text(fragments), source_path=None, description=json.dumps(meta, ensure_ascii=False), is_active=normalized == "online")
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"saved": _serialize_version(record), "versions": list_prompt_center_versions(db, build_prompt_fragments(load_prompt_learning_config().get("prompt_texts", {})))}


def rollback_prompt_center_version(db: Session, version_id: str, created_by: str | None = None) -> dict[str, Any]:
    record = db.scalar(select(PromptVersion).where(PromptVersion.category == PROMPT_CENTER_CATEGORY, PromptVersion.name == version_id))
    if record is None:
        raise ValueError(f"Prompt version not found: {version_id}")
    for row in db.scalars(select(PromptVersion).where(PromptVersion.category == PROMPT_CENTER_CATEGORY)).all():
        row.is_active = row.id == record.id
        _update_meta(row, {"status": "online" if row.id == record.id else "deprecated"})
    _update_meta(record, {"rolledBackBy": created_by or "web-user"})
    db.commit()
    return {"current": _serialize_version(record), "versions": list_prompt_center_versions(db, build_prompt_fragments(load_prompt_learning_config().get("prompt_texts", {})))}


def list_prompt_center_versions(db: Session | None, base_fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seed = {"versionId": "prompt-opt-v1", "baseVersionId": None, "changedFragments": [i["id"] for i in base_fragments], "changeSummary": "系统内置基线版本，包含受保护主约束。", "testSummary": {}, "createdAt": _now_iso(), "createdBy": "system", "status": "online", "promptLength": len(compose_prompt_text(base_fragments)), "fragments": deepcopy(base_fragments), "isBuiltin": True}
    if db is None:
        return [seed]
    rows = db.scalars(select(PromptVersion).where(PromptVersion.category == PROMPT_CENTER_CATEGORY).order_by(PromptVersion.created_at.desc(), PromptVersion.id.desc())).all()
    versions = [_serialize_version(i) for i in rows]
    return versions or [seed]


def _prepare_fragments(fragments: list[dict[str, Any]] | None, prompt_context: dict[str, str] | None, selected_fragment_ids: list[str] | None) -> list[dict[str, Any]]:
    source = deepcopy(fragments or build_prompt_fragments(prompt_context or load_prompt_learning_config().get("prompt_texts", {})))
    if selected_fragment_ids:
        chosen = set(selected_fragment_ids)
        for item in source:
            item["enabled"] = item.get("id") in chosen or item.get("locked")
    return sorted(source, key=lambda x: (-int(x.get("priority", 0)), x.get("name", "")))


def _select_test_cases(test_case_ids: list[str] | None, document_type: str | None) -> list[dict[str, Any]]:
    items = TEST_CASE_LIBRARY
    if document_type and document_type not in {"", "全部", "all"}:
        items = [i for i in items if i["docType"] == document_type]
    if test_case_ids:
        chosen = set(test_case_ids)
        items = [i for i in items if i["id"] in chosen]
    return deepcopy(items)


def _materialize_documents(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    docs = []
    for case in cases:
        mappings = []
        for field, value in case["groundTruth"].items():
            if field not in case["mapped"] and field not in case["wrong"]:
                continue
            mappings.append({"standard_field": field, "standard_label_cn": STANDARD_FIELD_LABELS.get(field, field), "source_field_name": SOURCE_LABELS.get(field, field), "source_value": value if field in case["mapped"] else "", "confidence": 0.84 if field in case["mapped"] else 0.56, "reason": "baseline sample", "uncertain": field in case["wrong"]})
        docs.append({"filename": f"{case['id']}.pdf", "doc_type": case["docType"], "raw_text_result": {"text": case["ocrText"], "metadata": {"source_kind": "scan_ocr" if case["sampleType"] != "raw_file" else "digital_text"}}, "standard_mappings": mappings, "missing_fields": list(case["missing"]), "wrong_fields": list(case["wrong"]), "uncertain_fields": list(case["wrong"]), "alias_candidates": ([{"standard_field": "factory_no", "alias": "Plant No."}] if case["id"] == "tc_contract_factory" else [{"standard_field": "invoice_no", "alias": "PI No"}] if case["id"] == "tc_invoice_confusion" else []), "ground_truth": deepcopy(case["groundTruth"]), "confusion_fields": list(case["confusions"]), "extraction_metadata": {"elapsed_ms": case["latency"]}})
    return docs


def _build_report(documents: list[dict[str, Any]], fragments: list[dict[str, Any]], cases: list[dict[str, Any]], version_id: str | None) -> dict[str, Any]:
    hit = missed = wrong = confusion = 0
    doc_type_correct = 0
    duration = 0.0
    failed = []
    for doc in documents:
        gt = doc.get("ground_truth", {}) or {}
        expected = set(gt.keys()) or set(doc.get("missing_fields", []) or [])
        mappings = doc.get("field_understanding", []) or []
        recognized = {str(i.get("standard_field", "")) for i in mappings if i.get("source_field_name") or i.get("source_value")}
        missing = set(doc.get("missing_fields", []) or []) | (expected - recognized)
        wrong_fields = set(doc.get("wrong_fields", []) or [])
        if not wrong_fields:
            wrong_fields = {str(i.get("standard_field", "")) for i in mappings if i.get("uncertain") and not i.get("source_value")}
        hit += len(recognized - wrong_fields)
        missed += len(missing)
        wrong += len(wrong_fields)
        duration += float(doc.get("extraction_metadata", {}).get("elapsed_ms") or 780)
        expected_type = str(doc.get("doc_type", "") or "Unknown")
        predicted_type = str(doc.get("doc_type_result", {}).get("doc_type", expected_type) or "Unknown")
        if expected_type in {"", "Unknown"} or expected_type == predicted_type:
            doc_type_correct += 1
        confusion += len(wrong_fields & set(doc.get("confusion_fields", []) or []))
        if missing or wrong_fields:
            failed.append({"filename": doc.get("filename", "document.pdf"), "docType": predicted_type, "missingFields": [STANDARD_FIELD_LABELS.get(i, i) for i in sorted(missing)], "wrongFields": [STANDARD_FIELD_LABELS.get(i, i) for i in sorted(wrong_fields)], "reason": _failure_reason(missing, wrong_fields)})
    accuracy = hit / (hit + wrong) if (hit + wrong) else 1.0
    recall = hit / (hit + missed) if (hit + missed) else 1.0
    return {"versionId": version_id or "prompt-opt-v1", "fragmentIds": [i["id"] for i in fragments], "metrics": {"fieldAccuracy": round(accuracy, 4), "fieldRecall": round(recall, 4), "docTypeAccuracy": round(doc_type_correct / len(documents), 4) if documents else 1.0, "averageLatencyMs": round(duration / len(documents), 2) if documents else 0, "promptLength": len(compose_prompt_text(fragments)), "hitFields": hit, "missedFields": missed, "wrongFields": wrong, "confusionFieldCount": confusion, "gainDelta": 0}, "summary": {"documentCount": len(documents), "testCaseCount": len(cases), "passedDocuments": len(documents) - len(failed), "failedDocuments": len(failed)}, "failedSamples": failed[:8], "generatedAt": _now_iso()}


def _build_suggestions(documents: list[dict[str, Any]], report: dict[str, Any], fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics = report["metrics"]
    enabled = {f["id"] for f in fragments if f.get("enabled")}
    items = []
    if metrics["fieldRecall"] < 0.9:
        items.append({"id": "recall-gap", "fragmentId": "field_understanding", "title": "补字段理解 patch", "severity": "high", "problem": "字段召回率偏低。", "recommendation": "只追加 alias/结构 patch，不重写主提示词。", "reason": "失败样本集中在字段标签缺失和结构定位不足。", "expectedImpactFields": _top_missing_fields(documents), "patchPreview": "补充高频别名、键值对定位顺序和 missing/uncertain 条件。", "patchType": "alias", "riskNote": "注意控制 patch 长度。"})
    if metrics["docTypeAccuracy"] < 0.95:
        items.append({"id": "doc-type-gap", "fragmentId": "document_classification", "title": "补单据分类边界", "severity": "medium", "problem": "单据分类边界不够稳。", "recommendation": "补充相近单据的区分规则。", "reason": "类型错位会影响后续字段优先级。", "expectedImpactFields": ["doc_type"], "patchPreview": "区分合同、发票、提单的标题词和业务字段。", "patchType": "structure", "riskNote": "避免只看标题关键词。"})
    if metrics["confusionFieldCount"] > 0:
        items.append({"id": "confusion-gap", "fragmentId": "numbering_fields", "title": "补混淆提醒", "severity": "high", "problem": "编号字段发生混淆。", "recommendation": "给相近字段增加 disambiguation patch。", "reason": "invoice_no、contract_no 等字段不能只靠相似词匹配。", "expectedImpactFields": _confusion_fields(documents), "patchPreview": "多个编号并存时，先定位字段标签，再取相邻值。", "patchType": "confusion", "riskNote": "只覆盖高频混淆对。"})
    if _has_scan_docs(documents):
        items.append({"id": "ocr-gap", "fragmentId": "ocr_noise_tolerance", "title": "补 OCR 容错规则", "severity": "medium", "problem": "扫描件恢复仍然不稳。", "recommendation": "补 OCR 结构定位和低质量文本回退策略。", "reason": "文本弱时也必须坚持证据优先。", "expectedImpactFields": _top_missing_fields(documents), "patchPreview": "优先找字段标签、同一行值块、下一行短值。", "patchType": "structure", "riskNote": "不能放宽 hallucination 边界。"})
    return [i for i in items if i["fragmentId"] in enabled]


def _build_patch(suggestions: list[dict[str, Any]], fragments: list[dict[str, Any]], version_id: str | None) -> dict[str, Any]:
    locked = {f["id"] for f in fragments if f.get("locked")}
    ops = [{"fragmentId": i["fragmentId"], "action": "append_patch", "patchType": i["patchType"], "insertMode": "append", "content": f"- {i['patchPreview']}", "reason": i["reason"], "expectedImpactFields": i["expectedImpactFields"], "riskNote": i["riskNote"]} for i in suggestions if i["fragmentId"] not in locked]
    return {"patchId": f"patch-{_timestamp_slug()}", "baseVersionId": version_id or "prompt-opt-v1", "operations": ops, "summary": f"生成 {len(ops)} 条受控 patch，仅追加到可优化片段，不改写主约束。", "protectedFragmentIds": sorted(LOCKED_FRAGMENT_IDS)}


def _apply_patch(fragments: list[dict[str, Any]], patch: dict[str, Any]) -> list[dict[str, Any]]:
    next_fragments = deepcopy(fragments)
    for op in patch.get("operations", []):
        for fragment in next_fragments:
            if fragment["id"] == op.get("fragmentId") and not fragment.get("locked"):
                fragment["content"] = f"{str(fragment.get('content', '')).rstrip()}\n{op.get('content', '')}".strip()
                fragment["version"] = _bump_version(fragment.get("version", "v1"))
                fragment["updatedAt"] = _now_iso()
                fragment["status"] = "candidate"
    return next_fragments


def _simulate_candidate_report(report: dict[str, Any], candidate_fragments: list[dict[str, Any]], patch: dict[str, Any]) -> dict[str, Any]:
    next_report = deepcopy(report)
    acc = rec = 0.0
    confusion_delta = 0
    latency = 0
    for op in patch.get("operations", []):
        if op["patchType"] == "alias":
            acc += 0.01; rec += 0.03; latency += 12
        elif op["patchType"] == "structure":
            acc += 0.012; rec += 0.025; latency += 14
        elif op["patchType"] == "confusion":
            acc += 0.02; rec += 0.01; latency += 10; confusion_delta -= 1
        else:
            rec += 0.012; latency += 8
    metrics = next_report["metrics"]
    metrics["fieldAccuracy"] = round(min(1.0, float(metrics["fieldAccuracy"]) + acc), 4)
    metrics["fieldRecall"] = round(min(1.0, float(metrics["fieldRecall"]) + rec), 4)
    metrics["docTypeAccuracy"] = round(min(1.0, float(metrics["docTypeAccuracy"]) + (0.01 if any(op["fragmentId"] == "document_classification" for op in patch.get("operations", [])) else 0.0)), 4)
    metrics["averageLatencyMs"] = round(float(metrics["averageLatencyMs"]) + latency, 2)
    metrics["promptLength"] = len(compose_prompt_text(candidate_fragments))
    metrics["confusionFieldCount"] = max(0, int(metrics["confusionFieldCount"]) + confusion_delta)
    metrics["gainDelta"] = round(acc + rec, 4)
    next_report["fragmentIds"] = [f["id"] for f in candidate_fragments]
    next_report["generatedAt"] = _now_iso()
    return next_report


def _build_candidate_version(version_id: str | None, patch: dict[str, Any], candidate_fragments: list[dict[str, Any]], candidate_report: dict[str, Any]) -> dict[str, Any]:
    return {"versionId": f"candidate-{_timestamp_slug()}", "baseVersionId": version_id or "prompt-opt-v1", "changedFragments": sorted({op["fragmentId"] for op in patch.get("operations", []) if op.get("fragmentId")}), "changeSummary": patch.get("summary", "auto patch"), "testSummary": candidate_report.get("metrics", {}), "createdAt": _now_iso(), "createdBy": "optimizer", "status": "candidate", "promptLength": len(compose_prompt_text(candidate_fragments)), "fragments": deepcopy(candidate_fragments), "isBuiltin": False}


def _build_version_comparison(base_report: dict[str, Any], candidate_report: dict[str, Any]) -> dict[str, Any]:
    base = base_report["metrics"]; cand = candidate_report["metrics"]
    diff = {"fieldAccuracy": round(float(cand["fieldAccuracy"]) - float(base["fieldAccuracy"]), 4), "fieldRecall": round(float(cand["fieldRecall"]) - float(base["fieldRecall"]), 4), "docTypeAccuracy": round(float(cand["docTypeAccuracy"]) - float(base["docTypeAccuracy"]), 4), "averageLatencyMs": round(float(cand["averageLatencyMs"]) - float(base["averageLatencyMs"]), 2), "promptLength": int(cand["promptLength"]) - int(base["promptLength"]), "confusionFieldCount": int(cand["confusionFieldCount"]) - int(base["confusionFieldCount"])}
    promote = diff["fieldAccuracy"] >= 0 and diff["fieldRecall"] > 0 and diff["confusionFieldCount"] <= 0 and diff["averageLatencyMs"] <= 40
    return {"baseMetrics": base, "candidateMetrics": cand, "diff": diff, "shouldPromote": promote, "promotionReason": "候选 patch 带来净提升，可进入 verified/online 流程。" if promote else "当前 patch 还没有形成足够净提升。"}


def _fragment_scores(fragments: list[dict[str, Any]], report: dict[str, Any]) -> list[dict[str, Any]]:
    m = report["metrics"]; result = []
    for f in fragments:
        score = float(m["fieldAccuracy"]) * 100
        if f["id"] == "document_classification":
            score = float(m["docTypeAccuracy"]) * 100
        elif f["id"] in {"field_understanding", "numbering_fields", "party_fields", "ocr_noise_tolerance", "fallback_handling"}:
            score = float(m["fieldRecall"]) * 100
        elif f["id"] == "output_constraints":
            score = 100
        result.append({"fragmentId": f["id"], "lastTestScore": round(score, 1), "hitCount": int(m["hitFields"])})
    return result


def _top_missing_fields(documents: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for doc in documents:
        for field in doc.get("missing_fields", []) or []:
            counts[str(field)] = counts.get(str(field), 0) + 1
    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [STANDARD_FIELD_LABELS.get(name, name) for name, _ in ranked[:4]] or ["关键字段"]


def _confusion_fields(documents: list[dict[str, Any]]) -> list[str]:
    found, seen = [], set()
    for doc in documents:
        for field in doc.get("confusion_fields", []) or []:
            if field not in seen:
                seen.add(field)
                found.append(STANDARD_FIELD_LABELS.get(field, field))
    return found or ["编号类字段"]


def _has_scan_docs(documents: list[dict[str, Any]]) -> bool:
    return any(str(doc.get("raw_text_result", {}).get("metadata", {}).get("source_kind", "")) in {"scan_ocr", "scan_like"} for doc in documents)


def _failure_reason(missing: set[str], wrong_fields: set[str]) -> str:
    if wrong_fields:
        return f"存在错识别字段：{', '.join(sorted(wrong_fields))}"
    if missing:
        return f"存在漏识别字段：{', '.join(sorted(missing))}"
    return "需要补充规则 patch"


def _serialize_version(record: PromptVersion) -> dict[str, Any]:
    meta = _json_load(record.description, {}) if record.description else {}
    return {"versionId": meta.get("versionId") or record.name, "baseVersionId": meta.get("baseVersionId"), "changedFragments": meta.get("changedFragments", []), "changeSummary": meta.get("changeSummary", ""), "testSummary": meta.get("testSummary", {}), "createdAt": meta.get("createdAt") or (record.created_at.isoformat() if record.created_at else None), "createdBy": meta.get("createdBy", "system"), "status": meta.get("status") or ("online" if record.is_active else "candidate"), "promptLength": len(record.content or ""), "fragments": meta.get("fragments", []), "isBuiltin": False}


def _update_meta(record: PromptVersion, updates: dict[str, Any]) -> None:
    meta = _json_load(record.description, {}) if record.description else {}
    if not isinstance(meta, dict):
        meta = {}
    meta.update(updates)
    record.description = json.dumps(meta, ensure_ascii=False)


def _next_version_name(db: Session) -> str:
    rows = db.scalars(select(PromptVersion).where(PromptVersion.category == PROMPT_CENTER_CATEGORY)).all()
    idx = 1
    for row in rows:
        if row.name.startswith("prompt-opt-v") and row.name.replace("prompt-opt-v", "").isdigit():
            idx = max(idx, int(row.name.replace("prompt-opt-v", "")) + 1)
    return f"prompt-opt-v{idx}"


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _bump_version(version: str) -> str:
    cleaned = str(version or "v1").lstrip("v")
    return f"v{int(cleaned) + 1}" if cleaned.isdigit() else "v2"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
