"""
PDF报告生成模块 - 完整客单价分析报告（仅订单数据）
"""
from datetime import datetime
from html import escape as html_escape
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from item_report_helpers import iter_subsections_for_report


# 注册中文字体（复用现有的字体注册逻辑）
def register_chinese_font():
    """注册系统中的中文字体"""
    font_paths = [
        ('/System/Library/Fonts/STHeiti Light.ttc', 0),
        ('/System/Library/Fonts/STHeiti Medium.ttc', 0),
        ('/System/Library/Fonts/PingFang.ttc', 0),
        ('/System/Library/Fonts/STHeiti Light.ttc', 1),
        ('/System/Library/Fonts/STHeiti Medium.ttc', 1)
    ]
    
    font_registered = False
    for font_path, subfont_index in font_paths:
        try:
            font_name = f'ChineseFont_{subfont_index}'
            if 'ttc' in font_path.lower():
                pdfmetrics.registerFont(TTFont(font_name, font_path, subfontIndex=subfont_index))
            else:
                pdfmetrics.registerFont(TTFont(font_name, font_path))
            font_registered = True
            return font_name
        except Exception as e:
            continue
    
    if not font_registered:
        return 'Helvetica'
    
    return 'ChineseFont_0'


CHINESE_FONT = register_chinese_font()


def generate_complete_pdf_report(group_sum, group_items, items_df, stats, output_path):
    """
    生成PDF格式的完整客单价分析报告（仅订单数据）
    
    Args:
        group_sum: 聚合后的消费团体DataFrame
        group_items: 包含商品明细的消费团体字典
        items_df: 商品DataFrame
        stats: 统计信息字典
        output_path: 输出PDF文件路径
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # 自定义样式 - 使用中文字体
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=18,
        textColor=colors.darkblue,
        spaceAfter=20,
        fontName=CHINESE_FONT
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.darkred,
        spaceBefore=15,
        spaceAfter=10,
        fontName=CHINESE_FONT
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontName=CHINESE_FONT,
        fontSize=10
    )

    # 订单索引表用：单元格内自动换行、列宽有限时避免文字挤出
    index_header_para = ParagraphStyle(
        'IndexHeader',
        parent=normal_style,
        fontSize=8,
        leading=10,
        alignment=TA_CENTER,
    )
    index_cell_center = ParagraphStyle(
        'IndexCellCenter',
        parent=normal_style,
        fontSize=7,
        leading=9,
        alignment=TA_CENTER,
    )
    index_cell_left = ParagraphStyle(
        'IndexCellLeft',
        parent=normal_style,
        fontSize=7,
        leading=9,
        alignment=TA_LEFT,
    )

    # 标题
    report_date = datetime.now().strftime("%Y-%m-%d")
    story.append(Paragraph("订单列表", title_style))
    story.append(Paragraph(f"生成日期: {report_date}", normal_style))
    story.append(Paragraph("报告说明: 按桌台排序，同桌台按下单时间从早到晚展示消费团体", normal_style))
    story.append(Spacer(1, 1*cm))

    # 人均由高到低名次（并列同名次，method=min）；再按桌台+时间展示索引行
    _gs = group_sum.copy()
    _gs["人均排序名次"] = (
        _gs["人均消费"].rank(method="min", ascending=False).astype(int)
    )
    display_df = _gs.sort_values(["桌台", "开始"]).reset_index(drop=True)

    # 前置索引页：方便按人均快速定位
    story.append(Paragraph("订单索引（按桌台与时间）", subtitle_style))
    story.append(Spacer(1, 0.3 * cm))
    index_data = [[
        Paragraph("索引", index_header_para),
        Paragraph("桌台", index_header_para),
        Paragraph("首单订单号", index_header_para),
        Paragraph("下单时间", index_header_para),
        Paragraph("就餐人数", index_header_para),
        Paragraph("菜品数量", index_header_para),
        Paragraph("被合并的订单号", index_header_para),
        Paragraph("订单总金额", index_header_para),
        Paragraph("人均", index_header_para),
        Paragraph("人均排序", index_header_para),
    ]]
    for idx, row in display_df.iterrows():
        items_df_group = group_items.get((row["桌台"], row["消费团体ID"]))
        dish_qty = 0
        if items_df_group is not None and len(items_df_group) > 0:
            dish_qty = int(items_df_group["数量"].fillna(0).sum())
        merged_order_ids = [
            str(oid) for oid in row["包含订单"] if str(oid) != str(row["首单订单号"])
        ]
        if merged_order_ids:
            merged_lines = "<br/>".join(html_escape(oid) for oid in merged_order_ids)
            merged_cell = Paragraph(merged_lines, index_cell_left)
        else:
            merged_cell = Paragraph("-", index_cell_center)

        oid_tail = str(row["首单订单号"])[-8:]
        oid_para = Paragraph(html_escape(oid_tail), index_cell_center)
        table_name = html_escape(str(row["桌台"]))
        table_para = Paragraph(table_name.replace("\n", "<br/>"), index_cell_left)

        arpu_s = f"¥{row['人均消费']:.2f}"
        if row["人均消费"] < 100:
            arpu_cell = Paragraph(
                f'<font color="red">{html_escape(arpu_s)}</font>',
                index_cell_center,
            )
        else:
            arpu_cell = Paragraph(html_escape(arpu_s), index_cell_center)

        rk = int(row["人均排序名次"])
        rank_cell = Paragraph(f"第{rk}名", index_cell_center)

        index_data.append(
            [
                Paragraph(str(idx + 1), index_cell_center),
                table_para,
                oid_para,
                Paragraph(
                    html_escape(row["开始"].strftime("%m-%d %H:%M")),
                    index_cell_center,
                ),
                Paragraph(str(int(row["团体人数"])), index_cell_center),
                Paragraph(str(dish_qty), index_cell_center),
                merged_cell,
                Paragraph(
                    html_escape(f"¥{row['团体总额']:.2f}"),
                    index_cell_center,
                ),
                arpu_cell,
                rank_cell,
            ]
        )
    # A4 可用宽约 17cm（左右边距各 2cm）
    index_table = Table(
        index_data,
        colWidths=[
            0.75 * cm,
            2.2 * cm,
            1.75 * cm,
            1.65 * cm,
            1.0 * cm,
            1.0 * cm,
            4.65 * cm,
            1.3 * cm,
            1.3 * cm,
            1.2 * cm,
        ],
    )
    index_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
    ])
    index_table.setStyle(index_style)
    story.append(index_table)
    story.append(PageBreak())

    # 遍历每个消费团体
    for idx, row in display_df.iterrows():
        add_order_section(story, normal_style, subtitle_style, row, group_items, idx+1)
        if idx < len(display_df) - 1:
            story.append(PageBreak())
    
    # 生成PDF
    doc.build(story)
    print(f"完整PDF报告已生成: {output_path}")


def add_order_section(story, normal_style, subtitle_style, row, group_items, rank):
    """
    添加单个订单的章节到PDF
    """
    table = row["桌台"]
    group_id = row["消费团体ID"]
    
    section_title_style = ParagraphStyle(
        'SectionTitle',
        parent=subtitle_style,
        fontSize=12,
        spaceBefore=10,
        spaceAfter=8,
        fontName=CHINESE_FONT,
        leading=14
    )
    
    title_text = f"{rank}. 桌台: {table} (消费团体ID: {group_id})"
    story.append(Paragraph(title_text, section_title_style))
    
    basic_info_data = [
        ["项目", "内容"],
        ["首单订单号", str(row["首单订单号"])],
        ["下单时间", row["开始"].strftime("%Y-%m-%d %H:%M:%S")],
        ["结账时间", row["结束"].strftime("%Y-%m-%d %H:%M:%S")],
        ["客人数", f"{int(row['团体人数'])} 人"],
        ["总金额", f"¥{row['团体总额']:.2f}"],
        ["订单收入", f"¥{row['订单收入']:.2f}"],
        ["人均消费", f"¥{row['人均消费']:.2f}"],
        ["合并订单数", f"{int(row['订单数'])} 单"]
    ]
    
    if row["订单数"] > 1:
        basic_info_data.append(["主单订单号", str(row["主单订单号"])])
    
    basic_table = Table(basic_info_data, colWidths=[3*cm, 8*cm])
    basic_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white])
    ]))
    
    story.append(basic_table)
    story.append(Spacer(1, 0.5*cm))
    
    if row["订单数"] > 1:
        story.append(Paragraph("<b>包含的订单号:</b>", normal_style))
        order_list = ", ".join([str(oid) for oid in row["包含订单"]])
        story.append(Paragraph(order_list, normal_style))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("<b>子订单下单时间:</b>", normal_style))
        for oid, otime in row.get("子订单下单时间", []):
            time_str = (
                otime.strftime("%Y-%m-%d %H:%M:%S")
                if hasattr(otime, "strftime")
                else str(otime)
            )
            story.append(Paragraph(f"{oid}: {time_str}", normal_style))
        story.append(Spacer(1, 0.3 * cm))
    
    story.append(Paragraph("<b>商品明细:</b>", normal_style))
    merged_multi = int(row["订单数"]) > 1
    if merged_multi:
        story.append(
            Paragraph(
                "<i>以下按原订单号分列，便于核对合并是否合理。</i>",
                normal_style,
            )
        )
        story.append(Spacer(1, 0.2 * cm))

    items_df_group = group_items.get((table, group_id))
    _item_table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        (
            'ROWBACKGROUNDS',
            (0, 1),
            (-1, -1),
            [colors.whitesmoke, colors.white],
        ),
    ])
    col_widths = [1 * cm, 3.5 * cm, 1.2 * cm, 1.5 * cm, 1.5 * cm, 2.3 * cm]

    if items_df_group is not None and len(items_df_group) > 0:
        subs = list(
            iter_subsections_for_report(
                items_df_group, row["包含订单"], merged_multi
            )
        )
        if not subs:
            story.append(Paragraph("暂无商品明细", normal_style))
        else:
            for label, sub_df in subs:
                if label is not None:
                    story.append(Paragraph(f"<b>子订单: {label}</b>", normal_style))
                    story.append(Spacer(1, 0.15 * cm))
                item_data = [
                    ["序号", "商品名称", "数量", "单价", "金额", "商品中类"]
                ]
                for j, (_, item_row) in enumerate(sub_df.iterrows(), start=1):
                    item_data.append([
                        str(j),
                        str(item_row["商品名称"])[:20],
                        str(int(item_row["数量"])),
                        f"¥{item_row['单价']:.2f}",
                        f"¥{item_row['菜品合计金额']:.2f}",
                        str(item_row["商品中类"])[:15],
                    ])
                item_table = Table(item_data, colWidths=col_widths)
                item_table.setStyle(_item_table_style)
                story.append(item_table)
                story.append(Spacer(1, 0.3 * cm))
    else:
        story.append(Paragraph("暂无商品明细", normal_style))
    
    story.append(Spacer(1, 0.5*cm))
