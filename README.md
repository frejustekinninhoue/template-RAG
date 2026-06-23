# Production RAG Backend Template

Backend FastAPI + LangGraph pour projets RAG multi-domaines.

## Architecture de données (prod)
- `MongoDB` (`support_bot.document_trees`): arbres documentaires + métadonnées (`collection`, `domain`, `source`, `source_type`, `source_ref`, `tags`). C'est la base RAG runtime.
- `MongoDB` (`support_bot.rag_collections`): registre des collections.
- `PostgreSQL`: mémoire/session LangGraph (checkpointer).
- `GPTCache`: cache sémantique des réponses.
- `PageIndex`: parsing structuré des PDF.

## Différence avec votre ancien flux Chroma/Supabase
Avant:
- dossier -> chunking/embedding -> Chroma -> éventuel transfert Supabase/pgvector.

Ici:
- source documentaire -> extraction/parsing -> arbre documentaire -> MongoDB -> retrieval.

Donc:
- la vérité documentaire runtime est dans MongoDB.

## Orchestration multi-formats (nouveau)
Le template accepte maintenant:
- `PDF (.pdf)`
- `Word (.docx)`
- `Excel (.xlsx)`
- `Google Docs` (via `google_doc_id`)
- `Google Sheets` (via `google_sheet_id`)
- `URLs` (contenu web)

Comment ça marche:
1. PDF -> PageIndex -> arbre natif.
2. DOCX/XLSX/Google Docs/Google Sheets/URL -> extraction texte -> chunking sémantique -> arbre compatible.
3. Arbre + métadonnées stockés dans MongoDB.

## Conditions/prérequis par format
- PDF: nécessite `PAGEINDEX_API_KEY`.
- DOCX/XLSX: nécessite dépendances Python (`python-docx`, `openpyxl`).
- Google Docs/Sheets: nécessite `GOOGLE_SERVICE_ACCOUNT_FILE` + accès API/partage des docs au compte de service.
- URL: nécessite accès réseau sortant depuis le backend.

## Où mettre les documents
2 modes:
1. Offline batch (recommandé prod): dossier/source traités par scripts `prep/*`.
2. Online API/UI: ingestion via endpoints `/api/v1/rag/...`.

Important: les fichiers originaux ne sont pas la source de recherche runtime. Le runtime lit les arbres stockés en MongoDB.

## Endpoints Vstorm bridge (mis à jour)

### Base
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

### Sprint 1 (ajouté)
- `POST /api/v1/rag/collections`
- `POST /api/v1/rag/collections/{name}`
- `DELETE /api/v1/rag/collections/{name}`
- `GET /api/v1/rag/collections/{name}/documents`
- `DELETE /api/v1/rag/collections/{name}/documents/{documentId}`
- `GET /api/v1/rag/status/stream`

## Ingestion API (multi-format)
Endpoint: `POST /api/v1/rag/collections/{name}/ingest`

Envoyer exactement une source:
- `file` (`.pdf`, `.docx`, `.xlsx`), ou
- `url`, ou
- `google_doc_id`, ou
- `google_sheet_id`

Paramètres complémentaires:
- `doc_id` (optionnel)
- `domain` (défaut `general`)
- `source` (défaut `api_upload`)
- `tags` (CSV)
- `replace=true|false` (query param)

## Ingestion offline

### 1) PDF batch (PageIndex)
```bash
python -m prep.index_docs \
  --pdf-dizr ./docs \
  --recursive \
  --workers 4 \
  --collection memoires-info \
  --domain informatique
```

### 2) Source unitaire multi-format
```bash
python -m prep.ingest_sources --file ./docs/memoire.docx --collection memoires-info
python -m prep.ingest_sources --file ./docs/resultats.xlsx --collection memoires-info
python -m prep.ingest_sources --url https://example.com/article --collection veille-tech
python -m prep.ingest_sources --google-doc-id <DOC_ID> --collection memoires-info
python -m prep.ingest_sources --google-sheet-id <SHEET_ID> --collection memoires-info
```

## Sécurité (état actuel)
Déjà en place:
- Auth JWT sur routes protégées.
- Rate limiting.
- Input guard.
- PII scrubbing + détection d'attaque/prompt injection (Rival AI).
- Circuit breakers + retries.

À renforcer (niveau entreprise):
- RBAC fin par périmètre (`domain`/`collection`).
- Audit logs de consultation documentaire.
- Scan antivirus + validation MIME avancée des uploads.
- Guardrails de sortie anti data leakage.
- Tests sécurité automatisés en CI.

## Projet 
Le template est adapté pour un prototype robuste, avec vigilance sur:
1. parsing de PDF académiques complexes,
2. chunking sémantique,
3. anti-hallucination + citation source.

## Cas 10k PDFs complexes
La brique retrieval moderne (Qdrant/hybrid/RRF/reranker) est documentée côté Vstorm; `Granite Docling + layout-aware chunking` reste une adaptation explicite à ajouter si vous ciblez ce niveau.

## NEXT
À consulter:
- `README_FUSION.md`
- `README_FRONTEND_SEPARATE.md`
- `ENDPOINT_MAPPING_VSTORM.md`
