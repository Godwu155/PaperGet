"""Windows-focused Qt Widgets interface for PaperGet."""

from __future__ import annotations

from collections import deque
from importlib.resources import files
import os
from pathlib import Path
from tempfile import TemporaryFile
from urllib.parse import quote, urljoin, urlparse

from PySide6.QtCore import QObject, QSettings, QStandardPaths, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QSpinBox, QSplitter, QStatusBar, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from .config import Config
from .credentials import clear_openalex_key, get_openalex_key, save_openalex_key
from .gui_backend import Task, perform
from .models import Result, SearchResult, TitleMatch
from .resolver import normalize_doi


STATUS = {
    "downloaded": "已下载", "existing": "已有文件", "found": "已找到",
    "not_found": "未找到 PDF", "ambiguous": "需选择论文", "failed": "失败",
}
ERROR = {
    "forbidden": "来源拒绝访问（403）", "rate_limited": "来源请求过多（429）",
    "timeout": "连接超时", "connection_error": "网络连接失败",
    "invalid_pdf": "来源返回的不是有效 PDF", "disk_error": "文件写入失败",
    "no_pdf": "没有可直接下载的 PDF", "invalid_response": "来源返回的数据无效",
    "ambiguous_title": "标题有多个候选，请先选定 DOI",
    "challenge_required": "来源可能需要人机验证；请在浏览器中查看",
    "no_pdf_link": "来源页面没有可识别的 PDF 链接",
    "no_open_pdf": "开放元数据没有直接 PDF 链接",
    "work_not_found": "OpenAlex 没有这篇 DOI 的记录",
    "page_not_found": "来源页面返回 404",
    "unsupported_content": "来源返回的不是网页或 PDF",
    "doi_mismatch": "来源页面引用了其他 DOI",
    "source_disabled": "来源未启用",
    "too_large": "PDF 超过设置的大小上限",
}

DEFAULT_SCIHUB_URL = "https://sci-hub.al/"
SCIHUB_MIRRORS = (
    ("sci-hub.al", DEFAULT_SCIHUB_URL),
    ("sci-hub.mk", "https://sci-hub.mk/"),
    ("sci-hub.vg", "https://sci-hub.vg/"),
    ("sci-hub.ee（待验证）", "https://sci-hub.ee/"),
    ("sci-hub.st（待验证）", "https://sci-hub.st/"),
)


def _item(value: object) -> QTableWidgetItem:
    cell = QTableWidgetItem(str(value) if value is not None else "")
    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
    return cell


def _configure_table(table: QTableWidget, headers: list[str]) -> None:
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setSelectionMode(QTableWidget.SingleSelection)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    for index in range(1, len(headers)):
        table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeToContents)


def _default_output() -> str:
    downloads = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
    return str(Path(downloads or Path.home() / "Downloads") / "PaperGet")


def _config(settings: QSettings) -> Config:
    output = Path(str(settings.value("output_dir", _default_output())))
    scihub_enabled = settings.value("scihub_enabled", True, type=bool)
    scihub_url = str(settings.value("scihub_url", DEFAULT_SCIHUB_URL)).strip() if scihub_enabled else ""
    order = tuple(str(settings.value("source_order", "scihub,openalex")).split(","))
    if len(order) != 2 or set(order) != {"openalex", "scihub"}:
        order = ("scihub", "openalex")
    return Config.from_env(
        output_dir=output,
        openalex_api_key=get_openalex_key() or os.getenv("OPENALEX_API_KEY") or None,
        crossref_mailto=str(settings.value("crossref_mailto", "")).strip() or os.getenv("CROSSREF_MAILTO") or None,
        scihub_base_url=scihub_url or None,
        source_order=order if scihub_url else ("openalex",),
        prefer_published=settings.value("prefer_published", False, type=bool),
        max_pdf_mb=settings.value("max_pdf_mb", 100, type=int),
        non_interactive=True,
    )


class SettingsDialog(QDialog):
    def __init__(self, settings: QSettings, parent: QWidget):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("设置")
        self.resize(600, 400)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        output_row = QHBoxLayout()
        self.output = QLineEdit(str(settings.value("output_dir", _default_output())))
        browse = QPushButton("选择…")
        browse.clicked.connect(self._browse)
        output_row.addWidget(self.output)
        output_row.addWidget(browse)
        form.addRow("下载目录", output_row)
        self.prefer = QCheckBox("优先尝试出版版本")
        self.prefer.setChecked(settings.value("prefer_published", False, type=bool))
        form.addRow("版本", self.prefer)
        self.maximum = QSpinBox()
        self.maximum.setRange(1, 1000)
        self.maximum.setValue(settings.value("max_pdf_mb", 100, type=int))
        self.maximum.setSuffix(" MB")
        form.addRow("PDF 大小上限", self.maximum)
        self.openalex_key = QLineEdit()
        self.openalex_key.setEchoMode(QLineEdit.Password)
        self.openalex_key.setPlaceholderText("已有 Key；留空保持不变" if get_openalex_key() else "粘贴 OpenAlex API Key（可选）")
        self.clear_key = QPushButton("清除")
        self.clear_key.clicked.connect(self._mark_key_for_clear)
        self._clear_key = False
        key_row = QHBoxLayout()
        key_row.addWidget(self.openalex_key)
        key_row.addWidget(self.clear_key)
        form.addRow("OpenAlex API Key", key_row)
        self.key_status = QLabel("已配置 Key" if get_openalex_key() else
                                 "当前使用环境变量" if os.getenv("OPENALEX_API_KEY") else "尚未配置")
        form.addRow("Key 状态", self.key_status)
        self.crossref_mailto = QLineEdit(str(settings.value("crossref_mailto", "")))
        self.crossref_mailto.setPlaceholderText("you@example.com（可选）")
        form.addRow("Crossref 联系邮箱", self.crossref_mailto)
        self.source_order = QComboBox()
        self.source_order.addItem("开放来源优先", "openalex,scihub")
        self.source_order.addItem("Sci-Hub 优先", "scihub,openalex")
        current_order = str(settings.value("source_order", "scihub,openalex"))
        self.source_order.setCurrentIndex(1 if current_order == "scihub,openalex" else 0)
        form.addRow("来源顺序", self.source_order)
        self.scihub = QCheckBox("启用实验性 Sci-Hub 来源")
        self.scihub.setChecked(settings.value("scihub_enabled", True, type=bool))
        form.addRow("Sci-Hub 来源", self.scihub)
        self.scihub_url = QLineEdit(str(settings.value("scihub_url", DEFAULT_SCIHUB_URL)))
        self.scihub_url.setPlaceholderText("https://…")
        self.scihub_mirror = QComboBox()
        for label, url in SCIHUB_MIRRORS:
            self.scihub_mirror.addItem(label, url)
        saved_url = self.scihub_url.text().strip()
        self.scihub_mirror.setCurrentIndex(self.scihub_mirror.findData(saved_url))
        self.scihub_mirror.currentIndexChanged.connect(self._select_scihub_mirror)
        self.scihub_mirror.setEnabled(self.scihub.isChecked())
        self.scihub.toggled.connect(self.scihub_mirror.setEnabled)
        form.addRow("镜像候选", self.scihub_mirror)
        self.scihub_url.setEnabled(self.scihub.isChecked())
        self.scihub.toggled.connect(self.scihub_url.setEnabled)
        form.addRow("Sci-Hub 入口", self.scihub_url)
        layout.addLayout(form)
        layout.addWidget(QLabel("Key 保存在 Windows 凭据管理器；不可用时仅在本次运行中使用。"))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择下载目录", self.output.text())
        if path:
            self.output.setText(path)

    def _select_scihub_mirror(self, index: int) -> None:
        if index >= 0:
            self.scihub_url.setText(str(self.scihub_mirror.itemData(index)))

    def _mark_key_for_clear(self) -> None:
        self.openalex_key.clear()
        self._clear_key = True
        self.key_status.setText("保存设置后清除系统凭据；环境变量仍可生效")

    def _save(self) -> None:
        raw = self.output.text().strip()
        if not raw:
            QMessageBox.warning(self, "设置无效", "请选择下载目录。")
            return
        path = Path(raw).expanduser().resolve()
        if path.exists() and not path.is_dir():
            QMessageBox.warning(self, "设置无效", "下载目录指向了一个文件。")
            return
        try:
            path.mkdir(parents=True, exist_ok=True)
            with TemporaryFile(dir=path):
                pass
        except OSError as exc:
            QMessageBox.warning(self, "设置无效", f"下载目录不可写：{exc}")
            return
        url = self.scihub_url.text().strip()
        if self.scihub.isChecked():
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname:
                QMessageBox.warning(self, "设置无效", "Sci-Hub 入口必须是有效的 HTTPS 地址。")
                return
        mailto = self.crossref_mailto.text().strip()
        if mailto and ("@" not in mailto or any(char.isspace() for char in mailto)):
            QMessageBox.warning(self, "设置无效", "请输入有效的 Crossref 联系邮箱。")
            return
        key = self.openalex_key.text().strip()
        if key:
            persisted = save_openalex_key(key)
            if not persisted:
                QMessageBox.information(self, "Key 仅本次有效", "无法访问 Windows 凭据管理器；Key 仅在本次运行中使用。")
        elif self._clear_key and not clear_openalex_key():
            QMessageBox.warning(self, "清除未完成", "无法访问系统凭据管理器，已保存的 Key 可能仍存在。")
            return
        self.settings.setValue("output_dir", str(path))
        self.settings.setValue("crossref_mailto", mailto)
        self.settings.setValue("prefer_published", self.prefer.isChecked())
        self.settings.setValue("max_pdf_mb", self.maximum.value())
        self.settings.setValue("source_order", self.source_order.currentData())
        self.settings.setValue("scihub_enabled", self.scihub.isChecked())
        self.settings.setValue("scihub_url", url)
        self.settings.sync()
        self.accept()


class BatchPreviewDialog(QDialog):
    def __init__(self, queries: list[str], parent: QWidget,
                 invalid_rows: list[tuple[int, str]] | None = None):
        super().__init__(parent)
        self.setWindowTitle("预览批量任务")
        self.resize(650, 440)
        seen: set[str] = set()
        self.queries: list[str] = []
        for query in queries:
            key = normalize_doi(query) or " ".join(query.split()).casefold()
            if key not in seen:
                seen.add(key)
                self.queries.append(query)
        layout = QVBoxLayout(self)
        invalid_rows = invalid_rows or []
        layout.addWidget(QLabel(
            f"有效 {len(queries)} 条；去重后 {len(self.queries)} 条；跳过 {len(invalid_rows)} 行。"
        ))
        if invalid_rows:
            details = "；".join(f"第 {line} 行：{reason}" for line, reason in invalid_rows[:5])
            if len(invalid_rows) > 5:
                details += f"；另有 {len(invalid_rows) - 5} 行"
            note = QLabel(details)
            note.setWordWrap(True)
            layout.addWidget(note)
        table = QTableWidget()
        _configure_table(table, ["序号", "DOI 或标题"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        shown = self.queries[:100]
        table.setRowCount(len(shown))
        for row, query in enumerate(shown):
            table.setItem(row, 0, _item(row + 1))
            table.setItem(row, 1, _item(query))
        layout.addWidget(table)
        if len(self.queries) > len(shown):
            layout.addWidget(QLabel(f"仅预览前 {len(shown)} 条；确认后处理全部。"))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("加入队列")
        buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self.queries))
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class DiagnosticsDialog(QDialog):
    def __init__(self, rows: list[dict], parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("来源诊断")
        self.resize(830, 440)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"找到 {len(rows)} 条来源事件。旧版记录可能没有诊断详情。"
        ))
        table = QTableWidget()
        _configure_table(table, ["时间", "来源", "阶段", "结果", "错误码", "候选数", "主机 / 说明"])
        table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        table.setRowCount(len(rows))
        stages = {"discovery": "查找链接", "download": "下载", "import": "手动导入"}
        states = {"found": "已找到", "empty": "无链接", "failed": "失败",
                  "downloaded": "成功", "disabled": "未启用", "skipped": "跳过"}
        for row, record in enumerate(rows):
            values = (
                record.get("created_at") or "", record.get("source") or "",
                stages.get(record.get("stage"), record.get("stage") or ""),
                states.get(record.get("status"), record.get("status") or ""),
                ERROR.get(record.get("error_code"), record.get("error_code") or ""),
                record.get("candidate_count") or 0,
                " / ".join(filter(None, (record.get("host"), record.get("message")))),
            )
            for col, value in enumerate(values):
                table.setItem(row, col, _item(value))
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class TaskWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, task: Task, config: Config):
        super().__init__()
        self.task = task
        self.config = config

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(perform(self.task, self.config))
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("PaperGet", "PaperGet")
        self.setWindowTitle("PaperGet · 论文工作台")
        self.resize(1100, 720)
        self.setMinimumSize(850, 560)
        self.matches: list[TitleMatch] = []
        self.selected_doi: str | None = None
        self.last_result: Result | None = None
        self.sources = []
        self.pending: deque[tuple[int, str]] = deque()
        self.queue_paused = False
        self._pending_inspect = False
        self.active_row: int | None = None
        self._thread: QThread | None = None
        self._worker: TaskWorker | None = None
        self._task: Task | None = None
        self._build()
        self._theme()
        self._run_task(Task("history"))

    def _build(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 12)
        top = QHBoxLayout()
        title = QLabel("PaperGet")
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch()
        settings_button = QPushButton("设置")
        settings_button.clicked.connect(self._settings)
        top.addWidget(settings_button)
        layout.addLayout(top)
        search = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("输入 DOI 或论文标题关键词")
        self.query.returnPressed.connect(self._search)
        self.search_button = QPushButton("搜索 / 检查")
        self.search_button.setObjectName("primary")
        self.search_button.clicked.connect(self._search)
        search.addWidget(self.query, 1)
        search.addWidget(self.search_button)
        layout.addLayout(search)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("候选论文 · 匹配分数仅用于排序"))
        self.candidates = QTableWidget()
        _configure_table(self.candidates, ["标题", "作者", "年份", "DOI", "匹配"])
        self.candidates.itemSelectionChanged.connect(self._select_candidate)
        left_layout.addWidget(self.candidates)
        split.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("论文详情与 PDF 来源"))
        self.paper_title = QLabel("选择候选论文，或输入 DOI。")
        self.paper_title.setWordWrap(True)
        self.paper_title.setObjectName("paperTitle")
        right_layout.addWidget(self.paper_title)
        self.paper_doi = QLabel("")
        self.paper_doi.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right_layout.addWidget(self.paper_doi)
        self.source_table = QTableWidget()
        _configure_table(self.source_table, ["来源", "版本", "许可", "链接"])
        self.source_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.source_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        right_layout.addWidget(self.source_table)
        actions = QHBoxLayout()
        self.inspect_button = QPushButton("检查来源")
        self.inspect_button.clicked.connect(self._inspect)
        self.download_button = QPushButton("获取 PDF")
        self.download_button.setObjectName("primary")
        self.download_button.clicked.connect(self._enqueue_selected)
        self.source_button = QPushButton("打开来源页")
        self.source_button.clicked.connect(self._open_source)
        actions.addWidget(self.inspect_button)
        actions.addWidget(self.download_button)
        actions.addWidget(self.source_button)
        right_layout.addLayout(actions)
        split.addWidget(right)
        split.setSizes([620, 480])
        layout.addWidget(split, 3)

        tabs = QTabWidget()
        queue_page = QWidget()
        queue_layout = QVBoxLayout(queue_page)
        queue_toolbar = QHBoxLayout()
        import_button = QPushButton("导入 TXT/CSV")
        import_button.clicked.connect(self._import)
        self.pause_button = QPushButton("暂停队列")
        self.pause_button.clicked.connect(self._toggle_queue)
        cancel_button = QPushButton("移除等待项")
        cancel_button.clicked.connect(self._cancel_pending)
        retry_button = QPushButton("重试选中项")
        retry_button.clicked.connect(self._retry_queue)
        retry_failed = QPushButton("重试失败项")
        retry_failed.clicked.connect(self._retry_failed)
        queue_toolbar.addWidget(import_button)
        queue_toolbar.addWidget(self.pause_button)
        queue_toolbar.addWidget(cancel_button)
        queue_toolbar.addWidget(retry_button)
        queue_toolbar.addWidget(retry_failed)
        queue_toolbar.addStretch()
        queue_layout.addLayout(queue_toolbar)
        queue_manual = QHBoxLayout()
        queue_open = QPushButton("打开 PDF")
        queue_open.clicked.connect(self._open_queue_pdf)
        queue_browser = QPushButton("浏览器处理")
        queue_browser.clicked.connect(self._open_queue_browser)
        queue_attach = QPushButton("导入本地 PDF")
        queue_attach.clicked.connect(self._attach_queue_pdf)
        queue_diagnostics = QPushButton("查看原因")
        queue_diagnostics.clicked.connect(self._diagnostics_queue)
        for button in (queue_open, queue_browser, queue_attach, queue_diagnostics):
            queue_manual.addWidget(button)
        queue_manual.addStretch()
        queue_layout.addLayout(queue_manual)
        self.queue_table = QTableWidget()
        _configure_table(self.queue_table, ["论文 / DOI", "状态", "说明", "文件"])
        queue_layout.addWidget(self.queue_table)
        tabs.addTab(queue_page, "下载队列")
        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_toolbar = QHBoxLayout()
        refresh_button = QPushButton("刷新历史")
        refresh_button.clicked.connect(lambda: self._run_task(Task("history")))
        export_button = QPushButton("导出 JSON/CSV")
        export_button.clicked.connect(self._export)
        self.history_open_button = QPushButton("打开 PDF")
        self.history_open_button.clicked.connect(lambda: self._open_pdf())
        self.history_folder_button = QPushButton("打开文件夹")
        self.history_folder_button.clicked.connect(lambda: self._open_pdf(folder=True))
        history_retry = QPushButton("重试")
        history_retry.clicked.connect(self._retry_history)
        for button in (refresh_button, export_button, history_retry,
                       self.history_open_button, self.history_folder_button):
            history_toolbar.addWidget(button)
        history_toolbar.addStretch()
        history_layout.addLayout(history_toolbar)
        history_diagnostics = QHBoxLayout()
        history_reason = QPushButton("查看来源诊断")
        history_reason.clicked.connect(self._diagnostics_history)
        history_attach = QPushButton("导入本地 PDF")
        history_attach.clicked.connect(self._attach_history_pdf)
        history_export_diagnostics = QPushButton("导出诊断 JSON/CSV")
        history_export_diagnostics.clicked.connect(self._export_diagnostics)
        for button in (history_reason, history_attach, history_export_diagnostics):
            history_diagnostics.addWidget(button)
        history_diagnostics.addStretch()
        history_layout.addLayout(history_diagnostics)
        filters = QHBoxLayout()
        self.history_filter = QLineEdit()
        self.history_filter.setPlaceholderText("筛选标题或 DOI")
        self.history_filter.textChanged.connect(self._filter_history)
        self.history_status = QComboBox()
        self.history_status.addItems(["全部", "已下载", "已有文件", "未找到 PDF", "需选择论文", "失败"])
        self.history_status.currentTextChanged.connect(self._filter_history)
        filters.addWidget(self.history_filter, 1)
        filters.addWidget(self.history_status)
        history_layout.addLayout(filters)
        self.history_table = QTableWidget()
        _configure_table(self.history_table, ["标题 / DOI", "状态", "来源", "更新时间", "文件"])
        self.history_table.itemSelectionChanged.connect(self._update_history_actions)
        history_layout.addWidget(self.history_table)
        tabs.addTab(history_page, "历史")
        layout.addWidget(tabs, 2)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self._set_status("就绪")
        self._update_actions()
        self._update_history_actions()

        action_import = QAction("导入", self)
        action_import.setShortcut("Ctrl+O")
        action_import.triggered.connect(self._import)
        self.addAction(action_import)
        action_settings = QAction("设置", self)
        action_settings.setShortcut("Ctrl+,")
        action_settings.triggered.connect(self._settings)
        self.addAction(action_settings)

    def _theme(self) -> None:
        dark = self.palette().color(QPalette.Window).lightness() < 128
        background, text, panel, accent = (("#20252B", "#F3F6F8", "#2C333A", "#27A8B6") if dark else
                                           ("#F7F8FA", "#20252B", "#FFFFFF", "#087E8B"))
        self.setStyleSheet(f"""
            QWidget {{ background: {background}; color: {text}; font-size: 13px; }}
            QLineEdit, QTableWidget, QSpinBox, QTabWidget::pane {{ background: {panel}; border: 1px solid #7F8992; border-radius: 5px; }}
            QLineEdit {{ padding: 8px; }}
            QPushButton {{ padding: 7px 12px; border: 1px solid #7F8992; border-radius: 5px; }}
            QPushButton:hover {{ border-color: {accent}; }}
            QPushButton#primary {{ background: {accent}; color: white; border-color: {accent}; font-weight: 600; }}
            QLabel#title {{ font-size: 22px; font-weight: 700; }}
            QLabel#paperTitle {{ font-size: 15px; font-weight: 600; }}
        """)

    def _set_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _update_actions(self) -> None:
        selected = bool(self.selected_doi)
        self.inspect_button.setEnabled(selected and self._thread is None)
        self.download_button.setEnabled(selected)
        self.source_button.setEnabled(bool(self.sources))
        self.search_button.setEnabled(self._thread is None)

    def _run_task(self, task: Task) -> bool:
        if self._thread is not None:
            self._set_status("当前任务尚未结束，请稍候。")
            return False
        self._task = task
        thread = QThread(self)
        worker = TaskWorker(task, _config(self.settings))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._completed)
        worker.failed.connect(self._failed)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._thread = thread
        self._worker = worker
        self._set_status({"search": "检索标题中…", "inspect": "检查 PDF 来源中…", "download": "下载中…",
                          "attach_pdf": "导入 PDF 中…", "diagnostics": "读取来源诊断中…",
                          "export_diagnostics": "导出诊断中…", "history": "读取历史中…",
                          "import": "读取文件中…", "export": "导出中…"}.get(task.kind, "处理中…"))
        self._update_actions()
        thread.start()
        return True

    def _thread_finished(self) -> None:
        was_download = self._task is not None and self._task.kind in {"download", "attach_pdf"}
        self._thread = None
        self._worker = None
        self._task = None
        self._update_actions()
        if self._pending_inspect and self.selected_doi:
            self._pending_inspect = False
            self._inspect()
        elif self.pending:
            self._next_download()
        if was_download and self._thread is None:
            self._run_task(Task("history"))

    def _search(self) -> None:
        if self._thread is not None:
            self._set_status("当前任务尚未结束，请稍候。")
            return
        query = self.query.text().strip()
        if not query:
            self._set_status("请输入 DOI 或标题关键词。")
            return
        doi = normalize_doi(query)
        if doi:
            self.matches = []
            self.candidates.setRowCount(0)
            self._set_paper(doi, "")
            self._inspect()
        else:
            self._set_paper(None, "")
            self._run_task(Task("search", query=query))

    def _set_paper(self, doi: str | None, title: str) -> None:
        self.selected_doi = doi
        self.last_result = None
        self.sources = []
        self.source_table.setRowCount(0)
        self.paper_title.setText(title or ("正在检查论文…" if doi else "选择候选论文，或输入 DOI。"))
        self.paper_doi.setText(doi or "")
        self._update_actions()

    def _show_search(self, result: SearchResult) -> None:
        self.matches = result.candidates
        self.candidates.setRowCount(len(self.matches))
        for row, match in enumerate(self.matches):
            for col, value in enumerate((match.title, ", ".join(match.authors[:2]),
                                         match.year or "—", match.doi, f"{match.match_score:.3f}")):
                self.candidates.setItem(row, col, _item(value))
        if result.status == "found":
            self._set_status(f"找到 {len(self.matches)} 条候选；请核对 DOI 后选择。")
        else:
            self._set_status(ERROR.get(result.error_code, result.message or "没有找到候选论文。"))

    def _select_candidate(self) -> None:
        row = self.candidates.currentRow()
        if 0 <= row < len(self.matches):
            match = self.matches[row]
            self._set_paper(match.doi, match.title)
            if self._thread is None:
                self._inspect()
            else:
                self._pending_inspect = True

    def _inspect(self) -> None:
        if self.selected_doi:
            self._run_task(Task("inspect", query=self.selected_doi))

    def _show_inspect(self, result: Result) -> None:
        if result.doi != self.selected_doi:
            return
        self.last_result = result
        self.paper_title.setText(result.title or self.paper_title.text())
        self.sources = result.candidates
        self.source_table.setRowCount(len(self.sources))
        for row, source in enumerate(self.sources):
            for col, value in enumerate((source.source, source.version or "—", source.license or "—",
                                         source.landing_page_url or source.url)):
                self.source_table.setItem(row, col, _item(value))
        self._update_actions()
        self._set_status(f"找到 {len(self.sources)} 个 PDF 来源。" if self.sources else
                         ERROR.get(result.error_code, result.message or "没有可用的 PDF 来源。"))

    def _open_source(self) -> None:
        row = self.source_table.currentRow()
        if row < 0 and self.sources:
            row = 0
        if 0 <= row < len(self.sources):
            source = self.sources[row]
            url = source.landing_page_url or source.url
            if urlparse(url).scheme in {"http", "https"}:
                QDesktopServices.openUrl(QUrl(url))

    def _enqueue_selected(self) -> None:
        if self.selected_doi:
            self._enqueue(self.selected_doi)

    def _enqueue(self, query: str) -> None:
        for row in range(self.queue_table.rowCount()):
            if self.queue_table.item(row, 0).text() == query and self.queue_table.item(row, 1).text() in {"等待", "下载中"}:
                self._set_status("该论文已在队列中。")
                return
        row = self.queue_table.rowCount()
        self.queue_table.insertRow(row)
        for col, value in enumerate((query, "等待", "", "")):
            self.queue_table.setItem(row, col, _item(value))
        self.pending.append((row, query))
        self._next_download()

    def _next_download(self) -> None:
        if self._thread is not None or self.queue_paused:
            return
        while self.pending:
            row, query = self.pending.popleft()
            if self.queue_table.item(row, 1).text() != "等待":
                continue
            self.active_row = row
            self.queue_table.item(row, 1).setText("下载中")
            self._run_task(Task("download", query=query))
            return
        self.active_row = None

    def _show_download(self, result: Result) -> None:
        if self.active_row is None:
            return
        row = self.active_row
        self.queue_table.item(row, 1).setText(STATUS.get(result.status, result.status))
        explanation = ("没有直接链接；请查看原因或在浏览器处理" if result.error_code == "no_pdf" else
                       ERROR.get(result.error_code, result.message or result.source or ""))
        self.queue_table.item(row, 2).setText(explanation)
        self.queue_table.item(row, 2).setToolTip(result.message or "")
        self.queue_table.item(row, 3).setText(str(result.path or ""))
        self._set_status(f"{STATUS.get(result.status, result.status)}：{result.query}")
        if result.status == "ambiguous":
            self.query.setText(result.query)
            self._set_status("该标题需要选择候选 DOI；已放入搜索框。")

    def _toggle_queue(self) -> None:
        self.queue_paused = not self.queue_paused
        self.pause_button.setText("继续队列" if self.queue_paused else "暂停队列")
        self._set_status("队列已暂停；当前任务完成后停止。" if self.queue_paused else "队列继续处理。")
        if not self.queue_paused:
            self._next_download()

    def _retry_failed(self) -> None:
        queries = [self.queue_table.item(row, 0).text()
                   for row in range(self.queue_table.rowCount())
                   if self.queue_table.item(row, 1).text() in {"失败", "未找到 PDF"}]
        for query in dict.fromkeys(queries):
            self._enqueue(query)
        self._set_status(f"已将 {len(set(queries))} 个失败项加入队列。" if queries else "没有可重试的失败项。")

    def _queue_query(self) -> str | None:
        row = self.queue_table.currentRow()
        return self.queue_table.item(row, 0).text() if row >= 0 else None

    def _history_query(self) -> str | None:
        row = self.history_table.currentRow()
        if row < 0:
            return None
        query, doi = self.history_table.item(row, 0).data(Qt.UserRole)
        return doi or query

    def _open_queue_browser(self) -> None:
        doi = normalize_doi(self._queue_query() or "")
        if not doi:
            self._set_status("请先选择含 DOI 的任务。")
            return
        config = _config(self.settings)
        url = (urljoin(config.scihub_base_url.rstrip("/") + "/", quote(doi, safe="/"))
               if config.scihub_base_url else f"https://doi.org/{quote(doi, safe='/')}")
        QDesktopServices.openUrl(QUrl(url))
        self._set_status("已在浏览器打开来源页；手动下载后可导入本地 PDF。")

    def _attach_queue_pdf(self) -> None:
        self._attach_pdf(self._queue_query())

    def _attach_history_pdf(self) -> None:
        self._attach_pdf(self._history_query())

    def _attach_pdf(self, query: str | None) -> None:
        doi = normalize_doi(query or "")
        if not doi:
            self._set_status("请先选择已确认 DOI 的论文。")
            return
        if self._thread is not None:
            self._set_status("请等待当前任务完成后导入 PDF。")
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择已下载的 PDF", "", "PDF (*.pdf)")
        if not path:
            return
        row = self.queue_table.rowCount()
        self.queue_table.insertRow(row)
        for col, value in enumerate((doi, "导入中", "", "")):
            self.queue_table.setItem(row, col, _item(value))
        self.active_row = row
        self._run_task(Task("attach_pdf", query=doi, path=Path(path)))

    def _diagnostics_queue(self) -> None:
        self._request_diagnostics(self._queue_query())

    def _diagnostics_history(self) -> None:
        self._request_diagnostics(self._history_query())

    def _request_diagnostics(self, query: str | None) -> None:
        if not query:
            self._set_status("请先选择一条记录。")
            return
        self._run_task(Task("diagnostics", query=query))

    def _import(self) -> None:
        if self._thread is not None:
            self._set_status("当前任务尚未结束，请稍候。")
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入 DOI 或标题", "", "TXT / CSV (*.txt *.csv)")
        if not path:
            return
        column = "doi_or_title"
        if path.lower().endswith(".csv"):
            from PySide6.QtWidgets import QInputDialog
            column, ok = QInputDialog.getText(self, "CSV 列名", "包含 DOI 或标题的列名", text=column)
            if not ok:
                return
        self._run_task(Task("import", path=Path(path), column=column))

    def _cancel_pending(self) -> None:
        row = self.queue_table.currentRow()
        if row >= 0 and self.queue_table.item(row, 1).text() == "等待":
            self.queue_table.item(row, 1).setText("已移除")
            self._set_status("已移除等待中的任务。")

    def _retry_queue(self) -> None:
        row = self.queue_table.currentRow()
        if row < 0:
            return
        if self.queue_table.item(row, 1).text() not in {"等待", "下载中"}:
            self._enqueue(self.queue_table.item(row, 0).text())

    def _open_queue_pdf(self) -> None:
        row = self.queue_table.currentRow()
        if row < 0:
            return
        path_text = self.queue_table.item(row, 3).text()
        path = Path(path_text) if path_text else None
        if path is None or not path.is_file():
            self._set_status("PDF 文件不存在。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _show_history(self, rows: list[dict]) -> None:
        self.history_table.setRowCount(len(rows))
        for row, record in enumerate(rows):
            title = record.get("title") or record.get("doi") or record.get("query") or ""
            for col, value in enumerate((title, STATUS.get(record["status"], record["status"]),
                                         record.get("source") or "", record.get("updated_at") or "",
                                         record.get("path") or "")):
                self.history_table.setItem(row, col, _item(value))
            self.history_table.item(row, 0).setData(Qt.UserRole, (record.get("query"), record.get("doi")))
        self._filter_history()
        self._update_history_actions()
        self._set_status(f"历史记录：{len(rows)} 条。")

    def _update_history_actions(self) -> None:
        row = self.history_table.currentRow()
        path_text = self.history_table.item(row, 4).text() if row >= 0 and self.history_table.item(row, 4) else ""
        available = bool(path_text and Path(path_text).is_file())
        self.history_open_button.setEnabled(available)
        self.history_folder_button.setEnabled(available)

    def _filter_history(self, *_args) -> None:
        term = self.history_filter.text().strip().casefold()
        status = self.history_status.currentText()
        for row in range(self.history_table.rowCount()):
            title_item = self.history_table.item(row, 0)
            _, doi = title_item.data(Qt.UserRole)
            searchable = f"{title_item.text().casefold()} {(doi or '').casefold()}"
            row_status = self.history_table.item(row, 1).text()
            self.history_table.setRowHidden(row, bool((term and term not in searchable) or
                                                    (status != "全部" and status != row_status)))

    def _retry_history(self) -> None:
        row = self.history_table.currentRow()
        if row < 0:
            return
        query, doi = self.history_table.item(row, 0).data(Qt.UserRole)
        if doi:
            self._enqueue(doi)
        elif query:
            self.query.setText(query)
            self._set_status("该标题需先确认 DOI；已放入搜索框。")

    def _open_pdf(self, *, folder: bool = False) -> None:
        row = self.history_table.currentRow()
        if row < 0:
            self._set_status("请先选择一条历史记录。")
            return
        path_text = self.history_table.item(row, 4).text()
        path = Path(path_text) if path_text else None
        if path is None or not path.is_file():
            self._set_status("PDF 文件不存在；可重新下载。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if folder else path)))

    def _export(self) -> None:
        if self._thread is not None:
            self._set_status("当前任务尚未结束，请稍候。")
            return
        path, selected = QFileDialog.getSaveFileName(self, "导出历史", "paperget-results.csv",
                                                       "CSV (*.csv);;JSON (*.json)")
        if not path:
            return
        format = "json" if selected.startswith("JSON") or path.lower().endswith(".json") else "csv"
        self._run_task(Task("export", path=Path(path), format=format))

    def _export_diagnostics(self) -> None:
        if self._thread is not None:
            self._set_status("请等待当前任务完成后导出。")
            return
        path, selected = QFileDialog.getSaveFileName(self, "导出来源诊断", "paperget-diagnostics.csv",
                                                       "CSV (*.csv);;JSON (*.json)")
        if not path:
            return
        format = "json" if selected.startswith("JSON") or path.lower().endswith(".json") else "csv"
        self._run_task(Task("export_diagnostics", path=Path(path), format=format))

    def _settings(self) -> None:
        if self._thread is not None:
            self._set_status("请等待当前任务结束后再更改设置。")
            return
        if SettingsDialog(self.settings, self).exec() == QDialog.Accepted:
            self._set_status("设置已保存，对新任务生效。")
            self._run_task(Task("history"))

    @Slot(object)
    def _completed(self, value: object) -> None:
        task = self._task
        if task is None:
            return
        if task.kind == "search":
            self._show_search(value)
        elif task.kind == "inspect":
            self._show_inspect(value)
        elif task.kind in {"download", "attach_pdf"}:
            self._show_download(value)
        elif task.kind == "import":
            preview = self._batch_preview(value)
            if preview.exec() == QDialog.Accepted:
                for query in preview.queries:
                    self._enqueue(query)
                self._set_status(f"已加入 {len(preview.queries)} 条；" + ("队列已暂停。" if self.queue_paused else "开始依次处理。"))
            else:
                self._set_status("已取消批量导入。")
        elif task.kind == "history":
            self._show_history(value)
        elif task.kind == "diagnostics":
            DiagnosticsDialog(value, self).exec()
        elif task.kind in {"export", "export_diagnostics"}:
            self._set_status(f"已导出：{value}")

    @Slot(str)
    def _failed(self, message: str) -> None:
        if self._task and self._task.kind in {"download", "attach_pdf"} and self.active_row is not None:
            self.queue_table.item(self.active_row, 1).setText("失败")
            self.queue_table.item(self.active_row, 2).setText(message)
        self._set_status(f"操作失败：{message}")

    def closeEvent(self, event) -> None:
        if self._thread is not None:
            QMessageBox.information(self, "任务进行中", "请等待当前操作完成后再关闭窗口。")
            event.ignore()
            return
        event.accept()

    def _batch_preview(self, preview_data) -> BatchPreviewDialog:
        return BatchPreviewDialog(
            preview_data.queries, self, preview_data.invalid_rows
        )


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("PaperGet")
    app.setOrganizationName("PaperGet")
    icon_path = files("paperget").joinpath("assets/paperget.ico")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    return app.exec()
