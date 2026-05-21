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
            raw_json = json.dumps(
                {k: str(v) if not isinstance(v, (int, float, bool, type(None))) else v
                 for k, v in row.to_dict().items()},
                ensure_ascii=False, default=str
            )
            try:
                self.conn.execute(
                    "INSERT OR IGNORE INTO orders (订单号, 原始数据, source_file, ingest_time) VALUES (?,?,?,?)",
                    (order_id, raw_json, source_file, now)
                )
                count += 1
            except Exception:
                continue
        self.conn.commit()
        return count

    def insert_items(self, items_df, source_file: str) -> int:
        """Insert items into DB. Deduplicates by (订单号, 商品编码, 商品名称). Returns count inserted."""
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
                    "INSERT OR IGNORE INTO items (订单号, 商品编码, 商品名称, 原始数据, source_file, ingest_time) VALUES (?,?,?,?,?,?)",
                    (order_id, item_code, item_name, raw_json, source_file, now)
                )
                if self.conn.total_changes > 0:
                    count += 1
            except Exception:
                continue
        self.conn.commit()
        return count

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
        """rows: list of (date, category, sub_category, 营业额, 百分比, 人数, 人均)"""
        self.conn.executemany(
            """INSERT OR REPLACE INTO daily_overview
               (date, category, sub_category, 营业额, 百分比, 人数, 人均)
               VALUES (?,?,?,?,?,?,?)""",
            rows
        )
        self.conn.commit()

    def upsert_daily_order_counts(self, rows: list):
        """rows: list of (date, 原始订单数, 外卖订单数, ... 统计消费团体数)"""
        self.conn.executemany(
            """INSERT OR REPLACE INTO daily_order_counts
               (date, 原始订单数, 外卖订单数, 非堂食订单数, 免单订单数,
                被合并订单数, 合并后消费团体数, 零食团体数, 打包团体数,
                零散小单团体数, 吧台团体数, 统计消费团体数)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows
        )
        self.conn.commit()

    def upsert_daily_buckets(self, rows: list):
        """rows: list of (date, bucket, 订单数, 占比)"""
        self.conn.executemany(
            """INSERT OR REPLACE INTO daily_buckets
               (date, bucket, 订单数, 占比)
               VALUES (?,?,?,?)""",
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
        return self.conn.execute(
            "SELECT date, category, sub_category, 营业额, 百分比, 人数, 人均 "
            "FROM daily_overview ORDER BY date, category, sub_category"
        ).fetchall()

    def read_all_order_counts(self) -> list:
        return self.conn.execute(
            "SELECT date, 原始订单数, 外卖订单数, 非堂食订单数, 免单订单数, "
            "被合并订单数, 合并后消费团体数, 零食团体数, 打包团体数, "
            "零散小单团体数, 吧台团体数, 统计消费团体数 "
            "FROM daily_order_counts ORDER BY date"
        ).fetchall()

    def read_all_buckets(self) -> list:
        return self.conn.execute(
            "SELECT date, bucket, 订单数, 占比 "
            "FROM daily_buckets ORDER BY date, bucket"
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

    def get_overview_for_period(self, start_date, end_date):
        """Return daily_overview rows for a date range."""
        return self.conn.execute(
            "SELECT date, category, sub_category, 营业额, 百分比, 人数, 人均 "
            "FROM daily_overview WHERE date BETWEEN ? AND ? "
            "ORDER BY date, category, sub_category",
            (start_date, end_date)
        ).fetchall()

    def get_buckets_for_period(self, start_date, end_date):
        """Return daily_buckets rows for a date range."""
        return self.conn.execute(
            "SELECT date, bucket, 订单数, 占比 "
            "FROM daily_buckets WHERE date BETWEEN ? AND ? "
            "ORDER BY date, bucket",
            (start_date, end_date)
        ).fetchall()

    def get_items_for_period(self, start_date, end_date):
        """Return items rows for a date range (via all order IDs in groups)."""
        import json
        rows = self.conn.execute(
            "SELECT first_order_id, order_ids FROM groups "
            "WHERE group_date BETWEEN ? AND ?",
            (start_date, end_date)
        ).fetchall()
        oid_set = set()
        for first_oid, order_ids_json in rows:
            oid_set.add(first_oid)
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
            rows = self.conn.execute(
                "SELECT 订单号, 原始数据, source_file, ingest_time FROM items WHERE 订单号 = ?",
                (oid,)
            ).fetchall()
            all_items.extend(rows)
        return all_items

    # ── Maintenance ─────────────────────────────────────────

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
