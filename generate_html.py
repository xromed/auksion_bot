"""
Генерирует статические HTML страницы из data/lots.json и data/history.json.
Результат помещается в docs/ (GitHub Pages).

Запуск: python generate_html.py
"""
import json
from pathlib import Path
from datetime import datetime

DATA_DIR  = Path("data")
DOCS_DIR  = Path("docs")
LOTS_FILE = DATA_DIR / "lots.json"
HIST_FILE = DATA_DIR / "history.json"

GROUP_NAMES = {1: "Недвижимость", 2: "Авто", 15: "Банкротство"}
GROUP_ICONS = {1: "🏠", 2: "🚗", 15: "⚖️"}


def load_data():
    if not LOTS_FILE.exists():
        return {}, 0, ""
    raw = json.loads(LOTS_FILE.read_text("utf-8"))
    return raw.get("lots", {}), raw.get("usd_rate", 0), raw.get("updated_at", "")


def load_history():
    if not HIST_FILE.exists():
        return {}
    raw = json.loads(HIST_FILE.read_text("utf-8"))
    return raw.get("daily", {})


def fmt_updated(updated_at: str) -> str:
    try:
        dt = datetime.fromisoformat(updated_at)
        return dt.strftime("%d.%m.%Y в %H:%M")
    except:
        return updated_at


def build_lots_json_for_js(lots: dict) -> str:
    """Возвращает JS-переменную со всеми лотами."""
    return json.dumps(list(lots.values()), ensure_ascii=False)


def build_history_json_for_js(history: dict) -> str:
    """Возвращает отсортированную историю для графиков."""
    sorted_days = sorted(history.items())
    return json.dumps([
        {"date": d, **v} for d, v in sorted_days
    ], ensure_ascii=False)


def generate_index(lots: dict, usd_rate: float, updated_at: str):
    """Генерирует docs/index.html."""
    lots_js    = build_lots_json_for_js(lots)
    history_js = build_history_json_for_js(load_history())
    updated    = fmt_updated(updated_at)
    usd_str   = f"{usd_rate:,.0f}".replace(",", " ") if usd_rate else "—"

    # Считаем статистику
    counts = {1: {"active": 0, "closed": 0, "dupe": 0},
              2: {"active": 0, "closed": 0, "dupe": 0},
              15: {"active": 0, "closed": 0, "dupe": 0}}
    for lot in lots.values():
        gid = lot.get("group_id", 1)
        if gid not in counts:
            continue
        if lot.get("is_duplicate"):
            counts[gid]["dupe"] += 1
        elif lot.get("is_closed"):
            counts[gid]["closed"] += 1
        else:
            counts[gid]["active"] += 1

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>E-Auksion Ташкент — Лоты недвижимости и авто</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: #f0f2f5; color: #1a1a2e; font-size: 14px; }}

/* Header */
.header {{ background: linear-gradient(135deg, #1565C0, #0D47A1);
           color: #fff; padding: 16px 24px; display: flex;
           justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }}
.header h1 {{ font-size: 20px; font-weight: 700; }}
.header .meta {{ font-size: 12px; opacity: 0.85; text-align: right; }}
.header .meta b {{ font-size: 14px; }}

/* Nav tabs */
.nav {{ background: #fff; border-bottom: 2px solid #e0e0e0;
        display: flex; gap: 0; overflow-x: auto; }}
.nav-tab {{ padding: 12px 20px; cursor: pointer; font-weight: 600; font-size: 14px;
            color: #546e7a; border-bottom: 3px solid transparent; white-space: nowrap;
            transition: color .2s, border-color .2s; }}
.nav-tab:hover {{ color: #1565C0; }}
.nav-tab.active {{ color: #1565C0; border-bottom-color: #1565C0; }}

/* Summary cards */
.summary {{ display: flex; gap: 12px; padding: 16px 20px; flex-wrap: wrap; }}
.card {{ background: #fff; border-radius: 10px; padding: 14px 18px;
         box-shadow: 0 2px 8px rgba(0,0,0,.07); min-width: 140px; flex: 1; }}
.card .label {{ font-size: 11px; color: #90a4ae; text-transform: uppercase; letter-spacing: .5px; }}
.card .value {{ font-size: 26px; font-weight: 800; color: #1565C0; margin: 4px 0 2px; }}
.card .sub {{ font-size: 12px; color: #78909c; }}
.card.green .value {{ color: #2e7d32; }}
.card.red   .value {{ color: #c62828; }}
.card.gray  .value {{ color: #607d8b; }}

/* Tab content */
.tab-content {{ display: none; padding: 0 20px 32px; }}
.tab-content.active {{ display: block; }}

/* Controls */
.controls {{ display: flex; gap: 10px; padding: 14px 0 10px; flex-wrap: wrap; align-items: center; }}
.controls input {{ flex: 1; min-width: 200px; padding: 8px 12px;
                   border: 1px solid #ccc; border-radius: 8px; font-size: 14px; }}
.controls select {{ padding: 8px 10px; border: 1px solid #ccc; border-radius: 8px;
                    font-size: 14px; background: #fff; cursor: pointer; }}
.controls .count {{ margin-left: auto; font-size: 13px; color: #78909c; white-space: nowrap; }}

/* Table */
.table-wrap {{ overflow-x: auto; border-radius: 10px;
               box-shadow: 0 2px 12px rgba(0,0,0,.08); }}
table {{ width: 100%; border-collapse: collapse; background: #fff; min-width: 900px; }}
thead th {{ background: #1565C0; color: #fff; padding: 10px 12px;
            text-align: left; font-size: 12px; font-weight: 600;
            white-space: nowrap; position: sticky; top: 0; cursor: pointer; }}
thead th:hover {{ background: #1976D2; }}
thead th.sort-asc::after  {{ content: " ▲"; }}
thead th.sort-desc::after {{ content: " ▼"; }}
tbody tr {{ border-bottom: 1px solid #f0f0f0; transition: background .15s; }}
tbody tr:hover {{ background: #f5f8ff; }}
tbody td {{ padding: 9px 12px; vertical-align: middle; }}
tbody td a {{ color: #1565C0; text-decoration: none; font-weight: 600; }}
tbody td a:hover {{ text-decoration: underline; }}

/* Row states */
tr.row-closed {{ opacity: .6; }}
tr.row-closed td:nth-child(6) {{ font-weight: 700; }}
tr.row-duplicate {{ background: #fffde7 !important; }}
tr.row-duplicate td:first-child::before {{ content: "↩ "; color: #f57f17; }}

/* Status badges */
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px;
          font-size: 11px; font-weight: 700; white-space: nowrap; }}
.badge-active   {{ background: #e8f5e9; color: #2e7d32; }}
.badge-closed   {{ background: #ffebee; color: #c62828; }}
.badge-pending  {{ background: #fff8e1; color: #f57f17; }}
.badge-dupe     {{ background: #fff9c4; color: #827717; }}

/* Auction type */
.up   {{ color: #2e7d32; font-weight: 700; }}
.down {{ color: #c62828; font-weight: 700; }}

/* Dashboard */
.dash-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; padding: 16px 0 32px; }}
@media (max-width: 700px) {{ .dash-grid {{ grid-template-columns: 1fr; }} }}
.chart-card {{ background: #fff; border-radius: 12px; padding: 20px;
               box-shadow: 0 2px 12px rgba(0,0,0,.08); }}
.chart-card h3 {{ font-size: 15px; color: #1565C0; margin-bottom: 16px; }}

/* Responsive */
@media (max-width: 600px) {{
  .header {{ padding: 12px 16px; }}
  .header h1 {{ font-size: 16px; }}
  .summary {{ padding: 12px; gap: 8px; }}
  .tab-content {{ padding: 0 12px 24px; }}
  .controls {{ padding: 10px 0 8px; }}
}}
</style>
</head>
<body>

<div class="header">
  <h1>🏛 E-Auksion — Ташкент</h1>
  <div class="meta">
    Обновлено: <b>{updated}</b><br>
    💱 1 USD = <b>{usd_str} сум</b>
  </div>
</div>

<div class="nav">
  <div class="nav-tab active" onclick="switchTab('realty', this)">
    🏠 Недвижимость <span id="cnt-1"></span>
  </div>
  <div class="nav-tab" onclick="switchTab('auto', this)">
    🚗 Авто <span id="cnt-2"></span>
  </div>
  <div class="nav-tab" onclick="switchTab('bankruptcy', this)">
    ⚖️ Банкротство <span id="cnt-15"></span>
  </div>
  <div class="nav-tab" onclick="switchTab('dashboard', this)">
    📊 Дашборд
  </div>
</div>

<!-- Summary cards -->
<div class="summary" id="summary-cards"></div>

<!-- Вкладки лотов -->
<div id="tab-realty" class="tab-content active">
  <div class="controls">
    <input type="text" id="search-1" placeholder="Поиск по названию, адресу..." oninput="renderTable(1)">
    <select id="filter-status-1" onchange="renderTable(1)">
      <option value="">Все статусы</option>
      <option value="active">Только активные</option>
      <option value="closed">Только закрытые</option>
    </select>
    <select id="sort-1" onchange="renderTable(1)">
      <option value="date_desc">Сначала новые</option>
      <option value="price_asc">Цена ↑</option>
      <option value="price_desc">Цена ↓</option>
    </select>
    <span class="count" id="count-1"></span>
  </div>
  <div class="table-wrap"><table id="table-1">
    <thead><tr>
      <th>ID</th><th>Тип</th><th>Название</th><th>Адрес</th>
      <th>Статус</th>
      <th>Нач. цена (сум)</th><th>Нач. ($)</th>
      <th>Добавлен</th><th>Дедлайн</th>
      <th>Заявки</th><th>Карта</th>
    </tr></thead>
    <tbody id="tbody-1"></tbody>
  </table></div>
</div>

<div id="tab-auto" class="tab-content">
  <div class="controls">
    <input type="text" id="search-2" placeholder="Поиск по марке, названию, адресу..." oninput="renderTable(2)">
    <select id="filter-status-2" onchange="renderTable(2)">
      <option value="">Все статусы</option>
      <option value="active">Только активные</option>
      <option value="closed">Только закрытые</option>
    </select>
    <select id="sort-2" onchange="renderTable(2)">
      <option value="date_desc">Сначала новые</option>
      <option value="price_asc">Цена ↑</option>
      <option value="price_desc">Цена ↓</option>
    </select>
    <span class="count" id="count-2"></span>
  </div>
  <div class="table-wrap"><table id="table-2">
    <thead><tr>
      <th>ID</th><th>Марка</th><th>Название</th><th>Адрес</th>
      <th>Статус</th>
      <th>Нач. цена (сум)</th><th>Нач. ($)</th>
      <th>Добавлен</th><th>Дедлайн</th>
      <th>Заявки</th><th>Карта</th>
    </tr></thead>
    <tbody id="tbody-2"></tbody>
  </table></div>
</div>

<div id="tab-bankruptcy" class="tab-content">
  <div class="controls">
    <input type="text" id="search-15" placeholder="Поиск по названию, адресу..." oninput="renderTable(15)">
    <select id="filter-status-15" onchange="renderTable(15)">
      <option value="">Все статусы</option>
      <option value="active">Только активные</option>
      <option value="closed">Только закрытые</option>
    </select>
    <select id="sort-15" onchange="renderTable(15)">
      <option value="date_desc">Сначала новые</option>
      <option value="price_asc">Цена ↑</option>
      <option value="price_desc">Цена ↓</option>
    </select>
    <span class="count" id="count-15"></span>
  </div>
  <div class="table-wrap"><table id="table-15">
    <thead><tr>
      <th>ID</th><th>Тип</th><th>Название</th><th>Адрес</th>
      <th>Статус</th>
      <th>Нач. цена (сум)</th><th>Нач. ($)</th>
      <th>Добавлен</th><th>Дедлайн</th>
      <th>Заявки</th><th>Карта</th>
    </tr></thead>
    <tbody id="tbody-15"></tbody>
  </table></div>
</div>

<div id="tab-dashboard" class="tab-content">
  <div class="dash-grid">
    <div class="chart-card" style="grid-column: 1/-1">
      <h3>📅 Новых лотов по дням (последние 30 дней)</h3>
      <canvas id="chartDaily" height="100"></canvas>
    </div>
    <div class="chart-card">
      <h3>📆 Новых лотов по месяцам</h3>
      <canvas id="chartMonthly" height="180"></canvas>
    </div>
    <div class="chart-card">
      <h3>🥧 Структура активных лотов</h3>
      <canvas id="chartPie" height="180"></canvas>
    </div>
  </div>
</div>

<script>
const LOTS = {lots_js};
const HISTORY = {history_js};

// ─── Табы ───────────────────────────────────────
function switchTab(name, el) {{
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  el.classList.add('active');
  if (name === 'dashboard') renderCharts();
}}

// ─── Рендер таблиц ──────────────────────────────
const sortState = {{}};

function fmtUsd(val) {{
  if (!val && val !== 0) return '—';
  const num = parseInt(String(val).replace(/[^\d]/g, ''));
  if (isNaN(num) || num === 0) return '—';
  return '$ ' + num.toLocaleString('ru-RU');
}}

function statusBadge(lot) {{
  const s = lot.status || '';
  const closed = ['Завершён','Отменён'].includes(s);
  const pending = ['Приостановлен','Ожидает','На рассмотрении'].includes(s);
  if (lot.is_duplicate) return `<span class="badge badge-dupe">↩ Дубль</span>`;
  if (closed)   return `<span class="badge badge-closed">❌ ${{s}}</span>`;
  if (pending)  return `<span class="badge badge-pending">⏸ ${{s}}</span>`;
  return `<span class="badge badge-active">✅ ${{s}}</span>`;
}}

function renderTable(gid) {{
  const search  = (document.getElementById('search-' + gid)?.value || '').toLowerCase();
  const fStatus = document.getElementById('filter-status-' + gid)?.value || '';
  const sortVal = document.getElementById('sort-' + gid)?.value || 'date_desc';
  const tbody   = document.getElementById('tbody-' + gid);
  if (!tbody) return;

  let rows = LOTS.filter(l => l.group_id === gid);

  // Поиск
  if (search) {{
    rows = rows.filter(l =>
      (l.name    || '').toLowerCase().includes(search) ||
      (l.address || '').toLowerCase().includes(search) ||
      (l.display_type || '').toLowerCase().includes(search)
    );
  }}

  // Фильтр статуса
  if (fStatus === 'active')  rows = rows.filter(l => !l.is_closed && !l.is_duplicate);
  if (fStatus === 'closed')  rows = rows.filter(l => l.is_closed);

  // Сортировка: активные сверху, дубли и закрытые снизу
  rows.sort((a, b) => {{
    const aDown = a.is_closed || a.is_duplicate ? 1 : 0;
    const bDown = b.is_closed || b.is_duplicate ? 1 : 0;
    if (aDown !== bDown) return aDown - bDown;
    if (sortVal === 'price_asc')  return a.start_price - b.start_price;
    if (sortVal === 'price_desc') return b.start_price - a.start_price;
    // date_desc: больший ID = новее
    return parseInt(b.id) - parseInt(a.id);
  }});

  document.getElementById('count-' + gid).textContent =
    `${{rows.filter(r => !r.is_closed && !r.is_duplicate).length}} активных / ${{rows.length}} всего`;

  tbody.innerHTML = rows.map(l => {{
    const trClass = l.is_duplicate ? 'row-duplicate' : (l.is_closed ? 'row-closed' : '');
    const mapCell = l.map_url
      ? `<a href="${{l.map_url}}" target="_blank">📍</a>`
      : '—';
    const deadline = (l.deadline || '').split(' ')[0];  // убираем время
    return `<tr class="${{trClass}}">
      <td><a href="${{l.url}}" target="_blank">${{l.id}}</a></td>
      <td>${{l.display_type || '—'}}</td>
      <td style="max-width:220px;word-break:break-word">${{l.name || '—'}}</td>
      <td style="max-width:180px;font-size:12px;color:#546e7a">${{l.address || '—'}}</td>
      <td>${{statusBadge(l)}}</td>
      <td style="text-align:right;font-weight:600">${{l.start_price_fmt || '—'}}</td>
      <td style="text-align:right;color:#1565C0">${{fmtUsd(l.start_price_usd)}}</td>
      <td style="white-space:nowrap;font-size:12px;color:#546e7a">${{l.added_date || '—'}}</td>
      <td style="white-space:nowrap;font-size:12px">${{deadline || '—'}}</td>
      <td style="text-align:center">${{l.orders ?? '—'}}</td>
      <td style="text-align:center">${{mapCell}}</td>
    </tr>`;
  }}).join('');
}}

// ─── Summary cards ───────────────────────────────
function renderSummary() {{
  const counts = {{1: {{a:0,c:0,d:0}}, 2: {{a:0,c:0,d:0}}, 15: {{a:0,c:0,d:0}}}};
  LOTS.forEach(l => {{
    if (!counts[l.group_id]) return;
    if (l.is_duplicate) counts[l.group_id].d++;
    else if (l.is_closed) counts[l.group_id].c++;
    else counts[l.group_id].a++;
  }});
  const icons = {{1:'🏠',2:'🚗',15:'⚖️'}};
  const names = {{1:'Недвижимость',2:'Авто',15:'Банкротство'}};
  const el = document.getElementById('summary-cards');
  let html = '';
  [1,2,15].forEach(gid => {{
    const c = counts[gid];
    document.getElementById('cnt-'+gid).textContent = `(${{c.a}})`;
    html += `<div class="card green">
      <div class="label">${{icons[gid]}} ${{names[gid]}}</div>
      <div class="value">${{c.a}}</div>
      <div class="sub">активных · ${{c.c}} закр · ${{c.d}} дублей</div>
    </div>`;
  }});
  el.innerHTML = html;
}}

// ─── Графики дашборда ────────────────────────────
let chartsBuilt = false;
function renderCharts() {{
  if (chartsBuilt) return;
  chartsBuilt = true;

  // Последние 30 дней
  const last30 = HISTORY.slice(-30);
  const labels30 = last30.map(d => d.date.slice(5));  // MM-DD
  const ctxDaily = document.getElementById('chartDaily').getContext('2d');
  new Chart(ctxDaily, {{
    type: 'bar',
    data: {{
      labels: labels30,
      datasets: [
        {{ label: '🏠 Недвижимость', data: last30.map(d => d.realty || 0),     backgroundColor: 'rgba(21,101,192,.8)' }},
        {{ label: '🚗 Авто',          data: last30.map(d => d.auto || 0),       backgroundColor: 'rgba(46,125,50,.8)'  }},
        {{ label: '⚖️ Банкротство',   data: last30.map(d => d.bankruptcy || 0), backgroundColor: 'rgba(198,40,40,.8)'  }},
      ]
    }},
    options: {{ responsive: true, scales: {{ x: {{ stacked: true }}, y: {{ stacked: true, beginAtZero: true }} }},
               plugins: {{ legend: {{ position: 'bottom' }} }} }}
  }});

  // По месяцам
  const byMonth = {{}};
  HISTORY.forEach(d => {{
    const m = d.date.slice(0, 7);
    if (!byMonth[m]) byMonth[m] = {{realty:0, auto:0, bankruptcy:0}};
    byMonth[m].realty     += d.realty || 0;
    byMonth[m].auto       += d.auto || 0;
    byMonth[m].bankruptcy += d.bankruptcy || 0;
  }});
  const months = Object.keys(byMonth).sort();
  const ctxM = document.getElementById('chartMonthly').getContext('2d');
  new Chart(ctxM, {{
    type: 'bar',
    data: {{
      labels: months,
      datasets: [
        {{ label: '🏠', data: months.map(m => byMonth[m].realty),     backgroundColor: 'rgba(21,101,192,.8)' }},
        {{ label: '🚗', data: months.map(m => byMonth[m].auto),       backgroundColor: 'rgba(46,125,50,.8)'  }},
        {{ label: '⚖️', data: months.map(m => byMonth[m].bankruptcy), backgroundColor: 'rgba(198,40,40,.8)'  }},
      ]
    }},
    options: {{ responsive: true, scales: {{ x: {{ stacked: true }}, y: {{ stacked: true, beginAtZero: true }} }},
               plugins: {{ legend: {{ position: 'bottom' }} }} }}
  }});

  // Pie — структура активных
  const active = LOTS.filter(l => !l.is_closed && !l.is_duplicate);
  const pc = {{1:0, 2:0, 15:0}};
  active.forEach(l => {{ if (pc[l.group_id] !== undefined) pc[l.group_id]++; }});
  const ctxPie = document.getElementById('chartPie').getContext('2d');
  new Chart(ctxPie, {{
    type: 'doughnut',
    data: {{
      labels: ['🏠 Недвижимость', '🚗 Авто', '⚖️ Банкротство'],
      datasets: [{{ data: [pc[1], pc[2], pc[15]],
        backgroundColor: ['#1565C0','#2E7D32','#C62828'],
        borderWidth: 3, borderColor: '#fff' }}]
    }},
    options: {{ responsive: true, plugins: {{ legend: {{ position: 'bottom' }} }} }}
  }});
}}

// ─── Init ────────────────────────────────────────
renderSummary();
renderTable(1);
renderTable(2);
renderTable(15);
</script>
</body>
</html>"""

    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "index.html").write_text(html, "utf-8")
    print(f"[html] Создан docs/index.html ({len(html)//1024} КБ, {len(lots)} лотов)")


def main():
    print("[html] Читаю данные...")
    lots, usd_rate, updated_at = load_data()
    if not lots:
        print("[html] data/lots.json пуст или не существует. Сначала запустите bot.py")
        return
    print(f"[html] Лотов: {len(lots)}")
    generate_index(lots, usd_rate, updated_at)
    print("[html] Готово! Открой docs/index.html")


if __name__ == "__main__":
    main()
