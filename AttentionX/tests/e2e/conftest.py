"""Save a screenshot and key panel texts when an e2e step fails."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ARTIFACTS = Path(os.getenv("ATTENTIONX_E2E_ARTIFACTS", "/tmp/attentionx-e2e"))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when != "call" or not rep.failed:
        return
    setup = item.funcargs.get("setup")
    if not setup:
        return
    page = setup["page"]
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(ARTIFACTS / f"{item.name}.png"), full_page=True)
        texts = {sel: page.locator(sel).inner_text() for sel in
                 ("#ax-search-notes", "#ax-inspector-head", "#ax-stage-msg", "#ax-col-msg") if page.locator(sel).count()}
        (ARTIFACTS / f"{item.name}.txt").write_text(repr(texts))
    except Exception as e:  # diagnostics must never mask the real failure
        (ARTIFACTS / f"{item.name}.txt").write_text(f"diagnostics failed: {e}")
