import os
import tempfile
from datetime import datetime
from html import escape as html_escape

import matplotlib
matplotlib.use('Agg')  # Headless backend to avoid GUI conflict
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
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

def generate_takeaway_pdf_report(output_path, summary_data, store_comp_df, platform_stats_df, meal_df, eff_df, overtime_df, start_date, end_date, daily_trends=None):
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
        
    # 6. Section 5: 每日趋势与细分统计 (时间段跨天时展示)
    chart_img_path = None
    if start_date != end_date and daily_trends is not None and not daily_trends.empty:
        # 新页起始
        story.append(PageBreak())
        story.append(Paragraph('五、每日外卖营业趋势分析', subtitle_style))
        story.append(Paragraph('本统计周期跨越多个营业日，各门店每日有效外卖订单数量及实收营业额（订单收入）波动走势如下所示：', normal_style))
        story.append(Spacer(1, 0.4 * cm))
        
        # 绘制折线图
        try:
            df_chart = daily_trends.copy()
            df_chart["营业日"] = df_chart["营业日"].astype(str)
            all_dates = sorted(df_chart["营业日"].unique())
            all_stores = sorted(df_chart["门店"].unique())
            
            # Matplotlib 绘图配置
            fig, ax = plt.subplots(figsize=(10, 4.5), dpi=300)
            
            # 支持中文的字体设置 (macOS 下 Arial Unicode MS / PingFang SC 极佳)
            plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang SC', 'STHeiti', 'Heiti SC', 'sans-serif']
            plt.rcParams['axes.unicode_minus'] = False
            
            # 专属色系
            store_colors = {
                "万荷店": "#1f4e78",
                "保利店": "#e74c3c",
                "湾里店": "#f39c12"
            }
            
            for store in all_stores:
                store_df = df_chart[df_chart["门店"] == store].set_index("营业日")
                # 对齐所有日期，缺失的填充 0
                y_vals = [float(store_df.loc[d, "订单收入"]) if d in store_df.index else 0.0 for d in all_dates]
                x_labels = [d[5:] if len(d) == 10 else d for d in all_dates]  # 简写为 MM-DD 格式
                
                color = store_colors.get(store, None)
                line, = ax.plot(x_labels, y_vals, marker='o', linewidth=2.5, markersize=6, label=store, color=color)
                
                # 数据标签 (天数不超过 14 天时标记)
                if len(all_dates) <= 14:
                    for x_idx, y_val in enumerate(y_vals):
                        if y_val > 0:
                            ax.text(x_idx, y_val + (max(y_vals) * 0.015), f"¥{y_val:.0f}", 
                                    ha='center', va='bottom', fontsize=8, color=line.get_color(), weight='bold')
            
            ax.set_title("每日外卖实收营业额变化趋势", fontsize=12, fontweight='bold', pad=12, color='#2c3e50')
            ax.set_xlabel("营业日 (月-日)", fontsize=9, labelpad=8, color='#34495e')
            ax.set_ylabel("外卖订单收入 (元)", fontsize=9, labelpad=8, color='#34495e')
            ax.grid(True, linestyle='--', alpha=0.5, color='#cccccc')
            ax.legend(loc="upper left", frameon=True, facecolor='#ffffff', edgecolor='#dddddd')
            
            y_max = df_chart["订单收入"].max()
            if y_max > 0:
                ax.set_ylim(0, y_max * 1.15)
                
            for spine in ['top', 'right']:
                ax.spines[spine].set_visible(False)
                
            plt.tight_layout()
            
            # 保存到临时路径
            temp_dir = tempfile.gettempdir()
            import uuid
            chart_img_path = os.path.join(temp_dir, f"takeaway_daily_chart_{uuid.uuid4().hex}.png")
            fig.savefig(chart_img_path, dpi=300)
            plt.close(fig)
            
            story.append(Image(chart_img_path, width=15*cm, height=6.75*cm))
            story.append(Spacer(1, 0.4 * cm))
            
        except Exception as e:
            print(f"⚠ 绘制折线图出错: {e}")
            story.append(Paragraph(f"[⚠ 趋势折线图生成失败: {e}]", normal_style))
            story.append(Spacer(1, 0.4 * cm))

        # 每日明细表格
        story.append(Paragraph('<b>每日外卖营业明细统计:</b>', normal_style))
        story.append(Spacer(1, 0.15 * cm))
        
        daily_hdr = ["营业日", "门店", "有效订单", "订单收入", "顾客实付", "外卖客单价"]
        daily_rows = [[_p(h, hdr_style) for h in daily_hdr]]
        
        df_table = daily_trends.sort_values(["营业日", "门店"]).copy()
        for _, r in df_table.iterrows():
            daily_rows.append([
                _p(r["营业日"], cell_c),
                _p(r["门店"], cell_c),
                _p(f"{r['有效订单数']:.0f} 单", cell_r),
                _p(f"¥{r['订单收入']:,.2f}", cell_r),
                _p(f"¥{r['顾客实付']:,.2f}", cell_r),
                _p(f"¥{r['客单价']:,.2f}", cell_r),
            ])
            
        daily_table = Table(daily_rows, colWidths=[3.0*cm, 2.5*cm, 2.0*cm, 3.0*cm, 3.0*cm, 2.5*cm])
        daily_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4e78')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D3D3D3')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(daily_table)

    try:
        doc.build(story)
        print(f"Summary PDF report successfully written to: {output_path}")
    finally:
        # 清理临时折线图文件
        if chart_img_path and os.path.exists(chart_img_path):
            try:
                os.remove(chart_img_path)
            except Exception as e:
                print(f"⚠ 清理临时折线图文件失败: {e}")

