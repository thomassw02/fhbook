"""Shared fixtures: local static site (with a fake Moodle login redirect) + headless fhbook.Browser."""
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
import fhbook  # noqa: E402


class Handler(SimpleHTTPRequestHandler):
    """Static files; any path containing 'protected' redirects to the login page like Moodle does."""

    def do_GET(self):
        if "protected" in self.path:
            self.send_response(303)
            self.send_header("Location", "/login/index.php")
            self.end_headers()
            return
        super().do_GET()

    def guess_type(self, path):
        if "download_folder" in str(path):
            return "application/zip"
        return "text/html" if str(path).endswith(".php") else super().guess_type(path)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="session")
def site():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "fixtures")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(scope="session")
def _pw():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        yield p


@pytest.fixture
def browser(_pw, tmp_path):
    ctx = _pw.firefox.launch_persistent_context(str(tmp_path / "profile"), headless=True)
    yield fhbook.Browser(ctx)
    ctx.close()
