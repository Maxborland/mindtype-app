from __future__ import annotations

import io
import json
import urllib.error


class Response:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body


def test_cloud_llm_uses_only_short_lived_access_token(monkeypatch) -> None:
    from app.llm import mindtype_cloud

    requests = []

    def request(call, *, timeout):
        requests.append((call, timeout))
        return Response({"balance_microunits": "1250", "ledger": []})

    monkeypatch.setattr(mindtype_cloud, "urlopen_with_ssl", request)
    provider = mindtype_cloud.MindTypeCloudProvider(
        access_token=lambda: "short-lived-access",
        timeout=12,
    )

    info = provider.get_balance()

    assert info.credits == 1250
    assert requests[0][0].get_header("Authorization") == (
        "Bearer short-lived-access"
    )
    assert requests[0][1] == 12
    assert not hasattr(provider, "license_key")


def test_cloud_llm_refreshes_once_after_401(monkeypatch) -> None:
    from app.llm import mindtype_cloud

    current = ["expired-access"]
    attempts = []

    def refresh() -> None:
        current[0] = "fresh-access"

    def request(call, *, timeout):
        del timeout
        attempts.append(call.get_header("Authorization"))
        if len(attempts) == 1:
            raise urllib.error.HTTPError(
                call.full_url,
                401,
                "Unauthorized",
                {},
                io.BytesIO(
                    json.dumps(
                        {
                            "error": {
                                "code": "AUTH_REQUIRED",
                                "message": "expired",
                            }
                        }
                    ).encode("utf-8")
                ),
            )
        return Response({"balance_microunits": "500", "ledger": []})

    monkeypatch.setattr(mindtype_cloud, "urlopen_with_ssl", request)
    provider = mindtype_cloud.MindTypeCloudProvider(
        access_token=lambda: current[0],
        refresh_access_token=refresh,
    )

    assert provider.get_balance().credits == 500
    assert attempts == [
        "Bearer expired-access",
        "Bearer fresh-access",
    ]
