# NAS File Center v0.3.5 Gate5-D / D2-B2-hotfix2 — Implementation & Verification Walkthrough

## 1. Commit Baseline & Identity (基线与提交身份)

- **Baseline Commit / ZIP Comment**: `bfc9d2b7f09ff645438aebd64f61192a12a2ee30`
- **Baseline Artifact SHA256**: `00876d1207c55d7ba3b9df624b09d4442b8bd8b15229346f078a05b78340f136`
- **Hotfix Implementation Commit**: `44f262f7902092dd97eec43b18568603fe6858e7`

---

## 2. Issue Addressed & Fix Details (修复清单)

### 2.1 Blocker: Legacy Non-Object Request Validation Compatibility
- **问题原因**：
  在 `app/api/router.py` 的 `DedupePlanRequest.validate_request_shape()` 中，此前包含：
  ```python
  if type(raw) is not dict:
      raise DedupeInvalidConfigError(
          "Dedupe plan request must be a JSON object",
          details={"field": "body"},
      )
  ```
  该逻辑导致请求体为非 JSON object（例如 `[]`、`"x"`、`123`、`true`）时抛出 `DedupeInvalidConfigError`，触发全局处理返回带有 `"error"` 的高级结构化信封，破坏了 D2-B1-hotfix3 baseline 下返回标准 Pydantic 校验信封（HTTP 422 `{"detail": [...]}` 且无 `"error"`）的 Legacy 契约。
- **修复方案**：
  在 `DedupePlanRequest.validate_request_shape` 中，如果 `type(raw) is not dict`，直接 `return raw`，不抛出异常，让 Pydantic BaseModel 原生校验机制处理非字典类型并生成标准的 `{"detail": [...]}` 校验错误。
  这在保持 Advanced 严格性（非字典 body 绝无法携带 `scorer_config`）的同时，完全恢复了 baseline 对非对象请求的 Legacy 校验行为。

---

## 3. Scope & Production Changes Audit (修改范围审计)

```bash
git diff --name-status bfc9d2b7f09ff645438aebd64f61192a12a2ee30..44f262f7902092dd97eec43b18568603fe6858e7
```
```text
M	app/api/router.py
M	tests/test_gate5d_dedupe_generate_api.py
```

生产代码修改仅涉及 `app/api/router.py`（4 行替换为 2 行），测试代码仅在 `tests/test_gate5d_dedupe_generate_api.py` 新增 1 个参数化测试（覆盖 4 种非对象类型）。未改动 `app/main.py` 及任何其他文件。

---

## 4. Verification Evidence (验证执行事实记录)

### 4.1 TDD RED / GREEN 周期
- **RED 阶段**：新增参数化测试 `test_legacy_non_object_body_preserves_baseline_pydantic_validation`，对 `[]`, `"x"`, `123`, `True` 4 种非对象 body 执行请求，观察到全部失败（返回了结构化 `"error"` 而非标准 `"detail"`）：
  ```text
  FAILED tests/test_gate5d_dedupe_generate_api.py::test_legacy_non_object_body_preserves_baseline_pydantic_validation[body0]
  FAILED tests/test_gate5d_dedupe_generate_api.py::test_legacy_non_object_body_preserves_baseline_pydantic_validation[x]
  FAILED tests/test_gate5d_dedupe_generate_api.py::test_legacy_non_object_body_preserves_baseline_pydantic_validation[123]
  FAILED tests/test_gate5d_dedupe_generate_api.py::test_legacy_non_object_body_preserves_baseline_pydantic_validation[True]
  ```
- **GREEN 阶段**：更新 `app/api/router.py` 后，该测试用例及全部 33 项 API 测试 100% 通过：
  ```text
  ======================== 33 passed, 2 warnings in 4.17s ========================
  ```

### 4.2 针对性回归套件 (Focused Regression)
```bash
docker exec -e PYTHONPATH=. nas-test-env pytest -o addopts="" \
  tests/test_gate5d_dedupe_generate_api.py \
  tests/test_gate5d_dedupe_generate.py \
  tests/test_gate5d_dedupe_preview_api.py \
  tests/test_gate5d_dedupe_preview_compiler.py \
  tests/test_planning.py
```
> **结果**：`112 passed, 2 warnings in 13.91s`

### 4.3 全量后端回归测试 (Full Backend Regression)
```bash
docker exec -e PYTHONPATH=. nas-test-env pytest -o addopts="" --disable-warnings -q
```
> **结果**：`776 passed, 20 warnings in 84.10s (0:01:24)`（全量 776 项测试通过，0 失败）

### 4.4 前端零修改回归 (Frontend Regression)
```bash
cd frontend && npm run typecheck && npm run build
```
> **结果**：
> - `npm run typecheck`: 0 errors
> - `npm run build`: built in 3.95s
> - 前端源码 0 修改

### 4.5 Docker 跨平台镜像构建与生产 Smoke (Docker Build & Smoke)
- 构建命令：`docker buildx build --platform linux/amd64 --load -t nas-file-center:d2b2-hotfix2 .`
- Smoke 验证：
  - API 容器健康检查：HTTP 200 `{"status":"ok","allow_mutation":false,"allow_delete":false,"allowed_roots":["/data"]}`
  - Worker 容器运行状态：`docker inspect -f '{{.State.Running}}' nfc-d2b2-hf2-worker` -> `true`
  - 容器及网络安全清理。

---

## 5. Known Limitations & Explicit Boundaries (边界与限制)

1. **D3 Workflow 严禁实现**：未实现 `mode=dedupe` 工作流，未修改 `app/workflows/*`。
2. **D4 Frontend 严禁实现**：未进行任何前端高级去重 UI 开发。
3. **架构保持冻结**：未修改 D2-A 编译器、DB Lineage、Phase A/B 架构、Gate3 物理身份与 DB Schema。

---

## 6. Formal Status (正式状态声明)

```text
D2-B2-hotfix2 IMPLEMENTATION COMPLETE
READY FOR INDEPENDENT REVIEW
D3 Workflow = FORBIDDEN
D4 Frontend = FORBIDDEN
```
