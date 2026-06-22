import pandas as pd
import re
import os
from datetime import datetime

def parse_metadata(df_raw):
    """
    Extract metadata (store name, order time range, report time) from rows above header
    """
    metadata = {
        "raw_store_name": None,
        "order_time_range": None,
        "report_time": None
    }
    
    # Scan the first 10 rows for keywords
    for _, row in df_raw.head(10).iterrows():
        row_vals = list(row.values)
        for i, val in enumerate(row_vals):
            val_str = str(val).strip()
            if val_str == "门店名称" and i + 1 < len(row_vals):
                metadata["raw_store_name"] = str(row_vals[i+1]).strip()
            elif val_str == "下单时间" and i + 1 < len(row_vals):
                metadata["order_time_range"] = str(row_vals[i+1]).strip()
            elif val_str == "制表时间" and i + 1 < len(row_vals):
                metadata["report_time"] = str(row_vals[i+1]).strip()
                
    return metadata

def clean_store_name(raw_store, file_path=None, force_store=None):
    """
    Deduce store name: force_store > Excel metadata raw_store (never filename).
    Standardize to '万荷店', '保利店', '湾里店'
    """
    _ = file_path  # kept for call-site compatibility
    if force_store:
        name = force_store
    elif raw_store:
        name = raw_store
    else:
        name = "未知门店"
        
    if "万荷" in name:
        return "万荷店"
    elif "保利" in name:
        return "保利店"
    elif "湾里" in name:
        return "湾里店"
    return "未知门店"

def load_takeaway_excel(file_path, force_store=None):
    """
    Loads sheet '平台外卖订单明细' from file_path, locates header dynamically,
    parses metadata, filters valid and completed/cancelled orders, masks privacy data.
    """
    # Load sheet
    xls = pd.ExcelFile(file_path)
    sheet_name = "平台外卖订单明细"
    if sheet_name not in xls.sheet_names:
        # Fallback to the first sheet if name doesn't match
        sheet_name = xls.sheet_names[0]
        
    df_raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
    
    # Parse metadata
    meta = parse_metadata(df_raw)
    
    # Locate header index dynamically
    header_idx = None
    for i, row in df_raw.iterrows():
        if "外卖订单号" in row.values:
            header_idx = i
            break
            
    if header_idx is None:
        raise ValueError(f"Could not find header row containing '外卖订单号' in {file_path}")
        
    header = df_raw.iloc[header_idx].tolist()
    data = df_raw.iloc[header_idx + 1:].copy()
    data.columns = header
    
    # Exclude title/合计/empty rows
    # 1. Total row (序号 == '合计' or 外卖订单号 == '-')
    data = data[data["外卖订单号"].notna()].copy()
    data["外卖订单号_str"] = data["外卖订单号"].astype(str).str.strip()
    data = data[data["外卖订单号_str"].str.fullmatch(r"\d+")].copy()
    
    # Clean store name
    store_name = clean_store_name(meta["raw_store_name"], file_path, force_store)
    data["store_name"] = store_name
    
    # Numeric columns
    num_cols = [
        '订单金额', '菜品合计金额', '附加费分摊', '菜品优惠', '菜品收入', 
        '餐盒费', '打包费', '配送费', '订单优惠', '平台优惠', '顾客实付', 
        '订单支出', '外卖抽佣', '配送支出', '其他支出', '部分退款', '订单收入'
    ]
    for col in num_cols:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors='coerce').fillna(0.0)
        else:
            data[col] = 0.0
            
    # Datetime columns
    date_cols = ['下单时间', '接单时间', '送达时间', '首次对账时间']
    for col in date_cols:
        if col in data.columns:
            data[col] = pd.to_datetime(data[col], errors='coerce')
            
    # Business date (营业日)
    if "营业日" in data.columns:
        data["营业日"] = pd.to_datetime(data["营业日"], errors='coerce').dt.strftime('%Y-%m-%d')
        # Fallback to 下单时间 date if null
        mask_null = data["营业日"].isna()
        if mask_null.any():
            data.loc[mask_null, "营业日"] = data.loc[mask_null, "下单时间"].dt.strftime('%Y-%m-%d')
    else:
        data["营业日"] = data["下单时间"].dt.strftime('%Y-%m-%d')
        
    # Clean rows with missing/invalid business dates (e.g. NaN or NaT) to prevent DB pollution
    if "营业日" in data.columns:
        data = data.dropna(subset=["营业日"]).copy()
        data = data[data["营业日"].astype(str).str.lower().str.strip().apply(lambda x: x not in ('nat', 'nan', 'none', ''))].copy()
        
    # Mask/remove privacy columns
    privacy_cols = ['收货人姓名', '收货人手机号', '送餐地址']
    for col in privacy_cols:
        data[col] = "***"
        
    # Set standard index/columns order
    data = data.reset_index(drop=True)
    
    # Add metadata back to data.attrs for reference
    data.attrs["store_name"] = store_name
    data.attrs["order_time_range"] = meta["order_time_range"]
    data.attrs["report_time"] = meta["report_time"]
    
    return data
