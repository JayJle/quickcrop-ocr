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

## OCR Providers

Tesseract is very fast for clean document-style text, but it struggles with mixed Chinese/English, stylized fonts, shadows, low contrast, and text over images.

QuickCrop OCR uses hosted vision models instead of local OCR preprocessing modes. This keeps the app simpler and usually improves accuracy on real screenshots. The tradeoff is that OCR requires internet access, uses API credits, and sends the selected crop to the selected provider.

Supported providers:

- Gemini
- Qwen through Alibaba Cloud Model Studio / DashScope

Gemini's image understanding docs describe passing inline image data to `generateContent`:

```text
https://ai.google.dev/gemini-api/docs/vision
```

Qwen's visual understanding docs describe passing image URLs or base64 data URLs to the DashScope multimodal generation endpoint:

```text
https://www.alibabacloud.com/help/en/model-studio/vision/
```

## Requirements

- Windows
- Python 3.10+
- A Gemini API key or a Qwen/DashScope API key

## Installation

Clone the repo, then install Python dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

Run the app:

```powershell
cd path\to\QuickCrop-OCR
python -m quickcrop_ocr
```

The terminal prompts for settings every run:

```text
OCR provider:
1. Gemini
2. Qwen

Enter API key:
Model [provider default]:

Qwen region:
1. China / Beijing
2. International / Singapore

Output format:
1. Preserve layout
2. Single line

Punctuation spacing:
1. Add spaces after punctuation
2. Keep OCR output as-is
```

API keys are shown while typing/pasting in the terminal and are not saved.

Keep the terminal open while the app is running. Press `Ctrl+C` in the terminal to quit.

## Usage

1. Press `Ctrl+Shift+X`.
2. Drag over the visible text region.
3. Release the mouse.
4. Paste anywhere with `Ctrl+V`.

Press `Esc` during selection to cancel.

## Prompted Settings

Provider:

- `Gemini`: default model `gemini-2.5-flash`
- `Qwen`: default model `qwen3-vl-plus`

Qwen region:

- `China / Beijing`: uses `https://dashscope.aliyuncs.com`
- `International / Singapore`: uses `https://dashscope-intl.aliyuncs.com`

Choose the region where your Qwen/DashScope API key was created. A correct key can still fail as invalid if it is sent to the wrong region endpoint.

Output format:

- `preserve`: keep line breaks, paragraphs, code indentation, and table-like layout as much as the selected provider returns them
- `single_line`: collapse the OCR result into one line

By default, QuickCrop OCR adds a space after punctuation when the next character is not already whitespace:

```text
Hello,world!Next sentence.
```

becomes:

```text
Hello, world! Next sentence.
```

You can disable this in the startup prompt.

## Troubleshooting

If the app says the API key is invalid, create a new key for the provider you selected.

If OCR is slow:

- Crop only the text area you need.
- Avoid selecting huge screen regions.
- Crop only the text area rather than a full screen.

If OCR is inaccurate:

- Crop slightly wider and taller than the visible text.
- Make sure the selected image is clear enough for a human to read.

## Privacy

- Screenshots are held in memory by default.
- The selected crop is sent to the selected OCR provider.
- Clipboard content remains local after OCR returns.
- No screenshot files are saved permanently by default.

## Project Status

This is a personal-use MVP optimized for quick hosted vision OCR on Windows.
