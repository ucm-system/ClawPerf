"""KV-cache prefix-cache hit-rate simulator with trace replay.

Loads request traces in the kvcache.ai JSONL format (``hash_ids``,
``input_length``, optional ``block_size``) and simulates a block-level
prefix cache under a configurable memory budget and eviction policy.

Two modes of operation:

1. **Local simulation** (no LLM endpoint needed): replays the trace through
   an in-memory prefix cache simulator, computing hit rate, ceiling, and
   ideal prefill speedup = 1 / (1 - r). Supports budget sweep to find the
   inflection point where marginal returns diminish.

2. **Real replay** (LLM endpoint needed): when the trace carries ``messages``
   fields, sends actual streaming requests to an endpoint while simultaneously
   tracking the cache behavior, producing both simulated and measured metrics.

The trace format is compatible with kvcache.ai's hit-rate simulator:

    {"block_size": 64, "hash_ids": [2001, 2002], "input_length": 128}
    {"block_size": 64, "hash_ids": [2003, 2004], "input_length": 128}

Optionally, a ``messages`` field can be included for real-request replay:

    {"hash_ids": [2001], "input_length": 64, "messages": [{"role": "user", "content": "..."}]}

Inspired by:
- kvcache.ai/tools/kv-cache-hit-rate-simulator
- kvcache.ai/blog/calculate-kvcache-cache-budge (budget sweep methodology)
- inferencex.semianalysis.com/agentx (agentic trace characterization)
"""

from __future__ import annotations

import gzip
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("clawperf")


# ── Trace data model ──────────────────────────────────────────────────────────

@dataclass
class TraceEntry:
    """One request in a trace."""
    index: int
    hash_ids: List[int]           # block-level prefix hash IDs
    input_length: int             # total input tokens
    block_size: int = 64          # tokens per block (overrides global)
    messages: Optional[List[Dict]] = None  # for real-request replay
    user_id: Optional[int] = None  # session/user id for session-aware concurrency


@dataclass
class TraceStats:
    """Summary statistics of a loaded trace."""
    request_count: int = 0
    total_input_tokens: int = 0
    unique_blocks: int = 0
    total_blocks: int = 0
    average_input_tokens: float = 0.0
    block_size: int = 64
    parse_errors: int = 0
    skipped_records: int = 0
    has_messages: bool = False


def _open_text(path: str | Path) -> Any:
    """Open a text file, supporting .gz compression and stdin."""
    import sys
    if str(path) == "-":
        return sys.stdin
    path = Path(path)
    if str(path).endswith(".gz"):
        # utf-8-sig: tolerate BOMs in traces produced by Windows tools.
        return gzip.open(path, "rt", encoding="utf-8-sig", errors="replace")
    return path.open("r", encoding="utf-8-sig", errors="replace")


class _Interner:
    """Map hash_id values (int or str) to dense internal integers."""

    def __init__(self) -> None:
        self._ids: Dict[str, int] = {}

    def intern(self, value: Any) -> int:
        if isinstance(value, bool):
            raise ValueError("hash_ids must be integers or strings, not booleans")
        if isinstance(value, int):
            key = str(value)
        elif isinstance(value, str):
            key = value
        else:
            raise ValueError("hash_ids must be integers or strings")
        existing = self._ids.get(key)
        if existing is not None:
            return existing
        assigned = len(self._ids)
        self._ids[key] = assigned
        return assigned

    def __len__(self) -> int:
        return len(self._ids)


def load_trace(path: str, block_size: int = 64,
               max_records: int = 0) -> Tuple[List[TraceEntry], TraceStats]:
    """Load a JSONL trace file in kvcache.ai format.

    Each line:
        {"hash_ids": [int, ...], "input_length": int, "block_size": int?, "messages": [...]?}

    Returns (entries, stats).
    """
    interner = _Interner()
    entries: List[TraceEntry] = []
    stats = TraceStats(block_size=block_size)
    fallback_bs = block_size

    with _open_text(path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                stats.parse_errors += 1
                continue

            raw_ids = obj.get("hash_ids")
            if not raw_ids or not isinstance(raw_ids, list):
                stats.parse_errors += 1
                continue

            input_length = obj.get("input_length", 0)
            if not isinstance(input_length, int) or input_length <= 0:
                stats.parse_errors += 1
                continue

            entry_bs = obj.get("block_size", fallback_bs)
            if not isinstance(entry_bs, int) or entry_bs <= 0:
                entry_bs = fallback_bs

            # Intern hash_ids to dense integers.
            interned = [interner.intern(hid) for hid in raw_ids]

            messages = obj.get("messages")

            # Session/user id for session-aware concurrency ("user_id",
            # "session_id", or "concurrent_id" — kvcache.ai's simulator
            # supports concurrent users the same way).
            raw_uid = obj.get("user_id", obj.get("session_id", obj.get("concurrent_id")))
            user_id = None
            if raw_uid is not None:
                try:
                    user_id = int(raw_uid)
                except (ValueError, TypeError):
                    user_id = hash(str(raw_uid)) & 0x7FFFFFFF

            entries.append(TraceEntry(
                index=stats.request_count,
                hash_ids=interned,
                input_length=input_length,
                block_size=entry_bs,
                messages=messages,
                user_id=user_id,
            ))
            stats.request_count += 1
            stats.total_input_tokens += input_length
            stats.total_blocks += len(interned)
            if messages:
                stats.has_messages = True

            if max_records > 0 and stats.request_count >= max_records:
                break

    stats.unique_blocks = len(interner)
    stats.average_input_tokens = (stats.total_input_tokens / stats.request_count
                                   if stats.request_count else 0.0)
    if stats.parse_errors:
        logger.warning("Trace parse: %d errors, %d valid records",
                       stats.parse_errors, stats.request_count)
    return entries, stats


# ── Prefix cache simulator ────────────────────────────────────────────────────

@dataclass
class CacheResult:
    """Result of simulating one trace through the cache."""
    hit_tokens: int = 0
    miss_tokens: int = 0
    total_tokens: int = 0
    hit_rate: float = 0.0
    ceiling: float = 0.0       # max possible hit rate (unlimited budget)
    speedup: float = 1.0       # 1 / (1 - hit_rate)
    evictions: int = 0
    cache_blocks: int = 0      # final block count
    cache_tokens: int = 0      # final token count (blocks × avg block_size)
    budget_tokens: int = 0     # configured budget
    policy: str = "lru"


class PrefixCacheSim:
    """Block-level prefix cache simulator with LRU or FIFO eviction.

    Models a prefix cache (like vLLM's radix tree) at the block granularity.
    Each cached block is identified by its hash_id and stores ``block_size``
    tokens. The cache has a token budget; when exceeded, blocks are evicted
    according to the policy.

    - **LRU**: evicts the least-recently-accessed block with ref_count == 0.
      Accessing a block (hit) updates its position. This approximates vLLM's
      radix-tree leaf-node eviction.
    - **FIFO**: evicts the oldest-inserted block with ref_count == 0.
    """

    def __init__(self, budget_tokens: int, policy: str = "lru", block_size: int = 64):
        self.budget_tokens = budget_tokens
        self.policy = policy.lower()
        self.block_size = block_size
        # Cached blocks: hash_id → (token_count, ref_count)
        self._cache: Dict[int, Tuple[int, int]] = {}
        # LRU/FIFO ordering: deque of hash_ids (most-recent at right for LRU).
        self._order: deque = deque()
        self._hit_tokens = 0
        self._miss_tokens = 0
        self._evictions = 0

    @property
    def cache_tokens(self) -> int:
        return sum(tc for tc, _ in self._cache.values())

    @property
    def cache_blocks(self) -> int:
        return len(self._cache)

    def _touch(self, hid: int):
        """Move hid to the most-recently-used position."""
        try:
            self._order.remove(hid)
        except ValueError:
            pass
        self._order.append(hid)

    def _evict_one(self):
        """Evict one block according to the policy."""
        # Find the first evictable block (ref_count == 0).
        for _ in range(len(self._order)):
            if self.policy == "fifo":
                candidate = self._order[0]  # oldest
            else:
                candidate = self._order[0]  # least recently used (leftmost)
            # Check ref_count.
            entry = self._cache.get(candidate)
            if entry is None:
                self._order.popleft()
                continue
            tc, rc = entry
            if rc > 0:
                # Can't evict — move to end and try next.
                self._order.rotate(-1)
                continue
            # Evict it.
            del self._cache[candidate]
            self._order.popleft()
            self._evictions += 1
            return
        # All blocks have ref_count > 0 — can't evict (shouldn't happen normally).
        logger.warning("Cannot evict: all %d blocks have ref_count > 0", len(self._cache))

    def _ensure_budget(self):
        """Evict blocks until cache fits within the budget."""
        while self.cache_tokens > self.budget_tokens and self._cache:
            self._evict_one()

    def _block_tokens(self, entry: TraceEntry, index: int) -> int:
        """Estimate tokens for the block at position ``index`` of the request.

        In kvcache.ai traces, ``hash_ids[i]`` is the identifier of the i-th
        prefix block — the position is the array index, not the hash value.
        Following their ``block_tokens()``: the first blocks carry a full
        block_size and the final partial block carries the remainder.
        """
        bs = entry.block_size or self.block_size
        input_length = entry.input_length
        if input_length <= 0:
            return bs
        remaining = input_length - index * bs
        if remaining <= 0:
            return 1
        return max(1, min(bs, remaining))

    def lookup(self, entry: TraceEntry):
        """Process one trace entry: look up its blocks, add misses, evict if needed."""
        for i, hid in enumerate(entry.hash_ids):
            if hid in self._cache:
                # Cache hit.
                tc, rc = self._cache[hid]
                self._cache[hid] = (tc, rc + 1)
                self._hit_tokens += tc
                if self.policy == "lru":
                    self._touch(hid)
            else:
                # Cache miss — add to cache.
                token_count = self._block_tokens(entry, i)
                self._cache[hid] = (token_count, 1)
                self._order.append(hid)
                self._miss_tokens += token_count

        # Decrement ref_counts for all blocks in this entry (they were
        # incremented during lookup; the "reference" is only for the duration
        # of this request, matching prefix-cache semantics where blocks stay
        # resident after the request completes).
        for hid in entry.hash_ids:
            if hid in self._cache:
                tc, rc = self._cache[hid]
                self._cache[hid] = (tc, max(0, rc - 1))

        self._ensure_budget()

    def result(self) -> CacheResult:
        total = self._hit_tokens + self._miss_tokens
        hit_rate = self._hit_tokens / total if total > 0 else 0.0
        speedup = 1.0 / (1.0 - hit_rate) if hit_rate < 1.0 else float("inf")
        return CacheResult(
            hit_tokens=self._hit_tokens,
            miss_tokens=self._miss_tokens,
            total_tokens=total,
            hit_rate=hit_rate,
            speedup=speedup,
            evictions=self._evictions,
            cache_blocks=self.cache_blocks,
            cache_tokens=self.cache_tokens,
            budget_tokens=self.budget_tokens,
            policy=self.policy,
        )


# ── Ceiling calculation (unlimited budget) ────────────────────────────────────

def compute_ceiling(entries: List[TraceEntry], block_size: int = 64) -> float:
    """Compute the theoretical maximum hit rate with unlimited cache budget.

    This is the hit rate if every block ever seen is still resident.
    """
    sim = PrefixCacheSim(budget_tokens=10**18, policy="lru", block_size=block_size)
    for entry in entries:
        sim.lookup(entry)
    return sim.result().hit_rate


# ── Simulation runner ────────────────────────────────────────────────────────

def simulate_trace(
    entries: List[TraceEntry],
    budget_tokens: int,
    policy: str = "lru",
    block_size: int = 64,
) -> CacheResult:
    """Run one simulation: replay the trace through a prefix cache.

    Args:
        entries: list of trace entries (from load_trace).
        budget_tokens: maximum cache capacity in tokens (0 = unlimited).
        policy: "lru" or "fifo".
        block_size: default block size (overridden per-entry if set).

    Returns a CacheResult with hit rate, speedup, and eviction stats.
    """
    if budget_tokens <= 0:
        budget_tokens = 10**18  # effectively unlimited

    sim = PrefixCacheSim(budget_tokens=budget_tokens, policy=policy, block_size=block_size)
    for entry in entries:
        sim.lookup(entry)

    result = sim.result()
    result.ceiling = compute_ceiling(entries, block_size)
    return result


# ── Budget sweep ──────────────────────────────────────────────────────────────

@dataclass
class BudgetSweepResult:
    """Hit rate at multiple budget levels."""
    levels: List[Dict] = field(default_factory=list)  # [{budget_tokens, hit_rate, speedup, evictions}]
    ceiling: float = 0.0
    inflection_budget: int = 0    # budget at the inflection point
    inflection_hit_rate: float = 0.0
    policy: str = "lru"


def budget_sweep(
    entries: List[TraceEntry],
    budget_levels: Sequence[int],
    policy: str = "lru",
    block_size: int = 64,
) -> BudgetSweepResult:
    """Run the simulation at multiple budget levels and find the inflection point.

    The inflection point is where the marginal speedup gain drops below 50%
    of the previous step's gain — the "diminishing returns" threshold from
    the kvcache.ai budget calculation methodology.

    Args:
        entries: trace entries.
        budget_levels: list of budget sizes in tokens (sorted ascending).
        policy: eviction policy.
        block_size: default block size.

    Returns a BudgetSweepResult with per-level stats and the inflection point.
    """
    result = BudgetSweepResult(policy=policy)
    result.ceiling = compute_ceiling(entries, block_size)

    prev_speedup = 1.0
    prev_gain = 0.0

    for budget in sorted(budget_levels):
        sim_result = simulate_trace(entries, budget, policy, block_size)
        level = {
            "budget_tokens": budget,
            "budget_gb": budget * 2 / (1024**3),  # rough: 2 bytes/token per layer
            "hit_rate": sim_result.hit_rate,
            "speedup": sim_result.speedup,
            "evictions": sim_result.evictions,
            "cache_blocks": sim_result.cache_blocks,
        }
        result.levels.append(level)

        gain = sim_result.speedup - prev_speedup
        # Inflection: first level where marginal gain < 50% of the previous gain.
        if (prev_gain > 0 and gain < prev_gain * 0.5
                and result.inflection_budget == 0):
            result.inflection_budget = budget
            result.inflection_hit_rate = sim_result.hit_rate
        prev_speedup = sim_result.speedup
        prev_gain = gain

    # If no inflection found, use the last level with meaningful gain.
    if result.inflection_budget == 0 and result.levels:
        result.inflection_budget = result.levels[-1]["budget_tokens"]
        result.inflection_hit_rate = result.levels[-1]["hit_rate"]

    return result


def default_budget_levels(total_tokens: int, block_size: int = 64) -> List[int]:
    """Generate a reasonable set of budget levels for a sweep.

    Creates a geometric series from 1 block up to the total unique blocks,
    covering the interesting range of the hit-rate-vs-budget curve.
    """
    if total_tokens <= 0:
        return [64, 640, 6400, 64000, 640000, 6400000]
    max_blocks = max(1, total_tokens // block_size)
    levels = []
    n = 1
    while n <= max_blocks:
        levels.append(n * block_size)
        n = max(n + 1, int(n * 1.5))
    if levels[-1] < total_tokens:
        levels.append(total_tokens)
    return levels


# ── Summary & formatting ──────────────────────────────────────────────────────

def summarize_simulation(
    entries: List[TraceEntry],
    stats: TraceStats,
    result: CacheResult,
    sweep: Optional[BudgetSweepResult] = None,
) -> Dict:
    """Build a summary dict for JSON output and report generation."""
    summary: Dict[str, Any] = {
        "mode": "trace",
        "request_count": stats.request_count,
        "total_input_tokens": stats.total_input_tokens,
        "unique_blocks": stats.unique_blocks,
        "total_blocks": stats.total_blocks,
        "average_input_tokens": round(stats.average_input_tokens, 1),
        "block_size": stats.block_size,
        "hit_rate": result.hit_rate,
        "ceiling": result.ceiling,
        "speedup": result.speedup if result.speedup != float("inf") else 999.0,
        "hit_tokens": result.hit_tokens,
        "miss_tokens": result.miss_tokens,
        "evictions": result.evictions,
        "cache_blocks": result.cache_blocks,
        "budget_tokens": result.budget_tokens,
        "policy": result.policy,
    }
    if sweep:
        summary["ceiling_hit_rate"] = sweep.ceiling
        summary["inflection_budget_tokens"] = sweep.inflection_budget
        summary["inflection_hit_rate"] = sweep.inflection_hit_rate
        summary["budget_sweep"] = sweep.levels
    return summary


# ── Real request replay (LLM endpoint required) ──────────────────────────────
# Thin wrapper over clawperf.player.ReplayPlayer — the streaming client,
# per-request timing, and summary math live in player.py so trace/replay modes
# share one implementation.

# Imported at the bottom on purpose: pure-simulation runs (no --endpoint) must
# not pull in player/httpx, and player imports this module's TraceEntry types.
from clawperf.player import ReplayPlayer, ReplayResult, summarize_replay  # noqa: E402,F401

TraceReplayResult = ReplayResult  # backward-compatible alias
replay_summary = summarize_replay  # backward-compatible alias


def clamp_replay_max_tokens(
    index: int,
    messages: Optional[List[Dict]],
    input_length: int,
    max_tokens: int,
    max_context_tokens: int,
    token_counter=None,
) -> Tuple[str, Optional[int], Optional[int]]:
    """Decide one replay request's ``max_tokens`` under a context window.

    Returns ``(action, max_tokens, in_tokens)``:

    - ``("none", None, n)``     — fits as-is (n = measured/estimated input)
    - ``("clamp", mt, n)``      — clamp ``max_tokens`` to ``mt``
    - ``("overflow", None, n)`` — input alone >= window; request impossible

    When ``token_counter`` (a ``messages -> tokens`` callable) is given, exact
    chat-templated counts are used. Otherwise the trace's chars/4
    ``input_length`` estimate is combined with a 10% safety margin.
    ``max_context_tokens <= 0`` disables the clamp entirely.
    """
    if max_context_tokens <= 0:
        return "none", None, None
    if token_counter is not None:
        try:
            in_tok = token_counter(messages)
            if in_tok >= max_context_tokens:
                return "overflow", None, in_tok
            room = max_context_tokens - in_tok
            if room >= max_tokens:
                return "none", None, in_tok
            logger.info(
                "replay: request %d input %d tokens — clamping max_tokens "
                "%d -> %d to fit the %d-token window (exact count)",
                index, in_tok, max_tokens, room, max_context_tokens,
            )
            return "clamp", max(16, room), in_tok
        except Exception as exc:
            logger.warning(
                "replay: token counting failed for request %d (%s) — using "
                "the trace estimate", index, exc,
            )
    # Fallback: chars/4 estimate + 10% safety margin.
    effective_window = int(max_context_tokens * 0.9)
    if input_length >= effective_window:
        return "overflow", None, input_length
    room = effective_window - input_length
    if room >= max_tokens:
        return "none", None, input_length
    logger.info(
        "replay: request %d input ~%d tokens — clamping max_tokens "
        "%d -> %d to fit the %d-token window (10%% margin)",
        index, input_length, max_tokens, room, max_context_tokens,
    )
    return "clamp", max(16, room), input_length


async def replay_trace_requests(
    entries: List[TraceEntry],
    endpoint: str,
    model: str,
    api_key: str = "",
    timeout: int = 600,
    concurrency: int = 1,
    active_users: int = 1,
    max_tokens: int = 512,
    max_context_tokens: int = 0,
    tokenizer_path: str = "",
    request_rate: float = 0.0,
) -> Tuple[List[TraceReplayResult], float]:
    """Replay real requests from a trace against a live LLM endpoint.

    Only entries with ``messages`` are sent. Returns (results, bench_time_s).

    Scheduling (delegated to :class:`ReplayPlayer`):
    - **Session-aware** (trace carries ``user_id``): entries are grouped per
      session — each session replays in file order, at most ``active_users``
      sessions run concurrently.
    - **Request-level** (no user ids): up to ``concurrency`` in flight.

    Each entry's messages are sent as a streaming chat-completions request,
    measuring TTFT, e2e latency, prompt/completion tokens, and ITL — the
    real-request analog of the local hash-based simulation.

    When ``max_context_tokens`` (the model's context window, e.g. from
    ``--model-context-length``) is known, each request's ``max_tokens`` is
    clamped to the remaining window (see :func:`clamp_replay_max_tokens`) so
    cumulative session contexts don't overflow with a hard 400; requests whose
    input alone exceeds the window are skipped with a clear error. When
    ``tokenizer_path`` loads, the clamp uses exact chat-templated token counts.
    """
    replayable = [e for e in entries if e.messages]
    if not replayable:
        return [], 0.0

    # Optional exact token counting for the clamp.
    token_counter = None
    if max_context_tokens > 0 and tokenizer_path:
        try:
            from clawperf.tokenizer import TokenizerManager
            tm = TokenizerManager(tokenizer_path)
            tm.tokenizer  # force load now — fail before any request is sent
            token_counter = tm.count_chat_tokens
            logger.info("replay: exact token counting via tokenizer %s", tokenizer_path)
        except Exception as e:
            logger.warning(
                "replay: tokenizer %r unavailable (%s) — context clamp falls "
                "back to the trace's chars/4 estimate + 10%% margin",
                tokenizer_path, e,
            )

    # Flat dicts in the format ReplayPlayer.extract_request understands.
    # Clamp per-request max_tokens to the model's context window when known;
    # requests whose input alone exceeds the window are skipped with a clear
    # error instead of burning a server round-trip on an inevitable 400.
    flat: List[Dict] = []
    skipped: List[TraceReplayResult] = []
    clamped = 0
    for e in replayable:
        item: Dict = {"index": e.index, "user_id": e.user_id, "messages": e.messages}
        action, mt, in_tok = clamp_replay_max_tokens(
            e.index, e.messages, e.input_length, max_tokens,
            max_context_tokens, token_counter=token_counter,
        )
        if action == "overflow":
            logger.warning(
                "replay: request %d input %s tokens >= window %d — skipping "
                "(cannot fit regardless of max_tokens)",
                e.index, f"{in_tok:,}" if in_tok is not None else "?", max_context_tokens,
            )
            skipped.append(TraceReplayResult(
                index=e.index, success=False,
                error=(f"context overflow: input {in_tok} tokens >= model context "
                       f"window {max_context_tokens} (--model-context-length); "
                       "request skipped — use a larger-window model or trim the trace"),
            ))
            continue
        if action == "clamp":
            item["max_tokens"] = mt
            clamped += 1
        flat.append(item)
    if clamped:
        logger.info(
            "replay: clamped max_tokens on %d/%d requests to fit the "
            "--model-context-length window", clamped, len(flat),
        )
    if skipped:
        logger.warning(
            "replay: %d/%d requests skipped — input alone exceeds the "
            "--model-context-length window", len(skipped), len(replayable),
        )
    t0 = time.monotonic()
    player = ReplayPlayer(
        endpoint=endpoint, model=model, api_key=api_key,
        timeout=timeout, concurrency=concurrency,
        history_mode="verbatim", active_users=active_users,
        default_max_tokens=max_tokens,
        request_rate=request_rate,
    )
    try:
        results = await player.replay(flat)
    finally:
        await player.close()
    results = list(results) + skipped
    results.sort(key=lambda r: r.index)
    bench_time_s = time.monotonic() - t0
    return results, bench_time_s
