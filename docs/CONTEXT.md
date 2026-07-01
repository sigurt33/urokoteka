# УрокоТека — контекст проекта (для продолжения разработки)

Этот файл — точка входа, чтобы после перезагрузки или смены ПК быстро вернуться
в контекст и продолжить. Хронология изменений — в [HISTORY.md](HISTORY.md).

## Что это

Локальная веб-страница для поиска и скачивания записей уроков с платформы
**Контур.Толк** (ktalk). Пользователь вводит имя записи или преподавателя —
видит записи за последние 3 дня и скачивает MP4.

- Репозиторий: <https://github.com/sigurt33/urokoteka> (публичный, аккаунт `sigurt33`).
- Автор: Николай Дубинец.
- Пространство Толка: `https://matrius.ktalk.ru`.

## Архитектура

Один файл **`server.py`** — HTTP-сервер на стандартной библиотеке Python
(без сторонних пакетов) + встроенная HTML-страница (константа `PAGE_HTML`).
Почему нужен сервер, а не чистый HTML: **у API Толка нет CORS** (preflight
`OPTIONS` → 405, нет `Access-Control-Allow-Origin`), поэтому браузер не может
ходить в API напрямую из файла. Сервер работает посредником и прячет ключ.

### Маршруты
- `GET /` — HTML-страница.
- `GET /api/search?q=` — записи за `DAYS_BACK` дней, фильтр по названию и ФИО
  преподавателя **локально** (на сервере). Возвращает JSON.
- `GET /download?key=&name=` — проксирует MP4 записи с заголовком-ключом,
  отдаёт файл с заданным именем (Content-Disposition, UTF-8).
- `GET /logos/<файл>` — отдаёт логотипы из папки `logos/`.

### Настройки (вверху `server.py`)
- `API_TOKEN` — берётся из переменной окружения `TALK_API_TOKEN` **или** из
  локального `config.py` (см. `config.example.py`). В коде НЕ хранится.
- `BASE_URL` = `https://matrius.ktalk.ru`.
- `HOST` = `127.0.0.1`, `PORT` = `8765` (порт 8000 зарезервирован Windows —
  WinError 10013).
- `DAYS_BACK` = 3, `PAGE_SIZE` = 200, `MAX_PAGES` = 50.

### Упаковка в .exe
`resource_dir()` возвращает `sys._MEIPASS` в собранном exe, иначе папку скрипта
(так логотипы находятся и внутри exe). При старте `main()` сам открывает браузер.

## Контракт API Толка (проверено вживую)

Авторизация — заголовок `X-Auth-Token: <ключ>`. Ключ создаётся в кабинете:
`dashboard?section=api`, там же настраиваются права. Нужны права на чтение
записей домена.

- `GET /api/domain/recordings?skip=&top=` — **весь домен**, список записей,
  сортировка по `createdDate` убыванию. Ответ:
  `{recordings:[{key, title, createdDate, createdBy{firstname,surname,patronymic,post,email}, duration(сек), size(байт), participants, roomName}]}`.
  Это основной источник списка.
- `GET /api/recordings/{key}/file` — скачивание видео (MP4).
- `GET /api/recordings/{key}` — детали (previewImage, commentsCount,
  transcription, qualities и т.д.).
- `GET /api/recordings/{key}/preview` — превью-картинка.
- `GET /api/users` — пользователи.
- Страница записи на сайте: `https://matrius.ktalk.ru/recordings/{key}`.

### Подводные камни
- `GET /api/recordings` (без `/domain/`) — **личный** эндпоинт, требует
  пользовательскую сессию; с app-ключом → 401. Параметр `initiator` булев.
- Комментарии чата `GET /api/recordings/{key}/chat/messages?channel=<guid>` →
  **403** для app-ключа (нет прав на чат), и `commentsCount` обычно 0. Поэтому
  «время первого комментария» недоступно — вместо него показываем `createdDate`.
- **Нет CORS** → чистый клиентский HTML невозможен (нужен сервер/exe).
- Порт 8000 на Windows зарезервирован → используем 8765.

## Как запускать и собирать

**Разработка:**
1. Скопировать `config.example.py` → `config.py`, вписать ключ.
2. `py server.py` → открыть <http://127.0.0.1:8765>.

**Сборка одного .exe (PyInstaller):**
```
py -m PyInstaller --onefile --noconfirm --clean --name UrokoTeka ^
  --add-data "logos;logos" --hidden-import config server.py
```
Результат: `dist/UrokoTeka.exe` (ключ и логотипы внутри).

**Архивы:** собираются PowerShell-ом (`Compress-Archive`). См. HISTORY.md.

## Безопасность / секреты

- `config.py` с ключом — в `.gitignore`, в репозиторий не попадает.
- В `.gitignore` также: `*.zip`, `portable*/`, `dist/`, `build/`, `*.exe`, `*.spec`
  (сборки содержат ключ — не публиковать).
- **Никогда не коммить ключ и не писать его в docs** (репозиторий публичный).

## Структура проекта

```
server.py            — сервер + страница (весь код)
config.py            — ключ (локально, не в git)
config.example.py    — образец config.py
logos/               — zerocoder.png, matrius.png, ktalk.png, ktalk.svg
start.bat            — запуск для переносимой версии (нужен Python)
README.md            — описание для GitHub
docs/CONTEXT.md      — этот файл
docs/HISTORY.md      — хронология разработки
```

## Идеи на будущее

- Иконка для .exe из логотипа.
- Превью-миниатюры записей (`/api/recordings/{key}/preview`).
- Управление периодом (не только 3 дня) и пагинация для «все записи».
- Скачивание протокола/транскрипции (эндпоинты `/summary/file`, `/transcript/file`).
