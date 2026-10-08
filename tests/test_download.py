"""store.download against a local server whose connection drops halfway (as PDOK's did once,
at 3.9 of 7.8 GB): the download must resume with a Range request, not keep half a file."""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from anonymate import store

DATA = bytes(range(256)) * 4096          # 1 MiB


def serve(drop_first: int, open_range: bool = True):
    """A server that, for the first ``drop_first`` requests, announces the whole length but
    sends only half and closes. ``open_range=False`` acts like PDOK (Azure Blob): an open range
    ``bytes=<start>-`` gets the whole file, only a closed one is honoured."""
    calls = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            start = 0
            rng = self.headers.get("Range")
            if rng and not open_range and rng.endswith("-"):
                rng = None
            if rng:
                start = int(rng.split("=")[1].split("-")[0])
            calls.append(start)
            body = DATA[start:]
            self.send_response(206 if rng else 200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if len(calls) <= drop_first:
                self.wfile.write(body[: len(body) // 2])
                self.close_connection = True
                return
            self.wfile.write(body)

        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(DATA)))
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, calls


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)


def test_resumes_after_a_dropped_connection(tmp_path):
    srv, calls = serve(drop_first=2)
    try:
        out = store.download(f"http://127.0.0.1:{srv.server_port}/bag.gpkg", tmp_path / "bag.gpkg")
    finally:
        srv.shutdown()
    assert out.read_bytes() == DATA
    assert calls[0] == 0 and calls[1] > 0 and len(calls) == 3


def test_gives_up_without_leaving_a_whole_looking_file(tmp_path):
    srv, _ = serve(drop_first=99)
    try:
        with pytest.raises(RuntimeError, match="onvolledig"):
            store.download(f"http://127.0.0.1:{srv.server_port}/bag.gpkg",
                           tmp_path / "bag.gpkg", attempts=2)
    finally:
        srv.shutdown()
    assert not (tmp_path / "bag.gpkg").exists()


def test_resumes_with_a_closed_range_like_pdok_wants(tmp_path):
    srv, calls = serve(drop_first=2, open_range=False)
    try:
        out = store.download(f"http://127.0.0.1:{srv.server_port}/bag.gpkg", tmp_path / "bag.gpkg")
    finally:
        srv.shutdown()
    assert out.read_bytes() == DATA
    assert calls[0] == 0 and calls[1] > 0 and calls[2] > calls[1]


def test_resumes_a_part_left_by_an_earlier_run(tmp_path):
    (tmp_path / "bag.gpkg.part").write_bytes(DATA[:1000])
    srv, calls = serve(drop_first=0, open_range=False)
    try:
        out = store.download(f"http://127.0.0.1:{srv.server_port}/bag.gpkg", tmp_path / "bag.gpkg")
    finally:
        srv.shutdown()
    assert out.read_bytes() == DATA and calls == [1000]
