#!/usr/bin/env python3
"""Drive the real app through the user walkthrough and save screenshots to docs/walkthrough/.

import -> search image text -> context/object search -> find similar -> review LinkedIn
collection -> correct a group -> restart -> export. Uses the committed test fixtures.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.e2e.test_browser_flows import CHROMIUM, FIX, App, _captions, _search, fill_stable, pick_collection  # noqa: E402

OUT = ROOT / "docs" / "walkthrough"


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="ax-walk-"))
    up = base / "upload"
    up.mkdir()
    man = json.loads((FIX / "manifest.json").read_text())
    for k, rec in man.items():
        shutil.copy(FIX / rec["file"], up / f"{k}{Path(rec['file']).suffix}")
    from tests.support.image_factory import make_text_image

    make_text_image(up / "IMG_0001_q9z.png", ["feature store", "online serving"])
    from tests.support.video_factory import make_text_video

    make_text_video(up / "MVI_0042.mp4", [{"text": "quarterly roadmap review", "start": 4, "end": 8, "x": 120, "y": 220}],
                    duration=12.0, audio=True)
    app = App(base / "lib")
    app.start()
    pw = sync_playwright().start()
    browser = pw.chromium.launch(executable_path=CHROMIUM)
    page = browser.new_page(viewport={"width": 1500, "height": 1150})
    page.set_default_timeout(90000)
    shots = []

    def shot(name: str, caption: str) -> None:
        page.screenshot(path=str(OUT / f"{name}.png"))
        shots.append((name, caption))

    try:
        page.goto(app.url)
        page.get_by_role("tab", name="Library").click()
        page.locator("#ax-upload input[type=file]").set_input_files(sorted(str(p) for p in up.iterdir()))
        page.wait_for_timeout(1500)
        page.locator("#ax-import").click()
        page.wait_for_function("document.querySelector('#ax-import-result').innerText.includes('Imported batch')")
        for _ in range(300):
            page.locator("#ax-refresh").click()
            time.sleep(2)
            caps = _captions(page)
            if len(caps) >= 18 and not any("⏳" in c for c in caps):
                break
        shot("01_imported", "Batch imported and analyzed; capability badges and job counts at the top.")
        _search(page, 'text:"feature store"')
        shot("02_text_search_highlight", 'text:"feature store" finds an image named IMG_0001_q9z.png and highlights the OCR region.')
        _search(page, 'source:linkedin text:"hiring"')
        shot("03_source_and_text", "Visible-LinkedIn-UI source filter AND a literal OCR phrase, with evidence and typed decisions.")
        _search(page, "object:cat")
        shot("04_object_filter", "object:cat — the detector box that matched is drawn; score is a raw detector score.")
        _search(page, "a cup of coffee")
        page.get_by_role("tab", name="Similar").click()
        page.locator("#ax-similar").click()
        page.wait_for_function("document.querySelector('#ax-search-notes').innerText.includes('Similar to')")
        time.sleep(1)
        shot("05_find_similar", "Find similar from the inspected image (visual similarity, no fabricated boxes).")
        page.get_by_role("tab", name="Collections").click()
        pick_collection(page, "LinkedIn screenshots")
        page.wait_for_function("document.querySelector('#ax-col-head').innerText.includes('LinkedIn')")
        time.sleep(1)
        shot("06_linkedin_collection", "Smart set 'LinkedIn screenshots' with membership method, affinity and its kind.")
        fill_stable(page, "#ax-col-label textarea", "LinkedIn — saved for job hunt")
        page.locator("#ax-col-rename").click()
        page.wait_for_function("document.querySelector('#ax-col-head').innerText.includes('job hunt')")
        member = page.locator("#ax-col-members tbody tr").first.locator("td").first.inner_text().strip()
        fill_stable(page, "#ax-col-assets textarea", member)
        page.locator("#ax-col-exclude").click()
        page.wait_for_function("document.querySelector('#ax-col-msg').innerText.includes('exclude applied')")
        shot("07_correction", "Rename + exclude a member; recorded as corrections, kept across re-analysis.")
        page.get_by_role("tab", name="Library").click()
        _search(page, 'type:video text:"roadmap review"')
        page.locator("#ax-gallery .thumbnail-item").first.click()
        page.wait_for_function("document.querySelector('#ax-evidence').innerText.includes('▶ at')")
        page.get_by_role("tab", name="Evidence").click()
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(2)
        shot("08_video_text_at_time", 'A video\'s on-screen text: found at 0:04 and highlighted on that keyframe (MediaMetadata/1.2).')
        page.get_by_role("tab", name="Generate clips").click()
        time.sleep(1.5)
        page.locator("#ax-gen-library input").click()
        time.sleep(0.8)
        page.get_by_role("option").filter(has_text="MVI_0042.mp4").first.click()
        page.locator("#ax-gen-run").click()
        page.wait_for_function("document.querySelector('#ax-gen-status textarea').value.length > 0", timeout=600000)
        time.sleep(1)
        shot("09_generate_from_library", "Generate clips straight from the library video; the status says ASR is unavailable. (The test "
             "Chromium build has no H.264 decoder, hence 'not playable'; the clip is valid and downloadable.)")
        app.stop()
        app.start()
        page.goto(app.url)
        page.get_by_role("tab", name="Collections").click()
        pick_collection(page, "job hunt")
        page.wait_for_function("document.querySelector('#ax-col-head').innerText.includes('job hunt')")
        page.locator("#ax-export").click()
        page.wait_for_function("document.querySelector('#ax-export-msg').innerText.includes('Exported')")
        time.sleep(1)
        shot("10_after_restart_export", "After an app restart the renamed set and the exclusion are intact; snapshot exported.")
    except Exception:
        for log in base.glob("app-*.log"):
            print(log.read_text()[-4000:])
        raise
    finally:
        browser.close()
        pw.stop()
        app.stop()
        shutil.rmtree(base, ignore_errors=True)
    (OUT / "captions.json").write_text(json.dumps(dict(shots), indent=1))
    print(json.dumps(shots, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
