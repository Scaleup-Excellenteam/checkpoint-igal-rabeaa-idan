"""Asynchronous VirusTotal URL reputation lookups."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from typing import Any

import aiohttp

VT_URL_API = "https://www.virustotal.com/api/v3/urls"
VT_TIMEOUT_SECONDS = 10


class ReputationCheckError(RuntimeError):
    """Raised when a URL cannot be given a trustworthy verdict."""


@dataclass(frozen=True)
class URLReputation:
    url: str
    malicious_vendors: int


def _url_identifier(url: str) -> str:
    """Return VirusTotal's URL-safe, unpadded base64 URL identifier."""
    return base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")


async def check_url_reputation(
    session: aiohttp.ClientSession, url: str, api_key: str
) -> URLReputation:
    """Fetch the latest VirusTotal analysis and return its malicious count."""
    endpoint = f"{VT_URL_API}/{_url_identifier(url)}"
    try:
        async with session.get(endpoint, headers={"x-apikey": api_key}) as response:
            if response.status != 200:
                raise ReputationCheckError(f"VirusTotal returned HTTP {response.status}")
            body: Any = await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise ReputationCheckError("VirusTotal request failed") from exc

    try:
        malicious = body["data"]["attributes"]["last_analysis_stats"]["malicious"]
    except (KeyError, TypeError) as exc:
        raise ReputationCheckError("VirusTotal response omitted analysis statistics") from exc

    if not isinstance(malicious, int) or isinstance(malicious, bool) or malicious < 0:
        raise ReputationCheckError("VirusTotal returned invalid analysis statistics")
    return URLReputation(url=url, malicious_vendors=malicious)


async def check_urls(urls: tuple[str, ...], api_key: str) -> tuple[URLReputation, ...]:
    """Check all URLs concurrently while sharing one bounded HTTP session."""
    timeout = aiohttp.ClientTimeout(total=VT_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        return tuple(
            await asyncio.gather(
                *(check_url_reputation(session, url, api_key) for url in urls)
            )
        )
