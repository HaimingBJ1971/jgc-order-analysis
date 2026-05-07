"""
餐饮订单合并与客单价分析系统 - 主程序入口
"""
import os
import sys
from datetime import datetime

# 添加当前目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from data_loader import load_excel, clean_orders, clean_items, get_item_features
from order_merger import merge_orders
from aggregator import aggregate_groups, get_group_items
from report_generator import generate_markdown_report
from pdf_generator import generate_pdf_report
from pdf_generator_complete import generate_complete_pdf_report


def main(excel_file_path, output_dir=None, generate_pdf=True):
    """
    主函数
    
    Args:
        excel_file_path: Excel文件路径
        output_dir: 输出目录（可选）
        generate_pdf: 是否生成PDF报告（默认True）
    
    Returns:
        (markdown_file, pdf_file): 生成的文件路径元组
    """
    print("=" * 60)
    print("餐饮订单合并与客单价分析系统")
    print("=" * 60)
    
    # 设置输出目录
    if output_dir is None:
        output_dir = os.path.dirname(excel_file_path)
    
    # 生成输出文件名
    today = datetime.now().strftime("%Y-%m-%d")
    markdown_file = os.path.join(output_dir, f"订单列表_{today}.md")
    pdf_complete_file = os.path.join(output_dir, f"订单列表_{today}.pdf")
    pdf_highlight_file = os.path.join(output_dir, f"客单价重点订单分析_{today}.pdf")
    
    print(f"\n输入文件: {excel_file_path}")
    print(f"Markdown输出: {markdown_file}")
    if generate_pdf:
        print(f"PDF订单列表输出: {pdf_complete_file}")
        print(f"PDF重点订单分析输出: {pdf_highlight_file}")
    print("\n开始处理...")
    
    # Step 1: 加载Excel文件
    print("\n[1/7] 加载Excel文件...")
    orders_df, items_df = load_excel(excel_file_path)
    print(f"  - 订单表: {len(orders_df)} 行")
    print(f"  - 商品表: {len(items_df)} 行")
    
    # Step 2: 清洗数据
    print("\n[2/7] 清洗数据...")
    orders_clean = clean_orders(orders_df)
    items_clean = clean_items(items_df)
    # 仅保留仍参与统计的订单对应的商品行（与订单表一致，含剔除「外点自取」等）
    _valid_order_ids = set(orders_clean["订单号"].astype(str))
    items_clean = items_clean[
        items_clean["订单号"].astype(str).isin(_valid_order_ids)
    ].copy()
    print(f"  - 清洗后订单表: {len(orders_clean)} 行（仅堂食，不含外点自取外卖）")
    print(f"  - 清洗后商品表: {len(items_clean)} 行")
    
    # Step 3: 提取商品特征
    print("\n[3/7] 提取商品特征...")
    item_sets, line_cnts = get_item_features(items_clean)
    print(f"  - 涉及订单数: {len(item_sets)}")
    
    # Step 4: 合并订单
    print("\n[4/7] 识别并合并订单...")
    orders_with_group, groups = merge_orders(
        orders_clean, item_sets, line_cnts, items_clean
    )
    print(f"  - 消费团体数: {len(groups)}")
    
    # Step 5: 聚合数据
    print("\n[5/7] 聚合数据并计算客单价...")
    group_sum, stats = aggregate_groups(orders_with_group, items_clean)
    group_items = get_group_items(group_sum, items_clean)
    print(f"  - 聚合完成，统计订单数: {len(group_sum)}")
    
    # Step 6: 生成Markdown订单列表
    print("\n[6/8] 生成Markdown订单列表...")
    generate_markdown_report(group_sum, group_items, stats, items_clean, markdown_file)
    
    # Step 7: 生成PDF订单列表（如果需要）
    pdf_complete_output_path = None
    pdf_highlight_output_path = None
    if generate_pdf:
        print("\n[7/8] 生成PDF订单列表...")
        generate_complete_pdf_report(group_sum, group_items, items_clean, stats, pdf_complete_file)
        pdf_complete_output_path = pdf_complete_file
    
    # Step 8: 生成PDF重点订单分析报告（如果需要）
    if generate_pdf:
        print("\n[8/8] 生成PDF重点订单分析报告...")
        generate_pdf_report(group_sum, group_items, items_clean, stats, pdf_highlight_file)
        pdf_highlight_output_path = pdf_highlight_file
    
    print("\n" + "=" * 60)
    print("处理完成！")
    print("=" * 60)
    
    return markdown_file, pdf_complete_output_path, pdf_highlight_output_path


if __name__ == "__main__":
    # 默认使用示例文件
    excel_file = "/Users/jgc/Documents/每日订单分析/店内订单明细2026-03-30+00_00_00~2026-03-30+23_59_59.xlsx"
    
    # 如果命令行参数提供了文件路径，则使用该路径
    if len(sys.argv) > 1:
        excel_file = sys.argv[1]
    
    # 运行主程序，生成Markdown和PDF报告
    md_file, pdf_complete_file, pdf_highlight_file = main(excel_file)
    
    # 打印生成的文件路径
    print("\n生成的文件:")
    print(f"  - Markdown订单列表: {md_file}")
    if pdf_complete_file:
        print(f"  - PDF订单列表: {pdf_complete_file}")
    if pdf_highlight_file:
        print(f"  - PDF重点订单分析: {pdf_highlight_file}")
