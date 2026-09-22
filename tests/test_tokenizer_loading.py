"""Tokenizer loading — local/offline behaviour, backend order, error messages.

The bug these lock down: a local ``--tokenizer /mnt/model/...`` used to go
through ModelScope first (network-ish, confusing "Loaded tokenizer from
ModelScope" log line) and a missing path produced an opaque hub traceback.
"""

from __future__ import annotations

import os
import sys

import pytest

from clawperf.tokenizer import TokenizerManager


class _FakeTokenizer:
    """Minimal stand-in for a HF/ModelScope tokenizer."""

    chat_template = "{{ messages }}"
    eos_token = "</s>"
    pad_token = None

    def __len__(self):
        return 42


def _stub_backends(monkeypatch, calls, fail=()):
    """Replace both loaders with recorders; ``fail`` names backends that raise."""
    def make(name):
        def loader(path, local_only):
            calls.append((name, path, local_only))
            if name in fail:
                raise RuntimeError(f"{name} boom")
            return _FakeTokenizer()
        return staticmethod(loader)

    monkeypatch.setattr(TokenizerManager, "_load_transformers", make("transformers"))
    monkeypatch.setattr(TokenizerManager, "_load_modelscope", make("modelscope"))


# ── Path classification ───────────────────────────────────────────────────────

@pytest.mark.parametrize("path,expected", [
    ("/mnt/model/Qwen3.5-0.8B", True),
    ("./tok", True),
    ("../tok", True),
    ("~/tok", True),
    ("D:\\models\\tok", True),
    ("Qwen/Qwen3-0.6B", False),
    ("clawperf/qwen3-0.6b", False),
    ("gpt2", False),
])
def test_is_local_path(path, expected):
    assert TokenizerManager._is_local_path(path) is expected


# ── Local directory: offline, transformers first ──────────────────────────────

def test_local_dir_loads_offline_with_transformers_first(monkeypatch, tmp_path):
    calls = []
    _stub_backends(monkeypatch, calls)
    d = tmp_path / "model"
    d.mkdir()

    tm = TokenizerManager(str(d))
    tm.load()

    assert calls == [("transformers", str(d), True)]
    assert tm.source == "local dir (transformers)"
    assert tm.tokenizer.pad_token == "</s>"  # pad falls back to eos


def test_local_dir_falls_back_to_modelscope(monkeypatch, tmp_path):
    calls = []
    _stub_backends(monkeypatch, calls, fail=("transformers",))
    d = tmp_path / "model"
    d.mkdir()

    tm = TokenizerManager(str(d))
    tm.load()

    assert [c[0] for c in calls] == ["transformers", "modelscope"]
    assert all(c[2] is True for c in calls)  # never touches the network


def test_local_dir_reports_both_backends_and_files(monkeypatch, tmp_path):
    calls = []
    _stub_backends(monkeypatch, calls, fail=("transformers", "modelscope"))
    d = tmp_path / "model"
    d.mkdir()
    (d / "config.json").write_text("{}", encoding="utf-8")

    tm = TokenizerManager(str(d))
    with pytest.raises(RuntimeError) as ei:
        tm.load()

    msg = str(ei.value)
    assert "transformers: RuntimeError: transformers boom" in msg
    assert "modelscope: RuntimeError: modelscope boom" in msg
    assert "config.json" in msg
    assert "no tokenizer files" in msg  # actionable hint


def test_backend_env_override(monkeypatch, tmp_path):
    calls = []
    _stub_backends(monkeypatch, calls)
    d = tmp_path / "model"
    d.mkdir()
    monkeypatch.setenv("CLAWPERF_TOKENIZER_BACKEND", "modelscope")

    tm = TokenizerManager(str(d))
    tm.load()

    assert calls == [("modelscope", str(d), True)]
    assert tm.source == "local dir (modelscope)"


# ── Missing local path: fail fast, list the parent ────────────────────────────

def test_missing_local_path_is_a_clear_error(tmp_path):
    missing = str(tmp_path / "nope" / "Qwen3.5-0.8B")
    tm = TokenizerManager(missing)
    with pytest.raises(RuntimeError) as ei:
        tm.load()
    msg = str(ei.value)
    assert "does not exist" in msg
    assert "nope" in msg  # parent listing shown


def test_empty_tokenizer_path_raises():
    with pytest.raises(RuntimeError, match="No tokenizer configured"):
        TokenizerManager("").load()


# ── Hub id: modelscope first, then HF ─────────────────────────────────────────

def test_hub_id_prefers_modelscope(monkeypatch):
    calls = []
    _stub_backends(monkeypatch, calls, fail=("modelscope",))

    tm = TokenizerManager("Qwen/Qwen3-0.6B")
    tm.load()

    assert calls == [
        ("modelscope", "Qwen/Qwen3-0.6B", False),
        ("transformers", "Qwen/Qwen3-0.6B", False),
    ]
    assert tm.source == "hub (modelscope)"


def test_hub_id_failure_mentions_local_dir(monkeypatch):
    calls = []
    _stub_backends(monkeypatch, calls, fail=("transformers", "modelscope"))

    tm = TokenizerManager("some/unknown-model")
    with pytest.raises(RuntimeError) as ei:
        tm.load()
    assert "pass --tokenizer <local-dir>" in str(ei.value)


# ── Real local tokenizer directory (uses the repo fixture when present) ───────

_REPO_TOK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tokenizers", "qwen3-0.6b"
)


@pytest.mark.skipif(not os.path.isdir(_REPO_TOK), reason="bundled tokenizer fixture missing")
def test_real_local_tokenizer_loads_offline():
    tm = TokenizerManager(_REPO_TOK)
    tm.load()
    assert tm.source.startswith("local dir")
    n = tm.count_tokens("hello world")
    assert n >= 2
    assert tm.count_chat_tokens([{"role": "user", "content": "hi"}]) > n


@pytest.mark.skipif(
    sys.version_info < (3, 10), reason="tokenizers library needs py3.10+"
)
def test_real_tokenizer_from_generated_dir(tmp_path):
    """A directory that only holds a tokenizer.json must still load."""
    pytest.importorskip("tokenizers")
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    from tokenizers import Tokenizer

    tok = Tokenizer(WordLevel({"hello": 0, "world": 1, "[UNK]": 2}, unk_token="[UNK]"))
    tok.pre_tokenizer = Whitespace()
    tok.save(str(tmp_path / "tokenizer.json"))

    tm = TokenizerManager(str(tmp_path))
    tm.load()
    assert tm.count_tokens("hello world") == 2
