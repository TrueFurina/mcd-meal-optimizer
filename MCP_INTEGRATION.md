# MCP 集成说明

本文说明「麦麦算盘」实际使用的麦当劳 MCP Server、Tool、调用流程与业务价值。

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
—— 仅用标准库实现 JSON-RPC 握手、`tools/list`、`tools/call`,并兼容
JSON 与 SSE 两种响应体。

## 2. 实际使用的 Tool

### 2.1 营养维度(核心)

#### `list-nutrition-foods`

- **参数**: 无。
- **返回**: 一个**紧凑表格字符串**(非 JSON):

  ```text
  [160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
    猪柳麦满分,null,1288,308,16,16,24,781,213
    巨无霸,null,2146,513,27,26,42,961,171
  ```

- **本项目处理**: `parsers.parse_nutrition_table()` 解析该表,得到
  158 款餐品的营养字典(160 行中有 2 组同名同值餐品)。
- **业务价值**: 这是"营养目标"的**唯一可信数据源** —— 热量与蛋白质
  的达标判定完全基于它,而非模型记忆。

### 2.2 券与价格维度

| Tool | 参数 | 返回形态 | 用途 |
| --- | --- | --- | --- |
| `query-my-coupons` | `page`, `pageSize` | Markdown 券列表 | 解析"用券价格/折扣"计入到手价 |
| `available-coupons` | 无 | `- 优惠券标题：` 块列表 | 麦麦省可领券,扩充候选券池 |
| `query-store-coupons` | `orderType`,`beType`,`storeCode` | 门店维度可用券 | 校验"这单在这个门店能不能用" |
| `calculate-price` | `storeCode`,`orderType`,`beType`,`items` | 价格明细 | **下单前强制复算**最终价 |

券规则解析(见 `parsers._classify_coupon`)覆盖五类:

| 券形态 | 识别规则 | 计入方式 |
| --- | --- | --- |
| 满减 | `满X减Y` / `满X元减Y元` | 整单满阈值后减免 |
| 固定价 | `9.9元中杯冰美式` | 该餐品到手价直接替换 |
| 折扣 | `7折` / `8.5折` | 该餐品价格 × 折扣率 |
| 买一送一 | `买一送一` | 识别并标注(不改变单件价) |
| 免费 | `免费脆薯饼` | 识别并标注 |

### 2.3 门店与菜单维度

| Tool | 关键参数 | 说明 |
| --- | --- | --- |
| `query-nearby-stores` | `beType`(1 到店/5 得来速), `searchType`(1 收藏/2 按位置), `city`, `keyword` | 到店场景门店解析 |
| `delivery-query-addresses` | 无 | 外送地址列表 |
| `delivery-query-stores` | `beType`(2 麦乐送/6 团餐), `addressId` | 外送场景门店解析 |
| `query-meals` | `storeCode`, `orderType`, `beType`, `beCode` | 候选餐品集(含价格) |
| `query-meal-detail` | `storeCode`, `orderType`, `beType`, `code` | 套餐组成与替换项 |

> **注意**: `beType=1`(到店自提)时**不要传 `beCode`**;`beType=5`
> (得来速)时**必须传 `beCode`**,且 `storeCode` 与 `beCode` 必须配对,
> 否则返回 `60002 未查询到门店信息`。

### 2.4 上下文与账号

| Tool | 用途 |
| --- | --- |
| `now-time-info` | 获取服务端时间(活动日历/预约场景需要) |
| `query-my-account` | 积分账户(用于自检与积分兑换场景) |
| `campaign-calendar` | 当月活动日历 |
| `order-list` | 历史订单 |

## 3. 调用流程

```text
                        ┌──────────────────────────┐
                        │  用户输入: 热量区间 /      │
                        │  蛋白下限 / 预算上限       │
                        └────────────┬─────────────┘
                                     │
                 ┌───────────────────┴───────────────────┐
                 │           数据采集 (MCP)               │
                 └───────────────────┬───────────────────┘
       ┌─────────────────┬───────────┴─────────┬──────────────────┐
       ▼                 ▼                     ▼                  ▼
list-nutrition-   query-my-coupons      query-nearby-stores   now-time-info
   foods          available-coupons      delivery-*             (上下文)
       │                 │                     │
       │  营养字典        │  券池                │  storeCode
       └────────┬────────┴──────────┬──────────┘
                │                   │
                ▼                   ▼
        ┌───────────────────────────────────┐
        │  normalize + attach_nutrition      │  ← 菜单餐品按名称挂营养
        └───────────────┬───────────────────┘
                        ▼
        ┌───────────────────────────────────┐
        │  optimize(): 双约束动态规划        │
        │  state = (热量桶, 蛋白桶, 必需掩码) │
        │  value = 最低到手价                 │
        └───────────────┬───────────────────┘
                        ▼
        ┌───────────────────────────────────┐
        │ 有效方案 (营养达标 / 预算内 / 件数合规)│
        └───────────────┬───────────────────┘
                        ▼
        ┌───────────────────────────────────┐
        │ calculate-price 复算  →  用户确认   │
        │        →  create-order 下单         │
        └───────────────────────────────────┘
```

### 关键设计决策

1. **降级而不编造**:门店类接口依赖账号侧配置。取不到菜单时,
   自动切换到 `examples/sample-menu.json` 并在输出顶部**明确标注**
   "价格为示例",绝不把示例价伪装成真实价。
2. **求解与取数解耦**:`optimizer.py` 是纯函数式求解器,不依赖网络,
   因此可以用穷举做差分验证。
3. **下单前强制复算**:任何"创建订单"前必须先 `calculate-price`,
   避免用可能过期的自算价下单。

## 4. 业务价值

| 维度 | 价值 |
| --- | --- |
| 对用户 | 把"减脂期怎么点麦当劳"从模糊感觉变成可复现的最优解:同样的钱多吃蛋白,同样的营养少花钱。 |
| 对 MCP 生态 | 展示了 MCP 不止能"问答式点餐",还能作为**结构化决策系统的数据底座** —— 营养库 + 券池 + 菜单三源合一,驱动一个真实的优化器。 |
| 对开发者 | 提供了一份"如何解析 MCP 非结构化返回"的参考实现:紧凑表格、Markdown 券列表、分类菜单三种形态都被显式处理并单元测试覆盖。 |
| 可扩展性 | 求解器与数据源解耦,新增约束(钠/钙上限、口味偏好、时间窗)只需扩展 `Constraints`,无需改动 MCP 调用层。 |

## 5. 自检与复现

```bash
# 连通性 + 账号状态
python -m mcd_meal_optimizer check

# 列出 MCP 当前全部工具
python -m mcd_meal_optimizer tools

# 券解析结果
python -m mcd_meal_optimizer coupons

# 营养库
python -m mcd_meal_optimizer nutrition --query 板烧 --top 10
```
