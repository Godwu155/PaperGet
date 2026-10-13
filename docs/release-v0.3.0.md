# PaperGet v0.3.0

发布日期：2026-10-13。源码标签：[`v0.3.0`](https://github.com/Godwu155/sci-hub-tool/releases/tag/v0.3.0)。项目源码采用 MIT 许可证。

## 下载与使用

从 [GitHub Release](https://github.com/Godwu155/sci-hub-tool/releases/tag/v0.3.0) 下载 `PaperGet-windows-v0.3.0.zip`，解压整个文件夹后运行 `PaperGet.exe`。不需要安装 Python 或虚拟环境。不要单独移动 EXE；同目录的 Qt 库和插件是运行所需文件。

| 发布物 | 大小 | SHA-256 |
| --- | ---: | --- |
| `PaperGet-windows-v0.3.0.zip` | 32,166,029 字节 | `550F617FCEA9133548F3D42AAC2174CDD72E17ECFB60003DEF20AF4C84E0462D` |

在 PowerShell 中可用 `Get-FileHash .\PaperGet-windows-v0.3.0.zip -Algorithm SHA256` 核对。ZIP 已进行完整性检查，内含 `PaperGet.exe`、MIT `LICENSE`、`THIRD_PARTY_NOTICES.md` 以及 Qt LGPLv3/GPLv3 文本。Qt/PySide6 对应源码获取入口和替换说明写在包内的第三方告知文件中。

## 本版内容

- Windows 图形界面：DOI 和模糊标题检索、候选 DOI 核对、来源诊断、单篇下载、TXT/CSV 批量队列、SQLite 历史及 JSON/CSV 导出。
- 设置页可管理下载目录、来源、出版版偏好和文件大小上限；OpenAlex API Key 使用 Windows 凭据管理器。PDF 以论文标题和 DOI 标识命名。
- 站点要求人机验证时可在浏览器自行处理并导入本地 PDF。程序不会自动解验证码。
- 遇到 403/429 时记录来源诊断并尝试其他候选；429 不再按较长 `Retry-After` 等待，单个 PDF 下载约 180 秒超时，避免队列长期停在“下载中”。
- 保留命令行和 Python API。Sci-Hub 为需用户显式启用并填写 HTTPS 入口的实验性来源；开放来源默认优先。

## 验收与限制

Windows 本机源码测试 60 项通过；正式 ZIP 完整性和独立解压启动已检查。用户确认此前 `0.3.0.dev4` 的程序均已验收且下载正常；正式版使用相同下载逻辑并更新版本、文档和许可告知。不同缩放比例、深色模式及所有外部站点错误组合没有逐项跨机器记录。

批量暂停在当前任务结束后生效，未运行队列不跨会话保存；活动网络请求无法强制取消。站点 403、429、无 PDF 或人机验证仍可能导致单篇失败；可在来源诊断中查看具体原因。详见 [发布与构建记录](release-readiness.md)。
