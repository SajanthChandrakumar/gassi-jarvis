# Cloud runtime: Mac capability code is excluded by .dockerignore.
FROM python:3.13-slim

WORKDIR /app

# Install only the cloud dependency set. The tested OpenBB and Uvicorn pins
# are intentionally repeated in requirements-cloud.txt.
COPY requirements-cloud.txt .

RUN pip install --no-cache-dir --disable-pip-version-check -r requirements-cloud.txt \
    && addgroup --system --gid 10001 jarvis \
    && adduser --system --uid 10001 --ingroup jarvis jarvis \
    && mkdir -p /data/chroma /data/sessions /data/device \
    && chown -R jarvis:jarvis /app /data

# The build context deliberately omits Mac executor/security/vision and
# launchd files. Copying only app also keeps local tests, env examples, and
# compatibility launchers out of the image.
COPY --chown=jarvis:jarvis app ./app

EXPOSE 8000

# Never run the cloud service as root.
USER jarvis:jarvis
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
