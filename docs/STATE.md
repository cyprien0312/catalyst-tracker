# catalyst-tracker — 短期记忆

> 本 repo 的**唯一**状态与待办来源。别处只能链接过来，不许另起清单。
> 最后更新：2026-08-05（C1/C2 正则误报核验，证据见待办 P1）

## 现在是什么状态

- **能跑吗**：能。`.venv/bin/pytest -q` → **271 passed**（2026-08-04 实跑）
- **跑在哪**：本机 crontab，**11 个 catalyst + 4 个辅助任务**（`crontab -l` 核对）
  | 任务 | 频率 |
  |---|---|
  | `c1_depreciation` `c2_neoclouds` `c3_openai` `c4_capex` `c5_grid` `c6_memory` `c7_credit` | 每半小时，错峰 |
  | `c11_spacex` | 每小时 :47 |
  | `c8_macro` 07:17 · `c9_crypto` 08:23 · `c10_liquidity` 08:29 | 每天 |
  | `refresh_knowledge.sh` 08:45 · `send_daily_report.sh` 09:00 · **`send_news_report.sh` 09:10** · `check_rungs.sh` 每小时 :53 | 每天/每小时 |

  GitHub Actions 的定时是**故意关掉**的，生产跑本机 cron。
- **邮件量**：2026-08-04 起，逐条告警只在 CRITICAL（新闻类）/ HIGH（C10）/ 全部（保险丝 C7
  C2、硬数据 C4 C1、buyplan）时即时发；其余全部进 09:10 的 news roll-up。
  按真实 7 天历史回放：**68 封 → 5 封**。
- **上次动它**：2026-08-04（新增 `scripts/news_report.py` + `bin/send_news_report.sh`，
  调整 `~/.catalyst.env` 的邮件地板，修正 Gmail SMTP → Resend 的过期文档）。
- **git**：`main`，与 origin 同步，工作区干净。

## 待办

| 优先级 | 事项 | 不做会怎样 |
|---|---|---|
| **P1** | **C1/C2 的正则在「风险因素」和「会计政策附注」样板句上误报**，已实锤两例（详见下方「正则误报核验证据」） | C2 是引信：一句假设句就把买入梯队从 Regime A 冻到 B，目标仓位 0% vs 应有的 10%。信号源不可信 ⇒ 整套买卖判断不可信 |
| P2 | C11 的新闻分类器把 HIGH 发得过于随意（近 7 天 53 条 HIGH 全是 RSS 新闻），HIGH 已失去区分度 | 现在靠 CRITICAL 地板绕过了，但 news roll-up 里 HIGH/MED 的排序仍然没意义；真要修得调 `c11_spacex.py` 的 proximity classifier |
| P2 | 每次 cron 运行写一个 `state:` commit，历史里全是自动提交 | 人写的改动被淹没，`git log` 失去可读性；排查"上次改了什么"要翻很多页 |
| P2 | 本文件的「上次人工改动」栏是从 commit 反推的，没核实 | 下次接手时对项目活跃度判断偏差 |

### 正则误报核验证据（2026-08-05 拉原始 filing 逐条核过，别重新验证）

**共同根因**：`c1_depreciation.py` / `c2_neoclouds.py` 的 pattern 是**纯文本匹配，不区分章节，
也不区分陈述句和假设句**。而 10-K/10-Q 里有两个专门堆砌灾难词汇的地方——**Item 1A 风险因素**
和 **Use of Estimates 会计政策附注**——那里出现 `impairment` / `covenant default` /
`going concern` 是**必然的**，与公司实际状况无关。逐个 pattern 打补丁治不好。

**例一 · C1 `IMPAIRMENT_PPE`**（[c1_depreciation.py:18](../catalysts/c1_depreciation.py)）
`r"impair(?:ment|ed)[^.]{0,80}property\s+and\s+equipment"` — 触发 2026-07-31 的
`[C1-HIGH] AMZN 10-Q`。全文只命中 1 处，在 Use of Estimates 样板句：
> Estimates are used for, but not limited to, ... **impairment of property and equipment** and operating leases, income taxes, ...

同一正则在前两期同样命中同一句 ⇒ 常驻文本，不是新增语言：

| 报告 | accession | 命中 |
|---|---|---|
| 10-Q Q2 2026（触发本次告警） | `0001018724-26-000026` | 1（样板句） |
| 10-Q Q1 2026 | `0001018724-26-000014` | 1（同一句） |
| 10-Q Q3 2025 | `0001018724-25-000123` | 1（同一句） |

该 10-Q 里真实计提只有 MD&A 一行：Other Operating Expense, Net **$199M(Q2'25) → $90M(Q2'26)**，
且未与无形资产摊销拆分 —— **同比腰斩**，无 useful-life 调整。

**例二 · C2 `COVENANT_DISTRESS`**（[c2_neoclouds.py:24](../catalysts/c2_neoclouds.py)）
`r"covenant\s+(breach|default|waiver|amendment)"` — 触发 2026-07-30 的
`[C2-HIGH] APLD 10-K`，进而触发 `[BUYPLAN] regime A → B` CRITICAL。
APLD 10-K（`0001144879-26-000048`，FY 截至 2026-05-31）59.4 万字符全文**只命中 1 处**，
在字符 **102,329**，而 `Item 1A` 起于 **76,419**、`Item 7` 起于 **212,821** ⇒ **确定在风险因素内**：
> any adverse developments affecting ChronoScale, including ... **debt covenant defaults** or other liabilities, **could** have a material adverse effect...

主句是 `could have`，纯假设。同份 filing 的反证：

| 检查项 | 命中 |
|---|---|
| `GOING_CONCERN` / `MATERIAL_ADVERSE` pattern | **0 / 0** |
| 全文 `substantial doubt`（审计师持续经营存疑） | **0** |
| `we were in default` / `we defaulted` / `are in breach` | **0** |
| 12 处 `waiver` | 逐条核过：1 处风险因素假设句、4 处新融资的先决条件豁免（放贷方给便利，方向相反）、7 处是 **2024 年**历史文件的附件索引引用。**无本期真实豁免** |

APLD 本期实际大事是**分拆**不是困境：2026-05-05 把云业务分离为 ChronoScale Corporation（持股
约 97%，仍并表），7-01 完成控股公司重组；PEPA 的 Series G 承诺额度从 $590M **上调至 $1.59B**。

**代价（已实际发生）**：假引信让买入梯队 07-30 起冻结 6 天，累计目标 0% 而非 Regime A 的 10%
（NDX 同期 -9.5% → -3.0%）。**该告警于 2026-08-06 06:38 滚出 `recent_by_catalyst` 的 7 天窗口后
会自动翻回 Regime A**，所以这条待办修的是正则，不是当前 regime。

**修的方向**（别逐 pattern 打补丁）：先按章节切掉 Item 1A / Use of Estimates，再要求命中处邻近
有陈述性证据（金额、`recorded`/`incurred`/`as of`、具体日期）。两个样板句都要做成
**断言「不命中」**的 canary fixture 进 `tests/fixtures/`。

## 已放弃（附原因，别再提）

- ~~用 GitHub Actions 跑生产调度~~ — 故意关掉，生产在本机 cron（见 CLAUDE.md）

## 最近关掉的

- **每天十几封告警邮件** — 凭据：按 `alerts` 表近 7 天真实历史回放新配置，
  68 封 → 5 封；`scripts/news_report.py` 实发一封验证通过（36 items）；
  `tests/test_news_report.py` 16 个用例 + 全套 271 passed。2026-08-04
- **`~/CLAUDE.md` 写着「five catalysts (C1–C5)」** — 已改为 C1–C11，并补上邮件量策略。
  凭据：`grep -n "five\|C1–C5" ~/CLAUDE.md` 已无残留。2026-08-04
- **文档写着 Gmail SMTP** — 实际早已换成 Resend HTTP API（`lib/email_send.py`），
  CLAUDE.md 和 README 的 4 处引用已改。2026-08-04
