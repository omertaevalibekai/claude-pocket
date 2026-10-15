// Claude Pocket — установщик. Запустите один раз в Scriptable:
// он скачает виджет и сохранит его как скрипт «Claude Code».
// Запустите ещё раз, чтобы обновить виджет.
const URL_BASE = "__POCKET_URL__";
const READ_KEY = "__POCKET_KEY__";

const req = new Request(URL_BASE + "/widget.js");
req.headers = { "X-Pocket-Key": READ_KEY };
const code = await req.loadString();
if (!code.includes("Claude Pocket")) throw new Error("Сервер не отдал скрипт: " + code.slice(0, 160));

let fm = FileManager.local();
try { fm = FileManager.iCloud(); fm.documentsDirectory(); } catch (e) { fm = FileManager.local(); }
fm.writeString(fm.joinPath(fm.documentsDirectory(), "Claude Code.js"), code);

const done = new Alert();
done.title = "Виджет установлен";
done.message = "В списке Scriptable появился скрипт «Claude Code». Добавьте виджет Scriptable на экран и в его настройках выберите этот скрипт.";
done.addAction("Хорошо");
await done.present();
