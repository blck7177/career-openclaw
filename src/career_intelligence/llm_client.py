"""
Unified LLM client — auto-detects provider from environment variables.

Priority: OPENAI_API_KEY > ANTHROPIC_API_KEY

LLM_MODEL env var overrides the provider's default model. Set it to match
the provider you are using:
  Anthropic default : claude-3-5-sonnet-20241022
  OpenAI default    : gpt-4o

Usage:
    from .llm_client import make_client

    client = make_client()
    if client is None:
        # no usable API key found
        ...
    text = client.call(system="You are ...", user="Extract ...", max_tokens=512)
"""

from __future__ import annotations

import os

_DEFAULT_MODEL_ANTHROPIC = "claude-3-5-sonnet-20241022"
_DEFAULT_MODEL_OPENAI = "gpt-4o"

_MIN_KEY_LENGTH = 20  # shorter strings are treated as placeholders

# Request-level reliability defaults. A bounded timeout turns an indefinitely
# hung HTTP call into a recoverable failure, so the single worker can never be
# frozen forever by one stuck LLM request. max_retries uses the SDK's built-in
# exponential backoff for transient errors (429 / 5xx / connection), and does
# not retry 4xx. Both are overridable via env.
_DEFAULT_LLM_TIMEOUT_S = 90.0
_DEFAULT_LLM_MAX_RETRIES = 2


class LLMClient:
    """Thin wrapper that normalises Anthropic / OpenAI call interface."""

    def __init__(self, provider: str, raw_client, default_model: str) -> None:
        self._provider = provider
        self._raw = raw_client
        self._default_model = default_model

    @property
    def provider(self) -> str:
        return self._provider

    def call(
        self,
        system: str,
        user: str,
        max_tokens: int = 2048,
        model: str | None = None,
    ) -> str:
        """
        Call the LLM and return the response text string.
        Raises on failure — callers should catch and handle.
        """
        resolved_model = model or os.environ.get("LLM_MODEL") or self._default_model

        if self._provider == "anthropic":
            message = self._raw.messages.create(
                model=resolved_model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return message.content[0].text

        if self._provider == "openai":
            # o1/o3/o4 family uses max_completion_tokens; gpt-4x also accepts it.
            # system role is unsupported on o1+; fold it into the user message instead.
            is_reasoning_model = resolved_model.startswith(("o1", "o3", "o4"))
            if is_reasoning_model:
                messages = [{"role": "user", "content": f"{system}\n\n{user}"}]
            else:
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
            response = self._raw.chat.completions.create(
                model=resolved_model,
                max_completion_tokens=max_tokens,
                messages=messages,
            )
            return response.choices[0].message.content

        raise RuntimeError(f"Unknown LLM provider: {self._provider}")


def make_client() -> LLMClient | None:
    """
    Auto-detect LLM provider from environment variables.

    Priority order:
      1. OPENAI_API_KEY (if present and not a placeholder)
      2. ANTHROPIC_API_KEY (if present and not a placeholder)

    Returns None when no usable key is found (pipeline continues with stubs).
    """
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if _is_real_key(openai_key):
        timeout_s, max_retries = _reliability_options()
        try:
            import openai as _openai  # type: ignore
            raw = _openai.OpenAI(
                api_key=openai_key,
                timeout=timeout_s,
                max_retries=max_retries,
            )
            return LLMClient("openai", raw, _DEFAULT_MODEL_OPENAI)
        except Exception:
            pass

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if _is_real_key(anthropic_key):
        timeout_s, max_retries = _reliability_options()
        try:
            import anthropic as _anthropic  # type: ignore
            raw = _anthropic.Anthropic(
                api_key=anthropic_key,
                timeout=timeout_s,
                max_retries=max_retries,
            )
            return LLMClient("anthropic", raw, _DEFAULT_MODEL_ANTHROPIC)
        except Exception:
            pass

    return None


def _reliability_options() -> tuple[float, int]:
    """
    Resolve (timeout_s, max_retries) from env, falling back to defaults.

    Parsed lazily — only after a usable API key is found — so a malformed
    LLM_TIMEOUT_S / LLM_MAX_RETRIES never breaks the no-key path that returns
    None. Invalid values fail fast with a clear, actionable message.
    """
    timeout_s = _parse_env_number("LLM_TIMEOUT_S", _DEFAULT_LLM_TIMEOUT_S, float)
    max_retries = _parse_env_number("LLM_MAX_RETRIES", _DEFAULT_LLM_MAX_RETRIES, int)
    return timeout_s, max_retries


def _parse_env_number(name: str, default, caster):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return caster(raw.strip())
    except ValueError as exc:
        raise ValueError(
            f"Invalid {name}={raw!r}: expected {caster.__name__}"
        ) from exc


def _is_real_key(key: str) -> bool:
    """Return True only when the key looks like a real secret (not a placeholder)."""
    if not key or len(key) < _MIN_KEY_LENGTH:
        return False
    if key.endswith("...") or key.endswith("-"):
        return False
    return True
