#!/usr/bin/env python3
"""Correct mis-tagged source_file rows where POS 门店名称 disagrees with filename."""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from db_manager import DatabaseManager


def main():
    parser = argparse.ArgumentParser(description="按 POS 门店名称纠正 orders/items 的 source_file")
    parser.add_argument("--db", required=True, help="长期订单分析 SQLite 路径")
    args = parser.parse_args()

    db = DatabaseManager(args.db)
    stats = db.fix_mislabeled_store_sources()
    print(f"已纠正 orders: {stats['orders_fixed']} 条, items: {stats['items_fixed']} 条")
    db.close()


if __name__ == "__main__":
    main()
