from __future__ import annotations

from dataclasses import dataclass


DEFAULT_OUTPUT_FORMAT = "single_line"
NO_TEXT_MARKER = "[NO_TEXT_DETECTED]"

_PRESERVE_LAYOUT = """Preserve the image's line breaks, paragraph breaks, and list structure.
Preserve code indentation and table rows using the original tabs or spaces as closely as possible.
Do not add Markdown fences, headings, or list markers that are not in the image."""


@dataclass(frozen=True)
class TextLayout:
    label: str
    instruction: str
    description: str


TEXT_LAYOUTS = {
    "preserve": TextLayout(
        "Preserve image layout", _PRESERVE_LAYOUT,
        "Keep original line breaks, paragraphs, lists, and indentation.",
    ),
    # The same faithful transcription is flattened locally, without another request.
    "single_line": TextLayout(
        "Single line", _PRESERVE_LAYOUT,
        "Merge all lines into one line of text.",
    ),
    "paragraphs": TextLayout(
        "Natural paragraphs",
        """Use the visual layout of the image to distinguish line wrapping from paragraph breaks.
Merge lines within the same paragraph only when the breaks are caused by the image's limited width.
Keep actual paragraph breaks as blank lines. Keep headings on separate lines.
Keep each list item on its own line with its original marker and indentation; merge only wrapped lines within an item.
Keep code indentation, code line breaks, and table rows. Do not merge separate columns.
Keep every original punctuation mark, including hyphens at line endings; do not dehyphenate or rewrite words.
When joining wrapped lines, retain word boundaries in English and do not insert spaces between continuous Chinese characters.
Do not add Markdown formatting. If a line break is ambiguous, preserve it rather than guessing.""",
        "Merge wrapped lines; keep separate paragraphs and list items.",
    ),
}


def get_layout(output_format: str) -> TextLayout:
    try:
        return TEXT_LAYOUTS[output_format]
    except KeyError as exc:
        raise ValueError(f"output format must be one of: {', '.join(TEXT_LAYOUTS)}") from exc


def format_text(text: str, output_format: str) -> str:
    get_layout(output_format)
    if text.strip() == NO_TEXT_MARKER:
        return NO_TEXT_MARKER
    if output_format == "single_line":
        return " ".join(text.split())
    # Paragraph boundaries are decided from the image, never guessed again from text.
    return text
