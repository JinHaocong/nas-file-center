# NAS File Center v0.3.5 Gate5-D / D2-B2-hotfix1 — Implementation & Verification Walkthrough

## 1. Commit Baseline & Identity (基线与提交身份)

- **Baseline Commit / ZIP Comment**: `152aa4d95bc2f0fe37a3508ba52c107896ab860e`
- **Baseline Artifact SHA256**: `5644c2e14d644029ea5ecaa75bb1014ce18d5e41f20129b1e1da5fc8f2235c99`
- **Hotfix Implementation Commit**: `39bbf455b5d19c36203cf65a1bc81dbe598bf0d8`

---

## 2. Issues Addressed & Fix Details (修复清单)

### 2.1 BLOCKER 1: Advanced `scorer_config` Error Mapping
- **问题原因**：
  在 `POST /api/scans/{scan_job_id}/dedupe-plan` 中，若请求体形状合法但 `scorer_config` 内容非法（如无效的 `selection_mode`、保留因子 `resolution`、因子为 `None` 等），底层编译模块抛出 `ValueError`。此前的实现直接落入外层 `except ValueError as exc: raise HTTPException(409, str(exc))`，导致高级去重生成错误地返回 HTTP 409 `{"detail": "..."}`，破坏了与 D2-B1 `/dedupe-preview` 一致的结构化错误契约。
- **修复方案**：
  在 `app/api/router.py` 的 `create_dedupe_plan` 路由中，对 `payload.is_advanced` 分支包裹独立的 `try...except ValueError`，沿用与 `/dedupe-preview` 严格一致的映射逻辑：
  - `DEDUPE_FACTOR_UNAVAILABLE` -> `DedupeFactorUnavailableError` (HTTP 422)
  - `DEDUPE_LIMIT_EXCEEDED` -> `DedupeLimitExceededError` (HTTP 422)
  - 其余配置校验异常 -> `DedupeInvalidConfigError` (HTTP 422)
  返回标准统一结构体：`{"error": {"code": "...", "message": "...", "details": {...}}}`。
  同时保留 Legacy 路径外层的 `ValueError -> 409` 行为完全不变。

### 2.2 BLOCKER 2: Legacy Request Compatibility & Validation Envelope Restoration
- **问题原因**：
  1. `DedupePlanRequest` 此前设置了全局 `model_config = ConfigDict(extra="forbid")` 并将 `policy` 声明为 `str | None = None`，导致：
     - `{"policy": null}` 被错误接受并回退到默认策略进入执行，破坏了 hotfix3 baseline 的 422 校验失败契约；
     - `{"policy": "balanced-roots", "unexpected": true}` 被错误拦截为 422 `extra_forbidden`，而 baseline 行为应忽略额外字段并正常执行。
  2. `app/main.py` 的 `validation_exception_handler` 将全局结构化信封扩展至 `or "/dedupe-plan" in request.url.path`，改变了 Legacy 请求遇到 Pydantic 校验错误时的报错格式（baseline 应为 `{"detail": [...]}`）。
- **修复方案**：
  1. 在 `DedupePlanRequest` 移除全局 `extra="forbid"`，将字段恢复为基线语义：
     `policy: str = "balanced-roots"`，以此恢复 Legacy 请求中对 `policy: null` 的 422 校验拒绝以及对未定义额外字段的默认忽略。
  2. 在 `model_validator(mode="before")` 中实现针对 Advanced 请求的 Fail-Closed 校验：
     当 `scorer_config` 存在时，严格只允许 `scorer_config` 和 `expected_preview_digest` 两项键，出现任何 Legacy 字段或未知字段立即抛出 `DedupeInvalidConfigError` (HTTP 422 结构化错误)。
  3. 在 `app/main.py` 中将通用错误信封恢复为仅限定于 `"/dedupe-preview"`。Advanced 的形状校验失败通过 `DedupeInvalidConfigError`（继承自 `DedupeError`）经由已有 handler 自动输出结构化信封，Legacy 的 Pydantic 校验失败则恢复为 baseline 的 `{"detail": [...]}`。

---

## 3. Production Changes & Scope Audit (代码修改审计)

```text
git diff --name-status 152aa4d95bc2f0fe37a3508ba52c107896ab860e..39bbf455b5d19c36203cf65a1bc81dbe598bf0d8

M	app/api/router.py
M	app/main.py
M	tests/test_gate5d_dedupe_generate_api.py
```

生产代码修改严格限定在 `app/api/router.py` 与 `app/main.py` 两个文件。

---

## 4. Verification Evidence (验证执行事实记录)

### 4.1 TDD RED / GREEN 事实
在实现前新增 5 组回归测试并确认失败（RED）：
- `test_advanced_invalid_scorer_config_selection_mode_returns_422_structured`: `409 != 422`
- `test_advanced_reserved_factor_returns_422_factor_unavailable`: `409 != 422`
- `test_advanced_factors_null_returns_422_structured`: `409 != 422`
- `test_legacy_policy_null_returns_422_validation_error_and_does_not_call_service`: `200 != 422`
- `test_legacy_unknown_extra_field_ignored_and_calls_service`: `422 != 200`

修复后执行全部 29 项 API 测试全部通过（GREEN）：
```text
======================== 29 passed, 2 warnings in 3.93s ========================
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
> **结果**：`108 passed, 2 warnings in 13.18s`

### 4.3 全量后端回归测试 (Full Backend Regression)
```bash
docker exec -e PYTHONPATH=. nas-test-env pytest -o addopts="" --disable-warnings -q
```
> **结果**：`772 passed, 20 warnings in 85.05s (0:01:25)`（全部 772 项测试通过，0 失败）

### 4.4 前端零改动回归测试 (Frontend Regression)
```bash
cd frontend && npm run typecheck && npm run build
```
> **结果**：
> - `npm run typecheck`: 0 errors
> - `npm run build`: built in 3.71s
> - 前端源码 0 修改

### 4.5 Docker 跨平台构建与生产 Smoke (Docker Build & Smoke)
- 构建命令：`docker buildx build --platform linux/amd64 --load -t nas-file-center:d2b2-hotfix1 .`
- Smoke 结果：
  - API 容器健康检查：HTTP 200 `{"status":"ok","allow_mutation":false,"allow_delete":false,"allowed_roots":["/data"]}`
  - Worker 容器运行状态：`docker inspect -f '{{.State.Running}}' nfc-d2b2-hf1-worker` -> `true`
  - 临时容器与网络清理完毕。

---

## 5. Known Limitations & Explicit Boundaries (边界与限制)

1. **D3 Workflow 严禁实现**：未实现 `mode=dedupe` 工作流，未修改 `app/workflows/*`。
2. **D4 Frontend 严禁实现**：未进行任何前端高级去重 UI 开发。
3. **架构与底层算法保持冻结**：未触动 D2-A 编译器、DB Lineage 算法、Phase A/B 架构、Gate3 物理身份边界与数据库模型定义。

---

## 6. Formal Status (正式状态声明)

```text
D2-B2-hotfix1 IMPLEMENTATION COMPLETE
READY FOR INDEPENDENT REVIEW
D3 Workflow = FORBIDDEN
D4 Frontend = FORBIDDEN
```
