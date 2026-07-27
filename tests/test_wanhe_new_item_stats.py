import importlib.util
from pathlib import Path

import pandas as pd
import pytest


MODULE_PATH = Path(__file__).parents[1] / "订单桌访合并" / "merge_order_zhuofang.py"
SPEC = importlib.util.spec_from_file_location("merge_order_zhuofang_new_items", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_wanhe_new_item_list_and_sales_sorting():
    items = pd.DataFrame(
        [
            {"商品名称": "薏仁当归三年老鸡汤", "数量": 5},
            {"商品名称": "腊肉青蒜炒鲜竹笋", "数量": 2},
            {"商品名称": "大蒜红薯叶", "数量": 4},
            {"商品名称": "白灼罗马生菜", "数量": 1},
            {"商品名称": "桂花乌龙牛乳茶（杯/冰）", "数量": 99},
        ]
    )

    assert MODULE.WANHE_TARGET_NEW_ITEMS == [
        "薏仁当归三年老鸡汤",
        "腊肉青蒜炒鲜竹笋",
        "大蒜红薯叶",
        "白灼罗马生菜",
    ]
    assert MODULE.compute_new_item_stats(items) == [
        ("薏仁当归三年老鸡汤", 5),
        ("大蒜红薯叶", 4),
        ("腊肉青蒜炒鲜竹笋", 2),
        ("白灼罗马生菜", 1),
    ]


def test_wanhe_management_sales_split_and_dish_filtering():
    groups = pd.DataFrame([
        {"桌台": "包间A01", "包含订单": ["R1"]},
        {"桌台": "大厅B01", "包含订单": ["H1"]},
        {"桌台": "户外C01", "包含订单": ["O1"]},
    ])
    base = {
        "菜品收入": 100,
        "菜品销售类型": "单品",
        "商品中类": "笃DuCooking",
        "商品大类": "金谷仓",
    }
    items = pd.DataFrame([
        {**base, "订单号": "R1", "商品名称": "鱼香梅花肉丝", "单价": 75, "数量": 2},
        {**base, "订单号": "H1", "商品名称": "鱼香梅花肉丝", "单价": 75, "数量": 3},
        {**base, "订单号": "R1", "商品名称": "古法干烧鱼（鲈鱼）", "单价": 288, "数量": 1},
        {**base, "订单号": "H1", "商品名称": "石锅酸汤雪花牛肉", "单价": 200, "数量": 2},
        {**base, "订单号": "O1", "商品名称": "低于门槛菜品", "单价": 199, "数量": 9},
        {
            **base,
            "订单号": "R1",
            "商品名称": "套餐内鲜椒鱼",
            "单价": 488,
            "数量": 1,
            "菜品销售类型": "套餐子项",
        },
        {
            **base,
            "订单号": "R1",
            "商品名称": "套餐父项",
            "单价": 588,
            "数量": 1,
            "菜品销售类型": "套餐",
            "商品中类": "套餐",
        },
        {
            **base,
            "订单号": "H1",
            "商品名称": "高价葡萄酒",
            "单价": 248,
            "数量": 1,
            "商品中类": "葡萄酒",
        },
        {
            **base,
            "订单号": "R1",
            "商品名称": "包房400",
            "单价": 400,
            "数量": 1,
            "商品大类": "金谷仓（包房）",
        },
        {
            **base,
            "订单号": "H1",
            "商品名称": "零收入高价菜",
            "单价": 388,
            "数量": 1,
            "菜品收入": 0,
        },
        {**base, "订单号": "X1", "商品名称": "无效团体高价菜", "单价": 388, "数量": 1},
    ])

    result = MODULE.compute_wanhe_management_sales(groups, items)

    assert result["group_counts"] == {"包房": 1, "大厅及户外": 2}
    assert result["total_groups"] == 3
    assert result["fish_qty"] == {"包房": 2.0, "大厅及户外": 3.0}
    assert result["high_price_qty"] == {"包房": 2.0, "大厅及户外": 2.0}
    assert [
        (row["product_name"], row["total_qty"])
        for row in result["high_price_dishes"]
    ] == [
        ("石锅酸汤雪花牛肉", 2.0),
        ("套餐内鲜椒鱼", 1.0),
        ("古法干烧鱼（鲈鱼）", 1.0),
    ]


def test_wanhe_management_sales_rejects_unclassified_tables():
    groups = pd.DataFrame([{"桌台": "未知桌台", "包含订单": ["1"]}])
    items = pd.DataFrame([{
        "订单号": "1",
        "商品名称": "鱼香梅花肉丝",
        "单价": 75,
        "数量": 1,
        "菜品收入": 75,
        "菜品销售类型": "单品",
        "商品中类": "炒Stir- Frying",
        "商品大类": "金谷仓",
    }])

    with pytest.raises(ValueError, match="无法闭合"):
        MODULE.compute_wanhe_management_sales(groups, items)


def test_wanhe_management_table_uses_per_100_tables_label():
    management_stats = {
        "group_counts": {"包房": 1, "大厅及户外": 2},
        "total_groups": 3,
        "fish_qty": {"包房": 2.0, "大厅及户外": 3.0},
        "high_price_qty": {"包房": 1.0, "大厅及户外": 2.0},
        "high_price_dishes": [],
    }

    table = MODULE._make_wanhe_management_summary_table(management_stats)
    row_labels = [str(row[0]) for row in table._cellvalues]

    assert MODULE.WANHE_PER_100_SALES_LABEL == "每百桌（单）销量"
    assert "鱼香梅花肉丝每百桌（单）销量" in row_labels
    assert "高价菜每百桌（单）销量" in row_labels
    assert all("每百团销量" not in label for label in row_labels)
