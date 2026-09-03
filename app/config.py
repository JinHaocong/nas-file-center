from __future__ import annotations

from functools import lru_cache
import ipaddress
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

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
    initial_admin_username: str | None = Field(default=None, validation_alias="INITIAL_ADMIN_USERNAME")
    initial_admin_password: str | None = Field(default=None, validation_alias="INITIAL_ADMIN_PASSWORD")
    session_cookie_name: str = Field(default="nfc_session", validation_alias="SESSION_COOKIE_NAME")
    session_max_age_seconds: int = Field(default=86400 * 7, validation_alias="SESSION_MAX_AGE_SECONDS")
    session_cookie_secure: bool = Field(default=False, validation_alias="SESSION_COOKIE_SECURE")
    trusted_proxies_raw: str = Field(
        default="127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
        validation_alias="TRUSTED_PROXIES",
    )

    @property
    def allowed_roots(self) -> list[Path]:
        roots = []
        for value in self.allowed_roots_raw.split(","):
            value = value.strip()
            if value:
                roots.append(Path(value).expanduser().resolve(strict=False))
        return roots

    @property
    def trusted_proxy_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        networks = []
        for raw in self.trusted_proxies_raw.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                if "/" in raw:
                    networks.append(ipaddress.ip_network(raw, strict=False))
                else:
                    ip = ipaddress.ip_address(raw)
                    networks.append(ipaddress.ip_network(f"{ip}/{32 if ip.version == 4 else 128}"))
            except ValueError:
                continue
        return networks

    def is_trusted_proxy(self, ip_str: str | None) -> bool:
        if not ip_str:
            return False
        try:
            ip = ipaddress.ip_address(ip_str.strip())
            return any(ip in net for net in self.trusted_proxy_networks)
        except ValueError:
            return False

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
