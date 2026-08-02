# catalyst-tracker — 真相源

> 本 repo 的**唯一**状态与待办来源。别处只能链接过来，不许另起清单。
> 最后更新：2026-08-03（首次建立，状态经实跑核对）

## 现在是什么状态

- **能跑吗**：能。`.venv/bin/pytest -q` → **255 passed**（2026-08-03 实跑）
- **跑在哪**：本机 crontab，**11 个 catalyst + 3 个辅助任务**（`crontab -l` 核对）
  | 任务 | 频率 |
  |---|---|
  | `c1_depreciation` `c2_neoclouds` `c3_openai` `c4_capex` `c5_grid` `c6_memory` `c7_credit` | 每半小时，错峰 |
  | `c11_spacex` | 每小时 :47 |
  | `c8_macro` 07:17 · `c9_crypto` 08:23 · `c10_liquidity` 08:29 | 每天 |
  | `refresh_knowledge.sh` 08:45 · `send_daily_report.sh` 09:00 · `check_rungs.sh` 每小时 :53 | 每天/每小时 |

  GitHub Actions 的定时是**故意关掉**的，生产跑本机 cron。
- **上次动它**：2026-08-03（最新 commit 是 cron 自动写的 `state:` 提交，不是开发改动）。
  最后一次**人写的**改动要往前翻——从 commit 记录反推，不是确认过的事实。
- **git**：`main`，与 origin 同步，工作区干净。

## 待办

| 优先级 | 事项 | 不做会怎样 |
|---|---|---|
| P1 | `~/CLAUDE.md` 和本 repo 的 CLAUDE.md 都写着「five catalysts (c1–c5)」，**实际有 c1–c11 + 3 个辅助任务** | 下个 session 按 5 个催化剂理解系统，改错调度或漏掉一半告警 |
| P2 | 每次 cron 运行写一个 `state:` commit，历史里全是自动提交 | 人写的改动被淹没，`git log` 失去可读性；排查"上次改了什么"要翻很多页 |
| P2 | 本文件的「上次人工改动」栏是从 commit 反推的，没核实 | 下次接手时对项目活跃度判断偏差 |

## 已放弃（附原因，别再提）

- ~~用 GitHub Actions 跑生产调度~~ — 故意关掉，生产在本机 cron（见 CLAUDE.md）

## 最近关掉的

- （首次建立，暂无）
