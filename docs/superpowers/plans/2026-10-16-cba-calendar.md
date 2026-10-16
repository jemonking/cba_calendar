# CBA Calendar Implementation Plan

> For agentic workers: use superpowers:executing-plans inline. User explicitly approved skipping staged approvals.

**Goal:** 可验证、失败保留旧版的上海CBA固定ICS订阅。
**Architecture:** 官方JSON -> 严格解析/完整性验证 -> 版本合并 -> 原子构建静态站 -> Pages artifact/deploy。备用HTML只交叉核对。
**Tech Stack:** Python3.12 stdlib; pytest and icalendar for independent tests.
**Spec:** ../specs/2026-10-16-cba-calendar.md

## Global Constraints
- 2026–2027/29125/46轮；UTC存储、Asia/Shanghai展示；稳定官方ID。
- 来源故障不得发布空或缩水日历；公开发布另行确认。
- workflow级串行锁，部署直接upload-pages-artifact/deploy-pages。

## Review Focus
- 缺失Season字段仍正确识别本赛季，明确其他赛季不混入。
- 隐藏月份表格且缺末轮的备用不能独立发布。
- 延期没有新时间时保持原UID和上次时间，状态待定。
- 旧线上state读取失败时禁止静默重建，避免SEQUENCE回退。
- 改期、比分、取消后恢复、季后赛缺失均不造成事件丢失。

## Tasks
1. [x] `tests/test_sources.py`, fixtures -> RED -> `cba_calendar/sources.py` parse_official/parse_backup/validate -> GREEN.
2. [x] `tests/test_calendar.py` -> RED -> `cba_calendar/calendar.py` merge/render_ics/validate_state -> GREEN.
3. [x] `tests/test_update.py` -> RED -> `cba_calendar/update.py` fetch/load_previous/build/main; offline和HTTP故障测试 -> GREEN.
4. [x] `.github/workflows/{ci,update}.yml`, README, index template, docs/source-audit.md -> test full suite + live CLI + visual preview + static workflow check.
5. [x] 独立只读审查，修复实质问题，再验证；本地commit并汇报待发布事项。

## Execution ledger
- Repository was clean initial README/LICENSE only. Fresh dedicated clone and feature branch used; no shared checkout changes.
- Ruling: no separate worktree needed for this fresh dedicated clone; no existing changes or concurrent edits.

- 解析器RED后14项通过；合并与ICS RED后累计32项；更新入口RED后42项，首发保护和workflow累计45项。
- 独立审查复现两个问题：新渲染器校验旧摘要、季后赛ID替换重复。修复后48项通过，增加格式修订号驱动SEQUENCE。
- 实时官方+备用构建46场；独立icalendar解析46。Canary桌面1280及手机390截图检查通过；未点击订阅以免修改真实日历。
- 两项独立审查问题均已复核关闭；补充官方新日期/时间待定的移动测试，最终49项通过。
- 实际HTTP恢复线上格式状态和ICS摘要通过（本地预览服务器）；云端CI/部署与Apple实机待确认。
