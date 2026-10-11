from __future__ import annotations

import base64
import io
import json
import math
import queue
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from PIL import Image

from .config import RuntimeConfig
from .layout import NO_TEXT_MARKER, format_text, get_layout


OCR_PROMPT = f"""You are an OCR transcription engine.

Transcribe only the text visible in the provided cropped image.

Rules:
1. Do not summarize.
2. Do not translate.
3. Do not explain.
4. Do not add text that is not visible.
5. Preserve the natural reading order.
6. Keep all original punctuation and symbols exactly; do not remove, normalize, or add punctuation.
7. Do not insert extra spaces after punctuation.
8. If no readable text exists, return: {NO_TEXT_MARKER}

Return only the transcribed text."""


QWEN_ENDPOINTS = {
    "beijing": "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
    "international": "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
}

TOTAL_TIMEOUT_SECONDS = 30.0
REQUEST_TIMEOUT_SECONDS = 20.0
MAX_ATTEMPTS = 3
RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}
# Bound abandoned socket calls too: cancelling must not create unbounded workers.
_REQUEST_SLOT = threading.BoundedSemaphore(1)


@dataclass(frozen=True)
class OcrResult:
    text: str
    backend: str


class OcrError(RuntimeError):
    pass


class NoOcrBackendError(OcrError):
    pass


class OcrCancelled(OcrError):
    pass


class OcrTimeout(OcrError):
    pass


@dataclass
class RequestControl:
    timeout: float = TOTAL_TIMEOUT_SECONDS
    on_progress: Callable[[str], None] = lambda _message: None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    started: float = field(default_factory=time.monotonic)

    def remaining(self) -> float:
        if self.cancel_event.is_set():
            raise OcrCancelled("OCR canceled")
        remaining = self.timeout - (time.monotonic() - self.started)
        if remaining <= 0:
            raise OcrTimeout(f"OCR exceeded the {self.timeout:g}s time budget. Try a smaller crop.")
        return remaining

    def wait(self, seconds: float) -> None:
        wake_at = time.monotonic() + seconds
        while True:
            remaining = self.remaining()
            delay = wake_at - time.monotonic()
            if delay <= 0:
                return
            # Timed waits can wake early. Recheck both clocks before retrying.
            self.cancel_event.wait(min(delay, remaining))


def recognize_text(
    image: Image.Image, config: RuntimeConfig, *, control: RequestControl | None = None
) -> OcrResult:
    if not config.api_key:
        raise NoOcrBackendError("API key is not set")

    control = control or RequestControl()
    control.remaining()
    result = _recognize_with_qwen(image, config, control)
    control.remaining()
    return result


def _recognize_with_qwen(
    image: Image.Image, config: RuntimeConfig, control: RequestControl
) -> OcrResult:
    model = config.model
    endpoint = _qwen_endpoint(config)
    try:
        layout = get_layout(config.output_format)
    except ValueError as exc:
        raise OcrError(str(exc)) from exc
    prompt = f"{OCR_PROMPT}\n\nText layout:\n{layout.instruction}"
    data_url = f"data:image/jpeg;base64,{_image_to_base64(image)}"
    payload = {
        "model": model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"image": data_url},
                        {"text": prompt},
                    ],
                }
            ]
        },
        "parameters": {
            "temperature": 0,
        },
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    body = _post_with_retries(request, control)
    control.on_progress("Checking Qwen result")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OcrError("received invalid JSON from Qwen") from exc

    text = _extract_response_text(parsed)
    return OcrResult(text=format_text(text, config.output_format), backend=f"qwen:{model}")


def _qwen_endpoint(config: RuntimeConfig) -> str:
    region = config.qwen_region or "beijing"
    try:
        return QWEN_ENDPOINTS[region]
    except KeyError as exc:
        raise OcrError("Qwen region must be beijing or international") from exc


def _post_with_retries(request: urllib.request.Request, control: RequestControl) -> str:
    last_error: OcrError | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        control.remaining()
        control.on_progress(f"Reading text with Qwen (attempt {attempt}/{MAX_ATTEMPTS})")
        delay = 0.4 * attempt
        try:
            status, body, retry_after = _request_with_budget(request, control)
            if status < 400:
                return body
            last_error = OcrError(f"Qwen HTTP {status}: {_compact_error(body)}")
            if status not in RETRYABLE_HTTP_CODES:
                raise last_error
            delay = _retry_delay(retry_after, delay)
        except urllib.error.URLError as exc:
            last_error = OcrError(_network_error_message(exc.reason))
        except TimeoutError:
            last_error = OcrError("Qwen request timed out")
        except ssl.SSLError as exc:
            last_error = OcrError(_network_error_message(exc))
        except (ConnectionResetError, OSError) as exc:
            last_error = OcrError(_network_error_message(exc))

        if attempt < MAX_ATTEMPTS:
            control.on_progress(f"{last_error}. Retrying {attempt + 1}/{MAX_ATTEMPTS} in {delay:g}s")
            control.wait(delay)

    raise last_error or OcrError("network request failed")


def _request_with_budget(
    request: urllib.request.Request, control: RequestControl
) -> tuple[int, str, str | None]:
    acquired = False
    while not acquired:
        acquired = _REQUEST_SLOT.acquire(timeout=min(0.05, control.remaining()))
        if not acquired:
            control.on_progress("Waiting for the previous Qwen connection to close")

    replies: queue.Queue[tuple[tuple[int, str, str | None] | None, Exception | None]] = queue.Queue()

    def send() -> None:
        try:
            timeout = min(REQUEST_TIMEOUT_SECONDS, control.remaining())
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    reply = (200, response.read().decode("utf-8"), None)
            except urllib.error.HTTPError as exc:
                with exc:
                    reply = (
                        exc.code, exc.read().decode("utf-8", errors="replace"),
                        exc.headers.get("Retry-After") if exc.headers else None,
                    )
            replies.put((reply, None))
        except Exception as exc:
            replies.put((None, exc))
        finally:
            _REQUEST_SLOT.release()

    try:
        control.remaining()
        threading.Thread(target=send, daemon=True, name="qwen-http").start()
    except Exception:
        _REQUEST_SLOT.release()
        raise

    # urllib's timeout is per socket operation, not a total deadline. Polling here
    # also lets the caller cancel DNS/connect/read without waiting for the socket.
    while True:
        remaining = control.remaining()
        try:
            reply, error = replies.get(timeout=min(0.05, remaining))
        except queue.Empty:
            continue
        control.remaining()
        if error is not None:
            raise error
        assert reply is not None
        return reply


def _retry_delay(value: str | None, default: float) -> float:
    if value:
        try:
            seconds = float(value)
            return max(0.0, seconds) if math.isfinite(seconds) else default
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                return max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
    return default


def _network_error_message(error: object) -> str:
    message = str(error)
    if "UNEXPECTED_EOF_WHILE_READING" in message:
        return (
            "Qwen network/TLS connection closed early. "
            "This is usually caused by network instability, VPN/proxy/firewall TLS inspection, "
            "or a reset connection. Try again, disable VPN/proxy, or use another network."
        )
    if "10054" in message or "forcibly closed" in message or "\u5f3a\u8feb\u5173\u95ed" in message:
        return (
            "Qwen connection was reset by the remote host. "
            "This is usually caused by network instability, VPN/proxy/firewall behavior, "
            "or a provider endpoint rejecting/closing the connection. Try again or switch networks."
        )

    return message


def _image_to_base64(image: Image.Image) -> str:
    rgb = image.convert("RGB")
    rgb.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    rgb.save(buffer, format="JPEG", quality=92, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _extract_response_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise OcrError("Qwen returned an invalid response object")
    if payload.get("code"):
        raise OcrError(f"Qwen rejected the request: {_compact_error(json.dumps(payload))}")
    output = payload.get("output")
    choices = output.get("choices") if isinstance(output, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise OcrError("Qwen returned no completed answer (missing choices)")
    choice = choices[0]
    reason = choice.get("finish_reason")
    if reason == "length":
        raise OcrError("Qwen output was truncated. Nothing copied; select a smaller region.")
    if reason != "stop":
        raise OcrError(f"Qwen did not complete the answer ({reason or 'missing finish_reason'}). Nothing copied.")
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise OcrError("Qwen returned an invalid answer message")
    if message.get("refusal"):
        raise OcrError("Qwen declined to process this image. Nothing copied.")
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list) and all(
        isinstance(part, dict) and isinstance(part.get("text"), str) for part in content
    ):
        text = "\n".join(part["text"] for part in content)
    else:
        raise OcrError("Qwen returned an invalid text answer")
    if not text.strip():
        raise OcrError("Qwen returned an empty answer, not a no-text result. Nothing copied.")
    return text


def _compact_error(body: str) -> str:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body[:300]

    if not isinstance(parsed, dict):
        return body[:300]
    if isinstance(parsed.get("message"), str):
        code = parsed.get("code") or "Error"
        return f"{code}: {parsed['message']}"[:300]
    error = parsed.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    return body[:300]
