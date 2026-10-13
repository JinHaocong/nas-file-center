# NAS File Center · Pure White v2.1 视觉契约

> 状态：产品负责人已确认 Pure White 白灰黑方向。这是第二轮重构的**视觉与交互基准**，不是浏览器视觉验收记录，更不是部署批准。

## 产品视觉定位

基于确认过的三张设计稿：Dashboard、扫描管理、Workflow 编辑器。设计追求安静、易扫描、可信赖的专业文件工作台，不走深蓝企业后台、科技渐变或大面积毛玻璃路线。

1. **色彩**：浅色页面 `#FFFFFF`、侧栏 `#FBFBFA`、主文字 `#20201F`、浅灰边界 `#EAEAE7`、主操作 `#262625`。鼠标选中/聚焦状态应靠灰度、形态和对比度表达，不靠品牌蓝色。
2. **语义状态**：成功、警告、危险仍可分别使用克制的绿色、琥珀色、红色。颜色不可单独表达状态，必须保留图标/文字/辅助描述。诸如执行计划、失败、删除确认不得因为“极简”而降低辨识度。
3. **深色主题**：独立设计中性深灰表面（背景 `#171716`、卡片 `#242422`、边框 `#383834`、文字 `#F5F5F2`），不是直接反转白色。跟随系统模式必须继续服从现有 ThemeContext，不修改其持久化策略。
4. **字距与数字**：一级标题宜 28–34px，区块标题宜 14–16px，正文 12–14px；数值使用 tabular-nums，路径/日志/哈希优先等宽字体并允许在安全的断点处换行或滚动。
5. **边界和留白**：除悬浮层外，卡片基本只用 1px 细边框、10–12px 圆角和接近不可见的阴影；模块间距分级 8/12/16/24/32px，优先通过对齐、分组而不是叠加装饰卡片建立信息层级。
6. **按钮**：默认主操作黑底白字；暗色模式主操作浅灰底深灰字。次要操作白底细边框；危险操作显式红色状态。不能用蓝色背景作为通用主要操作色。
7. **导航**：桌面 248px 白灰侧栏，可折叠；选中项浅灰背景 + 2px 左标识条；当前路由仍须提供 `aria-current=page`。顶栏白底单根分隔线；品牌区不放醒目的版本字符串，发行版本以侧栏底部低对比小字显示，并与发布元数据同步。
8. **键盘细节**：所有可操作元素保留清晰的 `:focus-visible`，浮层本身仍保留 3px 对比明显的焦点边框；点击、悬停、禁用、加载、错误、空状态都要有明确反馈，悬停并不是焦点的唯一证据。
9. **数据真实性**：不能因为参考稿好看就在真实应用中加上不存在的“全局搜索”“NAS CPU 监控”“存储容量”等数据或虚假趋势。Dashboard 仍只能显示 API 确认提供的真实指标。按钮必须有真实、可访问的动作。
10. **安全边界**：Workflow Preview 仍使用已保存的 revision；Plan → Freeze → Validate → Worker、重预览、隔离与危险操作的权限及确认流程全部保留，禁止以视觉简化为理由跳过验证。

## 代码落地分期

| 分期 | 视觉范围 | 边界 |
| --- | --- | --- |
| 01 · Foundation + Shell | 全局中性色 Token、原生侧栏/顶栏、主次按钮、移动导航、Portal 明暗主题一致性，以及 Dashboard 初步去装饰 | 不改 API、路由、权限、业务组件数据结构 |
| 02 · Dashboard + Scans | 工作台真实指标和任务优先级、扫描列表/筛选/空状态、表格对齐和响应式 | 无假 KPI 或不存在的搜索、批量操作 |
| 03 · Plans + Workflows | 详情页、版本控件、线性步骤编辑器、表单及预览 | 不改版本和危险操作语义 |
| 04 · Long-tail + Consolidation | 设置、登录、工具、隔离区、其他页面；安全清理互相覆盖的历史样式 | 必须有计算样式与截图证据，不能一次性删光 CSS |
| 05 · Browser Acceptance | 一次性统一浏览器对照、实际交互回归、问题修复、所有者最终确认 | 验收通过前不得称作视觉交付完成 |

## 第二阶段：Dashboard 与扫描历史细节修正

- **Dashboard 数据真实性**：摘要尚在读取或 API 失败时，已索引文件、执行计划、活跃队列及最新扫描摘要使用“— / 读取中 / 暂不可用”，不能伪显示数值 0；已成功获取的真实 0 保留为 0。
- **Dashboard 信息密度**：快捷入口改成单列轻量操作列表，不再嵌套四个独立卡片；最近扫描/任务采用一致的 17px 列内边距、表头细分隔线、tabular-nums 和 focus-within 行反馈。
- **扫描历史**：继续通过服务端分页获取实际数据，进行中的扫描每 3 秒刷新；“进行中·自动刷新”仅当列表中存在实际排队/运行的扫描时出现，静态记录数改成中文并允许千分位。
- **高频列表**：重复组、重复文件和可释放空间的表头与数值统一右对齐；长任务名与长文件路径安全换行，宽桌面表格由局部滚动容器接管；保留原生删除二次确认和关联 Plan 安全门槛。
- **移动端**：767px 及以下维持卡片视图，移动操作区域明确分隔，不把桌面表格强行压缩；真实状态色保留、深色运行态与浅色保持可识别的对比度。
- **回归策略**：独立源码级细节测试不得假冒截图或真实浏览器验收；所有真实功能调用、轮询、分页、删除确认、以及第一阶段新增的 Archive Recovery 必须保留。

## 第三阶段前置：全局弹窗遮罩清晰度修正

- **问题证据**：用户截图中整张页面（包括弹窗）均明显失焦；此前公共 Radix 遮罩使用深蓝灰底色与 `backdrop-filter: blur(4px)`，视觉与 Pure White 不一致。单凭截图尚不能证明是浏览器中的层叠顺序错误。
- **本批修正**：共享 Portal 遮罩及原生 `::backdrop` fallback 改为不模糊的纯中性半透明遮罩；浅色下为克制的黑灰蒙层，深色下单独设置对比度。弹窗本身应保留不模糊的完整清晰度。
- **层级契约**：保留各已有层级对（普通弹窗 1100/1101、扫描 1190/1191、DirectoryPicker 1200/1201、嵌套任务确认 1300/1301、Workflow Revision 1400/1401），遮罩始终低于所属 Content；保留 ESC、外部点击限制、繁忙禁用与焦点管理。
- **验收边界**：新增源码级层级/背景回归，并继续运行全部 frontend、CSS audit、backend 与 Docker CI；`light/dark/system` 实际浏览器中验证嵌套 DirectoryPicker、任务确认和 Workflow Revision，以及用户截图对应弹窗后，才能标记视觉缺陷最终修复。

## 第三阶段第一批：Workflow / Plan 细节收敛

- **Workflow Builder**：加载/失败/说明状态与模式选择改为 Pure White 中性色 Token，不保留旧品牌蓝；危险/错误/警告仍使用语义色。表单焦点和禁用反馈、步骤菜单触控范围及 reduced-motion 原样保留。
- **Revision Portal**：嵌套只读版本详情使用与主应用相同的白灰黑 / 独立深灰主题；版本记录数字等宽对齐，表格同时支持悬停和键盘 focus-within；SHA256、历史只读与回滚二次确认不变。
- **Plan 详情**：统一浅/深色兜底 Token 为中性系统，PlanItem 表格用 tabular-nums、行 hover/focus-within 区分。保留可滚动长路径、警告/危险语义、移动端 44px 操作和 reduced-motion。
- **行为安全**：完全保留已保存 Workflow Revision、Preview/Generate Draft、服务器分页、Plan Draft → Freeze → Validate → Worker、操作日志、Undo 和危险动作确认。此批不引入新 API，也不改变任何文件操作。
- **证据边界**：源码级回归 + 当前 HEAD 全套 CI 不是最终浏览器验收，后续需覆盖 8 档宽度、light/dark/system、键盘与弹窗叠加。

## 第三阶段第二批：Workflow Steps / Organizer / Dedupe 复杂表单

- **Workflow StepCard 与输入**：去除分类标签中不必要的紫色/琥珀装饰，采用中性灰；长路径与步骤摘要可安全换行；Root 选择列表保留 checked、hover、focus-within 与键盘可达性。
- **Organizer 配置 Portal**：独立浮层的旧蓝色 Token 转为 Pure White 白灰黑，深色单独设计；保留 Organizer Portal 1140/1141 与 DirectoryPicker 1200/1201 的层级、目录白名单、表单校验与繁忙提交限制。
- **Dedupe 创建计划与诊断**：灰黑主按钮及暗色高对比文字，诊断 SHA/文件路径按需换行，移动端操作控件至少 44px；保留 1220/1221 层级、只读证据和 Plan → Freeze → Validate → Execute 安全流程。
- **Scorer 与存储安全面板**：统一中性色板，提升键盘焦点与触控尺寸；保留 supported / unsupported / unknown、warning/error/verified 的绿色/琥珀/红色语义，后端仍是能力与授权权威。
- **验收边界**：仅修改已有的样式所有者与源码测试，没有新增版本覆盖层、API 或后端更改；回归测试与 CI 不能代替 light/dark/system 和 8 档宽度的浏览器视觉验收，也不能代替 NAS 上的部署验证。

## 第三阶段第三批：Preview / Results / Plan 历史清理

- **Organizer Preview**：基于服务器的 Stage A/B snapshot、分页、过滤和 digest-bound 生成机制保持不变。只整理 Preview 根路径控件、状态提示、proposal 表格、长路径与移动卡片的灰度层次、tabular-nums 和 hover/focus-within。Stage 冲突仍用原有警告/成功/危险语义色。
- **Advanced Dedupe**：结果筛选、决策/资格标签、行高、路径断行和焦点转为灰白中性色；真实后端结果、Preview Digest、Hardlink/Reflink 风险说明及仅生成 Draft 的行为不变。确认浮层保持 1280/1281 层级，浅色深灰主按钮和深色高对比主按钮分别定义文字色。
- **Dedupe Explain**：只读 Summary 与独立 Radix Sheet 统一中性色，层级 1225/1226；保留后端 canonical 解释、权重贡献、文件 provenance、分组与所有实际安全状态颜色。表格和长路径允许滚动/换行、聚焦可见。
- **Plan 历史清理**：终态白名单（completed / failed）和 Delete ≠ Undo 告知保持原状；只增强选中、键盘焦点、禁用和视口滚动的可见反馈。忙碌防重复提交与防关闭、删除确认及文件系统不受影响。
- **证据与限制**：新增 6 项源码级回归。完全不修改 API、Worker、数据库、文件操作、生产 NAS 或发布版本；CI 通过后也仍需 light/dark/system 与 360/390/430/768/1024/1280/1440/1920px 的真实浏览器验收。

## 第四阶段第一批：登录、设置与文件工具预览

- **Login**：移除登录页径向光晕、伪元素玻璃装饰与大幅暗蓝投影；保持纯白画布、灰度边框、克制阴影与独立深色对比度。原生 username/password 认证、三态主题、单次提交和错误提示均不变。
- **Completed Scan Picker**：原生输入控件和路径标签的旧蓝色兜底 Token 改为中性色，选中值始终依靠真实已完成任务和详细信息验证；长根路径换行，移动端弹出警告的关闭控件尺寸更可用。
- **Settings**：保持运行配置只读与管理员权限、审计预览/保存/清空双确认和会话撤销授权。仅改善终端会话表格的数字对齐、focus-within、滚动边界、移动设备卡片焦点与 44px 开关/操作尺寸；危险/警告/成功语义颜色保持。
- **Utility Workflow Preview**：把 Paper/Surface/Text/Focus 的蓝色兜底 Token 改为灰白黑及独立深灰模式；只读候选表增加 tabular-nums 与 focus-within，长路径、手机候选卡片与触控操作更清晰。保留 compile_digest、revision、READY 可选状态、Immutable Draft Request 与 Freeze → Validate → Execute 的后续安全链。
- **证据边界**：本批只修改原有 Login、Completed Scan、Settings、Utility Preview 样式所有者与测试文档，未新增 CSS 覆盖层或业务逻辑。CI 与源码测试不能替代 360–1920px 的浏览器主题/键盘/弹窗验收，也不是生产 NAS 部署。

## 第四阶段第二批：Quarantine 隔离区视觉与安全语义

- **隔离区 Ledger**：由旧 `--v2-indigo` 蓝灰兜底转为 `--nfc-` Pure White 灰度 Token，并分别设计暗色表面。桌面表格保留后端真实状态、服务器分页、终态清理白名单和 active-only 选择；数字等宽、长路径换行、鼠标悬停与键盘 focus-within 同等可辨。移动卡片、按钮和复选框更易触控，列表横向滚动不串联父页面。
- **单文件 Restore / Purge**：Portal 统一白灰黑与独立深灰，选中、禁用及键盘焦点易辨，移动端关闭按钮至少 44px，长文件路径显示完整。恢复严格只有 skip / rename / manual，不允许覆盖；永久清除必须管理员、双安全开关、输入大写 DELETE。红色危险、琥珀警告、绿色成功不能被中性色覆盖，hard link survivor 与独立内容副本必须保持 advisory 语义。
- **Bulk Restore / Purge**：仅 Preview 与生成 Draft，保持 Preview Digest 绑定、选中身份验证、只要存在 blocked 即 fail-closed，永久清除生成前仍要求 DELETE；表格/指标数字对齐、被阻止/允许状态明晰。弹窗层级沿用 Radix `nfc-v2-confirm-overlay` / `nfc-v2-dialog`，不新建 z-index 覆盖层；背景遮罩继续采用 PR #198 的无模糊中性设计，弹窗正文保持清晰。
- **交互保证**：原有请求防重入、繁忙时禁止关闭、Esc / 外部点击限制、不可逆操作明确确认与审计记录不变；不改动 API、RBAC、Worker、实际 NAS 文件或 Archive Recovery。
- **回归与边界**：新增 6 条纯源码专项回归，保留已有隔离区安全测试及 CSS 所有权审计。合并后的代码仍未完成真实浏览器的 `light/dark/system`、360/390/430/768/1024/1280/1440/1920px、长路径、键盘导航与叠层验收。上线部署前必须在实际浏览器复现并验证用户反馈的遮罩问题。

## 第四阶段第三批：历史 CSS 安全收敛

- **范围受控**：只整理旧 `v049-workspace.css` 五组相同选择器中已由后续声明覆盖的 13 项纯文本排版值；保留该文件其它所有本地规则、8 个媒体查询和导入顺序，不改变 `main.tsx` 或业务代码。
- **视觉契约**：后续真正生效的字号、字重、行距与间距数值不变；新增测试同时核对早期无效声明已移除、后期优先值仍在、独立声明未丢失。主色和弹窗遮罩仍由已完成的 Pure White owner CSS 决定。
- **不支持的结论**：通过源码级回归或 GitHub CI 不能证明运行时所有宽度、主题、悬停态的 computed style 不变。其它历史重复规则暂不处理，留待真实浏览器视觉验收后的第二批合并。
- **安全限制**：本批绝不更改 NAS 实际文件、后端、Worker、权限确认、Preview/Plan/Freeze/Validate/Execute 或部署。保留 Quarantine、Organizer 和 Plan 危险操作安全链。

## 第五阶段第一批：真实浏览器嵌套弹窗验收

- **发现**：`ScanCreate` 与嵌套 `DirectoryPicker` 属于独立 Radix Portal，仍持有旧蓝灰主题兜底和蓝色 primary。源头分别在原有的 `console-v2-scan-create.css` 与 `console-v2-directory-modal.css`。本批就地转换为 Pure White 独立 light/dark Token，不新增 CSS 覆盖层。
- **真实 Chromium 自动化**：`frontend/scripts/browser-overlay-smoke.mjs` 在 GitHub Actions 的 `UI Validation / browser-overlay-smoke` Job 中构建并启动真实 Vite/React 路由 `/scans`，真实点击 `新建扫描 → 选择目录`，以浏览器 `getComputedStyle` 核对无遮罩模糊、1190/1191 与 1200/1201 层级、深色按钮反差、窗口边界、点击命中、内层 Escape 关闭后外层保留，并为每种组合存放截图证据。
- **矩阵**：360/390/430/768/1024/1280/1440/1920px × light / dark / system-light / system-dark，32 个真实 Chromium case；使用 `prefers-reduced-motion: reduce`。只用**拦截的只读模拟 API**，任何 POST/PUT/DELETE 都会返回 405 并使断言失败，绝不访问真实 NAS。
- **可证实与不可证实**：这组检查能发现上述两层**真实 DOM + 真实 CSS 的浏览器计算样式与堆叠问题**，但不包含全部业务页面、生产服务器配置、具体用户截图的原环境，也不能由此宣称 NAS 端已修复或者 8 宽度 × 3 主题的完整人工视觉验收结束。截图由 Actions 上传，用户仍需在实际部署后比对。
- **安全不变量**：扫描真实请求/API 语义、目录白名单、安全模式、Plan → Freeze → Validate → Worker、忙碌禁止关闭、失败提示、只读证据、Archive Recovery 不变；仅修改既有 Scan/Directory Portal 样式、增加隔离浏览器验证和专项测试。

## 第五阶段第二批：任务抽屉与危险确认的真实浏览器验收

- **可重现范围**：在 Stage 5A 已通过的 `ScanCreate → DirectoryPicker` 真实 Chromium 回归之外，打开实际 `/tasks` 页面上的 `ConsoleSheet 任务详情 → 删除任务确认` 两层 Radix Portal；验证双层背景只变暗、不模糊、1100/1101 与 1300/1301 层级、焦点下真实命中、主题色和弹窗不越界。使用 Esc 关闭内部确认后抽屉仍应存在；关闭抽屉后返回任务列表。
- **独立危险流程**：打开真实 `清理任务历史` Radix Dialog，对已完成、已失败、已取消三种终态做选择状态交互；全部取消选中时，`确认清理` 必须 disabled，重新选一个终态后才可以点击，但自动化**绝不点击真正的清理确认**。
- **CI 证据**：`UI Validation / browser-overlay-smoke` Job 在既有 32 项嵌套扫描检查后，运行 `frontend/scripts/browser-task-overlays.mjs` 对八档视口 × light/dark/system-light/system-dark 共 32 组场景测试两种流程；共新增 64 张截图保存到 `frontend/artifacts/browser-task-overlay`，与 Scan 截图同时上传为同一个 SHA 绑定工件。
- **隔离与保护**：此阶段仅使用构建后的 Vite/React 和浏览器只读模拟 GET API；任何非 GET 都明确以 405 拦截，并在每个场景验证没有发出变更请求。保留真实任务、历史清理、安全白名单、Audit、NAS 文件保护与 Worker 行为，不增加 mock 生产运行时代码。
- **限制**：自动化验证真实 Chromium 计算样式、可交互栈与安全禁用状态，不等同于用户实际 NAS 域名部署后的截图复验、所有浏览器引擎或产品全站人工验收。未经实测，不可宣称所有弹窗已全部通过。

## 第五阶段第三批：Quarantine / Plan 确认弹窗真实浏览器验收

- **发现真实层级风险**：普通 `nfc-v2-confirm-overlay` 遮罩是 `z-index:1300`，但单项隔离区 Restore/Purge、批量 Restore/Purge 和计划历史清理对话框此前都复用了通用 `nfc-v2-dialog` 1101 正文层。修复是在三份既有特性 CSS 中为各弹窗开放态指定明确 1301，避免遮罩盖住内容、捕获点击；未新建全局覆盖层。
- **Chromium 检查**：在已有 32 项扫描与 32 项任务测试后，再启动真实 `/quarantine` 与 `/plans`，通过只读模拟 GET 数据分别打开单文件恢复、永久清除与计划历史清理，核对 z1300/1301、无遮罩模糊、正文点击命中、视口边界，覆盖八个宽度与 light/dark/system-light/system-dark（32 种组合，新建 96 张截图）。
- **安全闭环**：恢复只能 skip、rename、manual；永久清除严格要求大写 `DELETE`（小写不能激活，正确输入只验证按钮激活，**绝不点击最终确认**）；计划历史仅 completed、failed 两种终态，全部取消选中时确认按钮禁用。所有浏览器 API 为只读合成数据；POST/PUT/DELETE 请求返回 405 且测试失败。无真实 NAS 网络连接或文件操作。
- **未覆盖**：生产部署源站、真实 NAS 数据、Safari/Firefox、所有 Workflow/Plan 生命周期/Quarantine Bulk Preview 的服务端合约；上线前需要人工核查原始弹窗截图问题。新增源码回归只证明 CSS 层叠规则存在，真正计算层叠是否有效必须看 Chromium 结果。

## 像素级最终验收矩阵

- **视口**：360、390、430、768、1024、1280、1440、1920px；横向溢出必须由明确的表格滚动容器接管，不允许主页面出现意外滚动条。
- **主题**：light、dark、system，系统切换前后侧栏、状态色、浮层、表单、遮罩均保持清晰对比。
- **导航**：展开/折叠、移动抽屉、页面选中、菜单关闭、键盘 Tab 顺序、焦点返回。
- **复杂交互**：表格长文件名/长路径、筛选、分页、Workflow Step、错误与重试、弹窗堆叠与 Escape、危险操作取消确认。
- **状态**：loading、empty、success、warning、danger、disabled、busy、permission denied、历史只读；不能截取单一成功态冒充整体验收。
- **动效**：`prefers-reduced-motion: reduce` 保持无位移/短时切换；系统低透明偏好保持实体层级。
- **检查证据**：按每个独立 PR 的**最新精确 HEAD**记录前端类型检查、回归、CSS 所有权、后端、Docker、依赖与 GitHub Workflow；视觉验收必须另外提供真实浏览器截图和问题列表。
- **部署**：没有额外明确授权，不接触真实 NAS 文件系统，也不进行生产部署。

## Archive Recovery 新增功能视觉纳入

- 基于远程最新 `main` 中新增的 `/archive-recovery` 入口；在第一批 Pure White PR 同步纳入，不把损坏压缩包恢复页面留在旧蓝色系统中。
- 页面使用现有 `PageHeader`、`DataPanel`、`DirectoryPicker`、`ConsoleButton`、`ActionBar` 原生组件。桌面双栏呈现文件选择与检测执行，在 1023px 以下改单栏，窄屏 767px 以下压缩页面留白。
- 文件名与恢复报告路径允许换行；选中态使用中性灰黑，增强恢复限制使用安静的灰色说明框，危险、警告与错误继续保持语义颜色；空文件列表给出明确可操作反馈。
- 恢复 API 检测条件、写入许可/依赖守卫、密码清理、异步 Worker、取消任务、状态过滤、JSON 报告、AES/LZMA2 深度重同步能力与限制均保持原样，不能加入模拟状态或绕过真实验证。
- 专属 `console-v2-archive-recovery.css` 是**业务页面自身拥有的样式模块**，非新增一层全局版本覆盖；通过 `main.tsx` 明确导入，并纳入自动发现的 CSS 所有权审计。
- 添加 8 项回归覆盖保留的业务安全约束和响应式/主题规则；真实浏览器下的键盘、目录弹窗、恢复状态/长路径溢出仍需随后亲自验收。

## 第一批保留的兼容事项

- `--v2-indigo` 与 `--v2-indigo-soft` 是大量既有组件使用的历史变量名。本批保留这些标识符以防功能样式失效，但值已切换到**中性灰黑**；后续再通过有测试的渐进迁移统一命名。
- Dashboard 的 CSS 初步隐藏旧装饰性 NAS 设备图形；先保持现有真实数据 API、DOM 和事件模型不变，后续在 Dashboard 独立 PR 中处理结构和死代码。
- Portal 可能挂在 `.nfc-v2-shell` 之外；须由 `tokens.css` 的文档根 Token 和相应 Radix 样式共同覆盖浅色/深色模式。
- 上述修改只建立视觉基底，现有页面级硬编码色、历史覆盖链、以及实际浏览器里的细节问题仍需要逐页修正和统一验收。
