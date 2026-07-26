"""Tests for POS/takeaway ingest validation."""

import importlib.util
import sys
from pathlib import Path

import pytest

ORDER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ORDER_ROOT))

import pandas as pd  # noqa: E402

from ingest_validator import (  # noqa: E402
    _check_columns,
    _check_filename_store,
    allowed_missing_dates,
    load_closure_dates,
    load_schema,
    validate_pos_excel,
)


POS_SAMPLE = Path(
    "/Users/jgc/Downloads/同步空间/桌访周总结/260615/"
    "店内订单明细2026-06-15+00_00_00~2026-06-21+23_59_59.xlsx"
)


@pytest.mark.skipif(not POS_SAMPLE.exists(), reason="sample POS file not on disk")
def test_validate_pos_sample_ok():
    r = validate_pos_excel(POS_SAMPLE)
    assert r.ok, r.errors


def test_closure_dates_include_spring_festival():
    c = load_closure_dates()
    allowed = allowed_missing_dates("万荷店", c)
    assert "2024-02-10" in allowed
    assert "2023-10-10" in allowed


def test_closure_wanhe_pos_debug():
    c = load_closure_dates()
    allowed = allowed_missing_dates("万荷店", c)
    assert "2023-10-17" in allowed


def test_closure_baoli_no_debug_days():
    c = load_closure_dates()
    allowed = allowed_missing_dates("保利店", c)
    assert "2023-10-10" not in allowed


def test_schema_loads_three_sheets():
    s = load_schema()
    assert set(s.keys()) == {"pos_orders", "pos_items", "takeaway"}
    assert "会员手机号" in s["pos_orders"]["required"]
    assert "送达时间" in s["takeaway"]["nullable"]


def test_check_columns_detects_missing_column():
    req = ["订单号", "会员手机号", "就餐人数"]
    df = pd.DataFrame({"订单号": ["1", "2"], "就餐人数": ["3", "4"]})  # 缺 会员手机号
    errs = _check_columns(df, "店内订单明细", "订单号", req, set())
    assert any("会员手机号" in e for e in errs), errs


def test_check_columns_detects_blank_cell():
    req = ["订单号", "就餐人数"]
    df = pd.DataFrame({"订单号": ["1", "2"], "就餐人数": ["3", None]})
    errs = _check_columns(df, "店内订单明细", "订单号", req, set())
    assert any("就餐人数" in e for e in errs), errs


def test_check_columns_nullable_exempt():
    req = ["外卖订单号", "送达时间"]
    df = pd.DataFrame({"外卖订单号": ["1", "2"], "送达时间": ["x", None]})
    errs = _check_columns(df, "平台外卖订单明细", "外卖订单号", req, {"送达时间"})
    assert errs == [], errs


def test_check_columns_placeholder_dash_is_value():
    req = ["订单号", "会员手机号"]
    df = pd.DataFrame({"订单号": ["1", "2"], "会员手机号": ["-", "138"]})
    errs = _check_columns(df, "店内订单明细", "订单号", req, set())
    assert errs == [], errs


def test_filename_store_mismatch_is_rejected():
    errs = _check_filename_store(Path("万荷店内订单明细.xlsx"), "保利店", "POS")

    assert errs
    assert "文件名门店为 万荷店" in errs[0]
    assert "Excel 内容门店为 保利店" in errs[0]


def test_direct_single_store_ingest_validates_before_opening_db(monkeypatch, tmp_path: Path):
    module_path = ORDER_ROOT / "周期对比分析" / "ingest_store_stats.py"
    spec = importlib.util.spec_from_file_location("ingest_store_stats_for_validation_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    class FailedValidation:
        store_name = "万荷店"

        def raise_if_failed(self, *, prefix: str = "") -> None:
            raise SystemExit(f"{prefix}: validation failed")

    monkeypatch.setattr(module, "validate_pos_excel", lambda _path: FailedValidation())

    def fail_if_db_opened(_path):
        raise AssertionError("DatabaseManager should not be opened when validation fails")

    monkeypatch.setattr(module, "DatabaseManager", fail_if_db_opened)

    with pytest.raises(SystemExit, match="validation failed"):
        module.ingest("bad.xlsx", "万荷店", str(tmp_path / "test.db"), None, None)
