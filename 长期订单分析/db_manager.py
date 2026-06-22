"""
SQLite database manager for long-term order analysis.

Handles: schema creation, incremental detection, data read/write,
context loading for cross-boundary merges.
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta


class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    # ── Schema ──────────────────────────────────────────────

    def _create_tables(self):
        c = self.conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                订单号 TEXT PRIMARY KEY,
                原始数据 TEXT NOT NULL,
                source_file TEXT,
                ingest_time TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                订单号 TEXT NOT NULL,
                商品编码 TEXT,
                商品名称 TEXT,
                原始数据 TEXT NOT NULL,
                source_file TEXT,
                ingest_time TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_items_dedup ON items(订单号, 商品编码, 商品名称);

            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_date TEXT NOT NULL,
                table_name TEXT,
                group_amount REAL,
                order_revenue REAL,
                order_count INTEGER,
                start_time TEXT,
                end_time TEXT,
                guest_count REAL,
                anchor_order_id TEXT,
                first_order_id TEXT,
                order_ids TEXT,
                per_person REAL,
                is_member INTEGER DEFAULT 0,
                area TEXT,
                meal_period TEXT,
                filter_status TEXT DEFAULT 'kept',
                opener TEXT,
                UNIQUE(group_date, first_order_id, table_name)
            );

            CREATE TABLE IF NOT EXISTS daily_overview (
                date TEXT NOT NULL,
                category TEXT NOT NULL,
                sub_category TEXT DEFAULT '',
                营业额 REAL DEFAULT 0,
                百分比 REAL DEFAULT 0,
                人数 REAL DEFAULT 0,
                人均 REAL DEFAULT 0,
                PRIMARY KEY (date, category, sub_category)
            );

            CREATE TABLE IF NOT EXISTS daily_order_counts (
                date TEXT PRIMARY KEY,
                原始订单数 INTEGER DEFAULT 0,
                外卖订单数 INTEGER DEFAULT 0,
                非堂食订单数 INTEGER DEFAULT 0,
                免单订单数 INTEGER DEFAULT 0,
                被合并订单数 INTEGER DEFAULT 0,
                合并后消费团体数 INTEGER DEFAULT 0,
                零食团体数 INTEGER DEFAULT 0,
                打包团体数 INTEGER DEFAULT 0,
                零散小单团体数 INTEGER DEFAULT 0,
                吧台团体数 INTEGER DEFAULT 0,
                统计消费团体数 INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS daily_buckets (
                date TEXT NOT NULL,
                bucket TEXT NOT NULL,
                订单数 INTEGER DEFAULT 0,
                占比 REAL DEFAULT 0,
                PRIMARY KEY (date, bucket)
            );

            CREATE TABLE IF NOT EXISTS daily_opener_stats (
                date TEXT NOT NULL,
                opener_name TEXT NOT NULL,
                order_count INTEGER DEFAULT 0,
                total_amount REAL DEFAULT 0,
                PRIMARY KEY (date, opener_name)
            );

            CREATE INDEX IF NOT EXISTS idx_items_order ON items(订单号);
            CREATE INDEX IF NOT EXISTS idx_groups_date ON groups(group_date);
            CREATE INDEX IF NOT EXISTS idx_groups_table ON groups(table_name);
        """)
        self.conn.commit()
        self._migrate_schema()

    def _column_exists(self, table: str, column: str) -> bool:
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r[1] == column for r in rows)

    def _migrate_schema(self):
        """Add store_name dimension to daily stats tables (one-time migration)."""
        if not self._column_exists("daily_overview", "store_name"):
            self.conn.executescript("""
                CREATE TABLE daily_overview_new (
                    date TEXT NOT NULL,
                    store_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    sub_category TEXT DEFAULT '',
                    营业额 REAL DEFAULT 0,
                    百分比 REAL DEFAULT 0,
                    人数 REAL DEFAULT 0,
                    人均 REAL DEFAULT 0,
                    PRIMARY KEY (date, store_name, category, sub_category)
                );
                INSERT INTO daily_overview_new
                    (date, store_name, category, sub_category, 营业额, 百分比, 人数, 人均)
                SELECT date, '__legacy__', category, sub_category, 营业额, 百分比, 人数, 人均
                FROM daily_overview;
                DROP TABLE daily_overview;
                ALTER TABLE daily_overview_new RENAME TO daily_overview;
            """)
        if not self._column_exists("daily_buckets", "store_name"):
            self.conn.executescript("""
                CREATE TABLE daily_buckets_new (
                    date TEXT NOT NULL,
                    store_name TEXT NOT NULL,
                    bucket TEXT NOT NULL,
                    订单数 INTEGER DEFAULT 0,
                    占比 REAL DEFAULT 0,
                    PRIMARY KEY (date, store_name, bucket)
                );
                INSERT INTO daily_buckets_new (date, store_name, bucket, 订单数, 占比)
                SELECT date, '__legacy__', bucket, 订单数, 占比 FROM daily_buckets;
                DROP TABLE daily_buckets;
                ALTER TABLE daily_buckets_new RENAME TO daily_buckets;
            """)
        if not self._column_exists("daily_order_counts", "store_name"):
            self.conn.executescript("""
                CREATE TABLE daily_order_counts_new (
                    date TEXT NOT NULL,
                    store_name TEXT NOT NULL,
                    原始订单数 INTEGER DEFAULT 0,
                    外卖订单数 INTEGER DEFAULT 0,
                    非堂食订单数 INTEGER DEFAULT 0,
                    免单订单数 INTEGER DEFAULT 0,
                    被合并订单数 INTEGER DEFAULT 0,
                    合并后消费团体数 INTEGER DEFAULT 0,
                    零食团体数 INTEGER DEFAULT 0,
                    打包团体数 INTEGER DEFAULT 0,
                    零散小单团体数 INTEGER DEFAULT 0,
                    吧台团体数 INTEGER DEFAULT 0,
                    统计消费团体数 INTEGER DEFAULT 0,
                    PRIMARY KEY (date, store_name)
                );
                INSERT INTO daily_order_counts_new (
                    date, store_name, 原始订单数, 外卖订单数, 非堂食订单数, 免单订单数,
                    被合并订单数, 合并后消费团体数, 零食团体数, 打包团体数,
                    零散小单团体数, 吧台团体数, 统计消费团体数
                )
                SELECT date, '__legacy__', 原始订单数, 外卖订单数, 非堂食订单数, 免单订单数,
                       被合并订单数, 合并后消费团体数, 零食团体数, 打包团体数,
                       零散小单团体数, 吧台团体数, 统计消费团体数
                FROM daily_order_counts;
                DROP TABLE daily_order_counts;
                ALTER TABLE daily_order_counts_new RENAME TO daily_order_counts;
            """)
        self.conn.commit()

    # ── Incremental Detection ───────────────────────────────

    def get_existing_order_ids(self) -> set:
        """Return set of all order IDs already in the database."""
        rows = self.conn.execute("SELECT 订单号 FROM orders").fetchall()
        return {r[0] for r in rows}

    def get_existing_date_range(self) -> tuple:
        """Return (min_date, max_date) already in daily_order_counts, or (None, None)."""
        row = self.conn.execute(
            "SELECT MIN(date), MAX(date) FROM daily_order_counts"
        ).fetchone()
        return (row[0], row[1])

    # ── Context Loading (for cross-boundary merge) ──────────

    def load_context_orders(self, table_names: set, date_range: tuple) -> list:
        """
        Load existing orders from DB for given tables within date_range ±1 day,
        returned as list of dicts (raw order data) for merge context.
        """
        min_date, max_date = date_range
        if min_date is None or max_date is None:
            return []

        min_dt = datetime.strptime(min_date, "%Y-%m-%d") - timedelta(days=1)
        max_dt = datetime.strptime(max_date, "%Y-%m-%d") + timedelta(days=1)

        context_orders = []
        for table in table_names:
            rows = self.conn.execute(
                """SELECT o.原始数据 FROM orders o
                   INNER JOIN groups g ON o.订单号 = g.first_order_id
                   WHERE g.table_name = ?
                     AND g.group_date BETWEEN ? AND ?""",
                (table, min_dt.strftime("%Y-%m-%d"), max_dt.strftime("%Y-%m-%d"))
            ).fetchall()
            for (raw_json,) in rows:
                try:
                    context_orders.append(json.loads(raw_json))
                except (json.JSONDecodeError, TypeError):
                    continue
        return context_orders

    # ── Write Raw Data ──────────────────────────────────────

    def insert_orders(self, orders_df, source_file: str) -> int:
        """Insert orders into DB. Returns count of actually inserted rows."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        count = 0
        for _, row in orders_df.iterrows():
            order_id = str(row["订单号"])
            if not order_id.isdigit():
                continue
            row_source = str(row.get("source_file", source_file)) if "source_file" in orders_df.columns else source_file
            raw_json = json.dumps(
                {k: str(v) if not isinstance(v, (int, float, bool, type(None))) else v
                 for k, v in row.to_dict().items()},
                ensure_ascii=False, default=str
            )
            try:
                self.conn.execute(
                    "INSERT OR IGNORE INTO orders (订单号, 原始数据, source_file, ingest_time) VALUES (?,?,?,?)",
                    (order_id, raw_json, row_source, now)
                )
                count += 1
            except Exception:
                continue
        self.conn.commit()
        return count

    def insert_items(self, items_df, source_file: str) -> int:
        """Upsert items by (订单号, 商品编码, 商品名称). Returns count written."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        count = 0
        for _, row in items_df.iterrows():
            order_id = str(row["订单号"])
            item_code = str(row.get("商品编码", ""))
            item_name = str(row.get("商品名称", ""))
            raw_json = json.dumps(
                {k: str(v) if not isinstance(v, (int, float, bool, type(None))) else v
                 for k, v in row.to_dict().items()},
                ensure_ascii=False, default=str
            )
            try:
                self.conn.execute(
                    "INSERT OR REPLACE INTO items "
                    "(订单号, 商品编码, 商品名称, 原始数据, source_file, ingest_time) "
                    "VALUES (?,?,?,?,?,?)",
                    (order_id, item_code, item_name, raw_json, source_file, now)
                )
                count += 1
            except Exception:
                continue
        self.conn.commit()
        return count

    def relabel_order_sources(self, order_ids: list, source_file: str) -> int:
        """Update source_file for existing orders (fix legacy mis-tagged rows)."""
        if not order_ids:
            return 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = [(source_file, now, str(oid)) for oid in order_ids]
        self.conn.executemany(
            "UPDATE orders SET source_file=?, ingest_time=? WHERE 订单号=?",
            rows,
        )
        self.conn.commit()
        return self.conn.total_changes

    def relabel_item_sources(self, order_ids: list, source_file: str) -> int:
        """Update source_file on item rows for given order IDs."""
        if not order_ids:
            return 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = [(source_file, now, str(oid)) for oid in order_ids]
        self.conn.executemany(
            "UPDATE items SET source_file=?, ingest_time=? WHERE 订单号=?",
            rows,
        )
        self.conn.commit()
        return self.conn.total_changes

    # ── Write Groups ────────────────────────────────────────

    def insert_groups(self, groups_df) -> int:
        """Insert aggregated groups. Skips existing. Returns count inserted."""
        count = 0
        for _, g in groups_df.iterrows():
            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO groups
                       (group_date, table_name, group_amount, order_revenue, order_count,
                        start_time, end_time, guest_count, anchor_order_id, first_order_id,
                        order_ids, per_person, is_member, area, meal_period,
                        filter_status, opener)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        str(g.get("_date", "")),
                        str(g.get("桌台", "")),
                        float(g.get("团体总额", 0) or 0),
                        float(g.get("订单收入", 0) or 0),
                        int(g.get("订单数", 0) or 0),
                        str(g.get("开始", "")),
                        str(g.get("结束", "")),
                        float(g.get("团体人数", 0) or 0),
                        str(g.get("主单订单号", "")),
                        str(g.get("首单订单号", "")),
                        json.dumps(
                            g.get("包含订单", []) if isinstance(g.get("包含订单"), list)
                            else [], ensure_ascii=False
                        ),
                        float(g.get("人均消费", 0) or 0),
                        int(g.get("是否会员", False) or 0),
                        str(g.get("_area", "")),
                        str(g.get("_meal", "")),
                        str(g.get("_filter_status", "kept")),
                        str(g.get("_opener", "")),
                    )
                )
                count += 1
            except Exception:
                continue
        self.conn.commit()
        return count

    # ── Write/Update Daily Stats ────────────────────────────

    def upsert_daily_overview(self, rows: list):
        """rows: list of (date, store_name, category, sub_category, 营业额, 百分比, 人数, 人均)"""
        self.conn.executemany(
            """INSERT OR REPLACE INTO daily_overview
               (date, store_name, category, sub_category, 营业额, 百分比, 人数, 人均)
               VALUES (?,?,?,?,?,?,?,?)""",
            rows
        )
        self.conn.commit()

    def upsert_daily_order_counts(self, rows: list):
        """rows: list of (date, store_name, 原始订单数, ... 统计消费团体数)"""
        self.conn.executemany(
            """INSERT OR REPLACE INTO daily_order_counts
               (date, store_name, 原始订单数, 外卖订单数, 非堂食订单数, 免单订单数,
                被合并订单数, 合并后消费团体数, 零食团体数, 打包团体数,
                零散小单团体数, 吧台团体数, 统计消费团体数)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows
        )
        self.conn.commit()

    def upsert_daily_buckets(self, rows: list):
        """rows: list of (date, store_name, bucket, 订单数, 占比)"""
        self.conn.executemany(
            """INSERT OR REPLACE INTO daily_buckets
               (date, store_name, bucket, 订单数, 占比)
               VALUES (?,?,?,?,?)""",
            rows
        )
        self.conn.commit()

    def upsert_daily_opener_stats(self, rows: list):
        """rows: list of (date, opener_name, order_count, total_amount)"""
        self.conn.executemany(
            """INSERT OR REPLACE INTO daily_opener_stats
               (date, opener_name, order_count, total_amount)
               VALUES (?,?,?,?)""",
            rows
        )
        self.conn.commit()

    # ── Read Daily Stats (for Excel generation) ─────────────

    def read_all_overview(self) -> list:
        """Aggregate per-store rows into company totals for long-term Excel export."""
        return self.conn.execute(
            """
            SELECT date, category, sub_category,
                   SUM(营业额) AS 营业额,
                   0 AS 百分比,
                   SUM(人数) AS 人数,
                   CASE WHEN SUM(人数) > 0 THEN SUM(营业额) / SUM(人数) ELSE 0 END AS 人均
            FROM daily_overview
            WHERE store_name != '__legacy__'
            GROUP BY date, category, sub_category
            ORDER BY date, category, sub_category
            """
        ).fetchall()

    def read_all_order_counts(self) -> list:
        return self.conn.execute(
            """
            SELECT date,
                   SUM(原始订单数), SUM(外卖订单数), SUM(非堂食订单数), SUM(免单订单数),
                   SUM(被合并订单数), SUM(合并后消费团体数), SUM(零食团体数), SUM(打包团体数),
                   SUM(零散小单团体数), SUM(吧台团体数), SUM(统计消费团体数)
            FROM daily_order_counts
            WHERE store_name != '__legacy__'
            GROUP BY date
            ORDER BY date
            """
        ).fetchall()

    def read_all_buckets(self) -> list:
        return self.conn.execute(
            """
            SELECT date, bucket, SUM(订单数) AS 订单数, 0 AS 占比
            FROM daily_buckets
            WHERE store_name != '__legacy__'
            GROUP BY date, bucket
            ORDER BY date, bucket
            """
        ).fetchall()

    def read_all_opener_stats(self) -> list:
        return self.conn.execute(
            "SELECT date, opener_name, order_count, total_amount "
            "FROM daily_opener_stats ORDER BY date, opener_name"
        ).fetchall()

    def read_all_openers(self) -> list:
        """Return sorted list of all unique opener names."""
        rows = self.conn.execute(
            "SELECT DISTINCT opener_name FROM daily_opener_stats ORDER BY opener_name"
        ).fetchall()
        return [r[0] for r in rows]

    def read_all_dates(self) -> list:
        """Return sorted list of all dates in the database."""
        rows = self.conn.execute(
            "SELECT DISTINCT date FROM daily_order_counts ORDER BY date"
        ).fetchall()
        return [r[0] for r in rows]

    # ── Period-based queries (for comparison analysis) ────────

    def get_order_source_map(self) -> dict:
        rows = self.conn.execute("SELECT 订单号, source_file FROM orders").fetchall()
        return {str(r[0]): r[1] or "" for r in rows}

    def _infer_pos_store_for_order(self, order_id: str, order_data: dict | None = None) -> str:
        """Infer store from order JSON, falling back to its item rows."""
        from collections import Counter
        from store_utils import infer_store_from_pos_name

        if order_data:
            store = infer_store_from_pos_name(str(order_data.get("门店名称", "")))
            if store != "未知门店":
                return store
        rows = self.conn.execute(
            "SELECT 原始数据 FROM items WHERE 订单号 = ? LIMIT 20",
            (str(order_id),),
        ).fetchall()
        stores = []
        for (raw,) in rows:
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            store = infer_store_from_pos_name(str(data.get("门店名称", "")))
            if store != "未知门店":
                stores.append(store)
        if not stores:
            return "未知门店"
        return Counter(stores).most_common(1)[0][0]

    def get_order_pos_store_map(self) -> dict:
        """Map order_id -> store inferred from POS 门店名称 (orders, else items)."""
        rows = self.conn.execute("SELECT 订单号, 原始数据 FROM orders").fetchall()
        result = {}
        for oid, raw in rows:
            order_data = None
            try:
                order_data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
            result[str(oid)] = self._infer_pos_store_for_order(str(oid), order_data)
        return result

    def fix_mislabeled_store_sources(self) -> dict:
        """Correct source_file when POS 门店名称 disagrees with filename-based store."""
        from store_utils import (
            infer_store_from_pos_name,
            infer_store_from_source_file,
            corrected_source_file,
        )

        stats = {"orders_fixed": 0, "items_fixed": 0}
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        order_rows = self.conn.execute(
            "SELECT 订单号, 原始数据, source_file FROM orders"
        ).fetchall()
        for oid, raw, src in order_rows:
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                data = None
            pos_store = self._infer_pos_store_for_order(str(oid), data)
            if pos_store == "未知门店":
                continue
            file_store = infer_store_from_source_file(src or "")
            if file_store == pos_store or file_store == "未知门店":
                continue
            new_src = corrected_source_file(pos_store, src or "")
            self.conn.execute(
                "UPDATE orders SET source_file=?, ingest_time=? WHERE 订单号=?",
                (new_src, now, str(oid)),
            )
            stats["orders_fixed"] += 1

        item_rows = self.conn.execute(
            "SELECT id, 订单号, 原始数据, source_file FROM items"
        ).fetchall()
        for item_id, oid, raw, src in item_rows:
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            pos_store = infer_store_from_pos_name(str(data.get("门店名称", "")))
            if pos_store == "未知门店":
                pos_store = self._infer_pos_store_for_order(str(oid), None)
            if pos_store == "未知门店":
                continue
            file_store = infer_store_from_source_file(src or "")
            if file_store == pos_store or file_store == "未知门店":
                continue
            new_src = corrected_source_file(pos_store, src or "")
            self.conn.execute(
                "UPDATE items SET source_file=?, ingest_time=? WHERE id=?",
                (new_src, now, item_id),
            )
            stats["items_fixed"] += 1

        self.conn.commit()
        return stats

    def get_overview_for_period(self, start_date, end_date, store_name: str | None = None):
        """Return daily_overview rows for a date range, optionally filtered by store."""
        if store_name:
            return self.conn.execute(
                "SELECT date, category, sub_category, 营业额, 百分比, 人数, 人均 "
                "FROM daily_overview "
                "WHERE date BETWEEN ? AND ? AND store_name = ? "
                "ORDER BY date, category, sub_category",
                (start_date, end_date, store_name)
            ).fetchall()
        return self.conn.execute(
            "SELECT date, category, sub_category, 营业额, 百分比, 人数, 人均 "
            "FROM daily_overview WHERE date BETWEEN ? AND ? AND store_name = '__legacy__' "
            "ORDER BY date, category, sub_category",
            (start_date, end_date)
        ).fetchall()

    def get_buckets_for_period(self, start_date, end_date, store_name: str | None = None):
        """Return daily_buckets rows for a date range, optionally filtered by store."""
        if store_name:
            return self.conn.execute(
                "SELECT date, bucket, 订单数, 占比 "
                "FROM daily_buckets "
                "WHERE date BETWEEN ? AND ? AND store_name = ? "
                "ORDER BY date, bucket",
                (start_date, end_date, store_name)
            ).fetchall()
        return self.conn.execute(
            "SELECT date, bucket, 订单数, 占比 "
            "FROM daily_buckets WHERE date BETWEEN ? AND ? AND store_name = '__legacy__' "
            "ORDER BY date, bucket",
            (start_date, end_date)
        ).fetchall()

    def _group_store_name(
        self,
        order_ids_json,
        order_source_map,
        infer_fn,
        order_pos_store_map: dict | None = None,
    ) -> str:
        from collections import Counter
        try:
            order_ids = json.loads(order_ids_json) if order_ids_json else []
        except (json.JSONDecodeError, TypeError):
            order_ids = []
        stores = []
        for oid in order_ids:
            oid_s = str(oid)
            if order_pos_store_map:
                pos_store = order_pos_store_map.get(oid_s, "未知门店")
                if pos_store != "未知门店":
                    stores.append(pos_store)
                    continue
            source = order_source_map.get(oid_s, "")
            if source:
                stores.append(infer_fn(source))
        if not stores:
            return "未知门店"
        return Counter(stores).most_common(1)[0][0]

    def get_items_for_period(self, start_date, end_date, store_name: str | None = None):
        """Return items rows for a date range (via order IDs in groups), store-aware."""
        from store_utils import infer_store_from_source_file, infer_store_from_pos_name

        order_source_map = self.get_order_source_map()
        order_pos_store_map = self.get_order_pos_store_map()
        rows = self.conn.execute(
            "SELECT first_order_id, order_ids FROM groups "
            "WHERE group_date BETWEEN ? AND ?",
            (start_date, end_date)
        ).fetchall()
        oid_set = set()
        for first_oid, order_ids_json in rows:
            if store_name:
                group_store = self._group_store_name(
                    order_ids_json,
                    order_source_map,
                    infer_store_from_source_file,
                    order_pos_store_map,
                )
                if group_store != store_name:
                    continue
            oid_set.add(str(first_oid))
            try:
                merged = json.loads(order_ids_json) if order_ids_json else []
                for oid in merged:
                    oid_set.add(str(oid))
            except (json.JSONDecodeError, TypeError):
                pass
        if not oid_set:
            return []
        all_items = []
        for oid in oid_set:
            item_rows = self.conn.execute(
                "SELECT 订单号, 原始数据, source_file, ingest_time FROM items WHERE 订单号 = ?",
                (oid,)
            ).fetchall()
            for row in item_rows:
                if store_name:
                    try:
                        data = json.loads(row[1])
                    except (json.JSONDecodeError, TypeError):
                        continue
                    item_store = infer_store_from_pos_name(str(data.get("门店名称", "")))
                    if item_store != "未知门店" and item_store != store_name:
                        continue
                all_items.append(row)
        return all_items

    def rebuild_store_daily_stats(self, start_date: str, end_date: str, store_names: list | None = None):
        """Rebuild per-store daily stats from groups + order source files."""
        import pandas as pd
        from collections import Counter
        from daily_stats import compute_all_daily_stats
        from store_utils import infer_store_from_source_file

        order_source_map = self.get_order_source_map()
        order_pos_store_map = self.get_order_pos_store_map()
        rows = self.conn.execute(
            """
            SELECT group_date, table_name, order_revenue, order_count, start_time, end_time,
                   guest_count, first_order_id, order_ids, per_person, is_member, area,
                   meal_period, filter_status, opener
            FROM groups
            WHERE group_date BETWEEN ? AND ?
            """,
            (start_date, end_date),
        ).fetchall()
        if not rows:
            return 0

        records = []
        for row in rows:
            try:
                order_ids = json.loads(row[8]) if row[8] else []
            except (json.JSONDecodeError, TypeError):
                order_ids = []
            stores = []
            for oid in order_ids:
                oid_s = str(oid)
                pos_store = order_pos_store_map.get(oid_s, "未知门店")
                if pos_store != "未知门店":
                    stores.append(pos_store)
                    continue
                stores.append(
                    infer_store_from_source_file(order_source_map.get(oid_s, ""))
                )
            stores = [s for s in stores if s != "未知门店"]
            store = Counter(stores).most_common(1)[0][0] if stores else "未知门店"
            records.append({
                "_date": row[0],
                "桌台": row[1],
                "订单收入": row[2],
                "订单数": row[3],
                "开始": row[4],
                "结束": row[5],
                "团体人数": row[6],
                "首单订单号": row[7],
                "包含订单": order_ids,
                "人均消费": row[9],
                "是否会员": bool(row[10]),
                "_area": row[11],
                "_meal": row[12],
                "_filter_status": row[13] or "kept",
                "_opener": row[14] or "",
                "_store": store,
            })

        gs = pd.DataFrame(records)
        if gs.empty:
            return 0

        targets = store_names or sorted(s for s in gs["_store"].unique() if s != "未知门店")
        updated = 0
        for store in targets:
            store_groups = gs[gs["_store"] == store].copy()
            if store_groups.empty:
                continue
            stats = compute_all_daily_stats(
                store_groups, orders_df=None, pre_merge_daily={}, items_df=None, store_name=store
            )
            if stats["overview_rows"]:
                self.upsert_daily_overview(stats["overview_rows"])
            if stats["order_count_rows"]:
                self.upsert_daily_order_counts(stats["order_count_rows"])
            if stats["bucket_rows"]:
                self.upsert_daily_buckets(stats["bucket_rows"])
            updated += 1
        return updated

    # ── Maintenance ─────────────────────────────────────────

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
