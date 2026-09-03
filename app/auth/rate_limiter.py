from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import threading


class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, lockout_seconds: int = 900):
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self._lock = threading.Lock()
        # key -> list of failure timestamps
        self._failures: dict[str, list[float]] = defaultdict(list)
        # key -> lockout until timestamp
        self._lockouts: dict[str, float] = {}

    def _get_keys(self, username: str | None, ip_address: str | None) -> list[str]:
        keys = []
        clean_user = (username or "").strip().lower()
        clean_ip = (ip_address or "").strip()
        if clean_user and clean_ip:
            keys.append(f"user_ip:{clean_user}:{clean_ip}")
        if clean_ip:
            keys.append(f"ip:{clean_ip}")
        return keys

    def is_rate_limited(self, username: str | None, ip_address: str | None) -> bool:
        now = datetime.now(timezone.utc).timestamp()
        with self._lock:
            # Check user_ip or ip specific lockout
            keys = self._get_keys(username, ip_address)
            for key in keys:
                lockout_until = self._lockouts.get(key, 0)
                if now < lockout_until:
                    return True
                # Clean up expired failures
                cutoff = now - self.lockout_seconds
                self._failures[key] = [t for t in self._failures[key] if t > cutoff]
                if len(self._failures[key]) >= self.max_attempts:
                    self._lockouts[key] = now + self.lockout_seconds
                    return True
            return False

    def record_failure(self, username: str | None, ip_address: str | None):
        now = datetime.now(timezone.utc).timestamp()
        with self._lock:
            keys = self._get_keys(username, ip_address)
            for key in keys:
                cutoff = now - self.lockout_seconds
                self._failures[key] = [t for t in self._failures[key] if t > cutoff]
                self._failures[key].append(now)
                if len(self._failures[key]) >= self.max_attempts:
                    self._lockouts[key] = now + self.lockout_seconds

    def record_success(self, username: str | None, ip_address: str | None):
        with self._lock:
            keys = self._get_keys(username, ip_address)
            for key in keys:
                self._failures.pop(key, None)
                self._lockouts.pop(key, None)
