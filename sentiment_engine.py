import csv
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


SENTIMENTS = ("Positive", "Negative", "Neutral")
POSITIVE_WORDS = frozenset(
    """
    good great excellent amazing wonderful fantastic love loved like happy satisfied
    best awesome perfect nice helpful friendly fast quick easy clean reliable recommend
    smooth comfortable delicious beautiful impressive affordable valuable positive enjoy
    enjoyed works working well prompt professional polite efficient
    """.split()
)
NEGATIVE_WORDS = frozenset(
    """
    bad worst terrible awful hate hated poor disappointed disappointing slow broken late
    rude unhelpful difficult hard expensive dirty unreliable problem issue fail failed
    failure annoying frustrating useless negative unhappy unsatisfied defective damaged
    error mistake complaint refund delay horrible boring weak
    """.split()
)
NEGATIONS = frozenset(
    "not never no don't doesn't didn't can't couldn't won't wouldn't isn't aren't wasn't weren't hardly".split()
)
_CONTRACTIONS = {
    "aren't": "not",
    "can't": "not",
    "couldn't": "not",
    "didn't": "not",
    "doesn't": "not",
    "don't": "not",
    "isn't": "not",
    "wasn't": "not",
    "weren't": "not",
    "won't": "not",
    "wouldn't": "not",
}
_REVIEW_COLUMNS = ("review", "review_text", "text", "feedback", "comment", "customer_feedback")
_ADVERSATIVES = frozenset(("but", "however", "although", "yet"))


@dataclass(frozen=True)
class AnalysisResult:
    positive_count: int
    negative_count: int
    net_score: int
    sentiment: str
    confidence: float


class AnalyticsExportError(OSError):
    """Raised when database analytics cannot be written to the JavaScript export."""


def preprocess_text(text):
    """Lowercase, normalize common negation contractions, remove punctuation, and tokenize."""
    if not isinstance(text, str) or not text.strip():
        return []

    lowered = text.lower()
    for contraction, replacement in _CONTRACTIONS.items():
        lowered = re.sub(rf"\b{re.escape(contraction)}\b", replacement, lowered)
    cleaned = re.sub(r"[^\w\s]", " ", lowered)
    return cleaned.split()


def analyze_review(text):
    tokens = preprocess_text(text)
    positive_count = 0
    negative_count = 0
    negation_words_remaining = 0

    for word in tokens:
        if word in _ADVERSATIVES:
            negation_words_remaining = 0
            continue
        if word in NEGATIONS:
            negation_words_remaining = 3
            continue

        positive = word in POSITIVE_WORDS
        negative = word in NEGATIVE_WORDS
        if positive:
            if negation_words_remaining:
                negative_count += 1
            else:
                positive_count += 1
            negation_words_remaining = 0
        elif negative:
            if negation_words_remaining:
                positive_count += 1
            else:
                negative_count += 1
            negation_words_remaining = 0
        elif negation_words_remaining:
            negation_words_remaining -= 1

    net_score = positive_count - negative_count
    sentiment = "Positive" if net_score > 0 else "Negative" if net_score < 0 else "Neutral"
    matched_words = positive_count + negative_count
    confidence = abs(net_score) / matched_words * 100 if matched_words else 0.0
    return AnalysisResult(
        positive_count=positive_count,
        negative_count=negative_count,
        net_score=net_score,
        sentiment=sentiment,
        confidence=confidence,
    )


def _timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def iter_reviews_from_file(file_path):
    """Read supported review files without loading CSV or TXT files into memory."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Review file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".txt":
        with path.open("r", encoding="utf-8-sig") as source:
            yield from source
        return

    if suffix == ".csv":
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                if not reader.fieldnames:
                    raise ValueError("The CSV file is missing a header row.")
                normalized = {str(name).strip().lower(): name for name in reader.fieldnames if name}
                column = next((normalized[name] for name in _REVIEW_COLUMNS if name in normalized), None)
                if column is None:
                    if len(reader.fieldnames) == 1:
                        column = reader.fieldnames[0]
                    else:
                        raise ValueError(
                            "Include a review column named review, review_text, text, feedback, or comment."
                        )
                for row in reader:
                    yield row.get(column)
        except csv.Error as error:
            raise ValueError(f"Unable to read the CSV file: {error}") from error
        return

    if suffix in (".xlsx", ".xls"):
        try:
            import pandas
        except ImportError as error:
            raise RuntimeError(
                "Excel support requires pandas, openpyxl, and (for .xls files) xlrd."
            ) from error
        try:
            data = pandas.read_excel(path, dtype=object)
        except ImportError as error:
            raise RuntimeError(
                "The Excel reader is unavailable. Install pandas, openpyxl, and xlrd."
            ) from error
        if data.empty and not len(data.columns):
            raise ValueError("The Excel file contains no worksheet data.")
        normalized = {str(column).strip().lower(): column for column in data.columns}
        column = next((normalized[name] for name in _REVIEW_COLUMNS if name in normalized), None)
        if column is None:
            if len(data.columns) == 1:
                column = data.columns[0]
            else:
                raise ValueError(
                    "Include a review column named review, review_text, text, feedback, or comment."
                )
        for value in data[column]:
            yield value
        return

    raise ValueError("Unsupported file format. Choose a CSV, Excel (.xlsx/.xls), or TXT file.")


class SentimentDatabase:
    def __init__(self, database_path, export_path=None):
        self.database_path = Path(database_path)
        self.export_path = Path(export_path) if export_path else self.database_path.with_name("gsentiment.js")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        if self.connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            self.connection.close()
            raise sqlite3.DatabaseError("SQLite foreign-key enforcement could not be enabled.")
        try:
            self._initialize_schema()
            self.export_analytics()
        except Exception:
            self.connection.close()
            raise

    def _table_columns(self, table_name):
        return {
            row["name"]
            for row in self.connection.execute(f"PRAGMA table_info({table_name})")
        }

    def _create_tables(self):
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS Table_Reviews (
                review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS Table_Analysis (
                analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id INTEGER NOT NULL UNIQUE,
                positive_count INTEGER NOT NULL,
                negative_count INTEGER NOT NULL,
                net_score INTEGER NOT NULL,
                sentiment TEXT NOT NULL CHECK (sentiment IN ('Positive', 'Negative', 'Neutral')),
                analyzed_at TEXT NOT NULL,
                FOREIGN KEY (review_id) REFERENCES Table_Reviews(review_id) ON DELETE CASCADE
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS Table_Datasets (
                dataset_id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_name TEXT NOT NULL,
                total_reviews INTEGER NOT NULL,
                positive_count INTEGER NOT NULL,
                negative_count INTEGER NOT NULL,
                imported_at TEXT NOT NULL
            )
            """
        )

    def _initialize_schema(self):
        review_columns = self._table_columns("Table_Reviews")
        analysis_columns = self._table_columns("Table_Analysis")
        required_review_columns = {"review_id", "raw_text", "created_at"}
        required_analysis_columns = {
            "analysis_id", "review_id", "positive_count", "negative_count",
            "net_score", "sentiment", "analyzed_at",
        }
        if required_review_columns.issubset(review_columns) and required_analysis_columns.issubset(analysis_columns):
            with self.connection:
                self._create_tables()
                self._create_compatibility_view()
            return

        with self.connection:
            self._drop_analysis_view()
            existing_tables = {
                row["name"]
                for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if "Table_Analysis" in existing_tables:
                self.connection.execute("ALTER TABLE Table_Analysis RENAME TO _legacy_Table_Analysis")
            if "Table_Reviews" in existing_tables:
                self.connection.execute("ALTER TABLE Table_Reviews RENAME TO _legacy_Table_Reviews")
            self._create_tables()
            self._migrate_legacy_reviews()
            self._migrate_legacy_analyses()
            self.connection.execute("DROP TABLE IF EXISTS _legacy_Table_Analysis")
            self.connection.execute("DROP TABLE IF EXISTS _legacy_Table_Reviews")
            self._create_compatibility_view()

    def _drop_analysis_view(self):
        row = self.connection.execute(
            "SELECT type FROM sqlite_master WHERE name = 'analysis'"
        ).fetchone()
        if row and row["type"] == "view":
            self.connection.execute("DROP VIEW analysis")

    def _create_compatibility_view(self):
        self._drop_analysis_view()
        self.connection.execute(
            """
            CREATE VIEW analysis AS
            SELECT analysis_id AS id, review_id, positive_count, negative_count,
                   net_score, sentiment, analyzed_at
            FROM Table_Analysis
            """
        )

    def _migrate_legacy_reviews(self):
        if not self._table_columns("_legacy_Table_Reviews"):
            return
        columns = self._table_columns("_legacy_Table_Reviews")
        id_column = "review_id" if "review_id" in columns else "id"
        text_column = "raw_text" if "raw_text" in columns else "review"
        date_column = "created_at" if "created_at" in columns else "date_time"
        if id_column not in columns or text_column not in columns:
            raise sqlite3.DatabaseError("Cannot migrate Table_Reviews: required review fields are missing.")
        date_expression = f'"{date_column}"' if date_column in columns else "NULL"
        rows = self.connection.execute(
            f'SELECT "{id_column}", "{text_column}", {date_expression} FROM _legacy_Table_Reviews'
        ).fetchall()
        self.connection.executemany(
            "INSERT INTO Table_Reviews (review_id, raw_text, created_at) VALUES (?, ?, ?)",
            [
                (row[0], row[1] or "", row[2] or _timestamp())
                for row in rows
            ],
        )

    def _migrate_legacy_analyses(self):
        columns = self._table_columns("_legacy_Table_Analysis")
        if not columns:
            return
        if "review_id" not in columns:
            raise sqlite3.DatabaseError("Cannot migrate Table_Analysis: review_id is missing.")
        id_column = "analysis_id" if "analysis_id" in columns else "id"
        date_column = "analyzed_at" if "analyzed_at" in columns else None
        date_expression = f'"{date_column}"' if date_column else "NULL"
        rows = self.connection.execute(
            f'SELECT "{id_column}", review_id, {date_expression} '
            "FROM _legacy_Table_Analysis ORDER BY " + f'"{id_column}"'
        ).fetchall()
        existing_review_ids = {
            row["review_id"] for row in self.connection.execute("SELECT review_id FROM Table_Reviews")
        }
        migrated_review_ids = set()
        insert_sql = """
            INSERT INTO Table_Analysis
                (analysis_id, review_id, positive_count, negative_count, net_score, sentiment, analyzed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        for row in rows:
            review_id = row[1]
            if review_id not in existing_review_ids:
                raise sqlite3.IntegrityError(
                    f"Cannot migrate analysis {row[0]}: review {review_id} does not exist."
                )
            if review_id in migrated_review_ids:
                continue
            review = self.connection.execute(
                "SELECT raw_text FROM Table_Reviews WHERE review_id = ?", (review_id,)
            ).fetchone()
            result = analyze_review(review["raw_text"])
            self.connection.execute(
                insert_sql,
                (
                    row[0],
                    review_id,
                    result.positive_count,
                    result.negative_count,
                    result.net_score,
                    result.sentiment,
                    row[2] or _timestamp(),
                ),
            )
            migrated_review_ids.add(review_id)

    def add_review(self, raw_text):
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise ValueError("Review text must not be empty.")
        review = raw_text.strip()
        result = analyze_review(review)
        timestamp = _timestamp()
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO Table_Reviews (raw_text, created_at) VALUES (?, ?) RETURNING review_id",
                (review, timestamp),
            )
            review_id = cursor.fetchone()["review_id"]
            self.connection.execute(
                """
                INSERT INTO Table_Analysis
                    (review_id, positive_count, negative_count, net_score, sentiment, analyzed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    result.positive_count,
                    result.negative_count,
                    result.net_score,
                    result.sentiment,
                    timestamp,
                ),
            )
        self.export_analytics()
        return review_id, result

    def add_reviews(self, reviews, batch_size=500, dataset_name=None):
        inserted = 0
        skipped = 0
        seen = {
            " ".join(str(row["raw_text"]).split()).casefold()
            for row in self.connection.execute("SELECT raw_text FROM Table_Reviews")
        }
        dataset_seen = set()
        batch = []
        dataset_total = 0
        dataset_positive = 0
        dataset_negative = 0

        def persist_batch(items):
            nonlocal inserted
            analysis_rows = []
            for text in items:
                result = analyze_review(text)
                timestamp = _timestamp()
                cursor = self.connection.execute(
                    "INSERT INTO Table_Reviews (raw_text, created_at) VALUES (?, ?) RETURNING review_id",
                    (text, timestamp),
                )
                review_id = cursor.fetchone()["review_id"]
                analysis_rows.append(
                    (
                        review_id,
                        result.positive_count,
                        result.negative_count,
                        result.net_score,
                        result.sentiment,
                        timestamp,
                    )
                )
            self.connection.executemany(
                """
                INSERT INTO Table_Analysis
                    (review_id, positive_count, negative_count, net_score, sentiment, analyzed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                analysis_rows,
            )
            inserted += len(items)

        if batch_size < 1:
            raise ValueError("batch_size must be greater than zero.")
        with self.connection:
            for value in reviews:
                if not isinstance(value, str) or not value.strip():
                    skipped += 1
                    continue
                text = value.strip()
                duplicate_key = " ".join(text.split()).casefold()
                if dataset_name is not None:
                    if duplicate_key in dataset_seen:
                        skipped += 1
                        continue
                    dataset_seen.add(duplicate_key)
                    result = analyze_review(text)
                    dataset_total += 1
                    if result.sentiment == "Positive":
                        dataset_positive += 1
                    elif result.sentiment == "Negative":
                        dataset_negative += 1
                if duplicate_key in seen:
                    skipped += 1
                    continue
                seen.add(duplicate_key)
                batch.append(text)
                if len(batch) >= batch_size:
                    persist_batch(batch)
                    batch = []
            if batch:
                persist_batch(batch)
            if dataset_name is not None and dataset_total:
                self.connection.execute(
                    """
                    INSERT INTO Table_Datasets
                        (dataset_name, total_reviews, positive_count, negative_count, imported_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        Path(dataset_name).name,
                        dataset_total,
                        dataset_positive,
                        dataset_negative,
                        _timestamp(),
                    ),
                )
        self.export_analytics()
        return inserted, skipped

    def dataset_summary(self, limit=100):
        return self.connection.execute(
            """
            SELECT dataset_name, total_reviews, positive_count, negative_count, imported_at
            FROM Table_Datasets
            ORDER BY dataset_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def delete_all(self):
        with self.connection:
            self.connection.execute("DELETE FROM Table_Analysis")
            self.connection.execute("DELETE FROM Table_Reviews")
            self.connection.execute("DELETE FROM Table_Datasets")
        self.export_analytics()

    def analytics(self):
        grouped_rows = self.connection.execute(
            """
            WITH grouped AS (
                SELECT sentiment, COUNT(*) AS review_count
                FROM Table_Analysis
                GROUP BY sentiment
            ),
            total AS (
                SELECT COUNT(*) AS total_count
                FROM Table_Analysis
            )
            SELECT grouped.sentiment, grouped.review_count, total.total_count,
                   ROUND(grouped.review_count * 100.0 / NULLIF(total.total_count, 0), 2)
                       AS percentage
            FROM grouped
            CROSS JOIN total
            """
        ).fetchall()
        counts = {sentiment.lower(): 0 for sentiment in SENTIMENTS}
        percentages = {sentiment.lower(): 0.0 for sentiment in SENTIMENTS}
        for row in grouped_rows:
            counts[row["sentiment"].lower()] = row["review_count"]
            percentages[row["sentiment"].lower()] = row["percentage"]
        total = grouped_rows[0]["total_count"] if grouped_rows else 0
        return {"total": total, "counts": counts, "percentages": percentages}

    def recent_reviews(self, limit=8):
        return self.connection.execute(
            """
            SELECT r.raw_text, a.sentiment, r.created_at
            FROM Table_Reviews AS r
            JOIN Table_Analysis AS a ON a.review_id = r.review_id
            ORDER BY r.review_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def review_length_distribution(self):
        return self.connection.execute(
            """
            SELECT a.sentiment,
                   CASE
                       WHEN LENGTH(r.raw_text) >= 1000 THEN 1000
                       ELSE (LENGTH(r.raw_text) / 50) * 50
                   END AS length_bucket,
                   COUNT(*) AS review_count
            FROM Table_Reviews AS r
            JOIN Table_Analysis AS a ON a.review_id = r.review_id
            GROUP BY a.sentiment, length_bucket
            ORDER BY a.sentiment, length_bucket
            """
        ).fetchall()

    def review_lengths_by_sentiment(self):
        return self.connection.execute(
            """
            SELECT a.sentiment, LENGTH(r.raw_text) AS review_length
            FROM Table_Reviews AS r
            JOIN Table_Analysis AS a ON a.review_id = r.review_id
            ORDER BY a.sentiment, review_length
            """
        ).fetchall()

    def export_analytics(self, analytics=None):
        summary = analytics if analytics is not None else self.analytics()
        data = {
            "labels": list(SENTIMENTS),
            "values": [summary["counts"][sentiment.lower()] for sentiment in SENTIMENTS],
            "total": summary["total"],
            "percentages": summary["percentages"],
        }
        serialized = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
        serialized = serialized.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        contents = f"window.sentimentData = {serialized};\nwindow.dispatchEvent(new Event('sentiment-data-updated'));\n"
        temporary_path = self.export_path.with_name(self.export_path.name + ".tmp")
        try:
            self.export_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(contents, encoding="utf-8")
            temporary_path.replace(self.export_path)
        except OSError as error:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise AnalyticsExportError(
                f"Could not update {self.export_path}: {error}"
            ) from error
        return data

    def close(self):
        self.connection.close()
