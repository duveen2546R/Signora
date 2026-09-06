from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "SignSure"
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'signsure.db'}"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    clip_dir: Path = BASE_DIR / "data" / "clips"
    transition_dir: Path = BASE_DIR / "data" / "transitions"
    # Vite dev server; tighten for deployment.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    model_config = SettingsConfigDict(env_prefix="SIGNSURE_")


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.clip_dir.mkdir(parents=True, exist_ok=True)
settings.transition_dir.mkdir(parents=True, exist_ok=True)
