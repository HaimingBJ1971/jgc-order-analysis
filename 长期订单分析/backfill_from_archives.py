#!/usr/bin/env python3
"""
从归档 Excel 回填主库 orders/items 的完整列 JSON。

用法:
    cd 订单与桌访合并/长期订单分析
    python3 backfill_from_archives.py \\
        --db output/长期订单分析.db \\
        --dir "/path/历史数据记录/订单明细表" \\
        --extra ../店内订单历史数据Excel文件/*.xlsx
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

_skill_dir = os.path.join(os.path.dirname(__file__), "..", "每日订单分析", "order_merger_skill")
sys.path.insert(0, os.path.abspath(_skill_dir))
_order_root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(_order_root))

from data_loader import load_excel  # noqa: E402
from db_manager import DatabaseManager  # noqa: E402

_END_DATE_RE = re.compile(r"~(\d{4}-\d{2}-\d{2})")


def _file_sort_key(path: Path) -> str:
    m = _END_DATE_RE.search(path.name)
    return m.group(1) if m else path.name


def collect_xlsx(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            files.extend(sorted(path.glob("*.xlsx")))
        elif path.is_file() and path.suffix.lower() == ".xlsx":
            files.append(path)
    # 按文件名结束日期排序，后加载的文件覆盖较早导出
    return sorted(set(files), key=_file_sort_key)


def load_merged_archives(files: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame]:
    order_parts: list[pd.DataFrame] = []
    item_parts: list[pd.DataFrame] = []
    for fp in files:
        print(f"  读取 {fp.name} ...")
        orders, items = load_excel(str(fp))
        orders = orders.copy()
        items = items.copy()
        orders["source_file"] = fp.name
        items["source_file"] = fp.name
        order_parts.append(orders)
        item_parts.append(items)

    if not order_parts:
        return pd.DataFrame(), pd.DataFrame()

    orders_all = pd.concat(order_parts, ignore_index=True)
    items_all = pd.concat(item_parts, ignore_index=True)

    orders_all = orders_all[orders_all["订单号"].astype(str).str.fullmatch(r"\d+", na=False)]
    items_all = items_all[items_all["订单号"].astype(str).str.fullmatch(r"\d+", na=False)]

    orders_dedup = orders_all.drop_duplicates(subset="订单号", keep="last").copy()
    if not items_all.empty:
        selected_snapshot = orders_dedup[["订单号", "source_file"]].copy()
        selected_snapshot["_order_id"] = selected_snapshot["订单号"].astype(str)
        selected_snapshot["_source_file"] = selected_snapshot["source_file"].astype(str)
        selected_snapshot = selected_snapshot[["_order_id", "_source_file"]].drop_duplicates()

        items_all = items_all.copy()
        items_all["_order_id"] = items_all["订单号"].astype(str)
        items_all["_source_file"] = items_all["source_file"].astype(str)
        items_all = items_all.merge(
            selected_snapshot,
            on=["_order_id", "_source_file"],
            how="inner",
        )
        # POS 商品明细必须保留行级数据。同一订单内同一商品可能拆成多行，
        # 不能按「订单号 + 商品编码 + 商品名称」去重，否则会少算销量。
        # 历史导出包存在边界重叠时，订单快照先决定取哪个导出包；
        # 商品行只在同一导出包内部按 POS 行级键去重。
        items_all["_row_no"] = range(len(items_all))
        seq = items_all["序号"].astype(str) if "序号" in items_all.columns else items_all["_row_no"].astype(str)
        items_all["_item_line_key"] = (
            items_all["source_file"].astype(str)
            + "|"
            + items_all["订单号"].astype(str)
            + "|seq:"
            + seq
        )
        items_dedup = (
            items_all.drop_duplicates(subset="_item_line_key", keep="last")
            .drop(columns=["_item_line_key", "_row_no", "_order_id", "_source_file"])
            .copy()
        )
    else:
        items_dedup = pd.DataFrame()

    print(f"  合并去重后：订单 {len(orders_dedup)} 条，商品行级明细 {len(items_dedup)} 条")
    return orders_dedup, items_dedup


def audit_orders(db: DatabaseManager, std_cols: list[str]) -> dict:
    stats = {"total": 0, "missing_any_col": 0, "missing_门店名称": 0, "missing_会员手机号": 0}
    cur = db.conn.execute("SELECT 原始数据 FROM orders")
    while True:
        rows = cur.fetchmany(5000)
        if not rows:
            break
        for (raw,) in rows:
            stats["total"] += 1
            d = json.loads(raw)
            if "门店名称" not in d:
                stats["missing_门店名称"] += 1
            if "会员手机号" not in d:
                stats["missing_会员手机号"] += 1
            for c in std_cols:
                if c in DatabaseManager._INTERNAL_ROW_KEYS:
                    continue
                if c not in d or d[c] is None or str(d[c]).strip().lower() in ("", "nan", "none"):
                    stats["missing_any_col"] += 1
                    break
    return stats


def delete_items_for_orders(db: DatabaseManager, order_ids: set[str], chunk_size: int = 800) -> int:
    """Delete existing item rows for archive orders before row-level backfill."""
    ids = sorted(str(x) for x in order_ids)
    deleted = 0
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i : i + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        before = db.conn.total_changes
        db.conn.execute(f"DELETE FROM items WHERE 订单号 IN ({placeholders})", chunk)
        deleted += db.conn.total_changes - before
    db.conn.commit()
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description="从归档 Excel 回填 orders/items 完整列")
    parser.add_argument("--db", required=True, help="长期订单分析 SQLite 主库路径")
    parser.add_argument(
        "--dir",
        action="append",
        default=[],
        help="含历史店内订单 Excel 的目录（可多次指定）",
    )
    parser.add_argument(
        "--extra",
        nargs="*",
        default=[],
        help="额外 Excel 文件或目录（补最近两周等）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    args = parser.parse_args()

    sources = list(args.dir) + list(args.extra)
    if not sources:
        print("请至少指定 --dir 或 --extra")
        raise SystemExit(1)

    files = collect_xlsx(sources)
    if not files:
        print("未找到任何 .xlsx 文件")
        raise SystemExit(1)

    print(f"共 {len(files)} 个归档文件")
    orders_df, items_df = load_merged_archives(files)
    if orders_df.empty:
        print("归档中无有效订单")
        raise SystemExit(1)

    std_cols = [c for c in orders_df.columns if c != "source_file"]
    db = DatabaseManager(args.db)

    before = audit_orders(db, std_cols)
    print("\n回填前 audit:", before)

    existing_ids = db.get_existing_order_ids()
    archive_ids = set(orders_df["订单号"].astype(str))
    overlap = archive_ids & existing_ids
    only_db = existing_ids - archive_ids
    only_archive = archive_ids - existing_ids

    print(f"\n订单号：库内 {len(existing_ids)}，归档 {len(archive_ids)}，交集 {len(overlap)}")
    print(f"  仅在库内（归档无）：{len(only_db)}")
    print(f"  仅在归档（库内无）：{len(only_archive)}")

    if args.dry_run:
        db.close()
        print("\nDRY-RUN 完成，未写库")
        return

    print("\n写入 orders ...")
    n_orders = db.replace_orders(orders_df, "archive_backfill")
    print(f"  replace_orders: {n_orders}")

    if not items_df.empty:
        print("删除归档订单旧商品明细 ...")
        deleted_items = delete_items_for_orders(db, archive_ids)
        print(f"  deleted old item rows: {deleted_items}")

        print("写入 items ...")
        n_items = db.insert_items(items_df, "archive_backfill")
        print(f"  insert_items (upsert): {n_items}")

    after = audit_orders(db, std_cols)
    print("\n回填后 audit:", after)
    db.close()
    print("\n完成")


if __name__ == "__main__":
    main()
