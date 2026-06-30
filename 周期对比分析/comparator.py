"""
Comparison engine for 环比 (period-over-period) and 同比 (year-over-year) analysis.

Computes comparisons across 3 dimensions:
  1. Operational data (revenue, people, per-person, groups)
  2. Dish sales (key dishes + category distribution)
  3. Per-customer spending buckets
"""

import json
from datetime import datetime, timedelta

# POS 导出中常见的中类占位符（并非真实分类名）
_INVALID_CATEGORY_TOKENS = frozenset({
    '', '-', '—', '－', '–', '无', '未知', 'nan', 'none', 'null',
})


def category_field_for_store(store_name: str | None) -> str:
    """保利店 POS 未维护中类，第四节改用商品大类对比。"""
    if store_name and '保利' in str(store_name):
        return '商品大类'
    return '商品中类'


def category_section_meta(store_name: str | None) -> dict:
    field = category_field_for_store(store_name)
    if field == '商品大类':
        return {
            'field': field,
            'column': '商品大类',
            'title': '四、商品大类销售额分布',
        }
    return {
        'field': field,
        'column': '商品中类',
        'title': '四、商品中类销售额分布',
    }


def _normalize_category(raw) -> str | None:
    """Normalize category label; return None if row should be skipped entirely."""
    cat = str(raw or '').strip()
    if cat.lower() in _INVALID_CATEGORY_TOKENS or cat in _INVALID_CATEGORY_TOKENS:
        return '未分类'
    return cat


def _is_uncategorized_raw(raw) -> bool:
    """True when POS category field is a placeholder / missing."""
    cat = str(raw or '').strip()
    return cat.lower() in _INVALID_CATEGORY_TOKENS or cat in _INVALID_CATEGORY_TOKENS


def _item_revenue(data: dict) -> float:
    """Return POS item revenue; invalid values are treated as zero."""
    try:
        return float(data.get('菜品收入', 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _item_qty(data: dict) -> float:
    """Return POS item quantity; invalid values are treated as zero."""
    try:
        return float(data.get('数量', 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_positive_revenue_item(data: dict) -> bool:
    """商品销量/销售额统一商品归因口径。

    只要 `菜品收入 <= 0`，无论是赠送、免单、全额优惠还是测试单，
    都不计入销量/销售额。不要用“销售数量 - 赠菜数量”替代该判断，
    因为全额优惠/免单也会形成零收入数量。

    POS 套餐会同时导出“套餐”父项和“套餐子项”。收入归因只能保留
    子项，父项必须剔除，否则第四节商品分类销售额会重复统计。
    """
    return _item_revenue(data) > 0 and str(data.get('菜品销售类型', '')).strip() != '套餐'


def _calc_uncategorized_products(items_data, category_field: str = '商品中类'):
    """Aggregate products with missing POS category in the given field."""
    agg = {}
    for item_row in items_data:
        try:
            data = json.loads(item_row[1])
        except (json.JSONDecodeError, TypeError):
            continue
        if not _is_uncategorized_raw(data.get(category_field, '')):
            continue
        oid = str(data.get('订单号', ''))
        code = str(data.get('商品编码', ''))
        name = str(data.get('商品名称', '')).strip()
        if not name or name in ('nan', 'None'):
            continue
        if not _is_positive_revenue_item(data):
            continue
        qty = int(_item_qty(data))
        rev = _item_revenue(data)
        bucket = agg.setdefault(name, {'qty': 0, 'rev': 0.0})
        bucket['qty'] += qty
        bucket['rev'] += rev
    return sorted(
        ((name, v['qty'], v['rev']) for name, v in agg.items()),
        key=lambda x: x[2],
        reverse=True,
    )


def format_uncategorized_note(products: list, category_field: str = '商品中类') -> str:
    """Plain-text footnote listing all uncategorized products for reports."""
    if not products:
        return ''
    total_rev = sum(rev for _, _, rev in products)
    lines = [
        f"未分类商品明细（POS {category_field}为「-」或空，请在后台补全）："
        f"共 {len(products)} 项，合计 ¥{total_rev:,.0f}",
    ]
    for i, (name, qty, rev) in enumerate(products, 1):
        lines.append(f"{i}. {name}（{qty}份，¥{rev:,.0f}）")
    return '\n'.join(lines)


def _fmt_currency(val):
    return f"¥{val:,.0f}"


def _fmt_pct(val):
    if val is None:
        return '-'
    return f"{val:+.1f}%"


def _fmt_change(cur, base):
    """Format change: absolute value and percentage, or '-' if base is missing."""
    if base is None or base == 0:
        return '-', '-'
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
    """Calculate dish sales rankings from POS item lines."""
    dish_qty = {}
    for dish in target_dishes:
        dish_qty[dish] = 0
    for item_row in items_data:
        try:
            data = json.loads(item_row[1])
        except (json.JSONDecodeError, TypeError):
            continue
        name = str(data.get('商品名称', ''))
        qty = _item_qty(data)
        if qty <= 0 or not _is_positive_revenue_item(data):
            continue
        for dish in target_dishes:
            normalized_target = dish.replace('（', '(').replace('）', ')')
            normalized_name = name.replace('（', '(').replace('）', ')')
            if normalized_target in normalized_name:
                dish_qty[dish] += int(qty)
    return sorted(dish_qty.items(), key=lambda x: x[1], reverse=True)


def _calc_category_distribution(items_data, category_field: str = '商品中类'):
    """Calculate revenue distribution by category field from POS item lines."""
    cat_rev = {}
    for item_row in items_data:
        try:
            data = json.loads(item_row[1])
        except (json.JSONDecodeError, TypeError):
            continue
        cat = _normalize_category(data.get(category_field, ''))
        if cat is None:
            continue
        if not _is_positive_revenue_item(data):
            continue
        rev = _item_revenue(data)
        cat_rev[cat] = cat_rev.get(cat, 0) + rev
    return sorted(cat_rev.items(), key=lambda x: x[1], reverse=True)


import re

DRINK_DESSERT_CATS = [
    '饮料和水果', '调饮汁', '甜品', '啤酒', '葡萄酒', '茶', '咖啡', '冰淇淋', '鸡尾酒',
    '饮料', '调饮', '鸡尾酒', '甜品Dessert',
]


def _calc_drink_dessert_rankings(items_data):
    """酒水饮料甜品排行：从中类筛选，按商品名称汇总销量降序。
    Returns [(name, qty, cat), ...] with cat being the 商品中类.
    """
    dish_info = {}  # name -> {'qty': int, 'cat': str}
    for item_row in items_data:
        try:
            data = json.loads(item_row[1])
        except (json.JSONDecodeError, TypeError):
            continue
        cat = str(data.get('商品中类', '')).strip()
        if cat not in DRINK_DESSERT_CATS:
            continue
        name = str(data.get('商品名称', ''))
        qty = _item_qty(data)
        if qty <= 0 or not _is_positive_revenue_item(data):
            continue
        if name not in dish_info:
            dish_info[name] = {'qty': 0, 'cat': cat}
        dish_info[name]['qty'] += int(qty)
    return sorted(dish_info.items(), key=lambda x: x[1]['qty'], reverse=True)


_SPEC_PATTERN = re.compile(r'[（(][^）)]*[）)]$')


def _base_name(name):
    """提取核心品名：去掉末尾括号内的规格描述（杯/小瓶/大瓶/扎/壶/盅等）"""
    return _SPEC_PATTERN.sub('', name).strip()


def _group_drinks(ranked_list):
    """将核心品名相同的商品归组：组内按销量降序，组间按组内最高销量降序。"""
    groups = {}
    for name, info in ranked_list:
        base = _base_name(name)
        if base not in groups:
            groups[base] = []
        groups[base].append((name, info))
    result = []
    for base in sorted(groups, key=lambda b: max(i['qty'] for _, i in groups[b]), reverse=True):
        result.extend(sorted(groups[base], key=lambda x: x[1]['qty'], reverse=True))
    return result


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
        'uncategorized_products': [],
        'category_dimension': category_section_meta(store_name),
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
        db_manager.get_overview_for_period(current_start, current_end, store_name), overview_cats
    )
    ringbi_overview = _aggr_daily_overview(
        db_manager.get_overview_for_period(
            comparison_info['ringbi_start'], comparison_info['ringbi_end'], store_name
        ), overview_cats
    )
    tongbi_overview = _aggr_daily_overview(
        db_manager.get_overview_for_period(
            comparison_info['tongbi_start'], comparison_info['tongbi_end'], store_name
        ), overview_cats
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

    def _append_op_row(label, metric, cur, ring, tong):
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

        result['operational'].append({
            'label': label,
            'current': cur_str,
            'ringbi_diff': ring_diff,
            'ringbi_pct': ring_pct,
            'tongbi_diff': tong_diff,
            'tongbi_pct': tong_pct,
        })

    current_desk_revenue = current_overview.get('整体', {}).get('营业额', 0)
    ringbi_desk_revenue = ringbi_overview.get('整体', {}).get('营业额') if ringbi_overview else None
    tongbi_desk_revenue = tongbi_overview.get('整体', {}).get('营业额') if tongbi_overview else None
    current_total_revenue = db_manager.get_total_revenue_for_period(current_start, current_end, store_name)
    ringbi_total_revenue = (
        db_manager.get_total_revenue_for_period(comparison_info['ringbi_start'], comparison_info['ringbi_end'], store_name)
        if ringbi_overview else None
    )
    tongbi_total_revenue = (
        db_manager.get_total_revenue_for_period(comparison_info['tongbi_start'], comparison_info['tongbi_end'], store_name)
        if tongbi_overview else None
    )
    current_excluded_revenue = current_total_revenue - current_desk_revenue
    ringbi_excluded_revenue = (
        ringbi_total_revenue - ringbi_desk_revenue
        if ringbi_total_revenue is not None and ringbi_desk_revenue is not None else None
    )
    tongbi_excluded_revenue = (
        tongbi_total_revenue - tongbi_desk_revenue
        if tongbi_total_revenue is not None and tongbi_desk_revenue is not None else None
    )

    _append_op_row('整体营业额', '营业额', current_total_revenue, ringbi_total_revenue, tongbi_total_revenue)
    _append_op_row('堂食分桌总营业额', '营业额', current_desk_revenue, ringbi_desk_revenue, tongbi_desk_revenue)
    _append_op_row('自取外卖单、吧台及零食购买团体、第三方平台外卖单合计', '营业额', current_excluded_revenue, ringbi_excluded_revenue, tongbi_excluded_revenue)

    for cat, metric in op_labels:
        if cat == '整体' and metric == '营业额':
            continue
        cur = current_overview.get(cat, {}).get(metric, 0)
        ring = ringbi_overview.get(cat, {}).get(metric) if ringbi_overview else None
        tong = tongbi_overview.get(cat, {}).get(metric) if tongbi_overview else None
        label = cat.replace('|', ' ')
        _append_op_row(f"{label} {metric}", metric, cur, ring, tong)

    # ── 2. Dish rankings ──
    # Determine target dishes based on store
    if '保利' in str(store_name):
        target_dishes = [
            "川南鱼香肉丝（不能免葱）",
            "香菜回锅茄子",
        ]
    else:
        target_dishes = [
            "富顺鸡丝凉面", "古法干烧鱼(江团)", "古法干烧鱼(鲈鱼)", "富顺荤豆花",
            "206省道半汤牛蛙", "酸菜煸炒土豆片", "香菜回锅茄子", "火爆腰花",
            "炝炒莲花白菜", "金阳青花椒辣子鸡", "鱼香梅花肉丝", "文庙担担面",
            "茂萱婆婆芽菜包", "百合蜜枣无花果排骨汤",
        ]

    items_current = db_manager.get_all_items_for_period(current_start, current_end, store_name)
    items_ringbi = db_manager.get_all_items_for_period(
        comparison_info['ringbi_start'], comparison_info['ringbi_end'], store_name
    )
    items_tongbi = db_manager.get_all_items_for_period(
        comparison_info['tongbi_start'], comparison_info['tongbi_end'], store_name
    )

    result['dishes_current'] = _calc_dish_rankings(items_current, target_dishes)
    result['dishes_ringbi'] = _calc_dish_rankings(items_ringbi, target_dishes)
    result['dishes_tongbi'] = _calc_dish_rankings(items_tongbi, target_dishes)

    # Drink & dessert rankings
    result['drinks_current'] = _group_drinks(_calc_drink_dessert_rankings(items_current))
    result['drinks_ringbi'] = _calc_drink_dessert_rankings(items_ringbi)
    result['drinks_tongbi'] = _calc_drink_dessert_rankings(items_tongbi)

    # Category distribution (保利店用商品大类，万荷店用商品中类)
    cat_field = category_field_for_store(store_name)
    result['cats_current'] = _calc_category_distribution(items_current, cat_field)
    result['cats_ringbi'] = _calc_category_distribution(items_ringbi, cat_field)
    result['cats_tongbi'] = _calc_category_distribution(items_tongbi, cat_field)
    result['uncategorized_products'] = _calc_uncategorized_products(items_current, cat_field)

    # ── 3. Spending buckets ──
    result['buckets_current'] = _aggr_daily_buckets(
        db_manager.get_buckets_for_period(current_start, current_end, store_name)
    )
    result['buckets_ringbi'] = _aggr_daily_buckets(
        db_manager.get_buckets_for_period(
            comparison_info['ringbi_start'], comparison_info['ringbi_end'], store_name
        )
    )
    result['buckets_tongbi'] = _aggr_daily_buckets(
        db_manager.get_buckets_for_period(
            comparison_info['tongbi_start'], comparison_info['tongbi_end'], store_name
        )
    )

    return result
