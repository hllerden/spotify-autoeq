"""Default stdlib HTTP fetcher."""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Mapping

from .ports import ProviderError

_MAX_BYTES = 2_000_000


def urllib_fetcher(url: str, headers: Mapping[str, str], timeout_s: float) -> str:
    if not url.startswith("https://"):
        raise ProviderError("only https URLs are allowed")
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            return response.read(_MAX_BYTES).decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ProviderError(f"{url.split('?', 1)[0]}: {exc}") from exc
