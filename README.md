# NAS File Center v0.3.1

面向几十 TB NAS 数据的**中文 Web 文件批处理与精确去重中心**。

核心原则：**fclones 负责高性能重复发现；NAS File Center 负责规则、Dry Run、SHA256 二次校验、安全执行、审计和可视化操作。** fclones 永远不会被调用 `remove/link/dedupe` 等破坏性子命令。

---

## v0.3.1 核心更新与亮点

1. **全新现代化企业级 Web 管理界面**：
   - 升级为 **React + TypeScript + Vite + Ant Design 5** 架构，取代旧版 Bootstrap 页面。
   - 包含 Dashboard 概览、文件索引、扫描去重、跨目录路径匹配、批量重命名、批量处理、少女映画 Organizer、执行计划、任务中心、审计日志与系统设置。
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

### `compose.komodo.yaml` (极空间 / Komodo Stack 推荐配置)

```yaml
services:
  nas-file-center-api:
    image: kerwinjhc/nas-file-center:latest
    container_name: nas-file-center-api
    volumes:
      - /tmp/zfsv3/nvme13/15246330601/data/NasFileCenter:/config
      - /tmp/zfsv3/sata11/15246330601/data:/data:ro
    networks:
      - nginx_network
    environment:
      - CONFIG_DIR=/config
      - DATA_MOUNT=/data
      - ALLOWED_ROOTS=/data
      - QUARANTINE_ROOT=/data/.nas-file-center-trash
      - ALLOW_MUTATION=false
      - ALLOW_DELETE=false
      - PROTECT_LAST_FILE=true
      - FCLONES_BINARY=/usr/local/bin/fclones
      - MTIME_REFRESH_DELAY_SECONDS=2
      - SESSION_COOKIE_SECURE=true
      - INITIAL_ADMIN_USERNAME=${INITIAL_ADMIN_USERNAME:-}
      - INITIAL_ADMIN_PASSWORD=${INITIAL_ADMIN_PASSWORD:-}
    healthcheck:
      test: ["CMD-SHELL", "python3 -c 'import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8080/health\")' || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 5s
    restart: unless-stopped

  nas-file-center-worker:
    image: kerwinjhc/nas-file-center:latest
    container_name: nas-file-center-worker
    command:
      - python
      - -m
      - app.worker
    volumes:
      - /tmp/zfsv3/nvme13/15246330601/data/NasFileCenter:/config
      - /tmp/zfsv3/sata11/15246330601/data:/data:ro
    networks:
      - nginx_network
    environment:
      - CONFIG_DIR=/config
      - DATA_MOUNT=/data
      - ALLOWED_ROOTS=/data
      - QUARANTINE_ROOT=/data/.nas-file-center-trash
      - ALLOW_MUTATION=false
      - ALLOW_DELETE=false
      - PROTECT_LAST_FILE=true
      - FCLONES_BINARY=/usr/local/bin/fclones
      - MTIME_REFRESH_DELAY_SECONDS=2
    depends_on:
      nas-file-center-api:
        condition: service_healthy
    restart: unless-stopped

networks:
  nginx_network:
    external: true
```

默认三重安全状态：
- `/data:ro` (只读挂载)
- `ALLOW_MUTATION=false`
- `ALLOW_DELETE=false`

---

## 2. 从 v0.2 升级到 v0.3.1 步骤

1. 在构建机器构建 `linux/amd64` 镜像并推送：
   ```bash
   docker buildx build \
     --platform linux/amd64 \
     -t kerwinjhc/nas-file-center:latest \
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

### E. 少女映画 Organizer
- 深度识别照片/视频文件，按实际内容精确重算 `[P V GB]` 统计后缀并清除冗余历史尾巴，智能保留 `[存疑]` 等关键业务标记，准确比对 `changed` 状态生成改名计划。

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
  -t nas-file-center:v0.3.1-fixed2 \
  --load \
  .
```
