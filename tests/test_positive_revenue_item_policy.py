import json
import sys
import importlib.util
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "周期对比分析"))
sys.path.insert(0, str(ROOT / "饮品订单统计"))

from comparator import (  # noqa: E402
    _calc_category_distribution,
    _calc_dish_rankings,
    _calc_drink_dessert_rankings,
)
from generate_drink_order_stats_pdf import CATEGORIES, NON_ALCOHOL_CATS, _positive_revenue_items  # noqa: E402

DB_MANAGER_PATH = ROOT / "长期订单分析" / "db_manager.py"
DB_SPEC = importlib.util.spec_from_file_location("long_term_db_for_revenue_policy", DB_MANAGER_PATH)
long_term_db = importlib.util.module_from_spec(DB_SPEC)
assert DB_SPEC.loader is not None
sys.modules[DB_SPEC.name] = long_term_db
DB_SPEC.loader.exec_module(long_term_db)

TAKEAWAY_DB_PATH = ROOT / "平台外卖统计" / "db_manager.py"
TAKEAWAY_SPEC = importlib.util.spec_from_file_location("takeaway_db_for_revenue_policy", TAKEAWAY_DB_PATH)
takeaway_db = importlib.util.module_from_spec(TAKEAWAY_SPEC)
assert TAKEAWAY_SPEC.loader is not None
sys.modules[TAKEAWAY_SPEC.name] = takeaway_db
TAKEAWAY_SPEC.loader.exec_module(takeaway_db)


def _item_row(data: dict):
    return (None, json.dumps(data, ensure_ascii=False), None, None)


def test_item_rankings_exclude_all_zero_revenue_quantities_not_only_gifts():
    """118 总量、4 份赠送、9 份全额优惠时，正收入销量必须是 105 而不是 114。"""
    items = [
        _item_row({
            "商品名称": "朝日啤酒（黄啤）",
            "商品中类": "啤酒",
            "数量": 105,
            "菜品收入": 2940,
        }),
        _item_row({
            "商品名称": "朝日啤酒（黄啤）",
            "商品中类": "啤酒",
            "数量": 4,
            "菜品收入": 0,
            "零收入原因": "赠送",
        }),
        _item_row({
            "商品名称": "朝日啤酒（黄啤）",
            "商品中类": "啤酒",
            "数量": 9,
            "菜品收入": 0,
            "零收入原因": "免单/全额优惠",
        }),
    ]

    drink_rank = dict(_calc_drink_dessert_rankings(items))
    dish_rank = dict(_calc_dish_rankings(items, ["朝日啤酒（黄啤）"]))
    category_revenue = dict(_calc_category_distribution(items))

    assert drink_rank["朝日啤酒（黄啤）"]["qty"] == 105
    assert dish_rank["朝日啤酒（黄啤）"] == 105
    assert category_revenue["啤酒"] == 2940


def test_drink_stats_positive_revenue_filter_excludes_free_and_fully_discounted_rows():
    df = pd.DataFrame([
        {"商品名称": "朝日啤酒（黄啤）", "数量": 105, "菜品收入": 2940},
        {"商品名称": "朝日啤酒（黄啤）", "数量": 4, "菜品收入": 0},
        {"商品名称": "朝日啤酒（黄啤）", "数量": 9, "菜品收入": 0},
    ])

    positive = _positive_revenue_items(df)

    assert positive["数量"].sum() == 105
    assert positive["菜品收入"].sum() == 2940


def test_package_parent_rows_are_excluded_but_package_children_are_kept():
    items = [
        _item_row({
            "商品名称": "青花椒辣子鸡双人餐",
            "商品中类": "套餐",
            "菜品销售类型": "套餐",
            "数量": 1,
            "菜品收入": 223.72,
        }),
        _item_row({
            "商品名称": "凤梨洛神花果茶（杯）",
            "商品中类": "调饮汁",
            "菜品销售类型": "套餐子项",
            "数量": 2,
            "菜品收入": 50.01,
        }),
        _item_row({
            "商品名称": "鱼香梅花肉丝",
            "商品中类": "炒Stir- Frying",
            "菜品销售类型": "单品",
            "数量": 1,
            "菜品收入": 75,
        }),
    ]

    category_revenue = dict(_calc_category_distribution(items))

    assert "套餐" not in category_revenue
    assert category_revenue["调饮汁"] == 50.01
    assert category_revenue["炒Stir- Frying"] == 75


def test_drink_filter_excludes_package_parent_rows_but_keeps_children():
    df = pd.DataFrame([
        {"商品名称": "青花椒辣子鸡双人餐", "数量": 1, "菜品收入": 223.72, "菜品销售类型": "套餐"},
        {"商品名称": "凤梨洛神花果茶（杯）", "数量": 2, "菜品收入": 50.01, "菜品销售类型": "套餐子项"},
        {"商品名称": "可口可乐（有糖）", "数量": 1, "菜品收入": 15, "菜品销售类型": "单品"},
    ])

    positive = _positive_revenue_items(df)

    assert set(positive["商品名称"]) == {"凤梨洛神花果茶（杯）", "可口可乐（有糖）"}
    assert positive["菜品收入"].sum() == pytest.approx(65.01)


def test_drink_report_scope_includes_coffee_and_ice_cream():
    assert "咖啡" in CATEGORIES
    assert "冰淇淋" in CATEGORIES
    assert "咖啡" in NON_ALCOHOL_CATS
    assert "冰淇淋" in NON_ALCOHOL_CATS


def test_pos_order_revenue_uses_all_positive_in_store_orders(tmp_path: Path):
    manager = long_term_db.DatabaseManager(str(tmp_path / "orders.db"))
    orders = pd.DataFrame([
        {
            "订单号": "1001",
            "下单时间": "2026-06-01 12:00:00",
            "订单类型": "堂食",
            "订单收入": 100,
            "门店名称": "金谷仓家庭料理万荷餐厅",
        },
        {
            "订单号": "1002",
            "下单时间": "2026-06-01 13:00:00",
            "订单类型": "自取外卖",
            "订单收入": 80,
            "门店名称": "金谷仓家庭料理万荷餐厅",
        },
        {
            "订单号": "1003",
            "下单时间": "2026-06-01 14:00:00",
            "订单类型": "堂食",
            "订单收入": -20,
            "门店名称": "金谷仓家庭料理万荷餐厅",
        },
    ])

    manager.replace_orders(orders, "万荷店内订单明细.xlsx")

    assert manager.get_order_revenue_for_period("2026-06-01", "2026-06-01", "万荷店") == 180
    assert manager.get_order_ids_for_period("2026-06-01", "2026-06-01", "万荷店") == {"1001", "1002"}
    manager.close()


def test_takeaway_reimport_updates_status_and_revenue(tmp_path: Path):
    manager = takeaway_db.TakeawayDatabaseManager(str(tmp_path / "orders.db"))
    first = pd.DataFrame([
        {
            "外卖订单号": "2001",
            "store_name": "万荷店",
            "订单来源": "美团",
            "营业日": "2026-06-01",
            "订单状态": "已完成",
            "订单收入": 100,
            "顾客实付": 100,
            "收货人姓名": "张三",
        }
    ])
    corrected = first.copy()
    corrected.loc[0, "订单状态"] = "已取消"
    corrected.loc[0, "订单收入"] = 0

    assert manager.insert_takeaway_orders(first, "first.xlsx") == 1
    assert manager.insert_takeaway_orders(corrected, "corrected.xlsx") == 1
    manager.close()

    reader = long_term_db.DatabaseManager(str(tmp_path / "orders.db"))
    assert reader.get_takeaway_revenue_for_period("2026-06-01", "2026-06-01", "万荷店") == 0
    row = reader.conn.execute(
        "SELECT status, source_file, raw_data FROM takeaway_orders WHERE takeaway_order_id='2001'"
    ).fetchone()
    assert row[0] == "已取消"
    assert row[1] == "corrected.xlsx"
    assert json.loads(row[2])["收货人姓名"] == "***"
    reader.close()
