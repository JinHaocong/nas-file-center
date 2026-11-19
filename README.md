# NAS File Center v1.4.6

> **说明**：当前版本为 **NAS File Center v1.4.6**，在既有 NAS 安全执行与 Worker 体系上集成媒体资源包整理、每个 P/V 分组独立从 001 编号、普通文件重名自动避让、原路径映射及恢复保护。真实存储设备上的正式执行仍应先进行小范围兼容性验收。

面向几十 TB NAS 数据的**中文 Web 文件批处理与精确去重中心**。

> **版本权威**：当前产品 / Python package / Docker image 版本统一为 **1.4.6**。
> **v1.4.6 修复**：冻结清单校验信息更明确，防止 WorkJob ID 重用导致历史报告碰撞；预览报告禁止覆盖，并新增只读恢复证据排查工具。
> **v1.4.5 修复**：已有 P/V 数量大小分组中的文件参与统一扫描和安全重组；仅在完整冻结校验与暂存成功后清理已证实为空的旧分组目录，保留 FUSE 安全发布、禁止覆盖和中断恢复保护.
>
> **MediaPackage 报告安全排查**：冻结清单失败原因细分、旧报告任务 ID 防撞、只读检查命令与保留策略见 [媒体包报告与恢复安全说明](docs/media-package-report-safety.md)。
>
> 当前开发顺序以 [`docs/roadmap-current.md`](docs/roadmap-current.md) 为准；旧 roadmap 仅作历史证据。

核心原则：**fclones 负责高性能重复发现；NAS File Center 负责规则、Dry Run、SHA256 二次校验、安全执行、审计和可视化操作。** fclones 永远不会被调用 `remove/link/dedupe` 等破坏性子命令。

---

## v0.4.7 历史功能亮点（延续至 v1.4.6）

> **新增只读功能（实现 PR #261，须待 CI / NAS 验收）：** OpenList WebDAV → NAS 下载完整性校验，原始目录结构严格匹配，双端完整 SHA256，支持后台 Worker 与分页差异报告。默认禁用；凭据必须由运维通过只读 secret 文件部署。配置与限制见 [WebDAV 下载完整性校验](docs/webdav-download-verification.md)。

### v0.4.7 UI / Responsive

- 项目拥有独立的 `/DESIGN.md`，视觉方向以 Linear / Supabase 的克制 surface、hairline hierarchy 为主，并吸收 Carbon 的高密度数据与状态表达。
- Dashboard、Task Center、Plans、Scans、Advanced Dedupe、Quarantine、Audit、Indexes、Workflows、Organizer、Batch、Path Match、Rename、Settings、Login 与各类 Modal/Drawer 已迁移到统一视觉系统。
- Desktop / Tablet / Mobile 使用统一响应式合同；数据密集页面在移动端使用专用 card/list 视图，不再强行压缩宽表格。
- Light / Dark / System 主题继续支持；安全状态、Worker 状态、Plan 生命周期与危险操作门禁保持可见。
- 前端 release regression：438 / 438 tests PASS、TypeScript typecheck PASS、production build PASS。
- Runtime dependency audit：0 vulnerabilities。
- Release Docker image 已在 CI 完成 linux/amd64 构建验证；正式 Docker Hub 推送与 Komodo/NAS 部署由发布者在 merge 后执行。


1. **Organizer Profile 通用化体系 (v0.3.2-step2)**：
   - 全面支持通用整理方案（Organizer Profiles）的**创建、编辑、克隆、删除、导入、导出、只读预览与生成执行计划**。
   - **强大模板引擎**：支持 `{name}`, `{index}`, `{images}`, `{videos}`, `{files}`, `{folders}`, `{size}`, `{statistics}` 及 `{?videos: {videos}V}` 条件语法，前台提供实时渲染示例。
   - **安全冲突检测与只读预览**：支持流式大目录分页，只读阶段绝不写盘，自动检测目标冲突、磁盘同名与路径越界。
2. **可视化目录选择体系 (v0.3.2-step1)**：
   - 全局接入现代化 **DirectoryPicker** 目录选择弹窗组件，彻底替换所有业务表单的手动绝对路径输入。
   - **有界堆内存流式分页**：文件系统浏览基于 `heapq` 有界候选堆，彻底消除百千目录下的内存暴涨风险。
   - **真·自然排序 (Natural Sort)**：目录与文件均按自然数字序排列（如 `folder1 < folder2 < folder10`）。
   - **路径收藏与最近使用记录**：常用目录一键星标置顶，支持按用户隔离；最近使用路径自动记录与本地时区格式化显示。
   - **严密白名单与路径穿越防御**：严格校验 `ALLOWED_ROOTS` 白名单边界，禁止符号链接越界访问与路径穿越。

1. **全新现代化企业级 Web 管理界面**：
   - 升级为 **React + TypeScript + Vite + Ant Design 5** 架构，取代旧版 Bootstrap 页面。
   - 包含 Dashboard 概览、文件索引、扫描去重、跨目录路径匹配、批量重命名、批量处理、Organizer 智能整理、执行计划、任务中心、审计日志与系统设置。
   - 本地全量静态打包，**运行时严禁访问任何外部 CDN**，完全适配局域网 / 私有 NAS。
2. **本地管理员认证与 Session 会话安全**：
   - **Argon2id** 安全密码哈希算法。
   - **HttpOnly + SameSite=Lax + Secure** Cookie 会话存储，服务端 SQLite 仅保存 Token SHA256 哈希，禁止将认证 Token 存入 localStorage。
   - 支持防暴力破解频控锁定（15分钟5次失败限制）、CSRF/Origin 严格同源校验、修改密码自动吊销其他设备、多设备会话管理。
   - 环境变量初始化：支持 `INITIAL_ADMIN_USERNAME` 与 `INITIAL_ADMIN_PASSWORD`，一旦数据库存在任何用户后永久忽略该环境变量，避免重启被覆盖。
3. **视觉与主题体验**：
   - 内置定制设计 NAS Favicon（SVG / ICO）与 Apple Touch Icon。
   - 动态路由网页标题跟随。
   - 完整支持 **浅色 (Light) / 深色 (Dark) / 跟随系统 (System)** 主题一键切换。
4. **数据库自动备份与无损平滑迁移**：
   - 无论 API 还是 Worker 谁先启动，在执行任何 schema mutation 前均自动备份原 SQLite 数据库至 `/config/backups/nas-file-center-YYYYMMDD-HHMMSS.db`。
   - 完美兼容 v0.2 原有数据，**绝不要求删除已有数据库**。
   - 100% 保留 ZFS 大 inode (`12164156718799206349`) 防溢出修复与只读安全防御机制。

---

## 1. 部署架构与配置 (Zoraxy + Komodo Stack)

### 推荐生产部署网络拓扑
```text
用户浏览器 (HTTPS)
   ↓
https://file.kerwin.cloud
   ↓
Zoraxy 反向代理 (SSL Termination)
   ↓ (Docker 内部网络 nginx_network)
nas-file-center-api:8080 (容器内 HTTP 端口，禁止直接映射宿主机端口)
```

### `compose.komodo.yaml`（Komodo 部署模板）

使用仓库中的 [compose.komodo.yaml](compose.komodo.yaml)，避免复制与当前分支不一致的配置片段。
**当前 V1.6 开发分支的权限模板不能直接覆盖运行中的 1.4.6 配置。** 镜像版本尚未发布为 V1.6；
候选验证需要已审查的镜像摘要、独立配置副本、维护窗口及回滚方案，见
[NAS 验证与配置备份流程](docs/real-nas-acceptance.md#configuration-backup-candidate-validation-and-rollback-403)。

在 Komodo Stack 的环境变量中提供宿主机路径，真实值保存在私有 Variables 中，例如：

```dotenv
HOST_CONFIG_DIR=[[NFC_CONFIG_HOST]]
HOST_DATA_DIR=[[NFC_DATA_HOST]]
```

`HOST_CONFIG_DIR` 与 `HOST_DATA_DIR` 必须互不嵌套且不是同一目录，避免通过可写配置挂载访问媒体。
模板保留 `/config/app.db` 和 `/quarantine/.nas-file-center-trash` 容器路径。默认隔离区源为
`HOST_CONFIG_DIR/.nas-file-center-trash`，API 在隔离区路径及 `/config` 下的同一目录入口均使用只读挂载，
Worker 使用可写挂载。所有绑定源必须事先存在；模板不会自动创建错误路径。
跨存储覆盖文件中的 `HOST_QUARANTINE_DIR` 仍表示隔离区的**父目录**。自定义嵌套位置需要单独核实
所有可写路径入口，不能仅依赖一个只读挂载。不要重写已有隔离记录的绝对路径来适配新模板。

API / Worker 默认 UID 为 `10001` / `10002`，共享 GID 为 `10000`。现有配置目录、SQLite WAL/SHM、
报告和密码共享卷必须按候选验证流程确认兼容，不进行递归权限修复。
`MEDIA_PACKAGE_ROOT`、`MEDIA_PACKAGE_FUSE_COMPAT_ENABLED` 和管理员配置继续由 Komodo Variables 提供。
HTTPS 反向代理仍使用 `nginx_network` 和 `SESSION_COOKIE_SECURE=true`，不暴露宿主机端口。

V1.6 的执行开关及命名空间确认开关保持 `false`。API 媒体挂载为只读；Worker 的写挂载服务于已授权任务，
不能替代真实 NAS 的 ACL、SMB 并发写入控制或正式验收。

---

> **Worker 任务中断/重启排查：** 任务提示 `Worker restarted while job was running`
> 不代表 Docker 必然重启，也可能是 SQLite 写锁争用或 Worker 租约失效。
> 查看 [Worker 心跳、重启与 NAS 排障手册](docs/worker-restart-diagnosis.md)，
> 包含 Komodo/Docker Inspect、OOM、数据库写锁与恢复建议。
>
## 2. 升级到 v1.4.6

1. 在构建机器构建 `linux/amd64` 镜像并推送：
   ```bash
   docker buildx build \
     --platform linux/amd64 \
     -t kerwinjhc/nas-file-center:1.4.6 \
     --push \
     .
   ```
2. 在 Komodo / NAS 环境变量中配置管理员账号密码：
   - `INITIAL_ADMIN_USERNAME=admin`
   - `INITIAL_ADMIN_PASSWORD=YourSecurePassword123!`
3. 在 Komodo / NAS 管理后台对 NasFileCenter 服务执行 **Pull / Redeploy**。
4. 容器启动时会自动：
   - 检查 `/config/app.db` 是否存在；
   - 若存在旧版数据，自动在变更前备份至 `/config/backups/nas-file-center-*.db`；
   - 自动增量迁移创建 `users` 与 `sessions` 表；
   - 使用您提供的初始账号密码创建管理员（若未配置环境变量，禁止自动创建弱口令）。
5. 打开域名访问 `https://file.kerwin.cloud`：
   - 系统自动跳转至 `/login` 登录页；
   - 输入管理员账号密码即可安全登录并使用全新 React Ant Design 5 界面。

---

## 3. 功能操作指南

### A. 概览与状态指示
- 顶部导航栏直观显示 **只读安全模式 / 写入模式** 徽标与 **Worker 活跃状态**。
- 支持一键切换浅色 / 深色 / 系统跟随主题，并提供修改管理员密码与安全登出入口。

### B. 文件索引与路径匹配
- **文件索引**：对几十 TB 存储目录建立轻量增量 SQLite 索引，秒级检索文件。
- **路径匹配**：支持跨目录相对路径、文件名、去除后缀主名或正则表达式归一化匹配，直接从 `members[].path` 生成去重计划。

### C. 精确扫描与去重计划
- **新建扫描**：直接调用 Rust fclones 原生引擎，支持普通全量扫描与 A/B 跨目录隔离扫描。
- **去重策略**：支持多根目录均衡保留 (`balanced-roots`)、最新 (`keep-newest`)、最旧 (`keep-oldest`)、首根目录优先、完整路径优先级与相对路径优先级。
- **严格计划生命周期**：
  `Draft (草稿)` → `Freeze (冻结不可变)` → `Validate (实时 SHA256 二次校验)` → `Ready (已就绪)` → `Execute (安全执行)`。
  - **禁止未校验直接执行**：Draft 与 Frozen 状态禁止 Execute，必须先通过 Validate 达到 Ready 状态方可执行。
  - 在只读安全模式下（`ALLOW_MUTATION=false`），执行按钮物理锁定。

### D. 批量重命名与批量处理
- **批量重命名**：提供正则表达式、前后缀、编号补零、父目录名拼接，后端逐项比对 `conflict` 与 `conflict_reason`，存在重名冲突时禁止生成计划。
- **批量处理**：支持隔离 (`quarantine`)、`touch` 更新时间戳、跨目录移动与改名。

### E. Organizer 智能整理
- 深度识别照片/视频文件，按用户自定义 Profile 模板精确重算容量及媒体数量统计后缀并清除历史冗余尾巴，准确比对 `changed` 状态生成改名计划。

### F. 隔离区核心与安全加固 (Quarantine Core & Hardening, v0.3.4-Gate1-hotfix1)
- **原子级防覆盖移动与恢复**：采用底层系统调用 `renameat2(RENAME_NOREPLACE)` (Linux) 与 `renamex_np(RENAME_EXCL)` (macOS)，物理杜绝隔离与恢复阶段由于并发竞争或意外同名覆盖现有业务文件。
- **符号链接攻击严密防御**：在解析前进行词法检查，禁止针对符号链接条目的危险清除，确保符号链接所指受害者文件在任何情况下绝对不受影响。
- **缺失目标安全闭环 (Fail-Closed)**：清除时若磁盘目标缺失，立即转为 `inconsistent` 异常状态并返回 HTTP 409 状态冲突，严禁返回伪成功。
- **目录隔离、恢复与清理**：完整支持目录树隔离（`content_hash=None`）、目录树原子还原（默认跳过冲突）以及非跟随符号链接的安全物理清理。
- **服务启动自动对齐与崩溃恢复**：服务启动时独立事务对齐 `preparing`、`restoring` 和 `purging` 过渡态，确保异常断电或崩溃重启后数据自洽。
- **保留根目录边界防护**：文件索引、fclones 扫描去重及 Organizer 统计均严密排除并剪枝隔离区目录，杜绝隔离内容被二次索引或去重误伤。
- **外键关联与审计追踪**：`QuarantineEntry.task_id` 建立外键索引关联 `work_jobs.id`，具备完整的批处理任务溯源能力。

---

## 4. 开发与本地测试验证

### 自动化测试
```bash
# 运行全部后端安全与业务测试
PYTHONPATH=. pytest -v

# 检查前端类型定义 (0 errors)
cd frontend && npm run typecheck

# 构建前端生产产物 (0 errors)
npm run build
```

### Docker 容器构建验证
```bash
docker buildx build \
  --platform linux/amd64 \
  -t nas-file-center:0.4.7 \
  --load \
  .
```


## Archive file recovery (experimental, administrator-only)

The **压缩包恢复** tool supports best-effort ZIP / TAR / 7z / RAR file salvage with a same-directory unique result folder; original archives are left untouched. ZIP CRC and full image decode are distinguished from unverified extraction. The existing Worker/Task Center handles recovery jobs and cancellation. Defaults remain read-only: the archive parent must be explicitly writable and `ALLOW_MUTATION=true`.

Read [archive recovery deployment, supported formats, limits and known security boundaries](docs/archive-recovery.md) before enabling this feature. Password-protected archives additionally require a shared tmpfs mount, with optional [Compose](compose.archive-recovery-secrets.yaml) or [Komodo](compose.komodo.archive-recovery-secrets.yaml) overlay. No generic damaged encrypted solid-stream recovery is claimed.


Experimental AES-256-CBC + LZMA2 7z deep recovery is available for **intact, CRC-checked metadata** with independently decodable reset points and CRC-verifiable complete files; see [supported boundaries and limits](docs/archive-recovery.md#experimental-aes-256-cbc--lzma2-7z-deep-recovery). It does not reconstruct arbitrary encrypted solid streams.
