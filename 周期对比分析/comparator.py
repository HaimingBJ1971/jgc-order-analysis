"""
Comparison engine for 环比 (period-over-period) and 同比 (year-over-year) analysis.

Computes comparisons across 3 dimensions:
  1. Operational data (revenue, people, per-person, groups)
  2. Dish sales (key dishes + category distribution)
  3. Per-customer spending buckets
"""

import json
from datetime import datetime, timedelta


def _fmt_currency(val):
    return f"¥{val:,.0f}"


def _fmt_pct(val):
    if val is None:
        return '-'
    return f"{val:+.1f}%"


def _fmt_change(cur, base):
    """Format change: absolute value and percentage, or '-' if base is missing."""
    if base is None or base == 0:
        return _fmt_currency(cur), '-'
    diff = cur - base
    pct = diff / base * 100
    return f"{diff:+,.0f}", f"{pct:+.1f}%"


def _color_class(diff_str):
    """Return color: green for positive, red for negative, black for zero."""
    if diff_str == '-':
        return 'black'
    try:
        val = float(diff_str.replace(',', '').replace('+', ''))
        if val > 0:
            return 'green'
        elif val < 0:
            return 'red'
    except ValueError:
        pass
    return 'black'


def _aggr_daily_overview(rows, categories):
    """Aggregate daily_overview rows for a period. Returns {category_subcat: {营业额, 人数, 人均}}."""
    result = {}
    for row in rows:
        date, cat, sub, rev, pct, ppl, avg = row
        key = f"{cat}|{sub}" if sub else cat
        if categories and key not in categories:
            continue
        if key not in result:
            result[key] = {'营业额': 0, '人数': 0}
        result[key]['营业额'] += float(rev or 0)
        result[key]['人数'] += int(ppl or 0)
    for k, v in result.items():
        v['人均'] = round(v['营业额'] / v['人数'], 2) if v['人数'] > 0 else 0
    return result


def _aggr_daily_buckets(rows):
    """Aggregate daily_buckets rows. Returns {bucket: {订单数, 占比}}."""
    total = 0
    buckets = {}
    for row in rows:
        date, bucket, cnt, pct = row
        cnt = int(cnt or 0)
        if bucket not in buckets:
            buckets[bucket] = 0
        buckets[bucket] += cnt
        total += cnt
    result = {}
    for bk, cnt in buckets.items():
        result[bk] = {'订单数': cnt, '占比': round(cnt / total * 100, 1) if total > 0 else 0}
    return result


def _calc_dish_rankings(items_data, target_dishes):
    """Calculate dish sales rankings from items data. Deduplicates by (订单号, 商品编码, 商品名称)."""
    dish_qty = {}
    for dish in target_dishes:
        dish_qty[dish] = 0
    seen = set()
    for item_row in items_data:
        try:
            data = json.loads(item_row[1])
        except (json.JSONDecodeError, TypeError):
            continue
        oid = str(data.get('订单号', ''))
        code = str(data.get('商品编码', ''))
        name = str(data.get('商品名称', ''))
        key = (oid, code, name)
        if key in seen:
            continue
        seen.add(key)
        qty = float(data.get('数量', 0) or 0)
        for dish in target_dishes:
            normalized_target = dish.replace('（', '(').replace('）', ')')
            normalized_name = name.replace('（', '(').replace('）', ')')
            if normalized_target in normalized_name:
                dish_qty[dish] += int(qty)
    return sorted(dish_qty.items(), key=lambda x: x[1], reverse=True)


def _calc_category_distribution(items_data):
    """Calculate revenue distribution by 商品中类. Deduplicates by (订单号, 商品编码, 商品名称)."""
    cat_rev = {}
    seen = set()
    for item_row in items_data:
        try:
            data = json.loads(item_row[1])
        except (json.JSONDecodeError, TypeError):
            continue
        oid = str(data.get('订单号', ''))
        code = str(data.get('商品编码', ''))
        name = str(data.get('商品名称', ''))
        key = (oid, code, name)
        if key in seen:
            continue
        seen.add(key)
        cat = str(data.get('商品中类', '')).strip()
        if not cat or cat in ('nan', 'None', ''):
            continue
        rev = float(data.get('菜品收入', 0) or 0)
        cat_rev[cat] = cat_rev.get(cat, 0) + rev
    return sorted(cat_rev.items(), key=lambda x: x[1], reverse=True)


DRINK_DESSERT_CATS = [
    '饮料和水果', '调饮汁', '甜品', '啤酒', '葡萄酒', '茶', '咖啡', '冰淇淋', '鸡尾酒',
    '饮料', '调饮', '鸡尾酒', '甜品Dessert',
]


def _calc_drink_dessert_rankings(items_data):
    """酒水饮料甜品排行：从中类筛选，按商品名称汇总销量降序。"""
    dish_qty = {}
    seen = set()
    for item_row in items_data:
        try:
            data = json.loads(item_row[1])
        except (json.JSONDecodeError, TypeError):
            continue
        cat = str(data.get('商品中类', '')).strip()
        if cat not in DRINK_DESSERT_CATS:
            continue
        oid = str(data.get('订单号', ''))
        code = str(data.get('商品编码', ''))
        name = str(data.get('商品名称', ''))
        key = (oid, code, name)
        if key in seen:
            continue
        seen.add(key)
        qty = float(data.get('数量', 0) or 0)
        if qty <= 0:
            continue
        dish_qty[name] = dish_qty.get(name, 0) + int(qty)
    return sorted(dish_qty.items(), key=lambda x: x[1], reverse=True)


def compute_comparison(db_manager, period_info, comparison_info, mode, store_name):
    """
    Master comparison function.

    Args:
        db_manager: DatabaseManager instance
        period_info: from period_validator.validate_period()
        comparison_info: from period_validator.get_comparison_periods()
        mode: "week" or "month"
        store_name: store name for dish list selection

    Returns:
        dict with:
            - operational: list of comparison rows
            - dishes_current, dishes_ringbi, dishes_tongbi: dish rankings
            - buckets_current, buckets_ringbi, buckets_tongbi: bucket aggregates
            - data_quality: dict of missing data info
    """
    result = {
        'operational': [],
        'dishes_current': [],
        'dishes_ringbi': [],
        'dishes_tongbi': [],
        'buckets_current': {},
        'buckets_ringbi': {},
        'buckets_tongbi': {},
        'data_quality': {'ringbi_missing': False, 'tongbi_missing': False},
    }

    current_start = period_info['period_start']
    current_end = period_info['period_end']

    # ── 1. Operational data ──
    overview_cats = [
        '整体', '包间', '大厅', '户外',
        '午市|整体', '晚市|整体',
        '会员', '非会员',
    ]

    current_overview = _aggr_daily_overview(
        db_manager.get_overview_for_period(current_start, current_end), overview_cats
    )
    ringbi_overview = _aggr_daily_overview(
        db_manager.get_overview_for_period(comparison_info['ringbi_start'], comparison_info['ringbi_end']), overview_cats
    )
    tongbi_overview = _aggr_daily_overview(
        db_manager.get_overview_for_period(comparison_info['tongbi_start'], comparison_info['tongbi_end']), overview_cats
    )

    result['data_quality']['ringbi_missing'] = len(ringbi_overview) == 0
    result['data_quality']['tongbi_missing'] = len(tongbi_overview) == 0

    op_labels = [
        ('整体', '营业额'), ('整体', '人数'), ('整体', '人均'),
        ('包间', '营业额'), ('大厅', '营业额'), ('户外', '营业额'),
        ('包间', '人数'), ('大厅', '人数'), ('户外', '人数'),
        ('午市|整体', '营业额'), ('晚市|整体', '营业额'),
        ('会员', '营业额'),
    ]

    for cat, metric in op_labels:
        cur = current_overview.get(cat, {}).get(metric, 0)
        ring = ringbi_overview.get(cat, {}).get(metric) if ringbi_overview else None
        tong = tongbi_overview.get(cat, {}).get(metric) if tongbi_overview else None

        if metric == '营业额':
            cur_str = _fmt_currency(cur)
            ring_diff, ring_pct = _fmt_change(cur, ring)
            tong_diff, tong_pct = _fmt_change(cur, tong)
        elif metric == '人数':
            cur_str = f"{int(cur)}人"
            ring_diff = f"{int(cur - ring):+d}人" if ring is not None else '-'
            ring_pct = _fmt_pct((cur - ring) / ring * 100) if ring and ring > 0 else '-'
            tong_diff = f"{int(cur - tong):+d}人" if tong is not None else '-'
            tong_pct = _fmt_pct((cur - tong) / tong * 100) if tong and tong > 0 else '-'
        else:
            cur_str = _fmt_currency(cur)
            ring_diff = f"{cur - ring:+,.0f}" if ring is not None else '-'
            ring_pct = _fmt_pct((cur - ring) / ring * 100) if ring and ring > 0 else '-'
            tong_diff = f"{cur - tong:+,.0f}" if tong is not None else '-'
            tong_pct = _fmt_pct((cur - tong) / tong * 100) if tong and tong > 0 else '-'

        label = cat.replace('|', ' ')
        result['operational'].append({
            'label': f"{label} {metric}",
            'current': cur_str,
            'ringbi_diff': ring_diff,
            'ringbi_pct': ring_pct,
            'tongbi_diff': tong_diff,
            'tongbi_pct': tong_pct,
        })

    # ── 2. Dish rankings ──
    # Determine target dishes based on store
    if '保利' in str(store_name):
        from order_merger_skill import config
        target_dishes = [
            "川南鱼香肉丝（不能免葱）",
            "香菜回锅茄子",
        ]
    else:
        target_dishes = [
            "富顺鸡丝凉面", "古法干烧鱼(江团)", "古法干烧鱼(鲈鱼)", "富顺荤豆花",
            "206省道半汤牛蛙", "酸菜煸炒土豆片", "香菜回锅茄子", "火爆腰花",
            "炝炒莲花白菜", "金阳青花椒辣子鸡", "鱼香梅花肉丝", "文庙担担面",
            "茂萱婆婆芽菜包", "五指毛桃白芸豆猪肚三年老鸡汤(盅)",
        ]

    items_current = db_manager.get_items_for_period(current_start, current_end)
    items_ringbi = db_manager.get_items_for_period(comparison_info['ringbi_start'], comparison_info['ringbi_end'])
    items_tongbi = db_manager.get_items_for_period(comparison_info['tongbi_start'], comparison_info['tongbi_end'])

    result['dishes_current'] = _calc_dish_rankings(items_current, target_dishes)
    result['dishes_ringbi'] = _calc_dish_rankings(items_ringbi, target_dishes)
    result['dishes_tongbi'] = _calc_dish_rankings(items_tongbi, target_dishes)

    # Drink & dessert rankings
    result['drinks_current'] = _calc_drink_dessert_rankings(items_current)
    result['drinks_ringbi'] = _calc_drink_dessert_rankings(items_ringbi)
    result['drinks_tongbi'] = _calc_drink_dessert_rankings(items_tongbi)

    # Category distribution
    result['cats_current'] = _calc_category_distribution(items_current)
    result['cats_ringbi'] = _calc_category_distribution(items_ringbi)
    result['cats_tongbi'] = _calc_category_distribution(items_tongbi)

    # ── 3. Spending buckets ──
    result['buckets_current'] = _aggr_daily_buckets(
        db_manager.get_buckets_for_period(current_start, current_end)
    )
    result['buckets_ringbi'] = _aggr_daily_buckets(
        db_manager.get_buckets_for_period(comparison_info['ringbi_start'], comparison_info['ringbi_end'])
    )
    result['buckets_tongbi'] = _aggr_daily_buckets(
        db_manager.get_buckets_for_period(comparison_info['tongbi_start'], comparison_info['tongbi_end'])
    )

    return result
