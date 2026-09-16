import os
import re
import json
import time
import html
import hashlib
import logging
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask

from groq import Groq

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Telegram channel ID.
# Example:
# CHANNEL_ID=-1001234567890
CHANNEL_ID = os.getenv("CHANNEL_ID", "")

# Admin Telegram IDs:
# ADMIN_IDS=123456789,987654321
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

PORT = int(os.getenv("PORT", "8000"))

DB_PATH = os.getenv("DB_PATH", "quizbot.db")

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
PDF_DIR = DATA_DIR / "pdfs"

DATA_DIR.mkdir(parents=True, exist_ok=True)
PDF_DIR.mkdir(parents=True, exist_ok=True)


# Groq model can be changed through Koyeb environment variable.
GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "llama-3.3-70b-versatile"
)

REQUEST_TIMEOUT = 25

QUIZ_DEFAULT_COUNT = 10

# Negative marking:
NEGATIVE_MARK = 0.25


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("quizbot")


# =========================================================
# INTERNET SOURCES
# =========================================================

INTERNET_SOURCES = [
    {
        "name": "RajRAS",
        "url": "https://rajras.in/hi/ras/mains/books/",
        "type": "reference",
    },
    {
        "name": "RBSE Official",
        "url": "https://rajeduboard.rajasthan.gov.in/books/index.htm",
        "type": "official_reference",
    },
    {
        "name": "Samyak IAS RBSE Books",
        "url": "https://samyakias.com/samyak/rbse-books.php",
        "type": "reference",
    },
    {
        "name": "NCERT Books Guru",
        "url": "https://www-ncertbooks-guru.translate.goog/rbse-books-pdf/?_x_tr_sl=en&_x_tr_tl=hi&_x_tr_hl=hi&_x_tr_pto=tc",
        "type": "reference",
    },
    {
        "name": "Online2Study India GK",
        "url": "https://www.online2study.in/2020/01/indiagkpdf.html",
        "type": "reference",
    },
]


# =========================================================
# GLOBAL STATE
# =========================================================

DB_LOCK = threading.Lock()

ACTIVE_QUIZZES = {}

# Structure:
#
# ACTIVE_QUIZZES[user_id] = {
#     "questions": [...],
#     "index": 0,
#     "score": 0,
#     "correct": 0,
#     "wrong": 0,
#     "skipped": 0,
#     "started_at": timestamp
# }


# =========================================================
# DATABASE
# =========================================================

def db():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    return conn


def init_db():

    with DB_LOCK:

        conn = db()

        conn.executescript(
            """

            CREATE TABLE IF NOT EXISTS questions (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                question TEXT NOT NULL,

                option_a TEXT NOT NULL,
                option_b TEXT NOT NULL,
                option_c TEXT NOT NULL,
                option_d TEXT NOT NULL,

                correct_option INTEGER NOT NULL,

                explanation TEXT DEFAULT '',

                exam TEXT DEFAULT 'General',
                subject TEXT DEFAULT 'General',

                source_type TEXT DEFAULT 'manual',
                source_name TEXT DEFAULT '',
                source_url TEXT DEFAULT '',

                question_hash TEXT UNIQUE NOT NULL,

                active INTEGER DEFAULT 1,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP

            );


            CREATE TABLE IF NOT EXISTS quiz_history (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                question_id INTEGER NOT NULL,

                answered_at TEXT DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(user_id, question_id),

                FOREIGN KEY(question_id)
                    REFERENCES questions(id)
                    ON DELETE CASCADE

            );


            CREATE TABLE IF NOT EXISTS users (

                user_id INTEGER PRIMARY KEY,

                username TEXT DEFAULT '',

                first_name TEXT DEFAULT '',

                total_quizzes INTEGER DEFAULT 0,

                total_questions INTEGER DEFAULT 0,

                correct_answers INTEGER DEFAULT 0,

                wrong_answers INTEGER DEFAULT 0,

                skipped_answers INTEGER DEFAULT 0,

                score REAL DEFAULT 0,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                updated_at TEXT DEFAULT CURRENT_TIMESTAMP

            );


            CREATE TABLE IF NOT EXISTS pdf_files (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                telegram_file_id TEXT UNIQUE NOT NULL,

                file_unique_id TEXT DEFAULT '',

                file_name TEXT DEFAULT '',

                file_size INTEGER DEFAULT 0,

                channel_id TEXT DEFAULT '',

                message_id INTEGER DEFAULT 0,

                caption TEXT DEFAULT '',

                local_path TEXT DEFAULT '',

                created_at TEXT DEFAULT CURRENT_TIMESTAMP

            );


            CREATE TABLE IF NOT EXISTS sources (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT UNIQUE NOT NULL,

                url TEXT NOT NULL,

                source_type TEXT DEFAULT 'reference',

                enabled INTEGER DEFAULT 1,

                last_crawled TEXT DEFAULT '',

                created_at TEXT DEFAULT CURRENT_TIMESTAMP

            );


            CREATE INDEX IF NOT EXISTS idx_questions_exam
            ON questions(exam);


            CREATE INDEX IF NOT EXISTS idx_questions_subject
            ON questions(subject);


            CREATE INDEX IF NOT EXISTS idx_questions_hash
            ON questions(question_hash);


            CREATE INDEX IF NOT EXISTS idx_history_user
            ON quiz_history(user_id);

            """
        )

        for source in INTERNET_SOURCES:

            conn.execute(
                """
                INSERT OR IGNORE INTO sources
                (name, url, source_type)
                VALUES (?, ?, ?)
                """,
                (
                    source["name"],
                    source["url"],
                    source["type"],
                )
            )

        conn.commit()
        conn.close()


# =========================================================
# TEXT NORMALIZATION
# =========================================================

def normalize_text(text: str) -> str:

    if not text:
        return ""

    text = html.unescape(text)

    text = text.lower()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    text = re.sub(
        r"[^\w\s\u0900-\u097f]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def question_hash(question, options):

    raw = normalize_text(question)

    for option in options:
        raw += "|" + normalize_text(option)

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# =========================================================
# USER
# =========================================================

def ensure_user(user):

    if not user:
        return

    with DB_LOCK:

        conn = db()

        conn.execute(
            """
            INSERT INTO users
            (
                user_id,
                username,
                first_name
            )
            VALUES (?, ?, ?)

            ON CONFLICT(user_id)
            DO UPDATE SET

                username=excluded.username,
                first_name=excluded.first_name,
                updated_at=CURRENT_TIMESTAMP

            """,
            (
                user.id,
                user.username or "",
                user.first_name or "",
            )
        )

        conn.commit()
        conn.close()


# =========================================================
# QUESTION INSERT
# =========================================================

def add_question(
    question,
    options,
    correct_option,
    explanation="",
    exam="General",
    subject="General",
    source_type="manual",
    source_name="",
    source_url="",
):

    if len(options) != 4:
        return False, "Exactly 4 options required."

    if correct_option not in [0, 1, 2, 3]:
        return False, "Correct option must be 0-3."

    question = question.strip()

    if not question:
        return False, "Question empty."

    q_hash = question_hash(
        question,
        options
    )

    with DB_LOCK:

        conn = db()

        try:

            conn.execute(
                """
                INSERT INTO questions
                (
                    question,
                    option_a,
                    option_b,
                    option_c,
                    option_d,
                    correct_option,
                    explanation,
                    exam,
                    subject,
                    source_type,
                    source_name,
                    source_url,
                    question_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question,
                    options[0],
                    options[1],
                    options[2],
                    options[3],
                    correct_option,
                    explanation,
                    exam,
                    subject,
                    source_type,
                    source_name,
                    source_url,
                    q_hash,
                )
            )

            conn.commit()

            return True, "inserted"

        except sqlite3.IntegrityError:

            return False, "duplicate"

        finally:

            conn.close()


# =========================================================
# QUESTION FETCH
# =========================================================

def get_quiz_questions(
    user_id,
    count=10,
    exam=None,
    subject=None
):

    conn = db()

    conditions = [
        "q.active = 1",
        """
        q.id NOT IN (
            SELECT question_id
            FROM quiz_history
            WHERE user_id = ?
        )
        """
    ]

    params = [user_id]

    if exam:
        conditions.append(
            "q.exam = ?"
        )
        params.append(exam)

    if subject:
        conditions.append(
            "q.subject = ?"
        )
        params.append(subject)

    sql = f"""
        SELECT q.*
        FROM questions q
        WHERE {" AND ".join(conditions)}
        ORDER BY RANDOM()
        LIMIT ?
    """

    params.append(count)

    rows = conn.execute(
        sql,
        params
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


# =========================================================
# MARK QUESTION USED
# =========================================================

def mark_question_used(
    user_id,
    question_id
):

    with DB_LOCK:

        conn = db()

        conn.execute(
            """
            INSERT OR IGNORE INTO quiz_history
            (
                user_id,
                question_id
            )
            VALUES (?, ?)
            """,
            (
                user_id,
                question_id
            )
        )

        conn.commit()
        conn.close()


# =========================================================
# RESET USER HISTORY
# =========================================================

def reset_user_history(user_id):

    with DB_LOCK:

        conn = db()

        conn.execute(
            """
            DELETE FROM quiz_history
            WHERE user_id = ?
            """,
            (user_id,)
        )

        conn.commit()
        conn.close()


# =========================================================
# STATS
# =========================================================

def get_stats(user_id):

    conn = db()

    row = conn.execute(
        """
        SELECT *
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    used = conn.execute(
        """
        SELECT COUNT(*)
        FROM quiz_history
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()[0]

    total_questions = conn.execute(
        """
        SELECT COUNT(*)
        FROM questions
        WHERE active = 1
        """
    ).fetchone()[0]

    conn.close()

    if not row:

        return {
            "total_quizzes": 0,
            "total_questions": 0,
            "correct": 0,
            "wrong": 0,
            "skipped": 0,
            "score": 0,
            "used": used,
            "available": total_questions,
        }

    return {
        "total_quizzes": row["total_quizzes"],
        "total_questions": row["total_questions"],
        "correct": row["correct_answers"],
        "wrong": row["wrong_answers"],
        "skipped": row["skipped_answers"],
        "score": row["score"],
        "used": used,
        "available": total_questions,
    }


# =========================================================
# UPDATE USER STATS
# =========================================================

def update_user_stats(
    user_id,
    total,
    correct,
    wrong,
    skipped,
    score
):

    with DB_LOCK:

        conn = db()

        conn.execute(
            """
            UPDATE users

            SET
                total_quizzes =
                    total_quizzes + 1,

                total_questions =
                    total_questions + ?,

                correct_answers =
                    correct_answers + ?,

                wrong_answers =
                    wrong_answers + ?,

                skipped_answers =
                    skipped_answers + ?,

                score =
                    score + ?,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE user_id = ?

            """,
            (
                total,
                correct,
                wrong,
                skipped,
                score,
                user_id
            )
        )

        conn.commit()
        conn.close()


# =========================================================
# ADMIN CHECK
# =========================================================

def is_admin(user_id):

    return user_id in ADMIN_IDS


# =========================================================
# PDF SYNC
# =========================================================

async def channel_pdf_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.channel_post

    if not message:
        return

    if CHANNEL_ID:

        try:

            expected = int(CHANNEL_ID)

            if message.chat.id != expected:
                return

        except ValueError:
            pass

    if not message.document:
        return

    document = message.document

    filename = (
        document.file_name
        or f"{document.file_unique_id}.pdf"
    )

    if not filename.lower().endswith(".pdf"):
        return

    with DB_LOCK:

        conn = db()

        existing = conn.execute(
            """
            SELECT id
            FROM pdf_files
            WHERE telegram_file_id = ?
            """,
            (document.file_id,)
        ).fetchone()

        if existing:

            conn.close()

            logger.info(
                "PDF already synced: %s",
                filename
            )

            return

        conn.execute(
            """
            INSERT INTO pdf_files
            (
                telegram_file_id,
                file_unique_id,
                file_name,
                file_size,
                channel_id,
                message_id,
                caption
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document.file_id,
                document.file_unique_id,
                filename,
                document.file_size or 0,
                str(message.chat.id),
                message.message_id,
                message.caption or "",
            )
        )

        conn.commit()
        conn.close()

    try:

        tg_file = await context.bot.get_file(
            document.file_id
        )

        safe_name = re.sub(
            r"[^a-zA-Z0-9._-]",
            "_",
            filename
        )

        destination = (
            PDF_DIR / safe_name
        )

        await tg_file.download_to_drive(
            custom_path=str(destination)
        )

        with DB_LOCK:

            conn = db()

            conn.execute(
                """
                UPDATE pdf_files

                SET local_path = ?

                WHERE telegram_file_id = ?

                """,
                (
                    str(destination),
                    document.file_id
                )
            )

            conn.commit()
            conn.close()

        logger.info(
            "PDF synced: %s",
            destination
        )

    except Exception:

        logger.exception(
            "PDF download failed"
        )


# =========================================================
# WEB FETCH
# =========================================================

def fetch_web_page(url):

    headers = {
        "User-Agent":
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/131 Safari/537.36"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.text


# =========================================================
# EXTRACT PAGE TEXT
# =========================================================

def extract_page_text(
    html_content,
    max_chars=18000
):

    soup = BeautifulSoup(
        html_content,
        "html.parser"
    )

    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "footer",
            "nav"
        ]
    ):
        tag.decompose()

    text = soup.get_text(
        separator="\n"
    )

    lines = []

    for line in text.splitlines():

        line = re.sub(
            r"\s+",
            " ",
            line
        ).strip()

        if len(line) >= 3:
            lines.append(line)

    text = "\n".join(lines)

    return text[:max_chars]


# =========================================================
# SOURCE CRAWLER
# =========================================================

def crawl_source(
    source_name
):

    conn = db()

    source = conn.execute(
        """
        SELECT *
        FROM sources
        WHERE name = ?
        AND enabled = 1
        """,
        (source_name,)
    ).fetchone()

    conn.close()

    if not source:
      
