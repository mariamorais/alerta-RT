FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# SAPCAR must be downloaded manually from SAP (requires S-User) and placed at ./bin/SAPCAR
# Expected mount or build-time copy:
COPY bin/SAPCAR /usr/local/bin/SAPCAR
RUN chmod +x /usr/local/bin/SAPCAR || true

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
