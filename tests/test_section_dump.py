import fhbook


def test_section_dump(browser, site, tmp_path):
    out = tmp_path / "dump"
    browser.page().goto(site + "/section.html")
    r = browser.section_dump({"out": str(out)})
    md_files = list(out.glob("*.md"))
    assert [f.name for f in md_files] == ["Topic_ Woche 1 _ Mechanik.md"]
    md = md_files[0].read_text()
    assert "=== Skript Woche 1 ===" in md and "Inhalt der Seite" in md
    assert "NAVJUNK" not in md
    assert "Ganzes Buch Kapitel 1 und 2" in md            # book read via print view
    assert (out / "files" / "a.pdf").exists()
    assert "skipped: Giancoli: Kapitel 4 (lti)" in r
    assert "skipped: Selbsttest (quiz)" in r
    assert "Extern" not in r                              # non-activity links ignored
    assert browser.page().url.endswith("/section.html")   # current tab unchanged
    assert len(browser.ctx.pages) == 1                    # helper tab closed


def test_section_dump_filter(browser, site, tmp_path):
    browser.page().goto(site + "/section.html")
    r = browser.section_dump({"out": str(tmp_path / "d"), "filter": "skript"})
    assert "ok: Skript Woche 1" in r and "Formelbuch" not in r and "Checkliste" not in r


def test_section_dump_expired(browser, site, tmp_path):
    browser.page().goto(site + "/section_expired.html")
    assert browser.section_dump({"out": str(tmp_path / "d")}) == fhbook.SESSION_EXPIRED
    assert len(browser.ctx.pages) == 1
