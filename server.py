# -*- coding: utf-8 -*-
"""
Локальный поиск и скачивание записей уроков с платформы Толк (ktalk).

Запуск:  py server.py
Открыть: http://localhost:8000

Ключ API хранится здесь, на сервере, и в браузер не попадает.

Автор: Николай Дубинец.
"""

import json
import os
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------
# API-ключ НЕ хранится в этом файле, чтобы его можно было выложить в публичный
# репозиторий. Ключ берётся из переменной окружения TALK_API_TOKEN или из
# локального config.py (см. config.example.py; config.py исключён из git).
def _load_token():
    token = os.environ.get("TALK_API_TOKEN", "").strip()
    if token:
        return token
    try:
        import config
        return getattr(config, "API_TOKEN", "").strip()
    except ImportError:
        return ""

API_TOKEN = _load_token()
if not API_TOKEN:
    raise SystemExit(
        "Не задан API-ключ. Создайте config.py по образцу config.example.py "
        "или задайте переменную окружения TALK_API_TOKEN."
    )

BASE_URL = "https://matrius.ktalk.ru"
HOST = "127.0.0.1"
PORT = 8765

DAYS_BACK = 3          # за сколько дней показывать записи
PAGE_SIZE = 200        # сколько тянуть за один запрос к API
MAX_PAGES = 50         # предохранитель от бесконечного цикла

# ---------------------------------------------------------------------------
# Работа с API Толка
# ---------------------------------------------------------------------------

def api_get(path, params=None):
    """GET к API Толка с заголовком-ключом. Возвращает разобранный JSON."""
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-Auth-Token": API_TOKEN})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def teacher_name(created_by):
    """Собирает ФИО преподавателя из объекта createdBy."""
    if not created_by:
        return ""
    parts = [created_by.get("surname"), created_by.get("firstname"),
             created_by.get("patronymic")]
    return " ".join(p for p in parts if p).strip()


def fetch_recordings():
    """Тянет записи за последние DAYS_BACK дней (список отсортирован по дате убыванию)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    result = []
    for page in range(MAX_PAGES):
        data = api_get("/api/domain/recordings",
                       {"skip": page * PAGE_SIZE, "top": PAGE_SIZE})
        batch = data.get("recordings", [])
        if not batch:
            break
        stop = False
        for r in batch:
            created = parse_date(r.get("createdDate"))
            if created and created < cutoff:
                stop = True
                break
            result.append(r)
        if stop or len(batch) < PAGE_SIZE:
            break
    return result


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def search(query):
    """Записи за 3 дня, отфильтрованные по тексту (название или преподаватель)."""
    q = (query or "").strip().lower()
    out = []
    for r in fetch_recordings():
        title = r.get("title") or ""
        teacher = teacher_name(r.get("createdBy"))
        if q and q not in title.lower() and q not in teacher.lower():
            continue
        cb = r.get("createdBy") or {}
        out.append({
            "key": r.get("key"),
            "title": title,
            "teacher": teacher,
            "post": cb.get("post") or "",
            "createdDate": r.get("createdDate"),
            "duration": r.get("duration") or 0,
            "size": r.get("size") or 0,
            "pageUrl": f"{BASE_URL}/recordings/{r.get('key')}",
        })
    return out


def safe_filename(title, created_date):
    """Имя файла для скачивания: Название_ГГГГ-ММ-ДД_ЧЧ-ММ.mp4 (без запретных символов)."""
    base = (title or "recording").strip()
    dt = parse_date(created_date)
    if dt:
        base += "_" + dt.astimezone().strftime("%Y-%m-%d_%H-%M")
    for ch in '<>:"/\\|?*':
        base = base.replace(ch, "_")
    return base + ".mp4"


def ensure_mp4(name):
    """Чистит заданное пользователем имя от запретных символов и гарантирует .mp4."""
    base = (name or "recording").strip()
    for ch in '<>:"/\\|?*':
        base = base.replace(ch, "_")
    if base.lower().endswith(".mp4"):
        base = base[:-4]
    return (base or "recording") + ".mp4"


# ---------------------------------------------------------------------------
# HTTP-сервер
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # тише в консоли

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if route == "/":
            self.send_html(PAGE_HTML)
        elif route == "/api/search":
            self.handle_search(qs.get("q", [""])[0])
        elif route == "/download":
            self.handle_download(qs.get("key", [""])[0], qs.get("name", [""])[0])
        elif route.startswith("/logos/"):
            self.handle_logo(route)
        else:
            self.send_error(404, "Not found")

    # --- маршруты ---------------------------------------------------------

    def handle_search(self, query):
        try:
            items = search(query)
            body = json.dumps({"recordings": items}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except urllib.error.HTTPError as e:
            self.send_json_error(502, f"Платформа вернула ошибку {e.code}")
        except Exception as e:
            self.send_json_error(500, str(e))

    def handle_download(self, key, name=""):
        if not key:
            self.send_error(400, "key required")
            return
        # Имя файла: либо заданное пользователем, либо собираем из метаданных записи.
        if name.strip():
            fname = ensure_mp4(name)
        else:
            title, created = key, None
            try:
                meta = api_get(f"/api/recordings/{urllib.parse.quote(key)}")
                title = meta.get("title") or key
                created = meta.get("createdDate")
            except Exception:
                pass
            fname = safe_filename(title, created)

        url = f"{BASE_URL}/api/recordings/{urllib.parse.quote(key)}/file"
        req = urllib.request.Request(url, headers={"X-Auth-Token": API_TOKEN})
        try:
            upstream = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            self.send_error(502, f"Не удалось скачать запись ({e.code})")
            return

        fname_ascii = fname.encode("ascii", "ignore").decode("ascii") or "recording.mp4"
        fname_utf8 = urllib.parse.quote(fname)

        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        length = upstream.headers.get("Content-Length")
        if length:
            self.send_header("Content-Length", length)
        self.send_header(
            "Content-Disposition",
            f"attachment; filename=\"{fname_ascii}\"; filename*=UTF-8''{fname_utf8}",
        )
        self.end_headers()
        try:
            while True:
                chunk = upstream.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # пользователь отменил скачивание
        finally:
            upstream.close()

    # --- helpers ----------------------------------------------------------

    def handle_logo(self, route):
        """Отдаёт файлы логотипов из папки logos рядом со скриптом."""
        name = os.path.basename(route)  # защита от выхода из папки
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logos", name)
        if not os.path.isfile(path):
            self.send_error(404, "Logo not found")
            return
        ctype = "image/svg+xml" if name.lower().endswith(".svg") else "image/png"
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json_error(self, code, message):
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Страница
# ---------------------------------------------------------------------------

PAGE_HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>УрокоТека</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: system-ui, Segoe UI, Arial, sans-serif; margin: 0; background:#f5f6f8; color:#1c1d22; }
  header { background:#fff; border-bottom:1px solid #e3e5ea; padding:16px 20px; position:relative; }
  h1 { font-size:22px; margin:0 0 12px; }
  h1 .sub { font-size:14px; font-weight:400; color:#6b7280; }
  .logos { position:absolute; top:14px; right:20px; display:flex; align-items:center; gap:22px; perspective:900px; }
  .coin { position:relative; display:inline-block; transform-style:preserve-3d; animation: coin 6s linear infinite; }
  .coin .face { height:68px; width:auto; display:block; backface-visibility:hidden; }
  .coin .back { position:absolute; top:0; left:0; transform: rotateY(180deg); }
  @keyframes coin { from { transform: rotateY(0deg); } to { transform: rotateY(360deg); } }
  .search { display:flex; gap:8px; max-width:640px; }
  input { flex:1; padding:10px 12px; font-size:15px; border:1px solid #c8ccd4; border-radius:8px; }
  button { padding:10px 16px; font-size:15px; border:0; border-radius:8px; background:#2f6df6; color:#fff; cursor:pointer; }
  button:hover { background:#255ad6; }
  main { padding:16px 20px; }
  .hint { color:#6b7280; font-size:13px; margin:0 0 12px; }
  table { width:100%; border-collapse:collapse; background:#fff; border-radius:10px; overflow:hidden; box-shadow:0 1px 2px rgba(0,0,0,.05); }
  th, td { text-align:left; padding:10px 12px; border-bottom:1px solid #eef0f3; font-size:14px; vertical-align:top; }
  th { background:#fafbfc; color:#6b7280; font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.03em; }
  tr:last-child td { border-bottom:0; }
  .title { font-weight:600; }
  .teacher small { color:#8a8f99; display:block; }
  a.dl { display:inline-block; padding:6px 12px; background:#10894b; color:#fff; border-radius:6px; text-decoration:none; font-size:13px; white-space:nowrap; }
  a.dl:hover { background:#0c7340; }
  a.open { display:inline-block; padding:6px 12px; background:#fff; color:#2f6df6; border:1px solid #2f6df6; border-radius:6px; text-decoration:none; font-size:13px; white-space:nowrap; }
  a.open:hover { background:#eef3ff; }
  .namecell { white-space:nowrap; }
  select.grp { padding:6px 8px; font-size:13px; border:1px solid #c8ccd4; border-radius:6px; }
  input.num { width:84px; padding:6px 8px; font-size:13px; border:1px solid #c8ccd4; border-radius:6px; }
  span.lesson { font-size:13px; color:#444; }
  .status { color:#6b7280; font-size:14px; padding:8px 0; }
  .empty { color:#8a8f99; }
</style>
</head>
<body>
<header>
  <div class="logos">
    <span class="coin" title="Зерокодер">
      <img class="face front" src="/logos/zerocoder.png" alt="Зерокодер">
      <img class="face back"  src="/logos/zerocoder.png" alt="">
    </span>
    <span class="coin" title="Матриус">
      <img class="face front" src="/logos/matrius.png" alt="Матриус">
      <img class="face back"  src="/logos/matrius.png" alt="">
    </span>
    <span class="coin" title="kTalk">
      <img class="face front" src="/logos/ktalk.png" alt="kTalk">
      <img class="face back"  src="/logos/ktalk.png" alt="">
    </span>
  </div>
  <h1>УрокоТека <span class="sub">— записи уроков за последние 3 дня</span></h1>
  <div class="search">
    <input id="q" type="text" placeholder="Имя записи или преподаватель (пусто — все)" autofocus>
    <button id="go">Найти</button>
  </div>
</header>
<main>
  <p class="hint">Поиск по названию записи и ФИО преподавателя. Кнопка «Скачать» сохраняет MP4.</p>
  <div id="status" class="status"></div>
  <table id="results" hidden>
    <thead><tr><th>Название</th><th>Преподаватель</th><th>Создано</th><th>Длит.</th><th>Размер</th><th>Имя сохраняемого файла</th><th></th><th></th></tr></thead>
    <tbody></tbody>
  </table>
</main>
<script>
const q = document.getElementById('q');
const go = document.getElementById('go');
const status = document.getElementById('status');
const table = document.getElementById('results');
const tbody = table.querySelector('tbody');

function fmtDate(s){
  if(!s) return '';
  const d = new Date(s);
  return d.toLocaleString('ru-RU', {day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
}
function fmtDur(sec){
  sec = Math.round(sec||0);
  const h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60), s = sec%60;
  return (h? h+':' : '') + String(m).padStart(h?2:1,'0') + ':' + String(s).padStart(2,'0');
}
function fmtSize(b){
  if(!b) return '';
  const mb = b/1048576;
  return mb >= 1024 ? (mb/1024).toFixed(1)+' ГБ' : mb.toFixed(0)+' МБ';
}
function esc(t){ const d=document.createElement('div'); d.textContent=t||''; return d.innerHTML; }
function dlHref(key, name){ return '/download?key='+encodeURIComponent(key)+'&name='+encodeURIComponent(name||''); }

// Код урока по группе: AK → AP, остальные совпадают с группой.
function lessonCode(g){ return g === 'AK' ? 'AP' : g; }

// Имя файла: «Группа AK 1234  урок AP 5678» (два пробела перед «урок»).
function nameFrom(g, d1, d2){ return 'Группа '+g+' '+d1+'  урок '+lessonCode(g)+' '+d2; }

// Изменение группы или цифр обновляет «урок XX» и ссылку «Скачать» в строке.
function onNameChange(e){
  const tr = e.target.closest('tr');
  if(!tr || !e.target.closest('.namecell')) return;
  const g = tr.querySelector('.grp').value;
  tr.querySelector('.lesson').textContent = 'урок '+lessonCode(g);
  const a = tr.querySelector('a.dl');
  a.href = dlHref(a.dataset.key,
    nameFrom(g, tr.querySelector('.n1').value, tr.querySelector('.n2').value));
}
tbody.addEventListener('input', onNameChange);
tbody.addEventListener('change', onNameChange);

async function run(){
  status.textContent = 'Загрузка…';
  table.hidden = true;
  tbody.innerHTML = '';
  try {
    const res = await fetch('/api/search?q=' + encodeURIComponent(q.value));
    const data = await res.json();
    if(data.error){ status.textContent = 'Ошибка: ' + data.error; return; }
    const rows = data.recordings || [];
    if(!rows.length){ status.innerHTML = '<span class="empty">Ничего не найдено за 3 дня.</span>'; return; }
    status.textContent = 'Найдено: ' + rows.length;
    for(const r of rows){
      const tr = document.createElement('tr');
      tr.innerHTML =
        '<td class="title">'+esc(r.title)+'</td>' +
        '<td class="teacher">'+esc(r.teacher)+(r.post?'<small>'+esc(r.post)+'</small>':'')+'</td>' +
        '<td>'+fmtDate(r.createdDate)+'</td>' +
        '<td>'+fmtDur(r.duration)+'</td>' +
        '<td>'+fmtSize(r.size)+'</td>' +
        '<td class="namecell">' +
          '<select class="grp">' +
            '<option value="AK">Группа AK</option>' +
            '<option value="PG">Группа PG</option>' +
            '<option value="NT">Группа NT</option>' +
          '</select> ' +
          '<input class="num n1" type="text" placeholder="цифры"> ' +
          '<span class="lesson">урок AP</span> ' +
          '<input class="num n2" type="text" placeholder="цифры">' +
        '</td>' +
        '<td><a class="open" href="'+esc(r.pageUrl)+'" target="_blank" rel="noopener">Открыть в Толке</a></td>' +
        '<td><a class="dl" data-key="'+esc(r.key)+'" href="'+dlHref(r.key, nameFrom("AK","",""))+'">Скачать</a></td>';
      tbody.appendChild(tr);
    }
    table.hidden = false;
  } catch(e){
    status.textContent = 'Ошибка: ' + e;
  }
}
go.onclick = run;
q.addEventListener('keydown', e => { if(e.key==='Enter') run(); });
run();
</script>
</body>
</html>
"""


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Сервер запущен. Откройте http://{HOST}:{PORT}")
    print("Остановить: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
        server.shutdown()


if __name__ == "__main__":
    main()
