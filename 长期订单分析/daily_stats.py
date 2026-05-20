"""
Daily statistics computer for long-term order analysis.

Computes all 4 sheets' data from groups DataFrame:
  Sheet 1: Data overview (revenue by area/meal/membership)
  Sheet 2: Order count details (pipeline from raw to final)
  Sheet 3: Per-customer spending distribution (5 buckets, no opener column)
  Sheet 4: Opener statistics (wide format, one row per day)
"""

import pandas as pd
import numpy as np
from collections import defaultdict


def _area(table_name) -> str:
    """Classify table into area category."""
    t = str(table_name)
    if '包间' in t:
        return '包间'
    if '户外' in t:
        return '户外'
    if '大厅' in t:
        return '大厅'
    return '其他'


def _meal_period(start_time) -> str:
    """Classify by hour: before 16:00 = 午市, 16:00+ = 晚市."""
    try:
        h = int(pd.Timestamp(start_time).hour)
        return '午市' if h < 16 else '晚市'
    except Exception:
        return '晚市'


def _compute_member_status(orders_df, group_sum) -> pd.Series:
    """Determine if each group is member (any order has 会员姓名)."""
    order_member_map = {}
    if '会员姓名' in orders_df.columns:
        for _, r in orders_df.iterrows():
            mem = str(r.get('会员姓名', '')).strip()
            order_member_map[str(r['订单号'])] = mem not in ('', '-', 'nan', 'None', '无')

    def _has_member(order_ids):
        ids = order_ids if isinstance(order_ids, list) else []
        return any(order_member_map.get(str(oid), False) for oid in ids)

    return group_sum['包含订单'].apply(_has_member)


def _compute_opener(groups_df, orders_df) -> pd.Series:
    """Get opener for each group (from the anchor order's 开单人)."""
    opener_map = {}
    if '开单人' in orders_df.columns:
        for _, r in orders_df.iterrows():
            opener_map[str(r['订单号'])] = str(r.get('开单人', '')).strip()

    def _get_opener(order_ids):
        ids = order_ids if isinstance(order_ids, list) else []
        # Use first order's opener (or could use anchor)
        for oid in ids:
            op = opener_map.get(str(oid), '')
            if op and op not in ('', 'nan', 'None'):
                return op
        return '顾客/系统'

    return groups_df['包含订单'].apply(_get_opener)


def compute_all_daily_stats(groups_df, orders_df, pre_merge_daily, items_df=None):
    """
    Master function: compute all 4 sheets' daily statistics.

    Args:
        groups_df: DataFrame from aggregate_groups() with added columns:
                   _date, _area, _meal, 是否会员, _opener, _filter_status
        orders_df: orders_with_group DataFrame
        pre_merge_daily: dict[date] -> {原始订单数, 外卖订单数, 非堂食订单数}
        items_df: items DataFrame (for filter_groups, optional)

    Returns:
        dict with keys:
            - overview_rows: list of (date, category, sub_category, 营业额, 百分比, 人数, 人均)
            - order_count_rows: list of (date, 原始订单数, ...)
            - bucket_rows: list of (date, bucket, 订单数, 占比)
            - opener_rows: list of (date, opener_name, order_count, total_amount)
            - all_dates: sorted list of all dates
            - all_openers: sorted list of all unique opener names
    """
    if groups_df.empty:
        return {
            'overview_rows': [],
            'order_count_rows': [],
            'bucket_rows': [],
            'opener_rows': [],
            'all_dates': [],
            'all_openers': [],
        }

    gs = groups_df.copy()

    # Ensure computed columns exist
    if '_area' not in gs.columns:
        gs['_area'] = gs['桌台'].apply(_area)
    if '_meal' not in gs.columns:
        gs['_meal'] = gs['开始'].apply(_meal_period)
    if '是否会员' not in gs.columns and orders_df is not None:
        gs['是否会员'] = _compute_member_status(orders_df, gs)
    if '_opener' not in gs.columns and orders_df is not None:
        gs['_opener'] = _compute_opener(gs, orders_df)
    if '_filter_status' not in gs.columns:
        gs['_filter_status'] = 'kept'
    if '_date' not in gs.columns:
        gs['_date'] = pd.to_datetime(gs['开始'], errors='coerce').dt.strftime('%Y-%m-%d')

    # Only use kept groups for stats
    kept = gs[gs['_filter_status'] == 'kept'].copy()
    all_groups = gs.copy()  # includes filtered-out groups for order count stats

    # Get all dates across ALL groups (including filtered) for consistent date coverage
    all_dates = sorted(set(
        d for d in gs['_date'].dropna().unique()
        if d and d != 'NaT'
    ))

    # Collect unique openers across all dates
    all_openers = set()
    for _, g in kept.iterrows():
        op = str(g.get('_opener', '')).strip()
        if op and op not in ('', 'nan', 'None'):
            all_openers.add(op)

    # Sort openers: non-顾客/系统 alphabetical first, 顾客/系统 last
    openers_sorted = sorted(
        [o for o in all_openers if o != '顾客/系统']
    ) + (['顾客/系统'] if '顾客/系统' in all_openers else [])

    overview_rows = []
    order_count_rows = []
    bucket_rows = []
    opener_rows = []

    for date in all_dates:
        day_kept = kept[kept['_date'] == date]
        day_all = all_groups[all_groups['_date'] == date]

        # ── Sheet 1: Data Overview ──
        total_rev = float(day_kept['订单收入'].sum())
        total_ppl = float(day_kept['团体人数'].sum())
        total_avg = round(total_rev / total_ppl, 2) if total_ppl > 0 else 0.0

        def _seg(rev, ppl):
            return {
                '营业额': round(float(rev), 2),
                '人数': int(round(float(ppl))),
                '人均': round(float(rev) / float(ppl), 2) if float(ppl) > 0 else 0.0,
                '百分比': round(float(rev) / total_rev * 100, 1) if total_rev > 0 else 0.0,
            }

        # Overall
        overview_rows.append((date, '整体', '', total_rev,
                              _seg(total_rev, total_ppl)['百分比'],
                              total_ppl, total_avg))

        # By area (包间/大厅/户外)
        for area in ['包间', '大厅', '户外']:
            mask = day_kept['_area'] == area
            rev = float(day_kept.loc[mask, '订单收入'].sum())
            ppl = float(day_kept.loc[mask, '团体人数'].sum())
            seg = _seg(rev, ppl)
            overview_rows.append((date, area, '', seg['营业额'], seg['百分比'],
                                  seg['人数'], seg['人均']))

        # Lunch (午市)
        wu = day_kept[day_kept['_meal'] == '午市']
        wu_rev = float(wu['订单收入'].sum())
        wu_ppl = float(wu['团体人数'].sum())
        wu_seg = _seg(wu_rev, wu_ppl)
        overview_rows.append((date, '午市', '整体', wu_seg['营业额'], wu_seg['百分比'],
                              wu_seg['人数'], wu_seg['人均']))
        for area in ['包间', '大厅', '户外']:
            mask = (wu['_area'] == area)
            rev = float(wu.loc[mask, '订单收入'].sum())
            ppl = float(wu.loc[mask, '团体人数'].sum())
            seg = _seg(rev, ppl)
            # Percentage relative to lunch total
            pct = round(float(rev) / wu_rev * 100, 1) if wu_rev > 0 else 0.0
            overview_rows.append((date, '午市', area, seg['营业额'], pct,
                                  seg['人数'], seg['人均']))

        # Dinner (晚市)
        wan = day_kept[day_kept['_meal'] == '晚市']
        wan_rev = float(wan['订单收入'].sum())
        wan_ppl = float(wan['团体人数'].sum())
        wan_seg = _seg(wan_rev, wan_ppl)
        overview_rows.append((date, '晚市', '整体', wan_seg['营业额'], wan_seg['百分比'],
                              wan_seg['人数'], wan_seg['人均']))
        for area in ['包间', '大厅', '户外']:
            mask = (wan['_area'] == area)
            rev = float(wan.loc[mask, '订单收入'].sum())
            ppl = float(wan.loc[mask, '团体人数'].sum())
            seg = _seg(rev, ppl)
            pct = round(float(rev) / wan_rev * 100, 1) if wan_rev > 0 else 0.0
            overview_rows.append((date, '晚市', area, seg['营业额'], pct,
                                  seg['人数'], seg['人均']))

        # Member / Non-member
        for mem_label, mem_mask in [('会员', day_kept['是否会员'] == True),
                                     ('非会员', day_kept['是否会员'] != True)]:
            rev = float(day_kept.loc[mem_mask, '订单收入'].sum())
            ppl = float(day_kept.loc[mem_mask, '团体人数'].sum())
            seg = _seg(rev, ppl)
            overview_rows.append((date, mem_label, '', seg['营业额'], seg['百分比'],
                                  seg['人数'], seg['人均']))

        # ── Sheet 2: Order Count Details ──
        pre = pre_merge_daily.get(date, {'原始订单数': 0, '外卖订单数': 0, '非堂食订单数': 0})
        raw_orders = int(pre.get('原始订单数', 0))
        waimai_cnt = int(pre.get('外卖订单数', 0))
        feitangshi_cnt = int(pre.get('非堂食订单数', 0))

        # Filter stats from this date's all groups
        free_groups = day_all[day_all['_filter_status'] == '免单']
        snack_groups = day_all[day_all['_filter_status'] == '零食']
        pack_groups = day_all[day_all['_filter_status'] == '打包']
        tiny_groups = day_all[day_all['_filter_status'] == '零散小单']
        bar_groups = day_all[day_all['_filter_status'] == '吧台']

        free_order_cnt = int(free_groups['订单数'].sum()) if not free_groups.empty else 0
        snack_group_cnt = len(snack_groups)
        pack_group_cnt = len(pack_groups)
        tiny_group_cnt = len(tiny_groups)
        bar_group_cnt = len(bar_groups)

        pre_filter_cnt = len(day_all)
        post_filter_cnt = len(day_kept)

        merged_cnt = max(0, raw_orders - waimai_cnt - feitangshi_cnt - free_order_cnt - pre_filter_cnt)

        order_count_rows.append((
            date, raw_orders, waimai_cnt, feitangshi_cnt, free_order_cnt,
            merged_cnt, pre_filter_cnt,
            snack_group_cnt, pack_group_cnt, tiny_group_cnt, bar_group_cnt,
            post_filter_cnt
        ))

        # ── Sheet 3: Spending Buckets ──
        total_groups = len(day_kept)
        buckets_def = [
            ('≥300', day_kept['人均消费'] >= 300),
            ('200~300', (day_kept['人均消费'] >= 200) & (day_kept['人均消费'] < 300)),
            ('150~200', (day_kept['人均消费'] >= 150) & (day_kept['人均消费'] < 200)),
            ('100~150', (day_kept['人均消费'] >= 100) & (day_kept['人均消费'] < 150)),
            ('<100', day_kept['人均消费'] < 100),
        ]
        for label, mask in buckets_def:
            cnt = int(mask.sum())
            pct = round(cnt / total_groups * 100, 1) if total_groups > 0 else 0.0
            bucket_rows.append((date, label, cnt, pct))

        # ── Sheet 4: Opener Stats ──
        for opener in openers_sorted:
            mask = day_kept['_opener'] == opener
            cnt = int(mask.sum())
            amt = round(float(day_kept.loc[mask, '订单收入'].sum()), 2)
            opener_rows.append((date, opener, cnt, amt))

    return {
        'overview_rows': overview_rows,
        'order_count_rows': order_count_rows,
        'bucket_rows': bucket_rows,
        'opener_rows': opener_rows,
        'all_dates': all_dates,
        'all_openers': openers_sorted,
    }
