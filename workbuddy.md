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
3. 通过 Python `winreg` / `[Environment]::SetEnvironmentVariable`
   将 Token 写入**用户级环境变量** `MCD_MCP_TOKEN`,不落盘到仓库。

### 阶段二 · 接口实测(关键)

在写代码之前,先对 MCP 真实接口做了**探测**,而不是照着文档猜:

| 探测动作 | 发现 |
| --- | --- |
| `initialize` 握手 | 返回 `mcd-mcp 1.0.0`;响应体为**纯 JSON**(非 SSE) |
| `tools/list` | 实际 **35 个**工具(README 仅列约 30 个) |
| `tools/call` on `list-nutrition-foods` | 返回**紧凑表格字符串**而非 JSON,需自写解析器 |
| `tools/call` on `query-my-coupons` | 返回 **Markdown**,券规则需从标题推断 |
| `query-nearby-stores`(多城市) | 全部返回 `[]` —— 该账号无收藏门店 |

最重要的结论: **MCP 返回的不是结构化 JSON**。这直接决定了项目必须
自带解析层,也是本项目相对"提示词包装型"作品的核心工程价值。

### 阶段三 · 架构与实现

按"先定架构再填实现"的方式推进:

1. `models.py` —— 领域模型(营养/餐品/券/约束/方案);
2. `parsers.py` —— 三种返回形态的解析器;
3. `optimizer.py` —— 双约束动态规划求解器(纯函数,不依赖网络);
4. `mcp_client.py` —— 零依赖 MCP 客户端;
5. `planner.py` —— 编排层(取数 → 归一化 → 求解 → 渲染);
6. `cli.py` —— 命令行入口;
7. `SKILL.md` —— WorkBuddy Skill 定义。

### 阶段四 · 验证(含变异验证)

```bash
# 全量测试
python -m unittest discover -s tests -t .     # 23 tests, OK

# 随机差分测试: DP vs 穷举, 120 组实例
# 变异验证: 注入缺陷 → 确认测试 FAIL → 复原
```

关键纪律: **没有做变异验证的测试不算通过**。开发中注入了两次缺陷:

- "只搜索一半菜单" → 差分测试报 `24/120 次差分不一致`(已捕获);
- "丢掉热量下限" → 初版可行性测试**未捕获**,于是**补强了测试用例**
  (`test_kcal_min_enforced`),复验后才通过。

## 3. 使用的 WorkBuddy 能力

- **文件读写与代码编辑**: 直接在工作区创建并迭代源码;
- **命令执行**: 运行 Python 脚本、单元测试、CLI 端到端验证;
- **联网检索**: 抓取并解析两个官方 GitHub 仓库的规则文档;
- **环境配置**: 写入用户级环境变量,配置 MCP 连接器。

## 4. 复现命令

```bash
# 1. 申请 Token: https://open.mcd.cn/mcp
# 2. 设置环境变量 (Windows PowerShell)
[Environment]::SetEnvironmentVariable('MCD_MCP_TOKEN','<MCD_MCP_TOKEN>','User')

# 3. 自检
python -m mcd_meal_optimizer check

# 4. 求解
python -m mcd_meal_optimizer plan --kcal-min 550 --kcal-max 800 --protein 30 --budget 40

# 5. 测试
python -m unittest discover -s tests -t .
```

## 5. 诚实性说明

- 本文所述开发过程与项目实际代码一致,未夸大;
- 环境变量中的 Token 未写入任何仓库文件,仓库内仅存在占位符;
- 测试结论(23 passed / 变异被捕获)均有可复现命令支撑。
