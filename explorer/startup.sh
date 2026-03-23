#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Site Explorer — Startup Script
# ──────────────────────────────────────────────────────────────────────────────
# Usage:
#   ./startup.sh          → Start all containers (production)
#   ./startup.sh dev      → Start in dev mode (frontend hot-reload)
#   ./startup.sh rebuild  → Rebuild & restart backend + frontend
#   ./startup.sh logs     → Tail logs from all containers
#   ./startup.sh status   → Show container status
#   ./startup.sh stop     → Stop all containers
# ──────────────────────────────────────────────────────────────────────────────

cd "$(dirname "$0")" || exit 1

case "${1:-start}" in
  start)
    echo "▸ Starting all containers..."
    docker compose up -d
    echo "✔ Frontend: http://localhost:3000"
    echo "✔ Backend:  http://localhost:8000/docs"
    echo "✔ Ollama:   http://localhost:11435"
    ;;

  dev)
    echo "▸ Starting in dev mode (frontend hot-reload)..."
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
    echo ""
    echo "✔ Frontend (direct):  http://localhost:3000  ← use this for dev"
    echo "✔ Via nginx:          http://localhost"
    echo "✔ Backend API docs:   http://localhost:8000/docs"
    echo ""
    echo "  Edit any file in frontend/ → browser updates automatically"
    echo "  View frontend logs: docker logs amr_frontend -f"
    ;;

  rebuild)
    echo "▸ Rebuilding backend + frontend..."
    docker compose build backend frontend
    echo "▸ Restarting containers..."
    docker compose up -d --force-recreate --no-deps backend frontend
    echo "✔ Done. Frontend: http://localhost:3000"
    ;;

  logs)
    docker compose logs -f --tail 50
    ;;

  status)
    docker compose ps
    ;;

  stop)
    echo "▸ Stopping all containers..."
    docker compose down
    echo "✔ Stopped."
    ;;

  *)
    echo "Usage: $0 {start|dev|rebuild|logs|status|stop}"
    exit 1
    ;;
esac
