"""
订单合并算法模块

规则优先级（第一个命中即决策）：
  R0 并发拆单  → 直接合并
  R1 时间窗口  → 新会话（包间小单例外）
  R2 加单金额上限 → 新会话
  R3 结账后间隔  → 新会话（小单例外）
  弱规则打分   → 达标合并 / 否则新会话
"""
import pandas as pd
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from config import (
    T_WINDOW_HOURS_REGULAR,
    T_WINDOW_HOURS_PRIVATE,
    CONCURRENT_MINUTES,
    ADD_ON_MAX_RATIO,
    T_REOPEN_MIN_REGULAR,
    T_REOPEN_MIN_PRIVATE,
    SETTLE_GRACE_MIN,
    SMALL_RATIO,
    SMALL_LINE_CNT,
    SCORE_THRESHOLD,
    SMALL_ORDER_BONUS_LOW,
    SMALL_ORDER_BONUS_MID,
    SMALL_ORDER_BONUS_HIGH,
    DINNER_MERGE_START_HOUR,
    DINNER_MERGE_END_HOUR,
)


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def tokenize_payment(s):
    if pd.isna(s):
        return set()
    s = str(s)
    tokens = set()
    for t in ["微信", "支付宝", "银行卡", "会员卡", "现金", "团购", "抖音", "美团"]:
        if t in s:
            tokens.add(t)
    return tokens


def _is_small_order(row, anchor, line_cnts):
    """判断候选订单是否为"小单"（收入 <= 锚点×30% 或 商品行数 <= 2）"""
    revenue_small = row["订单收入"] <= anchor["订单收入"] * SMALL_RATIO
    line_small = line_cnts.get(row["订单号"], 0) <= SMALL_LINE_CNT
    return revenue_small or line_small


def _is_dinner_time(ts):
    """本地时间的晚餐窗口，用于包间酒水加单强合并。"""
    if pd.isna(ts):
        return False
    h = int(ts.hour)
    return DINNER_MERGE_START_HOUR <= h < DINNER_MERGE_END_HOUR


# 商品中类中含以下关键字则视为酒水/饮品（整单每件均须匹配才算「纯酒水加单」）
_DRINK_CATEGORY_MARKERS = (
    "啤酒", "红酒", "白酒", "洋酒", "酒水", "酒类", "饮品", "饮料", "软饮",
    "威士忌", "鸡尾酒", "葡萄酒", "米酒", "黄酒", "果酒", "liqueur",
    "Wine", "Beer", "Rum", "Cocktail",
    "茶", "咖啡", "果汁", "汽水", "矿泉水", "苏打", "可乐", "雪碧",
)


def _category_looks_like_drink(cat):
    c = str(cat or "")
    return any(m in c for m in _DRINK_CATEGORY_MARKERS)


def _items_for_order(order_id, items_df):
    if items_df is None or len(items_df) == 0:
        return None
    sub = items_df[items_df["订单号"] == order_id]
    if len(sub) == 0:
        sub = items_df[items_df["订单号"].astype(str) == str(order_id)]
    if len(sub) == 0:
        return None
    return sub


def _is_beverage_only_order(order_id, items_df):
    """该订单商品是否全部为酒水/饮品（用于包间晚餐加单强合并）。"""
    sub = _items_for_order(order_id, items_df)
    if sub is None or len(sub) == 0:
        return False
    for _, r in sub.iterrows():
        if not _category_looks_like_drink(r.get("商品中类")):
            return False
    return True


def _start_new_group(groups, table, group_id, group_order_ids,
                     group_start, group_end, anchor):
    """保存当前会话并返回新会话的初始状态"""
    groups[(table, group_id)] = {
        "order_ids": group_order_ids,
        "start_time": group_start,
        "end_time": group_end,
        "anchor_order": anchor,
    }


def _compute_weak_score(row, anchor, item_sets, line_cnts, gap_after_settle,
                        current_t_reopen_min):
    """计算弱规则得分"""
    score = 20  # 同桌且在窗口内的基础分

    # 时间接近度
    if gap_after_settle <= SETTLE_GRACE_MIN:
        score += 25
    elif gap_after_settle <= current_t_reopen_min:
        score += 10

    # 会员手机号
    p1 = str(row.get("会员手机号", "-"))
    p2 = str(anchor.get("会员手机号", "-"))
    if p1 != "-" and p2 != "-" and p1 == p2:
        score += 25
    elif p1 != "-" and p2 != "-" and p1 != p2:
        score -= 10

    # 就餐人数：仅两单人数完全相等时 +15；任意不一致则 0 分（不奖不罚，与差 1 人还是多人无关）
    if pd.notna(row["就餐人数"]) and pd.notna(anchor["就餐人数"]):
        if row["就餐人数"] == anchor["就餐人数"]:
            score += 15

    # 支付方式
    if tokenize_payment(row.get("支付方式", "")) & tokenize_payment(
        anchor.get("支付方式", "")
    ):
        score += 5

    # 菜品Jaccard相似度
    jac = jaccard(
        item_sets.get(row["订单号"], set()),
        item_sets.get(anchor["订单号"], set()),
    )
    if jac >= 0.1:
        score += 10

    # 小单金额分段加分
    is_small = _is_small_order(row, anchor, line_cnts)
    if is_small:
        rev = row["订单收入"]
        if rev < 40:
            score += SMALL_ORDER_BONUS_LOW
        elif rev < 60:
            score += SMALL_ORDER_BONUS_MID
        else:
            score += SMALL_ORDER_BONUS_HIGH

    # 备注一致
    r1 = str(row.get("整单备注", "-"))
    r2 = str(anchor.get("整单备注", "-"))
    if r1 != "-" and r2 != "-" and r1 == r2:
        score += 5

    return score


def merge_orders(orders_df, item_sets, line_cnts, items_df=None):
    """
    合并订单

    Returns:
        (orders_with_group, groups)
    """
    assignments = []
    groups = {}

    for table, g in orders_df.groupby("桌台", sort=False):
        g = g.sort_values("下单时间").copy()
        is_private_room = "包间" in str(table)

        t_window_hours = (
            T_WINDOW_HOURS_PRIVATE if is_private_room else T_WINDOW_HOURS_REGULAR
        )
        t_reopen_min = (
            T_REOPEN_MIN_PRIVATE if is_private_room else T_REOPEN_MIN_REGULAR
        )

        group_id = 0
        group_start = None
        group_end = None
        anchor = None
        group_order_ids = []
        last_order_time = None  # 会话中最后一笔订单的下单时间（用于并发检测）

        for _, row in g.iterrows():
            order_id = row["订单号"]

            # ── 首单：直接开启会话 ──
            if group_start is None:
                group_start = row["下单时间"]
                group_end = row["结账时间"]
                anchor = row
                group_order_ids = [order_id]
                last_order_time = row["下单时间"]
                assignments.append((order_id, table, group_id))
                continue

            # ── R0: 并发拆单（< 5分钟 → 直接合并） ──
            minutes_since_last = (
                (row["下单时间"] - last_order_time).total_seconds() / 60.0
            )
            if minutes_since_last < CONCURRENT_MINUTES:
                assignments.append((order_id, table, group_id))
                group_order_ids.append(order_id)
                group_end = max(group_end, row["结账时间"])
                last_order_time = row["下单时间"]
                if row["订单收入"] > anchor["订单收入"]:
                    anchor = row
                continue

            # ── 预计算：小单判定 ──
            is_small = _is_small_order(row, anchor, line_cnts)

            # ── R1: 时间窗口（普通桌1h / 包间3h） ──
            time_from_start = (
                row["下单时间"] - group_start
            ) > pd.Timedelta(hours=t_window_hours)
            if time_from_start and not (is_private_room and is_small):
                _start_new_group(
                    groups, table, group_id, group_order_ids,
                    group_start, group_end, anchor,
                )
                group_id += 1
                group_start = row["下单时间"]
                group_end = row["结账时间"]
                anchor = row
                group_order_ids = [order_id]
                last_order_time = row["下单时间"]
                assignments.append((order_id, table, group_id))
                continue

            # 包间晚餐 + 纯酒水加单：跳过加单金额上限，并在后续直接合并（弱规则常因人数登记不一致不达标）
            private_dinner_drink_addon = (
                is_private_room
                and items_df is not None
                and _is_dinner_time(row["下单时间"])
                and _is_beverage_only_order(order_id, items_df)
            )

            # ── R2: 加单金额上限（> 锚点 × 50% → 新会话） ──
            if (
                not private_dinner_drink_addon
                and row["订单收入"] > anchor["订单收入"] * ADD_ON_MAX_RATIO
            ):
                _start_new_group(
                    groups, table, group_id, group_order_ids,
                    group_start, group_end, anchor,
                )
                group_id += 1
                group_start = row["下单时间"]
                group_end = row["结账时间"]
                anchor = row
                group_order_ids = [order_id]
                last_order_time = row["下单时间"]
                assignments.append((order_id, table, group_id))
                continue

            # ── R3: 结账后间隔翻台判定 ──
            gap_after_settle = (
                (row["下单时间"] - group_end).total_seconds() / 60.0
            )
            if gap_after_settle > t_reopen_min and not is_small:
                _start_new_group(
                    groups, table, group_id, group_order_ids,
                    group_start, group_end, anchor,
                )
                group_id += 1
                group_start = row["下单时间"]
                group_end = row["结账时间"]
                anchor = row
                group_order_ids = [order_id]
                last_order_time = row["下单时间"]
                assignments.append((order_id, table, group_id))
                continue

            # ── R3.5: 包间晚餐纯酒水加单 → 直接并入当前会话 ──
            if private_dinner_drink_addon:
                assignments.append((order_id, table, group_id))
                group_order_ids.append(order_id)
                group_end = max(group_end, row["结账时间"])
                last_order_time = row["下单时间"]
                if row["订单收入"] > anchor["订单收入"]:
                    anchor = row
                continue

            # ── 弱规则打分 ──
            score = _compute_weak_score(
                row, anchor, item_sets, line_cnts,
                gap_after_settle, t_reopen_min,
            )

            if score >= SCORE_THRESHOLD:
                assignments.append((order_id, table, group_id))
                group_order_ids.append(order_id)
                group_end = max(group_end, row["结账时间"])
                last_order_time = row["下单时间"]
                if row["订单收入"] > anchor["订单收入"]:
                    anchor = row
            else:
                _start_new_group(
                    groups, table, group_id, group_order_ids,
                    group_start, group_end, anchor,
                )
                group_id += 1
                group_start = row["下单时间"]
                group_end = row["结账时间"]
                anchor = row
                group_order_ids = [order_id]
                last_order_time = row["下单时间"]
                assignments.append((order_id, table, group_id))

        # 保存最后一个会话
        if group_start is not None:
            groups[(table, group_id)] = {
                "order_ids": group_order_ids,
                "start_time": group_start,
                "end_time": group_end,
                "anchor_order": anchor,
            }

    assign_df = pd.DataFrame(
        assignments, columns=["订单号", "桌台", "消费团体ID"]
    )
    orders_with_group = orders_df.merge(
        assign_df, on=["订单号", "桌台"], how="left"
    )

    return orders_with_group, groups
