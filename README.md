# QuickCrop OCR

QuickCrop OCR is a lightweight Windows desktop utility for copying text from any visible screen region.

Press a global shortcut, drag over text, and the recognized text is copied to the clipboard for immediate pasting.

## Features

- Global hotkey: `Ctrl+Shift+X`
- Full-screen crop overlay with drag selection
- Exact region screenshot capture
- Local OCR with Tesseract
- Simplified Chinese + English OCR by default
- Optional OpenAI vision backend for higher-accuracy OCR
- Automatic clipboard copy
- Small success/failure notifications
- No permanent screenshot storage

## Requirements

- Windows
- Python 3.10+
- Tesseract OCR for local OCR

The app auto-detects Tesseract at:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

If Tesseract is installed somewhere else, set `QUICKCROP_TESSERACT_EXE`.

## Installation

Clone the repo, then install Python dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Install Tesseract for Windows from the UB Mannheim build:

```text
https://github.com/UB-Mannheim/tesseract/wiki
```

During installation, include the languages you need. For Chinese + English, make sure these are available:

```text
chi_sim
eng
```

You can verify with:

```cmd
"C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs
```

## Run

From PowerShell:

```powershell
cd path\to\QuickCrop-OCR
$env:QUICKCROP_OCR_MODE = "fast"
$env:QUICKCROP_TESSERACT_LANG = "chi_sim+eng"
$env:QUICKCROP_TESSERACT_PSM = "6"
python -m quickcrop_ocr
```

From cmd.exe:

```cmd
cd path\to\QuickCrop-OCR
set QUICKCROP_OCR_MODE=fast
set QUICKCROP_TESSERACT_LANG=chi_sim+eng
set QUICKCROP_TESSERACT_PSM=6
python -m quickcrop_ocr
```

Keep the terminal open while the app is running. Press `Ctrl+C` in the terminal to quit.

## Usage

1. Press `Ctrl+Shift+X`.
2. Drag over the visible text region.
3. Release the mouse.
4. Paste anywhere with `Ctrl+V`.

Press `Esc` during selection to cancel.

## OCR Modes

`fast` uses local Tesseract OCR:

```cmd
set QUICKCROP_OCR_MODE=fast
```

`accurate` uses OpenAI vision OCR:

```cmd
set QUICKCROP_OCR_MODE=accurate
set OPENAI_API_KEY=sk-...
```

`auto` tries Tesseract first, then OpenAI if available:

```cmd
set QUICKCROP_OCR_MODE=auto
```

The OpenAI backend sends a base64 image data URL to the Responses API, following the official OpenAI image input pattern:

```text
https://platform.openai.com/docs/guides/images-vision
```

Optional OpenAI settings:

```cmd
set QUICKCROP_OPENAI_MODEL=gpt-4.1-mini
set QUICKCROP_OPENAI_DETAIL=high
```

## Tesseract Settings

Default language:

```cmd
set QUICKCROP_TESSERACT_LANG=chi_sim+eng
```

`chi_sim+eng` is preferred over `eng+chi_sim` because Tesseract language order affects mixed Chinese/English recognition.

Page segmentation mode:

```cmd
set QUICKCROP_TESSERACT_PSM=6
```

Useful values:

- `6`: one block of text
- `7`: one single text line
- `11`: sparse text

## Troubleshooting

If English works but Chinese does not:

- Use `chi_sim+eng`, not `eng+chi_sim`.
- Crop slightly wider and taller than the visible text.
- Avoid tiny or heavily anti-aliased characters when possible.
- Confirm `chi_sim` appears in `tesseract --list-langs`.

If OCR returns no text, save the processed image that Tesseract receives:

```cmd
set QUICKCROP_DEBUG_IMAGE=%TEMP%\quickcrop-debug.png
python -m quickcrop_ocr
```

After a capture, open:

```text
%TEMP%\quickcrop-debug.png
```

If `tesseract` is not on `PATH`, either install it to the default location or set:

```cmd
set QUICKCROP_TESSERACT_EXE=C:\Program Files\Tesseract-OCR\tesseract.exe
```

## Privacy

- Screenshots are held in memory by default.
- Tesseract OCR runs locally.
- Temporary files used for Tesseract are deleted immediately after OCR.
- Clipboard content remains local.
- OpenAI mode sends the selected crop to the OpenAI API.

## Project Status

This is a personal-use MVP. It is currently optimized for Windows and local Chinese/English OCR through Tesseract.
