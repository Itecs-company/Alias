"""Минимальная обёртка над OpenAI Chat Completions с ответом в JSON."""
from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from app.core.config import get_settings
from app.core.http import get_openai_client
from app.services.log_recorder import SearchLogRecorder, serialize_payload
from app.services.telegram_notifier import notify_admins

settings = get_settings()


def parse_json_object(text: str | None) -> dict[str, Any] | None:
    """Достаёт JSON-объект из ответа модели (в том числе обёрнутый в ```json)."""
    if not text:
        return None
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def ai_available() -> bool:
    return bool(settings.openai_api_key)


async def chat_json(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 200,
    recorder: SearchLogRecorder | None = None,
    provider: str = "openai",
    query: str = "",
) -> dict[str, Any] | None:
    """Запрашивает у модели JSON-объект. Возвращает None при любой ошибке."""
    client = get_openai_client()
    if client is None:
        return None
    from openai import APIStatusError, AuthenticationError, BadRequestError, PermissionDeniedError, RateLimitError

    model = settings.openai_model_default
    request: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if recorder:
        await recorder.record(
            provider=provider,
            direction="request",
            query=query,
            payload=serialize_payload({k: v for k, v in request.items() if k != "response_format"}),
        )
    try:
        try:
            completion = await client.chat.completions.create(**request)
        except BadRequestError as exc:
            message = str(exc).lower()
            if not any(word in message for word in ("max_tokens", "temperature", "response_format", "unsupported")):
                raise
            # Новые модели (o-series, gpt-5) требуют max_completion_tokens и не принимают temperature
            logger.info("Retrying OpenAI request with max_completion_tokens for model {model}", model=model)
            retry: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "extra_body": {"max_completion_tokens": max(max_tokens * 8, 1024)},
            }
            if "response_format" not in message:
                retry["response_format"] = {"type": "json_object"}
            completion = await client.chat.completions.create(**retry)
    except (AuthenticationError, PermissionDeniedError) as exc:
        logger.error("OpenAI authentication failed: {exc}", exc=exc)
        await _log_error(recorder, provider, query, exc)
        notify_admins("openai-auth", "OpenAI: ошибка авторизации", str(exc))
        return None
    except RateLimitError as exc:
        logger.warning("OpenAI rate limit: {exc}", exc=exc)
        await _log_error(recorder, provider, query, exc)
        if "insufficient_quota" in str(exc):
            notify_admins("openai-quota", "OpenAI: закончился баланс/квота", str(exc), low_balance=True)
        return None
    except APIStatusError as exc:
        logger.warning("OpenAI API error: {exc}", exc=exc)
        await _log_error(recorder, provider, query, exc)
        return None
    except Exception as exc:  # noqa: BLE001 - сетевые ошибки, таймауты
        logger.warning("OpenAI request failed: {exc!r}", exc=exc)
        await _log_error(recorder, provider, query, exc)
        return None

    choice = completion.choices[0] if completion.choices else None
    content = choice.message.content if choice and choice.message else None
    data = parse_json_object(content)
    if recorder:
        usage = completion.usage.model_dump() if getattr(completion, "usage", None) else None
        await recorder.record(
            provider=provider,
            direction="response",
            query=query,
            status_code=200,
            payload=serialize_payload({"content": content, "usage": usage, "finish_reason": getattr(choice, "finish_reason", None)}),
        )
    if data is None:
        logger.debug("OpenAI returned non-JSON content: {content}", content=content)
    return data


async def _log_error(recorder: SearchLogRecorder | None, provider: str, query: str, exc: Exception) -> None:
    if recorder:
        status = getattr(exc, "status_code", None)
        await recorder.record(provider=provider, direction="response", query=query, status_code=status, payload=repr(exc)[:4000])
