---
name: skill-a-share-placement-discount-alpha
description: 当需要开发、计算、验证A股定增折价解禁Alpha因子时，使用此skill。适用于筛选高折价率定增个股，捕捉解禁后利空出尽反弹的超额收益机会。
tags: [quant, alpha, development, stock, a-share, placement, quantSkills]
---

# A股定增折价解禁 Alpha

## 适用场景

1. 用户需要计算或验证定增折价解禁因子
2. 用户需要筛选高折价率定增个股，捕捉解禁后利空出尽反弹
3. 用户提到定增、定向增发、折价率、解禁日、限售股解禁

## 因子逻辑

### 核心假设

定增（定向增发）发行价低于市价，形成折价。但实证表明：
- **高折价率定增**往往伴随利益输送（大股东低价获取股份），解禁后减持动机更强，股价表现更差
- **低折价率（接近市价）定增**说明参与者看好公司前景，愿意以接近市价参与，解禁后表现更好

核心Alpha来源是**解禁后"利空出尽"反弹**，且**低折价率股票反弹更强劲**：
- **解禁前30天**：股价承压（大股东减持预期），不适合买入
- **解禁后0-30天**：利空出尽，超跌反弹，Alpha最强
- **解禁后30-60天**：反弹延续，Alpha衰减

### 计算公式

```
# 折价率（必须用同日市价计算）
discount_rate = (market_price - issue_price) / market_price

# 距解禁天数（负=已解禁，正=未解禁）
days_to_relief = relief_date - as_of_date

# 时间权重（阶梯函数，解禁后0-30天权重最高）
time_weight = calc_time_weight(days_to_relief)

# 综合因子值（方向反转：低折价率→因子值高→买入信号）
factor_value = -discount_rate * time_weight
```

### 时间权重函数（与 factor.py 实现完全一致）

| 距解禁日范围 | 权重 | 说明 |
|--------------|------|------|
| 0 ~ 30天（已解禁） | 1.0 | Alpha最强，利空出尽反弹 |
| 31 ~ 60天（已解禁） | 0.7 | 反弹延续 |
| 61 ~ 120天（已解禁） | 0.4 | Alpha衰减 |
| -30 ~ -1天（解禁前） | 0.3 | 承压期，低权重 |
| -60 ~ -31天（解禁前） | 0.1 | 远期，极低权重 |
| 其他 / 无解禁日期 | 0.0 | 排除 |

### 排雷条件

1. **折价率 ≥ 0**：排除溢价发行
2. **必须有解禁日期**：排除无解禁信息的股票
3. **time_weight > 0**：聚焦有效窗口内
4. **排除ST/*ST股票**
5. **排除交易状态异常股票**

### 排序方向

`factor_value` 越大 → 折价率越低（接近市价）+ 接近解禁后反弹期 → 信号越强

## 输入数据

| 字段 | 来源 | 说明 |
|------|------|------|
| symbol | `get_stock_private_placement` | 股票代码 |
| announcement_date | `get_stock_private_placement` | 公告日期 |
| issue_price | `get_stock_private_placement` | 发行价格 |
| listed_date | `get_stock_private_placement` | 发行上市日期 |
| relief_date | `get_restricted_list` | 解禁日期 |
| relieve_shares | `get_restricted_list` | 解禁股份数 |
| close | `get_stock_daily` | 收盘价（计算折价率） |
| trade_status | `get_stock_daily` | 交易状态 |

### 时点对齐（as_of_date）

- **定增数据**：取 as_of_date 前已公告的所有定增（过去2年）
- **解禁数据**：取 as_of_date 前后各120天内的解禁
- **行情数据**：取 as_of_date 当日或最近交易日收盘价（前30天内最新）

### PandaAI data 实现

详见 [data_guide.md](references/data_guide.md)

## 输出结果

### 标准 Parquet 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| trade_date | str | 筛选基准日 YYYYMMDD |
| asset_type | str | "stock" |
| ts_code | str | 股票代码 |
| market | str | "cn" |
| factor_id | str | "placement_discount" |
| factor_name | str | "定增折价解禁因子" |
| factor_value | float | 综合因子值（折价率×时间权重） |
| score | float | 截面 rank 百分位 0-100 |
| rank | int | 截面排名（升序，rank=1 最值得买入） |
| signal | str | buy / hold / sell |
| confidence | float | 信号置信度 0-100 |
| data_version | str | 数据版本号 YYYYMMDD_HHMMSS |
| update_time | str | 生成时间 ISO 8601 |

### signal 生成规则

- `buy`：折价率≥15% 且 score≥80 且 time_weight>0
- `hold`：time_weight>0 但不满足buy全部条件
- `sell`：score<20

### 附加输出字段

| 字段 | 说明 |
|------|------|
| discount_rate | 折价率 |
| issue_price | 定增发行价 |
| market_price | 当前市价 |
| relief_date | 解禁日期 |
| days_to_relief | 距解禁天数（负=已解禁，正=未解禁） |
| time_weight | 时间权重 |

## 使用方式

### 认证方式

使用此 skill 需要 PandaAI 账号权限，支持以下四种认证方式：

**方式一：命令行参数**
```bash
python scripts/factor.py --username '86手机号' --password '密码'
```

**方式二：环境变量**
```bash
export PANDA_USERNAME='86手机号'
export PANDA_PASSWORD='密码'
python scripts/factor.py
```

**方式三：.env 文件**
```
PANDA_USERNAME=86手机号
PANDA_PASSWORD=密码
```

**方式四：交互式输入**
```bash
python scripts/factor.py
```

### 常用命令

```bash
# 计算因子（默认 as_of_date 为当日）
python scripts/factor.py

# 指定基准日
python scripts/factor.py --as-of-date 20250630

# 验证因子
python scripts/validate.py

# 回测因子
python scripts/backtest.py --period 20
```

## 验收要求

1. **未来函数检测通过**：折价率使用同日市价计算，公告日期不晚于基准日
2. **参数敏感性检测通过**：不同折价率阈值下IC变异系数 < 2.0
3. **样本外检测通过**：IC衰减不超过 50%
4. **回测指标达标**：|IC| > 0.03，|ICIR| > 0.5
5. **PandaAI data 数据源确认**：所有数据来自 panda_data SDK
6. **Parquet 质量检查通过**：主键唯一、字段完整、无NaN常量列
7. **验证脚本输出 PASS**：validate.py 所有检测项输出 ✅ PASS
