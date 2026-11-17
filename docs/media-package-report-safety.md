# MediaPackage 冻结清单与报告保留规则

> 本文仅针对媒体资源包整理。默认 **不会自动删除** `/config/reports` 下的任何报告。报告路径以私有 `CONFIG_DIR` 配置为准；不要把 NAS 的真实资源包路径提交到 GitHub。

## 为什么旧 `reports` 可能让新任务报错？

执行任务按 WorkJob ID 持久化冻结清单：

- 预览：`$CONFIG_DIR/reports/media_package-previews/<preview_id>.packages.jsonl`，还有 `.packages.idx`、`.summary.json`。
- 执行：`$CONFIG_DIR/reports/media_package-executions/<execution_id>/<ordinal:07d>.manifest.json`。

SQLite `INTEGER PRIMARY KEY` 在最高 ID 对应的任务行删除后，可能为新任务重用该 ID；但独立保存的报告不会随任务行删除。如果复用的执行 ID 与旧 `manifest.json` 撞号，新任务会错误地尝试加载旧清单，触发校验失败。这是一种可能的根因，不能在原清单已被删除时认定为已证实。

修复后，媒体包预览、执行和恢复任务在 SQLite `BEGIN IMMEDIATE` 事务中，联合检查数据库最大 ID、已有预览报告 ID 和执行报告目录 ID，分配更高的新 ID。新预览遇到同名旧报告会安全停止，**绝不先删除旧内容**。

## 失败时的明确原因

`Frozen manifest integrity mismatch` 现在会区分：

- `unreadable or invalid JSON`：文件损坏或内容不是有效 JSON。
- `invalid manifest envelope`：缺失有效的 `manifest` 对象。
- `SHA-256 checksum differs`：已存校验值与完整清单内容不一致。
- `schema version differs`：清单版本与当前 Worker 版本不一致。
- `execution job ID differs`：清单绑定的任务 ID 不一致。
- `package path differs from preview`：清单指向的资源包与原始预览不一致。

这些提示仅用于诊断；**不允许自动修复、重算覆盖 checksum、跳过校验或使用新的预览强行恢复已暂存文件**。

## 只读检查命令

在装有当前代码、挂载私有 `CONFIG_DIR` 的 Worker 容器内：

```bash
# 检查执行任务 #14 当前或失败位置的清单（任务 ID 请替换）
docker exec nas-file-center-worker \
  python -m app.batch.media_package_report_inspector inspect 14

# 指定资源包序号（从 0 开始）
docker exec nas-file-center-worker \
  python -m app.batch.media_package_report_inspector inspect 14 --ordinal 0

# 查看预览/执行报告的保留状态
docker exec nas-file-center-worker \
  python -m app.batch.media_package_report_inspector inventory
```

工具以 SQLite 只读模式读取任务记录，并且只读取报告及资源包一级目录中的暂存目录名称；**不修改数据库、不打开媒体文件内容、不执行移动或删除**。结果中包含私有文件路径，发给他人前应隐藏。

## 生命周期与人工清理策略

| 报告 | 策略 |
| --- | --- |
| 执行任务的 `manifest.json`、`result.json` 和目录 | **始终保留**；失败、取消或完成均可能用于恢复判断及审计 |
| 被任意执行任务关联的预览报告 | **保留**；删除任务历史后也不能据此推断可清理 |
| 仍有预览任务记录的报告 | **保留**；可能仍需审计或执行 |
| 没有找到对应任务/关联的预览报告 | 标记 `review_orphan_never_auto_delete`，**只建议人工审查，不自动删除** |
| 未识别或不完整的报告、符号链接 | 保留并人工核对，不根据文件名推断其安全性 |
| `.nfc-media_package-stage-*` | 是 **媒体目录中的中间状态**，不属于 `reports`，禁止手动删除 |

目前刻意没有提供自动清理按钮、定时清理或 `--force` 选项。若以后要增加删除功能，应先定义可证明安全的保留期限、数据库引用关系、Worker 租约、打开文件身份和审计备份，再实现单独的显式确认流程。

## 发生中断时

1. 不要立即重扫并执行同一资源包，也不要 `rm -rf reports`。
2. 先备份数据集或建立 NAS 存储快照，保留数据库、预览报告、执行清单、任务日志及所有暂存目录。
3. 运行 `inspect <execution_id>`，确认是哪个字段不一致，以及是否留有 `.nfc-media_package-stage-*`。
4. 若缺失/损坏恢复证据，停止自动恢复并人工核对实际文件位置；不要通过修改清单 checksum 来绕过保护。
5. 通过测试后再部署新版本；API 和 Worker 需使用**相同镜像版本**。不要在正在整理媒体文件时重启、升级或修改容器挂载。

相关实现：`app/batch/media_package_execution.py`、`app/batch/media_package_report_lifecycle.py`、`app/batch/media_package_report_inspector.py`。
