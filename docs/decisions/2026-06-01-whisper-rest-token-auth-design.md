# Spec de conception — Serveur Whisper-only REST + auth token (SQLite + admin)

- **Date** : 2026-06-01
- **Statut** : Approuvé (sortie de `/brainstorm`)
- **Périmètre** : `t4lk-server` (repo git séparé). Un suivi client distinct est décrit en §16.
- **Branche d'implémentation** : `feature/whisper-rest-token-auth` (créée depuis `main`).

---

## 1. Contexte & problème

Le serveur a dérivé vers une architecture **bi-moteur** (branche `feature/dual-engine-whisper-parakeet`, non mergée) :
NeMo **Parakeet** pour un WebSocket temps réel + **faster-whisper** pour le REST. Les deux modèles
sont chargés en VRAM au démarrage. Cette voie pose trois problèmes pour l'usage réel :

1. **Parakeet n'est plus utile** : le besoin de transcription live temps réel a disparu.
2. **Image lourde** : `nemo_toolkit[asr]` force la base Docker `nvcr.io/nvidia/nemo:25.02` (plusieurs Go).
3. **Pas d'auth serveur** : le client envoie déjà `Authorization: Bearer <token>`, mais le serveur ne valide rien.

L'objectif est de **revenir à un serveur simple whisper-only REST**, sur image légère, et de
**restaurer le système de token** qui existait dans l'import initial (Whisper Flow).

## 2. Découverte git déterminante

L'investigation a montré que **`main` EST déjà le serveur simple recherché** :

| Aspect | État sur `main` |
|---|---|
| `rest/engine.py` | faster-whisper (`WhisperModel`) — pas de Parakeet |
| Dépendances | `faster-whisper`, **aucun `nemo_toolkit`** |
| Dockerfile | `FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04` (léger) |
| WebSocket | présent (`ws_handler/ws_models/ws_router`), backé Whisper |
| Parakeet (`bbe2e67`) | **absent de main** — uniquement sur les branches features non mergées |

→ On ne « supprime » donc **pas** de code Parakeet : on **repart de `main`** et on abandonne les branches features.

Par ailleurs, l'ancien système de token existait dans l'import initial **`bb42967`**
(`auth/`, `admin/`, `db/`), puis a été **retiré dans `7c447cd`** (« rewrite server as structured stt/ package »).
Ce code est récupérable via `git show bb42967:<chemin>` et constitue la base de la restauration (§8).

## 3. Objectifs

- Serveur **whisper-only REST**, OpenAI-compatible (`/v1/audio/transcriptions` + `/stream` SSE).
- **Image légère** conservée (base CUDA, déjà sur `main`).
- **Restaurer l'auth complète** : tokens en base, dépendance `verify_token`, panel admin de gestion.
- DB = **SQLite** (fichier, zéro conteneur).

## 4. Non-objectifs (explicitement exclus)

- WebSocket temps réel (supprimé — choix produit).
- Parakeet / NeMo / GPU Phrase Boosting.
- Formateur de texte Goblin Tools (présent dans l'ancien `server.py`, hors sujet).
- Anciens endpoints `/transcribe` non-OpenAI (remplacés par `/v1/audio/transcriptions`).
- Multi-utilisateur à grande échelle / Postgres (SQLite suffit pour un service interne).

## 5. Décisions verrouillées

| # | Décision | Rationale |
|---|---|---|
| D1 | Drop Parakeet **et** WebSocket → whisper-only REST | Plus de besoin temps réel ; faster-whisper n'est pas un modèle streaming |
| D2 | Repartir de `main` (pas de suppression Parakeet) | Parakeet jamais mergé sur main ; diff minimal, zéro résidu NeMo |
| D3 | Restaurer le système d'auth complet (`auth/`+`db/`+`admin/`) | Code déjà écrit/testé dans `bb42967` ; multi-token, révocation, stats, panel |
| D4 | DB = SQLite (aiosqlite) | Service interne, 1 box GPU ; fichier + volume, pas de conteneur ; préserve « image simple » |
| D5 | Porter dans le package `rest/` + pydantic-settings | L'ancien code vivait en packages top-level + `os.getenv` ; aligner sur l'archi actuelle |

## 6. Architecture cible

```
Client desktop ──HTTPS──> FastAPI (4060) [rest/main.py : create_app()]
   Authorization: Bearer sk_<token>
        │
        ├─ /v1/audio/transcriptions[/stream]  → Depends(verify_token) → WhisperEngine (faster-whisper)
        ├─ /health                            → public (healthcheck Docker)
        └─ /admin/ + /admin/tokens[...]       → Depends(verify_admin_token) (ADMIN_TOKEN) → CRUD + dashboard HTML

   UsageLogMiddleware : écrit un UsageLog (endpoint, process_time) par requête authentifiée
   SQLite (rest/db) : tables tokens + usage_logs
```

Un seul moteur, un seul modèle Whisper en VRAM. Plus de file WS, plus de boosting.

## 7. Structure de fichiers (porté dans `rest/`)

```
rest/
├── main.py            # create_app : init_db (startup) / close_db (shutdown),
│                      #   include_router(admin_router), Depends(verify_token) sur le router /audio
├── settings.py        # + DATABASE_URL, ADMIN_TOKEN  (retire WS_*)
├── db/
│   ├── __init__.py
│   ├── database.py    # engine async aiosqlite, get_db, init_db (create_all), close_db, PRAGMA WAL
│   └── models.py      # Base, Token, UsageLog (UUID → CHAR(32) via type Uuid SQLAlchemy 2.0)
├── auth/
│   ├── __init__.py
│   ├── tokens.py      # generate_token (sk_+32hex), hash_token (SHA256), verify_token_hash, CRUD
│   └── dependencies.py# verify_token (HTTPBearer→DB→is_active→MAJ usage), CurrentToken
├── admin/
│   ├── __init__.py
│   ├── routes.py      # CRUD /admin/tokens (+ /stats), dashboard, verify_admin_token (compare_digest)
│   └── static/index.html  # dashboard (≈450 lignes), à valider/adapter aux routes restaurées
└── middlewares.py     # + UsageLogMiddleware (corrige la faille latente : écriture des UsageLog)
```

## 8. Composants restaurés (source : `bb42967`, portés)

### 8.1 `rest/db/` — couche SQLite
- **`models.py`** : `Token` (`id` UUID PK, `key_hash` SHA256 unique indexé, `name`, `created_at`,
  `last_used_at`, `is_active`, `usage_count`) ; `UsageLog` (`id`, `token_id` FK, `endpoint`,
  `timestamp`, `process_time`). Relation `Token.usage_logs` (cascade delete-orphan).
- **`database.py`** : `create_async_engine` avec `sqlite+aiosqlite:///…/tokens.db`, `async_sessionmaker`,
  `get_db` (commit/rollback par requête), `init_db` (`Base.metadata.create_all`), `close_db`.
  Activer **WAL** (`PRAGMA journal_mode=WAL`) pour la lecture concurrente.
- **Adaptation SQLite** : l'original visait Postgres (`asyncpg`). Le type `Uuid` de SQLAlchemy 2.0
  se mappe en `CHAR(32)` sur SQLite — **à valider par un test** (création + relecture d'un Token).

### 8.2 `rest/auth/`
- **`tokens.py`** : repris quasi tel quel (stdlib `hashlib.sha256` + `secrets.compare_digest`,
  pas de `passlib`/`bcrypt`). `generate_token()` renvoie `(plain "sk_…", hash)`. CRUD async
  (`create_token`, `get_token_by_plain`, `list_tokens`, `revoke_token`, `get_token_by_id`,
  `update_token_usage`, `get_token_stats`).
  **Amélioration (vs code restauré)** : `get_token_by_plain` itère sur tous les tokens actifs
  (héritage d'un raisonnement « hash salé »). Le SHA256 étant déterministe, faire un lookup direct
  indexé `WHERE key_hash = hash_token(plain)` (O(1)) au lieu de la boucle O(n).
- **`dependencies.py`** : `verify_token` via `HTTPBearer` → `get_token_by_plain` → check `is_active`
  → `update_token_usage` → renvoie le modèle `Token` ; 401 + `WWW-Authenticate: Bearer` sinon.
  Pose `request.state.token_id` pour le middleware d'usage (§8.4).

### 8.3 `rest/admin/`
- **`routes.py`** : router préfixé `/admin`. `GET /` (dashboard `FileResponse`),
  `POST /tokens` (create, renvoie le `sk_…` **une seule fois**), `GET /tokens` (list),
  `GET /tokens/{id}`, `DELETE /tokens/{id}` (révocation soft), `GET /tokens/{id}/stats`.
  Protégé par `verify_admin_token`.
- **Correction sécurité** : `verify_admin_token` doit utiliser `secrets.compare_digest`
  (l'original comparait avec `!=`, vulnérable au timing).
- **`static/index.html`** : dashboard récupéré. Vérifier qu'il appelle bien les routes ci-dessus
  (mêmes chemins/formes de réponse) ; adapter si dérive.

### 8.4 Intégration dans `create_app()` (`rest/main.py`)
- `lifespan` : `await init_db()` au startup, `await close_db()` au shutdown (en plus du chargement Whisper).
- `app.include_router(admin_router)`.
- Protéger les routes REST : `Depends(verify_token)` au niveau du router `/audio`
  (`/health` reste hors de ce router → exempt par construction).
- **`UsageLogMiddleware`** (nouveau) : après réponse, si `request.state.token_id` est présent,
  écrire un `UsageLog(token_id, endpoint=request.url.path, process_time=elapsed)` via une session
  `async_session_maker()` dédiée. Corrige le fait que l'ancien code n'écrivait jamais de `UsageLog`
  (donc `/stats` renvoyait des stats vides). Repli acceptable si besoin : `process_time=None`.

## 9. Comportement de l'authentification

- **`/v1/*`** : un **token DB valide et actif est toujours requis** (modèle du système restauré,
  pas de « mode ouvert »). Token absent / invalide / révoqué → **401**.
- **Bootstrap** : définir `ADMIN_TOKEN` dans l'env → ouvrir `/admin/` → créer un token
  (le `sk_…` n'est affiché qu'à la création) → le configurer côté client. Sans token créé,
  tous les appels `/v1` renvoient 401 (verrouillé par défaut, ce qui est voulu).
- **`/admin/*`** : protégé par `ADMIN_TOKEN` (env, comparaison temps-constant). `ADMIN_TOKEN`
  absent → 500 à l'accès admin (comportement d'origine conservé).
- **`/health`** : public (sinon le healthcheck Docker casse).

## 10. Partie « whisper-only » (depuis `main`)

À retirer du socle `main` (choix REST-seul, D1) :
- `rest/v1/transcriptions/ws_handler.py`, `ws_models.py`, `ws_router.py`.
- L'`include_router(ws_router)` dans `rest/main.py`.
- Les settings `WS_MAX_CONNECTIONS`, `WS_MAX_AUDIO_DURATION`, `WS_CHUNK_TIMEOUT`
  (ce sont les seuls — `WS_PARTIAL_INTERVAL` n'existe pas dans le code).
- La méthode de l'engine `transcribe_stream_pcm` (utilisée uniquement par le WS).
  `transcribe` et `transcribe_stream` restent (REST).
- Les tests WS.

Le moteur whisper (`rest/engine.py`), le router REST, les middlewares et le Dockerfile léger
restent inchangés.

## 11. Settings (`rest/settings.py`, pydantic-settings)

- **Ajouter** : `DATABASE_URL: str = "sqlite+aiosqlite:///./data/tokens.db"` (volume dédié persistant, cf. §14),
  `ADMIN_TOKEN: str = ""`.
- **Retirer** : les champs `WS_*`.
- Remplacer les `os.getenv(...)` de l'ancien code par des champs `Settings` injectés.

## 12. Dépendances (`pyproject.toml`)

- **Ajouter** : `sqlalchemy[asyncio]>=2.0.0`, `aiosqlite>=0.20.0`.
- **Ne pas ajouter** : `asyncpg`, `alembic` (on utilise `create_all`), `passlib`/`bcrypt`
  (hash = `hashlib` stdlib).
- `make sync` après modification.

## 13. Tests (couverture ≥ 80 %)

- **tokens** : `generate_token` (format `sk_`), `hash_token`/`verify_token_hash`, CRUD complet.
- **verify_token** (dépendance) : token valide → 200 ; invalide → 401 ; révoqué (`is_active=False`) → 401 ; absent → 401.
- **admin** : create/list/get/delete/stats avec bon vs mauvais `ADMIN_TOKEN` ; dashboard servi (200).
- **routes protégées** : `POST /v1/audio/transcriptions` sans token → 401 ; avec token valide → 200.
- **UsageLog** : un appel authentifié écrit une ligne ; `/stats` la reflète (count + endpoint).
- **SQLite/UUID** : créer puis relire un `Token`, vérifier l'`id` UUID.
- **/health** : public (200 sans token).
- DB de test : `sqlite+aiosqlite:///:memory:` (ou fichier temp), `httpx.AsyncClient`, `pytest-asyncio`.

## 14. Docker / docker-compose

- **Dockerfile** : inchangé (base CUDA légère de `main`). `aiosqlite` arrive via `uv sync`.
- **docker-compose** : sur le socle `main`, `/app/.cache` est un **volume Docker nommé** (`model-cache`),
  donc **purgé par `make clean` / `down -v`**. Y stocker `tokens.db` ferait perdre tous les tokens à un reset
  du cache modèle. → Stocker la DB dans un **volume dédié persistant** : ajouter `token-data:/app/data` au
  service + à la section `volumes`, avec `DATABASE_URL=sqlite+aiosqlite:///./data/tokens.db`
  (WORKDIR=`/app` → `/app/data/tokens.db`). En dev local (hors Docker), `./data/` est relatif au cwd — à gitignorer.
- **`.env.example`** : documenter `DATABASE_URL` et `ADMIN_TOKEN` (avec la commande de génération
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`).

## 15. Documentation

- **`CLAUDE.md`** (repo parent) : retirer `ASR_MODEL`/`BOOSTING_*`/WS ; poser `WHISPER_MODEL`
  comme modèle ; ajouter la section auth/DB (`DATABASE_URL`, `ADMIN_TOKEN`, endpoints `/admin`,
  flux de bootstrap token) ; passer « Base de données : aucune » → « SQLite (tokens uniquement) » ;
  mettre à jour la table des endpoints (auth requise sur `/v1`, ajout `/admin`).
- Le plan dual-engine obsolète (`docs/decisions/2026-03-25-dual-engine-whisper-parakeet-plan.md`,
  présent sur la branche dual-engine) est **superséder** par cette spec — naturellement absent du socle `main`.

## 16. Suivi client (cycle séparé — repo `t4lk-client`)

Le serveur n'expose plus de WebSocket. La connexion T4lk WS du client
(`src-tauri/src/t4lk_connection.rs`, commande `connect_t4lk`) devient **morte** → basculer sur le REST
(`POST /v1/audio/transcriptions`). Le Bearer token est **déjà supporté** côté client ; il suffit d'y
renseigner un `sk_…` minté via `/admin`. Ce travail fait l'objet d'un **cycle spec→plan→execute distinct**,
committé/poussé dans le repo client (règle CLAUDE.md : repo séparé).

## 17. Phasage proposé (pour `/plan`)

- **Phase A — Whisper-only REST** : retrait du WebSocket (§10). Petit, indépendant.
- **Phase B — Restauration auth/db/admin** : portage SQLite (§8), protection des routes,
  `UsageLogMiddleware`, dashboard. Le gros du travail.

## 18. Plan git

- Implémentation sur `feature/whisper-rest-token-auth` (déjà créée depuis `main`).
- **Note** : `main` local est 1 commit en avance sur `origin/main` (le commit WS `c19a44e`).
  À pousser/clarifier ; `/plan` peut décider de baser sur `origin/main` (sans WS, donc encore moins à retirer).
- Branches `feature/T4LK-000_*`, `feature/T4LK-001_*`, `feature/dual-engine-*` (local + origin) →
  **abandonnées** (suppression à décider hors périmètre).

## 19. Risques & questions ouvertes

- **UUID sur SQLite** : valider le mapping `Uuid` → `CHAR(32)` par un test (R1, §13).
- **Session du `UsageLogMiddleware`** : ouvre sa propre session hors scope `get_db` ; vérifier
  l'absence de fuite et le commit correct.
- **Dashboard HTML** : conçu pour l'ancienne API admin (mêmes chemins) ; vérifier l'alignement.
- **Socle `main` vs `origin/main`** : trancher au `/plan` (impacte la quantité de WS à retirer).

## 20. Critères de succès

- `make test` vert, couverture ≥ 80 %.
- `make lint` propre (ruff + mypy).
- L'image build ; `/health` répond `model_loaded: true`.
- Flux token vérifié de bout en bout : mint via `/admin` → appel `/v1` authentifié 200, sans token 401.
