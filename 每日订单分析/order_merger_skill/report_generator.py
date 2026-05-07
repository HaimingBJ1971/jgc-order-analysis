"""
Markdown报告生成模块 - 仅订单数据
"""
from datetime import datetime

from item_report_helpers import iter_subsections_for_report


def generate_markdown_report(group_sum, group_items, stats, items_df, output_path):
    """
    生成Markdown格式的客单价分析报告（仅订单数据）
    
    Args:
        group_sum: 聚合后的消费团体DataFrame
        group_items: 包含商品明细的消费团体字典
        stats: 统计信息字典
        items_df: 商品DataFrame
        output_path: 输出文件路径
    """
    md_lines = []
    
    # 标题
    report_date = datetime.now().strftime("%Y-%m-%d")
    md_lines.append(f"# 订单列表\n")
    md_lines.append(f"**生成日期**: {report_date}\n\n")
    md_lines.append(f"**报告说明**: 按桌台排序，同桌台按下单时间从早到晚展示消费团体\n\n")
    md_lines.append("---\n\n")

    _gs = group_sum.copy()
    _gs["人均排序名次"] = (
        _gs["人均消费"].rank(method="min", ascending=False).astype(int)
    )
    display_df = _gs.sort_values(["桌台", "开始"]).reset_index(drop=True)

    # 前置索引：方便快速按人均查询
    md_lines.append("## 订单索引（按桌台与时间）\n\n")
    md_lines.append(
        "| 索引 | 桌台 | 首单订单号 | 下单时间 | 就餐人数 | 菜品数量 | 被合并的订单号 | 订单总金额 | 人均 | 人均排序 |\n"
    )
    md_lines.append(
        "|------|------|------------|----------|----------|----------|----------------|------------|------|----------|\n"
    )
    for idx, row in display_df.iterrows():
        items_df_group = group_items.get((row["桌台"], row["消费团体ID"]))
        dish_qty = 0
        if items_df_group is not None and len(items_df_group) > 0:
            dish_qty = int(items_df_group["数量"].fillna(0).sum())
        arpu = f"¥{row['人均消费']:.2f}"
        if row["人均消费"] < 100:
            arpu = f"<span style='color:red'><strong>{arpu}</strong></span>"
        merged_order_ids = [
            str(oid) for oid in row["包含订单"] if str(oid) != str(row["首单订单号"])
        ]
        merged_order_text = ", ".join(merged_order_ids) if merged_order_ids else "-"
        total_amt = f"¥{row['团体总额']:.2f}"
        rk = int(row["人均排序名次"])
        arpu_rank_desc = f"第{rk}名"
        md_lines.append(
            f"| {idx + 1} | {row['桌台']} | {row['首单订单号']} | "
            f"{row['开始'].strftime('%Y-%m-%d %H:%M:%S')} | {int(row['团体人数'])} | {dish_qty} | {merged_order_text} | {total_amt} | {arpu} | {arpu_rank_desc} |\n"
        )
    md_lines.append("\n---\n\n")
    
    # 遍历每个消费团体
    for idx, row in display_df.iterrows():
        table = row["桌台"]
        group_id = row["消费团体ID"]
        rank = idx + 1
        
        # 会话标题
        md_lines.append(f"## {rank}. 桌台: {table} (消费团体ID: {group_id})\n\n")
        
        # 基本信息
        md_lines.append("### 基本信息\n\n")
        md_lines.append("| 项目 | 内容 |\n")
        md_lines.append("|------|------|\n")
        md_lines.append(f"| 首单订单号 | {row['首单订单号']} |\n")
        
        if row["订单数"] > 1:
            md_lines.append(f"| 主单订单号 | {row['主单订单号']} |\n")
        
        md_lines.append(f"| 下单时间 | {row['开始'].strftime('%Y-%m-%d %H:%M:%S')} |\n")
        md_lines.append(f"| 结账时间 | {row['结束'].strftime('%Y-%m-%d %H:%M:%S')} |\n")
        md_lines.append(f"| 客人数 | {int(row['团体人数'])} 人 |\n")
        md_lines.append(f"| 总金额 | ¥{row['团体总额']:.2f} |\n")
        md_lines.append(f"| 订单收入 | ¥{row['订单收入']:.2f} |\n")
        md_lines.append(f"| **人均消费** | **¥{row['人均消费']:.2f}** |\n")
        md_lines.append(f"| 合并订单数 | {int(row['订单数'])} 单 |\n")
        md_lines.append("\n")
        
        # 包含的订单号
        if row["订单数"] > 1:
            md_lines.append("**包含的订单号**:\n")
            for order_id in row["包含订单"]:
                md_lines.append(f"- {order_id}\n")
            md_lines.append("\n")
            md_lines.append("**子订单下单时间**:\n")
            for oid, otime in row.get("子订单下单时间", []):
                time_str = otime.strftime("%Y-%m-%d %H:%M:%S") if hasattr(otime, "strftime") else str(otime)
                md_lines.append(f"- {oid}: {time_str}\n")
            md_lines.append("\n")
        
        # 商品明细（多笔合并时按原订单号分块，便于人工复核）
        md_lines.append("### 商品明细\n\n")
        if int(row["订单数"]) > 1:
            md_lines.append(
                "*以下为按原订单号分列的菜品；合并判定如有疑义可对照子订单核对。*\n\n"
            )

        items_df_group = group_items.get((table, group_id))
        merged_multi = int(row["订单数"]) > 1

        if items_df_group is not None and len(items_df_group) > 0:
            subs = list(
                iter_subsections_for_report(
                    items_df_group, row["包含订单"], merged_multi
                )
            )
            if not subs:
                md_lines.append("*暂无商品明细*\n")
            else:
                for label, sub_df in subs:
                    if label is not None:
                        md_lines.append(f"#### 子订单 `{label}`\n\n")
                    md_lines.append(
                        "| 序号 | 商品名称 | 规格 | 单价 | 数量 | 金额 | 商品中类 |\n"
                    )
                    md_lines.append(
                        "|------|----------|------|------|------|------|----------|\n"
                    )
                    for j, (_, item_row) in enumerate(sub_df.iterrows(), start=1):
                        item_name = str(item_row["商品名称"]).replace("|", "\\|")
                        spec = str(item_row["规格"]).replace("|", "\\|")
                        category = str(item_row["商品中类"]).replace("|", "\\|")
                        md_lines.append(
                            f"| {j} | {item_name} | {spec} | "
                            f"¥{item_row['单价']:.2f} | {int(item_row['数量'])} | "
                            f"¥{item_row['菜品合计金额']:.2f} | {category} |\n"
                        )
                    md_lines.append("\n")
        else:
            md_lines.append("*暂无商品明细*\n")
        
        md_lines.append("\n")
        md_lines.append("---\n\n")
    
    # 写入文件
    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(md_lines)
    
    print(f"报告已生成: {output_path}")
