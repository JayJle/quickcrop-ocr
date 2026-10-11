import io
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

from quickcrop_ocr.ocr import (
    OcrCancelled, OcrError, OcrTimeout, RequestControl, _REQUEST_SLOT,
    _extract_response_text, _post_with_retries, _retry_delay,
)


def answer(reason="stop", text="complete"):
    return {"output": {"choices": [{
        "finish_reason": reason,
        "message": {"role": "assistant", "content": [{"text": text}]},
    }]}}


class ResponseSafetyTests(unittest.TestCase):
    def test_only_completed_answers_are_accepted(self):
        for reason in ("length", None, "content_filter", "tool_calls", "unknown"):
            with self.subTest(reason=reason), self.assertRaises(OcrError):
                _extract_response_text(answer(reason))

    def test_truncation_has_actionable_error(self):
        with self.assertRaisesRegex(OcrError, "truncated.*smaller region"):
            _extract_response_text(answer("length"))

    def test_bad_or_rejected_responses_are_not_no_text(self):
        cases = [None, [], {}, {"output": {}}, {"output": {"choices": []}},
                 {"code": "DataInspectionFailed", "message": "Request blocked"}]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(OcrError):
                _extract_response_text(payload)

    def test_refusal_and_non_text_content_are_rejected(self):
        for change in ({"refusal": "blocked"}, {"content": [{"image": "test"}]},
                       {"role": "user"}):
            payload = answer()
            payload["output"]["choices"][0]["message"].update(change)
            with self.subTest(change=change), self.assertRaises(OcrError):
                _extract_response_text(payload)

    def test_metadata_and_alternative_answers_are_not_concatenated(self):
        payload = answer(text="    exact\n")
        payload["metadata"] = {"text": "not OCR"}
        payload["output"]["choices"][0]["message"]["reasoning_content"] = "reasoning"
        payload["output"]["choices"].append(answer(text="alternative")["output"]["choices"][0])
        self.assertEqual(_extract_response_text(payload), "    exact\n")


class RequestBudgetTests(unittest.TestCase):
    def setUp(self):
        self.request = urllib.request.Request("https://dashscope.aliyuncs.com/test", data=b"test")

    def test_transient_http_statuses_retry_and_report_progress(self):
        for code in (408, 429, 500, 502, 503, 504):
            progress = Mock()
            control = RequestControl(on_progress=progress)
            control.wait = Mock()
            error = urllib.error.HTTPError(
                self.request.full_url, code, "Temporary", {"Retry-After": "2"},
                io.BytesIO(b'{"code":"Temporary","message":"Try again"}'),
            )
            with self.subTest(code=code), patch(
                "quickcrop_ocr.ocr.urllib.request.urlopen",
                side_effect=[error, io.BytesIO(b"success")],
            ) as send:
                self.assertEqual(_post_with_retries(self.request, control), "success")
            self.assertEqual(send.call_count, 2)
            control.wait.assert_called_once_with(2.0)
            self.assertTrue(any("Retrying 2/3" in c.args[0] for c in progress.call_args_list))

    def test_authentication_errors_do_not_retry(self):
        for code in (400, 401, 403):
            control = RequestControl()
            control.wait = Mock()
            with self.subTest(code=code), patch(
                "quickcrop_ocr.ocr._request_with_budget", return_value=(code, "denied", None)
            ) as send, self.assertRaisesRegex(OcrError, f"HTTP {code}"):
                _post_with_retries(self.request, control)
            send.assert_called_once()
            control.wait.assert_not_called()

    def test_retry_exhaustion_is_bounded(self):
        control = RequestControl()
        control.wait = Mock()
        with patch("quickcrop_ocr.ocr._request_with_budget", return_value=(503, "busy", None)) as send:
            with self.assertRaisesRegex(OcrError, "HTTP 503"):
                _post_with_retries(self.request, control)
        self.assertEqual(send.call_count, 3)
        self.assertEqual(control.wait.call_count, 2)

    def test_retry_after_cannot_extend_total_budget(self):
        with patch("quickcrop_ocr.ocr._request_with_budget", return_value=(429, "busy", "100")) as send:
            start = time.monotonic()
            with self.assertRaises(OcrTimeout):
                _post_with_retries(self.request, RequestControl(timeout=0.04))
        self.assertLess(time.monotonic() - start, 0.5)
        send.assert_called_once()

    def test_cancel_during_retry_backoff_stops_next_request(self):
        control = RequestControl()
        control.on_progress = lambda text: control.cancel_event.set() if "Retrying" in text else None
        with patch("quickcrop_ocr.ocr._request_with_budget", return_value=(503, "busy", None)) as send:
            with self.assertRaises(OcrCancelled):
                _post_with_retries(self.request, control)
        send.assert_called_once()

    def test_pre_canceled_request_does_not_send(self):
        control = RequestControl()
        control.cancel_event.set()
        with patch("quickcrop_ocr.ocr.urllib.request.urlopen") as send:
            with self.assertRaises(OcrCancelled):
                _post_with_retries(self.request, control)
        send.assert_not_called()

    def test_blocked_socket_obeys_deadline_and_cancellation(self):
        for cancel in (False, True):
            release = threading.Event()
            entered = threading.Event()
            control = RequestControl(timeout=0.08 if not cancel else 5)

            def blocked_send(*_args, **_kwargs):
                entered.set()
                release.wait(2)
                return io.BytesIO(b"late reply")

            timer = threading.Timer(0.04, control.cancel_event.set) if cancel else None
            with self.subTest(cancel=cancel), patch(
                "quickcrop_ocr.ocr.urllib.request.urlopen", side_effect=blocked_send
            ):
                try:
                    if timer:
                        timer.start()
                    start = time.monotonic()
                    with self.assertRaises(OcrCancelled if cancel else OcrTimeout):
                        _post_with_retries(self.request, control)
                    self.assertTrue(entered.is_set())
                    self.assertLess(time.monotonic() - start, 0.5)
                finally:
                    release.set()
                    if timer:
                        timer.join()
                    acquired = _REQUEST_SLOT.acquire(timeout=2)
                    if acquired:
                        _REQUEST_SLOT.release()
                    self.assertTrue(acquired, "HTTP test worker did not finish")

    def test_waiting_for_previous_socket_is_also_budgeted(self):
        _REQUEST_SLOT.acquire()
        try:
            with patch("quickcrop_ocr.ocr.urllib.request.urlopen") as send:
                with self.assertRaises(OcrTimeout):
                    _post_with_retries(self.request, RequestControl(timeout=0.03))
            send.assert_not_called()
        finally:
            _REQUEST_SLOT.release()

    def test_socket_timeout_is_capped_by_remaining_budget(self):
        with patch("quickcrop_ocr.ocr.urllib.request.urlopen", return_value=io.BytesIO(b"ok")) as send:
            _post_with_retries(self.request, RequestControl(timeout=1))
        self.assertLessEqual(send.call_args.kwargs["timeout"], 1)
        self.assertGreater(send.call_args.kwargs["timeout"], 0)

    def test_retry_after_http_date_and_invalid_values(self):
        self.assertEqual(_retry_delay("Thu, 01 Jan 1970 00:00:00 GMT", 0.4), 0)
        self.assertEqual(_retry_delay("not a date", 0.4), 0.4)
        self.assertEqual(_retry_delay(None, 0.4), 0.4)
        self.assertEqual(_retry_delay("inf", 0.4), 0.4)
        self.assertEqual(_retry_delay("NaN", 0.4), 0.4)

    def test_early_wait_wakeup_cannot_shortcut_backoff(self):
        clock = [0.0]
        control = RequestControl(timeout=1, started=0)
        control.cancel_event = Mock()
        control.cancel_event.is_set.return_value = False

        def wake_early(delay):
            clock[0] += min(delay, 0.25)

        control.cancel_event.wait.side_effect = wake_early
        with patch("quickcrop_ocr.ocr.time.monotonic", side_effect=lambda: clock[0]):
            control.wait(0.8)
            self.assertAlmostEqual(clock[0], 0.8)
            with self.assertRaises(OcrTimeout):
                control.wait(100)
            self.assertAlmostEqual(clock[0], 1.0)


if __name__ == "__main__":
    unittest.main()
