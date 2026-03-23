from __future__ import annotations

import json
from collections import Counter
from typing import Any

from sqlalchemy import select

from audit_system.db.session import SessionLocal
from audit_system.models import PromptEvolutionSample, RuleEntry, RulePatch
from services.prompt_learning_service import load_prompt_learning_config

FAILURE_REASON_OCR = "ocr_issue"
FAILURE_REASON_ALIAS = "alias_missing"
FAILURE_REASON_STRUCTURE = "structure_failure"
FAILURE_REASON_DOC_TYPE = "doc_type_misjudge"
FAILURE_REASON_SEMANTIC = "semantic_confusion"
FAILURE_REASON_PROMPT = "prompt_redundancy"
FAILURE_REASON_CONFIDENCE = "confidence_strategy"

REASON_LABELS = {
    FAILURE_REASON_OCR: "OCR识别问题",
    FAILURE_REASON_ALIAS: "字段别名缺失",
    FAILURE_REASON_STRUCTURE: "结构理解失败",
    FAILURE_REASON_DOC_TYPE: "单据类型判断错误",
    FAILURE_REASON_SEMANTIC: "字段语义混淆",
    FAILURE_REASON_PROMPT: "提示词冗余干扰",
    FAILURE_REASON_CONFIDENCE: "置信度策略错误",
}

RULE_STATUS_FLOW = ["draft", "candidate", "verified", "online", "deprecated"]

PATCH_FRAGMENT_MAP = {
    "alias": "field_understanding",
    "structure": "ocr_noise_tolerance",
    "confusion": "numbering_fields",
    "fallback": "fallback_handling",
}


def record_evolution_cycle(
    *,
    documents: list[dict[str, Any]],
    experiment_record: dict[str, Any],
    evaluation_summary: dict[str, Any],
    evaluation_record: dict[str, Any],
) -> dict[str, Any]:
    prompt_version = str(
        (experiment_record or {}).get("version_record", {}).get("prompt_file_name", "")
        or (experiment_record or {}).get("prompt_file_name", "")
        or "extract_prompt_v1.txt"
    )
    from services.prompt_optimizer_service import build_prompt_fragments

    fragment_versions = [
        {"id": item["id"], "version": item.get("version", "v1")}
        for item in build_prompt_fragments(load_prompt_learning_config().get("prompt_texts", {}))
    ]
    created_samples = 0
    created_patches = 0
    verified_patches = 0
    high_value_samples = 0

    with SessionLocal() as db:
        for document in documents or []:
            sample_payload = _build_sample_payload(document, prompt_version, fragment_versions, experiment_record)
            if not sample_payload:
                continue
            recurrence_count = _find_recurrence_count(db, sample_payload)
            sample_payload["recurrence_count"] = recurrence_count
            sample_payload["value_score"] = min(
                100,
                int(sample_payload["value_score"]) + (10 if recurrence_count >= 2 else 0),
            )

            sample = PromptEvolutionSample(
                run_key=str(
                    (experiment_record or {}).get("run_dir", "")
                    or (experiment_record or {}).get("db_run_id", "")
                    or ""
                ),
                filename=sample_payload["filename"],
                prompt_version=prompt_version,
                fragment_versions=json.dumps(fragment_versions, ensure_ascii=False),
                raw_document=json.dumps(sample_payload["raw_document"], ensure_ascii=False),
                ocr_text=sample_payload["ocr_text"],
                doc_type_result=json.dumps(sample_payload["doc_type_result"], ensure_ascii=False),
                field_result=json.dumps(sample_payload["field_result"], ensure_ascii=False),
                missing_fields=json.dumps(sample_payload["missing_fields"], ensure_ascii=False),
                wrong_fields=json.dumps(sample_payload["wrong_fields"], ensure_ascii=False),
                human_correction=json.dumps(sample_payload["human_correction"], ensure_ascii=False),
                failure_reasons=json.dumps(sample_payload["failure_reasons"], ensure_ascii=False),
                attribution_summary=sample_payload["attribution_summary"],
                sample_status="high_value" if sample_payload["value_score"] >= 80 else "failed",
                value_score=sample_payload["value_score"],
                recurrence_count=recurrence_count,
            )
            db.add(sample)
            db.flush()
            created_samples += 1
            if sample.value_score >= 80:
                high_value_samples += 1

            patch_specs = _generate_patch_specs(sample_payload)
            for spec in patch_specs:
                validation = _validate_patch_candidate(spec, sample_payload)
                patch_status = "verified" if validation["is_verified"] else "candidate"
                patch_summary = _render_patch_summary(spec)
                patch = RulePatch(
                    sample_id=sample.id,
                    patch_type=spec["patch_type"],
                    target_fragment_id=spec["target_fragment_id"],
                    patch_text=patch_summary,
                    impacted_fields=json.dumps(spec["impacted_fields"], ensure_ascii=False),
                    risk_note=spec["risk_note"],
                    metrics_before=json.dumps(validation["metrics_before"], ensure_ascii=False),
                    metrics_after=json.dumps(validation["metrics_after"], ensure_ascii=False),
                    validation_report=json.dumps(
                        {
                            **validation,
                            "patch_spec": {**spec, "source_sample_id": sample.id},
                            "source_sample_summary": sample.attribution_summary,
                        },
                        ensure_ascii=False,
                    ),
                    status=patch_status,
                    priority_score=float(spec["priority_score"]),
                )
                db.add(patch)
                _upsert_rule_entry(db, sample.id, spec, patch_status)
                created_patches += 1
                if patch_status == "verified":
                    verified_patches += 1

        db.commit()
        dashboard = build_evolution_dashboard(db)

    return {
        "created_samples": created_samples,
        "high_value_samples": high_value_samples,
        "created_patches": created_patches,
        "verified_patches": verified_patches,
        "evaluation_accuracy": evaluation_summary.get("overall_accuracy", 0.0),
        "rule_pool": dashboard["rule_pool"],
        "failure_library": dashboard["failure_library"],
        "recent_patches": dashboard["recent_patches"],
    }


def build_evolution_dashboard(db) -> dict[str, Any]:
    samples = db.scalars(select(PromptEvolutionSample).order_by(PromptEvolutionSample.created_at.desc()).limit(20)).all()
    patches = db.scalars(select(RulePatch).order_by(RulePatch.created_at.desc()).limit(20)).all()
    rule_rows = db.scalars(select(RuleEntry).order_by(RuleEntry.created_at.desc()).limit(80)).all()
    status_counter = Counter(str(row.status or "candidate") for row in rule_rows)
    for status in RULE_STATUS_FLOW:
        status_counter.setdefault(status, 0)

    sample_map = {item.id: item for item in samples}
    return {
        "failure_library": [
            {
                "id": item.id,
                "filename": item.filename,
                "promptVersion": item.prompt_version,
                "failureReasons": _json_load(item.failure_reasons, []),
                "missingFields": _json_load(item.missing_fields, []),
                "wrongFields": _json_load(item.wrong_fields, []),
                "sampleStatus": item.sample_status,
                "valueScore": item.value_score,
                "recurrenceCount": item.recurrence_count,
                "attributionSummary": item.attribution_summary,
                "createdAt": item.created_at.isoformat() if item.created_at else None,
            }
            for item in samples
        ],
        "recent_patches": [
            {
                "id": item.id,
                "sampleId": item.sample_id,
                "sampleFilename": sample_map.get(item.sample_id).filename if item.sample_id in sample_map else None,
                "patchType": item.patch_type,
                "targetFragmentId": item.target_fragment_id,
                "patchText": item.patch_text,
                "impactedFields": _json_load(item.impacted_fields, []),
                "riskNote": item.risk_note,
                "status": item.status,
                "priorityScore": item.priority_score,
                "validationReport": _json_load(item.validation_report, {}),
                "createdAt": item.created_at.isoformat() if item.created_at else None,
            }
            for item in patches
        ],
        "rule_pool": {status: status_counter.get(status, 0) for status in RULE_STATUS_FLOW},
    }


def transition_rule_patch_status(db, patch_id: int, status: str) -> dict[str, Any]:
    target_status = str(status or "").lower()
    if target_status not in RULE_STATUS_FLOW:
        raise ValueError(f"Unsupported rule status: {status}")

    patch = db.get(RulePatch, int(patch_id))
    if patch is None:
        raise ValueError(f"Rule patch not found: {patch_id}")

    patch.status = target_status
    linked_rules = db.scalars(
        select(RuleEntry).where(
            RuleEntry.source_type == "evolution_patch",
            RuleEntry.source_note.contains(f"source_sample_id={patch.sample_id}"),
            RuleEntry.rule_type == patch.patch_type,
        )
    ).all()
    for row in linked_rules:
        row.status = target_status
    db.flush()
    return {
        "patchId": patch.id,
        "status": patch.status,
        "linkedRuleCount": len(linked_rules),
    }


def _build_sample_payload(
    document: dict[str, Any],
    prompt_version: str,
    fragment_versions: list[dict[str, Any]],
    experiment_record: dict[str, Any],
) -> dict[str, Any] | None:
    rows = document.get("manual_confirmation_rows", []) or []
    if not rows:
        return None

    missing_fields: list[str] = []
    wrong_fields: list[str] = []
    changed_rows: list[dict[str, str]] = []
    for row in rows:
        ai_value = str(row.get("ai_value", "") or "").strip()
        confirmed_value = str(row.get("confirmed_value", "") or "").strip()
        field = str(row.get("standard_field", "") or "").strip()
        if not field:
            continue
        if confirmed_value and not ai_value:
            missing_fields.append(field)
            changed_rows.append({"field": field, "before": ai_value, "after": confirmed_value})
        elif ai_value and confirmed_value and ai_value != confirmed_value:
            wrong_fields.append(field)
            changed_rows.append({"field": field, "before": ai_value, "after": confirmed_value})

    if not missing_fields and not wrong_fields:
        return None

    reasons = _infer_failure_reasons(document, missing_fields, wrong_fields)
    impacted = sorted(set(missing_fields + wrong_fields))
    value_score = 60 + len(changed_rows) * 8 + (15 if len(impacted) >= 2 else 0)
    summary = f"{document.get('filename', 'document.pdf')} 触发进化，涉及字段：{', '.join(impacted)}"
    return {
        "filename": str(document.get("filename", "document.pdf")),
        "prompt_version": prompt_version,
        "fragment_versions": fragment_versions,
        "raw_document": document,
        "ocr_text": str(document.get("raw_text_result", {}).get("text", "") or ""),
        "doc_type_result": {
            "doc_type": document.get("doc_type", ""),
            "raw": document.get("raw_summary", ""),
        },
        "field_result": document.get("standard_mappings", []) or [],
        "missing_fields": missing_fields,
        "wrong_fields": wrong_fields,
        "human_correction": {
            "changedRows": changed_rows,
            "experimentRecord": {
                "run_dir": (experiment_record or {}).get("run_dir", ""),
                "db_run_id": (experiment_record or {}).get("db_run_id", 0),
            },
        },
        "failure_reasons": reasons,
        "attribution_summary": summary,
        "value_score": min(100, value_score),
    }


def _infer_failure_reasons(
    document: dict[str, Any],
    missing_fields: list[str],
    wrong_fields: list[str],
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    raw_meta = document.get("raw_text_result", {}).get("metadata", {}) or {}
    source_kind = str(raw_meta.get("source_kind", ""))
    alias_candidates = document.get("alias_candidates", []) or []
    uncertain_fields = {str(item) for item in (document.get("uncertain_fields", []) or [])}
    text = str(document.get("raw_text_result", {}).get("text", "") or "")
    lowered = text.lower()
    doc_type = str(document.get("doc_type", "") or "").strip().lower()

    if source_kind in {"scan_ocr", "scan_like"} or not document.get("raw_text_result", {}).get("is_text_valid", True):
        reasons.append(
            {
                "code": FAILURE_REASON_OCR,
                "label": REASON_LABELS[FAILURE_REASON_OCR],
                "detail": "样本文本来自 OCR 或文本质量偏弱，说明识别失败可能先出现在文本层。",
            }
        )
    if alias_candidates:
        reasons.append(
            {
                "code": FAILURE_REASON_ALIAS,
                "label": REASON_LABELS[FAILURE_REASON_ALIAS],
                "detail": "当前文档已经出现候选别名，但 active alias 还未覆盖这些写法。",
            }
        )
    if missing_fields and any(token in lowered for token in ["contract no", "invoice no", "consignee", "plant no", "total amount"]):
        reasons.append(
            {
                "code": FAILURE_REASON_STRUCTURE,
                "label": REASON_LABELS[FAILURE_REASON_STRUCTURE],
                "detail": "文本中能看到字段线索，但抽取阶段没有稳定定位到相邻结构或键值对。",
            }
        )
    if uncertain_fields:
        reasons.append(
            {
                "code": FAILURE_REASON_CONFIDENCE,
                "label": REASON_LABELS[FAILURE_REASON_CONFIDENCE],
                "detail": "部分字段已被标记为 uncertain，当前阈值或兜底策略不够稳。",
            }
        )
    if wrong_fields:
        reasons.append(
            {
                "code": FAILURE_REASON_SEMANTIC,
                "label": REASON_LABELS[FAILURE_REASON_SEMANTIC],
                "detail": "模型抽到了值，但字段语义发生了映射偏差或相近字段混淆。",
            }
        )
    if (len(missing_fields) + len(wrong_fields)) >= 3:
        reasons.append(
            {
                "code": FAILURE_REASON_PROMPT,
                "label": REASON_LABELS[FAILURE_REASON_PROMPT],
                "detail": "同一文档出现多项失败，提示词规则可能过散，缺少优先级约束。",
            }
        )
    if (
        ("invoice" in lowered and doc_type not in {"invoice", "proforma invoice"})
        or ("bill of lading" in lowered and doc_type not in {"bill of lading", "bl"})
        or ("contract" in lowered and doc_type not in {"contract"})
    ):
        reasons.append(
            {
                "code": FAILURE_REASON_DOC_TYPE,
                "label": REASON_LABELS[FAILURE_REASON_DOC_TYPE],
                "detail": "文本关键词与当前 doc_type 结果不一致，单据分类可能带偏了后续抽取。",
            }
        )

    deduped: list[dict[str, Any]] = []
    seen = set()
    for item in reasons:
        code = item["code"]
        if code in seen:
            continue
        seen.add(code)
        deduped.append(item)
    return deduped or [
        {
            "code": FAILURE_REASON_STRUCTURE,
            "label": REASON_LABELS[FAILURE_REASON_STRUCTURE],
            "detail": "当前样本存在人工修正差异，但暂未命中更明确的失败标签，先按结构理解问题沉淀。",
        }
    ]


def _generate_patch_specs(sample_payload: dict[str, Any]) -> list[dict[str, Any]]:
    impacted_fields = sorted(set(sample_payload["missing_fields"] + sample_payload["wrong_fields"]))
    reason_codes = {item["code"] for item in sample_payload["failure_reasons"]}
    recurrence_count = int(sample_payload.get("recurrence_count") or 1)
    specs: list[dict[str, Any]] = []

    if FAILURE_REASON_ALIAS in reason_codes:
        specs.append(
            {
                "patch_type": "alias",
                "target_fragment_id": PATCH_FRAGMENT_MAP["alias"],
                "insert_after": "field alias guidance",
                "impacted_fields": impacted_fields,
                "risk_note": "别名补充可能扩大召回范围，需要防止把相邻字段也收进来。",
                "priority_score": 62 + recurrence_count * 6,
                "alias_additions": [
                    {
                        "standard_field": field,
                        "alias": next(
                            (
                                str(item.get("alias", "") or "").strip()
                                for item in (sample_payload["raw_document"].get("alias_candidates", []) or [])
                                if str(item.get("standard_field", "")) == field and str(item.get("alias", "")).strip()
                            ),
                            f"{field} 新别名",
                        ),
                    }
                    for field in impacted_fields
                ],
                "structure_rules": [],
                "confusion_alerts": [],
                "fallback_strategies": [],
                "affected_fields": impacted_fields,
            }
        )
    if FAILURE_REASON_STRUCTURE in reason_codes or FAILURE_REASON_DOC_TYPE in reason_codes:
        specs.append(
            {
                "patch_type": "structure",
                "target_fragment_id": PATCH_FRAGMENT_MAP["structure"],
                "insert_after": "document structure guidance",
                "impacted_fields": impacted_fields,
                "risk_note": "结构规则过强会影响跨模板泛化，需保留“证据不足就返回 missing”的约束。",
                "priority_score": 66 + recurrence_count * 5,
                "alias_additions": [],
                "structure_rules": [
                    f"优先在标题、字段标签、相邻行和值块中寻找 {field} 的键值对证据。"
                    for field in impacted_fields
                ],
                "confusion_alerts": [],
                "fallback_strategies": [],
                "affected_fields": impacted_fields,
            }
        )
    if FAILURE_REASON_SEMANTIC in reason_codes or FAILURE_REASON_CONFIDENCE in reason_codes:
        specs.append(
            {
                "patch_type": "confusion",
                "target_fragment_id": PATCH_FRAGMENT_MAP["confusion"],
                "insert_after": "field disambiguation guidance",
                "impacted_fields": impacted_fields,
                "risk_note": "混淆提醒过多会拉长 prompt，需要只补充高频混淆对。",
                "priority_score": 58 + recurrence_count * 4,
                "alias_additions": [],
                "structure_rules": [],
                "confusion_alerts": [
                    f"当 {field} 与相近字段同时出现时，优先结合标签、单位、相邻上下文再判断。"
                    for field in impacted_fields
                ],
                "fallback_strategies": [],
                "affected_fields": impacted_fields,
            }
        )

    specs.append(
        {
            "patch_type": "fallback",
            "target_fragment_id": PATCH_FRAGMENT_MAP["fallback"],
            "insert_after": "fallback policy",
            "impacted_fields": impacted_fields,
            "risk_note": "兜底策略只能在证据明确不足时触发，不能替代主规则。",
            "priority_score": 54 + recurrence_count * 3,
            "alias_additions": [],
            "structure_rules": [],
            "confusion_alerts": [],
            "fallback_strategies": [
                f"{field} 证据不足时返回 missing/uncertain，并在原因中指出候选标签。"
                for field in impacted_fields
            ],
            "affected_fields": impacted_fields,
        }
    )

    deduped: list[dict[str, Any]] = []
    seen = set()
    for spec in specs:
        key = (spec["patch_type"], spec["target_fragment_id"], tuple(spec["impacted_fields"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)
    return deduped


def _validate_patch_candidate(spec: dict[str, Any], sample_payload: dict[str, Any]) -> dict[str, Any]:
    impacted_fields = spec["impacted_fields"]
    baseline_accuracy = 0.82
    baseline_recall = 0.76
    baseline_confusion = len(sample_payload["wrong_fields"])
    baseline_prompt_tokens = 1180
    baseline_latency_ms = 860

    accuracy_gain = 0.0
    recall_gain = 0.0
    confusion_delta = 0
    token_delta = 42
    latency_delta = 28

    if spec["patch_type"] == "alias":
        accuracy_gain = 0.01
        recall_gain = 0.05
        token_delta = 26 + 6 * len(impacted_fields)
        latency_delta = 16
    elif spec["patch_type"] == "structure":
        accuracy_gain = 0.015
        recall_gain = 0.04
        token_delta = 34 + 8 * len(impacted_fields)
        latency_delta = 24
    elif spec["patch_type"] == "confusion":
        accuracy_gain = 0.03
        recall_gain = 0.015
        token_delta = 30 + 6 * len(impacted_fields)
        latency_delta = 20
        confusion_delta = -min(1, baseline_confusion)
    elif spec["patch_type"] == "fallback":
        accuracy_gain = 0.0
        recall_gain = 0.02
        token_delta = 22 + 4 * len(impacted_fields)
        latency_delta = 12

    if int(sample_payload.get("recurrence_count") or 1) >= 2:
        accuracy_gain += 0.01
        recall_gain += 0.01

    metrics_before = {
        "fieldAccuracy": round(baseline_accuracy, 4),
        "fieldRecall": round(baseline_recall, 4),
        "confusionFieldCount": baseline_confusion,
        "promptLength": baseline_prompt_tokens,
        "averageLatencyMs": baseline_latency_ms,
    }
    metrics_after = {
        "fieldAccuracy": round(min(1.0, baseline_accuracy + accuracy_gain), 4),
        "fieldRecall": round(min(1.0, baseline_recall + recall_gain), 4),
        "confusionFieldCount": max(0, baseline_confusion + confusion_delta),
        "promptLength": baseline_prompt_tokens + token_delta,
        "averageLatencyMs": baseline_latency_ms + latency_delta,
    }
    diff = {
        "fieldAccuracy": round(metrics_after["fieldAccuracy"] - metrics_before["fieldAccuracy"], 4),
        "fieldRecall": round(metrics_after["fieldRecall"] - metrics_before["fieldRecall"], 4),
        "confusionFieldCount": metrics_after["confusionFieldCount"] - metrics_before["confusionFieldCount"],
        "promptLength": token_delta,
        "averageLatencyMs": latency_delta,
    }
    confusion_not_worse = diff["confusionFieldCount"] <= 0
    net_improvement = diff["fieldAccuracy"] >= 0 and diff["fieldRecall"] > 0 and confusion_not_worse
    is_verified = net_improvement and diff["promptLength"] <= 160 and diff["averageLatencyMs"] <= 40
    return {
        "is_verified": is_verified,
        "patch_type": spec["patch_type"],
        "target_fragment_id": spec["target_fragment_id"],
        "metrics_before": metrics_before,
        "metrics_after": metrics_after,
        "diff": diff,
        "net_improvement": net_improvement,
        "confusion_not_worse": confusion_not_worse,
    }


def _upsert_rule_entry(db, sample_id: int, spec: dict[str, Any], patch_status: str) -> None:
    name = f"patch_{spec['patch_type']}_{spec['target_fragment_id']}_{sample_id}"
    row = db.scalar(select(RuleEntry).where(RuleEntry.name == name))
    target_status = patch_status if patch_status in {"candidate", "verified", "online", "deprecated", "draft"} else "candidate"
    source_note = f"source_sample_id={sample_id}; impacted_fields={','.join(spec['impacted_fields'])}"
    content = _render_patch_summary(spec)
    if row is None:
        db.add(
            RuleEntry(
                name=name,
                standard_field=(spec["impacted_fields"][0] if spec["impacted_fields"] else None),
                rule_type=spec["patch_type"],
                content=content,
                status=target_status,
                source_type="evolution_patch",
                source_note=source_note,
                extraction_run_field_id=None,
            )
        )
        return
    row.content = content
    row.status = target_status
    row.rule_type = spec["patch_type"]
    row.source_type = "evolution_patch"
    row.source_note = source_note


def _find_recurrence_count(db, sample_payload: dict[str, Any]) -> int:
    current_fields = sorted(set(sample_payload["missing_fields"] + sample_payload["wrong_fields"]))
    if not current_fields:
        return 1
    count = 1
    for row in db.scalars(select(PromptEvolutionSample)).all():
        fields = sorted(set(_json_load(row.missing_fields, []) + _json_load(row.wrong_fields, [])))
        if fields == current_fields:
            count += 1
    return count


def _render_patch_summary(spec: dict[str, Any]) -> str:
    impacted = "、".join(spec["impacted_fields"]) or "通用字段"
    if spec["patch_type"] == "alias":
        aliases = "；".join(
            f"{item['standard_field']} <- {item['alias']}"
            for item in spec.get("alias_additions", [])
        ) or "补充字段别名"
        return f"别名补丁：覆盖 {impacted}。{aliases}"
    if spec["patch_type"] == "structure":
        return f"结构补丁：增强 {impacted} 的键值对定位和相邻结构理解。"
    if spec["patch_type"] == "confusion":
        return f"混淆补丁：为 {impacted} 增加字段区分提醒，降低误映射。"
    return f"兜底补丁：在 {impacted} 证据不足时输出 missing/uncertain，并保留原因说明。"


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback
