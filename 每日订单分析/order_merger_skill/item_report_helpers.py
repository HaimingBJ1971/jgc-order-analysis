"""
合并消费团体在报告中的菜品展示：多笔原订单时按订单号分块，便于人工复核。
"""


def sorted_items_for_order(items_df_group, order_id):
    """某原订单在团体商品表中的行，按分类与名称排序。"""
    sub = items_df_group[items_df_group["订单号"] == order_id].copy()
    if len(sub) == 0:
        return sub
    return sub.sort_values(["商品中类", "商品名称"]).reset_index(drop=True)


def iter_subsections_for_report(items_df_group, order_ids, merged_group):
    """
    生成报告用的小节迭代器。

    merged_group 为 True 时（团体内订单数>1），按 order_ids 顺序逐单输出；
    为 False 时整表一笔展示（顺序与单品类排序，与原先扁平一致）。

    Yields:
        (subsection_label, sub_df): subsection_label 在非合并时为 None（不显示子标题）；
        合并多笔时为原订单号字符串。sub_df 为该小节商品行。
    """
    if items_df_group is None or len(items_df_group) == 0:
        return

    order_ids = list(order_ids) if order_ids is not None else []

    if not merged_group or len(order_ids) <= 1:
        # None 表示不展示「子订单」标题，与历史单表行为一致
        df = items_df_group.sort_values(["商品中类", "商品名称"]).reset_index(
            drop=True
        )
        yield (None, df)
        return

    for oid in order_ids:
        sub = sorted_items_for_order(items_df_group, oid)
        if len(sub) == 0:
            continue
        yield (str(oid), sub)
