#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股定增折价解禁因子计算脚本（官方SDK版）

因子逻辑（v2 重新设计）：
  核心Alpha来源：解禁后"利空出尽"反弹
  - 解禁前30天：股价承压（大股东减持预期），不适合买入
  - 解禁后0-30天：利空出尽，超跌反弹，Alpha最强
  - 解禁后30-60天：反弹延续，Alpha衰减
  - 因子值 = 折价率 × 时间权重（解禁后权重高，解禁前权重低/排除）

核心接口：
  - get_stock_private_placement: 定增数据
  - get_restricted_list: 限售股解禁
  - get_stock_daily: 日线行情

排雷条件：
  - 折价率 ≥ 0（排除溢价发行）
  - 必须有解禁日期（排除无解禁信息的股票）
  - 聚焦解禁后0-60天窗口（Alpha最强区间）
  - 排除ST/*ST股票
  - 排除交易状态异常股票
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import panda_data


def _load_env_file(env_path: str = None):
    """加载 .env 文件到环境变量。

    认证优先级为 命令行参数 > 环境变量 > .env 文件，因此 .env 只能补充
    尚未设置的键，绝不覆盖已存在的环境变量（否则会顶掉 shell export 或
    上游已注入的凭据）。
    """
    if env_path is None:
        env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    # 仅在环境变量缺失时补充，保持 .env 的最低优先级
                    if key not in os.environ:
                        os.environ[key] = value.strip()


def _init_panda_token(
    username: str = None,
    password: str = None,
    interactive: bool = True,
):
    _load_env_file()

    if not username:
        username = os.environ.get("PANDA_USERNAME", "")
    if not password:
        password = os.environ.get("PANDA_PASSWORD", "")

    if interactive and not username:
        username = input("请输入 PandaAI 用户名（86手机号）: ").strip()
    if interactive and not password:
        password = input("请输入 PandaAI 密码: ").strip()

    if not username or not password:
        raise RuntimeError(
            "❌ 缺少认证信息。请通过以下方式之一提供：\n"
            "  1. 命令行参数: --username '86手机号' --password '密码'\n"
            "  2. 环境变量: export PANDA_USERNAME='86手机号' PANDA_PASSWORD='密码'\n"
            "  3. .env 文件\n"
            "  4. 运行时交互式输入\n"
        )

    panda_data.init_token(username, password)
    print("[API] ✅ 登录成功")


def _find_column(df: pd.DataFrame, candidates: list) -> str:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def get_private_placement_data(start_date: str, end_date: str) -> pd.DataFrame:
    print(f"[factor] 获取定增数据: {start_date} ~ {end_date}")
    try:
        df = panda_data.get_stock_private_placement(
            start_date=start_date,
            end_date=end_date,
            market="cn"
        )
        if df is not None and not df.empty:
            print(f"  定增数据: {len(df)} 条记录")
            sym_col = _find_column(df, ["symbol", "ts_code", "stock_symbol"])
            if sym_col:
                df = df.rename(columns={sym_col: "ts_code"})
            return df
    except Exception as e:
        print(f"  ⚠️  获取定增数据失败: {e}")
    return pd.DataFrame()


def get_restricted_data(start_date: str, end_date: str) -> pd.DataFrame:
    print(f"[factor] 获取限售股解禁数据: {start_date} ~ {end_date}")
    try:
        df = panda_data.get_restricted_list(
            start_date=start_date,
            end_date=end_date,
            market="cn"
        )
        if df is not None and not df.empty:
            print(f"  限售股解禁数据: {len(df)} 条记录")
            sym_col = _find_column(df, ["symbol", "ts_code", "stock_symbol"])
            if sym_col:
                df = df.rename(columns={sym_col: "ts_code"})
            date_col = _find_column(df, ["relieve_date", "unlock_date"])
            if date_col:
                df = df.rename(columns={date_col: "relief_date"})
            return df
    except Exception as e:
        print(f"  ⚠️  获取限售股数据失败: {e}")
    return pd.DataFrame()


def get_latest_daily_before(as_of_date: str, lookback_days: int = 30) -> pd.DataFrame:
    start_dt = datetime.strptime(as_of_date, "%Y%m%d") - timedelta(days=lookback_days)
    start_date = start_dt.strftime("%Y%m%d")
    print(f"[factor] 获取A股日线数据: {start_date} ~ {as_of_date}")
    try:
        df = panda_data.get_stock_daily(
            start_date=start_date,
            end_date=as_of_date,
            st=False
        )
        if df is not None and not df.empty:
            sym_col = _find_column(df, ["symbol", "ts_code", "stock_symbol"])
            if sym_col:
                df = df.rename(columns={sym_col: "ts_code"})
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
            latest_df = df.sort_values("date").groupby("ts_code").last().reset_index()
            print(f"  最新日线数据: {len(latest_df)} 条记录")
            return latest_df
    except Exception as e:
        print(f"  ⚠️  获取日线数据失败: {e}")
    return pd.DataFrame()


def calc_time_weight(days_to_relief: float) -> float:
    """
    时间权重函数：聚焦解禁后利空出尽反弹

    逻辑：
      - 解禁后0-30天：权重1.0（Alpha最强，利空出尽反弹）
      - 解禁后31-60天：权重0.7（反弹延续）
      - 解禁后61-120天：权重0.4（Alpha衰减）
      - 解禁后121-365天：权重0.2（远期，低权重）
      - 解禁前-30~0天：权重0.3（承压期，低权重）
      - 解禁前-31~-90天：权重0.2（远期，低权重）
      - 解禁前-91~-365天：权重0.1（远期，极低权重）
      - 无解禁日期或超出窗口：返回0（排除）
    """
    if pd.isna(days_to_relief):
        return 0.0
    days = float(days_to_relief)
    if 0 <= days <= 30:
        return 1.0
    elif 30 < days <= 60:
        return 0.7
    elif 60 < days <= 120:
        return 0.4
    elif 120 < days <= 365:
        return 0.2
    elif -30 <= days < 0:
        return 0.3
    elif -90 <= days < -30:
        return 0.2
    elif -365 <= days < -90:
        return 0.1
    else:
        return 0.0


def calculate_placement_discount_factor(
    placement_df: pd.DataFrame,
    restricted_df: pd.DataFrame,
    daily_df: pd.DataFrame,
    as_of_date: str,
) -> pd.DataFrame:
    if placement_df.empty or daily_df.empty:
        return pd.DataFrame()

    print(f"[factor] 计算定增折价因子...")

    placement_df = placement_df.copy()
    daily_df = daily_df.copy()

    price_col = _find_column(daily_df, ["close", "Close", "CLOSE"])
    if not price_col:
        print("  ❌ 日线数据无收盘价列")
        return pd.DataFrame()

    daily_df["market_price"] = pd.to_numeric(daily_df[price_col], errors="coerce")

    merged = placement_df.merge(
        daily_df[["ts_code", "market_price", "name", "trade_status"]],
        on="ts_code",
        how="inner"
    )

    issue_price_col = _find_column(merged, ["issue_price", "IssuePrice"])
    if issue_price_col:
        merged["issue_price"] = pd.to_numeric(merged[issue_price_col], errors="coerce")

    merged = merged.dropna(subset=["market_price", "issue_price"])
    merged = merged[merged["market_price"] > 0]
    merged = merged[merged["issue_price"] > 0]

    merged["discount_rate"] = (merged["market_price"] - merged["issue_price"]) / merged["market_price"]
    merged = merged[merged["discount_rate"] >= 0]

    if not restricted_df.empty:
        restricted_df = restricted_df.copy()
        restricted_df["relief_date_dt"] = pd.to_datetime(
            restricted_df["relief_date"], format="%Y%m%d", errors="coerce"
        )
        relief_agg = restricted_df.groupby("ts_code").agg(
            relief_date=("relief_date_dt", "min"),
            total_relieve_shares=("relieve_shares", "sum"),
        ).reset_index()
        merged = merged.merge(relief_agg, on="ts_code", how="inner")
    else:
        print("  ❌ 无限售股解禁数据")
        return pd.DataFrame()

    as_of_dt = datetime.strptime(as_of_date, "%Y%m%d")
    merged["days_to_relief"] = (merged["relief_date"] - as_of_dt).dt.days

    merged["time_weight"] = merged["days_to_relief"].apply(calc_time_weight)

    merged = merged[merged["time_weight"] > 0]

    # 因子方向反转：实证表明高折价率定增股解禁后表现更差（利益输送+减持动机）
    # 低折价率（接近市价）定增股表现更好（参与者看好公司前景）
    merged["factor_value"] = -merged["discount_rate"] * merged["time_weight"]

    merged = merged[merged["trade_status"] == 0]
    name_col = _find_column(merged, ["name", "stock_name"])
    if name_col:
        st_mask = merged[name_col].str.contains("ST", na=False)
        merged = merged[~st_mask]

    # 去重：保留最低折价率的定增（因子方向反转后，低折价率=好）
    merged = merged.sort_values("discount_rate", ascending=True)
    merged = merged.drop_duplicates(subset=["ts_code"], keep="first")

    if merged.empty:
        return pd.DataFrame()

    merged["score"] = merged["factor_value"].rank(pct=True) * 100
    merged["rank"] = merged["factor_value"].rank(ascending=False).astype(int)

    buy_threshold = 80
    sell_threshold = 20
    # signal条件：仅基于score，不限制折价率（因子方向已反转，低折价率=高因子值=买入）
    conditions = [
        merged["score"] >= buy_threshold,
        merged["score"] < sell_threshold,
    ]
    choices = ["buy", "sell"]
    merged["signal"] = np.select(conditions, choices, default="hold")

    merged["confidence"] = merged["score"].apply(
        lambda x: min(100, max(0, (x - 50) * 2)) if x >= 50 else min(100, max(0, (50 - x) * 2))
    )

    return merged


def build_output(df: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    output = pd.DataFrame({
        "trade_date": [as_of_date] * len(df),
        "asset_type": ["stock"] * len(df),
        "ts_code": df["ts_code"].values,
        "market": ["cn"] * len(df),
        "factor_id": ["placement_discount"] * len(df),
        "factor_name": ["定增折价解禁因子"] * len(df),
        "factor_value": df["factor_value"].values,
        "score": df["score"].values,
        "rank": df["rank"].values,
        "signal": df["signal"].values,
        "confidence": df["confidence"].values,
        "data_version": [datetime.now().strftime("%Y%m%d_%H%M%S")] * len(df),
        "update_time": [datetime.now().isoformat()] * len(df),
        "discount_rate": df["discount_rate"].values,
        "issue_price": df["issue_price"].values,
        "market_price": df["market_price"].values,
        "relief_date": df["relief_date"].dt.strftime("%Y%m%d").fillna("").values,
        "days_to_relief": df["days_to_relief"].values,
        "time_weight": df["time_weight"].values,
    })

    return output


def calculate_factor(as_of_date: str = None, username: str = None, password: str = None):
    print("=" * 60)
    print("A股定增折价解禁因子计算（官方SDK版 v2）")
    print(f"  as_of_date: {as_of_date}")
    print(f"  output:     开发产物/生产产物/数据库.parquet")
    print("=" * 60)

    print("[factor] 正在连接 PandaAI...")
    _init_panda_token(username, password)
    print("[factor] ✅ 已连接")

    if as_of_date is None:
        as_of_date = datetime.now().strftime("%Y%m%d")

    start_dt = datetime.strptime(as_of_date, "%Y%m%d") - timedelta(days=1095)
    placement_start = start_dt.strftime("%Y%m%d")

    relief_start_dt = datetime.strptime(as_of_date, "%Y%m%d") - timedelta(days=365)
    relief_end_dt = datetime.strptime(as_of_date, "%Y%m%d") + timedelta(days=365)
    relief_start = relief_start_dt.strftime("%Y%m%d")
    relief_end = relief_end_dt.strftime("%Y%m%d")

    print(f"[factor] 数据时间范围:")
    print(f"  定增公告: {placement_start} ~ {as_of_date}")
    print(f"  解禁日期: {relief_start} ~ {relief_end}")

    placement_df = get_private_placement_data(placement_start, as_of_date)
    restricted_df = get_restricted_data(relief_start, relief_end)
    daily_df = get_latest_daily_before(as_of_date, lookback_days=30)

    result_df = calculate_placement_discount_factor(
        placement_df, restricted_df, daily_df, as_of_date
    )

    if result_df.empty:
        print("[factor] ❌ 因子计算结果为空")
        return

    output = build_output(result_df, as_of_date)

    output_path = Path(__file__).parent.parent / "生产产物" / "数据库.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        output_path.unlink()

    output.to_parquet(str(output_path), index=False)

    print(f"[factor] Parquet 已保存: {output_path}")
    print(f"  行数: {len(output)}, 列数: {len(output.columns)}")
    print(f"  signal 分布: {output['signal'].value_counts().to_dict()}")
    print(f"  score 范围: [{output['score'].min():.1f}, {output['score'].max():.1f}]")
    print(f"  折价率范围: [{output['discount_rate'].min():.1%}, {output['discount_rate'].max():.1%}]")
    print(f"  距解禁日范围: [{output['days_to_relief'].min():.0f}, {output['days_to_relief'].max():.0f}]")

    buy_count = (output["signal"] == "buy").sum()
    hold_count = (output["signal"] == "hold").sum()
    sell_count = (output["signal"] == "sell").sum()
    print(f"[factor] 筛选完成: buy={buy_count}, hold={hold_count}, sell={sell_count}")


def main():
    parser = argparse.ArgumentParser(description="A股定增折价解禁因子计算")
    parser.add_argument("--as-of-date", type=str, default=None, help="基准日 YYYYMMDD")
    parser.add_argument("--username", type=str, default=None, help="PandaAI 用户名")
    parser.add_argument("--password", type=str, default=None, help="PandaAI 密码")
    args = parser.parse_args()

    try:
        calculate_factor(args.as_of_date, args.username, args.password)
    except Exception as e:
        print(f"[factor] ❌ 因子计算失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
