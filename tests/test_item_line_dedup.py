from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd


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
