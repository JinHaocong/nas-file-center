# OpenList WebDAV → NAS 严格 SHA256 下载完整性校验

此功能是独立只读任务，**不下载第二份文件，不对 PikPak 或 NAS 进行写入/删除/隔离操作**，也不改变现有双目录差异页面的 10,000 项 / 单对文件 256 MiB 限制。

## 使用

1. 由运维管理员在 OpenList 创建**只读 WebDAV 账号**，授予目标 PikPak 目录的只读访问，不授予文件上传/移动/删除权限。
2. 配置 OpenList 的 WebDAV `/dav/` 端点，**确保 GET 经 OpenList 返回 PikPak 文件原始字节**，不能是播放器转码流或指向不受控 CDN 的 HTTP 30x 跳转。程序默认拒绝跳转；不接受压缩表示、HTTP 206 部分内容。
3. 将 WebDAV 密码放在**仅 Worker 可读取**的只读受保护 secret 文件（例如单独只读 bind mount）。不要把密码明文写入 GitHub、环境变量值或 CI 日志。
4. API/Worker 设置以下一致的变量后重新部署（安全默认不启用本功能）：

```yaml
environment:
  - DOWNLOAD_VERIFY_WEBDAV_BASE_URL=https://your-openlist.example/dav/
  - DOWNLOAD_VERIFY_WEBDAV_USER=verification-readonly
  - DOWNLOAD_VERIFY_WEBDAV_PASSWORD_FILE=/run/secrets/nfc-webdav-password
# 仅为 Worker 容器添加只读 secret mount，
# 例如 /secure/nfc-webdav-password:/run/secrets/nfc-webdav-password:ro
```

若 OpenList 只能通过可信 Docker 内网 HTTP 访问，需额外显式设置
`DOWNLOAD_VERIFY_ALLOW_HTTP=true`；仅在已限定的内部服务网络上允许，公网必须用有效 TLS。固定的 WebDAV origin 来自管理员部署配置，用户发起校验时**不得提供任意 URL**。API 仅验证配置字段存在，不读取密码文件；Worker 运行任务时读取并验证 secret。运行时不继承 HTTP_PROXY/HTTPS_PROXY，也不会将 Basic 凭据随重定向泄漏给其它 host。

5. 登录管理员，打开“文件工具 → 下载完整性校验”，输入相对于已配置 `/dav/` 的远端目录，选择 NAS 的已下载本地根目录，点击“开始只读 SHA256 校验”。两边根目录以下的文件和目录相对路径必须完全相同。

## 结果

- `VERIFIED_IDENTICAL`：两次远端目录枚举、两次本地清单相符，所有对应普通文件完整读取并计算 SHA256 一致，目录和空目录也匹配。
- `DIFFERENT`：缺失/多余文件或目录、类型/大小不一致或 SHA256 不同。不会自动修复。
- `INCOMPLETE`：远端无法访问、读取中断、限额、网络错误、目录中存在不可核验的本地 symlink/特殊对象或任务未成功终结。
- `STALE`：校验过程中远端清单或 NAS 身份发生可检测的变化，需要重新校验。
- `WorkJob.completed` 只是执行状态；业务结论独立。任务被取消/暂停/失败，绝不能算全部一致。

V1 对单个文件进行两次完整读取：一次远端 WebDAV GET、一次本地读取；不对原始数据写临时副本。大型文件使用分块 SHA256，单个校验任务最高 200,000 条目，超限以 INCOMPLETE 终止，不可静默截断。流式任务支持暂停/取消，但暂停后重新从该文件开始读取，不对未校验完成的字节做断点哈希延续。已有运行记录和逐项结果可以在 UI 中分页查询。

## 安全和保证范围

- 本功能校验的是经 WebDAV 读到的字节，无法证明远端 PikPak 服务器底层存储未作修改或 OpenList 未返回替代表示。WebDAV 没有全局原子快照，双遍枚举只能发现**可观测的变化**；远端可能在两次枚举之间发生 ABA 而无法可靠检测。
- 连接从已批准的固定端点发出，显式禁用重定向及代理，单项 URL 由安全相对路径组成；不支持用户输入任意 host、URL 或远端上传命令。部署端仍应使用出站网络 ACL 约束目标 OpenList IP，保护 DNS 解析及内部管理网络。
- 本地 `ALLOWED_ROOTS`、隔离区禁止访问、no-follow fd、安全文件类型检查仍生效；只读任务不依赖 `ALLOW_MUTATION`。
- 旧目录比较 API、Quarantine、Plan 和文件索引行为不变。
- 单次全部内容校验可能引发大量 PikPak 外网流量、NAS 读 IO 和远端 API 速率限制。请在少量样本验证通过后再扩大规模。
- GitHub CI 只证明源码和合成用例；真实 OpenList/PikPak 原始流行为及极空间 NAS 接受测试必须单独完成，不将源代码合并等同为部署成功。
