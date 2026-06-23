# Endpoint Mapping - Vstorm Frontend -> production-ai-app Backend

Référence frontend scannée:
- `full-stack-ai-agent-template/template/{{cookiecutter.project_slug}}/frontend/src/app/api/**/*.ts`
- hooks chat (WebSocket): `frontend/src/hooks/use-chat.ts`

## Légende
- `OK`: endpoint attendu par le frontend et implémenté côté backend actuel.
- `PARTIEL`: endpoint proche existant mais contrat incomplet.
- `MISSING`: endpoint non implémenté côté backend actuel.

## 1) Endpoints compatibles (`OK`)

| Frontend expected | Méthode(s) | Backend actuel | Statut | Notes |
|---|---|---|---|---|
| `/api/v1/health` | GET | `/api/v1/health` | OK | health public |
| `/api/v1/agent/models` | GET | `/api/v1/agent/models` | OK | modèles low/high |
| `/api/v1/rag/supported-formats` | GET | `/api/v1/rag/supported-formats` | OK | actuellement `pdf` |
| `/api/v1/rag/collections` | GET | `/api/v1/rag/collections` | OK | liste collections |
| `/api/v1/rag/collections` | POST | `/api/v1/rag/collections` | OK | create collection |
| `/api/v1/rag/collections/{name}` | POST | `/api/v1/rag/collections/{name}` | OK | create collection by path |
| `/api/v1/rag/collections/{name}` | DELETE | `/api/v1/rag/collections/{name}` | OK | delete collection |
| `/api/v1/rag/collections/{name}/info` | GET | `/api/v1/rag/collections/{name}/info` | OK | infos collection |
| `/api/v1/rag/collections/{name}/documents` | GET | `/api/v1/rag/collections/{name}/documents` | OK | docs par collection |
| `/api/v1/rag/collections/{name}/documents/{documentId}` | DELETE | `/api/v1/rag/collections/{name}/documents/{documentId}` | OK | suppression doc |
| `/api/v1/rag/documents` | GET | `/api/v1/rag/documents` | OK | liste globale documents |
| `/api/v1/rag/search` | POST | `/api/v1/rag/search` | OK | body `query`, `collection_names`, `top_k` |
| `/api/v1/rag/collections/{name}/ingest` | POST | `/api/v1/rag/collections/{name}/ingest` | OK | upload PDF + index PageIndex |
| `/api/v1/rag/status/stream` | GET | `/api/v1/rag/status/stream` | OK | SSE statut RAG |
| `/api/v1/knowledge-bases/upload` | POST | `/api/v1/knowledge-bases/upload` | OK | alias upload KB |
| `/api/v1/files/upload` | POST | `/api/v1/files/upload` | OK | upload fichier brut |

## 2) Endpoints partiels (`PARTIEL`)

| Frontend expected | Méthode(s) | Endpoint actuel proche | Statut | Gap |
|---|---|---|---|---|
| `/api/v1/rag/documents/{docId}` | DELETE | aucun | PARTIEL | suppression doc globale non implémentée |
| `/api/v1/rag/documents/{docId}/download` | GET | aucun | PARTIEL | téléchargement doc source non implémenté |
| Streaming chat temps réel Vstorm | WS | `/api/v1/query/stream` (SSE) | PARTIEL | Vstorm attend WS `/api/v1/ws/agent` |

## 3) Endpoints absents (`MISSING`)

### 3.1 Chat / Conversations / Sessions
- `/api/v1/ws/agent` (WebSocket principal chat Vstorm)
- `/api/v1/conversations`
- `/api/v1/conversations/{id}`
- `/api/v1/conversations/{id}/messages`
- `/api/v1/conversations/{id}/shares`
- `/api/v1/conversations/{id}/shares/{shareId}`
- `/api/v1/conversations/shared-with-me`
- `/api/v1/conversations/export`
- `/api/v1/conversations/tool-stats`
- `/api/v1/sessions`
- `/api/v1/sessions/{id}`

### 3.2 RAG Sync / Connecteurs avancés
- `/api/v1/rag/sync/local`
- `/api/v1/rag/sync/{syncId}`
- `/api/v1/rag/sync/sources`
- `/api/v1/rag/sync/sources/{sourceId}`
- `/api/v1/rag/sync/sources/{sourceId}/trigger`
- `/api/v1/rag/sync/connectors`

### 3.3 Auth / Users / Orgs / KB
- `/api/v1/auth/login`
- `/api/v1/auth/register`
- `/api/v1/auth/refresh`
- `/api/v1/auth/logout`
- `/api/v1/auth/me`
- `/api/v1/auth/password-reset/request`
- `/api/v1/auth/password-reset/confirm`
- `/api/v1/auth/magic-link/request`
- `/api/v1/auth/magic-link/verify`
- `/api/v1/users/me`
- `/api/v1/users/me/avatar`
- `/api/v1/users/avatar/{userId}`
- `/api/v1/orgs`
- `/api/v1/orgs/{id}`
- `/api/v1/orgs/{id}/members`
- `/api/v1/orgs/{id}/members/{userId}`
- `/api/v1/orgs/{id}/invitations`
- `/api/v1/kb`
- `/api/v1/kb/{id}`
- `/api/v1/kb/{id}/documents`
- `/api/v1/kb/{id}/documents/{docId}`
- `/api/v1/kb/{id}/sync-sources`
- `/api/v1/kb/{id}/sync-sources/{sourceId}`
- `/api/v1/kb/{id}/sync-sources/{sourceId}/trigger`
- `/api/v1/kb/{id}/sync-sources/connectors`
- `/api/v1/invitations/{token}`
- `/api/v1/invitations/{token}/accept`
- `/api/v1/me/slash-commands`
- `/api/v1/me/slash-commands/{id}`
- `/api/v1/me/slash-commands/custom`
- `/api/v1/me/slash-commands/builtin`

### 3.4 Admin / Billing / Contact
- `/api/v1/admin/stats`
- `/api/v1/admin/users`
- `/api/v1/admin/users/{userId}`
- `/api/v1/admin/users/{userId}/impersonate`
- `/api/v1/admin/conversations`
- `/api/v1/admin/conversations/{id}`
- `/api/v1/admin/conversations/users`
- `/api/v1/admin/ratings`
- `/api/v1/admin/ratings/summary`
- `/api/v1/admin/ratings/export`
- `/api/v1/admin/stripe-events`
- `/api/v1/billing/checkout`
- `/api/v1/billing/portal`
- `/api/v1/billing/me/...`
- `/api/v1/contact`

## 4) Roadmap recommandée

### Sprint 2 (chat Vstorm réel)
1. Implémenter `WS /api/v1/ws/agent` (event model Vstorm).
2. Implémenter la couche `conversations/*` + `sessions/*`.

### Sprint 3 (SaaS Vstorm full)
- Auth complète, orgs, admin, billing, invitations, slash commands.

## 5) Conclusion
Le backend couvre maintenant le noyau RAG + gestion collections/documents attendu par l'UI Vstorm (Sprint 1). Le principal gap pour un branchement full UX reste le chat WebSocket et la couche SaaS (auth/org/admin/billing).
