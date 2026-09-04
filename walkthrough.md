# NAS File Center v0.3.3-step2-fixed5 验收报告与实现文档
## IndexRoot Progress Contract Backend Hotfix

## 1. Baseline（基线说明）
- **基线版本**：`NAS File Center v0.3.3-step2-fixed4`（Commit: `27a6895`）。
- **定位**：本轮为针对 NAS 实机实测 Task #23 故障的 **后端窄范围紧急修复（Backend Hotfix）**。前端生产代码零变动、DB Schema 零变动、Alembic Migration 零变动、API 契约零变动、第三方依赖零引入。

## 2. NAS Task #23 事故现场与精确根因
### 故障现象
NAS 实机执行大目录 `index-root` 任务（Task #23）时：
- 任务处理到第 1000 个文件后突然变为 `failed`；
- 状态数据显示：`progress_current=1000, progress_total=0, error_code="EXECUTION_ERROR"`；
- 报错信息为：`progress_total (0) cannot be smaller than saved progress_current (1000)`。

### 精确根因追踪
1. 在 [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py) 的 `FileCenterService.reindex_root()` 中：
   - 默认分批刷新阈值 `batch_size = 1000`；
   - 每批满 1000 个条目写入 DB 后，执行 `checkpoint_callback(files + folders, 0)`。
2. 第一次 batch 写入（条目数达 1000）：
   - `files + folders = 1000`，调用 `checkpoint_callback(1000, 0)`；
   - [`app/tasks/context.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/context.py) 的 `_apply_progress()` 逻辑中，初始 `saved_curr = 0`，`p_tot = 0`；
   - 校验 `p_tot < saved_curr`（`0 < 0`）为 False，校验通过，成功落库 `progress_current = 1000, progress_total = 0`。
3. 第二次 batch 写入（条目数超过 1000）：
   - `files + folders > 1000`，再次调用 `checkpoint_callback(files + folders, 0)`；
   - 此时 `_apply_progress()` 检查当前 DB 中已保存的 `saved_curr = 1000`，而本次传入的 `p_tot = 0`；
   - 条件 `p_tot < saved_curr`（`0 < 1000`）成立，触发保护性断言抛出 `ValueError: progress_total (0) cannot be smaller than saved progress_current (1000)`；
   - 任务被外层捕获并标记为 `failed`，`error_code = "EXECUTION_ERROR"`。

## 3. RED 阶段（先失败复现）
在 [`tests/test_index_root_progress_regression.py`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_index_root_progress_regression.py) 中构建真实多批次 `index-root` 场景（包含 1050 个条目以强行触发第 2 个 batch 的 flush）：
- 运行测试真实复现失败：
```text
AssertionError: Expected completed but got failed, error_code=EXECUTION_ERROR, error_text=progress_total (0) cannot be smaller than saved progress_current (1000)
assert 'failed' == 'completed'
```
100% 验证了 fixed4 原逻辑中的边界缺陷。

## 4. GREEN 阶段（契约收敛修复）
严格遵照不破坏、不放宽 `JobContext` 进度不变量（Invariant）的原则，在 Caller / Handler 层面收敛契约：
1. **明确未知总量（Indeterminate Progress）契约**：
   - 目录遍历阶段在未扫完全盘前无法预知最终总文件数；
   - 在 [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py) 中将 `flush()` 的 `checkpoint_callback(files + folders, 0)` 修改为 `checkpoint_callback(files + folders, None)`，显式声明总量未知。
2. **Handler 防御性转换**：
   - 在 [`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py) 的 `IndexRootHandler` 中：
     - 启动阶段设置 `progress_total = None`（消除原写死的 `progress_total = 1` 伪造总量）；
     - `on_batch` 中防卫性处理 `effective_total = total if (total is not None and total > 0) else None`，确保遍历阶段绝不向 `JobContext` 传递 `progress_total = 0`，保持优雅的 Indeterminate 状态；
     - 最终完成阶段原子上报 `progress_current = total_items, progress_total = total_items`，达成 `current == total == files + folders` 的 100% 自洽终态。

## 5. 修改文件清单
### 生产代码文件（极窄范围）：
- [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py)：`reindex_root` 中 `checkpoint_callback` 传递 `None`；
- [`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py)：启动检查点与 `on_batch` 适配未知总量契约。

### 测试与文档文件：
- [`tests/test_index_root_progress_regression.py`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_index_root_progress_regression.py)：[NEW] 新增 Cases A ~ F 全量回归用例；
- [`walkthrough.md`](file:///Users/Kerwin/MyProject/nas-file-center/walkthrough.md)：更新为 step2-fixed5 故障与验收报告。

## 6. 未修改范围
- **前端生产代码**：`frontend/src/**` 零修改（Frontend production diff = 0）；
- **数据库结构**：DB Schema 零修改、DB models 零修改；
- **迁移脚本**：Alembic migrations 零修改；
- **API 接口契约**：REST Endpoints 与 Schema 零修改；
- **第三方依赖**：零新依赖引入（New dependencies = 0）；
- **安全与控制**：Worker Lease、Fencing、Capability Actions 均保持不变。

## 7. 全量场景回归（Cases A ~ F 全部通过）
在 Docker `python:3.12-slim` 容器中运行 [`tests/test_index_root_progress_regression.py`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_index_root_progress_regression.py)：
- **Case A（<= 1000 entries）**：350 个文件单批次索引，`completed`，`current == total == 350`（PASS）；
- **Case B（> 1000 entries）**：1200 个文件跨 2 批次索引（复现 NAS Task #23 场景），`completed`，`current == total == 1200`（PASS）；
- **Case C（> 2000 entries）**：2150 个文件跨 3+ 批次索引，`completed`，`current == total == 2150`（PASS）；
- **Case D（Empty directory）**：0 文件 0 目录，`completed`，`current == total == 0`（PASS）；
- **Case E（Reindex existing rows）**：已有 400 条旧索引，增量扩充至 1100 条后重建索引，`completed`，旧 generation 正确清理，`current == total == 1100`（PASS）；
- **Case F（Final completed progress consistency）**：1100 文件 + 15 目录，最终完成检查点 `current == total == 1115`，Checkpoint Payload 中 files/folders 结构自洽（PASS）。

## 8. Backend Regression
在 Docker `python:3.12-slim` 容器中执行全量回归测试：
```bash
docker run --rm --platform linux/amd64 -v $(pwd):/app -w /app python:3.12-slim bash -c "pip install -q -e . pytest pytest-asyncio httpx && PYTHONPATH=. pytest -q"
```
结果：**231 passed in 100%**, 0 failed, 0 skipped（从 fixed4 的 225 项测试严格增长至 231 项）。

## 9. Frontend Regression
在 `frontend` 目录执行完整检查：
- `npm test`：**tests: 61, suites: 14, pass: 61, fail: 0**；
- `npm run typecheck` (`tsc --noEmit`)：**0 errors**；
- `npm run build` (`tsc && vite build`)：**3704 modules transformed, build completed**。

## 10. Docker Build & Smoke
- 构建生产镜像：`kerwinjhc/nas-file-center:0.3.3-step2-fixed5`（`linux/amd64`）成功；
- 启动容器测试：
  - `GET /health` $\rightarrow$ `200 OK`；
  - `GET /tasks` $\rightarrow$ `200 OK`；
  - 13 个 SPA 路由全部可达；
  - 4 个任务控制 mutation 端点鉴权与 CSRF 拦截有效。

## 11. Release Decision
**PASS**：NAS Task #23 故障根因彻底定位并修复，RED 阶段稳定复现，GREEN 阶段 Cases A ~ F 全部通过，全量 231 项后端测试与 61 项前端测试 100% 绿灯，生产镜像打包与 Smoke 验证完毕。
