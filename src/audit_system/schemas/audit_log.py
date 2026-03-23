from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AuditLogBase(BaseModel):
    actor: str = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=100)
    resource: str = Field(min_length=1, max_length=100)
    detail: str = Field(min_length=1)

    @field_validator("actor", "action", "resource", "detail", mode="before")
    @classmethod
    def strip_and_validate_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("must not be blank")
            return stripped
        return value


class AuditLogCreate(AuditLogBase):
    pass


class AuditLogRead(AuditLogBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
