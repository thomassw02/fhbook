# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.49"]
# ///
"""fhbook: own Firefox window for FH Moodle + e-books that an AI assistant can drive.

`fhbook start` opens a visible Firefox (persistent profile). The user logs in
themselves (credentials never pass through this tool). A localhost-only HTTP API lets tools (CLI / MCP server) read and
navigate the *current* tab. New tabs (e.g. LTI launches to Pearson) become
the current tab automatically.

Endpoints (GET unless noted):
  /read            text of current tab (all frames)
  /links?filter=   links/buttons of current tab (all frames), numbered
  /goto?url=       navigate current tab
  /click?text=&nth=  click link/button whose text contains `text`
  /back            history back
  /tabs            list tabs
  /tab?i=          make tab i current
  /shot?out=       full-page screenshot of current tab
  POST /eval       run JS body in current tab's main frame, return JSON
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = int(os.environ.get("FHBOOK_PORT", "9334"))
PROFILE = Path(os.environ.get("FHBOOK_PROFILE", Path.home() / ".local/share/fhbook/profile-ff"))
BASE = f"http://127.0.0.1:{PORT}"
START_URL = os.environ.get("FHBOOK_START_URL", "https://moodle.technikum-wien.at")

LINKS_JS = """() => {
  const els = [...document.querySelectorAll('a[href], button, [role=button], [role=link], [onclick]')];
  return els.filter(e => e.offsetParent !== null || e.getClientRects().length)
    .map(e => ({text: (e.innerText || e.title || e.getAttribute('aria-label') || '').trim().replace(/\\s+/g,' '),
                href: e.getAttribute('href') || ''}))
    .filter(l => l.text);
}"""


class Browser:
    def __init__(self, ctx):
        self.ctx = ctx
        self.cur = ctx.pages[0] if ctx.pages else ctx.new_page()
        ctx.on("page", self._on_page)

    def _on_page(self, pg):
        self.cur = pg

    def page(self):
        if self.cur.is_closed():
            self.cur = self.ctx.pages[-1]
        return self.cur

    def settle(self, pg):
        try:
            pg.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        pg.wait_for_timeout(800)

    def read(self, q):
        pg = self.page()
        out = [f"URL: {pg.url}\nTITLE: {pg.title()}\n"]
        for f in pg.frames:
            try:
                t = f.inner_text("body", timeout=5000).strip()
            except Exception:
                continue
            if t:
                out.append(f"--- frame {f.url[:120]} ---\n{t}\n")
        return "\n".join(out)

    def links(self, q):
        flt = q.get("filter", "").lower()
        pg = self.page()
        out, n = [], 0
        for f in pg.frames:
            try:
                items = f.evaluate(LINKS_JS)
            except Exception:
                continue
            for it in items:
                if flt and flt not in (it["text"] + " " + it["href"]).lower():
                    continue
                href = urllib.parse.urljoin(f.url, it["href"]) if it["href"] and not it["href"].startswith("javascript") else it["href"]
                out.append(f"[{n}] {it['text'][:120]}  ->  {href}")
                n += 1
        return f"URL: {pg.url}\n" + "\n".join(out)

    def goto(self, q):
        pg = self.page()
        pg.goto(q["url"], timeout=60000)
        self.settle(pg)
        return f"URL: {pg.url}\nTITLE: {pg.title()}"

    def click(self, q):
        text, nth = q["text"], int(q.get("nth", 0))
        pg = self.page()
        before = len(self.ctx.pages)
        hits = []
        for f in pg.frames:
            loc = f.locator("a, button, [role=button], [role=link], [onclick]").filter(has_text=text)
            try:
                c = loc.count()
            except Exception:
                continue
            hits += [loc.nth(i) for i in range(c)]
        if not hits:
            return f"no clickable element containing '{text}'"
        el = hits[min(nth, len(hits) - 1)]
        el.scroll_into_view_if_needed(timeout=5000)
        el.click(timeout=10000)
        pg.wait_for_timeout(1500)
        cur = self.page()
        self.settle(cur)
        new = " (opened new tab)" if len(self.ctx.pages) > before else ""
        return f"clicked {nth}/{len(hits)} matches{new}\nURL: {cur.url}\nTITLE: {cur.title()}"

    def back(self, q):
        pg = self.page()
        pg.go_back(timeout=30000)
        self.settle(pg)
        return f"URL: {pg.url}"

    def tabs(self, q):
        return "\n".join(f"[{i}]{' *' if p == self.page() else ''} {p.title()[:80]}  {p.url[:120]}"
                         for i, p in enumerate(self.ctx.pages))

    def tab(self, q):
        self.cur = self.ctx.pages[int(q["i"])]
        self.cur.bring_to_front()
        return self.tabs(q)

    def shot(self, q):
        out = q.get("out", "/tmp/fhbook.png")
        self.page().screenshot(path=out, full_page=q.get("full", "1") == "1")
        return out

    def eval(self, js):
        return json.dumps(self.page().evaluate(js), ensure_ascii=False, default=str)


def start():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.firefox.launch_persistent_context(str(PROFILE), headless=False, no_viewport=True)
        br = Browser(ctx)
        br.page().goto(START_URL)

        class H(BaseHTTPRequestHandler):
            def _reply(self, code, body):
                self.send_response(code)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode())

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                fn = getattr(br, u.path.strip("/") or "read", None)
                if u.path.strip("/") not in ("read", "links", "goto", "click", "back", "tabs", "tab", "shot", "") or fn is None:
                    return self._reply(404, "unknown endpoint")
                try:
                    self._reply(200, fn(q))
                except Exception as e:
                    self._reply(500, f"error: {e}")

            def do_POST(self):
                if self.path != "/eval":
                    return self._reply(404, "unknown endpoint")
                js = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
                try:
                    self._reply(200, br.eval(js))
                except Exception as e:
                    self._reply(500, f"error: {e}")

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", PORT), H)
        srv.timeout = 0.3
        print(f"fhbook running on {BASE}. Close the window to stop.", flush=True)
        while ctx.pages:
            srv.handle_request()
            try:
                ctx.pages[0].wait_for_timeout(50)
            except Exception:
                break


def call(path, data=None):
    req = urllib.request.Request(BASE + path, data=data)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        return e.read().decode()


if __name__ == "__main__":
    a = sys.argv[1:] or ["read"]
    cmd, rest = a[0], a[1:]
    if cmd == "start":
        start()
    elif cmd == "eval":
        print(call("/eval", rest[0].encode()))
    else:
        keys = {"links": "filter", "goto": "url", "click": "text", "tab": "i", "shot": "out"}
        qs = urllib.parse.urlencode({keys[cmd]: rest[0]}) if rest and cmd in keys else ""
        print(call(f"/{cmd}" + (f"?{qs}" if qs else "")))
