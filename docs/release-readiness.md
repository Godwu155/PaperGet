# PaperGet v0.3 发布准备记录

更新日期：2026-10-13。跨机器已验收的交付物为开发预览版 `0.3.0.dev2`；设置改动已组成 `0.3.0.dev3` 候选包，正式版尚未发布。

## 2026-10-13 dev3 候选

- 新安装的 GUI 默认启用 Sci-Hub，预填 `https://sci-hub.al/` 并优先尝试该来源；提供 `.mk`、`.vg`、`.ee`、`.st` 的 HTTPS 镜像候选供手动选择。已有设置保持原值，CLI 默认来源行为不变。`.ee` 与 `.st` 未做下载验证。
- Python 3.12.15 环境中运行 58 项测试通过，`git diff --check` 通过。Nuitka 4.1.1 的 `--windows-console-mode=disable` 构建在启动时抛出 `codeobject.c:356: bad argument to internal function` 并退出；全新目录和去除图标后可重现。改为 `attach` 模式后，直接运行和从 ZIP 解压运行都持续 7 秒。该模式从资源管理器启动不新建控制台；从已有终端启动时可附着输出。
- 候选包为 `dist/PaperGet-windows-v0.3.0.dev3.zip`，33,326,882 字节、82 个条目，SHA-256 `7B008FCF74AAD96452E4B09D0663270F0AB2079B094D68925763F188E52BCF50`。包含 `PaperGet.exe`、MIT `LICENSE` 与 `THIRD_PARTY_NOTICES.md`；从独立目录、以 `C:\Windows\Temp` 为工作目录启动成功。此包尚未经过跨机器完整下载验收。

## 2026-10-13 进展

- Python 3.12.15 + Nuitka 4.1.1 + Zig 构建的 `0.3.0.dev2` Windows 程序在本机正常图形模式下持续运行；Python 3.13 的同源构建仍会崩溃。构建脚本现检查解释器版本并显式启用 Zig。
- GUI 运行依赖改为 PySide6 Essentials。全新 Python 3.12 环境安装最小依赖后，57 项测试通过；独立包去除未使用的 `qpdf.dll` 后仍可启动，包内不含 Qt PDF 核心库和 Qt Virtual Keyboard。
- 已从候选构建生成 `dist/PaperGet-windows-v0.3.0.dev2.zip`（33,324,737 字节，82 个条目），SHA-256 `FA405D3C73B235980944E6688AA4E26123129A40D5796C5BE222F0566216683D`。ZIP 含 `PaperGet.exe`、MIT `LICENSE`、`THIRD_PARTY_NOTICES.md`、GNU LGPLv3/GPLv3 文本；从 ZIP 解压到独立目录后，以 `C:\Windows\Temp` 为工作目录启动并持续运行 7 秒。本机 Windows 版本 `10.0.26200.0`。
- 使用相同 Python 3.12 环境运行 CLI：`paperget get 10.1371/journal.pone.0000001 --output .tmp\dev2-open-download --json`，返回 `downloaded`，来源 OpenAlex、版本 `publishedVersion`；生成按论文标题命名的 816,502 字节文件，文件头为 `%PDF-`，SHA-256 `22f2423f45940809cc040415b5045a707b907fddec6a0c43bea16ac6455c72b0`。该项验证源码运行路径，独立 GUI 包的完整下载仍待跨机器验收。
- 上述构建与测试证据仅覆盖本机；另一台电脑的反馈见下一条。正式公开发布前仍须复核 Qt LGPL 分发义务与第三方告知文本。[Qt 官方说明](https://www.qt.io/development/open-source-lgpl-obligations)要求提供 LGPL 文本、显著告知及库源码获取方式等；当前候选包已包含文本和官方源码入口，但不能视为完整合规结论。
- 2026-10-13 用户反馈另一台电脑使用 dev2 候选包“没有问题”，对应上次请求的完整下载、批量导入、设置保存和中文显示四项验收；具体 Windows 版本未记录。正式公开发布前仍需异常场景人工记录及 Qt 分发审阅。

## 2026-10-12 暂停点

- 当前工作分支已加入 MIT `LICENSE`、图标和第三方告知生成脚本、批量导入无效行预览、磁盘错误处理及相应测试。本机 `unittest discover -s tests -q` 运行 57 项通过，`git diff --check` 通过。
- 当时的 Python 3.13 `0.3.0.dev2` 独立程序启动崩溃，旧 ZIP 是失败的诊断产物。2026-10-13 已用 Python 3.12 构建并覆盖该 ZIP；`0.3.0.dev1` 仍是最后一个经过跨机器验收的包。
- 诊断：Python 3.13 + Nuitka 4.1.1 的编译产物在导入 `paperget.gui_window` 时可能报 `SystemError: ... codeobject.c:455: bad argument to internal function`。使用旧版界面模块编译可正常启动；本轮新增的批量预览调用表达式触发了崩溃。刚将该表达式拆入 `MainWindow._batch_preview`，**尚未重新构建验证**。
- 以上是历史暂停记录；后续改用 Python 3.12 构建。无界面模式 `QT_QPA_PLATFORM=offscreen` 会让旧包也异常退出，不能用于启动验收。

## v0.3.0.dev1 已验证

| 项目 | 证据 |
| --- | --- |
| 代码基线 | Git 提交 `585ee3d`，分支 `codex/paperget-gui-v03`。 |
| 自动化 | Windows 本机运行 `python -m unittest discover -s tests -q`，51 项通过。 |
| 分发包 | `dist/PaperGet-windows-v0.3.0.dev1.zip`，SHA-256 `1CD1A29626F8FC2E18EF16AB9881EC5B9A55DF0D118DFB6E0B5A330DBFCDE5B3`。ZIP 内含 `PaperGet.exe`；本机从不同工作目录启动成功。 |
| 跨机器 | 用户反馈：另一台电脑解压 `v0.3.0.dev1` 后，完整下载、中文显示、设置保存、批量下载均正常。Windows 版本未记录。 |
| 仓库文件 | 跟踪文件仅有源码、测试、文档和构建脚本；`.gitignore` 排除 `.venv/`、`dist/`、下载目录、SQLite、`.env` 等本地文件。 |

## 发布前待核对

1. 补充异常路径记录：断网、403/429、无效 PDF、不可写目录，以及不同缩放比例和深色模式；确认失败后界面可继续，目标目录不留伪 PDF。自动化已覆盖前四类，缩放和深色模式仍需人工核对。
2. 核对 G2 的批量、历史和设置验收条款。已实现的功能需有对应测试或人工记录；尚缺的功能单独跟踪。
3. 用户已选择 MIT，仓库和候选包将包含项目 `LICENSE`。新构建脚本已嵌入 PaperGet 原创图标，并从构建环境生成第三方组件清单、复制已有许可文本。新包改用 PySide6 Essentials，移除未使用的 `qpdf.dll`；仍需复核 Qt LGPL 分发义务和第三方告知。
4. 从文档命令重新构建最终候选包，记录提交 SHA、测试结果、ZIP 哈希和 Windows 版本；核对 README 与实际界面。
5. 发布候选确认后再确定正式版本号、Git 标签和 GitHub 发布物，并在 Linear 关闭对应工单。

## 已知限制

- 图形界面新安装默认启用 Sci-Hub 并预填 `.al` 入口；命令行仍需显式配置。站点无 PDF 链接、403 或人机验证可能导致自动获取失败；验证码由用户在浏览器中处理，之后可导入本地 PDF。镜像下拉框不自动轮换，`.ee` 和 `.st` 尚未验证。
- 批量队列的暂停和未执行项仅保存在本次 GUI 会话。下载显示阶段状态，不显示字节进度，也不能强制中止活动网络任务。
- 新版会记录逐来源诊断；旧历史记录不会自动补全诊断事件，重新运行后才有详情。
