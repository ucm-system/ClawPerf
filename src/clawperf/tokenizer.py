"""Tokenizer management — reuses EvalScope's utilities directly.

Key reused components:
  - modelscope.AutoTokenizer / transformers.AutoTokenizer for loading
    (local directories are loaded strictly offline — see TokenizerManager)
  - evalscope.perf.plugin.datasets.utils.tokenize_chat_messages()
  - evalscope.perf.plugin.datasets.utils.gen_prompt_decode_to_target_len()
  - OpenaiPlugin._count_input_tokens() / _count_output_tokens()
"""

from __future__ import annotations

import logging
import os
import random
import re

logger = logging.getLogger("clawperf")


class TokenizerManager:
    """Manages tokenizer loading, token counting, and content generation.

    Delegates to EvalScope's utilities wherever possible.

    Loading strategy (this matters in air-gapped / NPU boxes):

    * **local directory** (``--tokenizer /mnt/model/Qwen3-0.6B``) — loaded
      strictly offline with ``local_files_only=True``, transformers first,
      ModelScope as fallback. No hub lookup, no network, no hang.
    * **local tokenizer.json** — loaded directly via ``PreTrainedTokenizerFast``.
    * **model id** (``Qwen/Qwen3-0.6B``) — ModelScope first (typical in CN
      environments), then the HuggingFace hub.
    * **missing path** — fails immediately with the resolved path and the
      directory listing instead of a hub traceback.

    ``CLAWPERF_TOKENIZER_BACKEND=transformers|modelscope`` forces one backend.
    """

    def __init__(self, tokenizer_path: str):
        self.tokenizer_path = tokenizer_path
        self._tokenizer = None
        self.source = ""          # e.g. "local dir (transformers)"
        self.load_errors: list = []

    @property
    def tokenizer(self):
        if self._tokenizer is None:
            self.load()
        return self._tokenizer

    # ── Loading ──

    @staticmethod
    def _is_local_path(path: str) -> bool:
        """True when *path* is written like a filesystem path, not a hub id.

        ``/mnt/model/x``, ``./tok``, ``~/tok``, ``D:\\tok`` → path;
        ``Qwen/Qwen3-0.6B`` (owner/name) → hub id.
        """
        p = path.strip()
        if p.startswith(("/", "./", "../", "~", ".\\", "..\\")):
            return True
        return bool(re.match(r"^[A-Za-z]:[\\/]", p))

    @staticmethod
    def _quiet_transformers() -> None:
        """Silence transformers' import-time advisories.

        ClawPerf only ever uses the tokenizer, so "PyTorch was not found. Models
        won't be available…" is pure noise — and it lands in the middle of the
        run banner, which is confusing on a first run.
        """
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        logging.getLogger("transformers").setLevel(logging.ERROR)

    @staticmethod
    def _load_transformers(path: str, local_only: bool):
        from transformers import AutoTokenizer
        return AutoTokenizer.from_pretrained(
            path, trust_remote_code=True, local_files_only=local_only
        )

    @staticmethod
    def _load_modelscope(path: str, local_only: bool):
        from modelscope import AutoTokenizer
        try:
            return AutoTokenizer.from_pretrained(
                path, trust_remote_code=True, local_files_only=local_only
            )
        except TypeError:
            # Older ModelScope releases don't take local_files_only.
            return AutoTokenizer.from_pretrained(path, trust_remote_code=True)

    def _try_backends(self, path: str, local_only: bool, order) -> bool:
        """Try each backend in *order*; keep the first tokenizer that loads."""
        for name in order:
            loader = self._load_transformers if name == "transformers" else self._load_modelscope
            try:
                self._tokenizer = loader(path, local_only)
            except ImportError as e:
                self.load_errors.append(f"{name}: not installed ({e})")
            except Exception as e:
                self.load_errors.append(f"{name}: {type(e).__name__}: {e}")
            else:
                return True
        return False

    def load(self):
        """Load the tokenizer (idempotent). Raises RuntimeError with an
        actionable message when nothing could be loaded."""
        if self._tokenizer is not None:
            return self._tokenizer

        self._quiet_transformers()
        path = (self.tokenizer_path or "").strip()
        if not path:
            raise RuntimeError(
                "No tokenizer configured: pass --tokenizer <local-dir|model-id> "
                "(or --model, which is used as the default)."
            )

        forced = (os.environ.get("CLAWPERF_TOKENIZER_BACKEND") or "").strip().lower()
        self.load_errors = []

        if os.path.isfile(path) and path.endswith(".json"):
            # A bare tokenizer.json — load it directly, no hub, no config.
            try:
                from transformers import PreTrainedTokenizerFast
                self._tokenizer = PreTrainedTokenizerFast(tokenizer_file=path)
                self.source = "local tokenizer.json"
                logger.info("Loaded tokenizer file: %s", path)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to load tokenizer file '{path}': {type(e).__name__}: {e}"
                ) from e
        elif os.path.isdir(path):
            order = ["transformers", "modelscope"]
            if forced in ("transformers", "modelscope"):
                order = [forced]
            if not self._try_backends(path, True, order):
                # Some model dirs ship a bare tokenizer.json without the config
                # files AutoTokenizer needs — load the file directly.
                tj = os.path.join(path, "tokenizer.json")
                if os.path.isfile(tj):
                    try:
                        from transformers import PreTrainedTokenizerFast
                        self._tokenizer = PreTrainedTokenizerFast(tokenizer_file=tj)
                        self.source = "local tokenizer.json"
                    except Exception as e:
                        self.load_errors.append(f"tokenizer.json: {type(e).__name__}: {e}")
            if self._tokenizer is None:
                raise RuntimeError(self._local_error(path))
            if not self.source:
                self.source = f"local dir ({order[0] if not forced else forced})"
            logger.info(
                "Loaded local tokenizer from %s [%s] — vocab=%s, chat_template=%s",
                path, self.source, self._safe_vocab_size(),
                "yes" if self._tokenizer.chat_template else "no",
            )
        else:
            if self._is_local_path(path):
                raise RuntimeError(self._missing_path_error(path))
            order = ["modelscope", "transformers"]
            if forced in ("transformers", "modelscope"):
                order = [forced]
            if not self._try_backends(path, False, order):
                raise RuntimeError(
                    f"Failed to load tokenizer '{path}' from the model hub.\n"
                    + self._format_errors()
                    + "\n  Fix: pass --tokenizer <local-dir> (e.g. the model "
                      "directory on this machine) or pre-download the tokenizer."
                )
            self.source = f"hub ({order[0]})"
            logger.info("Loaded tokenizer '%s' from %s", path, self.source)

        if getattr(self._tokenizer, "pad_token", None) is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token
        return self._tokenizer

    def _safe_vocab_size(self) -> str:
        try:
            return str(len(self._tokenizer))
        except Exception:
            return "?"

    def _format_errors(self) -> str:
        if not self.load_errors:
            return "  (no backend reported a detailed error)"
        return "\n".join(f"  - {e}" for e in self.load_errors)

    def _local_error(self, path: str) -> str:
        try:
            files = sorted(os.listdir(path))
        except OSError as e:
            files = [f"<unreadable: {e}>"]
        looks_like_tokenizer = any(
            f in files for f in (
                "tokenizer.json", "tokenizer_config.json", "vocab.json",
                "vocab.txt", "tokenizer.model", "spiece.model", "merges.txt",
            )
        )
        extra = "" if looks_like_tokenizer else (
            "\n  The directory holds no tokenizer files "
            "(tokenizer.json / tokenizer_config.json / vocab.json / "
            "tokenizer.model). Point --tokenizer at the model directory that "
            "contains them."
        )
        return (
            f"Failed to load a local tokenizer from '{path}'.\n"
            + self._format_errors()
            + f"\n  Files present: {', '.join(files[:20]) or '(empty directory)'}"
            + extra
            + "\n  Fix: check the path, or install the backend you want "
              "(pip install transformers / modelscope)."
        )

    def _missing_path_error(self, path: str) -> str:
        parent = os.path.dirname(path) or "/"
        try:
            siblings = sorted(os.listdir(parent))[:20]
        except OSError:
            siblings = []
        listing = f"\n  '{parent}' contains: {', '.join(siblings)}" if siblings else ""
        return (
            f"Tokenizer path '{path}' does not exist on this machine.{listing}\n"
            "  Fix: pass --tokenizer with a path that exists (mount the model "
            "directory into the container, or use a model id such as "
            "Qwen/Qwen3-0.6B to load from the hub)."
        )

    # ── Token counting (reuses EvalScope) ──

    def count_tokens(self, text: str) -> int:
        """Count tokens in a plain text string."""
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def _tokenize_chat(self, messages: list[dict], add_generation_prompt: bool = True) -> list:
        """Tokenize chat messages via EvalScope's helper (single import path)."""
        from evalscope.perf.plugin.datasets.utils import tokenize_chat_messages
        return tokenize_chat_messages(
            self.tokenizer, messages, add_generation_prompt=add_generation_prompt
        )

    def count_chat_tokens(self, messages: list[dict]) -> int:
        """Count tokens for chat-formatted messages.

        Uses EvalScope's utility if tokenizer has chat_template,
        otherwise falls back to simple concatenation.
        """
        # Check if tokenizer has chat_template
        if self.tokenizer.chat_template is not None:
            return len(self._tokenize_chat(messages, add_generation_prompt=True))

        # Fallback: simple role/content format
        total_text = ""
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            total_text += f"<|{role}|>\n{content}\n"
        total_text += "<|assistant|>\n"  # Add generation prompt
        return self.count_tokens(total_text)

    def count_input_tokens_from_request(self, request_json_str: str) -> int:
        """Count input tokens from a serialized request JSON — same as OpenaiPlugin._count_input_tokens."""
        import json
        request = json.loads(request_json_str)
        if 'messages' in request:
            # Match count_chat_tokens: include the generation prompt tokens.
            return len(self._tokenize_chat(request['messages'], add_generation_prompt=True))
        elif 'prompt' in request:
            prompt = request['prompt']
            if isinstance(prompt, list):
                return len(prompt)
            return len(self.tokenizer.encode(prompt, add_special_tokens=False))
        return 0

    def count_output_tokens(self, text: str) -> int:
        """Count output tokens — same as OpenaiPlugin._count_output_tokens."""
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    # ── Content generation (reuses EvalScope) ──

    def generate_random_content(self, target_tokens: int) -> str:
        """Generate random content of exactly target_tokens length.

        Uses EvalScope's gen_prompt_decode_to_target_len when available.
        """
        if target_tokens <= 0:
            return ""

        vocab = self.tokenizer.get_vocab()
        special_ids = set()
        if hasattr(self.tokenizer, "all_special_ids"):
            special_ids = set(self.tokenizer.all_special_ids)
        valid_ids = [tid for tid in vocab.values() if tid not in special_ids]
        if not valid_ids:
            valid_ids = list(vocab.values())

        token_ids = [random.choice(valid_ids) for _ in range(target_tokens)]

        # Use EvalScope's utility for exact length matching
        try:
            from evalscope.perf.plugin.datasets.utils import gen_prompt_decode_to_target_len
            text, _, _ = gen_prompt_decode_to_target_len(
                self.tokenizer, token_ids, target_tokens
            )
            return text
        except ImportError:
            pass

        # Fallback: decode then adjust
        text = self.tokenizer.decode(token_ids, skip_special_tokens=True)
        return self._adjust_to_target_length(text, target_tokens)

    def generate_content_from_file(self, file_path: str, target_tokens: int) -> str:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Content file not found: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return self._adjust_to_target_length(content, target_tokens)

    def _adjust_to_target_length(self, text: str, target_tokens: int) -> str:
        current_count = self.count_tokens(text)
        for _ in range(20):
            if current_count == target_tokens:
                break
            if current_count > target_tokens:
                ids = self.tokenizer.encode(text, add_special_tokens=False)
                text = self.tokenizer.decode(ids[:target_tokens], skip_special_tokens=True)
            else:
                vocab = self.tokenizer.get_vocab()
                special_ids = set(getattr(self.tokenizer, "all_special_ids", []))
                valid_ids = [tid for tid in vocab.values() if tid not in special_ids]
                if not valid_ids:
                    break
                extra = [random.choice(valid_ids) for _ in range(target_tokens - current_count)]
                existing = self.tokenizer.encode(text, add_special_tokens=False)
                text = self.tokenizer.decode(existing + extra, skip_special_tokens=True)
            current_count = self.count_tokens(text)
        return text
