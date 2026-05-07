"""
数据聚合与客单价计算模块
"""
import pandas as pd


def aggregate_groups(orders_with_group, items_df=None):
    """
    聚合消费团体数据
    
    Args:
        orders_with_group: 带消费团体ID的订单DataFrame
        items_df: 商品DataFrame（用于过滤，可选）
    
    Returns:
        (group_sum, stats): 聚合后的消费团体DataFrame和统计信息字典
    """
    # 收集统计信息
    stats = {}
    stats["原始订单数"] = len(orders_with_group)

    # 免单订单不参与订单列表（收入<=0 或缺失）
    paid_orders = orders_with_group[
        orders_with_group["订单收入"].notna() & (orders_with_group["订单收入"] > 0)
    ].copy()
    pre_filtered_free_count = len(orders_with_group) - len(paid_orders)
    stats["免单订单行数(已剔除)"] = pre_filtered_free_count
    # 对外展示口径：免单消费订单数（包含前置剔除）
    stats["免单消费订单数"] = pre_filtered_free_count
    
    # 基础聚合
    group_sum = (paid_orders.groupby(["桌台", "消费团体ID"])
                .agg(
                    团体总额=("订单金额", "sum"),
                    订单收入=("订单收入", "sum"),
                    订单数=("订单号", "count"),
                    开始=("下单时间", "min"),
                    结束=("结账时间", "max")
                )
                .reset_index())
    
    stats["合并后消费团体数"] = len(group_sum)
    # 仅在“有效付费订单”口径下统计被合并订单数，避免把免单剔除误计为合并
    stats["被合并的订单数"] = len(paid_orders) - stats["合并后消费团体数"]
    
    # 团体人数：优先取该团体"最高收入订单"的就餐人数
    idx = paid_orders.groupby(["桌台", "消费团体ID"])["订单收入"].idxmax()
    people = paid_orders.loc[idx, ["桌台", "消费团体ID", "就餐人数", "订单号"]].rename(
        columns={"就餐人数": "团体人数", "订单号": "主单订单号"}
    )
    group_sum = group_sum.merge(people, on=["桌台", "消费团体ID"], how="left")
    
    # 获取首单订单号
    first_order_idx = paid_orders.groupby(["桌台", "消费团体ID"])["下单时间"].idxmin()
    first_order = paid_orders.loc[first_order_idx, ["桌台", "消费团体ID", "订单号"]].rename(
        columns={"订单号": "首单订单号"}
    )
    group_sum = group_sum.merge(first_order, on=["桌台", "消费团体ID"], how="left")
    
    # 获取所有合并的订单号
    order_list = paid_orders.groupby(["桌台", "消费团体ID"])["订单号"].apply(list).reset_index()
    order_list = order_list.rename(columns={"订单号": "包含订单"})
    group_sum = group_sum.merge(order_list, on=["桌台", "消费团体ID"], how="left")

    # 获取子订单下单时间（用于报告人工复核）
    order_times = (
        paid_orders.sort_values("下单时间")
        .groupby(["桌台", "消费团体ID"])
        .apply(
            lambda x: [
                (str(r["订单号"]), r["下单时间"])
                for _, r in x[["订单号", "下单时间"]].iterrows()
            ]
        )
        .reset_index(name="子订单下单时间")
    )
    group_sum = group_sum.merge(order_times, on=["桌台", "消费团体ID"], how="left")
    
    # 计算人均消费
    group_sum["人均消费"] = group_sum["订单收入"] / group_sum["团体人数"]
    
    # 按人均消费降序排序
    group_sum = group_sum.sort_values("人均消费", ascending=False).reset_index(drop=True)
    
    # 过滤掉不符合条件的订单
    if items_df is not None:
        group_sum, filter_stats = filter_groups(group_sum, items_df)
        stats.update(filter_stats)
        # 叠加前置剔除的免单订单数，避免报表显示为0
        stats["免单消费订单数"] = (
            pre_filtered_free_count + stats.get("免单消费订单数", 0)
        )
    else:
        stats["零食购买订单数"] = 0
        stats["零散小单订单数"] = 0
    
    stats["统计订单数"] = len(group_sum)
    
    # 计算统计范围内的总营业额和总人数
    stats["统计范围内总营业额"] = group_sum["订单收入"].sum()
    stats["统计范围内消费总人数"] = group_sum["团体人数"].sum()
    
    return group_sum, stats


def filter_groups(group_sum, items_df):
    """
    过滤掉不符合条件的消费团体
    
    Args:
        group_sum: 聚合后的消费团体DataFrame
        items_df: 商品DataFrame
    
    Returns:
        (group_sum, filter_stats): 过滤后的消费团体DataFrame和过滤统计字典
    """
    # 标记需要过滤的行
    filtered_indices = []
    free_order_count = 0
    free_group_count = 0
    snack_order_count = 0
    snack_group_count = 0
    packing_order_count = 0
    packing_group_count = 0
    scattered_small_order_count = 0
    scattered_small_group_count = 0
    bar_order_count = 0
    bar_group_count = 0

    for idx, row in group_sum.iterrows():
        order_ids = row["包含订单"]

        # 检查1：人均消费为0
        if row["人均消费"] <= 0 or pd.isna(row["人均消费"]):
            filtered_indices.append(idx)
            free_order_count += len(order_ids)
            free_group_count += 1
            continue

        # 检查2：商品中类为"对外售卖零食"的独立订单
        # 获取该团体的所有商品
        group_items = items_df[items_df["订单号"].isin(order_ids)]

        # 检查是否所有商品都是"对外售卖零食"
        if len(group_items) > 0:
            all_snacks = (group_items["商品中类"] == "对外售卖零食").all()
            if all_snacks:
                filtered_indices.append(idx)
                snack_order_count += len(order_ids)
                snack_group_count += 1
                continue

            # 检查3：商品中类全是"打包"（仅购买餐盒等打包用品，无实际菜品）
            all_packing = (group_items["商品中类"] == "打包").all()
            if all_packing:
                filtered_indices.append(idx)
                packing_order_count += len(order_ids)
                packing_group_count += 1
                continue

        # 检查4：零散小单（人数=1、菜品数量=1、收入<100）
        # 这类订单通常无法确认归属，会干扰统计日整体人均。
        if len(group_items) > 0:
            dish_qty = group_items["数量"].fillna(0).sum()
        else:
            dish_qty = 0
        if (
            row["团体人数"] == 1
            and dish_qty == 1
            and row["订单收入"] < 100
        ):
            filtered_indices.append(idx)
            scattered_small_order_count += len(order_ids)
            scattered_small_group_count += 1
            continue

        # 检查5：吧台订单不计入统计范围
        if '吧台' in str(row['桌台']):
            filtered_indices.append(idx)
            bar_order_count += len(order_ids)
            bar_group_count += 1
            continue

    # 移除过滤的行
    if filtered_indices:
        group_sum = group_sum.drop(filtered_indices).reset_index(drop=True)

    filter_stats = {
        "免单消费订单数": free_order_count,
        "免单消费团体数": free_group_count,
        "零食购买订单数": snack_order_count,
        "零食购买团体数": snack_group_count,
        "打包用品订单数": packing_order_count,
        "打包用品团体数": packing_group_count,
        "零散小单订单数": scattered_small_order_count,
        "零散小单团体数": scattered_small_group_count,
        "吧台订单数": bar_order_count,
        "吧台团体数": bar_group_count,
    }

    return group_sum, filter_stats


def get_group_items(group_sum, items_df):
    """
    获取每个消费团体的商品明细
    
    Args:
        group_sum: 聚合后的消费团体DataFrame
        items_df: 商品DataFrame
    
    Returns:
        包含商品明细的消费团体字典
    """
    group_items = {}
    
    for _, row in group_sum.iterrows():
        table = row["桌台"]
        group_id = row["消费团体ID"]
        order_ids = row["包含订单"]
        
        # 获取该团体所有订单的商品
        group_items_df = items_df[items_df["订单号"].isin(order_ids)].copy()
        
        # 按商品中类和商品名称排序
        group_items_df = group_items_df.sort_values(["商品中类", "商品名称"]).reset_index(drop=True)
        
        group_items[(table, group_id)] = group_items_df
    
    return group_items
