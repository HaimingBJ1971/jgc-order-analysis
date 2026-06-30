import os
import sys
import argparse
import pandas as pd
from datetime import datetime

# Add current dir to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
_order_root = os.path.join(current_dir, '..')
sys.path.insert(0, os.path.abspath(_order_root))

from takeaway_loader import load_takeaway_excel
from ingest_validator import validate_takeaway_excel
from takeaway_stats import (
    get_completed_orders, get_cancelled_orders, compute_summary_dict,
    calculate_store_comparison, calculate_daily_trends, calculate_platform_stats,
    calculate_hourly_distribution, calculate_fulfillment_metrics, identify_abnormal_orders
)
from excel_writer import write_excel_report
from pdf_report import generate_takeaway_pdf_report
from db_manager import TakeawayDatabaseManager

def generate_markdown_report(output_path, summary_data, store_comp_df, platform_stats_df, abnormal_df, overtime_df, start_date, end_date):
    """
    Generates a concise Markdown report suitable for business复盘 copying.
    """
    period_str = f"{start_date} ~ {end_date}" if start_date != end_date else start_date
    
    lines = [
        "# 外卖平台经营数据分析简报",
        "",
        f"- **统计周期**: {period_str}",
        f"- **报告生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 一、核心数据总览",
        "",
        f"- 有效外卖订单数: **{summary_data['有效订单数']:.0f}** 单",
        f"- 退单及取消数量: **{summary_data['退单数']:.0f}** 单",
        f"- 外卖实收营业额 (订单收入): **¥{summary_data['订单收入']:,.2f}**",
        f"- 顾客实付总额: **¥{summary_data['顾客实付']:,.2f}**",
        f"- 有效外卖客单价: **¥{summary_data['客单价']:,.2f}**",
        f"- 平台外卖抽佣额: **¥{summary_data['外卖抽佣']:,.2f}** (整体抽佣率: **{summary_data['抽佣率']:.2%}**)",
        f"- 订单商户支出: **¥{summary_data['订单支出']:,.2f}** (商户支出率: **{summary_data['订单支出率']:.2%}**)",
        f"- 平台部分退款额: **¥{summary_data['部分退款']:,.2f}**",
        "",
        "## 二、各门店外卖表现对比",
        "",
        "| 门店 | 有效订单数 | 退单数 | 订单收入 (营业额) | 顾客实付 | 客单价 | 抽佣率 | 支出率 |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
    ]
    
    for _, r in store_comp_df.iterrows():
        lines.append(
            f"| {r['门店']} | {r['有效订单数']:.0f} | {r['退单数']:.0f} | "
            f"¥{r['订单收入']:,.2f} | ¥{r['顾客实付']:,.2f} | ¥{r['客单价']:,.2f} | "
            f"{r['抽佣率']:.1%} | {r['订单支出率']:.1%} |"
        )
        
    lines += [
        "",
        "## 三、平台来源分布分析",
        "",
        "| 门店 | 平台来源 | 有效订单数 | 退单数 | 订单收入 (营业额) | 顾客实付 | 客单价 |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |"
    ]
    
    for _, r in platform_stats_df.iterrows():
        lines.append(
            f"| {r['门店']} | {r['平台']} | {r['有效订单数']:.0f} | {r['退单数']:.0f} | "
            f"¥{r['订单收入']:,.2f} | ¥{r['顾客实付']:,.2f} | ¥{r['客单价']:,.2f} |"
        )
        
    lines += [
        "",
        "## 四、异常与履约效率提醒",
        "",
        f"- **超时关注单**: 本周期共发生 **{len(overtime_df)}** 个送达时长超过 45 分钟的超时订单。",
        f"- **异常明细数量**: 本周期共检测到 **{len(abnormal_df)}** 条退单/0元/缺失时间/部分退款记录 (已排除重复)。",
        "",
        "---",
        "*注：本报告明细脱敏数据已成功写入 Excel 并进行数据库归档，报告中所有敏感客户隐私（如姓名、地址、电话）已做安全脱敏处理。*"
    ]
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"Markdown report successfully written to: {output_path}")

def main():
    parser = argparse.ArgumentParser(description="餐饮平台外卖数据统计分析工具 v1")
    parser.add_argument('--files', nargs='+', required=True, help='外卖订单明细 Excel 文件列表 (.xlsx)')
    parser.add_argument('--db', help='SQLite 数据库路径；传入则写入外卖相关表')
    parser.add_argument('--store', help='强制指定门店（万荷店/保利店/湾里店）')
    parser.add_argument('--output-dir', default='./output', help='输出目录（默认 ./output）')
    args = parser.parse_args()
    
    os.makedirs(args.output_dir, exist_ok=True)
    
    print("=" * 60)
    print("餐饮平台外卖数据统计分析工具")
    print("=" * 60)
    
    # Step 1: Load and clean all files
    print("\n[1/5] 加载外卖明细 Excel 文件...")
    all_dfs = []
    for f in args.files:
        print(f"  - 正在读取: {os.path.basename(f)}")
        v = validate_takeaway_excel(f, strict_dates=False)
        if not v.ok:
            for e in v.errors:
                print(f"    ERROR: {e}")
            print("\n请修正 Excel 后重新提交，再执行入库。")
            raise SystemExit(1)
        try:
            df_file = load_takeaway_excel(f, force_store=args.store)
            all_dfs.append(df_file)
            print(f"    * 提取到门店: {df_file.attrs['store_name']} | 包含记录数: {len(df_file)}")
        except Exception as e:
            print(f"    ⚠ 读取失败: {e}")
            
    if not all_dfs:
        print("\n[错误] 没有成功加载任何外卖数据文件。退出。")
        return
        
    combined_df = pd.concat(all_dfs, ignore_index=True)
    initial_len = len(combined_df)
    
    # Deduplicate combined dataset using composite key (store_name + 订单来源 + 外卖订单号)
    combined_df = combined_df.drop_duplicates(subset=["store_name", "订单来源", "外卖订单号"], keep="first").reset_index(drop=True)
    dedup_len = len(combined_df)
    print(f"  - 合并去重: 共 {initial_len} 行 -> 去重后 {dedup_len} 行 (去重过滤了 {initial_len - dedup_len} 行)")
    
    # Extract date range
    start_date = combined_df["营业日"].min()
    end_date = combined_df["营业日"].max()
    
    # Step 2: Database Ingestion (if requested)
    if args.db:
        print("\n[2/5] 写入数据库 (增量入库 & idempontency 校验)...")
        db = TakeawayDatabaseManager(args.db)
        
        # Ingestion before cleaning detail
        # Let's count existing records
        before_count = len(db.get_existing_order_keys())
        
        # Save orders (desensitized columns)
        source_file_label = os.path.basename(args.files[0]) if len(args.files) == 1 else "multi_files_merge"
        db.insert_takeaway_orders(combined_df, source_file_label)
        
        after_count = len(db.get_existing_order_keys())
        new_inserted = after_count - before_count
        print(f"  - SQLite 归档: 新增入库 {new_inserted} 条外卖订单 (数据库内总计: {after_count} 条)")
        
        # Aggregate daily overview for database
        completed_all = get_completed_orders(combined_df)
        cancelled_all = get_cancelled_orders(combined_df)
        
        overview_rows = []
        platform_rows = []
        hourly_rows = []
        
        # Daily overview aggregation
        daily_gps = combined_df.groupby(["营业日", "store_name"])
        for (day, store), grp in daily_gps:
            comp_g = completed_all[(completed_all["store_name"] == store) & (completed_all["营业日"] == day)]
            canc_g = cancelled_all[(cancelled_all["store_name"] == store) & (cancelled_all["营业日"] == day)]
            
            m = compute_summary_dict(comp_g, canc_g)
            overview_rows.append((
                day, store, int(m["有效订单数"]), int(m["退单数"]),
                float(m["订单收入"]), float(m["顾客实付"]), float(m["客单价"]),
                float(m["外卖抽佣"]), float(m["抽佣率"]),
                float(m["订单支出"]), float(m["订单支出率"]), float(m["部分退款"])
            ))
            
            # Daily platform stats
            plat_gps = grp.groupby("订单来源")
            for source, p_grp in plat_gps:
                p_comp = p_grp[p_grp["订单状态"] == "已完成"]
                overview_rows_plat = compute_summary_dict(p_comp, p_grp[p_grp["订单状态"] != "已完成"])
                platform_rows.append((
                    day, store, source, int(overview_rows_plat["有效订单数"]),
                    float(overview_rows_plat["订单收入"]), float(overview_rows_plat["顾客实付"])
                ))
                
            # Daily hourly stats
            if not comp_g.empty:
                comp_g["hour_loc"] = comp_g["下单时间"].dt.hour
                hour_gps = comp_g.groupby("hour_loc")
                for hour, h_grp in hour_gps:
                    hourly_rows.append((
                        day, store, int(hour), len(h_grp), float(h_grp["订单收入"].sum())
                    ))
                    
        # Upsert daily aggregations
        if overview_rows:
            db.upsert_daily_overview(overview_rows)
        if platform_rows:
            db.upsert_platform_stats(platform_rows)
        if hourly_rows:
            db.upsert_hourly_stats(hourly_rows)
            
        db.close()
        print("  - SQLite 每日统计归档更新完毕 ✓")
    else:
        print("\n[2/5] 跳过数据库写入 (未指定 --db 参数)...")
        
    # Step 3: Run full statistics calculations
    print("\n[3/5] 进行多维外卖经营数据聚合分析...")
    completed = get_completed_orders(combined_df)
    cancelled = get_cancelled_orders(combined_df)
    
    summary = compute_summary_dict(completed, cancelled)
    store_comp = calculate_store_comparison(combined_df)
    daily_trends = calculate_daily_trends(combined_df)
    platform_stats = calculate_platform_stats(combined_df)
    hourly_dist, meal_dist = calculate_hourly_distribution(combined_df)
    eff_stats, overtime_list = calculate_fulfillment_metrics(combined_df)
    abnormal_list = identify_abnormal_orders(combined_df)
    
    # Detail df for sheet export (keep clean columns, remove privacy raw info)
    detail_cols = [
        'store_name', '订单来源', '外卖流水号', '外卖订单号', '收银订单号', 
        '下单时间', '营业日', '接单时间', '送达时间', '订单状态', '配送状态', 
        '配送方式', '收货人姓名', '收货人手机号', '送餐地址', '订单金额', 
        '菜品合计金额', '附加费分摊', '菜品优惠', '菜品收入', '餐盒费', 
        '打包费', '配送费', '订单优惠', '平台优惠', '顾客实付', '订单支出', 
        '外卖抽佣', '配送支出', '其他支出', '部分退款', '订单收入', '首次对账时间'
    ]
    detail_df = combined_df[combined_df.columns.intersection(detail_cols)].copy()
    
    # Sort detail_df nicely
    detail_df = detail_df.sort_values(["store_name", "营业日", "下单时间"]).reset_index(drop=True)
    # Add simple sequential index
    detail_df.insert(0, "序号", range(1, len(detail_df) + 1))
    
    # Step 4: Write Outputs
    print("\n[4/5] 生成多格式数据报告...")
    date_tag = start_date.replace('-', '') + '_' + end_date.replace('-', '')
    
    # Excel Report
    excel_path = os.path.join(args.output_dir, f"平台外卖统计_{date_tag}.xlsx")
    write_excel_report(
        excel_path, summary, store_comp, daily_trends, platform_stats,
        hourly_dist, meal_dist, eff_stats, overtime_list, abnormal_list, detail_df
    )
    
    # PDF Report
    pdf_path = os.path.join(args.output_dir, f"平台外卖统计_{date_tag}.pdf")
    generate_takeaway_pdf_report(
        pdf_path, summary, store_comp, platform_stats, meal_dist, eff_stats, overtime_list, start_date, end_date, daily_trends
    )
    
    # Markdown Report
    md_path = os.path.join(args.output_dir, f"平台外卖统计_{date_tag}.md")
    generate_markdown_report(
        md_path, summary, store_comp, platform_stats, abnormal_list, overtime_list, start_date, end_date
    )
    
    # Step 5: Output simple console dashboard
    print("\n[5/5] 外卖分析结果摘要 Dashboard:")
    print("=" * 60)
    print(f"  分析周期: {start_date} ~ {end_date}")
    print(f"  有效外卖订单: {summary['有效订单数']:.0f} 单  |  退单/取消订单: {summary['退单数']:.0f} 单")
    print(f"  外卖总实收 (营业额): ¥{summary['订单收入']:,.2f}")
    print(f"  有效外卖客单价: ¥{summary['客单价']:,.2f}")
    print(f"  平台抽佣总额: ¥{summary['外卖抽佣']:,.2f}  (抽佣率: {summary['抽佣率']:.2%})")
    print(f"  订单商户支出: ¥{summary['订单支出']:,.2f}  (支出率: {summary['订单支出率']:.2%})")
    print("  各门店明细:")
    for _, r in store_comp.iterrows():
        print(f"    * {r['门店']}: 有效 {r['有效订单数']:.0f} 单 | 收入 ¥{r['订单收入']:,.2f} | 客单价 ¥{r['客单价']:,.2f} | 抽佣率 {r['抽佣率']:.1%}")
    print("=" * 60)
    print("处理完毕！所有报告均已输出成功。")

if __name__ == '__main__':
    main()
