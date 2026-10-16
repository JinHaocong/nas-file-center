# WebDAV 下载完整性校验 — C0 Architecture Freeze（草案）

状态：**IMPLEMENTATION AUTHORIZED BY USER 2026-10-16 / SOURCE PR #261 UNDER CI / REAL-NAS ACCEPTANCE PENDING**
产品决策：2026-10-16；仅 OpenList WebDAV、严格双端 SHA256、保留原始相对目录结构。
源码基线：`main@b64d7aed7befe6386cf0c84370c732d771380310`（独立设计分支从该 SHA 创建）。
此文档是新增独立只读功能的设计草案；不能视为 CI、Docker 或真实 NAS 验收证据。

## 1. 范围 / 用户承诺

场景：用户已经通过 OpenList 挂载 PikPak，并把所选云端文件夹复制/下载到 NAS。校验时选择**云端 WebDAV 目录**与**NAS 本地目录**，严格按相对路径进行递归比较，包括空目录。逐个完整读取远端 GET 返回的原始表示及本地普通文件，分别计算 SHA256；不创建第二份本地文件，不修改 PikPak/NAS 文件。

V1：一条连接配置可绑定一个经过运维批准的 OpenList `/dav/` endpoint；一个校验任务 = 该连接内一个只读 remote root + `ALLOWED_ROOTS` 内一个 local root。相对路径、大小写、Unicode 码点及文件后缀保持精确语义；不自动折叠、移动、重命名、不支持“内容相同但改名算通过”。

严格验证通过的含义：在两次完整且无错误的 WebDAV 目录列举之间，针对每个对应文件完整读取 WebDAV GET 和本地字节流并得到相同 SHA256，远端返回表示满足“原始文件”读取前置条件，元数据/路径稳定，本地描述符和路径身份在校验前后稳定，所有目录和文件集合一一对应、无未知项。**这不是远端服务原子快照或对 PikPak 底层存储独立真实性的密码学证明**；WebDAV 服务端若遗漏或伪造数据，客户端无法凭空发现。

V1 不包括：下载/同步/修复文件、远端修改、目录映射、文件名归一化、WebDAV 写操作、自动定时任务、通过文件扩展名排除文件、依赖 ETag 代替 SHA256、把“大小相同”视为内容相同。

## 2. 已有源码 authority / 兼容性

- `app/batch/directory_compare.py`：本地双目录只读 Preview，每侧 10,000 条目，单对 SHA256 <=256 MiB；保留原有行为和 API 不变。可以提取纯比较规则或采用独立的清单联结服务，**不得**直接在老的 HTTP 同步 Preview 上加远端全量读取。
- `app/api/router.py`：已有 `/api/directories/compare/preview` 与 `/verify`；新功能用独立 `/api/download-verifications/*`，避免改变既有状态语义。
- `app/media/integrity.py`：可参考 SHA256 分块和基于 `dev/ino/size/mtime_ns` 的本地身份验证；旧单机媒体 baseline 不表示远端内容真相。zfuse 读诱发 ctime 变化时，ctime 仅用于诊断；仍需描述符、路径 ABA、安全范围复验。
- `app/tasks/handlers_base.py`、`app/tasks/context.py`、`app/worker.py`：复用注册的 `WorkJob`、单 Worker lease、checkpoint、Task Center；没有新的 daemon / Executor。长时间网络读取期间必须周期 checkpoint / cancellation / lease fencing。
- `app/models.py` + `app/db.py`：采用独立持久结果表、短 SQLite 事务和升级前备份，不把全量文件清单塞入 64 KiB checkpoint。
- `app/path_safety.py` / `ALLOWED_ROOTS` / `QUARANTINE_ROOT`：本地只读权限边界保持不变；符号链接、特殊文件、reserved paths 不可静默跳过并报全绿。
- 前端现有 `frontend/src/pages/DirectoryDiff/` 仅供 UI 复用，不改变“大小相同未验证”的原始类型。

## 3. WebDAV 客户端协议与目录枚举

- 端点为管理员预配置的固定 `https://<approved-host>/dav/`（同容器网络 HTTP 需独立明确批准）；校验任务只能指定该 endpoint 内的受限相对子目录。账号仅授予 WebDAV Read，不授予 Manage。
- 对每层目录调用 `PROPFIND` + `Depth: 1`；显式请求 `resourcetype`、`getcontentlength`、`getetag`、`getlastmodified`。只接受正确的 `207 Multi-Status`、完整 XML、各资源成功的 propstat；单条错误、401/403/404/5xx、畸形 XML、缺少必要类型/大小属性 => 整个清单不可信，fail closed。
- 安全、限量、抗 XML bomb 解析；禁止实体扩展/外部实体，限制单次响应字节数、单目录成员数、层级与总任务预算；超限中断而非输出截断后的“成功”。
- WebDAV `href` 必须在批准的 WebDAV 根下，按 segment 严格解析百分号编码、禁止重复路径、`..`、绝对外逸、encoded slash/backslash 分隔符歧义、NUL 与大小写/Unicode 归一化碰撞。将服务端自身目录条目仅按验证的 canonical URL 排除；不是按返回列表第一项猜测。
- 包含空目录；对未支持资源类型、无法读取的子目录、枚举循环和冲突 entry 保留错误证据；不能默默忽略。远端 WebDAV 无法明确表明 symlink 时，对可见表示按类型处理但不宣称已知其真实底层结构。
- 目录枚举至少两轮：校验前完整 manifest、内容读取完成后再完整 manifest；用稳定的相对路径/类型/大小及可用 ETag/mtime 比较。若 manifest 发生变化，标记 `REMOTE_CHANGED` / `STALE`，不发布完全一致。**双遍枚举也不能证明远端是原子快照**。
- WebDAV 目录项不得只因返回名包含非 ASCII、空格、`#`、`%` 就被破坏；严格编码每一独立路径 segment。

## 4. 原始字节 GET 与 SHA256

- 对一个候选文件，先确认对应路径、类型、大小一致；再分别完整读取远端 HTTP GET（`Accept-Encoding: identity`、无 Range）及本地受控常规文件，使用有界缓冲（建议 4–8 MiB）各算一遍 SHA256，**不写原始文件到 `/config` 或 `/data`**。
- 远端默认 **不跟随 HTTP 30x**，不能把重定向到公网/CDN 的 URL 自动放行，也不能把内部 WebDAV Basic 认证带到第三方 host。要求 OpenList 对被校验的 PikPak 文件走可验证的同源原始内容代理；若返回 302/转码资源/不支持 GET，报告 `REMOTE_ORIGINAL_UNAVAILABLE`，绝不显示通过。真实 OpenList/PikPak 读取策略必须通过隔离实测验证。
- 只接受完整 200 字节表示，拒绝意外 206、Content-Range、Content-Encoding 非 identity、HTTP 失败、body 异常终止；核对实际读取的字节数与已验证远端 getcontentlength、可用 HTTP Content-Length、结束后的再查询元数据。长度未知、矛盾或未能证明完整结束 => `UNVERIFIED`。
- ETag/Last-Modified 仅辅助变化检测，弱 ETag 不能证明内容恒定。强且可信的 ETag 可以用于 `If-Match`，仍须读取并计算 SHA256。若远端不提供可靠版本/etag，不能仅靠前后列表相同宣称完全抵抗中途 ABA 替换；UI 必须披露“非原子远端快照”保证边界。
- 本地每层用 no-follow fd-relative 遍历，文件用 `O_NOFOLLOW` 和目录描述符打开，校验 `regular/dev/ino/size/mtime_ns`，读取后验证 fd 和原路径仍是授权身份。现有 zfuse 的 hashed read 兼容性要求 ctime 为 diagnostic-only；本地对象变化 => `LOCAL_CHANGED`。
- 0 字节文件仍必须走正常 GET EOF 与本地 SHA256；任何网络断流、超时、DNS 变更、取消/租约失效不得被记录为 matched。
- V1 每文件从头校验；失败重试/重启必须重新确认远端、本地身份。允许文件边界取消与暂停；不承诺任意字节断点续传，也不沿用已经 stale 的旧结果。

## 5. 威胁模型 / 连接凭据

- 连接 endpoint 不是任意用户填写的外部 URL：管理员部署时批准确切 host/scheme/port/根路径和 DNS/IP 网络范围；阻断 SSRF、link-local、云 metadata、重绑定、代理/重定向绕过。逐请求固定目标策略、对 DNS 解析地址重新校验；任何请求不得跟随未批准域名或将凭据附加到其它 authority。
- V1 建议部署配置 `DOWNLOAD_VERIFY_WEBDAV_BASE_URL`、`DOWNLOAD_VERIFY_WEBDAV_USER` 与仅 Worker 可读的 `DOWNLOAD_VERIFY_WEBDAV_PASSWORD_FILE`。不把密码写入 `WorkJob.state_json`、SQLite、审计、响应、命令行或源码；日志/异常脱敏认证 header、query、userinfo、cookie 和原始外链。
- TLS 必须校验证书；对仅 Docker 内部 HTTP 连接需要显式独立 opt-in，不接受无提示 skip-verify。
- 普通用户可查询有权限范围内的报告；启动任务/连接配置默认仅管理员权限，后续 RBAC 调整需独立评审。所有 API 有 CSRF/Origin/鉴权、安全的分页查询。
- 所有远端请求仅 `PROPFIND` / `GET` / 可选只读 `HEAD`；无 `PUT`/`DELETE`/`MOVE`/`COPY`/`MKCOL`；本地仅打开读取，0 Plan / Quarantine / mutation authority。业务配置中的 `ALLOW_MUTATION=false` 不阻止只读任务。

## 6. 运行状态 / 结果等级

独立任务 `kind=download-verify-webdav`（不加入 Scheduler V1 target allowlist），状态机复用通用 `WorkJob`。业务阶段：

`QUEUED -> REMOTE_DISCOVER -> LOCAL_DISCOVER -> COMPARE -> HASHING -> REVALIDATE -> FINALIZE`。

单项状态至少：`VERIFIED_MATCH`、`HASH_MISMATCH`、`ONLY_REMOTE`、`ONLY_LOCAL`、`SIZE_MISMATCH`、`TYPE_MISMATCH`、`REMOTE_CHANGED`、`LOCAL_CHANGED`、`UNVERIFIED`、`ERROR`。目录条目同样参与一致性判定（含空目录）。

报告总结：
- `VERIFIED_IDENTICAL`：两个完整 manifest 一致；所有路径、类型、大小匹配；每个文件两端完整字节 SHA256 一致；无 skipped/error/unknown；本地稳定；远端无可见变化；原始表示策略可被验证。
- `DIFFERENT`：在可信 manifest 下发现确定的 missing/extra/size/type/hash 差异。
- `INCOMPLETE`：远端/本地列举或读取异常、上限、无法证明原始表示、用户取消、部分不可访问。
- `STALE`：远端/本地在验证期间出现变化；必须重新完整校验。
- 允许报告同时保留已发现的具体 DIFFERENT 行与 INCOMPLETE/STALE 的任务结论；**任何未知项优先阻止 `VERIFIED_IDENTICAL`**。WorkJob.status=`completed` 只代表任务正常终止，**不代表内容相同**。

后台进度用已校验文件数/字节数与总数，未知总量不得伪造百分比；保守默认一个远端内容流并发，后续压测允许 2，遵守现有 Resource Policy、Worker lease、网络超时与速率/流量上限。

## 7. 持久化 / API / 前端

设计建议新增、独立的 SQLite 表（最终列名在实施前 review）：
- `download_verification_runs`：`id`、`work_job_id`、`source_profile_id`（仅非敏感 ID）、remote relative root、local root、status、开始/结束时间、统计、前/后 manifest digest、错误码。
- `download_verification_items`：`run_id`、canonical relative path、resource kind、remote/local bytes、remote/local SHA256（成功读取时）、status、reason_code、时间戳。唯一键 `(run_id, relative_path)`；支持 server-side page/filter。路径不能携带 WebDAV secret。
- 可在 manifest 建立阶段使用 DB 流式分批写入/有界合并；使用事务分批提交、不一次将几十 TB 目录放进 RAM，不把明文凭据/完整清单塞入 WorkJob checkpoint；migration 必须遵守原 DB 备份/向后兼容。

API（意向合同，须先 TDD）：
- `POST /api/download-verifications`：管理员创建校验任务（profile ID + remote relative root + local root），返回 run/job IDs。
- `GET /api/download-verifications`、`GET /api/download-verifications/{id}`、`GET /api/download-verifications/{id}/items?page=&status=`：分页列表/摘要/差异项。
- `POST /api/download-verifications/{id}/retry`：生成新尝试 / WorkJob，不篡改旧结果；Cancel/Pause 遵从现有 Task Center 允许操作。
- 连接测试可新增管理员只读 preflight，但不得将完整 WebDAV response 或 secret 回传给浏览器。

UI：独立“下载完整性校验”页面：连接状态 + WebDAV 内远端目录选择/受控路径 + NAS DirectoryPicker + 明确“严格 SHA256（远端重新读取全部字节）”流量提示 + 开始 + 任务历史 + 精确结果和错误原因 + 服务端分页/CSV。仅只读，永远没有一键修复或自动删除。

## 8. 中断、性能与部署边界

- 通过受控请求生命周期（连接/首字节/读超时、数据流取消）和每一定量读取触发 JobContext checkpoint，不持有长 SQLite 写锁；Worker 失租即停止新远端读/本地哈希及 DB 结果提交，旧 Worker 不得将旧任务标 PASS。
- 暂停/取消优先在块边界响应。单文件中途暂停后应从文件开始重新散列，不能用未认证的 partial digest 续写结果。
- 同一文件二次校验需要远端、NAS 都全量读一遍。计划校验 `N` 字节至少产生大约 `N` 字节云端返回流量以及 `N` 字节本地读取；WebDAV 代理可能产生额外设备/外网流量和配额开销。
- 不增加 `/data` 宿主机挂载的写权限、不暴露整个 `/tmp/zfsv3`；只有 Worker 出站访问已批准 OpenList endpoint。发布前必须单独审计 Komodo 网络、凭据文件挂载和 Zoraxy/TLS。
- 不能因为云端限流或失败自动重试大量 GET 造成意外配额成本；使用退避、有限次数与明确可见的错误状态。

## 9. 必须通过的测试门禁

1. WebDAV 207 XML/Depth1、self entry、空目录、混合 200/4xx propstat、畸形/超大 XML、重复 href、Unicode、编码的斜杠、百分号、空格、路径逃逸、目录循环。
2. WebDAV 401/403/404/429/500、连接超时/中断、chunked 截断、Content-Length/metadata 不一致、GET 302、206、编码变体、访问重定向外部私有地址、Basic credential 不泄漏。
3. 路径相同且 SHA 一致 / 同大小不同 SHA / 大小不同 / remote-only / local-only / 目录类型冲突 / 空目录不一致 / 0-byte / >256 MiB 模拟与实际流式大文件。
4. 远端前后两次 manifest 变化、GET 中途变化/ABA（能检测时）、本地读中变化、symlink 和本地路径替换、zFuse ctime-only 正例、本地禁入目录/特殊文件不得误报 PASS。
5. Worker cancel/pause/retry、worker lease loss、重启后未完成记录不可发布 PASS、DB 批量回滚与结果分页、旧 DirectoryDiff API/测试完全不变、旧数据库迁移/备份。
6. 输出凭据脱敏、SSRF/DNS 重绑定测试、内存和流量限额、项目 Resource Control 容量限制及多任务竞争。
7. 后端 full pytest、前端 typecheck/test/build、linux/amd64 Docker、最新 PR HEAD 全部 CI checks 通过、独立复审。
8. 极空间 NAS `NASTest` 下隔离 fixture，配合可控测试 WebDAV endpoint 与少量**明确授权**的 PikPak 样本验证原始流；不在 production DATA/CONFIG 上创建测试数据。CI synthetic evidence 不等于 PikPak 实际行为接受证据。

## 10. Gate 顺序与待验证事项

C0（本草案）source audit + Architecture Freeze review → **用户显式批准** → C1 WebDAV 安全连接/枚举 TDD → C2 本地 manifest + DB + 分页 → C3 Worker streaming SHA256、远端稳定性/租约保护 → C4 API/UI/报告 → C5 full CI、独立审查、Docker、真实 OpenList/PikPak/NAS 小数据验收 → 才可 merge/release。

需要通过真实部署/测试最终验证：OpenList/PikPak 在选定 WebDAV 策略下 GET 是否返回原始字节、无重定向代理模式是否可用、Content-Length/ETag 行为、目录并发修改表现、zfuse 大文件读取及网络限流行为。在此之前，不承诺这些能力已支持。

参考：RFC 4918 WebDAV / OpenList WebDAV Read + /dav/ 文档 / OpenList PikPak driver 文档。实施与验收不得把设计假设当作生产证据。
