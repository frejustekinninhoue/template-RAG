# Frontend Separé - Intégration Next.js (Vstorm) + Backend production-ai-app

## Objectif
Utiliser un frontend Next.js (issu de `full-stack-ai-agent-template`) dans un dépôt séparé, branché sur le backend FastAPI `production-ai-app`.

## Architecture cible
- Repo A: frontend Next.js (Vstorm généré)
- Repo B: backend FastAPI (ce projet)
- Communication: HTTP + SSE via `http://backend:8000/api/v1/...`

## Variables frontend à configurer
Dans le repo frontend:
- `NEXT_PUBLIC_API_URL=http://localhost:8000`
- `BACKEND_URL=http://localhost:8000` (ou `http://backend:8000` en réseau docker)
- `NEXT_PUBLIC_WS_URL=ws://localhost:8000`
- `NEXT_PUBLIC_AUTH_ENABLED=true`

## Endpoints backend compatibles ajoutés
- `GET /api/v1/health`
- `GET /api/v1/agent/models`
- `GET /api/v1/rag/supported-formats`
- `GET /api/v1/rag/collections`
- `GET /api/v1/rag/collections/{name}/info`
- `GET /api/v1/rag/documents`
- `POST /api/v1/rag/search`
- `POST /api/v1/rag/collections/{name}/ingest`
- `POST /api/v1/knowledge-bases/upload`
- `POST /api/v1/files/upload`
- `POST /api/v1/query/stream`

## Dockerfiles frontend (repo séparé)
Templates fournis dans ce repo backend:
- `integration/frontend-separate/Dockerfile`
- `integration/frontend-separate/Dockerfile.dev`
- `integration/frontend-separate/docker-compose.frontend.yml`

Copier ces fichiers dans le repo frontend puis adapter les chemins `context`.

## Lancer Backend + Frontend

### Option A - Démarrage simple (recommandé pour dev)

#### 1) Backend
Dans `production-ai-app`:
```bash
cd .~/production-ai-app
cp .env.example .env
# Renseigner au minimum: JWT_SECRET, PAGEINDEX_API_KEY, GOOGLE_API_KEY ou OPENAI_API_KEY/GROQ_API_KEY

docker compose up --build
```

Backend disponible sur:
- `http://localhost:8000/health`
- `http://localhost:8000/api/v1/health`

#### 2) Frontend (repo séparé)
Dans le repo frontend Vstorm généré:
```bash
cd /path/to/your/frontend-repo
cp .env.example .env.local
```

Mettre dans `.env.local`:
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
NEXT_PUBLIC_AUTH_ENABLED=true
```

Lancer en local:
```bash
npm install
npm run dev
```

Frontend disponible sur `http://localhost:3000`.

### Option B - Démarrage Docker des 2 repos

1. Copier `integration/frontend-separate/docker-compose.frontend.yml` dans un dossier d'intégration.
2. Remplacer les placeholders:
- `/path/to/your/frontend-repo`
- `/path/to/production-ai-app`

3. Lancer:
```bash
docker compose -f docker-compose.frontend.yml up --build
```

## Smoke test rapide
1. Vérifier backend:
```bash
curl http://localhost:8000/api/v1/health
```

2. Vérifier collections RAG:
```bash
curl -H "Authorization: Bearer <JWT>" http://localhost:8000/api/v1/rag/collections
```

3. Depuis l'UI:
- Upload d'un PDF
- Vérifier apparition dans la liste documents
- Lancer une recherche RAG

## JWT de test (dev)
Le middleware attend un Bearer JWT signé avec `JWT_SECRET`.
Exemple payload minimal:
```json
{"sub":"dev-user-1"}
```

## Stratégie +80 périmètres
Pour répondre aux contraintes de scalabilité documentaire:
- Indexation batch: `prep/index_docs.py` avec `--pdf-dir`, `--recursive`, `--workers`
- Métadonnées de périmètre: `collection`, `domain`, `source`, `tags`
- Filtrage runtime: `RETRIEVAL_DOC_IDS`, `RETRIEVAL_DOMAINS`, `RETRIEVAL_MAX_DOCS`
- Prochaine étape recommandée: routeur sémantique + ACL stricte par périmètre (RBAC)

## Limites actuelles
- Streaming `/api/v1/query/stream` est SSE basé sur réponse finale (pas token streaming natif provider).
- Compatibilité API focalisée sur RAG/upload/stream; pas toutes les routes SaaS Vstorm.
