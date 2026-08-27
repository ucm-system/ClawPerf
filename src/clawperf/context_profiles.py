"""Named context-size profiles and pre-configured benchmark suites.

Inspired by agentic-swarm-bench's context profiles (fresh/short/medium/long/
full/xl/xxl) and suite configs (quick/standard/full). These provide
human-friendly names over raw token counts so users don't have to calculate
prefix sizes manually.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# ── Context profiles ─────────────────────────────────────────────────────────
# Each profile maps to a target system-prefix token count. The user-prefix
# is derived as ~1/3 of the system prefix (a realistic ratio seen in real
# agent sessions). Input/output per turn stay at the config defaults unless
# overridden by the suite or CLI.
#
# Token counts approximate real agentic session sizes:
#   fresh  = a quick single-shot question (~6K context)
#   short  = a short conversation with a few tool calls (~20K)
#   medium = a medium coding session with file contents (~40K)
#   long   = a long session with multiple files + history (~70K)
#   full   = a very long session approaching 100K
#   xl     = extreme: 200K context (stresses prefill heavily)
#   xxl    = maximum: 400K context (near the largest model windows)

CONTEXT_PROFILES: Dict[str, Dict[str, int]] = {
    "fresh":  {"system_prefix_tokens": 4_000,  "user_prefix_tokens": 1_500, "input_tokens_per_turn": 1_500},
    "short":  {"system_prefix_tokens": 14_000, "user_prefix_tokens": 5_000,  "input_tokens_per_turn": 3_000},
    "medium": {"system_prefix_tokens": 28_000, "user_prefix_tokens": 10_000, "input_tokens_per_turn": 5_000},
    "long":   {"system_prefix_tokens": 50_000, "user_prefix_tokens": 18_000, "input_tokens_per_turn": 7_000},
    "full":   {"system_prefix_tokens": 72_000, "user_prefix_tokens": 25_000, "input_tokens_per_turn": 8_000},
    "xl":     {"system_prefix_tokens": 150_000, "user_prefix_tokens": 45_000, "input_tokens_per_turn": 10_000},
    "xxl":    {"system_prefix_tokens": 300_000, "user_prefix_tokens": 80_000, "input_tokens_per_turn": 12_000},
}

# Profiles ordered from smallest to largest (for sweeps).
PROFILE_ORDER: List[str] = ["fresh", "short", "medium", "long", "full", "xl", "xxl"]

# The "realistic" sweep profile: fresh -> full (skip xl/xxl unless explicitly
# requested — they stress prefill so heavily that they're for specialized testing).
REALISTIC_PROFILES: List[str] = ["fresh", "short", "medium", "long", "full"]

# ── Suites ───────────────────────────────────────────────────────────────────
# A suite is a pre-configured combination of user counts and context profiles.
# `resolved_scenarios` produces a list of (num_users, profile_name, token_info)
# tuples — the cross-product of users × profiles, filtered by the model's
# context window.

SUITES: Dict[str, Dict] = {
    "quick": {
        "description": "Fast smoke test: 3 concurrency levels at a small context.",
        "users": [1, 4, 8],
        "profiles": ["fresh"],
        "max_turns": 10,
        "output_tokens_per_turn": 256,
    },
    "standard": {
        "description": "Standard benchmark: 4 concurrency levels at medium+long context.",
        "users": [1, 8, 16, 32],
        "profiles": ["medium", "long"],
        "max_turns": 20,
        "output_tokens_per_turn": 512,
    },
    "full": {
        "description": "Full sweep: 6 concurrency levels across all realistic profiles.",
        "users": [1, 4, 8, 16, 32, 64],
        "profiles": "realistic",  # expands to REALISTIC_PROFILES
        "max_turns": 30,
        "output_tokens_per_turn": 512,
    },
    "hitrate": {
        "description": "Prefix-cache hit-rate focused: single user, all profiles.",
        "users": [1],
        "profiles": "realistic",
        "max_turns": 5,
        "output_tokens_per_turn": 128,
    },
}


def get_profile(name: str) -> Dict[str, int]:
    """Look up a context profile by name (case-insensitive)."""
    key = name.lower().strip()
    if key not in CONTEXT_PROFILES:
        valid = ", ".join(CONTEXT_PROFILES)
        raise ValueError(f"Unknown context profile '{name}'. Valid: {valid}")
    return dict(CONTEXT_PROFILES[key])  # copy so caller can mutate


def resolve_suite(name: str, model_context_length: int = 0) -> List[Tuple[int, str, Dict[str, int]]]:
    """Expand a suite into a list of (num_users, profile_name, token_config) tuples.

    Tuples are ordered by profile then users (so each profile is fully tested
    before moving to the next). If ``model_context_length > 0``, profiles whose
    total context (system + user + input) exceeds the window are skipped.
    """
    key = name.lower().strip()
    if key not in SUITES:
        valid = ", ".join(SUITES)
        raise ValueError(f"Unknown suite '{name}'. Valid: {valid}")

    suite = SUITES[key]
    profiles_spec = suite["profiles"]
    if profiles_spec == "realistic":
        profiles = list(REALISTIC_PROFILES)
    elif isinstance(profiles_spec, str):
        profiles = [profiles_spec]
    else:
        profiles = list(profiles_spec)

    scenarios: List[Tuple[int, str, Dict[str, int]]] = []
    for pname in profiles:
        ptokens = get_profile(pname)
        total = ptokens["system_prefix_tokens"] + ptokens["user_prefix_tokens"] + ptokens["input_tokens_per_turn"]
        if model_context_length > 0 and total >= model_context_length:
            continue  # skip profiles that would overflow the model's window
        for u in suite["users"]:
            scenarios.append((u, pname, ptokens))

    return scenarios


def list_profiles() -> List[str]:
    """Return all profile names in size order."""
    return list(PROFILE_ORDER)


def list_suites() -> List[str]:
    """Return all suite names."""
    return list(SUITES.keys())


def suite_settings(name: str) -> Dict:
    """Return the run-level settings of a suite (max_turns, output per turn).

    Used by the runner to apply per-suite run parameters that aren't part of
    the (users × profile) expansion.
    """
    key = name.lower().strip()
    if key not in SUITES:
        valid = ", ".join(SUITES)
        raise ValueError(f"Unknown suite '{name}'. Valid: {valid}")
    return {
        "max_turns": int(SUITES[key].get("max_turns", 20)),
        "output_tokens_per_turn": int(SUITES[key].get("output_tokens_per_turn", 512)),
    }
