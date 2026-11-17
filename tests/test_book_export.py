import fhbook


def test_book_export(browser, site, tmp_path):
    out = tmp_path / "book"
    browser.page().goto(site + "/book.html")
    r = browser.book_export({"out": str(out)})
    dest = out / "Kapitel 4 Kräfte.md"
    assert r == f"saved {dest} (3 pages)"
    md = dest.read_text()
    assert "--- S. 1 ---\nText 1" in md and "--- S. 3 ---\nText 3" in md


def test_book_export_no_viewer(browser, site, tmp_path):
    browser.page().goto(site + "/index.html")
    r = browser.book_export({"out": str(tmp_path / "book")})
    assert r == fhbook.NO_BOOK
    assert not (tmp_path / "book").exists()
