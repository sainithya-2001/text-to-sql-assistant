# Text-to-SQL assistant: Streamlit UI on :8501, CLI available as `t2s`.
#
#   docker build -t text-to-sql .
#   docker run --rm -p 8501:8501 --env-file .env text-to-sql
#   docker run --rm --env-file .env text-to-sql t2s ask "How many orders were placed in 1995?"
#
# The TPC-H database and the embedding model are built into the image, so the container needs network
# access only for the Claude API.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    T2S_HOME=/app \
    T2S_MODEL_CACHE=/app/data/models \
    HF_HUB_DISABLE_PROGRESS_BARS=1

WORKDIR /app

# Dependencies first for layer caching
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -e ".[embed,ui]"

COPY app ./app
COPY eval ./eval
COPY glossary.yaml ./

# Bake the data and the embedding model into the image
RUN t2s init-db \
 && python -c "from text_to_sql.schema.embed import FastEmbedder; FastEmbedder().embed_query('warm up')"

RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "app/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
