FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY c3r ./c3r
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 c3r
USER c3r
EXPOSE 8080
CMD ["python", "-m", "c3r.serve"]
