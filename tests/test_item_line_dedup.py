from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "长期订单分析"
    / "db_manager.py"
)
SPEC = importlib.util.spec_from_file_location("long_term_db_manager", MODULE_PATH)
db_manager = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = db_manager
SPEC.loader.exec_module(db_manager)


def test_insert_items_keeps_repeated_same_product_lines(tmp_path: Path) -> None:
    db_path = tmp_path / "orders.db"
    manager = db_manager.DatabaseManager(str(db_path))

    items = pd.DataFrame(
        [
            {
                "序号": 1,
                "订单号": "112606251701474802700038",
                "商品编码": "DRINK001",
                "商品名称": "杨梅马蹄气泡水",
                "商品数量": 10,
                "菜品收入": 380,
            },
            {
                "序号": 2,
                "订单号": "112606251701474802700038",
                "商品编码": "DRINK001",
                "商品名称": "杨梅马蹄气泡水",
                "商品数量": 3,
                "菜品收入": 114,
            },
        ]
    )

    assert manager.insert_items(items, "万荷店内订单明细.xlsx") == 2
    manager.conn.close()

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT 原始数据 FROM items WHERE 商品名称='杨梅马蹄气泡水'"
    ).fetchall()

    assert len(rows) == 2
    assert sum(json.loads(raw)["商品数量"] for (raw,) in rows) == 13


def test_reinsert_same_source_and_same_pos_sequence_updates_not_duplicates(tmp_path: Path) -> None:
    db_path = tmp_path / "orders.db"
    manager = db_manager.DatabaseManager(str(db_path))

    first = pd.DataFrame(
        [
            {
                "序号": 1,
                "订单号": "112606251701474802700038",
                "商品编码": "DRINK001",
                "商品名称": "杨梅马蹄气泡水",
                "商品数量": 10,
                "菜品收入": 380,
            }
        ]
    )
    corrected = first.copy()
    corrected.loc[0, "商品数量"] = 11
    corrected.loc[0, "菜品收入"] = 418

    manager.insert_items(first, "万荷店内订单明细.xlsx")
    manager.insert_items(corrected, "万荷店内订单明细.xlsx")
    manager.conn.close()

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT 原始数据 FROM items WHERE 商品名称='杨梅马蹄气泡水'"
    ).fetchall()

    assert len(rows) == 1
    assert json.loads(rows[0][0])["商品数量"] == 11


def test_replace_items_for_orders_replaces_cross_source_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "orders.db"
    manager = db_manager.DatabaseManager(str(db_path))

    weekly = pd.DataFrame(
        [
            {
                "序号": 100672,
                "订单号": "112606251701474802700038",
                "商品编码": "DRINK001",
                "商品名称": "杨梅马蹄气泡水",
                "商品数量": 10,
                "菜品收入": 380,
            }
        ]
    )
    monthly = pd.DataFrame(
        [
            {
                "序号": 14165,
                "订单号": "112606251701474802700038",
                "商品编码": "DRINK001",
                "商品名称": "杨梅马蹄气泡水",
                "商品数量": 11,
                "菜品收入": 418,
            }
        ]
    )

    assert manager.replace_items_for_orders(weekly, "weekly.xlsx") == 1
    assert manager.replace_items_for_orders(monthly, "monthly.xlsx") == 1
    manager.conn.close()

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT source_file, item_line_key, 原始数据 FROM items WHERE 订单号=?",
        ("112606251701474802700038",),
    ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "monthly.xlsx"
    assert rows[0][1] == "112606251701474802700038|seq:14165"
    assert json.loads(rows[0][2])["商品数量"] == 11


def test_replace_orders_updates_existing_order_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "orders.db"
    manager = db_manager.DatabaseManager(str(db_path))

    weekly = pd.DataFrame(
        [
            {
                "订单号": "112606251701474802700038",
                "订单收入": 380,
                "桌台": "大厅A01",
            }
        ]
    )
    monthly = pd.DataFrame(
        [
            {
                "订单号": "112606251701474802700038",
                "订单收入": 418,
                "桌台": "大厅A01",
            }
        ]
    )

    assert manager.replace_orders(weekly, "weekly.xlsx") == 1
    assert manager.replace_orders(monthly, "monthly.xlsx") == 1
    manager.conn.close()

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT source_file, 原始数据 FROM orders WHERE 订单号=?",
        ("112606251701474802700038",),
    ).fetchone()

    assert row[0] == "monthly.xlsx"
    assert json.loads(row[1])["订单收入"] == 418


def test_replace_items_for_orders_keeps_repeated_same_product_lines(tmp_path: Path) -> None:
    db_path = tmp_path / "orders.db"
    manager = db_manager.DatabaseManager(str(db_path))

    items = pd.DataFrame(
        [
            {
                "序号": 1,
                "订单号": "112606251701474802700038",
                "商品编码": "DRINK001",
                "商品名称": "杨梅马蹄气泡水",
                "商品数量": 10,
                "菜品收入": 380,
            },
            {
                "序号": 2,
                "订单号": "112606251701474802700038",
                "商品编码": "DRINK001",
                "商品名称": "杨梅马蹄气泡水",
                "商品数量": 3,
                "菜品收入": 114,
            },
        ]
    )

    assert manager.replace_items_for_orders(items, "monthly.xlsx") == 2
    manager.conn.close()

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT 原始数据 FROM items WHERE 订单号=?",
        ("112606251701474802700038",),
    ).fetchall()

    assert len(rows) == 2
    assert sum(json.loads(raw)["商品数量"] for (raw,) in rows) == 13


def test_period_compare_closure_validation_catches_doubled_items() -> None:
    comparator_path = (
        Path(__file__).resolve().parents[1]
        / "周期对比分析"
        / "comparator.py"
    )
    spec = importlib.util.spec_from_file_location("period_comparator", comparator_path)
    comparator = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = comparator
    spec.loader.exec_module(comparator)

    class FakeDB:
        def get_order_revenue_for_period(self, start, end, store_name=None):
            return 100.0

        def get_all_items_for_period(self, start, end, store_name=None):
            item = {
                "订单号": "112606251701474802700038",
                "商品名称": "杨梅马蹄气泡水",
                "菜品销售类型": "单品",
                "菜品收入": 100.0,
            }
            raw = json.dumps(item, ensure_ascii=False)
            return [
                ("112606251701474802700038", raw, "weekly.xlsx", "2026-07-01"),
                ("112606251701474802700038", raw, "monthly.xlsx", "2026-07-01"),
            ]

    with pytest.raises(ValueError, match="POS商品归因收入未闭合"):
        comparator.validate_pos_item_revenue_closure(
            FakeDB(), "2026-06-01", "2026-06-30", "万荷店"
        )


def test_compute_comparison_blocks_doubled_items_before_report_data() -> None:
    comparator_path = (
        Path(__file__).resolve().parents[1]
        / "周期对比分析"
        / "comparator.py"
    )
    spec = importlib.util.spec_from_file_location("period_comparator_compute", comparator_path)
    comparator = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = comparator
    spec.loader.exec_module(comparator)

    class FakeDB:
        def get_order_revenue_for_period(self, start, end, store_name=None):
            return 100.0

        def get_all_items_for_period(self, start, end, store_name=None):
            item = {
                "订单号": "112606251701474802700038",
                "商品名称": "杨梅马蹄气泡水",
                "菜品销售类型": "单品",
                "菜品收入": 100.0,
            }
            raw = json.dumps(item, ensure_ascii=False)
            return [
                ("112606251701474802700038", raw, "weekly.xlsx", "2026-07-01"),
                ("112606251701474802700038", raw, "monthly.xlsx", "2026-07-01"),
            ]

    period_info = {
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
    }
    comparison_info = {
        "ringbi_start": "2026-05-01",
        "ringbi_end": "2026-05-31",
        "tongbi_start": "2025-06-01",
        "tongbi_end": "2025-06-30",
    }

    with pytest.raises(ValueError, match="POS商品归因收入未闭合"):
        comparator.compute_comparison(FakeDB(), period_info, comparison_info, "month", "万荷店")
