"""
PDF报告生成模块 - 客单价分析报告（最高/最低3个订单）
"""
import re
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from item_report_helpers import iter_subsections_for_report


# 注册中文字体
def register_chinese_font():
    """注册系统中的中文字体"""
    import sys
    import os
    font_paths = []
    
    # 1. macOS Paths
    font_paths.extend([
        ('/System/Library/Fonts/STHeiti Light.ttc', 0),
        ('/System/Library/Fonts/STHeiti Medium.ttc', 0),
        ('/System/Library/Fonts/PingFang.ttc', 0),
        ('/System/Library/Fonts/STHeiti Light.ttc', 1),
        ('/System/Library/Fonts/STHeiti Medium.ttc', 1)
    ])
    
    # 2. Windows Paths
    if sys.platform.startswith('win'):
        windir = os.environ.get('WINDIR', 'C:\\Windows')
        font_paths.extend([
            (os.path.join(windir, 'Fonts', 'msyh.ttc'), 0),      # Microsoft YaHei
            (os.path.join(windir, 'Fonts', 'msyhbd.ttc'), 0),    # Microsoft YaHei Bold
            (os.path.join(windir, 'Fonts', 'simsun.ttc'), 0),    # SimSun
            (os.path.join(windir, 'Fonts', 'simhei.ttf'), None), # SimHei
        ])
    else:
        font_paths.extend([
            ('C:\\Windows\\Fonts\\msyh.ttc', 0),
            ('C:\\Windows\\Fonts\\simsun.ttc', 0),
            ('C:\\Windows\\Fonts\\simhei.ttf', None),
        ])
        
    # 3. Linux Paths
    font_paths.extend([
        ('/usr/share/fonts/truetype/wqy/wqy-microhei.ttc', 0),
        ('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc', 0),
        ('/usr/share/fonts/fonts-go/Go-Medium.ttf', None),
        ('/usr/share/fonts/truetype/droid/DroidSansFallback.ttf', None),
        ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 0),
        ('/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc', 0),
        ('/usr/share/fonts/wqy-microhei/wqy-microhei.ttc', 0),
    ])
    
    font_registered = False
    for font_path, subfont_index in font_paths:
        if not os.path.exists(font_path):
            continue
        try:
            font_name = f'ChineseFont_{subfont_index}' if subfont_index is not None else 'ChineseFont'
            if 'ttc' in font_path.lower() and subfont_index is not None:
                # 对于TTC字体，指定子字体索引
                pdfmetrics.registerFont(TTFont(font_name, font_path, subfontIndex=subfont_index))
            else:
                pdfmetrics.registerFont(TTFont(font_name, font_path))
            print(f"成功注册字体: {font_name} from {font_path}")
            font_registered = True
            return font_name
        except Exception as e:
            print(f"尝试注册字体失败 {font_path} (index={subfont_index}): {e}")
            continue
    
    if not font_registered:
        print("警告: 无法找到中文字体，将使用默认字体")
        return 'Helvetica'
    
    return 'ChineseFont_0'


CHINESE_FONT = register_chinese_font()


def generate_pdf_report(group_sum, group_items, items_df, stats, output_path):
    """
    生成PDF格式的客单价分析报告（最高/最低3个订单）
    
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
    
    # 标题
    report_date = datetime.now().strftime("%Y-%m-%d")
    story.append(Paragraph("客单价分析报告", title_style))
    story.append(Paragraph(f"生成日期: {report_date}", normal_style))
    story.append(Paragraph("用途: 供前厅经营团队完整数据分析", normal_style))
    story.append(Spacer(1, 1*cm))
    
    # 添加总结章节
    add_summary_section(story, subtitle_style, normal_style, group_sum, items_df, stats)
    story.append(PageBreak())
    
    # 显式按人均消费排序，避免受其他展示顺序影响
    ranked = group_sum.sort_values("人均消费", ascending=False).reset_index(drop=True)
    top3 = ranked.head(3).copy()
    bottom3 = ranked.tail(3).copy()
    bottom3 = bottom3.iloc[::-1].copy()  # 反转，使最低的在最前面
    
    # 添加客单价最高的3个订单
    story.append(Paragraph("七、客单价最高的3个订单", subtitle_style))
    story.append(Spacer(1, 0.3*cm))
    
    for idx, row in top3.iterrows():
        add_order_section(story, normal_style, row, group_items, idx+1, is_top=True)
        if idx < 2:
            story.append(PageBreak())
    
    story.append(PageBreak())
    
    # 添加客单价最低的3个订单
    story.append(Paragraph("八、客单价最低的3个订单", subtitle_style))
    story.append(Spacer(1, 0.3*cm))
    
    for idx, row in bottom3.iterrows():
        add_order_section(story, normal_style, row, group_items, idx+1, is_top=False)
        if idx < 2:
            story.append(PageBreak())
    
    # 添加分析建议
    story.append(PageBreak())
    add_analysis_suggestions(story, subtitle_style, normal_style)
    
    # 生成PDF
    doc.build(story)
    print(f"PDF报告已生成: {output_path}")


def add_order_section(story, normal_style, row, group_items, rank, is_top=True):
    """
    添加单个订单的章节到PDF
    
    Args:
        story: PDF故事列表
        normal_style: 普通文本样式
        row: 订单数据行
        group_items: 商品明细字典
        rank: 排名
        is_top: 是否为最高订单
    """
    table = row["桌台"]
    group_id = row["消费团体ID"]
    
    # 子标题样式
    section_title_style = ParagraphStyle(
        'SectionTitle',
        parent=normal_style,
        fontSize=12,
        textColor=colors.darkgreen if is_top else colors.darkorange,
        spaceBefore=10,
        spaceAfter=8,
        fontName=CHINESE_FONT,
        leading=14
    )
    
    # 章节标题
    title_text = f"{rank}. 桌台: {table} (消费团体ID: {group_id})"
    story.append(Paragraph(title_text, section_title_style))
    
    # 基本信息数据
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
    
    # 包含的订单号
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
    
    # 商品明细（多笔合并时按原订单分列）
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

    items_df = group_items.get((table, group_id))
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

    if items_df is not None and len(items_df) > 0:
        subs = list(
            iter_subsections_for_report(
                items_df, row["包含订单"], merged_multi
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


def add_analysis_suggestions(story, subtitle_style, normal_style):
    """
    添加分析建议部分
    
    Args:
        story: PDF故事列表
        subtitle_style: 副标题样式
        normal_style: 普通文本样式
    """
    suggestions_title_style = ParagraphStyle(
        'SuggestionsTitle',
        parent=subtitle_style,
        fontSize=14,
        textColor=colors.darkblue,
        spaceBefore=15,
        spaceAfter=10,
        fontName=CHINESE_FONT
    )
    
    story.append(Paragraph("九、经营团队分析建议", suggestions_title_style))
    story.append(Spacer(1, 0.3*cm))
    
    suggestions = [
        "1. 针对客单价最高的订单：",
        "   - 分析这些订单的菜品构成，识别高毛利/高价值菜品",
        "   - 研究客群特征（桌台类型、就餐人数、支付方式）",
        "   - 总结成功经验，考虑推出类似的套餐或推荐组合",
        "",
        "2. 针对客单价最低的订单：",
        "   - 分析菜品构成，识别是否存在单点低价菜品的情况",
        "   - 检查服务员的推荐话术和技巧",
        "   - 考虑设计引导消费的策略（如加菜推荐、饮品搭配）",
        "",
        "3. 通用改进建议：",
        "   - 培训服务员的销售技巧，提高客单价意识",
        "   - 优化菜单设计，突出高价值菜品",
        "   - 设计合理的套餐组合，增加人均消费",
        "   - 定期分析数据，持续优化经营策略"
    ]
    
    for suggestion in suggestions:
        if suggestion:
            story.append(Paragraph(suggestion, normal_style))
        else:
            story.append(Spacer(1, 0.2*cm))


def add_summary_section(story, subtitle_style, normal_style, group_sum, items_df, stats):
    """
    添加总结章节到PDF
    
    Args:
        story: PDF故事列表
        subtitle_style: 副标题样式
        normal_style: 普通文本样式
        group_sum: 聚合后的消费团体DataFrame
        items_df: 商品DataFrame
        stats: 统计信息字典
    """
    story.append(Paragraph("一、数据总览", subtitle_style))
    story.append(Spacer(1, 0.3*cm))
    
    # 1. 统计范围内总营业额、消费总人数、人均消费
    total_revenue = stats["统计范围内总营业额"]
    total_people = stats["统计范围内消费总人数"]
    avg_per_person = total_revenue / total_people if total_people > 0 else 0
    
    summary_data = [
        ["指标", "数值"],
        ["统计范围内总营业额", f"¥{total_revenue:.2f}"],
        ["统计范围内消费总人数", f"{int(total_people)} 人"],
        ["整体人均消费", f"¥{avg_per_person:.2f}"]
    ]
    
    summary_table = Table(summary_data, colWidths=[5*cm, 6*cm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white])
    ]))
    
    story.append(summary_table)
    story.append(Spacer(1, 0.5*cm))
    
    # 订单数量明细
    story.append(Paragraph("二、订单数量明细", subtitle_style))
    story.append(Spacer(1, 0.3*cm))
    
    order_detail_data = [
        ["项目", "数量"],
        ["原始订单数", str(stats["原始订单数"])],
        ["- 被合并的订单数", str(stats["被合并的订单数"])],
        ["- 零食购买订单数", str(stats["零食购买订单数"])],
        ["- 零散小单订单数", str(stats.get("零散小单订单数", 0))],
        ["- 免单消费订单数", str(stats["免单消费订单数"])],
        ["= 统计订单数", str(stats["统计订单数"])]
    ]
    
    order_detail_table = Table(order_detail_data, colWidths=[5*cm, 6*cm])
    order_detail_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.whitesmoke, colors.white]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
        ('FONTWEIGHT', (0, -1), (-1, -1), 'BOLD')
    ]))
    
    story.append(order_detail_table)
    story.append(Spacer(1, 0.5*cm))
    
    # 计算公式说明
    formula_style = ParagraphStyle(
        'Formula',
        parent=normal_style,
        fontSize=9,
        textColor=colors.darkgrey,
        leading=12
    )
    
    story.append(Paragraph("<b>计算公式说明：</b>", normal_style))
    story.append(
        Paragraph(
            "统计订单数 = 原始订单数 - 被合并的订单数 - 零食购买订单数 - 零散小单订单数 - 免单消费订单数",
            formula_style,
        )
    )
    story.append(Spacer(1, 0.5*cm))
    
    # 三、客单价区间分布
    story.append(Paragraph("三、客单价区间分布", subtitle_style))
    story.append(Spacer(1, 0.3*cm))
    
    total_orders = len(group_sum)
    
    # 计算各区间订单数
    range_300_plus = len(group_sum[group_sum["人均消费"] >= 300])
    range_200_300 = len(group_sum[(group_sum["人均消费"] >= 200) & (group_sum["人均消费"] < 300)])
    range_150_200 = len(group_sum[(group_sum["人均消费"] >= 150) & (group_sum["人均消费"] < 200)])
    range_100_150 = len(group_sum[(group_sum["人均消费"] >= 100) & (group_sum["人均消费"] < 150)])
    range_below_100 = len(group_sum[group_sum["人均消费"] < 100])
    
    # 计算百分比
    def calc_pct(count):
        return f"{count / total_orders * 100:.1f}%" if total_orders > 0 else "0.0%"
    
    range_data = [
        ["客单价区间", "订单数", "占比"],
        ["300元以上", str(range_300_plus), calc_pct(range_300_plus)],
        ["200~300元", str(range_200_300), calc_pct(range_200_300)],
        ["150~200元", str(range_150_200), calc_pct(range_150_200)],
        ["100~150元", str(range_100_150), calc_pct(range_100_150)],
        ["100元以下", str(range_below_100), calc_pct(range_below_100)],
        ["合计", str(total_orders), "100.0%"]
    ]
    
    range_table = Table(range_data, colWidths=[3.5*cm, 2.5*cm, 3*cm])
    range_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.whitesmoke, colors.white]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
        ('FONTWEIGHT', (0, -1), (-1, -1), 'BOLD')
    ]))
    
    story.append(range_table)
    story.append(Spacer(1, 0.5*cm))
    
    # 五、重点菜品销售统计
    story.append(Paragraph("五、重点菜品销售统计", subtitle_style))
    story.append(Spacer(1, 0.3*cm))
    
    # 需要统计的菜品列表
    target_dishes = [
        "富顺鸡丝凉面",
        "古法干烧鱼(江团)",
        "古法干烧鱼(鲈鱼)",
        "富顺荤豆花",
        "206省道半汤牛蛙",
        "酸菜煸炒土豆片",
        "香菜回锅茄子",
        "火爆腰花",
        "宫保鸡腿肉丁",
        "炝炒莲花白菜",
        "血皮菜炒猪肝",
        "金阳青花椒辣子鸡",
        "鱼香梅花肉丝",
        "文庙担担面",
        "茂萱婆婆芽菜包",
        "板命街夜市醪糟小汤圆"
    ]
    
    # 模糊匹配统计
    dish_stats = []
    
    # 先一次性规范化所有商品名称
    items_df_copy = items_df.copy()
    items_df_copy["商品名称_规范化"] = items_df_copy["商品名称"].astype(str).apply(
        lambda x: x.replace('（', '(').replace('）', ')')
    )
    
    for target_dish in target_dishes:
        # 规范化目标菜品名称
        normalized_target = target_dish.replace('（', '(').replace('）', ')')
        
        # 尝试直接匹配规范化后的名称
        matched = items_df_copy[items_df_copy["商品名称_规范化"].str.contains(normalized_target, na=False, case=False, regex=False)]
        
        # 如果没找到，尝试关键词匹配（去掉括号内容）
        if len(matched) == 0:
            keyword = re.sub(r'[（(].*?[）)]', '', target_dish).strip()
            if keyword:
                matched = items_df_copy[items_df_copy["商品名称"].str.contains(keyword, na=False, case=False, regex=False)]
        
        total_qty = matched["数量"].sum() if len(matched) > 0 else 0
        dish_stats.append([target_dish, int(total_qty)])
    
    # 合并古法干烧鱼（江团）和古法干烧鱼（鲈鱼）
    gan_shao_jiangtuan_qty = 0
    gan_shao_luyu_qty = 0
    new_dish_stats = []
    
    for name, qty in dish_stats:
        if name == "古法干烧鱼(江团)":
            gan_shao_jiangtuan_qty = qty
        elif name == "古法干烧鱼(鲈鱼)":
            gan_shao_luyu_qty = qty
        else:
            new_dish_stats.append([name, qty])
    
    # 添加合并后的古法干烧鱼
    total_gan_shao_qty = gan_shao_jiangtuan_qty + gan_shao_luyu_qty
    new_dish_stats.append(["古法干烧鱼", total_gan_shao_qty])
    
    dish_stats = new_dish_stats
    
    # 按销售份数降序排序
    dish_stats_sorted = sorted(dish_stats, key=lambda x: x[1], reverse=True)
    
    # 转换为字符串格式
    dish_stats_final = [[name, str(qty)] for name, qty in dish_stats_sorted]
    
    dish_data = [["菜品名称", "销售份数"]] + dish_stats_final
    
    dish_table = Table(dish_data, colWidths=[7*cm, 3*cm])
    dish_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgreen),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white])
    ]))
    
    story.append(dish_table)
    story.append(Spacer(1, 0.5*cm))
    
    # 六、重点新品销售统计
    story.append(Paragraph("六、重点新品销售统计", subtitle_style))
    story.append(Spacer(1, 0.3*cm))
    
    # 需要统计的新品列表
    target_new_items = [
        "炝炒白菜苔",
        "酸菜腊肉煸春笋",
        "香椿炒鸡蛋",
        "干巴菌腊肉青豆焖饭",
        "肉沫豆汤豌豆尖",
        "凤梨洛神花果茶",
        "杨梅马蹄气泡水",
        "青花椒提拉米苏",
        "青花椒提拉米苏/杨梅马蹄",
        "青花椒提拉米苏/美式咖啡"
    ]
    
    # 模糊匹配统计新品
    new_item_stats = []
    
    for target_item in target_new_items:
        # 规范化目标商品名称
        normalized_target = target_item.replace('（', '(').replace('）', ')')
        
        # 尝试直接匹配规范化后的名称
        matched = items_df_copy[items_df_copy["商品名称_规范化"].str.contains(normalized_target, na=False, case=False, regex=False)]
        
        # 如果没找到，尝试关键词匹配
        if len(matched) == 0:
            matched = items_df_copy[items_df_copy["商品名称"].str.contains(target_item, na=False, case=False, regex=False)]
        
        total_qty = matched["数量"].sum() if len(matched) > 0 else 0
        new_item_stats.append([target_item, int(total_qty)])
    
    # 按销售份数降序排序
    new_item_stats_sorted = sorted(new_item_stats, key=lambda x: x[1], reverse=True)
    
    # 转换为字符串格式
    new_item_stats_final = [[name, str(qty)] for name, qty in new_item_stats_sorted]
    
    new_item_data = [["商品名称", "销售份数"]] + new_item_stats_final
    
    new_item_table = Table(new_item_data, colWidths=[7*cm, 3*cm])
    new_item_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightcoral),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white])
    ]))
    
    story.append(new_item_table)
    story.append(Spacer(1, 0.5*cm))
