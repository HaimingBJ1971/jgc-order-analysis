from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


LONG_TERM_DIR = Path(__file__).resolve().parents[1] / "长期订单分析"
SKILL_DIR = Path(__file__).resolve().parents[1] / "每日订单分析" / "order_merger_skill"
sys.path.insert(0, str(LONG_TERM_DIR))
sys.path.insert(0, str(SKILL_DIR))

MODULE_PATH = LONG_TERM_DIR / "backfill_from_archives.py"
SPEC = importlib.util.spec_from_file_location("backfill_from_archives", MODULE_PATH)
backfill = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = backfill
SPEC.loader.exec_module(backfill)


def test_archive_backfill_uses_selected_snapshot_instead_of_mixing_archive_packages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    older = tmp_path / "万荷店内订单明细2026-01-01+00_00_00~2026-01-07+23_59_59.xlsx"
    newer = tmp_path / "万荷店内订单明细2026-01-07+00_00_00~2026-01-14+23_59_59.xlsx"
    older.touch()
    newer.touch()

    def fake_load_excel(path: str):
        name = Path(path).name
        if name == older.name:
            orders = pd.DataFrame([{"订单号": "1001", "门店名称": "金谷仓家庭料理万荷餐厅"}])
            items = pd.DataFrame(
                [
                    {
                        "序号": 1,
                        "订单号": "1001",
                        "商品编码": "SKU589",
                        "商品名称": "杨梅马蹄气泡水",
                        "数量": 10,
                    },
                    {
                        "序号": 2,
                        "订单号": "1001",
                        "商品编码": "SKU589",
                        "商品名称": "杨梅马蹄气泡水",
                        "数量": 3,
                    },
                ]
            )
        else:
            orders = pd.DataFrame([{"订单号": "1001", "门店名称": "金谷仓家庭料理万荷餐厅"}])
            items = pd.DataFrame(
                [
                    {
                        "序号": 1,
                        "订单号": "1001",
                        "商品编码": "SKU589",
                        "商品名称": "杨梅马蹄气泡水",
                        "数量": 11,
                    }
                ]
            )
        return orders, items

    monkeypatch.setattr(backfill, "load_excel", fake_load_excel)

    orders_df, items_df = backfill.load_merged_archives([older, newer])

    assert len(orders_df) == 1
    assert len(items_df) == 1
    assert items_df.iloc[0]["source_file"] == newer.name
    assert items_df["数量"].sum() == 11
    assert items_df["序号"].tolist() == [1]


def test_archive_backfill_uses_items_from_selected_order_snapshot_when_sequence_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    older = tmp_path / "万荷店内订单明细2026-01-01+00_00_00~2026-01-07+23_59_59.xlsx"
    newer = tmp_path / "万荷店内订单明细2026-01-07+00_00_00~2026-01-14+23_59_59.xlsx"
    older.touch()
    newer.touch()

    def fake_load_excel(path: str):
        name = Path(path).name
        if name == older.name:
            orders = pd.DataFrame([{"订单号": "1001", "门店名称": "金谷仓家庭料理万荷餐厅"}])
            items = pd.DataFrame(
                [
                    {
                        "序号": 100672,
                        "订单号": "1001",
                        "商品编码": "SKU589",
                        "商品名称": "杨梅马蹄气泡水",
                        "菜品收入": 100,
                    }
                ]
            )
        else:
            orders = pd.DataFrame([{"订单号": "1001", "门店名称": "金谷仓家庭料理万荷餐厅"}])
            items = pd.DataFrame(
                [
                    {
                        "序号": 14165,
                        "订单号": "1001",
                        "商品编码": "SKU589",
                        "商品名称": "杨梅马蹄气泡水",
                        "菜品收入": 120,
                    }
                ]
            )
        return orders, items

    monkeypatch.setattr(backfill, "load_excel", fake_load_excel)

    orders_df, items_df = backfill.load_merged_archives([older, newer])

    assert len(orders_df) == 1
    assert orders_df.iloc[0]["source_file"] == newer.name
    assert len(items_df) == 1
    assert items_df.iloc[0]["source_file"] == newer.name
    assert int(items_df.iloc[0]["序号"]) == 14165
    assert int(items_df.iloc[0]["菜品收入"]) == 120
