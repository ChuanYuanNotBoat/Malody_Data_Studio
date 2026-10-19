# 人工重爬

入口为 `scripts/recrawl.py`。本次修复没有启动整体重爬，也没有设置自动任务。以下命令在项目根目录执行。

## 准备与范围

`prepare` 只建立 SQLite 一致性备份、隔离数据库和待处理任务，不发起网络请求。现有库保存在 `baseline.db`，采集结果写入 `data.db`，范围与批次 ID 保存在 `manifest.json`。

完整 ID 范围需要人工核实上界；连续若干 404 不能证明没有更高 ID。示例使用交互输入，避免把旧库最大 ID 当作源站真实上界：

```powershell
$Batch = "data/recrawl/20261018-full"
[int]$UidMax = Read-Host "已核实的本轮最大 UID"
[int]$SidMax = Read-Host "已核实的本轮最大 SID"
[int]$CidMax = Read-Host "已核实的本轮最大 CID"
.\.venv\Scripts\python.exe scripts/recrawl.py prepare --directory $Batch --uid-max $UidMax --sid-max $SidMax --cid-max $CidMax
```

上界不能小于库内已知 ID。范围逐段入队，不把百万 UID 一次装入内存。歌曲关联、谱面关联及排行榜中新发现的对象也会进入本批任务。

如只需要重核现有对象，可以明确使用 `--known-only`；这不等于覆盖全部未知 ID：

```powershell
.\.venv\Scripts\python.exe scripts/recrawl.py prepare --directory data/recrawl/known-only --known-only
```

已知玩家取资料、身份、刷新状态、历史排名/MMR 和启用配置的 UID 并集。EXP/MM 榜单使用全部支持模式，并按官方游标继续到列表结束。歌曲和谱面不限制模式或 Alpha/Beta/Stable 状态。旧完成位图、空歌曲集合和日常任务完成标记不直接继承为本轮完成。

## 人工启动与继续

```powershell
.\.venv\Scripts\python.exe scripts/recrawl.py run --directory $Batch --max-tasks 1000 --rpm 15
```

再次执行同一命令即可继续。`--max-tasks` 是本次处理任务/榜单页的上限，不是完成对象总数；`0` 表示处理到当前没有可执行任务为止。每分钟请求数限定 1–30，补充页面和评论请求也受统一限速约束。

任务分为玩家资料/排名、MMR、歌曲列表、谱面详情、评论，以及各模式 EXP/MM 榜单。只有所需保存成功后才能完成。达到评论分页限额时保留游标，下一次从同一代快照继续；部分结果不会删除旧记录。

Ctrl+C 会在当前操作结束后安全停止，未处理任务保留。异常退出留下的执行租约会到期回收；旧执行者不能确认另一执行者接管的任务。失败任务有重试时间，立即再次执行不一定会重复请求它。

登录过期时批次标记 `needs_credentials`。更新本地 `data/cookies.local.json` 后继续，不在聊天或版本库中存放凭据。

## 查看与收尾

```powershell
.\.venv\Scripts\python.exe scripts/recrawl.py status --directory $Batch
.\.venv\Scripts\python.exe scripts/recrawl.py report --directory $Batch
```

这两项不发起请求。`report` 输出 `report.json` 和 `exceptions.csv`，包含覆盖范围、继续位置、任务状态、前后计数、关键字段空值数、发生变化的对象数、失败/未完成/明确不存在对象。空值可能是未知，也可能是源明确不存在（如从未游玩的最后游玩日期），不能直接把它等同于漏采；每次写入的字段出现情况保存在观测记录中。

同秒评论超过接口单页能力时，时间游标可能无法继续。此时任务保持未完成并记录 `ambiguous_time_cursor`，不能把它手工改成完成来冒充全量。需要源站提供可继续的游标/查询能力，或保留这个覆盖例外。

`complete=true` 表示本批约定范围的任务闭环，不证明未知范围和已经消失的历史可恢复。未采集到的真实游玩次数、历史成就获得日期继续保持未知。页面成绩解析仅处理页面可见成绩，不代表完整成绩历史采集。

## 人工发布

核对报告后，可显式执行：

```powershell
.\.venv\Scripts\python.exe scripts/recrawl.py publish --directory $Batch
```

发布必须满足任务完成、数据库完整性检查通过、备份校验正确。它在同一写事务内核对原库与准备时基线，再应用保留旧历史的隔离结果；任何失败都会回滚数据和表结构变更。

**原库自准备后发生任何业务数据或表结构变化，发布会拒绝覆盖。** 此版本不自动合并并发修改；需保留本批结果，对照当前库核对冲突后再处理。不要通过替换基线文件或跳过校验绕过保护。发布前可停止日常写入，防止核对与发布期间产生新冲突。

`baseline.db` 是发布前的恢复依据，应与报告一起保留。发布成功后同一批次不能再继续采集或再次发布。
