"""
POS / 外卖 Excel 入库前完整性校验。

- 列：表头齐全，且每条有效数据行所有列非空
- 日期：文件声明范围内逐日有订单（营业日/下单时间），除 config/ingest_closure_dates.json 允许的闭店日
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

_WORKSPACE = Path(__file__).resolve().parents[1]
_DEFAULT_CLOSURE = _WORKSPACE / "config" / "ingest_closure_dates.json"
_DEFAULT_SCHEMA = _WORKSPACE / "config" / "ingest_schema.json"

_DATE_RANGE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}).*?(\d{4}-\d{2}-\d{2})"
)


@dataclass
class IngestValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    store_name: str = ""
    period_start: str = ""
    period_end: str = ""

    def raise_if_failed(self, *, prefix: str = "") -> None:
        if self.ok:
            return
        head = f"{prefix}: " if prefix else ""
        lines = [f"{head}入库校验未通过，请修正 Excel 后重新提交："]
        lines.extend(f"  - {e}" for e in self.errors)
        raise SystemExit("\n".join(lines))


def load_closure_dates(config_path: Path | None = None) -> dict[str, set[str]]:
    path = config_path or _DEFAULT_CLOSURE
    if not path.exists():
        return {"_all_stores": set(), "万荷店": set(), "保利店": set()}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for key, vals in data.items():
        if key == "_comment" or not isinstance(vals, list):
            continue
        out[key] = set(vals)
    out.setdefault("_all_stores", set())
    out.setdefault("万荷店", set())
    out.setdefault("保利店", set())
    return out


def allowed_missing_dates(store_name: str, closure: dict[str, set[str]] | None = None) -> set[str]:
    c = closure or load_closure_dates()
    allowed = set(c.get("_all_stores", set()))
    if store_name:
        allowed |= c.get(store_name, set())
    return allowed


def load_schema(config_path: Path | None = None) -> dict[str, dict]:
    """返回 {sheet_key: {"required": [...], "nullable": [...]}}。文件缺失返回空 dict（退化为遍历实际列）。"""
    path = config_path or _DEFAULT_SCHEMA
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}


def _schema_for(schema: dict, key: str) -> tuple[list[str] | None, set[str]]:
    entry = schema.get(key, {})
    required = entry.get("required") or None
    nullable = set(entry.get("nullable", []))
    return required, nullable


def _parse_export(df: pd.DataFrame, header_keyword: str) -> pd.DataFrame:
    header_idx = None
    for i, row in df.iterrows():
        if header_keyword in str(row.values):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(f"未找到含「{header_keyword}」的表头行")
    header = df.iloc[header_idx].tolist()
    data = df.iloc[header_idx + 1 :].copy()
    data.columns = header
    return data.dropna(axis=1, how="all").reset_index(drop=True)


def _read_metadata(df_raw: pd.DataFrame) -> dict[str, str]:
    """读取表头行之前的元数据键值（门店名称 / 下单时间范围）。

    一旦遇到表头行（含「订单号」「外卖订单号」），停止扫描，避免把表头里的
    「下单时间」列名误当成元数据值。同名键取首次出现。
    """
    meta: dict[str, str] = {}
    for _, row in df_raw.head(15).iterrows():
        vals = [str(v).strip() for v in row.values if str(v) != "nan"]
        if any(v in ("订单号", "外卖订单号") for v in vals):
            break
        for i, val in enumerate(vals):
            if val in ("门店名称", "下单时间", "营业日") and i + 1 < len(vals):
                meta.setdefault(val, vals[i + 1])
    return meta


def _normalize_store(raw: str) -> str:
    if "万荷" in raw:
        return "万荷店"
    if "保利" in raw:
        return "保利店"
    return raw or "未知门店"


def _store_from_filename(path: Path) -> str:
    name = path.name
    if "万荷" in name:
        return "万荷店"
    if "保利" in name:
        return "保利店"
    return "未知门店"


def _check_filename_store(path: Path, content_store: str, label: str) -> list[str]:
    expected = _store_from_filename(path)
    if content_store == "未知门店":
        return [f"{label}：无法从文件内容识别门店"]
    if expected != "未知门店" and expected != content_store:
        return [f"{label}：文件名门店为 {expected}，Excel 内容门店为 {content_store}"]
    return []


def _parse_range_text(text: str) -> tuple[str, str] | None:
    m = _DATE_RANGE_RE.search(str(text))
    if not m:
        return None
    return m.group(1), m.group(2)


def _parse_range_from_filename(path: Path) -> tuple[str, str] | None:
    return _parse_range_text(path.name)


def _iter_dates(start: str, end: str) -> list[str]:
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    out: list[str] = []
    cur = d0
    while cur <= d1:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _cell_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and pd.isna(v):
        return True
    if isinstance(v, (datetime, pd.Timestamp)):
        return pd.isna(v)
    s = str(v).strip().lower()
    return s in ("", "nan", "none", "nat")


def _check_columns(
    df: pd.DataFrame,
    label: str,
    id_col: str,
    required_cols: list[str] | None = None,
    nullable_cols: set[str] | None = None,
) -> list[str]:
    """列完整性校验。

    - required_cols 给定时：以标准列清单为基准，缺任一标准列即报错（可检出整列缺失/整列全空被 dropna 删除的情况）。
    - 空值校验范围：required_cols（去掉 nullable_cols）；未给 required_cols 时退化为遍历实际列。
    - 占位符「-」视为有值（POS 对无属性字段的正常导出）。
    """
    errors: list[str] = []
    nullable_cols = nullable_cols or set()
    if id_col not in df.columns:
        return [f"{label}：缺少必要列「{id_col}」"]

    valid = df[df[id_col].astype(str).str.fullmatch(r"\d+", na=False)]
    if valid.empty:
        return [f"{label}：无有效数据行"]

    actual = set(df.columns)

    if required_cols:
        missing = [c for c in required_cols if c not in actual]
        if missing:
            errors.append(
                f"{label}：相对标准缺少 {len(missing)} 列："
                + "、".join(missing)
                + "（请重新导出包含全部列的 Excel）"
            )
        check_cols = [c for c in required_cols if c in valid.columns and c not in nullable_cols]
    else:
        check_cols = [
            c
            for c in df.columns
            if str(c).strip() and str(c) != "nan" and c not in nullable_cols
        ]

    null_issues: list[str] = []
    for col in check_cols:
        n = int(valid[col].apply(_cell_empty).sum())
        if n:
            null_issues.append(f"{label}：列「{col}」有 {n} 行空值（要求每列每条记录均有值）")

    if len(null_issues) > 8:
        errors.extend(null_issues[:8])
        errors.append(f"{label}：另有 {len(null_issues) - 8} 列存在空值，请全表检查")
    else:
        errors.extend(null_issues)
    return errors


def _check_date_coverage(
    actual_dates: Iterable[str],
    period_start: str,
    period_end: str,
    store_name: str,
    closure: dict[str, set[str]] | None = None,
) -> list[str]:
    if not period_start or not period_end:
        return ["无法从文件元数据或文件名解析下单日期范围"]

    expected = _iter_dates(period_start, period_end)
    have = {str(d)[:10] for d in actual_dates if d and str(d) != "NaT"}
    allowed = allowed_missing_dates(store_name, closure)
    missing = [d for d in expected if d not in have and d not in allowed]
    if missing:
        return [
            f"声明范围 {period_start}~{period_end} 内缺 {len(missing)} 天订单数据："
            + ", ".join(missing[:15])
            + (" ..." if len(missing) > 15 else "")
            + "（非春节/已登记闭店日不可缺日，请重新导出完整 Excel）"
        ]
    return []


def validate_pos_excel(
    file_path: str | Path,
    *,
    closure_config: Path | None = None,
    schema_config: Path | None = None,
) -> IngestValidationResult:
    """校验店内订单 + 商品两个工作表。"""
    path = Path(file_path)
    result = IngestValidationResult(ok=True)
    closure = load_closure_dates(closure_config)
    schema = load_schema(schema_config)

    try:
        sheets = pd.ExcelFile(path).sheet_names
    except Exception as exc:
        result.ok = False
        result.errors.append(f"无法打开 {path.name}：{exc}")
        return result

    for sheet in ("店内订单明细", "商品-店内订单明细"):
        if sheet not in sheets:
            result.ok = False
            result.errors.append(f"缺少工作表「{sheet}」")
    if not result.ok:
        return result

    try:
        orders_raw = pd.read_excel(path, sheet_name="店内订单明细", header=None)
        items_raw = pd.read_excel(path, sheet_name="商品-店内订单明细", header=None)
    except Exception as exc:
        result.ok = False
        result.errors.append(f"无法读取 {path.name}：{exc}")
        return result

    meta = _read_metadata(orders_raw)
    store_raw = meta.get("门店名称", "")
    result.store_name = _normalize_store(store_raw)
    result.errors.extend(_check_filename_store(path, result.store_name, "POS"))

    rng = _parse_range_text(meta.get("下单时间", "")) or _parse_range_from_filename(path)
    if rng:
        result.period_start, result.period_end = rng

    try:
        orders = _parse_export(orders_raw, "订单号")
        items = _parse_export(items_raw, "订单号")
    except ValueError as exc:
        result.ok = False
        result.errors.append(str(exc))
        return result

    if store_raw:
        orders["门店名称"] = store_raw
        items["门店名称"] = store_raw

    o_req, o_null = _schema_for(schema, "pos_orders")
    i_req, i_null = _schema_for(schema, "pos_items")
    result.errors.extend(_check_columns(orders, "店内订单明细", "订单号", o_req, o_null))
    result.errors.extend(_check_columns(items, "商品-店内订单明细", "订单号", i_req, i_null))

    orders_valid = orders[orders["订单号"].astype(str).str.fullmatch(r"\d+", na=False)]
    if "下单时间" in orders_valid.columns:
        dates = pd.to_datetime(orders_valid["下单时间"], errors="coerce").dt.strftime("%Y-%m-%d")
        result.errors.extend(
            _check_date_coverage(dates.dropna(), result.period_start, result.period_end, result.store_name, closure)
        )
    else:
        result.errors.append("店内订单明细缺少「下单时间」列，无法校验日期完整性")

    result.ok = len(result.errors) == 0
    return result


def validate_takeaway_excel(
    file_path: str | Path,
    *,
    closure_config: Path | None = None,
    schema_config: Path | None = None,
    strict_dates: bool = False,
) -> IngestValidationResult:
    """校验平台外卖订单明细。"""
    path = Path(file_path)
    result = IngestValidationResult(ok=True)
    closure = load_closure_dates(closure_config)
    schema = load_schema(schema_config)

    try:
        df_raw = pd.read_excel(path, sheet_name="平台外卖订单明细", header=None)
    except Exception as exc:
        result.ok = False
        result.errors.append(f"无法读取 {path.name}：{exc}")
        return result

    meta = _read_metadata(df_raw)
    result.store_name = _normalize_store(meta.get("门店名称", ""))
    result.errors.extend(_check_filename_store(path, result.store_name, "外卖"))
    rng = _parse_range_text(meta.get("下单时间", "") or meta.get("营业日", "")) or _parse_range_from_filename(path)
    if rng:
        result.period_start, result.period_end = rng

    try:
        data = _parse_export(df_raw, "外卖订单号")
    except ValueError as exc:
        result.ok = False
        result.errors.append(str(exc))
        return result

    data = data[data["外卖订单号"].astype(str).str.fullmatch(r"\d+", na=False)]
    t_req, t_null = _schema_for(schema, "takeaway")
    result.errors.extend(_check_columns(data, "平台外卖订单明细", "外卖订单号", t_req, t_null))

    if "营业日" in data.columns:
        biz = pd.to_datetime(data["营业日"], errors="coerce").dt.strftime("%Y-%m-%d")
    elif "下单时间" in data.columns:
        biz = pd.to_datetime(data["下单时间"], errors="coerce").dt.strftime("%Y-%m-%d")
    else:
        biz = pd.Series(dtype=str)

    if strict_dates and not biz.empty:
        result.errors.extend(
            _check_date_coverage(biz.dropna(), result.period_start, result.period_end, result.store_name, closure)
        )

    result.ok = len(result.errors) == 0
    return result


def validate_pos_files(paths: Iterable[str | Path], **kwargs) -> IngestValidationResult:
    merged = IngestValidationResult(ok=True)
    for p in paths:
        r = validate_pos_excel(p, **kwargs)
        if not r.ok:
            merged.ok = False
        merged.errors.extend([f"[{Path(p).name}] {e}" for e in r.errors])
        merged.warnings.extend(r.warnings)
    return merged
