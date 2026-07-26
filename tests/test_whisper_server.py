from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest


class FakeResponse:
    def __init__(self, status: int = 200, payload: bytes = b"ok") -> None:
        self.status = status
        self._payload = payload

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            return self._payload
        return self._payload[:amount]


class FakeConnection:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests: list[tuple[str, str]] = []
        self.headers: dict[str, str] = {}
        self.sent: list[bytes] = []
        self.closed = False

    def request(self, method: str, path: str) -> None:
        self.requests.append((method, path))

    def putrequest(self, method: str, path: str) -> None:
        self.requests.append((method, path))

    def putheader(self, name: str, value: str) -> None:
        self.headers[name] = value

    def endheaders(self) -> None:
        pass

    def send(self, data: bytes) -> None:
        self.sent.append(bytes(data))

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if timeout == 0.01 and self.returncode is None:
            raise subprocess.TimeoutExpired(cmd="whisper-server", timeout=timeout)
        self.returncode = 0
        return 0


def _config(tmp_path: Path, *, threads: int = 4):
    from app.whisper_server import WhisperServerConfig

    server = tmp_path / "whisper-server.exe"
    model = tmp_path / "ggml-small.bin"
    server.write_bytes(b"server")
    model.write_bytes(b"model")
    return WhisperServerConfig(
        server_path=server,
        model_path=model,
        threads=threads,
        use_gpu=True,
    )


def test_runtime_reuses_process_and_restarts_when_configuration_changes(
    tmp_path: Path,
) -> None:
    from app.whisper_server import WhisperServerRuntime

    processes: list[FakeProcess] = []
    commands: list[list[str]] = []
    connections: list[FakeConnection] = []

    def popen(command: list[str], **_: Any) -> FakeProcess:
        commands.append(command)
        process = FakeProcess()
        processes.append(process)
        return process

    def connect(*_: Any, **__: Any) -> FakeConnection:
        connection = FakeConnection(FakeResponse())
        connections.append(connection)
        return connection

    runtime = WhisperServerRuntime(
        popen_factory=popen,
        connection_factory=connect,
        port_factory=lambda: 43123,
        token_factory=lambda: "secret-route",
        sleep=lambda _: None,
        startup_timeout=0.1,
        log_path=tmp_path / "server.log",
    )

    runtime.ensure_started(_config(tmp_path))
    runtime.ensure_started(_config(tmp_path))

    assert len(processes) == 1
    assert "--host" in commands[0]
    assert commands[0][commands[0].index("--host") + 1] == "127.0.0.1"
    assert commands[0][commands[0].index("--request-path") + 1] == "/secret-route"
    assert connections[0].requests == [("GET", "/secret-route/")]

    runtime.ensure_started(_config(tmp_path, threads=6))

    assert len(processes) == 2
    assert processes[0].terminate_calls == 1
    assert commands[1][commands[1].index("-t") + 1] == "6"


def test_startup_reports_native_process_exit_and_releases_it(tmp_path: Path) -> None:
    from app.whisper_server import WhisperServerRuntime

    process = FakeProcess()
    process.returncode = 7
    runtime = WhisperServerRuntime(
        popen_factory=lambda *_args, **_kwargs: process,
        connection_factory=lambda *_args, **_kwargs: FakeConnection(FakeResponse()),
        port_factory=lambda: 43123,
        token_factory=lambda: "secret-route",
        sleep=lambda _: None,
        startup_timeout=0.1,
        log_path=tmp_path / "server.log",
    )

    with pytest.raises(RuntimeError, match="exit code 7"):
        runtime.ensure_started(_config(tmp_path))

    assert not runtime.running


def test_inference_streams_multipart_audio_in_bounded_chunks(tmp_path: Path) -> None:
    from app.whisper_server import WhisperServerRuntime

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"a" * (2 * 1024 * 1024 + 17))
    response_payload = json.dumps(
        {
            "text": "привет",
            "language": "ru",
            "segments": [{"start": 0.0, "end": 1.0, "text": "привет"}],
        }
    ).encode("utf-8")
    connections = [
        FakeConnection(FakeResponse()),
        FakeConnection(FakeResponse(payload=response_payload)),
    ]

    runtime = WhisperServerRuntime(
        popen_factory=lambda *_args, **_kwargs: FakeProcess(),
        connection_factory=lambda *_args, **_kwargs: connections.pop(0),
        port_factory=lambda: 43123,
        token_factory=lambda: "secret-route",
        sleep=lambda _: None,
        startup_timeout=0.1,
        upload_chunk_size=256 * 1024,
        log_path=tmp_path / "server.log",
    )

    result = runtime.infer(
        _config(tmp_path),
        audio,
        language="ru",
        beam_size=5,
        word_timestamps=True,
    )
    inference = runtime.last_connection
    assert inference is not None

    assert result["text"] == "привет"
    assert inference.requests == [("POST", "/secret-route/inference")]
    assert int(inference.headers["Content-Length"]) == sum(
        len(part) for part in inference.sent
    )
    file_chunks = [part for part in inference.sent if len(part) >= 256 * 1024]
    assert file_chunks
    assert max(map(len, file_chunks)) <= 256 * 1024


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        json.dumps({"text": 42, "segments": []}).encode(),
        json.dumps({"text": "ok", "segments": "wrong"}).encode(),
        json.dumps(
            {"text": "ok", "segments": [{"start": 2.0, "end": 1.0, "text": "x"}]}
        ).encode(),
    ],
)
def test_inference_rejects_malformed_verbose_json(
    tmp_path: Path, payload: bytes
) -> None:
    from app.whisper_server import WhisperServerRuntime

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    connections = [
        FakeConnection(FakeResponse()),
        FakeConnection(FakeResponse(payload=payload)),
    ]
    runtime = WhisperServerRuntime(
        popen_factory=lambda *_args, **_kwargs: FakeProcess(),
        connection_factory=lambda *_args, **_kwargs: connections.pop(0),
        port_factory=lambda: 43123,
        token_factory=lambda: "secret-route",
        sleep=lambda _: None,
        startup_timeout=0.1,
        log_path=tmp_path / "server.log",
    )

    with pytest.raises(RuntimeError, match="whisper-server"):
        runtime.infer(_config(tmp_path), audio)


def test_cancel_closes_active_connection_then_stops_server(tmp_path: Path) -> None:
    from app.whisper_server import WhisperServerRuntime

    process = FakeProcess()
    process.wait = lambda timeout=None: (_ for _ in ()).throw(  # type: ignore[method-assign]
        subprocess.TimeoutExpired(cmd="whisper-server", timeout=timeout)
    )
    active = FakeConnection(FakeResponse())
    runtime = WhisperServerRuntime(
        popen_factory=lambda *_args, **_kwargs: process,
        connection_factory=lambda *_args, **_kwargs: FakeConnection(FakeResponse()),
        port_factory=lambda: 43123,
        token_factory=lambda: "secret-route",
        sleep=lambda _: None,
        startup_timeout=0.1,
        log_path=tmp_path / "server.log",
    )
    runtime.ensure_started(_config(tmp_path))
    runtime._active_connection = active

    runtime.cancel(grace_timeout=0.01)

    assert active.closed
    assert process.terminate_calls == 1
    assert process.kill_calls == 1


def test_concurrent_inference_is_rejected(tmp_path: Path) -> None:
    from app.whisper_server import WhisperServerRuntime

    runtime = WhisperServerRuntime(
        popen_factory=lambda *_args, **_kwargs: FakeProcess(),
        connection_factory=lambda *_args, **_kwargs: FakeConnection(FakeResponse()),
        port_factory=lambda: 43123,
        token_factory=lambda: "secret-route",
        sleep=lambda _: None,
        startup_timeout=0.1,
        log_path=tmp_path / "server.log",
    )
    runtime._request_lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="уже выполняется"):
            runtime.infer(_config(tmp_path), tmp_path / "unused.wav")
    finally:
        runtime._request_lock.release()
