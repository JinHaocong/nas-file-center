# NAS File Center v0.3.5 Gate5-D / D3 — Implementation & Verification Walkthrough

## 1. Commit Baseline & Identity (基线与提交身份)

- **Baseline Commit / ZIP Comment**: `185de4f1040cfc8076c7aec93000541cd48b13d6`
- **Baseline Artifact SHA256**: `1e233645ea3dfb932074afc1ab7a345891396908692d261a41461d9de7400572`
- **D3 Implementation Commit**: `2f67e605d3989c97b5e40702d7653bb57235b80a`

---

## 2. Architectural Compliance & Implementation Summary (架构落地与实现清单)

根据 `Gate5-D-D3-Architecture-Freeze-2026-09-08.md` 及 `Gate5-D-D3-Implementation-Plan-2026-09-08.md`，D3 在保持 D2-A 编译器权威与 D2-B2 意图语义完全不变的前提下，完成了工作流去重模式集成：

### 2.1 Workflow Dedupe Pipeline Grammar & Validation (`app/workflows/`)
- **Mode 扩展**: `WorkflowDefinition.mode` 与 `WorkflowListItem.mode` 支持 `"dedupe"`。
- **Step 定义**: 新增 `DedupeStep(id, type="dedupe", scorer_config)`，加入 `WorkflowStep` 联合体。
- **拓扑铁律校验**:
  - `mode == "dedupe"` 必须包含 **恰好 1 个 step** 且类型为 `"dedupe"`；严禁组合 `scan`、`filter`、`rename`、`move`、`touch`、`quarantine`、`organize` 或第二个 `dedupe`（报错 `INVALID_PIPELINE_STRUCTURE`）。
  - `mode in ("file", "organizer")` 严禁出现 `dedupe` step（报错 `UNSUPPORTED_STEP` / `INVALID_PIPELINE_STRUCTURE`）。
  - `scorer_config` 校验委托 canonical `validate_and_canonicalize_config`，禁止未知键（`DEDUPE_INVALID_CONFIG`）及保留因子（`DEDUPE_FACTOR_UNAVAILABLE`）。
- **RuntimeInputs 模式限制**:
  - `scan_job_id: int | None` 严格正整数校验（拒绝 `bool`、`<=0`、非整数）。
  - `mode == "dedupe"`: 严禁 `root_ids`，必填 `scan_job_id`（未完成报 409 `DEDUPE_SCAN_NOT_COMPLETED`，不存在报 404）。
  - `mode in ("file", "organizer")`: 严禁 `scan_job_id`。

### 2.2 Canonical Dedupe Authority Integration & Safety Policy Freeze (`app/workflows/compiler.py`)
- **零打分重写**: 直接复用 `compile_advanced_dedupe_preview` 产物与 `build_advanced_dedupe_draft_intents`。
- **单次请求安全快照冻结**: 一次性冻结 `(protect_last_file, allowed_roots, quarantine_root)` 并规范化为 `effective_safety_policy`，贯穿 Preview、Compile Digest 与 Metadata。
- **Workflow Compile Digest 计算**: 严格绑定 6 项要素：
  1. `workflow_id`
  2. `workflow_revision`
  3. `definition_sha256`
  4. `runtime_inputs.scan_job_id`
  5. `dedupe preview_digest`
  6. deterministic compiled quarantine operations
  （分页与 `only_changed` 过滤不改变 `compile_digest` / `preview_digest`）。

### 2.3 Preview & Plan Generation (`app/workflows/service.py`)
- **Dedupe Preview (`POST /api/workflows/{id}/preview`)**:
  - 分页单位为 member 决策行，支持 `only_changed=true`（仅返回 `QUARANTINE` 变更行）。
  - 返回 `preview_source="completed-scan-readonly-safety"`，保证 0 副作用、0 mutation。
- **Dedupe Generate Plan (`POST /api/workflows/{id}/generate-plan`)**:
  - **Phase A**: 只读重编译并严格比对 `expected_compile_digest`，不一致即报 409 `PREVIEW_CHANGED`，0 产生 draft。
  - **Phase B**: `BEGIN IMMEDIATE` 短事务：
    - 校验 Workflow 存在性及非归档状态（被归档报 409 `WORKFLOW_ARCHIVED`）。
    - 校验 Revision SHA 未被篡改。
    - 校验 `compute_current_dedupe_db_lineage_digest` 一致性（并发篡改报 409 `PREVIEW_CHANGED`）。
    - 原子持久化 1 个 `BatchPlan(status="draft")`，写入完整血缘元数据（`source="workflow"`, `workflow_mode="dedupe"`, `scan_job_id == runtime_inputs["scan_job_id"]`）。
    - 原子持久化 `BatchPlanItem`，真实持久化 `keep_path` 数据库列，Gate3 identity 初始化为零（`expected_device=0, inode=0, mtime_ns=0, expected_hash=None`）。

### 2.4 Stale Dedupe Rebuild Guard (`app/service.py`)
- 在 `_validate_rebuild_eligibility` 中识别 `workflow_mode == "dedupe"`，对于 `/plans/{id}/rebuild-preview` 与 `/plans/{id}/rebuild` 请求，一律返回 409 `DEDUPE_RESCAN_REQUIRED`，杜绝复用历史 scan 重建去重计划。

---

## 3. Scope & Production Changes Audit (修改范围审计)

```text
 M app/service.py
 M app/workflows/compiler.py
 M app/workflows/errors.py
 M app/workflows/schema.py
 M app/workflows/service.py
 M app/workflows/validation.py
 A tests/test_gate5d_d3_workflow_dedupe.py
```

未引入任何数据库迁移，未引入任何外部库，未修改前端 D4、Worker 执行协议、Gate3 物理身份模型。

---

## 4. Verification Evidence (验证执行事实记录)

### 4.1 D3 针对性验收套件（22 项全覆盖，27 个测试用例全部通过）
```bash
docker exec -e PYTHONPATH=. nas-test-env pytest tests/test_gate5d_d3_workflow_dedupe.py -v
```
```text
tests/test_gate5d_d3_workflow_dedupe.py::test_1_dedupe_workflow_valid_single_step PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_1_dedupe_workflow_rejects_empty_steps PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_1_dedupe_workflow_rejects_multiple_steps PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_1_dedupe_workflow_rejects_forbidden_step_combinations[forbidden_step0] PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_1_dedupe_workflow_rejects_forbidden_step_combinations[forbidden_step1] PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_1_dedupe_workflow_rejects_forbidden_step_combinations[forbidden_step2] PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_1_dedupe_workflow_rejects_forbidden_step_combinations[forbidden_step3] PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_1_dedupe_workflow_rejects_forbidden_step_combinations[forbidden_step4] PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_1_dedupe_workflow_rejects_forbidden_step_combinations[forbidden_step5] PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_1_dedupe_workflow_rejects_forbidden_step_combinations[forbidden_step6] PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_2_file_and_organizer_modes_reject_dedupe_step PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_3_dedupe_workflow_validates_scorer_config PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_4_runtime_inputs_strict_scan_job_id PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_5_mode_specific_input_restrictions PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_6_direct_d2_and_workflow_dedupe_parity PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_7_preview_pagination_invariance PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_8_preview_only_changed_invariance PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_9_compile_digest_sensitivity PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_10_generate_plan_mismatch_returns_409_zero_plans PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_11_to_15_generate_draft_plan_and_invariants PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_16_phase_a_b_db_race_detection PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_17_archive_race_detection PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_18_historical_revision_preview_and_generate PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_19_stale_dedupe_rebuild_guard PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_20_delete_scan_blocked_by_workflow_dedupe_plan PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_21_gate3_freeze_and_validate_lifecycle PASSED
tests/test_gate5d_d3_workflow_dedupe.py::test_22_modified_keep_file_fails_closed PASSED
======================== 27 passed, 2 warnings in 2.55s ========================
```

### 4.2 关联回归套件（226 passed, 0 failures）
```bash
docker exec -e PYTHONPATH=. nas-test-env pytest tests/test_workflow*.py tests/test_gate5c*.py tests/test_gate5d*.py -v
```
```text
======================= 226 passed, 2 warnings in 20.65s =======================
```

### 4.3 全量后端回归套件（803 passed, 0 failures）
```bash
docker exec -e PYTHONPATH=. nas-test-env pytest -o addopts="" --disable-warnings -q
```
```text
803 passed, 20 warnings in 87.78s (0:01:27)
```

### 4.4 前端类型与构建检查（Typecheck & Build 100% 通过）
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
✓ built in 3.81s
```

---

## 5. Current State Declaration (当前阶段声明)

本轮 NAS File Center v0.3.5 Gate5-D / D3 阶段目标已完全实现并通过严格验证。

**阶段声明**：
`D3 IMPLEMENTATION COMPLETE / READY FOR INDEPENDENT REVIEW`
（未越权声明 PASS/CLOSED，未进入 D4 前端工作流实现）。
