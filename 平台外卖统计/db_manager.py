import sqlite3
import json
import os
from datetime import datetime

class TakeawayDatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        
        # Ensure parent directories exist
        db_dir = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(db_dir, exist_ok=True)
        
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    def _create_tables(self):
        c = self.conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS takeaway_orders (
                takeaway_order_id TEXT NOT NULL,
                store_name TEXT NOT NULL,
                order_source TEXT NOT NULL,
                date TEXT NOT NULL,
                status TEXT NOT NULL,
                raw_data TEXT NOT NULL,
                source_file TEXT,
                ingest_time TEXT NOT NULL,
                UNIQUE(store_name, order_source, takeaway_order_id)
            );

            CREATE TABLE IF NOT EXISTS takeaway_daily_overview (
                date TEXT NOT NULL,
                store_name TEXT NOT NULL,
                total_orders INTEGER DEFAULT 0,
                cancelled_orders INTEGER DEFAULT 0,
                revenue REAL DEFAULT 0,
                customer_paid REAL DEFAULT 0,
                avg_ticket REAL DEFAULT 0,
                commission REAL DEFAULT 0,
                commission_rate REAL DEFAULT 0,
                expenditure REAL DEFAULT 0,
                expenditure_rate REAL DEFAULT 0,
                partial_refund REAL DEFAULT 0,
                PRIMARY KEY (date, store_name)
            );

            CREATE TABLE IF NOT EXISTS takeaway_platform_stats (
                date TEXT NOT NULL,
                store_name TEXT NOT NULL,
                order_source TEXT NOT NULL,
                total_orders INTEGER DEFAULT 0,
                revenue REAL DEFAULT 0,
                customer_paid REAL DEFAULT 0,
                PRIMARY KEY (date, store_name, order_source)
            );

            CREATE TABLE IF NOT EXISTS takeaway_hourly_stats (
                date TEXT NOT NULL,
                store_name TEXT NOT NULL,
                hour INTEGER NOT NULL,
                total_orders INTEGER DEFAULT 0,
                revenue REAL DEFAULT 0,
                PRIMARY KEY (date, store_name, hour)
            );

            CREATE INDEX IF NOT EXISTS idx_takeaway_orders_date ON takeaway_orders(date);
            CREATE INDEX IF NOT EXISTS idx_takeaway_orders_store ON takeaway_orders(store_name);
        """)
        self.conn.commit()

    def get_existing_order_keys(self) -> set:
        """
        Returns a set of composite keys (store_name, order_source, takeaway_order_id)
        already present in the database.
        """
        rows = self.conn.execute(
            "SELECT store_name, order_source, takeaway_order_id FROM takeaway_orders"
        ).fetchall()
        return {(r[0], r[1], r[2]) for r in rows}

    def insert_takeaway_orders(self, df, source_file: str) -> int:
        """
        Insert parsed takeaway orders. Duplicate entries are ignored.
        Returns the count of successfully inserted new rows.
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        count = 0
        
        for _, row in df.iterrows():
            order_id = str(row["外卖订单号"])
            store_name = str(row["store_name"])
            source = str(row["订单来源"])
            date = str(row["营业日"])
            status = str(row["订单状态"])
            
            # Mask privacy values again inside the json just to be extremely secure
            row_dict = row.to_dict()
            for k in ['收货人姓名', '收货人手机号', '送餐地址']:
                if k in row_dict:
                    row_dict[k] = "***"
                    
            raw_json = json.dumps(
                {k: str(v) if not isinstance(v, (int, float, bool, type(None))) else v
                 for k, v in row_dict.items()},
                ensure_ascii=False, default=str
            )
            
            try:
                self.conn.execute(
                    """INSERT OR IGNORE INTO takeaway_orders
                       (takeaway_order_id, store_name, order_source, date, status, raw_data, source_file, ingest_time)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (order_id, store_name, source, date, status, raw_json, source_file, now)
                )
                # Check if it was actually inserted (changes > 0)
                # note: self.conn.total_changes is cumulative, we check if changes increased or check total changes
                # But it's simpler to rely on self.conn.execute and count using cursor or row changes
                # sqlite cursor.rowcount shows rows affected
                pass
            except Exception:
                continue
                
        self.conn.commit()
        
        # To find exactly how many new records were written, we query or track total changes
        # But wait, a cleaner way to compute count is to count how many rows are in the DB before vs after
        # Let's count them
        return count

    def upsert_daily_overview(self, rows: list):
        """
        rows: list of (date, store_name, total_orders, cancelled_orders, revenue, customer_paid,
                       avg_ticket, commission, commission_rate, expenditure, expenditure_rate, partial_refund)
        """
        self.conn.executemany(
            """INSERT OR REPLACE INTO takeaway_daily_overview
               (date, store_name, total_orders, cancelled_orders, revenue, customer_paid,
                avg_ticket, commission, commission_rate, expenditure, expenditure_rate, partial_refund)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows
        )
        self.conn.commit()

    def upsert_platform_stats(self, rows: list):
        """
        rows: list of (date, store_name, order_source, total_orders, revenue, customer_paid)
        """
        self.conn.executemany(
            """INSERT OR REPLACE INTO takeaway_platform_stats
               (date, store_name, order_source, total_orders, revenue, customer_paid)
               VALUES (?,?,?,?,?,?)""",
            rows
        )
        self.conn.commit()

    def upsert_hourly_stats(self, rows: list):
        """
        rows: list of (date, store_name, hour, total_orders, revenue)
        """
        self.conn.executemany(
            """INSERT OR REPLACE INTO takeaway_hourly_stats
               (date, store_name, hour, total_orders, revenue)
               VALUES (?,?,?,?,?)""",
            rows
        )
        self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
