# NAS File Center v0.3.3-step2-fixed9-hotfix1 验收报告与实现文档
## Index Active-Job Corrupt State Isolation Fix

## 1. Baseline（基线说明）
- **基线版本**：`NAS File Center v0.3.3-step2-fixed9`（Commit: `5e7a87f647febc5d45641a6442132d0ac7219565`）。
- **性质定位**：
  - 属于 fixed9 的极小 Backend correctness hotfix；
  - 隔离 `WorkJob.state_json` 损坏或异常格式导致的非预期业务异常；
  - 确保活跃索引任务冲突检测遵循安全解析与真实归属原则（Safe Parse & Exact Root Match Truthfulness）；
  - 避免 malformed JSON 被误当业务 409 异常并向 API 用户泄露内部解析器错误。
- **严格约束**：
  - **后端生产文件变更仅 1 个**：仅修改 `app/service.py`；
  - **数据库结构零变更**：DB Schema Diff = 0，Migration Diff = 0；
  - **前端生产代码零变更**：Frontend Production Diff = 0；
  - **文件系统零破坏**：NAS 磁盘物理文件系统变更数 = 0；
  - **关联数据完整保留**：WorkJob、TaskEvent、ScanJob、BatchPlan、AuditEvent 完好保留，绝不级联误删。

---

## 2. 根因剖析与 RED → GREEN 修复实现

### A. 缺陷根因（JSONDecodeError 继承 ValueError）
- 在 fixed9 原 `delete_index_root()` 中，检查活跃索引任务的代码结构如下：
  ```python
  for job in active_jobs:
      if not job.state_json:
          continue
      try:
          payload = json.loads(job.state_json)
          job_root = payload.get("root")
          if job_root == root_str:
              raise ValueError(f"Cannot remove index for '{root_str}' while index task #{job.id} is active ({job.status})")
      except ValueError:
          raise
      except Exception:
          pass
  ```
- **关键机制**：在 Python 标准库中，`json.decoder.JSONDecodeError` 继承自 `ValueError`（`issubclass(json.JSONDecodeError, ValueError) == True`）。
- **引发故障**：
  1. 当数据库中存在任一活跃状态（`queued`, `running` 等）且 `state_json` 格式损坏（如 `"{broken json"`）的无关 `index-root` 工作任务时；
  2. 用户尝试删除某个正常的 `IndexRoot`（该根自身的任务已完成）；
  3. `json.loads(job.state_json)` 抛出 `JSONDecodeError`；
  4. 由于 `except ValueError:` 分支位于 `except Exception:` 之前，该异常被优先捕获并原样 `raise`；
  5. 路由层捕获到 `ValueError`，直接将其转译为 HTTP 409 Conflict，并将底层解析器原始错误文本（例如 `"Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"`）直接暴露给前端用户；
  6. 导致单条损坏的后台 Job 阻断全局所有 IndexRoot 的元数据清理，且列表界面呈现 `can_remove=true` 而点击删除却报 409，造成界面与后端策略脱节（Policy Divergence）。

---

### B. RED 阶段验证与精准复现
在 `tests/test_index_root_lifecycle.py` 中构建回归用例：
1. `test_malformed_unrelated_active_job_does_not_block_index_root_delete`：
   - 目标 IndexRoot A 自身任务已完成；数据库插入一条完全无关、`state_json="{broken json"` 的 running 任务；
   - 在 baseline 代码执行 `delete_index_root(A.id)`，直接抛出 `json.decoder.JSONDecodeError`，断言失败，稳定复现。
2. `test_api_delete_with_malformed_unrelated_active_job`：
   - 调用 `DELETE /api/indexes/{id}`；
   - 在 baseline 代码下返回 HTTP 409，错误详情包含 `"Unterminated string starting at: line 1 column 2 (char 1)"`，断言失败，稳定复现。
3. `test_malformed_payload_shapes_do_not_block_deletion[{broken]`：
   - 覆盖多种损坏形状，`{broken` 稳定触发 `JSONDecodeError`，证明 baseline 缺陷确凿。

---

### C. GREEN 阶段实现与安全解析语义（Safe Parse & Unified Helper）
1. 在 [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py) 提取纯净安全解析 helper：
   ```python
   def _index_job_root(job: WorkJob) -> str | None:
       raw = job.state_json
       if not raw:
           return None
       try:
           payload = json.loads(raw)
       except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
           return None
       if not isinstance(payload, dict):
           return None
       root = payload.get("root")
       if not isinstance(root, str):
           return None
       root = root.strip()
       if not root:
           return None
       return root
   ```
2. **安全解析规则**：
   - `null` / `None` / 空字符串：安全返回 `None`；
   - 损坏的 JSON 语法：被 `(json.JSONDecodeError, TypeError, UnicodeDecodeError)` 捕获，安全返回 `None`，绝不外溢为业务异常；
   - 非 dict 对象（如列表 `[]`、数值 `123`、字符串 `"hello"`）：安全返回 `None`；
   - 缺失 `root` 字段、`root` 为 `null`、非字符串、或纯空白字符：安全返回 `None`；
   - 只有当解析出合法且非空的字符串路径时，才作为候选 `job_root` 返回。
3. **统一策略复用**：
   - `list_index_roots` 与 `delete_index_root` 统一调用 `_index_job_root(job)`；
   - 保证“列表可删判定（`can_remove`）”与“删除接口拦截（`delete_index_root`）”逻辑完全同构，消除 Policy Divergence；
   - 严格进行 Exact String 匹配（`job_root == root_str`），禁止 substring、LIKE、或 startswith 匹配；
   - 若 `job_root == root_str`，抛出清晰业务异常：
     `ValueError(f"Cannot remove index root '{root_str}' while index task #{job.id} is active ({job.status})")`，由路由层规范转为 409。

---

## 3. 边界与不变性验证（Invariants & Boundaries）

1. **Unknown Non-Terminal Status 规则保持**：
   - 非终态集合通过 `WorkJob.status.not_in({"completed", "failed", "cancelled"})` 判定；
   - 遇到未知的非终态状态（如 `"future_active_state"`），只要 `job_root == target_root`，仍然严格 Fail-safe 拦截并返回 409。
2. **Terminal Status 规则保持**：
   - 终态状态（`"completed"`, `"failed"`, `"cancelled"`）即便 `job_root == target_root`，也绝不阻止删除。
3. **Exact Root 边界隔离**：
   - 目标 `/data/A`；
   - 活跃任务 `/data/AB` $\rightarrow$ 不阻止；
   - 活跃任务 `/data/A/sub` $\rightarrow$ 不阻止；
   - 活跃任务 `/data/A` $\rightarrow$ 严格阻止（409）。
4. **损坏 WorkJob 完好保留**：
   - 遇到 `state_json` 损坏的活跃任务时，仅将其视为“无法证明归属当前目标 Root”而安全跳过；
   - 绝不擅自删除、篡改、或重写该损坏任务，数据完整性完好保留。
5. **物理文件系统安全与零副作用**：
   - 物理文件与目录无任何 unlink、rmtree、rename、move、touch 操作；
   - `AuditEvent`、`TaskEvent`、`ScanJob`、`BatchPlan` 完好保留。

---

## 4. 测试矩阵与全量回归验证

### 1. 后端单元与集成测试（Pytest in Docker Rule 62 Isolated Container）
- **针对性生命周期回归**：`pytest tests/test_index_root_lifecycle.py`
  - 包含 7 组新增专项回归测试（用例数 29 个，覆盖损坏 JSON、API 返回、真实冲突、未知状态、异常载荷参数化、前缀边界、终态任务等）；
  - 结果：**29 passed, 2 warnings in 1.91s**。
- **数据库迁移回归**：`pytest tests/test_index_root_registry_migration.py`
  - 结果：**2 passed, 2 warnings in 0.25s**。
- **全量后端测试套件**：`pytest -q`
  - 结果：**314 passed, 18 warnings in 39.42s**（相比 fixed9 的 299 个净增 15 个，0 failures，18 warnings 与基线完全一致）。

### 2. 前端测试与构建验证
- **单元测试**：`npm test`
  - 结果：`122 tests, 36 suites, pass 122, fail 0`。
- **类型检查**：`npm run typecheck`
  - 结果：Exit Code 0，**0 errors**。
- **生产打包构建**：`npm run build`
  - 结果：成功构建，dist 产物完整生成。

### 3. Docker 多架构镜像与容器冒烟验证
- **镜像构建**：`docker build --platform linux/amd64 -t kerwinjhc/nas-file-center:0.3.3-step2-fixed9-hotfix1 .` 成功。
- **容器冒烟测试**：
  - `GET /health` $\rightarrow$ 200 OK；
  - 未认证访问 `GET /api/indexes` $\rightarrow$ 401 Unauthorized；
  - 未认证访问 `DELETE /api/indexes/1` $\rightarrow$ 401 Unauthorized；
  - 认证后无 Origin 头请求 `DELETE /api/indexes/1` $\rightarrow$ 403 Forbidden（CSRF 拦截成功）；
  - 认证后带合法 Origin 请求 `DELETE /api/indexes/1` $\rightarrow$ 404 Not Found（路由与鉴权正常）。

### 4. 手工 SQLite 场景验收（Manual SQLite Acceptance）
- 场景 1（存在无关损坏 active job）：`list_index_roots` 返回 `has_active_job=False, can_remove=True`；`delete_index_root` 成功删除目标，验证通过（List policy = Delete policy）。
- 场景 2（存在目标 exact-root running job）：`list_index_roots` 返回 `has_active_job=True, can_remove=False`；`delete_index_root` 严格返回 409 业务拦截，验证通过（List policy = Delete policy）。

---

## 5. 已知限制与边界声明（Known Limitations）

- **本轮职责边界**：
  本轮修复仅保证损坏的 `WorkJob.state_json` 不会错误扩散并阻止无关 `IndexRoot` 的正常生命周期删除，API 不泄露底层 JSON 解析器堆栈。
- **非本轮职责**：
  不负责修复已损坏的 `WorkJob` 记录、不负责恢复损坏任务的 payload 数据、不负责推测损坏任务原始的挂载路径。损坏任务数据的治理与修复属于后续专设的 Data Integrity / Task Repair Gate。

---

## 6. 干净发布包验证与 Release Decision

- **干净归档**：使用 `git archive` 打包生成发布 ZIP，彻底排除 `.git`、`node_modules`、`frontend/dist`、`__pycache__`、临时 SQLite 与备份文件。
- **独立纯净验证**：解压至独立纯净目录，运行全量测试套件 100% 通过。
- **Release Decision**：**PASS / APPROVED**。
