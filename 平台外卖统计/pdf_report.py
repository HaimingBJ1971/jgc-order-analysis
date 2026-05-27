import os
from datetime import datetime
from html import escape as html_escape

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def register_chinese_font():
    font_paths = [
        ('/System/Library/Fonts/STHeiti Medium.ttc', 0),
        ('/System/Library/Fonts/STHeiti Medium.ttc', 1),
        ('/System/Library/Fonts/STHeiti Light.ttc', 0),
        ('/System/Library/Fonts/STHeiti Light.ttc', 1),
        ('/System/Library/Fonts/PingFang.ttc', 0),
    ]
    for font_path, subfont_index in font_paths:
        try:
            name = f'ChineseFont_{subfont_index}'
            if 'ttc' in font_path.lower():
                pdfmetrics.registerFont(TTFont(name, font_path, subfontIndex=subfont_index))
            else:
                pdfmetrics.registerFont(TTFont(name, font_path))
            return name
        except Exception:
            continue
    return 'Helvetica'

CHINESE_FONT = register_chinese_font()

def _p(text, style):
    return Paragraph(html_escape(str(text)), style)

def _p_bold(text, style):
    return Paragraph(f"<b>{html_escape(str(text))}</b>", style)

def generate_takeaway_pdf_report(output_path, summary_data, store_comp_df, platform_stats_df, meal_df, eff_df, overtime_df, start_date, end_date):
    """
    Generates a beautifully formatted summary A4 PDF report in Chinese.
    """
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        rightMargin=1.5*cm, leftMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm
    )
    story = []
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'T', parent=styles['Title'], fontSize=18, leading=22,
        textColor=colors.HexColor('#1f4e78'), spaceAfter=15, fontName=CHINESE_FONT
    )
    subtitle_style = ParagraphStyle(
        'ST', parent=styles['Heading2'], fontSize=12, leading=16,
        textColor=colors.HexColor('#2c3e50'), spaceBefore=12, spaceAfter=8, fontName=CHINESE_FONT
    )
    normal_style = ParagraphStyle(
        'N', parent=styles['Normal'], fontName=CHINESE_FONT, fontSize=9, leading=12
    )
    bold_style = ParagraphStyle(
        'B', parent=normal_style, fontName=CHINESE_FONT, fontSize=9, leading=12, bold=True
    )
    cell_c = ParagraphStyle('CC', parent=normal_style, fontSize=8, leading=10, alignment=TA_CENTER)
    cell_l = ParagraphStyle('CL', parent=normal_style, fontSize=8, leading=10, alignment=TA_LEFT)
    cell_r = ParagraphStyle('CR', parent=normal_style, fontSize=8, leading=10, alignment=TA_RIGHT)
    
    hdr_style = ParagraphStyle('H', parent=normal_style, fontSize=8, leading=10, alignment=TA_CENTER, textColor=colors.white)
    
    # 1. Title Block
    story.append(Paragraph('金谷仓餐饮平台外卖经营数据汇总报告', title_style))
    period_str = f"{start_date} ~ {end_date}" if start_date != end_date else start_date
    story.append(Paragraph(f'统计周期: <b>{period_str}</b> &nbsp;&nbsp;&nbsp;&nbsp; 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}', normal_style))
    story.append(Spacer(1, 0.4 * cm))
    
    # 2. Section 1: 数据总览 (Overall Overview)
    story.append(Paragraph('一、数据总览', subtitle_style))
    
    # Layout a summary grid: 2 columns of key figures
    rev = summary_data.get("订单收入", 0.0)
    paid = summary_data.get("顾客实付", 0.0)
    orders = summary_data.get("有效订单数", 0.0)
    cancelled = summary_data.get("退单数", 0.0)
    avg_t = summary_data.get("客单价", 0.0)
    comm_r = summary_data.get("抽佣率", 0.0)
    exp_r = summary_data.get("订单支出率", 0.0)
    refund = summary_data.get("部分退款", 0.0)
    
    summary_grid_data = [
        [
            _p("有效外卖订单数:", bold_style), _p(f"{orders:,.0f} 单", normal_style),
            _p("退单及取消数量:", bold_style), _p(f"{cancelled:,.0f} 单", normal_style),
        ],
        [
            _p("外卖实收营业额:", bold_style), _p(f"¥{rev:,.2f}", normal_style),
            _p("顾客实付总额:", bold_style), _p(f"¥{paid:,.2f}", normal_style),
        ],
        [
            _p("有效外卖客单价:", bold_style), _p(f"¥{avg_t:,.2f}", normal_style),
            _p("平台部分退款额:", bold_style), _p(f"¥{refund:,.2f}", normal_style),
        ],
        [
            _p("整体抽佣率:", bold_style), _p(f"{comm_r:.2%}", normal_style),
            _p("订单支出率:", bold_style), _p(f"{exp_r:.2%}", normal_style),
        ],
    ]
    summary_grid_table = Table(summary_grid_data, colWidths=[4*cm, 4*cm, 4*cm, 4*cm])
    summary_grid_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F2F6F9')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D3D3D3')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_grid_table)
    story.append(Spacer(1, 0.4 * cm))
    
    # 3. Section 2: 门店对比 (Store Comparison)
    story.append(Paragraph('二、各门店外卖对比', subtitle_style))
    
    comp_hdr = ["门店", "订单数", "退单", "订单收入", "顾客实付", "客单价", "抽佣率", "支出率"]
    comp_rows = [[_p(h, hdr_style) for h in comp_hdr]]
    
    for _, r in store_comp_df.iterrows():
        comp_rows.append([
            _p(r["门店"], cell_c),
            _p(f"{r['有效订单数']:.0f}", cell_r),
            _p(f"{r['退单数']:.0f}", cell_r),
            _p(f"¥{r['订单收入']:,.2f}", cell_r),
            _p(f"¥{r['顾客实付']:,.2f}", cell_r),
            _p(f"¥{r['客单价']:,.2f}", cell_r),
            _p(f"{r['抽佣率']:.1%}", cell_r),
            _p(f"{r['订单支出率']:.1%}", cell_r),
        ])
        
    comp_table = Table(comp_rows, colWidths=[2.2*cm, 1.4*cm, 1.2*cm, 2.6*cm, 2.6*cm, 2.0*cm, 2.0*cm, 2.0*cm])
    comp_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4e78')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D3D3D3')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(comp_table)
    story.append(Spacer(1, 0.4 * cm))
    
    # 4. Section 3: 平台分布与时段 (Platform & Meal Period Stats)
    story.append(Paragraph('三、平台来源与下单时段', subtitle_style))
    
    # Left table: Platform split, Right table: Meal period split (Side-by-side or stacked)
    # Let's stack them for neatness
    story.append(Paragraph('<b>平台来源分布:</b>', normal_style))
    story.append(Spacer(1, 0.1 * cm))
    
    plat_hdr = ["门店", "平台", "订单数", "退单数", "订单收入", "顾客实付", "客单价"]
    plat_rows = [[_p(h, hdr_style) for h in plat_hdr]]
    for _, r in platform_stats_df.iterrows():
        plat_rows.append([
            _p(r["门店"], cell_c),
            _p(r["平台"], cell_c),
            _p(f"{r['有效订单数']:.0f}", cell_r),
            _p(f"{r['退单数']:.0f}", cell_r),
            _p(f"¥{r['订单收入']:,.2f}", cell_r),
            _p(f"¥{r['顾客实付']:,.2f}", cell_r),
            _p(f"¥{r['客单价']:,.2f}", cell_r),
        ])
    plat_table = Table(plat_rows, colWidths=[2.5*cm, 2.5*cm, 1.8*cm, 1.8*cm, 2.8*cm, 2.8*cm, 1.8*cm])
    plat_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4e78')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D3D3D3')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(plat_table)
    story.append(Spacer(1, 0.3 * cm))
    
    story.append(Paragraph('<b>午市 / 晚市订单分布:</b>', normal_style))
    story.append(Spacer(1, 0.1 * cm))
    
    meal_hdr = ["门店", "下单时段", "订单数", "订单收入", "订单收入占比"]
    meal_rows = [[_p(h, hdr_style) for h in meal_hdr]]
    for _, r in meal_df.iterrows():
        meal_rows.append([
            _p(r["门店"], cell_c),
            _p(r["时段"], cell_c),
            _p(f"{r['订单数']:.0f}", cell_r),
            _p(f"¥{r['订单收入']:,.2f}", cell_r),
            _p(f"{r['占比']:.1%}", cell_r),
        ])
    meal_table = Table(meal_rows, colWidths=[3.2*cm, 3.2*cm, 2.6*cm, 3.8*cm, 3.2*cm])
    meal_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4e78')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D3D3D3')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(meal_table)
    story.append(Spacer(1, 0.4 * cm))
    
    # 5. Section 4: 履约时效 (Fulfillment efficiency)
    story.append(Paragraph('四、各门店外卖履约效率', subtitle_style))
    
    eff_hdr = ["门店", "平均接单耗时", "P50接单", "P90接单", "平均送达时长", "P50送达", "P90送达"]
    eff_rows = [[_p(h, hdr_style) for h in eff_hdr]]
    for _, r in eff_df.iterrows():
        eff_rows.append([
            _p(r["门店"], cell_c),
            _p(f"{r['平均接单耗时']:.1f} 分钟", cell_r),
            _p(f"{r['P50接单耗时']:.1f} 分", cell_r),
            _p(f"{r['P90接单耗时']:.1f} 分", cell_r),
            _p(f"{r['平均送达时长']:.1f} 分钟", cell_r),
            _p(f"{r['P50送达时长']:.1f} 分", cell_r),
            _p(f"{r['P90送达时长']:.1f} 分", cell_r),
        ])
    eff_table = Table(eff_rows, colWidths=[2.2*cm, 2.3*cm, 2.0*cm, 2.0*cm, 2.3*cm, 2.6*cm, 2.6*cm])
    eff_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4e78')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D3D3D3')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(eff_table)
    
    # Write a note on overtime alerts if any
    ot_count = len(overtime_df)
    if ot_count > 0:
        story.append(Spacer(1, 0.25 * cm))
        story.append(Paragraph(f'注：本周期共产生 <b>{ot_count}</b> 个配送超时关注单 (下单至送达耗时超过 45 分钟)。详细清单参见 Excel 报表。', normal_style))
        
    doc.build(story)
    print(f"Summary PDF report successfully written to: {output_path}")
