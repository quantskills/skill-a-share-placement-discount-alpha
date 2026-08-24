#A股定增折价解禁 Alpha / A-Share Placement Discount Alpha

## 项目概述 / Overview

基于定向增发折价率与解禁事件驱动的 Alpha 因子。核心发现：**低折价率（接近市价）定增股
解禁后反弹更强劲**，高折价率定增往往伴随利益输送，解禁后表现更差。

Event-driven Alpha factor based on private placement discount rate and share unlock events.
Key finding: **low-discount (near-market-price) placements show stronger post-unlock rebounds**;
high-discount placements often involve tunneling and underperform post-unlock.

## 因子逻辑 / Factor Logic

```
discount_rate = (market_price - issue_price) / market_price
days_to_relief = relief_date - as_of_date
time_weight = calc_time_weight(days_to_relief)    # 阶梯函数
factor_value = -discount_rate × time_weight       # 方向反转
```

- 因子值越大 → 折价率越低 + 接近解禁后反弹期 → 买入信号越强
- Higher factor value → lower discount + near post-unlock rebound → stronger buy signal

## 时间权重 / Time Weight

| 距解禁日 / Days to Relief | 权重 / Weight | 说明 |
|--------------------------|--------------|------|
| 0–30 天（已解禁）| 1.0 | Alpha 最强 / Strongest |
| 31–60 天 | 0.7 | 反弹延续 / Rebound continues |
| 61–120 天 | 0.4 | Alpha 衰减 / Fading |
| 121–365 天 | 0.2 | 远期 / Remote |
| -1 ~ -30 天（解禁前）| 0.3 | 承压期 / Pressure period |
| -31 ~ -90 天 | 0.2 | 远期 / Remote |
| -91 ~ -365 天 | 0.1 | 极远 / Very remote |

## 关键文件 / Key Files

| 文件 | 说明 |
|------|------|
| `开发产物/SKILL.md` | 技能定义 / Skill definition |
| `开发产物/交接文档.md` | 交接文档 / Handover doc |
| `开发产物/scripts/factor.py` | 因子计算 / Factor calculation |
| `开发产物/scripts/validate.py` | 三层验证 / Three-layer validation |
| `开发产物/scripts/backtest.py` | 回测 / Backtest |
| `开发产物/生产产物/数据库.parquet` | 因子输出 / Factor output |

## 验证与回测结果 / Validation & Backtest

- 验证三项全过 · Three validation checks all PASS
- 回测（2025-01 ~ 2026-07，20 日周期）：IC=+0.0656，RankIC=+0.0869，ICIR=+0.4989
- Backtest: IC=+0.0656, RankIC=+0.0869, ICIR=+0.4989 (ICIR near 0.5 threshold)
- 最终产物：32 只有效定增股票，7 只 Buy 信号
- Final output: 32 valid placement stocks, 7 Buy signals

## 快速开始 / Quick Start

```bash
pip install panda_data pandas numpy pyarrow
python scripts/factor.py --as-of-date 20260720
python scripts/validate.py --base-date 20260601
python scripts/backtest.py --start-date 20250101 --end-date 20260701 --period 20
```

## 排雷条件 / Screening Conditions

1. 折价率 ≥ 0（排除溢价发行）· Discount rate ≥ 0 (exclude premium issuance)
2. 必须有解禁日期 · Must have relief date
3. time_weight > 0 · Effective window only
4. 排除 ST/*ST · Exclude ST stocks
5. 排除交易状态异常 · Exclude abnormal trading status
