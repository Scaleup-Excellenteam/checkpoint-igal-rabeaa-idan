import base64
import unittest
from unittest.mock import AsyncMock, patch

from Server.reputation import (
    ReputationCheckError,
    URLReputation,
    _url_identifier,
    check_url_reputation,
)
from Server.server import url_security_reason


class FakeResponse:
    def __init__(self, status: int, body: object) -> None:
        self.status = status
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self, *, content_type=None):
        return self.body


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.request_url = None
        self.request_headers = None

    def get(self, url: str, *, headers: dict[str, str]):
        self.request_url = url
        self.request_headers = headers
        return self.response


class ReputationTests(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_uses_unpadded_base64_and_reads_malicious_count(self) -> None:
        url = "https://example.com/path"
        session = FakeSession(
            FakeResponse(
                200,
                {
                    "data": {
                        "attributes": {"last_analysis_stats": {"malicious": 2}}
                    }
                },
            )
        )

        result = await check_url_reputation(session, url, "secret")

        expected_id = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
        self.assertEqual(_url_identifier(url), expected_id)
        self.assertTrue(session.request_url.endswith(f"/urls/{expected_id}"))
        self.assertEqual(session.request_headers, {"x-apikey": "secret"})
        self.assertEqual(result.malicious_vendors, 2)

    async def test_non_success_response_has_no_safe_verdict(self) -> None:
        session = FakeSession(FakeResponse(429, {}))
        with self.assertRaises(ReputationCheckError):
            await check_url_reputation(session, "https://example.com", "secret")

    @patch("Server.server.VT_API_KEY", "secret")
    @patch("Server.server.check_urls", new_callable=AsyncMock)
    async def test_malicious_url_returns_blocking_reason(self, check_urls_mock) -> None:
        check_urls_mock.return_value = (
            URLReputation("https://malicious.example", malicious_vendors=4),
        )

        reason = await url_security_reason("visit https://malicious.example now")

        self.assertEqual(reason, "URL flagged by 4 vendors")

    @patch("Server.server.VT_API_KEY", "secret")
    @patch("Server.server.check_urls", new_callable=AsyncMock)
    async def test_safe_url_is_allowed(self, check_urls_mock) -> None:
        check_urls_mock.return_value = (
            URLReputation("https://safe.example", malicious_vendors=0),
        )

        self.assertIsNone(await url_security_reason("https://safe.example"))


if __name__ == "__main__":
    unittest.main()
