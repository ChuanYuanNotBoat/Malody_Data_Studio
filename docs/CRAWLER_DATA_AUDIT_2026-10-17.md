# 爬虫数据源、解析与匹配核对

核对日期：2026-10-17（Asia/Singapore）。基于当前工作区，HEAD 为 `54b8b55cf88d394f7f67a5368ed8ff7448f8c964`，包含尚未提交的改动。

**结论：数据源域名和主要 API 路径正确，但存在可复现的身份错配、字段误解析和统计口径错误。不能据此认定现有数据全部准确。** 页面解析接口的错误与 STB 入库爬虫分别列出，避免混淆影响范围。

首轮为抽样网络读取、生产数据库只读检查、内存数据库复现和测试。后续已按用户要求更新本地凭据、补齐 Not recommend 采集并回填明确的历史分类；详见[完整度补充报告](CRAWLER_INTEGRITY_AUDIT_2026-10-17.md)。其余审计问题尚未修复，下面保留首轮证据。

## 数据源实测

网络请求使用现有爬虫会话配置；没有输出 Cookie 或访客令牌。源码抓取工具访问站点受限，以下结论来自本地实际 HTTP 请求和保存的响应。

| 数据源 | 本次结果 | 判断 |
| --- | --- | --- |
| `https://api.mugzone.net/api/web/auth/guest/wt` | 访客鉴权成功 | 新版 API 地址和鉴权流程可用 |
| `/ranking/global?mode=0&mm=0` / `mm=1` | 均 `code=0`，首批各 40 条，`hasMore=true,next=40` | EXP / MM 切换、主要字段和分页响应符合代码预期 |
| `/ranking/player/all?touid=1313854` | `code=0`，返回 `grade/gradeRank` 等 | 个人 MMR 读取的字段名正确 |
| `/community/chart/info`、`/community/song/info`、`/community/song/charts` | 均 `code=0` | 顶层详情字段与 `data` 列表的区分正确 |
| `/store/list2?from=0&type=0` | `code=0`，20 首歌曲，`next=20` | 新版歌曲发现入口可用 |
| `https://m.mugzone.net/chart/17302`、`/chart/8438`、`/song/4448` | 返回实际 HTML 内容 | 旧站谱面、歌曲页仍可作为数据源 |
| `POST /page/chart/filter` | 返回 JSON 内容，Content-Type 为 `text/html`；能正确读取 `id` | 兼容非标准 Content-Type 的处理有效 |
| `/plugin/talk/list?key=chart_…` | 正常返回；后续确认正、负投票都可能 `type=1` | 方向分类已补正；事件数仍不能直接等同当前投票总数 |
| `/page/all/player?from=0&mode=0`、`/accounts/user/1313854` | 首轮过期凭据重定向登录；更新后正常返回真实页面 | 本地 token 已更新并实测有效；认证页面识别仍有逻辑缺陷，详见补充报告 |

正向关联验证：SID 4448 的旧站歌曲页与新版歌曲谱面 API 都列出 **219 个 CID，集合完全一致**；CID 17302 对应 SID 4448，两套谱面数据中的谱师 UID 68358、稳定者 UID 23095、模式 0、Stable 状态 2 一致。这些样本没有发现 STB 主爬虫整体把 SID/CID 关联颠倒。

## 未修复问题

### 1. P1：旧昵称回退会把不同 UID 合并

用户补充：源站当前玩家名不能重名。以下为防护缺陷的隔离复现，不代表源站存在同时重名玩家；改名后的旧名能否被其他 UID 使用也尚未验证。修复按当前名唯一约束处理，改名关联仍以 UID 为准。

位置：[crawlers/rankings.py](../crawlers/rankings.py)，`resolve_player_identity`，约 753–779 行。

按新 UID 查不到身份后，代码不检查旧身份的 UID 是否冲突，就按 `alias` 选第一条记录，并覆盖该身份及其全部别名的 UID。

内存数据库复现：UID 1001 使用 `OldName`，改名为 `NewName`；随后 UID 2002 使用 `OldName`。两者得到同一个 `player_id=1`，原身份 UID 被改为 2002。后续历史排名和玩家统计会串到一起。

修正方向：提供 UID 时以 UID 为权威；名称回退仅使用已核实的唯一当前名，候选 UID 尚为空时才允许补齐。遇到同一当前名关联不同非空 UID 时核对陈旧记录或源异常，不覆盖原 UID 或按历史别名自动合并。

生产库只读检查：当时没有发现 `player_rankings.uid` 与对应 `player_identity.uid` 不一致的记录，**本项为已复现的规则缺陷，不代表已证明生产库发生串号**。

### 2. P1：评论采集失败会被当作零条，并删除原有明细

位置：[crawlers/stb.py](../crawlers/stb.py)，`_fetch_chart_talk_items`、`_build_chart_social_data`、`_save_chart_comments`，约 751–850 行。

网络异常、非零业务码、正常空列表和分页中途失败最终都可能返回空列表或部分列表。调用方据此设置评论数，再先 `DELETE FROM chart_comments WHERE cid=?` 后写入本次结果。

内存复现：已有一条评论，模拟 talk 接口 HTTP 503；最终得到 `(recommend_count=0, comment_count=0, items=[])`，保存明细后旧评论数变成 0。分页中途失败也会用部分明细替换完整明细。

修正方向：返回明确的成功状态、分页完整性和数据；失败时保留旧计数及明细，只有完整成功结果可以做全量替换。

### 3. P1：推荐事件数量与官方当前点赞数混用，且截断结果被当成总数

位置：[crawlers/stb.py](../crawlers/stb.py)，`_build_chart_social_data`、`_save_chart_data_from_new_api`、两个 HTML 详情抓取函数，约 811、947、1376、1433 行。

- 实测 CID 8438：官方 `like=6`，完整 talk 列表有 **7 条**推荐事件，本地 `recommend_count=7`。`max(api_like, event_count)` 把不同口径混为一个值；这两项本来就不保证相等。
- talk 抓取最多 20 页、500 条。实测一页 15 条；按该真实响应结构离线重放 20 页后，300 条即停止，仍有下一页。CID 17302 官方 `like=3546`，评论流的局部数量显然不能作为完整总数。
- HTML 路径直接把 `recommend_count` 替换为评论流统计；新版路径则取最大值。同一谱面会因采集入口不同得到不同含义的值。
- HTML 页上的爱心区域现为 `Very Positive` / `N/A` 文本，没有数字，解析默认 `love_count=0` 还可能覆盖新版 API 已知值。

修正方向：明确区分当前点赞数与历史推荐事件数；前者使用官方 `like`，后者带完整性或截断标记。字段未出现时保留未知状态，不当作 0 覆盖。

### 4. P1：页面解析接口把 CID 当作 SID

位置：[routers/page_parser.py](../routers/page_parser.py)，`_parse_basic_chart_info`，134–135 行。

HTML 的 `ID:c17302` 明确是谱面 CID，代码却将其填入返回值 `sid`。真实页面重放结果：CID 17302 返回 `sid=17302`，正确值为 **4448**；CID 8438 返回 `sid=8438`，正确值为 **3292**。

影响范围是 `/page-parser/chart/{cid}` 等页面解析响应。STB 主爬虫另有 SID 提取逻辑，本次两个样本提取正确，不能据此认定数据库所有歌曲关联都错误。

修正方向：优先读取明确的页面歌曲链接或完整的页面元数据，并与目标 CID 分开校验。

### 5. P1：认证重定向被当作正常页面，连接检测误报成功

位置：[crawlers/rankings.py](../crawlers/rankings.py)，`crawl_mode_player`，约 1131 行；[crawlers/stb.py](../crawlers/stb.py)，`test_connection`，约 472、514 行。

当前旧站排行榜返回的是 HTTP 200 登录页，`raise_for_status()` 不会报错，最终解析成空排行榜。STB 连接检查仍打印“排行榜页面访问正常”和“连接测试全部通过”；本次 2026-10-17 的运行日志中也有这种表现。排行榜默认数据源仍是 `page`。

修正方向：检查最终 URL、登录页标记和必要页面结构；把认证失败与真实空榜区分开。当前可用的新版 API 可作为明确的数据源选择或受控回退，不能把空采集描述为成功更新。

### 6. P2：页面解析接口从第 4 名起漏读名次

位置：[routers/page_parser.py](../routers/page_parser.py)，`_parse_rank`，约 207–229 行。

真实页面前三名用 `i.label.top-N`，第 4 名开始用 `i.ranknum`。代码只处理前三名及 `span.rank`；后者实际放的是头像。两个真实页面各 40 条成绩，均得到 **37 个 `rank=None`**。

修正方向：匹配 `i.ranknum`，并校验每条成绩都有合法排名。

### 7. P2：旧站页面的长度不能同时作为歌曲和谱面长度

位置：[crawlers/stb.py](../crawlers/stb.py)，`parse_chart_page`，约 1307–1311 行。

代码把同一个 HTML `Length` 同时写到 `chart_length` 和 `songs.length`。实测 CID 17302：HTML 长度 140 秒，官方歌曲长度 140 秒，官方谱面长度 **137 秒**；CID 8438：HTML 117 秒，官方谱面长度 **116 秒**。因此两个字段并非可互换，切换数据源会导致“谱面长度变化”。

修正方向：谱面长度以谱面 API 字段为准，歌曲长度以歌曲元数据为准；旧页仅有一个长度时明确其来源和语义。

### 8. P2：歌曲标题保留了前导分隔符

位置：[crawlers/stb.py](../crawlers/stb.py)，`parse_chart_page`，约 1209–1213 行。

移除艺术家节点后先执行 `.strip()`，得到 `- OblivioN`；之后检查 `startswith(' - ')` 永远匹配不到这个已去掉前导空格的字符串。CID 8438 被解析为 `- OblivioN`，CID 17302 为 `- 無人区-Vacuum Track#ADD8E6-`。

只读统计：27,159 首歌曲中 26,589 条标题以 `- ` 开头，与缺陷表现一致；没有逐条证明这些标题全部错误。API 的英文标题与 HTML 的原文标题还会互相覆盖，应另行定义统一展示策略。

修正方向：按 DOM 提取标题正文，或只移除已知的艺术家分隔符，保留歌名本身合法的标点。

### 9. P2：Mod 映射键与实际 CSS 类列表不匹配

位置：[routers/page_parser.py](../routers/page_parser.py)，`_parse_mods`，约 316–318 行；`data/mod_mapping.json`。

实际图标为 `class="g_mod g_mod_5"`，代码把完整字符串用作映射键，配置键却是 `g_mod_5`。实测返回原始 `g_mod g_mod_5`，映射不生效。目前配置值仍是 `mod_5` 等占位符，修好取键后仍需要可信的 Mod 名称表。

### 10. P2：部分采集入口忽略模式、状态筛选

位置：[crawlers/stb.py](../crawlers/stb.py)，`main` 的 source 分支，约 3215–3236 行。

源码确认：只有 `--source api` 分支读取 `--modes`、`--statuses`；`all` 和 `newapi` 没有传递或应用这些参数。`all` 的旧 API 子流程又使用默认 Key/Stable，结果可能与调用者要求不符。本项由参数传递链确认，没有另行执行批量抓取。

修正方向：在所有支持筛选的来源中统一过滤，或明确拒绝不支持的参数组合。

## 数据时效问题：MM 同步被遗留锁阻止

`data/mm_sync.lock` 记录 PID 14552、创建时间 `2026-09-11T18:46:13.952481`；核对时该 PID 不存在。`_acquire_mm_run_lock` 只检查文件是否存在，没有验证进程是否仍存活。最新调度日志显示 `MM sync is already running, skip this cycle.`。

只读查询：`player_rankings_mm` 最新时间为 2026-04-29；`player_mmr_samples` 最新时间为 `2026-04-29T00:24:43.860550`。新版 API 本次能正常返回实时结果，不能把这些旧记录当作已经成功刷新。

本次未删除锁、未启动同步。应先补充遗留锁恢复逻辑，再单独恢复采集；锁创建之前的停更原因没有据此追溯确定。

## 已验证有效的当前改动

核对期间新增的 `crawlers/chart_metrics.py` 与 `crawlers/stb.py` 计数字段改动已重新检查：Donation 能解析 `118,222`；`Hot` 没有被误当成独立游玩次数；新版 API 缺少打赏和游玩次数时使用未知值并保留已有数据。真实 CID 17302 的 HTML 打赏为 118222，新版路径补充后也为 118222。

这些改动已解决原先“新版缺少打赏字段却写 0”的问题；没有解决上文推荐/评论、SID、排名、标题和身份匹配问题。

## 验证与证据

- 当前相关单元测试：`python -m unittest tests.test_malody_rankings_edges tests.test_stb_metrics -q`，**15 项通过**，测试数据库均为临时/内存数据库。
- 离线复现：`python logs/crawler_audit_20261017/reproduce.py`，**10 个问题表现、打赏修复和源 ID 一致性检查均复现/验证通过**。这是问题复现脚本，退出成功表示当前行为符合报告中的缺陷描述，不表示业务无缺陷。
- API 路由测试未能运行：当前 Python 缺少 `httpx2`（`httpx` 也不存在），`starlette.testclient` 导入失败。没有修改全局环境来补装依赖，不能声称完整测试套件通过。
- 原始 HTTP 内容、API JSON、复现脚本和结果保存在 `logs/crawler_audit_20261017/`，该目录按仓库规则被忽略；未保存访客鉴权响应或输出 Cookie。
- 数据库检查时共 83,146 个谱面、27,159 首歌曲、1,129,968 份玩家资料。玩家主页在用户更新凭据后已完成实际页面验证，覆盖写入与进度问题见补充报告。

建议修复次序：身份 UID 冲突保护 → 评论失败保留旧数据与统计口径统一 → 页面 SID/排名解析 → 登录状态识别及 MM 遗留锁 → 长度、标题、Mod、筛选参数。现有历史数据需要在规则修好后另行评估和重采，本报告没有批量回写数据。
