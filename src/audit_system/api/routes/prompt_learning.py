from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from audit_system.db.session import get_db
from services.prompt_learning_service import list_learning_history, save_learning_feedback
from services.prompt_optimizer_service import (
    build_prompt_optimizer_config,
    optimize_prompt_fragments,
    rollback_prompt_center_version,
    run_prompt_test,
    save_prompt_center_version,
)
from services.prompt_evolution_service import transition_rule_patch_status

router = APIRouter()


class PromptLearningAnalyzePayload(BaseModel):
    documents: list[dict[str, Any]] = Field(default_factory=list)
    prompt_context: dict[str, str] = Field(default_factory=dict)
    prompt_flags: dict[str, bool] = Field(default_factory=dict)
    fragments: list[dict[str, Any]] = Field(default_factory=list)
    selected_fragment_ids: list[str] = Field(default_factory=list)
    test_case_ids: list[str] = Field(default_factory=list)
    document_type: str | None = None
    version_id: str | None = None


class PromptLearningFeedbackPayload(BaseModel):
    run_key: str | None = None
    prompt_name: str | None = None
    analysis_result: dict[str, Any] = Field(default_factory=dict)
    feedback_items: list[dict[str, Any]] = Field(default_factory=list)


class PromptVersionSavePayload(BaseModel):
    fragments: list[dict[str, Any]] = Field(default_factory=list)
    base_version_id: str | None = None
    changed_fragments: list[str] = Field(default_factory=list)
    change_summary: str = ''
    test_summary: dict[str, Any] = Field(default_factory=dict)
    created_by: str = 'web-user'
    status: str = 'candidate'


class PromptVersionRollbackPayload(BaseModel):
    version_id: str
    created_by: str = 'web-user'


class RulePatchStatusPayload(BaseModel):
    patch_id: int
    status: str


@router.get('/prompt-learning/ui-config')
def prompt_learning_ui_config(db: Session = Depends(get_db)) -> dict[str, Any]:
    config = build_prompt_optimizer_config(db)
    config['history'] = list_learning_history(db, limit=12)
    return config


@router.post('/prompt-learning/analyze')
def prompt_learning_analyze(payload: PromptLearningAnalyzePayload) -> dict[str, Any]:
    return run_prompt_test(
        payload.documents,
        payload.prompt_context,
        payload.prompt_flags,
        fragments=payload.fragments,
        selected_fragment_ids=payload.selected_fragment_ids,
        test_case_ids=payload.test_case_ids,
        document_type=payload.document_type,
        version_id=payload.version_id,
    )


@router.post('/prompt-learning/optimize')
def prompt_learning_optimize(payload: PromptLearningAnalyzePayload) -> dict[str, Any]:
    return optimize_prompt_fragments(
        payload.documents,
        fragments=payload.fragments,
        prompt_context=payload.prompt_context,
        prompt_flags=payload.prompt_flags,
        selected_fragment_ids=payload.selected_fragment_ids,
        test_case_ids=payload.test_case_ids,
        document_type=payload.document_type,
        version_id=payload.version_id,
    )


@router.post('/prompt-learning/save-version')
def prompt_learning_save_version(payload: PromptVersionSavePayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    return save_prompt_center_version(
        db,
        fragments=payload.fragments,
        base_version_id=payload.base_version_id,
        changed_fragments=payload.changed_fragments,
        change_summary=payload.change_summary,
        test_summary=payload.test_summary,
        created_by=payload.created_by,
        status=payload.status,
    )


@router.post('/prompt-learning/rollback')
def prompt_learning_rollback(payload: PromptVersionRollbackPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return rollback_prompt_center_version(db, payload.version_id, payload.created_by)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post('/prompt-learning/feedback')
def prompt_learning_feedback(payload: PromptLearningFeedbackPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    saved = save_learning_feedback(
        db,
        run_key=payload.run_key,
        prompt_name=payload.prompt_name,
        analysis_result=payload.analysis_result,
        feedback_items=payload.feedback_items,
    )
    return {
        'saved': saved,
        'history': list_learning_history(db, limit=12),
    }


@router.get('/prompt-learning/history')
def prompt_learning_history(limit: int = 20, db: Session = Depends(get_db)) -> dict[str, Any]:
    return list_learning_history(db, limit=limit)


@router.post('/prompt-learning/rule-patches/status')
def prompt_learning_rule_patch_status(payload: RulePatchStatusPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        result = transition_rule_patch_status(db, payload.patch_id, payload.status)
        db.commit()
        config = build_prompt_optimizer_config(db)
        config['history'] = list_learning_history(db, limit=12)
        return {
            'updated': result,
            'evolution': config['evolution'],
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
