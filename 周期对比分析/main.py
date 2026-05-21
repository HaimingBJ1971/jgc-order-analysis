"""
Period Comparison Analysis — CLI Entry Point.

Usage:
    cd 周期对比分析
    python3 main.py \
        --excel "path/orders.xlsx" \
        --db "../长期订单分析/output/长期订单分析.db" \
        --mode week \
        --store "万荷店" \
        --output-dir ./output
"""

import os
import sys
import argparse
import pandas as pd
from datetime import datetime

# Add order_merger_skill to path
_skill_dir = os.path.join(os.path.dirname(__file__), '..', '每日订单分析', 'order_merger_skill')
sys.path.insert(0, os.path.abspath(_skill_dir))

from data_loader import load_excel, clean_orders, clean_items, get_item_features
from order_merger import merge_orders
from aggregator import aggregate_groups, filter_groups

# Add long-term analysis modules to path
_lt_dir = os.path.join(os.path.dirname(__file__), '..', '长期订单分析')
sys.path.insert(0, os.path.abspath(_lt_dir))

from db_manager import DatabaseManager
from daily_stats import compute_all_daily_stats, _area, _meal_period, _compute_member_status, _compute_opener
from multi_file_loader import load_and_dedup_excels

from period_validator import validate_period, get_comparison_periods
from comparator import compute_comparison
from pdf_report import generate_comparison_pdf


def main():
    parser = argparse.ArgumentParser(description="周期对比分析 — 环比/同比经营数据对比")
    parser.add_argument('--excel', required=True, help='当前周期的 POS 订单 Excel 文件')
    parser.add_argument('--db', required=True, help='长期订单分析 SQLite 数据库路径')
    parser.add_argument('--mode', required=True, choices=['week', 'month'], help='周期模式: week 或 month')
    parser.add_argument('--store', default=None, help='门店名称（不传则自动推断）')
    parser.add_argument('--output-dir', default='./output', help='输出目录（默认 ./output）')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print("=" * 50)
    print("周期对比分析工具")
    print("=" * 50)

    # ── Step 1: Load data ──
    print("\n[1/5] 加载数据...")
    db = DatabaseManager(args.db)

    result = load_and_dedup_excels([args.excel], set())
    if result['raw_orders'].empty:
        print("  错误：没有有效订单数据")
        return

    raw_orders = result['raw_orders']
    raw_items = result['raw_items']
    pre_merge_daily = result['pre_merge_daily']

    # Determine store
    if args.store:
        store_name = args.store
    else:
        # Try to infer from table names
        tables = raw_orders['桌台'].astype(str).unique()
        store_name = '万荷店'
        for t in tables:
            if '外' in t and not t.startswith('户外'):
                store_name = '保利店'
                break
            if '包房' in t:
                store_name = '保利店'
                break
    print(f"  门店: {store_name}")

    # ── Step 2: Validate period ──
    print("\n[2/5] 校验周期...")
    if raw_orders['下单时间'].dtype == 'object':
        raw_orders['_dt'] = pd.to_datetime(raw_orders['下单时间'], errors='coerce')
    else:
        raw_orders['_dt'] = raw_orders['下单时间']
    dates_in_data = sorted(set(
        d.strftime('%Y-%m-%d') for d in raw_orders['_dt'].dropna()
        if hasattr(d, 'strftime')
    ))

    period_info = validate_period(dates_in_data, args.mode)
    if period_info['errors']:
        print("  [周期校验失败]")
        for e in period_info['errors']:
            print(f'    ⚠ {e}')
        return
    print(f"  周期: {period_info['period_label']} ✓")
    print(f"  日期范围: {period_info['period_start']} ~ {period_info['period_end']}")

    # ── Step 3: Process & write to DB ──
    print("\n[3/5] 处理订单并写入数据库...")

    orders_clean = clean_orders(raw_orders)
    items_clean = clean_items(raw_items) if not raw_items.empty else pd.DataFrame()
    if not items_clean.empty:
        valid_ids = set(orders_clean['订单号'].astype(str))
        items_clean = items_clean[items_clean['订单号'].astype(str).isin(valid_ids)].copy()
        items_clean = items_clean[items_clean['菜品收入'] > 0].copy()

    item_sets, line_cnts = get_item_features(items_clean) if not items_clean.empty else ({}, {})
    orders_with_group, groups = merge_orders(orders_clean, item_sets, line_cnts,
                                              items_clean if not items_clean.empty else None)

    group_sum, stats = aggregate_groups(orders_with_group, items_clean if not items_clean.empty else None)

    # Run filter_groups per date
    group_sum['_date'] = pd.to_datetime(group_sum['开始'], errors='coerce').dt.strftime('%Y-%m-%d')
    group_sum['_area'] = group_sum['桌台'].apply(_area)
    group_sum['_meal'] = group_sum['开始'].apply(_meal_period)
    group_sum['是否会员'] = _compute_member_status(orders_with_group, group_sum)
    group_sum['_opener'] = _compute_opener(group_sum, orders_with_group)

    all_dates_in_data = sorted(set(
        d for d in group_sum['_date'].dropna().unique() if d and d != 'NaT'
    ))

    all_filtered = []
    for date in all_dates_in_data:
        day = group_sum[group_sum['_date'] == date].copy()
        if day.empty:
            continue
        try:
            filtered, fstats = filter_groups(day, items_clean if not items_clean.empty else None)
            filtered['_date'] = date
            filtered['_area'] = filtered['桌台'].apply(_area)
            filtered['_meal'] = filtered['开始'].apply(_meal_period)
            filtered['是否会员'] = _compute_member_status(orders_with_group, filtered)
            filtered['_opener'] = _compute_opener(filtered, orders_with_group)
            filtered['_filter_status'] = 'kept'
            all_filtered.append(filtered)
        except Exception as e:
            print(f"    [警告] {date} 过滤出错: {e}")

    if all_filtered:
        kept_groups = pd.concat(all_filtered, ignore_index=True)
    else:
        kept_groups = pd.DataFrame()

    # Write to DB
    print("  写入数据库...")
    source_file = os.path.basename(args.excel)
    db.insert_orders(raw_orders, source_file)
    db.insert_items(raw_items, source_file)
    group_sum['_filter_status'] = 'kept'
    db.insert_groups(group_sum)

    # Compute and write daily stats
    stats_result = compute_all_daily_stats(
        group_sum, orders_with_group, pre_merge_daily,
        items_clean if not items_clean.empty else None
    )
    if stats_result['overview_rows']:
        db.upsert_daily_overview(stats_result['overview_rows'])
    if stats_result['order_count_rows']:
        db.upsert_daily_order_counts(stats_result['order_count_rows'])
    if stats_result['bucket_rows']:
        db.upsert_daily_buckets(stats_result['bucket_rows'])
    if stats_result['opener_rows']:
        db.upsert_daily_opener_stats(stats_result['opener_rows'])

    print("  数据库更新完成")

    # ── Step 4: Compute comparison ──
    print("\n[4/5] 计算同比环比...")
    comparison_info = get_comparison_periods(period_info, args.mode)
    print(f"  环比: {comparison_info['ringbi_label']} ({comparison_info['ringbi_start']} ~ {comparison_info['ringbi_end']})")
    print(f"  同比: {comparison_info['tongbi_label']} ({comparison_info['tongbi_start']} ~ {comparison_info['tongbi_end']})")

    comp_data = compute_comparison(db, period_info, comparison_info, args.mode, store_name)

    if comp_data['data_quality']['ringbi_missing']:
        print(f"  [警告] 环比数据缺失")
    if comp_data['data_quality']['tongbi_missing']:
        print(f"  [警告] 同比数据缺失")

    # ── Step 5: Generate PDF ──
    print("\n[5/5] 生成 PDF 报告...")
    date_tag = period_info['period_start'].replace('-', '') + '_' + period_info['period_end'].replace('-', '')
    pdf_name = f'周期对比分析_{date_tag}_{store_name}.pdf'
    pdf_path = os.path.join(args.output_dir, pdf_name)

    generate_comparison_pdf(pdf_path, period_info, comparison_info, comp_data, args.mode, store_name)
    print(f"PDF 报告已生成: {pdf_path}")

    db.close()
    print("\n完成！")


if __name__ == '__main__':
    main()
