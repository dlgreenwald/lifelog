
from pydantic import BaseModel


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
    speaker_id: str
    label: str


class UploadResponse(BaseModel):
    status: str
    recording_id: int
