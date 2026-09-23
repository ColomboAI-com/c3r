FROM python:3.11-alpine3.24

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN python -m pip uninstall -y jaraco.context wheel
COPY --chown=10001:10001 c3r ./c3r
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "c3r.serve"]
