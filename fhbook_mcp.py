# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2,<2"]
# ///
"""MCP server for fhbook: lets Claude read/navigate FH Moodle (Lernpfade)
and the Pearson Giancoli e-book in the user's own logged-in Firefox window.

The browser itself runs in `fhbook start` (separate process, keeps the login);
this server only talks to its localhost HTTP API.
"""
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image

BASE = f"http://127.0.0.1:{os.environ.get('FHBOOK_PORT', '9334')}"
FHBOOK = Path(__file__).with_name("fhbook.py")
SHOT = Path(os.environ.get("FHBOOK_PROFILE", Path.home() / ".local/share/fhbook")).parent / "fhbook-shot.png"

mcp = FastMCP("fhbook")


def _call(path: str, **q) -> str:
    qs = urllib.parse.urlencode({k: v for k, v in q.items() if v is not None})
    try:
        with urllib.request.urlopen(f"{BASE}{path}{'?' + qs if qs else ''}", timeout=120) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        return e.read().decode()
    except urllib.error.URLError:
        return "fhbook browser not running — call start_browser, then the user logs in."


@mcp.tool()
def start_browser() -> str:
    """Open the fhbook Firefox window (FH Moodle). The user must log in themselves."""
    if "not running" not in _call("/tabs"):
        return "already running:\n" + _call("/tabs")
    uv = shutil.which("uv")
    cmd = [uv, "run", "--script", str(FHBOOK), "start"] if uv else [sys.executable, str(FHBOOK), "start"]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(90):
        time.sleep(1)
        if "not running" not in _call("/tabs"):
            return "started — ask the user to log in to Moodle in the window."
    return "start timed out"


@mcp.tool()
def read_page() -> str:
    """Full text of the current tab (all iframes), e.g. a Lernpfad or a Giancoli chapter page."""
    return _call("/read")


@mcp.tool()
def list_links(filter: str | None = None) -> str:
    """Links/buttons on the current tab. Optional case-insensitive filter (e.g. 'Giancoli', 'Lernpfad', 'Kapitel')."""
    return _call("/links", filter=filter)


@mcp.tool()
def click(text: str, nth: int = 0) -> str:
    """Click the nth link/button whose text contains `text`. New tabs (Pearson LTI) become current automatically."""
    return _call("/click", text=text, nth=nth)


@mcp.tool()
def goto(url: str) -> str:
    """Navigate the current tab to a URL (Moodle or Pearson)."""
    return _call("/goto", url=url)


@mcp.tool()
def back() -> str:
    """Browser back in the current tab."""
    return _call("/back")


@mcp.tool()
def tabs() -> str:
    """List open tabs; * marks the current one."""
    return _call("/tabs")


@mcp.tool()
def switch_tab(index: int) -> str:
    """Make tab `index` (from tabs()) the current tab."""
    return _call("/tab", i=index)


@mcp.tool()
def screenshot(full_page: bool = False) -> Image:
    """Screenshot of the current tab — use for formulas, figures, diagrams."""
    _call("/shot", out=str(SHOT), full="1" if full_page else "0")
    return Image(path=str(SHOT))


@mcp.tool()
def download(url: str | None = None, text: str | None = None, nth: int = 0,
             out_dir: str | None = None) -> str:
    """Save a file (e.g. Moodle PDF) using the browser's login cookies.

    Give `url` (absolute or relative to the current tab), or `text` of a link on the
    current tab, or neither to save the current tab's URL (e.g. a PDF open in the viewer).
    Moodle resource view pages are followed to their pluginfile. Default dir: ~/Downloads/fhbook.
    Returns the saved path — read it afterwards with markitdown / Read.
    """
    return _call("/download", url=url, text=text, nth=nth if text else None, out=out_dir)


@mcp.tool()
def run_js(script: str) -> str:
    """Evaluate a JS expression/arrow function in the current tab's main frame (for odd page structures). Read-only use."""
    req = urllib.request.Request(BASE + "/eval", data=script.encode())
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode()
    except Exception as e:
        return f"error: {e}"


# --- Pearson e-book (Apryse/PDFTron WebViewer renders the PDF to canvas) ---

_INST = ("const inst=(()=>{try{return window.getInstance(document.getElementById('wc-viewer'))||window.getInstance()}"
         "catch(e){try{return window.getInstance()}catch(_){return null}}})(); if(!inst) return 'no book viewer on current tab';"
         "const dv=inst.Core.documentViewer; const doc=dv.getDocument();")


def _eval(js: str) -> str:
    return run_js(js)


@mcp.tool()
def book_info() -> str:
    """Current Giancoli/Pearson PDF: page count and current page. Open a chapter first via the Lernpfad 'Giancoli: Kapitel ...' link."""
    return _eval(f"async () => {{ {_INST} return {{pages: doc.getPageCount(), current: dv.getCurrentPage(),"
                 f" title: document.title}} }}")


@mcp.tool()
def book_read_pages(start: int, end: int | None = None) -> str:
    """Extract text of PDF pages start..end (1-based, inclusive, max 10 per call) of the open chapter."""
    end = min(end or start, start + 9)
    return _eval(f"async () => {{ {_INST} const n=doc.getPageCount(); let out='';"
                 f" for(let p={start}; p<=Math.min({end},n); p++){{ out += '\\n=== Seite '+p+'/'+n+' ===\\n' + await doc.loadPageText(p) }}"
                 f" return out }}")


@mcp.tool()
def book_goto_page(page: int) -> str:
    """Show PDF page `page` in the viewer (then screenshot() for figures/formulas)."""
    return _eval(f"async () => {{ {_INST} dv.setCurrentPage({page}, false); return 'page '+{page} }}")


@mcp.tool()
def book_search(term: str) -> str:
    """Find pages of the open chapter containing `term` (case-insensitive), with short context."""
    t = term.replace("\\", "\\\\").replace("'", "\\'")
    return _eval(f"async () => {{ {_INST} const q='{t}'.toLowerCase(); const hits=[];"
                 f" for(let p=1;p<=doc.getPageCount();p++){{ const s=await doc.loadPageText(p); const i=s.toLowerCase().indexOf(q);"
                 f" if(i>=0) hits.push('S.'+p+': …'+s.slice(Math.max(0,i-80),i+120).replace(/\\n/g,' ')+'…') }}"
                 f" return hits.length? hits.join('\\n') : 'no hits' }}")


if __name__ == "__main__":
    mcp.run()
