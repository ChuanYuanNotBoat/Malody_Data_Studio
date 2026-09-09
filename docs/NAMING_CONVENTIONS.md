# Malody Data Studio 命名规范

## 1. 统一身份

| 层级 | 规范值 | 说明 |
| --- | --- | --- |
| 产品名 | `Malody Data Studio` | 面向用户的英文名称 |
| 中文名 | `Malody 数据工作台` | 文档和界面中文名称 |
| Git 仓库 | `malody-data-studio` | GitHub 仓库名，使用 kebab-case |
| Desktop 包 | `malody-data-studio-desktop` | npm/Cargo 包名 |
| Python 导入包 | `malody_api` | 现阶段保留，作为兼容命名空间 |
| 环境变量前缀 | `MALODY_` | 已被部署和脚本使用，暂不改名 |
| SQLite 文件 | `malody_rankings.db` | 数据资产名称，暂不改名 |

## 2. 代码命名

- Python 文件、函数和变量使用 `snake_case`；类使用 `PascalCase`；常量使用 `UPPER_SNAKE_CASE`。
- React 组件使用 `PascalCase`；hooks 使用 `useXxx`；普通函数和变量使用 `camelCase`。
- 前端目录按职责使用小写目录名，例如 `pages/`, `features/`, `shared/`。
- API 路由使用小写资源名；已有的 `snake_case` 响应字段保持不变，避免破坏 CLI 和外部调用方。
- API 查询键使用资源分段形式，例如 `["crawler-tasks"]`、`["quality-job", jobId]`。

## 3. 兼容性规则

仓库重命名、产品改名和 Python 导入包改名是三个不同的迁移。首阶段只改产品和仓库身份：

1. 保留 `malody_api` 导入路径。
2. 保留 `MALODY_*` 环境变量。
3. 保留 `malody_rankings.db` 及其表结构名称。
4. Tauri 已发布版本继续使用 `net.malody.desktop` identifier，避免自动更新链断裂。
5. 如未来引入 `malody_data_studio` Python 命名空间，应提供旧路径转发层，并在至少一个主版本周期后再移除旧路径。

## 4. 重命名检查清单

- GitHub 仓库名和本地 `origin` URL。
- README、项目上下文、桌面端 README 和克隆命令。
- npm `package.json`、`package-lock.json`。
- Tauri `productName`/窗口标题；identifier 需要按兼容策略单独处理。
- Cargo 包名和描述。
- Tauri 项目根目录探测逻辑，不能依赖固定仓库目录名。
- GitHub Actions 的工作目录、缓存键和触发路径。
- 测试中的产品标题和路径断言。
