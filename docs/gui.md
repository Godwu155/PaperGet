# PaperGet 图形界面开发说明

## 工作台布局

- 顶部：DOI / 标题输入和设置。
- 中部左侧：标题候选表（标题、作者、年份、DOI、匹配分数）。分数范围 0–1，只用于排序，不是正确概率。
- 中部右侧：选中文献详情与 PDF 来源，包括来源、版本、许可和链接。检查来源不会下载 PDF。
- 底部：串行下载队列、可筛选的 SQLite 历史、JSON/CSV 导出。

浅色方案使用背景 `#F7F8FA`、正文 `#20252B`、主按钮 `#087E8B`；深色方案跟随系统调色板。默认窗口 1100×720，最小 850×560。主要操作支持键盘：Enter 搜索、方向键选候选、Ctrl+O 导入、Ctrl+, 设置。

## 数据流和线程

GUI 直接调用 `PaperGetService.search_title()`、`fetch(inspect=True)`、`fetch()`；批量 I/O 使用 `paperget.batch_io`。工作线程在执行任务时创建并关闭 service 与 SQLite 连接，不跨线程传递数据库连接。GUI 与 CLI 共享业务逻辑。

下载队列一次处理一项。TXT/CSV 导入先预览并去重；可暂停后续项、重试失败项，活动任务完成后才暂停。暂停队列只保存在当前 GUI 进程中，关闭窗口不会保留尚未运行的任务。状态包括等待、下载中、已下载、已有文件、未找到 PDF、需选择论文、失败和已移除。`forbidden`、`rate_limited`、`challenge_required`、`invalid_pdf` 等错误映射为中文说明。标题歧义要求用户选定 DOI，不自动挑选第一篇。

来源诊断保存在 `source_events` 表，按一次查询的运行 ID 记录每个来源的发现、下载或人工导入结果。GUI 可按 DOI 查看并导出全部诊断为 JSON/CSV；记录主机名和简要原因，不保留带查询令牌的 PDF URL。OpenAlex DOI 缺失、元数据没有 PDF、Sci-Hub 页面无链接、疑似人机验证及实际下载失败分别呈现。旧 SQLite 数据库打开时自动创建新表，已有结果和文件不移动。

人工处理入口使用系统浏览器打开配置的来源页。用户手动取得 PDF 后可选择文件导入；导入过程在工作线程验证 `%PDF-` 文件头、大小上限并原子复制到输出目录，关联 DOI、来源 `manual` 和 SHA-256，更新历史。导入不依赖网络，也不尝试自动处理验证码。

服务层尚无字节级进度和合作式取消回调，因此界面只显示当前阶段；正在处理的任务不可强制中止。更细的进度和取消应先在服务层设计回调，再接入界面。

## 设置与来源

非敏感偏好通过 `QSettings` 保存：输出目录、大小上限、来源顺序、Crossref 联系邮箱和 Sci-Hub 开关/入口。OpenAlex 默认优先；Sci-Hub 需要显式启用并填写 HTTPS 地址。GUI 的 OpenAlex Key 使用 Windows 凭据管理器保存，不写入 `QSettings`；如果系统凭据不可用，仅保存在当前进程内存中，并向用户说明。环境变量仍可作为回退来源。已有站点限制按服务层状态呈现；界面不处理验证码或访问限制。

下载文件名由论文标题及 DOI 的 12 位哈希组成，清理 Windows 禁用字符和控制字符，并限制标题长度；Crossref 标题缺失时尝试 OpenAlex 标题，仍缺失则退回旧版 DOI 文件名。数据库记录路径和同一输出目录中的旧版 DOI 文件名继续用于检测已下载文件，避免重复下载。旧文件不自动更名。

## 本地验证

```powershell
.venv\Scripts\python -m pip install -e '.[gui]'
$env:QT_QPA_PLATFORM = 'offscreen'
.venv\Scripts\python -m unittest discover -s tests -q
Remove-Item Env:QT_QPA_PLATFORM
.venv\Scripts\paperget-gui
```

自动测试中的 GUI 用模拟服务运行，不依赖外站。人工验收还需检查真实开放 DOI、中文字体、系统缩放、深色模式、失败来源和打包后的 Windows 程序。

## Windows 独立程序构建

在 Windows PowerShell 中执行：

```powershell
.venv\Scripts\python -m pip install -e '.[gui]'
.venv\Scripts\python -m pip install Nuitka==4.1.1
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build-windows.ps1
```

构建结果位于 `dist/windows_main.dist/PaperGet.exe`，需连同整个 `.dist` 目录分发。Nuitka 首次构建可能下载 Windows 依赖分析工具或编译器；再次构建使用缓存。构建后的程序应在干净 Windows 环境验收启动、中文显示、设置读写和开放 DOI 下载。

## 2026-10-10 开发预览验证

- 35 项自动化测试通过，涵盖 CLI 回归、批量 I/O、GUI 候选/来源/下载流程、失败后队列继续及设置读写。
- 真实开放 DOI `10.1371/journal.pone.0000001` 通过 GUI 后端检查到 1 个 OpenAlex PDF 来源，并成功下载有效 PDF。
- Windows 原生 Qt 平台检查了 1100×720、850×560 的中文布局和模拟深色调色板；主要控件可见。
- 全新 CLI-only 虚拟环境安装后可运行 `paperget --help`，其中没有 PySide6。
- Windows 独立程序已启动验证，运行时工作目录不同于仓库且未设置 `PYTHONPATH`。ZIP 分发包 SHA-256：`EE8EEC0DA004C508D7AE216126E0F366E522C8B3DCB57D02866F87E19C8C9734`。

此版的跨机器完整下载验收结果见下方记录；不同网络错误场景仍待补充，作为 v0.3 正式发布门槛。

## 2026-10-11 开发预览验证

- 51 项自动化测试通过，新增来源诊断、疑似人机验证、人工 PDF 导入、批量预览与队列控制的测试。
- 对 `10.1109/ICCV51070.2023.00371` 的真实检查返回 `not_found`，并分别记录 OpenAlex 缺少直接 PDF 与 Sci-Hub 页面没有可识别 PDF 链接；此样本没有检测到人机验证。
- `PaperGet.exe` 从与程序目录不同的工作目录启动成功，`PaperGet-windows-v0.3.0.dev1.zip` 包含可执行文件和 74 个运行文件，SHA-256：`1CD1A29626F8FC2E18EF16AB9881EC5B9A55DF0D118DFB6E0B5A330DBFCDE5B3`。
- 本机验收时尚缺跨机器验证；随后收到的结果见下方记录。

## 2026-10-12 跨机器验收反馈

用户确认在另一台电脑使用 `PaperGet-windows-v0.3.0.dev1.zip`，完整下载、中文显示、设置保存和批量下载均正常。Windows 具体版本未记录；此反馈未覆盖缩放比例、断网、403/429、错误 PDF 和不可写目录等边界情况。正式发布前的剩余核对见 [发布准备记录](release-readiness.md)。
