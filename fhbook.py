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
  /download?url=|text=&nth=&out=
                   save a file (e.g. Moodle PDF) with the browser's cookies.
                   url: direct/relative URL; text: href of matching link;
                   neither: current tab URL. out = target dir.
  /section_dump?filter=&out=
                   read every page/book of the current Moodle section into one
                   .md file (out dir), download its files to out/files
  /book_export?out=  all pages of the open Pearson/Apryse book PDF -> out/<title>.md
  POST /eval       run JS body in current tab's main frame, return JSON
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = int(os.environ.get("FHBOOK_PORT", "9334"))
PROFILE = Path(os.environ.get("FHBOOK_PROFILE", Path.home() / ".local/share/fhbook/profile-ff"))
BASE = f"http://127.0.0.1:{PORT}"
START_URL = os.environ.get("FHBOOK_START_URL", "https://moodle.technikum-wien.at")
DOWNLOADS = Path(os.environ.get("FHBOOK_DOWNLOADS", Path.home() / "Downloads/fhbook"))
CACHE = Path(os.environ.get("FHBOOK_CACHE", Path.home() / ".cache/pruefung/_fhbook"))
NO_BOOK = "error: no book viewer on current tab — open a 'Giancoli: Kapitel …' link first"
# Apryse WebViewer: all page texts of the open PDF, or null if there is no viewer (same lookup as fhbook_mcp._INST).
BOOK_JS = """async () => {
  const inst = (() => { try { return window.getInstance(document.getElementById('wc-viewer')) || window.getInstance() }
                        catch (e) { try { return window.getInstance() } catch (_) { return null } } })();
  if (!inst) return null;
  const doc = inst.Core.documentViewer.getDocument();
  const pages = [];
  for (let p = 1; p <= doc.getPageCount(); p++) pages.push(await doc.loadPageText(p));
  return pages;
}"""
READ_MODS = {"page", "book", "lesson", "label"}
FILE_MODS = {"resource", "folder"}
CLICKABLE = "a, button, [role=button], [role=link], [onclick]"
SESSION_EXPIRED = "error: Moodle session expired — log in again in the fhbook window"


def login_wall(url: str) -> bool:
    """True if `url` is Moodle's login page (session gone, request got redirected)."""
    return "/login/index.php" in urllib.parse.urlparse(url).path


def safe_name(s: str) -> str:
    """Filesystem-safe single path component derived from a page/file title."""
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "_", s).strip()[:120].strip()
    return name or "untitled"

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
        self._hp = None  # helper tab used by section_dump
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

    def _find(self, text):
        """All clickable elements (all frames) whose text contains `text`, as (frame, locator)."""
        hits = []
        for f in self.page().frames:
            loc = f.locator(CLICKABLE).filter(has_text=text)
            try:
                c = loc.count()
            except Exception:
                continue
            hits += [(f, loc.nth(i)) for i in range(c)]
        return hits

    def click(self, q):
        text, nth = q["text"], int(q.get("nth", 0))
        before = len(self.ctx.pages)
        hits = self._find(text)
        if not hits:
            return f"no clickable element containing '{text}'"
        el = hits[min(nth, len(hits) - 1)][1]
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

    def download(self, q):
        """Fetch a file through the browser context (shares the Moodle session cookies) and save it."""
        pg = self.page()
        if q.get("url"):
            url = urllib.parse.urljoin(pg.url, q["url"])
        elif q.get("text"):
            hits = self._find(q["text"])
            if not hits:
                return f"no link containing '{q['text']}'"
            f, el = hits[min(int(q.get("nth", 0)), len(hits) - 1)]
            href = el.get_attribute("href")
            if not href or href.startswith("javascript"):
                return f"element '{q['text']}' has no downloadable href"
            url = urllib.parse.urljoin(f.url, href)
        else:
            url = pg.url
        resp = self.ctx.request.get(url, timeout=60000)
        if login_wall(resp.url):
            return SESSION_EXPIRED
        ctype = resp.headers.get("content-type", "")
        if resp.ok and "html" in ctype:
            # Moodle mod/resource view page (embed/frame display): follow the pluginfile link inside.
            m = re.search(r'https?://[^"\'\s<>]+/pluginfile\.php/[^"\'\s<>]+', resp.text())
            if m:
                url = m.group(0).replace("&amp;", "&")
                resp = self.ctx.request.get(url, timeout=60000)
                if login_wall(resp.url):
                    return SESSION_EXPIRED
                ctype = resp.headers.get("content-type", "")
        if not resp.ok:
            return f"error: HTTP {resp.status} for {url}"
        if "html" in ctype:
            return f"error: got an HTML page, not a file ({url}) — open the resource and retry, or pass its pluginfile URL"
        name = ""
        cd = resp.headers.get("content-disposition", "")
        m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.I) or re.search(r'filename="?([^";]+)"?', cd, re.I)
        if m:
            name = urllib.parse.unquote(m.group(1).strip())
        name = safe_name(Path(name or urllib.parse.unquote(urllib.parse.urlparse(url).path)).name or "download.bin")
        out_dir = Path(q.get("out") or DOWNLOADS).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / name
        body = resp.body()
        dest.write_bytes(body)
        return f"saved {dest} ({len(body)} bytes, {ctype.split(';')[0]})"

    def _activities(self):
        """(text, absolute url, mod) for every Moodle activity link on the current tab, deduplicated."""
        seen, out = set(), []
        for f in self.page().frames:
            try:
                items = f.evaluate(LINKS_JS)
            except Exception:
                continue
            for it in items:
                url = urllib.parse.urljoin(f.url, it["href"]) if it["href"] else ""
                m = re.search(r"/mod/(\w+)/", urllib.parse.urlparse(url).path)
                if m and url not in seen:
                    seen.add(url)
                    out.append((it["text"], url, m.group(1)))
        return out

    def section_dump(self, q):
        """Read all text activities of the current section into one .md, download its files; skip the rest."""
        flt = q.get("filter", "").lower()
        out_dir = Path(q.get("out") or CACHE).expanduser()
        cur = self.page()
        title = cur.title()
        acts = [a for a in self._activities() if not flt or flt in (a[0] + " " + a[1]).lower()]
        parts, report = [f"# {title}\n{cur.url}\n"], []
        self._hp = None
        try:
            for text, url, mod in acts:
                try:
                    line = self._dump_one(text, url, mod, out_dir, parts)
                except Exception as e:
                    line = f"failed: {text} — {str(e).splitlines()[0]}"
                if line == SESSION_EXPIRED:
                    return SESSION_EXPIRED
                report.append(line)
        finally:
            if self._hp is not None:
                self._hp.close()
            self._hp = None
            self.cur = cur
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{safe_name(title)}.md"
        dest.write_text("\n".join(parts), encoding="utf-8")
        return f"saved {dest}\n" + ("\n".join(report) or "no Moodle activities found on this tab")

    def _dump_one(self, text, url, mod, out_dir, parts):
        """One activity of section_dump: append its text to `parts` or download it. Returns a report line
        or SESSION_EXPIRED. Text pages load in a lazily created helper tab (self._hp)."""
        qid = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("id", [""])[0]
        if mod in FILE_MODS:
            if mod == "folder":  # whole folder as one zip instead of only its first file
                url = urllib.parse.urljoin(url, f"download_folder.php?id={qid}")
            r = self.download({"url": url, "out": str(out_dir / "files")})
            return r if r == SESSION_EXPIRED else f"file: {text} — {r}"
        if mod not in READ_MODS:
            return f"skipped: {text} ({mod})"
        if mod == "book":  # print view = whole book on one page
            url = urllib.parse.urljoin(url, f"tool/print/index.php?id={qid}")
        if self._hp is None:
            self._hp = self.ctx.new_page()
        hp = self._hp
        hp.goto(url, timeout=60000)
        self.settle(hp)
        if login_wall(hp.url):
            return SESSION_EXPIRED
        main = hp.locator("#region-main")
        body = (main.first if main.count() else hp.locator("body")).inner_text(timeout=10000).strip()
        parts.append(f"=== {text} ===\n{url}\n\n{body}\n")
        return f"ok: {text}"

    def book_export(self, q):
        """Write the full text of the open book chapter to <out>/<title>.md with page markers."""
        pg = self.page()
        pages = None
        for f in pg.frames:
            try:
                pages = f.evaluate(BOOK_JS)
            except Exception:
                continue
            if pages is not None:
                break
        if not pages:
            return NO_BOOK
        out_dir = Path(q.get("out") or CACHE).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{safe_name(pg.title())}.md"
        dest.write_text("\n".join(f"--- S. {i} ---\n{t}\n" for i, t in enumerate(pages, 1)), encoding="utf-8")
        return f"saved {dest} ({len(pages)} pages)"

    def eval(self, js):
        return json.dumps(self.page().evaluate(js), ensure_ascii=False, default=str)


def _launch(p):
    """Launch persistent Firefox; install Playwright's Firefox once if it went missing (e.g. after an update)."""
    try:
        return p.firefox.launch_persistent_context(str(PROFILE), headless=False, no_viewport=True)
    except Exception as e:
        if "Executable doesn't exist" not in str(e):
            raise
        print("Playwright Firefox missing — installing ...", flush=True)
        subprocess.run([sys.executable, "-m", "playwright", "install", "firefox"], check=True)
        return p.firefox.launch_persistent_context(str(PROFILE), headless=False, no_viewport=True)


def start():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = _launch(p)
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
                if u.path.strip("/") not in ("read", "links", "goto", "click", "back", "tabs", "tab", "shot", "download", "section_dump", "book_export", "") or fn is None:
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
        keys = {"links": "filter", "goto": "url", "click": "text", "tab": "i", "shot": "out", "download": "url", "section_dump": "filter", "book_export": "out"}
        qs = urllib.parse.urlencode({keys[cmd]: rest[0]}) if rest and cmd in keys else ""
        print(call(f"/{cmd}" + (f"?{qs}" if qs else "")))
