# CBA Calendar

订阅一次，持续更新上海久事大鲨鱼的 CBA 比赛日程。首个赛季为 **2026–2027**，包含常规赛及官方公布后的季后赛，不含季前赛、俱乐部杯、全明星赛。

计划固定订阅地址：

```text
https://jemonking.github.io/cba_calendar/shanghai-sharks.ics
```

说明页：<https://jemonking.github.io/cba_calendar/>。首次部署成功后这些地址才可用。本项目为非官方球迷项目。

## 数据来源与核验

优先使用 [CBA 官方网站](https://www.cbaleague.com/) 首页实际调用的公开 JSON：
<https://portal-server.cbaleague.com/home/home_schedules>。

2026-10-16 已读取并独立复核上海常规赛 **46 场、1–46 轮、主客各 23 场**。五个指定验收日期与官方一致，包括新疆两场和广东客场的 20:00 开球；详见 [核验记录](docs/source-audit.md)。末轮对手官方冠名为“浙江浙商证券”（浙江广厦）。场馆只采用来源明确提供的信息，目前仅揭幕战有“上海体育馆”，其余不推测。

[备用 90vs](https://nba.90vs.com/zl/3/index.html) 需要解析 HTML 中全部隐藏月份表格。核验日它只含上海 **45 场常规赛，缺少 2027-04-07 末轮**，其余45场时间和主客与官方一致。因此备用仅作交叉核对与故障诊断，**不允许在官方抓取失败时独立发布**。冲突写入日志，官方时间优先。不得将备用源称为完整或长期可靠。

官方接口未提供版本契约，未来可能改版或只返回近期比赛。未知状态、字段变化、46场不完整等情况会阻止更新并保留旧版。没有尝试解密数据站接口、绕过登录或访问限制。

## 日历更新行为

- 固定 UID 使用官方 `ScheduleID`，不使用日期或队名；改期、比分、冠名变化更新同一事件。
- 内容变化时增加 `SEQUENCE` 并更新 `DTSTAMP`、`LAST-MODIFIED`，内容不变则整个 ICS 字节不变。维护者修改事件文本或格式时必须递增 `calendar.py` 中的 `RENDER_REVISION`，已有事件会同步增加版本；旧程序拒绝恢复比自身更新的格式版本。
- 北京时间转为带 `Z` 的 UTC，声明 `X-WR-TIMEZONE:Asia/Shanghai`。现代 Apple Calendar 会按设备时区显示；旅行时可启用时区覆盖/指定北京时间。
- 主客队及上海主客场明确，预计比赛2小时。仅明确场馆写入 `LOCATION`。
- 明确取消保留同一UID，标记 `STATUS:CANCELLED`；明确延期标记 `TENTATIVE`，有历史时保留上次已知时间供参考，等官方给出新时间后替换。若官方已给出新日期但未确定时刻，则移到新日期并以全天占位；描述说明其含义。
- 已完赛描述加入主客比分。来源遗漏比赛不当作取消；已有季后赛事件保留，常规赛快照缺少任何一场则整个更新失败。
- 新季后赛使用官方类型2；本赛季尚无真实季后赛样本，当前只验证了代表性测试，正式公布后还需对照官方复核。
- 仅识别官网已验证的数值状态1（赛前）、2（进行中）、4（完赛）；取消/延期依赖明确中文状态。其他数值不猜测，需审阅后新增映射。

## 自动更新与保存历史

工作流 [.github/workflows/update.yml](.github/workflows/update.yml) 每天 **北京时间10:23及18:23**运行，对应 UTC cron `23 2,10 * * *`；支持 `workflow_dispatch` 手动运行。GitHub 可能排队，时间不保证精确到分钟。公开仓库连续60天无仓库活动时，GitHub可能自动停用定时工作流；需在Actions重新启用，并关注失败通知和页面最后核验时间。见[GitHub定时触发限制](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。默认分支的程序变更也会更新日历。

每次先读取线上 `state.json`，校验版本、46场完整性、事件身份、序列号、固定规则的状态摘要以及线上ICS原始字节摘要，再抓取官方数据、交叉核对备用、生成整站。**读取线上状态失败绝不静默从仓库快照重建**，避免UID版本号回退。测试夹具仅用于本地预览和测试，生产参数禁止使用本地来源文件。

上传使用 `actions/upload-pages-artifact`，部署使用 `actions/deploy-pages`，没有自动提交及二次触发构建。工作流并发锁覆盖读取、构建和部署全过程。任何前置失败都不会执行部署，GitHub Pages继续保留上次成功版本；部署本身失败也不会用空目录替代线上版本。

每次日志输出 JSON，包括完整性、来源、备用缺场/冲突、增量、改期前后、保留的缺失比赛和ICS SHA-256。Actions摘要展示日志，诊断artifact保留90天。线上同时包含 `update-log.json` 和 `state.json`，两者仅含公开赛程；失败轮次的详情在Actions，不会覆盖线上最后成功日志。

请求超时25秒，网络或5xx错误最多两次；403、429不重试。备用不可用只记录警告，官方已完整通过时仍可更新。

## GitHub Pages 配置与首次部署

1. 在仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。本次只读检查已确认该仓库为此模式。
2. 将审阅后的代码合入默认分支 `main`。首次自动构建可能因尚无线上 `state.json` 而安全停止，这是预期保护。
3. 在 **Actions → Update and deploy calendar → Run workflow**，选择 `main`，**仅首次勾选 `bootstrap`**。只有线上 `state.json` 和ICS均不存在（404）时才允许首次建立历史；网络错误、403、429不能当成首次发布。
4. 等待 **build 与 deploy均成功**；若 `github-pages` 环境要求人工批准，在GitHub批准部署。
5. 打开说明页，检查 `state.json` 和ICS可访问且46场。此后手动更新不再勾选bootstrap。

部署需要 `pages:write` 与 `id-token:write`，源代码仅需 `contents:read`。仓库/组织策略若禁用Pages、外部Actions或环境部署，需由管理员调整。不是通过创建额外凭据解决。

固定地址目前按 `jemonking/cba_calendar` 配置。迁移仓库/自定义域名时需同时修改 `DEFAULT_BASE` 并为原地址保留跳转或迁移说明；随意换URL会影响已订阅用户。本项目只承诺首个赛季，下一赛季须明确设计与升级，不会静默混入。

## iOS / macOS 订阅

**iPhone / iPad：**在 Safari 或其他可处理 `webcal` 的浏览器打开说明页，点击“添加到 Apple 日历”并确认订阅。也可在日历App中打开“日历 → 添加日历 → 添加订阅日历”，粘贴固定HTTPS地址；不同系统版本菜单名称可能略有差异。

**macOS：**日历 → 文件 → 新建日历订阅，粘贴HTTPS地址，选择自动刷新间隔。需要跨设备时使用iCloud支持的订阅方式并确认账号同步设置。

必须选择**订阅**，直接下载ICS后导入只是一次性副本，之后不会自动更新。不要重复订阅同一URL。服务定时拉取后，Apple端还需自行刷新；ICS刷新间隔为建议值，并非推送或强制刷新。本次没有在实际iPhone/macOS Calendar账号中添加订阅，真实客户端同步仍需人工确认。

## 本地开发与验证

Python **3.12及以上**。生产逻辑仅依赖标准库；pytest、icalendar、PyYAML用于测试及独立格式解析。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest -q
```

使用真实公开快照离线生成可检查的站点（不发布）：

```bash
python -m cba_calendar.update --preview \
  --official-file tests/fixtures/official.json \
  --backup-file tests/fixtures/90vs.html \
  --output preview --log preview-log.json
python -m http.server 8765 --bind 127.0.0.1 --directory preview
```

使用实时官方/备用源本地预览：

```bash
python -m cba_calendar.update --preview --output preview --log preview-log.json
```

如要验证改期版本，可用 `--preview --previous-file preview/state.json` 配合官方快照重新构建；生产不会接受这些文件参数。预览不会部署、提交或修改Apple日历。部署命令只有工作流调用，正常运行不需新secret。

测试覆盖真实JSON/隐藏HTML解析、46场及五项验收、稳定UID、UTC转换、独立icalendar解析、75字节UTF8折行及转义、改期/比分/延期/取消/恢复、季后赛、来源异常与保持旧文件、状态损坏和网络限制。测试验证合成取消/延期逻辑，不表示这些状态已有真实线上样本。

## 故障排查

| 现象 | 检查与处理 |
|---|---|
| 首次运行提示 `previous state HTTP 404` | 确认从未部署，按上述首次步骤在main手动开启一次bootstrap；后续禁止随意开启。 |
| 提示 `expected 46 regular games` | 官网数据缺失或接口变为近期窗口。线上旧版仍在；检查官方，再修复适配器，不能降低门禁凑数。 |
| `unknown official status` | 查看官方公开样本和含义，补充有依据的映射与测试。不要把未知值直接当取消。 |
| `identity changed` / `match ID changed` | 官方变更了比赛身份，需要人工核验并迁移映射，避免重复日程。季后赛旧场次缺失且同轮同对手出现新编号时也会保守阻止发布，可能需人工区分新增场次与改编号。 |
| `previous state unavailable` / `checksum mismatch` | 停止发布；恢复最后成功部署的整站（含state和ICS）。不要删除state后强制bootstrap。 |
| HTTP 403 / 429 / 验证页 | 停止该来源，等待解除限制；不得绕过保护。网络和5xx允许下一轮重试。 |
| 备用只有45场、官方46场 | 本次已知差异，使用完整官方46场；查看交叉核对日志，不从日历删末轮。 |
| Pages部署失败 | 查看deploy日志、仓库Pages Source、环境批准、权限与额度；确认不是抓取失败。不应手动上传空日历。 |
| 日历时间未及时变化 | 查看页面最近核验、Actions日志与客户端订阅自动刷新；确认使用订阅而非导入，URL正确且未重复添加。 |

如需灾难恢复，应从仍可用的完整Pages部署artifact恢复；有效期受GitHub设置限制。仅重跑抓取工作流不会找回丢失的历史。恢复前须核对候选 `state.json` 与ICS一致且序列号不会倒退。诊断artifact只保留日志，不当作永久状态备份。建议关注GitHub Actions失败通知；站点显示的上次成功核验时间可识别陈旧数据。

接口和客户端参考：[GitHub Pages自定义工作流](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)、[Apple iPhone日历订阅说明](https://support.apple.com/guide/iphone/use-multiple-calendars-iph3d1110d4/ios)。
