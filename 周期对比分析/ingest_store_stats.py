#!/usr/bin/env python3
"""Ingest per-store daily stats from a POS Excel into SQLite (no report output).

Usage:
    python ingest_store_stats.py \\
        --excel path.xlsx --store 万荷店 --db path.db \\
        [--start 2025-06-09] [--end 2025-06-15]
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

_skill_dir = os.path.join(os.path.dirname(__file__), "..", "每日订单分析", "order_merger_skill")
_lt_dir = os.path.join(os.path.dirname(__file__), "..", "长期订单分析")
sys.path.insert(0, os.path.abspath(_skill_dir))
sys.path.insert(0, os.path.abspath(_lt_dir))

from data_loader import load_excel, clean_orders, clean_items, get_item_features
from order_merger import merge_orders
from aggregator import aggregate_groups, filter_groups
from ingest_validator import validate_pos_excel
from db_manager import DatabaseManager
from store_utils import read_pos_store_from_excel, infer_store_from_pos_name
from daily_stats import compute_all_daily_stats, _area, _meal_period, _compute_member_status, _compute_opener


def detect_store_from_excel(excel_path: str) -> str:
    """Detect store from POS Excel metadata (门店名称), not filename."""
    meta_name = read_pos_store_from_excel(excel_path)
    store = infer_store_from_pos_name(meta_name)
    if store == "未知门店":
        raise ValueError(f"无法从文件内容识别门店: {excel_path} (metadata 门店名称={meta_name!r})")
    return store


def _filter_by_date(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    if df.empty or (not start and not end):
        return df
    out = df.copy()
    out["_dt"] = pd.to_datetime(out["下单时间"], errors="coerce")
    if start:
        out = out[out["_dt"] >= pd.Timestamp(start)]
    if end:
        out = out[out["_dt"] <= pd.Timestamp(end) + pd.Timedelta(hours=23, minutes=59, seconds=59)]
    return out.drop(columns=["_dt"], errors="ignore")


def ingest(excel_path: str, store_name: str, db_path: str, start: str | None, end: str | None) -> None:
    validation = validate_pos_excel(excel_path)
    validation.raise_if_failed(prefix="单店入库")
    if validation.store_name != store_name:
        raise SystemExit(f"门店不一致: CLI={store_name}, 文件内容={validation.store_name}")

    db = DatabaseManager(db_path)
    raw_orders, raw_items = load_excel(excel_path)
    if start or end:
        raw_orders = _filter_by_date(raw_orders, start, end)
        if not raw_items.empty:
            valid_ids = set(raw_orders["订单号"].astype(str))
            raw_items = raw_items[raw_items["订单号"].astype(str).isin(valid_ids)].copy()

    if raw_orders.empty:
        print("  无有效订单，跳过。")
        db.close()
        return

    pre_merge_daily = {}
    raw_orders = raw_orders.copy()
    raw_orders["_date"] = pd.to_datetime(raw_orders["下单时间"], errors="coerce").dt.strftime("%Y-%m-%d")
    for date, grp in raw_orders.groupby("_date"):
        pre_merge_daily[date] = {
            "原始订单数": len(grp),
            "外卖订单数": int(grp["桌台"].astype(str).str.contains("外点自取").sum()),
            "非堂食订单数": int((grp["订单类型"] != "堂食").sum()) if "订单类型" in grp.columns else 0,
        }

    orders_clean = clean_orders(raw_orders)
    items_clean = clean_items(raw_items) if not raw_items.empty else pd.DataFrame()
    if not items_clean.empty:
        valid_ids = set(orders_clean["订单号"].astype(str))
        items_clean = items_clean[items_clean["订单号"].astype(str).isin(valid_ids)].copy()
        items_clean["菜品收入"] = pd.to_numeric(items_clean["菜品收入"], errors="coerce").fillna(0)
        items_clean = items_clean[items_clean["菜品收入"] > 0].copy()

    item_sets, line_cnts = get_item_features(items_clean) if not items_clean.empty else ({}, {})
    orders_with_group, _ = merge_orders(
        orders_clean, item_sets, line_cnts, items_clean if not items_clean.empty else None
    )
    group_sum, _ = aggregate_groups(orders_with_group, items_clean if not items_clean.empty else None)

    group_sum["_date"] = pd.to_datetime(group_sum["开始"], errors="coerce").dt.strftime("%Y-%m-%d")
    group_sum["_area"] = group_sum["桌台"].apply(_area)
    group_sum["_meal"] = group_sum["开始"].apply(_meal_period)
    group_sum["是否会员"] = _compute_member_status(orders_with_group, group_sum)
    group_sum["_opener"] = _compute_opener(group_sum, orders_with_group)

    kept_groups, _ = filter_groups(group_sum, items_clean if not items_clean.empty else None)
    kept_ids = set()
    for _, g in kept_groups.iterrows():
        for oid in g.get("包含订单", []) or []:
            kept_ids.add(str(oid))

    def _tag_status(row):
        oids = row.get("包含订单", []) or []
        if any(str(o) in kept_ids for o in oids):
            return "kept"
        row_ppl = row.get("人均消费", 0) or 0
        if row_ppl <= 0 or (isinstance(row_ppl, float) and pd.isna(row_ppl)):
            return "免单"
        return "other"

    group_sum["_filter_status"] = group_sum.apply(_tag_status, axis=1)

    stats = compute_all_daily_stats(
        group_sum, orders_with_group, pre_merge_daily,
        items_clean if not items_clean.empty else None,
        store_name=store_name,
    )
    source_file = os.path.basename(excel_path)
    snapshot_result = db.replace_pos_snapshot(
        raw_orders,
        raw_items,
        group_sum,
        source_file,
        stats_result=stats,
    )

    dates = sorted(set(d for d in group_sum["_date"].dropna().unique() if d and d != "NaT"))
    overall = sum(r[4] for r in stats["overview_rows"] if r[2] == "整体" and r[3] == "")
    print(
        f"  入库 {store_name}: {len(raw_orders)} 单, {len(dates)} 天, "
        f"整体营业额合计 ¥{overall:,.0f}; "
        f"移除旧订单 {snapshot_result['stale_orders_removed']} 单, "
        f"旧团体 {snapshot_result['old_groups_removed']} 个"
    )
    db.close()


def main():
    parser = argparse.ArgumentParser(description="单店 POS 统计入库（可指定日期区间）")
    parser.add_argument("--excel", required=True)
    parser.add_argument("--store", help="门店名称；不传则从 Excel 元数据 门店名称 自动识别")
    parser.add_argument("--db", required=True)
    parser.add_argument("--start", help="仅处理此日起（YYYY-MM-DD）")
    parser.add_argument("--end", help="仅处理此日止（YYYY-MM-DD）")
    args = parser.parse_args()
    detected_store = detect_store_from_excel(args.excel)
    store = args.store or detected_store
    if args.store and detected_store != args.store:
        raise SystemExit(f"门店不一致: CLI={args.store}, 文件内容={detected_store}")
    print(f"  识别门店(内容): {store}")
    ingest(args.excel, store, args.db, args.start, args.end)


if __name__ == "__main__":
    main()
