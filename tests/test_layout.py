import unittest

from quickcrop_ocr.layout import (
    DEFAULT_OUTPUT_FORMAT, NO_TEXT_MARKER, TEXT_LAYOUTS, format_text, get_layout,
)


class TextLayoutTests(unittest.TestCase):
    def test_only_three_modes_defaulting_to_single_line(self):
        self.assertEqual(list(TEXT_LAYOUTS), ["preserve", "single_line", "paragraphs"])
        self.assertEqual(DEFAULT_OUTPUT_FORMAT, "single_line")

    def test_preserve_is_exact_including_indent_and_trailing_newline(self):
        text = "    Heading:\r\n\t1. First item...\r\n\r\nSecond paragraph!\r\n"
        self.assertEqual(format_text(text, "preserve"), text)

    def test_single_line_changes_only_whitespace(self):
        text = "\u4f60\u597d\uff0c\u4e16\u754c\uff01\n3.14;2026-10-11\r\nhttps://example.test/a?q=1&x=2\tC++"
        output = format_text(text, "single_line")
        self.assertEqual(
            output,
            "\u4f60\u597d\uff0c\u4e16\u754c\uff01 3.14;2026-10-11 https://example.test/a?q=1&x=2 C++",
        )

    def test_natural_paragraphs_keeps_model_layout_without_guessing_again(self):
        text = "Heading\n\nA merged paragraph.\n\n- First item;\n- Second item!\n\n    code()\n"
        self.assertEqual(format_text(text, "paragraphs"), text)

    def test_all_modes_keep_every_non_whitespace_character(self):
        text = "\u201c\u4e2d\u6587\u201d\uff1a3.14\uff1b\nC++ = a_b / (x-y)?\n#1 @home!\u2026"
        original_characters = "".join(c for c in text if not c.isspace())
        for mode in TEXT_LAYOUTS:
            with self.subTest(mode=mode):
                output = format_text(text, mode)
                self.assertEqual("".join(c for c in output if not c.isspace()), original_characters)

    def test_no_text_marker_is_normalized_for_all_modes(self):
        for mode in TEXT_LAYOUTS:
            with self.subTest(mode=mode):
                self.assertEqual(format_text(f"  {NO_TEXT_MARKER}\n", mode), NO_TEXT_MARKER)

    def test_unknown_modes_fail_explicitly(self):
        for mode in ("", "no_punctuation", "invalid"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                format_text("text", mode)

    def test_natural_paragraph_instruction_is_image_aware_and_conservative(self):
        instruction = get_layout("paragraphs").instruction
        for expected in ("visual layout", "limited width", "list item", "code", "table", "punctuation", "ambiguous"):
            self.assertIn(expected, instruction)
        self.assertNotEqual(instruction, get_layout("preserve").instruction)


if __name__ == "__main__":
    unittest.main()
