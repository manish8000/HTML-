import os
import re
import json
import html
import time
import random
import hashlib
import sqlite3
import logging
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from bs4 import BeautifulSoup

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Telegram channel username or ID
# Example:
# CHANNEL_ID=-1001234567890
CHANNEL_ID = os.getenv("CHANNEL_ID", "")

DB_PATH = os.getenv("DB_PATH", "quizbot.db")

PORT = int(os.getenv("PORT", "8080"))

DEFAULT_QUIZ_SIZE = 20

# Internet sources
# Add only sources that allow reuse/API access.
#
# Format:
# {
#     "name": "My Source",
#     "url": "https://example.com/questions"
# }
INTERNET_SOURCES = [
    # {
    #     "name": "Example Source",
    #     "url": "https://example.com/questions"
    # }
]


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# DATABASE
# =========================================================

db_lock = threading.Lock()


def db():
    return sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
        timeout=30,
    )


def init_db():

    with db_lock:
        con = db()

        con.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                question TEXT NOT NULL,

                option_a TEXT NOT NULL,
                option_b TEXT NOT NULL,
                option_c TEXT NOT NULL,
                option_d TEXT NOT NULL,

                correct_option INTEGER NOT NULL,

                exam TEXT DEFAULT 'GENERAL',
                subject TEXT DEFAULT 'GENERAL',

                source_type TEXT DEFAULT 'internet',
                source_name TEXT,
                source_url TEXT,

                pdf_file TEXT,

                question_hash TEXT UNIQUE,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS pdf_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                telegram_file_id TEXT UNIQUE,
                telegram_message_id INTEGER,

                channel_id TEXT,

                file_name TEXT,
                local_path TEXT,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS quiz_history (
                chat_id TEXT NOT NULL,
                question_id INTEGER NOT NULL,

                asked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY(chat_id, question_id)
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                name TEXT,
                url TEXT UNIQUE,

                enabled INTEGER DEFAULT 1,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        con.commit()
        con.close()


# =========================================================
# NORMALIZATION / DUPLICATE DETECTION
# =========================================================

def normalize_text(text):

    text = str(text or "")

    text = text.lower()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    text = re.sub(
        r"[^\w\s\u0900-\u097F]",
        "",
        text,
    )

    return text.strip()


def make_question_hash(
    question,
    options,
):

    data = (
        normalize_text(question)
        + "|"
        + "|".join(
            normalize_text(x)
            for x in options
        )
    )

    return hashlib.sha256(
        data.encode("utf-8")
    ).hexdigest()


# =========================================================
# QUESTION DATABASE
# =========================================================

def add_question(
    question,
    options,
    correct_option,
    exam="GENERAL",
    subject="GENERAL",
    source_type="internet",
    source_name="",
    source_url="",
    pdf_file="",
):

    if len(options) != 4:
        return False, "Exactly 4 options required."

    question = question.strip()

    if not question:
        return False, "Question is empty."

    if correct_option not in [1, 2, 3, 4]:
        return False, "Correct option must be 1-4."

    q_hash = make_question_hash(
        question,
        options,
    )

    with db_lock:

        con = db()

        existing = con.execute(
            """
            SELECT id
            FROM questions
            WHERE question_hash = ?
            """,
            (q_hash,),
        ).fetchone()

        if existing:
            con.close()

            return (
                False,
                f"Duplicate question. Existing ID: {existing[0]}"
            )

        con.execute(
            """
            INSERT INTO questions (
                question,
                option_a,
                option_b,
                option_c,
                option_d,
                correct_option,
                exam,
                subject,
                source_type,
                source_name,
                source_url,
                pdf_file,
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
                exam,
                subject,
                source_type,
                source_name,
                source_url,
                pdf_file,
                q_hash,
            ),
        )

        con.commit()
        con.close()

    return True, "Question added."


# =========================================================
# GET QUESTIONS
# =========================================================

def get_questions(
    exam=None,
    subject=None,
    limit=20,
):

    with db_lock:

        con = db()

        query = """
            SELECT
                id,
                question,
                option_a,
                option_b,
                option_c,
                option_d,
                correct_option,
                exam,
                subject,
                source_type,
                source_name,
                source_url
            FROM questions
            WHERE 1=1
        """

        params = []

        if exam:

            query += " AND exam = ?"

            params.append(exam)

        if subject:

            query += " AND subject = ?"

            params.append(subject)

        query += """
            ORDER BY RANDOM()
            LIMIT ?
        """

        params.append(limit)

        rows = con.execute(
            query,
            params,
        ).fetchall()

        con.close()

    return rows


# =========================================================
# GET QUESTIONS WITHOUT PREVIOUSLY ASKED QUESTIONS
# =========================================================

def get_unused_questions(
    chat_id,
    exam=None,
    subject=None,
    limit=20,
):

    with db_lock:

        con = db()

        query = """
            SELECT
                q.id,
                q.question,
                q.option_a,
                q.option_b,
                q.option_c,
                q.option_d,
                q.correct_option,
                q.exam,
                q.subject,
                q.source_type,
                q.source_name,
                q.source_url
            FROM questions q
            LEFT JOIN quiz_history h
                ON q.id = h.question_id
                AND h.chat_id = ?
            WHERE h.question_id IS NULL
        """

        params = [str(chat_id)]

        if exam:

            query += " AND q.exam = ?"

            params.append(exam)

        if subject:

            query += " AND q.subject = ?"

            params.append(subject)

        query += """
            ORDER BY RANDOM()
            LIMIT ?
        """

        params.append(limit)

        rows = con.execute(
            query,
            params,
        ).fetchall()

        con.close()

    return rows


# =========================================================
# MARK QUESTIONS AS USED
# =========================================================

def mark_questions_used(
    chat_id,
    question_ids,
):

    with db_lock:

        con = db()

        for qid in question_ids:

            con.execute(
                """
                INSERT OR IGNORE INTO quiz_history
                (
                    chat_id,
                    question_id
                )
                VALUES (?, ?)
                """,
                (
                    str(chat_id),
                    qid,
                ),
            )

        con.commit()
        con.close()


# =========================================================
# RESET HISTORY
# =========================================================

def reset_history(chat_id):

    with db_lock:

        con = db()

        con.execute(
            """
            DELETE FROM quiz_history
            WHERE chat_id = ?
            """,
            (str(chat_id),),
        )

        con.commit()
        con.close()


# =========================================================
# PDF SYNC DATABASE
# =========================================================

def pdf_already_synced(file_id):

    with db_lock:

        con = db()

        row = con.execute(
            """
            SELECT id
            FROM pdf_files
            WHERE telegram_file_id = ?
            """,
            (file_id,),
        ).fetchone()

        con.close()

    return row is not None


def save_pdf_record(
    file_id,
    message_id,
    channel_id,
    file_name,
    local_path,
):

    with db_lock:

        con = db()

        con.execute(
            """
            INSERT OR IGNORE INTO pdf_files
            (
                telegram_file_id,
                telegram_message_id,
                channel_id,
                file_name,
                local_path
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                file_id,
                message_id,
                str(channel_id),
                file_name,
                local_path,
            ),
        )

        con.commit()
        con.close()


# =========================================================
# PDF DOWNLOAD
# =========================================================

async def sync_pdf(
    message,
    context,
):

    document = message.document

    if not document:
        return

    if document.mime_type != "application/pdf":
        return

    file_id = document.file_id

    if pdf_already_synced(file_id):

        logger.info(
            "PDF already synced: %s",
            document.file_name,
        )

        return

    pdf_dir = Path("synced_pdfs")

    pdf_dir.mkdir(
        exist_ok=True,
    )

    safe_name = re.sub(
        r"[^a-zA-Z0-9._-]",
        "_",
        document.file_name or "file.pdf",
    )

    timestamp = int(time.time())

    local_path = (
        pdf_dir
        / f"{timestamp}_{safe_name}"
    )

    telegram_file = await context.bot.get_file(
        file_id
    )

    await telegram_file.download_to_drive(
        custom_path=str(local_path)
    )

    channel_id = (
        message.chat.id
        if message.chat
        else ""
    )

    save_pdf_record(
        file_id=file_id,
        message_id=message.message_id,
        channel_id=channel_id,
        file_name=document.file_name,
        local_path=str(local_path),
    )

    logger.info(
        "PDF synced: %s",
        local_path,
    )


# =========================================================
# CHANNEL PDF HANDLER
# =========================================================

async def channel_pdf_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.channel_post

    if not message:
        return

    await sync_pdf(
        message,
        context,
    )


# =========================================================
# INTERNET QUESTION SOURCE
# =========================================================

def fetch_source(url):

    headers = {
        "User-Agent":
            "QuizBot/1.0 educational question importer"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=20,
    )

    response.raise_for_status()

    return response.text


# =========================================================
# GENERIC HTML QUESTION PARSER
#
# Expected HTML structure:
#
# <div class="question">
#   <div class="question-text">...</div>
#   <div class="option">A ...</div>
#   <div class="option">B ...</div>
#   <div class="option">C ...</div>
#   <div class="option">D ...</div>
#   <div class="answer">2</div>
# </div>
#
# Change selectors for your actual source.
# =========================================================

def parse_generic_questions(
    html_text,
):

    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    questions = []

    blocks = soup.select(
        ".question"
    )

    for block in blocks:

        q_node = block.select_one(
            ".question-text"
        )

        option_nodes = block.select(
            ".option"
        )

        answer_node = block.select_one(
            ".answer"
        )

        if not q_node:
            continue

        if len(option_nodes) < 4:
            continue

        if not answer_node:
            continue

        question = q_node.get_text(
            " ",
            strip=True,
        )

        options = [
            x.get_text(
                " ",
                strip=True,
            )
            for x in option_nodes[:4]
        ]

        answer_text = answer_node.get_text(
            " ",
            strip=True,
        )

        match = re.search(
            r"[1-4]",
            answer_text,
        )

        if not match:
            continue

        correct = int(
            match.group()
        )

        questions.append(
            {
                "question": question,
                "options": options,
                "correct_option": correct,
            }
        )

    return questions


# =========================================================
# IMPORT ONE INTERNET SOURCE
# =========================================================

def import_internet_source(
    name,
    url,
    exam="GENERAL",
    subject="GENERAL",
):

    logger.info(
        "Importing source: %s",
        url,
    )

    try:

        page = fetch_source(url)

        questions = parse_generic_questions(
            page
        )

    except Exception as e:

        logger.exception(
            "Source import failed"
        )

        return {
            "success": False,
            "error": str(e),
            "added": 0,
            "duplicates": 0,
        }

    added = 0
    duplicates = 0

    for item in questions:

        ok, message = add_question(
            question=item["question"],
            options=item["options"],
            correct_option=item["correct_option"],
            exam=exam,
            subject=subject,
            source_type="internet",
            source_name=name,
            source_url=url,
        )

        if ok:
            added += 1
        else:
            if "Duplicate" in message:
                duplicates += 1

    return {
        "success": True,
        "found": len(questions),
        "added": added,
        "duplicates": duplicates,
    }


# =========================================================
# ADMIN INTERNET SYNC
# =========================================================

async def syncinternet_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not INTERNET_SOURCES:

        await update.message.reply_text(
            "INTERNET_SOURCES में कोई source configured नहीं है."
        )

        return

    await update.message.reply_text(
        "Internet sources sync शुरू हो रहा है..."
    )

    total_added = 0
    total_duplicates = 0

    for source in INTERNET_SOURCES:

        result = import_internet_source(
            name=source["name"],
            url=source["url"],
        )

        total_added += result.get(
            "added",
            0,
        )

        total_duplicates += result.get(
            "duplicates",
            0,
        )

    await update.message.reply_text(
        "Internet Sync Complete\n\n"
        f"New Questions: {total_added}\n"
        f"Duplicates skipped: {total_duplicates}"
    )


# =========================================================
# /START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "Quiz Bot Online\n\n"
        "/quiz - Quiz शुरू करें\n"
        "/stats - Question statistics\n"
        "/reset - अपनी quiz history reset करें\n"
        "/syncinternet - Internet sources sync करें\n"
        "/help - Commands"
    )


# =========================================================
# /QUIZ
# =========================================================

async def quiz_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    try:

        count = int(
            context.args[0]
        ) if context.args else DEFAULT_QUIZ_SIZE

    except ValueError:

        count = DEFAULT_QUIZ_SIZE

    count = max(
        1,
        min(count, 100),
    )

    questions = get_unused_questions(
        chat_id=chat_id,
        limit=count,
    )

    # If previous questions exhausted,
    # reset history and start a new cycle.

    if len(questions) < count:

        reset_history(
            chat_id
        )

        questions = get_unused_questions(
            chat_id=chat_id,
            limit=count,
        )

    if not questions:

        await update.message.reply_text(
            "Database में अभी कोई question available नहीं है."
        )

        return

    mark_questions_used(
        chat_id,
        [row[0] for row in questions],
    )

    random.shuffle(
        questions
    )

    await update.message.reply_text(
        f"Quiz शुरू हो रहा है.\n"
        f"Questions: {len(questions)}"
    )

    for index, row in enumerate(
        questions,
        start=1,
    ):

        (
            qid,
            question,
            a,
            b,
            c,
            d,
            correct,
            exam,
            subject,
            source_type,
            source_name,
            source_url,
        ) = row

        options = [
            a,
            b,
            c,
            d,
        ]

        # Shuffle options while preserving
        # correct answer.

        correct_text = options[
            correct - 1
        ]

        random.shuffle(
            options
        )

        new_correct = (
            options.index(
                correct_text
            ) + 1
        )

        text = (
            f"<b>Q{index}.</b> "
            f"{html.escape(question)}\n\n"
            f"1. {html.escape(options[0])}\n"
            f"2. {html.escape(options[
