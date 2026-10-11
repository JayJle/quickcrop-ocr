import subprocess
import sys
import unittest
from pathlib import Path


class CliEntryPointTests(unittest.TestCase):
    def run_cli(self, answers):
        return subprocess.run(
            [sys.executable, "-m", "quickcrop_ocr"],
            input="\n".join(answers) + "\n",
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
            timeout=10,
        )

    def assert_canceled_cleanly(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("Setup canceled.", result.stdout)
        self.assertNotIn("Starting QuickCrop OCR", result.stdout)

    def test_quit_at_key_prompt(self):
        self.assert_canceled_cleanly(self.run_cli(["q"]))

    def test_real_input_retry_back_edit_and_quit(self):
        result = self.run_cli(["test-only-key", "", "bad", "2", "b", "", "1", "4", "3", "q"])
        self.assert_canceled_cleanly(result)
        self.assertIn("Invalid choice.", result.stdout)
        self.assertIn("3. Key region  : International / Singapore", result.stdout)
        self.assertIn("4. Text layout : Natural paragraphs", result.stdout)
        self.assertNotIn("test-only-key", result.stdout)

    def test_end_of_input_at_confirmation_does_not_start_app(self):
        result = self.run_cli(["test-only-key", "", "", ""])
        self.assert_canceled_cleanly(result)
        self.assertIn("Ready to start", result.stdout)
        self.assertIn("4. Text layout : Single line", result.stdout)


if __name__ == "__main__":
    unittest.main()
