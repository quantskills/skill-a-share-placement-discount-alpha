# PandaData 接口使用指南

## 认证方式

```python
import panda_data
panda_data.init_token(username="86手机号", password="密码")
```

## 本 Skill 使用的接口

### 1. get_stock_private_placement

获取股票定向增发数据。

```python
df = panda_data.get_stock_private_placement(
    start_date="20240101",
    end_date="20260720",
    market="cn"
)
```

**返回字段**：
| 字段 | 说明 |
|------|------|
| symbol | 股票代码（如 000001.SZ） |
| announcement_date | 公告日期 |
| issue_type | 发行类型（非公开发行等） |
| issue_status | 发行状态 |
| listed_date | 上市日期 |
| issued_shares | 发行股份数 |
| issue_price | 发行价格 |
| approval_date | 核准日期 |

### 2. get_restricted_list

获取股票限售解禁明细数据。

```python
df = panda_data.get_restricted_list(
    start_date="20260301",
    end_date="20261231",
    market="cn"
)
```

**返回字段**：
| 字段 | 说明 |
|------|------|
| symbol | 股票代码 |
| date | 数据日期 |
| relieve_shares | 解禁股份数 |
| relieve_date | 解禁日期 |
| shareholder | 股东名称 |
| actual_relieve_shares | 实际解禁股份数 |
| relieve_reason | 解禁原因（如"增发A股法人配售上市"） |
| shareholder_type | 股东类型（企业/自然人等） |

### 3. get_stock_daily

获取A股日线行情数据。

```python
df = panda_data.get_stock_daily(
    start_date="20260620",
    end_date="20260720",
    st=False  # 排除ST股票
)
```

**返回字段**：
| 字段 | 说明 |
|------|------|
| symbol | 股票代码 |
| date | 交易日期 |
| open / high / low / close | OHLC |
| volume | 成交量 |
| amount | 成交额 |
| pre_close | 前收盘价 |
| limit_up / limit_down | 涨停价/跌停价 |
| name | 股票名称 |
| trade_status | 交易状态（0=正常） |

## 字段映射

本 Skill 统一将 `symbol` 重命名为 `ts_code`，便于跨表连接。

## 注意事项

1. **认证方式**：必须使用 `init_token()`，不支持 `init()`
2. **日期格式**：所有日期参数为 `YYYYMMDD` 字符串
3. **市场参数**：定增和解禁接口的 `market` 默认为 `"cn"`
4. **ST过滤**：`get_stock_daily` 的 `st=False` 参数可排除ST股票
5. **解禁数据量**：解禁数据可能包含多条记录（多次解禁），需按 `ts_code` 聚合取最早解禁日
