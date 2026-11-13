import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from textwrap import wrap

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from dotenv import load_dotenv
from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from gui import SENTIMENT_COLORS, SentimentWindow
from sentiment_engine import (
    NEGATIVE_WORDS,
    POSITIVE_WORDS,
    AnalyticsExportError,
    SentimentDatabase,
    analyze_review,
    iter_reviews_from_file,
    preprocess_text,
)


APP_DIR = Path(__file__).resolve().parent
SENTIMENTS = ("positive", "negative", "neutral")
load_dotenv(APP_DIR / ".env")


class GroqSummaryWorker(QObject):
    succeeded = Signal(str)
    failed = Signal(str)
    completed = Signal()

    def __init__(self, api_key, model, prompt):
        super().__init__()
        self.api_key = api_key
        self.model = model
        self.prompt = prompt

    def run(self):
        try:
            from groq import Groq

            client = Groq(api_key=self.api_key, timeout=30.0, max_retries=0)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You summarize customer sentiment evidence accurately. "
                            "Do not invent details beyond the provided aggregate data."
                        ),
                    },
                    {"role": "user", "content": self.prompt},
                ],
                temperature=0.3,
                max_tokens=900,
            )
            summary = response.choices[0].message.content
            if not summary or not summary.strip():
                raise RuntimeError("Groq returned an empty summary.")
            self.succeeded.emit(summary.strip())
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            self.completed.emit()


def analyze_text(text):
    """Keep the original helper's return shape for existing callers."""
    result = analyze_review(text)
    return result.sentiment.lower(), result.confidence, result.net_score


REPORT_SECTIONS = (
    "POSITIVE FEEDBACK",
    "NEGATIVE FEEDBACK",
    "NEUTRAL FEEDBACK",
    "OVERALL SUMMARY",
    "RECOMMENDED ACTIONS",
)


def parse_report_summary(summary_text):
    heading_pattern = "|".join(re.escape(heading) for heading in REPORT_SECTIONS)
    parts = re.split(
        rf"(?im)^\s*(?:\#{{1,6}}\s*)?(?:\d+[.)]\s*)?(?:\*\*|__)?"
        rf"({heading_pattern}):?(?:\*\*|__)?\s*:?\s*$",
        summary_text,
    )
    sections = {}
    for index in range(1, len(parts), 2):
        heading = parts[index].upper()
        content = parts[index + 1].strip()
        if heading in sections or not content:
            raise ValueError(f"Groq report is missing a valid {heading} section.")
        sections[heading] = content
    missing = [heading for heading in REPORT_SECTIONS if heading not in sections]
    if missing:
        raise ValueError(
            "Groq report did not include required sections: " + ", ".join(missing)
        )
    return sections


def export_sentiment_report(
    database,
    output_path,
    summary_text,
    analytics=None,
    length_distribution=None,
):
    sections = parse_report_summary(summary_text)
    analytics = analytics if analytics is not None else database.analytics()
    length_distribution = (
        length_distribution
        if length_distribution is not None
        else database.review_length_distribution()
    )
    counts = analytics["counts"]
    percentages = analytics["percentages"]
    labels = [sentiment.title() for sentiment in SENTIMENTS]
    colors = [SENTIMENT_COLORS[sentiment] for sentiment in SENTIMENTS]
    values = [counts[sentiment] for sentiment in SENTIMENTS]

    with PdfPages(output_path) as report:
        summary_figure = Figure(figsize=(8.27, 11.69), facecolor="white")
        summary_axis = summary_figure.subplots()
        summary_axis.set_axis_off()
        summary_axis.text(
            0.06, 0.95, "CUSTOMER SENTIMENT REPORT",
            fontsize=21, fontweight="bold", color="#24344c",
            transform=summary_axis.transAxes, va="top",
        )
        summary_axis.text(
            0.06, 0.91,
            f"Generated {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
            fontsize=10, color="#718096", transform=summary_axis.transAxes, va="top",
        )
        summary_axis.text(
            0.06, 0.84, f"Analyzed reviews: {analytics['total']:,}",
            fontsize=15, fontweight="bold", color="#24344c",
            transform=summary_axis.transAxes, va="top",
        )
        summary_axis.text(
            0.06, 0.78,
            "\n".join(
                f"{label}: {counts[sentiment]:,} ({percentages[sentiment]:.2f}%)"
                for label, sentiment in zip(labels, SENTIMENTS)
            ),
            fontsize=12, color="#24344c", linespacing=1.8,
            transform=summary_axis.transAxes, va="top",
        )
        report_sections = (
            ("OVERALL SUMMARY", "#24344c"),
            ("POSITIVE FEEDBACK", SENTIMENT_COLORS["positive"]),
            ("NEGATIVE FEEDBACK", SENTIMENT_COLORS["negative"]),
            ("NEUTRAL FEEDBACK", SENTIMENT_COLORS["neutral"]),
            ("RECOMMENDED ACTIONS", "#315f97"),
        )
        section_lines = []
        for heading, color in report_sections:
            section_lines.append((heading, color, True))
            for paragraph in sections[heading].splitlines():
                lines = wrap(paragraph.strip(), width=96) if paragraph.strip() else [""]
                section_lines.extend((line, "#42536b", False) for line in lines)
            section_lines.append(("", "#42536b", False))

        page_capacity = 40
        section_pages = [
            section_lines[index:index + page_capacity]
            for index in range(0, len(section_lines), page_capacity)
        ]
        summary_axis.text(
            0.06, 0.06,
            "Sentiment counts are rule-based. Groq received aggregate counts and extracted terms only; "
            "individual review text is not included.",
            fontsize=9, color="#718096", wrap=True,
            transform=summary_axis.transAxes, va="bottom",
        )
        report.savefig(summary_figure, bbox_inches="tight")

        for page_index, lines in enumerate(section_pages):
            section_figure = Figure(figsize=(8.27, 11.69), facecolor="white")
            section_axis = section_figure.subplots()
            section_axis.set_axis_off()
            section_axis.text(
                0.06, 0.96,
                "GROQ CUSTOMER INSIGHTS" if page_index == 0 else "CUSTOMER INSIGHTS (CONTINUED)",
                fontsize=17, fontweight="bold", color="#24344c",
                transform=section_axis.transAxes, va="top",
            )
            y_position = 0.90
            for line, color, is_heading in lines:
                section_axis.text(
                    0.06, y_position, line,
                    fontsize=11 if is_heading else 9.5,
                    fontweight="bold" if is_heading else "normal",
                    color=color, transform=section_axis.transAxes, va="top",
                )
                y_position -= 0.026 if is_heading else 0.020
            report.savefig(section_figure, bbox_inches="tight")

        charts_figure = Figure(figsize=(11.69, 8.27), facecolor="white")
        axes = charts_figure.subplots(2, 2)
        charts_figure.suptitle("SENTIMENT SUMMARY GRAPHS", fontsize=17, fontweight="bold")
        charts_figure.subplots_adjust(
            left=0.08, right=0.96, top=0.88, bottom=0.1, hspace=0.38, wspace=0.3
        )

        axes[0, 0].bar(labels, values, color=colors)
        axes[0, 0].set_title("Sentiment Distribution")
        axes[0, 0].set_ylabel("Number of reviews")
        axes[0, 0].grid(axis="y", color="#e8ecf3", linewidth=0.7)
        axes[0, 0].set_axisbelow(True)

        axes[0, 1].set_title("Sentiment Percentage")
        if analytics["total"]:
            axes[0, 1].pie(
                values, labels=labels, colors=colors, autopct="%1.1f%%",
                startangle=90, textprops={"fontsize": 9},
            )
        else:
            axes[0, 1].text(
                0.5, 0.5, "No reviews yet", ha="center", va="center",
                transform=axes[0, 1].transAxes, color="#718096",
            )
            axes[0, 1].set_axis_off()

        cumulative = []
        running_total = 0
        for value in values:
            running_total += value
            cumulative.append(running_total)
        axes[1, 0].plot(
            labels, cumulative, color="#168b9a", marker="o", linewidth=1.8
        )
        axes[1, 0].set_title("Cumulative Sentiment Count")
        axes[1, 0].set_ylabel("Cumulative reviews")
        axes[1, 0].grid(color="#e8ecf3", linewidth=0.7)
        axes[1, 0].set_axisbelow(True)

        buckets = sorted({row["length_bucket"] for row in length_distribution})
        if buckets:
            positions = list(range(len(buckets)))
            width = 0.24
            for index, (sentiment, color) in enumerate(zip(SENTIMENTS, colors)):
                bucket_counts = {
                    row["length_bucket"]: row["review_count"]
                    for row in length_distribution
                    if row["sentiment"].lower() == sentiment
                }
                offsets = [position + (index - 1) * width for position in positions]
                axes[1, 1].bar(
                    offsets,
                    [bucket_counts.get(bucket, 0) for bucket in buckets],
                    width=width,
                    label=sentiment.title(),
                    color=color,
                )
            axes[1, 1].set_xticks(
                positions,
                ["1000+" if bucket == 1000 else str(bucket) for bucket in buckets],
            )
            axes[1, 1].legend(fontsize=8)
        else:
            axes[1, 1].text(
                0.5, 0.5, "No reviews yet", ha="center", va="center",
                transform=axes[1, 1].transAxes, color="#718096",
            )
        axes[1, 1].set_title("Review Length Distribution")
        axes[1, 1].set_xlabel("Review length (50-character buckets)")
        axes[1, 1].set_ylabel("Number of reviews")
        axes[1, 1].grid(axis="y", color="#e8ecf3", linewidth=0.7)
        axes[1, 1].set_axisbelow(True)
        report.savefig(charts_figure, bbox_inches="tight")


class SentimentApp(QObject):
    def __init__(self, window, database_path=None, export_path=None):
        super().__init__(window)
        self.window = window
        self.database = SentimentDatabase(
            database_path or APP_DIR / "sentiment.db",
            export_path or APP_DIR / "gsentiment.js",
        )
        window.analyze_requested.connect(self.predict_sentiment)
        window.upload_requested.connect(self.upload_file)
        window.clear_database_requested.connect(self.clear_database)
        window.dashboard_refresh_requested.connect(self.refresh_dashboard)
        window.dataset_refresh_requested.connect(self.refresh_dataset_history)
        window.analytics_refresh_requested.connect(self.refresh_charts)
        window.report_export_requested.connect(self.export_report)
        window.summary_requested.connect(self.generate_summary)
        window.groq_summary_requested.connect(self.generate_groq_summary)
        window.web_chart_requested.connect(self.open_interactive_chart)
        window.closing.connect(self.close)
        self.summary_thread = None
        self.summary_worker = None
        self.pending_report_data = None
        try:
            self._refresh_views()
        except (sqlite3.Error, AnalyticsExportError, OSError, RuntimeError) as error:
            window.show_error("Startup refresh failed", str(error))

    def close(self):
        if self.summary_thread is not None and self.summary_thread.isRunning():
            self.summary_thread.quit()
            self.summary_thread.wait(31000)
        self.database.close()

    def _refresh_views(self):
        analytics = self.database.analytics()
        recent_reviews = []
        for row in self.database.recent_reviews():
            text = " ".join(str(row["raw_text"]).split())
            if len(text) > 115:
                text = text[:112] + "..."
            recent_reviews.append((text, row["sentiment"], row["created_at"]))

        self.window.set_dashboard_data(
            analytics["total"],
            analytics["counts"],
            recent_reviews,
            analytics["percentages"],
        )
        self.database.export_analytics(analytics)

    def refresh_dashboard(self):
        try:
            self._refresh_views()
        except (sqlite3.Error, AnalyticsExportError, OSError, RuntimeError) as error:
            self.window.show_error("Dashboard refresh failed", str(error))

    def predict_sentiment(self, review):
        if not isinstance(review, str) or not review.strip():
            self.window.show_warning("Review required", "Enter a customer review before analyzing.")
            return
        try:
            _, result = self.database.add_review(review)
        except AnalyticsExportError as error:
            self.window.show_error(
                "Analytics export failed",
                f"The review was saved, but {error}",
            )
            self.refresh_dashboard()
            return
        except (sqlite3.Error, ValueError) as error:
            self.window.show_error("Analysis failed", str(error))
            return

        self.window.show_prediction(result.sentiment.lower(), result.confidence)
        try:
            self._refresh_views()
        except AnalyticsExportError as error:
            self.window.show_error(
                "Analytics export failed",
                f"The review was saved, but {error}",
            )
        except (sqlite3.Error, OSError, RuntimeError) as error:
            self.window.show_error(
                "Dashboard refresh failed",
                f"The review was saved, but the dashboard could not be refreshed: {error}",
            )

    def upload_file(self, path):
        try:
            inserted, skipped = self.database.add_reviews(
                iter_reviews_from_file(path),
                dataset_name=path,
            )
        except AnalyticsExportError as error:
            self.window.show_error(
                "Analytics export failed",
                f"The imported reviews were saved, but {error}",
            )
            self.refresh_dashboard()
            return
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
            self.window.show_error("Upload failed", str(error))
            return

        self.refresh_dataset_history()
        if inserted == 0:
            self.window.show_warning(
                "No new reviews imported",
                f"No new non-empty reviews were found. Skipped {skipped:,} empty or duplicate entries.",
            )
            try:
                self._refresh_views()
            except (sqlite3.Error, AnalyticsExportError, OSError, RuntimeError) as error:
                self.window.show_error("Dashboard refresh failed", str(error))
            return

        try:
            self._refresh_views()
        except AnalyticsExportError as error:
            self.window.show_error(
                "Analytics export failed",
                f"Bulk import saved {inserted} reviews, but {error}",
            )
            return
        except (sqlite3.Error, OSError, RuntimeError) as error:
            self.window.show_error(
                "Dashboard refresh failed",
                f"Bulk import saved {inserted} reviews, but the dashboard could not be refreshed: {error}",
            )
            return
        self.window.show_info(
            "Bulk analysis complete",
            f"Analyzed and saved {inserted:,} reviews. Skipped {skipped:,} empty or duplicate entries.",
        )

    def refresh_dataset_history(self):
        try:
            self.window.set_dataset_history(self.database.dataset_summary())
        except sqlite3.Error as error:
            self.window.show_error("Dataset history refresh failed", str(error))

    def clear_database(self):
        if not self.window.confirm_clear_database():
            return
        try:
            self.database.delete_all()
            self._refresh_views()
            self.refresh_dataset_history()
        except AnalyticsExportError as error:
            self.window.show_error(
                "Analytics export failed",
                f"The database was cleared, but {error}",
            )
            self.refresh_dashboard()
            return
        except (sqlite3.Error, OSError, RuntimeError) as error:
            self.window.show_error("Delete failed", str(error))
            return
        self.window.show_info("Database cleared", "All stored reviews and their analysis results were deleted.")

    def refresh_charts(self):
        try:
            analytics = self.database.analytics()
            self._render_charts(analytics, self.database.review_length_distribution())
            self.database.export_analytics(analytics)
        except (sqlite3.Error, AnalyticsExportError, OSError, RuntimeError) as error:
            self.window.show_error("Analytics refresh failed", str(error))

    def export_report(self, path):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            self.window.show_warning(
                "Groq API key required",
                "Add your Groq key as GROQ_API_KEY in the project .env file, then restart the application.",
            )
            return
        if self.summary_thread is not None and self.summary_thread.isRunning():
            self.window.show_warning(
                "Summary already running",
                "Wait for the current Groq summary to finish before exporting a report.",
            )
            return
        try:
            analytics = self.database.analytics()
            length_distribution = self.database.review_length_distribution()
            evidence = self._report_evidence(analytics)
        except (sqlite3.Error, RuntimeError) as error:
            self.window.show_error("Report preparation failed", str(error))
            return

        model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        prompt = (
            "Write a concise, evidence-based customer sentiment report from the aggregate data below. "
            "Do not invent themes, claim access to individual reviews, or treat a rule-based neutral "
            "label as proof that a customer has no opinion. If a sentiment has zero reviews or no "
            "terms, state that explicitly. Return exactly these five headings, each on its own line, "
            "followed by 1-3 concise sentences or bullets: "
            "OVERALL SUMMARY, POSITIVE FEEDBACK, NEGATIVE FEEDBACK, NEUTRAL FEEDBACK, "
            "RECOMMENDED ACTIONS. For neutral feedback, do not infer themes from absent terms; "
            "summarize the count and explain that neutral means a zero rule-based net score.\n\n"
            f"{evidence}"
        )
        self.pending_report_data = (path, analytics, length_distribution)
        self.window.set_report_busy(True)
        self.summary_thread = QThread()
        self.summary_worker = GroqSummaryWorker(api_key, model, prompt)
        self.summary_worker.moveToThread(self.summary_thread)
        self.summary_thread.started.connect(self.summary_worker.run)
        self.summary_worker.succeeded.connect(self._handle_groq_success)
        self.summary_worker.failed.connect(self._handle_groq_error)
        self.summary_worker.completed.connect(self.summary_thread.quit)
        self.summary_thread.finished.connect(self.summary_worker.deleteLater)
        self.summary_thread.finished.connect(self._groq_summary_finished)
        self.summary_thread.start()

    def _report_evidence(self, analytics=None):
        analytics = analytics if analytics is not None else self.database.analytics()
        terms = {sentiment: Counter() for sentiment in SENTIMENTS}
        rows = self.database.connection.execute(
            """
            SELECT r.raw_text, a.sentiment
            FROM Table_Reviews AS r
            JOIN Table_Analysis AS a ON a.review_id = r.review_id
            """
        )
        for row in rows:
            sentiment = row["sentiment"].lower()
            if sentiment == "positive":
                terms[sentiment].update(
                    word for word in preprocess_text(row["raw_text"])
                    if word in POSITIVE_WORDS
                )
            elif sentiment == "negative":
                terms[sentiment].update(
                    word for word in preprocess_text(row["raw_text"])
                    if word in NEGATIVE_WORDS
                )

        evidence_lines = [f"Analyzed reviews: {analytics['total']}"]
        for sentiment in SENTIMENTS:
            evidence_lines.append(
                f"{sentiment.title()}: {analytics['counts'][sentiment]} "
                f"({analytics['percentages'][sentiment]:.2f}%)"
            )
            if sentiment != "neutral":
                common_terms = ", ".join(
                    word for word, _ in terms[sentiment].most_common(5)
                ) or "none"
                evidence_lines.append(f"Common {sentiment} lexicon terms: {common_terms}")
            else:
                evidence_lines.append(
                    "Neutral lexicon terms: not available; neutral means no net matched sentiment."
                )
        return "\n".join(evidence_lines)

    def _render_charts(self, analytics, review_length_distribution):
        figure = Figure(figsize=(7.5, 5.5), dpi=100, facecolor="white")
        axes = figure.subplots(2, 2)
        figure.subplots_adjust(left=.1, right=.96, top=.9, bottom=.12, hspace=.48, wspace=.34)
        values = [analytics["counts"][sentiment] for sentiment in SENTIMENTS]
        total = analytics["total"]
        colors = [SENTIMENT_COLORS[sentiment] for sentiment in SENTIMENTS]
        labels = [sentiment.title() for sentiment in SENTIMENTS]

        for axis in axes.flat:
            axis.tick_params(labelsize=9)

        axes[0, 0].bar(labels, values, color=colors, width=.72)
        axes[0, 0].set_title("Sentiment Distribution", fontsize=11, pad=8)
        axes[0, 0].set_xlabel("Sentiment")
        axes[0, 0].set_ylabel("Number of Reviews")
        axes[0, 0].grid(axis="y", color="#e8ecf3", linewidth=.7)
        axes[0, 0].set_axisbelow(True)
        axes[0, 0].set_ylim(0, max(values, default=0) * 1.18 if total else 1)
        for index, value in enumerate(values):
            axes[0, 0].text(index, value, f" {value}", ha="center", va="bottom", fontsize=9)

        axes[0, 1].set_title("Sentiment Percentage", fontsize=11, pad=8)
        if total:
            axes[0, 1].pie(
                values,
                labels=labels,
                colors=colors,
                autopct="%1.1f%%",
                startangle=90,
                textprops={"fontsize": 8},
            )
        else:
            axes[0, 1].text(
                .5, .5, "No reviews yet", ha="center", va="center",
                transform=axes[0, 1].transAxes, color="#718096",
            )
            axes[0, 1].set_axis_off()

        cumulative = []
        running_total = 0
        for value in values:
            running_total += value
            cumulative.append(running_total)
        axes[1, 0].plot(
            labels, cumulative, color="#168b9a", marker="o", linewidth=1.8
        )
        axes[1, 0].set_title("Cumulative Sentiment Count", fontsize=11, pad=8)
        axes[1, 0].set_xlabel("Sentiment")
        axes[1, 0].set_ylabel("Cumulative Count")
        axes[1, 0].grid(color="#e8ecf3", linewidth=.7)
        axes[1, 0].set_axisbelow(True)
        if not total:
            axes[1, 0].text(
                .5, .5, "No reviews yet", ha="center", va="center",
                transform=axes[1, 0].transAxes, color="#718096",
            )

        sentiment_y = {"negative": 0, "neutral": 1, "positive": 2}
        actual_lengths = []
        actual_positions = []
        actual_colors = []
        for row in self.database.review_lengths_by_sentiment():
            sentiment = row["sentiment"].lower()
            if sentiment not in sentiment_y:
                continue
            actual_lengths.append(row["review_length"])
            actual_positions.append(sentiment_y[sentiment])
            actual_colors.append(SENTIMENT_COLORS[sentiment])

        if actual_lengths:
            axes[1, 1].scatter(
                actual_lengths,
                actual_positions,
                c=actual_colors,
                alpha=0.8,
                s=36,
                edgecolors="none",
            )
            min_length = max(0, min(actual_lengths) - 5)
            max_length = max(actual_lengths) + 5
            axes[1, 1].set_xlim(min_length, max_length)

        axes[1, 1].set_title("Review Length by Sentiment", fontsize=11, pad=8)
        axes[1, 1].set_xlabel("Review Length (characters)")
        axes[1, 1].set_ylabel("Sentiment")
        axes[1, 1].set_yticks(
            [sentiment_y[s] for s in ("negative", "neutral", "positive")],
            ["Negative", "Neutral", "Positive"],
        )
        axes[1, 1].grid(axis="x", color="#e8ecf3", linewidth=.7)
        axes[1, 1].set_axisbelow(True)
        if not total:
            axes[1, 1].text(
                .5, .5, "No reviews yet", ha="center", va="center",
                transform=axes[1, 1].transAxes, color="#718096",
            )

        canvas = FigureCanvasQTAgg(figure)
        self.window.set_chart_widget(canvas)
        canvas.draw()

    def _local_summary_text(self):
        try:
            analytics = self.database.analytics()
        except sqlite3.Error as error:
            raise RuntimeError(f"Unable to read sentiment analytics: {error}") from error
        if not analytics["total"]:
            return None

        positive_terms = Counter()
        negative_terms = Counter()
        try:
            rows = self.database.connection.execute(
                """
                SELECT r.raw_text, a.sentiment
                FROM Table_Reviews AS r
                JOIN Table_Analysis AS a ON a.review_id = r.review_id
                """
            )
            for row in rows:
                if row["sentiment"] == "Positive":
                    sentiment_words = POSITIVE_WORDS
                    term_counts = positive_terms
                elif row["sentiment"] == "Negative":
                    sentiment_words = NEGATIVE_WORDS
                    term_counts = negative_terms
                else:
                    continue
                term_counts.update(
                    word for word in preprocess_text(row["raw_text"]) if word in sentiment_words
                )
        except sqlite3.Error as error:
            raise RuntimeError(f"Unable to read customer reviews: {error}") from error

        def top_terms(counter):
            return ", ".join(word for word, _ in counter.most_common(5)) or "No recurring lexicon terms"

        counts = analytics["counts"]
        percentages = analytics["percentages"]
        return (
            f"Analyzed reviews: {analytics['total']}\n"
            f"Positive: {counts['positive']} ({percentages['positive']:.2f}%)\n"
            f"Negative: {counts['negative']} ({percentages['negative']:.2f}%)\n"
            f"Neutral: {counts['neutral']} ({percentages['neutral']:.2f}%)\n\n"
            f"Common positive terms: {top_terms(positive_terms)}\n"
            f"Common negative terms: {top_terms(negative_terms)}"
        )

    def generate_summary(self):
        try:
            summary = self._local_summary_text()
        except RuntimeError as error:
            self.window.show_error("Summary failed", str(error))
            return
        if summary is None:
            self.window.show_info("No reviews yet", "Analyze some reviews before generating a summary.")
            return
        self.window.show_summary(
            summary + "\n\nThis summary is generated locally; no external AI service is used."
        )

    def generate_groq_summary(self):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            self.window.show_warning(
                "Groq API key required",
                "Add your Groq key as GROQ_API_KEY in the project .env file, then restart the application.",
            )
            return
        if self.summary_thread is not None and self.summary_thread.isRunning():
            return
        try:
            evidence = self._local_summary_text()
        except RuntimeError as error:
            self.window.show_error("Summary failed", str(error))
            return
        if evidence is None:
            self.window.show_info("No reviews yet", "Analyze some reviews before generating a summary.")
            return

        model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        prompt = (
            "Create a concise customer feedback summary from the following rule-based "
            "aggregate counts, percentages, and lexicon terms. Mention the overall "
            "distribution, common positive and negative themes, and practical next steps. "
            "Do not claim access to individual reviews or infer facts not present in the data.\n\n"
            f"{evidence}"
        )
        self.window.set_summary_busy(True)
        self.window.set_summary_status(f"Generating Groq summary with {model}…")
        self.summary_thread = QThread()
        self.summary_worker = GroqSummaryWorker(api_key, model, prompt)
        self.summary_worker.moveToThread(self.summary_thread)
        self.summary_thread.started.connect(self.summary_worker.run)
        self.summary_worker.succeeded.connect(self._show_groq_summary)
        self.summary_worker.failed.connect(self._show_groq_error)
        self.summary_worker.completed.connect(self.summary_thread.quit)
        self.summary_thread.finished.connect(self.summary_worker.deleteLater)
        self.summary_thread.finished.connect(self._groq_summary_finished)
        self.summary_thread.start()

    def _show_groq_summary(self, summary):
        self.window.show_summary(summary)
        self.window.set_summary_status("Groq summary generated from database-derived aggregate evidence")

    def _handle_groq_success(self, summary):
        report_data = self.pending_report_data
        if report_data is None:
            self._show_groq_summary(summary)
            return

        self.pending_report_data = None
        output_path, analytics, length_distribution = report_data
        try:
            export_sentiment_report(
                self.database,
                output_path,
                summary,
                analytics=analytics,
                length_distribution=length_distribution,
            )
        except (sqlite3.Error, OSError, RuntimeError, ValueError) as error:
            self.window.show_error("Report export failed", str(error))
            return
        self.window.show_info("Report exported", f"Saved PDF report to:\n{output_path}")

    def _show_groq_error(self, message):
        self.window.set_summary_status("Groq summary could not be generated")
        self.window.show_error("Groq summary failed", message)

    def _handle_groq_error(self, message):
        if self.pending_report_data is None:
            self._show_groq_error(message)
            return
        self.pending_report_data = None
        self.window.show_error(
            "Groq report summary failed",
            f"The PDF was not created because Groq could not generate its structured summary.\n\n{message}",
        )

    def _groq_summary_finished(self):
        self.window.set_summary_busy(False)
        self.window.set_report_busy(False)
        self.summary_worker = None
        self.summary_thread = None

    def open_interactive_chart(self):
        chart_path = APP_DIR / "sentiment_chart.html"
        if not chart_path.is_file():
            self.window.show_error("Chart unavailable", f"Could not find {chart_path}.")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(chart_path))):
            self.window.show_error("Chart unavailable", "The interactive chart could not be opened.")


def main():
    application = QApplication(sys.argv)
    application.setApplicationName("CUSTOMER SENTIMENT CLASSIFIER")
    window = SentimentWindow()
    try:
        controller = SentimentApp(window)
    except (sqlite3.Error, AnalyticsExportError, OSError) as error:
        window.show_error("Application startup failed", str(error))
        return 1
    window.show()
    result = application.exec()
    controller.close()
    return result


if __name__ == "__main__":
    sys.exit(main())
