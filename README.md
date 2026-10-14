# 🎬 Claqueta

**¿Qué película veo esta noche?** Una app web (responsive, pensada para el móvil y para la tele) que te propone *una* película cada vez, según cómo te sientes, con quién estás, cuánto tiempo tienes y cuánta energía mental te queda. Si no te convence, la descartas con un motivo («muy larga», «pinta a tostón», «ya la vi»…) y te enseña la siguiente mejor, ya corregida con lo que acabas de decirle.

Está pensada para quien está empezando a descubrir clásicos y quiere **evitar los tostones**: el motor penaliza las películas que han envejecido mal y aprende cuánta tolerancia tienes a los clásicos a partir de lo que puntúas.

Se integra con **Letterboxd** (importando tu exportación y leyendo tu RSS público, sin tocar jamás tu cuenta ni tu watchlist), **Jellyfin**, **Jellyseerr**, **Radarr** y **TMDB**. Corre como un servicio más en tu Homeserver con Docker Compose.

---

## Puesta en marcha (Docker Compose)

Requisitos: Docker con el plugin `docker compose` (v2.24 o superior).

```bash
git clone <tu-repo> claqueta && cd claqueta      # o descomprime el zip
cp .env.example .env                               # edítalo si quieres (todo es opcional)
docker compose up -d --build
```

Abre `http://IP-DEL-SERVIDOR:8420` (el puerto se cambia con `CLAQUETA_PORT` en `.env`).

La primera vez te saldrá una pantalla de bienvenida: importa tu Letterboxd o valora unas cuantas películas y ya tienes recomendaciones. Todo lo demás (claves de TMDB, Jellyfin, etc.) se puede poner **desde Ajustes** dentro de la app; el `.env` solo sirve de valores iniciales.

### Conectarlo con el resto de tu stack

Para usar nombres de contenedor (`http://jellyfin:8096`, `http://jellyseerr:5055`, `http://radarr:7878`), únelo a la red donde vive tu stack: descomenta `networks` en `docker-compose.yml` y pon el nombre de tu red. Si no, usa la IP del servidor: `http://192.168.1.X:8096`.

### Detrás de un proxy inverso (HTTPS, dominio propio)

Apunta tu Caddy / Nginx Proxy Manager / Traefik a `claqueta:8000`. Si lo expones fuera de casa, **pon `ACCESS_PASSWORD`** en el `.env`: la app pedirá contraseña (cookie firmada de 60 días, con límite de intentos).

### Datos y copias de seguridad

Todo lo tuyo (base de datos SQLite, ajustes, caché de pósters) vive en el volumen `claqueta-data` (`/data` dentro del contenedor). Copia de seguridad:

```bash
docker compose stop claqueta
docker run --rm -v claqueta_claqueta-data:/d -v "$PWD":/b alpine tar czf /b/claqueta-backup.tgz -C /d .
docker compose start claqueta
```

(Si prefieres una carpeta del host, cambia el volumen en el compose por `./data:/data` y haz antes `mkdir -p data && sudo chown -R 1000:1000 data`.) Además puedes exportar lo visto y los pendientes en CSV desde Ajustes, en el formato que acepta Letterboxd.

### Actualizar

```bash
git pull   # o sustituye los archivos
docker compose up -d --build
```

La base de datos se migra sola al arrancar.

---

## Conectar tus servicios

| Servicio | Para qué | Dónde se configura |
|---|---|---|
| **TMDB** (gratis) | Carteles, sinopsis, reparto, duración, plataformas de streaming | Ajustes → TMDB. Clave en <https://www.themoviedb.org/settings/api> |
| **Letterboxd** | Tu historial, notas y watchlist | Ajustes → Importar tu Letterboxd |
| **Jellyfin** | Qué tienes ya disponible y qué has visto; botón «Reproducir» | Ajustes → Jellyfin (URL, clave de API, usuario) |
| **Jellyseerr** | Pedir una película que no tienes; ver el estado | Ajustes → Jellyseerr |
| **Radarr** | Solo lectura: progreso de descarga de lo pedido | Ajustes → Radarr |
| **LLM** (opcional, gratis) | Afina las «fichas de sensación» y entiende texto libre | Ajustes → LLM |

Cada bloque de Ajustes tiene un botón **Probar conexión**. Las claves se guardan en la base de datos y nunca se devuelven completas al navegador.

### Letterboxd, paso a paso

Letterboxd no tiene API pública, así que hay dos vías complementarias:

1. **Importación completa (una vez, y cuando quieras refrescar):** en letterboxd.com → *Ajustes → Importar y exportar → Exportar tus datos*. Te llega un ZIP; súbelo tal cual en *Ajustes → Importar tu Letterboxd* (también acepta los CSV sueltos: `diary.csv`, `ratings.csv`, `watched.csv`, `watchlist.csv`, `likes`). Trae tu historial, notas, *likes* y watchlist.
2. **Puesta al día automática:** escribe tu usuario en *Ajustes → Letterboxd* y Claqueta lee tu RSS público cada 6 horas (últimas ~50 entradas del diario).

Claqueta **solo lee**. Tu watchlist de Letterboxd no se modifica nunca: lo que aparcas o guardas en Claqueta es una lista interna aparte («Otro día»). Si quieres llevar algo de vuelta a Letterboxd, usa los botones de **exportar CSV** y lo importas tú allí.

### LLM gratuito (opcional)

Sin LLM todo funciona con el motor propio (heurísticas + 121 películas curadas a mano). Con LLM, Claqueta enriquece en segundo plano las fichas de películas nuevas y entiende frases libres tipo «vengo cansado y quiero algo corto». Hay ajustes preconfigurados (Ajustes → LLM):

- **Groq** (nivel gratuito), **Google Gemini** (nivel gratuito), **OpenRouter** (modelos `:free`) y **Ollama** (local, sin límites).
- Cualquier API compatible con OpenAI sirve.
- Hay un límite de tokens por minuto y un tope diario (configurable) para no pasarte nunca de la cuota gratuita.

---

## Cómo decide

Cada película tiene 15 «atributos de sensación» (ritmo, tensión, humor, calidez, oscuridad, exigencia, rareza, riesgo de que haya envejecido mal, facilidad para no cinéfilos…). Con ellos el motor:

1. **Filtra** lo imposible (ya vista, demasiado larga, no apta para la compañía, época descartada…). Si no queda casi nada, relaja los filtros por niveles y te lo dice.
2. **Puntúa** con componentes ponderados: tu gusto, el estado de ánimo, calidad (valoración bayesiana), concentración, compañía, variedad, disponibilidad en Jellyfin y si estaba en tu lista.
3. **Penaliza** el tiempo, el riesgo de «tostón» (según tu tolerancia aprendida a los clásicos) y lo que acabas de rechazar en esta sesión.
4. **Diversifica** (MMR) para no enseñarte tres películas casi idénticas seguidas.
5. **Explica** cada propuesta con razones concretas y avisos honestos («pide más concentración de la que traes»).

Cada descarte tiene motivo y se aplica **al instante** (p. ej. «muy larga» baja el tope por debajo de esa duración) y **a largo plazo** (ajustes pequeños y con caída exponencial en tu perfil, que nunca pisan tus notas). Todo es deshacible.

La página **Mi gusto** enseña lo que ha aprendido de ti, y **Rutas** son itinerarios cortos para descubrir clásicos de menos a más exigentes.

### Atajos de teclado

`←` descartar · `→` aceptar · `S` otro día · `Z` deshacer

---

## Para modificarlo

```
backend/app/
  main.py            Arranque, rutas, sirve la interfaz compilada
  models.py, db.py   SQLAlchemy 2 + SQLite (WAL)
  settings_store.py  Ajustes en BD con valores por defecto del entorno
  scheduler.py       Tareas periódicas (sincronizaciones, aprendizaje, mantenimiento)
  api/               Endpoints (reco, films, system, auth, media)
  engine/            El motor: moods, pesos, atributos, contexto, recomendación, feedback, gusto
  services/          Integraciones: tmdb, jellyfin, jellyseerr, radarr, letterboxd, llm, enrich
  data/              Semilla de 121 películas y rutas de cine
frontend/src/        React + TypeScript + Vite (pages/, components/, styles/)
```

| Quiero… | Toco… |
|---|---|
| Añadir un estado de ánimo | `engine/moods.py`: una entrada nueva en `MOODS` (la interfaz la pinta sola) |
| Cambiar la importancia de cada factor | Ajustes → *Afinado* (o `DEFAULT_WEIGHTS` en `engine/weights.py`) |
| Añadir motivos de descarte | `engine/feedback.py` (`REASONS` y su efecto de sesión) |
| Añadir una ruta de cine | `data/paths.py` |
| Ampliar el catálogo inicial | `data/seed.py` (o importa tu Letterboxd: el catálogo crece con lo que importas y descubres vía TMDB) |
| Otro proveedor de metadatos o servicio | Un módulo nuevo en `services/` y su bloque en `api/system.py` |
| Cambiar el aspecto | `frontend/src/styles/*.css` (paleta y tipografías en `tokens.css`) |

API documentada y probable en `http://IP:8420/api/docs`.

### Desarrollo local

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
DATA_DIR=./data uvicorn app.main:app --reload --port 8000

# Frontend (en otra terminal; proxy de /api a :8000)
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run build      # compila a frontend/dist, que el backend sirve solo
```

### Tests

```bash
cd backend && pytest -q
```

Cubren el motor (filtros, mood, anti-tostón, sesiones, deshacer, aprendizaje), la API completa y las integraciones con servidores simulados (TMDB, Jellyfin, Jellyseerr, Radarr, Letterboxd, LLM).

### Variables de entorno

Ver `.env.example`. Extras avanzados: `DISABLE_SCHEDULER=true` (sin tareas en segundo plano), `STATIC_DIR` (ruta de la interfaz compilada), `DATA_DIR`.

> **Importante:** ejecuta un único proceso (`uvicorn` sin `--workers`). El planificador y los trabajos en segundo plano viven dentro del proceso y SQLite funciona mejor así.

---

## Notas de privacidad

- Claqueta no envía tus datos a ningún sitio salvo a los servicios que tú configures: TMDB (títulos para buscar fichas) y, si lo activas, el LLM (títulos y metadatos de películas, y lo que pides esta noche: ánimo, compañía, minutos y la frase libre si la escribes; no tus notas ni tus datos personales).
- Nada se escribe en Letterboxd, ni en tu Jellyfin. Jellyseerr solo recibe una petición cuando tú pulsas «Pedir».
