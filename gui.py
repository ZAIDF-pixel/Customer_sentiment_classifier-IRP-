import html
import re
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QFrame,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


SENTIMENT_COLORS = {
    "positive": "#28b889",
    "neutral": "#f0ad4e",
    "negative": "#ee6c76",
}


class SentimentWindow(QMainWindow):
    analyze_requested = Signal(str)
    upload_requested = Signal(str)
    clear_database_requested = Signal()
    dashboard_refresh_requested = Signal()
    dataset_refresh_requested = Signal()
    analytics_refresh_requested = Signal()
    report_export_requested = Signal(str)
    summary_requested = Signal()
    groq_summary_requested = Signal()
    web_chart_requested = Signal()
    closing = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Customer Sentiment Classifier")
        self.resize(1360, 860)
        self.setMinimumSize(980, 680)
        self.chart_widget = None
        self.nav_buttons = []
        self._shortcuts = []
        self._build_ui()
        self._apply_theme()
        self.show_page(0)

    def _build_ui(self):
        central = QWidget()
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(central)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 26, 18, 20)
        sidebar_layout.setSpacing(8)

        brand = QLabel("CUSTOMER\nSENTIMENT\nCLASSIFIER")
        brand.setObjectName("brand")
        brand.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        sidebar_layout.addWidget(brand)
        tagline = QLabel("CUSTOMER INSIGHTS")
        tagline.setObjectName("sidebarCaption")
        sidebar_layout.addWidget(tagline)
        sidebar_layout.addSpacing(26)

        navigation = (
            "Overview",
            "Analyze review",
            "Upload dataset",
            "Datasets",
            "Analytics",
            "AI summary",
        )
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, title in enumerate(navigation):
            button = QPushButton(title)
            button.setObjectName("navButton")
            button.setCheckable(True)
            self.nav_group.addButton(button, index)
            sidebar_layout.addWidget(button)
            self.nav_buttons.append(button)
        self.nav_group.idClicked.connect(self.show_page)

        sidebar_layout.addSpacing(12)
        sidebar_note = QLabel("PRIVATE BY DESIGN\nReviews stay on this device")
        sidebar_note.setObjectName("sidebarNote")
        sidebar_layout.addWidget(sidebar_note)
        sidebar_layout.addStretch()

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(36, 30, 36, 32)
        content_layout.setSpacing(22)

        header = QHBoxLayout()
        page_heading = QVBoxLayout()
        self.page_title = QLabel("Overview")
        self.page_title.setObjectName("pageTitle")
        page_heading.addWidget(self.page_title)
        self.page_subtitle = QLabel("Your customer feedback pulse")
        self.page_subtitle.setObjectName("mutedText")
        page_heading.addWidget(self.page_subtitle)
        header.addLayout(page_heading)
        header.addStretch()
        quick_analyze = QPushButton("New analysis")
        quick_analyze.setObjectName("primaryButton")
        quick_analyze.clicked.connect(lambda: self.show_page(1))
        header.addWidget(quick_analyze)
        status = QLabel("LOCAL ENGINE READY")
        status.setObjectName("statusPill")
        header.addWidget(status)
        content_layout.addLayout(header)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_dashboard_page())
        self.pages.addWidget(self._build_analyze_page())
        self.pages.addWidget(self._build_upload_page())
        self.pages.addWidget(self._build_datasets_page())
        self.pages.addWidget(self._build_analytics_page())
        self.pages.addWidget(self._build_summary_page())
        content_layout.addWidget(self.pages, 1)
        root_layout.addWidget(sidebar)
        root_layout.addWidget(content, 1)

    def _build_dashboard_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        welcome = QFrame()
        welcome.setObjectName("welcomeCard")
        welcome_layout = QHBoxLayout(welcome)
        welcome_layout.setContentsMargins(26, 20, 26, 20)
        welcome_layout.setSpacing(18)
        welcome_copy_layout = QVBoxLayout()
        eyebrow = QLabel("CUSTOMER FEEDBACK, AT A GLANCE")
        eyebrow.setObjectName("eyebrow")
        welcome_copy_layout.addWidget(eyebrow)
        welcome_title = QLabel("Turn customer feedback into insight")
        welcome_title.setObjectName("welcomeTitle")
        welcome_copy_layout.addWidget(welcome_title)
        welcome_description = QLabel(
            "Analyze a review to discover its sentiment, then explore the trends."
        )
        welcome_description.setObjectName("welcomeDescription")
        welcome_copy_layout.addWidget(welcome_description)
        welcome_layout.addLayout(welcome_copy_layout, 1)
        welcome_action = QPushButton("Analyze a review")
        welcome_action.setObjectName("welcomeButton")
        welcome_action.clicked.connect(lambda: self.show_page(1))
        welcome_layout.addWidget(welcome_action, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addWidget(welcome)

        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(14)
        self.total_value, self.total_percent = self._add_stat_card(stats_layout, "TOTAL REVIEWS")
        self.positive_value, self.positive_percent = self._add_stat_card(
            stats_layout, "POSITIVE", SENTIMENT_COLORS["positive"]
        )
        self.neutral_value, self.neutral_percent = self._add_stat_card(
            stats_layout, "NEUTRAL", SENTIMENT_COLORS["neutral"]
        )
        self.negative_value, self.negative_percent = self._add_stat_card(
            stats_layout, "NEGATIVE", SENTIMENT_COLORS["negative"]
        )
        layout.addLayout(stats_layout)

        recent_header = QHBoxLayout()
        recent_title = QLabel("Recent reviews")
        recent_title.setObjectName("sectionTitle")
        recent_header.addWidget(recent_title)
        recent_header.addStretch()
        self.review_count_label = QLabel("Showing latest reviews")
        self.review_count_label.setObjectName("mutedText")
        recent_header.addWidget(self.review_count_label)
        refresh_button = QPushButton("Refresh")
        refresh_button.setObjectName("secondaryButton")
        refresh_button.clicked.connect(self.dashboard_refresh_requested.emit)
        recent_header.addWidget(refresh_button)
        upload_button = QPushButton("Upload dataset")
        upload_button.setObjectName("secondaryButton")
        upload_button.clicked.connect(self._choose_upload_file)
        recent_header.addWidget(upload_button)
        delete_button = QPushButton("Delete all data")
        delete_button.setObjectName("dangerButton")
        delete_button.clicked.connect(self.clear_database_requested.emit)
        recent_header.addWidget(delete_button)
        layout.addLayout(recent_header)

        self.empty_reviews = QLabel(
            "No reviews yet\nAnalyze your first customer review to see it here."
        )
        self.empty_reviews.setObjectName("emptyState")
        self.empty_reviews.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_reviews.setMinimumHeight(130)
        layout.addWidget(self.empty_reviews)
        self.recent_table = self._make_table(("Review", "Sentiment", "Date"))
        layout.addWidget(self.recent_table, 1)
        return page

    def _add_stat_card(self, layout, label_text, color="#24344c"):
        card = QFrame()
        card.setObjectName("statCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        label = QLabel(label_text)
        label.setObjectName("statLabel")
        value = QLabel("0")
        value.setObjectName("statValue")
        value.setStyleSheet(f"color: {color};")
        percentage = QLabel("")
        percentage.setObjectName("statPercent")
        card_layout.addWidget(label)
        card_layout.addWidget(value)
        card_layout.addWidget(percentage)
        layout.addWidget(card, 1)
        return value, percentage

    def _build_analyze_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        heading = QLabel("What are your customers saying?")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        description = QLabel("Enter a review below to see its sentiment and confidence.")
        description.setObjectName("mutedText")
        layout.addWidget(description)

        editor_card = QFrame()
        editor_card.setObjectName("panel")
        editor_layout = QVBoxLayout(editor_card)
        editor_layout.setContentsMargins(20, 18, 20, 18)
        editor_layout.setSpacing(12)
        editor_label = QLabel("CUSTOMER REVIEW")
        editor_label.setObjectName("eyebrow")
        editor_layout.addWidget(editor_label)
        input_header = QHBoxLayout()
        input_hint = QLabel("type a customer comment")
        input_hint.setObjectName("mutedText")
        input_header.addWidget(input_hint)
        input_header.addStretch()
        self.character_count = QLabel("0 characters")
        self.character_count.setObjectName("characterCount")
        input_header.addWidget(self.character_count)
        editor_layout.addLayout(input_header)
        self.review_input = QTextEdit()
        self.review_input.setObjectName("textInput")
        self.review_input.setPlaceholderText(
            "For example: The delivery was quick and the support team was wonderful..."
        )
        self.review_input.setMinimumHeight(190)
        self.review_input.textChanged.connect(self._update_character_count)
        editor_layout.addWidget(self.review_input)

        actions = QHBoxLayout()
        keyboard_hint = QLabel("Keyboard shortcut: Control and Enter to analyze")
        keyboard_hint.setObjectName("mutedText")
        actions.addWidget(keyboard_hint)
        actions.addStretch()
        clear_button = QPushButton("Clear")
        clear_button.setObjectName("secondaryButton")
        clear_button.clicked.connect(self.review_input.clear)
        actions.addWidget(clear_button)
        analyze_button = QPushButton("Analyze review")
        analyze_button.setObjectName("primaryButton")
        analyze_button.clicked.connect(
            lambda: self.analyze_requested.emit(self.review_input.toPlainText())
        )
        self.analyze_button = analyze_button
        actions.addWidget(analyze_button)
        editor_layout.addLayout(actions)
        layout.addWidget(editor_card)

        result_card = QFrame()
        result_card.setObjectName("resultCard")
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(20, 18, 20, 18)
        result_heading = QLabel("PREDICTION")
        result_heading.setObjectName("eyebrow")
        result_layout.addWidget(result_heading)
        self.result_label = QLabel("Your result will appear here")
        self.result_label.setObjectName("resultValue")
        result_layout.addWidget(self.result_label)
        self.confidence_label = QLabel("Add a review above to get started.")
        self.confidence_label.setObjectName("mutedText")
        result_layout.addWidget(self.confidence_label)
        self.confidence_bar = QProgressBar()
        self.confidence_bar.setObjectName("confidenceBar")
        self.confidence_bar.setRange(0, 100)
        self.confidence_bar.setValue(0)
        self.confidence_bar.setTextVisible(False)
        self.confidence_bar.setFixedHeight(8)
        result_layout.addWidget(self.confidence_bar)
        layout.addWidget(result_card)
        layout.addStretch()
        return page

    def _build_upload_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        heading = QLabel("Import customer feedback")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        description = QLabel(
            "Upload a dataset to analyze and save multiple customer reviews at once."
        )
        description.setObjectName("mutedText")
        layout.addWidget(description)

        upload_card = QFrame()
        upload_card.setObjectName("panel")
        card_layout = QVBoxLayout(upload_card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(12)

        eyebrow = QLabel("SUPPORTED FILES")
        eyebrow.setObjectName("eyebrow")
        card_layout.addWidget(eyebrow)
        formats = QLabel("CSV, Excel, and plain text")
        formats.setObjectName("sectionTitle")
        card_layout.addWidget(formats)
        details = QLabel(
            "Upload CSV or Excel files with a review column, or a TXT file with one review per line. "
            "Blank entries and duplicate reviews in the same import are skipped."
        )
        details.setObjectName("mutedText")
        details.setWordWrap(True)
        card_layout.addWidget(details)

        actions = QHBoxLayout()
        actions.addStretch()
        upload_button = QPushButton("Choose dataset")
        upload_button.setObjectName("primaryButton")
        upload_button.clicked.connect(self._choose_upload_file)
        actions.addWidget(upload_button)
        card_layout.addLayout(actions)
        layout.addWidget(upload_card)
        layout.addStretch()
        return page

    def _build_analytics_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QHBoxLayout()
        intro = QVBoxLayout()
        title = QLabel("Sentiment analytics")
        title.setObjectName("sectionTitle")
        intro.addWidget(title)
        subtitle = QLabel("Explore the reviews saved in your local history.")
        subtitle.setObjectName("mutedText")
        intro.addWidget(subtitle)
        header.addLayout(intro)
        header.addStretch()
        self.report_export_button = QPushButton("Export PDF report")
        self.report_export_button.setObjectName("primaryButton")
        self.report_export_button.clicked.connect(self._choose_report_path)
        header.addWidget(self.report_export_button)
        web_chart_button = QPushButton("Interactive web chart")
        web_chart_button.setObjectName("secondaryButton")
        web_chart_button.clicked.connect(self.web_chart_requested.emit)
        header.addWidget(web_chart_button)
        refresh_button = QPushButton("Refresh")
        refresh_button.setObjectName("secondaryButton")
        refresh_button.clicked.connect(self.analytics_refresh_requested.emit)
        header.addWidget(refresh_button)
        layout.addLayout(header)

        analytics_scroll = QScrollArea()
        analytics_scroll.setWidgetResizable(True)
        analytics_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chart_panel = QFrame()
        self.chart_panel.setObjectName("panel")
        self.chart_layout = QVBoxLayout(self.chart_panel)
        self.chart_layout.setContentsMargins(8, 8, 8, 8)
        analytics_scroll.setWidget(self.chart_panel)
        layout.addWidget(analytics_scroll, 1)
        return page

    def _build_datasets_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        header = QHBoxLayout()
        intro = QVBoxLayout()
        title = QLabel("Imported datasets")
        title.setObjectName("sectionTitle")
        intro.addWidget(title)
        subtitle = QLabel(
            "Review counts and sentiment results for each uploaded file."
        )
        subtitle.setObjectName("mutedText")
        intro.addWidget(subtitle)
        header.addLayout(intro)
        header.addStretch()
        refresh_button = QPushButton("Refresh")
        refresh_button.setObjectName("secondaryButton")
        refresh_button.clicked.connect(self.dataset_refresh_requested.emit)
        header.addWidget(refresh_button)
        layout.addLayout(header)

        self.dataset_empty_state = QLabel(
            "No datasets uploaded yet.\nUpload a CSV, Excel, or text file to see its summary here."
        )
        self.dataset_empty_state.setObjectName("emptyState")
        self.dataset_empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dataset_empty_state.setWordWrap(True)
        layout.addWidget(self.dataset_empty_state)

        self.dataset_table = self._make_table(
            ("Dataset", "Total Reviews", "Positive", "Negative", "Date")
        )
        self.dataset_table.setColumnWidth(0, 230)
        for column in (1, 2, 3):
            self.dataset_table.setColumnWidth(column, 125)
        self.dataset_table.setMinimumHeight(300)
        layout.addWidget(self.dataset_table, 1)
        return page

    def _build_summary_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        title = QLabel("Customer feedback summary")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        subtitle = QLabel(
            "Generate a local rule-based summary and Groq-powered summary."
        )
        subtitle.setObjectName("mutedText")
        layout.addWidget(subtitle)

        overview = QFrame()
        overview.setObjectName("summaryBanner")
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(18, 14, 18, 14)
        overview_title = QLabel("Your feedback brief")
        overview_title.setObjectName("summaryBannerTitle")
        overview_layout.addWidget(overview_title)
        overview_copy = QLabel(
            "Sentiment classification remains rule-based. Groq receives only aggregate counts and lexicon terms, not raw reviews."
        )
        overview_copy.setObjectName("summaryBannerCopy")
        overview_copy.setWordWrap(True)
        overview_layout.addWidget(overview_copy)
        layout.addWidget(overview)

        self.summary_output = QTextEdit()
        self.summary_output.setObjectName("summaryOutput")
        self.summary_output.setReadOnly(True)
        self.summary_output.setAcceptRichText(False)
        self.summary_output.setPlaceholderText(
            "Generate a summary to see sentiment counts, common lexicon terms, and customer concerns."
        )
        layout.addWidget(self.summary_output, 1)

        footer = QHBoxLayout()
        self.summary_status = QLabel(
            "Your latest customer insights will appear here."
        )
        self.summary_status.setObjectName("mutedText")
        footer.addWidget(self.summary_status)
        footer.addStretch()
        self.copy_summary_button = QPushButton("Copy summary")
        self.copy_summary_button.setObjectName("secondaryButton")
        self.copy_summary_button.setEnabled(False)
        self.copy_summary_button.clicked.connect(self.copy_summary)
        footer.addWidget(self.copy_summary_button)
        self.summary_button = QPushButton("DATA SUMMARY")
        self.summary_button.setObjectName("primaryButton")
        self.summary_button.clicked.connect(self.summary_requested.emit)
        footer.addWidget(self.summary_button)
        self.groq_summary_button = QPushButton("Suggestions from Groq")
        self.groq_summary_button.setObjectName("primaryButton")
        self.groq_summary_button.clicked.connect(self.groq_summary_requested.emit)
        footer.addWidget(self.groq_summary_button)
        layout.addLayout(footer)
        return page

    def _make_table(self, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setObjectName("reviewTable")
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        table.setWordWrap(False)
        table.setMinimumHeight(240)
        return table

    def _apply_theme(self):
        self.setFont(QFont("Segoe UI", 10))
        analyze_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        analyze_shortcut.activated.connect(self._request_analysis)
        self._shortcuts.append(analyze_shortcut)
        keypad_shortcut = QShortcut(QKeySequence("Ctrl+Enter"), self)
        keypad_shortcut.activated.connect(self._request_analysis)
        self._shortcuts.append(keypad_shortcut)
        for index in range(6):
            shortcut = QShortcut(QKeySequence(f"Alt+{index + 1}"), self)
            shortcut.activated.connect(lambda page=index: self.show_page(page))
            self._shortcuts.append(shortcut)
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f3f6fb; color: #1c2b43; }
            #sidebar { background: #14243a; }
            #brand {
                color: #f8fbff; background: transparent; font-size: 18px;
                font-weight: 800; padding: 5px 2px; letter-spacing: 1.2px;
            }
            #sidebarCaption {
                color: #91a7c3; background: transparent; font-size: 9px;
                font-weight: 800; letter-spacing: 2px;
            }
            #navButton {
                color: #aebdd0; background: transparent; border: 0;
                border-left: 3px solid transparent; border-radius: 7px;
                text-align: left; padding: 12px 13px; font-size: 13px;
            }
            #navButton:hover { background: #20344f; color: #ffffff; }
            #navButton:checked {
                color: #ffffff; background: #233a58; border-left-color: #65d0b1;
                font-weight: 700;
            }
            #sidebarNote {
                color: #9aadc6; background: #1a2e49; border: 1px solid #29415f;
                border-radius: 9px; padding: 12px; font-size: 10px;
                line-height: 1.5;
            }
            #pageTitle { color: #15263e; font-size: 25px; font-weight: 800; }
            #statusPill {
                color: #14785d; background: #e3f5ef; border: 1px solid #ccebdd;
                border-radius: 12px; padding: 7px 11px; font-size: 9px;
                font-weight: 800; letter-spacing: .5px;
            }
            #welcomeCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #183653, stop:1 #254b70);
                border: 1px solid #315779; border-radius: 16px;
            }
            #welcomeCard QLabel { background: transparent; }
            #eyebrow { color: #75869d; font-size: 9px; font-weight: 800; letter-spacing: 1.2px; }
            #welcomeCard #eyebrow { color: #9bc4e9; }
            #welcomeTitle { color: #ffffff; font-size: 25px; font-weight: 800; }
            #welcomeDescription { color: #d0deec; font-size: 12px; }
            #welcomeButton {
                color: #ffffff; background: #35618d; border: 1px solid #5b82a8;
                border-radius: 8px; padding: 12px 16px; font-weight: 700;
            }
            #welcomeButton:hover { background: #4274a5; }
            #mutedText { color: #758399; font-size: 12px; }
            #characterCount { color: #73829a; font-size: 11px; font-weight: 700; }
            #emptyState {
                color: #718198; background: #ffffff; border: 1px dashed #cbd6e4;
                border-radius: 12px; padding: 20px; font-size: 13px;
            }
            #statCard, #panel, #resultCard {
                background: #ffffff; border: 1px solid #e4eaf2; border-radius: 13px;
            }
            #statLabel { color: #7a879a; font-size: 9px; font-weight: 800; letter-spacing: 1px; }
            #statValue { font-size: 27px; font-weight: 800; }
            #statPercent { color: #77859a; font-size: 10px; }
            #sectionTitle { color: #1a2b44; font-size: 18px; font-weight: 800; }
            #textInput, #summaryOutput {
                color: #24364f; background: #fbfcfe; border: 1px solid #dce4ef;
                border-radius: 9px; padding: 13px; selection-background-color: #c7dcf7;
            }
            #summaryBanner {
                background: #edf4fc; border: 1px solid #dce8f6; border-radius: 11px;
            }
            #summaryBannerTitle { color: #24456c; font-size: 13px; font-weight: 750; }
            #summaryBannerCopy { color: #667990; font-size: 12px; }
            #summaryOutput { font-size: 12px; }
            #textInput:focus, #summaryOutput:focus { border: 1px solid #5c8dc7; }
            #textInput { font-size: 13px; }
            #resultValue { color: #20324b; font-size: 25px; font-weight: 800; }
            #confidenceBar { border: 0; border-radius: 4px; background: #e7edf5; }
            #confidenceBar::chunk { border-radius: 4px; background: #5286c8; }
            #primaryButton, #secondaryButton {
                min-height: 38px; border-radius: 8px; padding: 9px 15px;
                font-weight: 700;
            }
            #primaryButton {
                color: #ffffff; background: #356ca8; border: 1px solid #356ca8;
            }
            #primaryButton:hover { background: #2d5f95; border-color: #2d5f95; }
            #primaryButton:pressed { background: #244f7f; }
            #primaryButton:disabled { color: #f1f3f6; background: #9aaac0; border-color: #9aaac0; }
            #secondaryButton {
                color: #3d5069; background: #ffffff; border: 1px solid #d9e1eb;
            }
            #secondaryButton:hover { background: #f4f7fb; border-color: #c5d2e2; }
            #dangerButton {
                min-height: 38px; color: #a84550; background: #fff7f7;
                border: 1px solid #f0d7d9; border-radius: 8px;
                padding: 9px 15px; font-weight: 700;
            }
            #dangerButton:hover { background: #fff0f1; border-color: #e7bdc1; }
            #reviewTable {
                background: #ffffff; alternate-background-color: #f8fafd;
                border: 1px solid #e4eaf2; border-radius: 11px;
                gridline-color: transparent; selection-background-color: #e5eef9;
            }
            #reviewTable::item { padding: 10px; border: 0; }
            QHeaderView::section {
                color: #6d7d94; background: #f5f8fc; border: 0;
                border-bottom: 1px solid #e8edf4;
                padding: 11px; font-size: 9px; font-weight: 800;
            }
            QScrollBar:vertical {
                width: 10px; background: transparent; margin: 2px;
            }
            QScrollBar::handle:vertical {
                min-height: 28px; background: #cbd5e2; border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover { background: #aab9cc; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0; border: none; background: transparent;
            }
            QToolTip {
                color: #f8fbff; background: #172b45; border: 1px solid #304762;
                border-radius: 5px; padding: 5px 7px;
            }
            """
        )

    def show_page(self, index):
        titles = (
            "Overview",
            "Analyze review",
            "Upload dataset",
            "Datasets",
            "Analytics",
            "AI summary",
        )
        subtitles = (
            "Your customer feedback pulse",
            "Understand the sentiment behind every review",
            "Import and analyze a customer feedback dataset",
            "Review imported files and their dataset-level sentiment counts",
            "Explore patterns across your customer feedback",
            "Create optional Groq-powered summaries from rule-based analytics",
        )
        self.pages.setCurrentIndex(index)
        self.page_title.setText(titles[index])
        self.page_subtitle.setText(subtitles[index])
        for page_index, button in enumerate(self.nav_buttons):
            button.setChecked(page_index == index)
        if index == 0:
            self.dashboard_refresh_requested.emit()
        elif index == 3:
            self.dataset_refresh_requested.emit()
        elif index == 4:
            self.analytics_refresh_requested.emit()

    def set_dashboard_data(self, total, counts, recent_reviews, percentages=None):
        percentages = percentages or {}
        self.total_value.setText(str(total))
        self.total_percent.setText("Analyzed reviews")
        self.positive_value.setText(str(counts.get("positive", 0)))
        self.positive_percent.setText(f"{percentages.get('positive', 0):.2f}% of reviews")
        self.neutral_value.setText(str(counts.get("neutral", 0)))
        self.neutral_percent.setText(f"{percentages.get('neutral', 0):.2f}% of reviews")
        self.negative_value.setText(str(counts.get("negative", 0)))
        self.negative_percent.setText(f"{percentages.get('negative', 0):.2f}% of reviews")
        self.empty_reviews.setVisible(not recent_reviews)
        self.recent_table.setVisible(bool(recent_reviews))
        self.review_count_label.setText(
            f"{len(recent_reviews)} recent review"
            f"{'' if len(recent_reviews) == 1 else 's'} of {total} total"
        )
        self.recent_table.setRowCount(0)
        for review, sentiment, date_time in recent_reviews:
            row = self.recent_table.rowCount()
            self.recent_table.insertRow(row)
            values = (review, sentiment.title(), date_time)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    color = SENTIMENT_COLORS.get(value.lower(), "#eef1f5")
                    item.setForeground(QColor("#24344c"))
                    item.setBackground(QColor(color))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setToolTip(value)
                self.recent_table.setItem(row, column, item)
            self.recent_table.setRowHeight(row, 40)

    def _choose_upload_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Upload customer feedback dataset", "",
            "Feedback files (*.csv *.xlsx *.xls *.txt);;CSV files (*.csv);;Excel files (*.xlsx *.xls);;Text files (*.txt)")
        if path:
            self.upload_requested.emit(path)

    def _choose_report_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export customer sentiment report",
            "customer_sentiment_report.pdf",
            "PDF files (*.pdf)",
        )
        if path:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            self.report_export_requested.emit(path)

    def confirm_clear_database(self):
        result = QMessageBox.question(self, "Delete all stored data?",
            "This permanently deletes every saved review and its sentiment result. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return result == QMessageBox.StandardButton.Yes

    def _update_character_count(self):
        count = len(self.review_input.toPlainText())
        self.character_count.setText(
            f"{count:,} character{'s' if count != 1 else ''}"
        )

    def _request_analysis(self):
        if self.pages.currentIndex() == 1:
            self.analyze_requested.emit(self.review_input.toPlainText())

    def show_prediction(self, sentiment, confidence):
        color = SENTIMENT_COLORS.get(sentiment, "#5286c8")
        self.result_label.setText(f"{sentiment.title()} sentiment")
        self.result_label.setStyleSheet(f"color: {color};")
        self.confidence_label.setText(f"Confidence: {confidence:.1f}%")
        self.confidence_bar.setValue(round(confidence))
        self.confidence_bar.setStyleSheet(
            f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
        )

    def set_chart_widget(self, widget):
        if self.chart_widget is not None:
            self.chart_layout.removeWidget(self.chart_widget)
            self.chart_widget.setParent(None)
            self.chart_widget.deleteLater()
        self.chart_widget = widget
        self.chart_layout.addWidget(widget, 1)

    def set_dataset_history(self, rows):
        self.dataset_table.setRowCount(0)
        has_rows = bool(rows)
        self.dataset_table.setVisible(has_rows)
        self.dataset_empty_state.setVisible(not has_rows)
        for row in rows:
            dataset_row = self.dataset_table.rowCount()
            self.dataset_table.insertRow(dataset_row)
            imported_at = str(row["imported_at"])
            try:
                date_text = datetime.fromisoformat(imported_at).strftime("%b %d")
            except ValueError:
                date_text = imported_at
            values = (
                str(row["dataset_name"]),
                f'{int(row["total_reviews"]):,}',
                f'{int(row["positive_count"]):,}',
                f'{int(row["negative_count"]):,}',
                date_text,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {1, 2, 3}:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.dataset_table.setItem(dataset_row, column, item)

    def set_summary_busy(self, busy):
        self.summary_button.setEnabled(not busy)
        self.groq_summary_button.setEnabled(not busy)
        if busy:
            self.summary_status.setText("Generating feedback insights…")

    def set_report_busy(self, busy):
        self.report_export_button.setEnabled(not busy)
        self.report_export_button.setText(
            "Generating report…" if busy else "Export PDF report"
        )

    def show_summary(self, summary):
        self.summary_output.setHtml(self._summary_as_html(summary))
        self.summary_status.setText("Summary generated from your latest reviews")
        self.copy_summary_button.setEnabled(bool(summary.strip()))

    @staticmethod
    def _summary_as_html(summary):
        text = html.unescape(summary or "")
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = text.replace("•", "; ").replace("▪", "; ")
        text = re.sub(r"</(?:p|div|tr|h[1-6])\s*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]*>", "", text)
        text = re.sub(r"```(?:[\w+-]+)?\s*", "", text)
        text = text.replace("```", "")

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        cards = []
        paragraphs = []
        heading = "Customer feedback summary"
        for line in lines:
            if line.startswith("|") and line.endswith("|"):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if all(re.fullmatch(r"[:\-\s]+", cell or "-") for cell in cells):
                    continue
                if len(cells) >= 2 and cells[0].lower() in {"item", "topic"}:
                    continue
                if len(cells) >= 2:
                    label = SentimentWindow._clean_markdown(cells[0]).strip(" :")
                    content = SentimentWindow._clean_markdown(" ".join(cells[1:]))
                    if label and content:
                        cards.append((label, content))
                    continue

            clean = SentimentWindow._clean_markdown(line)
            if not clean:
                continue
            title_match = re.match(r"^(?:#{1,6}\s*)?(.+summary)\s*$", clean, re.I)
            if title_match and not paragraphs and not cards:
                heading = title_match.group(1)
                continue

            section_match = re.match(
                r"^(?:\d+[.)]\s*)?([^:]{2,70}):\s*(.+)$", clean
            )
            if section_match:
                cards.append(
                    (
                        section_match.group(1).strip(),
                        section_match.group(2).strip(),
                    )
                )
            else:
                paragraphs.append(clean)

        styles = """
            body { font-family: 'Segoe UI', sans-serif; color: #26364d; font-size: 10pt; }
            h2 { color: #1d2b42; font-size: 17pt; margin: 4px 0 8px; }
            .intro { color: #718096; margin: 0 0 18px; }
            .insight { background: #f6f8fc; border: 1px solid #e7ecf3;
                       border-radius: 8px; padding: 12px 14px; margin: 8px 0; }
            .label { color: #315f97; font-size: 10pt; font-weight: bold; margin: 0 0 5px; }
            .content { color: #45566f; line-height: 1.5; margin: 0; }
            .paragraph { color: #45566f; line-height: 1.5; margin: 12px 0; }
        """
        body = [f"<h2>{html.escape(heading)}</h2>"]
        if cards:
            body.append(
                '<p class="intro">Key themes and suggested actions from customer reviews.</p>'
            )
        for label, content in cards:
            body.append(
                '<div class="insight">'
                f'<p class="label">{html.escape(label)}</p>'
                f'<p class="content">{html.escape(content)}</p>'
                "</div>"
            )
        body.extend(
            f'<p class="paragraph">{html.escape(paragraph)}</p>'
            for paragraph in paragraphs
        )
        return f"<html><head><style>{styles}</style></head><body>{''.join(body)}</body></html>"

    @staticmethod
    def _clean_markdown(text):
        text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
        text = re.sub(r"(?<!\w)[*_](.+?)[*_](?!\w)", r"\1", text)
        text = text.replace("*", "").replace("_", "")
        text = re.sub(r"^\s*(?:[-+]\s+|\d+[.)]\s+)", "", text)
        return text.strip()

    def copy_summary(self):
        QApplication.clipboard().setText(self.summary_output.toPlainText())
        self.summary_status.setText("Summary copied to clipboard")

    def set_summary_status(self, message):
        self.summary_status.setText(message)

    def show_warning(self, title, message):
        QMessageBox.warning(self, title, message)

    def show_info(self, title, message):
        QMessageBox.information(self, title, message)

    def show_error(self, title, message):
        QMessageBox.critical(self, title, message)

    def closeEvent(self, event):
        self.closing.emit()
        super().closeEvent(event)
