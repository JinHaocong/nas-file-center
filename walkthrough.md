# NAS File Center v0.3.5 Gate5-B-hotfix3 — Implementation & Verification Walkthrough

## 1. Context & Scope (背景与状态)

当前正式状态：
```text
Gate2 = PASS
Gate3 = PASS
Gate4 = PASS
Gate5-A = PASS
NAS File Center v0.3.4 = CLOSED

Gate5-B-hotfix2 requested-fixes targeted review = PASS
Gate5-B overall = HOLD

P0 = 0
P1 = 0
P2 = 1 (P2-11 OrganizerProfileSnapshot contract mismatch) -> CLOSED
P3 = 0

Gate5-C+ = FORBIDDEN
v0.3.5 = NOT CLOSED
```

本轮任务严格限定于修复 P2-11（`OrganizerProfileSnapshot contract mismatch`），让 Workflow 中的 `OrganizerProfileSnapshot` 严格等价于当前 NAS File Center 现有 `OrganizerProfile` 的真实领域契约，绝不扩大范围，绝不引入 Gate5-C 特性。

---

## 2. Issues Closed & Technical Implementation (问题关闭与技术实现)

### 2.1 P2-11 — OrganizerProfileSnapshot 契约对齐与规范化

- **问题根因**：
  1. **枚举错位**：此前 Snapshot 中 `numbering_mode` 声明为 `"per_folder" | "continuous" | "none"`，而真实 Organizer 引擎仅支持 `"none" | "sequential"`，导致合法的 `"sequential"` 被错误拦截（422），而错误的 `"continuous"` 被错误接受；同理，`mtime_mode` 此前声明为 `"preserve" | "delay" | "current" | "none"`，而真实引擎仅支持 `"none" | "ordered"`。
  2. **边界与类型缺失**：`numbering_start` 缺少 `>= 0` 约束，`numbering_padding` 缺少 `1..10` 约束；`mtime_delay_seconds` 允许 `bool`（Pydantic 自动将 `True` 强转为 `1.0`）及超出 `0.0..60.0` 的非法浮点数。
  3. **默认值不一致**：此前 Snapshot 默认 `recursive=True`、`rename_template="{name}"`、`numbering_padding=4`、`mtime_delay_seconds=0.0`，与现有 OrganizerProfile 默认值严重不一致。
  4. **编译器多余宽容清洗**：`_compile_organizer_workflow()` 中仍存在针对字符串格式扩展名/标签的 `json.loads()` 容错 fallback，破坏了强类型 Recipe 的设计原则。

- **修复实现**：
  1. 在 [`app/workflows/schema.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/workflows/schema.py) 中全面重构 `OrganizerProfileSnapshot`：
     - **枚举约束**：
       - `numbering_mode: Literal["none", "sequential"] = "none"`
       - `mtime_mode: Literal["none", "ordered"] = "none"`
     - **数值与边界强校验**：
       - `numbering_start: int = 1`：严格校验 `type(v) is int`（拒绝 `bool`），要求 `v >= 0`；
       - `numbering_padding: int = 3`：严格校验 `type(v) is int`（拒绝 `bool`），要求 `1 <= v <= 10`；
       - `mtime_delay_seconds: float = 2.0`：严格校验 `type(v) in {int, float}`（拒绝 `bool`），要求有限数值且 `0.0 <= v <= 60.0`；
       - `recursive: bool = False`：严格校验纯布尔类型（拒绝字符串伪造）。
     - **模板与列表深层验证**：
       - `rename_template: str = "{name} {statistics}"` 复用 `validate_template(v, ALLOWED_RENAME_VARS)`；
       - `statistics_template: str = "[{images}P{?videos: {videos}V} {size}]"` 复用 `validate_template(v, ALLOWED_STATISTICS_VARS)`；
       - `cleanup_patterns` 复用 `validate_cleanup_patterns(v)`；
       - 列表字段 `image_extensions`、`video_extensions`、`preserve_tags` 严格校验为纯字符串列表（拒绝 raw string、number、bool 元素）。
  2. 在 [`app/workflows/compiler.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/workflows/compiler.py) 中：
     - 彻底移除 `json.loads(...)` 容错清洗逻辑，编译器直接信任经过不可变验证的 Recipe 快照；
     - 修复 `numbering_start` / `mtime_delay_seconds` 采用 `or` 时误将 `0` 判定为 falsy 并回退默认值的潜在问题。

---

## 3. Verification & Evidence (验证与证据)

### 3.1 TDD 失败基线证明 (RED Evidence)
在实现前编写针对性测试 [`tests/test_gate5b_hotfix3_red.py`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_gate5b_hotfix3_red.py)，完整复现了契约不一致的失败证据：
```text
FAILED tests/test_gate5b_hotfix3_red.py::test_sequential_snapshot_accepted
  -> ValidationError: Input should be 'per_folder', 'continuous' or 'none' (sequential rejected)
FAILED tests/test_gate5b_hotfix3_red.py::test_ordered_snapshot_accepted
  -> ValidationError: Input should be 'preserve', 'delay', 'current' or 'none' (ordered rejected)
FAILED tests/test_gate5b_hotfix3_red.py::test_continuous_snapshot_rejected
  -> Failed: DID NOT RAISE ValidationError (continuous accepted)
FAILED tests/test_gate5b_hotfix3_red.py::test_delay_snapshot_rejected
  -> Failed: DID NOT RAISE ValidationError (delay accepted)
FAILED tests/test_gate5b_hotfix3_red.py::test_numbering_padding_1000_rejected
  -> Failed: DID NOT RAISE ValidationError (padding 1000 accepted)
FAILED tests/test_gate5b_hotfix3_red.py::test_numbering_start_negative_rejected
  -> Failed: DID NOT RAISE ValidationError (start -5 accepted)
FAILED tests/test_gate5b_hotfix3_red.py::test_mtime_delay_seconds_bool_rejected
  -> Failed: DID NOT RAISE ValidationError (delay=True accepted)
```

### 3.2 修复后套件验证 (GREEN Evidence)
```bash
# 1. Gate5-B-hotfix3 CP1~CP11 完整测试套件 (11 passed in 1.34s)
docker exec -e PYTHONPATH=/app nas-test-env pytest tests/test_gate5b_hotfix3.py -v
# Output: 11 passed, 2 warnings in 1.34s

# 2. Gate5-B-hotfix3 专属 RED 验证测试 (7 passed in 0.05s)
docker exec -e PYTHONPATH=/app nas-test-env pytest tests/test_gate5b_hotfix3_red.py -v
# Output: 7 passed, 0 warnings in 0.05s

# 3. Gate5-B-hotfix2 回归测试 (6 passed in 0.90s)
docker exec -e PYTHONPATH=/app nas-test-env pytest tests/test_gate5b_hotfix2.py -v
# Output: 6 passed, 2 warnings in 0.90s

# 4. Gate5-B-hotfix1 回归与整理方案回归测试 (36 passed in 19.61s)
docker exec -e PYTHONPATH=/app nas-test-env pytest tests/test_gate5b_hotfix1_red.py tests/test_organizer_blockers_regression.py -v
# Output: 36 passed, 2 warnings in 19.61s

# 5. 工作流全集与过滤器测试 (54 passed in 2.34s)
docker exec -e PYTHONPATH=/app nas-test-env pytest tests/test_workflow_*.py tests/test_filter_*.py -v
# Output: 54 passed, 2 warnings in 2.34s

# 6. Gate2 核心套件 (55 passed)
docker exec -e PYTHONPATH=/app nas-test-env pytest tests/test_gate2*.py -q
# Output: 55 passed in 5.61s

# 7. 后端全量测试套件 (587 passed in 1m 09s)
docker exec -e PYTHONPATH=/app nas-test-env pytest -q tests
# Output: 587 passed, 20 warnings in 1m 09s

# 8. 前端测试与生产打包 (177 passed in 102ms, build succeeded in 3.46s)
cd frontend && npm test && npm run build
# Output: 177 passed in 102ms, built in 3.46s
```

### 3.3 Docker 容器黑盒端到端验收 (Blackbox Evidence)
全新构建生产镜像 `nas-file-center:v0.3.5-gate5b-hotfix3`，并在隔离容器环境中执行黑盒验收脚本 `scratch/test_gate5b_hotfix3_blackbox_acceptance.py`：
```text
=== Starting Gate5-B-hotfix3 Blackbox Acceptance against nas-file-center:v0.3.5-gate5b-hotfix3 ===
[DEPLOY] Starting API container nas-gate5b-hf3-accept-2fadb7...
[DEPLOY] API container is healthy.
[AUTH] Login successful, session cookie obtained.
[SETUP] Target IndexRoot ID: 1
[CP1] Verifying sequential snapshot accepted (201)...
[CP1] CP1: PASS
[CP2] Verifying ordered snapshot accepted (201)...
[CP2] CP2: PASS
[CP3] Verifying continuous / per_folder rejected (422)...
[CP3] CP3: PASS
[CP4] Verifying delay / preserve / current rejected (422)...
[CP4] CP4: PASS
[CP5] Verifying numbering bounds rejected (422)...
[CP5] CP5: PASS
[CP6] Verifying bool/string delay seconds rejected (422)...
[CP6] CP6: PASS
[CP7] Verifying existing OrganizerProfile -> snapshot roundtrip...
[CP7] CP7: PASS
[CP8] Verifying direct Organizer plan vs Workflow snapshot plan semantic equivalence...
[CP8] CP8: PASS
[CP9] Verifying live Profile mutation isolation...
[CP9] CP9: PASS
[CP10] Verifying zero unexpected filesystem mutation...
[CP10] CP10: PASS
[CP11] Verifying SQLite integrity and recipe immutability...
[CP11] CP11: PASS
[SUMMARY] Final Report: {
  "CP1": "PASS",
  "CP2": "PASS",
  "CP3": "PASS",
  "CP4": "PASS",
  "CP5": "PASS",
  "CP6": "PASS",
  "CP7": "PASS",
  "CP8": "PASS",
  "CP9": "PASS",
  "CP10": "PASS",
  "CP11": "PASS"
}

ALL GATE5-B-HOTFIX3 BLACKBOX ACCEPTANCE CHECKS PASSED!
```

---

## 4. Final Review Status & Artifacts (最终状态与发布制品)

```text
Gate5-B-hotfix3 implementation candidate ready for independent review.

P2-11: CLOSED

Gate5-A = PASS
Gate5-B = HOLD (Candidate Ready for Independent Review)
Gate5-C = FORBIDDEN
v0.3.5 = NOT CLOSED
```
