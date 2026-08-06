from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # pyannote HuggingFace token
    hf_token: str = ""

    # Model name
    model_name: str = "pyannote/speaker-diarization-3.1"

    # Device
    device: str = "cuda"

    class Config:
        env_file = ".env"


settings = Settings()
