from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeConfig:
    provider: str
    api_key: str
    model: str
    qwen_region: str | None
    output_format: str
    space_after_punctuation: bool


PROVIDER_DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "qwen": "qwen3-vl-plus",
}


def prompt_runtime_config() -> RuntimeConfig:
    print("QuickCrop OCR")
    print()

    provider = _prompt_choice(
        "OCR provider",
        [
            ("gemini", "Gemini"),
            ("qwen", "Qwen"),
        ],
        default="gemini",
    )
    api_key = _prompt_api_key(provider)
    model = _prompt_model(provider)
    qwen_region = _prompt_qwen_region() if provider == "qwen" else None
    output_format = _prompt_choice(
        "Output format",
        [
            ("preserve", "Preserve layout"),
            ("single_line", "Single line"),
        ],
        default="preserve",
    )
    spacing = _prompt_choice(
        "Punctuation spacing",
        [
            ("yes", "Add spaces after punctuation"),
            ("no", "Keep OCR output as-is"),
        ],
        default="yes",
    )

    print()
    print("Starting QuickCrop OCR...")
    print()

    return RuntimeConfig(
        provider=provider,
        api_key=api_key,
        model=model,
        qwen_region=qwen_region,
        output_format=output_format,
        space_after_punctuation=spacing == "yes",
    )


def _prompt_choice(
    title: str,
    options: list[tuple[str, str]],
    *,
    default: str,
) -> str:
    default_index = next(index for index, (value, _) in enumerate(options, start=1) if value == default)

    while True:
        print(f"{title}:")
        for index, (_, label) in enumerate(options, start=1):
            suffix = " [default]" if index == default_index else ""
            print(f"{index}. {label}{suffix}")

        answer = input(f"Choose 1-{len(options)} [{default_index}]: ").strip()
        print()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][0]

        print("Invalid choice. Try again.")
        print()


def _prompt_api_key(provider: str) -> str:
    label = "Gemini" if provider == "gemini" else "Qwen/DashScope"
    while True:
        api_key = input(f"Enter {label} API key (visible, not saved): ").strip()
        if api_key:
            return api_key

        print("API key is required.")


def _prompt_model(provider: str) -> str:
    default = PROVIDER_DEFAULT_MODELS[provider]
    model = input(f"Model [{default}]: ").strip()
    print()
    return model or default


def _prompt_qwen_region() -> str:
    return _prompt_choice(
        "Qwen region",
        [
            ("beijing", "China / Beijing"),
            ("international", "International / Singapore"),
        ],
        default="beijing",
    )
