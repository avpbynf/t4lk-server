# Guide de debogage -- T4lk

Ce guide couvre les diagnostics et la résolution de pannes du serveur T4lk (FastAPI + CUDA),
les cas où un client ne parvient pas à l'atteindre compris.

---

## Diagnostics rapides

Commandes a executer en premier pour evaluer l'etat du systeme :

```bash
# Verifier que les conteneurs sont en cours d'execution
docker ps

# Afficher les logs en temps reel (serveur)
make logs

# Verifier que l'API repond
make health
```

La cible `make health` appelle `GET /health`. Une reponse `200 OK` avec `{"status": "ok", "model_loaded": true}` indique que le serveur est operationnel. Toute autre reponse ou un timeout signale un probleme.

---

## Diagnostics FastAPI

### Interface Swagger

L'interface Swagger est disponible a l'adresse suivante en developpement :

```
http://localhost:8000/docs
```

Elle permet de tester tous les endpoints directement depuis le navigateur sans client supplementaire.

Interface alternative ReDoc :

```
http://localhost:8000/redoc
```

### Tracage des requetes

Les logs des requetes HTTP sont geres par `AccessLogMiddleware` dans `rest/middlewares.py`. Chaque requete produit une ligne de log avec methode, path, statut, duree et metadonnees STT :

```
2026-03-16 10:00:00 [INFO] rest.middlewares: POST /v1/audio/transcriptions 200 1234.5ms
[trace_id=abc123def456 audio=5000ms model=large-v3 lang=fr queue=0ms]
```

Chaque reponse inclut `X-Request-Id` pour correler client et logs serveur.

Pour reproduire une requete en dehors du client :

```bash
# Test d'une transcription avec curl
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -F "file=@/chemin/vers/audio.wav" \
  -F "language=fr"

# Test verbose_json (avec segments et duree)
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -F "file=@/chemin/vers/audio.wav" \
  -F "response_format=verbose_json"

# Test de la route SSE (transcription en flux)
curl -X POST http://localhost:8000/v1/audio/transcriptions/stream \
  -H "Accept: text/event-stream" \
  -F "file=@/chemin/vers/audio.wav"
```

### Logs Uvicorn

```bash
# Logs live du conteneur serveur
make logs

# Ou directement via Docker
docker logs t4lk-server --follow --tail 100
```

---

## Pannes courantes

### 503 -- Modele Whisper non charge ou timeout GPU

**Symptome** : `POST /v1/audio/transcriptions` retourne `503 Service Unavailable`.

**Causes possibles** :

1. Le serveur n'a pas encore termine de charger le modele au demarrage (le chargement de faster-whisper peut prendre 30 a 60 secondes).
2. Le modele specifie dans `WHISPER_MODEL` n'existe pas ou n'est pas accessible.
3. Erreur CUDA lors de l'initialisation (voir section CUDA out of memory).
4. Timeout GPU : `GPU_TIMEOUT` secondes d'attente depassees (requetes concurrentes trop nombreuses).

**Verifications** :

```bash
# Attendre et reessayer make health jusqu'a obtenir {"status": "ok", "model_loaded": true}
make health

# Verifier les logs au demarrage
make logs | grep -i "model\|whisper\|load\|timeout"

# Verifier la variable WHISPER_MODEL dans .env
grep WHISPER_MODEL .env
```

---

### 400 -- Fichier audio invalide

**Symptome** : `POST /v1/audio/transcriptions` retourne `400 Bad Request`.

**Causes possibles** :

1. Extension du fichier non supportee (seuls `wav`, `mp3`, `mp4`, `m4a`, `ogg`, `flac`, `webm` sont acceptes).
2. Taille du fichier superieure a 25 MB.
3. `response_format` non reconnu.

**Verifications** :

```bash
# Tester avec un fichier WAV simple
curl -X POST http://localhost:8000/v1/audio/transcriptions \
  -F "file=@test.wav"

# Lire le message d'erreur dans le champ "detail"
```

---

### CUDA out of memory

**Symptome** : Erreur `torch.cuda.OutOfMemoryError` ou `CUDA out of memory` dans les logs, suivie d'un `503` ou d'un crash du processus.

**Causes possibles** :

1. Un autre processus occupe la memoire GPU (autre instance du serveur, autre modele charge).
2. Le modele selectionne est trop grand pour la VRAM disponible.
3. Un batch de transcription concurrent depasse la capacite memoire.

**Verifications** :

```bash
# Etat de la GPU 4060
nvidia-smi

# Identifier les processus utilisant la GPU
nvidia-smi pmon -s m

# Verifier les logs du serveur
make logs | grep -i "cuda\|memory\|oom"
```

**Resolutions** :

- Reduire la taille du modele (`WHISPER_MODEL=medium` au lieu de `large-v3`) dans `.env` puis `make restart`.
- Liberer la memoire GPU en arretant les autres processus CUDA.
- Si le probleme est lie aux requetes concurrentes, limiter la concurrence dans la configuration Uvicorn (`--workers 1`).

---

### Serveur inaccessible depuis le client Tauri

**Symptome** : Le client affiche une erreur de connexion ou timeout, alors que le serveur repond correctement via curl.

**Causes possibles** :

1. L'URL du serveur configuree dans le client est incorrecte (mauvais port, mauvais host).
2. Le serveur ecoute sur `127.0.0.1` au lieu de `0.0.0.0`, inaccessible depuis un autre processus ou machine.
3. Regle de pare-feu ou politique reseau bloquant le port 8000.
4. Erreur CORS -- le client Tauri est considere comme une origine distincte.

**Verifications** :

```bash
# Depuis la machine hote ou tourne le client
curl http://localhost:8000/health

# Verifier sur quelle adresse Uvicorn ecoute
make logs | grep "Uvicorn running on"

# Verifier la configuration reseau Docker
docker inspect t4lk-server | grep -A 10 '"Ports"'
```

**Configuration CORS** : verifier la variable `CORS_ALLOW_ORIGINS` dans `.env`. Par defaut `*` autorise toutes les origines. Pour restreindre, lister les origines separees par virgule :

```env
CORS_ALLOW_ORIGINS=tauri://localhost,http://localhost,https://localhost
```

La configuration est chargee dans `rest/settings.py` et appliquee dans `rest/main.py`.

---

## Reference des cibles Makefile de diagnostic

| Cible | Description |
|-------|-------------|
| `make health` | Appelle `GET /health`, verifie que l'API repond |
| `make logs` | Affiche les logs en temps reel |
| `make gpu` | Affiche l'etat de la GPU via nvidia-smi |
| `make restart` | Redemarre le serveur sans reconstruire l'image |
| `make down` | Arrete tous les services Docker |
| `make up` | Demarre tous les services Docker |
