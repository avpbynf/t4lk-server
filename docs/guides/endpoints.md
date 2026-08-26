# Guide des endpoints FastAPI -- T4lk

Ce guide decrit les conventions et contrats d'interface des endpoints de T4lk (t4lk-server).

---

## Architecture des routes

t4lk-server protège toutes ses routes `/v1` par un token Bearer. L'architecture est directe et
compatible avec l'API OpenAI Audio :

```
client HTTP
    |
    v
rest/main.py        <-- application factory, health endpoint
    |
    +-- rest/routes.py          routeur versionne (prefixe /v1)
         +-- rest/v1/transcriptions/router.py   endpoints de transcription
```

**Regle de repartition** :
- Endpoint de sante (`/health`) -> `rest/main.py`
- Endpoints de transcription (`/v1/audio/transcriptions*`) -> `rest/v1/transcriptions/router.py`

---

## Conventions

### Authentification

Toute route `/v1` exige un token Bearer (`Authorization: Bearer sk_...`). Les tokens
sont mintés par l'administrateur, stockés hachés, et révocables machine par machine.
Les routes `/admin` sont protégées séparément par `ADMIN_TOKEN`. Seul `/health` reste
ouvert, pour que les sondes répondent sans secret.

`ADMIN_TOKEN` vide désactive `/admin` et verrouille `/v1` en 401 : un avertissement est
loggé au démarrage, c'est le premier endroit où regarder quand tout répond 401.

### Upload audio

Les endpoints de transcription acceptent un fichier audio via `multipart/form-data`. Le champ
s'appelle `file` et doit etre de type `UploadFile`.

```python
@router.post("/transcriptions")
async def create_transcription(file: UploadFile = File(...)):
    ...
```

Formats audio supportes : `wav`, `mp3`, `mp4`, `m4a`, `ogg`, `flac`, `webm`.
Taille maximale : 25 MB.

### Format des reponses

Le format de reponse est controle par le parametre `response_format` :

| Valeur | Type de retour | Description |
|--------|---------------|-------------|
| `json` (defaut) | `application/json` | `{"text": "..."}` |
| `verbose_json` | `application/json` | Texte + langue + duree + segments |
| `text` | `text/plain` | Transcription brute |
| `srt` | `text/plain` | Sous-titres SRT |
| `vtt` | `text/plain` | Sous-titres WebVTT |

Les erreurs utilisent le format FastAPI standard :

```json
{ "detail": "description de l'erreur" }
```

La route SSE (`/v1/audio/transcriptions/stream`) retourne un flux `text/event-stream`.

### En-tetes de reponse

Chaque reponse inclut des en-tetes de tracage et de performance :

| En-tete | Description |
|---------|-------------|
| `X-Request-Id` | Identifiant unique de la requete (hex 16 octets) |
| `X-Execution-Time` | Duree totale de traitement en ms (ex: `1234.5ms`) |

---

## Contrats actifs

### 1. POST /v1/audio/transcriptions

| Propriete | Valeur |
|-----------|--------|
| Methode | `POST` |
| Path | `/v1/audio/transcriptions` |
| Auth | Aucune |
| Content-Type | `multipart/form-data` |

Parametres form-data :

| Parametre | Type | Requis | Defaut | Description |
|-----------|------|--------|--------|-------------|
| `file` | `UploadFile` | oui | -- | Fichier audio |
| `model` | `str` | non | -- | Informatif seulement (le modele configure est utilise) |
| `language` | `str` | non | `DEFAULT_LANGUAGE` | Code BCP-47 (`fr`, `en`, etc.) |
| `response_format` | `str` | non | `json` | Format de retour (voir tableau ci-dessus) |
| `temperature` | `float` | non | `0.0` | Temperature d'echantillonnage |
| `prompt` | `str` | non | -- | Prompt initial pour guider la transcription |

Reponse `json` (defaut) :

```json
{"text": "Bonjour comment allez-vous"}
```

Reponse `verbose_json` :

```json
{
  "task": "transcribe",
  "language": "fr",
  "duration": 5.1,
  "text": "Bonjour comment allez-vous",
  "segments": [
    {"index": 0, "start": 0.0, "end": 2.5, "text": " Bonjour"},
    {"index": 1, "start": 2.5, "end": 5.1, "text": " comment allez-vous"}
  ]
}
```

---

### 2. POST /v1/audio/transcriptions/stream

| Propriete | Valeur |
|-----------|--------|
| Methode | `POST` |
| Path | `/v1/audio/transcriptions/stream` |
| Auth | Aucune |
| Content-Type | `multipart/form-data` |
| Reponse | `200` `text/event-stream` (SSE) |

Parametres form-data : identiques a l'endpoint precedent, sans `response_format`.

Format des evenements SSE :

```
event: segment
data: {"index": 0, "start": 0.0, "end": 2.5, "text": " Bonjour"}

event: segment
data: {"index": 1, "start": 2.5, "end": 5.1, "text": " comment allez-vous"}

event: done
data: {"text": "Bonjour comment allez-vous", "language": "fr", "duration": 5.1}
```

En cas d'erreur apres debut du streaming :

```
event: error
data: {"message": "GPU queue timeout exceeded after 120s", "type": "QueueTimeoutError"}
```

Extension YZ non presente dans l'API standard OpenAI.

---

### 3. GET /health

| Propriete | Valeur |
|-----------|--------|
| Methode | `GET` |
| Path | `/health` |
| Auth | Aucune |
| Reponse | `200` JSON |

```json
{
  "status": "ok",
  "model_loaded": true,
  "device": "cuda",
  "queue_size": 0
}
```

`status` vaut `"ok"` si le modele est charge, `"degraded"` sinon.
`queue_size` indique le nombre de requetes en attente d'un slot GPU.

---

## Codes d'erreur HTTP

| Code | Exception | Cause |
|------|-----------|-------|
| `400` | `InvalidAudioError` | Format/taille de fichier invalide, format de reponse non supporte |
| `422` | validation FastAPI | Parametre form-data manquant ou de mauvais type |
| `500` | `TranscriptionError` | Echec de transcription cote modele |
| `503` | `QueueTimeoutError` | Timeout d'attente GPU depasse (`GPU_TIMEOUT`) |

---

## Ajouter un endpoint

### Endpoint de transcription

Ajouter dans `rest/v1/transcriptions/router.py` en suivant le pattern :

```python
@router.get("/transcriptions/{id}")
async def get_transcription(
    id: str,
    request: Request,
):
    engine = _get_engine(request)
    # implementation
    return {"id": id}
```

### Nouvel endpoint versioned

Creer un nouveau sous-package dans `rest/v1/` et inclure le routeur dans `rest/routes.py` :

```python
from rest.v1.nouveau.router import router as nouveau_router
router.include_router(nouveau_router)
```

### Checklist avant merge

- [ ] Endpoint documente dans ce fichier (section "Contrats actifs")
- [ ] Validation de l'entree effectuee avant l'acces au GPU
- [ ] Reponse d'erreur testee (400, 422, 500, 503)
- [ ] Test unitaire ou d'integration ajoute
- [ ] Couverture globale maintenue au-dessus de 80 %
