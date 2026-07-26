# Persistent whisper-server contract

## User outcome

Local transcription on Windows must not reload the Whisper model for every
dictation or file. A single loopback-only `whisper-server` process owns the
model and is reused by sequential operations.

## Acceptance criteria

- The server binds to `127.0.0.1` on an ephemeral port and uses a random,
  unguessable request path.
- Startup waits for an HTTP readiness response and reports an early process
  exit with useful local log context.
- The same live process is reused while model path, thread count and GPU mode
  are unchanged.
- Changing runtime configuration performs a controlled restart.
- Only one inference request may be active.
- Multipart audio upload is streamed in bounded chunks; the whole audio file is
  not loaded into memory.
- Cancellation closes the active HTTP connection, then terminates the native
  server and kills it after a two-second grace period.
- A cancelled or failed request is never repeated automatically.
- `verbose_json` responses are validated before they reach the existing
  transcriber facade.
- `transcribe_stream()` exposes only the final result. It does not present
  already-recorded file processing as live streaming.
- Windows GPU terminology matches the bundled Vulkan runtime.
- Application shutdown releases the persistent native process.

## Deliberate exclusions

- No model is downloaded only to exercise this change.
- No quality or latency claim is made without a verified GGML model benchmark.
- The existing unverified Silero ONNX speech-presence gate is not represented
  as segmentation and is not passed to whisper-server as a VAD model.
- Local diarization is a separate, reviewable change.
