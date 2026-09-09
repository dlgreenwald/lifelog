import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Similarity threshold
    similarity_threshold: float = 0.75

    # HuggingFace token for gated model downloads (env var takes precedence)
    hf_token: str = os.environ.get("HF_TOKEN", "")

    # Device — must be "cuda:N" format for SpeechBrain
    device: str = "cuda:0"

    class Config:
        env_file = ".env"


settings = Settings()
