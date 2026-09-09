# 项目重命名与前端重写

## 当前状态

- 产品身份已统一为 `Malody Data Studio` / `Malody 数据工作台`。
- Desktop 前端已从单体 `App.tsx` 拆分为应用壳、导航、共享类型/工具和页面模块。
- API、Python 导入命名空间、环境变量和数据库文件保持兼容。
- GitHub 远程仓库重命名仍需在仓库托管平台完成；代码侧已按新仓库名更新文档。

## 前端目标结构

```text
desktop/src/
├── app/              # AppShell、导航和应用级配置
├── pages/            # overview、analytics、tasks、crawler、quality、db、plugins、query
├── shared/           # API 边界、类型、错误处理、导出和查询模板
└── i18n.ts           # 当前双语字典，后续可按领域继续拆分
```

页面只在被选中时创建，因此非当前页面不会在启动时发起请求。任务和日志页面使用 React Query 轮询，并在组件卸载时停止。

## 迁移原则

1. 前端重写期间不同时修改后端接口契约。
2. API wire format 保持现有字段名；类型转换集中在 `shared/api` 边界。
3. 页面级错误提供简短摘要，并保留可展开的技术细节。
4. 每个页面迁移后必须有组件测试、构建证据和手工验收记录。

## 验收命令

```powershell
cd desktop
npm ci
npm test
npm run build
cargo check --manifest-path src-tauri/Cargo.toml
```

后端继续执行仓库现有的 Python 单元测试、编译检查和一致性门禁。
