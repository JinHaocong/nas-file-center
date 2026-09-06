# NAS File Center v0.3.5 Gate5-B-hotfix4 — Implementation & Verification Walkthrough

## 1. Context & Scope (背景与状态)

当前正式状态：
```text
Gate2 = PASS
Gate3 = PASS
Gate4 = PASS
Gate5-A = PASS
NAS File Center v0.3.4 = CLOSED

Gate5-B-hotfix3 targeted review = PASS
Gate5-B overall = HOLD

P0 = 0
P1 = 0
P2 = 1 (P2-12 OrganizerProfileSnapshot canonical defaults / normalization mismatch) -> CLOSED
P3 = 0

Gate5-C+ = FORBIDDEN
v0.3.5 = NOT CLOSED
```

本轮任务严格限定于修复 P2-12（`OrganizerProfileSnapshot canonical defaults / normalization mismatch`），让 `OrganizerProfileSnapshot` 的默认值、字段规范化和领域语义与 `FileCenterService` 当前真实创建出来的 `OrganizerProfile` 完全一致，绝不扩大范围，绝不引入 Gate5-C 特性。

---

## 2. Issues Closed & Technical Implementation (问题关闭与技术实现)

### 2.1 P2-12 — OrganizerProfileSnapshot 领域契约与规范化对齐

- **问题根因**：
  1. **默认值与真实领域偏离**：此前 `OrganizerProfileSnapshot` 误以 ORM 模型列定义为准，将 `image_extensions` 设为空列表 `[]`、`rename_template` 设为 `"{name} {statistics}"`。但在用户通过 `FileCenterService._validate_profile_payload()` 创建默认档案时，真实默认值其实为 `image_extensions=["jpg", "jpeg", "png", "webp"]`、`video_extensions=["mp4", "mov", "mkv"]`、`rename_template="{name}"`、`statistics_template="[{images}P {videos}V {size}]"`。此差异导致最小配置的工作流会错误为目录强行追加统计后缀（例如将 `Album` 误重命名为 `Album [0P 1 B]`）。
  2. **扩展名校验与规范化缺失**：此前快照仅校验元素为字符串，未进行大写转小写与前导点去除（如 `".JPG"` 未规范化为 `"jpg"`），且未对非法字符（`/`, `\`, 空格）进行 422 拦截。
  3. **档案名称校验过宽**：此前快照仅校验 `isinstance(v, str)`，允许全空格字符串 `name="   "` 绕过校验。
  4. **标签处理分叉**：此前快照未对 `preserve_tags` 执行每个标签的 trim 操作，未丢弃空字符串，且未限制上限为 20 个标签。

- **修复实现**：
  1. **抽离统一规范化模块**：
     创建 [`app/organizers/profile_validation.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/organizers/profile_validation.py)，集中定义标准默认常量与校验函数，作为唯一的标准事实源：
     - 常量：`DEFAULT_ORGANIZER_IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp"]`、`DEFAULT_ORGANIZER_VIDEO_EXTENSIONS = ["mp4", "mov", "mkv"]`、`DEFAULT_ORGANIZER_RENAME_TEMPLATE = "{name}"`、`DEFAULT_ORGANIZER_STATISTICS_TEMPLATE = "[{images}P {videos}V {size}]"`、`DEFAULT_ORGANIZER_NUMBERING_MODE = "none"`、`DEFAULT_ORGANIZER_NUMBERING_START = 1`、`DEFAULT_ORGANIZER_NUMBERING_PADDING = 3`、`DEFAULT_ORGANIZER_MTIME_MODE = "none"`、`DEFAULT_ORGANIZER_MTIME_DELAY_SECONDS = 2.0`。
     - 校验器：`validate_profile_name()`、`normalize_preserve_tags()`、`validate_and_normalize_image_extensions()`、`validate_and_normalize_video_extensions()`、`validate_rename_template()`、`validate_statistics_template()`、`validate_profile_cleanup_patterns()`。
  2. **业务服务对齐**：
     重构 [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py) 中的 `FileCenterService._validate_profile_payload()`，全面调用上述共享验证与规范化函数，消除逻辑重复与分叉风险。
  3. **工作流快照 Schema 对齐**：
     在 [`app/workflows/schema.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/workflows/schema.py) 中更新 `OrganizerProfileSnapshot`：
     - 默认值全面对齐标准常量；
     - 增加 `validate_name` 校验器（拒绝空白名称，strip 处理）；
     - 增加 `validate_images` 与 `validate_videos` 校验器（复用扩展名规范化，非法扩展名报 422）；
     - 增加 `validate_tags` 校验器（trim、过滤空串、最多 20 个）；
     - 增加 `validate_cleanup` 校验器（复用正则模式校验）；
     - 保持原有严格的类型与数值边界（`numbering_mode`、`numbering_start >= 0`、`numbering_padding 1..10`、`mtime_mode`、`mtime_delay_seconds 0.0..60.0` 拒绝 bool）。
  4. **编译器默认值对齐**：
     在 [`app/workflows/compiler.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/workflows/compiler.py) 中将 `_compile_organizer_workflow` 的模板回退默认值统一为 `DEFAULT_ORGANIZER_RENAME_TEMPLATE`（`"{name}"`）与 `DEFAULT_ORGANIZER_STATISTICS_TEMPLATE`。
  5. **语义等价保障**：
     在目录 `/data/Album/a.jpg` 的场景下，最小快照 `{"name": "Minimal"}` 在工作流预览与直接整理档案预览中完全等价：生成 `Album -> Album`，`changed=False`，在工作流方案中产生 0 个操作，彻底杜绝意外附加统计后缀行为。

---

## 3. Verification & Evidence (验证与证据)

### 3.1 TDD 失败基线证明 (RED Evidence)
在修改代码前编写针对性失败测试 [`tests/test_gate5b_hotfix4_red.py`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_gate5b_hotfix4_red.py)，确认 5 项基线偏差在修复前全部失败：
```text
FAILED tests/test_gate5b_hotfix4_red.py::test_red_minimal_defaults_mismatch
  -> AssertionError: assert [] == ['jpg', 'jpeg', 'png', 'webp'] (default image_extensions was empty)
FAILED tests/test_gate5b_hotfix4_red.py::test_red_whitespace_name_not_rejected
  -> Failed: DID NOT RAISE ValidationError (name="   " was accepted)
FAILED tests/test_gate5b_hotfix4_red.py::test_red_extension_not_normalized
  -> AssertionError: assert ['.JPG'] == ['jpg'] (uppercase and leading dot not normalized)
FAILED tests/test_gate5b_hotfix4_red.py::test_red_invalid_extension_not_rejected
  -> Failed: DID NOT RAISE ValidationError (invalid ext "jpg/bad" was accepted)
FAILED tests/test_gate5b_hotfix4_red.py::test_red_preserve_tags_not_trimmed_and_capped
  -> AssertionError: assert len(tags) == 25 (expected 20 tags capped and trimmed)
```

### 3.2 修复后套件验证 (GREEN Evidence)
```bash
# 1. Gate5-B-hotfix4 Section 13 完整测试套件 (9 passed in 1.18s)
docker exec -e PYTHONPATH=/app nas-test-env pytest tests/test_gate5b_hotfix4.py -v
# Output: 9 passed, 2 warnings in 1.18s

# 2. Gate5-B-hotfix4 TDD RED->GREEN 验证 (5 passed in 0.19s)
docker exec -e PYTHONPATH=/app nas-test-env pytest tests/test_gate5b_hotfix4_red.py -v
# Output: 5 passed in 0.19s

# 3. Gate5-B 历史回归测试套件 (53 passed in 21.15s)
docker exec -e PYTHONPATH=/app nas-test-env pytest tests/test_gate5b_hotfix3.py tests/test_gate5b_hotfix2.py tests/test_gate5b_hotfix1_red.py tests/test_organizer_blockers_regression.py -v
# Output: 53 passed, 2 warnings in 21.15s

# 4. 工作流全集与过滤器测试 (54 passed in 2.30s)
docker exec -e PYTHONPATH=/app nas-test-env pytest tests/test_workflow_*.py tests/test_filter_*.py -q
# Output: 54 passed in 2.30s

# 5. Gate2 核心套件 (55 passed in 4.80s)
docker exec -e PYTHONPATH=/app nas-test-env pytest tests/test_gate2*.py -q
# Output: 55 passed in 4.80s

# 6. 后端全量测试套件 (601 passed in 1m 11s)
docker exec -e PYTHONPATH=/app nas-test-env pytest -q tests
# Output: 601 passed, 20 warnings in 1m 11s

# 7. 前端测试与生产打包 (177 passed in 102ms, build succeeded in 3.45s)
cd frontend && npm test -- --watchAll=false && npm run build
# Output: 177 passed in 102ms, built in 3.45s
```

### 3.3 Docker 容器黑盒端到端验收 (Blackbox Evidence)
基于生产镜像 `nas-file-center:v0.3.5-gate5b-hotfix4`，在隔离容器环境中执行黑盒验收脚本 `scratch/test_gate5b_hotfix4_blackbox_acceptance.py`：
```text
=== Starting Gate5-B-hotfix4 Blackbox Acceptance against nas-file-center:v0.3.5-gate5b-hotfix4 ===
[DEPLOY] Starting API container nas-gate5b-hf4-accept-d40511...
[DEPLOY] API container is healthy.
[AUTH] Login successful, session cookie obtained.
[SETUP] Target IndexRoot ID: 1
[CP1] Verifying minimal OrganizerProfile vs minimal Snapshot defaults...
[CP1] CP1: PASS
[CP2] Verifying minimal preview semantic equivalence (Album -> Album, changed=False)...
[CP2] CP2: PASS
[CP3] Verifying extension normalization...
[CP3] CP3: PASS
[CP4] Verifying invalid extensions rejection (422)...
[CP4] CP4: PASS
[CP5] Verifying whitespace-only name rejection (422)...
[CP5] CP5: PASS
[CP6] Verifying preserve_tags trimming and cap 20...
[CP6] CP6: PASS
[CP7] Verifying full existing OrganizerProfile round-trip...
[CP7] CP7: PASS
[CP8] Verifying sequential and ordered options in preview...
[CP8] CP8: PASS
[CP9] Verifying invalid enum / numeric cases rejection (422)...
[CP9] CP9: PASS
[CP10] Verifying SQLite integrity check...
[CP10] CP10: PASS
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
  "CP10": "PASS"
}

ALL GATE5-B-HOTFIX4 BLACKBOX ACCEPTANCE CHECKS PASSED!
```

---

## 4. Final Review Status & Artifacts (最终状态与发布制品)

```text
Gate5-B-hotfix4 implementation candidate ready for independent review.

P2-12: CLOSED

Gate5-A = PASS
Gate5-B = HOLD (Candidate Ready for Independent Review)
Gate5-C = FORBIDDEN
v0.3.5 = NOT CLOSED
```
