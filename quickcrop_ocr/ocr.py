from __future__ import annotations

import base64
import io
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from PIL import Image


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


@dataclass(frozen=True)
class OcrResult:
    text: str
    backend: str


class OcrError(RuntimeError):
    pass


class NoOcrBackendError(OcrError):
    pass


def recognize_text(image: Image.Image) -> OcrResult:
    if not os.getenv("GEMINI_API_KEY"):
        raise NoOcrBackendError("GEMINI_API_KEY is not set")

    return _recognize_with_gemini(image)


def _recognize_with_gemini(image: Image.Image) -> OcrResult:
    api_key = os.environ["GEMINI_API_KEY"]
    model = os.getenv("QUICKCROP_GEMINI_MODEL", "gemini-2.5-flash")
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
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise OcrError(f"HTTP {exc.code}: {_compact_error(error_body)}") from exc
    except urllib.error.URLError as exc:
        raise OcrError(str(exc.reason)) from exc
    except TimeoutError as exc:
        raise OcrError("timed out") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OcrError("received invalid JSON from Gemini") from exc

    text = _extract_response_text(parsed).strip()
    if not text:
        return OcrResult(text="[NO_TEXT_DETECTED]", backend="gemini")

    return OcrResult(text=_format_ocr_text(text), backend=f"gemini:{model}")


def _format_ocr_text(text: str) -> str:
    if text == "[NO_TEXT_DETECTED]":
        return text

    text = _apply_output_format(text)
    if not _space_after_punctuation_enabled():
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


def _apply_output_format(text: str) -> str:
    output_format = os.getenv("QUICKCROP_OUTPUT_FORMAT", "preserve").strip().lower()
    if output_format == "preserve":
        return text
    if output_format == "single_line":
        return " ".join(text.split())

    raise OcrError("QUICKCROP_OUTPUT_FORMAT must be preserve or single_line")


def _space_after_punctuation_enabled() -> bool:
    value = os.getenv("QUICKCROP_SPACE_AFTER_PUNCTUATION", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


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
        if value.get("type") in {"output_text", "text"} and isinstance(value.get("text"), str):
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
