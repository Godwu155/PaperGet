# PaperGet

输入 DOI 或论文标题，查找开放获取的 PDF，并将下载结果记录在本地。提供命令行、Windows 图形界面开发版和 Python API。默认从 OpenAlex 获取开放副本；Sci-Hub 是需要显式配置、且可能不可用的实验性后备来源。

## 安装

需要 Python 3.11 或更高版本，以及可访问 Crossref、OpenAlex 和论文托管站点的网络。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\paperget --help
```

## Windows 图形界面（开发版）

GUI 使用 PySide6 和系统凭据管理器，作为可选依赖安装；只使用命令行时无需安装它们。

```powershell
.venv\Scripts\python -m pip install -e '.[gui]'
.venv\Scripts\paperget-gui
```

在主窗口输入 DOI 可直接检查来源；输入部分标题则列出候选论文，选中并核对 DOI 后点击“获取 PDF”。下方可导入 TXT/CSV 批量任务，查看历史并导出 JSON/CSV。设置中可调整下载目录、来源顺序、出版版偏好与大小上限，也可填写 OpenAlex API Key 和 Crossref 联系邮箱。Windows 上的 Key 保存在凭据管理器，不写入普通设置文件；若凭据管理器不可用，输入的 Key 仅在本次运行中有效。环境变量 `OPENALEX_API_KEY` 和 `CROSSREF_MAILTO` 仍可使用。Sci-Hub 默认关闭，只有在设置中主动启用并填写 HTTPS 入口后才作为后备来源。

下载与网络操作在后台运行；当前显示阶段状态，不显示无法核实的下载百分比。等待中的批量任务可移除；正在进行的网络任务需等其结束后关闭窗口。界面实施与验收细节见 [GUI 开发说明](docs/gui.md)。

若本机 Python 的 `venv`/`ensurepip` 不可用，也可用 `uv venv .venv`、`uv pip install --python .venv\Scripts\python.exe .` 安装。若 `uv` 生成的 Windows 启动器无法运行，可用 `.venv\Scripts\python -m paperget.cli` 加相同子命令。

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

## 标题模糊搜索

`search` 只检索候选元数据，不下载 PDF，也不会自动选定论文。输入可以是部分标题或词序不同的关键词：

```powershell
paperget search "single cell RNA seq profiling human preimplantation embryos" --limit 10
paperget search "single cell RNA seq profiling human preimplantation embryos" --json
paperget get 10.1038/nsmb.2660 --output downloads
```

默认列出最多 10 条；`--limit` 可设为 1–50。候选包括标题、作者、年份、DOI 链接和 `match_score`。分数范围 0–1，只用于排序，**不是论文正确匹配的概率**；下载前请核对 DOI。`--json` 输出一个对象，字段为 `query`、`status`、`count`、`candidates`、`error_code`、`message`，便于后续 GUI 显示候选列表。标题搜索结果也使用输出目录中的 SQLite 元数据缓存。

PDF 使用论文标题命名，并附加由 DOI 生成的简短标识，默认保存到 `downloads`。例如 `Example paper [a1b2c3d4e5].pdf`；Crossref 没有标题时会尝试使用 OpenAlex 标题，两者都没有时退回 DOI 命名。文件名会清理 Windows 禁用字符并限制长度。同一输出目录里已存在的旧版 DOI 文件名仍被识别和复用，不会自动改名。已存在且文件头有效的 PDF 会跳过；`--force` 才重新下载。下载写入临时文件，检查大小和 `%PDF-` 文件头后原子改名。若开放链接返回 403、HTML 或无效文件，会尝试其他候选；同一主机返回 403 或 429 后不再尝试该主机。

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

也可以只为一次运行指定入口，例如 `paperget get 10.1038/nsmb.2660 --scihub-url https://sci-hub.al/ --output downloads`。若未配置后备来源且开放元数据没有直接 PDF，结果会明确提示后备来源未启用。

该适配器按 `GET /{doi}` 读取网页，提取 PDF 嵌入或链接，并排除已知的隐藏模板和广告框；它还会核对页面引文中的 DOI。它不处理验证码、登录或访问限制。`sci-hub.al` 在一个开放获取 DOI 上通过完整 GET 下载成功；同一 PDF 地址的 HEAD 与分段请求曾返回 403，因此**不能保证其他论文或网络环境也可用**。403 会作为失败原因报告，不会尝试代理轮换或绕过。未设置 `SCIHUB_BASE_URL` 时仅使用开放来源。

## Python API

```python
from pathlib import Path
from paperget import Config, PaperGetService

config = Config.from_env(output_dir=Path("downloads"), non_interactive=True)
with PaperGetService(config) as service:
    matches = service.search_title("single cell RNA seq profiling human preimplantation embryos", limit=10)
    print(matches.to_dict())
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

开发任务与决策见 [Linear 计划与验收](https://linear.app/godwu155/document/paperget-v01-开发计划与验收-5bf2cb120eba)。

已验证的样本和环境限制见 [验收记录](docs/acceptance.md)。
