# AlbFetcharr

Сервис для автоматической загрузки wanted-альбомов из [Lidarr](https://lidarr.audio/) через [Яндекс Музыку](https://music.yandex.ru/), [YouTube Music](https://music.youtube.com/) и [SoundCloud](https://soundcloud.com/). Разработан с поддержкой расширяемой модели источников.

## Возможности

- Получение списка wanted-альбомов из Lidarr API
- Поиск альбомов в Яндекс Музыке, YouTube Music и SoundCloud
- Загрузка через [yandex-music-downloader](https://github.com/llistochek/yandex-music-downloader) и [yt-dlp](https://github.com/yt-dlp/yt-dlp) с выбором качества
- Автоматический импорт загруженных альбомов в Lidarr (ManualImport + перенос обложек)
- Веб-интерфейс с пошаговым рабочим процессом (выбор → результаты → загрузка) и поддержкой нескольких источников

## Установка

### Docker Compose

Пример `docker-compose.yml` с AlbFetcharr и Lidarr:

```yaml
services:
  lidarr:
    image: linuxserver/lidarr
    container_name: lidarr
    environment:
      - PUID=1000
      - PGID=1000
    volumes:
      - ./lidarr/config:/config
      - /path/to/music:/data/library
      - /path/to/downloads:/data/downloads
    ports:
      - "8686:8686"
    restart: unless-stopped

  albfetcharr:
    image: semsemyonoff/albfetcharr
    container_name: albfetcharr
    environment:
      - YANDEX_MUSIC_TOKEN=your_token_here
      - YANDEX_MUSIC_QUALITY=2
      - LIDARR_URL=http://lidarr:8686
      - LIDARR_API_KEY=your_api_key_here
      - ALBFETCHARR_LIDARR_IMPORT_PATH=/data/downloads/alb
      - ALBFETCHARR_LIBRARY_MAP=/data/library=/libraries/music
    volumes:
      - /path/to/downloads/alb:/downloads
      - /path/to/music:/libraries/music
    ports:
      - "5000:5000"
    restart: unless-stopped
```

### Директории и маппинг библиотек

AlbFetcharr работает с двумя типами директорий:

- **Загрузки** — папка, куда yandex-music-downloader скачивает альбомы (монтируется как `/downloads`)
- **Библиотеки** — корневые папки Lidarr (root folders), куда Lidarr импортирует музыку

Lidarr может использовать несколько root folders (например, `/data/library` и `/data/soundtracks`). Пути внутри Lidarr и внутри AlbFetcharr могут различаться, поэтому используется маппинг `ALBFETCHARR_LIBRARY_MAP`:

```
ALBFETCHARR_LIBRARY_MAP=<путь_в_lidarr>=<путь_в_albfetcharr>,<путь2_в_lidarr>=<путь2_в_albfetcharr>
```

Маппинг нужен для переноса обложек после импорта — AlbFetcharr получает путь альбома из Lidarr API и транслирует его в локальный путь через маппинг.

**Пример с одной библиотекой:**

| Контейнер | Путь | Хост |
|---|---|---|
| Lidarr | `/data/library` | `/mnt/music` |
| Lidarr | `/data/downloads` | `/mnt/downloads` |
| AlbFetcharr | `/downloads` | `/mnt/downloads/alb` |
| AlbFetcharr | `/libraries/music` | `/mnt/music` |

```
ALBFETCHARR_LIBRARY_MAP=/data/library=/libraries/music
ALBFETCHARR_LIDARR_IMPORT_PATH=/data/downloads/alb
```

**Пример с несколькими библиотеками:**

```
ALBFETCHARR_LIBRARY_MAP=/data/music=/libraries/music,/data/soundtracks=/libraries/soundtracks
```

При запуске AlbFetcharr проверяет root folders через Lidarr API и выводит предупреждение, если для какой-либо из них нет записи в маппинге.

### Настройка Lidarr

1. Получите API-ключ Lidarr: **Settings → General → API Key**
2. Убедитесь, что в Lidarr есть wanted-альбомы (альбомы со статусом «Missing»)
3. AlbFetcharr использует ManualImport API для импорта загруженных альбомов — дополнительная настройка Download Client в Lidarr не требуется

### Запуск

```bash
docker compose up -d
```

Веб-интерфейс будет доступен по адресу `http://localhost:5000`.

## Источники

AlbFetcharr поддерживает несколько источников для поиска и загрузки альбомов:

| Источник | Требования | Заметки |
|---|---|---|
| **Yandex Music** | `YANDEX_MUSIC_TOKEN` | Наиболее точный поиск, полная информация об альбомах и исполнителях |
| **YouTube Music** | Включен по умолчанию | Поиск через `ytmusicapi` (авторизация не нужна); загрузка по отдельным трекам, опционально с `cookies.txt` (см. ниже) |
| **SoundCloud** | Включен по умолчанию | Для сетов (плейлистов), поиск может быть менее точным; теги могут быть неполными |

### Особенности источников

**Яндекс Музыка**
- Требует действительный токен авторизации
- Лучшее качество метаданных
- Поддержка различных форматов (AAC 64/192, FLAC)

**YouTube Music**
- Поиск выполняется через [ytmusicapi](https://github.com/sigma67/ytmusicapi) — **авторизация и cookies для поиска не требуются**
- Загрузка идёт по отдельным трекам альбома (`youtube.com/watch?v=…`) через [yt-dlp](https://github.com/yt-dlp/yt-dlp), теги пишутся из метаданных альбома ytmusicapi (`title`, `artist`, `album`, `albumartist`, `tracknumber`, `date`)
- Современный YouTube часто требует cookies при загрузке («Sign in to confirm you're not a bot»). Если вы столкнулись с этой ошибкой, передайте файл `cookies.txt` (см. [Cookies для YouTube](#cookies-для-youtube)). Без cookies поиск и загрузка остальных источников работают как прежде
- Если какие-то треки недоступны в вашем регионе, они пропускаются, а альбом импортируется частично (в логе будет строка `partial: N/M`)

**SoundCloud**
- Использует [yt-dlp](https://github.com/yt-dlp/yt-dlp) для поиска и загрузки
- Требует ffmpeg для конвертации аудио
- Поиск может возвращать неточные результаты — **рекомендуется проверить результаты в веб-интерфейсе перед загрузкой**
- Теги `artist`, `album`, `title`, `tracknumber` заполняются из метаданных плейлиста; если источник слабо помечен, может потребоваться ручная корректировка перед импортом в Lidarr

### Cookies для YouTube

Загрузка из YouTube может потребовать cookies авторизованного аккаунта (ошибка *«Sign in to confirm you're not a bot»*). Поддержка cookies **опциональна**:

1. Экспортируйте cookies в формате Netscape (`cookies.txt`) из браузера, где вы авторизованы на YouTube — например, расширением [Get cookies.txt LOCALLY](https://github.com/kairi003/Get-cookies.txt-LOCALLY) или `yt-dlp --cookies-from-browser`.
2. Положите файл в каталог, доступный контейнеру (например, рядом с загрузками), и укажите путь **внутри контейнера** в переменной `ALBFETCHARR_YTDLP_COOKIES`.
3. Перезапустите сервис. Файл подхватывается автоматически только если он существует.

Если переменная не задана или файл отсутствует, ничего не меняется: поиск YouTube (через ytmusicapi) cookies не использует, а SoundCloud и Яндекс Музыка работают как прежде.

## Переменные окружения

### Обязательные

| Переменная | Описание |
|---|---|
| `YANDEX_MUSIC_TOKEN` | [Токен авторизации Яндекс Музыки](https://yandex-music.readthedocs.io/en/main/token.html) |
| `LIDARR_URL` | URL Lidarr (например `http://lidarr:8686`) |
| `LIDARR_API_KEY` | API-ключ Lidarr |

### Сервис

| Переменная | По умолчанию | Описание |
|---|---|---|
| `ALBFETCHARR_PORT` | `5000` | Порт веб-интерфейса на хосте |
| `ALBFETCHARR_LIDARR_IMPORT_PATH` | — | Путь к загрузкам в контексте Lidarr (например `/data/downloads/alb`) |
| `ALBFETCHARR_LIBRARY_MAP` | — | Маппинг путей библиотек: `lidarr_path=albfetcharr_path,...` |
| `DOWNLOAD_DIR` | `/downloads` | Путь к папке загрузок внутри контейнера |
| `CHOWN_DIRS` | `true` | Устанавливать владельца для папок при старте (`true` / `false`) |
| `ALBFETCHARR_DEFAULT_LANG` | `en` | Язык UI по умолчанию (`en` / `ru`) |
| `ALBFETCHARR_DEFAULT_THEME` | `system` | Тема UI по умолчанию (`system` / `light` / `dark`) |

### Параметры загрузки

| Переменная | По умолчанию | Описание |
|---|---|---|
| `YANDEX_MUSIC_QUALITY` | `2` | Качество: `0` — AAC 64, `1` — AAC 192, `2` — FLAC |
| `ALBFETCHARR_LYRICS_FORMAT` | `lrc` | Формат текста песни: `none`, `text`, `lrc` |
| `ALBFETCHARR_COVER_RESOLUTION` | `400` | Разрешение обложки в пикселях или `original` |
| `ALBFETCHARR_EMBED_COVER` | `0` | Встраивать обложку в аудиофайл (`0` / `1`) |
| `ALBFETCHARR_SKIP_EXISTING` | `1` | Пропускать уже загруженные треки (`0` / `1`) |
| `ALBFETCHARR_CLEAR_COMMENTS` | `0` | Удалять тег comments из скачанных треков (`0` / `1`) |
| `ALBFETCHARR_DELAY` | `0` | Задержка между запросами (секунды) |
| `ALBFETCHARR_STICK_TO_ARTIST` | `0` | Загружать альбомы только данного исполнителя (`0` / `1`) |
| `ALBFETCHARR_ONLY_MUSIC` | `0` | Только музыка, без подкастов и аудиокниг (`0` / `1`) |
| `ALBFETCHARR_COMPAT_LEVEL` | `1` | Уровень совместимости (`0` — `1`) |
| `ALBFETCHARR_PATH_PATTERN` | — | Шаблон пути (`#album-artist/#album/#number - #title`) |
| `ALBFETCHARR_UNSAFE_PATH` | `0` | Не очищать путь от недопустимых символов (`0` / `1`) |
| `ALBFETCHARR_YTDLP_FORMAT` | `flac` | Формат аудио для yt-dlp источников: `flac`, `m4a`, `mp3` |
| `ALBFETCHARR_YTDLP_QUALITY` | `192` | Битрейт для сжатых форматов (кбит/с), игнорируется для FLAC |
| `ALBFETCHARR_YTDLP_COOKIES` | — | Путь (внутри контейнера) к Netscape `cookies.txt` для загрузки YouTube/SoundCloud за бот-гейтом. Опционально; если не задан или файл отсутствует — cookies не используются (см. [Cookies для YouTube](#cookies-для-youtube)) |
| `ALBFETCHARR_ENABLE_YOUTUBE_MUSIC` | `1` | Включить YouTube Music источник (`0` / `1`) |
| `ALBFETCHARR_ENABLE_SOUNDCLOUD` | `1` | Включить SoundCloud источник (`0` / `1`) |

### Сетевые параметры

| Переменная | По умолчанию | Описание |
|---|---|---|
| `ALBFETCHARR_TIMEOUT` | `20` | Таймаут запроса (секунды) |
| `ALBFETCHARR_TRIES` | `20` | Количество попыток при сетевых ошибках |
| `ALBFETCHARR_RETRY_DELAY` | `5` | Задержка между повторными попытками (секунды) |

### Контейнер

| Переменная | По умолчанию | Описание |
|---|---|---|
| `UID` | `1000` | UID пользователя в контейнере |
| `GID` | `1000` | GID пользователя в контейнере |
| `UMASK` | `022` | umask |

## Веб-интерфейс

По умолчанию контейнер запускает веб-сервер (gunicorn) на порту `5000`. Фронтенд собран с помощью Vite из React-компонентов.

Интерфейс работает в три шага (сеанс завершается после завершения загрузки):

1. **Select** — загрузить список wanted-альбомов из Lidarr, отфильтровать/отсортировать, выбрать источники для поиска
2. **Results** — поиск выбранных альбомов во всех включенных источниках, отображение результатов с обложками, выбор лучшего совпадения и качества для каждого альбома
3. **Download** — загрузка с отображением прогресса в реальном времени (прогресс-бары по альбомам, терминальный лог) и автоматический импорт в Lidarr (если `ALBFETCHARR_LIDARR_IMPORT_PATH` установлен)


## CLI-режим

AlbFetcharr также поддерживает запуск из командной строки:

```bash
# Загрузить все wanted-альбомы и импортировать в Lidarr
docker compose run --rm albfetcharr wanted

# Загрузить без импорта
docker compose run --rm albfetcharr wanted --no-import

# Использовать конкретный источник (yandex / youtube_music / soundcloud)
docker compose run --rm albfetcharr wanted --source youtube_music

# Загрузить конкретный альбом по URL (источник определяется автоматически)
docker compose run --rm albfetcharr download "https://music.yandex.ru/album/12345"

# Загрузить с явным указанием источника
docker compose run --rm albfetcharr download --source soundcloud "https://soundcloud.com/..."
```

## Миграция с Yamdarr

Если вы используете старый образ `semsemyonoff/yamdarr`, обновите `docker-compose.yml`:

1. Измените имя образа:
   ```diff
   - image: semsemyonoff/yamdarr
   + image: semsemyonoff/albfetcharr
   ```

2. Переименуйте переменные окружения (`YAMDARR_*` → `ALBFETCHARR_*`):
   ```diff
   - YAMDARR_LIDARR_IMPORT_PATH=/data/downloads/yamd
   + ALBFETCHARR_LIDARR_IMPORT_PATH=/data/downloads/alb
   - YAMDARR_LIBRARY_MAP=/data/library=/libraries/music
   + ALBFETCHARR_LIBRARY_MAP=/data/library=/libraries/music
   ```

   > **Примечание:** `YAMDARR_AUTO_DOWNLOAD` и `YAMDARR_AUTO_CRON` больше не поддерживаются — автоматическая фоновая загрузка удалена. Используйте веб-интерфейс или CLI для запуска загрузки вручную.

   Полный список переименованных переменных:
   | Старая (Yamdarr) | Новая (AlbFetcharr) |
   |---|---|
   | `YAMDARR_LIDARR_IMPORT_PATH` | `ALBFETCHARR_LIDARR_IMPORT_PATH` |
   | `YAMDARR_LIBRARY_MAP` | `ALBFETCHARR_LIBRARY_MAP` |
   | `YAMDARR_PORT` | `ALBFETCHARR_PORT` |
   | `YAMDARR_LYRICS_FORMAT` | `ALBFETCHARR_LYRICS_FORMAT` |
   | `YAMDARR_COVER_RESOLUTION` | `ALBFETCHARR_COVER_RESOLUTION` |
   | `YAMDARR_EMBED_COVER` | `ALBFETCHARR_EMBED_COVER` |
   | `YAMDARR_SKIP_EXISTING` | `ALBFETCHARR_SKIP_EXISTING` |
   | `YAMDARR_CLEAR_COMMENTS` | `ALBFETCHARR_CLEAR_COMMENTS` |
   | `YAMDARR_DELAY` | `ALBFETCHARR_DELAY` |
   | `YAMDARR_STICK_TO_ARTIST` | `ALBFETCHARR_STICK_TO_ARTIST` |
   | `YAMDARR_ONLY_MUSIC` | `ALBFETCHARR_ONLY_MUSIC` |
   | `YAMDARR_COMPAT_LEVEL` | `ALBFETCHARR_COMPAT_LEVEL` |
   | `YAMDARR_PATH_PATTERN` | `ALBFETCHARR_PATH_PATTERN` |
   | `YAMDARR_UNSAFE_PATH` | `ALBFETCHARR_UNSAFE_PATH` |
   | `YAMDARR_TIMEOUT` | `ALBFETCHARR_TIMEOUT` |
   | `YAMDARR_TRIES` | `ALBFETCHARR_TRIES` |
   | `YAMDARR_RETRY_DELAY` | `ALBFETCHARR_RETRY_DELAY` |

   Остальные переменные не изменились: `LIDARR_URL`, `LIDARR_API_KEY`, `YANDEX_MUSIC_TOKEN`, `YANDEX_MUSIC_QUALITY`, `DOWNLOAD_DIR`, `UID`, `GID`, `UMASK`.

## Зависимости

- [yandex-music-downloader](https://github.com/llistochek/yandex-music-downloader) — загрузка треков из Яндекс Музыки
- [yandex-music](https://github.com/MarshalX/yandex-music-api) — поиск альбомов через API Яндекс Музыки
- [ytmusicapi](https://github.com/sigma67/ytmusicapi) — поиск альбомов в YouTube Music (без авторизации)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — загрузка из YouTube Music и SoundCloud
- [ffmpeg](https://ffmpeg.org/) — конвертация аудио для yt-dlp источников (включён в Docker-образ; требуется на хосте при запуске без Docker)
- [Lidarr](https://lidarr.audio/) — управление библиотекой, wanted-список, импорт

> Фронтенд (React + Vite SPA) находится в **отдельном репозитории** и собирается там (`npm ci && npm run build`, требуется **Node.js 20+**). При запуске бэкенда вне Docker положите собранный фронтенд в `albfetcharr/web/static/dist/`, чтобы Flask отдавал интерфейс.

## Спасибо

- Разработчикам проекта [yandex-music-api](https://github.com/MarshalX/yandex-music-api)
- Разработчикам проекта [yandex-music-downloader](https://github.com/llistochek/yandex-music-downloader)
- Разработчикам проекта [Lidarr](https://github.com/Lidarr/Lidarr)

## Дисклеймер

Данный проект является независимой разработкой и никак не связан с компанией Яндекс, Google или SoundCloud.

Скачивание музыки из интернета может быть ограничено законами об авторских правах в вашей юрисдикции. **Пользователь несет полную ответственность за соответствие музыкального контента местному законодательству.**

При использовании YouTube Music и SoundCloud как источников учитывайте условия использования этих сервисов. Использование yt-dlp для автоматической загрузки контента может нарушать условия использования этих платформ.
