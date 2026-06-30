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
_order_root = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, os.path.abspath(_order_root))

from data_loader import load_excel, clean_orders, clean_items, get_item_features
from order_merger import merge_orders
from aggregator import aggregate_groups, filter_groups
from ingest_validator import validate_pos_excel

# Add long-term analysis modules to path
_lt_dir = os.path.join(os.path.dirname(__file__), '..', '长期订单分析')
sys.path.insert(0, os.path.abspath(_lt_dir))

from db_manager import DatabaseManager
from store_utils import infer_order_store
from daily_stats import compute_all_daily_stats, _area, _meal_period, _compute_member_status, _compute_opener

from period_validator import validate_period, get_comparison_periods
from comparator import compute_comparison
from pdf_report import generate_comparison_pdf
from word_report import generate_comparison_word


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

    print("\n[0/5] 入库前完整性检查...")
    v = validate_pos_excel(args.excel)
    if not v.ok:
        for e in v.errors:
            print(f"  ERROR: {e}")
        print("\n请修正 Excel 后重新提交，再执行入库。")
        raise SystemExit(1)
    print("  列与日期完整性校验通过 ✓")

    # ── Step 1: Load data ──
    print("\n[1/5] 加载数据...")
    db = DatabaseManager(args.db)

    raw_orders, raw_items = load_excel(args.excel)
    if raw_orders.empty:
        print("  错误：没有有效订单数据")
        return

    # Extract pre-clean daily counts (matching merge tool)
    pre_merge_daily = {}
    if '下单时间' in raw_orders.columns:
        raw_orders['_date'] = pd.to_datetime(raw_orders['下单时间'], errors='coerce').dt.strftime('%Y-%m-%d')
        for date, grp in raw_orders.groupby('_date'):
            count_raw = len(grp)
            waimai = int(grp['桌台'].astype(str).str.contains('外点自取').sum())
            fei_tangshi = int((grp['订单类型'] != '堂食').sum()) if '订单类型' in grp.columns else 0
            pre_merge_daily[date] = {'原始订单数': count_raw, '外卖订单数': waimai, '非堂食订单数': fei_tangshi}

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
    dates_in_data = sorted(set(
        d for d in raw_orders['_date'].dropna().unique() if d and d != 'NaT'
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

    # Global filter (matching merge tool behavior, not per-date)
    kept_groups, filter_stats = filter_groups(group_sum, items_clean if not items_clean.empty else None)

    # Tag filter status
    kept_ids = set()
    for _, g in kept_groups.iterrows():
        for oid in (g.get('包含订单', []) or []):
            kept_ids.add(str(oid))

    def _tag_status(row):
        oids = row.get('包含订单', []) or []
        if any(str(o) in kept_ids for o in oids):
            return 'kept'
        row_rev = row.get('订单收入', 0) or 0
        row_ppl = row.get('人均消费', 0) or 0
        if row_ppl <= 0 or (isinstance(row_ppl, float) and pd.isna(row_ppl)):
            return '免单'
        return 'other'

    group_sum['_filter_status'] = group_sum.apply(_tag_status, axis=1)

    # Write to DB
    print("  写入数据库...")
    source_file = os.path.basename(args.excel)
    db.insert_orders(raw_orders, source_file)
    db.insert_items(raw_items, source_file)
    if store_name:
        order_ids = [
            str(row["订单号"])
            for _, row in raw_orders.iterrows()
            if infer_order_store(row.to_dict(), source_file) == store_name
        ]
        db.relabel_order_sources(order_ids, source_file)
        db.relabel_item_sources(order_ids, source_file)
    db.insert_groups(group_sum)

    # Compute and write daily stats (using tagged group_sum)
    stats_result = compute_all_daily_stats(
        group_sum, orders_with_group, pre_merge_daily,
        items_clean if not items_clean.empty else None,
        store_name=store_name,
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

    # Word output
    word_name = f'周期对比分析_{date_tag}_{store_name}.docx'
    word_path = os.path.join(args.output_dir, word_name)
    generate_comparison_word(word_path, period_info, comparison_info, comp_data, args.mode, store_name)

    db.close()
    print("\n完成！")


if __name__ == '__main__':
    main()
