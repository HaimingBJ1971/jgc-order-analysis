import pandas as pd
from datetime import datetime

xlsx_file = '/Users/jgc/Documents/每日订单分析/店内订单明细2026-03-30+00_00_00~2026-03-30+23_59_59.xlsx'

# 读取店内订单明细
orders_df = pd.read_excel(xlsx_file, sheet_name='店内订单明细', skiprows=7)
orders_df.columns = orders_df.iloc[0]
orders_df = orders_df[1:]
orders_df = orders_df.reset_index(drop=True)
orders_df = orders_df.dropna(how='all')

# 只保留堂食订单
orders_df = orders_df[orders_df['订单类型'] == '堂食'].copy()

# 转换时间列
orders_df['下单时间'] = pd.to_datetime(orders_df['下单时间'])
orders_df['结账时间'] = pd.to_datetime(orders_df['结账时间'])

# 按桌台和下单时间排序
orders_df = orders_df.sort_values(['桌台', '下单时间'])

print('=== 按桌台分组的订单 ===')
for table_id, group in orders_df.groupby('桌台'):
    if len(group) > 1:
        print(f'\n桌台: {table_id}, 订单数: {len(group)}')
        for idx, row in group.iterrows():
            print(f'  订单号: {row["订单号"]}, 下单时间: {row["下单时间"]}, 结账时间: {row["结账时间"]}, 金额: {row["订单金额"]}, 人数: {row["就餐人数"]}, 手机号: {row["会员手机号"]}')
