"""Store inference helpers for multi-store daily statistics."""

from __future__ import annotations

import os
from collections import Counter

import pandas as pd


def read_pos_store_from_excel(file_path: str, sheet_name: str = "店内订单明细") -> str:
    """Read 门店名称 from POS Excel metadata rows above the data header."""
    raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None, nrows=10)
    for _, row in raw.iterrows():
        vals = [str(v).strip() for v in row.values if str(v) != "nan"]
        for i, val in enumerate(vals):
            if val == "门店名称" and i + 1 < len(vals):
                return vals[i + 1]
    return ""


def infer_store_from_source_file(source_file: str) -> str:
    name = os.path.basename(str(source_file or ""))
    if "万荷" in name:
        return "万荷店"
    if "保利" in name:
        return "保利店"
    if "湾里" in name:
        return "湾里店"
    return "未知门店"


def infer_store_from_pos_name(pos_name: str) -> str:
    """Infer store from POS export field 门店名称 (authoritative when present)."""
    name = str(pos_name or "").strip()
    if not name or name.lower() in ("nan", "none"):
        return "未知门店"
    if "万荷" in name:
        return "万荷店"
    if "保利" in name:
        return "保利店"
    if "湾里" in name:
        return "湾里店"
    return "未知门店"


def infer_order_store(order_row: dict, source_file: str = "") -> str:
    """Infer store from order row 门店名称 only (never from filename)."""
    _ = source_file  # kept for call-site compatibility
    return infer_store_from_pos_name(str(order_row.get("门店名称", "")))


def corrected_source_file(store: str, old_source: str) -> str:
    """Build a source_file tag that matches the true store after POS-name correction."""
    base = os.path.basename(str(old_source or ""))
    if store == "万荷店":
        if "万荷" in base:
            return base
        return f"万荷店内订单明细_门店名称纠正_{base}" if base else "万荷店内订单明细_门店名称纠正"
    if store == "保利店":
        if "保利" in base:
            return base
        return f"保利店内订单明细_门店名称纠正_{base}" if base else "保利店内订单明细_门店名称纠正"
    if store == "湾里店":
        if "湾里" in base:
            return base
        return f"湾里店内订单明细_门店名称纠正_{base}" if base else "湾里店内订单明细_门店名称纠正"
    return base or old_source


def attach_store_to_groups(groups_df, orders_df, order_source_map: dict | None = None):
    """Return a copy of groups_df with `_store` column."""
    order_store_map: dict[str, str] = {}
    if order_source_map:
        for oid, source in order_source_map.items():
            order_store_map[str(oid)] = infer_store_from_source_file(source)
    if orders_df is not None:
        for _, row in orders_df.iterrows():
            oid = str(row["订单号"])
            store = infer_order_store(row.to_dict())
            if store != "未知门店":
                order_store_map[oid] = store

    def _group_store(order_ids):
        ids = order_ids if isinstance(order_ids, list) else []
        stores = [order_store_map[str(oid)] for oid in ids if order_store_map.get(str(oid), "未知门店") != "未知门店"]
        if not stores:
            return "未知门店"
        return Counter(stores).most_common(1)[0][0]

    out = groups_df.copy()
    if "包含订单" in out.columns:
        out["_store"] = out["包含订单"].apply(_group_store)
    else:
        out["_store"] = "未知门店"
    return out
