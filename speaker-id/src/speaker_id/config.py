from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Similarity threshold
    similarity_threshold: float = 0.75

    # Device
    device: str = "cuda"

    class Config:
        env_file = ".env"


settings = Settings()
