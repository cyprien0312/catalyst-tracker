# catalyst-tracker — 短期记忆

> 本 repo 的**唯一**状态与待办来源。别处只能链接过来，不许另起清单。
> 最后更新：2026-08-05（C1/C2 regex 误报修复，状态经 27 份真实 filing 实测核对）

## 现在是什么状态

- **能跑吗**：能。`.venv/bin/pytest` → **295 passed**（2026-08-05 实跑，新增 24 个用例）
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
- **上次动它**：2026-08-05（新增 `lib/filing_context.py` 句子级上下文闸门，
  堵掉 C1/C2 的会计样板 / 风险因素误报）。
- **git**：`main`，与 origin 同步，工作区干净。

## 待办

| 优先级 | 事项 | 不做会怎样 |
|---|---|---|
| P1 | **buy plan 现在停在 Regime B，唯一撑着它的是 C2 那条误报**（2026-07-29 20:38 UTC 的
  APLD 10-K HIGH，是 7 天窗口内**唯一**一条 c2 告警）。regex 已修但**不会追溯删库里那一行**。
  它 **2026-08-05 20:38 UTC 自然滚出 7 天窗口**，届时 `rung_alert.py` 会发一条
  B→A 的 MED 翻转告警 | 在此之前梯子的快档是冻结的（Regime B = "freeze the fast ladder"），
  等于按一个假信号在管真钱。要立刻恢复就得手删那行 alerts 记录 —— **是否手删由用户定，我没动** |
| P2 | CLAUDE.md 的「坑 / 局限 / 故意没做的」三节合计 **18 条**，超过 workflow-kit 的 15 条阈值 | 按 kit 的规矩该拆出 `docs/limits.md`、CLAUDE.md 只留一行链接。**故意没拆**：SessionStart hook 靠 grep CLAUDE.md 的这几个小节标题给指针，拆走内容会让那个指针指向空壳。要拆得连 hook 一起改 |
| P2 | C11 的新闻分类器把 HIGH 发得过于随意（近 7 天 53 条 HIGH 全是 RSS 新闻），HIGH 已失去区分度 | 现在靠 CRITICAL 地板绕过了，但 news roll-up 里 HIGH/MED 的排序仍然没意义；真要修得调 `c11_spacex.py` 的 proximity classifier |
| P2 | 每次 cron 运行写一个 `state:` commit，历史里全是自动提交 | 人写的改动被淹没，`git log` 失去可读性；排查"上次改了什么"要翻很多页 |
| P2 | 本文件的「上次人工改动」栏是从 commit 反推的，没核实 | 下次接手时对项目活跃度判断偏差 |

## 已放弃（附原因，别再提）

- ~~用 GitHub Actions 跑生产调度~~ — 故意关掉，生产在本机 cron（见 CLAUDE.md）

## 最近关掉的

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
