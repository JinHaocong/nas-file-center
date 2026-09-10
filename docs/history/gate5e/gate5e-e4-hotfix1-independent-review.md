# Gate5-E / E4-hotfix1 Independent Review Report

## 1. 评审元数据与状态定义

- **评审分支 (Branch)**: `v0.3.5-gate5c-hotfix4`
- **评审 HEAD (reviewed HEAD)**: `43d250ec29272773e6a3a8ed16194bc27d5e3f27` (`docs(gate5e): record E4 hotfix1 verification and provenance`)
- **代码修复父提交 (actual code-fix parent)**: `702f93f0352eda87244544a8d9e63d893db26dfb` (`fix(gate5e): fence E4 mutations with stable directory descriptors`)
- **审查缺陷等级 (finding severity)**: **BLOCKER**
- **当前审查结论 (status)**: **NOT PASS / NOT CLOSED**

---

## 2. hotfix1 成效确认

Independent Review 确认，E4-hotfix1 通过引入 `parent_fd` 链式遍历与 `os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW`，已大幅收窄了祖先路径劫持与符号链接替换的竞态攻击面：
- `mkdir_empty`: 成功通过从 `anchor_fd` 逐级打开目录描述符，阻断了突变前父目录被替换为符号链接时的穿透逃逸问题；
- `rmdir_empty`: 成功消除了跨祖先目录重定向与符号链接目标误删风险。

---

## 3. 阻塞性缺陷剖析（Root Cause & Finding）

### 3.1 核心根本原因 (Root Cause)
在 POSIX 标准与现有 Python 系统调用接口中，`os.rmdir(leaf, dir_fd=parent_fd)`（底层映射为 `unlinkat(parent_fd, leaf, AT_REMOVEDIR)`）是一个**按文件名（lexical entry）执行的目录项移除操作**，操作系统内核**不提供**针对目录的原生条件原子删除系统调用（即不存在“仅当当前叶子 inode 依然等于指定 inode 时才删除”的原子系统调用原语）。

### 3.2 最小竞态时序 (Minimal Race Sequence)
hotfix1 在突变前加入了 `parent_fd` 内的 `os.stat` 校验，但仍存在叶子目录身份的 TOCTOU 窗口：

```text
1. final os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
2. Identity matches Frozen (st_dev == item.expected_device and st_leaf.st_ino == item.expected_inode) -> 通过
3. [RACE WINDOW]: 并发进程/外部 Actor 删除该 leaf，并在同名路径下重建了另一个合法的空目录（inode 变更为 Y）
4. os.rmdir(leaf, dir_fd=parent_fd) 执行
```

### 3.3 缺陷影响与未成立的强保证
在上述时序的步骤 3 与 4 之间，`os.rmdir` 将直接删除调用时刻对应的目录项（即新创建的 inode Y），而无法在内核执行删除的一瞬间判定 inode 是否已被改变。

因此，以下强保证目前**尚未成立**：
- `identity swap immediately before mutation must fail closed`（突变紧邻前发生身份替换必须 fail-closed）
- `replacement object must never be deleted`（替换对象绝不能被删除）
- `stable parent_fd completely eliminates final mutation TOCTOU`（稳定的 parent_fd 完全消除了最终突变 TOCTOU）**不得继续作为已证明结论**。

### 3.4 为什么增加 stat 无法解决该问题
这不是再在突变前增加一次 `stat` 或 `lstat` 可以解决的问题。任何在用户态先 `stat` 再 `rmdir` 的两阶段模式，在 `stat` 返回与 `rmdir` 生效之间都必然存在微秒级的内核抢占与并发窗口。

---

## 4. 为什么 parent_fd 解决了祖先遍历但未解决条件删除

- **解决祖先遍历**：`parent_fd` 基于已打开的稳定目录文件描述符锁定父容器，确保系统调用不会沿着被外部篡改的路径解析到非预期的父目录之外，杜绝了中间路径重定向。
- **未解决条件删除**：目录项的删除语义在文件系统中是由父目录持有的 dirent 决定的。`os.rmdir(leaf, dir_fd=parent_fd)` 只能锚定在正确的父目录中按名称删除子项，但无法将删除操作与叶子对象的物理 inode 进行内核级原子绑定。

---

## 5. 后续必须执行步骤 (Required Next Step)

1. **窄范围 E4 Architecture Freeze Amendment**：
   - 在进入 E4-hotfix2 生产代码实现之前，必须先编制并批准一份窄范围的 **E4 Architecture Freeze Amendment**（架构冻结修订案）。
   - 该修订案必须正视 POSIX 目录删除原语的客观物理约束，明确定义 File Center 对叶子空目录并发替换的合同保证边界、语义声明、降级防护或安全重命名隔离策略。
2. **严禁开始生产代码**：
   - 在架构修订案完成并正式冻结前，**严禁开始 E4-hotfix2 代码实现**。
3. **严格禁止事项**：
   - **Gate5-F 仍然严禁开始**。
   - **严禁将 E4 标记为 PASS 或 CLOSED**。

---

## 6. 状态结论 (Review Status)

```text
E4-hotfix1 Independent Review: NOT PASS / NOT CLOSED
Severity: BLOCKER
Next: E4-hotfix2 Architecture Freeze Amendment
```
