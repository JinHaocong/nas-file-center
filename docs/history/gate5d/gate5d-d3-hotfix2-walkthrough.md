# NAS File Center v0.3.5 Gate5-D / D3-hotfix2 — Implementation & Verification Walkthrough

## 1. Commit Baseline & Identity (基线与提交身份)

- **Baseline Commit / ZIP Comment**: `6462c3b92b527348439454670cc496ad9f0d808a`
- **Baseline Artifact SHA256**: `04c347e408381460662c25105f68f54f3c49f11a98874e99bbc304b66dd4c983`
- **Implementation Commit**: `8a0e9e2b173167a505bfae155bcbf1e16f3964db`
- **Final Handoff Commit**: *(待提交后更新)*

---

## 2. Commit History in this Stage (本阶段提交历史)

```text
8a0e9e2 fix(gate5d): require explicit dedupe workflow scorer_config (d3-hotfix2)
6462c3b docs(gate5d): hand off d3-hotfix1 for independent review
```

---

## 3. Diff Scope (修改范围审计)

```text
 app/workflows/schema.py                 |  34 +++++-
 tests/test_gate5d_d3_workflow_dedupe.py | 189 ++++++++++++++++++++++++++++++++
 2 files changed, 222 insertions(+), 1 deletion(-)
```

### Production Changes:
- **`app/workflows/schema.py`**:
  - `DedupeStep`: 将 `scorer_config: dict[str, Any] = Field(default_factory=dict)` 改为严格 required `scorer_config: dict[str, Any]`，完全符合 `Gate5-D-D3-Architecture-Freeze-2026-09-08.md` 冻结 schema。
  - 新增 `@model_validator(mode="before") validate_explicit_scorer_config`：
    - 针对非 dedupe 步骤类型自动放行，避免干扰 Union 分发。
    - 当为 dedupe step 时，若 raw payload 缺失 `"scorer_config"` 或 `"scorer_config"` 不是字典（如 None, int, str），直接抛出 `WorkflowValidationError(..., code="DEDUPE_INVALID_CONFIG", status_code=422)`。
    - 保留显式 `"scorer_config": {}` 的合法性，继续规范化为已有 D2 默认 canonical 配置。

---

## 4. RED & GREEN Evidence (红绿测试证据)

### A. Create missing scorer_config rejected (Test 33)
- **RED Evidence**:
  ```python
  res = client.post("/api/workflows", json={
      "name": "Missing Scorer Create WF",
      "definition": {"schema_version": 1, "mode": "dedupe", "steps": [{"id": "d1", "type": "dedupe"}]}
  })
  assert res.status_code == 422
  ```
  **失败输出**: `assert 201 == 422`（原实现静默填充默认空配置并创建了工作流）。
- **GREEN Evidence**:
  返回 `HTTP 422` 且 `error.code == "DEDUPE_INVALID_CONFIG"`；数据库严格验证 `Workflow` 与 `WorkflowRevision` 计数为 0，事务完整一致。

### B. Update missing scorer_config rejected (Test 34)
- **RED Evidence**:
  合法 revision 1 工作流执行 PUT 更新，payload 省略 `scorer_config`：
  ```python
  up_res = client.put(f"/api/workflows/{wf_id}", json={
      "expected_current_revision": 1,
      "definition": {"schema_version": 1, "mode": "dedupe", "steps": [{"id": "d1", "type": "dedupe"}]}
  })
  assert up_res.status_code == 422
  ```
  **失败输出**: `assert 200 == 422`（原实现错误接受并生成了 revision 2）。
- **GREEN Evidence**:
  返回 `HTTP 422` 且 `error.code == "DEDUPE_INVALID_CONFIG"`；工作流 `current_revision` 保持 1，总版本数严格保持 1，`name`、`description` 和 `definition_sha256` 均未被变更。

### C. Explicit empty scorer_config valid & canonicalized (Test 35)
- **GREEN Evidence**:
  显式传递 `"scorer_config": {}` 成功创建工作流（HTTP 201），数据库保存的 revision definition 包含完整的 canonical 配置（`selection_mode == "weighted"`，包含 `factors` 完整字段）。

### D. Historical / saved canonical config preview & generate (Test 36)
- **GREEN Evidence**:
  创建的规范去重工作流可正常执行 Preview（返回 `workflow_mode="dedupe"`，`dedupe_summary.preview_digest` 存在）与 Generate（匹配 `expected_compile_digest`，成功生成 draft 状态计划，`plan_id > 0`）。

---

## 5. Verification Execution Evidence (验证执行记录)

### 5.1 D3-hotfix2 单元测试套件（41 个测试全部通过，新增 4 个）
```bash
docker exec -e PYTHONPATH=. nas-test-env pytest -o addopts="" -q tests/test_gate5d_d3_workflow_dedupe.py
```
```text
.........................................                                [100%]
41 passed, 2 warnings in 4.70s
```

### 5.2 聚焦回归套件（15 个测试文件，240 passed, 0 failures）
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
........................................................................ [ 60%]
........................................................................ [ 90%]
........................                                                 [100%]
240 passed, 2 warnings in 21.30s
```

### 5.3 全量后端回归套件（817 passed, 0 failures，基线 813 -> 817）
```bash
docker exec -e PYTHONPATH=. nas-test-env pytest -o addopts="" --disable-warnings -q
```
```text
817 passed, 20 warnings in 93.20s (0:01:33)
```

### 5.4 前端验证（0 生产代码变更，Typecheck & Build 100% 通过）
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
✓ built in 3.97s
```

### 5.5 Docker & Smoke 验证
- **`linux/amd64` Docker 构建**:
  `docker build --platform linux/amd64 -t nas-file-center:d3-hotfix2-smoke .` (完成并导出镜像)
- **API Health Smoke**:
  `curl -i http://localhost:8089/health`
  `HTTP/1.1 200 OK`
  `{"status":"ok","allow_mutation":false,"allow_delete":false,"allowed_roots":["/data"]}`
- **Worker Recovery Smoke**:
  `python -c "from app.config import get_settings; from app.worker import recover_running_jobs; print('Worker recovery OK:', recover_running_jobs(get_settings()))"`
  `Worker recovery OK: 0`

---

## 6. Known Limitations (已知局限性说明)

- 本阶段聚焦于 Dedupe Workflow `scorer_config` 显式 required 契约修复，前端工作流交互属于 D4 阶段，本阶段前端生产代码 0 改动。
- 去重工作流 definition 必须包含显式 `"scorer_config": {}`，完全省略将被结构化错误 `DEDUPE_INVALID_CONFIG` 拒绝。

---

## 7. Current State Declaration (阶段声明)

**`D3-hotfix2 IMPLEMENTATION COMPLETE / READY FOR INDEPENDENT REVIEW`**

*(未声明 PASS / CLOSED，未进入 D4)*
