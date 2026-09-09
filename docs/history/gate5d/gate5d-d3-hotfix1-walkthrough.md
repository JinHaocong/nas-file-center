# NAS File Center v0.3.5 Gate5-D / D3-hotfix1 — Implementation & Verification Walkthrough

## 1. Commit Baseline & Identity (基线与提交身份)

- **Baseline Commit / ZIP Comment**: `6ee19bf61c57cf216f3cd0eee248ce9b2ecd5877`
- **Baseline Artifact SHA256**: `7946a2c2cb11fdaf930d2f95366dcf90cbe83ce32c54d64f645c3398f22a7785`
- **Implementation Commit**: `fbde1786966fd925cbcab44d9c4db3a0a332ae63`
- **Final Handoff Commit**: *(待提交后记录)*

---

## 2. Commit History in this Stage (本阶段提交历史)

```text
fbde178 fix(gate5d): resolve d3 independent review contract and safety blockers
6ee19bf docs(gate5d): hand off d3 for independent review
```

---

## 3. Diff Scope (修改范围审计)

```text
 app/service.py                        |   5 +-
 app/workflows/compiler.py             |  60 +++++++++++--
 app/workflows/schema.py               |   2 +
 app/workflows/service.py              | 147 ++++++++++++++++++-------------
 app/workflows/validation.py           |  82 ++++++++++++++---
 tests/test_gate5d_d3_workflow_dedupe.py | 650 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
 6 files changed, 838 insertions(+), 106 deletions(-)
```

### Production Changes:
- **`app/workflows/validation.py`**:
  - 新增 `validate_and_canonicalize_workflow_scorer_config(raw_config)` 统一处理工作流打分配置校验，捕获 `ValueError` 并映射为结构化 `WorkflowValidationError`（普通非法参数 -> 422 `DEDUPE_INVALID_CONFIG`，保留因子如 `resolution` -> 422 `DEDUPE_FACTOR_UNAVAILABLE`）。
  - 新增 `resolve_mode_runtime_inputs(mode, root_ids, runtime_inputs)` 共享助手函数，在 Preview 与 Generate 之间统一模式感知输入校验规则。
- **`app/workflows/schema.py`**:
  - `WorkflowPreviewResponse` 新增 `workflow_mode: Literal["file", "organizer", "dedupe"] = "file"`。
  - `WorkflowPreviewResponse` 新增 `dedupe_summary: dict[str, Any] | None = None`。
- **`app/workflows/compiler.py`**:
  - 定义 `@dataclass(frozen=True) class DedupeWorkflowSafetySnapshot`。
  - `WorkflowCompiler` 接收并在去重编译中优先使用 `safety_snapshot`，禁止重读 settings 与动态解析别名，杜绝 mixed-epoch authority。
  - 将 `group_provenance_id` 与 `group_decision_fingerprint` 纳入编译操作字典 `planned_operations`，强化 compile_digest operation identity。
  - 将缺少 `scan_job_id` 错误码规范为 422 `SCAN_JOB_ID_REQUIRED`。
- **`app/workflows/service.py`**:
  - 新增 `_capture_dedupe_safety_snapshot()`，在 Preview/Generate 开始时捕获单次请求不可变安全快照并传入 `compile_workflow_definition`。
  - `create_workflow` 与 `update_workflow` 统一调用 `validate_and_canonicalize_workflow_scorer_config`，彻底消除未捕获 plain `ValueError`（杜绝 HTTP 500），且事务保证 0 Workflow / 0 Revision 生成。
  - `preview_workflow`：空去重预览返回 `total_pages = 0`（file/organizer 保持 legacy `1`）；返回 `workflow_mode="dedupe"` 与完整的 16 项 canonical `dedupe_summary`。
  - `generate_plan`：空去重计划抛出 `DedupeEmptyPlanError`，返回 422 `DEDUPE_EMPTY_PLAN`，保证 0 Draft。
- **`app/service.py`**:
  - `_validate_rebuild_eligibility` 明确要求 `metadata.source == "workflow" and metadata.workflow_mode == "dedupe"` 双重条件，保持 direct 与 file/organizer 的原有行为。
  - 增加 `_capture_dedupe_safety_snapshot` 委托方法。

---

## 4. Blockers RED & GREEN Evidence (各阻断项红绿测试证据)

### Blocker 1: Workflow Create / Update invalid scorer_config 500 -> 422 structured (Tests A, B, C, D)
- **RED Evidence**:
  `res1 = client.post("/api/workflows", json={"definition": {"mode": "dedupe", "steps": [{"scorer_config": {"selection_mode": "bogus"}}]}})`
  原代码抛出未捕获的 `ValueError` 导致 `HTTP 500 Internal Server Error`。
- **GREEN Evidence**:
  返回 `HTTP 422` 且 `error.code == "DEDUPE_INVALID_CONFIG"`；针对保留因子 `resolution` 返回 `HTTP 422` 且 `error.code == "DEDUPE_FACTOR_UNAVAILABLE"`；数据库验证 `Workflow` 与 `WorkflowRevision` 计数为 0；更新失败时旧 revision 不变。

### Blocker 2: Per-request Effective Safety Snapshot (Tests K, L)
- **RED Evidence**:
  `service.workflow_service` 缺少 `_capture_dedupe_safety_snapshot` 方法；compiler 在运行期间二次解析 settings，对抗性 retarget 出现 mixed-epoch authority。
- **GREEN Evidence**:
  通过 `test_28_per_request_safety_snapshot_immutability`：请求开始时一次性捕获 `DedupeWorkflowSafetySnapshot`，即使后续 settings 被篡改，compiler 与 compile_context 仍然使用最初捕获的不可变快照，杜绝跨 epoch 混杂。

### Blocker 3: Workflow Dedupe Preview Response Contract (Tests F, G, H)
- **RED Evidence**:
  `WorkflowPreviewResponse` 缺少 `workflow_mode` 与 `dedupe_summary`，客户端解析报错 `KeyError: 'workflow_mode'`。
- **GREEN Evidence**:
  通过 `test_25_preview_workflow_mode_and_dedupe_summary_contract`：
  - `file`: `workflow_mode="file", dedupe_summary=None`
  - `dedupe`: `workflow_mode="dedupe"`, `dedupe_summary` 包含全量 16 项 canonical 字段：
    `scan_job_id, scan_roots, dedupe_engine_version, selection_mode, group_count, candidate_member_count, actionable_group_count, skipped_group_count, planned_quarantine_count, expected_reclaim_bytes, released_bytes_by_scan_root, scorer_config_digest, source_snapshot_digest, decision_digest, preview_digest, effective_safety_policy`。
  - `preview_digest` 与 Direct D2 `/api/scans/{id}/dedupe-preview` 保持绝对一致。

### Blocker 4: Empty Preview Pagination (Test I)
- **RED Evidence**:
  去重工作流空结果原代码返回 `total_pages = 1`，断言 `assert resp["total_pages"] == 0` 失败 (`assert 1 == 0`)。
- **GREEN Evidence**:
  通过 `test_26_empty_preview_total_pages_zero`：去重工作流空结果返回 `total_pages = 0`，保持与 Direct D2 对齐；普通文件工作流空结果保持 legacy `total_pages = 1`。

### Blocker 5: Runtime Semantic Error Codes (Test E)
- **RED Evidence**:
  缺少 scan_job_id 返回 `SCAN_JOB_REQUIRED`；dedupe + root_ids 返回 `INVALID_RUNTIME_INPUTS`；file + scan_job_id 返回 `INVALID_RUNTIME_INPUTS`。
- **GREEN Evidence**:
  通过 `test_24_exact_runtime_semantic_error_codes`：
  - missing dedupe scan_job_id -> 422 `SCAN_JOB_ID_REQUIRED`
  - dedupe + root_ids -> 422 `ROOT_IDS_FORBIDDEN`
  - file/organizer + scan_job_id -> 422 `SCAN_JOB_ID_FORBIDDEN`
  - top-level + nested root_ids -> 422 `AMBIGUOUS_RUNTIME_INPUTS`
  - nonexistent scan -> 404 `DEDUPE_SCAN_NOT_FOUND`
  - uncompleted scan -> 409 `DEDUPE_SCAN_NOT_COMPLETED`
  - top-level scan_job_id -> 422 拒绝（无别名兼容）

### Blocker 6: Empty Dedupe Generate (Test J)
- **RED Evidence**:
  匹配 compile_digest 但无计划操作时，原代码返回通用 `EMPTY_PLAN`，断言 `assert 'EMPTY_PLAN' == 'DEDUPE_EMPTY_PLAN'` 失败。
- **GREEN Evidence**:
  通过 `test_27_empty_dedupe_generate_empty_plan_zero_mutation`：返回 422 `DEDUPE_EMPTY_PLAN`，且数据库 0 BatchPlan、0 BatchPlanItem、0 WorkJob、0 QuarantineEntry、0 文件系统变更。

### Blocker 7: compile_digest operation identity (Test M)
- **RED Evidence**:
  `quarantine_operations` 中未绑定 `group_provenance_id` 与 `group_decision_fingerprint`。
- **GREEN Evidence**:
  通过 `test_29_compile_digest_operation_identity`：从 Intent 元数据提取组身份与决策指纹直接注入 planned operations 字典，参与计算 `compile_digest`，保持对组指纹敏感，同时分页与 only_changed 保持不变性。

### Blocker 8: Stale Rebuild Detection Authority (Test N)
- **RED Evidence**:
  原代码只检查 `workflow_mode == "dedupe"`。
- **GREEN Evidence**:
  通过 `test_30_stale_rebuild_detection_authority`：严格要求 `metadata.source == "workflow" and metadata.workflow_mode == "dedupe"` 同时成立，非 workflow 来源的计划不会误触发 `DEDUPE_RESCAN_REQUIRED`。

### 事务回滚与 Phase B 纯度验证 (Tests 31 & 32)
- 通过 `test_31_item_insertion_failure_full_rollback`：Phase B 写入 Item 发生异常时，整笔事务全部回滚，保持 0 BatchPlan。
- 通过 `test_32_phase_b_zero_filesystem_and_scoring_calls`：Phase B 纯粹读取 Phase A 编译产物入库，零文件系统 I/O 与零打分/平衡器重新计算。

---

## 5. Verification Execution Evidence (验证执行记录)

### 5.1 D3-hotfix1 单元测试套件（37 个测试全部通过）
```bash
docker exec -e PYTHONPATH=. nas-test-env pytest tests/test_gate5d_d3_workflow_dedupe.py
```
```text
tests/test_gate5d_d3_workflow_dedupe.py ..................................... [100%]
============================== 37 passed in 3.71s ==============================
```

### 5.2 聚焦回归套件（15 个测试文件，236 passed, 0 failures）
```bash
docker exec -e PYTHONPATH=. nas-test-env pytest -o addopts="" -q \
  tests/test_workflow_api.py \
  tests/test_workflow_compiler.py \
  tests/test_workflow_models.py \
  tests/test_workflow_validation.py \
  tests/test_gate5c_hotfix1_backend.py \
  tests/test_gate5c_hotfix2_backend.py \
  tests/test_gate5c_hotfix3_backend.py \
  tests/test_gate5c_integration_acceptance.py \
  tests/test_gate5c_rebuild.py \
  tests/test_gate5d_advanced_dedupe_core.py \
  tests/test_gate5d_d3_workflow_dedupe.py \
  tests/test_gate5d_dedupe_generate.py \
  tests/test_gate5d_dedupe_generate_api.py \
  tests/test_gate5d_dedupe_preview_api.py \
  tests/test_gate5d_dedupe_preview_compiler.py
```
```text
........................................................................ [ 30%]
........................................................................ [ 61%]
........................................................................ [ 91%]
....................                                                     [100%]
236 passed, 2 warnings in 20.25s
```

### 5.3 全量后端回归套件（813 passed, 0 failures，基线 803 -> 813）
```bash
docker exec -e PYTHONPATH=. nas-test-env pytest -o addopts="" --disable-warnings -q
```
```text
813 passed, 20 warnings in 85.08s (0:01:25)
```

### 5.4 前端验证（0 changes, Typecheck & Build 100% 通过）
```bash
cd frontend && npm run typecheck && npm run build
```
```text
> nas-file-center-frontend@0.3.3 typecheck
> tsc --noEmit

> nas-file-center-frontend@0.3.3 build
> tsc && vite build

vite v6.4.3 building for production...
✓ 3748 modules transformed.
✓ built in 3.77s
```

### 5.5 Docker & Smoke 验证
- **`linux/amd64` Docker 构建**:
  `docker build --platform linux/amd64 -t nas-file-center:d3-hotfix1-smoke .` (完成并导出镜像)
- **API Health Smoke**:
  `curl -i http://localhost:8089/health`
  `HTTP/1.1 200 OK`
  `{"status":"ok","allow_mutation":false,"allow_delete":false,"allowed_roots":["/data"]}`
- **Worker Recovery Smoke**:
  `python -c "from app.config import get_settings; from app.worker import recover_running_jobs; print('Worker recovery OK:', recover_running_jobs(get_settings()))"`
  `Worker recovery OK: 0`

---

## 6. Known Limitations (已知局限性说明)

- 本阶段聚焦于 Workflow Dedupe Contract 与 Safety Snapshot 修复，前端工作流交互属于 D4 阶段，本阶段前端代码 0 改动。
- 历史去重工作流计划（stale 状态）禁止直接 rebuild，必须重新执行扫描并生成新计划（符合设计规范）。

---

## 7. Current State Declaration (阶段声明)

**`D3-hotfix1 IMPLEMENTATION COMPLETE / READY FOR INDEPENDENT REVIEW`**

*(未声明 PASS / CLOSED，未进入 D4)*
