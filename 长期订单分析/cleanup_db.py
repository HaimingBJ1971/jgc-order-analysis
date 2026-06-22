#!/usr/bin/env python3
"""Remove stale __legacy__ daily stats and junk order rows from the long-term DB."""

from __future__ import annotations

import argparse
import re
import sqlite3

_VALID_ORDER_ID = re.compile(r"^\d+$")


def cleanup(db_path: str, dry_run: bool = False) -> dict:
    conn = sqlite3.connect(db_path)
    stats = {}

    def _count(table: str, where: str = "1=1") -> int:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]

    stats["legacy_overview"] = _count("daily_overview", "store_name='__legacy__'")
    stats["legacy_order_counts"] = _count("daily_order_counts", "store_name='__legacy__'")
    stats["legacy_buckets"] = _count("daily_buckets", "store_name='__legacy__'")

    bad_orders = [
        row[0]
        for row in conn.execute("SELECT 订单号 FROM orders").fetchall()
        if not _VALID_ORDER_ID.match(str(row[0]))
    ]
    orphan_orders = [
        row[0]
        for row in conn.execute(
            """
            SELECT o.订单号 FROM orders o
            LEFT JOIN items i ON o.订单号 = i.订单号
            WHERE i.订单号 IS NULL
            """
        ).fetchall()
    ]
    stats["junk_order_ids"] = bad_orders
    stats["orphan_orders_no_items"] = len(orphan_orders)

    if dry_run:
        conn.close()
        return stats

    conn.execute("DELETE FROM daily_overview WHERE store_name='__legacy__'")
    conn.execute("DELETE FROM daily_order_counts WHERE store_name='__legacy__'")
    conn.execute("DELETE FROM daily_buckets WHERE store_name='__legacy__'")

    for oid in bad_orders:
        conn.execute("DELETE FROM items WHERE 订单号=?", (oid,))
        conn.execute("DELETE FROM orders WHERE 订单号=?", (oid,))

    for oid in orphan_orders:
        conn.execute("DELETE FROM orders WHERE 订单号=?", (oid,))

    conn.commit()
    conn.close()
    return stats


def main():
    parser = argparse.ArgumentParser(description="清理长期订单 DB 中的 legacy 汇总行与无效订单")
    parser.add_argument("--db", required=True)
    parser.add_argument("--dry-run", action="store_true", help="只统计，不删除")
    args = parser.parse_args()
    stats = cleanup(args.db, dry_run=args.dry_run)
    mode = "（预览）" if args.dry_run else "（已执行）"
    print(f"清理{mode}:")
    print(f"  daily_overview __legacy__: {stats['legacy_overview']}")
    print(f"  daily_order_counts __legacy__: {stats['legacy_order_counts']}")
    print(f"  daily_buckets __legacy__: {stats['legacy_buckets']}")
    print(f"  无效订单号: {stats['junk_order_ids']}")
    print(f"  无明细孤儿订单: {stats['orphan_orders_no_items']}")


if __name__ == "__main__":
    main()
