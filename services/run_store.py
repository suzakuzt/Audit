from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from audit_system.db.session import SessionLocal
from audit_system.models import AliasEntry, ExtractionRun, ExtractionRunDocument, ExtractionRunField, PromptVersion, RuleEntry
from services.knowledge_store import refresh_knowledge_snapshot


REVIEW_STATUS_MAPPED = "mapped"
REVIEW_STATUS_MISSING = "missing"
REVIEW_STATUS_UNCERTAIN = "uncertain"
REVIEW_STATUS_CONFIRMED = "confirmed"
REVIEW_STATUS_CORRECT = "correct"
REVIEW_STATUS_WRONG = "wrong"
KNOWLEDGE_DIR = Path("knowledge")


def persist_extraction_run(
    run_key: str,
    output_dir: str,
    batch_summary: dict[str, Any],
    version_record: dict[str, Any],
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    with SessionLocal() as db:
        prompt = db.scalar(select(PromptVersion).where(PromptVersion.name == version_record.get("prompt_file_name", "")))
        run = ExtractionRun(
            run_key=run_key,
            output_dir=output_dir,
            prompt_version_id=prompt.id if prompt else None,
            prompt_name=version_record.get("prompt_file_name", ""),
            model_name=version_record.get("model_name", ""),
            ocr_model=version_record.get("ocr_model"),
            llm_base_url=version_record.get("llm_base_url"),
            llm_timeout_seconds=version_record.get("timeout_seconds"),
            use_alias_active=bool(version_record.get("alias_source") != "disabled"),
            use_rule_active=bool(version_record.get("rule_source") != "disabled"),
            ocr_enabled=bool(version_record.get("ocr_enabled")),
            force_ocr=bool(version_record.get("force_ocr")),
            total_documents=int(batch_summary.get("total_documents", 0)),
            text_valid_documents=int(batch_summary.get("text_valid_documents", 0)),
            avg_coverage_rate=float(batch_summary.get("document_coverage_rate", 0.0)),
            notes="database_first",
        )
        db.add(run)
        db.flush()

        for document in documents:
            doc_row = ExtractionRunDocument(
                run_id=run.id,
                filename=document.get("filename", ""),
                doc_type=document.get("doc_type"),
                extraction_method=document.get("raw_text_result", {}).get("extraction_method"),
                page_count=int(document.get("raw_text_result", {}).get("page_count", 0) or 0),
                is_text_valid=bool(document.get("raw_text_result", {}).get("is_text_valid")),
                raw_summary=document.get("raw_summary"),
                raw_model_response=document.get("raw_model_response"),
                warnings_text="\n".join(document.get("warnings", []) or []),
            )
            db.add(doc_row)
            db.flush()
            document["db_document_id"] = doc_row.id

            field_rows = _persist_document_fields(db, doc_row.id, document)
            field_by_standard = {row.standard_field: row for row in field_rows}

            for row in document.get("manual_confirmation_rows", []) or []:
                field_name = str(row.get("standard_field", ""))
                field_row = field_by_standard.get(field_name)
                if field_row is not None:
                    row["db_field_id"] = field_row.id

            for item in document.get("standard_mappings", []) or []:
                field_name = str(item.get("standard_field", ""))
                field_row = field_by_standard.get(field_name)
                if field_row is not None:
                    item["db_field_id"] = field_row.id

            _persist_alias_candidates(db, document.get("alias_candidates", []) or [], field_by_standard)
            _persist_rule_candidates(db, document.get("rule_candidates", []) or [], field_by_standard)

        db.commit()
        refresh_knowledge_snapshot(KNOWLEDGE_DIR / "alias_candidates.json")
        refresh_knowledge_snapshot(KNOWLEDGE_DIR / "rule_candidates.json")
        return {"db_run_id": run.id}


def apply_manual_confirmations(documents: list[dict[str, Any]], run_id: int | None = None) -> dict[str, Any]:
    updated_fields = 0
    promoted_aliases = 0
    duplicate_aliases: list[dict[str, str]] = []
    failed_aliases: list[dict[str, str]] = []
    with SessionLocal() as db:
        for document in documents:
            document_id = document.get("db_document_id")
            document_row = None
            if document_id:
                document_row = db.get(ExtractionRunDocument, int(document_id))
            if document_row is None and run_id and document.get("filename"):
                document_row = db.scalar(
                    select(ExtractionRunDocument).where(
                        ExtractionRunDocument.run_id == int(run_id),
                        ExtractionRunDocument.filename == str(document.get("filename", "")),
                    )
                )
            mapping_by_field = {
                str(item.get("standard_field", "")): item
                for item in document.get("standard_mappings", []) or []
                if item.get("standard_field")
            }
            for row in document.get("manual_confirmation_rows", []) or []:
                field = None
                field_id = row.get("db_field_id")
                if field_id:
                    field = db.get(ExtractionRunField, int(field_id))
                if field is None and document_row is not None and row.get("standard_field"):
                    field = db.scalar(
                        select(ExtractionRunField).where(
                            ExtractionRunField.document_id == int(document_row.id),
                            ExtractionRunField.standard_field == str(row.get("standard_field", "")),
                        )
                    )
                if field is None:
                    continue

                payload_mapping = mapping_by_field.get(field.standard_field, {})
                payload_source_field_name = str(payload_mapping.get("source_field_name", "") or "").strip()
                if payload_source_field_name:
                    field.source_field_name = payload_source_field_name
                if "source_value" in payload_mapping:
                    field.source_value = str(payload_mapping.get("source_value", "") or "") or None
                if "confidence" in payload_mapping:
                    field.confidence_score = _to_float(payload_mapping.get("confidence"))
                if "reason" in payload_mapping:
                    field.reason = str(payload_mapping.get("reason", "") or "") or None

                confirmed_value = str(row.get("confirmed_value", "") or "")
                ai_value = str(row.get("ai_value", "") or "")
                field.confirmed_value = confirmed_value
                field.review_status = _review_status(ai_value, confirmed_value)
                updated_fields += 1
                if bool(row.get("promote_alias", True)):
                    promote_result = _promote_alias_entry(db, field)
                    promoted_aliases += int(promote_result["promoted"])
                    if promote_result.get("failed"):
                        failed_aliases.append(
                            {
                                "standard_field": field.standard_field,
                                "alias": promote_result.get("alias_text", ""),
                                "message": promote_result.get("message", "alias ????"),
                            }
                        )
                    elif promote_result["duplicate"]:
                        duplicate_aliases.append(
                            {
                                "standard_field": field.standard_field,
                                "alias": promote_result["alias_text"],
                                "message": f"?? {field.standard_field} ? alias {promote_result['alias_text']} ??? active alias ??",
                            }
                        )
        db.commit()
    alias_snapshot = refresh_knowledge_snapshot(KNOWLEDGE_DIR / "alias_active.json")
    refresh_knowledge_snapshot(KNOWLEDGE_DIR / "alias_candidates.json")
    failed_aliases = [
        item for item in failed_aliases
        if _normalize_alias(item.get("alias", "")) not in {_normalize_alias(alias) for alias in (alias_snapshot.get(item.get("standard_field", ""), []) if isinstance(alias_snapshot, dict) else [])}
    ]
    return {
        "updated_fields": updated_fields,
        "promoted_aliases": promoted_aliases,
        "duplicate_alias_count": len(duplicate_aliases),
        "duplicate_aliases": duplicate_aliases,
        "failed_alias_count": len(failed_aliases),
        "failed_aliases": failed_aliases,
    }


def _persist_document_fields(db, document_id: int, document: dict[str, Any]) -> list[ExtractionRunField]:
    mapped_lookup = {
        str(item.get("standard_field", "")): item
        for item in document.get("standard_mappings", []) or []
        if item.get("standard_field")
    }
    missing_fields = set(document.get("missing_fields", []) or [])
    uncertain_fields = set(document.get("uncertain_fields", []) or [])
    rows: list[ExtractionRunField] = []
    for manual_row in document.get("manual_confirmation_rows", []) or []:
        field_name = str(manual_row.get("standard_field", ""))
        if not field_name:
            continue
        mapped = mapped_lookup.get(field_name, {})
        field_row = ExtractionRunField(
            document_id=document_id,
            standard_field=field_name,
            standard_label_cn=str(manual_row.get("standard_label_cn", field_name)),
            source_field_name=mapped.get("source_field_name") or None,
            source_value=str(manual_row.get("ai_value", "") or "") or None,
            confidence_score=_to_float(mapped.get("confidence")),
            reason=mapped.get("reason") or None,
            review_status=_initial_review_status(field_name, missing_fields, uncertain_fields, str(manual_row.get("ai_value", "") or "")),
            confirmed_value=str(manual_row.get("confirmed_value", "") or "") or None,
        )
        db.add(field_row)
        db.flush()
        rows.append(field_row)
    return rows


def _persist_alias_candidates(db, alias_candidates: list[dict[str, Any]], field_by_standard: dict[str, ExtractionRunField]) -> None:
    field_names = {
        str(item.get("standard_field", "")).strip()
        for item in alias_candidates
        if isinstance(item, dict) and str(item.get("standard_field", "")).strip()
    }
    existing_aliases = _existing_alias_map(db, field_names)
    seen_keys = set(existing_aliases)

    for item in alias_candidates:
        if not isinstance(item, dict):
            continue
        field_name = str(item.get("standard_field", "")).strip()
        alias_text = str(item.get("alias", "")).strip()
        normalized_alias = _normalize_alias(alias_text)
        if not field_name or not normalized_alias:
            continue
        key = (field_name, normalized_alias)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        field_row = field_by_standard.get(field_name)
        db.add(
            _build_alias_entry(
                standard_field=field_name,
                alias_text=alias_text,
                status="candidate",
                source_type="extraction_run",
                source_note=str(item.get("reason", "candidate alias")),
                confidence_score=_to_float(item.get("confidence")),
                extraction_run_field_id=field_row.id if field_row else None,
            )
        )


def _persist_rule_candidates(db, rule_candidates: list[dict[str, Any]], field_by_standard: dict[str, ExtractionRunField]) -> None:
    for item in rule_candidates:
        rule_name = str(item.get("name", ""))
        field_name = str(item.get("field", "")) or None
        if not rule_name:
            continue
        field_row = field_by_standard.get(field_name or "") if field_name else None
        db.add(
            RuleEntry(
                name=rule_name,
                standard_field=field_name,
                rule_type="candidate",
                content=str(item.get("reason", item.get("description", "candidate rule"))),
                status="candidate",
                source_type="extraction_run",
                source_note="candidate from extraction run",
                extraction_run_field_id=field_row.id if field_row else None,
            )
        )


def _promote_alias_entry(db, field: ExtractionRunField) -> dict[str, Any]:
    alias_text = _clean_alias_text(field.source_field_name or "")
    normalized_alias = _normalize_alias(alias_text)
    if not normalized_alias:
        return {"promoted": 0, "duplicate": False, "failed": True, "alias_text": alias_text, "message": "??????????? alias ?"}

    siblings = _find_alias_entries(db, field.standard_field, alias_text)
    candidate = next((row for row in siblings if row.status == "candidate"), None)
    active = next((row for row in siblings if row.status == "active"), None)

    if active is not None:
        for row in siblings:
            if row.status == "candidate":
                db.delete(row)
        active.extraction_run_field_id = field.id
        active.confidence_score = field.confidence_score
        return {"promoted": 0, "duplicate": True, "alias_text": alias_text}

    if candidate is not None:
        for row in siblings:
            if row is not candidate:
                db.delete(row)
        db.flush()
        candidate.alias_text = alias_text
        candidate.alias_text_normalized = normalized_alias
        candidate.status = "active"
        candidate.source_type = "manual_confirmed"
        candidate.source_note = f"confirmed from extraction_run_field:{field.id}"
        candidate.extraction_run_field_id = field.id
        candidate.confidence_score = field.confidence_score
        return {"promoted": 1, "duplicate": False, "alias_text": alias_text}

    db.add(
        _build_alias_entry(
            standard_field=field.standard_field,
            alias_text=alias_text,
            status="active",
            source_type="manual_confirmed",
            source_note=f"confirmed from extraction_run_field:{field.id}",
            confidence_score=field.confidence_score,
            extraction_run_field_id=field.id,
        )
    )
    return {"promoted": 1, "duplicate": False, "alias_text": alias_text}


def _existing_alias_map(db, field_names: set[str]) -> dict[tuple[str, str], AliasEntry]:
    if not field_names:
        return {}
    rows = db.scalars(select(AliasEntry).where(AliasEntry.standard_field.in_(sorted(field_names)))).all()
    result: dict[tuple[str, str], AliasEntry] = {}
    for row in rows:
        key = (str(row.standard_field), str(row.alias_text_normalized or _normalize_alias(row.alias_text)))
        result.setdefault(key, row)
    return result


def _find_alias_entries(db, standard_field: str, alias_text: str) -> list[AliasEntry]:
    normalized_alias = _normalize_alias(alias_text)
    if not normalized_alias:
        return []
    rows = db.scalars(select(AliasEntry).where(AliasEntry.standard_field == standard_field)).all()
    return [row for row in rows if _normalize_alias(str(row.alias_text or "")) == normalized_alias]


def _build_alias_entry(
    standard_field: str,
    alias_text: str,
    status: str,
    source_type: str,
    source_note: str | None,
    confidence_score: float | None,
    extraction_run_field_id: int | None,
) -> AliasEntry:
    cleaned_alias = _clean_alias_text(alias_text)
    return AliasEntry(
        standard_field=standard_field,
        alias_text=cleaned_alias,
        alias_text_normalized=_normalize_alias(cleaned_alias),
        status=status,
        source_type=source_type,
        source_note=source_note,
        confidence_score=confidence_score,
        extraction_run_field_id=extraction_run_field_id,
    )


def _clean_alias_text(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_alias(value: str) -> str:
    return _clean_alias_text(value).lower()


def _initial_review_status(field_name: str, missing_fields: set[str], uncertain_fields: set[str], ai_value: str) -> str:
    if field_name in missing_fields:
        return REVIEW_STATUS_MISSING
    if field_name in uncertain_fields:
        return REVIEW_STATUS_UNCERTAIN
    if ai_value.strip():
        return REVIEW_STATUS_MAPPED
    return "pending"


def _review_status(ai_value: str, confirmed_value: str) -> str:
    ai_norm = " ".join(ai_value.strip().lower().split())
    confirmed_norm = " ".join(confirmed_value.strip().lower().split())
    if not ai_norm and not confirmed_norm:
        return "empty"
    if confirmed_norm and not ai_norm:
        return REVIEW_STATUS_MISSING
    if ai_norm == confirmed_norm:
        return REVIEW_STATUS_CORRECT
    return REVIEW_STATUS_WRONG


def _to_float(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None
