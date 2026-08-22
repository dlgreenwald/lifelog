
from pydantic import BaseModel, Field, field_validator


class UserCreate(BaseModel):
    api_key: str | None = None
    oidc_sub: str | None = None
    name: str | None = None


class UserResponse(BaseModel):
    id: int
    api_key: str | None = None
    oidc_sub: str | None = None
    name: str | None = None


class RecordingResponse(BaseModel):
    id: int
    timestamp: str
    summary: str | None = None
    speakers: list | None = None
    todos: list | None = None
    calendar: list | None = None
    notes: list | None = None
    conversation_changes: list | None = None


class SpeakerLabel(BaseModel):
    recording_id: int
    speaker_id: str = Field(..., max_length=50)
    label: str = Field(..., min_length=1, max_length=100)


class CreateTodo(BaseModel):
    task: str = Field(..., min_length=1, max_length=500)
    owner: str = Field(default="Me", max_length=100)
    due: str | None = Field(default=None, max_length=10)
    priority: str = Field(default="medium")
    recording_id: int | None = None

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v):
        if v not in ("high", "medium", "low"):
            raise ValueError("priority must be high, medium, or low")
        return v


class CreateDecision(BaseModel):
    decision: str = Field(..., min_length=1, max_length=1000)
    made_by: str = Field(default="Me", max_length=100)
    context: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=2000)
    recording_id: int | None = None


class UploadResponse(BaseModel):
    status: str
    recording_id: int
