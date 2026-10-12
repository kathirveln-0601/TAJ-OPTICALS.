# Hosting notes for the TAJ OPTICALS source bundle

This is a platform-neutral source bundle for a small Python storefront. It includes a generic Dockerfile and the complete `static/` asset tree. It is **not a live deployment** and does not include any account credentials.

## Runtime requirements

- Python 3.10 or newer (the included Dockerfile uses Python 3.13).
- The host must run a long-lived Python web process or support the included Dockerfile.
- Attach a persistent writable disk at `/data`. The app stores SQLite at `/data/taj-opticals.sqlite3` and uploads under `/data/uploads`.
- Use one app instance while the app uses SQLite/local uploads. Do not scale horizontally.
- Serve over HTTPS and set `COOKIE_SECURE=1`.

## Environment variables

```text
PORT=8000                    # use the port assigned by the host, if it provides one
COOKIE_SECURE=1              # required behind HTTPS
TAJ_DB_PATH=/data/taj-opticals.sqlite3
TAJ_UPLOAD_DIR=/data/uploads
```

## Docker

Build the image in the project root:

```bash
docker build -t taj-opticals .
```

Run it with a persistent host directory mounted at `/data` (example for local testing):

```bash
mkdir -p ./taj-data
sudo chown -R 10001:10001 ./taj-data
docker run -d --name taj-opticals --restart unless-stopped \
  -p 8000:8000 \
  -e PORT=8000 -e COOKIE_SECURE=1 \
  -e TAJ_DB_PATH=/data/taj-opticals.sqlite3 \
  -e TAJ_UPLOAD_DIR=/data/uploads \
  -v "$(pwd)/taj-data:/data" \
  taj-opticals
```

If a cloud provider mounts `/data` as root-owned, either preconfigure it as writable by UID 10001 or run the container entrypoint as root so it can take ownership and then drop to the unprivileged `app` user before starting the server. Never run the web process itself as root.

## First admin account and verification

Create a fresh admin account from the host's shell/console:

```bash
python3 server.py create-admin
```

For a Docker container:

```bash
docker exec -it taj-opticals python3 /app/server.py create-admin
```

Use a new, unique password that is not shared in chat. Then check `https://YOUR_DOMAIN/api/health`; it should return `{"ok":true,...}`.

## Data and security

The bundle deliberately excludes the local SQLite database, uploads, and `.env` secrets. The schema and seed pages are created at first start. Re-enter or import product records and create the production admin after you provision persistent storage. Back up the database and uploads separately. A host without persistent storage is not suitable for this app.
