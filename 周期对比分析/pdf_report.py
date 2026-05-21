"""
PDF report generator for period comparison analysis.
"""

import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── Chinese font setup ──
_CHINESE_FONT = 'Helvetica'
_font_paths = [
    '/System/Library/Fonts/STHeiti Light.ttc',
    '/System/Library/Fonts/STHeiti Medium.ttc',
    '/System/Library/Fonts/PingFang.ttc',
    '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
    '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
]
for fp in _font_paths:
    if os.path.exists(fp):
        try:
            pdfmetrics.registerFont(TTFont('ChineseFont', fp))
            _CHINESE_FONT = 'ChineseFont'
            break
        except Exception:
            continue

_title_font = _CHINESE_FONT
_body_font = _CHINESE_FONT

# ── Styles ──
_styles = getSampleStyleSheet()
title_style = ParagraphStyle('Title2', parent=_styles['Title'], fontName=_title_font, fontSize=18, leading=24, spaceAfter=12)
subtitle_style = ParagraphStyle('Sub2', parent=_styles['Heading2'], fontName=_title_font, fontSize=14, leading=18, spaceBefore=16, spaceAfter=8)
normal_style = ParagraphStyle('Normal2', parent=_styles['Normal'], fontName=_body_font, fontSize=9, leading=13)
cell_style = ParagraphStyle('Cell2', parent=normal_style, fontSize=8, leading=11)
cell_c = ParagraphStyle('CellC', parent=cell_style, alignment=TA_CENTER)
cell_l = ParagraphStyle('CellL', parent=cell_style, alignment=TA_LEFT)
cell_r = ParagraphStyle('CellR', parent=cell_style, alignment=TA_RIGHT)

RED = colors.HexColor('#C0392B')
GREEN = colors.HexColor('#27AE60')


def _p(text, style=cell_c):
    return Paragraph(str(text), style)


def _p_color(text, color, style=cell_c):
    return Paragraph(f'<font color="{color}">{text}</font>', style)


def generate_comparison_pdf(output_path, period_info, comparison_info, comp_data, mode, store_name):
    """Generate the comparison PDF report."""
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                            rightMargin=1.5*cm, leftMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    story = []

    # ── Title ──
    story.append(Paragraph(f'周期对比分析报告', title_style))
    story.append(Paragraph(f'{store_name} ｜ 本期：{period_info["period_label"]}', subtitle_style))

    ringbi_label = comparison_info.get('ringbi_label', '环比')
    tongbi_label = comparison_info.get('tongbi_label', '同比')
    ringbi_dates = f'{comparison_info["ringbi_start"]} ~ {comparison_info["ringbi_end"]}'
    tongbi_dates = f'{comparison_info["tongbi_start"]} ~ {comparison_info["tongbi_end"]}'
    story.append(Paragraph(
        f'环比：{ringbi_label}（{ringbi_dates}）&nbsp;&nbsp;｜&nbsp;&nbsp;同比：{tongbi_label}（{tongbi_dates}）',
        normal_style
    ))
    story.append(Spacer(1, 0.5*cm))

    # ── Section 1: Operational data ──
    story.append(Paragraph('一、经营数据对比', subtitle_style))
    story.append(Spacer(1, 0.2*cm))

    op_header = ['指标', '本期', '环比', '', '同比', '']
    op_subheader = ['', '', '变化', '变化%', '变化', '变化%']
    op_data = [op_header, op_subheader]

    for item in comp_data['operational']:
        ring_color = RED if item['ringbi_diff'].startswith('-') else (GREEN if item['ringbi_diff'].startswith('+') else 'black')
        tong_color = RED if item['tongbi_diff'].startswith('-') else (GREEN if item['tongbi_diff'].startswith('+') else 'black')
        op_data.append([
            _p(item['label'], cell_l),
            _p(item['current'], cell_r),
            _p_color(item['ringbi_diff'], ring_color, cell_r),
            _p_color(item['ringbi_pct'], ring_color, cell_r),
            _p_color(item['tongbi_diff'], tong_color, cell_r),
            _p_color(item['tongbi_pct'], tong_color, cell_r),
        ])

    op_table = Table(op_data, colWidths=[4.5*cm, 2.5*cm, 2.5*cm, 2.0*cm, 2.5*cm, 2.0*cm])
    op_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 1), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 1), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, -1), _CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 2), (-1, -1), [colors.whitesmoke, colors.white]),
        ('SPAN', (2, 0), (3, 0)),
        ('SPAN', (4, 0), (5, 0)),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(op_table)
    story.append(Spacer(1, 0.15*cm))
    story.append(Paragraph('<font size="7" color="#666666">注：以上营业额已扣除外卖单、吧台及零食购买团体。</font>', normal_style))
    story.append(Spacer(1, 0.5*cm))

    # ── Section 2: Dish comparison ──
    story.append(Paragraph('二、重点菜品对比', subtitle_style))
    story.append(Spacer(1, 0.2*cm))

    cur_dishes = comp_data['dishes_current']
    ring_dishes_dict = dict(comp_data['dishes_ringbi'])
    tong_dishes_dict = dict(comp_data['dishes_tongbi'])

    dish_header = ['菜品名称', '本期销量', '环比销量', '变化', '变化率', '同比销量', '变化', '变化率']
    dish_data = [dish_header]
    for name, qty in cur_dishes:
        ring_qty = ring_dishes_dict.get(name)
        tong_qty = tong_dishes_dict.get(name)

        if ring_qty is not None and ring_qty > 0:
            ring_diff = qty - ring_qty
            ring_rate = round(ring_diff / ring_qty * 100, 1)
            ring_diff_str = f'{ring_diff:+d}'
            ring_rate_str = f'{ring_rate:+.1f}%'
            ring_color = RED if ring_diff < 0 else (GREEN if ring_diff > 0 else 'black')
        else:
            ring_diff_str = '-'
            ring_rate_str = '-'
            ring_color = 'black'

        if tong_qty is not None and tong_qty > 0:
            tong_diff = qty - tong_qty
            tong_rate = round(tong_diff / tong_qty * 100, 1)
            tong_diff_str = f'{tong_diff:+d}'
            tong_rate_str = f'{tong_rate:+.1f}%'
            tong_color = RED if tong_diff < 0 else (GREEN if tong_diff > 0 else 'black')
        else:
            tong_diff_str = '-'
            tong_rate_str = '-'
            tong_color = 'black'

        dish_data.append([
            _p(name, cell_l),
            _p(str(qty), cell_c),
            _p(str(ring_qty) if ring_qty is not None else '-', cell_c),
            _p_color(ring_diff_str, ring_color, cell_c),
            _p_color(ring_rate_str, ring_color, cell_c),
            _p(str(tong_qty) if tong_qty is not None else '-', cell_c),
            _p_color(tong_diff_str, tong_color, cell_c),
            _p_color(tong_rate_str, tong_color, cell_c),
        ])

    dish_table = Table(dish_data, colWidths=[4.5*cm, 1.6*cm, 1.6*cm, 1.4*cm, 1.6*cm, 1.6*cm, 1.4*cm, 1.6*cm])
    dish_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, -1), _CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(dish_table)

    # ── Category distribution ──
    cats_cur_list = comp_data.get('cats_current', [])
    cats_ring = dict(comp_data.get('cats_ringbi', []))
    cats_tong = dict(comp_data.get('cats_tongbi', []))

    if cats_cur_list:
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph('三、商品中类销售额分布', subtitle_style))
        story.append(Spacer(1, 0.2*cm))

        cur_total = sum(v for _, v in cats_cur_list)

        cat_header = ['商品中类', '本期金额', '本期占比', '环比变化', '环比变化率', '同比变化', '同比变化率']
        cat_data = [cat_header]
        for cat_name, rev in cats_cur_list:
            ring_rev = cats_ring.get(cat_name)
            tong_rev = cats_tong.get(cat_name)
            cur_pct = round(rev / cur_total * 100, 1) if cur_total > 0 else 0

            if ring_rev is not None and ring_rev > 0:
                ring_diff = rev - ring_rev
                ring_rate = round(ring_diff / ring_rev * 100, 1)
                ring_diff_str = f'{ring_diff:+,.0f}'
                ring_rate_str = f'{ring_rate:+.1f}%'
                ring_color = RED if ring_diff < 0 else (GREEN if ring_diff > 0 else 'black')
            else:
                ring_diff_str = '-'
                ring_rate_str = '-'
                ring_color = 'black'

            if tong_rev is not None and tong_rev > 0:
                tong_diff = rev - tong_rev
                tong_rate = round(tong_diff / tong_rev * 100, 1)
                tong_diff_str = f'{tong_diff:+,.0f}'
                tong_rate_str = f'{tong_rate:+.1f}%'
                tong_color = RED if tong_diff < 0 else (GREEN if tong_diff > 0 else 'black')
            else:
                tong_diff_str = '-'
                tong_rate_str = '-'
                tong_color = 'black'

            cat_data.append([
                _p(cat_name, cell_l),
                _p(f'¥{rev:,.0f}', cell_r),
                _p(f'{cur_pct}%', cell_c),
                _p_color(ring_diff_str, ring_color, cell_r),
                _p_color(ring_rate_str, ring_color, cell_c),
                _p_color(tong_diff_str, tong_color, cell_r),
                _p_color(tong_rate_str, tong_color, cell_c),
            ])

        # Totals row
        cur_total_rev = sum(v for _, v in cats_cur_list)
        ring_total_rev = sum(v for _, v in comp_data.get('cats_ringbi', []))
        tong_total_rev = sum(v for _, v in comp_data.get('cats_tongbi', []))

        ring_total_diff_str = f'{cur_total_rev - ring_total_rev:+,.0f}' if ring_total_rev > 0 else '-'
        ring_total_rate_str = f'{(cur_total_rev - ring_total_rev) / ring_total_rev * 100:+.1f}%' if ring_total_rev > 0 else '-'
        tong_total_diff_str = f'{cur_total_rev - tong_total_rev:+,.0f}' if tong_total_rev > 0 else '-'
        tong_total_rate_str = f'{(cur_total_rev - tong_total_rev) / tong_total_rev * 100:+.1f}%' if tong_total_rev > 0 else '-'
        ring_t_color = RED if ring_total_diff_str.startswith('-') else (GREEN if ring_total_diff_str.startswith('+') else 'black')
        tong_t_color = RED if tong_total_diff_str.startswith('-') else (GREEN if tong_total_diff_str.startswith('+') else 'black')

        cat_data.append([
            _p('合计', cell_l),
            _p(f'¥{cur_total_rev:,.0f}', cell_r),
            _p('100%', cell_c),
            _p_color(ring_total_diff_str, ring_t_color, cell_r),
            _p_color(ring_total_rate_str, ring_t_color, cell_c),
            _p_color(tong_total_diff_str, tong_t_color, cell_r),
            _p_color(tong_total_rate_str, tong_t_color, cell_c),
        ])

        cat_table = Table(cat_data, colWidths=[4.0*cm, 2.2*cm, 1.6*cm, 2.2*cm, 2.0*cm, 2.2*cm, 2.0*cm])
        cat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, -1), _CHINESE_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.whitesmoke, colors.white]),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#FFF2CC')),
            ('FONTNAME', (0, -1), (-1, -1), _CHINESE_FONT),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(cat_table)
        story.append(Spacer(1, 0.15*cm))
        story.append(Paragraph('<font size="7" color="#666666">注：以上为全部订单（含外卖）的商品销售额，合计大于一、经营数据中的营业额。</font>', normal_style))

    story.append(Spacer(1, 0.5*cm))

    # ── Section 4: Spending buckets ──
    story.append(Paragraph('四、客单价区间对比', subtitle_style))
    story.append(Spacer(1, 0.2*cm))

    buckets_cur = comp_data['buckets_current']
    buckets_ring = comp_data['buckets_ringbi']
    buckets_tong = comp_data['buckets_tongbi']

    bucket_order = ['≥300', '200~300', '150~200', '100~150', '<100']
    bkt_header = ['客单价区间', '本期单数', '本期占比', '环比单数变化', '环比变化率', '同比单数变化', '同比变化率']
    bkt_data = [bkt_header]
    for bk in bucket_order:
        cur_cnt = buckets_cur.get(bk, {}).get('订单数', 0)
        cur_pct = buckets_cur.get(bk, {}).get('占比', 0)
        ring_cnt = buckets_ring.get(bk, {}).get('订单数') if buckets_ring else None
        tong_cnt = buckets_tong.get(bk, {}).get('订单数') if buckets_tong else None

        if ring_cnt is not None and ring_cnt > 0:
            ring_diff = cur_cnt - ring_cnt
            ring_rate = round(ring_diff / ring_cnt * 100, 1)
            ring_diff_str = f'{ring_diff:+d}'
            ring_rate_str = f'{ring_rate:+.1f}%'
            ring_color = RED if ring_diff < 0 else (GREEN if ring_diff > 0 else 'black')
        else:
            ring_diff_str = '-'
            ring_rate_str = '-'
            ring_color = 'black'

        if tong_cnt is not None and tong_cnt > 0:
            tong_diff = cur_cnt - tong_cnt
            tong_rate = round(tong_diff / tong_cnt * 100, 1)
            tong_diff_str = f'{tong_diff:+d}'
            tong_rate_str = f'{tong_rate:+.1f}%'
            tong_color = RED if tong_diff < 0 else (GREEN if tong_diff > 0 else 'black')
        else:
            tong_diff_str = '-'
            tong_rate_str = '-'
            tong_color = 'black'

        bkt_data.append([
            _p(bk, cell_c),
            _p(str(cur_cnt), cell_c),
            _p(f"{cur_pct}%", cell_c),
            _p_color(ring_diff_str, ring_color, cell_c),
            _p_color(ring_rate_str, ring_color, cell_c),
            _p_color(tong_diff_str, tong_color, cell_c),
            _p_color(tong_rate_str, tong_color, cell_c),
        ])

    bkt_table = Table(bkt_data, colWidths=[3.5*cm, 2.0*cm, 2.0*cm, 2.2*cm, 2.0*cm, 2.2*cm, 2.0*cm])
    bkt_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, -1), _CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(bkt_table)

    # ── Data quality note ──
    dq = comp_data['data_quality']
    warnings = []
    if dq['ringbi_missing']:
        warnings.append(f'环比数据缺失（{comparison_info["ringbi_label"]}在数据库中无记录）')
    if dq['tongbi_missing']:
        warnings.append(f'同比数据缺失（{comparison_info["tongbi_label"]}在数据库中无记录）')
    if warnings:
        story.append(Spacer(1, 0.8*cm))
        story.append(Paragraph('数据完整性说明', subtitle_style))
        for w in warnings:
            story.append(Paragraph(f'<font color="red">⚠ {w}</font>', normal_style))

    doc.build(story)
