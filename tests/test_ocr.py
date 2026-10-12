import base64
import io
import json
import ssl
import unittest
import urllib.error
from dataclasses import replace
from unittest.mock import patch

import httpx
from PIL import Image

from quickcrop_ocr.config import DEFAULT_QWEN_MODEL, RuntimeConfig
from quickcrop_ocr.layout import TEXT_LAYOUTS, get_layout
from quickcrop_ocr.ocr import NoOcrBackendError, OcrError, recognize_text


def qwen_response(text):
    return (200, json.dumps({
        "output": {
            "choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": [{"text": text}]},
            }],
        },
    }), None)


class QwenOcrTests(unittest.TestCase):
    def setUp(self):
        self.config = RuntimeConfig(
            api_key="test-only-not-a-real-key",
            model=DEFAULT_QWEN_MODEL,
            qwen_region="beijing",
            output_format="single_line",
        )
        self.image = Image.new("RGB", (32, 24), "white")

    def tearDown(self):
        self.image.close()

    def test_requests_use_only_selected_dashscope_region(self):
        cases = [
            ("beijing", "dashscope.aliyuncs.com", DEFAULT_QWEN_MODEL),
            ("international", "dashscope-intl.aliyuncs.com", "qwen-vl-test-model"),
        ]
        for region, host, model in cases:
            with self.subTest(region=region), patch(
                "quickcrop_ocr.ocr.QwenTransport.post",
                return_value=qwen_response("recognized text"),
            ) as send:
                result = recognize_text(
                    self.image, replace(self.config, qwen_region=region, model=model)
                )

            send.assert_called_once()
            request = send.call_args.args[0]
            self.assertEqual(
                request.full_url,
                f"https://{host}/api/v1/services/aigc/multimodal-generation/generation",
            )
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.get_header("Authorization"), f"Bearer {self.config.api_key}")
            self.assertEqual(send.call_args.kwargs["timeout"], 20)
            payload = json.loads(request.data)
            self.assertEqual(payload["model"], model)
            self.assertEqual(payload["parameters"]["temperature"], 0)
            content = payload["input"]["messages"][0]["content"]
            data_url = content[0]["image"]
            self.assertTrue(data_url.startswith("data:image/jpeg;base64,"))
            with Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))) as image:
                self.assertEqual(image.size, self.image.size)
            self.assertIn("Transcribe only the text", content[1]["text"])
            self.assertEqual(result.text, "recognized text")
            self.assertEqual(result.backend, f"qwen:{model}")

    def test_single_line_keeps_chinese_and_does_not_add_punctuation_spaces(self):
        text = "\u4f60\u597d\uff0c\u4e16\u754c\uff01\nHello,world!\tNext."
        with patch(
            "quickcrop_ocr.ocr.QwenTransport.post", return_value=qwen_response(text)
        ):
            result = recognize_text(self.image, self.config)

        self.assertEqual(result.text, "\u4f60\u597d\uff0c\u4e16\u754c\uff01 Hello,world! Next.")

    def test_preserve_keeps_line_breaks_and_all_indentation(self):
        text = "    Title\n    indented text\n\nNext paragraph\n"
        with patch(
            "quickcrop_ocr.ocr.QwenTransport.post", return_value=qwen_response(text)
        ):
            result = recognize_text(self.image, replace(self.config, output_format="preserve"))

        self.assertEqual(result.text, text)

    def test_no_text_marker(self):
        for text in ("[NO_TEXT_DETECTED]", "  [NO_TEXT_DETECTED]\n"):
            with self.subTest(text=text), patch(
                "quickcrop_ocr.ocr.QwenTransport.post", return_value=qwen_response(text)
            ):
                result = recognize_text(self.image, self.config)
            self.assertEqual(result.text, "[NO_TEXT_DETECTED]")
            self.assertTrue(result.backend.startswith("qwen"))

    def test_empty_answers_are_errors_not_no_text(self):
        for text in ("", "   "):
            with self.subTest(text=text), patch(
                "quickcrop_ocr.ocr.QwenTransport.post", return_value=qwen_response(text)
            ), self.assertRaisesRegex(OcrError, "empty answer"):
                recognize_text(self.image, self.config)

    def test_missing_key_does_not_send_a_request(self):
        with patch("quickcrop_ocr.ocr.QwenTransport.post") as send:
            with self.assertRaises(NoOcrBackendError):
                recognize_text(self.image, replace(self.config, api_key=""))
        send.assert_not_called()

    def test_each_layout_is_passed_to_qwen_in_a_single_request(self):
        for mode in TEXT_LAYOUTS:
            text = "Heading\n\nParagraph one.\n\n- Item: 3.14!\n"
            with self.subTest(mode=mode), patch(
                "quickcrop_ocr.ocr.QwenTransport.post", return_value=qwen_response(text)
            ) as send:
                result = recognize_text(self.image, replace(self.config, output_format=mode))
            send.assert_called_once()
            payload = json.loads(send.call_args.args[0].data)
            prompt = payload["input"]["messages"][0]["content"][1]["text"]
            self.assertIn(get_layout(mode).instruction, prompt)
            self.assertIn("Keep all original punctuation", prompt)
            self.assertEqual(result.text, " ".join(text.split()) if mode == "single_line" else text)

    def test_unknown_layout_is_rejected_before_image_encoding_or_api_call(self):
        with patch("quickcrop_ocr.ocr.QwenTransport.post") as send, patch(
            "quickcrop_ocr.ocr._image_to_base64"
        ) as encode:
            with self.assertRaisesRegex(OcrError, "output format"):
                recognize_text(self.image, replace(self.config, output_format="unknown"))
        send.assert_not_called()
        encode.assert_not_called()

    def test_invalid_region_does_not_send_a_request(self):
        with patch("quickcrop_ocr.ocr.QwenTransport.post") as send:
            with self.assertRaisesRegex(OcrError, "Qwen region"):
                recognize_text(self.image, replace(self.config, qwen_region="invalid"))
        send.assert_not_called()

    def test_invalid_json_reports_qwen_error(self):
        with patch(
            "quickcrop_ocr.ocr.QwenTransport.post", return_value=(200, "not JSON", None)
        ):
            with self.assertRaisesRegex(OcrError, "invalid JSON from Qwen"):
                recognize_text(self.image, self.config)

    def test_auth_error_does_not_fall_back(self):
        reply = (401, '{"code":"InvalidApiKey","message":"Invalid API key"}', None)
        with patch(
            "quickcrop_ocr.ocr.QwenTransport.post", return_value=reply
        ) as send:
            with self.assertRaisesRegex(OcrError, "HTTP 401"):
                recognize_text(self.image, self.config)
        send.assert_called_once()

    def test_network_retries_stay_on_qwen_and_report_qwen(self):
        errors = [
            urllib.error.URLError(ssl.SSLError("UNEXPECTED_EOF_WHILE_READING")),
            ConnectionResetError("[WinError 10054] connection reset"),
            httpx.ConnectError("UNEXPECTED_EOF_WHILE_READING"),
            httpx.RemoteProtocolError("Server disconnected without sending a response"),
            httpx.ReadTimeout("read timed out"),
        ]
        for error in errors:
            with self.subTest(error=error), patch(
                "quickcrop_ocr.ocr.QwenTransport.post", side_effect=error
            ) as send, patch("quickcrop_ocr.ocr.RequestControl.wait") as wait:
                with self.assertRaisesRegex(OcrError, "Qwen"):
                    recognize_text(self.image, self.config)
            self.assertEqual(send.call_count, 3)
            self.assertEqual(wait.call_count, 2)
            for call in send.call_args_list:
                self.assertTrue(call.args[0].full_url.startswith("https://dashscope.aliyuncs.com/"))

    def test_transient_network_failure_retries_same_request(self):
        with patch(
            "quickcrop_ocr.ocr.QwenTransport.post",
            side_effect=[httpx.ReadError("stale connection"), qwen_response("Recovered")],
        ) as send, patch("quickcrop_ocr.ocr.RequestControl.wait"):
            result = recognize_text(self.image, self.config)

        self.assertEqual(result.text, "Recovered")
        self.assertEqual(send.call_count, 2)
        self.assertIs(send.call_args_list[0].args[0], send.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()
