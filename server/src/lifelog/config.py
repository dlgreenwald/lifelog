from pydantic_settings import BaseSettings


class Settings(BaseSettings):
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
    postgres_ssl: str = "prefer"

    # Logging
    log_level: str = "INFO"

    # CORS
    cors_origins: str = "http://localhost:3000"

    # Rate limiting
    rate_limit_default: str = "100/minute"
    rate_limit_upload: str = "10/minute"

    # Audio storage
    audio_storage_path: str = "/data/audio"

    # Session grouping
    session_gap_minutes: int = 5
    meaningful_speech_min_seconds: float = 30.0
    garbled_segment_ratio: float = 0.4
    hourly_reprocess_interval_minutes: int = 1

    # Async transcription worker compatibility and polling
    encryption_secret: str = ""
    verify_audio_writes: bool = False
    reprocess_chunk_minutes: int = 10
    transcription_worker_poll_interval: int = 5

    class Config:
        env_file = ".env"


settings = Settings()
