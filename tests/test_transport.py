import json
import threading
import time
import unittest
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import httpx
from PIL import Image

from quickcrop_ocr.config import RuntimeConfig
from quickcrop_ocr.ocr import OcrCancelled, RequestControl, _REQUEST_SLOT, recognize_text
from quickcrop_ocr.transport import KEEPALIVE_SECONDS, QwenTransport


def request(host="dashscope.aliyuncs.com", key="test-key"):
    return urllib.request.Request(
        f"https://{host}/test", data=b'{"model":"test"}',
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )


class TransportTests(unittest.TestCase):
    def factory(self, handler):
        real_client = httpx.Client
        self.clients = []
        self.options = []

        def create(**kwargs):
            self.options.append(kwargs)
            client = real_client(**kwargs, transport=httpx.MockTransport(handler))
            self.clients.append(client)
            return client

        return patch("quickcrop_ocr.transport.httpx.Client", side_effect=create)

    def test_lazy_reuse_headers_timeouts_and_response_close(self):
        sent, responses = [], []

        def handler(req):
            sent.append(req)
            response = httpx.Response(503, content=b"busy", headers={"Retry-After": "2"})
            responses.append(response)
            return response

        with self.factory(handler) as factory, patch("urllib.request.proxy_bypass", return_value=True):
            transport = QwenTransport()
            factory.assert_not_called()
            self.assertEqual(transport.post(request(), timeout=0.75), (503, "busy", "2"))
            transport.post(request(key="different-key"), timeout=2)
            factory.assert_called_once()
            self.assertEqual([r.headers["Authorization"] for r in sent], ["Bearer test-key", "Bearer different-key"])
            self.assertNotIn("Authorization", self.clients[0].headers)
            self.assertEqual(sent[0].content, b'{"model":"test"}')
            self.assertTrue(all(v == 0.75 for v in sent[0].extensions["timeout"].values()))
            self.assertTrue(all(r.is_closed for r in responses))
            limits = self.options[0]["limits"]
            self.assertEqual(limits.max_connections, 1)
            self.assertEqual(limits.keepalive_expiry, 60)
            self.assertEqual(KEEPALIVE_SECONDS, 60)
            transport.close()
            transport.close()
            self.assertTrue(self.clients[0].is_closed)
            with self.assertRaisesRegex(RuntimeError, "closed"):
                transport.post(request(), timeout=1)

    def test_region_change_closes_previous_pool(self):
        with self.factory(lambda req: httpx.Response(200, content=b"ok")), patch(
            "urllib.request.proxy_bypass", return_value=True
        ), QwenTransport() as transport:
            transport.post(request(), timeout=1)
            transport.post(request("dashscope-intl.aliyuncs.com"), timeout=1)
            self.assertEqual(len(self.clients), 2)
            self.assertTrue(self.clients[0].is_closed)
            self.assertFalse(self.clients[1].is_closed)
        self.assertTrue(self.clients[1].is_closed)

    def test_windows_proxy_route_and_bypass_are_preserved(self):
        with patch("quickcrop_ocr.transport.httpx.Client") as factory, patch(
            "urllib.request.getproxies", return_value={"https": "http://localhost:1234"}
        ), patch("urllib.request.proxy_bypass", side_effect=[False, True]):
            reply = factory.return_value.stream.return_value.__enter__.return_value
            reply.read.return_value = b"ok"
            with QwenTransport() as transport:
                transport.post(request(), timeout=1)
                transport.post(request(), timeout=1)
            self.assertEqual(factory.call_args_list[0].kwargs["proxy"], "http://localhost:1234")
            self.assertIsNone(factory.call_args_list[1].kwargs["proxy"])
            self.assertFalse(factory.call_args.kwargs["trust_env"])

    def test_redirect_is_returned_without_forwarding_credentials(self):
        sent = []

        def handler(req):
            sent.append(req)
            return httpx.Response(302, headers={"Location": "https://other.example/test"})

        with self.factory(handler), patch("urllib.request.proxy_bypass", return_value=True), QwenTransport() as transport:
            self.assertEqual(transport.post(request(), timeout=1)[0], 302)
        self.assertEqual(len(sent), 1)

    def test_close_during_body_read_is_deferred(self):
        entered, release = threading.Event(), threading.Event()

        class BlockingBody(httpx.SyncByteStream):
            def __iter__(self):
                entered.set()
                release.wait(2)
                yield b"complete"

        with self.factory(lambda req: httpx.Response(200, stream=BlockingBody())), patch(
            "urllib.request.proxy_bypass", return_value=True
        ):
            transport = QwenTransport()
            replies = []
            worker = threading.Thread(target=lambda: replies.append(transport.post(request(), timeout=1)))
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                start = time.monotonic()
                transport.close()
                self.assertLess(time.monotonic() - start, 0.2)
                self.assertFalse(self.clients[0].is_closed)
                with self.assertRaisesRegex(RuntimeError, "closed"):
                    transport.post(request(), timeout=1)
            finally:
                release.set()
                worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(replies, [(200, "complete", None)])
            self.assertTrue(self.clients[0].is_closed)

    def test_read_failure_releases_active_state_and_response(self):
        class BrokenBody(httpx.SyncByteStream):
            def __iter__(self):
                raise httpx.ReadError("connection reset")
                yield b"unreachable"

        bad = httpx.Response(200, stream=BrokenBody())
        replies = iter([bad, httpx.Response(200, content=b"recovered")])
        with self.factory(lambda req: next(replies)), patch(
            "urllib.request.proxy_bypass", return_value=True
        ), QwenTransport() as transport:
            with self.assertRaises(httpx.ReadError):
                transport.post(request(), timeout=1)
            self.assertTrue(bad.is_closed)
            self.assertEqual(transport.post(request(), timeout=1)[1], "recovered")

    def test_close_while_initializing_client_prevents_send(self):
        entered, release = threading.Event(), threading.Event()
        sent, errors = [], []
        client = httpx.Client(transport=httpx.MockTransport(lambda req: sent.append(req)))

        def create(**_kwargs):
            entered.set()
            release.wait(2)
            return client

        transport = QwenTransport()

        def send():
            try:
                transport.post(request(), timeout=1)
            except RuntimeError as error:
                errors.append(str(error))

        with patch("quickcrop_ocr.transport.httpx.Client", side_effect=create), patch(
            "urllib.request.proxy_bypass", return_value=True
        ):
            worker = threading.Thread(target=send)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                transport.close()
            finally:
                release.set()
                worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ["Qwen transport is closed"])
        self.assertEqual(sent, [])
        self.assertTrue(client.is_closed)

    def test_active_cancel_keeps_pool_usable_for_next_job(self):
        release = threading.Event()
        control = RequestControl()
        calls = []
        body = {"output": {"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": [{"text": "complete"}],
        }}]}}

        def handler(req):
            calls.append(req)
            if len(calls) == 1:
                control.cancel_event.set()
                release.wait(2)
            return httpx.Response(200, json=body)

        with self.factory(handler), patch("urllib.request.proxy_bypass", return_value=True), QwenTransport() as transport, Image.new("RGB", (20, 20)) as image:
            config = RuntimeConfig("local-test-key", "qwen3-vl-plus", "beijing", "single_line")
            try:
                with self.assertRaises(OcrCancelled):
                    recognize_text(image, config, control=control, transport=transport)
            finally:
                release.set()
                acquired = _REQUEST_SLOT.acquire(timeout=2)
                if acquired:
                    _REQUEST_SLOT.release()
                self.assertTrue(acquired)
            self.assertEqual(recognize_text(image, config, transport=transport).text, "complete")
            self.assertEqual(len(self.clients), 1)
            self.assertEqual(len(calls), 2)


@contextmanager
def local_qwen(*, close_connection=False):
    body = json.dumps({"output": {"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": [{"text": "Hello,world!"}],
    }}]}}).encode()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.server.connections += 1

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.server.requests += 1
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            if close_connection:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.connections = server.requests = 0
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


class RealConnectionTests(unittest.TestCase):
    def exercise(self, *, server_closes=False, expire=False):
        with local_qwen(close_connection=server_closes) as server, patch.dict(
            "quickcrop_ocr.ocr.QWEN_ENDPOINTS", {"beijing": f"http://127.0.0.1:{server.server_port}/test"}
        ), patch("urllib.request.proxy_bypass", return_value=True), patch(
            "quickcrop_ocr.transport.KEEPALIVE_SECONDS", 0.01 if expire else 60
        ), QwenTransport() as transport, Image.new("RGB", (20, 20)) as image:
            config = RuntimeConfig("local-test-key", "qwen3-vl-plus", "beijing", "single_line")
            for index in range(2):
                if expire and index:
                    time.sleep(0.03)
                result = recognize_text(image, config, transport=transport)
                self.assertEqual(result.text, "Hello,world!")
            self.assertEqual(server.requests, 2)
            self.assertEqual(server.connections, 2 if server_closes or expire else 1)

    def test_recognize_calls_reuse_one_real_connection(self):
        self.exercise()

    def test_server_closed_connection_reconnects(self):
        self.exercise(server_closes=True)

    def test_idle_expiry_reconnects(self):
        self.exercise(expire=True)

    def test_canceled_request_does_not_poison_shared_transport(self):
        with local_qwen() as server, patch.dict(
            "quickcrop_ocr.ocr.QWEN_ENDPOINTS", {"beijing": f"http://127.0.0.1:{server.server_port}/test"}
        ), patch("urllib.request.proxy_bypass", return_value=True), QwenTransport() as transport, Image.new("RGB", (20, 20)) as image:
            config = RuntimeConfig("local-test-key", "qwen3-vl-plus", "beijing", "single_line")
            control = RequestControl()
            control.cancel_event.set()
            with self.assertRaises(OcrCancelled):
                recognize_text(image, config, control=control, transport=transport)
            self.assertEqual(recognize_text(image, config, transport=transport).text, "Hello,world!")
            self.assertEqual(server.requests, 1)
