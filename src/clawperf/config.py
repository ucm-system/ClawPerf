"""Configuration for ClawPerfBench.

Wraps EvalScope's Arguments where possible, extends with
ClawPerfBench-specific context/compaction/scheduling parameters.

Supports layered configuration: CLI args > environment variables (CLAWPERF_*)
> YAML config file (--config) > dataclass defaults.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Optional


@dataclasses.dataclass
class BenchmarkConfig:
    """All configurable parameters for a benchmark run."""

    # ── Mode ──
    # "scenario" = multi-turn long-context workload (default).
    # "hitrate"  = controlled prefix-cache hit-rate test (prefill + measure).
    # "slo"      = SLO-driven max-concurrency sweep (find max users meeting TTFT/TPOT).
    # "agent"    = real agent-at-work perf (model runs coding tasks via tool calls).
    # "record"   = recording proxy: capture a real agent session as JSONL.
    # "replay"   = replay a recorded session against an endpoint.
    mode: str = "scenario"

    # ── Context profile / suite (convenience layer over raw token counts) ──
    # When set, overrides system_prefix_tokens / user_prefix_tokens /
    # input_tokens_per_turn from a named profile (fresh/short/medium/long/full/xl/xxl).
    context_profile: str = ""  # e.g. "medium", "long"
    # When set, expands to a list of (users, profile) scenarios run in sequence.
    suite: str = ""  # e.g. "quick", "standard", "full"
    model_context_length: int = 0  # 0 = no limit; skip profiles exceeding the window

    # ── Hit-rate mode configuration (ignored in other modes) ──
    num_requests: int = 100        # total measure-phase requests
    input_len: int = 1024          # total prompt length (prefix + boundary + suffix)
    output_len: int = 128          # generation length per request
    prefix_len: int = 0            # shared-prefix length (0 = derive from hit_rate)
    hit_rate: Optional[float] = None  # target fraction that's shared (0..1); derives prefix_len
    prefix_num: int = 1            # number of DISTINCT prefixes (requests-per-prefix = N//prefix_num)
    prefill: bool = True           # inject prefixes into cache before measuring
    concurrency: int = 1           # in-flight requests during measure phase
    seed: int = 0                  # reproducibility seed for prompt construction

    # ── SLO mode configuration (only with --mode slo) ──
    slo_ttft_ms: Optional[float] = None
    slo_tpot_ms: Optional[float] = None
    slo_percentile: float = 0.99
    slo_error_rate: Optional[float] = None
    slo_min_users: int = 1
    slo_max_users: int = 100
    slo_step_strategy: str = "geometric"
    slo_step_turns: int = 5
    slo_step_warmup_turns: int = 1
    slo_step_timeout_s: int = 300
    slo_step_reset_cache: bool = True

    # ── Agent mode configuration (only with --mode agent) ──
    agent_tasks: int = 4
    agent_task_file: Optional[str] = None
    agent_max_steps: int = 12
    agent_max_tokens: int = 512
    agent_shell_timeout: int = 30
    agent_workdir: str = ""

    # ── Record mode configuration (only with --mode record) ──
    upstream_endpoint: str = ""  # the real LLM endpoint to forward to
    proxy_port: int = 9090
    recording: str = "session.jsonl"  # JSONL output path
    upstream_api: str = "auto"  # "openai", "anthropic", "auto"

    # ── Replay mode configuration (only with --mode replay) ──
    # 'recording' is shared with record mode (the JSONL path).
    history_mode: str = "live"  # "live" (recommended) or "verbatim"

    # ── Trace mode configuration (only with --mode trace) ──
    # Loads a kvcache.ai-format JSONL trace (hash_ids + input_length) and
    # simulates a block-level prefix cache locally. Optionally replays real
    # requests if the trace carries 'messages' fields.
    trace_file: str = ""           # JSONL trace path
    cache_budget_tokens: int = 0   # 0 = unlimited; budget in tokens
    cache_budget_gb: float = 0.0   # alternative: budget in GB (overrides tokens)
    eviction_policy: str = "lru"   # "lru" or "fifo"
    trace_block_size: int = 64     # default block size (tokens per block)
    budget_sweep: bool = False     # run budget sweep across multiple levels
    kv_bytes_per_token: float = 2.0  # bytes per KV cache token (for GB→token conversion)
    trace_users: int = 1       # session-aware concurrency for real trace replay

    # ── User configuration ──
    num_users: int = 1
    user_arrival: str = "burst"

    # ── Context configuration ──
    system_prefix_tokens: int = 15000
    system_prefix_source: str = "random"
    user_prefix_tokens: int = 5000
    input_tokens_per_turn: int = 5000
    output_tokens_per_turn: int = 1000
    max_context_tokens: int = 128000
    compaction_prefix_increment: int = 5000

    # ── Run configuration ──
    max_turns: int = 100

    # ── Early abort configuration ──
    max_consecutive_failures: int = 0  # 0 = disabled; abort after N consecutive failures

    # ── API configuration ──
    endpoint: str = ""
    model: str = ""
    api_key: str = ""
    tokenizer: str = ""
    ignore_eos: bool = True
    request_timeout: int = 600

    # ── System metrics configuration ──
    metrics_endpoint: Optional[str] = None
    metrics_interval: int = 5
    metrics_samples: bool = False
    reset_cache: bool = False
    backend: str = "vllm"

    # ── Output configuration ──
    output: str = ""
    history: str = "clawperf_history.jsonl"
    verbose: bool = False

    # ── Derived fields ──
    arrival_mode: str = ""
    arrival_param: float = 0.0

    def __post_init__(self):
        if not self.tokenizer:
            self.tokenizer = self.model
        if not self.output:
            from datetime import datetime
            self.output = f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        self._parse_arrival_mode()
        self._apply_profile()

    def _apply_profile(self):
        """If context_profile is set, override the raw token fields."""
        if not self.context_profile:
            return
        from clawperf.context_profiles import get_profile
        profile = get_profile(self.context_profile)
        self.system_prefix_tokens = profile["system_prefix_tokens"]
        self.user_prefix_tokens = profile["user_prefix_tokens"]
        self.input_tokens_per_turn = profile["input_tokens_per_turn"]

    def _parse_arrival_mode(self):
        if self.user_arrival == "burst":
            self.arrival_mode = "burst"
            self.arrival_param = 0.0
            return

        if ":" not in self.user_arrival:
            raise ValueError(
                f"Invalid user_arrival format: {self.user_arrival!r}. "
                "Expected 'burst', 'steady:<seconds>', or 'poisson:<lambda>'."
            )

        prefix, _, raw_param = self.user_arrival.partition(":")
        try:
            param = float(raw_param)
        except (ValueError, TypeError):
            raise ValueError(
                f"Invalid user_arrival format: {self.user_arrival!r}. "
                "Expected 'burst', 'steady:<seconds>', or 'poisson:<lambda>' "
                f"with a numeric value after the colon (got {raw_param!r})."
            )

        if prefix == "steady":
            if param < 0:
                raise ValueError(f"steady arrival interval must be >= 0, got {param}.")
            self.arrival_mode = "steady"
            self.arrival_param = param
        elif prefix == "poisson":
            if param <= 0:
                raise ValueError(f"poisson arrival lambda must be > 0, got {param}.")
            self.arrival_mode = "poisson"
            self.arrival_param = param
        else:
            raise ValueError(
                f"Invalid user_arrival format: {self.user_arrival!r}. "
                "Expected 'burst', 'steady:<seconds>', or 'poisson:<lambda>'."
            )

    def to_evalscope_args(self):
        """Build an EvalScope Arguments object from this config."""
        from evalscope.perf.arguments import Arguments

        args = Arguments(
            model=self.model,
            url=self.endpoint,
            tokenizer_path=self.tokenizer,
            stream=True,
            max_tokens=self.output_tokens_per_turn,
            number=[self.num_users],
            parallel=[self.num_users],
            total_timeout=self.request_timeout,
            api="openai",
            no_test_connection=True,
            apply_chat_template=False,
        )
        if self.api_key:
            args.headers["Authorization"] = f"Bearer {self.api_key}"

        if self.ignore_eos:
            extra = dict(args.extra_args) if args.extra_args else {}
            extra["ignore_eos"] = True
            args.extra_args = extra

        return args

    def to_dict(self) -> dict:
        """Serialize the *public* config (excludes derived internal fields)."""
        d = dataclasses.asdict(self)
        d.pop("arrival_mode", None)
        d.pop("arrival_param", None)
        return d

    def validate(self) -> list[str]:
        """Return a list of human-readable configuration problems (empty if OK)."""
        problems: list[str] = []
        base = (
            self.system_prefix_tokens
            + self.user_prefix_tokens
            + self.input_tokens_per_turn
        )
        if base >= self.max_context_tokens:
            problems.append(
                f"Base context ({self.system_prefix_tokens} system + "
                f"{self.user_prefix_tokens} user-prefix + "
                f"{self.input_tokens_per_turn} input = {base} tokens) already "
                f">= max_context_tokens ({self.max_context_tokens}). Every turn "
                "will overflow — reduce prefix/input sizes or raise "
                "--max-context-tokens."
            )
        if self.compaction_prefix_increment <= 0:
            problems.append("compaction_prefix_increment must be > 0.")
        if self.num_users < 1:
            problems.append("num_users must be >= 1.")
        if self.max_turns < 1:
            problems.append("max_turns must be >= 1.")
        if self.max_consecutive_failures < 0:
            problems.append("max_consecutive_failures must be >= 0.")

        valid_modes = ("scenario", "hitrate", "slo", "agent", "record", "replay", "trace")
        if self.mode not in valid_modes:
            problems.append(f"unknown mode {self.mode!r} (expected one of {valid_modes}).")

        if self.mode == "hitrate":
            from clawperf.hitrate import BOUNDARY_TOKENS
            if self.num_requests < 1:
                problems.append("hitrate: num_requests must be >= 1.")
            if self.input_len < 1:
                problems.append("hitrate: input_len must be >= 1.")
            if self.output_len < 1:
                problems.append("hitrate: output_len must be >= 1.")
            if self.prefix_num < 1:
                problems.append("hitrate: prefix_num must be >= 1.")
            if self.prefix_num > self.num_requests:
                problems.append(
                    f"hitrate: prefix_num ({self.prefix_num}) must be <= "
                    f"num_requests ({self.num_requests})."
                )
            if self.hit_rate is not None and not (0.0 < self.hit_rate < 1.0):
                problems.append("hitrate: hit_rate must be in (0, 1).")
            plen = self.prefix_len
            if plen == 0 and self.hit_rate is not None:
                plen = int(self.input_len * self.hit_rate)
            if plen > 0 and self.input_len - plen - BOUNDARY_TOKENS < 1:
                problems.append(
                    f"hitrate: input_len ({self.input_len}) too small for "
                    f"prefix_len ({plen}) + boundary ({BOUNDARY_TOKENS})."
                )
        if self.mode == "slo":
            if self.slo_ttft_ms is None and self.slo_tpot_ms is None:
                problems.append("slo: specify at least one of --slo-ttft-ms / --slo-tpot-ms.")
            if self.slo_max_users < self.slo_min_users:
                problems.append("slo: slo_max_users must be >= slo_min_users.")
            if self.slo_step_turns < 1:
                problems.append("slo: slo_step_turns must be >= 1.")
            if not (0.0 < self.slo_percentile < 1.0):
                problems.append("slo: slo_percentile must be in (0, 1).")
        if self.mode == "agent":
            if self.agent_tasks < 1:
                problems.append("agent: agent_tasks must be >= 1.")
            if self.agent_max_steps < 1:
                problems.append("agent: agent_max_steps must be >= 1.")
        if self.mode == "record":
            if not self.upstream_endpoint:
                problems.append("record: --upstream-endpoint is required.")
        if self.mode == "replay":
            if not self.recording:
                problems.append("replay: --recording (JSONL path) is required.")
            if self.history_mode not in ("live", "verbatim"):
                problems.append(f"replay: history_mode must be 'live' or 'verbatim', got {self.history_mode!r}.")
        if self.mode == "trace":
            if not self.trace_file:
                problems.append("trace: --trace-file (JSONL path) is required.")
            if self.eviction_policy not in ("lru", "fifo"):
                problems.append(f"trace: eviction_policy must be 'lru' or 'fifo', got {self.eviction_policy!r}.")
            if self.trace_block_size < 1:
                problems.append("trace: trace_block_size must be >= 1.")
            if self.cache_budget_gb < 0:
                problems.append("trace: cache_budget_gb must be >= 0.")
        return problems


# ── Environment variable + YAML support ──────────────────────────────────────

def _env_prefix() -> str:
    return "CLAWPERF_"


def load_env_config() -> dict:
    """Load configuration from environment variables (CLAWPERF_*).

    Variable names map to config fields by uppercasing and replacing hyphens
    with underscores. Example: CLAWPERF_ENDPOINT → endpoint,
    CLAWPERF_MAX_TURNS → max_turns.

    Values are coerced to the field's declared type (int/float/bool, unwrapping
    Optional), so ``CLAWPERF_SLO_TTFT_MS=200`` enters as 200.0, not "200".
    """
    prefix = _env_prefix()
    field_names = {f.name for f in dataclasses.fields(BenchmarkConfig)}
    try:
        from typing import get_type_hints
        hints = get_type_hints(BenchmarkConfig)
    except Exception:  # pragma: no cover — fallback to raw annotations
        hints = {f.name: f.type for f in dataclasses.fields(BenchmarkConfig)}

    def _coerce(field_name: str, raw: str):
        ftype = hints.get(field_name, str)
        # Unwrap Optional[T] → T (env vars are always present).
        args = getattr(ftype, "__args__", None)
        if args and type(None) in args:
            ftype = next(a for a in args if a is not type(None))
        if ftype is int:
            try:
                return int(raw)
            except ValueError:
                return None
        if ftype is float:
            try:
                return float(raw)
            except ValueError:
                return None
        if ftype is bool:
            return raw.lower() in ("true", "1", "yes", "on")
        return raw

    config = {}
    for key, val in os.environ.items():
        if not key.startswith(prefix):
            continue
        field_name = key[len(prefix):].lower()
        if field_name not in field_names:
            # Try with hyphens → underscores.
            field_name = field_name.replace("-", "_")
            if field_name not in field_names:
                continue
        coerced = _coerce(field_name, val)
        if coerced is None:
            continue  # failed numeric parse — ignore the var
        config[field_name] = coerced
    return config


def load_yaml_config(path: str) -> dict:
    """Load configuration from a YAML file.

    Keys are normalized to dataclass field names: hyphens are converted to
    underscores (``max-turns`` → ``max_turns``, matching the CLI's long-option
    spelling). Unknown keys are reported via ``logging`` instead of silently
    dropped.
    """
    import logging
    import yaml

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"YAML config must be a mapping at the top level, got {type(data)}")

    field_names = {f.name for f in dataclasses.fields(BenchmarkConfig)}
    normalized: dict = {}
    for k, v in data.items():
        key = str(k).replace("-", "_")
        if key not in field_names:
            logging.getLogger("clawperf").warning(
                "Ignoring unknown config key %r in %s (known fields: %d)",
                k, path, len(field_names),
            )
            continue
        normalized[key] = v
    return normalized


def build_config(cli_args: dict, yaml_path: str = "") -> BenchmarkConfig:
    """Build a BenchmarkConfig with layered precedence:

    CLI args (explicitly passed) > environment variables > YAML > defaults.
    """
    env = load_env_config()
    merged = {**env}
    if yaml_path:
        merged.update(load_yaml_config(yaml_path))

    # CLI args override (only non-None values).
    for k, v in cli_args.items():
        if v is not None:
            merged[k] = v

    # Filter to known fields.
    field_names = {f.name for f in dataclasses.fields(BenchmarkConfig)}
    filtered = {k: v for k, v in merged.items() if k in field_names}

    return BenchmarkConfig(**filtered)
