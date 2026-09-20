FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# OCRmyPDF + Tesseract (Hindi + English) + Ghostscript
RUN apt-get update && apt-get install -y --no-install-recommends \
        ocrmypdf \
        tesseract-ocr \
        tesseract-ocr-hin \
        tesseract-ocr-eng \
        ghostscript \
        qpdf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Health server (Flask) is on this port; set the Koyeb service port to 8000.
EXPOSE 8000

CMD ["python", "bot.py"]
