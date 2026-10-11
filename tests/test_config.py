import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from quickcrop_ocr.config import DEFAULT_QWEN_MODEL, RuntimeConfig, SetupCancelled, prompt_runtime_config


def run_setup(answers):
    output = io.StringIO()
    with redirect_stdout(output), patch("builtins.input", side_effect=answers) as read_input:
        config = prompt_runtime_config()
    return config, output.getvalue(), read_input


class RuntimeConfigTests(unittest.TestCase):
    def test_defaults_skip_provider_selection(self):
        output = io.StringIO()
        with redirect_stdout(output), patch(
            "builtins.input", side_effect=["test-only-key", "", "", "", ""]
        ) as read_input:
            config = prompt_runtime_config()

        self.assertEqual(config.api_key, "test-only-key")
        self.assertEqual(config.model, DEFAULT_QWEN_MODEL)
        self.assertEqual(config.qwen_region, "beijing")
        self.assertEqual(config.output_format, "single_line")
        self.assertEqual(read_input.call_count, 5)
        self.assertIn("Qwen/DashScope API key", read_input.call_args_list[0].args[0])
        self.assertIn("visible, not saved", read_input.call_args_list[0].args[0])
        self.assertNotIn("OCR provider", output.getvalue())
        self.assertFalse(hasattr(config, "provider"))
        for step in range(1, 5):
            self.assertIn(f"[{step}/4]", output.getvalue())

    def test_custom_model_region_and_format(self):
        with redirect_stdout(io.StringIO()), patch(
            "builtins.input",
            side_effect=[" test-only-key ", " qwen-vl-test-model ", "2", "1", ""],
        ):
            config = prompt_runtime_config()

        self.assertEqual(config.api_key, "test-only-key")
        self.assertEqual(config.model, "qwen-vl-test-model")
        self.assertEqual(config.qwen_region, "international")
        self.assertEqual(config.output_format, "preserve")

    def test_empty_api_key_is_prompted_again(self):
        output = io.StringIO()
        with redirect_stdout(output), patch(
            "builtins.input", side_effect=["", "  ", "test-only-key", "", "", "", ""]
        ):
            config = prompt_runtime_config()

        self.assertEqual(config.api_key, "test-only-key")
        self.assertEqual(output.getvalue().count("API key is required."), 2)

    def test_invalid_choices_are_prompted_again(self):
        output = io.StringIO()
        with redirect_stdout(output), patch(
            "builtins.input",
            side_effect=["test-only-key", "", "3", "2", "bad", "1", ""],
        ):
            config = prompt_runtime_config()

        self.assertEqual(config.qwen_region, "international")
        self.assertEqual(config.output_format, "preserve")
        self.assertEqual(output.getvalue().count("Invalid choice."), 2)
        self.assertEqual(output.getvalue().count("1. China / Beijing"), 1)
        self.assertEqual(output.getvalue().count("1. Preserve image layout"), 1)

    def test_each_run_requests_a_new_key(self):
        with redirect_stdout(io.StringIO()), patch(
            "builtins.input",
            side_effect=["test-only-first", "", "", "", "", "test-only-second", "", "", "", ""],
        ) as read_input:
            first = prompt_runtime_config()
            second = prompt_runtime_config()

        self.assertEqual(first.api_key, "test-only-first")
        self.assertEqual(second.api_key, "test-only-second")
        self.assertEqual(read_input.call_count, 10)
        self.assertNotIn("keeps the entered key", read_input.call_args_list[5].args[0])

    def test_three_layout_choices_and_no_punctuation_prompt(self):
        output = io.StringIO()
        with redirect_stdout(output), patch(
            "builtins.input", side_effect=["test-only-key", "", "", "3", ""]
        ) as read_input:
            config = prompt_runtime_config()
        self.assertEqual(config.output_format, "paragraphs")
        self.assertEqual(read_input.call_count, 5)
        self.assertIn("1. Preserve image layout", output.getvalue())
        self.assertIn("2. Single line [Enter]", output.getvalue())
        self.assertIn("3. Natural paragraphs", output.getvalue())
        self.assertIn("Keep original line breaks", output.getvalue())
        self.assertIn("Merge all lines", output.getvalue())
        self.assertIn("Merge wrapped lines", output.getvalue())
        self.assertIn("Punctuation: preserved", output.getvalue())
        for call in read_input.call_args_list:
            self.assertNotIn("punctuation", call.args[0].lower())

    def test_unusual_numeric_input_is_rejected_without_crashing(self):
        with redirect_stdout(io.StringIO()), patch(
            "builtins.input", side_effect=["test-only-key", "", "", "\u00b2", "4", "3", ""]
        ):
            self.assertEqual(prompt_runtime_config().output_format, "paragraphs")

    def test_config_repr_does_not_expose_key(self):
        config = RuntimeConfig("private-test-key", DEFAULT_QWEN_MODEL, "beijing", "single_line")
        self.assertNotIn("private-test-key", repr(config))

    def test_summary_and_prompts_do_not_repeat_the_key(self):
        config, output, read_input = run_setup(["private-test-key", "custom-model", "2", "3", ""])
        self.assertNotIn(config.api_key, output)
        for call in read_input.call_args_list:
            self.assertNotIn(config.api_key, call.args[0])
        self.assertIn("Entered (not checked online)", output)
        self.assertIn("custom-model", output)
        self.assertIn("3. Key region  : International / Singapore", output)
        self.assertIn("4. Text layout : Natural paragraphs", output)

    def test_back_keeps_previous_choice_as_enter_default(self):
        config, _, read_input = run_setup(["test-only-key", "custom-model", "2", " B ", "", "3", ""])
        self.assertEqual(config.qwen_region, "international")
        self.assertEqual(config.model, "custom-model")
        self.assertIn("[2]", read_input.call_args_list[4].args[0])

    def test_back_at_first_step_does_not_exit(self):
        config, output, _ = run_setup(["b", "test-only-key", "", "", "", ""])
        self.assertEqual(config.api_key, "test-only-key")
        self.assertIn("Already at the first step", output)

    def test_review_edits_only_selected_field(self):
        config, output, read_input = run_setup(["test-only-key", "", "", "", "4", "3", ""])
        self.assertEqual(config.output_format, "paragraphs")
        self.assertEqual(output.count("[1/4]"), 1)
        self.assertEqual(output.count("[4/4]"), 2)
        self.assertEqual(read_input.call_count, 7)

    def test_review_can_keep_then_replace_key_without_echoing_it(self):
        config, output, read_input = run_setup([
            "test-only-first", "", "", "", "1", "", "1", "test-only-second", "",
        ])
        self.assertEqual(config.api_key, "test-only-second")
        self.assertIn("keeps the entered key", read_input.call_args_list[5].args[0])
        self.assertNotIn("test-only-first", output)
        self.assertNotIn("test-only-second", output)

    def test_review_can_edit_model_and_region(self):
        config, _, _ = run_setup(["test-only-key", "", "", "", "2", "custom", "3", "2", ""])
        self.assertEqual(config.model, "custom")
        self.assertEqual(config.qwen_region, "international")

    def test_back_during_review_edit_keeps_the_current_value(self):
        config, _, _ = run_setup(["test-only-key", "", "", "3", "4", "back", ""])
        self.assertEqual(config.output_format, "paragraphs")

    def test_back_from_review_reopens_last_step(self):
        config, _, _ = run_setup(["test-only-key", "", "", "", "back", "1", ""])
        self.assertEqual(config.output_format, "preserve")

    def test_invalid_review_input_cannot_start_app(self):
        config, output, _ = run_setup(["test-only-key", "", "", "", "yes", "5", ""])
        self.assertEqual(config.output_format, "single_line")
        self.assertEqual(output.count("choose 1-4 to change a setting"), 2)
        self.assertEqual(output.count("Starting QuickCrop OCR..."), 1)

    def test_quit_is_supported_at_every_step_and_review(self):
        defaults = ["test-only-key", "", "", ""]
        for step in range(5):
            with self.subTest(step=step), redirect_stdout(io.StringIO()) as output, patch(
                "builtins.input", side_effect=defaults[:step] + [" Q "]
            ), self.assertRaises(SetupCancelled):
                prompt_runtime_config()
            self.assertNotIn("Starting QuickCrop OCR", output.getvalue())

    def test_bad_key_input_is_not_repeated_in_the_error(self):
        config, output, _ = run_setup(["key with spaces", "\x1bsecret", "good-key", "", "", "", ""])
        self.assertEqual(config.api_key, "good-key")
        self.assertNotIn("key with spaces", output)
        self.assertNotIn("\x1bsecret", output)
        self.assertEqual(output.count("Paste only the API key"), 2)

    def test_model_rejects_whitespace_and_terminal_control_characters(self):
        config, output, _ = run_setup(["test-only-key", "bad model", "\x1bmodel", "", "", "", ""])
        self.assertEqual(config.model, DEFAULT_QWEN_MODEL)
        self.assertEqual(output.count("Enter a vision model ID"), 2)


if __name__ == "__main__":
    unittest.main()
