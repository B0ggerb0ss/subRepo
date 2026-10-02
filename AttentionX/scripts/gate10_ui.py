"""Gate 10 — UI validation."""
from __future__ import annotations

import os
import sys

from gate_common import check, summarize

import app


class _DummyQueuedDemo:
    def __init__(self, captured: dict) -> None:
        self.captured = captured

    def launch(self, **kwargs) -> None:
        self.captured.update(kwargs)


class _DummyDemo:
    def __init__(self, captured: dict) -> None:
        self.captured = captured

    def queue(self, default_concurrency_limit: int = 1) -> _DummyQueuedDemo:
        self.captured["default_concurrency_limit"] = default_concurrency_limit
        return _DummyQueuedDemo(self.captured)


def main() -> int:
    print("\n=== Gate 10 — UI ===\n")

    demo = app.build_demo()
    labels = {
        getattr(component, "label", None)
        for component in demo.blocks.values()
        if getattr(component, "label", None)
    }

    captured: dict = {}
    original_demo = app.demo
    old_server_name = os.environ.get("ATTENTIONX_SERVER_NAME")
    old_server_port = os.environ.get("ATTENTIONX_SERVER_PORT")
    old_no_block = os.environ.get("ATTENTIONX_NO_BLOCK")

    os.environ["ATTENTIONX_SERVER_NAME"] = "127.0.0.1"
    os.environ["ATTENTIONX_SERVER_PORT"] = "7865"
    os.environ["ATTENTIONX_NO_BLOCK"] = "1"
    app.demo = _DummyDemo(captured)
    try:
        app.launch_demo()
    finally:
        app.demo = original_demo
        if old_server_name is None:
            os.environ.pop("ATTENTIONX_SERVER_NAME", None)
        else:
            os.environ["ATTENTIONX_SERVER_NAME"] = old_server_name
        if old_server_port is None:
            os.environ.pop("ATTENTIONX_SERVER_PORT", None)
        else:
            os.environ["ATTENTIONX_SERVER_PORT"] = old_server_port
        if old_no_block is None:
            os.environ.pop("ATTENTIONX_NO_BLOCK", None)
        else:
            os.environ["ATTENTIONX_NO_BLOCK"] = old_no_block

    results = [
        check(
            "all primary UI components are present",
            lambda: {
                "Upload Long-Form Video",
                "Reference Shorts (optional — for style matching)",
                "Status",
                "Clip 1",
                "Clip 2",
                "Clip 3",
                "Download All Clips",
            }.issubset(labels)
            or (_ for _ in ()).throw(RuntimeError(f"labels={sorted(label for label in labels if label)}")),
        ),
        check(
            "demo title is AttentionX",
            lambda: demo.title == "AttentionX" or (_ for _ in ()).throw(RuntimeError(f"title={demo.title}")),
        ),
        check(
            "launch_demo wires queue and launch settings correctly",
            lambda: (
                captured.get("default_concurrency_limit") == 1
                and captured.get("server_name") == "127.0.0.1"
                and captured.get("server_port") == 7865
                and captured.get("prevent_thread_lock") is True
                and captured.get("show_error") is True
            )
            or (_ for _ in ()).throw(RuntimeError(f"captured={captured}")),
        ),
    ]
    return summarize(10, results)


if __name__ == "__main__":
    sys.exit(main())
