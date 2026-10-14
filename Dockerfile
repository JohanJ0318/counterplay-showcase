# Counterplay in one image: the web app by default, the parse worker with
# `python -m app.worker` as the command (deploy/docker-compose.yml runs both).
#
# Production is still the Hetzner box with systemd (deploy/README.md). This
# image is for a staging copy and for anyone who wants the app running in one
# command; CI builds it and checks it answers on every push
# (.github/workflows/docker.yml).
#
# State lives in /data (the database and every uploaded demo), a volume, never
# in the image. Secrets come in as environment variables, never baked in.

FROM python:3.12-slim

# LightGBM's wheel links against OpenMP.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# Never root, same as the systemd units.
RUN useradd --create-home --uid 1000 counterplay
WORKDIR /srv/counterplay

# Dependencies first, so a code change does not reinstall pandas.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY counterplay ./counterplay
COPY site ./site

ENV COUNTERPLAY_DB=/data/counterplay.db \
    COUNTERPLAY_DEMOS=/data/demos \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data/demos && chown -R counterplay:counterplay /data
VOLUME /data
USER counterplay

EXPOSE 8000
# HEAD answers like GET (HeadAsGet in app/main.py), so a plain request works.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4)"

# Migrations run on startup (db.init), so a new image upgrades the schema.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
