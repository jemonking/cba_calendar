# CBA Calendar 设计

用户已授权直接完成设计、计划、开发及测试；公开发布另行确认。

## 目标与验收
固定 `/shanghai-sharks.ics`，Apple Calendar 订阅上海久事 2026–2027 常规赛和官方公布后的季后赛。46场常规赛、轮次1–46、主客23/23；排除类型3季前赛、4全明星以及其他赛事。五场指定比赛对照官方抓取快照作为验收测试。

## 数据与边界
官方首页当前 JS 引用 `https://portal-server.cbaleague.com/home/home_schedules`。2026-10-16 公开HTTP200，490条（常规460、季前30），上海ID29125常规46条。只有首场包含Season/stadium扩展字段；日期窗口用于缺失Season的校验。数据站另一API默认返回加密正文，不使用、不解密、不尝试绕过。
备用站 `https://nba.90vs.com/zl/3/index.html` 全HTML隐藏月份表格包含上海常规45场，缺4月7日，另有3场季前赛。必须按table范围排除季前赛，不能把可见十月当完整赛季。备用不具备独立发布资格；官方故障时用于诊断，保持线上旧版本。冲突记录但不覆盖官方。

## 实现
Python3.12，生产仅标准库。解析、状态合并、ICS输出、更新入口分文件。UID=`cba-2026-2027-{ScheduleID}@cba-calendar`；不包含日期/球队冠名。UTC日期时间（北京时间转换），X-WR-TIMEZONE=Asia/Shanghai；每场2小时。比分与状态在描述中；可信场馆才写LOCATION。RFC5545 TEXT转义、CRLF、UTF8每行75字节折行。使用icalendar作为独立测试解析器。
状态记录SEQUENCE、DTSTAMP/LAST-MODIFIED；内容变化才递增。保留旧事件，来源缺失不解释为取消。常规减少、重复、改比赛ID、身份变化、未知状态均阻止发布。明确文字取消 => CANCELLED；延期 => TENTATIVE并保留旧时间；首次待定时间使用DATE而不伪造00:00比赛。

## 发布与恢复
GitHub Pages Actions直接上传整个站点并部署。固定北京时间10:23/18:23对应UTC02:23/10:23。一个workflow级并发锁，禁止取消执行中部署。已部署站点包含state.json和ICS；每次必须先恢复并验证线上state的canonical摘要与线上ICS原始字节摘要，网络错误不使用旧的仓库种子覆盖它。首发仅显式workflow_dispatch bootstrap且线上404时允许无历史；后续禁止bootstrap覆盖已存在版本。部署失败由Pages保留上个版本，日志artifact记录错误；不使用自动提交触发Pages。

## 测试与限制
真实公开快照离线解析、46场/五点/备用缺场；改期UID与SEQUENCE；比分、延期取消、遗漏保留、季后赛、跨赛季拒绝；RFC独立解析/时区/字节折行；入口故障不覆盖旧文件；网络重试/403和429立即停止。真实输入构建本地preview，公开发布前请求确认。Apple真实设备刷新不能由本机自动化保证，README解释客户端刷新并非推送。
