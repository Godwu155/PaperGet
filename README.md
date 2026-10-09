# PaperGet

按 DOI 或论文标题查找并下载论文 PDF 的 Python 命令行工具。默认先查询 OpenAlex 记录中的开放副本；可选配置 Sci-Hub 页面作为后备来源。当前 Sci-Hub 适配器仅能解析常见的 PDF 嵌入或链接，目标站点尚未完成实站验证。

## 安装

需要 Python 3.11 或更高版本：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
```

OpenAlex 的免费 API key 建议通过环境变量提供。Crossref 的 `mailto` 用于标识请求。下面的变量仅在当前 PowerShell 会话生效：

```powershell
$env:OPENALEX_API_KEY = "你的 OpenAlex API key"
$env:CROSSREF_MAILTO = "you@example.com"
$env:SCIHUB_BASE_URL = "https://sci-hub.al/"  # 可选；尚未验证该站点的 DOI 页面
```

不配置 Sci-Hub 地址时，程序只使用开放获取来源。密钥不会写入结果数据库。

## 使用

```powershell
paperget get "10.7717/peerj.4375"
paperget get --title "The state of OA: a large-scale analysis of the prevalence and impact of Open Access articles"
paperget inspect "10.7717/peerj.4375"
paperget batch papers.txt --output downloads
paperget batch papers.csv --column doi_or_title --json
```

TXT 文件每行一个 DOI 或标题；CSV 默认读取 `doi_or_title` 列。`--json` 每篇输出一个 JSON 对象，供程序或未来 GUI 读取。批量标题出现歧义时记为 `ambiguous`，不会自动选取。单篇命令在交互终端显示候选供选择。

文件以 DOI 命名，保存到 `downloads` 或 `--output` 指定的目录。目录中的 `paperget.sqlite3` 记录结果和每次下载尝试。已有有效 PDF 默认跳过；`--force` 重新下载。

退出码：`0` 全部成功或已存在；`1` 部分失败；`2` 参数错误；`3` 全部失败。

## 来源与限流

OpenAlex 返回的 PDF 地址可能属于出版社或仓库，它们各有访问规则；单个链接拒绝访问时程序会尝试下一个候选。HTTP 429 和暂时性服务错误会退避重试；HTTP 403 会停止访问该来源。程序不处理验证码、登录或访问限制绕过。

可用 `--source-order openalex,scihub` 调整来源顺序，`--prefer-published` 在同一来源的候选中优先尝试最终出版版。Sci-Hub 后备只有设置 `SCIHUB_BASE_URL` 才启用；其页面结构可能变化，当前版本不保证可用。

## 开发

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

规划与任务见 [Linear 开发计划](https://linear.app/godwu155/document/paperget-v01-开发计划讨论稿-5bf2cb120eba)。
