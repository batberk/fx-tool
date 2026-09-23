import os
from dataclasses import dataclass

DEFAULT_UPSTREAM_BASE = "https://api.frankfurter.dev"


@dataclass(frozen=True)
class Settings:
    upstream_base: str = DEFAULT_UPSTREAM_BASE
    upstream_timeout_seconds: float = 5.0
    latest_cache_ttl_seconds: float = 15 * 60

    @classmethod
    def from_env(cls) -> "Settings":
        base = os.environ.get("FX_UPSTREAM_BASE") or DEFAULT_UPSTREAM_BASE
        return cls(upstream_base=base.rstrip("/"))
