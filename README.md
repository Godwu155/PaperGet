# PaperGet

输入 DOI 或论文标题，查找开放获取的 PDF，并将下载结果记录在本地。首版提供命令行和可供未来图形界面调用的 Python API。默认从 OpenAlex 获取开放副本；Sci-Hub 是需要显式配置、且可能不可用的实验性后备来源。

## 安装

需要 Python 3.11 或更高版本，以及可访问 Crossref、OpenAlex 和论文托管站点的网络。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\paperget --help
```

OpenAlex 允许少量匿名查询；批量使用建议申请免费 API key。以下环境变量仅对当前 PowerShell 会话生效：

```powershell
$env:OPENALEX_API_KEY = "你的 OpenAlex API key"  # 可选
$env:CROSSREF_MAILTO = "you@example.com"     # 可选，帮助 Crossref 识别请求
```

## 单篇查询

```powershell
paperget get 10.1371/journal.pone.0000001 --output downloads
paperget get --title "Neural Substrate of Cold-Seeking Behavior in Endotoxin Shock"
paperget inspect 10.1371/journal.pone.0000001 --json
```

`inspect` 查询论文和候选位置，不下载 PDF。标题检索来自 Crossref；若多个结果接近，在交互终端提供前三项供选择。在非交互模式下返回 `ambiguous`，不会默默选一篇。`--prefer-published` 可优先尝试最终出版版。

PDF 使用安全化 DOI 命名，默认保存到 `downloads`。已存在且文件头有效的 PDF 会跳过；`--force` 才重新下载。下载写入临时文件，检查大小和 `%PDF-` 文件头后原子改名。若开放链接返回 403、HTML 或无效文件，会尝试其他候选；同一主机返回 403 或 429 后不再尝试该主机。

## 批量、报告与恢复

TXT 文件每行一个 DOI 或标题，空行和 `#` 注释会跳过。CSV 默认读取 `doi_or_title` 列，也可用 `--column` 指定。

```powershell
paperget batch papers.txt --output downloads --report batch-results.json
paperget batch papers.csv --column doi_or_title --output downloads --report batch-results.csv --json
paperget export --output downloads --format csv --file all-results.csv
```

`--json` 在标准输出中每篇输出一行 JSON；`--report` 把本次批量结果写为 JSON 数组或 CSV。出现标题歧义时，输出目录还会生成 `needs-review.json`。`export` 从本地 SQLite 历史记录导出所有最近结果。

输出目录的 `paperget.sqlite3` 保存结果、发现的候选、下载尝试、文件来源与元数据缓存。元数据缓存有效期为 7 天。中断后用同一输入重跑，已保存的有效 PDF 会被跳过；先前失败的条目会重试。

JSON 结果主要字段：`query`、`status`、`doi`、`title`、`path`、`source`、`version`、`sha256`、`error_code`、`message`、`candidates`。`status` 可为 `downloaded`、`existing`、`found`、`not_found`、`ambiguous` 或 `failed`。退出码为 `0`（全部成功或已存在）、`1`（部分失败或报告写入失败）、`2`（参数错误）、`3`（全部失败）。

## 可选 Sci-Hub 来源

仅在明确设置站点地址后启用：

```powershell
$env:SCIHUB_BASE_URL = "https://sci-hub.al/"
paperget inspect 10.1128/AEM.01532-09 --source-order openalex,scihub
```

该适配器按 `GET /{doi}` 读取网页，提取 PDF 嵌入或链接，并排除已知的隐藏模板和广告框；它还会核对页面引文中的 DOI。它不处理验证码、登录或访问限制。`sci-hub.al` 在一个开放获取 DOI 上通过完整 GET 下载成功；同一 PDF 地址的 HEAD 与分段请求曾返回 403，因此**不能保证其他论文或网络环境也可用**。403 会作为失败原因报告，不会尝试代理轮换或绕过。未设置 `SCIHUB_BASE_URL` 时仅使用开放来源。

## Python API

```python
from pathlib import Path
from paperget import Config, PaperGetService

config = Config.from_env(output_dir=Path("downloads"), non_interactive=True)
with PaperGetService(config) as service:
    result = service.fetch("10.1371/journal.pone.0000001")
    print(result.to_dict())
```

调用 `service.fetch(query, inspect=True)` 只查找候选。图形界面可直接调用此接口并读取 `Result`，无需解析命令行文本。来源发现、下载、缓存与结果存储彼此独立，便于扩展。

## 故障处理与开发

- `ambiguous_title`：使用交互终端选择结果，或提供 DOI。
- `no_pdf`：元数据中没有可直接下载的开放 PDF；可查看 `inspect` 的候选和论文着陆页。
- `forbidden` / `rate_limited`：目标站点限制请求；稍后再试或使用其他允许访问的来源。
- `invalid_pdf`：返回的是 HTML 等非 PDF 内容，程序不会将其保存成 PDF。

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

开发任务见 [Linear 计划](https://linear.app/godwu155/document/paperget-v01-开发计划讨论稿-5bf2cb120eba)。

已验证的样本和环境限制见 [验收记录](docs/acceptance.md)。
