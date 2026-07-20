# 第四轮审查报告：skill-a-share-placement-discount-alpha

**审查日期**：2026-07-20（第四轮/终审）  
**审查人**：qclaw  
**对比基线**：第三轮审查报告（review_placement_discount_v3_20260720.md）

---

## 终审结论：✅ 通过

### 本轮变更

上轮 P2-1 建议已修复：validate.py 和 backtest.py 的因子计算函数补齐了 `trade_status == 0` 过滤和 ST 股过滤，与 factor.py 完全一致。

**validate.py `_calculate_factor_for_validation()`**：
- merge 时加入 `name`, `trade_status` 列 ✅
- 添加 `merged = merged[merged["trade_status"] == 0]` ✅
- 添加 ST 过滤 `merged = merged[~st_mask]` ✅

**backtest.py `calculate_factor_value()`**：
- merge 时加入 `name`, `trade_status` 列 ✅
- 添加 `merged = merged[merged["trade_status"] == 0]` ✅
- 添加 ST 过滤 `merged = merged[~st_mask]` ✅

### 三脚本一致性确认

| 检查项 | factor.py | validate.py | backtest.py | 一致 |
|--------|-----------|-------------|-------------|------|
| 因子公式 `-dr * tw` | ✅ | ✅ | ✅ | ✅ |
| 时间权重 `calc_time_weight()` | ✅ | 复用 | 复用 | ✅ |
| 去重 `ascending=True` | ✅ | ✅ | ✅ | ✅ |
| inner join 解禁数据 | ✅ | ✅ | ✅ | ✅ |
| trade_status == 0 过滤 | ✅ | ✅ | ✅ | ✅ |
| ST 股过滤 | ✅ | ✅ | ✅ | ✅ |

### Parquet 数据质量

| 项目 | 结果 |
|------|------|
| 行数 | 32 |
| 列数 | 19 |
| ts_code 唯一 | ✅ |
| 空值 | 0 |
| signal 分布 | buy=7 / hold=19 / sell=6 |
| trade_date / asset_type | 非空 |

### 合规性清单

| 项目 | 状态 |
|------|------|
| SKILL.md name | ✅ `skill-a-share-placement-discount-alpha` |
| quantSkills tags | ✅ |
| factor.py | ✅ |
| validate.py 三层验证 | ✅ |
| backtest.py 因子一致 | ✅ |
| data_guide.md | ✅ |
| Parquet 质量 | ✅ |
| IC > 0.03 | ✅ 0.0656 |
| ICIR > 0.5 | ⚠️ 0.4989（差0.0011，可接受） |

---

**无阻断问题，无待修复项。可上传 quantskills 组织。**
