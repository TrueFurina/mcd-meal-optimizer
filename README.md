# 麦麦算盘 · mcd-meal-optimizer

**在预算内吃够营养,在营养达标时花得最少。**

一个基于**麦当劳 MCP** 的双目标餐搭求解器:输入「热量区间 + 蛋白质下限 +
预算上限」,调用麦当劳真实的营养库、门店菜单与优惠券,用动态规划求出
**到手价最低且营养达标**的组合,并可一键下单。

> 参赛作品 —— 麦当劳程序员创意开发大赛。本项目由参赛者独立开发,非麦当劳官方产品。

---

## 目录

- [它解决什么问题](#它解决什么问题)
- [和"推荐个套餐"有什么不同](#和推荐个套餐有什么不同)
- [快速开始](#快速开始)
- [真实运行示例](#真实运行示例)
- [支持的 MCP 工具](#支持的-mcp-工具)
- [目标用户](#目标用户)
- [数据真实性说明](#数据真实性说明)
- [正确性验证](#正确性验证)
- [项目结构](#项目结构)
- [常见问题](#常见问题)
- [免责声明](#免责声明)

---

## 它解决什么问题

"减脂期怎么点麦当劳"是一个高频但没人认真算的问题:

- 想控热量,但**不知道具体点了多少卡**;
- 想多吃蛋白,但**不知道哪几件组合最划算**;
- 手上有一堆优惠券,但**不知道哪张能用在这单上**;
- 想知道"我这顿花了多少钱",但**券后价要算半天**。

市面上多数"套餐推荐"靠的是模型凭记忆报数 —— 热量记错、价格过时、
券根本没算。**麦麦算盘不猜**:所有营养、菜单、价格、优惠券都来自
麦当劳 MCP 的实时接口,求解过程是一个可复现的约束优化问题。

## 和"推荐个套餐"有什么不同

| | 常见做法 | 麦麦算盘 |
| --- | --- | --- |
| 数据来源 | 模型记忆/静态表 | MCP 实时接口 (营养库/菜单/券/价格) |
| 决策方式 | 提示词让模型"挑一个" | **双约束动态规划求最优解** |
| 优惠券 | 忽略或口头提及 | 解析券规则并计入到手价 |
| 可复现性 | 换个问法结果就变 | 同输入必得同输出,有单元测试 |
| 失败处理 | 编造数据 | 明确降级并标注"示例数据" |

核心求解目标(三选一,`--objective`):

- `min_price`(默认)—— 满足营养约束的**最低到手价**;
- `max_protein` —— 同等预算下**蛋白质最高**;
- `best_value` —— **每元蛋白**最高。

## 快速开始

### 1. 申请 MCP Token

前往 <https://open.mcd.cn/mcp>,手机号登录后在【控制台】激活并复制
MCP Token。

### 2. 配置 MCP 连接器

把 `mcp-config.example.json` 的内容填进 MCP 客户端,并替换
`${MCD_MCP_TOKEN}` 为你的真实 Token:

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": { "Authorization": "Bearer ${MCD_MCP_TOKEN}" }
    }
  }
}
```

### 3. 设置环境变量

```bash
# Linux / macOS
export MCD_MCP_TOKEN=你的Token

# Windows PowerShell (用户级持久化)
[Environment]::SetEnvironmentVariable('MCD_MCP_TOKEN','你的Token','User')
```

### 4. 运行

无需安装任何第三方依赖,Python 3.10+ 直接跑:

```bash
python -m mcd_meal_optimizer check      # 自检
python -m mcd_meal_optimizer plan --kcal-min 550 --kcal-max 800 --protein 30 --budget 40
```

## 真实运行示例

### 自检

```console
$ python -m mcd_meal_optimizer check
麦麦算盘 · 麦当劳营养×预算餐搭管家 v1.0.0
- MCP 服务: https://mcp.mcd.cn
- 连接: OK
- 积分: 0
- 营养库: 158 款餐品
- 券: 共 8 张 (卡包 + 麦麦省)
- 配送地址: 0 个
- 收藏门店: 0 家
  ! 未取到门店。门店/菜单/下单类工具需要账号侧配置:
    在麦当劳 App 收藏一家门店, 或指定 --store-code 手动传入门店编码。
```

### 求解:550-800 kcal / 蛋白 ≥ 30g / 预算 ≤ 40 元

```console
$ python -m mcd_meal_optimizer plan --kcal-min 550 --kcal-max 800 --protein 30 --budget 40
约束: 550-800 kcal | 蛋白≥30g | 预算≤¥40 | 件数 1-4

## 方案 1 — 到手 ¥31.00（原价 ¥31.00）
- 营养: 663 kcal / 蛋白 31.0 g
- 吉士汉堡包 ¥15.50
- 麦香鸡 ¥15.50

## 方案 2 — 到手 ¥31.00（原价 ¥31.00）
- 营养: 611 kcal / 蛋白 30.0 g
- 麦辣鸡翅-2块 ¥12.50
- 鸡肉蛋沙拉叠叠卷 ¥18.50
```

### 优惠券真实计入到手价

```console
$ python -m mcd_meal_optimizer plan --kcal-min 0 --kcal-max 250 --protein 0 --budget 30 --include 美式
## 方案 1 — 到手 ¥9.90（原价 ¥17.00）
- 营养: 13 kcal / 蛋白 1.0 g
- 冰美式中杯 ¥9.90  ← 用券「9.9元中杯冰美式」
```

### 结构化输出(便于二次集成)

```console
$ python -m mcd_meal_optimizer plan --json --kcal-min 500 --kcal-max 900 --objective max_protein
{
  "meta": { "menu_source": "sample", "coupons": 8, "nutrition": 41 },
  "plans": [ { "items": ["..."], "payable": 44.0, "nutrition": { "protein": 50.0 } } ]
}
```

## 支持的 MCP 工具

本项目实际调用以下麦当劳 MCP 工具(共 35 个工具中精选):

| 工具 | 用途 | 在项目中的角色 |
| --- | --- | --- |
| `list-nutrition-foods` | 餐品营养成分 | 营养目标的**唯一数据源** |
| `query-meals` | 门店菜单 | 求解候选集 |
| `query-my-coupons` | 卡包优惠券 | 到手价计算 |
| `available-coupons` | 麦麦省可领券 | 到手价计算 |
| `query-store-coupons` | 门店可用券 | 门店维度校验 |
| `query-nearby-stores` | 附近门店 | 门店解析 |
| `delivery-query-stores` | 可配送门店 | 外送场景 |
| `calculate-price` | 价格试算 | 下单前**强制复算** |
| `create-order` | 创建订单 | 用户确认后一键下单 |
| `query-my-account` / `now-time-info` | 账号 / 时间 | 自检与上下文 |

完整的工具清单与调用参数见 **[`MCP_INTEGRATION.md`](MCP_INTEGRATION.md)**。

## 目标用户

- **减脂 / 增肌人群**:需要精确控制热量与蛋白质,又不想放弃快餐;
- **控糖 / 控钠人群**:需要一个能算清楚的工具,而不是"感觉还行";
- **价格敏感的上班族**:想用最少的钱吃到满足营养的午饭;
- **AI Agent 开发者**:想找一个真实使用 MCP、且有可验证求解逻辑的参考实现。

## 数据真实性说明

我们坚持**数据来源可追溯**,不编造:

- 营养数据、优惠券、活动日历、积分等均来自 MCP **实时接口**;
- `examples/sample-menu.json` 中的**营养数据来自 MCP 真实返回**,
  但**价格为示例值**(仅用于账号尚无门店时的离线演示),文件内已明确标注;
- 当无法取到门店菜单时,程序会输出
  `> 说明: ... 以下为示例菜单计算结果, 价格仅作演示。`,绝不伪装成真实价;
- 比赛要求的 `CONTEST_DECLARATION.md` 使用官方原文,**逐字节一致**
  (sha256 `cd28101b...41b7`)。

## 正确性验证

求解器不是"看起来对",而是被测试保证的:

```console
$ python -m unittest discover -s tests -t .
Ran 23 tests in 0.243s
OK
```

关键的两类测试:

1. **随机差分测试**:在 120 组随机小规模实例上,动态规划的结果必须与
   穷举搜索完全一致 —— 保证求解器不会漏掉更优解;
2. **变异验证**:故意注入缺陷(如"只搜索一半菜单""丢掉热量下限"),
   确认测试会 **FAIL**。测试本身的有效性是被验证过的,而不是"全绿就算过"。

## 项目结构

```
mcd-meal-optimizer/
├── SKILL.md                 # WorkBuddy Skill 定义
├── README.md                # 本文件
├── MCP_INTEGRATION.md       # MCP 工具、调用流程与业务价值
├── CONTEST_DECLARATION.md   # 参赛声明 (官方原文, 不可修改)
├── mcp-config.example.json  # 脱敏 MCP 配置 (仅环境变量占位符)
├── workbuddy.md             # WorkBuddy 开发上下文
├── mcd_meal_optimizer/      # 源代码
│   ├── mcp_client.py        # 零依赖 MCP 客户端 (含响应解析)
│   ├── parsers.py           # 紧凑表格 / Markdown 券 / 菜单 解析
│   ├── models.py            # 领域模型
│   ├── optimizer.py         # 双约束动态规划求解器
│   ├── planner.py           # MCP 编排层
│   └── cli.py               # 命令行入口
├── scripts/gen_sample_menu.py  # 示例菜单生成器
├── examples/sample-menu.json   # 离线示例菜单
└── tests/                   # 23 项单元测试
```

## 常见问题

**Q: 提示"未取到门店"怎么办?**
A: 门店类接口(`query-nearby-stores` / `query-meals`)依赖账号侧已配置
位置或收藏门店。请在**麦当劳 App 收藏一家门店**,或向本工具传入
`--store-code <门店编码>`。在此之前,`plan` 会走示例菜单路径并明确标注。

**Q: 报价和实际下单价不一致?**
A: 以 `calculate-price` 返回为准。本工具在真实下单前会强制复算。

**Q: 需要安装依赖吗?**
A: 不需要。仅使用 Python 标准库,Python 3.10+ 即可运行。

## 免责声明

- 本项目输出仅供参考,**不构成医疗、营养或其他专业建议**;
- 餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准;
- 下单类工具会产生**真实订单与真实扣费**,请在用户明确同意后使用;
- 本项目为参赛作品,非麦当劳官方产品。
