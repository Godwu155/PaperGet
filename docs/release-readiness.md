# PaperGet v0.3 发布准备记录

更新日期：2026-10-13。用户确认 `0.3.0.dev4` 的程序均已验收、可以正常下载，并要求发布正式版。以下保留各候选版本的历史排障记录；正式版交付证据见文首发布记录。

## v0.3.0 正式版交付

- 源码版本：`0.3.0`，标签 `v0.3.0`。Windows 独立包可解压运行，不需要安装 Python。
- 自动化：Windows 本机运行 `python -m unittest discover -s tests -q`，60 项通过。`0.3.0.dev4` 的跨机器完整下载经用户验收，用户于 2026-10-13 确认所有程序可正常下载。正式版沿用 dev4 的网络处理代码，更新版本号、文档与许可告知后重新构建。
- 发布物、提交与 SHA-256 以 [v0.3.0 发布说明](release-v0.3.0.md) 为准。

## 2026-10-13 dev4 限流修复候选

- 用户报告 DOI `10.1016/j.cell.2015.05.002` 长时间显示“下载中”。本机来源记录显示 `www.cell.com` 返回 403；对后续 MIT 候选地址的只读请求返回 429 与 `Retry-After: 900`。旧 HTTP 客户端对该地址最多等待 300 秒并重复请求三次，造成约 15 分钟无界面进度的等待。
- 现在 429 立即报告并跳过该地址，继续尝试其他候选；5xx 响应若要求等待超过 10 秒也不在当前任务中等待。单个 PDF 下载约 180 秒后报超时并清理临时文件，下载连接最多重试一次。源代码 60 项测试通过，覆盖 429 不等待、长 `Retry-After` 不等待、下载超时清理及另一主机回退。
- Python 3.12.15 + Nuitka 4.1.1 的 `disable` 控制台构建再次出现 `codeobject.c:356` 启动错误；构建脚本改为 `attach` 模式。候选 ZIP `dist/PaperGet-windows-v0.3.0.dev4.zip` 为 33,326,242 字节、82 个条目，SHA-256 `D3D3449D578FB3896157293DD13B81DB36997DC0856AB10E181ADF80946F9FEF`。从独立目录解压，以 `C:\Windows\Temp` 为工作目录启动并持续运行 7 秒。
- 后续用户确认此候选的程序均验收通过、可以正常下载。若同一任务先遇到 403 后遇到 429，主队列可能显示首个错误 403；逐来源诊断仍会记录两者。

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

## 发布前核对的处理结果

1. 异常路径中的 403/429、无效 PDF、下载超时、不可写目录已由模拟测试覆盖；真实站点和系统缩放的组合无法稳定复现，未声称逐项人工验收。用户确认整体下载流程通过。
2. 批量、历史、设置和跨机器解压使用已有自动化、本机验证与用户验收反馈。队列暂停只在当前会话有效，见已知限制。
3. 项目采用 MIT。Windows 包包含 MIT 许可证、第三方组件清单与 Qt LGPLv3/GPLv3 文本，Qt/PySide6 上游源码获取方式写入包内清单。正式公开分发时应继续维护这些告知与源码入口。
4. Windows 构建固定 Python 3.12、PySide6 Essentials 6.12.0、Nuitka 4.1.1 与 Zig；构建脚本和完整包校验值见发布说明。

## 已知限制

- Sci-Hub 是需要显式启用的实验来源。站点无 PDF 链接、403 或人机验证可能导致自动获取失败；验证码由用户在浏览器中处理，之后可导入本地 PDF。
- 批量队列的暂停和未执行项仅保存在本次 GUI 会话。下载显示阶段状态，不显示字节进度，也不能强制中止活动网络任务。
- 新版会记录逐来源诊断；旧历史记录不会自动补全诊断事件，重新运行后才有详情。
