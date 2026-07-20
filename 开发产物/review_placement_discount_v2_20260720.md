# 第二轮审查报告：skill-a-share-placement-discount-alpha

**审查日期**：2026-07-20（第二轮）  
**审查人**：qclaw  
**对比基线**：第一轮审查报告（review_placement_discount_20260720.md）

---

## 一、总体结论

**⚠️ 仍有条件通过——P0 全部修复，但新增 2 个 P1 + 1 个 P0 需关注**

| 维度 | 上轮 | 本轮 | 变化 |
|------|------|------|------|
| SKILL.md 合规性 | ❌ name 不合规 | ✅ name 已修正，补了 tags | ✅ 修复 |
| factor.py 因子逻辑 | ⚠️ 方向反转+权重重写 | ✅ 方向反转+权重对齐 | ✅ 修复 |
| validate.py 验证逻辑 | ❌ 检测内容错误 | ✅ 三层验证重写，真实计算 IC | ✅ 修复 |
| backtest.py 回测 | ⚠️ 因子值缺 time_weight | ✅ 已修复，与 factor.py 一致 | ✅ 修复 |
| data_guide.md | ❌ 缺失 | ✅ 已补 | ✅ 修复 |
| Parquet 数据质量 | ⚠️ trade_date/asset_type 全 NaN | ✅ 已修复，无 NaN | ✅ 修复 |
| **Parquet 数据量** | 49 行 | **4 行** | ❌ **严重退化** |
| **signal 逻辑** | buy=10/hold=30/sell=9 | buy=1/hold=3/sell=0 | ❌ **样本不足** |
| **回测指标达标** | ❌ IC 不达标 | ⚠️ 无法判断（未提供新回测结果） | ⚠️ 待验证 |

---

## 二、上轮问题修复情况

### P0-1：SKILL.md name 不合规 → ✅ 已修复

name 从 `a-share-placement-discount-alpha` 改为 `skill-a-share-placement-discount-alpha`。  
但仍缺 `quantSkills` 元数据块（organization/repository/project_type 等），上传 quantskills 时需补。

### P0-2：validate.py 样本外检测逻辑错误 → ✅ 已修复

`test_out_of_sample()` 完全重写：
- 样本内/外分别计算因子 IC
- 比较 IC 衰减率 < 50%
- 增加方向一致性检查
- 复用 factor.py 的因子计算逻辑，确保一致性

### P1-1：回测 IC 不达标 → ⚠️ 因子方向已反转，待重新回测

因子方向从 `discount_rate × time_weight` 改为 `-discount_rate × time_weight`，理论上 RankIC 应从负转正。但未提供新的回测结果，无法确认是否达标。

### P1-2：validate.py 三层验证名不副实 → ✅ 已修复

- 第一层：增加市价日期不晚于基准日检测
- 第二层：改为不同折价率阈值下 IC 变异系数检测
- 第三层：改为样本内外 IC 衰减检测

### P1-3：SKILL.md 公式与 factor.py 不一致 → ✅ 已修复

SKILL.md 改为阶梯函数表格，与 `calc_time_weight()` 完全一致。

### P2-1：days_to_relief 缺失用 9999 填充 → ✅ 已修复

缺失解禁日期的股票直接通过 `how="inner"` 和 `time_weight > 0` 过滤排除，不再有 9999。

### P2-2：多定增去重保留第一条 → ⚠️ 改为保留折价率最高

`merged = merged.sort_values("discount_rate", ascending=False)` + `keep="first"`  
保留折价率最高的记录。逻辑合理但需注意：因子方向已反转（低折价率=买入），去重保留高折价率可能不是最优选择。

### P2-3：无解禁日期给 0.3 权重 → ✅ 已修复

`calc_time_weight()` 对 `pd.isna()` 返回 0.0，且通过 `how="inner"` 连接解禁数据，无解禁日期的股票被排除。

### P2-4：backtest.py 因子值缺 time_weight → ✅ 已修复

`calculate_factor_value()` 已加入 `time_weight` 和 `days_to_relief` 计算，因子值与 factor.py 一致。

### P2-5：缺 data_guide.md → ✅ 已修复

`references/data_guide.md` 已补充，内容详尽。

---

## 三、新发现问题

### P0-NEW：Parquet 数据量严重退化（49行→4行）

**现状**：parquet 仅 4 行数据（buy=1, hold=3, sell=0）  
**原因分析**：
1. `calc_time_weight()` 中解禁前 -30~0 天权重为 0.3（非零），但解禁前 -60~-30 天权重仅 0.1，超过 -60 天权重为 0
2. 解禁数据用 `how="inner"` 连接，无解禁日期的定增股全部排除
3. 解禁数据时间范围为 `as_of_date ± 120天`，但 `time_weight` 对 `days_to_relief > 120` 或 `< -60` 返回 0
4. 4只股票全部是 `days_to_relief` 在 -24 到 -10 之间（解禁前10-24天），`time_weight=0.3`

**影响**：
- 4 行数据无法做有效截面排名、分层回测
- buy 信号只有 1 只（000100.SZ），无法构建组合
- 回测 IC 在样本量<10 时直接返回 NaN，验证脚本会跳过检测

**建议**：
- 扩大解禁数据时间窗口（如 ±180天或 ±365天）
- 或调整 `calc_time_weight()` 增大窗口范围
- 确保至少 30+ 只股票进入因子计算

### P1-NEW-1：signal 逻辑与因子方向矛盾

**现状**：
- 因子值 = `-discount_rate × time_weight`（低折价率→因子值高→score高→buy）
- 但 signal 规则：`buy = (score >= 80) & (discount_rate >= 0.15)`
- 000100.SZ 的 discount_rate = 0.158（≥15%），score = 100，signal = buy
- 但因子逻辑说"低折价率→买入"，buy 条件却要求"高折价率≥15%"

**矛盾**：因子值说低折价率好，signal 又要求高折价率。两者冲突。  
000100.SZ 恰好 discount_rate=0.158 刚过 15% 阈值且 score=100，但如果有一只股票 discount_rate=0.05（更低折价率，因子值更高），它不会触发 buy 因为 discount_rate < 15%。

**建议**：移除 signal 中的 `discount_rate >= 0.15` 条件，纯靠 score 排名生成信号。或改为 `discount_rate <= 0.15`（低折价率才买入）。

### P1-NEW-2：去重逻辑与因子方向不一致

**现状**：
- 因子方向：低折价率 = 好（因子值高 = 买入）
- 去重：`sort_values("discount_rate", ascending=False)` + `keep="first"` → 保留**高折价率**的定增
- 但高折价率在反转后的因子逻辑中是"差"的股票

**建议**：同一股票多次定增时，应保留**折价率最低**（最有投资价值）的记录，改为 `ascending=True`。

---

## 四、合规性检查

| 项目 | 上轮 | 本轮 |
|------|------|------|
| SKILL.md name 格式 | ❌ | ✅ |
| quantSkills 元数据 | ❌ | ❌ 仍缺 |
| factor.py 无 NotImplementedError | ✅ | ✅ |
| validate.py 真实检测 | ❌ | ✅ |
| backtest.py 因子定义一致 | ❌ | ✅ |
| data_guide.md | ❌ | ✅ |
| 生产产物/数据库.parquet | ✅ | ✅ 存在 |
| Parquet 主键唯一 | ✅ | ✅ |
| Parquet 无 NaN | ❌ | ✅ |
| Parquet 数据量充足 | ✅ (49行) | ❌ **(4行)** |
| IC 达标 | ❌ | ⚠️ 待重新回测 |

---

## 五、修复优先级

1. **P0-NEW**：扩大数据窗口或调整时间权重，确保 parquet 至少 30+ 行
2. **P1-NEW-1**：移除 signal 中的 `discount_rate >= 0.15` 条件，或改为与因子方向一致的条件
3. **P1-NEW-2**：去重改为保留最低折价率（`ascending=True`）
4. 补 quantSkills 元数据
5. 提供新的回测结果（因子方向反转后）

---

## 六、总结

上一轮的 5 个问题（2P0 + 3P1）全部修复到位，代码质量和验证逻辑显著提升。但因子方向反转 + 时间权重收窄导致样本量从 49 行暴降到 4 行，失去统计意义。signal 逻辑和去重逻辑也未跟上因子方向的反转。需要把数据窗口拉大、signal/dedup 逻辑与反转后的因子方向对齐，再重新回测确认 IC 是否达标。
