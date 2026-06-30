#!/usr/bin/env python3
"""万荷店饮品/酒水类订单统计 PDF（十一类商品中类、消费团体口径、A4 纵置）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from html import escape as html_escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_skill_dir = os.path.join(os.path.dirname(__file__), "..", "每日订单分析", "order_merger_skill")
_merger_dir = os.path.join(os.path.dirname(__file__), "..", "订单桌访合并")
_compare_dir = os.path.join(os.path.dirname(__file__), "..", "周期对比分析")
_lt_dir = os.path.join(os.path.dirname(__file__), "..", "长期订单分析")
for _p in (_skill_dir, _merger_dir, _compare_dir, _lt_dir):
    sys.path.insert(0, os.path.abspath(_p))
from merge_order_zhuofang import load_and_process_orders  # noqa: E402
from data_loader import load_excel  # noqa: E402
from period_validator import validate_period, get_comparison_periods  # noqa: E402
from db_manager import DatabaseManager  # noqa: E402

# 展示顺序：前五个非酒精，其后含酒精
CATEGORIES = [
    "调饮汁", "饮料和水果", "茶", "咖啡", "冰淇淋",
    "啤酒", "白酒", "葡萄酒", "鸡尾酒", "苏格兰威士忌", "黄酒",
]
ALCOHOL_CATS = {"啤酒", "白酒", "葡萄酒", "鸡尾酒", "苏格兰威士忌", "黄酒"}
NON_ALCOHOL_CATS = {"调饮汁", "饮料和水果", "茶", "咖啡", "冰淇淋"}
ALL_CATS_LABEL = "十一类合计"
NON_ALCOHOL_DIM_LABEL = "调饮汁+饮料和水果+茶+咖啡+冰淇淋"
ALCOHOL_DIM_LABEL = "啤酒+白酒+葡萄酒+鸡尾酒+苏格兰威士忌+黄酒"

# 与平台外卖统计 pdf_report.py 保持一致
COLOR_TITLE = colors.HexColor("#1f4e78")
COLOR_SUBTITLE = colors.HexColor("#2c3e50")
COLOR_HDR_BG = colors.HexColor("#1f4e78")
COLOR_GRID = colors.HexColor("#D3D3D3")
COLOR_ROW_ALT = colors.HexColor("#F9FAFB")
COLOR_SUMMARY_BG = colors.HexColor("#F2F6F9")


def _register_font() -> str:
    candidates = [
        ("/System/Library/Fonts/PingFang.ttc", 0),
        ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
        ("/Library/Fonts/Arial Unicode.ttf", None),
    ]
    for path, idx in candidates:
        if not os.path.exists(path):
            continue
        try:
            name = "ChineseFont"
            if path.endswith(".ttc") and idx is not None:
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=idx))
            else:
                pdfmetrics.registerFont(TTFont(name, path))
            return name
        except Exception:
            continue
    return "Helvetica"


def _p(text, style):
    return Paragraph(html_escape(str(text)), style)


def _p_html(html, style):
    return Paragraph(html, style)


def _pct(n: float, total: float) -> str:
    if total <= 0:
        return "-"
    return f"{n / total * 100:.1f}%"


def _money(n: float) -> str:
    return f"¥{n:,.0f}"


def _guests_for_groups(group_keys: set, guests_by_group: dict) -> float:
    return sum(guests_by_group.get(gk, 0.0) for gk in group_keys)


def _int_qty(n: float) -> str:
    if abs(n - round(n)) < 0.01:
        return str(int(round(n)))
    return f"{n:.1f}"


def _penetration_rate(qty: float, total_guests: float) -> str:
    """销售数量 / 全店总就餐人数；一人一杯 = 100%。"""
    if total_guests <= 0:
        return "-"
    return f"{qty / total_guests * 100:.1f}%"


def _penetration_ratio(qty: float, total_guests: float) -> float | None:
    if total_guests <= 0:
        return None
    return qty / total_guests


def _positive_revenue_items(df: pd.DataFrame) -> pd.DataFrame:
    """Return item rows that form attributable positive revenue.

    饮品销量/收入统一以 `菜品收入 > 0` 为准；赠送、免单、全额优惠等
    零收入商品全部剔除。POS 套餐父项会和套餐子项同时导出，父项
    必须剔除，只保留套餐子项归入实际品类。
    """
    if df.empty or "菜品收入" not in df.columns:
        return df.iloc[0:0].copy()
    mask = df["菜品收入"] > 0
    if "菜品销售类型" in df.columns:
        mask &= df["菜品销售类型"].astype(str).str.strip() != "套餐"
    return df[mask].copy()


def _build_stats_dict(
    group_sum,
    items,
    merge_stats: dict | None = None,
    qty_items=None,
    *,
    pos_order_revenue: float | None = None,
    takeaway_revenue: float = 0.0,
) -> dict:
    """从消费团体表 + 商品明细计算饮品统计（Excel 与主库共用）。

    团体、人数沿用有效消费团体口径；销量/收入/点购率的销量分子使用
    POS 店内商品归因行，包含自取外卖单、吧台及零食购买团体；
    排除赠送、免单、全额优惠等菜品收入<=0的商品；套餐父项排除，
    套餐子项保留。额占比分母使用整体营业额。
    """
    items = items.copy()
    items["菜品收入"] = items["菜品收入"].astype(float)
    items["数量"] = items["数量"].astype(float).fillna(0)
    qty_source = qty_items.copy() if qty_items is not None else items.copy()
    if "菜品收入" in qty_source.columns:
        qty_source["菜品收入"] = qty_source["菜品收入"].astype(float)
    qty_source["数量"] = qty_source["数量"].astype(float).fillna(0)

    order_to_group: dict[str, tuple] = {}
    guests_by_group: dict[tuple, float] = {}
    stat_order_ids: set[str] = set()
    for _, row in group_sum.iterrows():
        gk = (row["桌台"], row["消费团体ID"])
        guests_by_group[gk] = float(row["团体人数"])
        for oid in row["包含订单"]:
            oid_s = str(oid)
            order_to_group[oid_s] = gk
            stat_order_ids.add(oid_s)

    items = items[items["订单号"].astype(str).isin(stat_order_ids)].copy()
    sales_source = _positive_revenue_items(qty_source)

    total_groups = len(group_sum)
    total_guests = float(group_sum["团体人数"].sum())
    item_revenue = float(sales_source["菜品收入"].sum())
    pos_order_revenue = item_revenue if pos_order_revenue is None else float(pos_order_revenue or 0)
    takeaway_revenue = float(takeaway_revenue or 0)
    overall_revenue = pos_order_revenue + takeaway_revenue

    groups_by_cat: dict[str, set[tuple]] = {}
    revenue_by_cat: dict[str, float] = {}
    guests_by_cat: dict[str, float] = {}
    qty_by_cat: dict[str, float] = {}
    for cat in CATEGORIES:
        mask = items["商品中类"].astype(str).str.strip() == cat
        subset = items.loc[mask]
        sales_mask = sales_source["商品中类"].astype(str).str.strip() == cat
        sales_subset = sales_source.loc[sales_mask]
        gks = {
            order_to_group[oid]
            for oid in subset["订单号"].astype(str)
            if oid in order_to_group
        }
        groups_by_cat[cat] = gks
        revenue_by_cat[cat] = float(sales_subset["菜品收入"].sum())
        guests_by_cat[cat] = _guests_for_groups(gks, guests_by_group)
        qty_by_cat[cat] = float(sales_subset["数量"].sum())

    def _rev_for_cats(cat_set: set[str]) -> float:
        mask = sales_source["商品中类"].astype(str).str.strip().isin(cat_set)
        return float(sales_source.loc[mask, "菜品收入"].sum())

    def _qty_for_cats(cat_set: set[str]) -> float:
        mask = sales_source["商品中类"].astype(str).str.strip().isin(cat_set)
        return float(sales_source.loc[mask, "数量"].sum())

    alcohol_groups = set().union(*(groups_by_cat[c] for c in ALCOHOL_CATS))
    non_alcohol_groups = set().union(*(groups_by_cat[c] for c in NON_ALCOHOL_CATS))
    all_target_groups = alcohol_groups | non_alcohol_groups

    return {
        "total_groups": total_groups,
        "total_guests": total_guests,
        "total_revenue": overall_revenue,
        "overall_revenue": overall_revenue,
        "pos_order_revenue": pos_order_revenue,
        "takeaway_revenue": takeaway_revenue,
        "item_revenue": item_revenue,
        "guests_by_group": guests_by_group,
        "groups_by_cat": groups_by_cat,
        "revenue_by_cat": revenue_by_cat,
        "guests_by_cat": guests_by_cat,
        "qty_by_cat": qty_by_cat,
        "alcohol_groups": alcohol_groups,
        "non_alcohol_groups": non_alcohol_groups,
        "all_target_groups": all_target_groups,
        "alcohol_revenue": _rev_for_cats(ALCOHOL_CATS),
        "non_alcohol_revenue": _rev_for_cats(NON_ALCOHOL_CATS),
        "all_target_revenue": _rev_for_cats(set(CATEGORIES)),
        "alcohol_guests": _guests_for_groups(alcohol_groups, guests_by_group),
        "non_alcohol_guests": _guests_for_groups(non_alcohol_groups, guests_by_group),
        "all_target_guests": _guests_for_groups(all_target_groups, guests_by_group),
        "alcohol_qty": _qty_for_cats(ALCOHOL_CATS),
        "non_alcohol_qty": _qty_for_cats(NON_ALCOHOL_CATS),
        "all_target_qty": _qty_for_cats(set(CATEGORIES)),
        "merge_stats": merge_stats or {},
    }


def _pos_order_revenue_from_orders(raw_orders: pd.DataFrame) -> float:
    if raw_orders.empty or "订单收入" not in raw_orders.columns:
        return 0.0
    orders = raw_orders[raw_orders["订单号"].astype(str).str.fullmatch(r"\d+")].copy()
    if "订单类型" in orders.columns:
        orders = orders[orders["订单类型"].astype(str).str.strip() == "堂食"].copy()
    orders["订单收入"] = pd.to_numeric(orders["订单收入"], errors="coerce").fillna(0)
    return float(orders["订单收入"].sum())


def compute_stats(excel_path: str, *, takeaway_revenue: float = 0.0) -> dict:
    """本期统计：团体/人数沿用消费团体口径，销量/收入使用 POS 全量正收入口径。"""
    group_sum, _group_items, merge_stats, items, _orders_with_group = load_and_process_orders(excel_path)
    raw_orders, raw_items = load_excel(excel_path)
    raw_orders_valid = raw_orders[raw_orders["订单号"].astype(str).str.fullmatch(r"\d+")].copy()
    if "订单类型" in raw_orders_valid.columns:
        raw_orders_valid = raw_orders_valid[raw_orders_valid["订单类型"].astype(str).str.strip() == "堂食"].copy()
    valid_ids = set(raw_orders_valid["订单号"].astype(str))
    qty_items = raw_items[raw_items["订单号"].astype(str).isin(valid_ids)].copy()
    return _build_stats_dict(
        group_sum,
        items,
        merge_stats,
        qty_items=qty_items,
        pos_order_revenue=_pos_order_revenue_from_orders(raw_orders),
        takeaway_revenue=takeaway_revenue,
    )


def _items_df_from_db_rows(item_rows: list) -> pd.DataFrame:
    """将主库 items 行解析为商品 DataFrame（保留 POS 行级明细，剔除收入≤0）。"""
    records = []
    for row in item_rows:
        try:
            data = json.loads(row[1])
        except (json.JSONDecodeError, TypeError):
            continue
        oid = str(data.get("订单号", ""))
        name = str(data.get("商品名称", ""))
        rev = float(data.get("菜品收入", 0) or 0)
        if rev <= 0:
            continue
        records.append({
            "订单号": oid,
            "商品中类": str(data.get("商品中类", "")).strip(),
            "商品名称": name,
            "数量": float(data.get("数量", 0) or 0),
            "菜品收入": rev,
            "菜品销售类型": str(data.get("菜品销售类型", "")).strip(),
        })
    if not records:
        return pd.DataFrame(columns=["订单号", "商品中类", "商品名称", "数量", "菜品收入", "菜品销售类型"])
    return pd.DataFrame(records)


def _kept_groups_df(db: DatabaseManager, start: str, end: str, store_name: str) -> pd.DataFrame:
    """从主库读取 filter_status=kept 的消费团体，按门店过滤。"""
    from store_utils import infer_store_from_source_file

    order_source_map = db.get_order_source_map()
    order_pos_store_map = db.get_order_pos_store_map()
    rows = db.conn.execute(
        """
        SELECT table_name, guest_count, order_ids, first_order_id
        FROM groups
        WHERE group_date BETWEEN ? AND ? AND filter_status = 'kept'
        """,
        (start, end),
    ).fetchall()

    records = []
    for table_name, guest_count, order_ids_json, first_oid in rows:
        group_store = db._group_store_name(
            order_ids_json,
            order_source_map,
            infer_store_from_source_file,
            order_pos_store_map,
        )
        if group_store != store_name:
            continue
        try:
            order_ids = json.loads(order_ids_json) if order_ids_json else []
        except (json.JSONDecodeError, TypeError):
            order_ids = []
        if not order_ids and first_oid:
            order_ids = [first_oid]
        records.append({
            "桌台": table_name or "",
            "消费团体ID": str(first_oid),
            "团体人数": float(guest_count or 0),
            "包含订单": [str(o) for o in order_ids],
        })
    if not records:
        return pd.DataFrame(columns=["桌台", "消费团体ID", "团体人数", "包含订单"])
    return pd.DataFrame(records)


def _items_for_kept_groups(db: DatabaseManager, group_sum: pd.DataFrame, store_name: str) -> pd.DataFrame:
    """取 kept 团体对应订单的商品明细。"""
    from store_utils import infer_store_from_pos_name

    oid_set: set[str] = set()
    for _, row in group_sum.iterrows():
        for oid in row.get("包含订单", []) or []:
            oid_set.add(str(oid))
    if not oid_set:
        return _items_df_from_db_rows([])

    all_items = []
    for oid in oid_set:
        item_rows = db.conn.execute(
            "SELECT 订单号, 原始数据, source_file, ingest_time FROM items WHERE 订单号 = ?",
            (oid,),
        ).fetchall()
        for row in item_rows:
            try:
                data = json.loads(row[1])
            except (json.JSONDecodeError, TypeError):
                continue
            item_store = infer_store_from_pos_name(str(data.get("门店名称", "")))
            if item_store != "未知门店" and item_store != store_name:
                continue
            all_items.append(row)
    return _items_df_from_db_rows(all_items)


def compute_stats_from_db(db: DatabaseManager, start: str, end: str, store_name: str) -> dict | None:
    """从 SQLite 主库按日期区间计算饮品统计（环比/同比对比期）。"""
    group_sum = _kept_groups_df(db, start, end, store_name)
    if group_sum.empty:
        return None
    items = _items_for_kept_groups(db, group_sum, store_name)
    qty_items = _items_df_from_db_rows(db.get_all_items_for_period(start, end, store_name))
    return _build_stats_dict(
        group_sum,
        items,
        qty_items=qty_items,
        pos_order_revenue=db.get_order_revenue_for_period(start, end, store_name),
        takeaway_revenue=db.get_takeaway_revenue_for_period(start, end, store_name),
    )


def infer_db_store(display_store: str) -> str:
    """报告展示名 → 主库 store_name。"""
    if "保利" in display_store:
        return "保利店"
    if "万荷" in display_store:
        return "万荷店"
    return display_store


def extract_dates_from_excel(excel_path: str) -> list[str]:
    raw_orders, _ = load_excel(excel_path)
    if raw_orders.empty or "下单时间" not in raw_orders.columns:
        return []
    raw_orders["_date"] = pd.to_datetime(raw_orders["下单时间"], errors="coerce").dt.strftime("%Y-%m-%d")
    return sorted(d for d in raw_orders["_date"].dropna().unique() if d and d != "NaT")


def _fmt_change_pct(cur: float, base: float | None) -> str:
    if base is None or base == 0:
        return "-"
    return f"{(cur - base) / base * 100:+.1f}%"


def _fmt_penetration_pp(cur_qty: float, cur_guests: float, base_qty: float | None, base_guests: float | None) -> str:
    cur_r = _penetration_ratio(cur_qty, cur_guests)
    base_r = _penetration_ratio(base_qty or 0, base_guests or 0) if base_qty is not None and base_guests else None
    if cur_r is None or base_r is None:
        return "-"
    return f"{(cur_r - base_r) * 100:+.1f}pp"


def _cmp_color(text: str) -> str:
    if text in ("-", ""):
        return "#333333"
    if text.startswith("+"):
        return "#27AE60"
    if text.startswith("-"):
        return "#C0392B"
    return "#333333"


def _row_metrics(stats: dict, *, cat: str | None = None, dim: str | None = None) -> dict:
    """提取一行对比用原始指标。"""
    if cat is not None:
        return {
            "groups": len(stats["groups_by_cat"][cat]),
            "guests": stats["guests_by_cat"][cat],
            "qty": stats["qty_by_cat"][cat],
            "revenue": stats["revenue_by_cat"][cat],
        }
    if dim == "non_alcohol":
        return {
            "groups": len(stats["non_alcohol_groups"]),
            "guests": stats["non_alcohol_guests"],
            "qty": stats["non_alcohol_qty"],
            "revenue": stats["non_alcohol_revenue"],
        }
    if dim == "alcohol":
        return {
            "groups": len(stats["alcohol_groups"]),
            "guests": stats["alcohol_guests"],
            "qty": stats["alcohol_qty"],
            "revenue": stats["alcohol_revenue"],
        }
    return {
        "groups": len(stats["all_target_groups"]),
        "guests": stats["all_target_guests"],
        "qty": stats["all_target_qty"],
        "revenue": stats["all_target_revenue"],
    }


def _period_labels(mode: str) -> tuple[str, str, str]:
    """本周期 / 环比期 / 同比期 行标签（与下方对比表「周期」列一致）。"""
    if mode == "month":
        return "本月", "上月", "去年同月"
    return "本周", "上周", "去年同期"


def _fmt_vs_base_ratio(base: float, value: float | None, *, is_baseline: bool) -> str:
    if is_baseline:
        return "100%"
    if value is None:
        return "-"
    if base == 0:
        return "-" if value == 0 else "—"
    return f"{value / base * 100:.1f}%"


def _fmt_penetration_vs_base(
    cur_qty: float,
    cur_guests: float,
    other_qty: float | None,
    other_guests: float | None,
    *,
    is_baseline: bool,
) -> str:
    if is_baseline:
        return "100%"
    cur_r = _penetration_ratio(cur_qty, cur_guests)
    other_r = _penetration_ratio(other_qty or 0, other_guests or 0) if other_qty is not None else None
    if cur_r is None or other_r is None or cur_r == 0:
        return "-"
    return f"{other_r / cur_r * 100:.1f}%"


def _fmt_share_vs_base(
    cur_rev: float,
    cur_total_rev: float,
    other_rev: float | None,
    other_total_rev: float | None,
    *,
    is_baseline: bool,
) -> str:
    if is_baseline:
        return "100%"
    if other_rev is None or other_total_rev is None or cur_total_rev <= 0 or other_total_rev <= 0:
        return "-"
    cur_share = cur_rev / cur_total_rev
    other_share = other_rev / other_total_rev
    if cur_share == 0:
        return "-"
    return f"{other_share / cur_share * 100:.1f}%"


def _ratio_color(text: str, *, is_baseline: bool) -> str:
    if is_baseline or text in ("-", "—", "100%"):
        return "#333333"
    try:
        val = float(text.rstrip("%"))
        if val > 100:
            return "#27AE60"
        if val < 100:
            return "#C0392B"
    except ValueError:
        pass
    return "#333333"


def _display_metric_cells(
    m: dict,
    total_groups: float,
    total_guests: float,
    total_revenue: float,
) -> list[str]:
    """8 个指标列：团体、团占比、人数、人占比、销量、点购率、收入、额占比。"""
    return [
        str(int(m["groups"])),
        _pct(m["groups"], total_groups),
        _int_guests(m["guests"]),
        _pct(m["guests"], total_guests),
        _int_qty(m["qty"]),
        _penetration_rate(m["qty"], total_guests),
        _money(m["revenue"]),
        _pct(m["revenue"], total_revenue),
    ]


def _ratio_metric_cells(
    cur_m: dict,
    other_m: dict | None,
    cur_stats: dict,
    other_stats: dict | None,
    *,
    is_baseline: bool,
) -> list[str]:
    """以本周期为 100% 的 6 个比率列；额占比使用整体营业额作分母。"""
    if is_baseline:
        return ["100%"] * 6
    if other_m is None or other_stats is None:
        return ["-"] * 6
    return [
        _fmt_vs_base_ratio(cur_m["groups"], other_m["groups"], is_baseline=False),
        _fmt_vs_base_ratio(cur_m["guests"], other_m["guests"], is_baseline=False),
        _fmt_vs_base_ratio(cur_m["qty"], other_m["qty"], is_baseline=False),
        _fmt_penetration_vs_base(
            cur_m["qty"], cur_stats["total_guests"],
            other_m["qty"], other_stats["total_guests"],
            is_baseline=False,
        ),
        _fmt_vs_base_ratio(cur_m["revenue"], other_m["revenue"], is_baseline=False),
        _fmt_share_vs_base(
            cur_m["revenue"], cur_stats["total_revenue"],
            other_m["revenue"], other_stats["total_revenue"],
            is_baseline=False,
        ),
    ]


def _build_triple_row_group(
    cat_label: str,
    cur_stats: dict,
    ring_stats: dict | None,
    tong_stats: dict | None,
    period_labels: tuple[str, str, str],
    *,
    cat: str | None = None,
    dim: str | None = None,
) -> list[list]:
    """每个品类/维度 3 行：本周期、环比期、同比期。"""
    cur_m = _row_metrics(cur_stats, cat=cat, dim=dim)
    ring_m = _row_metrics(ring_stats, cat=cat, dim=dim) if ring_stats else None
    tong_m = _row_metrics(tong_stats, cat=cat, dim=dim) if tong_stats else None

    rows = []
    periods = [
        (period_labels[0], cur_stats, cur_m, True),
        (period_labels[1], ring_stats, ring_m, False),
        (period_labels[2], tong_stats, tong_m, False),
    ]
    for i, (plabel, pstats, pm, is_base) in enumerate(periods):
        if pstats is None and not is_base:
            metrics = ["-"] * 8
            ratios = ["-"] * 6
        else:
            tg = pstats["total_groups"]
            tgu = pstats["total_guests"]
            tr = pstats["total_revenue"]
            metrics = _display_metric_cells(pm, tg, tgu, tr)
            ratios = _ratio_metric_cells(cur_m, pm, cur_stats, pstats, is_baseline=is_base)
        label_cell = cat_label if i == 0 else ""
        rows.append([label_cell, plabel, *metrics, *ratios])
    return rows


def _int_guests(n: float) -> str:
    return f"{int(round(n))} 人"


def _cat_label(cat: str) -> str:
    tag = "含酒精" if cat in ALCOHOL_CATS else "非酒精"
    return f"{cat}<br/><font size=5 color='#666666'>({tag})</font>"


def build_pdf(
    output_path: str,
    stats: dict,
    store_label: str,
    period_label: str,
    comparison: dict | None = None,
) -> None:
    font = _register_font()
    has_cmp = comparison is not None
    page = landscape(A4) if has_cmp else A4
    doc = SimpleDocTemplate(
        output_path,
        pagesize=page,
        leftMargin=1.0 * cm,
        rightMargin=1.0 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )
    avail_w = doc.width

    title_style = ParagraphStyle(
        "title", fontName=font, fontSize=15, leading=18,
        alignment=TA_CENTER, textColor=COLOR_TITLE, spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "subtitle", fontName=font, fontSize=10, leading=13,
        textColor=COLOR_SUBTITLE, spaceBefore=3, spaceAfter=5,
    )
    normal_style = ParagraphStyle("normal", fontName=font, fontSize=8, leading=11)
    bold_style = ParagraphStyle("bold", fontName=font, fontSize=8, leading=11)
    cell_c = ParagraphStyle("cell_c", fontName=font, fontSize=7, leading=9, alignment=TA_CENTER)
    cell_l = ParagraphStyle("cell_l", fontName=font, fontSize=7, leading=9, alignment=TA_LEFT)
    cell_r = ParagraphStyle("cell_r", fontName=font, fontSize=7, leading=9, alignment=TA_RIGHT)
    hdr_style = ParagraphStyle(
        "hdr", fontName=font, fontSize=7, leading=9, alignment=TA_CENTER, textColor=colors.white
    )
    cell_cmp = ParagraphStyle(
        "cell_cmp", fontName=font, fontSize=6, leading=8, alignment=TA_CENTER
    )
    cat_style = ParagraphStyle(
        "cat", fontName=font, fontSize=7, leading=9, alignment=TA_LEFT
    )

    total_groups = stats["total_groups"]
    total_guests = stats["total_guests"]
    total_revenue = stats["total_revenue"]
    ms = stats.get("merge_stats", {})
    raw_pos = ms.get("原始订单数", "-")
    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    story = [
        Paragraph(html_escape(f"{store_label}饮品/酒水订单统计"), title_style),
        _p_html(
            f'统计周期: <b>{html_escape(period_label.replace("统计周期：", ""))}</b>'
            f'&nbsp;&nbsp;&nbsp;&nbsp; 生成时间: {html_escape(gen_time)}',
            normal_style,
        ),
    ]
    if comparison:
        ring_lbl = html_escape(comparison.get("ringbi_label", "环比"))
        tong_lbl = html_escape(comparison.get("tongbi_label", "同比"))
        ring_rng = html_escape(f'{comparison["ringbi_start"]} ~ {comparison["ringbi_end"]}')
        tong_rng = html_escape(f'{comparison["tongbi_start"]} ~ {comparison["tongbi_end"]}')
        mode_cn = "周" if comparison.get("mode") == "week" else "月"
        story.append(_p_html(
            f'对比口径: {mode_cn}评&nbsp;&nbsp;|&nbsp;&nbsp;'
            f'环比: {ring_lbl}（{ring_rng}）&nbsp;&nbsp;|&nbsp;&nbsp;'
            f'同比: {tong_lbl}（{tong_rng}）',
            normal_style,
        ))
        if comparison.get("ringbi_missing"):
            story.append(_p("⚠ 环比期主库无数据，对应列显示为 -", normal_style))
        if comparison.get("tongbi_missing"):
            story.append(_p("⚠ 同比期主库无数据，对应列显示为 -", normal_style))
    story.append(Spacer(1, 0.3 * cm))

    ring_stats = comparison.get("ringbi_stats") if comparison else None
    tong_stats = comparison.get("tongbi_stats") if comparison else None
    cmp_mode = comparison.get("mode", "week") if comparison else "week"
    period_labels = _period_labels(cmp_mode) if has_cmp else None

    def _summary_groups(s: dict | None) -> str:
        if s is None:
            return "-"
        return f"{s['total_groups']} 个"

    def _summary_guests(s: dict | None) -> str:
        if s is None:
            return "-"
        return _int_guests(s["total_guests"])

    def _summary_pos_order_revenue(s: dict | None) -> str:
        if s is None:
            return "-"
        return _money(s["pos_order_revenue"])

    def _summary_takeaway_revenue(s: dict | None) -> str:
        if s is None:
            return "-"
        return _money(s["takeaway_revenue"])

    def _summary_overall_revenue(s: dict | None) -> str:
        if s is None:
            return "-"
        return _money(s["overall_revenue"])

    def _summary_drink_revenue(s: dict | None) -> str:
        if s is None:
            return "-"
        return _money(s["all_target_revenue"])

    def _append_period_notes(cur_label: str) -> None:
        """口径说明以正文呈现，并标明仅属本周期，避免与环比/同比混淆。"""
        tag = f"【{cur_label}说明】"
        story.append(Spacer(1, 0.12 * cm))
        story.append(_p(
            f"{tag}团体和人数：沿用订单桌访合并结果，同桌补单算一个团体。",
            normal_style,
        ))
        story.append(_p(
            f"{tag}销量和收入：只统计 POS 商品明细里有收入的饮品；赠送、免单、全额优惠不计入；套餐父项不计入，套餐子项计入实际品类。",
            normal_style,
        ))
        story.append(_p(
            f"{tag}营业额闭环：POS 店内订单收入 + 第三方平台外卖已完成订单收入 = 整体营业额。",
            normal_style,
        ))
        story.append(_p(
            f"{tag}占比：团体、人和点购率按有效消费团体算；额占比=饮品收入÷整体营业额。",
            normal_style,
        ))

    if has_cmp:
        pl0, pl1, pl2 = period_labels
        summary_grid = [
            [
                Paragraph(html_escape("指标"), hdr_style),
                Paragraph(html_escape(pl0), hdr_style),
                Paragraph(html_escape(pl1), hdr_style),
                Paragraph(html_escape(pl2), hdr_style),
            ],
            [
                _p("消费团体数", bold_style),
                _p(_summary_groups(stats), normal_style),
                _p(_summary_groups(ring_stats), normal_style),
                _p(_summary_groups(tong_stats), normal_style),
            ],
            [
                _p("就餐人数合计", bold_style),
                _p(_summary_guests(stats), normal_style),
                _p(_summary_guests(ring_stats), normal_style),
                _p(_summary_guests(tong_stats), normal_style),
            ],
            [
                _p("POS店内订单收入", bold_style),
                _p(_summary_pos_order_revenue(stats), normal_style),
                _p(_summary_pos_order_revenue(ring_stats), normal_style),
                _p(_summary_pos_order_revenue(tong_stats), normal_style),
            ],
            [
                _p("第三方平台外卖收入", bold_style),
                _p(_summary_takeaway_revenue(stats), normal_style),
                _p(_summary_takeaway_revenue(ring_stats), normal_style),
                _p(_summary_takeaway_revenue(tong_stats), normal_style),
            ],
            [
                _p("整体营业额", bold_style),
                _p(_summary_overall_revenue(stats), normal_style),
                _p(_summary_overall_revenue(ring_stats), normal_style),
                _p(_summary_overall_revenue(tong_stats), normal_style),
            ],
            [
                _p(f"{ALL_CATS_LABEL}收入", bold_style),
                _p(_summary_drink_revenue(stats), normal_style),
                _p(_summary_drink_revenue(ring_stats), normal_style),
                _p(_summary_drink_revenue(tong_stats), normal_style),
            ],
        ]
        summary_col_widths = [avail_w * 0.20, avail_w * 0.27, avail_w * 0.27, avail_w * 0.26]
        summary_style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_HDR_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), font),
            ("BACKGROUND", (0, 1), (-1, -1), COLOR_SUMMARY_BG),
            ("GRID", (0, 0), (-1, -1), 0.5, COLOR_GRID),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ALIGN", (0, 1), (0, -1), "LEFT"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]
    else:
        summary_grid = [
            [
                _p("消费团体数:", bold_style), _p(f"{total_groups} 个", normal_style),
                _p("就餐人数合计:", bold_style), _p(_int_guests(total_guests), normal_style),
            ],
            [
                _p("POS店内订单收入:", bold_style), _p(_money(stats["pos_order_revenue"]), normal_style),
                _p("第三方平台外卖收入:", bold_style), _p(_money(stats["takeaway_revenue"]), normal_style),
            ],
            [
                _p("整体营业额:", bold_style), _p(_money(stats["overall_revenue"]), normal_style),
                _p(f"{ALL_CATS_LABEL}收入:", bold_style),
                _p(_money(stats["all_target_revenue"]), normal_style),
            ],
            [
                _p("额占比分母:", bold_style), _p(_money(total_revenue), normal_style),
                _p("收入口径:", bold_style), _p("排除套餐父项", normal_style),
            ],
        ]
        summary_col_widths = [avail_w * 0.18, avail_w * 0.32, avail_w * 0.18, avail_w * 0.32]
        summary_style_cmds = [
            ("BACKGROUND", (0, 0), (-1, -1), COLOR_SUMMARY_BG),
            ("GRID", (0, 0), (-1, -1), 0.5, COLOR_GRID),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ]

    summary_table = Table(summary_grid, colWidths=summary_col_widths)
    summary_table.setStyle(TableStyle(summary_style_cmds))
    story.append(summary_table)
    if has_cmp:
        _append_period_notes(pl0)
    else:
        _append_period_notes("本期")
    story.append(Spacer(1, 0.25 * cm))

    # ── 表格列定义：本期简表（9列）与对比详表（16列）分开 ──
    simple_hdr = ["品类", "团体", "团占比", "人数", "人占比", "销量", "点购率", "收入", "额占比"]
    simple_fracs = [0.152, 0.087, 0.098, 0.098, 0.098, 0.087, 0.098, 0.196, 0.087]
    simple_col_widths = [avail_w * f for f in simple_fracs]
    simple_right_cols = {1, 3, 5, 7}

    cmp_hdr = [
        "品类", "周期",
        "团体", "团占比", "人数", "人占比", "销量", "点购率", "收入", "额占比",
        "团体/本期", "人数/本期", "销量/本期", "点购/本期", "收入/本期", "额占/本期",
    ]
    cmp_fracs = [
        0.10, 0.055,
        0.048, 0.052, 0.052, 0.052, 0.048, 0.052, 0.078, 0.052,
        0.052, 0.052, 0.052, 0.052, 0.052, 0.052,
    ]
    cmp_col_widths = [avail_w * f for f in cmp_fracs]
    cmp_right_cols = {2, 4, 6, 8}
    cmp_ratio_start = 10

    def _cat_data_row(cat: str) -> list:
        n = len(stats["groups_by_cat"][cat])
        rev = stats["revenue_by_cat"][cat]
        g = stats["guests_by_cat"][cat]
        qty = stats["qty_by_cat"][cat]
        return [
            _cat_label(cat),
            str(n),
            _pct(n, total_groups),
            _int_guests(g),
            _pct(g, total_guests),
            _int_qty(qty),
            _penetration_rate(qty, total_guests),
            _money(rev),
            _pct(rev, total_revenue),
        ]

    def _dim_data_row(label_html: str, dim: str) -> list:
        if dim == "non_alcohol":
            g, qty, rev = stats["non_alcohol_guests"], stats["non_alcohol_qty"], stats["non_alcohol_revenue"]
            n = len(stats["non_alcohol_groups"])
        elif dim == "alcohol":
            g, qty, rev = stats["alcohol_guests"], stats["alcohol_qty"], stats["alcohol_revenue"]
            n = len(stats["alcohol_groups"])
        else:
            g, qty, rev = stats["all_target_guests"], stats["all_target_qty"], stats["all_target_revenue"]
            n = len(stats["all_target_groups"])
        return [
            label_html,
            str(n), _pct(n, total_groups),
            _int_guests(g), _pct(g, total_guests),
            _int_qty(qty), _penetration_rate(qty, total_guests),
            _money(rev), _pct(rev, total_revenue),
        ]

    def _render_simple_cell(val, col_idx: int):
        if col_idx == 0:
            if "<br/>" in str(val):
                return Paragraph(val, cat_style)
            return _p(val, cell_l)
        if col_idx in simple_right_cols:
            return _p(val, cell_r)
        return _p(val, cell_c)

    def _render_cmp_cell(val, col_idx: int, *, is_baseline_row: bool = False):
        if col_idx == 0:
            if "<br/>" in str(val):
                return Paragraph(val, cat_style)
            return _p(val, cell_l)
        if col_idx in cmp_right_cols:
            return _p(val, cell_r)
        if col_idx >= cmp_ratio_start:
            color = _ratio_color(str(val), is_baseline=is_baseline_row)
            return _p_html(f'<font color="{color}">{html_escape(str(val))}</font>', cell_cmp)
        return _p(val, cell_c)

    def _data_table_simple(header, rows, is_total_row: int | None = None):
        table_rows = [[Paragraph(html_escape(h), hdr_style) for h in header]]
        for row in rows:
            table_rows.append([_render_simple_cell(val, i) for i, val in enumerate(row)])
        t = Table(table_rows, colWidths=simple_col_widths, repeatRows=1)
        style_cmds = _base_table_style(font)
        style_cmds.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_ROW_ALT]))
        if is_total_row is not None:
            tr = is_total_row + 1
            style_cmds.append(("BACKGROUND", (0, tr), (-1, tr), colors.HexColor("#D6E4F0")))
        t.setStyle(TableStyle(style_cmds))
        return t

    def _data_table_triple(header, row_groups, total_group_idx: int | None = None):
        """row_groups: [(cat_label, [row, row, row]), ...]"""
        table_rows = [[Paragraph(html_escape(h), hdr_style) for h in header]]
        span_cmds = []
        block_cmds = []
        data_row_idx = 1
        for gi, (_cat_label, triple) in enumerate(row_groups):
            for ri, row in enumerate(triple):
                is_base = ri == 0
                table_rows.append([
                    _render_cmp_cell(row[ci], ci, is_baseline_row=is_base)
                    for ci in range(len(row))
                ])
                data_row_idx += 1
            start = data_row_idx - 3
            end = data_row_idx - 1
            span_cmds.append(("SPAN", (0, start), (0, end)))
            span_cmds.append(("VALIGN", (0, start), (0, end), "MIDDLE"))
            bg = colors.white if gi % 2 == 0 else COLOR_ROW_ALT
            block_cmds.append(("BACKGROUND", (0, start), (-1, end), bg))
            if total_group_idx is not None and gi == total_group_idx:
                block_cmds.append(("BACKGROUND", (0, start), (-1, end), colors.HexColor("#D6E4F0")))
        t = Table(table_rows, colWidths=cmp_col_widths, repeatRows=1)
        style_cmds = _base_table_style(font) + span_cmds + block_cmds
        t.setStyle(TableStyle(style_cmds))
        return t

    def _base_table_style(font_name):
        return [
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_HDR_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("GRID", (0, 0), (-1, -1), 0.5, COLOR_GRID),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ]

    # Section 1 — 本期分品类（始终 9 列简表，与截图二一致）
    sec1_title = "一、分品类统计（消费团体 / 人数 / 销量 / 金额）"
    if has_cmp:
        sec1_title += f"（{period_labels[0]}）"
    story.append(Paragraph(sec1_title, subtitle_style))
    sec1_rows = [_cat_data_row(cat) for cat in CATEGORIES]
    sec1_rows.append(_dim_data_row(ALL_CATS_LABEL, "all"))
    story.append(_data_table_simple(simple_hdr, sec1_rows, is_total_row=len(sec1_rows) - 1))
    story.append(Spacer(1, 0.1 * cm))
    story.append(_p(
        "注：品类按非酒精→含酒精排列；团体数=含该品类消费团体数（同桌补单已合并）。"
        f"点购率=销量÷统计范围就餐人数（{int(round(total_guests))} 人）；一人一杯为 100%。",
        normal_style,
    ))
    story.append(Spacer(1, 0.25 * cm))

    # Section 2 — 分品类同比环比（仅含对比时）
    if has_cmp:
        story.append(Paragraph(
            f"二、分品类同比环比对比（{period_labels[0]} / {period_labels[1]} / {period_labels[2]}）",
            subtitle_style,
        ))
        sec1_groups = [
            (_cat_label(cat), _build_triple_row_group(
                _cat_label(cat), stats, ring_stats, tong_stats, period_labels, cat=cat,
            ))
            for cat in CATEGORIES
        ]
        sec1_groups.append((
            ALL_CATS_LABEL,
            _build_triple_row_group(
                ALL_CATS_LABEL, stats, ring_stats, tong_stats, period_labels, dim="all",
            ),
        ))
        story.append(_data_table_triple(cmp_hdr, sec1_groups, total_group_idx=len(sec1_groups) - 1))
        story.append(Spacer(1, 0.1 * cm))
        story.append(_p(
            f"注：每品类 3 行分别为 {period_labels[0]}、{period_labels[1]}、{period_labels[2]} 原始数据；"
            "右侧六列为对比期相对本期的比率（本期=100%）。",
            normal_style,
        ))
        story.append(Spacer(1, 0.25 * cm))

    # 维度合并 — 本期简表
    dim_sec_num = "二" if not has_cmp else "三"
    dim_title = f"{dim_sec_num}、维度合并统计"
    if has_cmp:
        dim_title += f"（{period_labels[0]}）"
    story.append(Paragraph(dim_title, subtitle_style))
    both_n = len(stats["alcohol_groups"] & stats["non_alcohol_groups"])
    sec2_rows = [
        _dim_data_row(
            f"非酒精<br/><font size=5 color='#666666'>({NON_ALCOHOL_DIM_LABEL})</font>",
            "non_alcohol",
        ),
        _dim_data_row(
            f"含酒精<br/><font size=5 color='#666666'>({ALCOHOL_DIM_LABEL})</font>",
            "alcohol",
        ),
        _dim_data_row(ALL_CATS_LABEL, "all"),
    ]
    story.append(_data_table_simple(simple_hdr, sec2_rows, is_total_row=len(sec2_rows) - 1))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_p(
        f"交叉说明（团体维度）：仅含酒精 {len(stats['alcohol_groups'] - stats['non_alcohol_groups'])} 个；"
        f"仅非酒精 {len(stats['non_alcohol_groups'] - stats['alcohol_groups'])} 个；"
        f"同团体兼有 {both_n} 个。",
        normal_style,
    ))
    story.append(Spacer(1, 0.25 * cm))

    # 维度合并同比环比
    if has_cmp:
        story.append(Paragraph(
            f"四、维度合并同比环比对比（{period_labels[0]} / {period_labels[1]} / {period_labels[2]}）",
            subtitle_style,
        ))
        sec2_groups = [
            (
                "非酒精",
                _build_triple_row_group(
                    f"非酒精<br/><font size=5 color='#666666'>({NON_ALCOHOL_DIM_LABEL})</font>",
                    stats, ring_stats, tong_stats, period_labels, dim="non_alcohol",
                ),
            ),
            (
                "含酒精",
                _build_triple_row_group(
                    f"含酒精<br/><font size=5 color='#666666'>({ALCOHOL_DIM_LABEL})</font>",
                    stats, ring_stats, tong_stats, period_labels, dim="alcohol",
                ),
            ),
            (
                ALL_CATS_LABEL,
                _build_triple_row_group(
                    ALL_CATS_LABEL, stats, ring_stats, tong_stats, period_labels, dim="all",
                ),
            ),
        ]
        story.append(_data_table_triple(cmp_hdr, sec2_groups, total_group_idx=len(sec2_groups) - 1))
        story.append(Spacer(1, 0.25 * cm))

    notes_sec = "五" if has_cmp else "三"
    story.append(Paragraph(f"{notes_sec}、口径说明", subtitle_style))
    notes = [
        "1. 数据来自万荷店 POS 店内订单和商品明细。",
        f"2. 团体和人数沿用订单桌访合并结果：本期共 {total_groups} 个消费团体、{_int_guests(total_guests)}。",
        "3. 销量和收入只统计有收入的饮品商品；赠送、免单、全额优惠不计入；套餐父项不计入，套餐子项计入实际品类。",
        "4. 整体营业额 = POS 店内订单收入 + 第三方平台外卖已完成订单收入；额占比 = 饮品收入 ÷ 整体营业额。",
        "5. 一个团体可能点多类饮品，所以各品类的团体数、人数占比相加可能超过合计。",
        "6. 第三方平台外卖目前没有商品明细，暂不归入饮品品类，只计入整体营业额分母。",
    ]
    if has_cmp:
        notes.append(
            f"7. 对比表中，{period_labels[0]}、{period_labels[1]}、{period_labels[2]}分别列出原始数据；右侧比率以本期为 100%。"
        )
    for note in notes:
        story.append(_p(note, normal_style))

    doc.build(story)


def main():
    parser = argparse.ArgumentParser(description="万荷饮品/酒水订单占比 PDF（可选同比环比）")
    parser.add_argument("--excel", required=True, help="万荷店内订单明细 Excel（本期）")
    parser.add_argument("--output", required=True, help="输出 PDF 路径")
    parser.add_argument("--store", default="万荷餐厅", help="报告标题门店名")
    parser.add_argument("--start", default=None, help="统计周期起始（展示用，不传则从 Excel 推断）")
    parser.add_argument("--end", default=None, help="统计周期结束（展示用）")
    parser.add_argument(
        "--mode",
        choices=["week", "month"],
        default=None,
        help="周期模式：week=周评（环比上周/同比去年同周），month=月评（环比上月/同比去年同月）",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite 主库路径（对比期数据）；默认 订单与桌访合并/长期订单分析/output/长期订单分析.db",
    )
    args = parser.parse_args()

    comparison = None
    period_label = None
    current_takeaway_revenue = 0.0

    if args.mode:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        db_path = args.db or os.path.join(
            repo_root, "订单与桌访合并", "长期订单分析", "output", "长期订单分析.db"
        )
        if not os.path.isfile(db_path):
            print(f"错误：主库不存在: {db_path}")
            sys.exit(1)

        dates = extract_dates_from_excel(args.excel)
        period_info = validate_period(dates, args.mode)
        if not period_info.get("valid"):
            print("错误：周期校验失败")
            for e in period_info.get("errors", []):
                print(f"  ⚠ {e}")
            sys.exit(1)

        cmp_info = get_comparison_periods(period_info, args.mode)
        db_store = infer_db_store(args.store)

        db = DatabaseManager(db_path)
        current_takeaway_revenue = db.get_takeaway_revenue_for_period(
            period_info["period_start"], period_info["period_end"], db_store
        )
        ringbi_stats = compute_stats_from_db(
            db, cmp_info["ringbi_start"], cmp_info["ringbi_end"], db_store
        )
        tongbi_stats = compute_stats_from_db(
            db, cmp_info["tongbi_start"], cmp_info["tongbi_end"], db_store
        )
        db.close()

        comparison = {
            **cmp_info,
            "mode": args.mode,
            "ringbi_stats": ringbi_stats,
            "tongbi_stats": tongbi_stats,
            "ringbi_missing": ringbi_stats is None,
            "tongbi_missing": tongbi_stats is None,
        }
        period_label = f'{period_info["period_start"]} ~ {period_info["period_end"]}'
        print(f"本期: {period_info['period_label']} ({period_label})")
        print(f"环比: {cmp_info['ringbi_label']} ({cmp_info['ringbi_start']} ~ {cmp_info['ringbi_end']})"
              + (" ✓" if ringbi_stats else " [主库无数据]"))
        print(f"同比: {cmp_info['tongbi_label']} ({cmp_info['tongbi_start']} ~ {cmp_info['tongbi_end']})"
              + (" ✓" if tongbi_stats else " [主库无数据]"))
    else:
        start = args.start or "2026-06-15"
        end = args.end or "2026-06-21"
        period_label = f"{start} ~ {end}"

    stats = compute_stats(args.excel, takeaway_revenue=current_takeaway_revenue)
    build_pdf(args.output, stats, args.store, period_label, comparison=comparison)
    print(f"PDF 已生成: {args.output}")
    print(
        f"消费团体: {stats['total_groups']}，就餐人数: {int(round(stats['total_guests']))}，"
        f"整体营业额: ¥{stats['overall_revenue']:,.0f} "
        f"(POS店内 ¥{stats['pos_order_revenue']:,.0f} + 平台外卖 ¥{stats['takeaway_revenue']:,.0f})"
    )
    print(f"{ALL_CATS_LABEL}涉及团体: {len(stats['all_target_groups'])} ({len(stats['all_target_groups'])/stats['total_groups']*100:.1f}%)")


if __name__ == "__main__":
    main()
