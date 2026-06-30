from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "长期订单分析"
    / "multi_file_loader.py"
)
SPEC = importlib.util.spec_from_file_location("multi_file_loader", MODULE_PATH)
multi_file_loader = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = multi_file_loader
SPEC.loader.exec_module(multi_file_loader)


def test_pre_merge_counts_can_be_accumulated_per_store_without_cross_store_mix() -> None:
    counts_by_store: dict[str, dict] = {"万荷店": {}, "保利店": {}}
    total: dict = {}

    multi_file_loader._add_pre_merge_counts(
        counts_by_store["万荷店"],
        "2026-06-22",
        count_raw=51,
        waimai=2,
        fei_tangshi=0,
    )
    multi_file_loader._add_pre_merge_counts(
        counts_by_store["保利店"],
        "2026-06-22",
        count_raw=21,
        waimai=0,
        fei_tangshi=0,
    )
    multi_file_loader._add_pre_merge_counts(
        total,
        "2026-06-22",
        count_raw=51,
        waimai=2,
        fei_tangshi=0,
    )
    multi_file_loader._add_pre_merge_counts(
        total,
        "2026-06-22",
        count_raw=21,
        waimai=0,
        fei_tangshi=0,
    )

    assert counts_by_store["万荷店"]["2026-06-22"]["原始订单数"] == 51
    assert counts_by_store["保利店"]["2026-06-22"]["原始订单数"] == 21
    assert total["2026-06-22"]["原始订单数"] == 72
