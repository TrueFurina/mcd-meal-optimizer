# 麦麦算盘 · mcd-meal-optimizer

**在预算内吃够营养,在营养达标时花得最少。**

一个基于**麦当劳 MCP** 的双目标餐搭求解器:输入「热量区间 + 蛋白质下限 +
预算上限」,用**真实门店菜单、真实营养数据与真实优惠券**,通过动态规划
求出**到手价最低且营养达标**的组合,并用 `calculate-price` 复核真实成交价,
确认后可一键下单。

> 参赛作品 —— 麦当劳程序员创意开发大赛。本项目由参赛者独立开发,非麦当劳官方产品。

---

## 目录

- [它解决什么问题](#它解决什么问题)
- [和"推荐个套餐"有什么不同](#和推荐个套餐有什么不同)
- [快速开始](#快速开始)
- [真实运行示例](#真实运行示例)
- [覆盖范围与诚实边界](#覆盖范围与诚实边界)
- [支持的 MCP 工具](#支持的-mcp-工具)
- [目标用户](#目标用户)
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

多数"套餐推荐"靠模型凭记忆报数 —— 热量记错、价格过时、券根本没算。
**麦麦算盘不猜**:营养、菜单、价格、优惠券全部来自麦当劳 MCP 实时接口,
求解过程是一个可复现的约束优化问题。

## 和"推荐个套餐"有什么不同

| | 常见做法 | 麦麦算盘 |
| --- | --- | --- |
| 数据来源 | 模型记忆/静态表 | MCP 实时接口 (营养库/菜单/券/价格) |
| 决策方式 | 提示词让模型"挑一个" | **双约束动态规划求最优解** |
| 门店依赖 | 需要用户已收藏门店 | **按城市直接发现真实门店**,零配置 |
| 套餐营养 | 只能给单品,套餐靠猜 | **拆解套餐组成逐项求和** |
| 优惠券 | 忽略或口头提及 | 解析券规则并计入到手价 |
| 报价 | 用菜单牌价 | 下单前用 `calculate-price` **真实复核** |
| 数据缺口 | 按 0 计算,伪造"达标" | **排除出解并显式标注**,不伪造 |
| 可复现性 | 换个问法结果就变 | 同输入必得同输出,有单元测试 |

核心求解目标(三选一,`--objective`):

- `min_price`(默认)—— 满足营养约束的**最低到手价**;
- `max_protein` —— 同等预算下**蛋白质最高**;
- `best_value` —— **每元蛋白**最高。

## 快速开始

### 1. 申请 MCP Token

前往 <https://open.mcd.cn/mcp>,手机号登录后在【控制台】激活并复制 MCP Token。

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
python -m mcd_meal_optimizer check --city 上海          # 自检 + 验证门店发现
python -m mcd_meal_optimizer stores --city 上海         # 按城市发现真实门店
python -m mcd_meal_optimizer menu --city 上海 --top 20  # 看真实菜单与营养覆盖

# 核心:不用任何门店配置,直接按城市求解并复核真实价格
python -m mcd_meal_optimizer plan --city 上海 \
    --kcal-min 550 --kcal-max 800 --protein 30 --budget 40 --price-check
```

## 真实运行示例

以下输出均为**真实接口返回**,门店为「麦当劳上海黄浦华旭国际大厦餐厅」
(`1450713`),抓取时间 2026-10-10。

### 门店发现:账号零配置也能拿到真实门店

`query-nearby-stores` 依赖账号侧定位/收藏,全新账号会返回空。本项目改用
**公开的派对门店链路**发现门店(见下文「门店发现链路」):

```console
$ python -m mcd_meal_optimizer check --city 上海
麦麦算盘 · 麦当劳营养×预算餐搭管家 v1.1.0
- MCP 服务: https://mcp.mcd.cn
- 连接: OK
- 积分: 0
- 营养库: 158 款餐品
- 券: 共 8 张 (卡包 + 麦麦省)
- 配送地址: 0 个
- 收藏门店: 0 家
- 「上海」门店发现: 3 家
    1450713  麦当劳上海黄浦华旭国际大厦餐厅
    1450556  麦当劳上海黄浦区福州路上海书城餐厅
    1450699  麦当劳上海黄浦区无限极荟餐厅
- 到店自取下单链路: 可用 (无需账号配置门店)
```

### 真实菜单 + 套餐营养拆解

```console
$ python -m mcd_meal_optimizer menu --store-code 1450713 --top 8
{
  "count": 121, "with_nutrition": 99,
  "min_price": 3.0, "max_price": 91.7,
  "nutrition_coverage": { "total": 121, "complete": 82, "partial": 17, "none": 22 }
}

编码          餐品                              现价      原价      热量     蛋白
9900005456  麦辣鸡腿汉堡三件套                    33.50   46.00     921   28.0
511781      培根安格斯厚牛堡                     34.50   34.50     707   34.0
521741      脆薯饼                           8.50    8.50     146    1.0
9900011056  全明星双人分享餐八件套                  49.90  114.50    1706   74.0
...
```

「麦辣鸡腿汉堡三件套」本身不在营养库里,但它被 `query-meal-detail`
拆成 `麦辣鸡腿汉堡 + 中薯条 + 可乐中杯`,三者营养求和得到 921 kcal。

### 求解 + 真实算价复核

```console
$ python -m mcd_meal_optimizer plan --store-code 1450713 \
      --kcal-min 550 --kcal-max 800 --protein 30 --budget 40 --max-items 3 --price-check
约束: 550-800 kcal | 蛋白≥30g | 预算≤¥40 | 件数 1-3
数据来源: 菜单=live:1450713 | 券=8 | 营养完整=82/121

## 方案 1 — 到手 ¥23.80（原价 ¥23.80）
- 营养: 656 kcal / 蛋白 42.0 g（目标 550-800 kcal, 蛋白 ≥ 30 g）
- 蘸酱麦麦脆汁鸡 ¥11.90
- 蘸酱炸鸡 ¥11.90

--- 真实算价 (calculate-price) ---
## 方案 1 · 门店 1450713
- 蘸酱麦麦脆汁鸡 ×1  ¥11.90
- 蘸酱炸鸡 ×1  ¥11.90
- **合计 ¥23.80**
- 取餐方式: 堂食(eat-in) / 外带(locker-out)
```

求解器给出的 ¥23.80 与 `calculate-price` 的真实成交价**完全一致**。

### 下单:默认只预览,必须显式确认

```console
$ python -m mcd_meal_optimizer order --store-code 1450713 --item 9900005456 --item 521741
## 下单预览 (尚未提交)
- 门店: 1450713
- 取餐: eat-in  可选项: 堂食(eat-in) / 外带(locker-out)
  · 麦辣鸡腿汉堡三件套 ×1  ¥33.50
  · 脆薯饼 ×1  ¥8.50
- **合计 ¥42.00**

! 未提交: 真实下单会挂到你的麦当劳账号上。
  确认无误后, 追加 --confirm 重新执行即可建单。
```

真实建单需要 `--confirm`;代码层面 `submit()` 在未确认时**直接抛异常**,
且不会向 `create-order` 发出任何请求(有测试覆盖)。

### 端到端实测:建单 → 撤单(全链路已跑通)

下单链路不是"写完就算",而是**真实建单一次并立即撤销**,确认接口契约与
字段含义都对得上:

```console
$ python -m mcd_meal_optimizer order --store-code 1450713 \
      --item 9900016078 --item 9900016077 --confirm
## 订单已创建
- 订单号: 1030657600000754933792618028
- 应付: ¥23.80
- 支付入口: https://m.mcd.cn/mcp/scanToPay?orderId=...
```

创建后立刻撤销(`--reason 1` = 改主意),并用 `query-order` 独立复核终态:

```console
$ python -m mcd_meal_optimizer cancel --order-id 1030657600000754933792618028 --reason 1
订单 1030657600000754933792618028: 已取消

$ python -m mcd_meal_optimizer cancel ... --json   # 接口返回
{ "cancelResult": true, "orderId": "1030657600000754933792618028" }

# query-order 独立复核
{ "orderId": "1030657600000754933792618028",
  "orderStatus": "订单已取消", "status": "60",
  "totalAmount": "23.8", "realTotalAmount": "23.8" }
```

本次实测确认的接口行为(易踩,特此记录):

| 观察 | 说明 |
| --- | --- |
| `create-order` 返回 `orderStatus=待支付 / status=10` | 只建**未支付**订单,`expirePayTime` 为 15 分钟后 |
| 金额一致 | `totalAmount = realTotalAmount = 23.8`,与 `calculate-price` 逐分吻合 |
| `takeWay="堂食"` | 由 `calculate-price` 的 `takeWayList` 推导(`eat-in`),下单未传 `beCode` |
| `cancel-order` 幂等语义 | 返回 `cancelResult: true`;`status` 变为 `60`(**已取消**) |
| 订单明细含套餐组成 | `comboItemList` 给出 `麦麦脆汁鸡-琵琶腿 + 韩式烟熏芝士风味酱`,与解析层一致 |

> 上述订单已撤销,不会产生任何扣费。仓库内不保存订单号以外的任何个人数据。

### 离线复现:真实菜单快照

仓库内 `examples/real-menu-1450713.json` 是上面那家门店的**完整真实快照**
(121 项,含价格、营养、套餐组成)。不联网也能跑出同样结果:

```console
$ python -m mcd_meal_optimizer plan --menu-file examples/real-menu-1450713.json \
      --kcal-min 550 --kcal-max 800 --protein 30 --budget 40 --max-items 3 --top 1
## 方案 1 — 到手 ¥23.80（原价 ¥23.80）
- 营养: 656 kcal / 蛋白 42.0 g
```

重新抓取快照:`python scripts/snapshot_store.py --city 上海`

## 覆盖范围与诚实边界

营养库(`list-nutrition-foods`)收录 158 款餐品,而门店在售约 121 项,
两者**不是一一对应**。当季新品(如「龙焰」系列、「心月」系列)、带规格的
单品(「雪碧」「牛奶」「薯条」)都可能对不上。

本项目的处理方式是**不猜、不补零**:

| 状态 | 含义 | 求解时的处理 |
| --- | --- | --- |
| `complete` | 组成全部命中营养库 | 正常参与求解 |
| `partial` | 部分组成未收录 | **排除出解**,并列出缺失组成 |
| `none` | 无可用营养数据 | **排除出解** |

原因很直接:缺营养的餐品若按 0 kcal / 0 g 蛋白参与计算,会**伪造出
"营养达标"**的结论。宁可少给一个方案,也不给一个错的。

上海这家门店的实际覆盖:`121 项 = 82 完整 + 17 部分 + 22 无`,
**82 项可用候选**已足够求解。若某次求解无解,输出会提示放宽约束。

### 门店发现链路

`query-nearby-stores` 需要账号侧已配置定位或收藏门店,全新账号必然返回空。
本项目用一条**不依赖账号配置**的公开链路替代:

```
mall-points-products                       # 取派对商品 spuId (公开数据)
  └─> query-party-city   {spuId}           # 取城市 code + 经纬度
        └─> query-party-store {code, latitude, longitude, spuId}
                                           # 取该城市门店列表 (含 storeCode)
```

拿到 `storeCode` 后,`query-meals` / `calculate-price` / `create-order`
**只认门店编码,与账号收藏无关**,因此到店自取下单链路可以立即打通。
若该链路异常,会自动回退到 `query-nearby-stores`,对已配置账号同样可用。

### 名称匹配的口径

跨接口对齐餐品名时,只接受**高置信**匹配(字面相同 / 归一化相同 /
剔除包装与规格后字符多重集相同),并刻意保留区分字:

- `冰美式中杯` **不会**匹配到 `热美式中杯`(冰/热不同);
- `中薯条` **不会**匹配到 `大薯条`(规格不同);
- `麦乐鸡4块` **不会**匹配到 `麦乐鸡5块`(块数不同 —— 这是真实陷阱,
  4 块 179 kcal、5 块 223 kcal);
- `100% 苹果汁(盒装)` 可以匹配 `100%苹果汁`(仅包装词不同);
- `韩式烟熏芝士风味酱`、`玩具`、`棒球帽` 等佐料/周边**不计营养也不算缺失**。

这些边界都有单元测试,且做过变异验证(见下文)。

## 支持的 MCP 工具

本项目实际调用以下麦当劳 MCP 工具(共 35 个工具中精选):

| 工具 | 用途 | 在项目中的角色 |
| --- | --- | --- |
| `list-nutrition-foods` | 餐品营养成分 (158 款) | 营养目标的**唯一数据源** |
| `query-meals` | 门店菜单 | 求解候选集 (真实名称与价格) |
| `query-meal-detail` | 餐品详情/可选组成 | **套餐拆解** + 单品精确规格名 |
| `mall-points-products` → `query-party-city` → `query-party-store` | 城市门店发现 | **零配置门店解析** |
| `query-my-coupons` | 卡包优惠券 | 到手价计算 |
| `available-coupons` | 麦麦省可领券 | 到手价计算 |
| `query-store-coupons` | 门店可用券 | 门店维度校验 |
| `query-nearby-stores` | 附近门店 | 回退路径 (依赖账号配置) |
| `delivery-query-stores` / `delivery-query-addresses` | 外送门店/地址 | 外送场景 |
| `calculate-price` | 价格试算 | 下单前**强制复算** |
| `create-order` | 创建订单 | **显式确认后**建单 |
| `cancel-order` | 取消订单 | 撤单 |
| `query-my-account` / `now-time-info` | 账号 / 时间 | 自检与上下文 |

完整的工具清单、调用参数与业务价值见 **[`MCP_INTEGRATION.md`](MCP_INTEGRATION.md)**。

## 目标用户

- **减脂 / 增肌人群**:需要精确控制热量与蛋白质,又不想放弃快餐;
- **控糖 / 控钠人群**:需要一个能算清楚的工具,而不是"感觉还行";
- **价格敏感的上班族**:想用最少的钱吃到满足营养的午饭;
- **AI Agent 开发者**:想找一个真实使用 MCP、门店零配置、且有可验证
  求解逻辑的参考实现。

## 正确性验证

```console
$ python -m unittest discover -s tests -t .
Ran 64 tests in 0.238s
OK
```

四类测试,每类都做过**变异验证**(故意注入缺陷,确认测试会 FAIL):

1. **随机差分测试**:120 组随机小规模实例上,动态规划结果必须与穷举完全
   一致 —— 保证不会漏掉更优解;
2. **约束门禁测试**:缺营养/部分命中的餐品必须被排除。注入"不再排除"
   的缺陷后测试立即 FAIL;
3. **下单安全闸门测试**:未显式确认时 `submit()` 必须抛异常,并断言
   **没有**发出 `create-order` 请求。注入"去掉闸门"后测试立即 FAIL;
4. **名称匹配边界测试**:把「块」误当容器词后,`麦乐鸡4块` 立刻错配成
   `麦乐鸡5块`,测试当场 FAIL —— 证明这组边界是真被守住的。

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
│   ├── parsers.py           # 紧凑表格 / 券 Markdown / 菜单 / 套餐组成 / 名称匹配
│   ├── models.py            # 领域模型 (含营养完整度)
│   ├── optimizer.py         # 双约束动态规划求解器 + 营养门禁
│   ├── stores.py            # 门店发现 (不依赖账号配置)
│   ├── orders.py            # 真实算价 / 下单 (带确认闸门) / 撤单
│   ├── planner.py           # MCP 编排层
│   └── cli.py               # 命令行入口
├── scripts/
│   ├── gen_sample_menu.py   # 示例菜单生成器
│   └── snapshot_store.py    # 真实门店菜单快照导出
├── examples/
│   ├── sample-menu.json         # 离线示例菜单 (营养真实, 价格示例)
│   └── real-menu-1450713.json   # 真实门店快照 (121 项, 可离线复现)
└── tests/                   # 64 项单元测试
```

## 常见问题

**Q: `check` 显示"收藏门店 0 家",会影响使用吗?**
A: 不会。门店发现默认走**按城市**的公开链路(`--city 上海`),不需要账号
收藏门店。`--store-code` 也可以直接指定编码。

**Q: 为什么有些餐品显示"—"或"部分"?**
A: 那是一年内新品或带规格的单品,营养库(158 款)尚未收录。它们会被
**排除出解**而不是按 0 计算,避免得出"营养达标"的错误结论。

**Q: 报价和实际下单价不一致?**
A: 以 `calculate-price` 为准。本工具在真实下单前会强制复算,且下单默认
只预览。

**Q: 会自己下单吗?**
A: 不会。`order` 默认只预览价格,真实建单必须显式加 `--confirm`;
代码层面未确认时会抛异常并且不发请求。

**Q: 需要安装依赖吗?**
A: 不需要。仅使用 Python 标准库,Python 3.10+ 即可运行。

## 免责声明

- 本项目输出仅供参考,**不构成医疗、营养或其他专业建议**;
- 餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准;
- 下单类工具会产生**真实订单与真实扣费**,请在用户明确同意后使用;
- 本项目为参赛作品,非麦当劳官方产品。
