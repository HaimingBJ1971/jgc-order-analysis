#!/usr/bin/env python3
"""万荷店饮品/酒水类订单统计 PDF（九类商品中类、消费团体口径、A4 纵置）。"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from html import escape as html_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_skill_dir = os.path.join(os.path.dirname(__file__), "..", "每日订单分析", "order_merger_skill")
_merger_dir = os.path.join(os.path.dirname(__file__), "..", "订单桌访合并")
sys.path.insert(0, os.path.abspath(_skill_dir))
sys.path.insert(0, os.path.abspath(_merger_dir))
from merge_order_zhuofang import load_and_process_orders  # noqa: E402

# 展示顺序：前三个非酒精，其后含酒精
CATEGORIES = [
    "调饮汁", "饮料和水果", "茶",
    "啤酒", "白酒", "葡萄酒", "鸡尾酒", "苏格兰威士忌", "黄酒",
]
ALCOHOL_CATS = {"啤酒", "白酒", "葡萄酒", "鸡尾酒", "苏格兰威士忌", "黄酒"}
NON_ALCOHOL_CATS = {"调饮汁", "饮料和水果", "茶"}
ALL_CATS_LABEL = "九类合计"
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


def compute_stats(excel_path: str) -> dict:
    """与订单桌访合并同一 pipeline：堂食、去外点自取、同桌补单合并、过滤后按消费团体统计。"""
    group_sum, _group_items, merge_stats, items, _orders_with_group = load_and_process_orders(excel_path)

    items["菜品收入"] = items["菜品收入"].astype(float)
    items["数量"] = items["数量"].astype(float).fillna(0)

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

    total_groups = len(group_sum)
    total_guests = float(group_sum["团体人数"].sum())
    total_revenue = float(items["菜品收入"].sum())

    groups_by_cat: dict[str, set[tuple]] = {}
    revenue_by_cat: dict[str, float] = {}
    guests_by_cat: dict[str, float] = {}
    qty_by_cat: dict[str, float] = {}
    for cat in CATEGORIES:
        mask = items["商品中类"].astype(str).str.strip() == cat
        subset = items.loc[mask]
        gks = {
            order_to_group[oid]
            for oid in subset["订单号"].astype(str)
            if oid in order_to_group
        }
        groups_by_cat[cat] = gks
        revenue_by_cat[cat] = float(subset["菜品收入"].sum())
        guests_by_cat[cat] = _guests_for_groups(gks, guests_by_group)
        qty_by_cat[cat] = float(subset["数量"].sum())

    def _rev_for_cats(cat_set: set[str]) -> float:
        mask = items["商品中类"].astype(str).str.strip().isin(cat_set)
        return float(items.loc[mask, "菜品收入"].sum())

    def _qty_for_cats(cat_set: set[str]) -> float:
        mask = items["商品中类"].astype(str).str.strip().isin(cat_set)
        return float(items.loc[mask, "数量"].sum())

    alcohol_groups = set().union(*(groups_by_cat[c] for c in ALCOHOL_CATS))
    non_alcohol_groups = set().union(*(groups_by_cat[c] for c in NON_ALCOHOL_CATS))
    all_target_groups = alcohol_groups | non_alcohol_groups

    return {
        "total_groups": total_groups,
        "total_guests": total_guests,
        "total_revenue": total_revenue,
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
        "merge_stats": merge_stats,
    }


def _int_guests(n: float) -> str:
    return f"{int(round(n))} 人"


def _cat_label(cat: str) -> str:
    tag = "含酒精" if cat in ALCOHOL_CATS else "非酒精"
    return f"{cat}<br/><font size=5 color='#666666'>({tag})</font>"


def build_pdf(output_path: str, stats: dict, store_label: str, period_label: str) -> None:
    font = _register_font()
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
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
        Spacer(1, 0.3 * cm),
    ]

    summary_grid = [
        [
            _p("消费团体数:", bold_style), _p(f"{total_groups} 个", normal_style),
            _p("就餐人数合计:", bold_style), _p(_int_guests(total_guests), normal_style),
        ],
        [
            _p("商品收入合计:", bold_style), _p(_money(total_revenue), normal_style),
            _p("人数口径:", bold_style),
            _p("合并后团体「团体人数」汇总", normal_style),
        ],
        [
            _p("统计口径:", bold_style),
            _p("与订单桌访合并一致：堂食、去外点自取、同桌补单合并", normal_style),
            _p("POS原始单数(参考):", bold_style),
            _p(f"{raw_pos} 单（未合并，含已剔除项）", normal_style),
        ],
        [
            _p("占比分母:", bold_style),
            _p("团体/人数/金额/点购率均以统计范围内消费团体为分母", normal_style),
            _p("", bold_style), _p("", normal_style),
        ],
    ]
    summary_table = Table(summary_grid, colWidths=[avail_w * 0.18, avail_w * 0.32, avail_w * 0.18, avail_w * 0.32])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_SUMMARY_BG),
        ("GRID", (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.25 * cm))

    # A4 纵置 9 列：缩短表头文字 + 7pt 字号
    table_hdr = ["品类", "团体", "团占比", "人数", "人占比", "销量", "点购率", "收入", "额占比"]
    col_fracs = [0.152, 0.087, 0.098, 0.098, 0.098, 0.087, 0.098, 0.196, 0.087]
    col_widths = [avail_w * f for f in col_fracs]
    right_cols = {1, 3, 5, 7}

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

    def _data_table(header, rows, is_total_row: int | None = None):
        table_rows = [[Paragraph(html_escape(h), hdr_style) for h in header]]
        for row in rows:
            cells = []
            for i, val in enumerate(row):
                if i == 0:
                    if "<br/>" in str(val):
                        cells.append(Paragraph(val, cat_style))
                    else:
                        cells.append(_p(val, cell_l))
                elif i in right_cols:
                    cells.append(_p(val, cell_r))
                else:
                    cells.append(_p(val, cell_c))
            table_rows.append(cells)
        t = Table(table_rows, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), COLOR_HDR_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("GRID", (0, 0), (-1, -1), 0.5, COLOR_GRID),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_ROW_ALT]),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ]
        if is_total_row is not None:
            tr = is_total_row + 1
            style_cmds.append(("BACKGROUND", (0, tr), (-1, tr), colors.HexColor("#D6E4F0")))
            style_cmds.append(("FONTNAME", (0, tr), (-1, tr), font))
        t.setStyle(TableStyle(style_cmds))
        return t

    # Section 1
    story.append(Paragraph("一、分品类统计（消费团体 / 人数 / 销量 / 金额）", subtitle_style))
    sec1_hdr = table_hdr
    sec1_rows = [_cat_data_row(cat) for cat in CATEGORIES]
    all_n = len(stats["all_target_groups"])
    all_rev = stats["all_target_revenue"]
    all_g = stats["all_target_guests"]
    all_qty = stats["all_target_qty"]
    sec1_rows.append([
        ALL_CATS_LABEL,
        str(all_n),
        _pct(all_n, total_groups),
        _int_guests(all_g),
        _pct(all_g, total_guests),
        _int_qty(all_qty),
        _penetration_rate(all_qty, total_guests),
        _money(all_rev),
        _pct(all_rev, total_revenue),
    ])
    story.append(_data_table(sec1_hdr, sec1_rows, is_total_row=len(sec1_rows) - 1))
    story.append(Spacer(1, 0.1 * cm))
    story.append(_p(
        "注：品类按非酒精→含酒精排列；团体数=含该品类消费团体数（同桌补单已合并）。"
        f"点购率=销量÷统计范围就餐人数（{int(round(total_guests))} 人）；一人一杯为 100%。",
        normal_style,
    ))
    story.append(Spacer(1, 0.25 * cm))

    # Section 2
    story.append(Paragraph("二、维度合并统计", subtitle_style))
    alc_n = len(stats["alcohol_groups"])
    non_n = len(stats["non_alcohol_groups"])
    both_n = len(stats["alcohol_groups"] & stats["non_alcohol_groups"])
    sec2_hdr = table_hdr
    sec2_rows = [
        [
            "非酒精<br/><font size=5 color='#666666'>(调饮汁+饮料和水果+茶)</font>",
            str(non_n), _pct(non_n, total_groups),
            _int_guests(stats["non_alcohol_guests"]), _pct(stats["non_alcohol_guests"], total_guests),
            _int_qty(stats["non_alcohol_qty"]), _penetration_rate(stats["non_alcohol_qty"], total_guests),
            _money(stats["non_alcohol_revenue"]), _pct(stats["non_alcohol_revenue"], total_revenue),
        ],
        [
            f"含酒精<br/><font size=5 color='#666666'>({ALCOHOL_DIM_LABEL})</font>",
            str(alc_n), _pct(alc_n, total_groups),
            _int_guests(stats["alcohol_guests"]), _pct(stats["alcohol_guests"], total_guests),
            _int_qty(stats["alcohol_qty"]), _penetration_rate(stats["alcohol_qty"], total_guests),
            _money(stats["alcohol_revenue"]), _pct(stats["alcohol_revenue"], total_revenue),
        ],
        [
            ALL_CATS_LABEL,
            str(all_n), _pct(all_n, total_groups),
            _int_guests(all_g), _pct(all_g, total_guests),
            _int_qty(all_qty), _penetration_rate(all_qty, total_guests),
            _money(all_rev), _pct(all_rev, total_revenue),
        ],
    ]
    story.append(_data_table(sec2_hdr, sec2_rows, is_total_row=len(sec2_rows) - 1))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_p(
        f"交叉说明（团体维度）：仅含酒精 {len(stats['alcohol_groups'] - stats['non_alcohol_groups'])} 个；"
        f"仅非酒精 {len(stats['non_alcohol_groups'] - stats['alcohol_groups'])} 个；"
        f"同团体兼有 {both_n} 个。",
        normal_style,
    ))
    story.append(Spacer(1, 0.25 * cm))

    # Section 3 — 口径说明（压缩间距以适配纵置单页）
    story.append(Paragraph("三、口径说明", subtitle_style))
    for note in [
        "1. 数据来源：万荷店 POS「店内订单明细」+「商品-店内订单明细」，统计周期内堂食有效数据。",
        "2. 消费团体识别：复用订单桌访合并 pipeline——剔除非堂食、外点自取、免单、纯零食/打包、零散小单、吧台等，同桌后续补单合并为一团体。",
        "3. 品类识别：以 POS「商品中类」精确匹配上述九类；分表按非酒精→含酒精排列；销量为「数量」合计。",
        f"4. 统计范围共 {total_groups} 个消费团体、{_int_guests(total_guests)}，与订单桌访合并报告一致。",
        f"5. 点购率=销售数量÷统计范围就餐人数（共 {_int_guests(total_guests)}）；100%表示人均约 1 份该品类。",
        "6. 各品类团体/人数占比之和可能大于合计（一团体可含多类）；金额按「菜品收入」汇总。",
        "7. 已剔除无效行、合计行及菜品收入≤0 的明细。",
    ]:
        story.append(_p(note, normal_style))

    doc.build(story)


def main():
    parser = argparse.ArgumentParser(description="万荷饮品/酒水订单占比 PDF")
    parser.add_argument("--excel", required=True, help="万荷店内订单明细 Excel")
    parser.add_argument("--output", required=True, help="输出 PDF 路径")
    parser.add_argument("--store", default="万荷餐厅")
    parser.add_argument("--start", default="2026-06-15")
    parser.add_argument("--end", default="2026-06-21")
    args = parser.parse_args()

    stats = compute_stats(args.excel)
    period = f"{args.start} ~ {args.end}"
    build_pdf(args.output, stats, args.store, period)
    print(f"PDF 已生成: {args.output}")
    print(f"消费团体: {stats['total_groups']}，就餐人数: {int(round(stats['total_guests']))}，菜品收入: ¥{stats['total_revenue']:,.0f}")
    print(f"{ALL_CATS_LABEL}涉及团体: {len(stats['all_target_groups'])} ({len(stats['all_target_groups'])/stats['total_groups']*100:.1f}%)")


if __name__ == "__main__":
    main()
