FROM python:3.11-slim
WORKDIR /app
ARG INSTALL_SEMANTIC=0
COPY requirements.txt requirements-semantic.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_SEMANTIC" = 1 ]; then pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir -r requirements-semantic.txt; fi
COPY integrity integrity
COPY migrations migrations
RUN useradd --no-create-home --uid 10001 integrity
USER integrity
CMD ["uvicorn", "integrity.api:app", "--host", "0.0.0.0", "--port", "8000"]
