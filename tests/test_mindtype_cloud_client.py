from __future__ import annotations

import hashlib
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest


class ScriptedTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, *, headers, body, timeout):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout": timeout,
            }
        )
        response = self.responses.pop(0)
        return response(self.requests[-1]) if callable(response) else response


def response(status: int, payload=None, headers=None):
    from app.providers.mindtype_cloud import HTTPResponse

    body = (
        b""
        if payload is None
        else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )
    return HTTPResponse(status=status, headers=headers or {}, body=body)


def test_url_transport_wraps_success_response_read_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.providers.mindtype_cloud import TransportError, UrlLibTransport

    class StalledResponse:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size=-1):
            raise TimeoutError("response body stalled")

    monkeypatch.setattr(
        "urllib.request.build_opener",
        lambda *_handlers: SimpleNamespace(
            open=lambda *_args, **_kwargs: StalledResponse()
        ),
    )

    with pytest.raises(TransportError, match="response body stalled"):
        UrlLibTransport().request(
            "GET",
            "https://mindtype.space/v1/usage",
            headers={},
            body=None,
            timeout=1,
        )


def test_url_transport_wraps_error_response_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.providers.mindtype_cloud import TransportError, UrlLibTransport

    class StalledErrorBody:
        def read(self, _size=-1):
            raise OSError("error body stalled")

        def close(self):
            return None

    failure = urllib.error.HTTPError(
        "https://mindtype.space/v1/usage",
        503,
        "unavailable",
        {},
        StalledErrorBody(),
    )

    def raise_failure(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(
        "urllib.request.build_opener",
        lambda *_handlers: SimpleNamespace(open=raise_failure),
    )

    with pytest.raises(TransportError, match="error body stalled"):
        UrlLibTransport().request(
            "GET",
            "https://mindtype.space/v1/usage",
            headers={},
            body=None,
            timeout=1,
        )


def test_url_transport_rejects_oversized_response_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.providers.mindtype_cloud import (
        ResponseTooLargeError,
        UrlLibTransport,
    )

    class OversizedResponse:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size=-1):
            return b"12345"

    monkeypatch.setattr(
        "urllib.request.build_opener",
        lambda *_handlers: SimpleNamespace(
            open=lambda *_args, **_kwargs: OversizedResponse()
        ),
    )

    with pytest.raises(ResponseTooLargeError):
        UrlLibTransport(max_response_bytes=4).request(
            "GET",
            "https://mindtype.space/v1/usage",
            headers={},
            body=None,
            timeout=1,
        )


def test_url_transport_rejects_redirects_before_reusing_headers() -> None:
    from app.providers.mindtype_cloud import _RejectRedirects

    handler = _RejectRedirects()

    assert (
        handler.redirect_request(
            None,
            None,
            302,
            "Found",
            {},
            "https://attacker.example/collect",
        )
        is None
    )


def test_401_refreshes_once_and_preserves_idempotency_key() -> None:
    from app.providers.mindtype_cloud import MindTypeCloudClient

    transport = ScriptedTransport(
        [
            response(401, {"error": {"code": "AUTH_REQUIRED"}}),
            response(202, {"id": "job-1", "state": "queued"}),
        ]
    )
    tokens = iter(["expired", "fresh"])
    current = [next(tokens)]

    client = MindTypeCloudClient(
        "https://mindtype.space",
        access_token=lambda: current[0],
        refresh_access_token=lambda: current.__setitem__(0, next(tokens)),
        transport=transport,
        sleep=lambda _seconds: None,
    )
    job = client.create_transcription(
        upload_id="upload-1",
        operation_id="operation-1",
        options={"language": "ru"},
    )

    assert job["id"] == "job-1"
    assert len(transport.requests) == 2
    assert {
        request["headers"]["Idempotency-Key"]
        for request in transport.requests
    } == {"operation-1:transcription"}
    assert transport.requests[1]["headers"]["Authorization"] == "Bearer fresh"
    assert json.loads(transport.requests[1]["body"]) == {
        "operation_id": "operation-1",
        "upload_id": "upload-1",
        "options": {"language": "ru"},
    }


def test_missing_in_memory_access_token_refreshes_before_request() -> None:
    from app.providers.mindtype_cloud import MindTypeCloudClient

    transport = ScriptedTransport([response(200, {"usage": []})])
    current = [""]

    def refresh() -> None:
        current[0] = "fresh"

    client = MindTypeCloudClient(
        "https://mindtype.space",
        access_token=lambda: current[0],
        refresh_access_token=refresh,
        transport=transport,
    )

    client.get_usage()

    assert transport.requests[0]["headers"]["Authorization"] == "Bearer fresh"


def test_provider_error_preserves_retry_after_and_job_id() -> None:
    from app.providers.mindtype_cloud import (
        CloudAPIError,
        CloudErrorCode,
        MindTypeCloudClient,
    )

    transport = ScriptedTransport(
        [
            response(
                429,
                {
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "wait",
                        "retryable": True,
                        "retry_after_seconds": 17,
                        "job_id": "job-rate",
                    }
                },
            )
        ]
    )
    client = MindTypeCloudClient(
        "https://mindtype.space",
        access_token="token",
        transport=transport,
        retry_delays=(),
    )

    with pytest.raises(CloudAPIError) as raised:
        client.get_transcription("job-rate")

    assert raised.value.code is CloudErrorCode.RATE_LIMITED
    assert raised.value.retryable is True
    assert raised.value.retry_after_seconds == 17
    assert raised.value.job_id == "job-rate"


def test_resumable_upload_skips_existing_part_and_retries_identical_chunk(
    tmp_path: Path,
) -> None:
    from app.providers.mindtype_cloud import MindTypeCloudClient

    source = tmp_path / "audio.wav"
    source.write_bytes(b"abcdefghij")
    sleeps = []
    transport = ScriptedTransport(
        [
            response(
                201,
                {
                    "id": "upload-1",
                    "upload_token": "part-token",
                    "uploaded_parts": [1],
                },
            ),
            response(
                500,
                {
                    "error": {
                        "code": "PROVIDER_UNAVAILABLE",
                        "retryable": True,
                    }
                },
            ),
            response(200, {"part_number": 2}),
            response(200, {"state": "complete"}),
        ]
    )
    client = MindTypeCloudClient(
        "https://mindtype.space",
        access_token="access-token",
        transport=transport,
        chunk_size=5,
        retry_delays=(1,),
        sleep=sleeps.append,
        minimum_chunk_size=1,
    )
    hash_calls = []
    original_sha256 = client._sha256

    def counted_sha256(path):
        hash_calls.append(path)
        return original_sha256(path)

    client._sha256 = counted_sha256

    completed = client.upload_file(source, operation_id="operation-upload")

    puts = [
        request for request in transport.requests if request["method"] == "PUT"
    ]
    assert completed["state"] == "complete"
    assert len(puts) == 2
    assert puts[0]["body"] == puts[1]["body"] == b"fghij"
    assert puts[0]["headers"]["X-Part-SHA256"] == hashlib.sha256(
        b"fghij"
    ).hexdigest()
    assert puts[0]["headers"]["Authorization"] == "Bearer part-token"
    assert sleeps == [1]
    assert hash_calls == [source]


def test_existing_upload_is_recovered_without_duplicate_create(
    tmp_path: Path,
) -> None:
    from app.providers.mindtype_cloud import MindTypeCloudClient

    source = tmp_path / "private meeting name.wav"
    source.write_bytes(b"abcdefghij")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    transport = ScriptedTransport(
        [
            response(
                200,
                {
                    "id": "upload-existing",
                    "upload_token": "part-token",
                    "uploaded_parts": [1],
                    "size": 10,
                    "sha256": source_hash,
                    "part_size": 5,
                },
            ),
            response(200, {"part_number": 2}),
            response(200, {"state": "complete"}),
        ]
    )
    client = MindTypeCloudClient(
        "https://mindtype.space",
        access_token="access-token",
        transport=transport,
        chunk_size=5,
        minimum_chunk_size=1,
    )

    client.upload_file(
        source,
        operation_id="operation-upload",
        remote_upload_id="upload-existing",
    )

    assert [request["method"] for request in transport.requests] == [
        "GET",
        "PUT",
        "POST",
    ]
    assert transport.requests[0]["url"].endswith(
        "/v1/uploads/upload-existing"
    )


def test_upload_creation_does_not_send_local_filename(tmp_path: Path) -> None:
    from app.providers.mindtype_cloud import MindTypeCloudClient

    source = tmp_path / "секретное совещание.wav"
    source.write_bytes(b"audio")
    transport = ScriptedTransport(
        [
            response(
                201,
                {
                    "id": "upload-1",
                    "upload_token": "part-token",
                    "uploaded_parts": [],
                },
            )
        ]
    )
    client = MindTypeCloudClient(
        "https://mindtype.space",
        access_token="access-token",
        transport=transport,
    )

    client.create_upload(source, operation_id="operation-upload")

    body = transport.requests[0]["body"].decode("utf-8")
    assert source.name not in body
    assert str(source) not in body


def test_non_https_cloud_endpoint_is_rejected() -> None:
    from app.providers.mindtype_cloud import MindTypeCloudClient

    with pytest.raises(ValueError, match="HTTPS"):
        MindTypeCloudClient(
            "http://mindtype.space",
            access_token="token",
        )


def test_insufficient_credits_is_not_retried() -> None:
    from app.providers.mindtype_cloud import (
        CloudAPIError,
        CloudErrorCode,
        MindTypeCloudClient,
    )

    transport = ScriptedTransport(
        [
            response(
                402,
                {
                    "error": {
                        "code": "INSUFFICIENT_CREDITS",
                        "retryable": False,
                    }
                },
            )
        ]
    )
    client = MindTypeCloudClient(
        "https://mindtype.space",
        access_token="token",
        transport=transport,
        retry_delays=(0, 0),
    )

    with pytest.raises(CloudAPIError) as raised:
        client.create_transcription(
            upload_id="upload-1",
            operation_id="operation-1",
            options={},
        )

    assert raised.value.code is CloudErrorCode.INSUFFICIENT_CREDITS
    assert len(transport.requests) == 1


def test_existing_remote_job_is_polled_without_duplicate_post() -> None:
    from app.providers.mindtype_cloud import MindTypeCloudClient

    transport = ScriptedTransport(
        [response(200, {"id": "remote-existing", "state": "running"})]
    )
    client = MindTypeCloudClient(
        "https://mindtype.space",
        access_token="token",
        transport=transport,
    )

    job = client.recover_or_create_transcription(
        remote_job_id="remote-existing",
        upload_id="upload-unused",
        operation_id="operation-existing",
        options={},
    )

    assert job["state"] == "running"
    assert [request["method"] for request in transport.requests] == ["GET"]


def test_retry_after_is_bounded_before_retry() -> None:
    from app.providers.mindtype_cloud import MindTypeCloudClient

    waits = []
    transport = ScriptedTransport(
        [
            response(
                429,
                {
                    "error": {
                        "code": "RATE_LIMITED",
                        "retryable": True,
                        "retry_after_seconds": 3600,
                    }
                },
            ),
            response(200, {"jobs": []}),
        ]
    )
    client = MindTypeCloudClient(
        "https://mindtype.space",
        access_token="token",
        transport=transport,
        retry_delays=(1,),
        retry_wait=lambda delay: waits.append(delay) or False,
    )

    client.get_usage()

    assert waits == [30.0]
    assert len(transport.requests) == 2


def test_retry_wait_can_be_interrupted_without_second_request() -> None:
    from app.providers.mindtype_cloud import (
        CloudAPIError,
        MindTypeCloudClient,
    )

    transport = ScriptedTransport(
        [
            response(
                503,
                {"error": {"code": "PROVIDER_UNAVAILABLE", "retryable": True}},
            ),
        ]
    )
    client = MindTypeCloudClient(
        "https://mindtype.space",
        access_token="token",
        transport=transport,
        retry_delays=(1,),
        retry_wait=lambda _delay: True,
    )

    with pytest.raises(CloudAPIError, match="interrupted") as raised:
        client.get_usage()

    assert raised.value.retryable is True
    assert len(transport.requests) == 1


def test_transcription_result_requires_canonical_schema() -> None:
    from app.providers.mindtype_cloud import MindTypeCloudClient
    from app.result_schema import CanonicalResultError
    from tests.test_result_schema import canonical_result

    valid = canonical_result("operation-cloud")
    good = MindTypeCloudClient(
        "https://mindtype.space",
        access_token="token",
        transport=ScriptedTransport([response(200, valid)]),
    )
    assert good.get_transcription_result("job-1")["operation_id"] == (
        "operation-cloud"
    )

    invalid = dict(valid)
    invalid["schema_version"] = "2.0"
    bad = MindTypeCloudClient(
        "https://mindtype.space",
        access_token="token",
        transport=ScriptedTransport([response(200, invalid)]),
    )
    with pytest.raises(CanonicalResultError):
        bad.get_transcription_result("job-1")


def test_ack_and_cancel_are_explicit_existing_job_calls() -> None:
    from app.providers.mindtype_cloud import MindTypeCloudClient

    transport = ScriptedTransport(
        [
            response(204),
            response(202, {"id": "job-1", "state": "cancelling"}),
        ]
    )
    client = MindTypeCloudClient(
        "https://mindtype.space",
        access_token="token",
        transport=transport,
    )

    client.acknowledge_transcription("job-1")
    cancelled = client.cancel_transcription("job-1")

    assert cancelled["state"] == "cancelling"
    assert [
        (request["method"], request["url"].split("mindtype.space")[-1])
        for request in transport.requests
    ] == [
        ("POST", "/v1/transcriptions/job-1/ack"),
        ("DELETE", "/v1/transcriptions/job-1"),
    ]


def test_summary_uses_server_artifact_and_canonical_contract() -> None:
    from app.providers.mindtype_cloud import MindTypeCloudClient
    from tests.test_result_schema import canonical_result

    expected = canonical_result("operation-summary")
    transport = ScriptedTransport(
        [
            response(202, {"id": "summary-1", "state": "queued"}),
            response(200, {"result": expected}),
        ]
    )
    client = MindTypeCloudClient(
        "https://mindtype.space",
        access_token="token",
        transport=transport,
    )

    job = client.create_summary(
        operation_id="operation-summary",
        transcript_artifact_id="transcript-result-1",
        options={
            "preset": "pm",
            "input_token_estimate": 1200,
            "max_output_tokens": 800,
        },
    )
    result = client.get_summary_result(
        job["id"],
        expected_operation_id="operation-summary",
    )

    assert result["operation_id"] == "operation-summary"
    assert json.loads(transport.requests[0]["body"]) == {
        "operation_id": "operation-summary",
        "source_artifact_id": "transcript-result-1",
        "preset": "pm",
        "input_token_estimate": 1200,
        "max_output_tokens": 800,
    }
    assert transport.requests[0]["headers"]["Idempotency-Key"] == (
        "operation-summary:summary"
    )
