# catalyst-tracker — 真相源

> 本 repo 的**唯一**状态与待办来源。别处只能链接过来，不许另起清单。
> 最后更新：2026-08-04（邮件降噪改造，状态经实跑核对）

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
| P2 | C11 的新闻分类器把 HIGH 发得过于随意（近 7 天 53 条 HIGH 全是 RSS 新闻），HIGH 已失去区分度 | 现在靠 CRITICAL 地板绕过了，但 news roll-up 里 HIGH/MED 的排序仍然没意义；真要修得调 `c11_spacex.py` 的 proximity classifier |
| P2 | 每次 cron 运行写一个 `state:` commit，历史里全是自动提交 | 人写的改动被淹没，`git log` 失去可读性；排查"上次改了什么"要翻很多页 |
| P2 | 本文件的「上次人工改动」栏是从 commit 反推的，没核实 | 下次接手时对项目活跃度判断偏差 |

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
