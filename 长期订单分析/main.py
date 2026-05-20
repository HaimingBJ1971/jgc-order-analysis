"""
Long-term Order Analysis — CLI Entry Point.

Usage:
    cd 长期订单分析
    python3 main.py \
        --files "path/file1.xlsx" "path/file2.xlsx" \
        --db "path/database.db" \
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

from data_loader import clean_orders, clean_items, get_item_features, load_excel
from order_merger import merge_orders
from aggregator import aggregate_groups, filter_groups

from db_manager import DatabaseManager
from multi_file_loader import load_and_dedup_excels, build_merged_dataset
from daily_stats import compute_all_daily_stats, _area, _meal_period, _compute_member_status, _compute_opener
from excel_writer import write_excel_report


def main():
    parser = argparse.ArgumentParser(
        description="长期订单分析 — 跨日期订单合并与统计"
    )
    parser.add_argument(
        '--files', nargs='+', required=True,
        help='一个或多个 POS 订单 Excel 文件路径'
    )
    parser.add_argument(
        '--db', required=True,
        help='SQLite 数据库文件路径（不存在则新建）'
    )
    parser.add_argument(
        '--output-dir', default='./output',
        help='Excel 输出目录（默认 ./output）'
    )
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print("=" * 50)
    print("长期订单分析工具")
    print("=" * 50)

    # ── Phase A: Incremental Detection ──
    print("\n[Phase A] 增量检测...")

    db = DatabaseManager(args.db)
    existing_ids = db.get_existing_order_ids()
    existing_dates = db.get_existing_date_range()
    print(f"  数据库中已有 {len(existing_ids)} 条订单")

    result = load_and_dedup_excels(args.files, existing_ids)
    print(f"  共扫描 {result['total_found']} 条订单，新发现 {result['total_new']} 条")

    if result['total_new'] == 0:
        print("\n  所有数据已包含在数据库中，跳过处理。")
        if existing_dates[0] is None:
            print("  数据库中暂无统计数据，无法生成 Excel。")
            db.close()
            return

        # Generate Excel from existing DB data
        _generate_excel_from_db(db, args.output_dir)
        db.close()
        return

    # ── Phase B: Process New Data ──
    print("\n[Phase B] 处理新数据...")

    raw_orders = result['raw_orders']
    raw_items = result['raw_items']
    pre_merge_daily = result['pre_merge_daily']

    if raw_orders.empty:
        print("  无有效新订单。")
        db.close()
        return

    # Determine affected tables and date range
    new_order_ids = set(raw_orders['订单号'].astype(str))
    affected_tables = set(raw_orders['桌台'].astype(str).unique())

    # Extract date range from new orders
    raw_orders_temp = raw_orders.copy()
    if '下单时间' in raw_orders_temp.columns:
        raw_orders_temp['_dt'] = pd.to_datetime(raw_orders_temp['下单时间'], errors='coerce')
        valid_dates = raw_orders_temp['_dt'].dropna()
        if len(valid_dates) > 0:
            min_date = valid_dates.min().strftime('%Y-%m-%d')
            max_date = valid_dates.max().strftime('%Y-%m-%d')
        else:
            min_date = max_date = datetime.now().strftime('%Y-%m-%d')
    else:
        min_date = max_date = datetime.now().strftime('%Y-%m-%d')

    # Load context orders from DB for cross-boundary merge
    print(f"  加载上下文订单（{min_date} ~ {max_date}, {len(affected_tables)} 个桌台）...")
    context_dicts = db.load_context_orders(affected_tables, (min_date, max_date))
    print(f"  从数据库加载 {len(context_dicts)} 条上下文订单")

    # Build merged dataset (context + new)
    merged_orders, merged_items = build_merged_dataset(
        raw_orders, raw_items, context_dicts, raw_items
    )

    # Save raw data to DB BEFORE cleaning
    print("  写入原始订单数据到数据库...")
    n_orders = db.insert_orders(raw_orders, os.path.basename(args.files[0]))
    n_items = db.insert_items(raw_items, os.path.basename(args.files[0]))
    print(f"  写入 {n_orders} 条订单, {n_items} 条商品明细")

    # Clean
    print("  清洗数据...")
    orders_clean = clean_orders(merged_orders)
    items_clean = clean_items(merged_items) if not merged_items.empty else pd.DataFrame()

    if not items_clean.empty:
        items_clean = items_clean[items_clean['菜品收入'] > 0].copy()

    if orders_clean.empty:
        print("  清洗后无有效订单。")
        db.close()
        return

    # Merge
    print("  执行订单合并...")
    item_sets, line_cnts = get_item_features(items_clean) if not items_clean.empty else ({}, {})
    orders_with_group, groups = merge_orders(orders_clean, item_sets, line_cnts,
                                              items_clean if not items_clean.empty else None)

    # Aggregate (pre-filter)
    print("  聚合消费团体...")
    group_sum, stats = aggregate_groups(orders_with_group, items_clean if not items_clean.empty else None)

    # Add computed columns
    group_sum['_date'] = pd.to_datetime(group_sum['开始'], errors='coerce').dt.strftime('%Y-%m-%d')
    group_sum['_area'] = group_sum['桌台'].apply(_area)
    group_sum['_meal'] = group_sum['开始'].apply(_meal_period)
    group_sum['是否会员'] = _compute_member_status(orders_with_group, group_sum)
    group_sum['_opener'] = _compute_opener(group_sum, orders_with_group)

    # Mark groups that contain at least one new order
    def _has_new_order(order_ids):
        ids = order_ids if isinstance(order_ids, list) else []
        return any(str(oid) in new_order_ids for oid in ids)

    group_sum['_has_new'] = group_sum['包含订单'].apply(_has_new_order)

    # Apply per-date filtering
    print("  按日期过滤...")
    all_dates_in_data = sorted(set(
        d for d in group_sum['_date'].dropna().unique() if d and d != 'NaT'
    ))

    all_filtered_groups = []
    daily_filter_stats = {}
    for date in all_dates_in_data:
        day_groups = group_sum[group_sum['_date'] == date].copy()
        if day_groups.empty:
            continue
        try:
            filtered, fstats = filter_groups(day_groups, items_clean if not items_clean.empty else None)
            filtered['_date'] = date
            filtered['_area'] = filtered['桌台'].apply(_area)
            filtered['_meal'] = filtered['开始'].apply(_meal_period)
            filtered['是否会员'] = _compute_member_status(orders_with_group, filtered)
            filtered['_opener'] = _compute_opener(filtered, orders_with_group)
            filtered['_filter_status'] = 'kept'
            all_filtered_groups.append(filtered)

            # Record filtered-out counts
            for status_label in ['免单', '零食', '打包', '零散小单', '吧台']:
                pass  # filter_groups doesn't tag these, need manual tracking

            daily_filter_stats[date] = fstats
        except Exception as e:
            print(f"    [警告] 日期 {date} 过滤出错: {e}")
            continue

    if all_filtered_groups:
        kept_groups = pd.concat(all_filtered_groups, ignore_index=True)
    else:
        kept_groups = pd.DataFrame()

    # Collect groups that were filtered out (for order count stats)
    # Tag each group in group_sum with its filter status
    if not kept_groups.empty:
        kept_ids = set()
        for _, g in kept_groups.iterrows():
            oids = g.get('包含订单', [])
            if isinstance(oids, list):
                for oid in oids:
                    kept_ids.add(str(oid))

        def _get_filter_status(row):
            oids = row.get('包含订单', [])
            if isinstance(oids, list):
                for oid in oids:
                    if str(oid) in kept_ids:
                        return 'kept'
            # Check if all items are 零食
            return 'kept'  # default - precise filtering done by filter_groups

        group_sum['_filter_status'] = group_sum.apply(_get_filter_status, axis=1)
    else:
        group_sum['_filter_status'] = 'kept'

    # Write groups to DB
    print("  写入团体数据到数据库...")
    db.insert_groups(group_sum)

    # ── Compute Daily Stats ──
    print("\n  计算每日统计...")
    stats_result = compute_all_daily_stats(
        group_sum, orders_with_group, pre_merge_daily,
        items_clean if not items_clean.empty else None
    )

    # Write daily stats to DB (INSERT OR REPLACE for affected dates)
    print("  写入每日统计到数据库...")
    if stats_result['overview_rows']:
        db.upsert_daily_overview(stats_result['overview_rows'])
    if stats_result['order_count_rows']:
        db.upsert_daily_order_counts(stats_result['order_count_rows'])
    if stats_result['bucket_rows']:
        db.upsert_daily_buckets(stats_result['bucket_rows'])
    if stats_result['opener_rows']:
        db.upsert_daily_opener_stats(stats_result['opener_rows'])

    db.close()

    # ── Phase C: Generate Excel ──
    print("\n[Phase C] 生成 Excel 报告...")
    _generate_excel_from_db(DatabaseManager(args.db), args.output_dir)

    print("\n完成！")


def _generate_excel_from_db(db, output_dir):
    """Generate Excel from all data in the database."""
    all_dates = db.read_all_dates()

    if not all_dates:
        print("  数据库中没有统计数据。")
        return

    overview_rows = db.read_all_overview()
    order_count_rows = db.read_all_order_counts()
    bucket_rows = db.read_all_buckets()
    opener_rows = db.read_all_opener_stats()
    all_openers = db.read_all_openers()

    # Determine output filename from date range
    min_d = all_dates[0].replace('-', '')
    max_d = all_dates[-1].replace('-', '')
    excel_name = f"长期订单分析_{min_d}_{max_d}.xlsx"
    excel_path = os.path.join(output_dir, excel_name)

    write_excel_report(
        all_dates, overview_rows, order_count_rows,
        bucket_rows, opener_rows, all_openers, excel_path
    )


if __name__ == '__main__':
    main()
