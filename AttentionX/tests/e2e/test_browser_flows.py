"""Real-browser acceptance flows (Chromium via Playwright) against the real app.

Starts ``python app.py`` with a temporary library root and a background worker
thread, then drives the UI like a user. No component-label-only assertions:
every step checks visible results that come from real analysis.

Run: bash run_tests.sh e2e   (needs provisioned models and /opt/pw-browsers/chromium)
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "images"
CHROMIUM = os.getenv("ATTENTIONX_CHROMIUM", "/opt/pw-browsers/chromium")

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class App:
    def __init__(self, lib_root: Path) -> None:
        self.lib_root = lib_root
        self.port = _free_port()
        self.proc = None

    def start(self) -> None:
        env = dict(os.environ, ATTENTIONX_LIBRARY_ROOT=str(self.lib_root), ATTENTIONX_WORKER="thread",
                   ATTENTIONX_SERVER_PORT=str(self.port), ATTENTIONX_SERVER_NAME="127.0.0.1",
                   GRADIO_ANALYTICS_ENABLED="False", PYTHONPATH=str(ROOT))
        log = open(self.lib_root.parent / f"app-{self.port}.log", "w")
        self.proc = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
                return
            except OSError:
                if self.proc.poll() is not None:
                    raise RuntimeError("app exited during startup; see " + log.name)
                time.sleep(0.5)
        raise RuntimeError("app did not start")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    if not Path(CHROMIUM).exists():
        pytest.skip("Chromium not available")
    from services.library.config import config_from_env

    if config_from_env().model_path("clip_vit_b32_laion2b_s34b_b79k") is None:
        pytest.skip("models not provisioned")
    base = tmp_path_factory.mktemp("e2e")
    files = base / "upload"
    files.mkdir()
    man = json.loads((FIX / "manifest.json").read_text())
    chosen = ["li_hiring_python", "li_skew", "li_skew_variant", "cat", "coffee", "adversarial", "film_a", "film_b"]
    for k in chosen:
        shutil.copy(FIX / man[k]["file"], files / f"upload_{k}{Path(man[k]['file']).suffix}")
    from tests.support.image_factory import make_text_image

    make_text_image(files / "IMG_0001_q9z.png", ["feature store", "online serving"])
    many = base / "many"
    many.mkdir()
    for i in range(42):  # > one gallery page
        Image.new("RGB", (64, 48), (i * 5 % 255, 80, 160)).save(many / f"tile_{i:02d}.png")
    app = App(base / "lib")
    app.start()
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(executable_path=CHROMIUM)
    page = browser.new_page(viewport={"width": 1500, "height": 1100})
    page.set_default_timeout(60000)
    yield {"app": app, "page": page, "files": files, "many": many, "base": base, "browser": browser}
    browser.close()
    pw.stop()
    app.stop()


def _text(page, sel: str) -> str:
    return page.locator(sel).inner_text()


_SEQ = re.compile(r"Search #(\d+)")


def _seq(page) -> int:
    m = _SEQ.search(page.locator("#ax-search-notes").inner_text())
    return int(m.group(1)) if m else 0


def _search(page, q: str) -> None:
    """Run a query and wait for a *new* search number (never accept stale output)."""
    before = _seq(page)
    page.locator("#ax-query textarea").fill(q)
    page.locator("#ax-search").click()
    page.wait_for_function(
        "b => { const m = /Search #(\\d+)/.exec(document.querySelector('#ax-search-notes').innerText);"
        " return m && parseInt(m[1]) > b; }", arg=before)
    time.sleep(0.7)


def _captions(page) -> list[str]:
    return [c.strip() for c in page.locator("#ax-gallery .caption-label").all_inner_texts()]


def pick_collection(page, text: str, attempts: int = 6) -> None:
    """Open the collection dropdown and choose the option containing ``text``.

    The list is refreshed when the tab opens; if the update has not landed yet,
    use the Reload button and retry instead of reading a stale (empty) list."""
    for _ in range(attempts):
        dd = page.locator("#ax-col-pick input")
        dd.click()
        time.sleep(0.5)
        options = [o for o in page.get_by_role("option").all_inner_texts() if text in o]
        if options:
            page.get_by_role("option").filter(has_text=options[0]).first.click()
            page.wait_for_function(
                "t => document.querySelector('#ax-col-head').innerText.includes(t)", arg=text)
            return
        page.keyboard.press("Escape")
        page.locator("#ax-col-reload").click()
        time.sleep(2)
    raise AssertionError(f"collection option containing {text!r} never appeared")


def _wait_analyzed(page, n: int, timeout: float = 600) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        page.locator("#ax-refresh").click()
        time.sleep(2)
        caps = _captions(page)
        if len(caps) >= n and not any("⏳" in c for c in caps):
            return
    raise AssertionError(f"analysis did not finish: {_captions(page)}")


def test_01_import_batch_and_analysis(setup):
    page, files = setup["page"], setup["files"]
    page.goto(setup["app"].url)
    page.get_by_role("tab", name="Library").click()
    page.locator("#ax-upload input[type=file]").set_input_files(sorted(str(p) for p in files.iterdir()))
    page.wait_for_timeout(1500)
    page.locator("#ax-import").click()
    page.wait_for_function("document.querySelector('#ax-import-result').innerText.includes('Imported batch')")
    assert "9 new" in _text(page, "#ax-import-result")
    _wait_analyzed(page, 9)
    assert all("✅" in c for c in _captions(page)), _captions(page)


def test_02_text_search_highlights_matching_region(setup):
    page = setup["page"]
    _search(page, 'text:"feature store"')
    caps = _captions(page)
    assert len(caps) == 1 and "IMG_0001_q9z.png" in caps[0] and "OCR_PHRASE" in caps[0]
    page.locator("#ax-gallery .thumbnail-item").first.click()
    page.wait_for_function("document.querySelector('#ax-evidence').innerText.includes('OCR_PHRASE')")
    assert "feature store" in _text(page, "#ax-evidence")
    # The inspector image carries the drawn highlight: count highlight-colored pixels.
    img = page.locator("#ax-inspector img").first
    img.wait_for()
    shot = Image.open(io.BytesIO(img.screenshot())).convert("RGB")
    a = np.asarray(shot).astype(int)
    yellow = ((abs(a[..., 0] - 255) < 40) & (abs(a[..., 1] - 196) < 60) & (a[..., 2] < 90)).sum()
    assert yellow > 50, yellow


def test_03_context_filters_objects_and_errors(setup):
    page = setup["page"]
    _search(page, "a cat")
    assert "upload_cat" in _captions(page)[0]
    _search(page, "object:cat")
    assert any("upload_cat" in c and "OBJECT_DETECTION" in c for c in _captions(page))
    _search(page, 'source:linkedin text:"hiring"')
    caps = _captions(page)
    assert any("upload_li_hiring_python" in c for c in caps) and not any("adversarial" in c for c in caps)
    _search(page, "colour:red")
    assert "unknown filter" in _text(page, "#ax-search-notes")


def test_04_similar_and_crop(setup):
    page = setup["page"]
    _search(page, "a cup of coffee")
    page.locator("#ax-gallery .thumbnail-item").first.click()
    page.wait_for_function("document.querySelector('#ax-inspector-head').innerText.includes('upload_coffee')")
    page.get_by_role("tab", name="Similar").click()
    for sel, v in (("#ax-cx0 input", "0.2"), ("#ax-cy0 input", "0.2"), ("#ax-cx1 input", "0.8"), ("#ax-cy1 input", "0.8")):
        page.locator(sel).fill(v)
    page.locator("#ax-similar").click()
    page.wait_for_function("document.querySelector('#ax-search-notes').innerText.includes('Similar to')")
    assert "crop" in _text(page, "#ax-search-notes")


def test_05_annotations_persist(setup):
    page = setup["page"]
    _search(page, "a cat")
    page.locator("#ax-gallery .thumbnail-item").first.click()
    page.wait_for_function("document.querySelector('#ax-inspector-head').innerText.includes('upload_cat')")
    page.get_by_role("tab", name="Annotations").click()
    page.locator("#ax-title textarea").fill("Office cat")
    page.locator("#ax-tags textarea").fill("pets, favorites")
    page.locator("#ax-save-ann").click()
    page.wait_for_function("document.querySelector('#ax-save-msg').innerText.includes('Saved')")
    _search(page, "tag:favorites")
    assert len(_captions(page)) == 1 and "upload_cat" in _captions(page)[0]


def test_06_retry_and_stage_status(setup):
    page = setup["page"]
    _search(page, 'text:"feature store"')
    page.locator("#ax-gallery .thumbnail-item").first.click()
    page.get_by_role("tab", name="Stages").click()
    page.locator("#ax-retry").click()
    page.wait_for_function("document.querySelector('#ax-stage-msg').innerText.includes('Queued job')")
    page.locator("#ax-cancel").click()
    page.wait_for_function("document.querySelector('#ax-stage-msg').innerText.match(/Cancellation|No queued/)")
    rows = page.locator("#ax-stages").inner_text()
    assert "ocr" in rows and "pixels" in rows


def test_07_pagination(setup):
    page = setup["page"]
    page.get_by_role("tab", name="Library").click()
    page.locator("#ax-folder textarea").fill(str(setup["many"]))
    page.locator("#ax-import-folder").click()
    page.wait_for_function("document.querySelector('#ax-import-result').innerText.includes('42 new')")
    page.locator("#ax-query textarea").fill("")
    page.locator("#ax-refresh").click()
    time.sleep(1.5)
    first = _captions(page)
    assert len(first) == 40
    page.locator("#ax-next").click()
    time.sleep(1.5)
    second = _captions(page)
    assert 0 < len(second) <= 11 and not set(second) & set(first)


def test_08_collections_rename_exclude_export(setup):
    page = setup["page"]
    page.get_by_role("tab", name="Collections").click()
    pick_collection(page, "LinkedIn screenshots")
    page.locator("#ax-col-label textarea").fill("My LinkedIn saves")
    page.locator("#ax-col-rename").click()
    page.wait_for_function("document.querySelector('#ax-col-head').innerText.includes('My LinkedIn saves')")
    member = page.locator("#ax-col-members tbody tr").first.locator("td").first.inner_text().strip()
    page.locator("#ax-col-assets textarea").fill(member)
    page.locator("#ax-col-exclude").click()
    page.wait_for_function("document.querySelector('#ax-col-msg').innerText.includes('exclude applied')")
    assert "excluded" in page.locator("#ax-col-members").inner_text()
    page.locator("#ax-export").click()
    page.wait_for_function("document.querySelector('#ax-export-msg').innerText.includes('Exported')")
    setup["excluded"] = member


def test_09_restart_recovers_library_and_corrections(setup):
    app, page = setup["app"], setup["page"]
    app.stop()
    app.start()
    page.goto(app.url)
    page.get_by_role("tab", name="Library").click()
    _search(page, 'text:"feature store"')   # issued right away: must not be overwritten by the page-load listing
    time.sleep(2)
    assert len(_captions(page)) == 1
    _search(page, "tag:favorites")
    assert "upload_cat" in _captions(page)[0]
    page.get_by_role("tab", name="Collections").click()
    pick_collection(page, "My LinkedIn saves")
    assert "excluded" in page.locator("#ax-col-members").inner_text()
