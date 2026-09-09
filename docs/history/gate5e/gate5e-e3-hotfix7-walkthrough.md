# Gate5-E / E3-hotfix7 Walkthrough: Canonical Wrapper Physical-Identity Semantics Fix

## 1. 任务背景与根本原因

在 E3-hotfix6 独立评审中，发现了以下规范化路径物理身份语义缺陷（Canonical Wrapper Physical-Identity Semantics Fix）：

1. **符号链接与 `..` 遍历的文本归一化错误（Symlink / Dotdot Failure）**：
   - 此前 `canonicalize_wrapper_path` 在解析文件系统对象前执行了 `norm = os.path.normpath(raw)`；
   - 当路径中包含符号链接组件时，文本路径归一化并不等价于真实文件系统遍历。
   - 典型复现：
     - 文件系统结构：`root/A/B/`, `root/A/W/intended.txt`, `root/W/wrong.txt`, `root/link -> root/A/B`；
     - 输入动作路径：`root/link/../W`；
     - 真实文件系统遍历解析：`link` 目标为 `root/A/B`，其上一级目录 `..` 为 `root/A`，因此 `link/../W` 实际指向 `root/A/W`；
     - 文本归一化：`os.path.normpath` 将 `link/..` 直接消除，错误归一化为 `root/W`，导致 Preview 与 Generate 错误操作 `root/W/wrong.txt`。
2. **文件名有效空格被错误截断（Whitespace Failure）**：
   - 此前调用 `str(path).strip()` 剥离了两端空白；
   - 在 Unix 文件系统中，组件结尾或内部的空白字符（例如 `root/"W "`）是完全合法的目录名。`strip()` 导致其被错误重写为 `root/W`。
3. **解析失败未能 Fail-Closed**：
   - 此前若严格解析失败，静默回退至返回文本 `norm`，可能引发后续路径漂移或错误。

---

## 2. 核心改动

### 2.1 `app/batch_utilities/digest.py`
- 重写 `canonicalize_wrapper_path(path: str) -> str`：
  - 严禁调用 `.strip()` 与 `os.path.normpath()`；
  - 仅通过 `raw.rstrip("/") or "/"` 剥离尾随斜杠以执行 `os.lstat` 检查叶子节点符号链接状态，保留符号链接路径供预检（preflight）进行安全拦截；
  - 若非符号链接，直接通过原始路径的实际文件系统遍历进行严格解析：`Path(raw).resolve(strict=True)`；
  - 若解析失败（如不存在或权限问题），严格 Fail-Closed：
    - `FileNotFoundError` 抛出 `BatchUtilityScopeNotFoundError`（HTTP 404）；
    - `OSError` 抛出 `BatchUtilityInvalidConfigError`（HTTP 422）；
    - 严禁回退至任何推测性的文本路径。

### 2.2 零生产范围外改动
- 生产代码仅修改 `app/batch_utilities/digest.py`，未改动 `app/batch_utilities/flatten_graph.py`、`app/batch_utilities/graph.py`、`app/execution/executor.py`、`app/fs_ops.py`、`app/tasks/handlers.py`、`app/models.py`、`frontend/**`、`migrations/**`、`app/workflows/**`。

---

## 3. 测试验证

### 3.1 独立评审人回归验证（Reviewer Regressions）
1. **A. 符号链接敏感的 `..` 遍历选择（Symlink-sensitive dotdot selection）**：
   - 构造 `root/A/B`, `root/A/W/intended.txt`, `root/W/wrong.txt`, `root/link -> root/A/B`；
   - 输入 `root/link/../W`；
   - 验证规范化 wrapper 解析为 `root/A/W`；
   - 验证 Preview 仅包含 `root/A/W/intended.txt`，绝不包含 `root/W/wrong.txt`；
   - 验证 Generate 201 创建的 Draft move 项 source 为 `root/A/W/intended.txt`。
2. **B. 有效尾随空格目录（Valid trailing-space directory）**：
   - 构造 `root/W/wrong.txt`, `root/"W "/intended.txt`；
   - 输入 `root/"W "`；
   - 验证规范化 wrapper 保持结尾空格不变，Preview 与 Generate 绝不切换至 `root/W`。
3. **C. 既有规范化摘要等价性**：
   - `W` 与 `W/` 解析为完全相同的物理 wrapper 与相同的 `action_config_digest`。
4. **D. 普通非符号链接冗余路径**：
   - `root/X/../W`（X 为真实非符号链接目录）正确解析为 `root/W`。
5. **E. Wrapper 输入顺序摘要不敏感性**：
   - 输入顺序打乱保持 digest 一致。
6. **F. 物理重复 wrapper 拒绝**：
   - 重复 wrapper 输入（包括符号链接等同路径）仍触发 `BatchUtilityScopeOverlapError`。

### 3.2 自动化测试集结果
- **针对性回归测试（Compiler + API + Generate）**：
  `pytest -k "dotdot or trailing_space or canonical_wrapper"`：10 passed (100% PASS)。
- **E3 核心套件**：
  `pytest tests/test_gate5e_e3_*.py`：85 passed (100% PASS)。
- **E1 + E2 套件**：
  `pytest tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py`：77 passed (100% PASS)。
- **全量后端测试套件**：
  `pytest tests/`：979 passed, 0 failed (100% PASS)。

---

## 4. 边界与约束遵守确认

- [x] 未开启 E4。
- [x] 未声明 E3 PASS / CLOSED。
- [x] 零生产范围外修改：仅限 `app/batch_utilities/digest.py` 及测试文件。
- [x] 零 DB migration，零新 Worker，零新 Undo 引擎，零空目录删除。
- [x] Plan metadata 中 `wrapper_paths` 与 `canonical_action_config` 绑定真实物理解析路径，`db_lineage_digest` 保持 `None`。
