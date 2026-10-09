# V3 — 文件名质量巡检

## 业务边界

V3 在现有「文件工具」中增加「文件名巡检」工作台。对用户选择的目录下一级普通文件执行只读名称分析；不递归，不跟随符号链接，不读取文件内容。

检测问题：
- 文件名首尾空白字符（edge_whitespace）。
- Windows 末尾句点或空格（windows_trailing_dot_space）。
- Windows 不兼容字符、保留设备名（windows_invalid_character / windows_reserved_device）。
- 控制字符、零宽格式字符与方向性格式字符（invisible_or_control）。
- 未使用 NFC 规范化的 Unicode 文件名（unicode_non_nfc）。
- UTF-8 文件名字节数超过 240 的早期警告（long_name）；240 不是所有文件系统的最大值，也不等于非法。
- 完全重复扩展名（repeated_extension），例如 photo.jpg.jpg。
- 文档/媒体后缀后再跟脚本/可执行后缀时的审阅提醒（suspicious_double_extension），例如 invoice.pdf.exe；不自动宣称恶意文件。

**只有首尾 ASCII 普通空格**可产生 rename 建议，并且清理后如果仍有其他巡检问题，就只报告不建议修改；其他类别没有自动修复。

## 安全原则

- 目录必须在 ALLOWED_ROOTS，排除 quarantine_root。
- 遍历目录使用 O_NOFOLLOW 的逐级目录描述符；跳过符号链接、目录和特殊设备文件。
- 直接目录条目最多 10,000 个（包括忽略条目），超过即整次拒绝。
- 源文件再次核验设备、inode、文件大小、mtime；若文件在扫描中变化，不生成建议。
- 现有目标、大小写折叠重名、目标建议内部相互碰撞、不合法文件名均不产生建议。
- API 仍须用户登录；工作台可按问题筛选、导出 CSV，并中和 CSV 注入公式。
- 创建 Draft Plan 前由服务器再次重算预览，若选中项变更即拒绝旧建议。正式执行仍走已有通用 Rename Plan 的 Freeze → Validate → Execute/Worker、安全配置及审计链。
- Preview 不自动提交 Plan、不修改文件。创建 Draft Plan 本身也不执行文件变更。

## 验收范围

新增测试覆盖：正常/问题名称识别、UTF-8/Unicode、Windows 名称兼容、扩展名、无递归与 symlink、防跨根访问、隔离区、限流规模、已有目标冲突、保守建议、API 登录和只读 Draft 创建。

## 明确不包含

V3 不会按内容推断文件类型、不执行查毒、不自动修复重复扩展名、不批量修改目录、不做递归巡检、不对外承诺跨平台命名全部正确。CI 通过不代表 NAS 生产已部署。