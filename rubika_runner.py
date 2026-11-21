import os, sys, json, glob, importlib.util, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SDIR = os.path.join(HERE, "state")
os.makedirs(SDIR, exist_ok=True)
STATS = os.path.join(SDIR, "stats.json")
TOKEN = os.environ.get("RUBIKA_TOKEN", "")
CHAT = os.environ.get("RUBIKA_CHAT_ID", "")
MIN_N, WINDOW = 15, 20  # حداقل ۱۵ نتیجه؛ ارزیابی روی ۲۰ نتیجه آخر
CLOSED = ("TP1_HIT", "STOPPED", "EXPIRED", "CANCELLED_TP_FIRST",
          "CANCELLED_DISTANCE", "CANCELLED_STRUCTURE")


def find_analyzer():
    seen = []
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "state"]
        for f in sorted(files):
            if not f.endswith(".py") or f == "rubika_runner.py":
                continue
            p = os.path.join(root, f)
            seen.append(os.path.relpath(p, HERE))
            try:
                t = open(p, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            if "def run_once" in t and "def dispatch_final_verdict" in t:
                return p
    print("فایل‌های py دیده‌شده:", seen or "هیچ")
    sys.exit("فایل تحلیلگر پیدا نشد؛ فایل کامل ربات طلا (.py) را در مخزن آپلود کن")


spec = importlib.util.spec_from_file_location("analyzer", find_analyzer())
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.STATE_FILE = os.path.join(SDIR, "xauusd_state.json")

cap = {"reports": [], "ctx": None, "verdict": None}
_eval, _disp = mod.evaluate_active_signals, mod.dispatch_final_verdict


def eval_wrap(state, bars, now):
    r = _eval(state, bars, now)
    mod.save_state(state)  # ذخیره وضعیت بسته‌شده‌ها تا دوباره گزارش نشوند
    cap["reports"] = r
    return r


def disp_wrap(ctx):
    v = _disp(ctx)
    cap["ctx"], cap["verdict"] = ctx, v
    return v


mod.evaluate_active_signals = eval_wrap
mod.dispatch_final_verdict = disp_wrap


def send(text):
    if not TOKEN or not CHAT:
        print("[NO-TOKEN]\n" + text)
        return
    url = f"https://botapi.rubika.ir/v3/{TOKEN}/sendMessage"
    body = json.dumps({"chat_id": CHAT, "text": text}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    try:
        print("[SEND]", urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")[:200])
    except Exception as e:
        print("[SEND-ERR]", e)


if os.environ.get("SEND_TEST") == "true":
    send("✅ پیام آزمایشی ربات طلا؛ اتصال به کانال برقرار است.")
    sys.exit(0)


def load_stats():
    try:
        return json.load(open(STATS, encoding="utf-8"))
    except Exception:
        return {"sent": [], "counted": [], "res": {"NORMAL": [], "SCALP": []}}


def enabled(s, t):
    r = s["res"][t][-WINDOW:]
    return len(r) < MIN_N or sum(r) > 0


def fmt_signal(sg, side, now):
    arrow = "🟢 خرید" if side == "BUY" else "🔴 فروش"
    t = mod.tehran_local(now).strftime("%H:%M")
    return (f"📊 سیگنال طلا (XAUUSD)\n{arrow}\n\n"
            f"ورود (Limit): {sg['entry']:.2f}\n"
            f"حد ضرر: {sg['sl']:.2f}\n"
            f"هدف ۱: {sg['tp1']:.2f}\n"
            f"هدف ۲: {sg['tp2']:.2f}\n\n"
            f"⏰ ساعت تهران {t} | اعتبار {mod.SIGNAL_TTL_MINUTES} دقیقه\n"
            f"📡 منبع قیمت: {getattr(mod, 'SOURCE_NAME', '')}\n"
            f"⚠️ فقط راهنما؛ مسئولیت معامله با خودتان است.")


try:
    mod.run_once()
except Exception as e:
    print("[RUN-ERR]", e)

s = load_stats()

# نتیجه سیگنال‌های قبلی
for r in cap["reports"]:
    sg = r["sig"]
    st = sg["status"]
    k = f"{sg['type']}-{sg['id']}"
    if st not in CLOSED or k in s["counted"]:
        continue
    s["counted"].append(k)
    if st in ("TP1_HIT", "STOPPED"):
        risk = abs(sg["entry"] - sg["sl"])
        R = abs(sg["tp1"] - sg["entry"]) / risk if st == "TP1_HIT" and risk > 0 else -1.0
        s["res"][sg["type"]].append(round(R, 2))
    if k in s["sent"]:
        side = "خرید" if sg["side"] == "BUY" else "فروش"
        send(f"📌 نتیجه سیگنال {side} طلا (ورود {sg['entry']:.2f})\n{mod.signal_status_fa(st)}")

# سیگنال جدید
v, ctx = cap["verdict"], cap["ctx"]
if v in ("CONFIRMED_SCALP", "CONFIRMED_NORMAL"):
    typ = "SCALP" if v.endswith("SCALP") else "NORMAL"
    sg = ctx["confirmed_scalp"] if typ == "SCALP" else ctx["confirmed_normal"]["signal"]
    side = sg.get("side", sg.get("direction"))
    if enabled(s, typ):
        iso = ctx["now_utc"].isoformat()
        for a in mod.load_state().get("active_signals", []):
            if a["created_at"] == iso and a["type"] == typ:
                s["sent"].append(f"{typ}-{a['id']}")
        send(fmt_signal(sg, side, ctx["now_utc"]))
    else:
        print(f"[DISABLED] استراتژی {typ} فعلاً ضررده است؛ فقط پایش می‌شود")

s["sent"], s["counted"] = s["sent"][-200:], s["counted"][-400:]
json.dump(s, open(STATS, "w", encoding="utf-8"))
print("[STATS]", {t: (len(x), round(sum(x[-WINDOW:]), 2)) for t, x in s["res"].items()})
