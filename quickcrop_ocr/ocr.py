from __future__ import annotations

import base64
import io
import json
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from PIL import Image

from .config import RuntimeConfig


OCR_PROMPT = """You are an OCR transcription engine.

Transcribe only the text visible in the provided cropped image.

Rules:
1. Do not summarize.
2. Do not translate.
3. Do not explain.
4. Do not add text that is not visible.
5. Preserve the natural reading order.
6. Preserve line breaks and paragraph breaks.
7. If the image contains code, preserve indentation as much as possible.
8. If the image contains a table, preserve rows using tabs or spaces.
9. If no readable text exists, return: [NO_TEXT_DETECTED]

Return only the transcribed text."""


QWEN_ENDPOINTS = {
    "beijing": "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
    "international": "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
}


@dataclass(frozen=True)
class OcrResult:
    text: str
    backend: str


class OcrError(RuntimeError):
    pass


class NoOcrBackendError(OcrError):
    pass


def recognize_text(image: Image.Image, config: RuntimeConfig) -> OcrResult:
    if not config.api_key:
        raise NoOcrBackendError("API key is not set")

    if config.provider == "gemini":
        return _recognize_with_gemini(image, config)
    if config.provider == "qwen":
        return _recognize_with_qwen(image, config)

    raise OcrError(f"unsupported OCR provider: {config.provider}")


def _recognize_with_gemini(image: Image.Image, config: RuntimeConfig) -> OcrResult:
    model = config.model
    image_data = _image_to_base64(image)
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": OCR_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_data,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "thinkingConfig": {
                "thinkingBudget": 0,
            },
        },
    }

    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-goog-api-key": config.api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    body = _post_with_retries(request)

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OcrError("received invalid JSON from Gemini") from exc

    text = _extract_response_text(parsed).strip()
    if not text:
        return OcrResult(text="[NO_TEXT_DETECTED]", backend="gemini")

    return OcrResult(text=_format_ocr_text(text, config), backend=f"gemini:{model}")


def _recognize_with_qwen(image: Image.Image, config: RuntimeConfig) -> OcrResult:
    model = config.model
    endpoint = _qwen_endpoint(config)
    data_url = f"data:image/jpeg;base64,{_image_to_base64(image)}"
    payload = {
        "model": model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"image": data_url},
                        {"text": OCR_PROMPT},
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

    body = _post_with_retries(request, provider="Qwen")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OcrError("received invalid JSON from Qwen") from exc

    text = _extract_response_text(parsed).strip()
    if not text:
        return OcrResult(text="[NO_TEXT_DETECTED]", backend="qwen")

    return OcrResult(text=_format_ocr_text(text, config), backend=f"qwen:{model}")


def _qwen_endpoint(config: RuntimeConfig) -> str:
    region = config.qwen_region or "beijing"
    try:
        return QWEN_ENDPOINTS[region]
    except KeyError as exc:
        raise OcrError("Qwen region must be beijing or international") from exc


def _post_with_retries(request: urllib.request.Request, *, provider: str = "Gemini") -> str:
    attempts = 3
    last_error: OcrError | None = None

    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise OcrError(f"HTTP {exc.code}: {_compact_error(error_body)}") from exc
        except urllib.error.URLError as exc:
            last_error = OcrError(_network_error_message(exc.reason, provider=provider))
        except TimeoutError as exc:
            last_error = OcrError("timed out")
        except ssl.SSLError as exc:
            last_error = OcrError(_network_error_message(exc, provider=provider))
        except (ConnectionResetError, OSError) as exc:
            last_error = OcrError(_network_error_message(exc, provider=provider))

        if attempt < attempts:
            time.sleep(0.4 * attempt)

    raise last_error or OcrError("network request failed")


def _network_error_message(error: object, *, provider: str) -> str:
    message = str(error)
    if "UNEXPECTED_EOF_WHILE_READING" in message:
        return (
            f"{provider} network/TLS connection closed early. "
            "This is usually caused by network instability, VPN/proxy/firewall TLS inspection, "
            "or a reset connection. Try again, disable VPN/proxy, or use another network."
        )
    if "10054" in message or "forcibly closed" in message or "\u5f3a\u8feb\u5173\u95ed" in message:
        return (
            f"{provider} connection was reset by the remote host. "
            "This is usually caused by network instability, VPN/proxy/firewall behavior, "
            "or a provider endpoint rejecting/closing the connection. Try again or switch networks."
        )

    return message


def _format_ocr_text(text: str, config: RuntimeConfig) -> str:
    if text == "[NO_TEXT_DETECTED]":
        return text

    text = _apply_output_format(text, config)
    if not config.space_after_punctuation:
        return text

    result: list[str] = []
    punctuation = set(",;:!?\u3001\uff0c\u3002\uff1b\uff1a\uff01\uff1f")

    for index, char in enumerate(text):
        result.append(char)
        if char not in punctuation and char != ".":
            continue

        next_char = text[index + 1] if index + 1 < len(text) else ""
        prev_char = text[index - 1] if index > 0 else ""
        if not next_char or next_char.isspace():
            continue
        if char == "." and prev_char.isdigit() and next_char.isdigit():
            continue

        result.append(" ")

    return "".join(result)


def _apply_output_format(text: str, config: RuntimeConfig) -> str:
    if config.output_format == "preserve":
        return text
    if config.output_format == "single_line":
        return " ".join(text.split())

    raise OcrError("output format must be preserve or single_line")


def _image_to_base64(image: Image.Image) -> str:
    rgb = image.convert("RGB")
    rgb.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    rgb.save(buffer, format="JPEG", quality=92, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _extract_response_text(payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for candidate in payload.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        for part in content.get("parts", []):
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])

    if chunks:
        return "\n".join(chunks)

    _walk_response(payload, chunks)
    return "\n".join(chunk for chunk in chunks if chunk)


def _walk_response(value: Any, chunks: list[str]) -> None:
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            chunks.append(value["text"])
        for child in value.values():
            _walk_response(child, chunks)
    elif isinstance(value, list):
        for child in value:
            _walk_response(child, chunks)


def _compact_error(body: str) -> str:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body[:300]

    error = parsed.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    return body[:300]
