from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Whisper ASR (transcription + diarization)
    whisper_asr_url: str = "http://localhost:9000"

    # Speaker ID Service
    speaker_id_url: str = "http://localhost:8443"

    # LLM — OpenAI-compatible endpoint (Ollama, llama.cpp, vLLM, etc.)
    openai_base_url: str = "http://localhost:11434/v1"
    openai_api_key: str = "ollama"  # Ollama ignores this; llama.cpp may need "none"
    openai_model: str = "llama3"

    # OIDC Configuration
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_redirect_uri: str = ""

    # PostgreSQL Database
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "lifelog"
    postgres_user: str = "lifelog"
    postgres_password: str = ""

    # Logging
    log_level: str = "INFO"

    # Audio storage
    audio_storage_path: str = "/data/audio"

    # Session grouping
    session_gap_minutes: int = 5
    meaningful_speech_min_seconds: float = 30.0
    garbled_segment_ratio: float = 0.4
    hourly_reprocess_interval_minutes: int = 1

    # Live transcription sliding window
    live_transcribe_window_seconds: int = 300  # 5-minute window
    live_transcribe_overlap_seconds: int = 60  # 1-minute overlap

    class Config:
        env_file = ".env"


settings = Settings()
