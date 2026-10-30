"""Token Factory client for CrisisGuard AI (Person A).

Wraps the OpenAI-compatible Nebius Token Factory API with:
  - timeouts and bounded API retries (connection errors, 429, 5xx)
  - a clear ModelUnavailable exception for the dashboard's model-down banner
  - JSON extraction + Pydantic validation, with one repair retry
  - an on-disk record/replay cache (cheap evals, replay mode if credits run out)

Two kinds of retry exist in the project and must stay separate:
  1. API / JSON-format retries   -> handled HERE.
  2. Validator-rejection retries -> handled by the orchestrator (max 3).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, TypeVar

import openai
from openai import OpenAI
from pydantic import BaseModel

try:  # optional: load NEBIUS_* settings from a local .env file
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

log = logging.getLogger("TRIAGEOPS.llm")

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
# Example ID from NVIDIA's docs. Model IDs change: confirm with scripts/check_token_factory.py
DEFAULT_EXTRACTION_MODEL = "nvidia/Nemotron-3-Nano-30B-A3B"

T = TypeVar("T", bound=BaseModel)


class ModelUnavailable(Exception):
    """The model could not be reached (network, rate limit, 5xx). Show the banner / manual mode."""


class CacheMiss(ModelUnavailable):
    """replay_only mode and the request was not recorded."""


class LLMConfigError(Exception):
    """Bad key, unknown model ID or malformed request. A config bug, not an outage."""


class StructuredOutputError(Exception):
    """The model never produced JSON matching the schema, even after one repair attempt."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


@dataclass
class LLMResult:
    text: str
    model: str
    latency_ms: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached: bool = False


def extract_json(text: str) -> Any:
    """Pull the first JSON object out of a model reply (handles <think> blocks and code fences)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    return json.loads(text[start : end + 1])


class TokenFactoryClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        extraction_model: str | None = None,
        planning_model: str | None = None,
        timeout: float = 45.0,
        max_api_retries: int = 2,
        cache_dir: str | Path | None = None,
        cache_mode: str | None = None,
        openai_client: Any = None,  # injected in tests
    ):
        self.base_url = base_url or os.getenv("NEBIUS_BASE_URL", DEFAULT_BASE_URL)
        self.extraction_model = extraction_model or os.getenv(
            "NEBIUS_EXTRACTION_MODEL", DEFAULT_EXTRACTION_MODEL
        )
        # Falls back to the extraction model until you pick a larger Nemotron for planning.
        self.planning_model = (
            planning_model or os.getenv("NEBIUS_PLANNING_MODEL") or self.extraction_model
        )
        self.max_api_retries = max_api_retries
        self.cache_mode = (cache_mode or os.getenv("LLM_CACHE_MODE", "off")).lower()
        if self.cache_mode not in {"off", "readwrite", "replay_only"}:
            raise LLMConfigError("LLM_CACHE_MODE must be off, readwrite or replay_only")
        self.cache_dir = Path(cache_dir or os.getenv("LLM_CACHE_DIR", ".llm_cache"))
        self._json_mode_ok = True
        self._sleep = time.sleep

        self._client = openai_client
        if self._client is None and self.cache_mode != "replay_only":
            api_key = api_key or os.getenv("NEBIUS_API_KEY")
            if not api_key:
                raise LLMConfigError("NEBIUS_API_KEY is not set")
            # max_retries=0: we do our own bounded retries so behaviour is predictable.
            self._client = OpenAI(
                api_key=api_key, base_url=self.base_url, timeout=timeout, max_retries=0
            )

    # ------------------------------------------------------------------ public API
    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 1500,
        json_mode: bool = False,
    ) -> LLMResult:
        key = self._cache_key(model, messages, temperature, max_tokens, json_mode)
        if self.cache_mode != "off":
            hit = self._cache_read(key)
            if hit is not None:
                log.info("llm cache hit model=%s", model)
                return replace(hit, cached=True)
            if self.cache_mode == "replay_only":
                raise CacheMiss("request not found in replay cache")

        result = self._call_live(messages, model, temperature, max_tokens, json_mode)
        if self.cache_mode == "readwrite":
            self._cache_write(key, result)
        return result

    def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: type[T],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 1500,
    ) -> tuple[T, LLMResult]:
        """Call the model, parse JSON, validate against `schema`. One repair retry on bad output."""
        msgs = list(messages)
        last_err: Exception | None = None
        res: LLMResult | None = None
        for _ in range(2):  # initial attempt + one repair
            res = self.complete(
                msgs,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=self._json_mode_ok,
            )
            try:
                return schema.model_validate(extract_json(res.text)), res
            except ValueError as err:  # JSONDecodeError and pydantic ValidationError both subclass it
                last_err = err
                msgs = msgs + [
                    {"role": "assistant", "content": res.text},
                    {
                        "role": "user",
                        "content": "That reply was not valid. Error: "
                        f"{str(err)[:500]}\nReply with ONLY the corrected JSON object.",
                    },
                ]
        raise StructuredOutputError(str(last_err), raw=res.text if res else "")

    def extract(self, messages, schema: type[T], **kw) -> tuple[T, LLMResult]:
        return self.complete_json(messages, schema, model=self.extraction_model, **kw)

    def plan(self, messages, schema: type[T], **kw) -> tuple[T, LLMResult]:
        return self.complete_json(messages, schema, model=self.planning_model, **kw)

    def list_models(self) -> list[str]:
        if self._client is None:
            raise LLMConfigError("no live client (replay_only mode)")
        return sorted(m.id for m in self._client.models.list().data)

    # ------------------------------------------------------------------ internals
    def _call_live(self, messages, model, temperature, max_tokens, json_mode) -> LLMResult:
        last_err: Exception | None = None
        attempt = 0
        while attempt <= self.max_api_retries:
            kwargs: dict[str, Any] = dict(
                model=model, messages=messages, temperature=temperature, max_tokens=max_tokens
            )
            if json_mode and self._json_mode_ok:
                kwargs["response_format"] = {"type": "json_object"}
            started = time.perf_counter()
            try:
                resp = self._client.chat.completions.create(**kwargs)
            except openai.BadRequestError as err:
                if "response_format" in kwargs:  # server rejected JSON mode: drop it, don't count
                    log.warning("JSON mode rejected by server; falling back to prompt-only JSON")
                    self._json_mode_ok = False
                    continue
                raise LLMConfigError(f"bad request: {err}") from err
            except (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError) as err:
                raise LLMConfigError(f"check API key and model ID ({model}): {err}") from err
            except (openai.APIConnectionError, openai.RateLimitError) as err:
                last_err = err
            except openai.APIStatusError as err:
                if err.status_code < 500:
                    raise LLMConfigError(f"request rejected ({err.status_code}): {err}") from err
                last_err = err
            else:
                latency_ms = (time.perf_counter() - started) * 1000
                usage = getattr(resp, "usage", None)
                result = LLMResult(
                    text=resp.choices[0].message.content or "",
                    model=model,
                    latency_ms=round(latency_ms, 1),
                    prompt_tokens=getattr(usage, "prompt_tokens", None),
                    completion_tokens=getattr(usage, "completion_tokens", None),
                )
                log.info(
                    "llm call model=%s latency=%.0fms tokens=%s/%s",
                    model, latency_ms, result.prompt_tokens, result.completion_tokens,
                )
                return result
            attempt += 1
            if attempt <= self.max_api_retries:
                self._sleep(min(2**attempt, 8))
        raise ModelUnavailable(f"Token Factory unreachable after retries: {last_err}")

    @staticmethod
    def _cache_key(model, messages, temperature, max_tokens, json_mode) -> str:
        blob = json.dumps(
            [model, messages, temperature, max_tokens, json_mode], sort_keys=True, ensure_ascii=False
        )
        return hashlib.sha256(blob.encode()).hexdigest()

    def _cache_read(self, key: str) -> LLMResult | None:
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        return LLMResult(**json.loads(path.read_text()))

    def _cache_write(self, key: str, result: LLMResult) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        data = asdict(replace(result, cached=False))
        (self.cache_dir / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False))