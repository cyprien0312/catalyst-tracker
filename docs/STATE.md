# catalyst-tracker — 短期记忆

> 本 repo 的**唯一**状态与待办来源。别处只能链接过来，不许另起清单。
> 最后更新：2026-08-05（C1/C2 正则 + C3/C6/C11 新闻分类器误报**均已修**，
> 分别经 27 份真实 filing 与 2901 条真实告警实测核对）

## 现在是什么状态

- **能跑吗**：能。`.venv/bin/pytest` → **309 passed**（2026-08-05 实跑）
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
- **上次动它**：2026-08-05（两轮误报修复：`lib/filing_context.py` 句子级上下文闸门堵
  C1/C2 的会计样板 / 风险因素；`lib/rss.py` 的 `entry_text()` + 各自的词义/同名冲突闸门
  堵 C3/C6/C11 的新闻误报）。
- **buy plan 此刻仍在 Regime B**，撑着它的只有那条已被认定为误报的 C2 告警
  （2026-07-29 20:38 UTC / **07-30 06:38 本地**）。**改正则不回溯清洗 `alerts` 表**，
  该行 **2026-08-05 20:38 UTC（08-06 06:38 本地）** 自然滚出 7 天窗口，
  届时 `rung_alert.py` 发一条 B→A 的 MED 翻转告警。
  用户 2026-08-05 决定**让它自然过期，不手删**。无需动作。
- **git**：`main`，与 origin 同步，工作区干净。

## 待办

| 优先级 | 事项 | 不做会怎样 |
|---|---|---|
| ~~**P1**~~ | ~~**C1/C2 的正则在「风险因素」和「会计政策附注」样板句上误报**，已实锤两例（详见下方「正则误报核验证据」）~~ —— **2026-08-05 关闭，凭据见「最近关掉的」第一条** | ~~C2 是引信：一句假设句就把买入梯队从 Regime A 冻到 B~~ |
| P2 | CLAUDE.md 的「坑 / 局限 / 故意没做的」三节合计 **18 条**，超过 workflow-kit 的 15 条阈值 | 按 kit 的规矩该拆出 `docs/limits.md`、CLAUDE.md 只留一行链接。**故意没拆**：SessionStart hook 靠 grep CLAUDE.md 的这几个小节标题给指针，拆走内容会让那个指针指向空壳。要拆得连 hook 一起改 |
| P2 | C11 的新闻分类器把 HIGH 发得过于随意（近 7 天 53 条 HIGH 全是 RSS 新闻），HIGH 已失去区分度 | 现在靠 CRITICAL 地板绕过了，但 news roll-up 里 HIGH/MED 的排序仍然没意义。**2026-08-05 部分处理**：CRITICAL 的误报已修（见「最近关掉的」），但 HIGH 本身仍是 150 条 `unlock`/`lock-up expir` 的评论 —— 那是**调音量**不是 bug，要动得先定「HIGH 应该意味着什么」 |
| P2 | **C6 的 CRITICAL 层从没响过一次**（1034 条告警里 0 条），因为 `_SUBJECT_RE` 只认产品词（DRAM/NAND/HBM/SSD/HDD），而砍单/砍资本开支这类最高级别的事**是用公司口径报道的**："Samsung's chip output cut"、"hyperscalers cut capex" 都 subject=False | C6 的邮件地板是 CRITICAL ⇒ **C6 至今一封邮件都没发过**。修法是把内存厂商名加进 subject 闸门，但那会让 C6 显著变吵（当初就是故意不放公司名的）—— 属于调音量，要先拍板 |
| P2 | C3 的 98% 告警（1567/1595）来自单个 token `\bIPO\b`，代码注释自己都写着 "daily speculation" | MED 层完全被 IPO 投机刷屏，news roll-up 里 C3 那一段没有信息量。删或降级都行，但那是**调音量**，得用户定 |
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

> ✅ **已于 2026-08-05 实现，但故意没按「按章节切」做** —— `lib/filing_context.py` 走的是
> **句子级**判断。实测原因：AMZN FY2025 10-K 里**真正的** 6→5 年折旧变更就写在
> Use of Estimates 附注**里面**，紧跟样板句后约 150 字符
> （"…viewing patterns of capitalized video content. Actual results could differ materially
> from these estimates. **Effective January 1, 2025 we changed our estimate of the useful
> lives of a subset of our servers and networking equipment from six years to five years.**"）。
> **把 Use of Estimates 整节切掉，会连 C1 最核心的真信号一起切掉**；任何宽到能看见样板句的
> 字符窗口同理。这条被钉进 `tests/fixtures/amzn_use_of_estimates_note.txt`（样板句与真披露
> 留在同一段）。「邻近有陈述性证据」这一半采纳了，实现为 `AFFIRMATIVE` + 各 catalyst 的
> `REQUIRES`。

## 已放弃（附原因，别再提）

- ~~用 GitHub Actions 跑生产调度~~ — 故意关掉，生产在本机 cron（见 CLAUDE.md）

## 最近关掉的

- **C3 / C6 / C11 新闻分类器的同类误报** —— 承接 C1/C2 那轮，按用户要求只修**确定性 bug**，
  调音量的部分留成待办（见上表三条 P2）。

  **共同根因**（和 filing 那套不同）：proximity window **只量字符距离，不做实体归属**；
  且 Google News 的 item 不是纯文本，title 尾巴是 ` - 出版方`、summary 是 HTML 裹着
  base64 URL 再加一遍出版方名 —— **出版方的名字能贡献 tier token**。

  修了四处：
  1. `lib/rss.py` 新增 **`entry_text()`**，剥掉出版方名 / HTML / 文章 URL，成为 C3/C6/C11
     分类的唯一入口（原来三个模块各自手写 `title + summary`）。
  2. `c3_openai._TOKEN_GUARDS` —— `restructuring` 要求不是"裁员/换人"义，`default` 要求
     债务语境。
  3. `c6_memory` —— `_DEAL_NOISE_RE` 补上零售 SKU 定价（`drops to $x.99`、`41% off`），
     新增 `_TICKER_COLLISION_RE`（**HBM 也是 Hudbay Minerals 的代码**）和分析师
     `target price` 排除。
  4. `c11_spacex` 的 CRITICAL lock-up token **原来是反的**：命中 "staggered lock-up
     release"（日程内、leg 1 的 `UNLOCK_SCHEDULE` 早就确定性发过），却匹配不到
     "waived the lock-up early"（真正的意外供给）。改成要求 waive/accelerate/早于日程，
     日程内的 release 降到 HIGH。

  凭据：把 `alerts` 表里 **2901 条真实新闻告警**用「改前 vs 改后」两份代码全量重放：

  | | CRITICAL | HIGH | 说明 |
  |---|---|---|---|
  | C3 | **9 → 5** | — | 消掉的 4 条：Starling 裁员、"long-term default"（设置义）、安全负责人离职、以及出版方就叫 **"Going Concern"** 的那条 |
  | C6 | 0 → 0 | **69 → 43**，另有 65 条整体降为不告警 | 消掉的全是 Technobezz 之流的零售 SSD 降价 + Hudbay Minerals(HBM.US) |
  | C11 | **3 → 0** | 147 → 150 | 那 3 条 CRITICAL 全是日程内 release，降到 HIGH 才对 |

  真信号存活已逐条验证：C6 的 DRAM 暴跌/oversupply 四条仍 HIGH；C3 的 Oracle 债降级、
  SoftBank 发债仍 CRITICAL，且构造的 "OpenAI defaulted on a $2bn loan payment" 仍 CRITICAL；
  C11 构造的 "waived the lock-up early" 现在能进 CRITICAL（改之前进不去）。
  **改动自身没引入任何新的 CRITICAL**（重放实测 0 条）。
  `pytest` → **309 passed**（改前 295，新增 14 个用例，全部钉在真实标题上）。2026-08-05

  ⚠️ **留了一条已知残留**：「Meta Admits AI Restructuring Fell Short … Close Gap With
  OpenAI」仍是 C3 CRITICAL。这是**实体归属**问题，不是词义问题。**故意没用「离 token
  最近的公司才算」规则修** —— 那条规则会把「S&P Downgrades **Oracle**'s **Bond** Rating,
  Names OpenAI as a Credit Risk」这种真信号一起杀掉。宁可留一条误报。

- **C1 `IMPAIRMENT_PPE` 命中每份 10-Q 都有的 GAAP「Use of Estimates」样板** —— 以及同一类
  的另外三个误报。新增 `lib/filing_context.py`：按**句子**（不是字符窗口）判断命中落在
  会计政策样板 / 风险因素虚拟语气 / 真实披露里，前两者丢弃，**失败时放行**（漏报是静默的，
  更贵）。C1/C2 的 `scan_text` 都改走它，并从 `search` 换成 `finditer`（样板总在文件靠前，
  `search` 会让它挡住后面的真信号）。

  凭据：抓了 6 个 hyperscaler + 3 个 neocloud 的 **27 份真实 10-K/10-Q** 跑前后对比 ——
  6 份会告警的降到 2 份，消掉的 4 份逐条核对过都是误报：

  | filing | 之前 | 之后 |
  |---|---|---|
  | AMZN 10-Q 2026-07-31（`0001018724-26-000026`，就是那条 C1-HIGH） | HIGH | **不再告警** |
  | AMZN 10-Q 2026-04-30 | HIGH | **不再告警**（"长期合同加权平均剩余年限 5.5 年" 误命中 `META_5_5_YEARS`） |
  | GOOGL 10-K 2026-02-05 | HIGH | **不再告警**（ASC 360 减值*方法*段落，不是减值） |
  | APLD 10-K 2026-07-29（翻了 buy plan regime 的那条） | HIGH | **不再告警**（风险因素虚拟语气） |
  | AMZN 10-K 2026-02-06 | HIGH | HIGH ✅ 真的 6→5 年折旧变更**照常告警** |
  | META 10-K 2026-01-29 | HIGH | HIGH ✅ 真的 $237M 减值 + 5.5 年变更**照常告警** |

  `.venv/bin/python -m pytest` → **295 passed**（原 271 + 24）。新增 canary fixture 全是
  真实 filing 的**逐字**摘录：`amzn_use_of_estimates_note.txt` 特意把样板句和它后面约 150
  字符处的**真**披露留在同一段，钉死「不能用字符窗口做上下文判断」这条。2026-08-05

- **每天十几封告警邮件** — 凭据：按 `alerts` 表近 7 天真实历史回放新配置，
  68 封 → 5 封；`scripts/news_report.py` 实发一封验证通过（36 items）；
  `tests/test_news_report.py` 16 个用例 + 全套 271 passed。2026-08-04
- **`~/CLAUDE.md` 写着「five catalysts (C1–C5)」** — 已改为 C1–C11，并补上邮件量策略。
  凭据：`grep -n "five\|C1–C5" ~/CLAUDE.md` 已无残留。2026-08-04
- **文档写着 Gmail SMTP** — 实际早已换成 Resend HTTP API（`lib/email_send.py`），
  CLAUDE.md 和 README 的 4 处引用已改。2026-08-04
