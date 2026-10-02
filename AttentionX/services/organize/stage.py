"""Post-commit pipeline stage: incremental organization for the analyzed asset."""
from __future__ import annotations

import json

from services.analyze.pipeline import Ctx, StageResult, register_post_commit
from services.organize.service import organize_asset


def _organize(ctx: Ctx) -> StageResult:
    out = organize_asset(ctx.repo, ctx.cfg, ctx.asset.id)
    status = "complete" if ctx.cfg.features.clustering else "disabled"
    return StageResult(status, detail=json.dumps(out, sort_keys=True)[:400])


register_post_commit("organize", _organize)
