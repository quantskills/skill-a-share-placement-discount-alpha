# 审查报告：skill-a-share-placement-discount-alpha

**审查日期**：2026-07-20  
**审查人**：qclaw  
**审查对象**：E:\因子skill集\skill-a-share-placement-discount-alpha

---

## 一、总体结论

**⚠️ 有条件通过——存在 2 个 P0 问题 + 3 个 P1 问题需修复**

| 维度 | 结论 |
|------|------|
| SKILL.md 合规性 | ⚠️ name 不合规 |
| factor.py 因子逻辑 | ⚠️ 1个P0 + 2个P1 |
| validate.py 验证逻辑 | ⚠️ 1个P0 + 1个P1 |
| backtest.py 回测逻辑 | ✅ 基本合理 |
| Parquet 数据质量 | ✅ 通过 |
| 交接文档 | ✅ 详尽 |

---

## 二、P0 问题（阻断性）

### P0-1：SKILL.md name 不合规

**位置**：SKILL.md 第 2 行  
**现状**：`name: a-share-placement-discount-alpha`  
**要求**：应为 `skill-a-share-placement-discount-alpha`（与仓库名一致，带 `skill-` 前缀）  
**影响**：与 quantskills 组织命名规范不一致，无法通过模板 CI 校验

### P0-2：validate.py 样本外检测逻辑错误

**位置**：validate.py `test_out_of_sample()` 函数  
**现状**：样本外检测仅比较样本内外的**平均发行价偏差率**，而非因子值的 IC 衰减  
**问题**：
- 发行价是定增事件的固有属性，不随时间变化，比较发行价均值毫无意义
- SKILL.md 验收要求明确写的是「IC 衰减不超过 50%」，但 validate.py 完全没有计算 IC
- 这是「三层验证」的第三层，实际检测内容与声明不符

**应改为**：在样本内和样本外分别计算因子 IC，比较 |IC_oos / IC_insample| 是否 ≥ 0.5

---

## 三、P1 问题（需修复）

### P1-1：回测 IC 值异常低

**位置**：交接文档 6.2 节  
**现状**：IC = 0.0062，RankIC = -0.0437，ICIR = 0.0496  
**问题**：
- SKILL.md 验收要求 `|IC| > 0.03`，但实际 IC = 0.0062 **不达标**
- RankIC 为负值（-0.0437），说明因子方向可能反了——折价率越高反而收益越低
- ICIR = 0.0496 远低于要求的 0.5
- 交接文档如实记录了这些数值但未标注「不达标」

**影响**：因子实际选股能力弱，甚至可能反向。需重新审视因子逻辑或调整信号方向

### P1-2：validate.py 三层验证名不副实

**位置**：validate.py 全局  
**现状**：
- 第一层「未来函数检测」：仅检查公告日期是否在基准日之后，**没有检测折价率计算是否使用了基准日之后的市价**
- 第二层「参数敏感性检测」：仅统计不同折价率阈值下的样本数和平均折价率，**没有检测因子稳定性**（如排名相关性）
- 第三层「样本外检测」：如 P0-2 所述，检测内容完全错误

**影响**：验证脚本输出 PASS 但实际未执行 SKILL.md 声明的验证内容

### P1-3：factor.py 时间权重与 SKILL.md 公式不一致

**位置**：factor.py `calc_time_weight()` vs SKILL.md  
**现状**：
- SKILL.md 公式：`time_decay_weight = max(0, 1 - abs(days_to_relief - (-15)) / 60)`
  - 即以 days_to_relief = -15（解禁前15天）为峰值，向两侧线性衰减，60天外为0
- factor.py 实现：分段硬编码
  - -30~30天 → 1.0
  - ±60天 → 0.7
  - ±120天 → 0.4
  - 其他 → 0.1
  - 缺失 → 0.3

**问题**：两套逻辑完全不同。SKILL.md 是连续函数，代码是阶梯函数；峰值位置不同（-15天 vs 0天）；衰减范围不同（60天 vs 120天）

---

## 四、P2 问题（建议优化）

### P2-1：days_to_relief 缺失值用 9999 填充

**位置**：factor.py `build_output()`  
**现状**：`output["days_to_relief"] = df["days_to_relief"].fillna(9999).astype(int)`  
**建议**：9999 是魔法数字，建议用 `pd.NA` 或 `-1` 表示「无解禁日期」，或在 signal 逻辑中直接排除无解禁数据的股票

### P2-2：多定增去重保留第一条（最早公告）

**位置**：factor.py `drop_duplicates(subset=["ts_code"], keep="first")`  
**现状**：同一股票多次定增只保留最早公告的一次  
**建议**：应保留**折价率最高**或**距解禁最近**的一次定增，因为这才是最有投资价值的事件

### P2-3：relief_date 为空时 time_weight = 0.3

**位置**：factor.py `calc_time_weight()`  
**现状**：没有解禁日期的股票给 0.3 的权重  
**问题**：定增折价因子的核心是解禁事件驱动，没有解禁日期的股票不应参与因子计算，给 0.3 权重会让它们获得非零因子值

### P2-4：回测 `calculate_factor_value()` 未使用时间权重

**位置**：backtest.py  
**现状**：回测中 `merged["factor_value"] = merged["discount_rate"]`，直接用折价率作为因子值，**没有乘以 time_weight**  
**问题**：回测的因子定义与 factor.py 不一致，回测结果不能代表真实因子表现

### P2-5：交接文档缺少 references/data_guide.md

**位置**：文件结构  
**现状**：交接文档列出了 references/ 目录但实际不存在 data_guide.md  
**影响**：缺少数据接口字段的详细映射文档

---

## 五、Parquet 数据检查

| 检查项 | 结果 |
|--------|------|
| 行数 | 49 |
| 列数 | 19 |
| ts_code 唯一性 | ✅ 0 重复 |
| signal 分布 | buy=10, hold=30, sell=9 |
| score 范围 | 2.04 - 100.0 |
| factor_value 范围 | 0.0015 - 0.7727 |
| discount_rate 范围 | 0.5% - 92.8% |
| 空值 | trade_date / asset_type 全 NaN |

**⚠️ trade_date 和 asset_type 全部为 NaN**——`build_output()` 中用 `as_of_date` 赋值但可能因类型问题未写入成功。

---

## 六、合规性检查清单

| 项目 | 状态 | 说明 |
|------|------|------|
| SKILL.md name 格式 | ❌ | 缺 `skill-` 前缀 |
| quantSkills 元数据 | ❌ | 缺失 |
| factor.py 无 NotImplementedError | ✅ | |
| validate.py 真实检测 | ❌ | 检测内容与声明不符 |
| backtest.py IC 定义 | ⚠️ | IC 计算正确但因子值定义与 factor.py 不一致 |
| data_guide.md | ❌ | 缺失 |
| 生产产物/数据库.parquet | ✅ | 存在，49行 |
| Parquet 主键唯一 | ✅ | |
| Parquet 字段完整 | ⚠️ | trade_date / asset_type 全 NaN |
| IC 达标 (|IC|>0.03) | ❌ | IC=0.0062 |
| ICIR 达标 (|ICIR|>0.5) | ❌ | ICIR=0.0496 |

---

## 七、修复优先级

1. **P0-1**：SKILL.md name 改为 `skill-a-share-placement-discount-alpha` + 补 quantSkills 元数据
2. **P0-2**：validate.py 样本外检测改为 IC 衰减检测
3. **P1-1**：回测 IC 不达标——需审视因子方向（RankIC 为负），可能需要反转信号或重新设计因子
4. **P1-2**：validate.py 三层验证实现与声明对齐
5. **P1-3**：统一 SKILL.md 公式与 factor.py 实现
6. **P2-4**：backtest.py 因子值加入 time_weight
7. **P2-5**：补 references/data_guide.md
8. **P2-1~3**：优化缺失值处理和去重逻辑
