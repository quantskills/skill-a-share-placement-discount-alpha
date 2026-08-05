#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股定增折价解禁因子单元测试（离线，无需联网/无需 PandaAI 账号）

覆盖范围：
  1. calc_time_weight        —— 7 档时间权重及边界/NaN 行为
  2. _load_env_file          —— .env 不覆盖已存在环境变量（P0：去 .env 覆盖）
  3. _init_panda_token       —— 认证优先级 命令行 > 环境变量 > .env（P0：认证传参）
  4. calculate_placement_discount_factor —— 折价反转、ST/交易状态过滤、去重、signal 门槛
  5. build_output            —— 输出 Parquet 字段完整性

运行：
    python scripts/test.py

说明：
  factor.py 顶层 `import panda_data`，为保证离线可跑，本测试在导入 factor 前
  向 sys.modules 注入一个假的 panda_data 桩，用于记录 init_token 的入参。
"""

import os
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 注入假的 panda_data 桩，使 factor.py 可在无 SDK 环境下导入
# ---------------------------------------------------------------------------
_fake_panda = types.ModuleType("panda_data")
_fake_panda.last_init = None


def _fake_init_token(username=None, password=None):
    # 记录最终用于登录的凭据，供认证优先级测试断言
    _fake_panda.last_init = {"username": username, "password": password}


_fake_panda.init_token = _fake_init_token
_fake_panda.get_stock_private_placement = lambda **kw: pd.DataFrame()
_fake_panda.get_restricted_list = lambda **kw: pd.DataFrame()
_fake_panda.get_stock_daily = lambda **kw: pd.DataFrame()
sys.modules["panda_data"] = _fake_panda

# 导入被测模块（复用 factor.py，与生产逻辑完全一致）
sys.path.insert(0, str(Path(__file__).parent))
import factor  # noqa: E402
from factor import (  # noqa: E402
    calc_time_weight,
    _load_env_file,
    _init_panda_token,
    calculate_placement_discount_factor,
    build_output,
)


class TestCalcTimeWeight(unittest.TestCase):
    """时间权重 7 档 + 边界 + NaN（与 SKILL.md 表格保持一致）"""

    def test_relieved_tiers(self):
        self.assertEqual(calc_time_weight(0), 1.0)
        self.assertEqual(calc_time_weight(30), 1.0)
        self.assertEqual(calc_time_weight(31), 0.7)
        self.assertEqual(calc_time_weight(60), 0.7)
        self.assertEqual(calc_time_weight(61), 0.4)
        self.assertEqual(calc_time_weight(120), 0.4)
        self.assertEqual(calc_time_weight(121), 0.2)
        self.assertEqual(calc_time_weight(365), 0.2)

    def test_pre_relief_tiers(self):
        self.assertEqual(calc_time_weight(-1), 0.3)
        self.assertEqual(calc_time_weight(-30), 0.3)
        self.assertEqual(calc_time_weight(-31), 0.2)
        self.assertEqual(calc_time_weight(-90), 0.2)
        self.assertEqual(calc_time_weight(-91), 0.1)
        self.assertEqual(calc_time_weight(-365), 0.1)

    def test_out_of_window_and_nan(self):
        self.assertEqual(calc_time_weight(366), 0.0)
        self.assertEqual(calc_time_weight(-366), 0.0)
        self.assertEqual(calc_time_weight(np.nan), 0.0)


class TestLoadEnvFile(unittest.TestCase):
    """P0：.env 只能补充缺失键，绝不覆盖已存在环境变量"""

    def setUp(self):
        self.tmp_env = Path(__file__).parent / "_test_tmp.env"
        self.tmp_env.write_text(
            "PANDA_USERNAME=from_env_file\nPANDA_PASSWORD=pwd_from_file\n",
            encoding="utf-8",
        )
        self._saved = {
            k: os.environ.get(k) for k in ("PANDA_USERNAME", "PANDA_PASSWORD")
        }

    def tearDown(self):
        if self.tmp_env.exists():
            self.tmp_env.unlink()
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_does_not_override_existing(self):
        os.environ["PANDA_USERNAME"] = "already_set"
        os.environ.pop("PANDA_PASSWORD", None)
        _load_env_file(self.tmp_env)
        # 已存在的键保持不变
        self.assertEqual(os.environ["PANDA_USERNAME"], "already_set")
        # 缺失的键由 .env 补充
        self.assertEqual(os.environ["PANDA_PASSWORD"], "pwd_from_file")

    def test_fills_missing(self):
        os.environ.pop("PANDA_USERNAME", None)
        os.environ.pop("PANDA_PASSWORD", None)
        _load_env_file(self.tmp_env)
        self.assertEqual(os.environ["PANDA_USERNAME"], "from_env_file")
        self.assertEqual(os.environ["PANDA_PASSWORD"], "pwd_from_file")


class TestInitPandaTokenPriority(unittest.TestCase):
    """P0：认证优先级 命令行参数 > 环境变量 > .env 文件"""

    def setUp(self):
        _fake_panda.last_init = None
        self._saved = {
            k: os.environ.get(k) for k in ("PANDA_USERNAME", "PANDA_PASSWORD")
        }

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_cli_args_win_over_env(self):
        os.environ["PANDA_USERNAME"] = "env_user"
        os.environ["PANDA_PASSWORD"] = "env_pwd"
        _init_panda_token("cli_user", "cli_pwd", interactive=False)
        self.assertEqual(_fake_panda.last_init["username"], "cli_user")
        self.assertEqual(_fake_panda.last_init["password"], "cli_pwd")

    def test_env_used_when_no_cli(self):
        os.environ["PANDA_USERNAME"] = "env_user"
        os.environ["PANDA_PASSWORD"] = "env_pwd"
        _init_panda_token(None, None, interactive=False)
        self.assertEqual(_fake_panda.last_init["username"], "env_user")
        self.assertEqual(_fake_panda.last_init["password"], "env_pwd")

    def test_raises_when_missing(self):
        os.environ.pop("PANDA_USERNAME", None)
        os.environ.pop("PANDA_PASSWORD", None)
        # 隔离真实 .env：临时将 _load_env_file 置为 no-op，模拟“任何来源都没有凭据”
        original_loader = factor._load_env_file
        factor._load_env_file = lambda env_path=None: None
        try:
            # interactive=False 且无凭据时应报错而非阻塞等待输入
            with self.assertRaises(RuntimeError):
                _init_panda_token(None, None, interactive=False)
        finally:
            factor._load_env_file = original_loader


class TestCalculateFactor(unittest.TestCase):
    """核心因子逻辑：折价反转、过滤、去重、signal 门槛"""

    def _build_inputs(self):
        as_of_date = "20260101"
        # 5 只股票：
        #   A 低折价率（好）、B 高折价率（差）、C 溢价发行（应被排除）
        #   D ST 股（应被排除）、E trade_status!=0（应被排除）
        placement = pd.DataFrame({
            "ts_code": ["A", "B", "C", "D", "E"],
            "issue_price": [9.5, 5.0, 12.0, 8.0, 8.0],
        })
        daily = pd.DataFrame({
            "ts_code": ["A", "B", "C", "D", "E"],
            "close": [10.0, 10.0, 10.0, 10.0, 10.0],
            "name": ["万科A", "平安银行", "某某股份", "ST康美", "某某科技"],
            "trade_status": [0, 0, 0, 0, 1],
        })
        # 解禁日均在基准日后 10 天内 => time_weight = 1.0
        restricted = pd.DataFrame({
            "ts_code": ["A", "B", "C", "D", "E"],
            "relief_date": ["20260110"] * 5,
            "relieve_shares": [1000] * 5,
        })
        return placement, restricted, daily, as_of_date

    def test_reversal_filters_and_dedup(self):
        placement, restricted, daily, as_of_date = self._build_inputs()
        result = calculate_placement_discount_factor(
            placement, restricted, daily, as_of_date
        )
        codes = set(result["ts_code"])
        # C 溢价（发行价>市价，折价率<0）被排除；D 为 ST 被排除；E 交易状态异常被排除
        self.assertEqual(codes, {"A", "B"})

        # 折价率：A=(10-9.5)/10=0.05，B=(10-5)/10=0.5
        row_a = result[result["ts_code"] == "A"].iloc[0]
        row_b = result[result["ts_code"] == "B"].iloc[0]
        self.assertAlmostEqual(row_a["discount_rate"], 0.05, places=6)
        self.assertAlmostEqual(row_b["discount_rate"], 0.5, places=6)

        # 方向反转：factor_value = -discount_rate * time_weight（tw=1.0）
        self.assertAlmostEqual(row_a["factor_value"], -0.05, places=6)
        self.assertAlmostEqual(row_b["factor_value"], -0.5, places=6)

        # 低折价率 A 的因子值更高 => rank 更靠前（rank=1 最值得买入）
        self.assertLess(row_a["rank"], row_b["rank"])

    def test_signal_threshold_score_only(self):
        placement, restricted, daily, as_of_date = self._build_inputs()
        result = calculate_placement_discount_factor(
            placement, restricted, daily, as_of_date
        )
        # signal 仅基于 score：score>=80 -> buy，score<20 -> sell
        for _, row in result.iterrows():
            if row["score"] >= 80:
                self.assertEqual(row["signal"], "buy")
            elif row["score"] < 20:
                self.assertEqual(row["signal"], "sell")
            else:
                self.assertEqual(row["signal"], "hold")

    def test_build_output_schema(self):
        placement, restricted, daily, as_of_date = self._build_inputs()
        result = calculate_placement_discount_factor(
            placement, restricted, daily, as_of_date
        )
        output = build_output(result, as_of_date)
        expected_cols = {
            "trade_date", "asset_type", "ts_code", "market", "factor_id",
            "factor_name", "factor_value", "score", "rank", "signal",
            "confidence", "data_version", "update_time", "discount_rate",
            "issue_price", "market_price", "relief_date", "days_to_relief",
            "time_weight",
        }
        self.assertTrue(expected_cols.issubset(set(output.columns)))
        self.assertEqual(output["asset_type"].unique().tolist(), ["stock"])
        self.assertEqual(output["market"].unique().tolist(), ["cn"])
        self.assertEqual(output["factor_id"].unique().tolist(), ["placement_discount"])
        # 无空值常量列
        self.assertFalse(output.isnull().any().any())


if __name__ == "__main__":
    unittest.main(verbosity=2)
