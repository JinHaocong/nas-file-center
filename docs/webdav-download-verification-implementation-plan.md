# WebDAV 下载完整性校验 — Implementation Plan / TDD Matrix（待批准）

状态：**DRAFT — planning only**；不得将以下命令/文件视为已实现或已测试。
配套 Architecture Freeze：[`webdav-download-verification-c0-architecture-freeze.md`](webdav-download-verification-c0-architecture-freeze.md)。
冻结用户需求：**OpenList WebDAV → NAS；严格 SHA256 双端完整读取；原始相对路径完全一致；只读**。
Source audit baseline：`main@b64d7aed7befe6386cf0c84370c732d771380310`（2026-10-16 设计起点）。已有 PR #259 是其它 CI/acceptance 工作，禁止混入其变更。

## 0. 权限 / 发布门禁

先由用户明确批准 C0 Architecture Freeze，再允许 production implementation；以批准时 fresh `main` 创建唯一实现分支。新功能不自动合并到 `main`，最新 PR HEAD 必须包含所有 GitHub Check Runs + Workflow Runs 的成功证据；涉及真实远端/本地文件行为的 closure 另需独立 review、Docker 和隔离 NAS evidence。不得复用别的 SHA 的结果。

## 1. C1 — 只读 WebDAV transport + 安全目录清单

建议新增：
- `app/download_verification/webdav.py`：固定 endpoint 的管理员配置，安全 requests/response streaming、PROPFIND Depth 1、XML response parser、GET 原始流、超时和限制；
- `app/download_verification/paths.py`：严格解析 URL/href 和相对路径，判定根内、拒绝歧义/冲突；
- `tests/test_download_verification_webdav.py`：完整 mock 207 + unsafe cases；
- `tests/test_download_verification_ssrf.py`：DNS/IP、302、TLS/credential leak fail-closed。

RED first：同名条目、路径 escape、混合 propstat 和 302 意外、XML 截断测试必须失败；GREEN 最小实现；REFACTOR 仅保留无副作用 transport。服务端原始表示策略失败时 V1 返回明确不可验证状态。

## 2. C2 — bounded local manifest + DB + read-only 比较

建议新增：
- `app/download_verification/local.py`：no-follow root/FD recursion；特殊对象显式 `UNVERIFIED` 而非静默跳过；
- `app/download_verification/compare.py`：按精确相对路径、类型、大小生成唯一清单联结结果，包括空目录；不包含跨名匹配；
- `app/download_verification/models.py` 或 `app/models.py`：run/items 两表与索引、外键；
- `app/download_verification/service.py`：短事务写入和分页；
- `app/db.py`：现有 DB boot-time backed-up additive migration + legacy preservation；
- `tests/test_download_verification_compare.py`、`tests/test_download_verification_migration.py`。

RED：大小相同但字节不同未验证、0-byte、目录差异、超过旧目录对比 10k 项时仍能分批运行、DB 断电重启保留 `INCOMPLETE` 且不造假。旧 `app/batch/directory_compare.py` 的 256MiB 和 10,000-item 旧合同不改。

## 3. C3 — Worker 严格双端 SHA256 / stable manifest

建议新增：
- `app/download_verification/handler.py`：`@register_handler`，绑定 WorkJob / progress / checkpoint，远端完整 GET + 本地完整读取 SHA256，逐文件提交验证结果；
- `app/download_verification/verify.py`：本地 fd/path identity、远端数量/HTTP framing/metadata revalidate；
- `app/tasks/handlers.py` 或显式 registry initialization：注册新 handler；
- `app/tasks/recovery.py`：评估将该 read-only job 加入 `RESOURCE_CONTROLLED_JOB_KINDS`，不允许 Scheduler 自动派发；
- `tests/test_download_verification_worker.py`、`tests/test_download_verification_races.py`。

RED：同大小不同内容、>256 MiB 的模拟流、断流、HTTP 206/302/编码变形、远端二轮 scan 改变、本地 symlink/ABA/文件修改、zFuse ctime-only 不误报、lease loss/restart/cancel/pause 后绝不 `VERIFIED_IDENTICAL`；GREEN：按文件边界 checkpoint/restart 重新读取。保持 IO 限速和源端流量可见，不保存远端 payload。

## 4. C4 — HTTP API + UI + read-only UX

建议新增：
- `app/download_verification/router.py`：管理员创建、分页列举、详情、项目、重试；不允许通过 API 提供任意 URL；
- `app/main.py`（或现有 router 集成点）：新 router；
- `frontend/src/api/downloadVerification.ts`、`frontend/src/pages/DownloadVerification/index.tsx`、类型模型和路由/导航；
- `frontend/tests/download_verification.test.ts`：筛选、分页、进度和错误状态；
- `tests/test_download_verification_api.py`：401/403, CSRF, POST allowlist, secret redaction。

界面必须显示：WebDAV 和 NAS root、远端重复读取约等于校验文件大小的网络流量提示、SHA256 校验进度、异常清单、可验证结果/不可验证原因、CSV export（防公式注入），并明确远端非原子快照限制。不出现“大小相同=通过”。

## 5. C5 — 评审 / CI / 真 NAS

- `PYTHONPATH=. pytest -q` + 新 focused suites；前端 `npm ci`、typecheck、test、build；依赖变更 audit；linux/amd64 Docker。
- 当前生产版本 `0.4.7` 的迁移回归，验证原 SQLite、IndexedPath、Task Center、旧 DirectoryDiff、Audit/Quarantine 完全保留。
- 同一 PR 最新 exact HEAD 的 GitHub Actions check runs/workflow runs 全成功后方可考虑 merge；独立 reviewer 不由实现者自称。
- 隔离验收使用 NAS `/tmp/zfsv3/sata11/15246330601/data/NASTest` 下数据，**不写 production DATA/CONFIG**。要测真实远端，从真实 OpenList/PikPak 只读子目录取管理员明确允许的少量样本。部署/测试 secrets 不贴在 issue/CI 日志。
- Real NAS matrix：1 file/empty/large, same-size-different-content, missing local/remote, extra empty directory, unicode, remote 302/proxy, server-side mutation during scan, denied/timeout/429, cancel/restart；测试结束验证 zero-residue。
- C5 通过后才允许让新增功能正式标记可用；生产 Komodo 密钥注入/网络变更/部署仍单独授权。

## 未完成决策与外部依赖

此设计冻结草案已明确用户选择，无需再次确认 A/B/C 模式。仍需在实现前评审/实测：
- 实际 OpenList endpoint 是否支持 PikPak 原始 WebDAV GET 的同源代理 200 streaming；
- admin secrets delivery（推荐 Docker secret / password-file），是否需要 UI 配置多 profile：V1 推荐只支持一个固定连接；
- 后端受限网络的 SSRF allowlist 与 TLS 模式；
- 非原子远端状态下 `VERIFIED_IDENTICAL` 的保证措辞，不能升格为某个时间点 PikPak 原始云数据的强证明；
- 资源上限和真实 NAS 性能/流量预算。

以上均不授权扩大文件系统变更能力。
