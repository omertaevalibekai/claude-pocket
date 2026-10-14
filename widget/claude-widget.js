// Claude Pocket — виджет Claude Code для Scriptable.
// Показывает, что делают сессии Claude Code на компьютере.
// Размеры: малый, средний, большой; на экране блокировки — строка, прямоугольник, круг.
// Нажатие на виджет открывает подробности.

const URL_BASE = "__POCKET_URL__";
const READ_KEY = "__POCKET_KEY__";
const CACHE = "claude-widget-cache.json";

const C = {
  ink: new Color("#0B0B0C"),
  orange: new Color("#FF9F0A"),
  orangeText: Color.dynamic(new Color("#8A4300"), new Color("#FFB648")),
  blue: new Color("#3D7BD9"),
  green: Color.dynamic(new Color("#17652C"), new Color("#7BE39A")),
  greenDot: new Color("#2DB357"),
  bg: Color.dynamic(new Color("#FFFFFF"), new Color("#17181C")),
  fg: Color.dynamic(new Color("#111317"), new Color("#FFFFFF")),
  dim: Color.dynamic(new Color("#4A5260"), new Color("#A3A9B4")),
  grey: Color.dynamic(new Color("#ECEEF2"), new Color("#24262C")),
  white: new Color("#FFFFFF"),
  whiteDim: new Color("#FFFFFF", 0.68),
};

// ------------------------------------------------------------------ данные

async function load() {
  const fm = FileManager.local();
  const cachePath = fm.joinPath(fm.documentsDirectory(), CACHE);
  try {
    const req = new Request(URL_BASE + "/state");
    req.headers = { "X-Pocket-Key": READ_KEY };
    req.timeoutInterval = 10;
    const data = await req.loadJSON();
    if (req.response && req.response.statusCode && req.response.statusCode !== 200) {
      throw new Error("HTTP " + req.response.statusCode);
    }
    if (!data || !data.state) throw new Error("пустой ответ");
    data.fetched = Date.now() / 1000;
    fm.writeString(cachePath, JSON.stringify(data));
    return finish(data, false);
  } catch (e) {
    if (fm.fileExists(cachePath)) {
      const data = JSON.parse(fm.readString(cachePath));
      return finish(data, true);
    }
    return { offline: true, unreachable: true, sessions: [], today: null, ageS: null, sent: null };
  }
}

function finish(data, fromCache) {
  const st = data.state || {};
  const now = Date.now() / 1000;
  const sent = st.sent || 0;
  const ageS = Math.max(0, now - sent);
  // сервер считает состояние в момент запроса: «нет связи» — это только кеш
  return {
    offline: fromCache,
    unreachable: fromCache,
    sessions: st.sessions || [],
    today: st.today || null,
    sent: sent,
    ageS: ageS,
  };
}

function groups(d) {
  const by = (s) => d.sessions.filter((x) => x.state === s);
  return {
    wait: by("wait").concat(by("ask")),
    think: by("think"),
    done: by("done"),
  };
}

function when(ts) { return new Date(ts * 1000); }

function plural(n, one, few, many) {
  const m = n % 100;
  if (m >= 11 && m <= 14) return n + " " + many;
  if (n % 10 === 1) return n + " " + one;
  if (n % 10 >= 2 && n % 10 <= 4) return n + " " + few;
  return n + " " + many;
}

function workText(s) {
  const m = Math.round((s || 0) / 60);
  if (m < 60) return m + " мин";
  return Math.floor(m / 60) + " ч " + (m % 60) + " мин";
}

function waitLabel(x) { return x.state === "ask" ? "ждёт ответа" : "ждёт разрешения"; }

// ------------------------------------------------------------------ кирпичики

function text(stack, value, font, color, opts) {
  const t = stack.addText(value);
  t.font = font;
  t.textColor = color;
  t.lineLimit = (opts && opts.lines) || 1;
  if (opts && opts.scale) t.minimumScaleFactor = opts.scale;
  if (opts && opts.right) t.rightAlignText();
  return t;
}

function timer(stack, ts, font, color) {
  const t = stack.addDate(when(ts));
  t.applyTimerStyle();
  t.font = font;
  t.textColor = color;
  t.lineLimit = 1;
  return t;
}

function dot(stack, color, size) {
  const s = stack.addStack();
  s.size = new Size(size || 7, size || 7);
  s.cornerRadius = (size || 7) / 2;
  s.backgroundColor = color;
  return s;
}

function header(stack, color, label, labelColor) {
  const row = stack.addStack();
  row.layoutHorizontally();
  row.centerAlignContent();
  dot(row, color);
  row.addSpacer(6);
  text(row, label, Font.boldSystemFont(11.5), labelColor);
  return row;
}

function hoursChart(hours, width, height, active, idle) {
  const dc = new DrawContext();
  dc.size = new Size(width, height);
  dc.opaque = false;
  dc.respectScreenScale = true;
  const from = 6, to = 24;
  const slice = hours.slice(from, to);
  const max = Math.max(600, ...slice);
  const gap = 4;
  const bw = (width - gap * (slice.length - 1)) / slice.length;
  slice.forEach((v, i) => {
    const h = Math.max(4, (v / max) * height);
    const p = new Path();
    p.addRoundedRect(new Rect(i * (bw + gap), height - h, bw, h), 2.5, 2.5);
    dc.addPath(p);
    dc.setFillColor(v > 60 ? active : idle);
    dc.fillPath();
  });
  return dc.getImage();
}

function ring(count, accent, width) {
  const size = 58;
  const dc = new DrawContext();
  dc.size = new Size(size, size);
  dc.opaque = false;
  dc.respectScreenScale = true;
  const total = Math.max(1, count.total);
  const r = size / 2 - 4;
  const seg = (Math.PI * 2) / total;
  for (let i = 0; i < total; i++) {
    const start = -Math.PI / 2 + i * seg + 0.08;
    const end = start + seg - 0.16;
    const p = new Path();
    const steps = 18;
    for (let k = 0; k <= steps; k++) {
      const a = start + ((end - start) * k) / steps;
      const pt = new Point(size / 2 + r * Math.cos(a), size / 2 + r * Math.sin(a));
      if (k === 0) p.move(pt); else p.addLine(pt);
    }
    dc.addPath(p);
    dc.setStrokeColor(i < count.lit ? accent : new Color("#FFFFFF", 0.3));
    dc.setLineWidth(width || 5);
    dc.strokePath();
  }
  return dc.getImage();
}

// ------------------------------------------------------------------ малый

function small(d) {
  const w = new ListWidget();
  w.setPadding(14, 14, 14, 14);
  const g = groups(d);

  if (d.offline) return offlineSmall(w, d);

  if (g.wait.length) {
    const x = g.wait[0];
    w.backgroundColor = C.ink;
    const top = w.addStack();
    top.layoutHorizontally();
    top.centerAlignContent();
    dot(top, C.orange);
    top.addSpacer(6);
    text(top, "ждёт ", Font.boldSystemFont(11.5), C.whiteDim);
    timer(top, x.since, Font.semiboldMonospacedSystemFont(11.5), C.whiteDim);
    w.addSpacer();
    text(w, x.name, Font.heavySystemFont(22), C.white, { scale: 0.6 });
    w.addSpacer(3);
    text(w, x.detail.replace(/^ждёт разрешения$/, waitLabel(x)), Font.semiboldSystemFont(13), new Color("#FFB648"), { lines: 2, scale: 0.8 });
    const more = g.wait.length - 1 + g.think.length;
    if (more) {
      w.addSpacer(3);
      const verb = more === g.think.length ? (more === 1 ? " работает" : " работают") : "";
      text(w, "+ ещё " + more + verb, Font.systemFont(11), C.whiteDim);
    }
    return w;
  }

  w.backgroundColor = C.bg;
  if (g.think.length) {
    header(w, C.blue, "Claude Code", C.dim);
    w.addSpacer();
    text(w, String(g.think.length), Font.heavySystemFont(34), C.fg);
    text(w, g.think.length === 1 ? "работает" : "работают", Font.semiboldSystemFont(13), C.fg);
    w.addSpacer(6);
    g.think.slice(0, 2).forEach((x) => {
      const row = w.addStack();
      row.layoutHorizontally();
      text(row, x.name, Font.systemFont(11.5), C.dim);
      row.addSpacer();
      timer(row, x.since, Font.mediumMonospacedSystemFont(11.5), C.dim);
    });
    return w;
  }

  if (g.done.length) {
    const x = g.done[g.done.length - 1];
    header(w, C.greenDot, "только что", C.green);
    w.addSpacer();
    text(w, x.name, Font.heavySystemFont(22), C.fg, { scale: 0.6 });
    w.addSpacer(3);
    text(w, "готово", Font.semiboldSystemFont(13), C.green);
    return w;
  }

  header(w, new Color("#9AA3B0"), "Claude Code", C.dim);
  w.addSpacer();
  text(w, "Всё тихо", Font.heavySystemFont(22), C.fg);
  if (d.today && d.today.sessions) {
    w.addSpacer(6);
    text(w, "Сегодня " + plural(d.today.sessions, "сессия", "сессии", "сессий") + ", " +
      plural(d.today.commits, "коммит", "коммита", "коммитов"), Font.systemFont(12), C.dim, { lines: 2 });
    text(w, workText(d.today.work_s) + " работы", Font.systemFont(11), C.dim);
  }
  return w;
}

function offlineSmall(w, d) {
  w.backgroundColor = C.grey;
  header(w, new Color("#9AA3B0"), "нет связи", C.dim);
  w.addSpacer();
  text(w, "Сервер не отвечает", Font.heavySystemFont(18), C.fg, { lines: 2 });
  if (d.sent) {
    w.addSpacer(6);
    const row = w.addStack();
    text(row, "данные ", Font.systemFont(12), C.dim);
    const t = row.addDate(when(d.sent));
    t.applyRelativeStyle();
    t.font = Font.systemFont(12);
    t.textColor = C.dim;
  }
  return w;
}

// ------------------------------------------------------------------ средний и большой

function sessionRow(stack, x, big) {
  const row = stack.addStack();
  row.layoutHorizontally();
  row.centerAlignContent();
  const waiting = x.state === "wait" || x.state === "ask";
  const bar = row.addStack();
  bar.size = new Size(4, big ? 34 : 30);
  bar.cornerRadius = 2;
  bar.backgroundColor = waiting ? C.orange : x.state === "done" ? C.greenDot : C.blue;
  row.addSpacer(9);
  const col = row.addStack();
  col.layoutVertically();
  text(col, x.name, Font.boldSystemFont(14), C.fg);
  const detail = waiting ? (x.detail === "ждёт разрешения" ? waitLabel(x) : "ждёт · " + x.detail)
    : x.state === "done" ? "готово" : x.detail;
  text(col, detail, Font.systemFont(11.5), waiting ? C.orangeText : x.state === "done" ? C.green : C.dim);
  row.addSpacer();
  if (x.state === "done") {
    const t = row.addDate(when(x.since));
    t.applyRelativeStyle();
    t.font = Font.mediumSystemFont(11.5);
    t.textColor = C.dim;
  } else {
    timer(row, x.since, Font.semiboldMonospacedSystemFont(12), waiting ? C.orangeText : C.dim);
  }
}

function medium(d) {
  const w = new ListWidget();
  w.backgroundColor = C.bg;
  w.setPadding(14, 14, 14, 14);
  const g = groups(d);
  const list = g.wait.concat(g.think, g.done);

  if (d.offline || !list.length) return quietMedium(w, d);

  const body = w.addStack();
  body.layoutHorizontally();
  const left = body.addStack();
  left.layoutVertically();
  left.size = new Size(104, 0);
  left.backgroundColor = C.ink;
  left.cornerRadius = 16;
  left.setPadding(12, 12, 12, 12);
  header(left, g.wait.length ? C.orange : C.blue, "Claude", C.whiteDim);
  left.addSpacer();
  const main = g.wait.length || g.think.length;
  text(left, String(main), Font.heavySystemFont(40), g.wait.length ? C.orange : C.white);
  text(left, g.wait.length ? "ждёт тебя" : (g.think.length === 1 ? "работает" : "работают"), Font.semiboldSystemFont(12), C.white);
  if (g.wait.length && g.think.length) {
    text(left, g.think.length + (g.think.length === 1 ? " работает" : " работают"), Font.systemFont(11), C.whiteDim);
  }

  body.addSpacer(14);
  const right = body.addStack();
  right.layoutVertically();
  list.slice(0, 3).forEach((x, i) => {
    if (i) right.addSpacer();
    sessionRow(right, x, false);
  });
  if (list.length < 3) right.addSpacer();
  return w;
}

function quietMedium(w, d) {
  if (d.offline) {
    w.backgroundColor = C.grey;
    header(w, new Color("#9AA3B0"), "нет связи", C.dim);
    w.addSpacer();
    text(w, "Сервер не отвечает: нет сети или он выключен", Font.heavySystemFont(17), C.fg, { lines: 2 });
    return w;
  }
  const top = w.addStack();
  top.layoutHorizontally();
  top.centerAlignContent();
  dot(top, new Color("#9AA3B0"), 8);
  top.addSpacer(7);
  text(top, "Claude Code", Font.heavySystemFont(13), C.fg);
  top.addSpacer();
  text(top, "всё тихо", Font.systemFont(11), C.dim);
  w.addSpacer(8);
  const t = d.today || { hours: new Array(24).fill(0), sessions: 0, commits: 0, work_s: 0 };
  w.addImage(hoursChart(t.hours, 330, 54, C.blue, new Color("#8891A0", 0.25)));
  w.addSpacer(4);
  const axis = w.addStack();
  text(axis, "6:00", Font.mediumMonospacedSystemFont(10), C.dim);
  axis.addSpacer();
  text(axis, "15:00", Font.mediumMonospacedSystemFont(10), C.dim);
  axis.addSpacer();
  text(axis, "24:00", Font.mediumMonospacedSystemFont(10), C.dim);
  w.addSpacer();
  const stats = w.addStack();
  text(stats, plural(t.sessions, "сессия", "сессии", "сессий"), Font.semiboldSystemFont(12), C.fg);
  stats.addSpacer();
  text(stats, workText(t.work_s) + " работы", Font.semiboldSystemFont(12), C.fg);
  stats.addSpacer();
  text(stats, plural(t.commits, "коммит", "коммита", "коммитов"), Font.semiboldSystemFont(12), C.fg);
  return w;
}

function chip(stack, value, label, bg, fg) {
  const c = stack.addStack();
  c.layoutVertically();
  c.backgroundColor = bg;
  c.cornerRadius = 12;
  c.setPadding(8, 10, 8, 10);
  text(c, String(value), Font.heavySystemFont(20), fg);
  text(c, label, Font.systemFont(11), fg);
  return c;
}

function large(d) {
  const w = new ListWidget();
  w.backgroundColor = C.bg;
  w.setPadding(16, 16, 16, 16);
  const g = groups(d);

  const top = w.addStack();
  top.layoutHorizontally();
  top.centerAlignContent();
  dot(top, d.offline ? new Color("#9AA3B0") : C.orange, 9);
  top.addSpacer(8);
  text(top, "Claude Code", Font.heavySystemFont(15), C.fg);
  top.addSpacer();
  dot(top, d.offline ? new Color("#9AA3B0") : C.greenDot, 6);
  top.addSpacer(5);
  text(top, d.offline ? "нет связи" : "на связи", Font.systemFont(11), C.dim);

  w.addSpacer(12);
  const chips = w.addStack();
  chips.layoutHorizontally();
  chip(chips, g.wait.length, "ждёт тебя", Color.dynamic(new Color("#FFF0DB"), new Color("#2A1E10")), C.orangeText);
  chips.addSpacer(8);
  chip(chips, g.think.length, "работают", Color.dynamic(new Color("#E4ECF8"), new Color("#142033")),
    Color.dynamic(new Color("#2B3A55"), new Color("#C4D8FF")));
  chips.addSpacer(8);
  chip(chips, g.done.length, "готово", Color.dynamic(new Color("#DDF3E3"), new Color("#13261A")), C.green);
  chips.addSpacer();

  w.addSpacer(14);
  const list = g.wait.concat(g.think, g.done).slice(0, 4);
  if (!list.length) {
    text(w, d.offline ? "Нет связи с сервером" : "Всё тихо", Font.heavySystemFont(20), C.fg);
    w.addSpacer(10);
    const t = d.today;
    if (t) w.addImage(hoursChart(t.hours, 320, 70, C.blue, new Color("#8891A0", 0.25)));
  }
  list.forEach((x, i) => {
    if (i) w.addSpacer(10);
    sessionRow(w, x, true);
  });
  w.addSpacer();
  if (d.today) {
    const foot = w.addStack();
    text(foot, "Сегодня: " + plural(d.today.sessions, "сессия", "сессии", "сессий"), Font.systemFont(11.5), C.dim);
    foot.addSpacer();
    text(foot, workText(d.today.work_s) + " работы", Font.systemFont(11.5), C.dim);
    foot.addSpacer();
    text(foot, plural(d.today.commits, "коммит", "коммита", "коммитов"), Font.systemFont(11.5), C.dim);
  }
  return w;
}

// ------------------------------------------------------------------ экран блокировки

function lockRect(d) {
  const w = new ListWidget();
  const g = groups(d);
  if (d.offline) {
    text(w, "Claude Code", Font.heavySystemFont(14), C.white);
    text(w, "нет связи с сервером", Font.semiboldSystemFont(13), C.white);
    return w;
  }
  if (g.wait.length) {
    const x = g.wait[0];
    const top = w.addStack();
    top.layoutHorizontally();
    text(top, x.name, Font.heavySystemFont(14), C.white);
    top.addSpacer();
    timer(top, x.since, Font.semiboldMonospacedSystemFont(12), C.white);
    text(w, waitLabel(x), Font.semiboldSystemFont(13), C.white);
    if (x.detail && x.detail !== "ждёт разрешения") text(w, x.detail, Font.mediumMonospacedSystemFont(11.5), C.whiteDim);
    return w;
  }
  if (g.think.length) {
    const x = g.think[0];
    const top = w.addStack();
    top.layoutHorizontally();
    text(top, x.name, Font.heavySystemFont(14), C.white);
    top.addSpacer();
    timer(top, x.since, Font.semiboldMonospacedSystemFont(12), C.white);
    text(w, x.detail || "думает", Font.semiboldSystemFont(13), C.white);
    if (g.think.length > 1) text(w, "+ ещё " + (g.think.length - 1), Font.systemFont(11.5), C.whiteDim);
    return w;
  }
  text(w, "Claude Code", Font.heavySystemFont(14), C.white);
  text(w, "всё тихо", Font.semiboldSystemFont(13), C.white);
  if (d.today) text(w, plural(d.today.commits, "коммит", "коммита", "коммитов") + " · " + workText(d.today.work_s), Font.systemFont(11.5), C.whiteDim);
  return w;
}

function lockCircle(d) {
  const w = new ListWidget();
  const g = groups(d);
  const total = g.wait.length + g.think.length;
  const stack = w.addStack();
  stack.layoutVertically();
  stack.centerAlignContent();
  if (d.offline) {
    text(stack, "—", Font.heavySystemFont(20), C.white);
    text(stack, "нет связи", Font.boldSystemFont(9), C.white);
    return w;
  }
  w.backgroundImage = ring({ total: Math.max(total, 1), lit: total ? g.wait.length || total : 0 }, C.white, 5);
  text(stack, String(g.wait.length || total), Font.heavySystemFont(20), C.white);
  text(stack, g.wait.length ? "ждёт" : "сессии", Font.boldSystemFont(9), C.white);
  return w;
}

function lockInline(d) {
  const w = new ListWidget();
  const g = groups(d);
  let line = "Claude: всё тихо";
  if (d.offline) line = "Claude: нет связи";
  else if (g.wait.length || g.think.length) {
    const parts = [];
    if (g.wait.length) parts.push(g.wait.length + " ждёт");
    if (g.think.length) parts.push(g.think.length + (g.think.length === 1 ? " работает" : " работают"));
    line = "◉ " + parts.join(" · ");
  }
  text(w, line, Font.semiboldSystemFont(14), C.white);
  return w;
}

// ------------------------------------------------------------------ подробности по нажатию

function esc(s) {
  return String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function detailsHtml(d) {
  const g = groups(d);
  const now = Date.now() / 1000;
  const ago = (ts) => {
    const m = Math.max(0, Math.round((now - ts) / 60));
    return m < 1 ? "только что" : m < 60 ? m + " мин" : Math.floor(m / 60) + " ч " + (m % 60) + " мин";
  };
  const block = (title, items, cls) => !items.length ? "" :
    `<h2 class="${cls}">${title}</h2><div class="card">` + items.map((x) =>
      `<div class="row"><div class="col"><b>${esc(x.name)}</b><span>${esc(x.state === "done" ? "готово" : x.detail)}</span></div>` +
      `<em>${ago(x.since)}</em></div>`).join("") + "</div>";
  const t = d.today;
  const status = d.offline ? "сервер не отвечает, показаны последние данные" : "на связи";
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#F2F3F6;--card:#fff;--fg:#111317;--dim:#4A5260;--line:#ECEEF2;--wait:#8A4300}
@media (prefers-color-scheme:dark){:root{--bg:#0E1016;--card:#1A1C21;--fg:#fff;--dim:#A3A9B4;--line:#2A2D35;--wait:#FFB648}}
body{margin:0;padding:20px 16px 40px;background:var(--bg);color:var(--fg);font:15px -apple-system,system-ui,sans-serif}
.head{display:flex;gap:10px;align-items:center;margin-bottom:18px}
.logo{width:34px;height:34px;border-radius:10px;background:#0B0B0C;display:grid;place-items:center}
.logo i{width:10px;height:10px;border-radius:50%;background:#FF9F0A}
.head b{font-size:22px;display:block}.head small{color:var(--dim);font-size:12px}
h2{font-size:12px;letter-spacing:.06em;color:var(--dim);margin:18px 4px 8px}h2.wait{color:var(--wait)}
.card{background:var(--card);border-radius:16px;overflow:hidden}
.row{display:flex;gap:10px;align-items:center;padding:12px 14px;border-top:1px solid var(--line)}.row:first-child{border-top:0}
.col{display:flex;flex-direction:column;flex:1;min-width:0}.col span{color:var(--dim);font-size:13px}
em{font-style:normal;color:var(--dim);font-size:13px;font-variant-numeric:tabular-nums}
.empty{color:var(--dim);padding:16px 4px}
.foot{color:var(--dim);font-size:13px;margin:20px 4px 0;line-height:1.5}
</style></head><body>
<div class="head"><span class="logo"><i></i></span><div><b>Claude Code</b><small>${status}</small></div></div>
${block("ЖДЁТ ТЕБЯ", g.wait, "wait")}${block("РАБОТАЮТ", g.think, "")}${block("ГОТОВО", g.done, "")}
${!g.wait.length && !g.think.length && !g.done.length ? '<div class="empty">Сейчас ни одна сессия не работает.</div>' : ""}
${g.wait.length ? '<div class="foot">Ответить можно на компьютере, в терминале Claude Code.</div>' : ""}
${t ? `<div class="foot">Сегодня: ${plural(t.sessions, "сессия", "сессии", "сессий")}, ${workText(t.work_s)} работы Claude, ${plural(t.commits, "коммит", "коммита", "коммитов")}.</div>` : ""}
</body></html>`;
}

// ------------------------------------------------------------------ запуск

async function main() {
  const d = await load();
  if (config.runsInWidget || config.runsInAccessoryWidget) {
    const family = config.widgetFamily;
    const make = { small, medium, large, extraLarge: large,
      accessoryRectangular: lockRect, accessoryCircular: lockCircle, accessoryInline: lockInline }[family] || small;
    const w = make(d);
    w.refreshAfterDate = new Date(Date.now() + 5 * 60 * 1000);
    Script.setWidget(w);
  } else {
    const view = new WebView();
    await view.loadHTML(detailsHtml(d));
    await view.present();
  }
  Script.complete();
}

await main();
