"""Small provider-neutral OpenAI-compatible target adapter."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from tracefold.hashing import sha256_domain
from tracefold.schemas.common import HashDomain, TokenizerIdentity
from tracefold.schemas.phase7 import (
    ReplayRecord,
    TargetMode,
    TargetRequest,
    TargetResponse,
    TargetSettings,
    TargetStatus,
    UsageAccounting,
    UsageSource,
)
from tracefold.serialization import canonical_json_bytes

TRANSIENT_STATUS_CODES = frozenset({408, 409, 425, 429}) | frozenset(range(500, 600))
MAX_PROVIDER_RETRY_WAIT_SECONDS = 120.0
COMPONENT_VERSION = "tracefold.target/1.0.0"


def _hash_payload(payload: object, domain: HashDomain = HashDomain.CONTEXT_ARTIFACT) -> str:
    return sha256_domain(domain, canonical_json_bytes(payload))


def request_hash(request: TargetRequest) -> str:
    return _hash_payload(
        request.model_dump(mode="json", exclude={"request_hash"}),
        HashDomain.COMPRESSION_REQUEST,
    )


def response_hash(payload: object) -> str:
    return _hash_payload(payload)


def replay_record_hash(record: ReplayRecord) -> str:
    return _hash_payload(record.model_dump(mode="json", exclude={"replay_record_hash"}))


def load_replay_records(path: str | Path) -> tuple[ReplayRecord, ...]:
    records: list[ReplayRecord] = []
    request_hashes: set[str] = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = ReplayRecord.model_validate(json.loads(line))
            if record.request_hash in request_hashes:
                raise ValueError("duplicate replay request hash")
            request_hashes.add(record.request_hash)
            records.append(record)
    return tuple(records)


def build_target_request(
    *,
    request_id: str,
    benchmark_item_id: str,
    method_id: str,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    context: str,
    temperature: float,
    maximum_output_tokens: int,
    seed: int | None,
    timeout_seconds: float,
    metadata: dict[str, str | int | bool] | None = None,
) -> TargetRequest:
    draft = TargetRequest(
        request_id=request_id,
        benchmark_item_id=benchmark_item_id,
        method_id=method_id,
        model_id=model_id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        context=context,
        temperature=temperature,
        maximum_output_tokens=maximum_output_tokens,
        seed=seed,
        timeout_seconds=timeout_seconds,
        metadata=metadata or {},
        request_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"request_hash": request_hash(draft)})


class TargetAdapter:
    """HTTPX adapter with explicit live, replay, and disabled behavior."""

    def __init__(
        self,
        settings: TargetSettings,
        *,
        api_base_url: str | None = None,
        api_key: str | None = None,
        replay_records: Iterable[ReplayRecord] = (),
        transport: httpx.BaseTransport | None = None,
        sleep: Any = time.sleep,
        allow_live: bool = False,
    ) -> None:
        self.settings = settings
        self._api_base_url = api_base_url.rstrip("/") if api_base_url else None
        self._api_key = api_key
        self._replay: dict[str, ReplayRecord] = {}
        for item in replay_records:
            if item.request_hash in self._replay:
                raise ValueError("duplicate replay request hash")
            self._replay[item.request_hash] = item
        self._transport = transport
        self._sleep = sleep
        self._allow_live = allow_live
        self._live_requests_started = 0
        self._live_error: str | None
        if settings.mode == TargetMode.LIVE and allow_live is False:
            self._live_error = "LIVE_PERMISSION_REQUIRED"
        else:
            self._live_error = None

    @classmethod
    def from_environment(
        cls,
        *,
        mode: TargetMode | None = None,
        replay_records: Iterable[ReplayRecord] = (),
        transport: httpx.BaseTransport | None = None,
        allow_live: bool = False,
    ) -> TargetAdapter:
        selected_mode = mode or TargetMode(os.getenv("TRACEFOLD_API_MODE", "disabled"))
        settings = TargetSettings(
            mode=selected_mode,
            model_id=os.getenv("TRACEFOLD_TARGET_MODEL", "unconfigured"),
            endpoint_class="openai_compatible",
            request_timeout_seconds=float(os.getenv("TRACEFOLD_REQUEST_TIMEOUT_SECONDS", "30")),
            temperature=0.0,
            maximum_output_tokens=128,
            seed=0,
            maximum_retries=2,
            inter_request_delay_seconds=float(
                os.getenv("TRACEFOLD_INTER_REQUEST_DELAY_SECONDS", "0")
            ),
        )
        return cls(
            settings,
            api_base_url=os.getenv("TRACEFOLD_API_BASE_URL"),
            api_key=os.getenv("TRACEFOLD_API_KEY"),
            replay_records=replay_records,
            transport=transport,
            allow_live=allow_live,
        )

    def invoke(self, request: TargetRequest) -> TargetResponse:
        if request.request_hash != request_hash(request):
            return self._failure(request, "REQUEST_HASH_MISMATCH", "request hash mismatch")
        if request.model_id != self.settings.model_id:
            return self._failure(request, "MODEL_MISMATCH", "request model differs from adapter")
        if self.settings.mode == TargetMode.DISABLED:
            return self._failure(
                request, "TARGET_DISABLED", "target inference disabled", unavailable=True
            )
        if self.settings.mode == TargetMode.REPLAY:
            return self._replay_response(request)
        if self._live_error is not None:
            return self._failure(
                request, self._live_error, "live inference requires explicit permission"
            )
        if self._live_requests_started and self.settings.inter_request_delay_seconds:
            self._sleep(self.settings.inter_request_delay_seconds)
        self._live_requests_started += 1
        return self._live_response(request)

    def _failure(
        self,
        request: TargetRequest,
        code: str,
        message: str,
        *,
        unavailable: bool = False,
        http_status: int | None = None,
        retry_count: int = 0,
    ) -> TargetResponse:
        return TargetResponse(
            request_id=request.request_id,
            model_id=request.model_id,
            status=TargetStatus.UNAVAILABLE if unavailable else TargetStatus.INFRASTRUCTURE_FAILURE,
            http_status=http_status,
            retry_count=retry_count,
            error_code=code,
            error_message=message,
        )

    def _replay_response(self, request: TargetRequest) -> TargetResponse:
        record = self._replay.get(request.request_hash)
        if record is None:
            return self._failure(request, "REPLAY_MISSING", "no replay record for request hash")
        if record.model_id != request.model_id:
            return self._failure(
                request, "REPLAY_MODEL_MISMATCH", "replay model differs from request"
            )
        if record.benchmark_item_id not in {None, request.benchmark_item_id}:
            return self._failure(request, "REPLAY_ITEM_MISMATCH", "replay item differs request")
        if record.method_id not in {None, request.method_id}:
            return self._failure(request, "REPLAY_METHOD_MISMATCH", "replay method differs request")
        expected_prompt_hash = request.metadata.get("prompt_hash")
        if record.prompt_hash not in {None, expected_prompt_hash}:
            return self._failure(request, "REPLAY_PROMPT_MISMATCH", "replay prompt differs request")
        expected_tokenizer = request.metadata.get("tokenizer_identity")
        record_tokenizer = (
            canonical_json_bytes(record.tokenizer_identity.model_dump(mode="json")).decode("utf-8")
            if record.tokenizer_identity is not None
            else None
        )
        if record_tokenizer not in {None, expected_tokenizer}:
            return self._failure(
                request,
                "REPLAY_TOKENIZER_MISMATCH",
                "replay tokenizer differs request",
            )
        for field_name, failure_code in (
            ("compiler_commit", "REPLAY_COMPILER_MISMATCH"),
            ("benchmark_runner_commit", "REPLAY_RUNNER_MISMATCH"),
        ):
            recorded = getattr(record, field_name)
            expected = request.metadata.get(field_name)
            if recorded not in {None, expected}:
                return self._failure(request, failure_code, f"replay {field_name} differs request")
        if record.replay_record_hash != replay_record_hash(record):
            return self._failure(request, "REPLAY_HASH_MISMATCH", "replay record hash mismatch")
        payload = {
            "request_hash": record.request_hash,
            "answer_text": record.answer_text,
            "usage": record.usage.model_dump(mode="json"),
            "finish_reason": record.finish_reason,
            "error_code": record.sanitized_error_code,
            "error_message": record.sanitized_error_message,
        }
        if record.response_hash != response_hash(payload):
            return self._failure(request, "RESPONSE_HASH_MISMATCH", "replay response hash mismatch")
        status = (
            TargetStatus.SUCCESS
            if record.answer_text is not None and record.sanitized_error_code is None
            else TargetStatus.INFRASTRUCTURE_FAILURE
        )
        return TargetResponse(
            request_id=request.request_id,
            provider_request_id=record.provider_request_id,
            model_id=record.model_id,
            answer_text=record.answer_text,
            finish_reason=record.finish_reason,
            input_tokens=record.usage.input_tokens,
            output_tokens=record.usage.output_tokens,
            cached_input_tokens=record.usage.cached_input_tokens,
            reasoning_tokens=record.usage.reasoning_tokens,
            request_latency_ms=record.latency_ms,
            error_code=record.sanitized_error_code,
            error_message=record.sanitized_error_message,
            raw_response_hash=record.response_hash,
            replay_record_hash=record.replay_record_hash,
            status=status,
        )

    def _endpoint(self) -> tuple[str, str]:
        base = self._api_base_url or ""
        if base.endswith("/chat/completions"):
            return base, "chat"
        if base.endswith("/responses"):
            return base, "responses"
        if base.endswith("/v1"):
            if self.settings.endpoint_class == "responses":
                return base + "/responses", "responses"
            return base + "/chat/completions", "chat"
        if self.settings.endpoint_class == "responses":
            return base + "/v1/responses", "responses"
        return base + "/v1/chat/completions", "chat"

    def _live_response(self, request: TargetRequest) -> TargetResponse:
        if not self._api_base_url or not self._api_key:
            return self._failure(
                request, "LIVE_CONFIGURATION_MISSING", "live endpoint or key unavailable"
            )
        endpoint, api_mode = self._endpoint()
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        if api_mode == "responses":
            payload: dict[str, Any] = {
                "model": request.model_id,
                "input": [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_prompt},
                ],
                "temperature": request.temperature,
                "max_output_tokens": request.maximum_output_tokens,
            }
        else:
            payload = {
                "model": request.model_id,
                "messages": [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": request.user_prompt},
                ],
                "temperature": request.temperature,
                "max_tokens": request.maximum_output_tokens,
            }
        if request.seed is not None:
            payload["seed"] = request.seed
        retries = 0
        provider_wait_seconds = 0.0
        started = time.monotonic()
        last_error: tuple[str, str, int | None] | None = None
        with httpx.Client(timeout=request.timeout_seconds, transport=self._transport) as client:
            while True:
                try:
                    response = client.post(endpoint, headers=headers, json=payload)
                except httpx.TimeoutException:
                    return self._failure(
                        request,
                        "REQUEST_TIMEOUT",
                        "target request timed out",
                        retry_count=retries,
                    )
                except httpx.HTTPError as exc:
                    return self._failure(
                        request, "HTTP_CLIENT_ERROR", type(exc).__name__, retry_count=retries
                    )
                if (
                    response.status_code in TRANSIENT_STATUS_CODES
                    and retries < self.settings.maximum_retries
                ):
                    remaining_wait = MAX_PROVIDER_RETRY_WAIT_SECONDS - provider_wait_seconds
                    delay = min(_retry_delay(response, retries), max(0.0, remaining_wait))
                    if delay:
                        self._sleep(delay)
                        provider_wait_seconds += delay
                    retries += 1
                    continue
                if response.status_code >= 400:
                    code, message = _provider_error(response, secret=self._api_key)
                    last_error = (code, message, response.status_code)
                    break
                try:
                    data = response.json()
                    answer = _answer_from_payload(data, api_mode)
                except (ValueError, TypeError, KeyError) as exc:
                    return self._failure(
                        request,
                        "MALFORMED_PROVIDER_RESPONSE",
                        type(exc).__name__,
                        http_status=response.status_code,
                        retry_count=retries,
                    )
                if answer is None:
                    return self._failure(
                        request,
                        "EMPTY_PROVIDER_RESPONSE",
                        "provider response contained no answer",
                        http_status=response.status_code,
                        retry_count=retries,
                    )
                usage = _usage_from_payload(data)
                raw_hash = response_hash(data)
                return TargetResponse(
                    request_id=request.request_id,
                    provider_request_id=_provider_request_id(data),
                    model_id=str(data.get("model", request.model_id)),
                    answer_text=answer,
                    finish_reason=_finish_reason(data),
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cached_input_tokens=usage.cached_input_tokens,
                    reasoning_tokens=usage.reasoning_tokens,
                    request_latency_ms=(time.monotonic() - started) * 1000,
                    http_status=response.status_code,
                    retry_count=retries,
                    raw_response_hash=raw_hash,
                    status=TargetStatus.SUCCESS,
                )
        assert last_error is not None
        return self._failure(
            request,
            last_error[0],
            last_error[1],
            http_status=last_error[2],
            retry_count=retries,
        )


def _sanitize_provider_text(value: object, *, secret: str | None) -> str:
    text = str(value)
    if secret:
        text = text.replace(secret, "[redacted]")
    return re.sub(r"Bearer\s+\S+", "Bearer [redacted]", text, flags=re.IGNORECASE)[:240]


def _provider_error(response: httpx.Response, *, secret: str | None) -> tuple[str, str]:
    try:
        payload = response.json()
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = _sanitize_provider_text(
            error.get("code", f"HTTP_{response.status_code}"), secret=secret
        )
        message = _sanitize_provider_text(
            error.get("message", "provider request failed"), secret=secret
        )
    except (ValueError, TypeError):
        code, message = f"HTTP_{response.status_code}", "provider request failed"
    return code, message


def _retry_delay(response: httpx.Response, retry_count: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            seconds = float(retry_after)
        except ValueError:
            pass
        else:
            if seconds >= 0:
                return min(seconds, MAX_PROVIDER_RETRY_WAIT_SECONDS)
    return float(0.25 * (2**retry_count))


def _answer_from_payload(payload: dict[str, Any], mode: str) -> str | None:
    if mode == "responses":
        output_text = payload.get("output_text")
        if isinstance(output_text, str):
            return output_text
        output = payload.get("output", [])
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                for content in item.get("content", []) if isinstance(item, dict) else []:
                    if isinstance(content, dict) and isinstance(content.get("text"), str):
                        parts.append(content["text"])
            return "".join(parts) or None
        return None
    choices = payload.get("choices", [])
    if not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message", {})
    answer = message.get("content") if isinstance(message, dict) else None
    return answer if isinstance(answer, str) else None


def _usage_from_payload(payload: dict[str, Any]) -> UsageAccounting:
    usage = payload.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    prompt_details = usage.get("prompt_tokens_details", {})
    completion_details = usage.get("completion_tokens_details", {})
    return UsageAccounting(
        source=UsageSource.PROVIDER,
        input_tokens=input_tokens if isinstance(input_tokens, int) else None,
        output_tokens=output_tokens if isinstance(output_tokens, int) else None,
        cached_input_tokens=(
            prompt_details.get("cached_tokens") if isinstance(prompt_details, dict) else None
        ),
        reasoning_tokens=(
            completion_details.get("reasoning_tokens")
            if isinstance(completion_details, dict)
            else None
        ),
    )


def _provider_request_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("id")
    return value if isinstance(value, str) else None


def _finish_reason(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices", [])
    if choices and isinstance(choices[0], dict):
        value = choices[0].get("finish_reason")
        return value if isinstance(value, str) else None
    value = payload.get("status")
    return value if isinstance(value, str) else None


def replay_record_from_response(request: TargetRequest, response: TargetResponse) -> ReplayRecord:
    usage = UsageAccounting(
        source=UsageSource.PROVIDER if response.input_tokens is not None else UsageSource.UNKNOWN,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cached_input_tokens=response.cached_input_tokens,
        reasoning_tokens=response.reasoning_tokens,
    )
    payload = {
        "request_hash": request.request_hash,
        "answer_text": response.answer_text,
        "usage": usage.model_dump(mode="json"),
        "finish_reason": response.finish_reason,
        "error_code": response.error_code,
        "error_message": response.error_message,
    }
    tokenizer_payload = request.metadata.get("tokenizer_identity")
    tokenizer_identity = (
        TokenizerIdentity.model_validate(json.loads(tokenizer_payload))
        if isinstance(tokenizer_payload, str) and tokenizer_payload != "null"
        else None
    )
    draft = ReplayRecord(
        request_hash=request.request_hash,
        model_id=response.model_id,
        answer_text=response.answer_text,
        usage=usage,
        latency_ms=response.request_latency_ms,
        finish_reason=response.finish_reason,
        sanitized_error_code=response.error_code,
        sanitized_error_message=response.error_message,
        response_hash=response_hash(payload),
        generated_at=datetime.now(UTC),
        provider_request_id=response.provider_request_id,
        benchmark_item_id=request.benchmark_item_id,
        method_id=request.method_id,
        prompt_hash=(
            str(request.metadata["prompt_hash"]) if "prompt_hash" in request.metadata else None
        ),
        tokenizer_identity=tokenizer_identity,
        compiler_commit=(
            str(request.metadata["compiler_commit"])
            if "compiler_commit" in request.metadata
            else None
        ),
        benchmark_runner_commit=(
            str(request.metadata["benchmark_runner_commit"])
            if "benchmark_runner_commit" in request.metadata
            else None
        ),
        replay_record_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"replay_record_hash": replay_record_hash(draft)})


__all__ = [
    "COMPONENT_VERSION",
    "TargetAdapter",
    "build_target_request",
    "load_replay_records",
    "replay_record_from_response",
    "replay_record_hash",
    "request_hash",
    "response_hash",
]
