# Gate5-E / E3-hotfix5 Walkthrough: Wrapper Enumeration Snapshot Continuity

## 1. 任务背景与目标

在 E3-hotfix4 独立评审中，发现了 Phase-A 快照连续性中的 Wrapper 枚举变更缺陷：
1. **非空 Wrapper 竞态增添子项（Partial Flatten 隐患）**：
   - Preview 观察到 `W/a.txt`；
   - Generate Phase-A 期间，discovery 与 wrapper observation 完成后、在 graph authority 校验完成前，创建了 `W/new.txt`；
   - Wrapper 保持相同的 `st_dev` 与 `st_ino`，但 `st_mtime_ns` 与子项枚举发生了变更；
   - Hotfix4 未校验 wrapper `st_mtime_ns` 与直接子项枚举快照，导致 fresh preview_digest 与 expected_preview_digest 匹配，HTTP 201 成功生成 Draft 但仅包含 `W/a.txt -> Root/a.txt`，静默遗漏 `W/new.txt`。
2. **空 Wrapper 竞态增添子项（空计划状态码错误）**：
   - Preview 观察到 `W` 为空目录（0 candidate，0 planned_operations）；
   - Generate Phase-A 期间创建 `W/new.txt`；
   - Hotfix4 仅在遍历 candidate items 时校验 wrapper 连续性。对于空 wrapper（0 个 candidate），wrapper 连续性检查被完全跳过，返回 `422 BATCH_UTILITY_EMPTY_PLAN` 而非 `409 PREVIEW_CHANGED`。

目标：实现 Wrapper 枚举快照连续性（Wrapper Enumeration Snapshot Continuity），保证任何非空或空 wrapper 在 Phase-A 期间发生枚举或 mtime 变更时，均 fail-closed 返回 `409 PREVIEW_CHANGED` 且生成 0 Draft。

---

## 2. 核心改动

### 2.1 `app/batch_utilities/compiler.py`
1. **Wrapper 观测捕获直接子项枚举快照**：
   - 在 `compile_flatten_one_level_preview` 中，遍历 `canonical_wrappers` 时通过 `os.scandir(w_lex)` 捕获排序后的 `direct_children` 列表，绑定入 `wrapper_observations` 及 `source_snapshot_payload`。
2. **空 Wrapper 冲突映射入决策行**：
   - 在候选子项决策行生成后，检查所有 canonical wrappers；若某个 wrapper 存在 blocking conflict（如空 wrapper 发生枚举变更）且未在 `decision_rows` 中体现，则生成对应的 `BLOCKING_CONFLICT` 决策行（`reason_code="WRAPPER_IDENTITY_CHANGED"`），使 `blocking_conflict_count > 0` 且 preview digest 及时感知变化。
3. **冲突优先级配置更新**：
   - 将 `CONFLICT_PRIORITY_RANK` 中的 `WRAPPER_IDENTITY_CHANGED` 设定为 rank 5，与 `SOURCE_IDENTITY_CHANGED` 同级，通过字母排序实现细粒度 Source 错误优先于 Wrapper 错误呈现。

### 2.2 `app/batch_utilities/flatten_graph.py`
1. **独立 Wrapper 连续性检查 Pass（与 candidate 数量解耦）**：
   - 在 `resolve_flatten_graph` 头部遍历所有 `wrapper_observations`，无论 candidate 数量是否为 0 均执行严密的连续性检验：
     - 严格无跟随 `_lstat` 检查存在性、目录属性及非 symlink；
     - 校验物理身份（`device`、`inode`）；
     - 校验直接子项枚举指纹（`_scandir` 读取的当前直接子项集合与 `direct_children` 一致）以及 `st_mtime_ns`。
2. **区分容器替换与枚举变更**：
   - 若 Wrapper 容器自身发生物理置换（symlink 替换、inode 改变、非目录等），直接阻断该 wrapper 下的所有候选子项（`WRAPPER_IDENTITY_CHANGED`）；
   - 若 Wrapper 容器物理身份未变，但枚举或 mtime 发生变化：
     - 先对 candidate 自身执行精确的 physical identity 与 source authority 校验（如果 candidate 自身被替换或删除，保留精确的 `SOURCE_IDENTITY_CHANGED` 或 `SOURCE_MISSING`）；
     - 若 candidate 自身无 source 级冲突，则因 wrapper 枚举变更赋予 `WRAPPER_IDENTITY_CHANGED` 并将其阻断；
   - 若 Wrapper 没有 candidate（如空 wrapper），直接向 `conflicts` 添加 `WRAPPER_IDENTITY_CHANGED` 冲突。

---

## 3. 测试验证

1. **E3-hotfix5 针对性新增回归测试**：
   - `test_compiler_nonempty_wrapper_child_appearance_blocked`：验证非空 wrapper 在 Phase-A 期间竞态增添新文件时，0 safe items, 0 Draft intents, `WRAPPER_IDENTITY_CHANGED`。
   - `test_compiler_empty_wrapper_child_appearance_blocked`：验证空 wrapper 在 Phase-A 期间竞态增添新文件时，产生针对该 wrapper 的 `BLOCKING_CONFLICT`（`WRAPPER_IDENTITY_CHANGED`），`blocking_conflict_count == 1`。
   - `test_generate_flatten_nonempty_wrapper_child_appearance_race_raises_409`：API 级验证非空 wrapper 增添文件竞态抛出 HTTP 409 `PREVIEW_CHANGED`，DB 中创建 0 个 BatchPlan / BatchPlanItem。
   - `test_generate_flatten_empty_wrapper_child_appearance_race_raises_409`：API 级验证空 wrapper 增添文件竞态抛出 HTTP 409 `PREVIEW_CHANGED`（而非 422），DB 中创建 0 个 BatchPlan / BatchPlanItem。
2. **全套 Gate5-E 测试**：
   - `tests/test_gate5e_*.py` 包含 140 项测试全部通过（100% PASS）。
3. **全量后端测试套件**：
   - `nas-test-env:latest` 运行 `pytest tests/`，全量 957 项测试全部通过（100% PASS）。

---

## 4. 边界与约束遵守确认

- [x] 未开启 E4。
- [x] 未声明 E3 PASS / CLOSED。
- [x] 零生产范围外修改：仅限 `app/batch_utilities/compiler.py` 与 `app/batch_utilities/flatten_graph.py`。
- [x] 零 DB migration，零新 Worker，零新 Undo 引擎，零空目录删除。
- [x] Draft 物理身份严格保持 `expected_device=0, expected_inode=0, expected_mtime_ns=0, expected_hash=None`。
