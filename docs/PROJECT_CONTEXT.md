# Malody Data Studio 项目上下文文档

## 0. 代码文件 Tree

```text
malody-data-studio/
|-- run.py
|-- config.py
|-- selector.py
|-- malody_rankings.py
|-- player_profile_crawler.py
|-- stb_crawler.py
|-- crawler_controller.py
|-- malody_stats.py
|-- requirements.txt
|-- core/
|   |-- database.py
|   |-- models.py
|   |-- security.py
|   `-- services/
|       |-- analysis_service.py
|       |-- chart_service.py
|       |-- crawler_task_service.py
|       |-- dashboard_service.py
|       |-- db_maintenance_service.py
|       |-- official_api_service.py
|       |-- player_service.py
|       |-- plugin_service.py
|       `-- quality_service.py
|-- routers/
|   |-- analytics.py
|   |-- charts.py
|   |-- crawler.py
|   |-- official_api.py
|   |-- page_parser.py
|   |-- players.py
|   |-- plugins.py
|   |-- quality.py
|   |-- query.py
|   `-- system.py
|-- utils/
|   |-- crawler_manager.py
|   |-- export_response.py
|   |-- query_builder.py
|   |-- selector.py
|   |-- stats_export_runner.py
|   |-- stats_update_runner.py
|   `-- stats_xlsx_formatter.py
|-- stats_cli/
|   |-- app.py
|   `-- plugins/
|       |-- registry.py
|       `-- *.py (commands)
|-- desktop/
|   |-- src/
|   |   |-- App.tsx
|   |   |-- api.ts
|   |   `-- i18n.ts
|   `-- src-tauri/
|       |-- src/main.rs
|       `-- tauri.conf.json
|-- scripts/
|   |-- run_pre_merge_gate.ps1
|   |-- check_stats_api_consistency.py
|   `-- probe_*.py
|-- tests/
|   `-- test_*.py (31 files)
`-- docs/
    |-- PROJECT_CONTEXT.md
    |-- OPERATIONS_RUNBOOK.md
    `-- CAPABILITY_MATRIX.md
```

## 1. 项目定位

`Malody Data Studio` 是一个围绕 Malody 数据生态构建的本地化数据平台，核心目标是：

- 通过爬虫采集排行榜、玩家资料、谱面/歌曲等数据并落地到 SQLite
- 通过 FastAPI 提供查询、分析、导出、运维接口
- 通过 CLI（`stats_cli`）和 Desktop GUI（`desktop/`）提供操作与可视化入口

一句话概括：**采集层 + 数据层 + 服务层 + 多终端入口**。

---

## 2. 顶层结构与职责分区

### 2.1 目录分层（按职责）

- `run.py`：FastAPI 启动入口，注册路由、中间件、文档与全局异常处理
- `routers/`：HTTP 接口层（参数校验、协议转换、调用 service）
- `core/services/`：业务服务层（SQL 组装、聚合、任务/质量/维护逻辑）
- `core/`：基础层（数据库连接、Pydantic 模型、安全鉴权）
- `selector.py` + `utils/selector.py`：统一筛选器（玩家/谱面 SQL where 生成）
- `malody_rankings.py` / `player_profile_crawler.py` / `stb_crawler.py`：三类主爬虫
- `crawler_controller.py`：爬虫编排控制器（邮件 + 本地命令 + 预设参数）
- `stats_cli/`：命令行交互与插件式命令系统
- `desktop/`：Tauri + React 桌面端，自动拉起本地 API 子进程
- `scripts/`：一致性校验、API 探测、打包辅助、预合并门禁脚本
- `tests/`：31 个测试文件，覆盖 API/服务/CLI/导出/路由边界

### 2.2 运行时分层

- 数据采集层：爬虫脚本与任务调度
- 数据存储层：`malody_rankings.db`（SQLite）
- 服务 API 层：FastAPI（默认 `0.0.0.0:8000`）
- 工具层：
  - CLI：`stats_cli/app.py`
  - Desktop：`desktop/src-tauri` + `desktop/src`

---

## 3. API 子系统架构

## 3.1 启动与装配

入口文件：`run.py`

- `create_app()`：创建 FastAPI 应用，配置 CORS、静态目录挂载
- `register_routers()`：注册 10 个路由模块
- `setup_routes()`：自定义 `/docs`、`/redoc`、根路由、健康检查、全局异常
- `main()`：检查 DB 文件，启动 uvicorn

已注册路由：

- `/players`
- `/charts`
- `/analytics`
- `/system`
- `/query`
- `/page-parser`
- `/crawler`
- `/official-api`
- `/quality`
- `/plugins`

## 3.2 路由层（routers）

- `players.py`：玩家榜单、玩家详情、历史、搜索、MM/MMR 统计
- `charts.py`：谱面统计、热度、最近更新、创作者、稳定者、导出
- `analytics.py`：玩家趋势、谱面趋势、模式对比、玩家对比、仪表盘总览
- `query.py`：受控高级查询（白名单表 + 安全过滤）
- `system.py`：系统健康、库信息、DB 维护操作
- `crawler.py`：爬虫任务发起与任务日志追踪、数据源健康快照
- `quality.py`：质量规则、同步/异步质量检查、质量报告
- `plugins.py`：内置插件目录与执行入口
- `official_api.py`：官方 API 代理（guest auth + store/song/chart/ranking/player）
- `page_parser.py`：网页解析（谱面页排行榜解析、歌曲检索与详情）

## 3.3 服务层（core/services）

- `PlayerService`
  - 排行榜数据查询（`exp/mm` 双表）
  - 玩家身份解析（uid/当前名/别名）
  - MM/MMR 数据健康统计（`player_rankings_mm`、`player_mmr_*`）
- `ChartService`
  - 谱面统计、质量评分、趋势、创作者维度聚合
  - 评论/推荐者（`chart_comments`）
- `AnalysisService`
  - 玩家时间窗变化分析、模式对比、多玩家对比
- `DashboardService`
  - 聚合 player/chart/db/crawler 四类概览数据
- `CrawlerTaskService`
  - 子进程任务编排、日志落盘、任务状态追踪
- `DBMaintenanceService`
  - DB 健康检查（page/freelist/quick_check）
  - `ANALYZE` / `VACUUM` 执行与审计历史
- `QualityService`
  - 规则检查、评分、趋势、报告持久化（`logs/quality_reports.json`）
- `PluginService`
  - 内置插件注册与运行（当前内置 quality snapshot、db health probe）
- `OfficialAPIService`
  - 对 `https://api.mugzone.net/api` 的会话封装与 token 刷新

---

## 4. 数据与筛选模型

## 4.1 统一响应与模型

- `core/models.py` 提供：
  - `GameMode`、`ChartStatus` 枚举
  - `Player`、`ChartStats` 等 Pydantic 模型
  - 统一响应模型 `APIResponse`（`success/data/message/error/timestamp`）

## 4.2 筛选器 MCSelector

核心文件：`selector.py`

- 统一管理筛选条件：`players/difficulties/time_range/modes/statuses`
- 产出：
  - `build_player_sql_where()`
  - `build_chart_sql_where()`
- 被 API 路由、Service、CLI 多处复用，保证筛选语义一致

## 4.3 高级查询安全边界

核心文件：`utils/query_builder.py`

- 表白名单：`SafeQueryBuilder.ALLOWED_TABLES`
- 字段名正则校验
- 操作符白名单：`=, !=, >, <, >=, <=, LIKE, IN, BETWEEN, IS NULL, IS NOT NULL`
- 通过 `AdvancedQueryService` 对外提供受控查询能力

---

## 5. 爬虫与调度子系统

## 5.1 三类主爬虫

- `malody_rankings.py`
  - 排行榜主爬虫，含 `--ranking-source page/newapi`、MM/MMR 同步相关参数
- `player_profile_crawler.py`
  - 玩家主页资料爬取，支持 uid/list/range/file/from-db/from-leaderboard
  - 支持全局限速、断点恢复（`global_progress.bin`）
- `stb_crawler.py`
  - 谱面/歌曲数据采集，支持 source、CID/SID 两种扫描、失败重试与进度文件

## 5.2 API 任务化调度

`/crawler/run` 由 `CrawlerTaskService` 以子进程方式启动爬虫：

- 每个任务拥有 `task_id`、`status`、`pid`、`started_at/ended_at`、`log_file`
- 日志落地 `logs/crawler_tasks/`
- 元数据落地 `logs/crawler_tasks/tasks.json`

## 5.3 控制器（非 API 主链）

`crawler_controller.py` 提供额外编排能力：

- 本地命令触发
- daemon 管理（start/stop/list）
- 邮件指令接入与报告回传（依赖 `config.yaml`）
- 参数 preset 展开

---

## 6. CLI 子系统（stats_cli）

## 6.1 入口与机制

- 入口：`stats_cli/app.py`（兼容入口 `malody_stats.py`）
- 框架：`cmd.Cmd`
- 插件注入：`stats_cli/plugins/registry.py`

`install_plugins(...)` 会把大量命令动态挂到 `MalodyViz`，例如：

- 数据更新：`update`
- 导出：`export`
- 趋势/对比/搜索/修复等命令
- STB 专项命令

## 6.2 关键能力拆分

- `utils/stats_update_runner.py`
  - 定义更新参数白名单与类型规则
  - 将 CLI 输入映射为爬虫实际命令（含范围参数转换）
- `utils/stats_export_runner.py`
  - 统一导出参数解析（type/mode/limit/players/time-range/format）
  - 支持 `csv/xlsx`、可选 metadata/summary
- `utils/stats_xlsx_formatter.py`
  - 自动列宽、行高、变化列条件格式

---

## 7. Desktop 子系统（Tauri + React）

## 7.1 后端进程托管

文件：`desktop/src-tauri/src/main.rs`

- App 启动时自动检测项目根目录并 spawn `python run.py`
- 强制本地监听：
  - `MALODY_API_HOST=127.0.0.1`
  - `MALODY_API_PORT=18765`
- 关闭窗口时 kill 子进程
- 后端日志：`logs/gui_backend.log`

## 7.2 前端结构

文件：`desktop/src/App.tsx` + `desktop/src/api.ts`

- API 基址固定：`http://127.0.0.1:18765`
- React Query 负责数据请求与缓存
- Ant Design + ECharts 做展示
- i18n：中英文双语字典（`desktop/src/i18n.ts`）
- 页面能力覆盖：
  - Overview
  - Analytics
  - Crawler Control
  - Data Quality
  - DB Maintenance
  - Plugins
  - Query & Export

---

## 8. 运维、脚本与质量保障

## 8.1 关键脚本

- `scripts/run_pre_merge_gate.ps1`
  - Gate1：`unittest`
  - Gate2：`compileall`
  - Gate3：`check_stats_api_consistency.py`
- `scripts/check_stats_api_consistency.py`
  - 对比 DB 基线与 API 输出一致性
- `start_gui.ps1`
  - 一键启动 desktop（可选自动 `npm install`）

## 8.2 测试覆盖概况

`tests/` 当前 31 个文件，覆盖：

- API 路由（players/charts/analytics/crawler/quality/plugins/official/system/query）
- 核心服务（chart_service/player_service/dashboard）
- CLI 参数边界与回归场景
- 导出与格式化逻辑
- selector 与兼容导入链路

---

## 9. 配置与环境变量

## 9.1 API 服务

- `MALODY_DB_PATH`
- `MALODY_API_HOST`
- `MALODY_API_PORT`
- `MALODY_DEBUG`
- `MALODY_LOG_LEVEL`
- `MALODY_ALLOWED_ORIGINS`
- `MALODY_API_KEY` / `MALODY_API_TOKEN`（敏感接口鉴权）

## 9.2 Desktop

- `MALODY_PROJECT_DIR`
- `MALODY_API_PYTHON`

## 9.3 控制器与邮件（crawler_controller）

- 可从 `config.yaml` + 环境变量覆盖读取 SMTP/IMAP 凭据等

---

## 10. 关键数据流（端到端）

## 10.1 采集到查询

1. 爬虫脚本抓取外部站点/API数据  
2. 写入 `malody_rankings.db`  
3. FastAPI Service 层按 selector 组装 SQL  
4. Router 统一封装 `APIResponse` 返回

## 10.2 任务化运维流

1. `/crawler/run` 发起任务  
2. `CrawlerTaskService` 生成 task + 日志文件  
3. `/crawler/tasks` 与 `/crawler/tasks/{id}/log` 追踪执行态  
4. Desktop/CLI 展示并形成操作闭环

## 10.3 导出流

1. Query/Chart API 或 CLI export 触发  
2. pandas DataFrame 生成结果  
3. CSV/XLSX 输出（XLSX 自动格式化）

---

## 11. 当前已识别风险与注意事项

1. `routers/crawler.py` 中 `_collect_data_source_health()` 已构造 `data` 但未显式 `return data`，会影响 `/crawler/status` 的 `data_source_health` 结构完整性。  
2. API Key 鉴权是“可选启用”策略：若未配置 `MALODY_API_KEY/MALODY_API_TOKEN`，受保护路由将放行，部署时需明确安全基线。  
3. 爬虫与 `official-api` 子系统对外部站点结构与鉴权状态敏感，建议结合 `docs/OPERATIONS_RUNBOOK.md` 做常态化巡检。  
4. 项目中存在体积较大的本地数据库与日志文件，建议在 CI 与开发环境中区分数据目录策略。

---

## 12. 新成员快速上手建议

1. 先启动 API：`python run.py`，确认 `/docs` 可访问  
2. 读 `routers/*` + 对应 `core/services/*` 建立“接口到 SQL”映射  
3. 跑 `scripts/run_pre_merge_gate.ps1` 了解回归门禁  
4. 需要可视化时再进入 `desktop/` 运行 `npm run tauri:dev`  
5. 需要批量运维或离线分析时使用 `stats_cli`
