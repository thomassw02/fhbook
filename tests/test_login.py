import fhbook


def test_login_wall():
    assert fhbook.login_wall("https://moodle.technikum-wien.at/login/index.php")
    assert fhbook.login_wall("https://moodle.technikum-wien.at/login/index.php?x=1")
    assert not fhbook.login_wall("https://moodle.technikum-wien.at/course/view.php?id=1")


def test_safe_name():
    assert fhbook.safe_name("Kap. 4: Kräfte/Newton") == "Kap. 4_ Kräfte_Newton"
    assert fhbook.safe_name("  ") == "untitled"
    assert fhbook.safe_name("../../etc") == ".._.._etc"
    assert len(fhbook.safe_name("a" * 500)) == 120


def test_download_login_redirect(browser, site, tmp_path):
    browser.page().goto(site + "/index.html")
    assert browser.download({"url": "/protected.pdf", "out": str(tmp_path / "dl")}) == fhbook.SESSION_EXPIRED
    assert not (tmp_path / "dl").exists()
