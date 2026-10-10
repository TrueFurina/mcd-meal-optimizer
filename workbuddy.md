# WorkBuddy 开发上下文

本文记录本项目在 **WorkBuddy**(腾讯 WorkBuddy 智能体)中开发的过程,
用于参赛的 WorkBuddy 联动奖励核验。

> 安全说明: 本文**不包含**任何真实 Token、密钥或账号凭证,所有出现的
> Token 均已用占位符 `<MCD_MCP_TOKEN>` 表示。

## 1. 开发环境

| 项 | 值 |
| --- | --- |
| 开发工具 | WorkBuddy (WorkBuddy 智能体) |
| 操作系统 | Windows (win32) |
| 运行时 | Python 3.13 |
| 第三方依赖 | 无(仅标准库) |
| 项目路径 | `mcd-meal-optimizer/` |

## 2. 开发流程

### 阶段一 · 情报收集

1. 读取官方仓库 `M-China/mcd-mcp-server`,确认接入地址
   `https://mcp.mcd.cn`、鉴权方式(Streamable HTTP + Bearer Token)、
   工具清单与错误码(401 / 429)。
2. 读取活动仓库 `M-China/mcd-developer-innovation-challenge` 的
   `README.md` 与 `activityGuidelines.md`,确认投稿要求:
   `README.md` / `CONTEST_DECLARATION.md` / `MCP_INTEGRATION.md` /
   `mcp-config.example.json` / `workbuddy.md`。
3. 通过 PowerShell `[Environment]::SetEnvironmentVariable` 将 Token 写入
   **用户级环境变量** `MCD_MCP_TOKEN`,不落盘到仓库。

### 阶段二 · 接口实测(关键)

在写代码之前,先对 MCP 真实接口做了**探测**,而不是照着文档猜:

| 探测动作 | 发现 |
| --- | --- |
| `initialize` 握手 | 返回 `mcd-mcp 1.0.0`;响应体为**纯 JSON**(非 SSE) |
| `tools/list` | 实际 **35 个**工具(README 仅列约 30 个) |
| `tools/call` on `list-nutrition-foods` | 返回**紧凑表格字符串**而非 JSON,需自写解析器 |
| `tools/call` on `query-my-coupons` | 返回 **Markdown**,券规则需从标题推断 |
| `query-nearby-stores`(多城市多关键词) | 全部返回 `[]` —— 该账号无收藏门店/定位 |

最重要的结论: **MCP 返回的不是结构化 JSON**。这直接决定了项目必须
自带解析层,也是本项目相对"提示词包装型"作品的核心工程价值。

### 阶段三 · 架构与实现

按"先定架构再填实现"的方式推进:

1. `models.py` —— 领域模型(营养/餐品/券/约束/方案);
2. `parsers.py` —— 四类返回形态的解析器;
3. `optimizer.py` —— 双约束动态规划求解器(纯函数,不依赖网络);
4. `mcp_client.py` —— 零依赖 MCP 客户端;
5. `planner.py` —— 编排层(取数 → 归一化 → 求解 → 渲染);
6. `cli.py` —— 命令行入口;
7. `SKILL.md` —— WorkBuddy Skill 定义。

### 阶段四 · 验证(含变异验证)

```bash
# 全量测试
python -m unittest discover -s tests -t .     # 64 tests, OK

# 随机差分测试: DP vs 穷举, 120 组实例
# 变异验证: 注入缺陷 → 确认测试 FAIL → 复原
```

关键纪律: **没有做变异验证的测试不算通过**。开发中先后注入多次缺陷:

| 注入的缺陷 | 结果 |
| --- | --- |
| "只搜索一半菜单" | 差分测试报 `24/120 次差分不一致`(已捕获) |
| "丢掉热量下限" | 初版可行性测试**未捕获** → **补强测试用例**(`test_kcal_min_enforced`)后才通过 |
| "去掉下单确认闸门" | `test_submit_without_confirm_refuses` 立即 FAIL(已捕获) |
| "不再排除营养不完整餐品" | `test_incomplete_items_excluded` 立即 FAIL(已捕获) |
| "把『块』误当容器词" | `麦乐鸡4块` 当场错配成 `麦乐鸡5块`,测试 FAIL(已捕获) |
| "不再剔除包装词" | 包装词相关的 3 个匹配用例 FAIL(已捕获) |

### 阶段五 · 打通真实链路(第二迭代)

初版只能读营养库与券;门店/菜单/下单因账号无配置而全部落空。第二迭代
把这条链路补全,**不要求用户做任何账号侧配置**:

1. **门店发现**: 实测发现 `query-nearby-stores` 与 `delivery-query-*`
   都依赖账号侧收藏/地址。转而验证一条公开链路
   `mall-points-products` → `query-party-city` → `query-party-store`,
   成功按城市拿到真实 `storeCode`(上海实测 3~5 家门店)。
2. **真实菜单**: `query-meals` 返回 `{categories, meals}`,价格是**元**、
   分类要反查。写成 `parse_menu_payload()`。
3. **套餐营养**: 套餐不在营养库里。用 `query-meal-detail` 的
   `rounds[].choices[]` 还原默认组成,逐项对齐营养库求和 ——
   这一步让「三件套」也能算出准确热量。
4. **单品规格坑**: 菜单显示「薯条」「雪碧」「牛奶」,营养库却是
   「中薯条」「雪碧（小杯）」「热牛奶中杯」,直接匹配全部落空。
   发现 `query-meal-detail` 的 `data.name` 正是**带规格的精确名**,
   改用它匹配后,营养完整项从 **58/121 提升到 82/121**。
5. **真实算价与下单**: `calculate-price` 返回单位是**分**,统一换算;
   `create-order` 前加**确认闸门**(未确认直接抛异常且不发请求)。
   实测求解器预测 ¥23.80,`calculate-price` 真实算价 ¥23.80,**完全一致**。
6. **可复现证据**: 新增 `scripts/snapshot_store.py`,把真实门店菜单导出为
   `examples/real-menu-1450713.json`(121 项),离线跑出的结果与联网一致。

## 3. 使用的 WorkBuddy 能力

- **文件读写与代码编辑**: 直接在工作区创建并迭代源码;
- **命令执行**: 运行 Python 脚本、单元测试、CLI 端到端验证;
- **联网检索**: 抓取并解析两个官方 GitHub 仓库的规则文档;
- **环境配置**: 写入用户级环境变量,配置 MCP 连接器;
- **长程自主迭代**: 按"实测 → 实现 → 测试 → 变异验证 → 文档"循环,
  在单个会话内完成两轮迭代(含真实链路打通与文档同步)。

## 4. 复现命令

```bash
# 1. 申请 Token: https://open.mcd.cn/mcp
# 2. 设置环境变量 (Windows PowerShell)
[Environment]::SetEnvironmentVariable('MCD_MCP_TOKEN','<MCD_MCP_TOKEN>','User')

# 3. 自检 + 门店发现链路
python -m mcd_meal_optimizer check --city 上海

# 4. 按城市发现真实门店
python -m mcd_meal_optimizer stores --city 上海

# 5. 真实菜单 + 营养覆盖
python -m mcd_meal_optimizer menu --city 上海 --top 20

# 6. 求解 + 真实算价复核
python -m mcd_meal_optimizer plan --city 上海 \
    --kcal-min 550 --kcal-max 800 --protein 30 --budget 40 --price-check

# 7. 下单预览 (加 --confirm 才真实建单)
python -m mcd_meal_optimizer order --city 上海 --item 9900005456

# 8. 导出真实门店快照 / 离线复现
python scripts/snapshot_store.py --city 上海
python -m mcd_meal_optimizer plan --menu-file examples/real-menu-1450713.json \
    --kcal-min 550 --kcal-max 800 --protein 30 --budget 40

# 9. 测试
python -m unittest discover -s tests -t .
```

## 5. 诚实性说明

- 本文所述开发过程与项目实际代码一致,未夸大;
- 环境变量中的 Token 未写入任何仓库文件,仓库内仅存在占位符
  (`mcp-config.example.json` 用 `${MCD_MCP_TOKEN}`);
- 测试结论(64 passed / 6 次变异被捕获)均有可复现命令支撑;
- README 中的运行输出均为**真实接口返回**,门店为
  「麦当劳上海黄浦华旭国际大厦餐厅」(1450713),抓取时间 2026-10-10;
- 营养库覆盖不到的餐品(121 项中 39 项)在文档与程序输出中**如实标注**
  并排除出解,未通过补零等方式"凑出"达标结论。
