import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fhbook_mcp  # noqa: E402


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"ok"


def test_long_tools_get_long_timeout(monkeypatch):
    seen = {}
    monkeypatch.setattr(fhbook_mcp.urllib.request, "urlopen",
                        lambda url, timeout: seen.setdefault(url.split("?")[0].rsplit("/", 1)[1], timeout) and _Resp())
    fhbook_mcp.section_dump()
    fhbook_mcp.book_export()
    fhbook_mcp.read_page()
    assert seen["section_dump"] >= 900 and seen["book_export"] >= 900
    assert seen["read"] == 120
