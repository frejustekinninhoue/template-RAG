# Template de production 

Construit avec FastAPI + LangGraph + PageIndex + Ragas + Rival AI.

---

## Architecture

``` 
POST /query
  │
  ├─ Middleware : auth JWT · limitation de débit (slowapi) · garde-fou d’entrée
  │
  ├─ Vérification du cache sémantique (serveur GPTCache)
  │     └─ HIT → retour immédiat
  │
  └─ Graphe LangGraph (LangSmith trace tout)
       ├─ safety_gate         Nettoyage PII avec Presidio + détection d’attaque Rival (en parallèle)
       ├─ query_intelligence  1 appel LLM structuré → intention, sous-requêtes, complexité
       ├─ session_memory      Checkpointer LangGraph PostgresSaver
       ├─ context_retrieval   Recherche d’arbre PageIndex + MongoDB
       ├─ execution           Gemini Flash / Pro / sous-requêtes en parallèle (API Send)
       ├─ output_validation   Fidélité Ragas + métrique de complétude personnalisée
       └─ cache_store         Écriture GPTCache + résumé structlog
```

## Stack

| Couche | Outil |
|---|---|
| Framework API | FastAPI |
| Orchestration du graphe | LangGraph |
| Auth | python-jose |
| Limitation de débit | slowapi |
| Nettoyage PII | presidio-analyzer + presidio-anonymizer |
| Détection d’attaque | rival-ai (Bhairava-0.4B, microservice séparé) |
| Cache sémantique | GPTCache (mode serveur) |
| Récupération RAG | PageIndex + MongoDB (motor) |
| Mémoire de session | LangGraph PostgresSaver + asyncpg |
| LLM (faible complexité) | configurable |
| LLM (haute complexité) | configurable |
| Détection d’hallucination | Ragas Faithfulness |
| Vérification de complétude | Métrique personnalisée LLM-as-judge |
| Observabilité (LLM) | LangSmith |
| Observabilité (app) | structlog |
| Retries | tenacity |
| Circuit breaking | pybreaker |
| Client HTTP | httpx |

## Démarrage rapide

**1. Cloner et configurer**

```bash
git clone https://github.com/your-handle/apple-support-bot
cd production-ai-ap
cp .env.example .env
# Renseignez vos clés API dans .env
```

**2. Indexer vos documents de support Apple**

```bash
# À exécuter une fois avant de démarrer l’app
python -m prep.index_docs --pdf path/to/apple-support-guide.pdf --doc-id apple-support
```

**3. Démarrer tous les services**

```bash
docker compose up --build
```

Cela démarre :
- `app` — application FastAPI principale sur le port 8000
- `rival-service` — microservice Rival AI sur le port 8002
- `gptcache` — serveur GPTCache sur le port 8001
- `mongodb` — arbres de documents sur le port 27017
- `postgres` — mémoire de session sur le port 5432

**4. Faire une requête**

```bash
curl -X POST http://localhost:8000/query \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "Comment réinitialiser mon MacBook Pro aux paramètres d’usine ?", "session_id": "session-abc"}'
```

## Structure du projet

``` 
apple-support-bot/
├── main.py                        # App FastAPI, endpoint /query
├── config.py                      # Configuration via pydantic-settings
├── graph/
│   ├── state.py                   # TypedDict SupportBotState
│   ├── graph.py                   # Définition StateGraph + compilation
│   └── nodes/
│       ├── safety_gate.py         # Presidio + Rival (asyncio.gather)
│       ├── query_intelligence.py  # Appel LLM structuré
│       ├── session_memory.py      # Élagage de l’historique
│       ├── context_retrieval.py   # PageIndex + MongoDB
│       ├── execution.py           # Sélection de modèle + fan-out Send
│       ├── output_validation.py   # Ragas + complétude
│       └── cache_store.py         # Écriture GPTCache + log final
├── services/
│   └── rival_service/
│       ├── main.py                # Microservice FastAPI autonome
│       ├── requirements.txt
│       └── Dockerfile
├── metrics/
│   └── completeness.py            # Métrique de complétude LLM-as-judge
├── prompts/
│   └── v1/
│       ├── query_intelligence.txt
│       ├── generation.txt
│       └── completeness_judge.txt
├── prep/
│   └── index_docs.py              # Hors ligne : PageIndex → MongoDB
├── resilience/
│   ├── breakers.py                # Circuit breakers pybreaker
│   └── retry.py                   # Décorateurs de retry tenacity
├── middleware/
│   ├── auth.py                    # Vérification JWT
│   ├── rate_limit.py              # Limiteur slowapi
│   └── input_guard.py             # Vérification longueur + encodage
├── observability/
│   └── logging.py                 # Configuration structlog
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Configuration

Toute la configuration passe par des variables d’environnement. Voir `.env.example` pour la liste complète.

Variables clés :

| Variable | Défaut | Description |
|---|---|---|
| `LOW_COMPLEXITY_MODEL` | `configurable` | Modèle pour les requêtes simples |
| `HIGH_COMPLEXITY_MODEL` | `configurable` | Modèle pour les requêtes complexes. Mettre `gpt-4o` pour utiliser OpenAI |
| `FAITHFULNESS_THRESHOLD` | `0.7` | Un score Ragas sous ce seuil déclenche un avertissement |
| `COMPLETENESS_THRESHOLD` | `0.6` | Un score de complétude sous ce seuil déclenche un avertissement |
| `MAX_INPUT_CHARS` | `4000` | Les requêtes plus longues sont rejetées avec une 400 |
| `MAX_SESSION_TURNS` | `10` | Nombre de tours de conversation conservés dans le contexte |

## Versioning des prompts

Les prompts vivent dans `prompts/v{n}/`. La version active est définie dans `graph/nodes/query_intelligence.py`. La chaîne de version est stockée dans l’état LangGraph et journalisée à chaque requête, pour corréler les changements de qualité avec les changements de prompt dans LangSmith.

Pour créer une nouvelle version de prompt : copiez `prompts/v1/` vers `prompts/v2/`, modifiez, puis mettez à jour `PROMPT_VERSION` dans le nœud.

## Circuit breakers et fallbacks

| Dépendance | Ouverture du breaker après | Comportement de repli |
|---|---|---|
| Rival (détection d’attaque) | 5 échecs | Laisse passer la requête, journalise un avertissement |
| PageIndex / MongoDB | 5 échecs | Contexte vide, le LLM répond avec sa connaissance |
| GPTCache | 10 échecs | Ignore le cache, continue normalement |
| Fournisseur LLM | — (tenacity retries x3) | 503 renvoyé à l’utilisateur |

## Et ensuite

- **Suite de régression d’évaluation** — jeux de données + évaluations LangSmith pour détecter les régressions lors des changements de prompt ou de modèle
- **Sortie en streaming** — `StreamingResponse` FastAPI avec streaming asynchrone LangChain
- **Tests A/B de modèles** — router N% du trafic vers un nouveau modèle, comparer les scores avant bascule
- **Mémoire long terme inter-sessions** — stockage des préférences utilisateur (modèle d’appareil, incidents passés, style de communication)

## Test rapide avec une clé API Groq (sans se pencher sur l’API)

Vous pouvez tester Groq en mode "plug-and-play" via l’endpoint OpenAI-compatible, sans changer le flux principal.

1. Ouvrir le fichier `.env` et renseigner :

```env
GROQ_API_KEY=VOTRE_CLE_GROQ
GROQ_BASE_URL=https://api.groq.com/openai/v1
HIGH_COMPLEXITY_MODEL=groq/llama-3.1-8b-instant
```

2. Laisser `OPENAI_API_KEY` vide si vous testez uniquement Groq.

3. Redémarrer l’application :

```bash
docker compose up --build
```

4. Envoyer une requête normale sur `/query`.

Notes :
- Le préfixe `groq/` sur `HIGH_COMPLEXITY_MODEL` active automatiquement le routage Groq.
- Le chemin `LOW_COMPLEXITY_MODEL` reste inchangé (Gemini) ; ce mode est pensé pour tester Groq rapidement sur les requêtes complexes.
