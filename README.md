# NAS File Center v0.2

面向几十 TB NAS 数据的**中文 Web 文件批处理与精确去重中心**。

核心原则：**fclones 负责高性能重复发现；NAS File Center 负责规则、Dry Run、SHA256 二次校验、安全执行、审计和可视化操作。** fclones 永远不会被调用 `remove/link/dedupe` 等破坏性子命令。

## v0.2 重点

- 全中文 Web 管理界面，不再依赖 Swagger 完成日常操作
- 本地打包 Bootstrap 5 + Bootstrap Icons，**运行时不访问外部 CDN**，适合国内 / 局域网 NAS
- Dashboard：索引量、重复组、预计可释放空间、最近扫描 / Worker 状态
- 扫描去重：直接创建 fclones 扫描、查看重复组、生成去重计划
- 去重策略：
  - 多根目录均衡保留 `balanced-roots`
  - 保留最新 `keep-newest`
  - 保留最旧 `keep-oldest`
  - 优先第一个根目录 `keep-first-root`
  - 完整路径优先级 `path-priority`
  - 相对路径优先级 `relative-path-preference`
- 执行计划：Dry Run → Freeze → Validate → Execute
- 批量重命名：正则、前后缀、编号、父目录拼接，左右预览
- 批量处理：隔离、touch、移动、重命名，统一先生成计划
- 路径匹配：相对路径 / basename / stem / 正则归一化路径
- 增量文件索引
- 少女映画 Organizer：按实际内容重算 P/V/大小并清理旧统计尾巴，保留 `[存疑]`
- Worker 任务中心和审计日志
- 安全设置页面只展示状态；危险开关不能从网页一键开启
- **ZFS 大 inode 修复**：支持真实观察到的 inode `12164156718799206349`，不再触发 `Python int too large to convert to SQLite INTEGER`

## 1. 你当前极空间 + Komodo 推荐 Compose

项目里已经附带：

```text
compose.komodo.yaml
```

它按当前环境配置为：

```text
镜像：kerwinjhc/nas-file-center:latest
Web：8089 -> 8080
配置：/tmp/zfsv3/nvme13/15246330601/data/NasFileCenter
数据：/tmp/zfsv3/sata11/15246330601/data -> /data:ro
网络：nginx_network
```

默认仍然是三重安全状态：

```text
/data:ro
ALLOW_MUTATION=false
ALLOW_DELETE=false
```

部署后访问：

- Web UI: `http://NAS-IP:8089/`
- Health: `http://NAS-IP:8089/health`
- Swagger（高级/调试）: `http://NAS-IP:8089/docs`

## 2. 从 v0.1 升级

在 Mac 项目目录重新构建并推送：

```bash
docker buildx build \
  --platform linux/amd64 \
  -t kerwinjhc/nas-file-center:latest \
  --push \
  .
```

然后在 Komodo 对 NasFileCenter Stack 执行 **Pull / Redeploy**。

现有 `/config/app.db` 可以继续使用。v0.2 对 ZFS `st_dev/st_ino` 使用带前缀的十六进制文本绑定，即使旧 SQLite 数据库对应列仍具有 INTEGER affinity，也不会把大 unsigned inode 强制转成 REAL 丢失精度。

之前因为大 inode 失败的扫描任务可以保留作为历史记录，升级后重新创建扫描即可。

## 3. 推荐使用顺序

### A. 文件索引

打开左侧 **文件索引**：

1. 填 `/data/Download` 或更具体的目录
2. 点击“加入索引队列”
3. 在 **任务中心** 查看状态

同一根目录后续重新索引会更新变化项并清除 stale 项。

### B. 精确查重

打开 **扫描去重**：

- 单目录内部查重：只填一个根目录，关闭 isolate
- A/B 跨目录查重：每行一个根目录，开启 isolate

示例：

```text
/data/NasFileCenterTest_20260902/A
/data/NasFileCenterTest_20260902/B
```

完成后进入扫描详情，可以展开重复组，并直接选择“均衡保留 / 最新 / 最旧 / 路径优先”等策略生成 Dry Run 计划。

### C. 计划生命周期

所有文件修改统一走：

```text
创建计划
  ↓
Freeze
  ↓
Validate（去重时重新 streaming SHA256）
  ↓
Execute
```

在默认只读模式下，Execute 按钮会被 UI 禁用；后端安全检查仍然存在，UI 不能绕过。

## 4. 开启隔离执行

只有当 Dry Run 和 Validate 都确认正确后，再改 Compose：

```yaml
- /tmp/zfsv3/sata11/15246330601/data:/data:rw
```

以及：

```yaml
- ALLOW_MUTATION=true
- ALLOW_DELETE=false
```

Redeploy 后，精确去重默认仍是 **quarantine 隔离**，不会直接 unlink。隔离目录默认：

```text
/data/.nas-file-center-trash/<plan-id>/...
```

## 5. 永久删除

永久 unlink 额外要求：

```yaml
- ALLOW_MUTATION=true
- ALLOW_DELETE=true
```

UI v0.2 不主动生成永久删除计划。推荐几十 TB 正式数据长期使用隔离模式。

## 6. 批量重命名

打开 **批量重命名**，每行输入一个文件或目录，可组合：

- 正则查找 / 替换
- 前缀 / 后缀
- 自动编号、补零
- 拼接父目录名

页面会先显示 `原路径 → 新路径`，确认后才生成计划。

## 7. 批量处理

打开 **批量处理**：

- 隔离：每行一个源路径
- touch：每行一个路径
- move / rename：每行使用 `源 -> 目标`

同样只创建 Dry Run 计划。

## 8. 少女映画 Organizer

打开 **Organizer**，输入：

```text
/data/Download/少女映画/百度网盘1（更新）
```

会按真实文件重新统计 P/V/大小，清除已有统计后缀并生成目录改名预览，业务标记如 `[存疑]` 会保留。

## 9. 几十 TB 使用建议

- 第一次扫描先从小目录验证，再逐步扩大
- 正式数据长期保持 fclones cache 和 SQLite `/config` 持久化
- HDD 大规模扫描不要频繁中断；Worker 与 Web API 分离，浏览器关闭不会停止后台任务
- 路径匹配优先先建立增量索引，避免每次重新遍历整棵树
- 删除前保持 quarantine；不要为了省一步直接开启永久 unlink
- 定期备份 `/config/app.db`，它包含索引、计划和审计历史

## 10. 开发验证

```bash
PYTHONPATH=. python -m pytest -q
python -m compileall -q app
```

项目继续保留完整 JSON API；Web UI 是建立在同一 `FileCenterService` 安全层之上的浏览器操作面。
