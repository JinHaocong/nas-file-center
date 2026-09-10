# Gate5-E / E3-hotfix11 Walkthrough: Mandatory Wrapper Identity — No Unbound Discovery

## 1. 任务背景与根本原因

在 E3-hotfix10 实现了基于描述符（fd）的物理身份绑定与统一枚举权限后，独立评审发现 Wrapper 物理身份捕获仍存在一个致命的 Fail-Closed 漏洞：

### 1.1 物理身份捕获静默退化（Silent Identity Capture Degradation）
- **故障场景**：
  1. 初始文件系统存在合法 Wrapper 目录 `root/W`（内含 `before.txt`）。
  2. 在预检 `validate_wrappers_preflight()` 中：
     ```python
     try:
         st_phys = os.stat(w_phys)
         identities[...] = (st_phys.st_dev, st_phys.st_ino)
     except OSError:
         pass
     ```
     若物理路径解析成功，但在物理身份观察 `os.stat(w_phys)` 时遭遇单次瞬态 I/O 故障，`except OSError: pass` 会静默吞掉异常，导致 `identities` 字典缺少该 Wrapper 的身份条目。
  3. 编译器此前使用了容错回退语义：
     `expected_identities = validate_wrappers_preflight(...) or {}`
     并在后续校验中通过 `if exp_id is not None:` 静默跳过了身份校验；
  4. 随后执行 Discovery 时，`discover_flatten_one_level()` 未获得预期设备号与 inode，以未绑定的状态（`expected_device = None, expected_inode = None`）执行了目录获取；
  5. 若在此期间 `root/W` 被外部并发替换为包含 `secret.txt` 的另一个普通真实目录，Discovery 直接枚举了 `secret.txt`，编译层产出：
     `planned_operations_count = 1, candidate_count = 1, blocking_conflict_count = 0`，违背了物理身份绑定的安全约束。

### 1.2 无绑定发现兼容回退（Unbound Discovery Fallback Downgrade）
- 历史代码中包含：
  ```python
  try:
      discover_flatten_one_level(canonical_wrappers, expected_identities=expected_identities)
  except TypeError:
      discover_flatten_one_level(canonical_wrappers)
  ```
  该兼容回退为了容忍旧单元测试 mock 的过时单参签名，弱化了生产编译层的物理身份强制要求。

---

## 2. 全局安全权威不变式（Global Authority Invariant）

> **在生产 Flatten 编译器流程中，每一个授权 Wrapper 在进行任何 Discovery 获取之前，必须具备完整的预期物理身份 `(st_dev, st_ino)`。**
> 物理身份绑定是绝对强制的，绝非可选。
> 若物理身份无法确立，必须在 Discovery 获取前立即 Fail-Closed；严禁以 `expected_device = None, expected_inode = None` 静默继续；严禁生产编译器执行无身份绑定的 Discovery 降级重试。

---

## 3. 核心架构修复与代码改动

### 3.1 `app/batch_utilities/flatten_graph.py`
- 修复 `validate_wrappers_preflight()`：
  - 彻底移除物理身份捕获处的 `except OSError: pass`；
  - 若 `os.stat(w_phys)` 发生任何异常，立即抛出结构化 `BatchUtilityInvalidConfigError`（HTTP 422），携带 `stage="PREFLIGHT"`、`wrapper_path` 与底层 `errno`；
  - 严禁携带缺失的身份映射返回。

### 3.2 `app/batch_utilities/compiler.py`
- 拒绝空的身份映射：
  - 若预检返回非字典或空字典，立即抛出 `BatchUtilityInvalidConfigError(stage="PREFLIGHT")`；
- 强制完整身份映射：
  - 遍历输入路径 `action.wrapper_paths` 及规范化路径 `canonical_wrappers` 时，校验 `exp_id is None`；若缺少物理身份映射，立即抛出 `BatchUtilityInvalidConfigError(stage="CANONICALIZE")`，杜绝任何静默跳过；
  - 快照观测扫描中同样强制校验 `exp_id is None`，缺失则立即抛出 `BatchUtilityInvalidConfigError(stage="SNAPSHOT")`；
- 彻底移除无绑定发现降级：
  - 移除 `try ... except TypeError:` 兼容回退，直接调用 `discover_flatten_one_level(canonical_wrappers, expected_identities=expected_identities)`。

### 3.3 测试用例 mock 签名更新
- 更新 `tests/test_gate5e_e3_generate.py` 中 4 处针对 `discover_flatten_one_level` 的 mock 签名，使其接收 `*args, **kwargs`，确保测试用例透明兼容且不弱化生产环境。

### 3.4 零生产范围外修改
- 严格遵循范围限制，生产代码仅修改 `app/batch_utilities/flatten_graph.py` 与 `app/batch_utilities/compiler.py`（未修改 `flatten.py`）。
- 零 DB migration，零新 Worker，零新 Undo 引擎。

---

## 4. 测试验证与结果

### 4.1 明确的 RED 失败与 GREEN 修复验证
1. **编译器预检身份捕获失败回归**：[`test_compiler_preflight_identity_capture_failure_fails_closed`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_gate5e_e3_compiler.py)
   - RED 表现：hotfix10 基线下未抛出异常，`secret.txt` 被采纳为候选，`planned_operations_count = 1`。
   - GREEN 表现：抛出 `BatchUtilityInvalidConfigError(stage="PREFLIGHT")`，0 discovery 替换子项枚举，0 候选。
2. **Generate Phase A 身份权限建立失败回归**：[`test_generate_preflight_identity_capture_failure_fails_closed`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_gate5e_e3_generate.py)
   - RED 表现：Generate Phase A 执行了无绑定 discovery，枚举了 `secret.txt`。
   - GREEN 表现：返回 HTTP 422 `BATCH_UTILITY_INVALID_CONFIG`，0 discovery 子项枚举，0 `BatchPlan`，0 `BatchPlanItem`，0 文件系统变动。

### 4.2 自动化测试结果
- **针对性回归测试（2 tests）**：2 passed (100% PASS)
- **E3 核心套件（`pytest tests/test_gate5e_e3_*.py`）**：105 passed (100% PASS)
- **E1 + E2 套件（`pytest tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py`）**：77 passed (100% PASS)
- **全量后端测试套件（`pytest tests/`）**：999 passed, 0 failed (100% PASS)

---

## 5. 边界与约束遵守确认

- [x] 未开启 E4。
- [x] 未声明 E3 PASS / CLOSED。
- [x] 零生产范围外修改（仅修改允许的文件）。
- [x] 零 DB migration，零新 Worker，零新 Undo 引擎。
- [x] 严格满足全局强制身份绑定与禁止无绑定 Discovery 不变式。
