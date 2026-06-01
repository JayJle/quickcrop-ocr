from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageEnhance, ImageOps


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

WINDOWS_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


@dataclass(frozen=True)
class OcrResult:
    text: str
    backend: str


class OcrError(RuntimeError):
    pass


class NoOcrBackendError(OcrError):
    pass


def recognize_text(image: Image.Image) -> OcrResult:
    mode = os.getenv("QUICKCROP_OCR_MODE", "auto").strip().lower()
    if mode not in {"auto", "fast", "accurate"}:
        raise OcrError("QUICKCROP_OCR_MODE must be auto, fast, or accurate")

    errors: list[str] = []

    if mode in {"auto", "fast"}:
        tesseract_command = _find_tesseract_command()
        if tesseract_command:
            try:
                return _recognize_with_tesseract(image, tesseract_command)
            except OcrError as exc:
                errors.append(f"Tesseract: {exc}")
        elif mode == "fast":
            raise NoOcrBackendError("Tesseract is not installed or not on PATH")

    if mode in {"auto", "accurate"}:
        if os.getenv("OPENAI_API_KEY"):
            try:
                return _recognize_with_openai(image)
            except OcrError as exc:
                errors.append(f"OpenAI: {exc}")
        elif mode == "accurate":
            raise NoOcrBackendError("OPENAI_API_KEY is not set")

    if errors:
        raise OcrError("; ".join(errors))

    raise NoOcrBackendError(
        "No OCR backend available. Install Tesseract or set OPENAI_API_KEY."
    )


def _find_tesseract_command() -> str | None:
    command = shutil.which("tesseract")
    if command:
        return command

    for path in WINDOWS_TESSERACT_PATHS:
        if os.path.exists(path):
            return path

    configured = os.getenv("QUICKCROP_TESSERACT_EXE")
    if configured and os.path.exists(configured):
        return configured

    return None


def _recognize_with_tesseract(image: Image.Image, tesseract_command: str) -> OcrResult:
    lang = _normalize_tesseract_lang(os.getenv("QUICKCROP_TESSERACT_LANG", "chi_sim+eng"))
    psm = os.getenv("QUICKCROP_TESSERACT_PSM", "6")
    processed = _preprocess_for_tesseract(image)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        temp_path = tmp.name

    try:
        processed.save(temp_path, "PNG")
        _maybe_save_debug_image(processed)
        process = subprocess.run(
            [tesseract_command, temp_path, "stdout", "-l", lang, "--psm", psm],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OcrError("timed out") from exc
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

    if process.returncode != 0:
        message = process.stderr.strip() or "tesseract returned a non-zero exit code"
        raise OcrError(message)

    text = process.stdout.strip()
    return OcrResult(text=text or "[NO_TEXT_DETECTED]", backend="tesseract")


def _normalize_tesseract_lang(lang: str) -> str:
    parts = [part.strip() for part in lang.replace(",", "+").split("+") if part.strip()]
    if not parts:
        return "chi_sim+eng"

    # Tesseract's language order affects recognition. Prefer Chinese first for mixed
    # Chinese/English captures, otherwise English can dominate short CJK text.
    chinese_first = [part for part in parts if part.startswith("chi_") or part.startswith("script\\Han")]
    rest = [part for part in parts if part not in chinese_first]
    return "+".join(chinese_first + rest)


def _preprocess_for_tesseract(image: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(image)
    width, height = gray.size
    scale = 2 if max(width, height) < 1800 else 1
    if scale > 1:
        gray = gray.resize((width * scale, height * scale), Image.Resampling.LANCZOS)

    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(1.6)
    return gray.point(lambda pixel: 255 if pixel > 170 else 0, mode="1")


def _maybe_save_debug_image(image: Image.Image) -> None:
    debug_path = os.getenv("QUICKCROP_DEBUG_IMAGE")
    if not debug_path:
        return

    image.save(debug_path, "PNG")


def _recognize_with_openai(image: Image.Image) -> OcrResult:
    api_key = os.environ["OPENAI_API_KEY"]
    model = os.getenv("QUICKCROP_OPENAI_MODEL", "gpt-4.1-mini")
    detail = os.getenv("QUICKCROP_OPENAI_DETAIL", "high")
    data_url = _image_to_data_url(image)
    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": OCR_PROMPT},
                    {"type": "input_image", "image_url": data_url, "detail": detail},
                ],
            }
        ],
        "temperature": 0,
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
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
        raise OcrError("received invalid JSON from OpenAI") from exc

    text = _extract_response_text(parsed).strip()
    return OcrResult(text=text or "[NO_TEXT_DETECTED]", backend="openai")


def _image_to_data_url(image: Image.Image) -> str:
    rgb = image.convert("RGB")
    rgb.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    rgb.save(buffer, format="JPEG", quality=92, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _extract_response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text

    chunks: list[str] = []
    _walk_response(payload.get("output"), chunks)
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
