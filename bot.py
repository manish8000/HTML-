# ============================================================
# TELEGRAM QUIZ BOT
# PART 1/4
# Config + Database + Question Management
# ============================================================

import os
import re
import json
import time
import uuid
import html
import hashlib
import logging
import sqlite3
import threading
import asyncio
from pathlib import Path
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from flask import Flask

from groq import Groq

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    TypeHandler,
    filters,
)


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().lstrip("-").isdigit()
}

PORT = int(os.getenv("PORT", "8000"))

DB_PATH = os.getenv(
    "DB_PATH",
    "quizbot.db"
)

DATA_DIR = Path(
    os.getenv(
        "DATA_DIR",
        "data"
    )
)

PDF_DIR = DATA_DIR / "pdfs"

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)

PDF_DIR.mkdir(
    parents=True,
    exist_ok=True
)

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-120b"
)

REQUEST_TIMEOUT = int(
    os.getenv(
        "REQUEST_TIMEOUT",
        "30"
    )
)

DEFAULT_QUIZ_COUNT = int(
    os.getenv(
        "DEFAULT_QUIZ_COUNT",
        "10"
    )
)

DEFAULT_NEGATIVE_MARK = float(
    os.getenv(
        "NEGATIVE_MARK",
        "0.25"
    )
)

MAX_IMPORT_QUESTIONS = int(
    os.getenv(
        "MAX_IMPORT_QUESTIONS",
        "500"
    )
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    )
)

logger = logging.getLogger(
    "quizbot"
)


# ============================================================
# GLOBAL STATE
# ============================================================

DB_LOCK = threading.RLock()

ACTIVE_QUIZZES = {}

PENDING = {}

QUIZ_CREATE = {}

CLONE_QUEUE = []

CLONE_LOCK = threading.Lock()


# ============================================================
# FLASK HEALTH SERVER
# ============================================================

health_app = Flask(__name__)


@health_app.route("/")
def health():
    return "Quiz Bot is running", 200


@health_app.route("/health")
def health_check():
    return {
        "status": "ok",
        "service": "telegram-quiz-bot"
    }, 200


def run_health_server():
    try:
        health_app.run(
            host="0.0.0.0",
            port=PORT,
            debug=False,
            use_reloader=False
        )
    except Exception as e:
        logger.exception(
            "Health server error: %s",
            e
        )


# ============================================================
# INTERNET SOURCES
# ============================================================

DEFAULT_SOURCES = [

    (
        "rajras",
        "https://www.rajras.in/",
    ),

    (
        "rbse",
        "https://rajeduboard.rajasthan.gov.in/",
    ),

    (
        "samyak_rbse",
        "https://www.samyakias.com/",
    ),

    (
        "ncert",
        "https://ncert.nic.in/",
    ),

    (
        "online2study",
        "https://www.online2study.in/",
    ),
]


# ============================================================
# DATABASE CONNECTION
# ============================================================

def db():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA journal_mode=WAL"
    )

    conn.execute(
        "PRAGMA foreign_keys=ON"
    )

    return conn


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_db():

    with DB_LOCK:

        conn = db()

        conn.executescript(
            """

            CREATE TABLE IF NOT EXISTS users (

                id INTEGER PRIMARY KEY,

                username TEXT,

                first_name TEXT,

                last_name TEXT,

                questions_answered INTEGER
                    DEFAULT 0,

                correct_answers INTEGER
                    DEFAULT 0,

                wrong_answers INTEGER
                    DEFAULT 0,

                skipped_questions INTEGER
                    DEFAULT 0,

                score REAL
                    DEFAULT 0,

                quizzes_completed INTEGER
                    DEFAULT 0,

                created_at TEXT,

                updated_at TEXT

            );


            CREATE TABLE IF NOT EXISTS questions (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                question TEXT NOT NULL,

                option_a TEXT NOT NULL,

                option_b TEXT NOT NULL,

                option_c TEXT NOT NULL,

                option_d TEXT NOT NULL,

                answer TEXT NOT NULL,

                explanation TEXT,

                exam TEXT,

                subject TEXT,

                source TEXT,

                hash TEXT UNIQUE,

                active INTEGER DEFAULT 1,

                created_at TEXT,

                updated_at TEXT

            );


            CREATE TABLE IF NOT EXISTS quiz_history (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                question_id INTEGER NOT NULL,

                selected_answer TEXT,

                correct INTEGER DEFAULT 0,

                score REAL DEFAULT 0,

                answered_at TEXT,

                UNIQUE (
                    user_id,
                    question_id
                ),

                FOREIGN KEY(user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE,

                FOREIGN KEY(question_id)
                    REFERENCES questions(id)
                    ON DELETE CASCADE

            );


            CREATE TABLE IF NOT EXISTS quizzes (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT NOT NULL,

                description TEXT,

                created_by INTEGER,

                active INTEGER DEFAULT 1,

                created_at TEXT,

                updated_at TEXT

            );


            CREATE TABLE IF NOT EXISTS quiz_questions (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                quiz_id INTEGER NOT NULL,

                question_id INTEGER NOT NULL,

                position INTEGER DEFAULT 0,

                UNIQUE (
                    quiz_id,
                    question_id
                ),

                FOREIGN KEY(quiz_id)
                    REFERENCES quizzes(id)
                    ON DELETE CASCADE,

                FOREIGN KEY(question_id)
                    REFERENCES questions(id)
                    ON DELETE CASCADE

            );


            CREATE TABLE IF NOT EXISTS pdf_files (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                filename TEXT,

                path TEXT,

                imported_by INTEGER,

                question_count INTEGER DEFAULT 0,

                created_at TEXT

            );


            CREATE TABLE IF NOT EXISTS sources (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT UNIQUE,

                url TEXT,

                enabled INTEGER DEFAULT 1,

                created_at TEXT

            );


            CREATE TABLE IF NOT EXISTS settings (

                key TEXT PRIMARY KEY,

                value TEXT

            );


            CREATE TABLE IF NOT EXISTS import_jobs (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER,

                filename TEXT,

                status TEXT,

                question_count INTEGER DEFAULT 0,

                error TEXT,

                created_at TEXT,

                updated_at TEXT

            );


            CREATE INDEX IF NOT EXISTS idx_questions_active
            ON questions(active);


            CREATE INDEX IF NOT EXISTS idx_questions_exam
            ON questions(exam);


            CREATE INDEX IF NOT EXISTS idx_questions_subject
            ON questions(subject);


            CREATE INDEX IF NOT EXISTS idx_history_user
            ON quiz_history(user_id);


            CREATE INDEX IF NOT EXISTS idx_history_question
            ON quiz_history(question_id);


            CREATE INDEX IF NOT EXISTS idx_quiz_questions_quiz
            ON quiz_questions(quiz_id);

            """
        )


        now = utcnow()

        for name, url in DEFAULT_SOURCES:

            conn.execute(
                """
                INSERT OR IGNORE INTO sources
                (
                    name,
                    url,
                    enabled,
                    created_at
                )
                VALUES (?, ?, 1, ?)
                """,
                (
                    name,
                    url,
                    now
                )
            )


        conn.execute(
            """
            INSERT OR IGNORE INTO settings
            (
                key,
                value
            )
            VALUES (?, ?)
            """,
            (
                "negative_mark",
                str(DEFAULT_NEGATIVE_MARK)
            )
        )


        conn.commit()

        conn.close()

        logger.info(
            "Database initialized"
        )


# ============================================================
# TIME
# ============================================================

def utcnow():

    return datetime.now(
        timezone.utc
    ).isoformat()


# ============================================================
# SETTINGS
# ============================================================

def get_setting(
    key,
    default=None
):

    with DB_LOCK:

        conn = db()

        row = conn.execute(
            """
            SELECT value
            FROM settings
            WHERE key = ?
            """,
            (key,)
        ).fetchone()

        conn.close()

    if not row:
        return default

    return row["value"]


def set_setting(
    key,
    value
):

    with DB_LOCK:

        conn = db()

        conn.execute(
            """
            INSERT INTO settings
            (
                key,
                value
            )
            VALUES (?, ?)

            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value
            """,
            (
                key,
                str(value)
            )
        )

        conn.commit()

        conn.close()


def get_negative_mark():

    value = get_setting(
        "negative_mark",
        DEFAULT_NEGATIVE_MARK
    )

    try:
        return float(value)

    except Exception:
        return DEFAULT_NEGATIVE_MARK


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(text):

    if text is None:
        return ""

    text = str(text)

    text = text.replace(
        "\u200b",
        ""
    )

    text = text.replace(
        "\xa0",
        " "
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip().lower()


# ============================================================
# QUESTION HASH
# ============================================================

def question_hash(
    question,
    option_a,
    option_b,
    option_c,
    option_d
):

    raw = "|".join(
        [
            normalize_text(question),
            normalize_text(option_a),
            normalize_text(option_b),
            normalize_text(option_c),
            normalize_text(option_d),
        ]
    )

    return hashlib.sha256(
        raw.encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# CLEAN OPTION
# ============================================================
# ============================================================
# PART 2/4
# Question Validation + Question Management
# Groq + Web Crawl + PDF/TXT Import
# ============================================================


# ============================================================
# CLEAN OPTION
# ============================================================

def clean_option(option):
    """
    Option text को साफ करता है।
    A) / A. / (A) जैसे prefixes हटाता है।
    """

    if option is None:
        return ""

    option = str(option).strip()

    option = re.sub(
        r"^\s*[\(\[]?[A-Da-d1-4][\)\].:\-]\s*",
        "",
        option
    )

    option = re.sub(
        r"^\s*Option\s*[A-Da-d1-4]\s*[:.)-]\s*",
        "",
        option,
        flags=re.IGNORECASE
    )

    return option.strip()


# ============================================================
# VALIDATE QUESTION PAYLOAD
# ============================================================

def valid_question_payload(data):
    """
    Question dictionary validate करता है।
    """

    if not isinstance(data, dict):
        return False

    required = [
        "question",
        "option_a",
        "option_b",
        "option_c",
        "option_d",
        "answer",
    ]

    for key in required:

        value = data.get(key)

        if value is None:
            return False

        if not str(value).strip():
            return False

    answer = str(
        data.get("answer")
    ).strip().upper()

    answer = answer.replace(
        "OPTION ",
        ""
    )

    answer = answer.replace(
        "(",
        ""
    ).replace(
        ")",
        ""
    )

    answer = answer.replace(
        ".",
        ""
    ).replace(
        ":",
        ""
    )

    if answer not in {
        "A",
        "B",
        "C",
        "D",
    }:
        return False

    options = [
        clean_option(data.get("option_a")),
        clean_option(data.get("option_b")),
        clean_option(data.get("option_c")),
        clean_option(data.get("option_d")),
    ]

    if any(
        not option
        for option in options
    ):
        return False

    normalized_options = [
        normalize_text(x)
        for x in options
    ]

    if len(
        set(normalized_options)
    ) != 4:
        return False

    question = str(
        data.get("question")
    ).strip()

    if len(question) < 5:
        return False

    data["question"] = question

    data["option_a"] = options[0]
    data["option_b"] = options[1]
    data["option_c"] = options[2]
    data["option_d"] = options[3]

    data["answer"] = answer

    data["explanation"] = str(
        data.get("explanation") or ""
    ).strip()

    data["exam"] = str(
        data.get("exam") or ""
    ).strip()

    data["subject"] = str(
        data.get("subject") or ""
    ).strip()

    data["source"] = str(
        data.get("source") or ""
    ).strip()

    return True


# ============================================================
# ADD QUESTION
# ============================================================

def add_question(data):
    """
    Database में question add करता है।

    Duplicate question hash के आधार पर रोका जाता है।
    """

    if not valid_question_payload(data):
        return None, "invalid"

    q_hash = question_hash(
        data["question"],
        data["option_a"],
        data["option_b"],
        data["option_c"],
        data["option_d"],
    )

    now = utcnow()

    with DB_LOCK:

        conn = db()

        existing = conn.execute(
            """
            SELECT id
            FROM questions
            WHERE hash = ?
            LIMIT 1
            """,
            (q_hash,)
        ).fetchone()

        if existing:

            conn.close()

            return (
                existing["id"],
                "duplicate"
            )

        cursor = conn.execute(
            """
            INSERT INTO questions
            (
                question,
                option_a,
                option_b,
                option_c,
                option_d,
                answer,
                explanation,
                exam,
                subject,
                source,
                hash,
                active,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                data["question"],
                data["option_a"],
                data["option_b"],
                data["option_c"],
                data["option_d"],
                data["answer"],
                data.get("explanation", ""),
                data.get("exam", ""),
                data.get("subject", ""),
                data.get("source", ""),
                q_hash,
                now,
                now,
            )
        )

        question_id = cursor.lastrowid

        conn.commit()
        conn.close()

    return question_id, "added"


# ============================================================
# GET QUESTION
# ============================================================

def get_question(question_id):

    try:
        question_id = int(
            question_id
        )
    except Exception:
        return None

    with DB_LOCK:

        conn = db()

        row = conn.execute(
            """
            SELECT *
            FROM questions
            WHERE id = ?
            """,
            (question_id,)
        ).fetchone()

        conn.close()

    return row


# ============================================================
# GET ALL QUESTIONS
# ============================================================

def get_all_questions(
    active_only=True
):

    with DB_LOCK:

        conn = db()

        if active_only:

            rows = conn.execute(
                """
                SELECT *
                FROM questions
                WHERE active = 1
                ORDER BY id ASC
                """
            ).fetchall()

        else:

            rows = conn.execute(
                """
                SELECT *
                FROM questions
                ORDER BY id ASC
                """
            ).fetchall()

        conn.close()

    return rows


# ============================================================
# DELETE QUESTION
# ============================================================

def delete_question(
    question_id
):

    try:
        question_id = int(
            question_id
        )
    except Exception:
        return False

    with DB_LOCK:

        conn = db()

        cursor = conn.execute(
            """
            UPDATE questions
            SET active = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (
                utcnow(),
                question_id
            )
        )

        conn.commit()

        changed = (
            cursor.rowcount > 0
        )

        conn.close()

    return changed


# ============================================================
# UPDATE QUESTION
# ============================================================

def update_question(
    question_id,
    data
):

    try:
        question_id = int(
            question_id
        )
    except Exception:
        return False, "invalid_id"

    if not valid_question_payload(data):
        return False, "invalid"

    q_hash = question_hash(
        data["question"],
        data["option_a"],
        data["option_b"],
        data["option_c"],
        data["option_d"],
    )

    with DB_LOCK:

        conn = db()

        duplicate = conn.execute(
            """
            SELECT id
            FROM questions
            WHERE hash = ?
            AND id != ?
            LIMIT 1
            """,
            (
                q_hash,
                question_id
            )
        ).fetchone()

        if duplicate:

            conn.close()

            return (
                False,
                "duplicate"
            )

        cursor = conn.execute(
            """
            UPDATE questions

            SET question = ?,
                option_a = ?,
                option_b = ?,
                option_c = ?,
                option_d = ?,
                answer = ?,
                explanation = ?,
                exam = ?,
                subject = ?,
                source = ?,
                hash = ?,
                updated_at = ?

            WHERE id = ?
            """,
            (
                data["question"],
                data["option_a"],
                data["option_b"],
                data["option_c"],
                data["option_d"],
                data["answer"],
                data.get("explanation", ""),
                data.get("exam", ""),
                data.get("subject", ""),
                data.get("source", ""),
                q_hash,
                utcnow(),
                question_id,
            )
        )

        conn.commit()

        changed = (
            cursor.rowcount > 0
        )

        conn.close()

    if not changed:
        return False, "not_found"

    return True, "updated"


# ============================================================
# QUESTION SELECTION
# ============================================================

def get_quiz_questions(
    user_id,
    count=10,
    exam=None,
    subject=None,
    quiz_id=None
):
    """
    User को ऐसे questions देता है जिन्हें उसने पहले use नहीं किया।

    यही function question repetition रोकने का मुख्य हिस्सा है।
    """

    try:
        user_id = int(user_id)
    except Exception:
        return []

    try:
        count = int(count)
    except Exception:
        count = DEFAULT_QUIZ_COUNT

    count = max(
        1,
        min(count, MAX_IMPORT_QUESTIONS)
    )

    with DB_LOCK:

        conn = db()

        params = [
            user_id
        ]

        if quiz_id is not None:

            try:
                quiz_id = int(
                    quiz_id
                )
            except Exception:
                conn.close()
                return []

            query = """
                SELECT q.*
                FROM questions q
                INNER JOIN quiz_questions qq
                    ON qq.question_id = q.id
                WHERE qq.quiz_id = ?
                AND q.active = 1
                AND NOT EXISTS (
                    SELECT 1
                    FROM quiz_history h
                    WHERE h.user_id = ?
                    AND h.question_id = q.id
                )
            """

            params = [
                quiz_id,
                user_id
            ]

        else:

            query = """
                SELECT q.*
                FROM questions q
                WHERE q.active = 1

                AND NOT EXISTS (
                    SELECT 1
                    FROM quiz_history h
                    WHERE h.user_id = ?
                    AND h.question_id = q.id
                )
            """

        if exam:

            query += """
                AND LOWER(COALESCE(q.exam, ''))
                    = LOWER(?)
            """

            params.append(
                str(exam).strip()
            )

        if subject:

            query += """
                AND LOWER(COALESCE(q.subject, ''))
                    = LOWER(?)
            """

            params.append(
                str(subject).strip()
            )

        query += """
            ORDER BY RANDOM()
            LIMIT ?
        """

        params.append(
            count
        )

        rows = conn.execute(
            query,
            tuple(params)
        ).fetchall()

        conn.close()

    return rows


# ============================================================
# MARK QUESTION USED
# ============================================================

def mark_question_used(
    user_id,
    question_id,
    selected_answer="",
    correct=0,
    score=0
):
    """
    Question को user history में permanently reserve करता है।

    INSERT OR IGNORE इसलिए है ताकि double callback से
    question दोबारा history में न जाए।
    """

    try:
        user_id = int(
            user_id
        )

        question_id = int(
            question_id
        )

    except Exception:
        return False

    with DB_LOCK:

        conn = db()

        try:

            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO quiz_history
                (
                    user_id,
                    question_id,
                    selected_answer,
                    correct,
                    score,
                    answered_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    question_id,
                    selected_answer or "",
                    int(bool(correct)),
                    float(score),
                    utcnow()
                )
            )

            conn.commit()

            inserted = (
                cursor.rowcount > 0
            )

        finally:

            conn.close()

    return inserted


# ============================================================
# ENSURE USER
# ============================================================

def ensure_user(
    telegram_user
):

    if telegram_user is None:
        return False

    user_id = int(
        telegram_user.id
    )

    username = (
        telegram_user.username
        or ""
    )

    first_name = (
        telegram_user.first_name
        or ""
    )

    last_name = (
        telegram_user.last_name
        or ""
    )

    now = utcnow()

    with DB_LOCK:

        conn = db()

        conn.execute(
            """
            INSERT INTO users
            (
                id,
                username,
                first_name,
                last_name,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)

            ON CONFLICT(id)
            DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                username,
                first_name,
                last_name,
                now,
                now
            )
        )

        conn.commit()
        conn.close()

    return True


# ============================================================
# ADMIN CHECK
# ============================================================

def is_admin(
    user_id
):

    try:
        return int(
            user_id
        ) in ADMIN_IDS

    except Exception:
        return False


# ============================================================
# RESET USER HISTORY
# ============================================================

def reset_user_history(
    user_id
):

    try:
        user_id = int(
            user_id
        )
    except Exception:
        return False

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

    return True


# ============================================================
# USER STATS
# ============================================================

def get_stats(
    user_id
):

    try:
        user_id = int(
            user_id
        )
    except Exception:
        return None

    with DB_LOCK:

        conn = db()

        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
            """,
            (user_id,)
        ).fetchone()

        conn.close()

    return row


# ============================================================
# UPDATE USER STATS
# ============================================================

def update_user_stats(
    user_id,
    correct=False,
    skipped=False,
    score_delta=0
):

    try:
        user_id = int(
            user_id
        )
    except Exception:
        return False

    with DB_LOCK:

        conn = db()

        conn.execute(
            """
            INSERT OR IGNORE INTO users
            (
                id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                utcnow(),
                utcnow()
            )
        )

        conn.execute(
            """
            UPDATE users

            SET questions_answered =
                    questions_answered + ?,

                correct_answers =
                    correct_answers + ?,

                wrong_answers =
                    wrong_answers + ?,

                skipped_questions =
                    skipped_questions + ?,

                score =
                    score + ?,

                updated_at = ?

            WHERE id = ?
            """,
            (
                1 if not skipped else 0,
                1 if correct and not skipped else 0,
                1 if not correct and not skipped else 0,
                1 if skipped else 0,
                float(score_delta),
                utcnow(),
                user_id
            )
        )

        conn.commit()
        conn.close()

    return True


# ============================================================
# QUIZ COMPLETED
# ============================================================

def increment_quiz_count(
    user_id
):

    try:
        user_id = int(
            user_id
        )
    except Exception:
        return False

    with DB_LOCK:

        conn = db()

        conn.execute(
            """
            UPDATE users
            SET quizzes_completed =
                    quizzes_completed + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (
                utcnow(),
                user_id
            )
        )

        conn.commit()
        conn.close()

    return True


# ============================================================
# GROQ CLIENT
# ============================================================

groq_client = None

if GROQ_API_KEY:

    try:

        groq_client = Groq(
            api_key=GROQ_API_KEY
        )

    except Exception as e:

        logger.exception(
            "Groq initialization failed: %s",
            e
        )


# ============================================================
# EXTRACT JSON FROM GROQ RESPONSE
# ============================================================

def extract_json(
    text
):
    """
    Groq response में JSON ढूँढता है।
    """

    if not text:
        return None

    text = str(
        text
    ).strip()

    # Markdown code fence हटाएँ
    text = re.sub(
        r"```(?:json)?",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = text.replace(
        "```",
        ""
    ).strip()

    # Direct JSON
    try:

        return json.loads(
            text
        )

    except Exception:
        pass

    # JSON object/list खोजें
    candidates = []

    first_array = text.find("[")
    last_array = text.rfind("]")

    if (
        first_array >= 0
        and last_array > first_array
    ):
        candidates.append(
            text[
                first_array:
                last_array + 1
            ]
        )

    first_object = text.find("{")
    last_object = text.rfind("}")

    if (
        first_object >= 0
        and last_object > first_object
    ):
        candidates.append(
            text[
                first_object:
                last_object + 1
            ]
        )

    for candidate in candidates:

        try:

            return json.lo
            json.loads(
    candidate
)

        except Exception:
            continue

    return None


# ============================================================
# NORMALIZE GENERATED QUESTION
# ============================================================

def normalize_generated_question(
    item,
    source=""
):

    if not isinstance(item, dict):
        return None

    question = (
        item.get("question")
        or item.get("q")
        or item.get("Question")
    )

    options = item.get("options")

    if isinstance(options, list) and len(options) >= 4:

        option_a = options[0]
        option_b = options[1]
        option_c = options[2]
        option_d = options[3]

    else:

        option_a = (
            item.get("option_a")
            or item.get("a")
            or item.get("A")
        )

        option_b = (
            item.get("option_b")
            or item.get("b")
            or item.get("B")
        )

        option_c = (
            item.get("option_c")
            or item.get("c")
            or item.get("C")
        )

        option_d = (
            item.get("option_d")
            or item.get("d")
            or item.get("D")
        )

    answer = (
        item.get("answer")
        or item.get("correct_answer")
        or item.get("correct")
    )

    data = {
        "question": question,
        "option_a": option_a,
        "option_b": option_b,
        "option_c": option_c,
        "option_d": option_d,
        "answer": answer,
        "explanation": item.get(
            "explanation",
            ""
        ),
        "exam": item.get(
            "exam",
            ""
        ),
        "subject": item.get(
            "subject",
            ""
        ),
        "source": (
            item.get("source", "")
            or source
        ),
    }

    if not valid_question_payload(data):
        return None

    return data


# ============================================================
# GROQ GENERATE QUESTIONS
# ============================================================

def groq_generate_questions(
    topic,
    count=10,
    context_text="",
    source=""
):

    if groq_client is None:
        raise RuntimeError(
            "GROQ_API_KEY configured नहीं है।"
        )

    try:
        count = int(count)
    except Exception:
        count = 10

    count = max(
        1,
        min(
            count,
            MAX_IMPORT_QUESTIONS
        )
    )

    context_text = str(
        context_text or ""
    )[:30000]

    prompt = f"""
आप एक परीक्षा प्रश्न निर्माण विशेषज्ञ हैं।

विषय:
{topic}

आपको {count} अलग-अलग MCQ प्रश्न बनाने हैं।

भाषा:
हिंदी।

प्रत्येक प्रश्न में ये fields अनिवार्य हैं:

question
option_a
option_b
option_c
option_d
answer
explanation
exam
subject

नियम:

1. केवल valid MCQ बनाएं।
2. चारों options अलग होने चाहिए।
3. answer केवल A, B, C या D होना चाहिए।
4. प्रश्न factual और परीक्षा उपयोगी हों।
5. प्रश्न आपस में duplicate नहीं होने चाहिए।
6. दिए गए context का उपयोग करें।
7. कोई अतिरिक्त text न दें।
8. केवल JSON array दें।

Format:

[
  {{
    "question": "प्रश्न",
    "option_a": "विकल्प A",
    "option_b": "विकल्प B",
    "option_c": "विकल्प C",
    "option_d": "विकल्प D",
    "answer": "A",
    "explanation": "व्याख्या",
    "exam": "CET",
    "subject": "Polity"
  }}
]

Context:
{context_text}
"""

    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "आप MCQ generator हैं। "
                    "केवल valid JSON array दें।"
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.4,
        max_tokens=12000,
    )

    content = (
        response.choices[0]
        .message.content
    )

    parsed = extract_json(
        content
    )

    if isinstance(parsed, dict):

        parsed = (
            parsed.get("questions")
            or parsed.get("data")
            or []
        )

    if not isinstance(parsed, list):
        return []

    result = []
    seen_hashes = set()

    for item in parsed:

        data = normalize_generated_question(
            item,
            source=source
        )

        if not data:
            continue

        q_hash = question_hash(
            data["question"],
            data["option_a"],
            data["option_b"],
            data["option_c"],
            data["option_d"],
        )

        if q_hash in seen_hashes:
            continue

        seen_hashes.add(
            q_hash
        )

        result.append(data)

    return result
    # ============================================================
# HTTP FETCH
# ============================================================

def fetch_url(url):

    try:

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return response.text

    except Exception as e:

        logger.exception(
            "URL fetch failed: %s",
            url
        )

        return ""


# ============================================================
# HTML TO TEXT
# ============================================================

def html_to_text(
    html_content
):

    if not html_content:
        return ""

    try:

        soup = BeautifulSoup(
            html_content,
            "html.parser"
        )

        # Unwanted elements remove
        for tag in soup([
            "script",
            "style",
            "noscript",
            "svg",
            "iframe",
            "nav",
            "footer",
            "header",
        ]):

            tag.decompose()

        text = soup.get_text(
            separator="\n"
        )

        lines = []

        for line in text.splitlines():

            line = normalize_text(
                line
            )

            if line:
                lines.append(line)

        return "\n".join(lines)

    except Exception:

        logger.exception(
            "HTML extraction failed"
        )

        return ""


# ============================================================
# HTML LINKS
# ============================================================

def extract_links(
    html_content,
    base_url
):

    if not html_content:
        return []

    links = []

    try:

        soup = BeautifulSoup(
            html_content,
            "html.parser"
        )

        from urllib.parse import (
            urljoin,
            urlparse,
        )

        base_domain = urlparse(
            base_url
        ).netloc

        for tag in soup.find_all(
            "a",
            href=True
        ):

            href = tag.get(
                "href",
                ""
            ).strip()

            if not href:
                continue

            full_url = urljoin(
                base_url,
                href
            )

            parsed = urlparse(
                full_url
            )

            if parsed.scheme not in (
                "http",
                "https"
            ):
                continue

            # Same domain only
            if (
                parsed.netloc
                and parsed.netloc != base_domain
            ):
                continue

            if full_url not in links:
                links.append(
                    full_url
                )

        return links

    except Exception:

        logger.exception(
            "Link extraction failed"
        )

        return []


# ============================================================
# CRAWL SOURCE
# ============================================================

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
        raise ValueError(
            f"Source नहीं मिला: {source_name}"
        )

    base_url = source["url"]

    html_content = fetch_url(
        base_url
    )

    if not html_content:
        return {
            "source": source_name,
            "url": base_url,
            "text": "",
            "links": [],
        }

    text = html_to_text(
        html_content
    )

    links = extract_links(
        html_content,
        base_url
    )

    return {
        "source": source_name,
        "url": base_url,
        "text": text[:50000],
        "links": links[:100],
    }


# ============================================================
# CRAWL + GENERATE QUESTIONS
# ============================================================

def scrape_and_generate(
    source_name,
    topic=None,
    count=10
):

    data = crawl_source(
        source_name
    )

    source_text = data.get(
        "text",
        ""
    )

    if not source_text:
        return []

    if topic:

        generation_topic = (
            f"{topic}\n\n"
            f"Source: {source_name}"
        )

    else:

        generation_topic = (
            f"इस source की सामग्री से "
            f"परीक्षा उपयोगी MCQ बनाएं: "
            f"{source_name}"
        )

    questions = groq_generate_questions(
        topic=generation_topic,
        count=count,
        context_text=source_text,
        source=source_name,
    )

    saved = []

    for question in questions:

        try:

            question_id = add_question(
                question
            )

            if question_id:
                saved.append(
                    question_id
                )

        except Exception:

            logger.exception(
                "Failed saving scraped question"
            )

    return saved
    # ============================================================
# PDF / TXT EXTRACTION
# ============================================================

def extract_pdf_text(file_path):

    try:
        from pypdf import PdfReader

        reader = PdfReader(
            str(file_path)
        )

        pages = []

        for page in reader.pages:

            try:
                text = page.extract_text() or ""

                if text.strip():
                    pages.append(text)

            except Exception:
                continue

        return "\n".join(pages)

    except Exception:

        logger.exception(
            "PDF extraction failed: %s",
            file_path
        )

        return ""


def extract_txt_text(file_path):

    try:

        path = Path(file_path)

        # पहले UTF-8
        try:

            return path.read_text(
                encoding="utf-8"
            )

        except UnicodeDecodeError:

            pass

        # fallback encodings
        for encoding in (
            "utf-8-sig",
            "cp1252",
            "latin-1",
        ):

            try:

                return path.read_text(
                    encoding=encoding
                )

            except Exception:
                continue

        return ""

    except Exception:

        logger.exception(
            "TXT extraction failed: %s",
            file_path
        )

        return ""


# ============================================================
# SAVE PDF FILE RECORD
# ============================================================

def save_pdf_file(
    user_id,
    file_name,
    file_path
):

    conn = db()

    try:

        cursor = conn.execute(
            """
            INSERT INTO pdf_files
            (
                user_id,
                file_name,
                file_path,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                file_name,
                str(file_path),
                utcnow(),
            )
        )

        conn.commit()

        return cursor.lastrowid

    except Exception:

        logger.exception(
            "PDF record save failed"
        )

        return None

    finally:

        conn.close()


# ============================================================
# IMPORT QUESTIONS FROM TEXT
# ============================================================

def import_questions_from_text(
    text,
    source="import",
    count=None
):

    if not text:
        return []

    text = str(text)

    # Groq को बहुत बड़ा input न भेजें
    text = text[:50000]

    if count is None:

        count = DEFAULT_QUIZ_COUNT

    try:
        count = int(count)
    except Exception:
        count = DEFAULT_QUIZ_COUNT

    count = max(
        1,
        min(
            count,
            MAX_IMPORT_QUESTIONS
        )
    )

    questions = groq_generate_questions(
        topic=(
            "दिए गए अध्ययन सामग्री से "
            "महत्वपूर्ण परीक्षा उपयोगी MCQ तैयार करें।"
        ),
        count=count,
        context_text=text,
        source=source,
    )

    saved_ids = []

    for question in questions:

        try:

            question_id = add_question(
                question
            )

            if question_id:
                saved_ids.append(
                    question_id
                )

        except Exception:

            logger.exception(
                "Imported question save failed"
            )

    return saved_ids


# ============================================================
# IMPORT PDF
# ============================================================

def import_pdf(
    user_id,
    file_path,
    file_name,
    count=None
):

    text = extract_pdf_text(
        file_path
    )

    if not text.strip():
        return []

    pdf_id = save_pdf_file(
        user_id=user_id,
        file_name=file_name,
        file_path=file_path,
    )

    saved_ids = import_questions_from_text(
        text=text,
        source=file_name,
        count=count,
    )

    return saved_ids


# ============================================================
# IMPORT TXT
# ============================================================

def import_txt(
    file_path,
    file_name,
    count=None
):

    text = extract_txt_text(
        file_path
    )

    if not text.strip():
        return []

    return import_questions_from_text(
        text=text,
        source=file_name,
        count=count,
    )


# ============================================================
# QUESTION TEXT PARSER
# ============================================================

def parse_question_text(text):

    if not text:
        return None

    text = str(text).strip()

    question_match = re.search(
        r"(?:^|\n)\s*(?:Question\s*:?\s*)?"
        r"(.+?)"
        r"\n\s*A[\)\.\:]\s*(.+?)"
        r"\n\s*B[\)\.\:]\s*(.+?)"
        r"\n\s*C[\)\.\:]\s*(.+?)"
        r"\n\s*D[\)\.\:]\s*(.+?)"
        r"(?:\n|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if not question_match:
        return None

    question = question_match.group(1).strip()

    option_a = question_match.group(2).strip()
    option_b = question_match.group(3).strip()
    option_c = question_match.group(4).strip()
    option_d = question_match.group(5).strip()

    answer_match = re.search(
        r"(?:Answer|Correct\s*Answer)"
        r"\s*[:\-]?\s*"
        r"([ABCD])\b",
        text,
        re.IGNORECASE,
    )

    if not answer_match:
        return None

    answer = (
        answer_match
        .group(1)
        .upper()
    )

    explanation_match = re.search(
        r"Explanation\s*[:\-]?\s*(.+?)(?=\n\s*(?:Exam|Subject)\s*:|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    exam_match = re.search(
        r"Exam\s*[:\-]?\s*(.+?)(?=\n|$)",
        text,
        re.IGNORECASE,
    )

    subject_match = re.search(
        r"Subject\s*[:\-]?\s*(.+?)(?=\n|$)",
        text,
        re.IGNORECASE,
    )

    data = {
        "question": question,
        "option_a": option_a,
        "option_b": option_b,
        "option_c": option_c,
        "option_d": option_d,
        "answer": answer,
        "explanation": (
            explanation_match.group(1).strip()
            if explanation_match
            else ""
        ),
        "exam": (
            exam_match.group(1).strip()
            if exam_match
            else ""
        ),
        "subject": (
            subject_match.group(1).strip()
            if subject_match
            else ""
        ),
        "source": "manual",
    }

    if not valid_question_payload(data):
        return None

    return data
    # ============================================================
# QUIZ QUESTION SELECTION
# ============================================================

def get_quiz_questions(
    user_id,
    count=10,
    exam=None,
    subject=None,
    quiz_id=None
):

    try:
        count = int(count)
    except Exception:
        count = DEFAULT_QUIZ_COUNT

    count = max(1, count)

    conn = db()

    try:

        params = [user_id]

        conditions = [
            "q.active = 1",
            """
            NOT EXISTS (
                SELECT 1
                FROM quiz_history h
                WHERE h.user_id = ?
                AND h.question_id = q.id
            )
            """
        ]

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

        if quiz_id:

            conditions.append(
                """
                q.id IN (
                    SELECT question_id
                    FROM quiz_questions
                    WHERE quiz_id = ?
                )
                """
            )

            params.append(quiz_id)

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
            tuple(params)
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:

        conn.close()


# ============================================================
# MARK QUESTION AS USED
# ============================================================

def mark_question_used(
    user_id,
    question_id
):

    conn = db()

    try:

        conn.execute(
            """
            INSERT OR IGNORE INTO quiz_history
            (
                user_id,
                question_id,
                used_at
            )
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                question_id,
                utcnow(),
            )
        )

        conn.commit()

        return True

    except Exception:

        logger.exception(
            "Failed marking question used"
        )

        return False

    finally:

        conn.close()


# ============================================================
# CHECK WHETHER QUESTION WAS USED
# ============================================================

def question_was_used(
    user_id,
    question_id
):

    conn = db()

    try:

        row = conn.execute(
            """
            SELECT 1
            FROM quiz_history
            WHERE user_id = ?
            AND question_id = ?
            LIMIT 1
            """,
            (
                user_id,
                question_id,
            )
        ).fetchone()

        return row is not None

    finally:

        conn.close()


# ============================================================
# GET UNSEEN QUESTION COUNT
# ============================================================

def get_unseen_question_count(
    user_id,
    exam=None,
    subject=None
):

    conn = db()

    try:

        params = [user_id]

        conditions = [
            "q.active = 1",
            """
            NOT EXISTS (
                SELECT 1
                FROM quiz_history h
                WHERE h.user_id = ?
                AND h.question_id = q.id
            )
            """
        ]

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
            SELECT COUNT(*)
            FROM questions q
            WHERE {" AND ".join(conditions)}
        """

        row = conn.execute(
            sql,
            tuple(params)
        ).fetchone()

        return int(row[0] or 0)

    finally:

        conn.close()


# ============================================================
# SAVE QUIZ
# ============================================================

def create_quiz(
    user_id,
    title,
    exam=None,
    subject=None,
    negative_mark=None
):

    conn = db()

    try:

        if negative_mark is None:
            negative_mark = get_negative_mark()

        cursor = conn.execute(
            """
            INSERT INTO quizzes
            (
                title,
                user_id,
                exam,
                subject,
                negative_mark,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                user_id,
                exam or "",
                subject or "",
                float(negative_mark),
                utcnow(),
            )
        )

        conn.commit()

        return cursor.lastrowid

    except Exception:

        logger.exception(
            "Quiz creation failed"
        )

        return None

    finally:

        conn.close()


# ============================================================
# ADD QUESTION TO QUIZ
# ============================================================

def add_question_to_quiz(
    quiz_id,
    question_id,
    position
):

    conn = db()

    try:

        conn.execute(
            """
            INSERT OR IGNORE INTO quiz_questions
            (
                quiz_id,
                question_id,
                position
            )
            VALUES (?, ?, ?)
            """,
            (
                quiz_id,
                question_id,
                position,
            )
        )

        conn.commit()

        return True

    except Exception:

        logger.exception(
            "Failed adding question to quiz"
        )

        return False

    finally:

        conn.close()


# ============================================================
# SAVE QUIZ QUESTIONS
# ============================================================

def save_quiz_questions(
    quiz_id,
    question_ids
):

    for position, question_id in enumerate(
        question_ids,
        start=1
    ):

        add_question_to_quiz(
            quiz_id,
            question_id,
            position
        )

    return True


# ============================================================
# GET SAVED QUIZ
# ============================================================

def get_quiz(
    quiz_id
):

    conn = db()

    try:

        row = conn.execute(
            """
            SELECT *
            FROM quizzes
            WHERE id = ?
            """,
            (quiz_id,)
        ).fetchone()

        return (
            dict(row)
            if row
            else None
        )

    finally:

        conn.close()


# ============================================================
# GET SAVED QUIZ QUESTIONS
# ============================================================

def get_saved_quiz_questions(
    quiz_id
):

    conn = db()

    try:

        rows = conn.execute(
            """
            SELECT q.*
            FROM questions q
            INNER JOIN quiz_questions qq
                ON qq.question_id = q.id
            WHERE qq.quiz_id = ?
            AND q.active = 1
            ORDER BY qq.position ASC
            """,
            (quiz_id,)
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:

        conn.close()


# ============================================================
# GET ONLY UNSEEN SAVED QUIZ QUESTIONS
# ============================================================

def get_unseen_saved_quiz_questions(
    user_id,
    quiz_id,
    count=10
):

    try:
        count = int(count)
    except Exception:
        count = DEFAULT_QUIZ_COUNT

    conn = db()

    try:

        rows = conn.execute(
            """
            SELECT q.*
            FROM questions q
            INNER JOIN quiz_questions qq
                ON qq.question_id = q.id
            WHERE qq.quiz_id = ?
            AND q.active = 1

            AND NOT EXISTS (
                SELECT 1
                FROM quiz_history h
                WHERE h.user_id = ?
                AND h.question_id = q.id
            )

            ORDER BY qq.position ASC
            LIMIT ?
            """,
            (
                quiz_id,
                user_id,
                count,
            )
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:

        conn.close()


# ============================================================
# CREATE QUIZ AND RANDOM QUESTIONS
# ============================================================

def create_random_quiz(
    user_id,
    title="New Quiz",
    count=10,
    exam=None,
    subject=None
):

    questions = get_quiz_questions(
        user_id=user_id,
        count=count,
        exam=exam,
        subject=subject,
    )

    if not questions:
        return None, []

    quiz_id = create_quiz(
        user_id=user_id,
        title=title,
        exam=exam,
        subject=subject,
    )

    if not quiz_id:
        return None, []

    question_ids = [
        q["id"]
        for q in questions
    ]

    save_quiz_questions(
        quiz_id,
        question_ids
    )

    return quiz_id, questions


# ============================================================
# START QUIZ SESSION
# ============================================================

def create_quiz_session(
    user_id,
    questions,
    quiz_id=None
):

    session_id = uuid.uuid4().hex[:12]

    ACTIVE_QUIZZES[
        session_id
    ] = {
        "user_id": user_id,
        "quiz_id": quiz_id,
        "questions": questions,
        "index": 0,
        "score": 0,
        "correct": 0,
        "wrong": 0,
        "skipped": 0,
        "started_at": time.time(),
        "answered": set(),
    }

    return session_id


# ============================================================
# GET QUIZ SESSION
# ============================================================

def get_quiz_session(
    session_id
):

    return ACTIVE_QUIZZES.get(
        session_id
    )


# ============================================================
# DELETE QUIZ SESSION
# ============================================================

def remove_quiz_session(
    session_id
):

    ACTIVE_QUIZZES.pop(
        session_id,
        None
    )


# ============================================================
# GET CURRENT QUESTION
# ============================================================

def get_current_question(
    session_id
):

    session = get_quiz_session(
        session_id
    )

    if not session:
        return None

    index = session.get(
        "index",
        0
    )

    questions = session.get(
        "questions",
        []
    )

    if index < 0 or index >= len(
        questions
    ):
        return None

    return questions[index]
    # ============================================================
# QUIZ DISPLAY
# ============================================================

async def send_quiz_question(
    update,
    context,
    session_id
):

    session = get_quiz_session(
        session_id
    )

    if not session:
        return

    question = get_current_question(
        session_id
    )

    if not question:

        user_id = session["user_id"]

        await update.effective_message.reply_text(
            "Quiz पूरा हो गया।\n\n"
            f"सही: {session['correct']}\n"
            f"गलत: {session['wrong']}\n"
            f"स्कोर: {session['score']}"
        )

        remove_quiz_session(
            session_id
        )

        return

    index = session["index"] + 1
    total = len(session["questions"])

    text = (
        f"प्रश्न {index}/{total}\n\n"
        f"{question['question']}\n\n"
        f"A) {question['option_a']}\n"
        f"B) {question['option_b']}\n"
        f"C) {question['option_c']}\n"
        f"D) {question['option_d']}"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "A",
                callback_data=f"ans:{session_id}:A"
            ),
            InlineKeyboardButton(
                "B",
                callback_data=f"ans:{session_id}:B"
            ),
        ],
        [
            InlineKeyboardButton(
                "C",
                callback_data=f"ans:{session_id}:C"
            ),
            InlineKeyboardButton(
                "D",
                callback_data=f"ans:{session_id}:D"
            ),
        ],
        [
            InlineKeyboardButton(
                "Stop Quiz",
                callback_data=f"stopquiz:{session_id}"
            )
        ],
    ]

    await update.effective_message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


# ============================================================
# /QUIZ
# ============================================================

async def quiz_command(
    update,
    context
):

    user = update.effective_user

    ensure_user(user)




    args = context.args

    count = DEFAULT_QUIZ_COUNT

    if args:

        try:
            count = int(args[0])
        except Exception:
            count = DEFAULT_QUIZ_COUNT

    count = max(
        1,
        min(
            count,
            MAX_IMPORT_QUESTIONS
        )
    )

    questions = get_quiz_questions(
        user_id=user.id,
        count=count
    )

    if not questions:

        unseen = get_unseen_question_count(
            user.id
        )

        if unseen == 0:

            await update.message.reply_text(
                "आपके लिए सभी उपलब्ध questions "
                "पहले ही इस्तेमाल हो चुके हैं।\n\n"
                "नई questions add/import करें।"
            )

        else:

            await update.message.reply_text(
                "Quiz के लिए questions उपलब्ध नहीं हैं।"
            )

        return

    session_id = create_quiz_session(
        user_id=user.id,
        questions=questions
    )

    await send_quiz_question(
        update,
        context,
        session_id
    )


# ============================================================
# /QUIZID
# ============================================================

async def quizid_command(
    update,
    context
):

    user = update.effective_user

   
    ensure_user(user)


    

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "/quizid QUIZ_ID"
        )

        return

    try:

        quiz_id = int(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "Invalid Quiz ID."
        )

        return

    quiz = get_quiz(
        quiz_id
    )

    if not quiz:

        await update.message.reply_text(
            "Quiz नहीं मिला।"
        )

        return

    questions = get_unseen_saved_quiz_questions(
        user_id=user.id,
        quiz_id=quiz_id,
        count=MAX_IMPORT_QUESTIONS
    )

    if not questions:

        await update.message.reply_text(
            "इस quiz के सभी questions "
            "आप पहले ही कर चुके हैं।"
        )

        return

    session_id = create_quiz_session(
        user_id=user.id,
        questions=questions,
        quiz_id=quiz_id
    )

    await send_quiz_question(
        update,
        context,
        session_id
    )


# ============================================================
# ANSWER CALLBACK
# ============================================================

async def answer_callback(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    data = query.data or ""

    parts = data.split(":")

    if len(parts) != 3:
        return

    if parts[0] != "ans":
        return

    session_id = parts[1]
    selected = parts[2].upper()

    if selected not in (
        "A",
        "B",
        "C",
        "D"
    ):
        return

    session = get_quiz_session(
        session_id
    )

    if not session:

        await query.edit_message_text(
            "यह quiz session समाप्त हो चुका है।"
        )

        return

    if query.from_user.id != session["user_id"]:

        await query.answer(
            "यह quiz आपका नहीं है।",
            show_alert=True
        )

        return

    index = session["index"]

    if index >= len(
        session["questions"]
    ):
        return

    question = session["questions"][index]

    question_id = question["id"]

    # Same question दोबारा answer न हो
    if question_id in session["answered"]:

        await query.answer(
            "यह question पहले ही answer हो चुका है।",
            show_alert=True
        )

        return

    session["answered"].add(
        question_id
    )

    correct_answer = str(
        question["answer"]
    ).strip().upper()

    # Question को तुरंत history में डालना
    mark_question_used(
        session["user_id"],
        question_id
    )

    if selected == correct_answer:

        session["correct"] += 1
        session["score"] += 1

        result_text = "सही उत्तर"

    else:

        session["wrong"] += 1

        negative_mark = get_negative_mark()

        session["score"] -= negative_mark

        result_text = (
            "गलत उत्तर\n"
            f"सही उत्तर: {correct_answer}"
        )

    explanation = (
        question.get(
            "explanation",
            ""
        )
        or ""
    ).strip()

    response = (
        f"{result_text}\n\n"
        f"आपका उत्तर: {selected}\n"
        f"सही उत्तर: {correct_answer}"
    )

    if explanation:

        response += (
            f"\n\nव्याख्या:\n"
            f"{explanation}"
        )

    await query.edit_message_text(
        response
    )

    session["index"] += 1

    # अगला question
    if session["index"] < len(
        session["questions"]
    ):

        await send_quiz_question(
            update,
            context,
            session_id
        )

    else:

        score = session["score"]

        await query.message.reply_text(
            "Quiz पूरा हो गया।\n\n"
            f"कुल प्रश्न: "
            f"{len(session['questions'])}\n"
            f"सही: {session['correct']}\n"
            f"गलत: {session['wrong']}\n"
            f"स्कोर: {score}"
        )

        remove_quiz_session(
            session_id
        )


# ============================================================
# STOP QUIZ CALLBACK
# ============================================================

async def stop_quiz_callback(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    data = query.data or ""

    parts = data.split(":")

    if len(parts) != 2:
        return

    session_id = parts[1]

    session = get_quiz_session(
        session_id
    )

    if not session:
        return

    if query.from_user.id != session["user_id"]:

        await query.answer(
            "यह quiz आपका नहीं है।",
            show_alert=True
        )

        return

    remove_quiz_session(
        session_id
    )

    await query.edit_message_text(
        "Quiz रोक दिया गया।"
            )
    # ============================================================
# START COMMAND
# ============================================================

async def start_command(
    update,
    context
):

    user = update.effective_user

    
    ensure_user(user)




    admin_text = ""

    if is_admin(user.id):
        admin_text = (
            "\n\nAdmin commands भी available हैं।"
        )

    await update.message.reply_text(
        "Quiz Bot चालू है।\n\n"
        "Commands:\n"
        "/quiz - Quiz शुरू करें\n"
        "/stats - अपनी stats देखें\n"
        "/newquiz - नया quiz बनाएं\n"
        "/quizid ID - Saved quiz शुरू करें\n"
        "/help - सभी commands देखें"
        + admin_text
    )


# ============================================================
# STATS COMMAND
# ============================================================

async def stats_command(
    update,
    context
):

    user = update.effective_user

    ensure_user(user)



    

    stats = get_stats(
        user.id
    )

    if not stats:
        await update.message.reply_text(
            "अभी आपकी कोई stats उपलब्ध नहीं है।"
        )
        return

    await update.message.reply_text(
        "आपकी Quiz Stats\n\n"
        f"कुल Quiz: {stats.get('quiz_count', 0)}\n"
        f"कुल Questions: {stats.get('total_questions', 0)}\n"
        f"सही: {stats.get('correct', 0)}\n"
        f"गलत: {stats.get('wrong', 0)}\n"
        f"स्कोर: {stats.get('score', 0)}"
    )


# ============================================================
# HELP COMMAND
# ============================================================

async def help_command(
    update,
    context
):

    text = """
Quiz Bot Commands

User Commands:

/start
Bot status और basic menu

/quiz
Random quiz शुरू करें

/quiz 20
20 questions का quiz

/stats
अपनी performance देखें

/quizid ID
Saved quiz शुरू करें

/newquiz
नया quiz बनाएं

/help
Commands की पूरी list

Admin Commands:

/add
नया question add करें

/edit ID
Question edit करें

/delete ID
Question delete करें

/generate 10 Topic
AI से questions बनाएं

/scrape SOURCE
Website से content लेकर questions बनाएं

/pdfimport
PDF से questions import करें

/txtimport
TXT से questions import करें

/pdfinfo
PDF information

/htmlinfo
HTML/source information

/htmlreport
Source report

/poll2q
Telegram quiz poll को question में बदलें

/scrapepoll
Forward किए गए polls process करें

/clone ID
Quiz clone करें

/queue
Clone queue देखें

/negmark 0.25
Negative marking सेट करें

/resetpenalty
Default negative marking लगाएं

/stop
Active operation रोकें

/cancel
Pending operation cancel करें
"""

    await update.message.reply_text(
        text.strip()
    )


# ============================================================
# ADMIN CHECK
# ============================================================

async def require_admin(
    update
):

    user = update.effective_user

    if not user:
        return False

    if not is_admin(user.id):

        if update.effective_message:

            await update.effective_message.reply_text(
                "यह command केवल admin के लिए है।"
            )

        return False

    return True


# ============================================================
# /ADD
# ============================================================

async def add_command(
    update,
    context
):

    if not await require_admin(update):
        return

    user_id = update.effective_user.id

    PENDING[user_id] = {
        "action": "add"
    }

    await update.message.reply_text(
        "Question इस format में भेजें:\n\n"
        "Question\n"
        "A) Option A\n"
        "B) Option B\n"
        "C) Option C\n"
        "D) Option D\n"
        "Answer: B\n"
        "Explanation: Explanation\n"
        "Exam: CET\n"
        "Subject: Polity\n\n"
        "Cancel करने के लिए /cancel भेजें।"
    )


# ============================================================
# /EDIT
# ============================================================

async def edit_command(
    update,
    context
):

    if not await require_admin(update):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "/edit QUESTION_ID"
        )

        return

    try:

        question_id = int(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "Invalid Question ID."
        )

        return

    question = get_question(
        question_id
    )

    if not question:

        await update.message.reply_text(
            "Question नहीं मिला।"
        )

        return

    user_id = update.effective_user.id

    PENDING[user_id] = {
        "action": "edit",
        "question_id": question_id,
    }

    await update.message.reply_text(
        "Question का नया data भेजें:\n\n"
        "Question\n"
        "A) Option A\n"
        "B) Option B\n"
        "C) Option C\n"
        "D) Option D\n"
        "Answer: B\n"
        "Explanation: Explanation\n"
        "Exam: CET\n"
        "Subject: Polity\n\n"
        "Cancel: /cancel"
    )


# ============================================================
# /DELETE
# ============================================================

async def delete_command(
    update,
    context
):

    if not await require_admin(update):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "/delete QUESTION_ID"
        )

        return

    try:

        question_id = int(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "Invalid Question ID."
        )

        return

    question = get_question(
        question_id
    )

    if not question:

        await update.message.reply_text(
            "Question नहीं मिला।"
        )

        return

    success = delete_question(
        question_id
    )

    if success:

        await update.message.reply_text(
            f"Question #{question_id} delete कर दिया गया।"
        )

    else:

        await update.message.reply_text(
            "Question delete नहीं हो सका।"
        )


# ============================================================
# PENDING TEXT HANDLER
# ============================================================

async def pending_text_handler(
    update,
    context
):

    user = update.effective_user

    if not user:
        return

    user_id = user.id

    pending = PENDING.get(
        user_id
    )

    if not pending:
        return

    if not is_admin(user_id):
        return

    text = (
        update.message.text
        or ""
    ).strip()

    if not text:
        return

    data = parse_question_text(
        text
    )

    if not data:

        await update.message.reply_text(
            "Question format सही नहीं है।\n\n"
            "Example:\n"
            "भारत का संविधान कब लागू हुआ?\n"
            "A) 1947\n"
            "B) 1950\n"
            "C) 1952\n"
            "D) 1949\n"
            "Answer: B\n"
            "Explanation: संविधान 26 जनवरी 1950 को लागू हुआ।\n"
            "Exam: CET\n"
            "Subject: Polity"
        )

        return

    action = pending.get(
        "action"
    )

    if action == "add":

        question_id = add_question(
            data
        )

        if question_id:

            PENDING.pop(
                user_id,
                None
            )

            await update.message.reply_text(
                "Question successfully add हो गया।\n\n"
                f"Question ID: {question_id}"
            )

        else:

            await update.message.reply_text(
                "Question add नहीं हो सका। "
                "Duplicate हो सकता है।"
            )

        return

    if action == "edit":

        question_id = pending.get(
            "question_id"
        )

        if not question_id:

            PENDING.pop(
                user_id,
                None
            )

            return

        success = update_question(
            question_id,
            data
        )

        if success:

            PENDING.pop(
                user_id,
                None
            )

            await update.message.reply_text(
                f"Question #{question_id} "
                "successfully update हो गया।"
            )

        else:

            await update.message.reply_text(
                "Question update नहीं हो सका।"
            )


# ============================================================
# /CANCEL
# ============================================================

async def cancel_command(
    update,
    context
):

    user_id = update.effective_user.id

    removed = False

    if user_id in PENDING:

        PENDING.pop(
            user_id,
            None
        )

        removed = True

    if user_id in QUIZ_CREATE:

        QUIZ_CREATE.pop(
            user_id,
            None
        )

        removed = True

    if removed:

        await update.message.reply_text(
            "Current operation cancel कर दिया गया।"
        )

    else:

        await update.message.reply_text(
            "कोई pending operation नहीं है।"
    )
        # ============================================================
# NEW QUIZ COMMAND
# ============================================================

async def newquiz_command(
    update,
    context
):

    user = update.effective_user

    
    ensure_user(user)




    # पुराने quiz creation state को साफ करें
    QUIZ_CREATE.pop(
        user.id,
        None
    )

    QUIZ_CREATE[
        user.id
    ] = {
        "step": "title"
    }

    await update.message.reply_text(
        "नया Quiz बनाने के लिए जानकारी दें।\n\n"
        "पहले Quiz का नाम भेजें।\n\n"
        "Cancel: /cancel"
    )


# ============================================================
# NEW QUIZ TEXT FLOW
# ============================================================

async def newquiz_text_handler(
    update,
    context
):

    user = update.effective_user

    if not user:
        return

    user_id = user.id

    state = QUIZ_CREATE.get(
        user_id
    )

    if not state:
        return

    text = (
        update.message.text
        or ""
    ).strip()

    if not text:
        return

    step = state.get(
        "step"
    )

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    if step == "title":

        state["title"] = text
        state["step"] = "exam"

        await update.message.reply_text(
            "Exam का नाम भेजें।\n\n"
            "Example: CET\n\n"
            "अगर नहीं देना है तो - भेजें।"
        )

        return

    # --------------------------------------------------------
    # EXAM
    # --------------------------------------------------------

    if step == "exam":

        state["exam"] = (
            ""
            if text == "-"
            else text
        )

        state["step"] = "subject"

        await update.message.reply_text(
            "Subject भेजें।\n\n"
            "Example: Polity\n\n"
            "अगर नहीं देना है तो - भेजें।"
        )

        return

    # --------------------------------------------------------
    # SUBJECT
    # --------------------------------------------------------

    if step == "subject":

        state["subject"] = (
            ""
            if text == "-"
            else text
        )

        state["step"] = "count"

        await update.message.reply_text(
            "कितने questions चाहिए?\n\n"
            "Example: 10"
        )

        return

    # --------------------------------------------------------
    # COUNT
    # --------------------------------------------------------

    if step == "count":

        try:

            count = int(text)

        except Exception:

            await update.message.reply_text(
                "कृपया केवल number भेजें।\n"
                "Example: 10"
            )

            return

        if count < 1:

            await update.message.reply_text(
                "Questions की संख्या कम से कम 1 होनी चाहिए।"
            )

            return

        count = min(
            count,
            MAX_IMPORT_QUESTIONS
        )

        state["count"] = count

        title = state["title"]
        exam = state.get("exam") or None
        subject = state.get("subject") or None

        await update.message.reply_text(
            "Quiz बनाया जा रहा है...\n"
            "कृपया प्रतीक्षा करें।"
        )

        try:

            quiz_id, questions = create_random_quiz(
                user_id=user_id,
                title=title,
                count=count,
                exam=exam,
                subject=subject,
            )

        except Exception:

            logger.exception(
                "New quiz creation failed"
            )

            await update.message.reply_text(
                "Quiz create करते समय error आया।"
            )

            QUIZ_CREATE.pop(
                user_id,
                None
            )

            return

        QUIZ_CREATE.pop(
            user_id,
            None
        )

        if not quiz_id:

            await update.message.reply_text(
                "Quiz create नहीं हो सका।\n\n"
                "हो सकता है आपके लिए "
                "unseen questions उपलब्ध नहीं हैं।"
            )

            return

        await update.message.reply_text(
            "Quiz successfully create हो गया।\n\n"
            f"Quiz ID: {quiz_id}\n"
            f"Title: {title}\n"
            f"Questions: {len(questions)}\n\n"
            f"Start करने के लिए:\n"
            f"/quizid {quiz_id}"
        )


# ============================================================
# NEGATIVE MARKING
# ============================================================

async def negmark_command(
    update,
    context
):

    if not await require_admin(update):
        return

    if not context.args:

        current = get_negative_mark()

        await update.message.reply_text(
            f"Current negative marking: {current}\n\n"
            "Set करने के लिए:\n"
            "/negmark 0.25"
        )

        return

    try:

        value = float(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "Invalid value.\n\n"
            "Example:\n"
            "/negmark 0.25"
        )

        return

    if value < 0:

        await update.message.reply_text(
            "Negative marking 0 से कम नहीं हो सकती।"
        )

        return

    if value > 10:

        await update.message.reply_text(
            "Value बहुत ज्यादा है।"
        )

        return

    set_setting(
        "negative_mark",
        str(value)
    )

    await update.message.reply_text(
        f"Negative marking set कर दी गई: {value}"
    )


# ============================================================
# RESET NEGATIVE MARKING
# ============================================================

async def resetpenalty_command(
    update,
    context
):

    if not await require_admin(update):
        return

    set_setting(
        "negative_mark",
        str(DEFAULT_NEGATIVE_MARK)
    )

    await update.message.reply_text(
        "Negative marking reset हो गई।\n\n"
        f"Current value: {DEFAULT_NEGATIVE_MARK}"
    )


# ============================================================
# STOP COMMAND
# ============================================================

async def stop_command(
    update,
    context
):

    user_id = update.effective_user.id

    stopped = []

    # Pending operations
    if user_id in PENDING:

        PENDING.pop(
            user_id,
            None
        )

        stopped.append(
            "pending operation"
        )

    # Quiz creation
    if user_id in QUIZ_CREATE:

        QUIZ_CREATE.pop(
            user_id,
            None
        )

        stopped.append(
            "quiz creation"
        )

    # Active quiz sessions
    session_ids = []

    for session_id, session in list(
        ACTIVE_QUIZZES.items()
    ):

        if session.get(
            "user_id"
        ) == user_id:

            session_ids.append(
                session_id
            )

    for session_id in session_ids:

        remove_quiz_session(
            session_id
        )

        stopped.append(
            "active quiz"
        )

    if stopped:

        await update.message.reply_text(
            "Current operations stop कर दी गईं।"
        )

    else:

        await update.message.reply_text(
            "आपकी कोई active operation नहीं है।"
        )


# ============================================================
# CLONE QUEUE STATUS
# ============================================================

async def queue_command(
    update,
    context
):

    if not await require_admin(update):
        return

    with CLONE_LOCK:

        queue_copy = list(
            CLONE_QUEUE
        )

    if not queue_copy:

        await update.message.reply_text(
            "Clone queue खाली है।"
        )

        return

    lines = [
        "Clone Queue",
        ""
    ]

    for index, item in enumerate(
        queue_copy,
        start=1
    ):

        lines.append(
            f"{index}. "
            f"Quiz ID: {item.get('quiz_id', '-')}"
        )

        lines.append(
            f"User ID: {item.get('user_id', '-')}"
        )

        lines.append(
            f"Status: {item.get('status', 'queued')}"
        )

        lines.append("")

    await update.message.reply_text(
        "\n".join(lines)
    )
    # ============================================================
# AI GENERATE COMMAND
# ============================================================

async def generate_command(update, context):

    if not await require_admin(update):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage:\n\n"
            "/generate 10 Indian Polity\n\n"
            "Example:\n"
            "/generate 20 Rajasthan History"
        )
        return

    try:
        count = int(context.args[0])
    except Exception:
        await update.message.reply_text(
            "पहला argument questions की संख्या होना चाहिए।\n\n"
            "Example:\n"
            "/generate 10 Indian Polity"
        )
        return

    if count < 1:
        await update.message.reply_text(
            "Questions की संख्या कम से कम 1 होनी चाहिए।"
        )
        return

    count = min(count, MAX_IMPORT_QUESTIONS)

    topic = " ".join(
        context.args[1:]
    ).strip()

    if not topic:
        await update.message.reply_text(
            "Topic देना जरूरी है।\n\n"
            "Example:\n"
            "/generate 10 Indian Polity"
        )
        return

    await update.message.reply_text(
        f"AI {count} questions generate कर रहा है...\n\n"
        f"Topic: {topic}"
    )

    try:

        questions = groq_generate_questions(
            topic=topic,
            count=count
        )

    except Exception as e:

        logger.exception(
            "AI generation failed"
        )

        await update.message.reply_text(
            "AI question generation में error आया।\n\n"
            f"Error: {str(e)[:500]}"
        )

        return

    if not questions:

        await update.message.reply_text(
            "AI से कोई valid question प्राप्त नहीं हुआ।"
        )

        return

    added = 0
    duplicate = 0
    failed = 0

    for question in questions:

        try:

            question_id = add_question(
                question
            )

            if question_id:
                added += 1
            else:
                duplicate += 1

        except Exception:

            logger.exception(
                "Question save failed"
            )

            failed += 1

    await update.message.reply_text(
        "AI Generation Complete\n\n"
        f"Requested: {count}\n"
        f"Generated: {len(questions)}\n"
        f"Added: {added}\n"
        f"Duplicate: {duplicate}\n"
        f"Failed: {failed}"
    )


# ============================================================
# SCRAPE COMMAND
# ============================================================

async def scrape_command(update, context):

    if not await require_admin(update):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n\n"
            "/scrape SOURCE\n\n"
            "Available sources:\n"
            "rajras\n"
            "rbse\n"
            "samyak_rbse\n"
            "ncert\n"
            "online2study"
        )

        return

    source_name = (
        context.args[0]
        .strip()
        .lower()
    )

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

        await update.message.reply_text(
            "Source नहीं मिला या disabled है।\n\n"
            "Available:\n"
            "rajras\n"
            "rbse\n"
            "samyak_rbse\n"
            "ncert\n"
            "online2study"
        )

        return

    await update.message.reply_text(
        f"Source scrape किया जा रहा है:\n"
        f"{source_name}\n\n"
        "यह process थोड़ा समय ले सकता है।"
    )

    try:

        result = scrape_and_generate(
            source_name
        )

    except Exception:

        logger.exception(
            "Scrape failed"
        )

        await update.message.reply_text(
            "Scraping में error आया।"
        )

        return

    if not result:

        await update.message.reply_text(
            "Scraping से कोई question generate नहीं हुआ।"
        )

        return

    added = 0
    duplicate = 0
    failed = 0

    for question in result:

        try:

            question_id = add_question(
                question
            )

            if question_id:
                added += 1
            else:
                duplicate += 1

        except Exception:

            logger.exception(
                "Scraped question save failed"
            )

            failed += 1

    await update.message.reply_text(
        "Scraping Complete\n\n"
        f"Source: {source_name}\n"
        f"Generated: {len(result)}\n"
        f"Added: {added}\n"
        f"Duplicate: {duplicate}\n"
        f"Failed: {failed}"
    )


# ============================================================
# SOURCE LIST COMMAND
# ============================================================

async def sources_command(update, context):

    if not await require_admin(update):
        return

    conn = db()

    rows = conn.execute(
        """
        SELECT name, url, enabled
        FROM sources
        ORDER BY name
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "कोई source configured नहीं है।"
        )

        return

    lines = [
        "Configured Sources",
        ""
    ]

    for row in rows:

        status = (
            "Enabled"
            if row["enabled"]
            else "Disabled"
        )

        lines.append(
            f"{row['name']} — {status}"
        )

        lines.append(
            row["url"]
        )

        lines.append("")

    await update.message.reply_text(
        "\n".join(lines)
    )


# ============================================================
# SOURCE ADD COMMAND
# ============================================================

async def addsource_command(update, context):

    if not await require_admin(update):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "Usage:\n\n"
            "/addsource SOURCE_NAME URL\n\n"
            "Example:\n"
            "/addsource example https://example.com/"
        )

        return

    name = (
        context.args[0]
        .strip()
        .lower()
    )

    url = (
        context.args[1]
        .strip()
    )

    if not re.match(
        r"^https?://",
        url,
        re.IGNORECASE
    ):

        await update.message.reply_text(
            "Valid HTTP/HTTPS URL दें।"
        )

        return

    conn = db()

    try:

        conn.execute(
            """
            INSERT INTO sources
            (name, url, enabled)
            VALUES (?, ?, 1)

            ON CONFLICT(name)
            DO UPDATE SET
                url = excluded.url,
                enabled = 1
            """,
            (
                name,
                url
            )
        )

        conn.commit()

    except Exception:

        conn.rollback()

        logger.exception(
            "Source add failed"
        )

        await update.message.reply_text(
            "Source save नहीं हो सका।"
        )

        conn.close()

        return

    conn.close()

    await update.message.reply_text(
        "Source successfully save हो गया।\n\n"
        f"Name: {name}\n"
        f"URL: {url}"
    )


# ============================================================
# SOURCE ENABLE / DISABLE
# ============================================================

async def source_command(update, context):

    if not await require_admin(update):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "Usage:\n\n"
            "/source NAME on\n"
            "/source NAME off"
        )

        return

    name = (
        context.args[0]
        .strip()
        .lower()
    )

    action = (
        context.args[1]
        .strip()
        .lower()
    )

    if action not in (
        "on",
        "off"
    ):

        await update.message.reply_text(
            "केवल on या off इस्तेमाल करें।"
        )

        return

    enabled = 1 if action == "on" else 0

    conn = db()

    cursor = conn.execute(
        """
        UPDATE sources
        SET enabled = ?
        WHERE name = ?
        """,
        (
            enabled,
            name
        )
    )

    conn.commit()

    changed = cursor.rowcount

    conn.close()

    if not changed:

        await update.message.reply_text(
            "Source नहीं मिला।"
        )

        return

    status = (
        "enabled"
        if enabled
        else "disabled"
    )

    await update.message.reply_text(
        f"Source '{name}' {status} कर दिया गया।"
    )
    # ============================================================
# PDF / TXT IMPORT COMMANDS
# ============================================================

async def pdfimport_command(update, context):

    if not await require_admin(update):
        return

    user_id = update.effective_user.id

    PENDING[user_id] = {
        "action": "pdfimport"
    }

    await update.message.reply_text(
        "अब PDF file भेजें।\n\n"
        "PDF के questions database में import किए जाएंगे।\n\n"
        "Cancel करने के लिए /cancel भेजें।"
    )


async def txtimport_command(update, context):

    if not await require_admin(update):
        return

    user_id = update.effective_user.id

    PENDING[user_id] = {
        "action": "txtimport"
    }

    await update.message.reply_text(
        "अब TXT file भेजें।\n\n"
        "TXT के questions database में import किए जाएंगे।\n\n"
        "Cancel करने के लिए /cancel भेजें।"
    )


# ============================================================
# PDF INFO
# ============================================================

async def pdfinfo_command(update, context):

    if not await require_admin(update):
        return

    try:

        files = sorted(
            PDF_DIR.iterdir(),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

    except Exception:

        await update.message.reply_text(
            "PDF directory access नहीं हो सकी।"
        )

        return

    pdf_files = [
        p for p in files
        if p.is_file()
        and p.suffix.lower() == ".pdf"
    ]

    if not pdf_files:

        await update.message.reply_text(
            "अभी कोई PDF उपलब्ध नहीं है।"
        )

        return

    lines = [
        "PDF Files",
        ""
    ]

    for index, path in enumerate(
        pdf_files[:30],
        start=1
    ):

        try:

            size_mb = (
                path.stat().st_size
                / (1024 * 1024)
            )

            modified = datetime.fromtimestamp(
                path.stat().st_mtime
            ).strftime(
                "%Y-%m-%d %H:%M"
            )

        except Exception:

            size_mb = 0
            modified = "-"

        lines.append(
            f"{index}. {path.name}"
        )

        lines.append(
            f"Size: {size_mb:.2f} MB"
        )

        lines.append(
            f"Modified: {modified}"
        )

        lines.append("")

    if len(pdf_files) > 30:

        lines.append(
            f"... और {len(pdf_files) - 30} files"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


# ============================================================
# DOCUMENT IMPORT HANDLER
# ============================================================

async def document_import_handler(
    update,
    context
):

    if not update.message:
        return

    user = update.effective_user

    if not user:
        return

    if not is_admin(user.id):
        return

    document = update.message.document

    if not document:
        return

    filename = (
        document.file_name
        or "unknown"
    )

    extension = (
        Path(filename)
        .suffix
        .lower()
    )

    pending = PENDING.get(
        user.id
    )

    # --------------------------------------------------------
    # अगर कोई import operation pending नहीं है
    # --------------------------------------------------------

    if not pending:

        if extension in (
            ".pdf",
            ".txt"
        ):

            await update.message.reply_text(
                "File receive हुई है लेकिन कोई import operation "
                "select नहीं किया गया।\n\n"
                "PDF के लिए पहले:\n"
                "/pdfimport\n\n"
                "TXT के लिए:\n"
                "/txtimport"
            )

        return

    action = pending.get(
        "action"
    )

    # --------------------------------------------------------
    # PDF IMPORT
    # --------------------------------------------------------

    if action == "pdfimport":

        if extension != ".pdf":

            await update.message.reply_text(
                "इस operation में केवल PDF file भेजें।"
            )

            return

        await update.message.reply_text(
            "PDF download और process की जा रही है...\n"
            "कृपया प्रतीक्षा करें।"
        )

        try:

            telegram_file = await context.bot.get_file(
                document.file_id
            )

            safe_name = (
                f"{uuid.uuid4().hex}_"
                f"{Path(filename).name}"
            )

            destination = (
                PDF_DIR / safe_name
            )

            await telegram_file.download_to_drive(
                custom_path=str(destination)
            )

            # PDF को database में import करें
            result = import_pdf(
                user_id=user.id,
                file_path=str(destination),
                file_name=filename,
            )

        except Exception:

            logger.exception(
                "PDF import failed"
            )

            PENDING.pop(
                user.id,
                None
            )

            await update.message.reply_text(
                "PDF import करते समय error आया।"
            )

            return

        PENDING.pop(
            user.id,
            None
        )

        if isinstance(result, dict):

            added = result.get(
                "added",
                0
            )

            duplicate = result.get(
                "duplicate",
                result.get("duplicates", 0)
            )

            failed = result.get(
                "failed",
                0
            )

            total = result.get(
                "total",
                added + duplicate + failed
            )

            await update.message.reply_text(
                "PDF Import Complete\n\n"
                f"File: {filename}\n"
                f"Total: {total}\n"
                f"Added: {added}\n"
                f"Duplicate: {duplicate}\n"
                f"Failed: {failed}"
            )

        else:

            await update.message.reply_text(
                "PDF process हो गई।\n\n"
                f"Result: {result}"
            )

        return

    # --------------------------------------------------------
    # TXT IMPORT
    # --------------------------------------------------------

    if action == "txtimport":

        if extension != ".txt":

            await update.message.reply_text(
                "इस operation में केवल TXT file भेजें।"
            )

            return

        await update.message.reply_text(
            "TXT file process की जा रही है..."
        )

        temp_path = None

        try:

            temp_path = (
                DATA_DIR
                / f"{uuid.uuid4().hex}.txt"
            )

            telegram_file = await context.bot.get_file(
                document.file_id
            )

            await telegram_file.download_to_drive(
                custom_path=str(temp_path)
            )

            result = import_txt(
                file_path=str(temp_path),
                file_name=filename,
            )

        except Exception:

            logger.exception(
                "TXT import failed"
            )

            PENDING.pop(
                user.id,
                None
            )

            await update.message.reply_text(
                "TXT import करते समय error आया।"
            )

            return

        finally:

            if temp_path:

                try:

                    temp_path.unlink(
                        missing_ok=True
                    )

                except Exception:

                    pass

        PENDING.pop(
            user.id,
            None
        )

        if isinstance(result, dict):

            added = result.get(
                "added",
                0
            )

            duplicate = result.get(
                "duplicate",
                result.get("duplicates", 0)
            )

            failed = result.get(
                "failed",
                0
            )

            total = result.get(
                "total",
                added + duplicate + failed
            )

            await update.message.reply_text(
                "TXT Import Complete\n\n"
                f"File: {filename}\n"
                f"Total: {total}\n"
                f"Added: {added}\n"
                f"Duplicate: {duplicate}\n"
                f"Failed: {failed}"
            )

        else:

            await update.message.reply_text(
                "TXT process हो गई।\n\n"
                f"Result: {result}"
            )

        return
        # ============================================================
# TELEGRAM POLL HELPERS
# ============================================================

def extract_poll_question(poll):
    """
    Telegram Poll object से question payload तैयार करता है।
    """

    if not poll:
        return None

    question_text = (
        poll.question
        or ""
    ).strip()

    options = [
        (option.text or "").strip()
        for option in poll.options
    ]

    if not question_text:
        return None

    if len(options) != 4:
        return None

    if any(
        not option
        for option in options
    ):
        return None

    correct_index = poll.correct_option_id

    if (
        correct_index is None
        or correct_index < 0
        or correct_index >= len(options)
    ):
        return None

    correct_letter = chr(
        ord("A") + correct_index
    )

    return {
        "question": question_text,
        "option_a": options[0],
        "option_b": options[1],
        "option_c": options[2],
        "option_d": options[3],
        "answer": correct_letter,
        "explanation": "",
        "exam": "",
        "subject": "",
    }


# ============================================================
# SAVE POLL QUESTION
# ============================================================

def save_poll_question(poll):

    payload = extract_poll_question(
        poll
    )

    if not payload:
        return {
            "success": False,
            "reason": "invalid_poll",
            "question_id": None,
        }

    question_id = add_question(
        payload
    )

    if question_id:

        return {
            "success": True,
            "reason": "added",
            "question_id": question_id,
        }

    return {
        "success": False,
        "reason": "duplicate",
        "question_id": None,
    }


# ============================================================
# POLL2Q COMMAND
# ============================================================

async def poll2q_command(
    update,
    context
):

    if not await require_admin(update):
        return

    PENDING[
        update.effective_user.id
    ] = {
        "action": "poll2q"
    }

    await update.message.reply_text(
        "अब Telegram Quiz Poll भेजें या forward करें।\n\n"
        "Bot उसके question, options और correct answer "
        "को database में save करेगा।\n\n"
        "केवल Quiz Poll स्वीकार किया जाएगा।\n\n"
        "Cancel: /cancel"
    )


# ============================================================
# POLL MESSAGE HANDLER
# ============================================================

async def poll_message_handler(
    update,
    context
):

    user = update.effective_user

    if not user:
        return

    if not is_admin(user.id):
        return

    poll = None

    if update.message:
        poll = update.message.poll

    elif update.channel_post:
        poll = update.channel_post.poll

    if not poll:
        return

    pending = PENDING.get(
        user.id
    )

    # --------------------------------------------------------
    # अगर poll2q mode active नहीं है
    # --------------------------------------------------------

    if not pending:

        await update.effective_message.reply_text(
            "Poll receive हुआ है।\n\n"
            "इसे question में convert करने के लिए पहले:\n"
            "/poll2q"
        )

        return

    action = pending.get(
        "action"
    )

    if action not in (
        "poll2q",
        "scrapepoll"
    ):

        return

    result = save_poll_question(
        poll
    )

    if result["success"]:

        await update.effective_message.reply_text(
            "Poll successfully question में convert हो गया।\n\n"
            f"Question ID: {result['question_id']}"
        )

    elif result["reason"] == "duplicate":

        await update.effective_message.reply_text(
            "यह question पहले से database में मौजूद है।\n"
            "Duplicate होने के कारण save नहीं किया गया।"
        )

    else:

        await update.effective_message.reply_text(
            "Poll valid Quiz Poll नहीं है।\n\n"
            "चार options वाला quiz poll भेजें जिसमें "
            "correct answer मौजूद हो।"
        )


# ============================================================
# SCRAPE POLL COMMAND
# ============================================================

async def scrapepoll_command(
    update,
    context
):

    if not await require_admin(update):
        return

    PENDING[
        update.effective_user.id
    ] = {
        "action": "scrapepoll",
        "count": 0,
        "added": 0,
        "duplicate": 0,
        "failed": 0,
    }

    await update.message.reply_text(
        "Poll scraping mode ON है।\n\n"
        "अब Quiz Polls forward/send करें।\n\n"
        "हर valid poll को database में save किया जाएगा।\n\n"
        "Statistics देखने के लिए /stop या /cancel भेजें।"
    )


# ============================================================
# SCRAPE POLL STATUS
# ============================================================

async def poll_status(
    update,
    context
):

    user_id = update.effective_user.id

    pending = PENDING.get(
        user_id
    )

    if not pending:

        await update.message.reply_text(
            "Poll scraping mode active नहीं है।"
        )

        return

    if pending.get(
        "action"
    ) != "scrapepoll":

        await update.message.reply_text(
            "Poll scraping mode active नहीं है।"
        )

        return

    await update.message.reply_text(
        "Poll Processing Status\n\n"
        f"Processed: {pending.get('count', 0)}\n"
        f"Added: {pending.get('added', 0)}\n"
        f"Duplicate: {pending.get('duplicate', 0)}\n"
        f"Failed: {pending.get('failed', 0)}"
    )


# ============================================================
# UPDATED POLL HANDLER FOR SCRAPING STATS
# ============================================================

async def process_poll(
    update,
    context
):

    user = update.effective_user

    if not user:
        return

    if not is_admin(user.id):
        return

    poll = None

    if update.message:
        poll = update.message.poll

    elif update.channel_post:
        poll = update.channel_post.poll

    if not poll:
        return

    pending = PENDING.get(
        user.id
    )

    if not pending:
        return

    action = pending.get(
        "action"
    )

    if action == "scrapepoll":

        pending["count"] = (
            pending.get("count", 0) + 1
        )

        result = save_poll_question(
            poll
        )

        if result["success"]:

            pending["added"] = (
                pending.get("added", 0) + 1
            )

        elif result["reason"] == "duplicate":

            pending["duplicate"] = (
                pending.get("duplicate", 0) + 1
            )

        else:

            pending["failed"] = (
                pending.get("failed", 0) + 1
            )

        await update.effective_message.reply_text(
            "Poll processed.\n\n"
            f"Processed: {pending['count']}\n"
            f"Added: {pending['added']}\n"
            f"Duplicate: {pending['duplicate']}\n"
            f"Failed: {pending['failed']}"
        )

        return

    if action == "poll2q":

        result = save_poll_question(
            poll
        )

        PENDING.pop(
            user.id,
            None
        )

        if result["success"]:

            await update.effective_message.reply_text(
                "Poll successfully convert हो गया।\n\n"
                f"Question ID: {result['question_id']}"
            )

        elif result["reason"] == "duplicate":

            await update.effective_message.reply_text(
                "Question पहले से database में मौजूद है।"
            )

        else:

            await update.effective_message.reply_text(
                "Invalid Quiz Poll।"
            )
            # ============================================================
# CLONE QUIZ HELPERS
# ============================================================

def get_next_clone_job():
    """
    Queue से अगला queued job निकालता है।
    """

    with CLONE_LOCK:

        for item in CLONE_QUEUE:

            if item.get("status") == "queued":

                item["status"] = "processing"

                return item

    return None


def update_clone_job(
    job_id,
    **updates
):

    with CLONE_LOCK:

        for item in CLONE_QUEUE:

            if item.get("job_id") == job_id:

                item.update(
                    updates
                )

                return item

    return None


def clone_saved_quiz(
    source_quiz_id,
    owner_id,
    new_title=None
):
    """
    Existing saved quiz को clone करके नया quiz बनाता है।
    """

    source = get_quiz(
        source_quiz_id
    )

    if not source:
        raise ValueError(
            "Source quiz नहीं मिला।"
        )

    questions = get_saved_quiz_questions(
        source_quiz_id
    )

    if not questions:
        raise ValueError(
            "Source quiz में कोई question नहीं है।"
        )

    title = (
        new_title
        or f"{source['title']} - Clone"
    )

    new_quiz_id = create_quiz(
        owner_id=owner_id,
        title=title,
        description=source["description"]
        if "description" in source.keys()
        else ""
    )

    if not new_quiz_id:
        raise RuntimeError(
            "New quiz create नहीं हो सका।"
        )

    question_ids = []

    for question in questions:

        if isinstance(
            question,
            sqlite3.Row
        ):
            question_id = question["id"]
        else:
            question_id = (
                question.get("id")
                if isinstance(
                    question,
                    dict
                )
                else None
            )

        if question_id:
            question_ids.append(
                question_id
            )

    if not question_ids:
        raise RuntimeError(
            "Quiz questions प्राप्त नहीं हुए।"
        )

    save_quiz_questions(
        new_quiz_id,
        question_ids
    )

    return (
        new_quiz_id,
        len(question_ids)
    )


# ============================================================
# CLONE QUEUE WORKER
# ============================================================

async def clone_queue_worker(
    application
):

    while True:

        job = get_next_clone_job()

        if not job:

            await asyncio.sleep(
                1
            )

            continue

        job_id = job.get(
            "job_id"
        )

        try:

            new_quiz_id, count = (
                clone_saved_quiz(
                    source_quiz_id=job["quiz_id"],
                    owner_id=job["user_id"],
                    new_title=job.get("title")
                )
            )

            update_clone_job(
                job_id,
                status="completed",
                new_quiz_id=new_quiz_id,
                question_count=count,
                completed_at=utcnow()
            )

            try:

                await application.bot.send_message(
                    chat_id=job["user_id"],
                    text=(
                        "Quiz Clone Complete\n\n"
                        f"Original Quiz: {job['quiz_id']}\n"
                        f"New Quiz ID: {new_quiz_id}\n"
                        f"Questions: {count}\n\n"
                        f"Start करने के लिए:\n"
                        f"/quizid {new_quiz_id}"
                    )
                )

            except Exception:

                logger.exception(
                    "Clone completion message failed"
                )

        except Exception as e:

            logger.exception(
                "Clone job failed"
            )

            update_clone_job(
                job_id,
                status="failed",
                error=str(e)[:500],
                completed_at=utcnow()
            )

            try:

                await application.bot.send_message(
                    chat_id=job["user_id"],
                    text=(
                        "Quiz clone नहीं हो सका।\n\n"
                        f"Quiz ID: {job['quiz_id']}\n"
                        f"Error: {str(e)[:500]}"
                    )
                )

            except Exception:

                logger.exception(
                    "Clone failure message failed"
                )


# ============================================================
# CLONE COMMAND
# ============================================================

async def clone_command(
    update,
    context
):

    if not await require_admin(update):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n\n"
            "/clone QUIZ_ID\n\n"
            "Optional title:\n"
            "/clone 12 New CET Quiz"
        )

        return

    try:

        quiz_id = int(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "Invalid Quiz ID."
        )

        return

    source = get_quiz(
        quiz_id
    )

    if not source:

        await update.message.reply_text(
            "Quiz नहीं मिला।"
        )

        return

    questions = get_saved_quiz_questions(
        quiz_id
    )

    if not questions:

        await update.message.reply_text(
            "इस Quiz में कोई question नहीं है।"
        )

        return

    title = None

    if len(context.args) > 1:

        title = " ".join(
            context.args[1:]
        ).strip()

    job_id = uuid.uuid4().hex[:12]

    job = {
        "job_id": job_id,
        "user_id": update.effective_user.id,
        "quiz_id": quiz_id,
        "title": title,
        "status": "queued",
        "question_count": len(questions),
        "created_at": utcnow(),
    }

    with CLONE_LOCK:

        CLONE_QUEUE.append(
            job
        )

    await update.message.reply_text(
        "Clone request queue में add हो गई।\n\n"
        f"Job ID: {job_id}\n"
        f"Original Quiz: {quiz_id}\n"
        f"Questions: {len(questions)}\n\n"
        "Status देखने के लिए:\n"
        "/queue"
    )


# ============================================================
# CLONE JOB STATUS
# ============================================================

async def clone_status_command(
    update,
    context
):

    if not await require_admin(update):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n\n"
            "/clonestatus JOB_ID"
        )

        return

    job_id = (
        context.args[0]
        .strip()
    )

    with CLONE_LOCK:

        job = next(
            (
                item
                for item in CLONE_QUEUE
                if item.get("job_id") == job_id
            ),
            None
        )

    if not job:

        await update.message.reply_text(
            "Clone Job नहीं मिला।"
        )

        return

    text = (
        "Clone Job\n\n"
        f"Job ID: {job.get('job_id')}\n"
        f"Original Quiz: {job.get('quiz_id')}\n"
        f"Status: {job.get('status')}\n"
        f"Questions: {job.get('question_count', 0)}\n"
    )

    if job.get("new_quiz_id"):

        text += (
            f"New Quiz ID: "
            f"{job.get('new_quiz_id')}\n"
        )

    if job.get("error"):

        text += (
            f"\nError: {job.get('error')}"
        )

    await update.message.reply_text(
        text
    )


# ============================================================
# CLEAR COMPLETED CLONE JOBS
# ============================================================

async def clearqueue_command(
    update,
    context
):

    if not await require_admin(update):
        return

    with CLONE_LOCK:

        before = len(
            CLONE_QUEUE
        )

        CLONE_QUEUE[:] = [
            item
            for item in CLONE_QUEUE
            if item.get("status")
            not in (
                "completed",
                "failed"
            )
        ]

        removed = (
            before
            - len(CLONE_QUEUE)
        )

    await update.message.reply_text(
        f"{removed} completed/failed clone jobs "
        "queue से remove कर दिए गए।"
                )
    # ============================================================
# HTML SOURCE INFO
# ============================================================

def analyze_html_source(source_name):
    """
    Source website को fetch करके basic HTML information निकालता है।
    """

    conn = db()

    source = conn.execute(
        """
        SELECT *
        FROM sources
        WHERE name = ?
        """,
        (source_name,)
    ).fetchone()

    conn.close()

    if not source:
        return None

    url = source["url"]

    response = fetch_url(url)

    if not response:
        raise RuntimeError(
            "Website fetch नहीं हो सकी।"
        )

    html_content = response.text

    soup = BeautifulSoup(
        html_content,
        "html.parser"
    )

    title = ""

    if soup.title:
        title = (
            soup.title.get_text(
                " ",
                strip=True
            )
        )

    description = ""

    meta_description = soup.find(
        "meta",
        attrs={
            "name": "description"
        }
    )

    if meta_description:
        description = (
            meta_description.get(
                "content",
                ""
            )
            or ""
        ).strip()

    links = []

    for tag in soup.find_all(
        "a",
        href=True
    ):

        href = (
            tag.get(
                "href",
                ""
            )
            or ""
        ).strip()

        text = tag.get_text(
            " ",
            strip=True
        )

        if href:

            links.append(
                {
                    "text": text[:200],
                    "url": href
                }
            )

    images = soup.find_all(
        "img"
    )

    scripts = soup.find_all(
        "script"
    )

    styles = soup.find_all(
        "link",
        rel=lambda value: (
            value
            and "stylesheet" in value
        )
    )

    headings = []

    for level in range(1, 7):

        for heading in soup.find_all(
            f"h{level}"
        ):

            text = heading.get_text(
                " ",
                strip=True
            )

            if text:

                headings.append(
                    {
                        "level": level,
                        "text": text[:300]
                    }
                )

    text_content = html_to_text(
        html_content
    )

    words = re.findall(
        r"\S+",
        text_content
    )

    return {
        "name": source_name,
        "url": url,
        "title": title,
        "description": description,
        "status_code": response.status_code,
        "content_type": response.headers.get(
            "content-type",
            ""
        ),
        "html_size": len(
            html_content
        ),
        "text_size": len(
            text_content
        ),
        "word_count": len(
            words
        ),
        "links": links,
        "link_count": len(
            links
        ),
        "images": len(
            images
        ),
        "scripts": len(
            scripts
        ),
        "stylesheets": len(
            styles
        ),
        "headings": headings,
    }


# ============================================================
# /htmlinfo
# ============================================================

async def htmlinfo_command(
    update,
    context
):

    if not await require_admin(update):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n\n"
            "/htmlinfo SOURCE\n\n"
            "Example:\n"
            "/htmlinfo rajras"
        )

        return

    source_name = (
        context.args[0]
        .strip()
    )

    try:

        info = analyze_html_source(
            source_name
        )

        if not info:

            await update.message.reply_text(
                "Source नहीं मिला।\n\n"
                "/sources से available sources देखें।"
            )

            return

        text = (
            "HTML Source Information\n\n"
            f"Source: {info['name']}\n"
            f"URL: {info['url']}\n"
            f"Title: {info['title'] or 'N/A'}\n"
            f"Status: {info['status_code']}\n"
            f"Content-Type: {info['content_type']}\n\n"
            f"HTML Size: {info['html_size']} bytes\n"
            f"Text Size: {info['text_size']} chars\n"
            f"Words: {info['word_count']}\n"
            f"Links: {info['link_count']}\n"
            f"Images: {info['images']}\n"
            f"Scripts: {info['scripts']}\n"
            f"Stylesheets: {info['stylesheets']}\n"
            f"Headings: {len(info['headings'])}"
        )

        await update.message.reply_text(
            text
        )

    except Exception as e:

        logger.exception(
            "HTML info failed"
        )

        await update.message.reply_text(
            "HTML information निकालते समय error आया:\n\n"
            f"{str(e)[:1000]}"
        )


# ============================================================
# HTML REPORT GENERATOR
# ============================================================

def build_html_report(
    source_name
):

    info = analyze_html_source(
        source_name
    )

    if not info:
        raise ValueError(
            "Source नहीं मिला।"
        )

    report = []

    report.append(
        "<!DOCTYPE html>"
    )

    report.append(
        "<html>"
    )

    report.append(
        "<head>"
    )

    report.append(
        '<meta charset="UTF-8">'
    )

    report.append(
        f"<title>{html.escape(source_name)} Report</title>"
    )

    report.append(
        """
        <style>
        body {
            font-family: Arial, sans-serif;
            margin: 40px;
            line-height: 1.5;
        }

        h1, h2 {
            margin-top: 30px;
        }

        table {
            border-collapse: collapse;
            width: 100%;
        }

        th, td {
            border: 1px solid #999;
            padding: 8px;
            text-align: left;
        }

        th {
            background: #eee;
        }

        .box {
            border: 1px solid #aaa;
            padding: 15px;
            margin-bottom: 20px;
        }

        a {
            word-break: break-all;
        }
        </style>
        """
    )

    report.append(
        "</head>"
    )

    report.append(
        "<body>"
    )

    report.append(
        f"<h1>HTML Source Report</h1>"
    )

    report.append(
        '<div class="box">'
    )

    report.append(
        f"<p><b>Source:</b> "
        f"{html.escape(info['name'])}</p>"
    )

    report.append(
        f"<p><b>URL:</b> "
        f"{html.escape(info['url'])}</p>"
    )

    report.append(
        f"<p><b>Title:</b> "
        f"{html.escape(info['title'] or 'N/A')}</p>"
    )

    report.append(
        f"<p><b>Status Code:</b> "
        f"{info['status_code']}</p>"
    )

    report.append(
        f"<p><b>Content Type:</b> "
        f"{html.escape(info['content_type'])}</p>"
    )

    report.append(
        f"<p><b>HTML Size:</b> "
        f"{info['html_size']} bytes</p>"
    )

    report.append(
        f"<p><b>Text Size:</b> "
        f"{info['text_size']} characters</p>"
    )

    report.append(
        f"<p><b>Word Count:</b> "
        f"{info['word_count']}</p>"
    )

    report.append(
        f"<p><b>Links:</b> "
        f"{info['link_count']}</p>"
    )

    report.append(
        f"<p><b>Images:</b> "
        f"{info['images']}</p>"
    )

    report.append(
        f"<p><b>Scripts:</b> "
        f"{info['scripts']}</p>"
    )

    report.append(
        f"<p><b>Stylesheets:</b> "
        f"{info['stylesheets']}</p>"
    )

    report.append(
        "</div>"
    )

    # --------------------------------------------------------
    # DESCRIPTION
    # --------------------------------------------------------

    if info["description"]:

        report.append(
            "<h2>Description</h2>"
        )

        report.append(
            "<p>"
            + html.escape(
                info["description"]
            )
            + "</p>"
        )

    # --------------------------------------------------------
    # HEADINGS
    # --------------------------------------------------------

    report.append(
        "<h2>Headings</h2>"
    )

    if info["headings"]:

        report.append(
            "<table>"
            "<tr>"
            "<th>Level</th>"
            "<th>Heading</th>"
            "</tr>"
        )

        for heading in info["headings"]:

            report.append(
                "<tr>"
                f"<td>H{heading['level']}</td>"
                f"<td>{html.escape(heading['text'])}</td>"
                "</tr>"
            )

        report.append(
            "</table>"
        )

    else:

        report.append(
            "<p>No headings found.</p>"
        )

    # --------------------------------------------------------
    # LINKS
    # --------------------------------------------------------

    report.append(
        "<h2>Links</h2>"
    )

    if info["links"]:

        report.append(
            "<table>"
            "<tr>"
            "<th>#</th>"
            "<th>Text</th>"
            "<th>URL</th>"
            "</tr>"
        )

        for index, link in enumerate(
            info["links"],
            start=1
        ):

            link_url = link["url"]

            report.append(
                "<tr>"
                f"<td>{index}</td>"
                f"<td>{html.escape(link['text'])}</td>"
                f"<td>{html.escape(link_url)}</td>"
                "</tr>"
            )

        report.append(
            "</table>"
        )

    else:

        report.append(
            "<p>No links found.</p>"
        )

    report.append(
        "<hr>"
    )

    report.append(
        "<p>"
        "Generated by Telegram Quiz Bot"
        "</p>"
    )

    report.append(
        "</body>"
    )

    report.append(
        "</html>"
    )

    return "\n".join(
        report
    )


# ============================================================
# /htmlreport
# ============================================================

async def htmlreport_command(
    update,
    context
):

    if not await require_admin(update):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n\n"
            "/htmlreport SOURCE\n\n"
            "Example:\n"
            "/htmlreport rajras"
        )

        return

    source_name = (
        context.args[0]
        .strip()
    )

    try:

        await update.message.reply_text(
            "HTML report generate हो रही है..."
        )

        report = build_html_report(
            source_name
        )

        safe_name = re.sub(
            r"[^a-zA-Z0-9_-]+",
            "_",
            source_name
        )

        report_path = (
            DATA_DIR
            / f"{safe_name}_report.html"
        )

        report_path.write_text(
            report,
            encoding="utf-8"
        )

        with report_path.open(
            "rb"
        ) as file:

            await update.message.reply_document(
                document=file,
                filename=(
                    f"{safe_name}_report.html"
                ),
                caption=(
                    f"HTML Report: "
                    f"{source_name}"
                )
            )

    except Exception as e:

        logger.exception(
            "HTML report failed"
        )

        await update.message.reply_text(
            "HTML report generate नहीं हो सकी:\n\n"
            f"{str(e)[:1000]}"
        )
        # ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(update, context):
    logger.exception(
        "Telegram update error",
        exc_info=context.error
    )

    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "Bot में unexpected error आया।\n"
                "कृपया थोड़ी देर बाद दोबारा try करें।"
            )
    except Exception:
        logger.exception(
            "Could not send error message"
        )
        # ============================================================
# BOT STATUS
# ============================================================

async def status_command(update, context):
    user = update.effective_user

    if user:
        
      ensure_user(user)




    conn = db()

    try:
        question_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM questions
            WHERE active = 1
            """
        ).fetchone()[0]

        quiz_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM quizzes
            """
        ).fetchone()[0]

        user_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM users
            """
        ).fetchone()[0]

    finally:
        conn.close()

    await update.effective_message.reply_text(
        "Bot Status\n\n"
        "Status: Online\n"
        f"Questions: {question_count}\n"
        f"Saved Quizzes: {quiz_count}\n"
        f"Users: {user_count}"
    )
    # ============================================================
# APPLICATION
# ============================================================

async def post_init(application):

    logger.info(
        "Starting background workers..."
    )

    application.create_task(
        clone_queue_worker(application)
    )

    logger.info(
        "Clone queue worker started."
    )


def build_application():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable missing."
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # ========================================================
    # USER COMMANDS
    # ========================================================

    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_command
        )
    )

    application.add_handler(
        CommandHandler(
            "quiz",
            quiz_command
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats_command
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    application.add_handler(
        CommandHandler(
            "newquiz",
            newquiz_command
        )
    )

    application.add_handler(
        CommandHandler(
            "quizid",
            quizid_command
        )
    )

    # ========================================================
    # ADMIN - QUESTION MANAGEMENT
    # ========================================================

    application.add_handler(
        CommandHandler(
            "add",
            add_command
        )
    )

    application.add_handler(
        CommandHandler(
            "edit",
            edit_command
        )
    )

    application.add_handler(
        CommandHandler(
            "delete",
            delete_command
        )
    )

    application.add_handler(
        CommandHandler(
            "generate",
            generate_command
        )
    )

    # ========================================================
    # ADMIN - SOURCES / SCRAPING
    # ========================================================

    application.add_handler(
        CommandHandler(
            "scrape",
            scrape_command
        )
    )

    application.add_handler(
        CommandHandler(
            "sources",
            sources_command
        )
    )

    application.add_handler(
        CommandHandler(
            "addsource",
            addsource_command
        )
    )

    application.add_handler(
        CommandHandler(
            "source",
            source_command
        )
    )

    application.add_handler(
        CommandHandler(
            "htmlinfo",
            htmlinfo_command
        )
    )

    application.add_handler(
        CommandHandler(
            "htmlreport",
            htmlreport_command
        )
    )

    # ========================================================
    # PDF / TXT
    # ========================================================

    application.add_handler(
        CommandHandler(
            "pdfimport",
            pdfimport_command
        )
    )

    application.add_handler(
        CommandHandler(
            "txtimport",
            txtimport_command
        )
    )

    application.add_handler(
        CommandHandler(
            "pdfinfo",
            pdfinfo_command
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            document_import_handler
        )
    )

    # ========================================================
    # POLL
    # ========================================================

    application.add_handler(
        CommandHandler(
            "poll2q",
            poll2q_command
        )
    )

    application.add_handler(
        CommandHandler(
            "scrapepoll",
            scrapepoll_command
        )
    )

    application.add_handler(
        MessageHandler(
            filters.POLL,
            process_poll
        )
    )

    # ========================================================
    # CLONE
    # ========================================================

    application.add_handler(
        CommandHandler(
            "clone",
            clone_command
        )
    )

    application.add_handler(
        CommandHandler(
            "clonestatus",
            clone_status_command
        )
    )

    application.add_handler(
        CommandHandler(
            "queue",
            queue_command
        )
    )

    application.add_handler(
        CommandHandler(
            "clearqueue",
            clearqueue_command
        )
    )

    # ========================================================
    # NEGATIVE MARKING
    # ========================================================

    application.add_handler(
        CommandHandler(
            "negmark",
            negmark_command
        )
    )

    application.add_handler(
        CommandHandler(
            "resetpenalty",
            resetpenalty_command
        )
    )

    # ========================================================
    # STOP / CANCEL
    # ========================================================

    application.add_handler(
        CommandHandler(
            "stop",
            stop_command
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_command
        )
    )

    # ========================================================
    # QUIZ CALLBACKS
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            answer_callback,
            pattern=r"^ans:"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            stop_quiz_callback,
            pattern=r"^stopquiz:"
        )
    )
    # ========================================================
    # TEXT INPUT
    #
    # Group 0 -> New Quiz
    # Group 1 -> Add/Edit question
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            newquiz_text_handler
        ),
        group=0
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            pending_text_handler
        ),
        group=1
    )

    # ========================================================
    # ERROR HANDLER
    # ========================================================

    application.add_error_handler(
        error_handler
    )

    return application
    # ============================================================
# HEALTH SERVER
# ============================================================


        # ============================================================
# MAIN
# ============================================================

def main():

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        )
    )

    logger.info(
        "Initializing database..."
    )

    init_db()

    logger.info(
        "Database initialized."
    )

    health_thread = threading.Thread(
        target=run_health_server,
        daemon=True,
        name="health-server"
    )

    health_thread.start()

    logger.info(
        "Health server started on port %s",
        PORT
    )

    application = build_application()

    logger.info(
        "Telegram Quiz Bot starting..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
