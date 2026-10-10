# PaperGet 图形界面开发说明

## 工作台布局

- 顶部：DOI / 标题输入和设置。
- 中部左侧：标题候选表（标题、作者、年份、DOI、匹配分数）。分数范围 0–1，只用于排序，不是正确概率。
- 中部右侧：选中文献详情与 PDF 来源，包括来源、版本、许可和链接。检查来源不会下载 PDF。
- 底部：串行下载队列、可筛选的 SQLite 历史、JSON/CSV 导出。

浅色方案使用背景 `#F7F8FA`、正文 `#20252B`、主按钮 `#087E8B`；深色方案跟随系统调色板。默认窗口 1100×720，最小 850×560。主要操作支持键盘：Enter 搜索、方向键选候选、Ctrl+O 导入、Ctrl+, 设置。

## 数据流和线程

GUI 直接调用 `PaperGetService.search_title()`、`fetch(inspect=True)`、`fetch()`；批量 I/O 使用 `paperget.batch_io`。工作线程在执行任务时创建并关闭 service 与 SQLite 连接，不跨线程传递数据库连接。GUI 与 CLI 共享业务逻辑。

下载队列一次处理一项。状态包括等待、下载中、已下载、已有文件、未找到 PDF、需选择论文、失败和已移除。`forbidden`、`rate_limited`、`invalid_pdf` 等错误映射为中文说明，原始消息保留在记录中。标题歧义要求用户选定 DOI，不自动挑选第一篇。

服务层尚无字节级进度和合作式取消回调，因此界面只显示当前阶段；正在处理的任务不可强制中止。更细的进度和取消应先在服务层设计回调，再接入界面。

## 设置与来源

非敏感偏好通过 `QSettings` 保存：输出目录、大小上限、来源顺序和 Sci-Hub 开关/入口。OpenAlex 默认优先；Sci-Hub 需要显式启用并填写 HTTPS 地址。API key 仍只从环境变量读取，界面不写入设置文件。已有站点限制按服务层状态呈现；界面不处理验证码或访问限制。

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

此版仍需在另一台干净 Windows 机器上验收打包程序的完整下载、系统缩放和不同网络错误场景，作为 v0.3 正式发布门槛。
