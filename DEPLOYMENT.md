# Deployment

Talkshow ships as a container image to the kibble
registry on every `git tag v*`. To deploy:

## Pre-flight checklist

- [ ] Public hostname for talkshow (eg.
      `talkshow.cobd.ca`) with an A record pointing at
      the host that will run it.
- [ ] TLS terminated by a reverse proxy (nginx /
      Traefik / Caddy). Talkshow speaks plain HTTP on
      `:8000`.
- [ ] An Azure Cognitive Services Speech resource —
      subscription key + region.
- [ ] Persistent volume for the audio cache
      (`/app/cache` inside the container). Optional but
      recommended; without it every container restart
      starts the cache fresh.

## Image distribution

`.github/workflows/release.yml` builds and pushes a
container image to the kibble registry on every
`git tag v*`. The registry is anonymous-push for the
`cobdfamily/*` path and speaks plain HTTP, so no login
secrets are required.

```sh
git tag -a v0.4.1 -m "Release 0.4.1"
git push origin v0.4.1
```

Within a couple of minutes the workflow lands two image
tags at:

- `kibble.apps.blindhub.ca/cobdfamily/talkshow:0.4.1`
- `kibble.apps.blindhub.ca/cobdfamily/talkshow:latest`

## Configure

Talkshow reads config from environment variables (no
yaml file). The `MSTTS_*` prefix matches the bundled
Azure TTS plugin.

```sh
# Azure Speech credentials (REQUIRED for the bundled engine)
MSTTS_SUBSCRIPTION_KEY=<your-key>
MSTTS_REGION=<azure-region>           # eg. eastus

# Defaults applied when /v1/speak doesn't override
MSTTS_DEFAULT_VOICE=en-US-EmmaMultilingualNeural
MSTTS_DEFAULT_LANGUAGE=en-US
MSTTS_DEFAULT_RATE=0%
MSTTS_DEFAULT_PITCH=0%

# Optional: where the audio cache lives. Defaults to
# /app/cache inside the container.
TALKSHOW_CACHE_DIR=/app/cache
```

## Run

Production-shaped `docker-compose.yml`:

```yaml
services:
  talkshow:
    image: kibble.apps.blindhub.ca/cobdfamily/talkshow:0.4.0
    container_name: talkshow
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"      # bind to localhost,
                                   # reverse-proxy to it
    environment:
      MSTTS_SUBSCRIPTION_KEY: ${MSTTS_SUBSCRIPTION_KEY}
      MSTTS_REGION: ${MSTTS_REGION:-eastus}
      MSTTS_DEFAULT_VOICE: ${MSTTS_DEFAULT_VOICE:-en-US-EmmaMultilingualNeural}
      MSTTS_DEFAULT_LANGUAGE: ${MSTTS_DEFAULT_LANGUAGE:-en-US}
    volumes:
      - ./cache:/app/cache         # persist audio cache
```

Bring it up:

```sh
mkdir -p /opt/talkshow/cache
chmod 700 /opt/talkshow/cache
cd /opt/talkshow
docker compose pull
docker compose up -d
docker compose logs -f talkshow
```

Behind your TLS reverse proxy, route
`https://talkshow.cobd.ca/*` to `127.0.0.1:8000`.

## Verify

```sh
# Liveness
curl -fsS https://talkshow.cobd.ca/

# Plugin discovery
curl -fsS https://talkshow.cobd.ca/v1/plugins | jq

# Synthesise a quick test (requires Azure key configured)
curl -fsS \
  "https://talkshow.cobd.ca/v1/speak?text=hello+world" \
  > /tmp/talkshow-test.wav
file /tmp/talkshow-test.wav    # should report RIFF WAV
```

## Routine operations

### Upgrading

```sh
# On the dev host -- cut and push the tag.
git tag -a v0.4.1 -m "Release 0.4.1"
git push origin v0.4.1
# CI builds and pushes the image.

# On the deploy host -- pin the new tag and restart.
sed -i 's|talkshow:[^ ]*|talkshow:0.4.1|' docker-compose.yml
docker compose pull
docker compose up -d --no-deps talkshow
```

### Backups

What must persist:

- `cache/` — the rendered audio. Losing it costs CPU
  (re-synthesis) but no correctness. Optional.
- `.env` — has the Azure subscription key. Treat as a
  production secret.

What is safe to lose:

- Everything else. Talkshow is stateless aside from the
  audio cache.
