# NAS File Center v0.3.5 Gate5-A-hotfix2 — Implementation & Safety Walkthrough

## 1. Context & Scope (背景与本次范围)

当前整体状态：
```text
Gate2 = PASS
Gate3 = PASS
Gate4 = PASS
NAS File Center v0.3.4 = CLOSED

Gate5-A-hotfix1 independent targeted review:
  Original P2-01 (media_type in/nin 500) = CLOSED
  Original P2-02 (fail-closed AST) = CLOSED
  Original P2-03 (mtime/string strict typing) = CLOSED

New finding:
  P2-04 = OPEN (mtime SQLite signed INT64 overflow -> HTTP 500)

Gate5-A = HOLD pending independent review
Gate5-B = FORBIDDEN
v0.3.5 = NOT CLOSED
```

### 1.1 本轮唯一目标
修复 Gate5-A independent review 发现的 **P2-04** 缺陷：`mtime` 过滤条件经过 Gate5-A validation 校验后，可能超过 SQLite 64 位有符号整型上限（`INT64_MAX = 9_223_372_036_854_775_807`），导致 SQLite 执行阶段抛出 `OverflowError: Python int too large to convert to SQLite INTEGER` 并引发 HTTP 500 异常。

### 1.2 严格 mtime 契约与范围红线
1. **常量契约**:
   - `INT64_MAX = (1 << 63) - 1 = 9_223_372_036_854_775_807`
   - `MIN_MTIME_NS = 0`
   - `MAX_MTIME_NS = INT64_MAX`
   - `MAX_EPOCH_SECONDS = INT64_MAX // 1_000_000_000 = 9_223_372_036`
2. **校验行为契约**:
   - 整数输入：仅接受 `0 <= val <= 9_223_372_036`。输入 `9223372036` 返回 200；输入 `9223372037` 或负数、浮点、布尔一律抛出 `FilterValidationError` 并返回 HTTP 422。
   - ISO 8601 字符串：必须 timezone-aware（带时区）；禁止使用 `dt.timestamp() * 1e9`（存在浮点精度丢失），必须使用基于 `datetime(1970, 1, 1, tzinfo=timezone.utc)` 的纯整数微秒/秒累加运算。
   - ISO 边界：
     - `2262-04-11T23:47:16Z` (9223372036s) $\rightarrow$ 接受 (200)
     - `2262-04-11T23:47:16.854775Z` (9223372036854775000ns) $\rightarrow$ 接受 (200)
     - `2262-04-11T23:47:16.854776Z` (9223372036854776000ns > INT64_MAX) $\rightarrow$ 拒绝 (422)
     - `2262-04-12T00:00:00Z` $\rightarrow$ 拒绝 (422)
     - `9999-12-31T23:59:59Z` $\rightarrow$ 拒绝 (422)
     - `1969-12-31T23:59:59Z` (负纳秒) $\rightarrow$ 拒绝 (422)
3. **范围红线**:
   - 仅允许修改 `app/filters/validation.py`、`tests/test_filter_ast.py`、`tests/test_filter_preview.py`、`walkthrough.md`。
   - 绝不修改 DB Schema、`compiler.py`、`schema.py`、`models.py`。
   - 绝不执行 `git push`、`git tag`、`docker push`。
   - 绝不提前宣布 Gate5-A PASS 或启动 Gate5-B。

---

## 2. Technical Implementation (技术实现)

### 2.1 修改文件清单
- [`app/filters/validation.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/filters/validation.py): 定义 `INT64_MAX`、`MIN_MTIME_NS`、`MAX_MTIME_NS`、`MAX_EPOCH_SECONDS`、`EPOCH_UTC`；重构 `_parse_mtime_to_ns` 使用无精度损失的纯整数纳秒计算及边界校验。
- [`tests/test_filter_ast.py`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_filter_ast.py): 增加 `9223372036` (ACCEPT)、`9223372037` (422)、`-1` (422)、`2262-04-11T23:47:16.854775Z` (ACCEPT)、`2262-04-11T23:47:16.854776Z` (422)、`9999-12-31T23:59:59Z` (422)、`1969-12-31T23:59:59Z` (422) 测试用例。
- [`tests/test_filter_preview.py`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_filter_preview.py): 增加 API 端到端边界用例（`9223372036` $\rightarrow$ 200, `9223372037` $\rightarrow$ 422, `2262-04-11T23:47:16.854775Z` $\rightarrow$ 200, `2262-04-11T23:47:16.854776Z` $\rightarrow$ 422, `9999-12-31T23:59:59Z` $\rightarrow$ 422）。

### 2.2 核心代码实现
```python
INT64_MAX = (1 << 63) - 1
MIN_MTIME_NS = 0
MAX_MTIME_NS = INT64_MAX
MAX_EPOCH_SECONDS = INT64_MAX // 1_000_000_000
EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_mtime_to_ns(val: Any) -> int:
    """Parse timezone-aware string ISO-8601 or int epoch seconds into UTC nanoseconds integer within SQLite INT64 range."""
    if isinstance(val, bool):
        raise FilterValidationError("mtime value cannot be a boolean")
    if isinstance(val, float):
        raise FilterValidationError("mtime value cannot be a float")
    if type(val) is int:
        if val < 0 or val > MAX_EPOCH_SECONDS:
            raise FilterValidationError(f"mtime epoch seconds out of supported range (0 to {MAX_EPOCH_SECONDS}), got {val}")
        ns = val * 1_000_000_000
        if ns < MIN_MTIME_NS or ns > MAX_MTIME_NS:
            raise FilterValidationError(f"mtime nanoseconds out of supported range ({MIN_MTIME_NS} to {MAX_MTIME_NS}), got {ns}")
        return ns
    if isinstance(val, str):
        val_str = val.strip()
        if val_str.endswith("Z") or val_str.endswith("z"):
            val_clean = val_str[:-1] + "+00:00"
        else:
            val_clean = val_str
        try:
            dt = datetime.fromisoformat(val_clean)
        except Exception as exc:
            raise FilterValidationError(f"Invalid mtime format '{val}': {exc}") from exc
        if dt.tzinfo is None:
            raise FilterValidationError("mtime ISO datetime must be timezone-aware (missing timezone)")
        dt_utc = dt.astimezone(timezone.utc)
        delta = dt_utc - EPOCH_UTC
        ns = delta.days * 86_400 * 1_000_000_000 + delta.seconds * 1_000_000_000 + delta.microseconds * 1_000
        if ns < MIN_MTIME_NS or ns > MAX_MTIME_NS:
            raise FilterValidationError(f"mtime nanoseconds out of supported range ({MIN_MTIME_NS} to {MAX_MTIME_NS}), got {ns}")
        return ns
    raise FilterValidationError(f"mtime value must be timezone-aware ISO string or integer epoch seconds, got {type(val).__name__}")
```

---

## 3. TDD RED $\rightarrow$ GREEN 验证记录

### 3.1 真实 RED 证据
在修复前直接复现 P2-04 缺陷：
1. **Validator 误通过超范围值**:
   ```text
   --- Test validator on 9223372037 ---
   BUG: 9223372037 accepted, ns=9223372037000000000
   --- Test validator on 9999-12-31T23:59:59Z ---
   BUG: 9999-12-31T23:59:59Z accepted, ns=253402300798999986176
   ```
2. **预览 API 触发 HTTP 500 异常**:
   ```text
   === Test 1: mtime = 9223372037 ===
   Status: 500
   Body: Internal Server Error
   === Test 2: mtime = 9999-12-31T23:59:59Z ===
   Status: 500
   Body: Internal Server Error
   ```
3. **SQLite 抛出 OverflowError 堆栈**:
   ```text
     File "/usr/local/lib/python3.12/site-packages/sqlalchemy/engine/default.py", line 952, in do_execute
       cursor.execute(statement, parameters)
   OverflowError: Python int too large to convert to SQLite INTEGER
   parameters = ('...', 9223372037000000000, ...)
   ```
4. **Pytest 新增用例失败**:
   ```text
   FAILED tests/test_filter_ast.py::test_mtime_strict_typing_and_timezone
   FAILED tests/test_filter_preview.py::test_preview_fail_closed_validation_errors
   2 failed, 17 passed
   ```

### 3.2 修复后 GREEN 结果
- `tests/test_filter_ast.py` & `tests/test_filter_preview.py`: **19 passed** (100% GREEN).
- API 行为验证：
  - `mtime=9223372036` $\rightarrow$ HTTP 200
  - `mtime=9223372037` $\rightarrow$ HTTP 422 (FilterValidationError: `mtime epoch seconds out of supported range (0 to 9223372036), got 9223372037`)
  - `mtime="2262-04-11T23:47:16.854775Z"` $\rightarrow$ HTTP 200
  - `mtime="2262-04-11T23:47:16.854776Z"` $\rightarrow$ HTTP 422 (FilterValidationError: `mtime nanoseconds out of supported range (0 to 9223372036854775807), got 9223372036854776000`)
  - `mtime="9999-12-31T23:59:59Z"` $\rightarrow$ HTTP 422 (FilterValidationError: `mtime nanoseconds out of supported range (0 to 9223372036854775807), got 253402300799000000000`)

---

## 4. 全量自动化测试与回归验证

### 4.1 Gate5-A 专项测试 (6 文件)
运行 6 个 Gate5-A 专属测试用例：
```bash
pytest tests/test_filter_ast.py tests/test_filter_compiler.py tests/test_filter_index_freshness.py tests/test_filter_policy.py tests/test_filter_preview.py tests/test_filter_preview_readonly.py
```
$\rightarrow$ **30 passed in 1.42s (100% PASS)**

### 4.2 Gate2, Gate3, Gate4 安全回归测试
运行 Gate2, Gate3, Gate4 全量安全测试：
```bash
pytest tests/test_gate2*.py tests/test_gate3*.py tests/test_gate4*.py
```
$\rightarrow$ **108 passed in 31.63s (100% PASS)**

### 4.3 后端全量测试套件
```bash
pytest -q
```
$\rightarrow$ **529 passed, 0 failures (100% PASS)**

### 4.4 前端自动化测试与构建
```bash
npm test -- --run && npm run typecheck && npm run build
```
$\rightarrow$ **177 passed, 52 suites, 0 failed**
$\rightarrow$ **Typecheck: 0 errors**
$\rightarrow$ **Build: Success (3.38s)**

---

## 5. Docker 独立黑盒验收 (11/11 Checkpoints PASS)

运行 `scratch/test_gate5a_hotfix2_blackbox_acceptance.py` 对真实构建的 Docker 镜像 `nas-file-center:v0.3.5-gate5a-hotfix2` 进行黑盒验收：

| 检查点 | 检查内容 | 结果 | 核心断言与安全表现 |
| :--- | :--- | :---: | :--- |
| **CP1** | 安全整型边界 `9223372036` | **PASS** | HTTP 200，正常查询索引库并返回 `matched_count: 0` |
| **CP2** | 溢出整型 `9223372037` | **PASS** | HTTP 422 严密拦截，绝不发生 SQLite 500 溢出 |
| **CP3** | 安全 ISO 微秒边界 `2262-04-11T23:47:16.854775Z` | **PASS** | HTTP 200，正常查询索引库 |
| **CP4** | 溢出 ISO 微秒 `2262-04-11T23:47:16.854776Z` | **PASS** | HTTP 422 严密拦截，绝不发生 SQLite 500 溢出 |
| **CP5** | 公元 9999 年 ISO `9999-12-31T23:59:59Z` | **PASS** | HTTP 422 严密拦截，绝不发生 SQLite 500 溢出 |
| **CP6** | 1970 年前负纳秒 (`-1`, `1969-12-31T23:59:59Z`) | **PASS** | HTTP 422 严密拦截 |
| **CP7** | 回归：media_type IN / NIN | **PASS** | HTTP 200，正确使用 `or_` / `and_` 复合表达式并过滤媒体类型 |
| **CP8** | 回归：Fail-closed AST 结构校验 | **PASS** | 字段拼写错误、额外多余字段、非法 child/children 均被 422 拒绝 |
| **CP9** | 回归：浮点数 / 无时区 ISO mtime | **PASS** | 严格强类型拦截，一律返回 422 |
| **CP10**| Preview 零副作用与零数据突变 | **PASS** | 0 plan, 0 items, 0 new jobs, 0 journals, 0 quarantines, 100% 物理文件 Manifest 一致 |
| **CP11**| SQLite 物理完整性校验 | **PASS** | `PRAGMA integrity_check = ok`, `PRAGMA foreign_key_check = 0`, `PRAGMA journal_mode = wal` |

---

## 6. Artifact & Provenance (交付工件与溯源信息)
- **Branch**: `v0.3.5-gate5a`
- **Candidate ZIP**: `nas-file-center-v0.3.5-gate5a-hotfix2.zip`
- **ZIP Comment / Commit**: 当前 HEAD Commit
- **SHA256**: 记录于外部 `SHA256SUMS.txt`

---

## 7. Current Status (当前状态声明)
```text
Gate5-A-hotfix2 implementation candidate ready for independent review
Gate5-A remains HOLD pending independent review
Gate5-B remains FORBIDDEN
v0.3.5 remains NOT CLOSED
```
