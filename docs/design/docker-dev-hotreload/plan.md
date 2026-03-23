# Docker Dev Hot-Reload Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Fix and harden the Docker development mode so that every frontend file save is reflected instantly in the browser without container restarts.

**Architecture:** A `docker-compose.dev.yml` override already exists and largely works. This plan addresses the remaining issues: the production Dockerfile is still used as the base image (which means a multi-stage build runs before the `command: npm run dev` override can even take effect), the nginx config does not proxy Turbopack's HMR WebSocket, and the `startup.sh` dev command needs a few quality-of-life improvements.

**Tech Stack:** Docker Compose override files, Next.js 15 + Turbopack, nginx WebSocket proxying, Node.js 20 Alpine.

---

## Current State Assessment

### What Already Works ✅

The existing `docker-compose.dev.yml` is **95% correct** and **already functional**:

| Feature | Status | Evidence |
|---------|--------|----------|
| Bind mount `./frontend:/app` | ✅ Working | Compose override mounts it |
| `npm run dev --turbopack` in container | ✅ Working | Logs show `Next.js 15.5.12 (Turbopack) ✓ Ready in 831ms` |
| `CHOKIDAR_USEPOLLING=true` | ✅ Set | In dev override |
| `WATCHPACK_POLLING=true` | ✅ Set | In dev override |
| Named volume for `node_modules` | ✅ Working | `frontend_node_modules:/app/node_modules` prevents host override |
| Named volume for `.next` cache | ✅ Working | `frontend_next_cache:/app/.next` persists build cache |
| File change detection | ✅ Working | Tested: edit file → `○ Compiling / ... ✓ Compiled / in 6s` appears in logs |
| `npm ci` on startup | ✅ Working | Container runs `npm ci --prefer-offline && npm run dev` |
| `setup.sh --docker-dev` entry point | ✅ Working | Documented, functional |

### What Needs Fixing 🔧

1. **Inefficient image build** — The production Dockerfile runs a full `npm run build` + multi-stage copy even though the dev override discards all of that and runs `npm run dev`. This wastes 20–30 seconds on every `docker compose build`.

2. **No nginx HMR proxy** — When accessing via `http://localhost` (port 80, nginx), Turbopack's HMR WebSocket connections fail because nginx doesn't have a dedicated `/_next/` location block with WebSocket upgrade headers. Direct access on `http://localhost:3000` works fine, but nginx access does not get live updates.

3. **No `startup.sh dev` shorthand** — The dev mode requires the long `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d` command or `setup.sh --docker-dev` (which also re-pulls Ollama models). There's no quick `startup.sh dev` subcommand.

4. **`version: "3.9"` deprecation warnings** — Both compose files emit a warning on every command. Cosmetic but noisy.

### Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Breaking production image build | **Low** | Dev Dockerfile is a separate file; production Dockerfile untouched |
| Port conflicts if both prod and dev frontend run | **Low** | Compose uses the same container name `amr_frontend`, so only one can run |
| `node_modules` volume stale after `package.json` change | **Medium** | The `npm ci` in the startup command already handles this; document the edge case for manual volume prune |
| Large initial `npm ci` on first run | **Low** | One-time cost (~14s); the named volume caches it across restarts |
| Turbopack HMR polling CPU usage | **Low** | `WATCHPACK_POLLING=true` has minimal overhead on Linux where inotify also works; it's a fallback for Docker Desktop on Mac/Windows |

---

## Implementation Tasks

### Task 1: Create a lightweight dev Dockerfile (PARALLEL)

**Files:**
- Create: `explorer/frontend/Dockerfile.dev`

**Rationale:** The production Dockerfile is a 3-stage build that compiles a standalone output and runs `node server.js`. In dev mode, the override `command: npm run dev` works, but we still pay for the full production build on every `docker compose build`. A minimal dev Dockerfile skips the build entirely.

**Step 1: Create `Dockerfile.dev`**

```dockerfile
# Dockerfile.dev — lightweight image for development with hot-reload
FROM node:20-alpine
WORKDIR /app

# Only copy package files — source code is bind-mounted at runtime
COPY package.json package-lock.json* ./
RUN npm ci --prefer-offline

# Source code comes from the bind mount — do NOT copy it here
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]
```

**Step 2: Verify it builds**

Run: `cd explorer && docker compose -f docker-compose.yml -f docker-compose.dev.yml build frontend`
Expected: Build completes in ~15s (vs ~45s for production Dockerfile)

**Step 3: Commit**

```bash
git add explorer/frontend/Dockerfile.dev
git commit -m "feat: add lightweight dev Dockerfile for hot-reload"
```

---

### Task 2: Update `docker-compose.dev.yml` to use dev Dockerfile (SERIAL — depends on Task 1)

**Files:**
- Modify: `explorer/docker-compose.dev.yml`

**Step 1: Update the override file**

```yaml
services:
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile.dev
    command: ["sh", "-c", "npm ci --prefer-offline && npm run dev -- --hostname 0.0.0.0 --port 3000"]
    environment:
      - NODE_ENV=development
      - NEXT_PUBLIC_API_URL=http://localhost:8000
      - CHOKIDAR_USEPOLLING=true
      - WATCHPACK_POLLING=true
    volumes:
      - ./frontend:/app
      - frontend_node_modules:/app/node_modules
      - frontend_next_cache:/app/.next

volumes:
  frontend_node_modules:
  frontend_next_cache:
```

Changes from current:
- Added `build.dockerfile: Dockerfile.dev` — uses the lightweight dev image
- Removed `version: "3.9"` to eliminate deprecation warning

**Step 2: Verify the merged config**

Run: `cd explorer && docker compose -f docker-compose.yml -f docker-compose.dev.yml config 2>&1 | grep -A 5 "dockerfile"`
Expected: Shows `dockerfile: Dockerfile.dev`

**Step 3: Test full dev stack**

Run:
```bash
cd explorer
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d frontend
sleep 15
docker logs amr_frontend --tail 5
```
Expected: Logs show `✓ Ready in <Xs>` with Turbopack

**Step 4: Commit**

```bash
git add explorer/docker-compose.dev.yml
git commit -m "feat: use lightweight Dockerfile.dev in dev compose"
```

---

### Task 3: Add nginx HMR WebSocket proxy (PARALLEL)

**Files:**
- Modify: `explorer/infrastructure/nginx/nginx.conf`

**Rationale:** When users access the app through `http://localhost` (nginx on port 80), Turbopack's HMR WebSocket must be proxied correctly. The current `location /` block already has WebSocket headers, but Next.js Turbopack uses `/_next/` paths for HMR that may need explicit handling.

**Step 1: Add `/_next/` location block before the catch-all**

Add this location block **before** the existing `location / { ... }` block:

```nginx
# Next.js Turbopack HMR + static assets
location /_next/ {
    proxy_pass         http://frontend;
    proxy_http_version 1.1;
    proxy_set_header   Upgrade $http_upgrade;
    proxy_set_header   Connection "upgrade";
    proxy_set_header   Host $host;
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;
}
```

**Step 2: Reload nginx**

Run: `docker exec amr_nginx nginx -s reload`

**Step 3: Test HMR through nginx**

Run:
```bash
# Start dev mode
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d frontend
# Access through nginx
curl -s -o /dev/null -w '%{http_code}' http://localhost:80
```
Expected: HTTP 200

**Step 4: Commit**

```bash
git add explorer/infrastructure/nginx/nginx.conf
git commit -m "feat: add nginx proxy for Turbopack HMR WebSocket"
```

---

### Task 4: Add `startup.sh dev` subcommand (PARALLEL)

**Files:**
- Modify: `explorer/startup.sh`

**Step 1: Add `dev` case to the script**

Add this case before the `*)` fallback:

```bash
  dev)
    echo "▸ Starting dev mode (frontend hot reload)..."
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
    echo "✔ Dev mode active. Frontend hot-reload on http://localhost:3000"
    echo "✔ Via nginx: http://localhost"
    echo "✔ Backend:   http://localhost:8000/docs"
    echo ""
    echo "  Edit files in explorer/frontend/ → changes reflect instantly"
    echo "  View logs:  docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f frontend"
    ;;
```

Update the usage line:
```bash
    echo "Usage: $0 {start|dev|rebuild|logs|status|stop}"
```

**Step 2: Test**

Run: `cd explorer && bash startup.sh dev`
Expected: All containers start, frontend shows dev mode message

**Step 3: Commit**

```bash
git add explorer/startup.sh
git commit -m "feat: add startup.sh dev subcommand for hot-reload mode"
```

---

### Task 5: Remove `version` key from compose files (PARALLEL)

**Files:**
- Modify: `explorer/docker-compose.yml`
- Modify: `explorer/docker-compose.dev.yml`

**Step 1: Remove `version: "3.9"` from both files**

The `version` key is obsolete in modern Docker Compose and produces a warning on every command.

**Step 2: Verify no warnings**

Run: `cd explorer && docker compose config --quiet 2>&1`
Expected: No `version is obsolete` warning

**Step 3: Commit**

```bash
git add explorer/docker-compose.yml explorer/docker-compose.dev.yml
git commit -m "chore: remove obsolete version key from compose files"
```

---

## Task Dependency Graph

```
Task 1 (Dockerfile.dev)  ──→  Task 2 (update dev compose)
Task 3 (nginx HMR)       ──→  (independent)
Task 4 (startup.sh dev)  ──→  (independent)
Task 5 (remove version)  ──→  (independent)
```

- **PARALLEL tasks:** Tasks 1, 3, 4, 5 can all be done concurrently
- **SERIAL tasks:** Task 2 must follow Task 1

---

## Verification Checklist

After all tasks are complete, run this full verification:

```bash
cd explorer

# 1. Start dev mode
bash startup.sh dev

# 2. Wait for startup
sleep 20

# 3. Verify frontend container is running dev mode
docker logs amr_frontend --tail 5
# Expected: "✓ Ready in <X>ms" with "Next.js 15.x.x (Turbopack)"

# 4. Verify HTTP access
curl -s -o /dev/null -w '%{http_code}' http://localhost:3000  # → 200
curl -s -o /dev/null -w '%{http_code}' http://localhost:80     # → 200

# 5. Test hot-reload: make change, check logs
echo "// hot-reload test" >> frontend/app/page.tsx
sleep 3
docker logs amr_frontend --tail 5
# Expected: "○ Compiling / ..." then "✓ Compiled / in Xs"

# 6. Revert test change
sed -i '$ d' frontend/app/page.tsx

# 7. Switch back to production mode
docker compose up -d frontend
```

---

## Usage Summary (For End Users)

### Development mode (hot-reload):
```bash
cd explorer
bash startup.sh dev
# Edit any file in frontend/ → changes reflect instantly at http://localhost:3000
```

### Production mode (optimized build):
```bash
cd explorer
bash startup.sh start
```

### Switching between modes:
```bash
bash startup.sh stop     # stop everything
bash startup.sh dev      # start in dev mode
# — or —
bash startup.sh stop
bash startup.sh start    # start in production mode
```

### If `package.json` changes (new dependencies):
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
docker volume rm explorer_frontend_node_modules
bash startup.sh dev
```
