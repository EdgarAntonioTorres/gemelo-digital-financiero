#!/usr/bin/env bash
# t021 — Inicializa el repo local con la estrategia GitFlow (main + develop).
# Uso:
#   1) Crea el repo vacío en GitHub (sin README/licencia).
#   2) ./setup_git.sh <url-del-remoto>
set -e

REMOTE_URL="$1"
if [ -z "$REMOTE_URL" ]; then
  echo "Uso: ./setup_git.sh <url-del-remoto-github>"
  exit 1
fi

git init
git add .
git commit -m "chore: bootstrap del repo (estructura, docker-compose, CI) — t021-t024"
git branch -M main
git remote add origin "$REMOTE_URL"
git push -u origin main

git checkout -b develop
git push -u origin develop

echo "Listo. Ramas main y develop creadas y pusheadas."
echo "Para trabajar una tarea nueva: git checkout develop && git checkout -b feature/<nombre>"
