"""
订单与桌访合并工具 v2
整合完整订单处理 pipeline（合并、人均、过滤），关联桌访数据，生成 PDF 报告。
"""
import sys
import os
import argparse
import re
from datetime import datetime

import pandas as pd
from html import escape as html_escape
from reportlab.lib.pagesizes import A4, A3, landscape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# 复用 order_merger_skill
_skill_dir = os.path.join(os.path.dirname(__file__), '..', '每日订单分析', 'order_merger_skill')
sys.path.insert(0, os.path.abspath(_skill_dir))
from data_loader import load_excel, clean_orders, clean_items, get_item_features
from order_merger import merge_orders
from aggregator import aggregate_groups, get_group_items
from item_report_helpers import iter_subsections_for_report

STORES = ['万荷店', '保利店', '湾里店']

# ── PDF 字体 ──────────────────────────────────────────────────────


def register_chinese_font():
    import sys
    import os
    font_paths = []
    
    # 1. macOS Paths
    font_paths.extend([
        ('/System/Library/Fonts/STHeiti Medium.ttc', 0),
        ('/System/Library/Fonts/STHeiti Medium.ttc', 1),
        ('/System/Library/Fonts/STHeiti Light.ttc', 0),
        ('/System/Library/Fonts/STHeiti Light.ttc', 1),
        ('/System/Library/Fonts/PingFang.ttc', 0),
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
    
    for font_path, subfont_index in font_paths:
        if not os.path.exists(font_path):
            continue
        try:
            name = f'ChineseFont_{subfont_index}' if subfont_index is not None else 'ChineseFont'
            if 'ttc' in font_path.lower() and subfont_index is not None:
                pdfmetrics.registerFont(TTFont(name, font_path, subfontIndex=subfont_index))
            else:
                pdfmetrics.registerFont(TTFont(name, font_path))
            return name
        except Exception:
            continue
    return 'Helvetica'


CHINESE_FONT = register_chinese_font()

# ── 重点菜品 / 新品列表 ────────────────────────────────────────────

TARGET_DISHES = [
    "富顺鸡丝凉面",
    "古法干烧鱼(江团)",
    "古法干烧鱼(鲈鱼)",
    "富顺荤豆花",
    "206省道半汤牛蛙",
    "酸菜煸炒土豆片",
    "香菜回锅茄子",
    "火爆腰花",
    "炝炒莲花白菜",
    "金阳青花椒辣子鸡",
    "鱼香梅花肉丝",
    "文庙担担面",
    "茂萱婆婆芽菜包",
    "五指毛桃白芸豆猪肚三年老鸡汤(盅)",
]

TARGET_NEW_ITEMS = [
    "麻辣红油凉鸡",
    "酸辣手工米皮",
    "川西腊肉炒黄瓜花",
    "蒜蓉干椒红苋菜",
    "山楂覆盆子果饮（扎/冰）",
    "红心芭乐（扎/冰）",
    "桂花乌龙牛乳茶（杯/冰）",
]

BAOLI_TARGET_DISHES = [
    "川南鱼香肉丝（不能免葱）",
    "香菜回锅茄子",
]


def compute_dish_stats(items_df):
    """统计重点菜品销售份数，按数量降序返回 [(菜名, 份数), ...]"""
    items_df = items_df.copy()
    items_df["商品名称_规范化"] = items_df["商品名称"].astype(str).apply(
        lambda x: x.replace('（', '(').replace('）', ')')
    )

    dish_stats = []
    for target in TARGET_DISHES:
        normalized = target.replace('（', '(').replace('）', ')')
        matched = items_df[items_df["商品名称_规范化"].str.contains(normalized, na=False, case=False, regex=False)]
        if len(matched) == 0:
            keyword = re.sub(r'[（(].*?[）)]', '', target).strip()
            if keyword:
                matched = items_df[items_df["商品名称"].str.contains(keyword, na=False, case=False, regex=False)]
        qty = int(matched["数量"].sum()) if len(matched) > 0 else 0
        dish_stats.append((target, qty))

    # 合并古法干烧鱼(江团)+(鲈鱼) → 古法干烧鱼
    merged = {}
    jt_qty = lu_qty = 0
    for name, qty in dish_stats:
        if name == "古法干烧鱼(江团)":
            jt_qty = qty
        elif name == "古法干烧鱼(鲈鱼)":
            lu_qty = qty
        else:
            merged[name] = qty
    merged["古法干烧鱼"] = jt_qty + lu_qty

    return sorted(merged.items(), key=lambda x: x[1], reverse=True)


def compute_new_item_stats(items_df):
    """统计重点新品销售份数，按数量降序返回 [(品名, 份数), ...]"""
    items_df = items_df.copy()
    items_df["商品名称_规范化"] = items_df["商品名称"].astype(str).apply(
        lambda x: x.replace('（', '(').replace('）', ')')
    )

    stats = []
    for target in TARGET_NEW_ITEMS:
        normalized = target.replace('（', '(').replace('）', ')')
        matched = items_df[items_df["商品名称_规范化"].str.contains(normalized, na=False, case=False, regex=False)]
        if len(matched) == 0:
            matched = items_df[items_df["商品名称"].str.contains(target, na=False, case=False, regex=False)]
        qty = int(matched["数量"].sum()) if len(matched) > 0 else 0
        stats.append((target, qty))

    return sorted(stats, key=lambda x: x[1], reverse=True)


def _make_dish_table(data_rows):
    """创建菜品统计表，复用统一样式。"""
    tbl = Table(data_rows, colWidths=[7*cm, 3*cm])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('ALIGN', (1, 1), (1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
    ]))
    return tbl


def _compute_baoli_dish_stats(items_df):
    """保利店专用：仅统计两个指定菜品。"""
    stats = []
    items_df = items_df.copy()
    items_df["商品名称_规范化"] = items_df["商品名称"].astype(str).apply(
        lambda x: x.replace('（', '(').replace('）', ')')
    )
    for target in BAOLI_TARGET_DISHES:
        normalized = target.replace('（', '(').replace('）', ')')
        matched = items_df[items_df["商品名称_规范化"].str.contains(normalized, na=False, case=False, regex=False)]
        if len(matched) == 0:
            keyword = re.sub(r'[（(].*?[）)]', '', target).strip()
            if keyword:
                matched = items_df[items_df["商品名称"].str.contains(keyword, na=False, case=False, regex=False)]
        qty = int(matched["数量"].sum()) if len(matched) > 0 else 0
        stats.append((target, qty))
    return sorted(stats, key=lambda x: x[1], reverse=True)


def compute_lunch_dinner_top5(items_df, gs):
    """保利店：按午市/晚市分别统计销量前5的菜品。
    返回 (lunch_top5, dinner_top5)，各为 [(菜名, 份数), ...]
    """
    # 构建 订单号 → 午市/晚市 映射
    order_meal = {}
    for _, row in gs.iterrows():
        meal = row.get('_meal', '')
        for oid in row.get('包含订单', []):
            order_meal[str(oid)] = meal

    items = items_df.copy()
    items['_meal'] = items['订单号'].astype(str).map(order_meal)

    def _top5(subset):
        dish_qty = subset.groupby('商品名称')['数量'].sum()
        dish_qty = dish_qty[dish_qty > 0]
        top = dish_qty.nlargest(6).astype(int)
        return list(zip(top.index, top.values))

    lunch = _top5(items[items['_meal'] == '午市'])
    dinner = _top5(items[items['_meal'] == '晚市'])
    return lunch, dinner

# ── 数据加载 ──────────────────────────────────────────────────────


def load_and_process_orders(excel_path):
    """加载 Excel → 清洗 → 合并 → 聚合 → 过滤，返回 (group_sum, group_items, stats, orders_with_group)"""
    orders_df, items_df = load_excel(excel_path)

    # 统计清洗前的原始数据
    raw_total = len(orders_df)
    # 外卖：桌台含「外点自取」
    takeout_mask = orders_df['桌台'].astype(str).str.contains('外点自取', na=False)
    takeout_count = int(takeout_mask.sum())
    # 非堂食：订单类型不为「堂食」
    non_dinein_count = int((orders_df['订单类型'] != '堂食').sum())

    orders_clean = clean_orders(orders_df)
    items_clean = clean_items(items_df)
    # 只保留仍参与统计的订单对应的商品行
    valid_ids = set(orders_clean['订单号'].astype(str))
    items_clean = items_clean[items_clean['订单号'].astype(str).isin(valid_ids)].copy()

    # 过滤菜品收入为 0 的商品（POS 中已取消/作废但未删行，退菜也一并排除）
    items_clean = items_clean[items_clean['菜品收入'] > 0].copy()

    item_sets, line_cnts = get_item_features(items_clean)
    orders_with_group, groups = merge_orders(orders_clean, item_sets, line_cnts, items_clean)
    group_sum, stats = aggregate_groups(orders_with_group, items_clean)
    group_items = get_group_items(group_sum, items_clean)

    # 覆盖原始订单数为清洗前总数，补入外卖订单数
    stats['原始订单数'] = raw_total
    stats['外点自取订单数'] = takeout_count
    stats['非堂食订单数'] = non_dinein_count

    return group_sum, group_items, stats, items_clean, orders_with_group


def load_csv_feedback(csv_path, store_name=None, target_date=None, target_date_end=None):
    """加载桌访 CSV，按门店和日期区间过滤，返回有效记录和未识别记录"""
    for enc in ['utf-8-sig', 'utf-8', 'gbk', 'gb2312']:
        try:
            df = pd.read_csv(csv_path, encoding=enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        raise ValueError(f'无法读取 CSV: {csv_path}')

    unrecognized = df[df['订单号'].astype(str).isin(['未识别', 'nan', '', 'None'])].copy()
    valid = df[~df['订单号'].astype(str).isin(['未识别', 'nan', '', 'None'])].copy()
    valid['订单号'] = valid['订单号'].astype(str).str.strip()

    if store_name and '店面' in valid.columns:
        valid = valid[valid['店面'] == store_name].copy()
        if '店面' in unrecognized.columns:
            unrecognized = unrecognized[unrecognized['店面'] == store_name].copy()

    if target_date and '营业日期' in valid.columns:
        end = target_date_end or target_date
        valid['_日期'] = pd.to_datetime(valid['营业日期'], errors='coerce').dt.strftime('%Y-%m-%d')
        valid = valid[(valid['_日期'] >= target_date) & (valid['_日期'] <= end)].drop(columns=['_日期']).copy()
        if '营业日期' in unrecognized.columns:
            unrecognized['_日期'] = pd.to_datetime(unrecognized['营业日期'], errors='coerce').dt.strftime('%Y-%m-%d')
            unrecognized = unrecognized[(unrecognized['_日期'] >= target_date) & (unrecognized['_日期'] <= end)].drop(columns=['_日期']).copy()

    return valid, unrecognized


def build_feedback_map(csv_df):
    """建立 {订单号: [桌访记录列表]} 的字典"""
    fmap = {}
    for _, row in csv_df.iterrows():
        oid = str(row['订单号']).strip()
        fmap.setdefault(oid, []).append(row)
    return fmap


def infer_store(excel_orders, csv_df):
    """根据订单号交集推断门店"""
    excel_ids = set(excel_orders['订单号'].astype(str).unique())
    best, best_n = None, 0
    for store in STORES:
        if '店面' not in csv_df.columns:
            continue
        store_ids = set(csv_df[csv_df['店面'] == store]['订单号'].astype(str).unique())
        n = len(excel_ids & store_ids)
        if n > best_n:
            best_n = n
            best = store
    return best, best_n


def extract_date_from_excel(excel_path):
    """从 Excel 实际数据中提取起止日期，返回 (start_date, end_date) 元组。"""
    orders_df, _ = load_excel(excel_path)
    orders_clean = clean_orders(orders_df)
    start = orders_clean['下单时间'].min().strftime('%Y-%m-%d')
    end = orders_clean['下单时间'].max().strftime('%Y-%m-%d')
    return start, end


# ── 桌访关联 ──────────────────────────────────────────────────────


def match_unrecognized_by_table_amount(unrecognized, orders_df):
    """
    对无订单号的桌访记录，通过三变量「桌台号、支付金额、下单时间」中任意两个一致来匹配。

    匹配规则（三选二）：
    - 桌台号一致：CSV桌台号是订单桌台名的子串，或反过来
    - 支付金额一致：与订单的「订单金额」或「订单收入」相等（精确到元）
    - 下单时间一致：CSV下单时间与订单下单时间相差 ≤ 5 分钟

    返回：
        matched: list of (order_id, record_dict) — 匹配成功的记录，record 含 _amount_matched=True
        unmatched: DataFrame — 仍然无法匹配的记录
    """
    if unrecognized is None or len(unrecognized) == 0:
        return [], unrecognized

    # 建立订单列表
    order_list = []
    for _, orow in orders_df.iterrows():
        table = str(orow.get('桌台', ''))
        oid = str(orow['订单号'])
        amt_val = orow.get('订单金额')
        order_time = orow.get('下单时间')
        if pd.isna(amt_val):
            continue
        order_list.append({
            'oid': oid,
            'table': table,
            'amount': int(round(float(amt_val))),
            'order_time': order_time,
        })
        # 也加入订单收入（可能与订单金额不同）
        rev_val = orow.get('订单收入')
        if not pd.isna(rev_val):
            rev_int = int(round(float(rev_val)))
            if rev_int != order_list[-1]['amount']:
                order_list.append({
                    'oid': oid,
                    'table': table,
                    'amount': rev_int,
                    'order_time': order_time,
                })

    matched = []
    unmatched_rows = []

    for _, ur in unrecognized.iterrows():
        table_no = str(ur.get('桌台号', '')).strip()
        pay_amt = ur.get('支付金额')

        # 解析 CSV 下单时间
        csv_time = pd.NaT
        raw_time = ur.get('下单时间')
        if pd.notna(raw_time):
            try:
                csv_time = pd.to_datetime(raw_time)
            except (ValueError, TypeError):
                pass

        # 解析支付金额
        pay_amt_int = None
        if pd.notna(pay_amt):
            try:
                pay_amt_int = int(round(float(pay_amt)))
            except (ValueError, TypeError):
                pass

        found = False
        for order in order_list:
            # 三个匹配条件
            table_ok = bool(table_no) and (table_no in order['table'] or order['table'] in table_no)
            amount_ok = pay_amt_int is not None and order['amount'] == pay_amt_int
            time_ok = False
            if pd.notna(csv_time) and hasattr(order['order_time'], 'strftime'):
                delta = abs((csv_time - order['order_time']).total_seconds())
                time_ok = delta <= 300  # 5 分钟

            # 三选二
            match_count = sum([table_ok, amount_ok, time_ok])
            if match_count >= 2:
                rec = ur.to_dict()
                rec['订单号'] = order['oid']
                rec['_amount_matched'] = True
                matched.append((order['oid'], rec))
                found = True
                break

        if not found:
            unmatched_rows.append(ur)

    unmatched_df = pd.DataFrame(unmatched_rows) if unmatched_rows else pd.DataFrame()
    return matched, unmatched_df


def associate_feedback(group_sum, orders_with_group, feedback_map):
    """
    为每个消费团体关联桌访数据。
    - 检查团体的所有子订单是否有桌访
    - 如果 CSV 就餐人数与 Excel 不一致，以 CSV 为准并重新计算人均
    - 返回增强后的 group_sum 副本
    """
    gs = group_sum.copy()
    # 新增列
    gs['桌访人'] = ''
    gs['桌访状态'] = '未桌访'
    gs['桌访记录'] = [[] for _ in range(len(gs))]
    gs['人数修正'] = False

    # 建立 订单号 → (开单人, 结账人) 映射
    opener_map = {}
    closer_map = {}
    if '开单人' in orders_with_group.columns:
        for _, r in orders_with_group.iterrows():
            opener_map[str(r['订单号'])] = str(r.get('开单人', ''))
    if '结账人' in orders_with_group.columns:
        for _, r in orders_with_group.iterrows():
            closer_map[str(r['订单号'])] = str(r.get('结账人', ''))

    # 主单的开单人/结账人
    gs['开单人'] = gs['主单订单号'].map(lambda oid: opener_map.get(str(oid), ''))
    gs['结账人'] = gs['主单订单号'].map(lambda oid: closer_map.get(str(oid), ''))

    for idx, row in gs.iterrows():
        order_ids = [str(oid) for oid in row['包含订单']]
        # 查找所有匹配的桌访记录
        matched_records = []
        for oid in order_ids:
            if oid in feedback_map:
                matched_records.extend(feedback_map[oid])

        if not matched_records:
            continue

        gs.at[idx, '桌访状态'] = '已桌访'
        gs.at[idx, '桌访记录'] = matched_records

        # 桌访人：取所有记录的服务员，去重
        waiters = list(dict.fromkeys(str(r.get('服务员', '')) for r in matched_records if str(r.get('服务员', ''))))
        gs.at[idx, '桌访人'] = '、'.join(waiters)

        # 人数修正：以 CSV 就餐人数为准
        csv_people = None
        for r in matched_records:
            p = r.get('就餐人数')
            if pd.notna(p):
                try:
                    csv_people = int(float(p))
                except (ValueError, TypeError):
                    pass

        if csv_people is not None and csv_people > 0:
            excel_people = int(row['团体人数'])
            if csv_people != excel_people:
                gs.at[idx, '团体人数'] = csv_people
                gs.at[idx, '人数修正'] = True
                # 重新计算人均
                gs.at[idx, '人均消费'] = row['订单收入'] / csv_people

    return gs


def detect_anomalies(gs, items_clean, store_name=''):
    """
    检测消费团体中的疑似异常情况。

    规则（按优先级）：
    1a. 人数>=5 且 商品数<=3
    1b. 人数>=3 且 商品数<=2
    1c. 人数>=2 且 商品数==1
    2a-c. 人均过低（万荷店: <10/20/30; 保利店: <15>=2人）
    3.  同桌台前后消费疑似同一拨人

    返回 gs 副本，新增 '异常标记' 列（字符串，无异常为空）。
    """
    is_baoli = '保利' in str(store_name)
    gs = gs.copy()
    gs['异常标记'] = ''

    # 预计算每个团体的商品数量
    dish_counts = {}
    for _, row in gs.iterrows():
        order_ids = row['包含订单']
        items = items_clean[items_clean['订单号'].isin(order_ids)]
        dish_counts[(row['桌台'], row['消费团体ID'])] = items['数量'].fillna(0).sum()

    gs['_商品数'] = gs.apply(lambda r: dish_counts.get((r['桌台'], r['消费团体ID']), 0), axis=1)

    # 规则 1：人数与商品数量不匹配（整体级别，分三个子级）
    for idx, row in gs.iterrows():
        people = int(row['团体人数'])
        dishes = row['_商品数']
        if people >= 5 and dishes <= 3:
            gs.at[idx, '异常标记'] = f'人数{people}仅{int(dishes)}件商品，请确认就餐人数'
        elif people >= 3 and dishes <= 2:
            gs.at[idx, '异常标记'] = f'人数{people}仅{int(dishes)}件商品，疑似人数多录'
        elif people >= 2 and dishes == 1:
            gs.at[idx, '异常标记'] = f'人数{people}仅1件商品，请关注'

    # 规则 2：人均异常低（排除已被标记的）
    for idx, row in gs.iterrows():
        if gs.at[idx, '异常标记']:
            continue
        people = int(row['团体人数'])
        arpu = row['人均消费']
        if is_baoli:
            if people >= 2 and arpu < 15:
                gs.at[idx, '异常标记'] = f'人均仅¥{arpu:.0f}（{people}人），偏低'
        else:
            if people >= 2 and arpu < 10:
                gs.at[idx, '异常标记'] = f'人均仅¥{arpu:.0f}（{people}人），疑似人数多录或免单'
            elif people >= 3 and arpu < 20:
                gs.at[idx, '异常标记'] = f'人均仅¥{arpu:.0f}（{people}人）'
            elif people >= 4 and arpu < 30:
                gs.at[idx, '异常标记'] = f'人均仅¥{arpu:.0f}（{people}人），偏低'

    # 规则 3：同桌台前后消费疑似同一拨人
    sorted_gs = gs.sort_values(['桌台', '开始'])
    prev = None
    for idx, row in sorted_gs.iterrows():
        if prev is not None:
            same_table = row['桌台'] == prev['桌台']
            if same_table and not gs.at[idx, '异常标记']:
                time_gap = (row['开始'] - prev['结束']).total_seconds() / 60 if hasattr(row['开始'], 'strftime') and hasattr(prev['结束'], 'strftime') else 999
                if 0 <= time_gap <= 90:
                    prev_dishes = prev['_商品数']
                    curr_dishes = row['_商品数']
                    if prev_dishes >= 4 and curr_dishes <= 2 and int(row['团体人数']) >= 3:
                        prev_end = prev['结束'].strftime('%H:%M') if hasattr(prev['结束'], 'strftime') else '?'
                        curr_start = row['开始'].strftime('%H:%M') if hasattr(row['开始'], 'strftime') else '?'
                        gs.at[idx, '异常标记'] = f'疑似与前一桌（{prev_end}-{curr_start}）同一批客人'
        prev = row

    gs = gs.drop(columns=['_商品数'])
    return gs


# ── PDF 生成 ──────────────────────────────────────────────────────


def _p(text, style):
    """快捷创建 Paragraph"""
    return Paragraph(html_escape(str(text)), style)


def _p_html(html_text, style):
    """快捷创建带 HTML 的 Paragraph"""
    return Paragraph(html_text, style)


def _s(text):
    """快捷创建纯字符串单元格（不换行）"""
    return str(text)


def _validate_closure(gs, total_revenue, total_people, store_name):
    """校验数据总览各维度闭合，发现问题打印警告。"""
    errors = []

    # 1. 区域闭合（含"其他"警告）
    area_rev = {}
    area_ppl = {}
    for area in ['包间', '大厅', '户外']:
        mask = gs['_area'] == area
        area_rev[area] = gs.loc[mask, '订单收入'].sum()
        area_ppl[area] = int(gs.loc[mask, '团体人数'].sum())
    other_rev = total_revenue - sum(area_rev.values())
    other_ppl = total_people - sum(area_ppl.values())

    if abs(other_rev) > 0.01 or other_ppl > 0:
        other_tables = set(gs[~gs['_area'].isin(['包间', '大厅', '户外'])]['桌台'].unique())
        errors.append(f'区域分类存在"其他"：营业额 ¥{other_rev:,.2f}，{other_ppl} 人，桌台: {sorted(other_tables)}')

    sum_area_rev = sum(area_rev.values()) + other_rev
    if abs(total_revenue - sum_area_rev) > 0.1:
        errors.append(f'整体营业额 ¥{total_revenue:,.2f} ≠ 区域合计 ¥{sum_area_rev:,.2f}（差 ¥{total_revenue - sum_area_rev:,.2f}）')

    # 2. 午市/晚市闭合
    for meal, meal_label in [('午市', '午市（<16:00）'), ('晚市', '晚市（≥16:00）')]:
        meal_mask = gs['_meal'] == meal
        meal_rev = gs.loc[meal_mask, '订单收入'].sum()
        meal_ppl = int(gs.loc[meal_mask, '团体人数'].sum())

        meal_area_sum_rev = 0
        meal_area_sum_ppl = 0
        for area in ['包间', '大厅', '户外']:
            mask = meal_mask & (gs['_area'] == area)
            meal_area_sum_rev += gs.loc[mask, '订单收入'].sum()
            meal_area_sum_ppl += int(gs.loc[mask, '团体人数'].sum())

        gap_rev = meal_rev - meal_area_sum_rev
        gap_ppl = meal_ppl - meal_area_sum_ppl
        if abs(gap_rev) > 0.01 or gap_ppl != 0:
            errors.append(f'{meal_label}：区域合计 ¥{meal_area_sum_rev:,.2f}（{meal_area_sum_ppl}人）≠ {meal_label}整体 ¥{meal_rev:,.2f}（{meal_ppl}人），缺口 ¥{gap_rev:,.2f}（{gap_ppl}人）')

    # 3. 会员/非会员闭合
    member_rev = gs.loc[gs['是否会员'] == True, '订单收入'].sum()
    non_member_rev = gs.loc[gs['是否会员'] != True, '订单收入'].sum()
    if abs(total_revenue - (member_rev + non_member_rev)) > 0.1:
        errors.append(f'会员 ¥{member_rev:,.2f} + 非会员 ¥{non_member_rev:,.2f} ≠ 整体 ¥{total_revenue:,.2f}')

    if errors:
        print(f'\n  [数据闭合警告] {store_name}:')
        for e in errors:
            print(f'    ⚠ {e}')


MEMBER_CATEGORY_LABELS = [
    '乐享卡/纯储值卡消费（无折扣会员卡）',
    '折扣会员卡消费（有折扣会员卡）',
    '其他会员消费（非卡支付但关联会员）',
    '普通非会员消费（无会员信息）',
]


def classify_member_consumption(gs, orders_with_group):
    """按统计消费团体互斥划分会员及卡消费类型，并校验数量闭合。"""
    if '总优惠金额' not in orders_with_group.columns:
        raise ValueError('会员及卡消费类型判定缺少 POS 标准列：总优惠金额')
    order_lookup = {
        str(row['订单号']): row
        for _, row in orders_with_group.iterrows()
    }

    def _valid_member(value):
        return str(value).strip() not in ('', '-', 'nan', 'None')

    def _classify(order_ids):
        rows = [order_lookup[str(oid)] for oid in order_ids if str(oid) in order_lookup]
        has_member_card = any('会员卡' in str(row.get('支付方式', '')) for row in rows)
        discounts = [pd.to_numeric(row.get('总优惠金额', 0), errors='coerce') for row in rows]
        discount = sum(0 if pd.isna(value) else float(value) for value in discounts)
        has_member = any(
            _valid_member(row.get('会员姓名', '')) or _valid_member(row.get('会员手机号', ''))
            for row in rows
        )
        if has_member_card:
            return MEMBER_CATEGORY_LABELS[0] if abs(float(discount)) < 0.005 else MEMBER_CATEGORY_LABELS[1]
        if has_member:
            return MEMBER_CATEGORY_LABELS[2]
        return MEMBER_CATEGORY_LABELS[3]

    result = gs.copy()
    result['会员及卡消费类型'] = result['包含订单'].apply(_classify)
    result['是否会员'] = result['会员及卡消费类型'] != MEMBER_CATEGORY_LABELS[3]
    counts = result['会员及卡消费类型'].value_counts().reindex(MEMBER_CATEGORY_LABELS, fill_value=0)
    if int(counts.sum()) != len(result):
        raise ValueError(f'会员及卡消费类型数量不闭合：分类合计 {int(counts.sum())}，统计消费团体数 {len(result)}')
    return result, counts


def generate_pdf_report(gs, group_items, stats, items_df, store_name, target_date, output_path, unrecognized=None):
    """生成统计分析 + 索引表 + 逐团体详情的 PDF"""
    page = A3
    doc = SimpleDocTemplate(output_path, pagesize=page,
                            rightMargin=1.5*cm, leftMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('T', parent=styles['Title'], fontSize=18,
                                 textColor=colors.darkblue, spaceAfter=20, fontName=CHINESE_FONT)
    subtitle_style = ParagraphStyle('ST', parent=styles['Heading2'], fontSize=14,
                                    textColor=colors.darkred, spaceBefore=15,
                                    spaceAfter=10, fontName=CHINESE_FONT)
    normal_style = ParagraphStyle('N', parent=styles['Normal'], fontName=CHINESE_FONT, fontSize=10)
    cell_c = ParagraphStyle('CC', parent=normal_style, fontSize=8, leading=10, alignment=TA_CENTER)
    cell_l = ParagraphStyle('CL', parent=normal_style, fontSize=8, leading=10, alignment=TA_LEFT)
    opener_style = ParagraphStyle('Opener', parent=normal_style, fontSize=8, leading=11, alignment=TA_LEFT, wordSpace='CJK')
    section_title_style = ParagraphStyle('SecT', parent=subtitle_style, fontSize=12,
                                         spaceBefore=10, spaceAfter=8, fontName=CHINESE_FONT, leading=14)

    # 标题
    story.append(Paragraph(f'订单桌访合并报告（{store_name}）', title_style))
    story.append(Paragraph(f'营业日期: {target_date}    生成日期: {datetime.now().strftime("%Y-%m-%d %H:%M")}', normal_style))

    # 统计摘要
    total = len(gs)
    visited = len(gs[gs['桌访状态'] == '已桌访'])
    story.append(Paragraph(f'消费团体数: <b>{total}</b>；其中 已桌访: <b>{visited}</b>；未桌访: <b>{total - visited}</b>；覆盖率: <b>{visited / total * 100:.1f}%</b>' if total > 0 else '无数据', normal_style))
    story.append(Spacer(1, 0.5 * cm))

    # ── 统计分析（一、二、三节）──
    total_revenue = stats.get('统计范围内总营业额', gs['订单收入'].sum())
    total_people = stats.get('统计范围内消费总人数', gs['团体人数'].sum())
    avg_per_person = total_revenue / total_people if total_people > 0 else 0

    def _area(table_name):
        t = str(table_name)
        if t.startswith(('包间', '包房')): return '包间'
        if t.startswith(('大厅', '沙发')): return '大厅'
        if t.startswith('户外'): return '户外'
        return '其他'

    def _meal_period(start_time):
        if hasattr(start_time, 'hour'):
            return '午市' if start_time.hour < 16 else '晚市'
        return '未知'

    def _seg_stats(mask):
        sub = gs[mask]
        rev = sub['订单收入'].sum()
        ppl = int(sub['团体人数'].sum())
        arpu = rev / ppl if ppl > 0 else 0
        return rev, ppl, arpu

    gs['_area'] = gs['桌台'].apply(_area)
    gs['_meal'] = gs['开始'].apply(_meal_period)

    hdr = ['维度', '营业额', '百分比', '人数', '人均']
    rows = []
    def _pct(rev, base):
        return f'{rev / base * 100:.1f}%' if base > 0 else '-'
    def _row(label, rev, ppl, arpu, pct_text='', bold=False):
        prefix = '<b>' if bold else ''
        suffix = '</b>' if bold else ''
        return [
            Paragraph(html_escape(label), subtitle_style if bold else normal_style),
            Paragraph(f'{prefix}¥{rev:,.2f}{suffix}', normal_style),
            Paragraph(f'{prefix}{pct_text}{suffix}', normal_style),
            Paragraph(f'{prefix}{ppl} 人{suffix}', normal_style),
            Paragraph(f'{prefix}¥{arpu:,.2f}{suffix}', normal_style),
        ]

    # 整体
    rows.append(_row('整体', total_revenue, int(total_people), avg_per_person, '100.0%', bold=True))
    # 整体按区域
    for area in ['包间', '大厅', '户外']:
        rev, ppl, arpu = _seg_stats(gs['_area'] == area)
        rows.append(_row(f'　{area}', rev, ppl, arpu, _pct(rev, total_revenue)))
    # 午市
    lunch_mask = gs['_meal'] == '午市'
    lunch_rev, lunch_ppl, lunch_arpu = _seg_stats(lunch_mask)
    rows.append(_row('午市（<16:00）', lunch_rev, lunch_ppl, lunch_arpu, _pct(lunch_rev, total_revenue), bold=True))
    for area in ['包间', '大厅', '户外']:
        rev, ppl, arpu = _seg_stats(lunch_mask & (gs['_area'] == area))
        rows.append(_row(f'　{area}', rev, ppl, arpu, _pct(rev, lunch_rev)))
    # 晚市
    dinner_mask = gs['_meal'] == '晚市'
    dinner_rev, dinner_ppl, dinner_arpu = _seg_stats(dinner_mask)
    rows.append(_row('晚市（≥16:00）', dinner_rev, dinner_ppl, dinner_arpu, _pct(dinner_rev, total_revenue), bold=True))
    for area in ['包间', '大厅', '户外']:
        rev, ppl, arpu = _seg_stats(dinner_mask & (gs['_area'] == area))
        rows.append(_row(f'　{area}', rev, ppl, arpu, _pct(rev, dinner_rev)))
    # 会员与非会员（全天整体对比）
    member_mask = gs['是否会员'] == True
    rev, ppl, arpu = _seg_stats(member_mask)
    rows.append(_row('会员（全天）', rev, ppl, arpu, _pct(rev, total_revenue), bold=True))
    non_member_mask = gs['是否会员'] == False
    rev, ppl, arpu = _seg_stats(non_member_mask)
    rows.append(_row('非会员（全天）', rev, ppl, arpu, _pct(rev, total_revenue), bold=True))

    # ── 数据闭合校验 ──
    _validate_closure(gs, total_revenue, int(total_people), store_name)

    # 一、数据总览
    story.append(Paragraph('一、数据总览', subtitle_style))
    story.append(Spacer(1, 0.3 * cm))
    summary_data = [hdr] + rows
    summary_table = Table(summary_data, colWidths=[6.0*cm, 3.0*cm, 1.8*cm, 1.8*cm, 2.8*cm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#e8e8e8')),
        ('BACKGROUND', (0, 5), (-1, 5), colors.HexColor('#e8e8e8')),
        ('BACKGROUND', (0, 9), (-1, 9), colors.HexColor('#e8e8e8')),
        ('BACKGROUND', (0, 13), (-1, 13), colors.HexColor('#e8e8e8')),
    ]))
    story.append(summary_table)

    # 人数来源说明
    corrected_count = int(gs['人数修正'].sum()) if '人数修正' in gs.columns else 0
    if corrected_count > 0:
        note_style = ParagraphStyle('NoteStyle', parent=normal_style, fontSize=8,
                                     textColor=colors.darkgrey, leading=10)
        if corrected_count == len(gs):
            note = '注：所有消费团体人数均来自桌访数据。'
        else:
            note = f'注：{corrected_count} 个团体的人数已按桌访数据修正，总人数为修正后值；其余团体使用 POS 系统登记人数。'
        story.append(Paragraph(note, note_style))
    story.append(Spacer(1, 0.5 * cm))

    # 二、订单数量明细
    story.append(Paragraph('二、订单数量明细', subtitle_style))
    story.append(Spacer(1, 0.3 * cm))
    snack_orders = stats.get('零食购买订单数', 0)
    snack_groups = stats.get('零食购买团体数', 0)
    scattered_orders = stats.get('零散小单订单数', 0)
    scattered_groups = stats.get('零散小单团体数', 0)
    packing_orders = stats.get('打包用品订单数', 0)
    packing_groups = stats.get('打包用品团体数', 0)
    bar_orders = stats.get('吧台订单数', 0)
    bar_groups = stats.get('吧台团体数', 0)
    merged_groups_count = stats.get('合并后消费团体数', 0)
    order_detail_data = [
        ['项目', '数量'],
        ['原始订单数（含外卖）', str(stats.get('原始订单数', 0))],
        ['- 外卖（外点自取）订单数', str(stats.get('外点自取订单数', 0))],
        ['- 非堂食订单数', str(stats.get('非堂食订单数', 0))],
        ['- 免单（零收入）订单数', str(stats.get('免单订单行数(已剔除)', 0))],
        ['- 被合并的订单数（含小单和零食单）', str(stats.get('被合并的订单数', 0))],
        ['= 合并后消费团体数', str(merged_groups_count)],
        ['- 零食购买团体数', f'{snack_groups} 团（{snack_orders} 单）' if snack_groups > 0 else '0'],
        ['- 打包用品团体数', f'{packing_groups} 团（{packing_orders} 单）' if packing_groups > 0 else '0'],
        ['- 零散小单团体数', f'{scattered_groups} 团（{scattered_orders} 单）' if scattered_groups > 0 else '0'],
        ['- 吧台团体数', f'{bar_groups} 团（{bar_orders} 单）' if bar_groups > 0 else '0'],
        ['= 统计消费团体数', str(stats.get('统计订单数', len(gs)))],
    ]
    order_detail_table = Table(order_detail_data, colWidths=[7.5*cm, 3.5*cm])
    order_detail_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -2), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.whitesmoke, colors.white]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
        ('BACKGROUND', (0, 4), (0, 4), colors.HexColor('#f0f0f0')),
    ]))
    story.append(order_detail_table)
    formula_style = ParagraphStyle('Formula', parent=normal_style, fontSize=9, textColor=colors.darkgrey, leading=12)
    story.append(Paragraph('<b>计算公式：</b>合并后消费团体数 = 原始订单数 − 外卖 − 非堂食 − 免单(零收入) − 被合并；统计消费团体数 = 合并后团体数 − 零食 − 打包 − 零散 − 吧台', formula_style))
    member_counts = gs['会员及卡消费类型'].value_counts().reindex(MEMBER_CATEGORY_LABELS, fill_value=0)
    member_total = int(member_counts.sum())
    member_data = [['会员及卡消费类型（判定口径）', '团体数', '占总团体比']]
    for label in MEMBER_CATEGORY_LABELS:
        count = int(member_counts[label])
        member_data.append([label, f'{count} 团', f'{count / member_total * 100:.2f}%' if member_total else '0.00%'])
    member_data.append(['= 统计消费团体数（全部）', f'{member_total} 团', '100.00%' if member_total else '0.00%'])
    member_table = Table(member_data, colWidths=[7.5*cm, 2.2*cm, 2.5*cm])
    member_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.whitesmoke, colors.white]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
    ]))
    story.append(Spacer(1, 0.35 * cm))
    story.append(member_table)
    story.append(Paragraph('<b>判定规则：</b>1. 乐享卡/纯储值卡：支付方式含“会员卡”且总优惠金额合计为 0；2. 折扣会员卡：支付方式含“会员卡”且总优惠金额合计非 0；3. 其他会员：支付方式不含“会员卡”但有关联会员姓名/手机号。', formula_style))
    story.append(Spacer(1, 0.5 * cm))

    # 三、客单价区间分布
    story.append(Paragraph('三、客单价区间分布', subtitle_style))
    story.append(Spacer(1, 0.3 * cm))
    total_orders = len(gs)
    r300_df = gs[gs['人均消费'] >= 300]
    r200_df = gs[(gs['人均消费'] >= 200) & (gs['人均消费'] < 300)]
    r150_df = gs[(gs['人均消费'] >= 150) & (gs['人均消费'] < 200)]
    r100_df = gs[(gs['人均消费'] >= 100) & (gs['人均消费'] < 150)]
    r_below_df = gs[gs['人均消费'] < 100]
    r300, r200 = len(r300_df), len(r200_df)
    r150, r100, r_below = len(r150_df), len(r100_df), len(r_below_df)

    def _openers(df):
        """提取开单人，按开单数量从高到低排序，格式为「姓名(数量)」"""
        names = df['开单人'].dropna().astype(str).str.strip()
        names = names[names != '']
        if len(names) == 0:
            return _p('-', opener_style)
        counts = names.value_counts()
        text = '、'.join(f'{n}({c})' for n, c in counts.items())
        return Paragraph(html_escape(text), opener_style)

    pct = lambda c: f'{c / total_orders * 100:.1f}%' if total_orders > 0 else '0.0%'
    range_data = [
        ['客单价区间', '订单数', '占比', '开单人'],
        [_p('300元以上', cell_c), _p(str(r300), cell_c), _p(pct(r300), cell_c), _openers(r300_df)],
        [_p('200~300元', cell_c), _p(str(r200), cell_c), _p(pct(r200), cell_c), _openers(r200_df)],
        [_p('150~200元', cell_c), _p(str(r150), cell_c), _p(pct(r150), cell_c), _p('', cell_c)],
        [_p('100~150元', cell_c), _p(str(r100), cell_c), _p(pct(r100), cell_c), _p('', cell_c)],
        [_p('100元以下', cell_c), _p(str(r_below), cell_c), _p(pct(r_below), cell_c), _p('', cell_c)],
        [_p('合计', cell_c), _p(str(total_orders), cell_c), _p('100.0%', cell_c), _p('', cell_c)],
    ]
    range_table = Table(range_data, colWidths=[2.5*cm, 1.5*cm, 1.5*cm, 7*cm])
    range_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
        ('ALIGN', (-1, 1), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.whitesmoke, colors.white]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
    ]))
    story.append(range_table)

    # 四、开单人统计
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph('四、开单人统计', subtitle_style))
    story.append(Spacer(1, 0.3 * cm))
    opener_clean = gs['开单人'].dropna().astype(str).str.strip()
    opener_clean = opener_clean[opener_clean != '']
    opener_counts = opener_clean.value_counts()
    opener_amounts = gs.loc[opener_clean.index, '订单收入'].groupby(opener_clean).sum()
    opener_data = [['开单人', '开单数量', '开单金额']]
    for name, cnt in opener_counts.items():
        label = f'{name}（扫码点餐）' if name == '顾客/系统' else name
        amt = opener_amounts.get(name, 0)
        opener_data.append([label, str(cnt), f'¥{amt:,.2f}'])
    total_amt = opener_amounts.sum()
    opener_data.append(['合计', str(opener_counts.sum()), f'¥{total_amt:,.2f}'])
    opener_table = Table(opener_data, colWidths=[4*cm, 2.5*cm, 3*cm])
    opener_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.whitesmoke, colors.white]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
    ]))
    story.append(opener_table)

    # 五、桌访人统计
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph('五、桌访人统计', subtitle_style))
    story.append(Spacer(1, 0.3 * cm))
    waiter_all = []
    for val in gs['桌访人'].dropna().astype(str).str.strip():
        if val:
            waiter_all.extend(w.strip() for w in val.split('、') if w.strip())
    waiter_counts = pd.Series(waiter_all).value_counts()
    waiter_data = [['桌访人', '桌访数量']]
    for name, cnt in waiter_counts.items():
        waiter_data.append([name, str(cnt)])
    waiter_data.append(['合计', str(waiter_counts.sum())])
    waiter_table = Table(waiter_data, colWidths=[5*cm, 3*cm])
    waiter_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('ALIGN', (1, 1), (1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.whitesmoke, colors.white]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
    ]))
    story.append(waiter_table)

    is_baoli = '保利' in str(store_name)

    # 六、重点菜品销售统计
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph('六、重点菜品销售统计', subtitle_style))
    story.append(Spacer(1, 0.3 * cm))
    if is_baoli:
        dish_stats = _compute_baoli_dish_stats(items_df)
    else:
        dish_stats = compute_dish_stats(items_df)
    dish_data = [['菜品名称', '销售份数']] + [[name, str(qty)] for name, qty in dish_stats]
    story.append(_make_dish_table(dish_data))

    # 七、重点新品销售统计 / 保利店午晚热销统计
    story.append(Spacer(1, 0.5 * cm))
    if is_baoli:
        story.append(Paragraph('七、午晚热销统计', subtitle_style))
        story.append(Spacer(1, 0.3 * cm))
        lunch_top, dinner_top = compute_lunch_dinner_top5(items_df, gs)

        story.append(Paragraph('<b>午市（&lt;16:00）Top 6</b>', normal_style))
        story.append(Spacer(1, 0.15 * cm))
        lunch_data = [['菜品名称', '销售份数']] + [[name, str(qty)] for name, qty in lunch_top]
        if len(lunch_data) == 1:
            lunch_data.append(['-', '0'])
        story.append(_make_dish_table(lunch_data))
        story.append(Spacer(1, 0.3 * cm))

        story.append(Paragraph('<b>晚市（≥16:00）Top 6</b>', normal_style))
        story.append(Spacer(1, 0.15 * cm))
        dinner_data = [['菜品名称', '销售份数']] + [[name, str(qty)] for name, qty in dinner_top]
        if len(dinner_data) == 1:
            dinner_data.append(['-', '0'])
        story.append(_make_dish_table(dinner_data))
    else:
        story.append(Paragraph('七、重点新品销售统计', subtitle_style))
        story.append(Spacer(1, 0.3 * cm))
        new_stats = compute_new_item_stats(items_df)
        new_data = [['商品名称', '销售份数']] + [[name, str(qty)] for name, qty in new_stats]
        story.append(_make_dish_table(new_data))

    # 八、疑似异常汇总
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph('八、疑似异常汇总', subtitle_style))
    story.append(Spacer(1, 0.3 * cm))
    anomaly_df = gs[gs['异常标记'] != '']
    if len(anomaly_df) > 0:
        anomaly_summary_data = [['桌台', '首单(末8位)', '人数', '商品数', '人均', '异常说明']]
        for _, r in anomaly_df.iterrows():
            oids = r['包含订单']
            sub_items = items_df[items_df['订单号'].isin(oids)]
            dish_cnt = int(sub_items['数量'].fillna(0).sum())
            anomaly_summary_data.append([
                str(r['桌台']),
                str(r['首单订单号'])[-8:],
                str(int(r['团体人数'])),
                str(dish_cnt),
                f"¥{r['人均消费']:.0f}",
                str(r['异常标记']),
            ])
        anomaly_summary_table = Table(anomaly_summary_data,
            colWidths=[2.5*cm, 2.0*cm, 1.0*cm, 1.0*cm, 1.5*cm, 14*cm])
        anomaly_summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(anomaly_summary_table)
    else:
        story.append(Paragraph('本报告期无疑似异常消费团体。', normal_style))

    story.append(PageBreak())

    # 排序：桌台 → 日期 → 下单时间
    display_df = gs.copy()
    display_df['_date'] = display_df['开始'].apply(lambda t: t.strftime('%Y-%m-%d') if hasattr(t, 'strftime') else '')
    display_df = display_df.sort_values(['桌台', '_date', '开始']).drop(columns=['_date']).reset_index(drop=True)

    # ── 索引表 ──
    story.append(Paragraph('九、订单索引（按桌台与时间）', subtitle_style))
    # 桌访覆盖率
    idx_visited = len(gs[gs['桌访状态'] == '已桌访'])
    idx_total = len(gs)
    idx_coverage = idx_visited / idx_total * 100 if idx_total > 0 else 0
    coverage_style = ParagraphStyle('CoverageStyle', parent=normal_style, fontSize=10, leading=14)
    story.append(Paragraph(f'桌访覆盖率：<b>{idx_visited}</b> / <b>{idx_total}</b> = <b>{idx_coverage:.1f}%</b>', coverage_style))

    # 未匹配的桌访记录（有桌访但无对应订单号）
    if unrecognized is not None and len(unrecognized) > 0:
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(f'未匹配桌访记录（{len(unrecognized)} 条，无对应订单号）：', coverage_style))
        ur_cell_style = ParagraphStyle('UrCell', parent=normal_style, fontSize=7, leading=9, alignment=TA_LEFT, wordSpace='CJK')
        ur_data = [[
            '序号', '服务员',
            '创建时间', '桌台号',
            '就餐人数', '支付金额',
            '下单时间', '会员状态',
            '语音转录',
        ]]
        for k, (_, ur) in enumerate(unrecognized.iterrows(), 1):
            transcript = str(ur.get('语音转录', ''))
            if transcript in ('nan', '', '-', 'None'):
                transcript = '-'
            table_no = str(ur.get('桌台号', '-'))
            if table_no in ('nan', '', 'None'):
                table_no = '-'
            create_time = str(ur.get('创建时间', '-'))
            if create_time in ('nan', '', 'None'):
                create_time = '-'
            people = ur.get('就餐人数', '')
            try:
                people = str(int(float(people)))
            except (ValueError, TypeError):
                people = '-'
            waiter = str(ur.get('服务员', '-'))
            if waiter in ('nan', '', 'None'):
                waiter = '-'
            amount = ur.get('支付金额', '')
            try:
                amount = f'¥{float(amount):.0f}'
            except (ValueError, TypeError):
                amount = '-'
            order_time = str(ur.get('下单时间', '-'))
            if order_time in ('nan', '', 'None'):
                order_time = '-'
            member = str(ur.get('会员状态', '-'))
            if member in ('nan', '', 'None'):
                member = '-'
            ur_data.append([
                _p(str(k), ur_cell_style),
                _p(waiter, ur_cell_style),
                _p(create_time, ur_cell_style),
                _p(table_no, ur_cell_style),
                _p(people, ur_cell_style),
                _p(amount, ur_cell_style),
                _p(order_time, ur_cell_style),
                _p(member, ur_cell_style),
                Paragraph(html_escape(transcript), ur_cell_style),
            ])
        ur_table = Table(ur_data, colWidths=[0.7*cm, 1.5*cm, 2.4*cm, 1.4*cm, 1.0*cm, 1.4*cm, 2.2*cm, 1.2*cm, 11.2*cm])
        ur_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ('LEFTPADDING', (0, 0), (-1, -1), 2),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(ur_table)
    story.append(Spacer(1, 0.3 * cm))

    # 索引表用 Paragraph 样式（允许被合并订单号换行）
    index_cell_left = ParagraphStyle('IdxCL', parent=normal_style, fontSize=7, leading=9, alignment=TA_LEFT)

    index_data = [[
        '序号', '桌台', '首单订单号',
        '被合并订单号',
        '日期', '下单时间', '结账时间', '人数',
        '总金额', '人均', '合并数',
        '开单人', '结账人', '桌访人',
        '桌访状态', '疑似异常',
    ]]

    for i, row in display_df.iterrows():
        oid_tail = str(row['首单订单号'])[-8:]
        arpu_s = f"¥{row['人均消费']:.0f}"
        arpu_alert = 40 if '保利' in str(store_name) else 100
        arpu_cell = _p_html(f'<font color="red">{arpu_s}</font>', cell_c) if row['人均消费'] < arpu_alert else _p(arpu_s, cell_c)
        status_s = row['桌访状态']
        status_cell = _p_html(f'<font color="red">{status_s}</font>', cell_c) if status_s == '未桌访' else _p(status_s, cell_c)

        # 被合并订单号：排除首单，用 <br/> 换行
        merged_ids = [str(oid) for oid in row['包含订单'] if str(oid) != str(row['首单订单号'])]
        if merged_ids:
            merged_cell = Paragraph('<br/>'.join(html_escape(oid) for oid in merged_ids), index_cell_left)
        else:
            merged_cell = _p('-', cell_c)

        # 疑似异常标记
        anomaly = str(row.get('异常标记', ''))
        anomaly_cell = _p_html(f'<font color="red">{html_escape(anomaly)}</font>', cell_l) if anomaly else _p('-', cell_c)

        index_data.append([
            _p(i + 1, cell_c),
            _p(str(row['桌台']), cell_l),
            _p(oid_tail, cell_c),
            merged_cell,
            _p(row['开始'].strftime('%m-%d') if hasattr(row['开始'], 'strftime') else '-', cell_c),
            _p(row['开始'].strftime('%H:%M') if hasattr(row['开始'], 'strftime') else '-', cell_c),
            _p(row['结束'].strftime('%H:%M') if hasattr(row['结束'], 'strftime') else '-', cell_c),
            _p(int(row['团体人数']), cell_c),
            _p(f"¥{row['团体总额']:.0f}", cell_c),
            arpu_cell,
            _p(int(row['订单数']), cell_c),
            _p(row.get('开单人', ''), cell_c),
            _p(row.get('结账人', ''), cell_c),
            _p(row.get('桌访人', ''), cell_c),
            status_cell,
            anomaly_cell,
        ])

    idx_widths = [0.7*cm, 2.2*cm, 2.0*cm, 2.5*cm, 1.5*cm, 1.6*cm, 1.6*cm, 1.0*cm,
                  1.6*cm, 1.5*cm, 1.0*cm, 2.2*cm, 2.2*cm, 2.8*cm, 2.2*cm, 3.0*cm]
    idx_table = Table(index_data, colWidths=idx_widths, repeatRows=1)
    idx_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
    ]))
    story.append(idx_table)
    story.append(PageBreak())

    # ── 逐团体详情 ──
    for i, row in display_df.iterrows():
        table_name = row['桌台']
        group_id = row['消费团体ID']
        rank = i + 1

        story.append(Paragraph(f"{rank}. 桌台: {table_name} (消费团体ID: {group_id})", section_title_style))

        # 基本信息表
        people_str = f"{int(row['团体人数'])} 人"
        if row.get('人数修正', False):
            people_str += '（桌访修正）'

        _ip = lambda t: Paragraph(html_escape(str(t)), ParagraphStyle('InfoCell', parent=normal_style, fontSize=10))
        info_rows = [
            ['项目', '内容'],
            ['首单订单号', str(row['首单订单号'])],
            ['下单时间', row['开始'].strftime('%Y-%m-%d %H:%M:%S') if hasattr(row['开始'], 'strftime') else '-'],
            ['结账时间', row['结束'].strftime('%Y-%m-%d %H:%M:%S') if hasattr(row['结束'], 'strftime') else '-'],
            ['就餐人数', people_str],
            ['订单总金额', f"¥{row['团体总额']:.2f}"],
            ['订单收入', f"¥{row['订单收入']:.2f}"],
            ['人均消费', f"¥{row['人均消费']:.2f}"],
            ['被合并订单数', f"{int(row['订单数'])} 单"],
            [_ip('开单人'), _ip(row.get('开单人', '-'))],
            [_ip('结账人'), _ip(row.get('结账人', '-'))],
            [_ip('桌访人'), _ip(row.get('桌访人', '-') or '-')],
        ]
        if row.get('整单备注') and str(row.get('整单备注', '')) not in ('nan', '-', ''):
            info_rows.append(['整单备注', str(row['整单备注'])])

        info_table = Table(info_rows, colWidths=[4*cm, 18*cm])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 0.3 * cm))

        # 疑似异常提示
        anomaly = str(row.get('异常标记', ''))
        if anomaly:
            story.append(Paragraph(f'<font color="red"><b>疑似异常：</b>{html_escape(anomaly)}</font>', normal_style))
            story.append(Spacer(1, 0.3 * cm))

        # 被合并的子订单
        if row['订单数'] > 1:
            story.append(Paragraph('<b>被合并的子订单:</b>', normal_style))
            for oid, otime in row.get('子订单下单时间', []):
                time_str = otime.strftime('%H:%M:%S') if hasattr(otime, 'strftime') else str(otime)
                story.append(Paragraph(f"&nbsp;&nbsp;{oid} | 下单: {time_str}", normal_style))
            story.append(Spacer(1, 0.3 * cm))

        # 商品明细
        story.append(Paragraph('<b>商品明细:</b>', normal_style))
        merged_multi = int(row['订单数']) > 1
        if merged_multi:
            story.append(Paragraph('<i>以下按原订单号分列，便于核对合并是否合理。</i>', normal_style))
            story.append(Spacer(1, 0.2 * cm))

        items_df_group = group_items.get((table_name, group_id))
        _item_table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
            ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
        ])
        _item_col_widths = [1*cm, 5*cm, 1.2*cm, 1.5*cm, 1.5*cm, 3*cm]

        if items_df_group is not None and len(items_df_group) > 0:
            subs = list(iter_subsections_for_report(items_df_group, row['包含订单'], merged_multi))
            if not subs:
                story.append(Paragraph('暂无商品明细', normal_style))
            else:
                for label, sub_df in subs:
                    if label is not None:
                        story.append(Paragraph(f'<b>子订单: {label}</b>', normal_style))
                        story.append(Spacer(1, 0.15 * cm))
                    item_data = [['序号', '商品名称', '数量', '单价', '金额', '商品中类']]
                    for j, (_, item_row) in enumerate(sub_df.iterrows(), start=1):
                        item_data.append([
                            str(j),
                            str(item_row['商品名称'])[:20],
                            str(int(item_row['数量'])),
                            f"¥{item_row['单价']:.2f}",
                            f"¥{item_row['菜品合计金额']:.2f}",
                            str(item_row['商品中类'])[:15],
                        ])
                    item_table = Table(item_data, colWidths=_item_col_widths)
                    item_table.setStyle(_item_table_style)
                    story.append(item_table)
                    story.append(Spacer(1, 0.3 * cm))
        else:
            story.append(Paragraph('暂无商品明细', normal_style))
        story.append(Spacer(1, 0.3 * cm))

        # 桌访内容
        feedback_records = row.get('桌访记录', [])
        if feedback_records:
            n = len(feedback_records)
            label = f'【桌访内容】（{n} 条记录）' if n > 1 else '【桌访内容】'
            story.append(Paragraph(f'<b>{label}</b>', normal_style))
            story.append(Spacer(1, 0.15 * cm))

            for j, rec in enumerate(feedback_records, 1):
                waiter = rec.get('服务员', '-')
                create_time = rec.get('创建时间', '-')
                score = rec.get('总体满意度评分', '-')
                transcript = str(rec.get('语音转录', '-')).strip()
                if len(transcript) > 300:
                    transcript = transcript[:300] + '...'

                prefix = f'记录 {j} - ' if n > 1 else ''
                story.append(Paragraph(
                    f'<b>{prefix}服务员: {html_escape(str(waiter))}</b> | '
                    f'创建时间: {html_escape(str(create_time))} | '
                    f'满意度: {html_escape(str(score))}',
                    normal_style
                ))
                # 金额匹配的桌访标注
                if rec.get('_amount_matched') is True:
                    story.append(Paragraph(
                        f'<font color="#D35400"><b>注：此桌访订单号缺失，通过桌台号与支付金额一致匹配至本订单。</b></font>',
                        ParagraphStyle('AmtMatchNote', parent=normal_style, fontSize=9, textColor=colors.HexColor('#D35400'))
                    ))
                story.append(Paragraph(f'"{html_escape(transcript)}"', normal_style))
                story.append(Spacer(1, 0.2 * cm))
        else:
            story.append(Paragraph('<b>【桌访内容】</b>', normal_style))
            story.append(Paragraph('<font color="red">⚠ 未进行桌访</font>', normal_style))

        if i < len(display_df) - 1:
            story.append(PageBreak())

    doc.build(story)
    print(f'PDF 报告已生成: {output_path}')


# ── Markdown / Excel 输出 ─────────────────────────────────────────


def generate_markdown_report(gs, stats, store_name, target_date, output_path, unrecognized, items_df):
    """生成结论先行的 Markdown 报告"""
    total = len(gs)
    visited = len(gs[gs['桌访状态'] == '已桌访'])
    uncovered = total - visited
    coverage = (visited / total * 100) if total > 0 else 0

    lines = [
        f'# 订单桌访合并报告（{store_name} {target_date}）',
        '', '## 一、先说结论', '',
        f'- 消费团体总数：**{total}**',
        f'- 已桌访：**{visited}**（覆盖率 **{coverage:.1f}%**）',
        f'- 未桌访：**{uncovered}**',
    ]
    if len(unrecognized) > 0:
        lines.append(f'- 桌访中未识别订单：**{len(unrecognized)}** 条')

    lines += ['', '## 二、订单数量明细', '',
              '| 项目 | 数量 |', '|------|------|',
              f"| 原始订单数（含外卖） | {stats.get('原始订单数', 0)} |",
              f"| - 外卖（外点自取）订单数 | {stats.get('外点自取订单数', 0)} |",
              f"| - 非堂食订单数 | {stats.get('非堂食订单数', 0)} |",
              f"| - 免单（零收入）订单数 | {stats.get('免单订单行数(已剔除)', 0)} |",
              f"| - 被合并的订单数（含小单和零食单） | {stats.get('被合并的订单数', 0)} |",
              f"| = 合并后消费团体数 | {stats.get('合并后消费团体数', 0)} |",
              f"| - 零食购买团体数 | {stats.get('零食购买团体数', 0)} 团（{stats.get('零食购买订单数', 0)} 单） |",
              f"| - 打包用品团体数 | {stats.get('打包用品团体数', 0)} 团（{stats.get('打包用品订单数', 0)} 单） |",
              f"| - 零散小单团体数 | {stats.get('零散小单团体数', 0)} 团（{stats.get('零散小单订单数', 0)} 单） |",
              f"| - 吧台团体数 | {stats.get('吧台团体数', 0)} 团（{stats.get('吧台订单数', 0)} 单） |",
              f"| = 统计消费团体数 | {stats.get('统计订单数', total)} |", '',
              '**计算公式：** 合并后消费团体数 = 原始订单数 − 外卖 − 非堂食 − 免单（零收入）− 被合并；统计消费团体数 = 合并后团体数 − 零食 − 打包 − 零散 − 吧台。', '',
              '| 会员及卡消费类型（判定口径） | 团体数 | 占总团体比 |',
              '|------|------:|------:|']
    member_counts = gs['会员及卡消费类型'].value_counts().reindex(MEMBER_CATEGORY_LABELS, fill_value=0)
    for label in MEMBER_CATEGORY_LABELS:
        count = int(member_counts[label])
        lines.append(f'| {label} | {count} 团 | {count / total * 100:.2f}% |' if total else f'| {label} | 0 团 | 0.00% |')
    lines += [f'| **= 统计消费团体数（全部）** | **{total} 团** | **{"100.00%" if total else "0.00%"}** |', '',
              '**判定规则：** 1. 乐享卡/纯储值卡：支付方式含“会员卡”且总优惠金额合计为 0；2. 折扣会员卡：支付方式含“会员卡”且总优惠金额合计非 0；3. 其他会员：支付方式不含“会员卡”但有关联会员姓名/手机号。', '',
              '## 三、已桌访的消费团体', '']
    visited_df = gs[gs['桌访状态'] == '已桌访'].sort_values(['桌台', '开始'])
    if not visited_df.empty:
        lines.append('| 桌台 | 首单(末8位) | 时间 | 人数 | 总额 | 人均 | 开单人 | 结账人 | 桌访人 | 疑似异常 |')
        lines.append('|------|------------|------|------|------|------|--------|--------|--------|----------|')
        for _, r in visited_df.iterrows():
            t = r['开始'].strftime('%H:%M') if hasattr(r['开始'], 'strftime') else '-'
            anomaly = str(r.get('异常标记', ''))
            lines.append(f"| {r['桌台']} | ...{str(r['首单订单号'])[-8:]} | {t} | {int(r['团体人数'])} | ¥{r['团体总额']:.0f} | ¥{r['人均消费']:.0f} | {r.get('开单人','')} | {r.get('结账人','')} | {r.get('桌访人','')} | {anomaly if anomaly else '-'} |")

    lines += ['', '## 四、未桌访的消费团体（按金额降序）', '']
    uncovered_df = gs[gs['桌访状态'] == '未桌访'].sort_values('团体总额', ascending=False)
    if not uncovered_df.empty:
        lines.append('| 桌台 | 首单(末8位) | 时间 | 人数 | 总额 | 人均 | 开单人 | 结账人 | 备注 | 疑似异常 |')
        lines.append('|------|------------|------|------|------|------|--------|--------|------|----------|')
        for _, r in uncovered_df.iterrows():
            t = r['开始'].strftime('%H:%M') if hasattr(r['开始'], 'strftime') else '-'
            remark = str(r.get('整单备注', '-'))
            if remark in ('nan', '-'):
                remark = '-'
            anomaly = str(r.get('异常标记', ''))
            lines.append(f"| {r['桌台']} | ...{str(r['首单订单号'])[-8:]} | {t} | {int(r['团体人数'])} | ¥{r['团体总额']:.0f} | ¥{r['人均消费']:.0f} | {r.get('开单人','')} | {r.get('结账人','')} | {remark} | {anomaly if anomaly else '-'} |")

    # 五、开单人统计
    lines += ['', '## 五、开单人统计', '']
    opener_clean = gs['开单人'].dropna().astype(str).str.strip()
    opener_clean = opener_clean[opener_clean != '']
    opener_counts = opener_clean.value_counts()
    opener_amounts = gs.loc[opener_clean.index, '订单收入'].groupby(opener_clean).sum()
    lines.append('| 开单人 | 开单数量 | 开单金额 |')
    lines.append('|--------|----------|----------|')
    for name, cnt in opener_counts.items():
        label = f'{name}（扫码点餐）' if name == '顾客/系统' else name
        amt = opener_amounts.get(name, 0)
        lines.append(f'| {label} | {cnt} | ¥{amt:,.2f} |')
    total_amt = opener_amounts.sum()
    lines.append(f'| **合计** | **{opener_counts.sum()}** | **¥{total_amt:,.2f}** |')

    # 六、桌访人统计
    lines += ['', '## 六、桌访人统计', '']
    waiter_all = []
    for val in gs['桌访人'].dropna().astype(str).str.strip():
        if val:
            waiter_all.extend(w.strip() for w in val.split('、') if w.strip())
    waiter_counts = pd.Series(waiter_all).value_counts()
    lines.append('| 桌访人 | 桌访数量 |')
    lines.append('|--------|----------|')
    for name, cnt in waiter_counts.items():
        lines.append(f'| {name} | {cnt} |')
    lines.append(f'| **合计** | **{waiter_counts.sum()}** |')

    is_baoli_md = '保利' in str(store_name)

    # 七、重点菜品销售统计
    lines += ['', '## 七、重点菜品销售统计', '']
    lines.append('| 菜品名称 | 销售份数 |')
    lines.append('|----------|----------|')
    md_dish_stats = _compute_baoli_dish_stats(items_df) if is_baoli_md else compute_dish_stats(items_df)
    for name, qty in md_dish_stats:
        lines.append(f'| {name} | {qty} |')

    # 七、重点新品销售统计 / 保利店午晚热销统计
    if is_baoli_md:
        lines += ['', '## 八、午晚热销统计', '']
        lunch_top, dinner_top = compute_lunch_dinner_top5(items_df, gs)
        lines += ['', '### 午市（<16:00）Top 6', '']
        lines.append('| 菜品名称 | 销售份数 |')
        lines.append('|----------|----------|')
        for name, qty in lunch_top:
            lines.append(f'| {name} | {qty} |')
        if not lunch_top:
            lines.append('| - | 0 |')
        lines += ['', '### 晚市（≥16:00）Top 6', '']
        lines.append('| 菜品名称 | 销售份数 |')
        lines.append('|----------|----------|')
        for name, qty in dinner_top:
            lines.append(f'| {name} | {qty} |')
        if not dinner_top:
            lines.append('| - | 0 |')
    else:
        lines += ['', '## 八、重点新品销售统计', '']
        lines.append('| 商品名称 | 销售份数 |')
        lines.append('|----------|----------|')
        for name, qty in compute_new_item_stats(items_df):
            lines.append(f'| {name} | {qty} |')

    if len(unrecognized) > 0:
        lines += ['', '## 九、未匹配桌访记录', '',
                  '以下桌访记录因缺少订单号，无法关联到具体消费团体：', '',
                  '| 序号 | 服务员 | 创建时间 | 桌台号 | 就餐人数 | 支付金额 | 下单时间 | 会员状态 | 语音转录 |',
                  '|------|--------|----------|--------|----------|----------|----------|----------|----------|']
        for k, (_, ur) in enumerate(unrecognized.iterrows(), 1):
            transcript = str(ur.get('语音转录', ''))
            if transcript in ('nan', '', '-', 'None'):
                transcript = '-'
            table_no = str(ur.get('桌台号', '-'))
            if table_no in ('nan', '', 'None'):
                table_no = '-'
            create_time = str(ur.get('创建时间', '-'))
            if create_time in ('nan', '', 'None'):
                create_time = '-'
            people = ur.get('就餐人数', '')
            try:
                people = str(int(float(people)))
            except (ValueError, TypeError):
                people = '-'
            waiter = str(ur.get('服务员', '-'))
            if waiter in ('nan', '', 'None'):
                waiter = '-'
            amount = ur.get('支付金额', '')
            try:
                amount = f'¥{float(amount):.0f}'
            except (ValueError, TypeError):
                amount = '-'
            order_time = str(ur.get('下单时间', '-'))
            if order_time in ('nan', '', 'None'):
                order_time = '-'
            member = str(ur.get('会员状态', '-'))
            if member in ('nan', '', 'None'):
                member = '-'
            lines.append(f'| {k} | {waiter} | {create_time} | {table_no} | {people} | {amount} | {order_time} | {member} | {transcript} |')
        lines.append('')

    lines += ['', '## 十、数据质量说明', '',
              f'- 消费团体数: {total}',
              f'- 桌访覆盖率: {coverage:.1f}%', '']

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


# ── 主程序 ────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description='订单与桌访合并工具 v3')
    parser.add_argument('--excel', required=True, help='POS 订单 Excel')
    parser.add_argument('--csv', required=True, help='桌访 CSV')
    parser.add_argument('--store', help='门店名称（不传则自动推断）')
    parser.add_argument('--output-dir', help='输出目录')
    args = parser.parse_args()

    target_date, target_date_end = extract_date_from_excel(args.excel)
    output_dir = args.output_dir or os.path.join(os.path.dirname(os.path.abspath(args.excel)), 'output')
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: 完整订单处理 pipeline
    print('=' * 50)
    print('订单与桌访合并工具 v2')
    print('=' * 50)
    print(f'\n[1/5] 加载并处理订单...')
    gs, gi, stats, items_clean, orders_with_group = load_and_process_orders(args.excel)
    print(f'  消费团体数: {len(gs)}（已过滤免单/零食/零散小单）')

    # Step 2: 加载桌访
    print(f'\n[2/5] 加载桌访 CSV...')
    csv_valid, csv_unrecognized = load_csv_feedback(args.csv, target_date=target_date, target_date_end=target_date_end)
    print(f'  有效记录: {len(csv_valid)}，未识别: {len(csv_unrecognized)}')

    # Step 3: 确定门店
    store_name = args.store
    if not store_name:
        store_name, n = infer_store(orders_with_group, csv_valid)
        print(f'  自动推断门店: {store_name}（匹配 {n} 单）')
    else:
        print(f'  指定门店: {store_name}')

    if store_name and '店面' in csv_valid.columns:
        csv_valid = csv_valid[csv_valid['店面'] == store_name].copy()
        if '店面' in csv_unrecognized.columns:
            csv_unrecognized = csv_unrecognized[csv_unrecognized['店面'] == store_name].copy()

    # Step 3.5: 有订单号但 POS 中不存在的记录，也纳入三选二模糊匹配
    if len(csv_valid) > 0:
        pos_order_ids = set(orders_with_group['订单号'].astype(str))
        valid_has_pos = csv_valid['订单号'].astype(str).isin(pos_order_ids)
        valid_no_pos = csv_valid[~valid_has_pos].copy()
        if len(valid_no_pos) > 0:
            csv_unrecognized = pd.concat([csv_unrecognized, valid_no_pos], ignore_index=True)
            csv_valid = csv_valid[valid_has_pos].copy()
            print(f'  订单号未匹配: {len(valid_no_pos)} 条（有订单号但POS中不存在，转入三选二匹配）')

    # Step 3.6: 通过桌台号+金额+时间三选二匹配无订单号的桌访记录
    amount_matched_count = 0
    if len(csv_unrecognized) > 0:
        amount_matched, csv_unrecognized = match_unrecognized_by_table_amount(
            csv_unrecognized, orders_with_group
        )
        if amount_matched:
            matched_df = pd.DataFrame([rec for _, rec in amount_matched])
            csv_valid = pd.concat([csv_valid, matched_df], ignore_index=True)
            amount_matched_count = len(amount_matched)
    print(f'  三选二匹配: {amount_matched_count} 条（通过桌台号+金额+时间模糊匹配）')

    # Step 4: 关联桌访
    print(f'\n[3/5] 关联桌访数据...')
    feedback_map = build_feedback_map(csv_valid)
    gs = associate_feedback(gs, orders_with_group, feedback_map)
    visited = len(gs[gs['桌访状态'] == '已桌访'])
    print(f'  已桌访: {visited}/{len(gs)}')

    # Step 4.5: 桌访修正后重新计算统计人数和人均
    if gs['人数修正'].any():
        corrected_people = gs['团体人数'].sum()
        stats['统计范围内消费总人数'] = corrected_people
        stats['整体人均消费'] = stats['统计范围内总营业额'] / corrected_people if corrected_people > 0 else 0
        avg_after = stats['整体人均消费']
        print(f'  人数修正后: 总人数 {int(corrected_people)}，整体人均 ¥{avg_after:.2f}')

    # Step 4.6: 异常检测
    print(f'\n[3.5/5] 异常检测...')
    gs = detect_anomalies(gs, items_clean, store_name)
    anomaly_count = len(gs[gs['异常标记'] != ''])
    print(f'  疑似异常: {anomaly_count} 个团体')
    for _, r in gs[gs['异常标记'] != ''].iterrows():
        print(f'    {r["桌台"]} | ...{str(r["首单订单号"])[-8:]} | {r["异常标记"]}')

    # Step 4.7: 会员及卡消费类型（四类互斥，数量必须闭合）
    gs, member_counts = classify_member_consumption(gs, orders_with_group)
    print('  会员及卡消费类型: ' + '；'.join(
        f'{label} {int(member_counts[label])} 团' for label in MEMBER_CATEGORY_LABELS
    ))

    # Step 5: 生成报告
    date_str = target_date.replace('-', '') if target_date else datetime.now().strftime('%Y%m%d')
    if target_date_end and target_date_end != target_date:
        date_str = f'{target_date.replace("-", "")}_{target_date_end.replace("-", "")}'
    report_label = target_date if target_date == target_date_end else f'{target_date} ~ {target_date_end}'
    store_suffix = f'_{store_name}' if store_name else ''

    print(f'\n[4/5] 生成 PDF...')
    pdf_path = os.path.join(output_dir, f'订单桌访合并_{date_str}{store_suffix}.pdf')
    generate_pdf_report(gs, gi, stats, items_clean, store_name or '未知', report_label or '未知', pdf_path, csv_unrecognized)

    print(f'\n[5/5] 生成 Markdown...')
    md_path = os.path.join(output_dir, f'订单桌访合并_{date_str}{store_suffix}.md')
    generate_markdown_report(gs, stats, store_name or '未知', report_label or '未知', md_path, csv_unrecognized, items_clean)

    print(f'\n完成！')
    print(f'  PDF: {pdf_path}')
    print(f'  Markdown: {md_path}')


if __name__ == '__main__':
    main()
