from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from audit_system.models.prompt_learning_record import PromptLearningRecord
from audit_system.models.prompt_suggestion import PromptSuggestion
from schemas.document_schema import STANDARD_FIELD_LABELS

PROMPTS_DIR = Path('llm/prompts')

PROMPT_FILES = {
    'base': 'audit_learning_base_prompt.txt',
    'classify': 'audit_doc_classify_prompt.txt',
    'field_understanding': 'audit_field_understanding_prompt.txt',
    'suggestion': 'audit_prompt_suggestion_prompt.txt',
}

DEFAULT_PROMPTS = {
    'base': '你是一个审单提示词学习助手，请先理解单据业务含义，再逐步沉淀审单经验。',
    'classify': '请先判断当前文件属于什么单据，并说明它在业务中的作用。',
    'field_understanding': '请在识别单据后，继续理解文档中的业务字段含义。',
    'suggestion': '请根据识别结果与人工修正差异，输出提示词补充建议。',
}

DEFAULT_PROMPT_FLAGS = {
    'classify': True,
    'field_understanding': True,
    'suggestion': True,
}

DOC_TYPE_ROLES = {
    '合同': '交易基准单据，用于确认买卖双方、品名、数量、价格、金额、付款条款、贸易条款和装运安排。',
    '发票': '执行与结算单据，用于确认本票实际成交金额和执行内容。',
    '装箱单': '说明货物装箱、箱数、重量和包装情况。',
    '无木制装箱声明': '用于声明货物包装不含木质包装材料。',
    '批次清单': '记录批次、生产、屠宰和保质期等追溯信息。',
    '原产地证书': '用于证明货物原产地。',
    '卫生证': '用于证明货物符合卫生、检疫或食品安全要求。',
    '提单': '运输承运单据，体现承运、船名、航次、港口、柜号和封号等运输信息。',
    '清真证书': '用于证明货物符合清真要求。',
    'Unknown': '当前证据不足，暂时无法稳定判断具体单据类型。',
}

DOC_TYPE_KEYWORDS = {
    '合同': ['contract', 'sales contract', 'buyer', 'seller', 'payment term', 'trade term'],
    '发票': ['invoice', 'proforma invoice', 'invoice no', 'amount due'],
    '装箱单': ['packing list', 'carton', 'gross weight', 'net weight', 'packages'],
    '无木制装箱声明': ['non-wood', 'no wood packing', 'wood packaging'],
    '批次清单': ['batch', 'lot', 'slaughter', 'production date', 'expiry'],
    '原产地证书': ['certificate of origin', 'origin criterion', 'country of origin'],
    '卫生证': ['health certificate', 'sanitary', 'inspection', 'quarantine'],
    '提单': ['bill of lading', 'vessel', 'voyage', 'container no', 'seal no', 'notify party'],
    '清真证书': ['halal', 'halal certificate'],
}


def normalize_prompt_flags(prompt_flags: dict[str, Any] | None = None) -> dict[str, bool]:
    incoming = prompt_flags or {}
    return {key: bool(incoming.get(key, default)) for key, default in DEFAULT_PROMPT_FLAGS.items()}


def load_prompt_learning_config() -> dict[str, Any]:
    prompt_texts: dict[str, str] = {}
    for key, file_name in PROMPT_FILES.items():
        path = PROMPTS_DIR / file_name
        if path.exists():
            prompt_texts[key] = path.read_text(encoding='utf-8')
        else:
            prompt_texts[key] = DEFAULT_PROMPTS[key]
    return {
        'prompt_texts': prompt_texts,
        'prompt_flags': normalize_prompt_flags(),
        'doc_roles': DOC_TYPE_ROLES,
    }


def analyze_documents_for_learning(
    documents: list[dict[str, Any]],
    prompt_context: dict[str, str] | None = None,
    prompt_flags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_flags = normalize_prompt_flags(prompt_flags)
    analyzed_documents = []
    all_suggestions: list[dict[str, Any]] = []
    for doc in documents or []:
        doc_result = _analyze_single_document(doc, normalized_flags)
        analyzed_documents.append(doc_result)
        all_suggestions.extend(doc_result['prompt_suggestions'])
    deduped_suggestions = _dedupe_suggestions(all_suggestions)
    return {
        'prompt_context': prompt_context or {},
        'prompt_flags': normalized_flags,
        'documents': analyzed_documents,
        'prompt_suggestions': deduped_suggestions,
    }


def save_learning_feedback(
    db: Session,
    *,
    run_key: str | None,
    prompt_name: str | None,
    analysis_result: dict[str, Any],
    feedback_items: list[dict[str, Any]],
) -> dict[str, Any]:
    feedback_map = {str(item.get('filename', '')): item for item in feedback_items or []}
    created_records = []
    created_suggestions = 0
    for doc in analysis_result.get('documents', []):
        filename = str(doc.get('filename', ''))
        record = PromptLearningRecord(
            run_key=run_key,
            filename=filename or 'unknown.pdf',
            prompt_name=prompt_name,
            doc_type_result=json.dumps(doc.get('doc_type_result', {}), ensure_ascii=False),
            field_result=json.dumps(doc.get('field_understanding', []), ensure_ascii=False),
            human_feedback=json.dumps(feedback_map.get(filename, {}), ensure_ascii=False),
            suggestion_result=json.dumps(doc.get('prompt_suggestions', []), ensure_ascii=False),
            status='reviewed' if feedback_map.get(filename) else 'pending',
        )
        db.add(record)
        db.flush()
        for item in doc.get('prompt_suggestions', []):
            db.add(PromptSuggestion(
                learning_record_id=record.id,
                suggestion_type=str(item.get('suggestion_type', 'general')),
                target_scope=str(item.get('target_scope', 'global')),
                suggestion_text=str(item.get('suggestion_text', '')),
                why=str(item.get('why', '')),
                priority=str(item.get('priority', 'medium')),
                is_adopted=False,
            ))
            created_suggestions += 1
        created_records.append(record.id)
    db.commit()
    return {
        'created_records': created_records,
        'created_suggestions': created_suggestions,
        'total_documents': len(created_records),
    }


def list_learning_history(db: Session, limit: int = 20) -> dict[str, Any]:
    records = db.scalars(select(PromptLearningRecord).order_by(PromptLearningRecord.created_at.desc()).limit(limit)).all()
    suggestions = db.scalars(select(PromptSuggestion).order_by(PromptSuggestion.created_at.desc()).limit(limit)).all()
    return {
        'records': [
            {
                'id': item.id,
                'filename': item.filename,
                'prompt_name': item.prompt_name,
                'status': item.status,
                'created_at': item.created_at.isoformat() if item.created_at else None,
                'doc_type_result': _json_load(item.doc_type_result, {}),
                'human_feedback': _json_load(item.human_feedback, {}),
            }
            for item in records
        ],
        'suggestions': [
            {
                'id': item.id,
                'learning_record_id': item.learning_record_id,
                'suggestion_type': item.suggestion_type,
                'target_scope': item.target_scope,
                'suggestion_text': item.suggestion_text,
                'why': item.why,
                'priority': item.priority,
                'is_adopted': item.is_adopted,
                'created_at': item.created_at.isoformat() if item.created_at else None,
            }
            for item in suggestions
        ],
    }


def _analyze_single_document(doc: dict[str, Any], prompt_flags: dict[str, bool]) -> dict[str, Any]:
    filename = str(doc.get('filename', 'document.pdf'))
    text = str(doc.get('raw_text_result', {}).get('text', '') or '')
    doc_type_result = _build_doc_type_result(doc, text, prompt_flags)
    field_understanding = _build_field_understanding(doc, text, prompt_flags)
    prompt_suggestions = _build_prompt_suggestions(doc, doc_type_result, field_understanding, prompt_flags)
    return {
        'filename': filename,
        'doc_type_result': doc_type_result,
        'field_understanding': field_understanding,
        'prompt_suggestions': prompt_suggestions,
    }


def _build_doc_type_result(doc: dict[str, Any], text: str, prompt_flags: dict[str, bool]) -> dict[str, Any]:
    if not prompt_flags.get('classify', True):
        extracted_doc_type = str(doc.get('doc_type', '') or '').strip() or 'Unknown'
        return {
            'doc_type': extracted_doc_type,
            'doc_role': '单据识别 Prompt 当前已禁用，本次不生成额外的单据类型学习判断。',
            'confidence': 0.0,
            'reasoning': ['单据识别 Prompt 已禁用，系统保留原始识别结果，不追加学习分析。'],
            'candidate_doc_types': [],
            'uncertain': False,
            'disabled': True,
        }

    text_lower = text.lower()
    scores = []
    for doc_type, keywords in DOC_TYPE_KEYWORDS.items():
        hits = [item for item in keywords if item in text_lower]
        scores.append({'type': doc_type, 'score': len(hits), 'hits': hits})
    scores.sort(key=lambda item: item['score'], reverse=True)
    extracted_doc_type = str(doc.get('doc_type', '') or '').strip()
    final_type = extracted_doc_type if extracted_doc_type and extracted_doc_type != 'Unknown' else (scores[0]['type'] if scores and scores[0]['score'] > 0 else 'Unknown')
    top_score = scores[0]['score'] if scores else 0
    next_score = scores[1]['score'] if len(scores) > 1 else 0
    confidence = 0.55
    if extracted_doc_type and final_type == extracted_doc_type:
        confidence += 0.18
    if top_score > 0:
        confidence += min(top_score * 0.08, 0.25)
    if top_score and next_score and top_score - next_score <= 1:
        confidence -= 0.12
    confidence = max(0.35, min(confidence, 0.96))

    reasons = []
    if extracted_doc_type:
        reasons.append(f'当前提取流程已返回单据类型：{extracted_doc_type}。')
    for keyword in (scores[0]['hits'] if scores and scores[0]['hits'] else [])[:3]:
        reasons.append(f'文本中命中了更接近“{final_type}”的关键词：{keyword}。')
    if not reasons:
        reasons.append('当前文本中的单据类型证据还不够充分，建议结合版式和人工判断继续确认。')

    candidates = []
    for item in scores[:3]:
        if item['score'] <= 0:
            continue
        candidates.append({
            'type': item['type'],
            'confidence': max(0.3, min(0.9, 0.35 + item['score'] * 0.12)),
            'reason': f"命中 {len(item['hits'])} 个关键词：{', '.join(item['hits'][:3])}",
        })
    uncertain = bool(candidates and len(candidates) > 1 and abs(candidates[0]['confidence'] - candidates[1]['confidence']) < 0.1)
    return {
        'doc_type': final_type,
        'doc_role': DOC_TYPE_ROLES.get(final_type, DOC_TYPE_ROLES['Unknown']),
        'confidence': round(confidence, 2),
        'reasoning': reasons,
        'candidate_doc_types': candidates,
        'uncertain': uncertain,
        'disabled': False,
    }


def _build_field_understanding(doc: dict[str, Any], text: str, prompt_flags: dict[str, bool]) -> list[dict[str, Any]]:
    if not prompt_flags.get('field_understanding', True):
        return []

    results = []
    for item in doc.get('standard_mappings', []) or []:
        standard_field = str(item.get('standard_field', ''))
        source_name = str(item.get('source_field_name', '') or '')
        source_value = str(item.get('source_value', '') or '')
        excerpt = _excerpt_around(text, source_name or source_value)
        standard_label = item.get('standard_label_cn') or STANDARD_FIELD_LABELS.get(standard_field, standard_field)
        results.append({
            'standard_field': standard_field,
            'standard_label': standard_label,
            'source_field_name': source_name,
            'source_value': source_value,
            'confidence': item.get('confidence', 0),
            'reason': item.get('reason') or f'系统根据字段标签或字段值上下文，判断“{source_name or source_value or standard_label}”更接近标准字段“{standard_label}”。',
            'evidence_excerpt': excerpt,
            'uncertain': bool(item.get('uncertain', False)),
            'candidate_meanings': [],
        })
    return results


def _build_prompt_suggestions(
    doc: dict[str, Any],
    doc_type_result: dict[str, Any],
    field_understanding: list[dict[str, Any]],
    prompt_flags: dict[str, bool],
) -> list[dict[str, Any]]:
    if not prompt_flags.get('suggestion', True):
        return []

    suggestions: list[dict[str, Any]] = []
    if doc_type_result.get('uncertain'):
        suggestions.append({
            'suggestion_type': 'doc_type',
            'target_scope': doc_type_result.get('doc_type', 'global'),
            'suggestion_text': f"补充“{doc_type_result.get('doc_type', '当前单据')}”与相近单据的区分说明，避免只因少量关键词命中就误判。",
            'why': '当前候选单据类型接近，说明单据识别提示词还需要更明确的区分依据。',
            'priority': 'high',
        })
    for field_name in doc.get('missing_fields', []) or []:
        suggestions.append({
            'suggestion_type': 'field_understanding',
            'target_scope': field_name,
            'suggestion_text': f"补充标准字段“{STANDARD_FIELD_LABELS.get(field_name, field_name)}”的业务含义说明，并提示模型结合上下文寻找可能的表达方式。",
            'why': '当前字段未稳定识别出来，说明字段业务理解提示还不够明确。',
            'priority': 'medium',
        })
    for item in field_understanding:
        confidence = float(item.get('confidence') or 0)
        if item.get('uncertain') or confidence < 0.75:
            suggestions.append({
                'suggestion_type': 'correction_rule',
                'target_scope': item.get('standard_field', 'global'),
                'suggestion_text': f"补充标准字段“{item.get('standard_label', item.get('standard_field', '字段'))}”的判断线索，强调相邻标签、业务语义和示例值的联合判断。",
                'why': '当前字段识别置信度偏低，容易在相近字段之间混淆。',
                'priority': 'medium',
            })
    if doc.get('alias_candidates'):
        suggestions.append({
            'suggestion_type': 'general',
            'target_scope': 'alias-learning',
            'suggestion_text': '保留本次候选字段叫法，待人工确认后再沉淀为别名经验，不要提前写死到正式提示词里。',
            'why': '当前识别已经出现新的候选叫法，适合先进入学习池，再决定是否采纳。',
            'priority': 'low',
        })
    return _dedupe_suggestions(suggestions)


def _dedupe_suggestions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    results = []
    for item in items:
        marker = (item.get('suggestion_type'), item.get('target_scope'), item.get('suggestion_text'))
        if marker in seen:
            continue
        seen.add(marker)
        results.append(item)
    return results


def _excerpt_around(text: str, token: str) -> str:
    if not text or not token:
        return ''
    lowered = text.lower()
    idx = lowered.find(token.lower())
    if idx == -1:
        return ''
    return text[max(0, idx - 50): min(len(text), idx + len(token) + 90)]


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or '')
    except Exception:
        return fallback
