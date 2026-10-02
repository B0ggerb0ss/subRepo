"""After provisioning, import -> full analysis -> search works with the network off.

Outbound sockets to anything but loopback raise, so any hidden download or
cloud fallback would fail this test.
"""
from __future__ import annotations

import socket
from pathlib import Path

import pytest

from services.library.config import config_from_env
from services.library.registry import Library
from services.library.worker import Worker
from tests.support.image_factory import make_text_image

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "images"


@pytest.fixture
def no_network(monkeypatch):
    attempts: list = []
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and (host.startswith("127.") or host in {"::1", "localhost"} or host.startswith("/")):
            return real_connect(self, address)
        attempts.append(address)
        raise OSError(f"network disabled in test: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded)
    monkeypatch.setattr(socket, "create_connection",
                        lambda address, *a, **k: (attempts.append(address), (_ for _ in ()).throw(
                            OSError(f"network disabled in test: {address!r}")))[1])
    return attempts


def test_full_analysis_and_search_offline(tmp_path: Path, no_network) -> None:
    cfg = config_from_env(tmp_path / "lib")
    if cfg.model_path("clip_vit_b32_laion2b_s34b_b79k") is None:
        pytest.skip("models not provisioned")
    fx = make_text_image(tmp_path / "in" / "x1.png", ["offline feature store"])
    lib = Library(cfg)
    ids = lib.import_files([fx["path"], FIX / "cat.png"]).asset_ids
    assert Worker(cfg, lib.repo).run_until_idle() == ["complete", "complete"]
    assert [h.asset_id for h in lib.search('text:"offline feature store"').hits] == [ids[0]]
    assert lib.search("a cat").hits[0].asset_id == ids[1]
    assert lib.search("object:cat").hits[0].asset_id == ids[1]
    assert no_network == []          # nothing even tried to leave the machine
    lib.close()
