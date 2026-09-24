FROM python:3.11-alpine3.24@sha256:cd04730b8511def3fbf14204d66a0c1536f290b8e896ed5a94cd64cb15ac1356

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN python -m pip uninstall -y setuptools wheel jaraco.context
COPY --chown=10001:10001 c3r ./c3r
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "c3r.serve"]

