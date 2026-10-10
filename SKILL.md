---
name: mcd-meal-optimizer
description: 麦当劳营养×预算双目标餐搭管家。在「热量区间 + 蛋白质下限 + 预算上限」多重约束下，用麦当劳 MCP 的真实门店菜单、真实营养数据与真实优惠券，通过动态规划求出到手价最低、营养达标的餐搭方案，可用 calculate-price 复核真实成交价，确认后一键下单。门店发现不需要用户收藏门店——按城市即可拿到真实门店。当用户提出「预算内吃够蛋白」「今天吃多少卡」「帮我搭一顿达标的麦当劳」「控制热量又不想超预算」「用券后最便宜的组合」等需求时使用。触发词：麦当劳餐搭、麦麦算盘、热量预算、营养搭配、减脂怎么点、用券最省、mcd、点麦当劳。
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

> **不需要**用户在麦当劳 App 里收藏门店 —— 见「第 2 步」。

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

### 第 2 步 · 确定门店(零配置)

问一句用户所在城市即可,然后:

```bash
MCD_MCP_TOKEN=xxx python -m mcd_meal_optimizer check --city 上海
```

- 只要能读到营养库即为连通;
- 门店发现走**城市链路**(`mall-points-products` → `query-party-city`
  → `query-party-store`),**不依赖账号收藏门店**;
- 若用户已知门店编码,也可直接 `--store-code 1450713`;
- 若 `--city` 与 `--store-code` 都不可用,才回退到
  `examples/real-menu-1450713.json` 真实快照(离线复现,结果与联网一致)。

### 第 3 步 · 求解

```bash
# 推荐: 按城市自动发现门店 + 真实算价复核
MCD_MCP_TOKEN=xxx python -m mcd_meal_optimizer plan --city 上海 \
  --kcal-min 550 --kcal-max 800 --protein 30 --budget 40 --price-check

# 或直接指定门店编码
MCD_MCP_TOKEN=xxx python -m mcd_meal_optimizer plan --store-code 1450713 \
  --kcal-min 550 --kcal-max 800 --protein 30 --budget 40
```

求解目标 `--objective`:`min_price`(默认,最低到手价)/ `max_protein`
(同预算蛋白最高)/ `best_value`(每元蛋白最高)。

### 第 4 步 · 输出、复核与下单

1. 用 `plan --json` 拿结构化结果,向用户展示方案表(餐品/热量/蛋白/到手价/用券);
2. **如实转述营养覆盖率**:`plan` 输出里的
   `> 营养覆盖: X/Y 项完整; ...` 说明有多少候选因营养未收录被排除。
   这是**必须**转达给用户的限制,不要省略;
3. **下单前必须**用 `calculate-price` 复核真实成交价(`--price-check` 或
   `price` 子命令),确认与报价一致;
4. 得用户明确同意后,才加 `--confirm` 执行 `order`。

## 核心约束(务必遵守)

- **未经用户明确同意,绝不执行 `order --confirm`**,也绝不调用
  `cancel-order` / `mall-create-order` / `party-order-create` 等会产生
  真实副作用的工具。`order` 不带 `--confirm` 只做预览,可放心运行。
- **绝不把"营养未收录"的餐品当作 0 热量参与推荐**。系统已默认把这类
  餐品排除出解并标注 —— 不要绕过该门禁去"凑出一个方案"。
- 报价与实际不符时,以 `calculate-price` 返回为准,并说明差异。
- 营养/价格数据来自 MCP 实时返回,不要凭记忆补充麦当劳餐品数据。
- 输出营养结论时声明"仅供参考,不构成营养或医疗建议"。

## 常用命令速查

| 命令 | 用途 |
| --- | --- |
| `check --city 上海` | 连通性 + 账号状态 + 门店发现链路自检 |
| `tools` | 列出 MCP 当前支持的工具 |
| `nutrition --query 板烧` | 查营养 |
| `coupons` | 查卡包 + 麦麦省可领券 |
| `stores --city 上海` | **按城市发现真实门店**(不依赖账号) |
| `menu --city 上海 --top 20` | 真实菜单 + 营养覆盖统计 |
| `plan ... --price-check` | **核心**: 双目标求解 + 真实算价复核 |
| `price --item <编码>` | 指定组合真实算价 |
| `order --item <编码>` | 下单预览(加 `--confirm` 才真实建单) |
| `cancel --order-id <id>` | 取消订单 |

重新导出真实门店快照:`python scripts/snapshot_store.py --city 上海`

详见 `README.md` 与 `MCP_INTEGRATION.md`。
