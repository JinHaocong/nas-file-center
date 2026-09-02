from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    config_dir: Path = Field(default=Path("/config"), validation_alias="CONFIG_DIR")
    data_mount: Path = Field(default=Path("/data"), validation_alias="DATA_MOUNT")
    allowed_roots_raw: str = Field(default="/data", validation_alias="ALLOWED_ROOTS")
    allow_delete: bool = Field(default=False, validation_alias="ALLOW_DELETE")
    allow_mutation: bool = Field(default=False, validation_alias="ALLOW_MUTATION")
    quarantine_root: Path = Field(default=Path("/data/.nas-file-center-trash"), validation_alias="QUARANTINE_ROOT")
    protect_last_file: bool = Field(default=True, validation_alias="PROTECT_LAST_FILE")
    fclones_binary: str = Field(default="fclones", validation_alias="FCLONES_BINARY")
    fclones_threads: str | None = Field(default=None, validation_alias="FCLONES_THREADS")
    verification_hash: str = Field(default="sha256", validation_alias="VERIFICATION_HASH")
    mtime_refresh_delay_seconds: float = Field(default=2.0, validation_alias="MTIME_REFRESH_DELAY_SECONDS")

    @property
    def allowed_roots(self) -> list[Path]:
        roots = []
        for value in self.allowed_roots_raw.split(","):
            value = value.strip()
            if value:
                roots.append(Path(value).expanduser().resolve(strict=False))
        return roots

    @property
    def database_path(self) -> Path:
        return self.config_dir / "app.db"

    @property
    def reports_dir(self) -> Path:
        return self.config_dir / "reports"

    @property
    def backups_dir(self) -> Path:
        return self.config_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.config_dir / "logs"

    @property
    def fclones_home(self) -> Path:
        return self.config_dir / "home"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
