import importlib.util
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).parents[1] / "订单桌访合并" / "merge_order_zhuofang.py"
SPEC = importlib.util.spec_from_file_location("merge_order_zhuofang", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_member_consumption_categories_are_mutually_exclusive_and_closed():
    groups = pd.DataFrame({
        "包含订单": [["1"], ["2", "3"], ["4"], ["5"]],
    })
    orders = pd.DataFrame([
        {"订单号": "1", "支付方式": "会员卡", "支付优惠": -5, "总优惠金额": 0, "会员姓名": "张三", "会员手机号": "13800000001"},
        {"订单号": "2", "支付方式": "会员卡,微信", "支付优惠": 0, "总优惠金额": 0, "会员姓名": "李四", "会员手机号": "13800000002"},
        {"订单号": "3", "支付方式": "微信", "支付优惠": 0, "总优惠金额": -10, "会员姓名": "李四", "会员手机号": "13800000002"},
        {"订单号": "4", "支付方式": "微信", "支付优惠": 0, "总优惠金额": 0, "会员姓名": "王五", "会员手机号": "-"},
        {"订单号": "5", "支付方式": "支付宝", "支付优惠": 0, "总优惠金额": 0, "会员姓名": "-", "会员手机号": "-"},
    ])

    classified, counts = MODULE.classify_member_consumption(groups, orders)

    assert classified["会员及卡消费类型"].tolist() == MODULE.MEMBER_CATEGORY_LABELS
    assert counts.tolist() == [1, 1, 1, 1]
    assert int(counts.sum()) == len(groups)
    assert classified["是否会员"].tolist() == [True, True, True, False]
