FROM python:3.12-slim-bookworm
RUN useradd -m -u 1000 app
WORKDIR /app

# Install system Chromium — works natively on both ARM64 (Pi 5) and x86_64.
# Using the system package avoids Playwright's own Chromium download, which is
# unreliable on ARM64 and adds ~300 MB to the image.
RUN apt-get update && \
    apt-get install -y --no-install-recommends chromium && \
    rm -rf /var/lib/apt/lists/*

# Tell Playwright to skip its own browser download and use the system binary.
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
ENV CHROMIUM_PATH=/usr/bin/chromium

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .
USER app
HEALTHCHECK --interval=30s --timeout=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
