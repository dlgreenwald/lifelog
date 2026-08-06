from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Wyoming Whisper
    wyoming_host: str = "localhost"
    wyoming_port: int = 10700

    # Diarization Service (HTTPS)
    diarization_url: str = "https://localhost:8443"
    diarization_cert: str = "certs/ca.crt"

    # Speaker ID Service (HTTPS)
    speaker_id_url: str = "https://localhost:8443"
    speaker_id_cert: str = "certs/ca.crt"

    # LLM — OpenAI-compatible endpoint (Ollama, llama.cpp, vLLM, etc.)
    openai_base_url: str = "http://localhost:11434/v1"
    openai_api_key: str = "ollama"  # Ollama ignores this; llama.cpp may need "none"
    openai_model: str = "llama3"

    # OIDC Configuration
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""

    # PostgreSQL Database
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "lifelog"
    postgres_user: str = "lifelog"
    postgres_password: str = ""

    # Audio storage
    audio_storage_path: str = "/data/audio"

    class Config:
        env_file = ".env"


settings = Settings()
