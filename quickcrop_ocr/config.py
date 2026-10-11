from __future__ import annotations

from dataclasses import dataclass, field

from .layout import DEFAULT_OUTPUT_FORMAT, TEXT_LAYOUTS


@dataclass(frozen=True)
class RuntimeConfig:
    api_key: str = field(repr=False)
    model: str
    qwen_region: str
    output_format: str


DEFAULT_QWEN_MODEL = "qwen3-vl-plus"
QWEN_REGIONS = {
    "beijing": "China / Beijing",
    "international": "International / Singapore",
}
_SETUP_FIELDS = (
    ("api_key", "API key"),
    ("model", "Vision model"),
    ("qwen_region", "Key region"),
    ("output_format", "Text layout"),
)


class SetupCancelled(Exception):
    """The user chose to leave setup without starting the app."""


class _GoBack(Exception):
    pass


def prompt_runtime_config() -> RuntimeConfig:
    print("\nQuickCrop OCR | Qwen")
    print("--------------------")
    print("Enter keeps the shown setting. B goes back. Q quits.")
    print("Settings apply to this run only; nothing is saved.")
    print()

    values = {
        "api_key": "",
        "model": DEFAULT_QWEN_MODEL,
        "qwen_region": "beijing",
        "output_format": DEFAULT_OUTPUT_FORMAT,
    }
    step = 0
    while step < len(_SETUP_FIELDS):
        try:
            values[_SETUP_FIELDS[step][0]] = _prompt_step(step, values)
        except _GoBack:
            if step:
                step -= 1
            else:
                print("Already at the first step. Enter your key, or Q to quit.\n")
        else:
            step += 1

    while True:
        _print_summary(values)
        try:
            answer = _read_answer("Enter to start | 1-4 to edit | B to go back | Q to quit: ")
        except _GoBack:
            step = len(_SETUP_FIELDS) - 1
        else:
            if not answer:
                print("Starting QuickCrop OCR...\n", flush=True)
                return RuntimeConfig(**values)
            step = _choice_index(answer, len(_SETUP_FIELDS))
            if step is None:
                print("Enter starts the app; choose 1-4 to change a setting.\n")
                continue
        try:
            values[_SETUP_FIELDS[step][0]] = _prompt_step(step, values)
        except _GoBack:
            pass


def _prompt_step(step: int, values: dict[str, str]) -> str:
    field, title = _SETUP_FIELDS[step]
    print(f"[{step + 1}/{len(_SETUP_FIELDS)}] {title}")
    current = values[field]
    if field == "api_key":
        return _prompt_api_key(current)
    if field == "model":
        return _prompt_model(current)
    if field == "qwen_region":
        print("Use the region where this API key was created.")
        return _prompt_choice(list(QWEN_REGIONS.items()), default=current)
    return _prompt_choice(
        [(value, layout.label) for value, layout in TEXT_LAYOUTS.items()],
        default=current,
        descriptions={value: layout.description for value, layout in TEXT_LAYOUTS.items()},
    )


def _print_summary(values: dict[str, str]) -> None:
    print("Ready to start")
    print("--------------")
    print("1. API key     : Entered (not checked online)")
    print(f"2. Vision model: {values['model']}")
    print(f"3. Key region  : {QWEN_REGIONS[values['qwen_region']]}")
    print(f"4. Text layout : {TEXT_LAYOUTS[values['output_format']].label}")
    print("Punctuation: preserved in every layout.\n")


def _read_answer(prompt: str) -> str:
    answer = input(prompt).strip()
    print()
    if answer.lower() in {"q", "quit"}:
        raise SetupCancelled
    if answer.lower() in {"b", "back"}:
        raise _GoBack
    return answer


def _choice_index(answer: str, count: int) -> int | None:
    try:
        index = int(answer)
    except ValueError:
        return None
    return index - 1 if 1 <= index <= count else None


def _prompt_choice(
    options: list[tuple[str, str]],
    *,
    default: str,
    descriptions: dict[str, str] | None = None,
) -> str:
    default_index = next(index for index, (value, _) in enumerate(options, start=1) if value == default)

    for index, (value, label) in enumerate(options, start=1):
        suffix = " [Enter]" if index == default_index else ""
        print(f"  {index}. {label}{suffix}")
        if descriptions:
            print(f"     {descriptions[value]}")
    print()
    while True:
        answer = _read_answer(f"Choose 1-{len(options)} [{default_index}] (B back, Q quit): ")
        if not answer:
            return default
        index = _choice_index(answer, len(options))
        if index is not None:
            return options[index][0]
        print(f"Invalid choice. Enter a number from 1 to {len(options)}, or press Enter for {default_index}.")


def _prompt_api_key(current: str = "") -> str:
    hint = "Enter keeps the entered key; " if current else ""
    while True:
        api_key = _read_answer(f"Qwen/DashScope API key (visible, not saved; {hint}Q quits): ")
        if not api_key and current:
            return current
        if api_key and api_key.isprintable() and not any(c.isspace() for c in api_key):
            return api_key
        if not api_key:
            print("API key is required.")
        else:
            print("Paste only the API key, without spaces or control characters.")


def _prompt_model(current: str = DEFAULT_QWEN_MODEL) -> str:
    while True:
        model = _read_answer(f"Qwen vision model [{current}] (B back, Q quit): ")
        if not model:
            return current
        if model.isprintable() and not any(c.isspace() for c in model):
            return model
        print("Enter a vision model ID without spaces, or press Enter to keep the shown model.")
