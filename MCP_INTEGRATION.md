# MCP 集成说明

本文说明「麦麦算盘」实际使用的麦当劳 MCP Server、Tool、调用流程与业务价值。
所有参数与返回形态均以**实测响应**为准,不是照抄文档。

## 1. MCP Server

| 项 | 值 |
| --- | --- |
| 名称 | `mcd-mcp` (麦当劳中国 MCP 服务) |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 鉴权 | 请求头 `Authorization: Bearer <MCD_MCP_TOKEN>` |
| Token 申请 | <https://open.mcd.cn/mcp> |
| 限流 | 600 次请求 / 分钟 (超限返回 429) |
| 服务端版本 | 握手返回 `serverInfo: {name: "mcd-mcp", version: "1.0.0"}` |
| 工具总数 | 35 |

客户端实现: [`mcd_meal_optimizer/mcp_client.py`](mcd_meal_optimizer/mcp_client.py)
—— 仅用标准库实现 JSON-RPC 握手、`tools/list`、`tools/call`,兼容 JSON 与
SSE 两种响应体。工具返回的 `content[0].text` 里混着说明文字与真实 JSON,
由 `_parse_payload_text()` 按 `## Original Response` 标记定位并抽取。

## 2. 实际使用的 Tool

### 2.1 营养维度(核心)

#### `list-nutrition-foods`

- **参数**: 无(实测 `inputSchema.properties` 为空对象)。
- **返回**: 一个**紧凑表格字符串**(非 JSON):

  ```text
  [160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
    猪柳麦满分,null,1288,308,16,16,24,781,213
    巨无霸,null,2146,513,27,26,42,961,171
  ```

- **本项目处理**: `parsers.parse_nutrition_table()` 解析该表,得到
  158 款餐品的营养字典(表头声明 160 行,其中 2 组为同名同值餐品)。
- **业务价值**: "营养目标"的**唯一可信数据源** —— 热量与蛋白质达标判定
  完全基于它,而非模型记忆。
- **重要约束**: 该表**只按餐品名索引,不带价格、不带编码**,而且粒度为
  **带规格的单品**(`中薯条`/`大薯条`、`冰美式中杯`/`热美式中杯` 各自独立)。
  这直接决定了后文「套餐拆解」与「名称匹配」的设计。

### 2.2 菜单与详情维度

#### `query-meals`

- **参数**: `storeCode`(必填)、`orderType`、`beType`、`beCode`(按场景)。
- **返回**: `{"data": {"categories": [...], "meals": {code: {...}}}}`

  ```json
  {
    "categories": [{"name": "人气热卖", "meals": [{"code": "9900005456", "tags": ["套餐"]}]}],
    "meals": {
      "9900005456": {"name": "麦辣鸡腿汉堡三件套", "currentPrice": "33.5", "originalPrice": "46"}
    }
  }
  ```

- **要点**:
  - 价格是**元**(字符串),不是分;`meals` 里**不含分类**,分类名要从
    `categories` 反查。
  - 餐品名是**通用展示名**(`薯条`、`雪碧`、`牛奶`),**不带规格**。
- **本项目处理**: `parsers.parse_menu_payload()` 解析该结构并合并分类/标签。

#### `query-meal-detail`

- **参数**: `storeCode`、`orderType`、`beType`、`code`。
- **返回**: `{"data": {"code", "name", "rounds": [...]}}`

  ```json
  {
    "name": "麦辣鸡腿汉堡三件套",
    "rounds": [
      {"name": "麦辣鸡腿汉堡", "choices": [{"code": "1440", "name": "麦辣鸡腿汉堡", "isDefault": 1}]},
      {"name": "选择套餐内小食", "choices": [{"name": "中薯条", "isDefault": 1},
                                          {"name": "5块心形薯饼+韩式辣椒黄油风味酱", "quantity": 0}]}
    ]
  }
  ```

- **两个关键用途**:
  1. **套餐拆解** —— `rounds[].choices[]` 里 `isDefault=1`(或 `quantity>0`)
     的那一项就是默认组成。套餐的营养 = 组成单品营养之和,这样「三件套」
     也能算出准确热量,而不是靠猜。
  2. **单品精确规格名** —— 单品的 `rounds` 为空,但 `data.name` 是**带规格的
     精确 SKU 名**:菜单显示「薯条」,detail 返回「中薯条」;菜单显示「雪碧」,
     detail 返回「雪碧（小杯）」。营养库是按精确名建的,所以**必须**用
     detail 的名字去匹配,否则所有带规格的单品都会因歧义全部落空。

  实测效果:仅用菜单名匹配时营养完整项为 58/121;补上精确名后提升到 **82/121**。

### 2.3 门店发现:绕开账号依赖

#### `query-nearby-stores`(回退路径)

- **参数**: `beType`(1 到店自提 / 5 得来速)、`searchType`(1 收藏门店 / 2 按位置)、
  `city`、`keyword`。
- **实测行为**: 全新账号(无收藏门店、无定位)在任意城市/关键词下**一律返回空**。
  这是账号侧配置问题,不是参数问题。

#### 派对门店链路(默认路径)

`delivery-query-*` 同理依赖地址配置,不可用。因此本项目采用一条**公开数据链路**
发现真实门店,完全不依赖账号配置:

| 步骤 | Tool | 参数 | 产出 |
| --- | --- | --- | --- |
| 1 | `mall-points-products` | 无 | 派对商品 `spuId`(如 1830 亲子读书会) |
| 2 | `query-party-city` | `spuId` | 城市 `code` + `latitude`/`longitude` |
| 3 | `query-party-store` | `code`,`latitude`,`longitude`,`spuId` | 门店列表(含 `code`/`name`/`address`/`distance`) |

拿到 `storeCode` 后,`query-meals` / `calculate-price` / `create-order`
**只认门店编码,与账号收藏无关** —— 到店自取链路即刻打通。

城名对齐采用「精确 → 前缀(上海 → 上海市)→ 包含」三级匹配。
链路异常时自动回退 `query-nearby-stores`,对已配置账号同样可用。
实现见 [`mcd_meal_optimizer/stores.py`](mcd_meal_optimizer/stores.py)。

### 2.4 券与价格维度

| Tool | 参数 | 返回形态 | 用途 |
| --- | --- | --- | --- |
| `query-my-coupons` | `page`,`pageSize` | Markdown 券列表 | 解析"用券价格/折扣"计入到手价 |
| `available-coupons` | 无 | `- 优惠券标题：` 块列表 | 麦麦省可领券,扩充候选券池 |
| `query-store-coupons` | `orderType`,`beType`,`storeCode` | 门店维度可用券 | 校验"这单在这个门店能不能用" |
| `calculate-price` | `storeCode`,`orderType`,`beType`,`items` | 价格明细 + 取餐方式 | **下单前强制复算**最终价 |

券规则解析(见 `parsers._classify_coupon`)覆盖五类:

| 券形态 | 识别规则 | 计入方式 |
| --- | --- | --- |
| 满减 | `满X减Y` / `满X元减Y元` | 整单满阈值后减免 |
| 固定价 | `9.9元中杯冰美式` | 该餐品到手价直接替换 |
| 折扣 | `7折` / `8.5折` | 该餐品价格 × 折扣率 |
| 买一送一 | `买一送一` | 识别并标注(不改变单件价) |
| 免费 | `免费脆薯饼` | 识别并标注 |

#### `calculate-price` 的两个坑

1. **单位是「分」**。返回 `price: 4200` 表示 ¥42.00;`productList[].subtotal`
   同样是分。本项目在 `orders._yuan()` 里统一换算,上层只见到「元」。
2. **订单类型参数规则**(实测有效):

   | 场景 | beType | orderType | beCode |
   | --- | --- | --- | --- |
   | 到店自取 | 1 | 1 | **不要传**(传了报错) |
   | 得来速 | 5 | 1 | 必传(来自 `query-nearby-stores`) |
   | 麦乐送 | 2 | 2 | 必传(来自 `delivery-query-stores`) |
   | 企业团餐 | 6 | 2 | 必传 |

   到店自取是**唯一不需要账号侧配置**的下单路径,因此本项目默认走它。
   返回的 `takeWayList[].code`(`eat-in` 堂食 / `locker-out` 外带)是
   `create-order` 的必传参数 `takeWayCode` 的来源。

### 2.5 下单与撤单

| Tool | 关键参数 | 说明 |
| --- | --- | --- |
| `create-order` | `storeCode`,`orderType`,`beType`,`takeWayCode`,`items` | 创建**未支付**订单并返回支付入口 |
| `cancel-order` | `orderId`,`cancelReasonCode` | 撤销订单(1 改主意 / 2 重复下单 / 3 点错 / 4 地址错 / 5 时间错 / -1 其它) |

**安全闸门**:`create-order` 虽然只创建未支付订单,但它仍是挂在用户账号上的
**真实订单**。因此 `OrderService.submit()` 在未显式传 `confirm=True` 时
**直接抛 `OrderConfirmRequired`**,且不会发出任何请求;CLI 层对应 `--confirm`
开关。这条约束有单元测试断言(「拒绝执行」+「未发出请求」两条都测)。

### 2.6 上下文与账号

| Tool | 用途 |
| --- | --- |
| `now-time-info` | 服务端时间(活动日历/预约场景需要) |
| `query-my-account` | 积分账户(自检与积分兑换场景) |
| `campaign-calendar` | 当月活动日历 |
| `order-list` | 历史订单 |

## 3. 调用流程

### 3.1 门店发现(零账号配置)

```text
mall-points-products ──> spuId
        │
        ▼
query-party-city {spuId} ──> 城市 code + 经纬度
        │
        ▼
query-party-store {code, latitude, longitude, spuId} ──> storeCode + 门店名/地址
                                                          │
                        (链路失败则回退 query-nearby-stores)
```

### 3.2 求解主流程

```text
                        ┌──────────────────────────────┐
                        │ 用户输入: 热量区间 / 蛋白下限  │
                        │ / 预算上限 / 件数 / 含排除词   │
                        └───────────────┬──────────────┘
                                        │
        ┌───────────────────────────────┴───────────────────────────────┐
        │                      数据采集 (MCP)                            │
        └───────────────────────────────┬───────────────────────────────┘
   ┌──────────────┬────────────────┬────┴────────────┬────────────────────┐
   ▼              ▼                ▼                 ▼                    ▼
query-party-*  query-meals   list-nutrition-   query-my-coupons   (now-time-info
 门店发现        真实菜单         foods            available-*        上下文)
   │              │            158 款精确名单      券池
   ▼              ▼                │                 │
storeCode    121 项候选            │                 │
   │              │                │                 │
   │              ├─ 名称直接匹配 ─┴─> 命中? ──> 挂营养
   │              │                │
   │              └─ 未命中 ──> query-meal-detail
   │                             ├─ 套餐: rounds 默认项 -> 组成求和
   │                             └─ 单品: data.name 精确名 -> 再匹配
   │                                        │
   │                            ┌───────────┴────────────┐
   │                            ▼                        ▼
   │                     complete 进候选池        partial/none 排除出解
   │                                                  (绝不按 0 计算)
   ▼                            │
calculate-price <────── optimize(): 双约束动态规划
 真实算价                state = (热量桶, 蛋白桶, 必需掩码)
 (强制复算)             value = 最低到手价 (含券后价)
                                │
                                ▼
                    有效方案 (营养达标 / 预算内 / 件数合规)
                                │
                                ▼
                 ┌──────────────────────────────┐
                 │ 用户显式确认 (--confirm)      │
                 │   │                          │
                 │   └─ 未确认 -> submit() 抛异常 │
                 └──────────────┬───────────────┘
                                ▼
                        create-order 下单
```

### 关键设计决策

1. **不编造,也不补零**:营养库覆盖不到的餐品(当季新品、规格歧义项)
   一律**排除出解**并显式标注,而不是当作 0 kcal / 0 g 蛋白参与计算 ——
   后者会伪造出"营养达标"的结论。`Constraints.require_complete_nutrition`
   默认开启,`optimizer._filter_items()` 强制执行。
2. **匹配宁可漏,不可错**:名称对齐只接受高置信匹配,并刻意保留区分字。
   `冰美式中杯`≠`热美式中杯`、`中薯条`≠`大薯条`、`麦乐鸡4块`≠`麦乐鸡5块`
   (179 kcal vs 223 kcal)。包装词(`盒装`)与佐料/周边(`酱`/`玩具`/`帽`)
   可以剔除或忽略 —— 前者不影响营养,后者不提供营养。
3. **降级而不伪装**:门店菜单完全取不到时,回退 `examples/sample-menu.json`
   并在输出顶部**明确标注**"价格为示例"。仓库另附
   `examples/real-menu-1450713.json` 真实快照,可离线复现真实结果。
4. **求解与取数解耦**:`optimizer.py` 是纯函数求解器,不依赖网络,因此
   可以用穷举做随机差分验证。
5. **下单前强制复算 + 显式确认**:任何建单前先 `calculate-price`,且
   未确认不发请求。

## 4. 业务价值

| 维度 | 价值 |
| --- | --- |
| 对用户 | 把"减脂期怎么点麦当劳"从模糊感觉变成可复现的最优解:同样的钱多吃蛋白,同样的营养少花钱;报价与真实成交价一致。 |
| 对 MCP 生态 | 展示了 MCP 不止能"问答式点餐",还能作为**结构化决策系统的数据底座** —— 营养库 + 券池 + 菜单 + 详情四源合一,驱动一个真实的优化器;并给出一条**绕开账号配置约束**的门店发现链路,让新用户零配置即可跑通全链路。 |
| 对开发者 | 一份"如何解析 MCP 非结构化返回"的参考实现:紧凑表格、Markdown 券列表、分类菜单、套餐轮次四种形态都被显式处理并单元测试覆盖;分/元、beCode 传递规则等实测坑点均在文档与代码中固化。 |
| 可扩展性 | 求解器与数据源解耦,新增约束(钠/钙上限、口味偏好、时间窗、外送)只需扩展 `Constraints` 或 `BE_TYPE_RULES`,无需改动 MCP 调用层。 |

## 5. 自检与复现

```bash
# 连通性 + 账号状态 + 门店发现链路
python -m mcd_meal_optimizer check --city 上海

# 列出 MCP 当前全部工具
python -m mcd_meal_optimizer tools

# 按城市发现真实门店
python -m mcd_meal_optimizer stores --city 上海

# 真实菜单 + 营养覆盖统计
python -m mcd_meal_optimizer menu --store-code 1450713 --top 20

# 券解析结果 / 营养库
python -m mcd_meal_optimizer coupons
python -m mcd_meal_optimizer nutrition --query 板烧 --top 10

# 求解 + 真实算价 / 算价 / 下单预览
python -m mcd_meal_optimizer plan --store-code 1450713 --price-check
python -m mcd_meal_optimizer price --store-code 1450713 --item 9900005456
python -m mcd_meal_optimizer order --store-code 1450713 --item 9900005456

# 导出真实门店快照 (供离线复现)
python scripts/snapshot_store.py --city 上海
```
