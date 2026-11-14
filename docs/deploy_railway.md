# Deploying Transition Studio on Railway

Two Railway services from the same GitHub repo, plus one volume:

| Service | Builds from | Public? | What it is |
|---|---|---|---|
| **api** | `/Dockerfile` (config `/railway.json`) | optional (for `/docs`) | FastAPI backend, SQLite database and data files on a volume |
| **web** | `/frontend/Dockerfile` (config `/frontend/railway.json`) | **yes**: the URL people open | Dash front end; talks to `api` over Railway's private network |

Synthetic data only. Memory measured locally: api ≈ 300 MB, web ≈ 125 MB, so the Hobby plan is
enough.

## 1. Push the code to GitHub

Railway deploys from the GitHub repo (`SkanderSoltani/advisor_demo`). Everything below must be
committed and pushed first: the Dockerfiles, `railway.json` files and `scripts/start_api.sh`.

## 2. Create the project and the **api** service

1. Railway → **New Project** → **Deploy from GitHub repo** → pick the repo. Rename the service to
   `api` (the web service's variables below refer to it by that name).
2. **Settings**
   - Root Directory: `/` (default)
   - Config file path: `/railway.json`. This makes it build the root `Dockerfile` and wait for
     `/health`.
3. **Volume**: right-click the service → **Attach volume** → mount path **`/srv/data`**.
   This keeps the database, the client book (`book.json`), the model catalog (including Custom
   Models saved in the Model Builder) and recorded transitions across redeploys.
4. **Variables**

   | Variable | Value |
   |---|---|
   | `PORT` | `8000` |
   | `JWT_SECRET` | a long random string (e.g. from `openssl rand -hex 32`) |
   | `DEMO_MODE` | `true` (offline rule-based guide), or `false` with the two lines below |
   | `LLM_PROVIDER` | `anthropic` (optional: Claude for the AI guide) |
   | `ANTHROPIC_API_KEY` | your key (optional; set it as a Railway variable, never commit it) |

5. Deploy. On first start the container copies the starter data into the empty volume, seeds the
   database from `book.json`, renders the sample statement PDFs and starts the API. That takes
   about 15–30 s, and the health check waits up to 5 minutes. Later starts skip the seeding.

## 3. Add the **web** service

1. In the same project: **New** → **GitHub Repo** → the same repo. Rename it `web`.
2. **Settings**
   - Root Directory: **`/frontend`**
   - Config file path: **`/frontend/railway.json`**
   - Networking → **Generate Domain**. That URL is the app.
3. **Variables**

   | Variable | Value |
   |---|---|
   | `API_BASE_URL` | `http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000/api/v1` |
   | `USE_MOCKS` | `false` |

   `${{api.RAILWAY_PRIVATE_DOMAIN}}` is filled in by Railway, so type it literally. The API
   listens on IPv6 as well (`--host ::`), which Railway's private network needs.
4. Deploy, open the generated domain and sign in with `demo@advisor.test` / `demo1234`.

## How the data behaves

- The volume is the master copy once deployed. Redeploys never overwrite files in it; they only
  add starter files that are missing. Approving a transition, adding clients or saving Custom
  Models persists across redeploys.
- **Reset to the repo's data:** delete the volume's files and redeploy. One way is to attach a new
  volume. The app then seeds again from the `book.json` and catalog in the repo.
- Without a volume, the app still works, but every redeploy starts again from the repo's data.

## Troubleshooting

- **web shows "Couldn't reach the server"**: check `API_BASE_URL` (service name `api`, port
  `8000`) and that `PORT=8000` is set on the api service.
- **api health check fails on the first deploy**: look at the deploy logs for the seeding step.
  It prints "Book file: … totals check: OK" when the database is ready.
- **Changed the starter data in the repo, but production doesn't show it**: expected, because the
  volume wins. Reset as described above.
- **Local Docker (same images):** `docker compose up --build`, then open http://localhost:8050.
