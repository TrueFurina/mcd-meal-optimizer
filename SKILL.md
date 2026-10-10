---
name: mcd-meal-optimizer
description: 麦当劳营养×预算双目标餐搭管家。在「热量区间 + 蛋白质下限 + 预算上限」多重约束下，调用麦当劳 MCP 的真实营养库、真实门店菜单与真实优惠券，用动态规划求出到手价最低、营养达标的餐搭方案，并可一键下单。当用户提出「预算内吃够蛋白」「今天吃多少卡」「帮我搭一顿达标的麦当劳」「控制热量又不想超预算」「用券后最便宜的组合」等需求时使用。触发词：麦当劳餐搭、麦麦算盘、热量预算、营养搭配、减脂怎么点、用券最省、mcd、点麦当劳。
---

# 麦麦算盘 (mcd-meal-optimizer)

在**预算**与**营养**双约束下,从麦当劳真实菜单里算出最优餐搭,而
不是"凭感觉推荐一个套餐"。

## 何时使用

- 用户给出热量/蛋白质目标或预算上限,想点麦当劳;
- 用户问"今天这顿吃多少卡 / 摄入了多少蛋白";
- 用户手上有一堆优惠券,想知道哪套组合券后最便宜;
- 用户想把一顿饭的热量控制在某个区间内(减脂/增肌/控糖)。

## 前置条件

1. 已申请麦当劳 MCP Token: https://open.mcd.cn/mcp
2. 已配置 MCP 连接器 `mcd-mcp`(见 `mcp-config.example.json`),
   并在连接器管理页【启用】;
3. 环境变量 `MCD_MCP_TOKEN` 已设置(本 Skill 的脚本可直接读取)。

## 执行流程

### 第 1 步 · 摸清用户约束

向用户确认(缺失则用默认值,不要反复追问):

| 参数 | 含义 | 默认 |
| --- | --- | --- |
| `kcal_min` / `kcal_max` | 这一餐的热量区间 (kcal) | 500 / 800 |
| `protein` | 蛋白质下限 (g) | 30 |
| `budget` | 到手价预算上限 (元) | 40 |
| `max_items` | 最多几件 | 4 |
| `include` / `exclude` | 必须含 / 排除的关键词 | 无 |

### 第 2 步 · 自检账号状态

```bash
MCD_MCP_TOKEN=xxx python -m mcd_meal_optimizer check
```

- 只要能读到营养库即为连通。
- **若提示"未取到门店"**: 门店/菜单/下单类工具需要账号侧配置。
  请让用户在麦当劳 App 收藏一家门店,或向用户索要 `storeCode`,
  然后带 `--store-code <code>` 重新执行。

### 第 3 步 · 求解

有门店:

```bash
MCD_MCP_TOKEN=xxx python -m mcd_meal_optimizer plan \
  --kcal-min 550 --kcal-max 800 --protein 30 --budget 40 \
  --store-code <storeCode>
```

无门店(离线示例路径,输出会明确标注为示例数据):

```bash
MCD_MCP_TOKEN=xxx python -m mcd_meal_optimizer plan \
  --kcal-min 550 --kcal-max 800 --protein 30 --budget 40
```

### 第 4 步 · 输出与下单

1. 用 `plan --json` 拿到结构化结果,向用户展示方案表(热量/蛋白/到手价/用券情况);
2. **下单前必须**用 `calculate-price` 复算最终价,确认与报价一致;
3. 得用户明确同意后再调用 `create-order`(会真实产生订单!)。

## 核心约束(务必遵守)

- **未经用户明确同意,绝不调用 `create-order` / `cancel-order` /
  `mall-create-order` / `party-order-create` 等会产生真实副作用的工具。**
- 报价与实际不符时,以 `calculate-price` 返回为准,并说明差异。
- 营养/价格数据来自 MCP 实时返回,不要凭记忆补充麦当劳餐品数据。
- 输出营养结论时声明"仅供参考,不构成营养或医疗建议"。

## 常用命令速查

| 命令 | 用途 |
| --- | --- |
| `check` | 连通性 + 账号状态自检 |
| `tools` | 列出 MCP 当前支持的工具 |
| `nutrition --query 板烧` | 查营养 |
| `coupons` | 查卡包 + 麦麦省可领券 |
| `stores --city 上海` | 查门店 |
| `menu --store-code X` | 查门店菜单 |
| `plan ...` | **核心**: 双目标求解 |

详见 `README.md` 与 `MCP_INTEGRATION.md`。
