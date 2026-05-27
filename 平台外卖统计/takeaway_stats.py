import pandas as pd
import numpy as np

def get_completed_orders(df):
    return df[df["订单状态"] == "已完成"].copy()

def get_cancelled_orders(df):
    return df[df["订单状态"] != "已完成"].copy()

def compute_summary_dict(completed_df, cancelled_df):
    """
    Computes overall summary metrics as a dictionary
    """
    total_valid = len(completed_df)
    total_cancelled = len(cancelled_df)
    
    revenue = completed_df["订单收入"].sum()
    cust_paid = completed_df["顾客实付"].sum()
    avg_ticket = revenue / total_valid if total_valid > 0 else 0.0
    
    commission = completed_df["外卖抽佣"].sum()
    comm_rate = abs(commission) / cust_paid if cust_paid > 0 else 0.0
    
    expenditure = completed_df["订单支出"].sum()
    exp_rate = abs(expenditure) / cust_paid if cust_paid > 0 else 0.0
    
    partial_refund = completed_df["部分退款"].sum()
    order_amt = completed_df["订单金额"].sum()
    dish_amt = completed_df["菜品合计金额"].sum()
    dish_rev = completed_df["菜品收入"].sum()
    dish_promo = completed_df["菜品优惠"].sum()
    order_promo = completed_df["订单优惠"].sum()
    platform_promo = completed_df["平台优惠"].sum()
    
    return {
        "有效订单数": total_valid,
        "退单数": total_cancelled,
        "订单收入": revenue,
        "顾客实付": cust_paid,
        "客单价": avg_ticket,
        "外卖抽佣": commission,
        "抽佣率": comm_rate,
        "订单支出": expenditure,
        "订单支出率": exp_rate,
        "部分退款": partial_refund,
        "订单金额": order_amt,
        "菜品合计金额": dish_amt,
        "菜品收入": dish_rev,
        "菜品优惠": dish_promo,
        "订单优惠": order_promo,
        "平台优惠": platform_promo
    }

def calculate_store_comparison(df):
    """
    Side-by-side performance of stores
    """
    completed = get_completed_orders(df)
    cancelled = get_cancelled_orders(df)
    
    stores = df["store_name"].unique()
    comparison_rows = []
    
    for s in sorted(stores):
        s_comp = completed[completed["store_name"] == s]
        s_canc = cancelled[cancelled["store_name"] == s]
        
        metrics = compute_summary_dict(s_comp, s_canc)
        metrics["门店"] = s
        comparison_rows.append(metrics)
        
    return pd.DataFrame(comparison_rows)

def calculate_daily_trends(df):
    """
    Daily stats per store and day
    """
    completed = get_completed_orders(df)
    cancelled = get_cancelled_orders(df)
    
    rows = []
    # Group by store and date
    groups = df.groupby(["store_name", "营业日"])
    for (store, day), grp in groups:
        comp_g = completed[(completed["store_name"] == store) & (completed["营业日"] == day)]
        canc_g = cancelled[(cancelled["store_name"] == store) & (cancelled["营业日"] == day)]
        
        m = compute_summary_dict(comp_g, canc_g)
        m["门店"] = store
        m["营业日"] = day
        rows.append(m)
        
    df_res = pd.DataFrame(rows)
    if not df_res.empty:
        df_res = df_res.sort_values(["门店", "营业日"]).reset_index(drop=True)
    return df_res

def calculate_platform_stats(df):
    """
    Stats per store and platform (订单来源)
    """
    completed = get_completed_orders(df)
    cancelled = get_cancelled_orders(df)
    
    rows = []
    groups = df.groupby(["store_name", "订单来源"])
    for (store, source), grp in groups:
        comp_g = completed[(completed["store_name"] == store) & (completed["订单来源"] == source)]
        canc_g = cancelled[(cancelled["store_name"] == store) & (cancelled["订单来源"] == source)]
        
        m = compute_summary_dict(comp_g, canc_g)
        m["门店"] = store
        m["平台"] = source
        rows.append(m)
        
    df_res = pd.DataFrame(rows)
    if not df_res.empty:
        df_res = df_res.sort_values(["门店", "平台"]).reset_index(drop=True)
    return df_res

def calculate_hourly_distribution(df):
    """
    Hourly (0-23) distribution per store and overall
    Also calculates Lunch vs Dinner summary
    """
    completed = get_completed_orders(df).copy()
    if completed.empty:
        return pd.DataFrame(), pd.DataFrame()
        
    completed["hour"] = completed["下单时间"].dt.hour
    completed["时段"] = completed["hour"].apply(lambda h: "午市" if h < 16 else "晚市")
    
    # Hour Stats
    h_rows = []
    groups = completed.groupby(["store_name", "hour"])
    for (store, hour), grp in groups:
        h_rows.append({
            "门店": store,
            "小时": hour,
            "订单数": len(grp),
            "订单收入": grp["订单收入"].sum()
        })
    df_hour = pd.DataFrame(h_rows)
    if not df_hour.empty:
        df_hour = df_hour.sort_values(["门店", "小时"]).reset_index(drop=True)
        
    # Meal Period Stats
    m_rows = []
    groups = completed.groupby(["store_name", "时段"])
    for (store, period), grp in groups:
        m_rows.append({
            "门店": store,
            "时段": period,
            "订单数": len(grp),
            "订单收入": grp["订单收入"].sum(),
            "占比": 0.0 # Will calculate later relative to store total
        })
    df_meal = pd.DataFrame(m_rows)
    if not df_meal.empty:
        # Calculate percentages
        store_totals = df_meal.groupby("门店")["订单收入"].transform("sum")
        df_meal["占比"] = df_meal["订单收入"] / store_totals
        df_meal = df_meal.sort_values(["门店", "时段"]).reset_index(drop=True)
        
    return df_hour, df_meal

def calculate_fulfillment_metrics(df, threshold_minutes=45):
    """
    Fulfillment/delivery efficiency metrics (Mean, P50, P90 times)
    Also identifies超时关注单 (orders > threshold_minutes)
    """
    completed = get_completed_orders(df).copy()
    if completed.empty:
        return pd.DataFrame(), pd.DataFrame()
        
    # Compute durations in minutes
    completed["接单耗时"] = (completed["接单时间"] - completed["下单时间"]).dt.total_seconds() / 60.0
    completed["送达时长"] = (completed["送达时间"] - completed["下单时间"]).dt.total_seconds() / 60.0
    completed["配送段时长"] = (completed["送达时间"] - completed["接单时间"]).dt.total_seconds() / 60.0
    
    stores = completed["store_name"].unique()
    eff_rows = []
    
    for s in sorted(stores):
        sub = completed[completed["store_name"] == s]
        
        # Helper to compute metrics
        def get_stat(series):
            clean = series.dropna()
            if clean.empty:
                return 0.0, 0.0, 0.0
            return clean.mean(), clean.median(), clean.quantile(0.9)
            
        mean_jd, p50_jd, p90_jd = get_stat(sub["接单耗时"])
        mean_sd, p50_sd, p90_sd = get_stat(sub["送达时长"])
        mean_ps, p50_ps, p90_ps = get_stat(sub["配送段时长"])
        
        eff_rows.append({
            "门店": s,
            "平均接单耗时": mean_jd,
            "P50接单耗时": p50_jd,
            "P90接单耗时": p90_jd,
            "平均送达时长": mean_sd,
            "P50送达时长": p50_sd,
            "P90送达时长": p90_sd,
            "平均配送段时长": mean_ps,
            "P50配送段时长": p50_ps,
            "P90配送段时长": p90_ps
        })
        
    df_eff = pd.DataFrame(eff_rows)
    
    # Overtime orders
    overtime_df = completed[completed["送达时长"] > threshold_minutes].copy()
    overtime_cols = ["store_name", "订单来源", "外卖订单号", "下单时间", "接单时间", "送达时间", "送达时长"]
    overtime_df = overtime_df[overtime_df.columns.intersection(overtime_cols)].copy()
    if not overtime_df.empty:
        overtime_df = overtime_df.sort_values(["store_name", "送达时长"], ascending=[True, False]).reset_index(drop=True)
        
    return df_eff, overtime_df

def identify_abnormal_orders(df):
    """
    Identifies abnormal or exception orders:
    - Cancelled /已退单
    - Zero-amount orders (completed but revenue=0 or amount=0)
    - Missing times (接单时间 or 送达时间 is null for completed)
    - Partial refunds (completed with refund > 0)
    """
    completed = get_completed_orders(df).copy()
    cancelled = get_cancelled_orders(df).copy()
    
    abnormal_rows = []
    
    # 1. Cancelled
    for _, r in cancelled.iterrows():
        abnormal_rows.append({
            "门店": r["store_name"],
            "平台": r["订单来源"],
            "外卖订单号": r["外卖订单号"],
            "订单状态": r["订单状态"],
            "下单时间": r["下单时间"],
            "订单收入": r["订单收入"],
            "异常说明": "客户已退单/已取消"
        })
        
    # 2. Zero-amount completed
    zero_orders = completed[(completed["订单收入"] == 0) | (completed["订单金额"] == 0)]
    for _, r in zero_orders.iterrows():
        abnormal_rows.append({
            "门店": r["store_name"],
            "平台": r["订单来源"],
            "外卖订单号": r["外卖订单号"],
            "订单状态": r["订单状态"],
            "下单时间": r["下单时间"],
            "订单收入": r["订单收入"],
            "异常说明": f"0元订单 (收入: {r['订单收入']}, 金额: {r['订单金额']})"
        })
        
    # 3. Missing times for completed
    missing_times = completed[completed["接单时间"].isna() | completed["送达时间"].isna()]
    for _, r in missing_times.iterrows():
        reason = []
        if pd.isna(r["接单时间"]): reason.append("缺失接单时间")
        if pd.isna(r["送达时间"]): reason.append("缺失送达时间")
        abnormal_rows.append({
            "门店": r["store_name"],
            "平台": r["订单来源"],
            "外卖订单号": r["外卖订单号"],
            "订单状态": r["订单状态"],
            "下单时间": r["下单时间"],
            "订单收入": r["订单收入"],
            "异常说明": " & ".join(reason)
        })
        
    # 4. Partial refunds
    partial_refunds = completed[completed["部分退款"] > 0]
    for _, r in partial_refunds.iterrows():
        abnormal_rows.append({
            "门店": r["store_name"],
            "平台": r["订单来源"],
            "外卖订单号": r["外卖订单号"],
            "订单状态": r["订单状态"],
            "下单时间": r["下单时间"],
            "订单收入": r["订单收入"],
            "异常说明": f"存在部分退款 (金额: ¥{r['部分退款']:.2f})"
        })
        
    df_abn = pd.DataFrame(abnormal_rows)
    if not df_abn.empty:
        # Deduplicate identical orders showing multiple exceptions (e.g. 0-amount and missing times)
        df_abn = df_abn.groupby(["门店", "平台", "外卖订单号", "订单状态", "下单时间", "订单收入"])["异常说明"].apply(lambda x: " | ".join(x.unique())).reset_index()
        df_abn = df_abn.sort_values(["门店", "下单时间"]).reset_index(drop=True)
        
    return df_abn
