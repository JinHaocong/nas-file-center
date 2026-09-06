# NAS File Center v0.3.5 Gate5-A-hotfix3 — Implementation & Safety Walkthrough

## 1. Context & Scope (背景与本次范围)

当前整体状态：
```text
Gate2 = PASS
Gate3 = PASS
Gate4 = PASS
NAS File Center v0.3.4 = CLOSED

Gate5-A-hotfix2 independent review:
  Original P2-01 (media_type in/nin 500) = CLOSED
  Original P2-02 (fail-closed AST) = CLOSED
  Original P2-03 (mtime/string strict typing) = CLOSED
  P2-04 direct SQLite INT64 overflow = CLOSED

New finding:
  P2-04 timezone normalization edge = OPEN (datetime.astimezone OverflowError -> HTTP 500)

Gate5-A = HOLD pending independent review
Gate5-B = FORBIDDEN
v0.3.5 = NOT CLOSED
```

### 1.1 本轮唯一目标
修复 timezone-aware ISO datetime 在执行 `datetime.astimezone(timezone.utc)` 时，当日期处于公元 1 年或 9999 年极端时区偏移（例如 `9999-12-31T23:59:59-12:00` 换算至 UTC 跨入公元 10000 年，或 `0001-01-01T00:00:00+14:00` 换算至 UTC 跨入公元 0 年）所引发的 Python `OverflowError: date value out of range`，导致 Filter Preview 返回 HTTP 500 的问题。将其统一规范化为严格的 HTTP 422 (`FilterValidationError`)。

### 1.2 严格契约与算术原则
1. **彻底避免 `astimezone()`**:
   - 废除 `dt.astimezone(timezone.utc)`，避免构造出超出 Python `datetime` 年份表示范围（1~9999）的中间对象。
   - 定义 `EPOCH_NAIVE = datetime(1970, 1, 1)`。
   - 提取 `offset = dt.utcoffset()` 并获取 `local_naive = dt.replace(tzinfo=None)`。
   - 精确计算 `delta = local_naive - EPOCH_NAIVE - offset`。
2. **禁止回退浮点数**:
   - 绝不使用 `dt.timestamp()` 或 `float` 运算。
   - 继续采用纯整数微秒/天数累加：
     $$\text{ns} = \Delta\text{days} \times 86400 \times 10^9 + \Delta\text{seconds} \times 10^9 + \Delta\text{microseconds} \times 1000$$
   - 统一由 `if ns < MIN_MTIME_NS or ns > MAX_MTIME_NS` 拦截超范围值并抛出 `FilterValidationError` (422)。
3. **范围红线**:
   - 仅允许修改 `app/filters/validation.py`、`tests/test_filter_ast.py`、`tests/test_filter_preview.py`、`walkthrough.md`。
   - 绝不修改 DB Schema、`compiler.py`、`schema.py`、`models.py`。
   - 绝不执行 `git push`、`git tag`、`docker push`。
   - 绝不提前宣布 Gate5-A PASS 或启动 Gate5-B。

---

## 2. Technical Implementation (技术实现)

### 2.1 核心代码重构
[`app/filters/validation.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/filters/validation.py):
```python
INT64_MAX = (1 << 63) - 1
MIN_MTIME_NS = 0
MAX_MTIME_NS = INT64_MAX
MAX_EPOCH_SECONDS = INT64_MAX // 1_000_000_000
EPOCH_NAIVE = datetime(1970, 1, 1)


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
        offset = dt.utcoffset()
        if offset is None:
            raise FilterValidationError("mtime ISO datetime must be timezone-aware (missing timezone)")
        local_naive = dt.replace(tzinfo=None)
        delta = local_naive - EPOCH_NAIVE - offset
        ns = delta.days * 86_400 * 1_000_000_000 + delta.seconds * 1_000_000_000 + delta.microseconds * 1_000
        if ns < MIN_MTIME_NS or ns > MAX_MTIME_NS:
            raise FilterValidationError(f"mtime nanoseconds out of supported range ({MIN_MTIME_NS} to {MAX_MTIME_NS}), got {ns}")
        return ns
    raise FilterValidationError(f"mtime value must be timezone-aware ISO string or integer epoch seconds, got {type(val).__name__}")
```

---

## 3. TDD RED $\rightarrow$ GREEN 验证记录

### 3.1 真实 RED 证据
在修复前直接复现极端时区边缘下的 OverflowError 与 HTTP 500：
```text
=== Validator 底层复现 ===
_parse_mtime_to_ns("9999-12-31T23:59:59-12:00") -> OverflowError: date value out of range
_parse_mtime_to_ns("0001-01-01T00:00:00+14:00") -> OverflowError: date value out of range

=== 预览 API 复现 ===
POST /api/filters/preview with mtime="9999-12-31T23:59:59-12:00" -> Status: 500 Internal Server Error
POST /api/filters/preview with mtime="0001-01-01T00:00:00+14:00" -> Status: 500 Internal Server Error

=== Pytest TDD 初始失败 ===
FAILED tests/test_filter_ast.py::test_mtime_strict_typing_and_timezone - OverflowError: date value out of range
FAILED tests/test_filter_preview.py::test_preview_fail_closed_validation_errors - OverflowError
2 failed, 17 passed
```

### 3.2 修复后 GREEN 结果
- `tests/test_filter_ast.py` & `tests/test_filter_preview.py`: **19 passed (100% GREEN)**。
- 关键测试用例行为确认：
  - `9999-12-31T23:59:59-12:00` $\rightarrow$ 严格返回 HTTP 422 (`FilterValidationError: mtime nanoseconds out of supported range (0 to 9223372036854775807), got 253402343999000000000`)
  - `0001-01-01T00:00:00+14:00` $\rightarrow$ 严格返回 HTTP 422 (`FilterValidationError: mtime nanoseconds out of supported range (0 to 9223372036854775807), got -62135647200000000000`)
  - `1970-01-01T14:00:00+14:00` (大正向时区偏移换算至纪元 0) $\rightarrow$ 正常返回 HTTP 200，精确解析为 0 ns
  - `1970-01-01T00:00:00-01:00` $\rightarrow$ 正常返回 HTTP 200，精确解析为 3600000000000 ns
  - `9223372036` $\rightarrow$ HTTP 200
  - `9223372037` $\rightarrow$ HTTP 422
  - `2262-04-11T23:47:16.854775Z` $\rightarrow$ HTTP 200
  - `2262-04-11T23:47:16.854776Z` $\rightarrow$ HTTP 422

---

## 4. 全量自动化测试与回归验证

### 4.1 Gate5-A 专项测试 (6 文件)
```bash
pytest tests/test_filter_ast.py tests/test_filter_compiler.py tests/test_filter_index_freshness.py tests/test_filter_policy.py tests/test_filter_preview.py tests/test_filter_preview_readonly.py
```
$\rightarrow$ **30 passed in 1.33s (100% PASS)**

### 4.2 Gate2, Gate3, Gate4 安全回归测试
```bash
pytest tests/test_gate2*.py tests/test_gate3*.py tests/test_gate4*.py
```
$\rightarrow$ **108 passed in 9.93s (100% PASS)**

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
$\rightarrow$ **Build: Success (3.32s)**

---

## 5. Docker 独立黑盒验收 (11/11 Checkpoints PASS)

运行 `scratch/test_gate5a_hotfix3_blackbox_acceptance.py` 对真实构建的 Docker 镜像 `nas-file-center:v0.3.5-gate5a-hotfix3` 进行黑盒验收：

| 检查点 | 检查内容 | 结果 | 核心断言与安全表现 |
| :--- | :--- | :---: | :--- |
| **CP1** | 时区溢出边界 `9999-12-31T23:59:59-12:00` | **PASS** | HTTP 422 严密拦截，绝不发生 `OverflowError` 500 |
| **CP2** | 时区下溢边界 `0001-01-01T00:00:00+14:00` | **PASS** | HTTP 422 严密拦截，绝不发生 `OverflowError` 500 |
| **CP3** | 合法时区偏移 `1970-01-01T14:00:00+14:00` | **PASS** | HTTP 200，精确计算为 0 ns，成功匹配全部索引文件 |
| **CP4** | 安全整型边界 `9223372036` | **PASS** | HTTP 200，正常查询索引库并返回 `matched_count: 0` |
| **CP5** | 溢出整型 `9223372037` | **PASS** | HTTP 422 严密拦截，绝不发生 SQLite 500 溢出 |
| **CP6** | 安全 ISO 微秒边界 `2262-04-11T23:47:16.854775Z` | **PASS** | HTTP 200，正常查询索引库 |
| **CP7** | 溢出 ISO 微秒 `2262-04-11T23:47:16.854776Z` | **PASS** | HTTP 422 严密拦截，绝不发生 SQLite 500 溢出 |
| **CP8** | 回归：media_type IN / NIN | **PASS** | HTTP 200，正确使用复合表达式过滤媒体类型 |
| **CP9** | 回归：Fail-closed AST 结构校验 | **PASS** | 字段拼写错误、额外多余字段、非法形态均被 422 拒绝 |
| **CP10**| Preview 零副作用与零数据突变 | **PASS** | 0 plan, 0 items, 0 new jobs, 0 journals, 0 quarantines, 100% 物理文件 Manifest 一致 |
| **CP11**| SQLite 物理完整性校验 | **PASS** | `PRAGMA integrity_check = ok`, `PRAGMA foreign_key_check = 0`, `PRAGMA journal_mode = wal` |

---

## 6. Artifact & Provenance (交付工件与溯源信息)
- **Branch**: `v0.3.5-gate5a`
- **Candidate ZIP**: `nas-file-center-v0.3.5-gate5a-hotfix3.zip`
- **ZIP Comment / Commit**: 当前 HEAD Commit
- **SHA256**: 记录于外部 `SHA256SUMS.txt`

---

## 7. Current Status (当前状态声明)
```text
Gate5-A-hotfix3 implementation candidate ready for independent review
Gate5-A remains HOLD pending independent review
Gate5-B remains FORBIDDEN
v0.3.5 remains NOT CLOSED
```
