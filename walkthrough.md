# NAS File Center v0.3.5 Gate5-B-hotfix2 — Implementation & Verification Walkthrough

## 1. Context & Scope (背景与状态)

当前正式状态：
```text
Gate2 = PASS
Gate3 = PASS
Gate4 = PASS
Gate5-A = PASS
NAS File Center v0.3.4 = CLOSED

Gate5-B-hotfix1 targeted review = PASS
Gate5-B overall independent review = FAIL / HOLD

P0 = 0
P1 = 2 (P1-03, P1-04)
P2 = 4 (P2-07, P2-08, P2-09, P2-10)
P3 = 1 (P3-02)

Gate5-C+ = FORBIDDEN
v0.3.5 = NOT CLOSED
```

本轮任务严格限定于修复 Gate5-B 整体独立评审发现的 7 个问题（2 个 P1、4 个 P2、1 个 P3），绝不扩大范围，绝不引入 Gate5-C 特性。

---

## 2. Issues Closed & Technical Implementation (问题关闭与技术实现)

### 2.1 P1-03 — Organizer Global Exclude Bypass & Digest Linkage
- **问题根因**：此前文件工作流正确应用了 `FilterPolicy.exclude_dir_names_json`，但整理工作流（Organizer Workflow）仅排除了 `quarantine_root`，导致 `.git/`、`.recycle/`、`@eaDir/` 等目录仍可被扫描整理；且编译上下文中的 `effective_exclude_dir_names` 硬编码为空列表，全局排除策略更新不会引发 `compile_digest` 变化。
- **修复方案**：
  1. 在 `app/organizers/engine.py` 中扩展 `_make_exclusion_filter(excluded_roots, exclude_dir_names)`，实现段敏感（Segment-aware）的目录过滤：
     - 路径任一段匹配 `exclude_dir_names`（如 `.git`）即排除（如 `.git/`, `subdir/.git/`）；
     - 非全字匹配段（如 `.git2/`, `my.git/`）予以保留；
     - 保持硬排除 `quarantine_root` 不变。
  2. 在 `collect_directory_stats`、`collect_tree_stats_bottom_up` 与 `generate_organizer_proposals` 中全链路透传 `exclude_dir_names`。
  3. 在 `app/workflows/compiler.py` 的 `_compile_organizer_workflow` 中动态拉取 `FilterPolicy` 的全局排除目录列表，传入整理提议生成器，并将排序后的排除项写入 `compile_context["effective_exclude_dir_names"]`，使得排除策略变更时 `compile_digest` 必然联动刷新。

### 2.2 P1-04 — Empty Roots Fail Closed & IndexRoot Boundary Validation
- **问题根因**：当未指定根目录时，文件工作流可能泛化到所有 IndexedPath；且越界或不存在的 root ID 此前仅被静默丢弃。
- **修复方案**：
  1. 在 `app/workflows/compiler.py` 的 `_compile_file_workflow` 中：
     - 严格要求 `1 <= len(effective_root_ids) <= 16`，空列表抛出 422 `ROOT_REQUIRED`，超过 16 个抛出 422 `ROOT_LIMIT_EXCEEDED`；
     - 对每一个 root ID 强校验存在性与边界：不存在或不在 `ALLOWED_ROOTS` 内时，立即抛出 422 `INDEX_ROOT_NOT_FOUND`；
     - 强制将 `IndexedPath.root_key.in_(target_roots)` 加入查询条件，根绝根目录泛化漏洞。
  2. 在 `_compile_organizer_workflow` 中：
     - 若指定 `effective_root_ids`，强制要求数量为 1，否则分别返回 422 `ROOT_REQUIRED`（0 个）或 422 `ORGANIZER_SINGLE_ROOT_REQUIRED`（>1 个）；
     - 同样执行 `INDEX_ROOT_NOT_FOUND` 边界校验。

### 2.3 P2-07 — Real SQLite Concurrency Transaction
- **问题根因**：此前在 `WorkflowService` 的 `update_workflow`、`archive_workflow`、`rollback_workflow` 中，先以默认 DEFERRED 读取 `wf.current_revision`，再检查并发冲突。当两并发线程同时发起预期相同版本的更新时，导致 Check-Then-Act 窗口，在第二阶段写入时引发 SQLite `IntegrityError` 或 `database is locked`（HTTP 500）。
- **修复方案**：
  - 在 `create_workflow`、`update_workflow`、`archive_workflow`、`rollback_workflow` 的事务开启最初阶段立即执行 `session.execute(text("BEGIN IMMEDIATE"))`，在读取工作流对象前即获得排他写锁；
  - 第二个竞争线程排队等待直至前序事务完成，随后在排他事务中读取到已更新的版本号，干净利落地抛出 409 `WorkflowRevisionConflictError` (`WORKFLOW_REVISION_CONFLICT`)，杜绝 500 与数据完整性异常。

### 2.4 P2-08 — Organizer profile_snapshot Strict Validation & Immutability
- **问题根因**：工作流步骤定义中 `OrganizeStep.profile_snapshot` 采用宽松的 `dict[str, Any]`，未在创建与更新时强校验字段类型与未知字段，可能留存至运行期才报错。
- **修复方案**：
  1. 在 `app/workflows/schema.py` 中定义严格的 `OrganizerProfileSnapshot` Pydantic 模型：
     - 声明 `model_config = ConfigDict(extra="forbid")`，禁止任何额外未知属性；
     - 强制数字字段校验（`numbering_start`, `numbering_padding` 为纯正整数，严禁布尔值与字符串）；
     - 强制列表字段校验（`image_extensions`, `video_extensions`, `preserve_tags`, `cleanup_patterns` 必须为字符串数组，严禁 raw string）；
  2. `OrganizeStep.profile_snapshot` 采用强类型绑定，在 Workflow 创建与更新入口（POST/PUT）直接拦截并返回 422；
  3. 快照在写入 `workflow_revisions.definition_json` 后固化为不可变版本，原始 `OrganizerProfile` 后续修改或删除均不影响工作流快照。

### 2.5 P2-09 — Runtime Root Contract Ambiguity
- **问题根因**：`WorkflowPreviewRequest` 与 `WorkflowGeneratePlanRequest` 同时暴露顶层 `root_ids` 与 `runtime_inputs.root_ids`，缺乏明确的单一事实源约束与冲突处理规范。
- **修复方案**：
  1. 在 `WorkflowPreviewRequest` 与 `WorkflowGeneratePlanRequest` 模型中增加 Pydantic `model_validator`：
     - 若同时提供顶层 `root_ids` 与 `runtime_inputs`，立即拒绝并抛出 422 `AMBIGUOUS_RUNTIME_INPUTS`；
  2. 在 `WorkflowService.preview_workflow` 与 `generate_plan` 中以 `runtime_inputs.root_ids` 为首要事实源；
  3. 整理工作流在预览时传入多个 root ID 直接抛出 422 `ORGANIZER_SINGLE_ROOT_REQUIRED`。

### 2.6 P2-10 — Virtual Graph O(n) Optimization
- **问题根因**：在 `app/workflows/graph.py` 的依赖边构建中（Lines 342, 343, 354），反复对完整操作列表调用 `all_ops.index(...)` 导致 $O(n^2)$ 复杂度假死（20,000 操作图构建需耗时 38.87 秒）。
- **修复方案**：
  1. 构建内存索引字典 `op_index_by_id = {id(op): idx for idx, op in enumerate(all_ops)}`，将依赖节点查表由 $O(n)$ 降为 $O(1)$；
  2. 拓扑排序升级为带稳定堆（Min-Heap）的确定性 Kahn 算法：
     - 堆元素键采用 `(op.workflow_step_index, op.candidate_operation_index, op.candidate_id, op.source, idx)`，兼具绝对确定性与极低排序开销；
  3. 复杂性彻底降至 $O(V + E \log V)$。实测 10,000 候选对象（20,000 操作）的依赖建图与拓扑解析耗时由 **38.87s** 锐减至 **0.095s**（性能提升超 400 倍）。

### 2.7 P3-02 — Stale Walkthrough
- 更新代码库中的 `walkthrough.md` 与会话制品，完整记录 Gate5-B-hotfix2 的缺陷根因、修复细节与全量验证数据。

---

## 3. Verification & Evidence (验证与证据)

### 3.1 TDD 失败基线证明 (RED Evidence)
在实现前编写针对性失败测试 `tests/test_gate5b_hotfix2_red.py`，完整复现了 6 项缺陷：
```text
FAILED tests/test_gate5b_hotfix2_red.py::test_p1_03_organizer_global_exclude_and_digest
  -> AssertionError: subdir/.git was not excluded
FAILED tests/test_gate5b_hotfix2_red.py::test_p1_04_empty_roots_and_boundary_validation
  -> AssertionError: assert 200 == 422 (empty roots allowed instead of ROOT_REQUIRED)
FAILED tests/test_gate5b_hotfix2_red.py::test_p2_07_real_sqlite_concurrency_transaction
  -> IntegrityError: UNIQUE constraint failed: workflow_revisions.workflow_id, workflow_revisions.revision
FAILED tests/test_gate5b_hotfix2_red.py::test_p2_08_organizer_profile_snapshot_strict_validation
  -> AssertionError: assert 201 == 422 (bad snapshot string numbering accepted)
FAILED tests/test_gate5b_hotfix2_red.py::test_p2_09_runtime_root_contract_ambiguity
  -> AssertionError: assert 200 == 422 (ambiguous roots accepted instead of AMBIGUOUS_RUNTIME_INPUTS)
FAILED tests/test_gate5b_hotfix2_red.py::test_p2_10_virtual_graph_performance
  -> AssertionError: Graph resolution took 38.87s, exceeding 5.0s limit
```

### 3.2 修复后套件验证 (GREEN Evidence)
```bash
# 1. Gate5-B-hotfix2 专项测试套件 (6 passed in 0.88s)
docker exec -e PYTHONPATH=/app nas-test-env pytest tests/test_gate5b_hotfix2.py -v
# Output: 6 passed, 2 warnings in 0.88s

# 2. Gate5-B-hotfix1 回归测试与整理方案回归测试 (36 passed in 19.41s)
docker exec -e PYTHONPATH=/app nas-test-env pytest tests/test_gate5b_hotfix1_red.py tests/test_organizer_blockers_regression.py -v
# Output: 36 passed, 2 warnings in 19.41s

# 3. 工作流全集模块单元/接口测试 (24 passed in 1.26s)
docker exec -e PYTHONPATH=/app nas-test-env pytest tests/test_workflow_*.py -v
# Output: 24 passed, 2 warnings in 1.26s

# 4. 后端全量测试套件 (569 passed in 58.39s)
docker exec -e PYTHONPATH=/app nas-test-env pytest -v
# Output: 569 passed, 20 warnings in 58.39s

# 5. 前端全量测试与生产构建 (177 passed in 83.6ms, build succeeded)
npm test && npm run build
# Output: 177 passed in 83.6ms, built in 3.30s
```

### 3.3 Docker 容器黑盒端到端验收 (Blackbox Evidence)
全新构建生产镜像 `nas-file-center:v0.3.5-gate5b-hotfix2`，并在隔离容器环境中执行黑盒验收脚本 `scratch/test_gate5b_hotfix2_blackbox_acceptance.py`：
```text
=== Starting Gate5-B-hotfix2 Blackbox Acceptance against nas-file-center:v0.3.5-gate5b-hotfix2 ===
[DEPLOY] Starting API container nas-gate5b-hf2-accept-c623c1...
[DEPLOY] API container is healthy.
[SETUP] Created IndexRoot ID: 1
[CP1] Verifying P1-03: Organizer Global Exclude segment-awareness and compile_digest...
[CP1] P1-03: PASS
[CP2] Verifying P1-04: Empty roots fail closed...
[CP2] P1-04: PASS
[CP3] Verifying P2-07: SQLite BEGIN IMMEDIATE concurrency conflict...
[CP3] Concurrent update response status codes: [409, 200]
[CP3] P2-07: PASS
[CP4] Verifying P2-08: Organizer profile_snapshot strict validation...
[CP4] P2-08: PASS
[CP5] Verifying P2-09: Ambiguity and Organizer root limit...
[CP5] P2-09: PASS
[CP6] Verifying P2-10: Virtual Graph performance in container...
[CP6] Container graph performance output: OPS=20000 DUR=0.095
[SUMMARY] Final Report: {
  "P1-03": "PASS",
  "P1-04": "PASS",
  "P2-07": "PASS",
  "P2-08": "PASS",
  "P2-09": "PASS",
  "P2-10": "PASS"
}

ALL GATE5-B-HOTFIX2 BLACKBOX ACCEPTANCE CHECKS PASSED!
```

---

## 4. Final Review Status (最终状态声明)

```text
Gate5-B-hotfix2 implementation candidate ready for independent review.

P1-03: CLOSED
P1-04: CLOSED
P2-07: CLOSED
P2-08: CLOSED
P2-09: CLOSED
P2-10: CLOSED
P3-02: CLOSED

Gate5-A = PASS
Gate5-B = HOLD (Candidate Ready for Independent Review)
Gate5-C = FORBIDDEN
v0.3.5 = NOT CLOSED
```
