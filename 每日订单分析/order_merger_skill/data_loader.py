"""
数据加载与预处理模块
"""
import pandas as pd
import re


def parse_export(df, header_keyword="订单号"):
    """
    解析导出的Excel数据，找到真正的表头
    
    Args:
        df: 原始DataFrame
        header_keyword: 表头关键字，用于定位表头行
    
    Returns:
        处理后的DataFrame
    """
    header_idx = None
    for i, row in df.iterrows():
        if header_keyword in str(row.values):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(f"Header row with '{header_keyword}' not found")

    header = df.iloc[header_idx].tolist()
    data = df.iloc[header_idx + 1:].copy()
    data.columns = header
    data = data.dropna(axis=1, how="all").reset_index(drop=True)
    return data


def load_excel(file_path):
    """
    加载Excel文件
    
    Args:
        file_path: Excel文件路径
    
    Returns:
        (orders_df, items_df): 订单表和商品表的DataFrame
    """
    orders_raw = pd.read_excel(file_path, sheet_name="店内订单明细")
    items_raw = pd.read_excel(file_path, sheet_name="商品-店内订单明细")

    orders = parse_export(orders_raw)
    items = parse_export(items_raw)

    return orders, items


def clean_orders(orders_df):
    """
    清洗订单表数据
    
    Args:
        orders_df: 原始订单DataFrame
    
    Returns:
        清洗后的订单DataFrame
    """
    # 剔除合计行（订单号不是数字的行）
    orders_df = orders_df[orders_df["订单号"].astype(str).str.fullmatch(r"\d+")].copy()
    
    # 类型转换
    orders_df["下单时间"] = pd.to_datetime(orders_df["下单时间"], errors="coerce")
    orders_df["结账时间"] = pd.to_datetime(orders_df["结账时间"], errors="coerce")
    orders_df["订单金额"] = pd.to_numeric(orders_df["订单金额"], errors="coerce")
    orders_df["订单收入"] = pd.to_numeric(orders_df["订单收入"], errors="coerce")
    orders_df["就餐人数"] = pd.to_numeric(orders_df["就餐人数"], errors="coerce")
    
    # 只保留堂食订单
    orders_df = orders_df[orders_df["订单类型"] == "堂食"].copy()

    # 外卖：桌台名称含「外点自取」的订单不参与合并与统计
    _table = orders_df["桌台"].astype(str)
    orders_df = orders_df[~_table.str.contains("外点自取", na=False)].copy()
    
    # 按桌台和下单时间排序
    orders_df = orders_df.sort_values(["桌台", "下单时间"]).reset_index(drop=True)
    
    return orders_df


def clean_items(items_df):
    """
    清洗商品表数据
    
    Args:
        items_df: 原始商品DataFrame
    
    Returns:
        清洗后的商品DataFrame
    """
    # 剔除合计行
    items_df = items_df[items_df["订单号"].astype(str).str.fullmatch(r"\d+")].copy()
    
    # 类型转换
    items_df["单价"] = pd.to_numeric(items_df["单价"], errors="coerce")
    items_df["数量"] = pd.to_numeric(items_df["数量"], errors="coerce")
    items_df["菜品合计金额"] = pd.to_numeric(items_df["菜品合计金额"], errors="coerce")
    
    return items_df


def get_item_features(items_df):
    """
    从商品表中提取每单的特征
    
    Args:
        items_df: 商品DataFrame
    
    Returns:
        (item_sets, line_cnts): 商品名称集合字典和商品行数字典
    """
    # 每单的商品名称集合（用于Jaccard相似度计算）
    items_df["商品名称"] = items_df["商品名称"].astype(str)
    item_sets = items_df.groupby("订单号")["商品名称"].apply(
        lambda x: set(i.strip() for i in x)
    ).to_dict()
    
    # 每单的商品行数
    line_cnts = items_df.groupby("订单号").size().to_dict()
    
    return item_sets, line_cnts
