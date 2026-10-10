# PaperGet v0.2 验收样本

验收日期：2026-10-10。实站结果仅说明当时的网络与站点状态，重跑可能变化。测试文件保存在本地忽略目录 `.tmp/`，不提交论文 PDF。

| 场景 | 输入或模拟条件 | 预期及观测 |
| --- | --- | --- |
| 开放获取 DOI | `10.1371/journal.pone.0000001` | OpenAlex 提供 PLOS PDF；完整下载成功，816,502 字节，文件头 `%PDF-`；重复运行返回 `existing`。 |
| 标题检索 | `Neural Substrate of Cold-Seeking Behavior in Endotoxin Shock` | Crossref 解析到上述 DOI，并可列出开放候选。 |
| Sci-Hub 页面及 PDF | `10.1128/AEM.01532-09`，入口 `https://sci-hub.al/` | `GET /{doi}` 找到嵌入的 PDF；完整 GET 下载成功，1,046,802 字节；`pdftotext` 核对首页 DOI 和标题一致。此文自身为开放获取论文，不代表其他 DOI 可用。 |
| 无开放 PDF 的实际 DOI | `10.1038/nsmb.2660` | OpenAlex 未给出可直接下载的开放 PDF；未配置 Sci-Hub 时返回明确启用提示。用 `--scihub-url https://sci-hub.al/` 后下载成功，1,311,127 字节、12 页，首页 DOI 和标题一致；重复运行返回 `existing`。 |
| 开放来源失败后回退 | 同上，OpenAlex 候选返回 403 | 继续尝试 Sci-Hub 候选并下载成功。 |
| 标题歧义 | 模拟两个高相似候选 | 非交互模式返回 `ambiguous_title`，不静默选择。 |
| 错误页面与中断 | 模拟 HTML 伪装 PDF、传输中断 | 不留下目标 PDF 或 `.part` 文件，可尝试下一候选。 |
| 限流与禁止 | 模拟 429、403 | 429 按 `Retry-After` 重试；403 立即停止该主机的后续候选。 |
| 批量继续与导出 | 三行 TXT：有效 DOI、Crossref 坏 JSON 的标题、重复 DOI | 依次得到 `downloaded`、`failed`、`existing`；报告和 SQLite 导出仍可读。 |
| 标题模糊搜索 | `single cell RNA seq profiling human preimplantation embryos` | `search --limit 10` 实际返回 10 条 Crossref 候选；目标 DOI `10.1038/nsmb.2660` 排第一。只查询元数据，不下载；JSON 包含作者、年份、排序分数和 DOI 链接。 |

本机系统 Python 的 `ensurepip` 无法建立虚拟环境，因此改用 `uv venv --seed` 基于 Python 3.12.14 创建全新环境，再用该环境的 `pip` 安装 v0.2 wheel 及依赖；`paperget.exe search --help` 成功运行。单独用 `uv pip` 安装同一 wheel 时，模块入口可用，但其生成的 Windows `paperget.exe` 在本机报 `Failed to canonicalize script path`；已确认不是项目的 `pip` 安装入口故障。标准自动化测试 29 项通过。
