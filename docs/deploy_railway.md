# Deploying Transition Studio on Railway

One Railway service. The root `Dockerfile` runs the backend and the UI together in one container:
the API listens inside it and the Dash UI on Railway's port. `railway.json` tells Railway what to
build and which page to health-check.

## Steps

1. **New Project** → **Deploy from GitHub repo** → `SkanderSoltani/advisor_demo`.
2. **Variables** tab → add:

   | Name | Value |
   |---|---|
   | `JWT_SECRET` | any long random string (e.g. from `openssl rand -hex 32`) |

   Optional: `DEMO_MODE=false`, `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=…` to run the AI
   guide on Claude.
3. **Settings** → **Networking** → **Generate Domain**. If it asks for a port, use **8080**.
4. Open the domain and sign in with `demo@advisor.test` / `demo1234`.

The first start seeds the demo data, which takes about 15–30 s; the health check waits up to 5
minutes.

## Keeping data between deploys (optional)

Without a volume, every redeploy starts again from the data in the repo, which is fine for demos.
To keep changes made in the app (approved transitions, new clients, Custom Models), add a
**Volume** mounted at **`/srv/data`**. Once the volume holds data, redeploys never overwrite it.
To reset, attach a fresh volume.

## Troubleshooting

- **Deploy fails or never becomes healthy:** open the deployment's logs. Look for
  `API ready; starting the UI`, and paste the last lines if it isn't there.
- **Local Docker:** `docker build -t ts . && docker run -p 8080:8080 ts`, then open
  http://localhost:8080. (`docker compose up` still runs the API and UI as two containers.)
