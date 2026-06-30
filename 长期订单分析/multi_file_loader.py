"""
Multi-file Excel loader for long-term order analysis.

Handles: loading multiple files, extracting pre-clean daily counts,
cross-file deduplication, and filtering out already-ingested orders.
"""

import pandas as pd
import os
import sys

# Reuse existing data loader
_lt_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(_lt_dir))
_skill_dir = os.path.join(os.path.dirname(__file__), '..', '每日订单分析', 'order_merger_skill')
sys.path.insert(0, os.path.abspath(_skill_dir))
from data_loader import load_excel
from store_utils import infer_store_from_pos_name, read_pos_store_from_excel


def _extract_basename(path: str) -> str:
    return os.path.basename(path)


def _empty_pre_merge_counts() -> dict:
    return {'原始订单数': 0, '外卖订单数': 0, '非堂食订单数': 0}


def _add_pre_merge_counts(
    target: dict,
    date: str,
    *,
    count_raw: int,
    waimai: int,
    fei_tangshi: int,
) -> None:
    if date not in target:
        target[date] = _empty_pre_merge_counts()
    target[date]['原始订单数'] += count_raw
    target[date]['外卖订单数'] += waimai
    target[date]['非堂食订单数'] += fei_tangshi


def _detect_store_from_excel(file_path: str) -> str:
    """Detect store from POS metadata. Never infer store from filename."""
    try:
        return infer_store_from_pos_name(read_pos_store_from_excel(file_path))
    except Exception:
        return "未知门店"


def load_and_dedup_excels(file_paths: list, existing_order_ids: set = None):
    """
    Load multiple Excel files, deduplicate, and extract pre-clean daily counts.

    Args:
        file_paths: list of Excel file paths
        existing_order_ids: set of order IDs already in DB (for incremental skip)

    Returns:
        dict with keys:
            - raw_orders: deduped raw orders DataFrame (all new orders)
            - raw_items: deduped raw items DataFrame
            - pre_merge_daily: dict[date_str] -> {原始订单数, 外卖订单数, 非堂食订单数}
            - pre_merge_daily_by_store: dict[store] -> dict[date_str] -> counts
            - files_loaded: list of successfully loaded file names
            - total_found: total order count across all files
            - total_new: count of orders not already in DB
            - skipped_files: list of files with no new orders
    """
    if existing_order_ids is None:
        existing_order_ids = set()

    all_orders_raw = []
    all_items_raw = []
    pre_merge_counts = {}  # date_str -> {原始订单数, 外卖订单数, 非堂食订单数}
    pre_merge_counts_by_store = {}
    files_loaded = []
    skipped_files = []

    for fp in file_paths:
        if not os.path.exists(fp):
            print(f"  [警告] 文件不存在，跳过: {fp}")
            continue

        fname = _extract_basename(fp)
        store_name = _detect_store_from_excel(fp)
        try:
            orders_raw, items_raw = load_excel(fp)
        except Exception as e:
            print(f"  [错误] 无法加载文件 {fname}: {e}")
            continue

        orders_raw = orders_raw.copy()
        orders_raw["source_file"] = fname
        if '下单时间' in orders_raw.columns:
            orders_raw['_date'] = pd.to_datetime(
                orders_raw['下单时间'], errors='coerce'
            ).dt.strftime('%Y-%m-%d')

            for date, grp in orders_raw.groupby('_date'):
                count_raw = len(grp)
                # 外卖 = 桌台列含"外点自取"
                waimai = int(grp['桌台'].astype(str).str.contains('外点自取').sum())
                # 非堂食 = 订单类型不是"堂食"
                if '订单类型' in grp.columns:
                    fei_tangshi = int((grp['订单类型'] != '堂食').sum())
                else:
                    fei_tangshi = 0

                _add_pre_merge_counts(
                    pre_merge_counts,
                    date,
                    count_raw=count_raw,
                    waimai=waimai,
                    fei_tangshi=fei_tangshi,
                )
                if store_name != "未知门店":
                    pre_merge_counts_by_store.setdefault(store_name, {})
                    _add_pre_merge_counts(
                        pre_merge_counts_by_store[store_name],
                        date,
                        count_raw=count_raw,
                        waimai=waimai,
                        fei_tangshi=fei_tangshi,
                    )

        all_orders_raw.append(orders_raw)
        if items_raw is not None and not items_raw.empty:
            all_items_raw.append(items_raw)
        files_loaded.append(fname)

    if not all_orders_raw:
        return {
            'raw_orders': pd.DataFrame(),
            'raw_items': pd.DataFrame(),
            'pre_merge_daily': pre_merge_counts,
            'pre_merge_daily_by_store': pre_merge_counts_by_store,
            'files_loaded': [],
            'total_found': 0,
            'total_new': 0,
            'skipped_files': skipped_files,
        }

    # ── Concatenate all files ──
    orders_concat = pd.concat(all_orders_raw, ignore_index=True)
    items_concat = pd.concat(all_items_raw, ignore_index=True) if all_items_raw else pd.DataFrame()

    total_found = len(orders_concat)

    # ── Filter out already-existing orders (incremental) ──
    if existing_order_ids:
        mask_new = ~orders_concat['订单号'].astype(str).isin(existing_order_ids)
        new_count = int(mask_new.sum())
        old_count = total_found - new_count
        print(f"  已有 {old_count} 条订单在数据库中，新发现 {new_count} 条")
        orders_concat = orders_concat[mask_new].copy()
    else:
        new_count = total_found

    if orders_concat.empty:
        return {
            'raw_orders': pd.DataFrame(),
            'raw_items': pd.DataFrame(),
            'pre_merge_daily': pre_merge_counts,
            'pre_merge_daily_by_store': pre_merge_counts_by_store,
            'files_loaded': files_loaded,
            'total_found': total_found,
            'total_new': 0,
            'skipped_files': skipped_files,
        }

    # ── Dedup across files (keep='first' based on load order) ──
    orders_dedup = orders_concat.drop_duplicates(subset='订单号', keep='first').copy()

    if not items_concat.empty:
        # 商品明细必须保留 POS 行级数据；同一订单同一商品多次加单/拆行都是真实销量。
        items_dedup = items_concat.copy()
        # Only keep items whose orders survived dedup
        valid_order_ids = set(orders_dedup['订单号'].astype(str))
        items_dedup = items_dedup[items_dedup['订单号'].astype(str).isin(valid_order_ids)].copy()
    else:
        items_dedup = pd.DataFrame()

    return {
        'raw_orders': orders_dedup,
        'raw_items': items_dedup,
        'pre_merge_daily': pre_merge_counts,
        'pre_merge_daily_by_store': pre_merge_counts_by_store,
        'files_loaded': files_loaded,
        'total_found': total_found,
        'total_new': len(orders_dedup),
        'skipped_files': skipped_files,
    }


def build_merged_dataset(new_orders, new_items, context_order_dicts, items_df_raw):
    """
    Merge new orders with context orders from DB for cross-boundary merge.
    Returns (merged_orders_df, merged_items_df).

    context_order_dicts: list of dicts from DB (raw order data)
    items_df_raw: DataFrame of raw items (to be filtered for context orders)
    """
    import pandas as pd

    context_orders_df = pd.DataFrame(context_order_dicts) if context_order_dicts else pd.DataFrame()

    if context_orders_df.empty:
        return new_orders.copy(), new_items.copy()

    # Combine context orders with new orders
    all_orders = pd.concat([context_orders_df, new_orders], ignore_index=True)
    all_orders = all_orders.drop_duplicates(subset='订单号', keep='first')

    # Get context order IDs
    context_ids = set()
    for d in context_order_dicts:
        oid = str(d.get('订单号', ''))
        if oid:
            context_ids.add(oid)

    # Filter items to new orders + context orders
    all_order_ids = set(all_orders['订单号'].astype(str))
    all_items = items_df_raw[items_df_raw['订单号'].astype(str).isin(all_order_ids)].copy()

    return all_orders, all_items
