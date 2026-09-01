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


class UtteranceSpan(BaseModel):
    """Per-utterance range in combined-stream seconds.

    The worker emits one entry per utterance in a quick (and full) job
    so the server-side apply loop can map combined segments back to the
    right utterance without relying on wall-clock timestamp drift.
    """

    utterance_id: int
    start: float
    end: float


class JobResult(BaseModel):
    """Body of ``/internal/transcription/complete/{job_id}``.

    The transcription worker POSTs WhisperX segments plus speaker data;
    quick jobs also POST ``utterance_spans`` so the server can route
    each segment back to the right utterance precisely.
    """

    segments: list[dict] = Field(default_factory=list)
    full_transcript: dict | None = None
    speaker_map: dict = Field(default_factory=dict)
    speaker_segments: list[dict] = Field(default_factory=list)
    utterance_spans: list[UtteranceSpan] = Field(default_factory=list)
    utterance_ids: list[int] = Field(default_factory=list)


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


class UserSettings(BaseModel):
    language: str = "auto"
    llm_context: str = ""


class UserSettingsResponse(BaseModel):
    language: str
    llm_context: str
