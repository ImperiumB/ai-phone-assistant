# Прототип речевого контура UL-17568

Состоит из двух частей:

- **Сервис** (`ai_assistant/service/`) — постоянно работающий демон на виртуалке
  `10.20.0.10`, Python 3.12. Держит gRPC-поток распознавания и HTTP-ручки
  диалога/синтеза.
- **AGI-клиент** (`ai_assistant/agi/ai_assistant.py`) — тонкий скрипт на
  Астериске, Python 3.9. Гонит аудио звонка в сервис и исполняет то, что тот
  прикажет.

Питон в проекте вызывается как `py -3.12` — голый `python` в Windows часто
оказывается заглушкой Microsoft Store и молча ничего не делает.

## Сервис (виртуалка 10.20.0.10, Python 3.12)

```bash
py -3.12 -m pip install -r ai_assistant/requirements.txt
```

### Модель Vosk

Модель уже скачана и лежит в `C:\Users\user\models\vosk-model-small-ru-0.22`.
Если разворачиваете заново:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\models" | Out-Null
cd "$env:USERPROFILE\models"
curl.exe -LO https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
Expand-Archive vosk-model-small-ru-0.22.zip -DestinationPath .
```

### Запуск

Все настройки читаются из переменных окружения с префиксом `AIA_`
(`ai_assistant/service/config.py`). Путь к модели Vosk — отдельная
переменная `AIA_VOSK_MODEL_PATH`, читается напрямую в `main.py`, в общий
`Config` не входит.

Машина сервиса — **Windows**. Команда `export` здесь не работает, это
синтаксис Linux-оболочки: переменная молча не выставится, и Vosk упадёт с
`Failed to create a model`, пытаясь загрузить модель по пустому пути.

Проще всего запускать на GigaAM — ему путь к модели не нужен, он сам качает
и кэширует веса, и он вдвое быстрее Vosk на распознавании:

```powershell
$env:AIA_STT_ENGINE = "gigaam"
cd "C:\Users\user\Desktop\Новый бот-помощник"
py -3.12 -m ai_assistant.service.main
```

С Vosk путь к модели обязателен:

```powershell
$env:AIA_STT_ENGINE = "vosk"
$env:AIA_VOSK_MODEL_PATH = "C:\Users\user\models\vosk-model-small-ru-0.22"
cd "C:\Users\user\Desktop\Новый бот-помощник"
py -3.12 -m ai_assistant.service.main
```

В `cmd` то же самое, но `set ПЕРЕМЕННАЯ=значение` без `$env:` и без кавычек,
а переход в каталог — `cd /d "путь"`. Переменные живут только в текущем окне.

Полный старт демона (загрузка эмбеддера базы знаний, движка распознавания,
VAD и синтеза) занимает **около 32-35 секунд для обоих движков** — выбор
Vosk/GigaAM почти не влияет на время старта, потому что основное время ест
эмбеддер базы знаний и Silero VAD/TTS, которые грузятся независимо от того,
какой движок распознавания выбран. По трём чистым замерам на каждый: Vosk —
31,9 / 31,9 / 33,0 с; GigaAM — 33,9 / 33,9 / 34,5 с. Подробности замера и
почему более ранняя (ошибочная) цифра «18 секунд для Vosk» была неверной —
в `ai_assistant/RESULTS.md`. Пока в логе не появится строка
`Uvicorn running on http://0.0.0.0:8080`, ручки не отвечают.

Проверка живости: `curl http://10.20.0.10:8080/health`

### Переменные окружения (`AIA_*`, см. `ai_assistant/service/config.py`)

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `AIA_GRPC_PORT` | `50051` | Порт gRPC-потока распознавания |
| `AIA_HTTP_PORT` | `8080` | Порт HTTP-ручек (`/dialog`, `/tts`, `/health`, `/metrics`) |
| `AIA_STT_ENGINE` | `vosk` | Движок распознавания: `vosk` или `gigaam` |
| `AIA_PREWARM_TTS` | `1` | Синтезировать все известные фразы при старте. Холодный синтез стоит до 2 секунд, и клиент слушает их как тишину. Выключается значением `0` |
| `AIA_GIGAAM_MODEL` | `v3_rnnt` | Модель GigaAM. Замер 14.08.2026 на одном материале: `v3_rnnt` 0,281 с против `v2_rnnt` 0,378 с при том же результате. Ещё есть `v3_ctc` (быстрее, чуть менее точна) и `v3_e2e_rnnt` (расставляет пунктуацию и заглавные буквы) |
| `AIA_VOSK_MODEL_PATH` | — (пусто) | Путь к модели Vosk. Читается отдельно в `main.py`, обязателен при `AIA_STT_ENGINE=vosk` |
| `AIA_TTS_MODEL` | `v4_ru` | Модель синтеза Silero. `v5_ru` звучит иначе и синтезирует медленнее |
| `AIA_TTS_VOICE` | `eugene` | Голос синтеза по умолчанию |
| `AIA_EMBEDDER_MODEL` | `ai-forever/ru-en-RoSBERTa` | Модель эмбеддингов для базы знаний |
| `AIA_SIMILARITY_THRESHOLD` | `0.65` | Порог сходства при поиске по базе знаний. Подобран замером 14.08.2026: верные попадания 0,669-0,857, посторонние вопросы 0,455-0,568. Чем больше синонимов в записях, тем выше можно держать порог |
| `AIA_SILENCE_TIMEOUT_MS` | `15000` | Таймаут тишины в VAD |
| `AIA_UTTERANCE_PAUSE_MS` | `1500` | Пауза, которой сегментируется конец реплики. Меньше — бот отвечает живее, но перебьёт задумавшегося; больше — разговор ощущается сломанным |
| `AIA_STT_TIMEOUT_S` | `10` | Таймаут распознавания одной реплики |
| `AIA_KNOWLEDGE_PATH` | `ai_assistant/knowledge_base.json` | Путь к базе знаний |
| `AIA_TTS_CACHE_DIR` | `/tmp/aia_tts_cache` | Каталог кэша готовых WAV |

Смена движка распознавания: `AIA_STT_ENGINE=gigaam` (модель GigaAM
скачивается/кэшируется автоматически при первом обращении, отдельная
переменная пути не нужна).

## Клиент (Астериск, Python 3.9)

```bash
scp ai_assistant/agi/ai_assistant.py root@<астериск>:/var/lib/asterisk/agi-bin/
scp ai_assistant/proto/speech_pb2.py ai_assistant/proto/speech_pb2_grpc.py \
    root@<астериск>:/var/lib/asterisk/agi-bin/
scp ai_assistant/sounds/service_unavailable.wav root@<астериск>:/var/lib/asterisk/sounds/ai_bot/service_unavailable.wav
ssh root@<астериск> "chmod +x /var/lib/asterisk/agi-bin/ai_assistant.py && \
                     python3 -m py_compile /var/lib/asterisk/agi-bin/ai_assistant.py && \
                     mkdir -p /var/lib/asterisk/sounds/ai_bot/cache"
```

Владельца каталога менять не нужно: на станции `asterisk-ai` Астериск работает
под `root` (проверено 13.08.2026), пользователя `asterisk` там нет вообще.

Подробный пошаговый разбор для человека, который пойдёт на станцию (включая
резервную копию диалплана, правку `extensions.conf`, проверку сети и
брандмауэра, откат) — в `ai_assistant/РАЗВЁРТЫВАНИЕ.md`.

## Замеры

- Тайминги: `curl http://10.20.0.10:8080/metrics`
- Пополнение базы знаний: `curl -X POST http://10.20.0.10:8080/knowledge/save`
- Запись разговора на Астериске: `/var/spool/asterisk/monitor/<uniqueid>.wav49`
- Таблица для заполнения результатами живого звонка: `ai_assistant/RESULTS.md`

## Тесты

```bash
py -3.12 -m pytest ai_assistant/tests -q
```

151 юнит-тест идёт по умолчанию. 4 интеграционных теста (маркер
`integration`) требуют реальных моделей и переменных `AIA_VOSK_MODEL_PATH` /
`AIA_TEST_WAV` — без них два из них тихо пропускаются (`skipped`), это
нормально, а не ошибка.
