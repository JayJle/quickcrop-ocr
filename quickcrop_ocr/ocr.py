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


@dataclass(frozen=True)
class TesseractCandidate:
    text: str
    confidence: float
    variant: str


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
    speed = _tesseract_speed()
    psm_values = _tesseract_psm_values(os.getenv("QUICKCROP_TESSERACT_PSM", "6"), speed)
    variants = _preprocess_variants_for_tesseract(image, speed)
    candidates: list[TesseractCandidate] = []

    for psm in psm_values:
        for variant_name, processed in variants:
            candidates.append(
                _run_tesseract_candidate(tesseract_command, processed, lang, psm, f"{variant_name}-psm{psm}")
            )

    valid_candidates = [candidate for candidate in candidates if candidate.text.strip()]
    if not valid_candidates:
        return OcrResult(text="[NO_TEXT_DETECTED]", backend="tesseract")

    best = max(valid_candidates, key=_score_tesseract_candidate)
    return OcrResult(text=best.text.strip(), backend=f"tesseract:{best.variant}")


def _run_tesseract_candidate(
    tesseract_command: str,
    image: Image.Image,
    lang: str,
    psm: str,
    variant_name: str,
) -> TesseractCandidate:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        temp_path = tmp.name

    try:
        image.save(temp_path, "PNG")
        _maybe_save_debug_image(image, variant_name)
        process = subprocess.run(
            [tesseract_command, temp_path, "stdout", "-l", lang, "--psm", psm, "tsv"],
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

    text, confidence = _parse_tesseract_tsv(process.stdout)
    return TesseractCandidate(text=text, confidence=confidence, variant=variant_name)


def _score_tesseract_candidate(candidate: TesseractCandidate) -> float:
    compact_text = "".join(candidate.text.split())
    return candidate.confidence + min(len(compact_text), 120) * 0.08


def _normalize_tesseract_lang(lang: str) -> str:
    parts = [part.strip() for part in lang.replace(",", "+").split("+") if part.strip()]
    if not parts:
        return "chi_sim+eng"

    # Tesseract's language order affects recognition. Prefer Chinese first for mixed
    # Chinese/English captures, otherwise English can dominate short CJK text.
    chinese_first = [part for part in parts if part.startswith("chi_") or part.startswith("script\\Han")]
    rest = [part for part in parts if part not in chinese_first]
    return "+".join(chinese_first + rest)


def _tesseract_speed() -> str:
    speed = os.getenv("QUICKCROP_TESSERACT_SPEED", "fast").strip().lower()
    if speed not in {"fast", "balanced", "thorough"}:
        raise OcrError("QUICKCROP_TESSERACT_SPEED must be fast, balanced, or thorough")

    return speed


def _tesseract_psm_values(psm: str, speed: str) -> list[str]:
    normalized = psm.strip().lower()
    if normalized == "auto":
        if speed == "fast":
            return ["6"]
        if speed == "balanced":
            return ["6"]
        return ["6", "11"]

    return [value.strip() for value in normalized.replace(",", "+").split("+") if value.strip()]


def _preprocess_variants_for_tesseract(image: Image.Image, speed: str) -> list[tuple[str, Image.Image]]:
    mode = os.getenv("QUICKCROP_TESSERACT_PREPROCESS", "fast").strip().lower()
    if mode not in {"fast", "auto", "color", "gray", "binary", "invert"}:
        raise OcrError("QUICKCROP_TESSERACT_PREPROCESS must be fast, auto, color, gray, binary, or invert")

    if mode == "fast":
        return [("binary170", _prepare_binary(image, threshold=170))]
    if mode == "color":
        return [("color", _upscale_for_tesseract(image.convert("RGB")))]
    if mode == "gray":
        return [("gray", _prepare_gray(image))]
    if mode == "binary":
        return [("binary", _prepare_binary(image, threshold=170))]
    if mode == "invert":
        return [("invert", _prepare_inverted_binary(image))]

    if speed == "fast":
        return [("binary170", _prepare_binary(image, threshold=170))]
    if speed == "balanced":
        return [
            ("gray", _prepare_gray(image)),
            ("binary170", _prepare_binary(image, threshold=170)),
        ]

    return [
        ("color", _upscale_for_tesseract(image.convert("RGB"))),
        ("gray", _prepare_gray(image)),
        ("binary170", _prepare_binary(image, threshold=170)),
        ("binary130", _prepare_binary(image, threshold=130)),
        ("invert", _prepare_inverted_binary(image)),
    ]


def _upscale_for_tesseract(image: Image.Image) -> Image.Image:
    width, height = image.size
    scale = 2 if max(width, height) < 1800 else 1
    if scale == 1:
        return image

    return image.resize((width * scale, height * scale), Image.Resampling.LANCZOS)


def _prepare_gray(image: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(image)
    gray = _upscale_for_tesseract(gray)
    gray = ImageOps.autocontrast(gray)
    return ImageEnhance.Contrast(gray).enhance(1.35)


def _prepare_binary(image: Image.Image, *, threshold: int) -> Image.Image:
    gray = ImageOps.grayscale(image)
    gray = _upscale_for_tesseract(gray)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(1.6)
    return gray.point(lambda pixel: 255 if pixel > threshold else 0, mode="1")


def _prepare_inverted_binary(image: Image.Image) -> Image.Image:
    gray = ImageOps.invert(ImageOps.grayscale(image))
    gray = _upscale_for_tesseract(gray)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(1.6)
    return gray.point(lambda pixel: 255 if pixel > 150 else 0, mode="1")


def _maybe_save_debug_image(image: Image.Image, variant_name: str) -> None:
    debug_path = os.getenv("QUICKCROP_DEBUG_IMAGE")
    if not debug_path:
        return

    root, ext = os.path.splitext(debug_path)
    if not ext:
        ext = ".png"
    image.save(f"{root}-{variant_name}{ext}", "PNG")


def _parse_tesseract_tsv(tsv: str) -> tuple[str, float]:
    lines: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []

    for row in tsv.splitlines()[1:]:
        columns = row.split("\t")
        if len(columns) < 12:
            continue

        try:
            level = int(columns[0])
            block_num = int(columns[2])
            par_num = int(columns[3])
            line_num = int(columns[4])
            confidence = float(columns[10])
        except ValueError:
            continue

        text = columns[11].strip()
        if level != 5 or not text:
            continue

        lines.setdefault((block_num, par_num, line_num), []).append(text)
        if confidence >= 0:
            confidences.append(confidence)

    text_lines = [_join_tokens(tokens) for _, tokens in sorted(lines.items())]
    text = "\n".join(line for line in text_lines if line.strip())
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return text, confidence


def _join_tokens(tokens: list[str]) -> str:
    if not tokens:
        return ""

    output = tokens[0]
    for token in tokens[1:]:
        previous = output[-1] if output else ""
        current = token[0]
        if _is_cjk(previous) or _is_cjk(current):
            output += token
        else:
            output += f" {token}"
    return output


def _is_cjk(char: str) -> bool:
    if not char:
        return False

    code = ord(char)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
    )


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
