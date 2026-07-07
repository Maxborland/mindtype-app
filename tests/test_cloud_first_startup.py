import builtins
import importlib
import sys


def _purge_app_and_onnx_modules():
    for name in list(sys.modules):
        if name == "onnxruntime" or name.startswith("onnxruntime."):
            sys.modules.pop(name, None)
        if name in {
            "app.main",
            "app.accelerator",
            "app.transcriber",
            "app.transcriber_cpp",
            "app.transcriber_onnx",
        }:
            sys.modules.pop(name, None)


def test_app_main_import_does_not_require_onnxruntime(monkeypatch):
    _purge_app_and_onnx_modules()
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "onnxruntime" or name.startswith("onnxruntime."):
            raise ImportError("onnxruntime import blocked for cloud-first startup")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    importlib.import_module("app.main")


def test_openrouter_transcriber_creation_does_not_require_onnxruntime(monkeypatch):
    _purge_app_and_onnx_modules()
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "onnxruntime" or name.startswith("onnxruntime."):
            raise ImportError("onnxruntime import blocked for cloud-first startup")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    transcriber_mod = importlib.import_module("app.transcriber")
    transcriber = transcriber_mod.create_transcriber("openrouter")

    assert transcriber.__class__.__name__ == "OpenRouterTranscriber"


def test_entrypoint_import_does_not_preload_gpu_dll_directories(monkeypatch):
    sys.modules.pop("main", None)
    added = []

    def fake_add_dll_directory(path):
        added.append(path)

    monkeypatch.setattr("os.add_dll_directory", fake_add_dll_directory, raising=False)

    importlib.import_module("main")

    assert added == []