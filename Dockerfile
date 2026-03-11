FROM python:3.11-slim

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY data/     ./data/

# Ensure data dir exists (for SQLite DB)
RUN mkdir -p data

# Non-root user
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# APP_API_KEY must be set at runtime:
#   docker run -e APP_API_KEY=your-secret -p 8000:8000 judgment-interest
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
