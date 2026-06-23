# README_FUSION - Template (fusion `production-ai-app` + `full-stack-ai-agent-template`)

## 1) Objectif
Construire une base unique réutilisable , sans réécrire le backend à chaque mission.

Cette fusion garde le moteur backend robuste de `production-ai-app` (LangGraph, guardrails, cache, RAG, validation) et ajoute une couche de compatibilité API pour brancher rapidement une UI Next.js issue du template Vstorm.

## 2) Ce qui est repris de chaque projet

### Depuis `production-ai-app`
- Pipeline `/query` orienté production: sécurité, cache sémantique, retrieval, exécution, validation.
- Persistance de session via Postgres + checkpointer LangGraph.
- Stockage documentaire en MongoDB via PageIndex trees.
- Validation de réponse (faithfulness/completeness).

### Depuis `full-stack-ai-agent-template` (Vstorm)
- Convention d'API `api/v1` pour brancher une UI Next.js sans réécrire tout le backend.
- Endpoints RAG/upload compatibles avec les flows frontend (collections, ingestion, search, supported formats).
- Streaming type ChatGPT côté API (`/api/v1/query/stream`, SSE).
- Approche frontend/backend découplée (Next.js -> FastAPI via HTTP/SSE/WebSocket).
- Inspiration UI/UX: upload en direct, dashboard KB, chat moderne, extensible multi-agent.

## 3) Nouvelles capacités implémentées

### 3.1 Provider-agnostic LLM (multi-client)
Ajout d'une factory centralisée `services/llm_factory.py`.

Support provider:
- `gemini`
- `openai`
- `groq`
- `openai_compatible`

Variables clés:
- `LOW_COMPLEXITY_PROVIDER`, `LOW_COMPLEXITY_MODEL`
- `HIGH_COMPLEXITY_PROVIDER`, `HIGH_COMPLEXITY_MODEL`
- `QUERY_INTELLIGENCE_PROVIDER`, `QUERY_INTELLIGENCE_MODEL`
- `TREE_SEARCH_PROVIDER`, `TREE_SEARCH_MODEL`
- `COMPLETENESS_JUDGE_PROVIDER`, `COMPLETENESS_JUDGE_MODEL`

Conséquence:
- Plus de hardcode Gemini dans les nœuds principaux.
- Même code backend pour clients Gemini/OpenAI/Groq.

### 3.2 Retrieval multi-périmètres (base pour +80 domaines)
Ajouts de filtres de retrieval:
- `RETRIEVAL_DOC_IDS`
- `RETRIEVAL_DOMAINS`
- `RETRIEVAL_MAX_DOCS`

Utilité:
- Isoler la recherche par périmètre/document.
- Préparer une architecture multi-domaines (RH, juridique, compta, technique...).

### 3.3 Ingestion batch PDF industrialisable
`prep/index_docs.py` supporte maintenant:
- mode single PDF (`--pdf`)
- mode batch dossier (`--pdf-dir`, `--recursive`)
- parallélisme (`--workers`)
- métadonnées (`--collection`, `--domain`, `--source`, `--tags`)
- pilotage de polling (`--max-attempts`, `--poll-seconds`)

Cela couvre la préparation de gros corpus (ex: 10k PDFs: texte, tableaux, scans OCRés via PageIndex).

### 3.4 Couche d'API compatible UI Vstorm
Nouveaux endpoints dans `main.py`:
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
- `POST /api/v1/query/stream` (SSE)

But:
- Permettre de greffer rapidement l'UI Next.js Vstorm.
- Réduire le gap endpoint/front sans migration lourde.

## 4) Frontend séparé (repo à part)
Le frontend Next.js doit vivre dans un repo dédié.

Documentation dédiée:
- `README_FRONTEND_SEPARATE.md`

Templates fournis:
- `integration/frontend-separate/Dockerfile`
- `integration/frontend-separate/Dockerfile.dev`
- `integration/frontend-separate/docker-compose.frontend.yml`

Variables frontend attendues:
- `NEXT_PUBLIC_API_URL=http://localhost:8000`
- `BACKEND_URL=http://localhost:8000` (ou `http://backend:8000` en docker network)
- `NEXT_PUBLIC_AUTH_ENABLED=true`

## 5) Exemples d'exécution

### 5.1 Indexer un seul PDF
```bash
python -m prep.index_docs \
  --pdf ./docs/guide.pdf \
  --doc-id support-guide \
  --collection support \
  --domain technique
```

### 5.2 Indexer un dossier complet
```bash
python -m prep.index_docs \
  --pdf-dir ./docs \
  --recursive \
  --workers 4 \
  --doc-prefix client-a \
  --collection kb-client-a \
  --domain juridique \
  --source sharepoint \
  --tags production,contractuel
```

### 5.3 Lancer le stack backend
```bash
docker compose up --build
```

## 6) Stratégie +80 périmètres (roadmap recommandée)

### Déjà en place
- Filtrage retrieval par doc/domain.
- Métadonnées d'ingestion.
- Pipeline batch.
- Compatibilité API pour uploader/rechercher via UI moderne.

### Étapes suivantes recommandées
1. Ajouter un routeur sémantique dédié (classification de périmètre -> filtre strict).
2. Ajouter ACL par rôle/périmètre (RBAC + policy checks) pour éviter les fuites inter-domaines.
3. Séparer indexes/collections par domaine critique (juridique, finance, RH).
4. Mettre en place un pipeline CDC (Drive/SharePoint webhooks + sync incrémentale).
5. Industrialiser les évaluations RAG en CI (faithfulness, context precision/recall, answer relevance).
6. Ajouter jeux de tests de non-régression multi-périmètres (au moins 10 questions par domaine).

## 7) Limites actuelles
- L'endpoint stream SSE envoie des deltas simulés à partir de la réponse finale (pas encore un vrai token streaming natif du provider).
- Les endpoints de compatibilité couvrent surtout la brique RAG/upload/stream; la totalité des APIs SaaS Vstorm (orgs, billing, admin complet) n'est pas portée.
- Faithfulness Ragas reste adossé à un judge OpenAI-compatible (fallback à `1.0` si désactivé/non configuré).

## 8) Positionnement recruteur / mission
Cette base démontre:
- architecture backend production (FastAPI + LangGraph + persistence + sécurité),
- capacité d'intégration front moderne (Next.js découplé),
- trajectoire crédible pour montée à l'échelle documentaire multi-domaines,
- standardisation template freelance multi-clients sans lock-in fournisseur LLM.

## 9) Focus 10 000 PDFs (texte + tableaux + graphiques + scans)

Vous avez cité: `Granite Docling (VLM) + Layout-Aware Chunking + Qdrant hybrid (BM42+dense) + RRF + cross-encoder reranker`.

### Ce qui est déjà présent dans `full-stack-ai-agent-template`
- Qdrant comme backend vectoriel.
- Hybrid search BM25 + dense avec fusion RRF.
- Reranking final avec CrossEncoder (ou Cohere).

### Ce qui n'est pas natif (à adapter)
- Granite Docling VLM n'est pas branché par défaut dans le template.
- Layout-aware chunking avancé orienté documents complexes (charts/tables/scans) est à implémenter comme stratégie de chunking dédiée.

### Adaptation recommandée dans votre fusion
1. Remplacer/étendre le parser d'ingestion par un adapter `DoclingParser`.
2. Ajouter un chunker "layout-aware" (blocs, tableaux, légendes, zones OCR) avec métadonnées structurelles.
3. Conserver Qdrant hybrid + RRF + reranker CrossEncoder pour la phase retrieval/ranking.
4. Stocker les métadonnées de structure (`block_type`, `page`, `table_id`, `figure_id`, `bbox`) pour améliorer le rerank et la génération.
5. Mettre des tests RAG multi-périmètres en CI pour valider précision/fidélité après chaque changement de parser/chunker.

Conclusion: oui, ce stack est très adapté au scénario de l'image (10k PDFs hétérogènes). Le socle retrieval/rerank est déjà aligné côté template Vstorm; l'effort principal est sur le parsing/segmenting Docling + layout-aware.
