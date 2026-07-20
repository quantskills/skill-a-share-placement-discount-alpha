#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股定增折价解禁因子回测脚本（官方SDK版 v2）

分析指标：
  - IC / RankIC 时序（T期因子 vs T+1期收益）
  - ICIR（信息系数比率）
  - 分层收益（5组，多空组合）
  - 最大回撤
  - 换手率
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import panda_data

sys.path.insert(0, str(Path(__file__).parent))
from factor import (
    _load_env_file,
    _init_panda_token,
    _find_column,
    get_private_placement_data,
    get_restricted_data,
    calc_time_weight,
)


def load_daily_data(start_date: str, end_date: str) -> pd.DataFrame:
    try:
        df = panda_data.get_stock_daily(
            start_date=start_date,
            end_date=end_date,
            st=False
        )
        if df is not None and not df.empty:
            sym_col = _find_column(df, ["symbol", "ts_code", "stock_symbol"])
            if sym_col:
                df = df.rename(columns={sym_col: "ts_code"})
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
            return df
    except Exception:
        pass
    return pd.DataFrame()


def calculate_factor_value(
    placement_df: pd.DataFrame,
    restricted_df: pd.DataFrame,
    daily_df: pd.DataFrame,
    as_of_date: str,
) -> pd.DataFrame:
    """计算因子值（与 factor.py 逻辑一致：折价率 × 时间权重）"""
    if placement_df.empty or daily_df.empty:
        return pd.DataFrame()

    placement = placement_df.copy()
    daily = daily_df.copy()

    as_of_dt = datetime.strptime(as_of_date, "%Y%m%d")

    daily_before = daily[daily["date"] <= as_of_dt]
    if daily_before.empty:
        return pd.DataFrame()

    latest_daily = daily_before.sort_values("date").groupby("ts_code").last().reset_index()

    price_col = _find_column(latest_daily, ["close"])
    if not price_col:
        return pd.DataFrame()

    latest_daily["market_price"] = pd.to_numeric(latest_daily[price_col], errors="coerce")

    merged = placement.merge(
        latest_daily[["ts_code", "market_price", "name", "trade_status"]],
        on="ts_code",
        how="inner"
    )

    issue_col = _find_column(merged, ["issue_price"])
    if issue_col:
        merged["issue_price"] = pd.to_numeric(merged[issue_col], errors="coerce")

    merged = merged.dropna(subset=["market_price", "issue_price"])
    merged = merged[(merged["market_price"] > 0) & (merged["issue_price"] > 0)]
    merged["discount_rate"] = (merged["market_price"] - merged["issue_price"]) / merged["market_price"]
    merged = merged[merged["discount_rate"] >= 0]

    merged = merged[merged["trade_status"] == 0]
    name_col = _find_column(merged, ["name", "stock_name"])
    if name_col:
        st_mask = merged[name_col].str.contains("ST", na=False)
        merged = merged[~st_mask]

    if not restricted_df.empty:
        restricted = restricted_df.copy()
        restricted["relief_date_dt"] = pd.to_datetime(
            restricted["relief_date"], format="%Y%m%d", errors="coerce"
        )
        relief_agg = restricted.groupby("ts_code").agg(
            relief_date=("relief_date_dt", "min")
        ).reset_index()
        merged = merged.merge(relief_agg, on="ts_code", how="inner")
    else:
        return pd.DataFrame()

    merged["days_to_relief"] = (merged["relief_date"] - as_of_dt).dt.days
    merged["time_weight"] = merged["days_to_relief"].apply(calc_time_weight)
    merged = merged[merged["time_weight"] > 0]

    # 因子值 = -折价率 × 时间权重（与 factor.py 一致，方向反转）
    merged["factor_value"] = -merged["discount_rate"] * merged["time_weight"]

    # 去重：保留最低折价率的定增（与 factor.py 一致）
    merged = merged.sort_values("discount_rate", ascending=True)
    merged = merged.drop_duplicates(subset=["ts_code"], keep="first")

    return merged[["ts_code", "factor_value", "discount_rate", "time_weight", "days_to_relief"]]


def load_forward_returns(daily_df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """计算 T+1 期收益率（IC计算用）"""
    df = daily_df.copy()
    df = df.sort_values(["ts_code", "date"])
    df[f"ret_{period}d"] = df.groupby("ts_code")["close"].pct_change(period).shift(-period)
    return df


def calculate_ic(factor_df: pd.DataFrame, ret_col: str = "ret_20d") -> tuple:
    valid = factor_df.dropna(subset=["factor_value", ret_col])
    if len(valid) < 10:
        return np.nan, np.nan

    ic = valid["factor_value"].corr(valid[ret_col])
    rank_ic = valid["factor_value"].rank().corr(valid[ret_col].rank())
    return ic, rank_ic


def calculate_icir(ic_values: list) -> float:
    ic_array = np.array([i for i in ic_values if not np.isnan(i)])
    if len(ic_array) < 2:
        return np.nan
    return np.mean(ic_array) / np.std(ic_array)


def calculate_stratified_returns(factor_df: pd.DataFrame, n_groups: int = 5, ret_col: str = "ret_20d") -> pd.DataFrame:
    df = factor_df.copy()
    df = df.dropna(subset=["factor_value", ret_col])
    if len(df) < n_groups * 2:
        return pd.DataFrame()

    df["group"] = pd.qcut(df["factor_value"], n_groups, labels=False, duplicates="drop")
    grouped = df.groupby("group")[ret_col].agg(["mean", "std", "count"])
    grouped.index = [f"Group {i+1}" for i in grouped.index]

    if len(grouped) >= 2:
        grouped.loc["Long-Short"] = pd.Series({
            "mean": grouped.iloc[-1]["mean"] - grouped.iloc[0]["mean"],
            "std": np.sqrt(grouped.iloc[-1]["std"]**2 + grouped.iloc[0]["std"]**2),
            "count": min(grouped.iloc[-1]["count"], grouped.iloc[0]["count"]),
        })

    return grouped


def calculate_max_drawdown(returns: list) -> float:
    if not returns:
        return np.nan

    cumulative = np.cumprod([1 + r for r in returns])
    peak = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - peak) / peak
    return float(np.min(drawdown))


def calculate_turnover(factor_series_list: list, top_pct: float = 0.2) -> float:
    if len(factor_series_list) < 2:
        return np.nan

    turnover_rates = []
    for i in range(1, len(factor_series_list)):
        prev = factor_series_list[i-1]
        curr = factor_series_list[i]

        n_top = max(1, int(len(prev) * top_pct))
        prev_top = set(prev.nlargest(n_top).index)
        curr_top = set(curr.nlargest(n_top).index)

        if prev_top and curr_top:
            overlap = len(prev_top & curr_top)
            turnover = 1 - overlap / len(prev_top)
            turnover_rates.append(turnover)

    return float(np.mean(turnover_rates)) if turnover_rates else np.nan


def run_backtest(start_date: str, end_date: str, period: int = 20):
    print(f"[backtest] 加载数据...")
    print(f"  回测区间: {start_date} ~ {end_date}")
    print(f"  持仓周期: {period}天")

    placement_start = (datetime.strptime(start_date, "%Y%m%d") - timedelta(days=730)).strftime("%Y%m%d")
    placement_df = get_private_placement_data(placement_start, end_date)
    print(f"  定增数据: {len(placement_df)} 条")

    restricted_start = (datetime.strptime(start_date, "%Y%m%d") - timedelta(days=365)).strftime("%Y%m%d")
    restricted_end = (datetime.strptime(end_date, "%Y%m%d") + timedelta(days=180)).strftime("%Y%m%d")
    restricted_df = get_restricted_data(restricted_start, restricted_end)
    print(f"  解禁数据: {len(restricted_df)} 条")

    daily_end = (datetime.strptime(end_date, "%Y%m%d") + timedelta(days=period + 10)).strftime("%Y%m%d")
    daily_df = load_daily_data(start_date, daily_end)
    print(f"  日线数据: {len(daily_df)} 条")

    if placement_df.empty or daily_df.empty:
        print("❌ 数据不足，无法回测")
        return

    daily_df = load_forward_returns(daily_df, period)
    ret_col = f"ret_{period}d"

    daily_dates = daily_df["date"].dropna().unique()
    daily_dates = sorted(daily_dates)

    if len(daily_dates) < period * 2:
        print("❌ 交易日数据不足，无法回测")
        return

    ic_list = []
    rank_ic_list = []
    factor_series_list = []

    step = max(1, period // 2)
    sampled_dates = daily_dates[::step][:-2] if len(daily_dates[::step]) > 2 else daily_dates[:-2]

    print(f"[backtest] 回测中，共 {len(sampled_dates)} 个调仓日...")

    for dt in sampled_dates:
        dt_str = pd.Timestamp(dt).strftime("%Y%m%d")
        factor_df = calculate_factor_value(placement_df, restricted_df, daily_df, dt_str)

        if factor_df.empty:
            continue

        daily_at_date = daily_df[daily_df["date"] == dt]
        if daily_at_date.empty:
            continue

        merged = factor_df.merge(
            daily_at_date[["ts_code", ret_col]],
            on="ts_code",
            how="inner"
        )

        if len(merged) < 10:
            continue

        ic, rank_ic = calculate_ic(merged, ret_col)
        if not np.isnan(ic):
            ic_list.append(ic)
            rank_ic_list.append(rank_ic)

            factor_s = merged.set_index("ts_code")["factor_value"]
            factor_series_list.append(factor_s)

    if not ic_list:
        print("❌ 无有效IC数据，回测失败")
        return

    print("\n--- 回测指标 ---")
    print(f"[backtest] 有效调仓日: {len(ic_list)} 个")

    avg_ic = np.mean(ic_list)
    avg_rank_ic = np.mean(rank_ic_list)
    ic_std = np.std(ic_list)
    icir = avg_ic / ic_std if ic_std > 0 else np.nan

    print(f"\nIC:        {avg_ic:.4f}")
    print(f"RankIC:    {avg_rank_ic:.4f}")
    print(f"ICIR:      {icir:.4f}")
    print(f"平均 IC:   {avg_ic:.4f}")
    print(f"IC 标准差: {ic_std:.4f}")

    print(f"\n达标情况:")
    print(f"  |IC| > 0.03:   {'✅' if abs(avg_ic) > 0.03 else '❌'} ({abs(avg_ic):.4f})")
    print(f"  |ICIR| > 0.5:  {'✅' if abs(icir) > 0.5 else '❌'} ({abs(icir):.4f})")

    last_dt = sampled_dates[-1]
    last_dt_str = pd.Timestamp(last_dt).strftime("%Y%m%d")
    last_factor = calculate_factor_value(placement_df, restricted_df, daily_df, last_dt_str)

    if not last_factor.empty:
        last_daily = daily_df[daily_df["date"] == last_dt]
        if not last_daily.empty:
            last_merged = last_factor.merge(
                last_daily[["ts_code", ret_col]],
                on="ts_code",
                how="inner"
            )
            if not last_merged.empty:
                stratified = calculate_stratified_returns(last_merged, 5, ret_col)
                if not stratified.empty:
                    print("\n--- 分层收益 ---")
                    print(stratified.to_string())

    if factor_series_list:
        turnover = calculate_turnover(factor_series_list)
        max_dd = calculate_max_drawdown(ic_list)
        print(f"\n最大回撤:  {max_dd:.2%}")
        print(f"换手率:    {turnover:.2%}")

    print("\n✅ 回测完成")


def main():
    parser = argparse.ArgumentParser(description="定增折价因子回测")
    parser.add_argument("--start-date", type=str, default=None, help="回测开始日期 YYYYMMDD")
    parser.add_argument("--end-date", type=str, default=None, help="回测结束日期 YYYYMMDD")
    parser.add_argument("--period", type=int, default=20, help="持仓周期（天）")
    parser.add_argument("--username", type=str, default=None, help="PandaAI 用户名")
    parser.add_argument("--password", type=str, default=None, help="PandaAI 密码")
    args = parser.parse_args()

    end_date = args.end_date or datetime.now().strftime("%Y%m%d")
    if args.start_date:
        start_date = args.start_date
    else:
        start_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=365)).strftime("%Y%m%d")

    print("=" * 60)
    print("A股定增折价解禁因子回测（官方SDK版 v2）")
    print(f"  period: {args.period}d")
    print("=" * 60)

    print("[backtest] 正在连接 PandaAI...")
    _init_panda_token(args.username, args.password, interactive=True)
    print("[backtest] ✅ 已连接")

    try:
        run_backtest(start_date, end_date, args.period)
    except Exception as e:
        print(f"❌ 回测失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
