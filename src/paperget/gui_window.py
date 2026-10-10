"""Windows-focused Qt Widgets interface for PaperGet."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from tempfile import TemporaryFile
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QSettings, QStandardPaths, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QSpinBox, QSplitter, QStatusBar, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from .config import Config
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
}


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
    scihub_enabled = settings.value("scihub_enabled", False, type=bool)
    scihub_url = str(settings.value("scihub_url", "")).strip() if scihub_enabled else ""
    order = tuple(str(settings.value("source_order", "openalex,scihub")).split(","))
    if len(order) != 2 or set(order) != {"openalex", "scihub"}:
        order = ("openalex", "scihub")
    return Config.from_env(
        output_dir=output,
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
        self.resize(560, 280)
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
        self.source_order = QComboBox()
        self.source_order.addItem("开放来源优先", "openalex,scihub")
        self.source_order.addItem("Sci-Hub 优先", "scihub,openalex")
        current_order = str(settings.value("source_order", "openalex,scihub"))
        self.source_order.setCurrentIndex(1 if current_order == "scihub,openalex" else 0)
        form.addRow("来源顺序", self.source_order)
        self.scihub = QCheckBox("启用实验性 Sci-Hub 后备来源")
        self.scihub.setChecked(settings.value("scihub_enabled", False, type=bool))
        form.addRow("后备来源", self.scihub)
        self.scihub_url = QLineEdit(str(settings.value("scihub_url", "")))
        self.scihub_url.setPlaceholderText("https://…")
        self.scihub_url.setEnabled(self.scihub.isChecked())
        self.scihub.toggled.connect(self.scihub_url.setEnabled)
        form.addRow("Sci-Hub 入口", self.scihub_url)
        layout.addLayout(form)
        layout.addWidget(QLabel("开放来源优先。API key 与 Crossref 邮箱从环境变量读取，不保存在设置中。"))
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
        self.settings.setValue("output_dir", str(path))
        self.settings.setValue("prefer_published", self.prefer.isChecked())
        self.settings.setValue("max_pdf_mb", self.maximum.value())
        self.settings.setValue("source_order", self.source_order.currentData())
        self.settings.setValue("scihub_enabled", self.scihub.isChecked())
        self.settings.setValue("scihub_url", url)
        self.settings.sync()
        self.accept()


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
        cancel_button = QPushButton("移除等待项")
        cancel_button.clicked.connect(self._cancel_pending)
        retry_button = QPushButton("重试选中项")
        retry_button.clicked.connect(self._retry_queue)
        queue_open = QPushButton("打开 PDF")
        queue_open.clicked.connect(self._open_queue_pdf)
        queue_toolbar.addWidget(import_button)
        queue_toolbar.addWidget(cancel_button)
        queue_toolbar.addWidget(retry_button)
        queue_toolbar.addWidget(queue_open)
        queue_toolbar.addStretch()
        queue_layout.addLayout(queue_toolbar)
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
                          "history": "读取历史中…", "import": "读取文件中…", "export": "导出中…"}.get(task.kind, "处理中…"))
        self._update_actions()
        thread.start()
        return True

    def _thread_finished(self) -> None:
        was_download = self._task is not None and self._task.kind == "download"
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
        if self._thread is not None:
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
        self.queue_table.item(row, 2).setText(ERROR.get(result.error_code, result.message or result.source or ""))
        self.queue_table.item(row, 2).setToolTip(result.message or "")
        self.queue_table.item(row, 3).setText(str(result.path or ""))
        self._set_status(f"{STATUS.get(result.status, result.status)}：{result.query}")
        if result.status == "ambiguous":
            self.query.setText(result.query)
            self._set_status("该标题需要选择候选 DOI；已放入搜索框。")

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
        elif task.kind == "download":
            self._show_download(value)
        elif task.kind == "import":
            for query in value:
                self._enqueue(query)
            self._set_status(f"已导入 {len(value)} 条，开始依次处理。")
        elif task.kind == "history":
            self._show_history(value)
        elif task.kind == "export":
            self._set_status(f"已导出：{value}")

    @Slot(str)
    def _failed(self, message: str) -> None:
        if self._task and self._task.kind == "download" and self.active_row is not None:
            self.queue_table.item(self.active_row, 1).setText("失败")
            self.queue_table.item(self.active_row, 2).setText(message)
        self._set_status(f"操作失败：{message}")

    def closeEvent(self, event) -> None:
        if self._thread is not None:
            QMessageBox.information(self, "任务进行中", "请等待当前操作完成后再关闭窗口。")
            event.ignore()
            return
        event.accept()


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("PaperGet")
    app.setOrganizationName("PaperGet")
    window = MainWindow()
    window.show()
    return app.exec()
