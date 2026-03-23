from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from audit_system.db.session import SessionLocal
from audit_system.models import AliasEntry, PromptVersion, RuleEntry
from utils.json_utils import dump_json_text, load_json_text

PROMPTS_DIR = Path("llm/prompts")
KNOWLEDGE_DIR = Path("knowledge")


@dataclass(slots=True)
class PromptVersionRef:
    name: str
    content: str
    source_path: str | None = None

    def read_text(self, encoding: str = "utf-8") -> str:
        return self.content

    def __str__(self) -> str:
        return self.source_path or self.name


def list_prompt_version_refs() -> list[PromptVersionRef]:
    _sync_prompt_versions_from_files()
    with SessionLocal() as db:
        prompts = db.scalars(select(PromptVersion).order_by(PromptVersion.name.asc())).all()
        if prompts:
            return [
                PromptVersionRef(name=item.name, content=item.content, source_path=item.source_path)
                for item in prompts
            ]
    return []


def get_prompt_text(prompt_name: str) -> str:
    _sync_prompt_versions_from_files()
    with SessionLocal() as db:
        prompt = db.scalar(select(PromptVersion).where(PromptVersion.name == prompt_name))
        if prompt is None:
            raise FileNotFoundError(f"????????: {prompt_name}")
        return prompt.content


def load_knowledge_payload(path: Path) -> Any:
    loader = {
        "alias_active.json": _load_alias_active,
        "alias_candidates.json": _load_alias_candidates,
        "rule_active.json": _load_rule_active,
        "rule_candidates.json": _load_rule_candidates,
    }.get(path.name)
    if loader is None:
        if not path.exists():
            return {} if "alias" in path.name else []
        return load_json_text(path.read_text(encoding="utf-8"))
    return loader(path)


def save_knowledge_payload(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_json_text(payload), encoding="utf-8")
    saver = {
        "alias_active.json": _save_alias_active,
        "alias_candidates.json": _save_alias_candidates,
        "rule_active.json": _save_rule_active,
        "rule_candidates.json": _save_rule_candidates,
    }.get(path.name)
    if saver is not None:
        saver(payload, path)


def refresh_knowledge_snapshot(path: Path) -> Any:
    payload = load_knowledge_payload(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_json_text(payload), encoding="utf-8")
    return payload


def _sync_prompt_versions_from_files() -> None:
    prompt_files = sorted(PROMPTS_DIR.glob("*.txt"))
    if not prompt_files:
        return
    with SessionLocal() as db:
        for prompt_path in prompt_files:
            content = prompt_path.read_text(encoding="utf-8")
            item = db.scalar(select(PromptVersion).where(PromptVersion.name == prompt_path.name))
            if item is None:
                item = PromptVersion(
                    name=prompt_path.name,
                    category="extract" if "extract" in prompt_path.name else "compare",
                    content=content,
                    source_path=str(prompt_path),
                    is_active=prompt_path.name == "extract_prompt_v1.txt",
                )
                db.add(item)
            else:
                item.content = content
                item.source_path = str(prompt_path)
        db.commit()


def _load_alias_active(path: Path) -> dict[str, list[str]]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(AliasEntry)
            .where(AliasEntry.status == "active")
            .order_by(AliasEntry.standard_field.asc(), AliasEntry.alias_text.asc())
        ).all()
        if rows or _has_any_alias_rows(db):
            grouped: dict[str, list[str]] = {}
            seen: set[tuple[str, str]] = set()
            for row in rows:
                normalized_alias = str(row.alias_text_normalized or _normalize_alias(row.alias_text))
                key = (row.standard_field, normalized_alias)
                if key in seen:
                    continue
                seen.add(key)
                grouped.setdefault(row.standard_field, []).append(row.alias_text)
            return grouped
    payload = _read_json_payload(path, {})
    _save_alias_active(payload, path)
    return payload


def _load_alias_candidates(path: Path) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(AliasEntry)
            .where(AliasEntry.status == "candidate")
            .order_by(AliasEntry.standard_field.asc(), AliasEntry.alias_text.asc())
        ).all()
        if rows or _has_any_alias_rows(db):
            result: list[dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()
            for row in rows:
                normalized_alias = str(row.alias_text_normalized or _normalize_alias(row.alias_text))
                key = (row.standard_field, normalized_alias)
                if key in seen:
                    continue
                seen.add(key)
                result.append(
                    {
                        "standard_field": row.standard_field,
                        "alias": row.alias_text,
                        "source": row.source_note or row.source_type,
                        "confidence": row.confidence_score,
                    }
                )
            return result
    payload = _read_json_payload(path, [])
    _save_alias_candidates(payload, path)
    return payload


def _load_rule_active(path: Path) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(RuleEntry)
            .where(RuleEntry.status.in_(("active", "online")))
            .order_by(RuleEntry.name.asc())
        ).all()
        if rows or _has_any_rule_rows(db):
            return [
                {
                    "name": row.name,
                    "field": row.standard_field,
                    "description": row.content,
                    "rule_type": row.rule_type,
                }
                for row in rows
            ]
    payload = _read_json_payload(path, [])
    _save_rule_active(payload, path)
    return payload


def _load_rule_candidates(path: Path) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.scalars(select(RuleEntry).where(RuleEntry.status == "candidate").order_by(RuleEntry.name.asc())).all()
        if rows or _has_any_rule_rows(db):
            return [
                {
                    "name": row.name,
                    "field": row.standard_field,
                    "description": row.content,
                    "rule_type": row.rule_type,
                }
                for row in rows
            ]
    payload = _read_json_payload(path, [])
    _save_rule_candidates(payload, path)
    return payload


def _save_alias_active(payload: Any, path: Path) -> None:
    rows: list[AliasEntry] = []
    seen: set[tuple[str, str]] = set()
    if isinstance(payload, dict):
        for field, aliases in payload.items():
            field_name = str(field or "").strip()
            for alias in aliases or []:
                alias_text = str(alias or "").strip()
                normalized_alias = _normalize_alias(alias_text)
                key = (field_name, normalized_alias)
                if not field_name or not normalized_alias or key in seen:
                    continue
                seen.add(key)
                rows.append(_build_alias_entry(field_name, alias_text, "active", "json_sync", str(path), None))
    _replace_alias_rows("active", rows)


def _save_alias_candidates(payload: Any, path: Path) -> None:
    rows: list[AliasEntry] = []
    seen: set[tuple[str, str]] = set()
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            field_name = str(item.get("standard_field", "") or "").strip()
            alias_text = str(item.get("alias", "") or "").strip()
            normalized_alias = _normalize_alias(alias_text)
            key = (field_name, normalized_alias)
            if not field_name or not normalized_alias or key in seen:
                continue
            seen.add(key)
            rows.append(
                _build_alias_entry(
                    field_name,
                    alias_text,
                    "candidate",
                    "json_sync",
                    str(item.get("source", item.get("reason", str(path)))),
                    _to_float(item.get("confidence")),
                )
            )
    _replace_alias_rows("candidate", rows)


def _save_rule_active(payload: Any, path: Path) -> None:
    rows = _build_rule_rows(payload, "active", path)
    _replace_rule_rows("active", rows)


def _save_rule_candidates(payload: Any, path: Path) -> None:
    rows = _build_rule_rows(payload, "candidate", path)
    _replace_rule_rows("candidate", rows)


def _has_any_alias_rows(db) -> bool:
    return db.scalar(select(AliasEntry.id).limit(1)) is not None


def _has_any_rule_rows(db) -> bool:
    return db.scalar(select(RuleEntry.id).limit(1)) is not None


def _build_rule_rows(payload: Any, status: str, path: Path) -> list[RuleEntry]:
    rows: list[RuleEntry] = []
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            rows.append(
                RuleEntry(
                    name=str(item.get("name", "")),
                    standard_field=str(item.get("field", item.get("applicable_field", ""))) or None,
                    rule_type=str(item.get("rule_type", item.get("type", "mapping"))),
                    content=str(item.get("description", item.get("content", ""))),
                    status=status,
                    source_type="json_sync",
                    source_note=str(path),
                )
            )
    return rows


def _replace_alias_rows(status: str, rows: list[AliasEntry]) -> None:
    with SessionLocal() as db:
        db.execute(delete(AliasEntry).where(AliasEntry.status == status))
        seen: set[tuple[str, str]] = set()
        for row in rows:
            key = (row.standard_field, row.alias_text_normalized)
            if not row.standard_field or not row.alias_text or key in seen:
                continue
            seen.add(key)
            db.add(row)
        db.commit()


def _replace_rule_rows(status: str, rows: list[RuleEntry]) -> None:
    with SessionLocal() as db:
        db.execute(delete(RuleEntry).where(RuleEntry.status == status))
        for row in rows:
            if row.name and row.content:
                db.add(row)
        db.commit()


def _build_alias_entry(
    standard_field: str,
    alias_text: str,
    status: str,
    source_type: str,
    source_note: str | None,
    confidence_score: float | None,
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
    )


def _clean_alias_text(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_alias(value: str) -> str:
    return _clean_alias_text(value).lower()


def _read_json_payload(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return load_json_text(path.read_text(encoding="utf-8"))


def _to_float(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None
