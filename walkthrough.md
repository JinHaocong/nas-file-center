# NAS File Center v0.3.4-Gate1 Quarantine Core 验收报告

## 1. 交付概述与演进血统 (Release Lineage & Provenance)

- **当前交付版本**：`NAS File Center v0.3.4-Gate1 (v0.3.4-Gate1-hotfix2)`
- **交付性质**：`Documentation / Provenance Truthfulness Only`（仅文档与交付血统修正，生产代码与业务逻辑 0 变更）
- **正式基线版本 (Stable Release Baseline)**：`NAS File Center v0.3.3 Final`
  - **v0.3.3 Final Commit**：`b5a3fcab87d0cca41abd6b93e0406f3ade06fb3a`
  - **v0.3.3 Final 归档 SHA256**：`7d7480962b8ef78d0c82d658176612a7a09958265b5dbd2327a496b3b2802dbd`
- **Gate1 演进血统 (Gate1 Evolution Lineage)**：
  - **Gate1 Original**：`b9e6847efa9aa67776b693c35b2e1cbfa2e60f24`（初始 Quarantine Core 实现，发现 9 项安全与恢复 blocker）
  - **Gate1-hotfix1**：`830147dcf949f19b14f34d5b0ee5de144044e4c1`（完成 9 项安全与恢复加固实现，测试全绿）
    - 前一 Artifact：`nas-file-center-v0.3.4-gate1-hotfix1.zip`
    - SHA256：`4de313f6b9634387cb43b9f3f5ca95efb7b5825b6ca2738920b7d035ad3d0035`
    - Physical ZIP size：`624,391 bytes`
    - Entries：`283 entries`（精确拆分：`231 files, 52 directories`）
    - Uncompressed payload：`1,925,448 bytes`
  - **Gate1-hotfix2**：当前提交（文档与交付血统修正，纠正先前交付产物中的元数据描述与归档规格）

---

## 2. Gate1-hotfix1 安全与恢复根因全景 (Root Causes & Hardening)

在 Gate1-hotfix1 中完整识别并解决了以下 9 项安全与恢复 blocker：

1. **Purge 符号链接受害者文件防护 (Purge symlink referent safety)**：
   - *根因*：清除前直接调用 `Path.resolve()` 解析符号链接，导致底层 `unlink()` 作用于链接指向的宿主真实受害者文件。
   - *解决*：采用词法前置检查（`is_symlink()` / `os.path.islink()`）。若条目为符号链接，强行阻断并拒绝清除，绝不调用 `resolve()`，受害者文件毫发无损。

2. **缺失目标安全闭环 (Missing target fail-closed)**：
   - *根因*：物理磁盘隔离目标已缺失时，清除操作跳过 `unlink` 并错误将数据库标记为 `purged`，产生伪成功。
   - *解决*：严格 Fail-Closed：若磁盘目标缺失，立即转为 `inconsistent` 异常状态并持久化 `last_error`，抛出 `StateConflictError`（API 层映射为 `HTTP 409 Conflict`）。

3. **目录隔离支持 (Directory quarantine)**：
   - *根因*：执行计划原先假定待隔离对象必为普通文件，对目录调用 `safe_quarantine_hash` 触发 `IsADirectoryError` 崩溃。
   - *解决*：增加目录感知分支：目录隔离时记录 `content_hash = None`，精确统计目录树大小与元数据，支持整树隔离。

4. **目录还原与无跟随清除 (Directory restore/purge)**：
   - *根因*：缺乏目录树还原能力；递归清除目录时可能跟随子符号链接删除外部文件。
   - *解决*：还原时通过原子原语支持目录树还原与冲突策略；清理时采用自底向上无跟随词法遍历（`os.walk(followlinks=False, topdown=False)`），子链接仅删除链接自身，保护外部目标。

5. **服务启动崩溃恢复与条目隔离 (Startup reconciliation)**：
   - *根因*：系统断电或崩溃重启后，遗留的 `preparing`、`restoring`、`purging` 过渡态条目处于未完成状态。
   - *解决*：在 `FileCenterService.__init__` 中挂载 `reconcile_startup_entries()`，每条条目采用独立事务隔离恢复，单条异常不阻塞系统启动。

6. **保留根目录穿透遍历剪枝 (Reserved-root recursive pruning)**：
   - *根因*：索引器、fclones 扫描器及智能整理器遍历时深入隔离区保留根目录。
   - *解决*：索引器递归剪枝排除 `quarantine_root`；fclones 自动添加 `--exclude '<quarantine_root>/**'` 并在解析时双重过滤；Organizer 统计自动排除隔离区。

7. **原子防覆盖隔离与还原 (Atomic rename_noreplace)**：
   - *根因*：普通 `os.replace` 在并发竞争或意外同名时会静默覆盖现有文件。
   - *解决*：在 `app/fs_ops.py` 中实现内核级原子原语 `rename_noreplace`（Linux `renameat2(RENAME_NOREPLACE)` + macOS `renamex_np(RENAME_EXCL)`），目标存在时抛出 `FileExistsError`，并在跳过或重命名策略下安全处理。

8. **隔离根目录符号链接伪装防御 (Quarantine-root symlink defense)**：
   - *根因*：仅依赖 `resolve()` 校验隔离根目录，若保留根目录本身是符号链接可能导致路径穿越。
   - *解决*：在 `build_quarantine_target_path` 中优先对原始未解析路径执行 `is_symlink()` 词法校验，杜绝符号链接根目录伪装。

9. **任务外键关联与索引 (task_id FK)**：
   - *根因*：模型缺少显式外键级联与索引支持。
   - *解决*：在 `QuarantineEntry` 中补充 `ForeignKey("work_jobs.id", ondelete="SET NULL")` 与 `index=True`，并通过 `PRAGMA foreign_key_list` 自动化迁移测试。

---

## 3. 测试与验证实证 (Real Test Evidence)

本轮文档修正前后，所有业务与生产代码与 `830147dcf949f19b14f34d5b0ee5de144044e4c1` 保持完全字节一致（Byte-Identical），测试结果严格真实可复现：

- **后端全量回归测试 (Backend Pytest)**：
  - **总计**：`388 passed, 0 failed` (100% 通过)
  - **版本一致性测试**：`tests/test_release_version_consistency.py` 6 passed
  - **隔离安全强化测试 (Hardening Suite)**：`tests/test_quarantine_hardening.py` **18 / 18 passed**
    - 符号链接清除逃逸阻断 (1)
    - 缺失目标 Fail-Closed 409 (1)
    - 目录隔离、还原与安全清除 (3)
    - 服务启动崩溃恢复 preparing / restoring / purging (3)
    - 索引器、扫描器与整理器隔离区剪枝 (3)
    - 根目录符号链接拒绝 (1)
    - task_id 外键与索引约束 (1)
    - rename_noreplace 冲突防覆盖与并发竞争 (3)
    - API 状态冲突 409 与恢复策略 (2)
- **前端全量单元测试与构建 (Frontend Suite & Build)**：
  - **单元测试**：`150 passed, 44 suites, 0 failed`
  - **TypeScript 静态检查**：`npm run typecheck` (0 errors)
  - **生产打包构建**：`npm run build` (Vite 打包成功，无异常)
- **全链路对抗验证 (Adversarial Smoke)**：
  - 在 Docker 干净容器中对 v0.3.3 数据库迁移快照、符号链接攻击阻断、缺失目标 Fail-Closed 409、目录整树隔离还原与物理清理全链路验证，全部通过。

---

## 4. 已知边界与后续 Gate 规划 (Known Limitations)

作为 Gate1 里程碑（Quarantine Core），本阶段仅负责隔离区核心存储引擎、数据模型与底层安全防护，以下功能属于后续 Gate 的既定范围，本阶段严格保持边界隔离：

1. **Plan Execute 同步执行**：当前计划执行仍由 API 线程同步处理，后台异步任务编排与 Worker 驱动由 **Gate2** 承接；
2. **无操作审计日志 (No Operation Journal)**：操作回溯与逆向操作记录由 **Gate2** 承接；
3. **无撤销执行计划 (No Undo Plan)**：反向回滚引擎与撤销计划生成由 **Gate2** 承接；
4. **无陈旧计划自动重算 (No Stale Plan)**：执行前文件变动的陈旧计划冲突检测与重算由 **Gate3** 承接；
5. **无隔离区管理 UI (No Quarantine UI)**：前端隔离区展示、按条目恢复、批量清理等交互界面由 **Gate4** 承接；
6. **无后台自动清除 (No Automatic Purge)**：默认保留天数为 `0`（永久保留），不引入后台静默清理，清除必须由管理员显式传入 `confirmation="DELETE"`；
7. **跨卷操作安全阻断 (EXDEV Fail-Closed)**：跨物理卷移动强行中止并标记失败，防止隐式跨卷数据截断。

---

## 5. 验收决议 (Release Decision)

- **当前验收结论**：**v0.3.4-Gate1 acceptance PASS**（隔离区核心引擎与安全防护门禁已完全达标，准予作为 Gate1 阶段性基线，允许进入后续 Gate2 开发）。
- **非正式最终版声明**：本交付为 Gate1 阶段门禁验收，**绝非 v0.3.4 Final Release**。
