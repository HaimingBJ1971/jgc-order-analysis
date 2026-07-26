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
    / "multi_file_loader.py"
)
SPEC = importlib.util.spec_from_file_location("multi_file_loader", MODULE_PATH)
multi_file_loader = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = multi_file_loader
SPEC.loader.exec_module(multi_file_loader)

DB_MANAGER_PATH = (
    Path(__file__).resolve().parents[1]
    / "长期订单分析"
    / "db_manager.py"
)
DB_SPEC = importlib.util.spec_from_file_location("long_term_db_manager_for_loader_tests", DB_MANAGER_PATH)
db_manager = importlib.util.module_from_spec(DB_SPEC)
assert DB_SPEC.loader is not None
sys.modules[DB_SPEC.name] = db_manager
DB_SPEC.loader.exec_module(db_manager)


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


def _orders_df(order_id: str, source_amount: int = 100) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "订单号": order_id,
                "下单时间": "2026-06-01 12:00:00",
                "桌台": "大厅A01",
                "订单类型": "堂食",
                "订单收入": source_amount,
            }
        ]
    )


def _items_df(order_id: str, seq: int, revenue: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "序号": seq,
                "订单号": order_id,
                "商品编码": "D001",
                "商品名称": "测试菜",
                "商品数量": 1,
                "菜品收入": revenue,
            }
        ]
    )


def test_existing_order_reimport_still_provides_snapshot_items_for_replace(monkeypatch, tmp_path: Path) -> None:
    def fake_load_excel(path: str):
        return _orders_df("1001", 120), _items_df("1001", 9, 120)

    monkeypatch.setattr(multi_file_loader.os.path, "exists", lambda path: True)
    monkeypatch.setattr(multi_file_loader, "load_excel", fake_load_excel)

    result = multi_file_loader.load_and_dedup_excels(["monthly.xlsx"], existing_order_ids={"1001"})

    assert result["total_new"] == 0
    assert result["raw_orders"].empty
    assert result["raw_items"].empty
    assert len(result["snapshot_items"]) == 1

    db_path = tmp_path / "orders.db"
    manager = db_manager.DatabaseManager(str(db_path))
    manager.replace_items_for_orders(_items_df("1001", 1, 80), "weekly.xlsx")
    manager.replace_items_for_orders(result["snapshot_items"], "monthly.xlsx")
    manager.conn.close()

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT source_file, 原始数据 FROM items WHERE 订单号='1001'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "monthly.xlsx"
    assert json.loads(rows[0][1])["菜品收入"] == 120


def test_overlapping_files_keep_items_from_selected_order_snapshot(monkeypatch) -> None:
    def fake_load_excel(path: str):
        if path == "week.xlsx":
            return _orders_df("1001", 100), _items_df("1001", 100672, 100)
        return _orders_df("1001", 120), _items_df("1001", 14165, 120)

    monkeypatch.setattr(multi_file_loader.os.path, "exists", lambda path: True)
    monkeypatch.setattr(multi_file_loader, "load_excel", fake_load_excel)

    result = multi_file_loader.load_and_dedup_excels(["week.xlsx", "month.xlsx"], existing_order_ids=set())

    assert len(result["snapshot_orders"]) == 1
    assert result["snapshot_orders"].iloc[0]["source_file"] == "week.xlsx"
    assert len(result["snapshot_items"]) == 1
    assert result["snapshot_items"].iloc[0]["source_file"] == "week.xlsx"
    assert int(result["snapshot_items"].iloc[0]["序号"]) == 100672
    assert len(result["raw_items"]) == 1


def test_reimport_with_partial_new_orders_keeps_full_current_snapshot(monkeypatch) -> None:
    def fake_load_excel(path: str):
        orders = pd.DataFrame(
            [
                {
                    "订单号": "1001",
                    "下单时间": "2026-06-01 12:00:00",
                    "桌台": "大厅A01",
                    "订单类型": "堂食",
                    "订单收入": 100,
                },
                {
                    "订单号": "1002",
                    "下单时间": "2026-06-01 13:00:00",
                    "桌台": "大厅A02",
                    "订单类型": "堂食",
                    "订单收入": 120,
                },
            ]
        )
        items = pd.DataFrame(
            [
                {"序号": 1, "订单号": "1001", "商品编码": "D001", "商品名称": "测试菜", "菜品收入": 100},
                {"序号": 2, "订单号": "1002", "商品编码": "D002", "商品名称": "测试菜2", "菜品收入": 120},
            ]
        )
        return orders, items

    monkeypatch.setattr(multi_file_loader.os.path, "exists", lambda path: True)
    monkeypatch.setattr(multi_file_loader, "load_excel", fake_load_excel)

    result = multi_file_loader.load_and_dedup_excels(["current.xlsx"], existing_order_ids={"1001"})

    assert set(result["raw_orders"]["订单号"].astype(str)) == {"1002"}
    assert set(result["snapshot_orders"]["订单号"].astype(str)) == {"1001", "1002"}
    assert set(result["snapshot_items"]["订单号"].astype(str)) == {"1001", "1002"}
    assert result["pre_merge_daily"]["2026-06-01"]["原始订单数"] == 2


def test_replace_groups_for_scope_updates_existing_group_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "orders.db"
    manager = db_manager.DatabaseManager(str(db_path))

    old_groups = pd.DataFrame(
        [
            {
                "_date": "2026-06-01",
                "桌台": "大厅A01",
                "团体总额": 100,
                "订单收入": 100,
                "订单数": 1,
                "开始": "2026-06-01 12:00:00",
                "结束": "2026-06-01 12:30:00",
                "团体人数": 2,
                "主单订单号": "1001",
                "首单订单号": "1001",
                "包含订单": ["1001"],
                "人均消费": 50,
                "是否会员": False,
                "_area": "大厅",
                "_meal": "午餐",
                "_filter_status": "kept",
                "_opener": "甲",
            }
        ]
    )
    new_groups = old_groups.copy()
    new_groups.loc[0, "团体总额"] = 180
    new_groups.loc[0, "订单收入"] = 180

    assert manager.replace_groups_for_scope(old_groups) == 1
    assert manager.replace_groups_for_scope(new_groups) == 1
    manager.close()

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT group_amount, order_revenue FROM groups WHERE group_date='2026-06-01' AND table_name='大厅A01'"
    ).fetchone()
    assert row == (180.0, 180.0)


def _snapshot_orders(rows: list[tuple[str, str, str, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "订单号": order_id,
                "下单时间": "2026-06-01 12:00:00",
                "桌台": table_name,
                "订单类型": "堂食",
                "订单收入": revenue,
                "门店名称": (
                    "金谷仓家庭料理万荷餐厅"
                    if store_name == "万荷店"
                    else "金谷仓家庭料理保利餐厅"
                ),
            }
            for order_id, store_name, table_name, revenue in rows
        ]
    )


def _snapshot_items(rows: list[tuple[str, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "序号": index,
                "订单号": order_id,
                "商品编码": f"D{index:03d}",
                "商品名称": f"测试菜{index}",
                "商品数量": 1,
                "菜品收入": revenue,
            }
            for index, (order_id, revenue) in enumerate(rows, start=1)
        ]
    )


def _snapshot_groups(rows: list[tuple[str, str, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "_date": "2026-06-01",
                "桌台": table_name,
                "团体总额": revenue,
                "订单收入": revenue,
                "订单数": 1,
                "开始": "2026-06-01 12:00:00",
                "结束": "2026-06-01 12:30:00",
                "团体人数": 2,
                "主单订单号": order_id,
                "首单订单号": order_id,
                "包含订单": [order_id],
                "人均消费": revenue / 2,
                "是否会员": False,
                "_area": "大厅",
                "_meal": "午餐",
                "_filter_status": "kept",
                "_opener": "甲",
            }
            for order_id, table_name, revenue in rows
        ]
    )


def _snapshot_stats(store_name: str, revenue: int) -> dict:
    return {
        "overview_rows": [
            ("2026-06-01", store_name, "整体", "", revenue, 100.0, 2, revenue / 2),
        ],
        "order_count_rows": [
            ("2026-06-01", store_name, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1),
        ],
        "bucket_rows": [
            ("2026-06-01", store_name, "100-150", 1, 100.0),
        ],
        "opener_rows": [],
    }


def test_replace_pos_snapshot_removes_old_table_when_order_moves(tmp_path: Path) -> None:
    manager = db_manager.DatabaseManager(str(tmp_path / "orders.db"))
    manager.replace_pos_snapshot(
        _snapshot_orders([("1001", "万荷店", "大厅A01", 100)]),
        _snapshot_items([("1001", 100)]),
        _snapshot_groups([("1001", "大厅A01", 100)]),
        "first.xlsx",
        stats_result=_snapshot_stats("万荷店", 100),
    )

    result = manager.replace_pos_snapshot(
        _snapshot_orders([("1001", "万荷店", "大厅A02", 120)]),
        _snapshot_items([("1001", 120)]),
        _snapshot_groups([("1001", "大厅A02", 120)]),
        "corrected.xlsx",
        stats_result=_snapshot_stats("万荷店", 120),
    )

    assert result["old_groups_removed"] == 1
    rows = manager.conn.execute(
        "SELECT table_name, group_amount FROM groups ORDER BY table_name"
    ).fetchall()
    assert rows == [("大厅A02", 120.0)]
    raw_order = json.loads(
        manager.conn.execute(
            "SELECT 原始数据 FROM orders WHERE 订单号='1001'"
        ).fetchone()[0]
    )
    assert raw_order["桌台"] == "大厅A02"
    assert manager.conn.execute(
        "SELECT 营业额 FROM daily_overview "
        "WHERE date='2026-06-01' AND store_name='万荷店' "
        "AND category='整体' AND sub_category=''"
    ).fetchone()[0] == 120
    manager.close()


def test_replace_pos_snapshot_removes_orders_missing_from_complete_scope(tmp_path: Path) -> None:
    manager = db_manager.DatabaseManager(str(tmp_path / "orders.db"))
    manager.replace_pos_snapshot(
        _snapshot_orders([
            ("1001", "万荷店", "大厅A01", 100),
            ("1002", "万荷店", "大厅A02", 80),
        ]),
        _snapshot_items([("1001", 100), ("1002", 80)]),
        _snapshot_groups([
            ("1001", "大厅A01", 100),
            ("1002", "大厅A02", 80),
        ]),
        "first.xlsx",
        stats_result=_snapshot_stats("万荷店", 180),
    )

    result = manager.replace_pos_snapshot(
        _snapshot_orders([("1001", "万荷店", "大厅A01", 100)]),
        _snapshot_items([("1001", 100)]),
        _snapshot_groups([("1001", "大厅A01", 100)]),
        "corrected.xlsx",
        stats_result=_snapshot_stats("万荷店", 100),
    )

    assert result["stale_orders_removed"] == 1
    assert manager.conn.execute(
        "SELECT 订单号 FROM orders ORDER BY 订单号"
    ).fetchall() == [("1001",)]
    assert manager.conn.execute(
        "SELECT DISTINCT 订单号 FROM items ORDER BY 订单号"
    ).fetchall() == [("1001",)]
    assert manager.conn.execute(
        "SELECT table_name FROM groups ORDER BY table_name"
    ).fetchall() == [("大厅A01",)]
    manager.close()


def test_replace_pos_snapshot_preserves_same_table_from_other_store(tmp_path: Path) -> None:
    manager = db_manager.DatabaseManager(str(tmp_path / "orders.db"))
    manager.replace_pos_snapshot(
        _snapshot_orders([("1001", "万荷店", "大厅A01", 100)]),
        _snapshot_items([("1001", 100)]),
        _snapshot_groups([("1001", "大厅A01", 100)]),
        "wanhe.xlsx",
        stats_result=_snapshot_stats("万荷店", 100),
    )
    manager.replace_pos_snapshot(
        _snapshot_orders([("2001", "保利店", "大厅A01", 80)]),
        _snapshot_items([("2001", 80)]),
        _snapshot_groups([("2001", "大厅A01", 80)]),
        "baoli.xlsx",
        stats_result=_snapshot_stats("保利店", 80),
    )

    manager.replace_pos_snapshot(
        _snapshot_orders([("1001", "万荷店", "大厅A02", 120)]),
        _snapshot_items([("1001", 120)]),
        _snapshot_groups([("1001", "大厅A02", 120)]),
        "wanhe_corrected.xlsx",
        stats_result=_snapshot_stats("万荷店", 120),
    )

    groups = manager.conn.execute(
        "SELECT first_order_id, table_name, group_amount "
        "FROM groups ORDER BY first_order_id"
    ).fetchall()
    assert groups == [
        ("1001", "大厅A02", 120.0),
        ("2001", "大厅A01", 80.0),
    ]
    baoli_daily = manager.conn.execute(
        "SELECT 营业额 FROM daily_overview "
        "WHERE date='2026-06-01' AND store_name='保利店' "
        "AND category='整体' AND sub_category=''"
    ).fetchone()
    assert baoli_daily == (80.0,)
    manager.close()


def test_replace_pos_snapshot_rolls_back_all_tables_on_group_failure(tmp_path: Path) -> None:
    manager = db_manager.DatabaseManager(str(tmp_path / "orders.db"))
    manager.replace_pos_snapshot(
        _snapshot_orders([("1001", "万荷店", "大厅A01", 100)]),
        _snapshot_items([("1001", 100)]),
        _snapshot_groups([("1001", "大厅A01", 100)]),
        "first.xlsx",
        stats_result=_snapshot_stats("万荷店", 100),
    )
    duplicate_groups = pd.concat(
        [
            _snapshot_groups([("1001", "大厅A02", 120)]),
            _snapshot_groups([("1001", "大厅A02", 120)]),
        ],
        ignore_index=True,
    )

    with pytest.raises(sqlite3.IntegrityError):
        manager.replace_pos_snapshot(
            _snapshot_orders([("1001", "万荷店", "大厅A02", 120)]),
            _snapshot_items([("1001", 120)]),
            duplicate_groups,
            "broken.xlsx",
            stats_result=_snapshot_stats("万荷店", 120),
        )

    raw_order = json.loads(
        manager.conn.execute(
            "SELECT 原始数据 FROM orders WHERE 订单号='1001'"
        ).fetchone()[0]
    )
    assert raw_order["桌台"] == "大厅A01"
    assert manager.conn.execute(
        "SELECT table_name, group_amount FROM groups"
    ).fetchall() == [("大厅A01", 100.0)]
    assert manager.conn.execute(
        "SELECT 营业额 FROM daily_overview "
        "WHERE date='2026-06-01' AND store_name='万荷店' "
        "AND category='整体' AND sub_category=''"
    ).fetchone() == (100.0,)
    manager.close()


def test_build_merged_dataset_prefers_current_snapshot_over_context() -> None:
    current = _snapshot_orders([("1001", "万荷店", "大厅A02", 120)])
    context = _snapshot_orders([("1001", "万荷店", "大厅A01", 100)]).to_dict("records")
    items = _snapshot_items([("1001", 120)])

    merged_orders, _merged_items = multi_file_loader.build_merged_dataset(
        current,
        items,
        context,
        items,
    )

    assert len(merged_orders) == 1
    assert merged_orders.iloc[0]["桌台"] == "大厅A02"
