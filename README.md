# QuickCrop OCR

QuickCrop OCR is a lightweight Windows desktop utility for copying text from any visible screen region.

Press a global shortcut, drag over text, and the recognized text is copied to the clipboard for immediate pasting.

## Features

- Global hotkey: `Ctrl+Shift+X`
- Full-screen crop overlay with drag selection
- Exact region screenshot capture
- Gemini vision OCR through the Gemini API
- Stronger recognition for Chinese, English, mixed text, UI screenshots, subtitles, and decorative backgrounds
- Automatic clipboard copy
- Small success/failure notifications
- No permanent screenshot storage

## Why Gemini OCR

Tesseract is very fast for clean document-style text, but it struggles with mixed Chinese/English, stylized fonts, shadows, low contrast, and text over images.

QuickCrop OCR uses one Gemini vision pipeline instead of multiple local OCR modes. This keeps the app simpler and usually improves accuracy on real screenshots. The tradeoff is that OCR requires internet access, uses API credits, and sends the selected crop to Google Gemini.

Gemini's image understanding docs describe passing inline image data to `generateContent`:

```text
https://ai.google.dev/gemini-api/docs/vision
```

## Requirements

- Windows
- Python 3.10+
- A Gemini API key

## Installation

Clone the repo, then install Python dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

From PowerShell:

```powershell
cd path\to\QuickCrop-OCR
$env:GEMINI_API_KEY = "your-gemini-api-key"
python -m quickcrop_ocr
```

From cmd.exe:

```cmd
cd path\to\QuickCrop-OCR
set GEMINI_API_KEY=your-gemini-api-key
python -m quickcrop_ocr
```

Keep the terminal open while the app is running. Press `Ctrl+C` in the terminal to quit.

## Usage

1. Press `Ctrl+Shift+X`.
2. Drag over the visible text region.
3. Release the mouse.
4. Paste anywhere with `Ctrl+V`.

Press `Esc` during selection to cancel.

## Optional Settings

Default Gemini model:

```cmd
set QUICKCROP_GEMINI_MODEL=gemini-2.5-flash
```

Output format:

```cmd
set QUICKCROP_OUTPUT_FORMAT=preserve
```

Available values:

- `preserve`: keep line breaks, paragraphs, code indentation, and table-like layout as much as Gemini returns them
- `single_line`: collapse the OCR result into one line

By default, QuickCrop OCR adds a space after punctuation when the next character is not already whitespace:

```text
Hello,world!Next sentence.
```

becomes:

```text
Hello, world! Next sentence.
```

Disable it with:

```cmd
set QUICKCROP_SPACE_AFTER_PUNCTUATION=0
```

## Troubleshooting

If the app says `GEMINI_API_KEY is not set`, set your API key in the same terminal before starting the app.

If OCR is slow:

- Crop only the text area you need.
- Avoid selecting huge screen regions.
- Crop only the text area rather than a full screen.

If OCR is inaccurate:

- Crop slightly wider and taller than the visible text.
- Make sure the selected image is clear enough for a human to read.

## Privacy

- Screenshots are held in memory by default.
- The selected crop is sent to the Gemini API for OCR.
- Clipboard content remains local after OCR returns.
- No screenshot files are saved permanently by default.

## Project Status

This is a personal-use MVP optimized for quick Gemini-powered screenshot OCR on Windows.
