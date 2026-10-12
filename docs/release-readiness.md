# PaperGet v0.3 发布准备记录

更新日期：2026-10-12。跨机器已验收的交付物为开发预览版 `0.3.0.dev1`；后续改动将组成 `0.3.0.dev2` 候选包，正式版尚未发布。

## 2026-10-12 暂停点

- 当前工作分支已加入 MIT `LICENSE`、图标和第三方告知生成脚本、批量导入无效行预览、磁盘错误处理及相应测试。本机 `unittest discover -s tests -q` 运行 57 项通过，`git diff --check` 通过。
- `0.3.0.dev2` 独立程序仍有启动崩溃；`dist/PaperGet-windows-v0.3.0.dev2.zip` 是失败的诊断产物，**不得交付**。已确认 `0.3.0.dev1` 仍是最后一个经过跨机器验收的包。
- 诊断：Python 3.13 + Nuitka 4.1.1 的编译产物在导入 `paperget.gui_window` 时可能报 `SystemError: ... codeobject.c:455: bad argument to internal function`。使用旧版界面模块编译可正常启动；本轮新增的批量预览调用表达式触发了崩溃。刚将该表达式拆入 `MainWindow._batch_preview`，**尚未重新构建验证**。
- 下次先构建并在普通 Windows 图形模式启动新候选包（无界面模式 `QT_QPA_PLATFORM=offscreen` 会让旧包也异常退出，不能用于启动验收）；再验证批量预览、生成 ZIP 和哈希。正式发布前仍须核对 Qt PDF/PDFium 许可和跨机器 dev2 验收。

## 已验证

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
3. 用户已选择 MIT，仓库和候选包将包含项目 `LICENSE`。新构建脚本已嵌入 PaperGet 原创图标，并从构建环境生成第三方组件清单、复制已有许可文本。打包审计发现旧预览包带入未使用的 Qt Virtual Keyboard 插件和 PDF 图像插件；新版移除前者的构建参数并剔除 `qpdf.dll`。`qt6pdf.dll` 仍需保留，否则启动失败；其 PDFium 等第三方许可须在正式发布前复核。
4. 从文档命令重新构建最终候选包，记录提交 SHA、测试结果、ZIP 哈希和 Windows 版本；核对 README 与实际界面。
5. 发布候选确认后再确定正式版本号、Git 标签和 GitHub 发布物，并在 Linear 关闭对应工单。

## 已知限制

- Sci-Hub 是需要显式启用的实验来源。站点无 PDF 链接、403 或人机验证可能导致自动获取失败；验证码由用户在浏览器中处理，之后可导入本地 PDF。
- 批量队列的暂停和未执行项仅保存在本次 GUI 会话。下载显示阶段状态，不显示字节进度，也不能强制中止活动网络任务。
- 新版会记录逐来源诊断；旧历史记录不会自动补全诊断事件，重新运行后才有详情。
