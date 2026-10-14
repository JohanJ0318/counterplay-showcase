# A staging copy on a free cloud machine

Production stays the Hetzner box (deploy/README.md). This is a second copy,
in Docker, on Google Cloud's free tier, for trying a migration or a page
change before it touches real coaches.

**It never gets the production database.** That file holds real accounts,
share tokens and coaches' matches. A staging copy starts empty: sign up on
it, upload a demo or two of your own, and use that.

## What you need

* A Google Cloud account (free tier; it asks for a card but the machine
  below costs nothing). AWS works the same way with a t3.micro.
* A GitHub personal access token with only `read:packages`, so the machine
  can pull the private image. GitHub, Settings, Developer settings, Tokens
  (classic). Keep it out of chat and out of the repository.
* Optional: a DNS record `staging.counterplaycs.com` pointing at the
  machine. Logging in needs HTTPS (cookies are Secure), and Caddy can only
  get a certificate for a real name.

## 1. The machine

Compute Engine, Create instance:

* Machine type **e2-micro** in us-west1, us-central1 or us-east1 (the
  always-free regions), Ubuntu 24.04, 30GB standard disk.
* Allow HTTP and HTTPS traffic.

1GB of memory runs the web app and Caddy. It cannot parse demos (the worker
wants up to 3GB), so on this machine run without the worker, below. An
e2-small (2GB, a few dollars a month) parses small demos.

## 2. Docker

SSH in from the console, then:

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER && newgrp docker
```

## 3. The image

CI builds and pushes it on every push to master
(.github/workflows/docker.yml). Log the machine in to pull it, pasting the
token when asked:

```bash
docker login ghcr.io -u JohanJ0318
```

## 4. Run it

Copy `deploy/docker-compose.yml`, `deploy/Caddyfile.staging` and
`deploy/staging.env.example` to the machine (or clone the repository), then:

```bash
cp staging.env.example staging.env
export STAGING_DOMAIN=staging.counterplaycs.com
docker compose up -d web caddy          # e2-micro: no worker
docker compose up -d                    # 2GB or more: with the worker
```

Check it: `curl -I https://staging.counterplaycs.com/` answers 200, and
`docker compose logs web` shows the migrations running.

## 5. Updating it

```bash
docker compose pull && docker compose up -d
```

## What this is good for

* A migration runs on staging first, against a database with real shape
  and no real people.
* A page change is checked on a phone at a real address before the deploy.
* Nothing here changes how production deploys; that is still deploy.sh.
