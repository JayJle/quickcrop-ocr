# QuickCrop OCR

**English** | [简体中文](README.zh-CN.md)

QuickCrop OCR is a lightweight Windows desktop utility for copying text from a captured screen region.

Press a global shortcut, drag over text, and the recognized text is copied to the clipboard for immediate pasting.

## Features

- Global hotkey: `Ctrl+Shift+X`
- Frozen-screen crop overlay with drag selection
- Exact region screenshot capture
- Qwen vision OCR through Alibaba Cloud Model Studio / DashScope
- Recognition of Chinese, English, mixed text, UI screenshots, and subtitles
- Three text layouts: preserve image layout, single line, or natural paragraphs
- Guided terminal setup with back navigation and a settings review before starting
- Automatic clipboard copy
- Persistent progress window with elapsed time, retry status, and cancellation
- Clipboard backup/recovery and a Copy again button
- Incomplete or rejected model answers are not copied
- No permanent screenshot storage

## Qwen OCR

QuickCrop OCR uses Qwen vision models exclusively. There is no provider selection or automatic fallback to another service.

OCR requires internet access and a Qwen/DashScope API key. Requests send the selected crop to the chosen Qwen region and may incur API charges.

Qwen's visual understanding docs describe passing image URLs or base64 data URLs to the DashScope multimodal generation endpoint:

```text
https://www.alibabacloud.com/help/en/model-studio/vision/
```

## Requirements

- Windows
- Python 3.10+
- A Qwen/DashScope API key with access to the selected vision model

Tesseract, OpenAI, and Gemini are not used or required. The terminal menus and prompts are in English.

## Installation

Clone [JayJle/quickcrop-ocr](https://github.com/JayJle/quickcrop-ocr), then install Python dependencies. **Choose the commands for your terminal; do not mix the path styles.**

- **PowerShell**: the prompt usually starts with `PS`, for example `PS C:\quickcrop-ocr>`.
- **Command Prompt (CMD)**: the prompt usually looks like `C:\quickcrop-ocr>`.
- **Git Bash**: the prompt often contains `MINGW64` or `MINGW32`, with a `$` before commands. Use forward slashes `/`, not the unquoted backslashes `\` in the PowerShell/CMD examples.

Copy only the commands, not the prompt symbols (`$`, `>`, or `(base)`). All examples below use Windows Python, not WSL/Linux Python.

### PowerShell / Command Prompt (CMD)

```powershell
git clone https://github.com/JayJle/quickcrop-ocr.git
cd quickcrop-ocr
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Git Bash

```bash
git clone https://github.com/JayJle/quickcrop-ocr.git
cd quickcrop-ocr
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

If you already cloned the repo, open its folder and skip `git clone` and `cd quickcrop-ocr`. If `.venv` was already created successfully, skip `python -m venv .venv` too. Both sets of commands use the virtual environment directly; activation is not needed, even if your prompt shows `(base)`.

## Run

From the cloned project folder, use the command for your terminal.

**PowerShell / Command Prompt (CMD):**

```powershell
.\.venv\Scripts\python.exe -m quickcrop_ocr
```

**Git Bash:**

```bash
./.venv/Scripts/python.exe -m quickcrop_ocr
```

If you already installed the dependencies in your active Python or Conda environment, `python -m quickcrop_ocr` works as well.

The terminal walks through four settings every run:

```text
QuickCrop OCR | Qwen
--------------------
Enter keeps the shown setting. B goes back. Q quits.
Settings apply to this run only; nothing is saved.

[1/4] API key
Qwen/DashScope API key (visible, not saved; Q quits):

[2/4] Vision model
Qwen vision model [qwen3-vl-plus] (B back, Q quit):

[3/4] Key region
Use the region where this API key was created.
  1. China / Beijing [Enter]
  2. International / Singapore

Choose 1-2 [1] (B back, Q quit):

[4/4] Text layout
  1. Preserve image layout
     Keep original line breaks, paragraphs, lists, and indentation.
  2. Single line [Enter]
     Merge all lines into one line of text.
  3. Natural paragraphs
     Merge wrapped lines; keep separate paragraphs and list items.

Choose 1-3 [2] (B back, Q quit):

Ready to start
--------------
1. API key     : Entered (not checked online)
2. Vision model: qwen3-vl-plus
3. Key region  : China / Beijing
4. Text layout : Single line
Punctuation: preserved in every layout.

Enter to start | 1-4 to edit | B to go back | Q to quit:
```

API keys are shown while typing/pasting in the terminal and are not saved by the app. The review never repeats the key, although the original visible input can remain in terminal scrollback. Setup does not make a network request or verify the key with Qwen.

After entering your key, press Enter at each remaining prompt, including the final review, to use `qwen3-vl-plus`, Beijing, and single-line output. Settings and keys are requested again on every run.

- Enter `B` during setup to revisit the previous step. Earlier choices stay selected for this run.
- At the review, enter `1` through `4` to edit just that setting, then return to the review. `B` reopens text layout; `B` while editing returns to the review without changing that setting.
- On revisiting the API key, Enter keeps the key already entered for this run. On a fresh run, a key is always required.
- Enter `Q` or press `Ctrl+C` to leave setup without starting OCR. Invalid entries are re-prompted without repeating the full option list.

Keep the terminal open while the app is running. Messages are labeled `[Ready]`, `[OCR]`, `[Busy]`, `[Status]`, or `[Error]`. Press `Ctrl+C` in the terminal to quit; during OCR, use **Cancel** in the status window to cancel only that request.

## Usage

1. Press `Ctrl+Shift+X` to freeze the current desktop locally.
2. Drag over the text region in the frozen image.
3. Release the mouse.
4. Paste anywhere with `Ctrl+V`.

Press `Esc` during selection to cancel.

The progress window stays open while OCR runs. It shows elapsed time and retry status; **Cancel** stops waiting and prevents any late result from being copied. Pressing `Ctrl+Shift+X` while processing reopens this window instead of starting another capture.

After recognition, **Copy again** copies the most recent successful OCR result without making another API request. The result stays in memory until it is replaced by another successful result or the app exits. Closing the status window hides it; the next operation displays it again.

## Request Safety

- OCR has a **30-second total budget**, starting after selection. Each socket operation is capped at 20 seconds or the remaining budget, whichever is shorter.
- Network failures and HTTP 408, 429, 500, 502, 503, and 504 are retried up to three attempts within that same budget. Server `Retry-After` delays are respected without extending the budget. Authentication errors are not retried.
- Cancellation and timeout discard late results and stop further retries. A request already sent to Qwen may still complete and incur charges. A blocked socket can finish in the background; a new request waits for that connection slot, with its own visible status and time budget.
- Only a completed Qwen answer is accepted. Truncated answers, refusals, malformed responses, and empty answers produce distinct errors instead of being copied or labeled as an image with no text. An explicit `[NO_TEXT_DETECTED]` answer is treated as no readable text.

Completion checks follow the [DashScope response format](https://help.aliyun.com/en/model-studio/qwen-api-via-dashscope). They detect API-reported truncation, not transcription mistakes or omissions in a normally completed answer.

## Clipboard Safety

Before replacing clipboard contents, the app allocates the new text, locks the clipboard, and attempts to back up readable formats. Allocation or lock failures leave the clipboard unchanged. Unreadable, unsupported, or nonduplicable formats are skipped during backup, so they do not block normal copying. A successful copy replaces the old clipboard contents with the OCR text.

If writing fails, the app attempts to restore the available backup while still holding the lock. Recovery is **best-effort**: skipped formats cannot be restored, and Windows may also reject recovery writes. Partial recovery is reported explicitly, never described as a full restoration. Transient copy failures are retried up to three times, but incomplete recovery is not automatically retried. The OCR result remains in memory for **Copy again** if copying fails.

## Prompted Settings

Qwen model:

- Default: `qwen3-vl-plus`
- You can enter another Qwen vision model available to your API key in the selected region. A text-only model cannot process screenshots.

Qwen region:

- `China / Beijing`: uses `https://dashscope.aliyuncs.com`
- `International / Singapore`: uses `https://dashscope-intl.aliyuncs.com`

Choose the region where your Qwen/DashScope API key was created. A correct key can still fail as invalid if it is sent to the wrong region endpoint.

Text layout (all three modes retain punctuation):

- `preserve` / **Preserve image layout**: ask Qwen to preserve the image's line breaks, paragraphs, lists, code indentation, and table rows. Copy its response without trimming whitespace. This is plain text, not a reproduction of fonts, colors, or exact pixel positions.
- `single_line` / **Single line** (default): use the same transcription instructions, then collapse whitespace locally into one line, keeping all non-whitespace characters. Existing runs of spaces and tabs are also collapsed.
- `paragraphs` / **Natural paragraphs**: ask Qwen to merge lines wrapped only because of image width, while retaining real paragraph breaks, headings, separate list items, code, and table rows. Ambiguous line breaks should be retained. The returned paragraphs are copied without a second text-reflow pass.

Natural-paragraph detection happens in the same image-recognition request; there is no extra formatting API call. The app does not use punctuation heuristics to guess paragraph boundaries from already transcribed text. Models can still misjudge layout, especially in dense columns and complex lists; choose **Preserve image layout** when exact line structure matters.

There is no punctuation-removal setting. All modes ask Qwen to retain original punctuation, symbols, list markers, and line-ending hyphens. Local formatting neither deletes punctuation nor inserts extra spaces after it. Model transcription errors are still possible.

For example, choose **Natural paragraphs** to request this transformation:

```text
Image:
This sentence wraps because
the column is narrow.

- A separate list item.

Requested output:
This sentence wraps because the column is narrow.

- A separate list item.
```

## Troubleshooting

If Git Bash reports `bash: ..venvScriptspython.exe: command not found`, a PowerShell/CMD path was pasted into Bash. Bash treated the unquoted backslashes as escape characters. From the project folder, use these commands instead:

```bash
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe -m quickcrop_ocr
```

This error alone does not mean virtual-environment creation failed. You do not need to recreate an existing `.venv` or activate it.

If the app says the API key is invalid, first check that the selected region matches the region where you created the key, then check for copy/paste errors or a revoked key.

If OCR is slow:

- Crop only the text area you need.
- Avoid selecting huge screen regions.
- Check the progress window for retry messages, or cancel and try a smaller crop.

If OCR is inaccurate:

- Crop slightly wider and taller than the visible text.
- Make sure the selected image is clear enough for a human to read.

## Known Limitations

- Capture-protected windows may appear black in the snapshot. This app does not bypass screen-capture protection; OCR cannot recover content missing from the captured image.
- Qwen can misread characters, punctuation, or paragraph boundaries. Preserve image layout retains the returned plain-text structure, not the image's fonts or styling.
- Crops are resized to fit within 1800 by 1800 pixels and encoded as JPEG before upload. Very large selections can make small text harder to recognize; crop tightly around the text you need.
- Cancellation stops waiting and copying, but cannot withdraw a request already sent to Qwen. Clipboard recovery is best-effort if Windows rejects a write or restore.

## Privacy

- The full desktop snapshot stays local in memory and is released after selection or cancellation.
- The selected crop is sent only to Qwen through the selected DashScope region.
- Clipboard content remains local after OCR returns.
- Clipboard backups and the last OCR result are kept in memory only, not in logs or files.
- No screenshot files are saved permanently by default.

## Project Status

This is a personal-use MVP optimized for quick hosted vision OCR on Windows.

## Tests

Run the offline regression tests from the project folder.

**PowerShell / Command Prompt (CMD):**

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

**Git Bash:**

```bash
./.venv/Scripts/python.exe -m unittest discover -v
```

With an already configured active Python environment, use `python -m unittest discover -v` instead. The tests do not need a real API key or make paid OCR requests.

The tests use synthetic images, mocked API responses, and a simulated clipboard. Windows-only memory tests verify Unicode allocation and duplication without reading or changing the system clipboard. Coverage includes setup navigation and review, invalid input, key redaction, real CLI entry-point cancellation, all three layout choices, punctuation preservation, request prompt routing, truncated/rejected answers, cancellation, total deadlines, early timer wakeups, HTTP retries, late responses, clipboard recovery, hotkey lifecycle, and frozen-image cropping across negative monitor coordinates. Layout tests verify instructions and response handling, not the model's accuracy on real images. A live capture still needs to be checked with your own Qwen key and desktop.
