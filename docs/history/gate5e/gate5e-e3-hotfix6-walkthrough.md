# Gate5-E / E3-hotfix6 Walkthrough: Wrapper Scan Authority + Canonical Action Closure

## 1. 任务背景与目标

在 E3-hotfix5 独立评审中，发现了以下两处闭环 blocker：

1. **Wrapper 扫描权限与异常语义不一致（Inconsistent Wrapper Scan Authority）**：
   - 在 Phase-A 期间，Wrapper 目录会在 3 个阶段进行扫描：
     1) 直接子项发现（Discovery）：`discover_flatten_one_level`；
     2) Wrapper 快照直接子项枚举捕获（Snapshot）：`compile_flatten_one_level_preview`；
     3) 图连续性重扫描（Continuity）：`resolve_flatten_graph` 中的 `_validate_wrapper`。
   - 此前三阶段的 `OSError` 语义不统一：
     - Snapshot 阶段捕获 `OSError` 后静默将 `children` 置空并记录 `scan_status = "OK"`；
     - Continuity 阶段将 `scandir` 产生的 `OSError` 转换为普通的 `WRAPPER_IDENTITY_CHANGED` 冲突并返回 HTTP 200 预览。
   - 根据 E3 冻结契约，所选 wrapper 无法被枚举属于配置/范围权限故障（Scope/Config Authority Failure），严禁作为空目录或普通冲突处理，必须 fail-closed 抛出 `BatchUtilityInvalidConfigError`（HTTP 422 `BATCH_UTILITY_INVALID_CONFIG`，包含 `wrapper_path`、`errno`、`stage`），生成 0 Draft。

2. **规范化 Wrapper Action 配置与摘要闭包（Canonical Wrapper Action Config & Digest Closure）**：
   - 此前 `canonical_action` 与 `action_config_digest` 绑定了原始表示语法，例如 `"/root/W"` 与 `"/root/W/"` 会产生不同的 digest，打破了相同实际动作语义的等价性。
   - 需要统一单点规范化实现：统一在 `app/batch_utilities/digest.py` 中处理，保证冗余分隔符、尾随斜杠、`..` 规范化为唯一规范形式，同时保持符号链接敏感性、输入顺序不敏感性及重复路径拒绝。
   - 计划元数据 `plan_metadata["wrapper_paths"]` 需使用完全相同的规范表示，`db_lineage_digest` 保持 `None`。

---

## 2. 核心改动

### 2.1 `app/batch_utilities/digest.py`
- 新增 `canonicalize_wrapper_path(path: str) -> str`：
  - 规范化冗余分隔符、尾随斜杠以及 `.` / `..`；
  - 若路径存在且为真实目录（非符号链接），解析为严格规范路径；
  - 若路径为符号链接，保留其路径不进行解引用，确保后续预检安全机制能够准确拦截符号链接。
- 重构 `canonicalize_flatten_one_level_action(action: FlattenOneLevelAction) -> dict[str, Any]`：
  - 对 `action.wrapper_paths` 进行规范化；
  - 校验规范化后的路径是否包含重复项，若重复则抛出 `BatchUtilityScopeOverlapError`；
  - 对规范化后的路径进行排序（`sorted`），确保输入顺序不影响动作标识；
  - 使得 `canonicalize_batch_utility_action` 与 `compute_action_config_digest` 自动消费此规范化结果。

### 2.2 `app/batch_utilities/compiler.py`
- 在 `compile_flatten_one_level_preview` 中：
  - 优先对原始 `action.wrapper_paths` 执行 `validate_wrappers_preflight`，确保 raw paths 符号链接与跨 root 检查不被绕过；
  - 通过 `canonicalize_flatten_one_level_action(action)` 获取规范化动作与 `canonical_wrappers`；
  - 在 wrapper observations 直接子项扫描时，捕获 `OSError` 统一抛出：
    ```python
    raise BatchUtilityInvalidConfigError(
        f"Failed to scan wrapper directory '{w_lex}': {e}",
        details={
            "wrapper_path": w_lex,
            "errno": getattr(e, "errno", None),
            "stage": "SNAPSHOT",
        },
    )
    ```
  - 严禁静默 fallback 为 `children = []` 或标记 `scan_status = "OK"`。

### 2.3 `app/batch_utilities/flatten.py`
- 在 `discover_flatten_one_level` 中捕获 `OSError` 时，在 details 中补全 `"stage": "DISCOVERY"`，确保三阶段详情结构统一。

### 2.4 `app/batch_utilities/flatten_graph.py`
- 在 `validate_wrappers_preflight` 中增加对 `norm_lex = os.path.normpath(w_lex)` 的 `os.lstat` 检查，防止尾随斜杠导致底层系统对符号链接隐式解引用为目录而绕过符号链接检查；
- 在 `resolve_flatten_graph` 的 `_validate_wrapper` 中，重扫描捕获 `OSError` 时，不再转换为 `WRAPPER_IDENTITY_CHANGED`，而是统一抛出：
  ```python
  raise BatchUtilityInvalidConfigError(
      f"Failed to scan wrapper directory '{w_lex}': {e}",
      details={
          "wrapper_path": w_lex,
          "errno": getattr(e, "errno", None),
          "stage": "CONTINUITY",
      },
  )
  ```

---

## 3. 测试验证

### 3.1 独立评审人回归验证（Reviewer Regressions A-F）
1. **A. Snapshot 第二次 scandir 失败 / 空 wrapper**：
   - 发现成功，快照阶段抛出 `PermissionError(errno=13)`；
   - 验证编译器与 API 均返回 HTTP 422 `BATCH_UTILITY_INVALID_CONFIG`，`stage="SNAPSHOT"`, `errno=13`。
2. **B. Snapshot 第二次 scandir 失败 / 非空 wrapper**：
   - 同上，非空 wrapper 在快照阶段失败同样返回 HTTP 422 `BATCH_UTILITY_INVALID_CONFIG`，`stage="SNAPSHOT"`。
3. **C. Continuity 第三次 scandir 失败 / 空 wrapper**：
   - 发现和快照成功，连续性重扫描阶段抛出 `PermissionError(errno=13)`；
   - 验证返回 HTTP 422 `BATCH_UTILITY_INVALID_CONFIG`，`stage="CONTINUITY"`, `errno=13`；
   - Generate 阶段创建 0 Draft。
4. **D. Continuity 第三次 scandir 失败 / 非空 wrapper**：
   - 同上，非空 wrapper 在连续性重扫描阶段失败同样返回 HTTP 422 `BATCH_UTILITY_INVALID_CONFIG`，`stage="CONTINUITY"`；
   - Generate 阶段创建 0 Draft。
5. **E. W vs W/ 规范化摘要等价性**：
   - `wrapper_paths=["/root/W"]` 与 `wrapper_paths=["/root/W/"]` 产生完全相同的 `action_config_digest`、`source_snapshot_digest` 及 `preview_digest`。
6. **F. Wrapper 输入顺序摘要不敏感性**：
   - `[W1, W2]` 与 `[W2, W1]` 产生完全相同的规范化列表与 digest。

### 3.2 自动化测试集结果
- **针对性回归测试（Reviewer Regressions）**：
  `pytest -k "scandir_failure or canonical_wrapper"`：15 selected，15 passed (100% PASS)。
- **E3 核心套件**：
  `pytest tests/test_gate5e_e3_*.py`：78 passed (100% PASS)。
- **E1 + E2 套件**：
  `pytest tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py`：77 passed (100% PASS)。
- **全量后端测试套件**：
  `pytest tests/`：972 passed, 0 failed (100% PASS)。

---

## 4. 边界与约束遵守确认

- [x] 未开启 E4。
- [x] 未声明 E3 PASS / CLOSED。
- [x] 零生产范围外修改：仅限 `app/batch_utilities/compiler.py`、`app/batch_utilities/digest.py`、`app/batch_utilities/flatten.py`、`app/batch_utilities/flatten_graph.py` 以及对应测试文件。
- [x] 未触碰 `app/batch_utilities/graph.py`、`app/execution/executor.py`、`app/fs_ops.py`、`app/tasks/handlers.py`、`app/models.py`、`frontend/**`、`migrations/**`、`app/workflows/**`。
- [x] 零 DB migration，零新 Worker，零新 Undo 引擎，零空目录删除。
- [x] Plan metadata 中 `wrapper_paths` 保持与 `action_config_digest` 一致的规范形式，`db_lineage_digest` 保持 `None`。
