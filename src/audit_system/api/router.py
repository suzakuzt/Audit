from fastapi import APIRouter

from audit_system.api.routes.audit_logs import router as audit_logs_router
from audit_system.api.routes.canonical_debug import router as canonical_debug_router
from audit_system.api.routes.document_compare import router as document_compare_router
from audit_system.api.routes.prompt_learning import router as prompt_learning_router


api_router = APIRouter()
api_router.include_router(audit_logs_router, prefix="/audit-logs", tags=["audit-logs"])
api_router.include_router(document_compare_router, tags=["document-foundation"])
api_router.include_router(canonical_debug_router, tags=["document-structuring-debug"])
api_router.include_router(prompt_learning_router, tags=["prompt-learning"])

