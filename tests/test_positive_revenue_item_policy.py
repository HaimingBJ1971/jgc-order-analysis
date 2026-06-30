import json
import sys
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
