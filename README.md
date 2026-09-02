# NAS File Center

面向几十 TB NAS 数据的批量文件整理与精确去重中心。

核心原则：**fclones 负责高性能重复发现；本项目负责规则、Dry Run、SHA256 二次校验、安全执行和审计。** fclones 永远不会被调用 `remove/link/dedupe` 等破坏性子命令。

## V1 已实现

- fclones 持久 Hash Cache 的精确查重
- 普通多根目录扫描 / isolate 跨根目录查重
- SQLite 持久扫描任务 + 单 worker 串行执行
- 容器重启后把 running worker 任务恢复为 queued
- 重复组导入 SQLite
- 去重保留策略：
  - `keep-first-root`
  - `keep-newest`
  - `keep-oldest`
  - `balanced-roots`
  - `path-priority`
  - `relative-path-preference`
- Freeze -> SHA256 Validate -> Execute 生命周期
- 默认隔离删除（quarantine），不是永久 unlink
- 永久删除双开关：`DATA_MODE=rw` + `ALLOW_MUTATION=true`，且 unlink 还必须 `ALLOW_DELETE=true`
- 一级目录最后一个文件保护
- 批量重命名 Dry Run：正则、前缀、后缀、编号补零、拼接父目录名
- 文件树统计模板：图片数、视频数、文件数、目录数、总大小
- 持久增量路径索引
- 按相对路径 / basename / stem / 正则归一化路径匹配
- 少女映画 Profile：清理旧 `[P/V/Size]`、保留 `[存疑]`、按实际文件重算 P/V/大小、生成有顺序的 mtime touch 计划
- SQLite 审计事件
- Swagger API

V2 暂不包括：近似图片去重、视频指纹/转码相似检测、EXIF 时间策略、hardlink/reflink、无人值守自动删除。

## 1. 极空间部署

把项目目录放到 NAS 上，例如：

```bash
cd /tmp/zfsv3/nvme13/你的用户目录/appdata
mkdir -p nas-file-center
cd nas-file-center
```

将本项目文件复制到该目录，然后：

```bash
cp config.example.env .env
```

编辑 `.env`，最关键的是：

```dotenv
HOST_DATA_DIR=/tmp/zfsv3/sata11/你的用户目录/data
HOST_CONFIG_DIR=/tmp/zfsv3/nvme13/你的用户目录/appdata/nas-file-center-config
```

第一次一定保持：

```dotenv
DATA_MODE=ro
ALLOW_MUTATION=false
ALLOW_DELETE=false
```

启动：

```bash
docker compose up -d --build
```

访问：

- Dashboard: `http://NAS-IP:8080/`
- Swagger: `http://NAS-IP:8080/docs`
- Health: `http://NAS-IP:8080/health`

## 2. 推荐首次使用流程

### A. 先建立增量路径索引

Swagger 调用：

`POST /api/indexes`

```json
{
  "root": "/data/Download"
}
```

返回 `work_job_id`，使用：

`GET /api/work-jobs/{id}`

查看状态。

索引用于批量路径查询/匹配。后续再次索引会更新变化文件并删除 stale 记录，不会把全部历史记录不断追加。

### B. 精确查重

`POST /api/scans`

同一个目录内部查重：

```json
{
  "name": "Download internal",
  "roots": ["/data/Download"],
  "isolate": false
}
```

A/B 两个目录只查跨目录重复：

```json
{
  "name": "A vs B",
  "roots": ["/data/A", "/data/B"],
  "isolate": true
}
```

扫描由 `worker` 容器执行。fclones 使用持久 cache，重复扫描未变化文件时可以大量复用已有 Hash。

查看：

`GET /api/scans/{scan_job_id}`

### C. 生成去重计划

例如均衡去重：

`POST /api/scans/{scan_job_id}/dedupe-plan`

```json
{
  "policy": "balanced-roots"
}
```

时间策略：

```json
{"policy":"keep-newest"}
```

路径优先：

```json
{
  "policy": "path-priority",
  "path_priority_patterns": [
    "*/整理完成/*",
    "*/原始/*",
    "*"
  ]
}
```

### D. Freeze 和 SHA256 Validate

```text
POST /api/plans/{plan_id}/freeze
POST /api/plans/{plan_id}/validate
```

`validate` 会对 dedupe 的保留文件和待处理文件重新做 streaming SHA256。只有校验通过的计划才进入 `ready`。

### E. Safe Mode 下先看结果

此时仍然是：

```dotenv
DATA_MODE=ro
ALLOW_MUTATION=false
```

即便误点 Execute，也不会修改文件。

## 3. 开启隔离执行

确认 Dry Run / Validate 正确后：

```dotenv
DATA_MODE=rw
ALLOW_MUTATION=true
ALLOW_DELETE=false
```

重建容器：

```bash
docker compose up -d
```

然后：

`POST /api/plans/{plan_id}/execute`

去重计划默认 operation 是 `quarantine`。文件会移动到：

```text
/data/.nas-file-center-trash/<plan-id>/root-N/原相对路径
```

因此第一次大规模处理建议始终使用隔离模式，不直接永久删除。

## 4. 永久删除

只有你明确要执行 `unlink` 计划时才需要：

```dotenv
DATA_MODE=rw
ALLOW_MUTATION=true
ALLOW_DELETE=true
```

精确去重默认仍然生成 quarantine，不会因为打开 `ALLOW_DELETE` 自动变成永久删除。

## 5. 批量重命名预览

`POST /api/rename/preview`

例如：

```json
{
  "paths": [
    "/data/test/foo 01.jpg",
    "/data/test/foo 02.jpg"
  ],
  "regex_pattern": "^foo ",
  "regex_replacement": "",
  "prefix": "PIC-",
  "number_start": 1,
  "number_width": 3,
  "include_parent": true
}
```

它只返回 source -> target，不直接改文件。

要执行时，把预览结果转成 `rename` Batch Plan，再经过 Freeze/Execute。

## 6. 路径匹配

少量目录可以直接：

`POST /api/path-match/preview`

几十 TB 数据更建议先建持久索引，然后调用：

`POST /api/index-match/preview`

支持：

- `relative-path`
- `basename`
- `stem`
- `normalized-relative-path`

`normalized-relative-path` 可以用正则消掉诸如 `001 `、`999 ` 这类编号后再比较路径。

注意：**路径匹配只是候选发现，不会单独授权删除。永久/隔离去重仍要求内容 Hash 验证。**

## 7. 少女映画 Profile

预览：

`POST /api/organizers/shaonv/preview`

```json
{
  "root": "/data/Download/少女映画/百度网盘1（更新）"
}
```

它会重新读取真实文件并生成例如：

```text
112 少女映画 银狼 [40P 2V 634.7MB]
```

重复旧统计块会被移除，语义块如 `[存疑]` 会保留。

底层统计/rename/touch 都是通用模块，少女映画只是 Profile，不会影响其他目录规则。

## 8. 大目录建议

几十 TB 首次查重一定会产生大量磁盘读取，这是无法避免的。后续 fclones `--cache` 会基于文件 metadata/inode 复用 Hash。建议：

- 默认让 fclones 自动识别 HDD/SSD 并调节并发
- 如果 NAS 日常还在使用，可设置较低 `FCLONES_THREADS`
- 先分根目录索引，不要一次对整个 `/data` 做所有路径操作
- exact dedupe 扫描和批量执行由单 worker 串行，避免同时把多个机械盘打满
- 第一次执行始终 quarantine
- 重要数据先有独立备份

## 9. 开发验证

```bash
python -m pytest -q
python -m compileall -q app
```

项目当前使用 SQLite WAL。`/config` 应放在 NAS 本机持久磁盘，不要放到不可靠的网络共享路径。

## 10. 安全边界

- fclones：只 discovery
- 扫描结果：不是删除授权
- Dedupe Plan：必须 Freeze
- Freeze 后：SHA256 Validate
- Execute：再次检查路径、symlink、size、hash、目录保护
- 默认删除：quarantine
- Permanent unlink：额外 `ALLOW_DELETE=true`
- 所有操作：写 audit event
