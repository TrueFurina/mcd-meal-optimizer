# MEMORY.md — mcd 项目长期笔记

## 项目定位
本工作区（`E:/Program/mcd`）承载 **麦当劳 MCP 相关开发**，当前主线是
**「麦当劳程序员创意开发大赛」参赛项目**。

## 参赛项目：麦麦算盘（mcd-meal-optimizer）
- 一句话：营养 × 预算双目标餐搭求解器（热量区间 + 蛋白下限 + 预算上限 → 最优组合）。
- 仓库：https://github.com/TrueFurina/mcd-meal-optimizer （公开）
- 本地：`E:/Program/mcd/mcd-meal-optimizer`
- 报名 Issue：#204（M-China/mcd-developer-innovation-challenge）
- 命题期：2026-10-09 ~ 2026-10-25 23:59；**按 Star 数排名**（前 100 名有奖）。
  **Star 数为 0 的项目不进入排行榜**（拉星 = 入榜门槛，不是加分项）。
- 官方规则原文：`E:/Program/mcd/activityGuidelines.md`
- **官方排行榜**：活动仓库根目录 `RANKING.md`（滚动更新，读法见下）。
  2026-10-13 01:00 快照：榜上 **115 项**，头部 232 星，**末位门槛 5 星**；
  我方 2 星**未入榜**。快照存 `promo/官方排行榜快照-20261013.md`。
  → 参赛 ≠ 获奖：**技术闭环走完只是入场，拉星才是比分**。
- **赛道同质化**：115 个榜上项目中 **32 个**同为「营养/预算/热量/券/优化」方向
  → 功能优势不足以拉星，**胜负在传播渠道**。
- 🔴 **严禁刷星**（规则第 92 行）：禁止刷榜/操纵 Star 数据/多账号/与其他用户串通/
  群控软件 → **取消参赛资格及获奖资格**。合法路径只有「真实内容触达真实用户」。
- 视觉物料：`mcd-meal-optimizer/assets/{hero,architecture}.svg`（手写 SVG，
  生成脚本在工作区 `_svg_gen.py`，不进仓库；改图后用 headless Chrome 渲 PNG 目视校验）。
- 传播物料在仓库外：`E:/Program/mcd/promo/`（对比物料 / 发布长文 / 短文案）。

## 合规红线（活动规则原文，不可碰）
- 规则「内容合规」第 e 条：**禁止将麦当劳品牌、产品与其他品牌、产品对比**，
  亦禁止贬低麦当劳品牌/产品/形象 → 所有文案只对比「模糊回答 vs 可验证读数」。
- 官方 Issue 示例方向是「麦当劳营养膳食专家（根据每日消耗搭配麦麦套餐）」，
  不要写成"套餐推荐助手/省钱助手"。

## 关键约定（长期）
- **必需文件**（缺一报名失败，文件名不可改）：
  `README.md` / `CONTEST_DECLARATION.md` / `MCP_INTEGRATION.md` /
  `mcp-config.example.json`。`CONTEST_DECLARATION.md` 必须用官方原文且**不可修改**，
  改动会失去参赛资格。
- **仓库内绝不放真实 Token**：配置文件只允许环境变量占位符（`${MCD_MCP_TOKEN}`）。
- **`.gitattributes` 必须保留**（`* text=auto eol=lf`）：Windows 下 CRLF 转换会
  改变官方声明的字节。
- 麦当劳 MCP Token 存于 **Windows 用户级环境变量 `MCD_MCP_TOKEN`**（HKCU），
  不落盘到任何仓库文件。MCP 连接器配置在 `~/.workbuddy/mcp.json`。

## 麦当劳 MCP 服务要点
- 端点：`https://mcp.mcd.cn`（Streamable HTTP + `Authorization: Bearer <token>`），
  35 个工具，限流 600 次/分钟；响应是纯 JSON，真实数据在
  `result.content[0].text` 的 `## Original Response` 段之后。
- 返回体是**文本套 JSON/表格/Markdown**，不是结构化 JSON —— 必须走解析层
  （见 `mcd_meal_optimizer/parsers.py`）。
- **门店发现不需要账号配置**（v1.1.0 推翻旧结论）：`query-nearby-stores` /
  `delivery-query-*` 依赖账号收藏与地址，全新账号必然空；改用公开链路
  `mall-points-products → query-party-city{spuId} → query-party-store{code,lat,lng,spuId}`
  按城市拿到真实 `storeCode`。拿到 storeCode 后 `query-meals` /
  `calculate-price` / `create-order` 只认门店编码，与账号收藏无关。
  到店自取 = `beType=1 / orderType=1 / 不传 beCode`（传了报错）。
- 关键接口实测细节（易踩）：
  - `query-meals` → `{categories, meals}`；**价格单位是元**，分类要从 categories 反查。
  - `query-meal-detail` → `rounds[].choices[]` 的 `isDefault=1` 是**套餐默认组成**
    （套餐营养 = 组成求和）；单品 rounds 为空，但 `data.name` 是**带规格精确名**
    （菜单「薯条」→ detail「中薯条」）→ 营养匹配必须用 detail 名。
  - `calculate-price` **返回单位是「分」**；`takeWayList[].code`
    （`eat-in`/`locker-out`）是 `create-order` 必传的 `takeWayCode`。
  - `create-order` 只创建**未支付**订单并返回支付入口，但仍是真实订单
    → 代码里有确认闸门（未确认抛异常且不发请求）。
  - **订单状态码**：`status` **10 = 待支付**，**60 = 已取消**（`orderStatus` 同义文本）。
    撤单 `cancel-order {orderId, cancelReasonCode:1}` → `{"cancelResult": true}`；
    查单可用 `query-order {orderId}` 或 `order-list`（无参，`data.list[]`）。
  - 订单金额三方一致：求解器预测 == `calculate-price.price` == 订单 `totalAmount`
    （单位元；`create-order` 返回体里也是元，与 `calculate-price` 的「分」不同）。
  - 端到端已实测闭合（2026-10-10，门店 1450713，¥23.80，建单后立即撤销）。

## 技术栈与验证纪律
- Python 3.10+，**零第三方依赖**（仅标准库）。
- 测试：`python -m unittest discover -s tests -t .`（64 项）。
- 求解器改动必须做 **DP vs 穷举差分 + 变异验证**，两条都过才算通过。
- 营养门禁：营养约束生效时**默认排除**营养不完整餐品
  （`Constraints.require_complete_nutrition=True`）—— 按 0 计算会伪造"达标"。
- 名称匹配只接受高置信匹配并**刻意保留区分字**（`麦乐鸡4块`≠`麦乐鸡5块`）；
  实现用**字符多重集**而非分词（中文连写无空格，分词处理不了词序差异）。

