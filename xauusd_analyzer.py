"""XAUUSD ANALYZER v5.5 - نسخه GitHub Actions (داده: Yahoo، پشتیبان: Binance PAXG)"""
import os, sys, json, time, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

# ============================ SETTINGS ======================================
SYMBOL = os.environ.get("YF_SYMBOL", "XAUUSD=X")
BN_SYMBOL = os.environ.get("BN_SYMBOL", "PAXGUSDT")
TEHRAN_OFFSET_HOURS = 3.5
BROKER_OPEN_SUNDAY_HOUR_UTC = 22
BROKER_CLOSE_FRIDAY_HOUR_UTC = 21
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
FRESHNESS_GRACE_SEC = {"M1": 120, "M5": 180, "M15": 300, "H1": 600, "H4": 900, "D1": 3600}
HARD_STALE_MULT = {k: 3 for k in TF_SECONDS}
DATA_STALL_WARN_SEC = {k: 900 for k in TF_SECONDS}
DATA_STALL_CRITICAL_SEC = {k: 1800 for k in TF_SECONDS}
TIMEFRAMES = {"D1": "1d", "H4": "4h", "H1": "1h", "M15": "15m", "M5": "5m", "M1": "1m"}
REQUIRED_TFS = ("H1", "M15", "M5")
LIMIT = 300
MIN_BARS_REQUIRED = 60
FETCH_RETRIES = 2
FETCH_RETRY_SLEEP = 2
FETCH_TIMEOUT_SEC = 15
LIVE_TICK_INVALID_RANGE = (500.0, 20000.0)
LIVE_TICK_STALE_SEC = 240

SWING_LOOKBACK = 3
TREND_MIN_MOVE_PCT = 0.0003
ATR_PERIOD = 14
BOS_MIN_BODY_ATR = 0.3
MSS_DISPLACEMENT_ATR = 0.8
M5_MSS_WINDOW = 12
M1_MSS_WINDOW = 10
M15_STRUCT_WINDOW = 10
REACTION_MIN_BODY_ATR = 0.3
SWEEP_WINDOW_MAX = 30
SWEEP_LOOKBACK_MIN = 5
SWEEP_WINDOW_FRESH = 6
SWEEP_WINDOW_MID = 15
FVG_MIN_GAP_PCT = 0.00015
PD_MIN_SWING_GAP = 5
PD_RANGE_MIN_ATR = 3.0
PD_RANGE_MAX_ATR = 40.0
PD_FALLBACK_BARS = 60
PD_EXTREME_THRESHOLD = 0.05
OB_LOOKBACK = 8
OB_MIN_HEIGHT_ATR = 0.3
OB_TOUCHED_PEN = 0.1
OB_MITIGATED_PEN = 0.6
OB_APPROACH_ATR = 1.5
TF_BASE_WEIGHT = {"D1": 3.0, "H4": 2.5, "H1": 2.0, "M15": 1.0, "M5": 0.5, "M1": 0.0}
MTF_OB_BONUS_MAX_DIST_ATR = 1.5
REACTION_MAX_ZONE_DISTANCE_ATR = 1.5
REACTION_MIN_PENETRATION_ATR = 0.05
REACTION_FRESH_TOUCH = 12
REACTION_CONFIRM_MAX_AFTER = 4
REACTION_FORMING_TOUCH = 2

MIN_SCORE = 75
SCALP_MIN_SCORE = 75
SPREAD_BLOCK_RATIO = 0.5
SPREAD_WARN_RATIO = 0.3
SCALP_SPREAD_ESTIMATE = 0.35
MIN_SL_ATR = 0.8
NORMAL_MAX_SL_ATR = 3.0
SCALP_MAX_SL_ATR = 2.5
RR_TP1 = 2.0
RR_TP2 = 3.0
NORMAL_RR_MIN = 1.9
SCALP_RR_MIN = 1.9
MAX_ENTRY_DISTANCE_ATR = 1.0
SCALP_ZONE_CONFIRM_ATR = 1.0
SCALP_ATR_MIN_M5 = 0.8
SCALP_ATR_MAX_M5 = 20.0

PRUNE_RESOLVED_AFTER_HOURS = 24
SIGNAL_TTL_MINUTES = 30
TP_HIT_BEFORE_ENTRY_CANCEL = True
STRUCTURE_CANCEL_BODY_ATR = 0.5
DISTANCE_CANCEL_ATR = 3.0
SIGNAL_DEDUP_WINDOW_MIN = 60
SCALP_DEDUP_WINDOW_MIN = 30

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, "xauusd_v55_state.json")
SOURCE_NAME = ""


def log(msg=""):
    print(msg); sys.stdout.flush()


# ============================ TIME / SESSIONS ===============================
def _nth_sunday_utc(y, m, n):
    f = datetime(y, m, 1, tzinfo=timezone.utc)
    off = (6 - f.weekday()) % 7
    return f + timedelta(days=off) + timedelta(weeks=n - 1)


def _last_sunday_utc(y, m):
    nxt = datetime(y + 1, 1, 1, tzinfo=timezone.utc) if m == 12 else datetime(y, m + 1, 1, tzinfo=timezone.utc)
    last = nxt - timedelta(days=1)
    off = (last.weekday() - 6) % 7
    return last - timedelta(days=off)


def is_uk_dst(n):
    y = n.year
    return _last_sunday_utc(y, 3).replace(hour=1) <= n < _last_sunday_utc(y, 10).replace(hour=1)


def is_us_dst(n):
    y = n.year
    return _nth_sunday_utc(y, 3, 2).replace(hour=7) <= n < _nth_sunday_utc(y, 11, 1).replace(hour=6)


def london_local(n): return n + timedelta(hours=(1 if is_uk_dst(n) else 0))
def ny_local(n): return n + timedelta(hours=(-4 if is_us_dst(n) else -5))
def tehran_local(n): return n + timedelta(hours=TEHRAN_OFFSET_HOURS)


def market_status(now_utc=None):
    if now_utc is None: now_utc = datetime.now(timezone.utc)
    wd, hour = now_utc.weekday(), now_utc.hour
    if wd == 5:
        return "CLOSED", "شنبه (تعطیلی آخر هفته)", None
    if wd == 6 and hour < BROKER_OPEN_SUNDAY_HOUR_UTC:
        return "CLOSED", "یکشنبه (قبل از باز شدن)", None
    if wd == 4 and hour >= BROKER_CLOSE_FRIDAY_HOUR_UTC:
        return "CLOSED", "جمعه (بعد از بسته شدن)", None
    return "OPEN", "", None


def current_session(now_utc=None):
    if now_utc is None: now_utc = datetime.now(timezone.utc)
    st, _, _ = market_status(now_utc)
    if st == "CLOSED": return "MARKET-CLOSED"
    lo = london_local(now_utc); ny = ny_local(now_utc)
    lo_on = lo.weekday() < 5 and 8 <= lo.hour < 17
    ny_on = ny.weekday() < 5 and 8 <= ny.hour < 17
    if lo_on and ny_on: return "LONDON+NY"
    if lo_on: return "LONDON"
    if ny_on: return "NY"
    return "OFF-SESSION"


def soft_stale_threshold_sec(tf): return TF_SECONDS[tf] + FRESHNESS_GRACE_SEC[tf]
def hard_stale_threshold_sec(tf): return soft_stale_threshold_sec(tf) * HARD_STALE_MULT[tf]


# ============================ PARSING =======================================
def parse_iso(ts):
    if not isinstance(ts, str): return None
    s = ts.strip()
    if not s: return None
    if s.endswith("Z"): s = s[:-1] + "+00:00"
    try: dt = datetime.fromisoformat(s)
    except Exception: return None
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fnum(v):
    try: x = float(v)
    except (TypeError, ValueError): return None
    if x != x or x in (float("inf"), float("-inf")): return None
    return x


def _coerce_bool(v):
    if isinstance(v, bool): return v
    if isinstance(v, (int, float)): return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes"): return True
        if s in ("false", "0", "no"): return False
    return None


# ============================ FETCH (Yahoo / Binance) =======================
class FetchError(Exception): pass


_SRC = {"name": None}
_CACHE = {}
_IV_SEC = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
_YF_RANGE = {"1m": "1d", "5m": "5d", "15m": "10d", "1h": "1mo", "4h": "3mo", "1d": "6mo"}


def _http_json(url):
    last = None
    for a in range(1, FETCH_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        if a < FETCH_RETRIES: time.sleep(FETCH_RETRY_SLEEP * a)
    raise FetchError(last)


def _agg4h(bars):
    out = {}
    for b in bars:
        k = b["t"] // 14400
        if k not in out:
            out[k] = {"t": k * 14400, "open": b["open"], "high": b["high"], "low": b["low"],
                      "close": b["close"], "volume": b["volume"]}
        else:
            o = out[k]
            o["high"] = max(o["high"], b["high"]); o["low"] = min(o["low"], b["low"]); o["close"] = b["close"]
            if o["volume"] is not None and b["volume"] is not None: o["volume"] += b["volume"]
            else: o["volume"] = None
    return [out[k] for k in sorted(out)]


def _yahoo(interval, limit):
    iv = "1h" if interval == "4h" else interval
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(SYMBOL)
           + f"?interval={iv}&range={_YF_RANGE[interval]}")
    d = _http_json(url)
    res = (d.get("chart") or {}).get("result")
    if not res: raise FetchError("yahoo: result خالی")
    r = res[0]; ts = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    vols = q.get("volume") or [None] * len(ts)
    bars = []
    for i, t in enumerate(ts):
        try: o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        except Exception: continue
        if None in (o, h, l, c): continue
        v = vols[i] if i < len(vols) else None
        bars.append({"t": int(t), "open": o, "high": max(h, o, c), "low": min(l, o, c), "close": c,
                     "volume": v if v else None})
    if interval == "4h": bars = _agg4h(bars)
    now = time.time(); sec = _IV_SEC[interval]
    return [{"openTime": datetime.fromtimestamp(b["t"], timezone.utc).isoformat(), "open": b["open"],
             "high": b["high"], "low": b["low"], "close": b["close"], "volume": b["volume"],
             "isOpen": b["t"] + sec > now} for b in bars[-limit:]]


def _binance(interval, limit):
    d = _http_json(f"https://data-api.binance.vision/api/v3/klines?symbol={BN_SYMBOL}&interval={interval}&limit={limit}")
    if not isinstance(d, list) or not d: raise FetchError("binance: خالی")
    now = time.time(); sec = _IV_SEC[interval]
    return [{"openTime": datetime.fromtimestamp(k[0] / 1000, timezone.utc).isoformat(), "open": k[1], "high": k[2],
             "low": k[3], "close": k[4], "volume": k[5], "isOpen": k[0] / 1000 + sec > now} for k in d]


def fetch_ohlc(symbol, interval, limit=LIMIT):
    key = (interval, limit)
    if key in _CACHE: return _CACHE[key]
    global SOURCE_NAME
    order = [_SRC["name"]] if _SRC["name"] else ["yahoo", "binance"]
    last = None
    for p in order:
        try:
            bars = (_yahoo if p == "yahoo" else _binance)(interval, limit)
            if not bars: raise FetchError("خالی")
            _SRC["name"] = p
            SOURCE_NAME = "Yahoo XAUUSD" if p == "yahoo" else f"Binance {BN_SYMBOL} (ممکن است چند دلار با XAUUSD فرق کند)"
            _CACHE[key] = bars
            return bars
        except Exception as e:
            last = f"{p}: {e}"
    raise FetchError(last)


def fetch_live_tick(symbol=SYMBOL):
    ra = datetime.now(timezone.utc)
    try:
        raw = fetch_ohlc(symbol, "1m", LIMIT)
        b = [x for x in raw if _fnum(x["close"]) is not None][-1]
        price = _fnum(b["close"]); lo, hi = LIVE_TICK_INVALID_RANGE
        if price is None or not (lo < price < hi):
            return {"status": "INVALID", "reason": f"قیمت {price} خارج بازه", "received_at": ra}
        return {"status": "OK", "price": price, "bid": None, "ask": None, "spread": None,
                "source_ts": parse_iso(b["openTime"]), "received_at": ra, "market_state": None}
    except Exception as e:
        return {"status": "ERROR", "reason": f"{type(e).__name__}: {e}", "received_at": ra}


def assess_tick_freshness(tick, now_utc):
    if tick["status"] != "OK": return False, True, None, tick.get("reason", "tick در دسترس نیست")
    ra = tick["received_at"]; st = tick.get("source_ts")
    if st is not None:
        lag = (ra - st).total_seconds()
        if lag > LIVE_TICK_STALE_SEC: return True, False, lag, f"سن tick {int(lag)}s"
        return False, False, lag, ""
    return False, False, None, "timestamp منبع نیست"


# ============================ BAR VALIDATION ================================
def _empty_meta(tf, now_utc):
    return {"last_closed_bar_time": None, "last_fetch_time": now_utc, "bar_close_age_sec": None,
            "fetch_lag_sec": None, "data_stall_sec": 0.0, "soft_stale_sec": soft_stale_threshold_sec(tf),
            "hard_stale_sec": hard_stale_threshold_sec(tf), "data_stall_warn": False, "data_stall_critical": False}


def normalize_and_validate_bars(raw_bars, tf_name, now_utc=None):
    if now_utc is None: now_utc = datetime.now(timezone.utc)
    issues = []; tf_sec = TF_SECONDS.get(tf_name, 3600); last_fetch = now_utc
    if not isinstance(raw_bars, list): return [], ["raw_bars لیست نیست"], _empty_meta(tf_name, now_utc), "hard"
    parsed = []; rej = {"nd": 0, "missing": 0, "bad_num": 0, "bad_ohlc": 0, "bad_time": 0, "bad_isopen": 0}
    req = ("openTime", "open", "high", "low", "close")
    for rb in raw_bars:
        if not isinstance(rb, dict): rej["nd"] += 1; continue
        if any(k not in rb for k in req): rej["missing"] += 1; continue
        dt = parse_iso(rb["openTime"])
        if dt is None: rej["bad_time"] += 1; continue
        o, h, l, c = _fnum(rb["open"]), _fnum(rb["high"]), _fnum(rb["low"]), _fnum(rb["close"])
        if None in (o, h, l, c): rej["bad_num"] += 1; continue
        if not (h >= max(o, c) and l <= min(o, c) and h > 0 and l > 0): rej["bad_ohlc"] += 1; continue
        is_open = rb.get("isOpen", None)
        flag = _coerce_bool(is_open) if is_open is not None else None
        if flag is not None: closed = not flag
        elif is_open is None: closed = (dt + timedelta(seconds=tf_sec)) <= now_utc
        else: rej["bad_isopen"] += 1; continue
        parsed.append({"openTime": dt, "closeTime": dt + timedelta(seconds=tf_sec), "open": o, "high": h, "low": l,
                       "close": c, "volume": _fnum(rb.get("volume")) if "volume" in rb else None, "closed": closed})
    if any(rej.values()): issues.append(f"ردشده: {rej}")
    parsed.sort(key=lambda b: b["openTime"])
    deduped = []; seen = set()
    for b in parsed:
        k = b["openTime"].isoformat()
        if k in seen: continue
        seen.add(k); deduped.append(b)
    aligned = [b for b in deduped if b["openTime"].second == 0] or deduped
    closed_bars = [b for b in aligned if b["closed"]]
    if len(closed_bars) < MIN_BARS_REQUIRED:
        return [], issues + [f"کندل بسته کافی نیست ({len(closed_bars)}<{MIN_BARS_REQUIRED})"], _empty_meta(tf_name, now_utc), "hard"
    last = closed_bars[-1]; last_ct = last["closeTime"]
    bca = (now_utc - last_ct).total_seconds(); fl = (last_fetch - last_ct).total_seconds(); ds = (now_utc - last_fetch).total_seconds()
    soft = soft_stale_threshold_sec(tf_name); hard = hard_stale_threshold_sec(tf_name)
    stall_w = ds > DATA_STALL_WARN_SEC[tf_name]; stall_c = ds > DATA_STALL_CRITICAL_SEC[tf_name]
    meta = {"last_closed_bar_time": last_ct, "last_fetch_time": last_fetch, "bar_close_age_sec": bca,
            "fetch_lag_sec": fl, "data_stall_sec": ds, "soft_stale_sec": soft, "hard_stale_sec": hard,
            "data_stall_warn": stall_w, "data_stall_critical": stall_c}
    st, _, _ = market_status(now_utc)
    if st == "CLOSED": return closed_bars, issues, meta, "market-closed"
    if stall_c: issues.append("DATA-STALL-CRITICAL"); return closed_bars, issues, meta, "hard"
    if bca > hard: issues.append(f"بسیار کهنه: {int(bca)}s > {int(hard)}s"); return closed_bars, issues, meta, "hard"
    if bca > soft: issues.append(f"کمی کهنه: {int(bca)}s > {int(soft)}s"); return closed_bars, issues, meta, "soft"
    return closed_bars, issues, meta, "ok"


# ============================ INDICATORS ====================================
def find_swings(bars, lookback=SWING_LOOKBACK):
    highs = []; lows = []; n = len(bars)
    if n < lookback * 2 + 1: return highs, lows
    for i in range(lookback, n - lookback):
        h, l = bars[i]["high"], bars[i]["low"]; ih = True; il = True
        for j in range(i - lookback, i + lookback + 1):
            if j == i: continue
            if bars[j]["high"] >= h: ih = False
            if bars[j]["low"] <= l: il = False
            if not ih and not il: break
        if ih: highs.append((i, h))
        if il: lows.append((i, l))
    return highs, lows


def confirmed_swings(swings, n, lookback=SWING_LOOKBACK):
    return [(i, p) for i, p in swings if i <= n - 1 - lookback]


def determine_trend(sh, sl):
    if len(sh) < 2 or len(sl) < 2: return "SIDEWAYS", 0.0
    h1, h2 = sh[-2][1], sh[-1][1]; l1, l2 = sl[-2][1], sl[-1][1]
    hm = abs(h2 - h1) / h1 if h1 > 0 else 0; lm = abs(l2 - l1) / l1 if l1 > 0 else 0
    if hm < TREND_MIN_MOVE_PCT and lm < TREND_MIN_MOVE_PCT: return "SIDEWAYS", 0.0
    if h2 > h1 and l2 > l1: return "UP", (hm + lm) / 2
    if h2 < h1 and l2 < l1: return "DOWN", (hm + lm) / 2
    return "SIDEWAYS", 0.0


def calculate_atr(bars, period=ATR_PERIOD):
    if len(bars) < period + 1: return 0.0
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period if trs else 0.0


def detect_bos_choch(bars, sh, sl, atr):
    events = []; n = len(bars); sh_c = confirmed_swings(sh, n); sl_c = confirmed_swings(sl, n)
    if len(sh_c) < 2 or len(sl_c) < 2 or atr <= 0: return {"events": [], "final_trend": "SIDEWAYS"}
    confirms = []
    for idx, p in sh_c: confirms.append((idx + SWING_LOOKBACK, "HIGH", p, idx))
    for idx, p in sl_c: confirms.append((idx + SWING_LOOKBACK, "LOW", p, idx))
    confirms.sort(key=lambda x: x[0])
    cur = "SIDEWAYS"
    if sh_c[-1][1] > sh_c[0][1] and sl_c[-1][1] > sl_c[0][1]: cur = "UP"
    elif sh_c[-1][1] < sh_c[0][1] and sl_c[-1][1] < sl_c[0][1]: cur = "DOWN"
    broken = set(); lh = ll = None; lhs = lls = None; cp = 0
    for i in range(n):
        while cp < len(confirms) and confirms[cp][0] <= i:
            it = confirms[cp]
            if it[1] == "HIGH": lh, lhs = it[2], it[3]
            else: ll, lls = it[2], it[3]
            cp += 1
        close = bars[i]["close"]; body = abs(close - bars[i]["open"])
        if body < atr * BOS_MIN_BODY_ATR: continue
        if lh is not None and close > lh:
            k = ("H", lhs)
            if k not in broken:
                et = "BOS" if cur == "UP" else "CHoCH"
                events.append((i, et, lh, "bullish", body >= atr * MSS_DISPLACEMENT_ATR)); broken.add(k); cur = "UP"
        elif ll is not None and close < ll:
            k = ("L", lls)
            if k not in broken:
                et = "BOS" if cur == "DOWN" else "CHoCH"
                events.append((i, et, ll, "bearish", body >= atr * MSS_DISPLACEMENT_ATR)); broken.add(k); cur = "DOWN"
    return {"events": events, "final_trend": cur}


def detect_mss(events, bars, window=M5_MSS_WINDOW):
    n = len(bars)
    for item in reversed(events):
        age = n - 1 - item[0]
        if 0 <= age <= window and item[1] == "CHoCH" and item[4]:
            return {"index": item[0], "price": item[2], "direction": item[3]}
    return None


def detect_m1_confirmation(m1_opt, target_dir, window=M1_MSS_WINDOW):
    if m1_opt is None: return False, "M1 نیست"
    bars = m1_opt["bars"]; atr = m1_opt["atr"]
    if atr <= 0 or len(bars) < 5: return False, "ATR_M1 یا کندل کم"
    found = False; mss = m1_opt.get("mss")
    if mss and mss["direction"] == target_dir: found = True
    if not found:
        n = len(bars)
        for e in reversed(m1_opt["events"]):
            age = n - 1 - e[0]
            if age < 0 or age > window: continue
            if e[3] == target_dir and e[1] in ("MSS", "CHoCH") and e[4]: found = True; break
    if not found: return False, f"M1 {target_dir} MSS نیست"
    last = bars[-1]; body = abs(last["close"] - last["open"])
    if body < REACTION_MIN_BODY_ATR * atr: return False, "بدنه M1 کم"
    if target_dir == "bullish" and last["close"] <= last["open"]: return False, "M1 صعودی نیست"
    if target_dir == "bearish" and last["close"] >= last["open"]: return False, "M1 نزولی نیست"
    return True, "تأیید M1"


def detect_liquidity_sweep_v2(bars, sh, sl, atr):
    sweeps = []; n = len(bars)
    if n < SWEEP_WINDOW_MAX + 5 or atr <= 0: return sweeps
    cp = bars[-1]["close"]; max_d = atr * 2.0
    for i in range(n - SWEEP_WINDOW_MAX, n):
        b = bars[i]; low, high, close, op = b["low"], b["high"], b["close"], b["open"]
        bl = None
        for si, sp in sl:
            if i - (si + SWING_LOOKBACK) < SWEEP_LOOKBACK_MIN: continue
            if low < sp and close > sp and close > op:
                if bl is None or sp < bl[1]: bl = (si, sp)
        if bl and abs(cp - bl[1]) <= max_d:
            sweeps.append({"index": i, "direction": "bullish", "swept_price": bl[1], "level_type": "low", "age": n - 1 - i})
        bh = None
        for si, sp in sh:
            if i - (si + SWING_LOOKBACK) < SWEEP_LOOKBACK_MIN: continue
            if high > sp and close < sp and close < op:
                if bh is None or sp > bh[1]: bh = (si, sp)
        if bh and abs(cp - bh[1]) <= max_d:
            sweeps.append({"index": i, "direction": "bearish", "swept_price": bh[1], "level_type": "high", "age": n - 1 - i})
    return sweeps


def sweep_score(sweeps, target_dir):
    m = [s for s in sweeps if s["direction"] == target_dir]
    if not m: return 0, None
    fr = [s for s in m if s["age"] <= SWEEP_WINDOW_FRESH]
    if fr: return 18, sorted(fr, key=lambda x: x["age"])[0]
    mid = [s for s in m if s["age"] <= SWEEP_WINDOW_MID]
    if mid: return 10, sorted(mid, key=lambda x: x["age"])[0]
    mx = [s for s in m if s["age"] <= SWEEP_WINDOW_MAX]
    if mx: return 4, sorted(mx, key=lambda x: x["age"])[0]
    return 0, None


def detect_fvg(bars, min_gap_pct=FVG_MIN_GAP_PCT):
    fvgs = []; n = len(bars)
    for i in range(2, n):
        h2, l2 = bars[i - 2]["high"], bars[i - 2]["low"]; h0, l0 = bars[i]["high"], bars[i]["low"]
        ref = (h2 + l2) / 2
        if ref <= 0: continue
        if (l0 - h2) > 0 and (l0 - h2) / ref >= min_gap_pct:
            fvgs.append({"index": i, "type": "bullish", "bottom": h2, "top": l0, "touched": False, "invalid": False})
        if (l2 - h0) > 0 and (l2 - h0) / ref >= min_gap_pct:
            fvgs.append({"index": i, "type": "bearish", "bottom": h0, "top": l2, "touched": False, "invalid": False})
    for fvg in fvgs:
        for j in range(fvg["index"] + 1, n):
            close, low, high = bars[j]["close"], bars[j]["low"], bars[j]["high"]
            if fvg["type"] == "bullish":
                if close < fvg["bottom"]: fvg["invalid"] = True; break
                if high >= fvg["bottom"]: fvg["touched"] = True
            else:
                if close > fvg["top"]: fvg["invalid"] = True; break
                if low <= fvg["top"]: fvg["touched"] = True
    return fvgs


def premium_discount_v2(bars, sh, sl, atr):
    n = len(bars); lc = bars[-1]["close"]; sh_c = confirmed_swings(sh, n); sl_c = confirmed_swings(sl, n)
    ch = cl = None; source = "unknown"
    if len(sh_c) >= 1 and len(sl_c) >= 1:
        cands = []
        for hi_i, hi in sh_c[-3:]:
            for lo_i, lo in sl_c[-3:]:
                if abs(hi_i - lo_i) >= PD_MIN_SWING_GAP and hi > lo:
                    rng = hi - lo
                    if atr <= 0 or (PD_RANGE_MIN_ATR * atr <= rng <= PD_RANGE_MAX_ATR * atr):
                        cands.append((max(hi_i, lo_i), hi, lo))
        if cands:
            cands.sort(key=lambda x: x[0], reverse=True)
            _, ch, cl = cands[0]; source = "swing-based"
    if ch is None or cl is None:
        lb = min(PD_FALLBACK_BARS, n)
        ch = max(b["high"] for b in bars[-lb:]); cl = min(b["low"] for b in bars[-lb:])
        source = f"fallback-{lb}bar"
    rng = ch - cl
    if rng <= 0: return {"zone": "UNKNOWN", "position": 0.5, "high": ch, "low": cl, "label": "UNKNOWN", "range_source": source}
    pos = max(0.0, min(1.0, (lc - cl) / rng))
    if pos <= PD_EXTREME_THRESHOLD or pos >= (1.0 - PD_EXTREME_THRESHOLD):
        lb = min(PD_FALLBACK_BARS, n)
        fh = max(b["high"] for b in bars[-lb:]); fl = min(b["low"] for b in bars[-lb:])
        if (fh - fl) > rng:
            ch, cl, rng = fh, fl, fh - fl; source = f"fallback-{lb}bar-extreme"
            pos = max(0.0, min(1.0, (lc - cl) / rng))
    if pos >= 0.70: zone, label = "PREMIUM", "STRONG PREMIUM"
    elif pos >= 0.55: zone, label = "PREMIUM", "WEAK PREMIUM"
    elif pos > 0.45: zone, label = "EQUILIBRIUM", "EQUILIBRIUM"
    elif pos > 0.30: zone, label = "DISCOUNT", "WEAK DISCOUNT"
    else: zone, label = "DISCOUNT", "STRONG DISCOUNT"
    return {"zone": zone, "position": pos, "high": ch, "low": cl, "label": label, "range_source": source}


def analyze_volume(bars, period=20):
    bad = {"avg": 0.0, "current": 0.0, "ratio": 1.0, "spike": False, "valid": False}
    if len(bars) < period + 2: return bad
    window = bars[-(period + 2):-1]; vols = []
    for b in window:
        v = b.get("volume")
        if v is None or v <= 0: return bad
        vols.append(v)
    avg = sum(vols) / len(vols); cur = bars[-1].get("volume")
    if avg <= 0 or cur is None or cur <= 0: return bad
    ratio = cur / avg
    return {"avg": avg, "current": cur, "ratio": ratio, "spike": ratio >= 1.8, "valid": True}


# ============================ ORDER BLOCKS ==================================
def find_order_blocks_tf(tf_name, bars, events, atr):
    obs = []; n = len(bars)
    if atr <= 0: return obs
    for event in events:
        ei, direction = event[0], event[3]
        if not (0 <= ei < n): continue
        start = ei - 1; end = max(ei - OB_LOOKBACK, 0)
        for j in range(start, end - 1, -1):
            if j < 0 or j >= n: continue
            b = bars[j]; o, c, h, l = b["open"], b["close"], b["high"], b["low"]
            if (h - l) < atr * OB_MIN_HEIGHT_ATR: continue
            if direction == "bullish" and c < o:
                obs.append({"tf": tf_name, "index": j, "event_index": ei, "top": h, "bottom": l, "type": "bullish", "formed_at": b["openTime"]}); break
            if direction == "bearish" and c > o:
                obs.append({"tf": tf_name, "index": j, "event_index": ei, "top": h, "bottom": l, "type": "bearish", "formed_at": b["openTime"]}); break
    return obs


def _ob_dist(ob, cp):
    if cp < ob["bottom"]: return ob["bottom"] - cp
    if cp > ob["top"]: return cp - ob["top"]
    return 0.0


def ob_dir_label(ob, cp):
    if cp < ob["bottom"]: return "above"
    if cp > ob["top"]: return "below"
    return "inside"


def classify_ob_state(ob, tf_bars, atr_tf):
    n = len(tf_bars); ei = ob["event_index"]; top = ob["top"]; bot = ob["bottom"]; h = top - bot
    if h <= 0 or atr_tf <= 0: return {"state": "INVALIDATED", "max_penetration": 1.0, "touched_count": 0, "invalidated": True, "last_state_change_at": None}
    mp = 0.0; tc = 0; inv = False; lc = None
    for i in range(ei + 1, n):
        b = tf_bars[i]; close, high, low = b["close"], b["high"], b["low"]
        if ob["type"] == "bullish":
            if close < bot: inv = True; lc = b["closeTime"]; break
            pen = (top - low) / h
        else:
            if close > top: inv = True; lc = b["closeTime"]; break
            pen = (high - bot) / h
        if pen < 0: pen = 0.0
        if pen > 1.0: pen = 1.0
        if pen > mp: mp = pen; lc = b["closeTime"]
        if pen >= OB_TOUCHED_PEN: tc += 1
    if inv: return {"state": "INVALIDATED", "max_penetration": mp, "touched_count": tc, "invalidated": True, "last_state_change_at": lc}
    cp = tf_bars[-1]["close"]; dist = _ob_dist(ob, cp); da = dist / atr_tf if atr_tf > 0 else None
    if mp >= OB_MITIGATED_PEN: state = "MITIGATED"
    elif mp >= OB_TOUCHED_PEN: state = "TOUCHED"
    elif da is not None and da <= OB_APPROACH_ATR: state = "APPROACHING"
    else: state = "FRESH"
    return {"state": state, "max_penetration": mp, "touched_count": tc, "invalidated": False, "last_state_change_at": lc}


def build_mtf_order_blocks(results, degraded, cp):
    all_obs = []
    for tf, analysis in results.items():
        if tf not in TF_BASE_WEIGHT: continue
        bw = TF_BASE_WEIGHT[tf]
        if bw <= 0: continue
        st = degraded.get(tf, "ok")
        if st in ("hard", "absent"): w = 0.0; deg = True
        elif st == "soft": w = bw * 0.5; deg = True
        else: w = bw; deg = False
        atr = analysis["atr"]; bars = analysis["bars"]
        for ob in analysis["order_blocks"]:
            si = classify_ob_state(ob, bars, atr)
            d = _ob_dist(ob, cp); da = d / atr if atr > 0 else None
            e = dict(ob)
            e.update({"weight": w, "degraded": deg, "tf_status": st, "state": si["state"],
                      "max_penetration": si["max_penetration"], "touched_count": si["touched_count"],
                      "invalidated": si["invalidated"], "last_state_change_at": si["last_state_change_at"],
                      "distance": d, "dist_atr": da, "direction_from_price": ob_dir_label(ob, cp), "atr_tf": atr})
            all_obs.append(e)
    all_obs.sort(key=lambda x: (-x["weight"], -x["event_index"]))
    return all_obs


# ============================ ZONE REACTION =================================
def zone_reaction_tier(bars, zt, zb, ztype, atr, cp):
    n = len(bars)
    if n < 3 or atr <= 0: return "none", "داده کم"
    if zt < zb: zt, zb = zb, zt
    dist = 0.0
    if cp < zb: dist = zb - cp
    elif cp > zt: dist = cp - zt
    if dist > atr * REACTION_MAX_ZONE_DISTANCE_ATR:
        return "historical", f"دور ({dist / atr:.2f}xATR)"
    touch = None; start = max(0, n - 60)
    for i in range(n - 1, start - 1, -1):
        b = bars[i]; high, low = b["high"], b["low"]
        pen = min(high, zt) - max(low, zb)
        if pen < atr * REACTION_MIN_PENETRATION_ATR: continue
        if ztype == "bullish" and low <= zt and high >= zb: touch = i; break
        if ztype == "bearish" and high >= zb and low <= zt: touch = i; break
    if touch is None: return "historical", "بدون لمس ۶۰ کندل"
    age = n - 1 - touch
    if age > REACTION_FRESH_TOUCH: return "historical", f"سن لمس={age}"
    end = min(n, touch + 1 + REACTION_CONFIRM_MAX_AFTER)
    for i in range(touch + 1, end):
        b = bars[i]; o, c = b["open"], b["close"]; body = abs(c - o)
        if body < atr * REACTION_MIN_BODY_ATR: continue
        if ztype == "bullish" and c > o and c > zb: return "fresh", f"سن={age} تأیید@{i}"
        if ztype == "bearish" and c < o and c < zt: return "fresh", f"سن={age} تأیید@{i}"
    if age <= REACTION_FORMING_TOUCH: return "forming", f"سن={age} بدون تأیید"
    return "historical", f"سن={age} بدون تأیید"


def find_active_zone_with_reaction(m5, side, atr):
    tt = "bullish" if side == "BUY" else "bearish"
    cp = m5["bars"][-1]["close"]; prio = {"fresh": 3, "forming": 2, "historical": 1, "none": 0}
    best = ("none", "NONE", 0.0, 0.0, "بدون ناحیه", "N/A")
    for ob in reversed(m5["order_blocks"]):
        if ob["type"] != tt: continue
        si = classify_ob_state({"event_index": ob["event_index"], "top": ob["top"], "bottom": ob["bottom"], "type": ob["type"]}, m5["bars"], atr)
        if si["invalidated"]: continue
        tier, det = zone_reaction_tier(m5["bars"], ob["top"], ob["bottom"], tt, atr, cp)
        if prio[tier] > prio[best[0]]:
            best = (tier, "OB", ob["top"], ob["bottom"], f"OB {tt}", det)
    for fvg in reversed(m5["fvgs"]):
        if fvg["type"] != tt or fvg["invalid"]: continue
        tier, det = zone_reaction_tier(m5["bars"], fvg["top"], fvg["bottom"], tt, atr, cp)
        if prio[tier] > prio[best[0]]:
            best = (tier, "FVG", fvg["top"], fvg["bottom"], f"FVG {tt}", det)
    return best


# ============================ TF ANALYSIS ===================================
def analyze_timeframe(tf_name, bars):
    sh, sl = find_swings(bars); tr, st = determine_trend(sh, sl); atr = calculate_atr(bars)
    structure = detect_bos_choch(bars, sh, sl, atr); events = structure["events"]
    obs_raw = find_order_blocks_tf(tf_name, bars, events, atr)
    fvgs = detect_fvg(bars); vol = analyze_volume(bars)
    pd = premium_discount_v2(bars, sh, sl, atr)
    sweeps = detect_liquidity_sweep_v2(bars, sh, sl, atr)
    mss = detect_mss(events, bars, window=(M1_MSS_WINDOW if tf_name == "M1" else M5_MSS_WINDOW))
    return {"tf": tf_name, "bars": bars, "swing_highs": sh, "swing_lows": sl, "trend": tr, "trend_strength": st,
            "events": events, "final_trend": structure["final_trend"], "mss": mss, "sweeps": sweeps,
            "order_blocks": obs_raw, "fvgs": fvgs, "premium_discount": pd, "volume": vol,
            "volume_valid": vol["valid"], "atr": atr}


def derive_setup_state(m5_tier, m1_ok, m1_detail):
    return "SETUP_CONFIRMED" if m5_tier == "fresh" else "SETUP_NONE"


# ============================ SCORING — NORMAL ==============================
def _mtf_trend_points(tf_analysis, side, weight_tf):
    if tf_analysis is None: return 0
    tr = tf_analysis.get("trend")
    if tr is None or tr == "SIDEWAYS": return 3
    aligned = (side == "BUY" and tr == "UP") or (side == "SELL" and tr == "DOWN")
    if weight_tf == "D1": return 8 if aligned else 0
    return 5 if aligned else 0


def _mtf_ob_bonus(mtf_obs, target_type, side, atr_m5):
    if not mtf_obs or atr_m5 <= 0: return 0, ""
    cands = [o for o in mtf_obs if o["type"] == target_type and o["weight"] >= 2.0 and not o["invalidated"]
             and o["state"] in ("FRESH", "APPROACHING") and o.get("dist_atr") is not None
             and o["dist_atr"] <= MTF_OB_BONUS_MAX_DIST_ATR]
    if not cands: return 0, ""
    cands.sort(key=lambda o: (-o["weight"], o["distance"]))
    best = cands[0]; pts = int(min(10, best["weight"] * 2))
    return pts, f"OB مهم {best['tf']} هم‌جهت +{pts}"


def score_and_veto(h1, m15, m5, h4, d1, mtf_obs, session, side, h1_stale, m5_zone_ok, m5_dir_ok, spread_ratio):
    bd = {}; reasons = []; blockers = []; vetoes = []
    target = "bullish" if side == "BUY" else "bearish"
    h1t = h1["trend"]
    h1_o = 20 if ((side == "BUY" and h1t == "UP") or (side == "SELL" and h1t == "DOWN")) else (8 if h1t == "SIDEWAYS" else 0)
    h1_f = 0 if (h1_o > 0 and h1_stale) else h1_o
    bd["h1_trend"] = h1_f
    if h1_o >= 15: reasons.append(f"H1 {h1t}")
    m15t = m15["trend"]
    m15b = 15 if ((side == "BUY" and m15t == "UP") or (side == "SELL" and m15t == "DOWN")) else (5 if m15t == "SIDEWAYS" else 0)
    bd["m15_trend"] = m15b
    if m15b >= 10: reasons.append(f"M15 {m15t}")
    sw_pts, sw_info = sweep_score(m5["sweeps"], target)
    bd["sweep"] = sw_pts
    if sw_info: reasons.append(f"{sw_info['level_type']} sweep age={sw_info['age']}")
    n15 = len(m15["bars"])
    rev = [e for e in m15["events"] if e[3] == target and 0 <= n15 - 1 - e[0] <= M15_STRUCT_WINDOW]
    m15_pts = 8 if rev else 0
    if rev: reasons.append(f"M15 {target} break")
    mss = m5.get("mss"); mss_pts = 8 if (mss and mss["direction"] == target) else 0
    if mss_pts: reasons.append(f"M5 MSS {target}")
    if m15_pts == 0 and mss_pts == 0:
        bd["m15_struct"] = 0; bd["m5_mss"] = 0
        vetoes.append("VETO-STRUCT: هیچ تأیید ساختاری نیست")
    else:
        bd["m15_struct"] = m15_pts; bd["m5_mss"] = mss_pts
    tier, z_type, z_top, z_bot, z_msg, z_det = find_active_zone_with_reaction(m5, side, m5["atr"])
    if tier == "fresh":
        bd["ob_fvg"] = 18; reasons.append(f"واکنش تازه: {z_msg} ({z_det})")
    elif tier == "forming":
        bd["ob_fvg"] = 6; blockers.append(f"واکنش در حال تشکیل: {z_msg}")
    elif tier == "historical":
        bd["ob_fvg"] = 2; blockers.append(f"واکنش تاریخی: {z_det}")
    else:
        bd["ob_fvg"] = 0; vetoes.append("VETO-ZONE: ناحیه واکنش معتبر نیست")
    if m5["volume_valid"]:
        v = m5["volume"]; bd["vol"] = 5 if v["spike"] else (3 if v["ratio"] >= 1.2 else 1)
        if bd["vol"] == 5: reasons.append(f"حجم {v['ratio']:.2f}x")
    else: bd["vol"] = 0
    if session == "LONDON+NY": bd["sess"] = 5
    elif session in ("LONDON", "NY"): bd["sess"] = 4
    else: bd["sess"] = 0
    if bd["sess"] > 0: reasons.append(f"سشن {session}")
    pdm15 = m15["premium_discount"]; pd_pts = 0
    if side == "BUY":
        if pdm15["zone"] == "DISCOUNT": pd_pts = 10; reasons.append(f"M15 {pdm15['label']}")
        elif pdm15["zone"] == "EQUILIBRIUM": pd_pts = 4
        else: blockers.append(f"M15 {pdm15['label']} (نامناسب BUY)")
    else:
        if pdm15["zone"] == "PREMIUM": pd_pts = 10; reasons.append(f"M15 {pdm15['label']}")
        elif pdm15["zone"] == "EQUILIBRIUM": pd_pts = 4
        else: blockers.append(f"M15 {pdm15['label']} (نامناسب SELL)")
    if not m5_zone_ok: pd_pts = max(0, pd_pts - 3); blockers.append("M5 PD نامناسب")
    bd["pd"] = pd_pts
    if not m5_dir_ok: blockers.append("M5 SIDEWAYS")
    if side == "BUY" and h1["trend"] == "DOWN": blockers.append("⚠ BUY vs H1 DOWN")
    if side == "SELL" and h1["trend"] == "UP": blockers.append("⚠ SELL vs H1 UP")
    d1_pts = _mtf_trend_points(d1, side, "D1"); h4_pts = _mtf_trend_points(h4, side, "H4")
    bd["d1_coherence"] = d1_pts; bd["h4_coherence"] = h4_pts
    h1_opp = (side == "BUY" and h1["trend"] == "DOWN") or (side == "SELL" and h1["trend"] == "UP")
    h4_opp = (side == "BUY" and h4 is not None and h4["trend"] == "DOWN") or (side == "SELL" and h4 is not None and h4["trend"] == "UP")
    if h1_opp and h4_opp:
        vetoes.append(f"VETO-COUNTER: H1 و H4 هر دو مخالف {side}")
    if d1 is not None and d1.get("trend") not in (None, "SIDEWAYS"):
        if (side == "BUY" and d1["trend"] == "DOWN" and d1.get("trend_strength", 0) > 0.006) or \
           (side == "SELL" and d1["trend"] == "UP" and d1.get("trend_strength", 0) > 0.006):
            blockers.append(f"⚠ {side} vs D1 {d1['trend']} قوی")
    if d1_pts > 0: reasons.append(f"D1 هم‌جهت +{d1_pts}")
    if h4_pts > 0: reasons.append(f"H4 هم‌جهت +{h4_pts}")
    ob_bonus, ob_note = _mtf_ob_bonus(mtf_obs, target, side, m5["atr"])
    bd["mtf_ob"] = ob_bonus
    if ob_bonus > 0: reasons.append(ob_note)
    if spread_ratio is not None and m5["atr"] >= 1.0:
        if spread_ratio >= SPREAD_BLOCK_RATIO: vetoes.append(f"VETO-SPREAD: {spread_ratio:.2f}")
        elif spread_ratio >= SPREAD_WARN_RATIO: blockers.append(f"spread بالا {spread_ratio:.2f}")
    last_bar = m5["bars"][-1]
    last_body = last_bar["close"] - last_bar["open"]
    if side == "BUY" and last_body < -m5["atr"] * 0.15:
        vetoes.append("VETO-MOMENTUM: کندل آخر M5 نزولی")
    if side == "SELL" and last_body > m5["atr"] * 0.15:
        vetoes.append("VETO-MOMENTUM: کندل آخر M5 صعودی")
    raw = sum(bd.values()); final = raw if len(vetoes) == 0 else 0
    return (raw, final, bd, reasons, blockers, vetoes, tier, (z_top, z_bot, z_type))


# ============================ NORMAL SIGNAL BUILD ===========================
def build_signal(side, m5, atr, tier, z_top, z_bot, z_type, live_price):
    bars = m5["bars"]
    if atr <= 0 or not bars: return None, "ATR یا کندل نیست"
    if tier != "fresh": return None, f"فقط fresh (tier={tier})"
    lc = bars[-1]["close"]
    ref = live_price if live_price is not None else lc
    if side == "BUY":
        if ref > z_top + atr * 0.5: return None, "قیمت بالاتر از ناحیه - منتظر پولبک"
        if ref < z_bot - atr * 0.5: return None, "قیمت از ناحیه شکسته"
        entry = min(ref, z_top)
        if entry > ref + 0.05 * atr: entry = ref
        recent_lows = [p for i, p in m5["swing_lows"] if len(bars) - 1 - i <= 10]
        sl = (min(recent_lows) - atr * 0.3) if recent_lows else (z_bot - atr * 0.5)
        if entry - sl < atr * MIN_SL_ATR: sl = entry - atr * MIN_SL_ATR
        risk = entry - sl
        if risk <= 0: return None, "ریسک غیرمثبت"
        if risk > atr * NORMAL_MAX_SL_ATR: return None, f"SL بزرگ ({risk / atr:.2f}xATR)"
        tp1 = entry + risk * RR_TP1; tp2 = entry + risk * RR_TP2
    else:
        if ref < z_bot - atr * 0.5: return None, "قیمت پایین‌تر از ناحیه - منتظر پولبک"
        if ref > z_top + atr * 0.5: return None, "قیمت از ناحیه شکسته"
        entry = max(ref, z_bot)
        if entry < ref - 0.05 * atr: entry = ref
        recent_highs = [p for i, p in m5["swing_highs"] if len(bars) - 1 - i <= 10]
        sl = (max(recent_highs) + atr * 0.3) if recent_highs else (z_top + atr * 0.5)
        if sl - entry < atr * MIN_SL_ATR: sl = entry + atr * MIN_SL_ATR
        risk = sl - entry
        if risk <= 0: return None, "ریسک غیرمثبت"
        if risk > atr * NORMAL_MAX_SL_ATR: return None, f"SL بزرگ ({risk / atr:.2f}xATR)"
        tp1 = entry - risk * RR_TP1; tp2 = entry - risk * RR_TP2
    if live_price is not None and abs(entry - live_price) > atr * MAX_ENTRY_DISTANCE_ATR:
        return None, f"ورود بیش از {MAX_ENTRY_DISTANCE_ATR}xATR از قیمت لحظه‌ای"
    if side == "BUY" and not (sl < entry < tp1 < tp2): return None, "هندسه BUY نامعتبر"
    if side == "SELL" and not (sl > entry > tp1 > tp2): return None, "هندسه SELL نامعتبر"
    if (side == "BUY" and (tp1 - entry) / risk < NORMAL_RR_MIN): return None, "RR زیر حداقل"
    if (side == "SELL" and (entry - tp1) / risk < NORMAL_RR_MIN): return None, "RR زیر حداقل"
    return {"type": "NORMAL", "side": side, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2,
            "rr1": abs(tp1 - entry) / risk, "rr2": abs(tp2 - entry) / risk, "atr": atr,
            "sl_dist_atr": abs(entry - sl) / atr, "zone_type": z_type, "zone_top": z_top,
            "zone_bottom": z_bot, "last_closed": lc}, ""


# ============================ SCALP =========================================
def _tf_aligned(tf, direction):
    if tf is None: return False
    tr = tf.get("trend")
    if tr is None or tr == "SIDEWAYS": return False
    return (direction == "BUY" and tr == "UP") or (direction == "SELL" and tr == "DOWN")


def score_scalp(direction, h1, m15, m5, m1_opt, d1, h4, mtf_obs, spread_ratio):
    target = "bullish" if direction == "BUY" else "bearish"; score = 0; details = []
    h1_ok = (direction == "BUY" and h1["trend"] == "UP") or (direction == "SELL" and h1["trend"] == "DOWN")
    m15_ok = (direction == "BUY" and m15["trend"] == "UP") or (direction == "SELL" and m15["trend"] == "DOWN")
    if h1_ok and m15_ok: score += 30; details.append("H1+M15 +30")
    elif m15_ok: score += 15; details.append("M15 +15")
    elif h1_ok: score += 10; details.append("H1 +10")
    d1a = _tf_aligned(d1, direction); h4a = _tf_aligned(h4, direction)
    if d1a and h4a: score += 15; details.append("D1+H4 +15")
    elif d1a: score += 10; details.append("D1 +10")
    elif h4a: score += 8; details.append("H4 +8")
    sw_pts, sw_info = sweep_score(m5["sweeps"], target)
    if sw_info is not None and sw_info["age"] <= SWEEP_WINDOW_FRESH: score += 20; details.append("sweep fresh +20")
    elif sw_info is not None: score += 10; details.append("sweep +10")
    mss = m5.get("mss")
    if mss and mss["direction"] == target: score += 18; details.append("M5 MSS +18")
    recent_events = [e for e in m5["events"] if 0 <= len(m5["bars"]) - 1 - e[0] <= M5_MSS_WINDOW]
    aligned_events = [e for e in recent_events if e[3] == target]
    if aligned_events:
        pts = min(10, 5 * len(aligned_events)); score += pts; details.append(f"breaks +{pts}")
    tier, z_type, z_top, z_bot, z_msg, z_det = find_active_zone_with_reaction(m5, direction, m5["atr"])
    if tier == "fresh": score += 22; details.append("zone fresh +22")
    elif tier == "forming": score += 6; details.append("zone forming +6")
    ob_bonus, ob_note = _mtf_ob_bonus(mtf_obs, target, direction, m5["atr"])
    if ob_bonus > 0: score += ob_bonus; details.append(ob_note)
    if m1_opt is not None:
        m1_mss = m1_opt.get("mss")
        if m1_mss and m1_mss["direction"] == target: score += 8; details.append("M1 MSS +8")
        else:
            m1_a = [e for e in m1_opt["events"] if e[3] == target and 0 <= len(m1_opt["bars"]) - 1 - e[0] <= M1_MSS_WINDOW]
            if m1_a: score += 4; details.append("M1 break +4")
    if spread_ratio is not None and m5["atr"] >= 1.0:
        if spread_ratio >= SPREAD_BLOCK_RATIO: return 0, details + [f"spread-block {spread_ratio:.2f}"], tier, (z_top, z_bot, z_type)
        if spread_ratio >= SPREAD_WARN_RATIO: score = max(0, score - 5); details.append("spread -5")
    return min(100, score), details, tier, (z_top, z_bot, z_type)


def determine_scalp_direction(h1, m15, m5):
    mss = m5.get("mss")
    if mss: return "BUY" if mss["direction"] == "bullish" else "SELL"
    recent = [e for e in m5["events"] if 0 <= len(m5["bars"]) - 1 - e[0] <= M5_MSS_WINDOW]
    if recent: return "BUY" if recent[-1][3] == "bullish" else "SELL"
    fresh_sweeps = [s for s in m5["sweeps"] if s["age"] <= SWEEP_WINDOW_FRESH]
    if fresh_sweeps: return "BUY" if sorted(fresh_sweeps, key=lambda x: x["age"])[0]["direction"] == "bullish" else "SELL"
    return None


def build_scalp_signal(direction, m5, m1_opt, m15, atr, score, tier, z_top, z_bot, z_type, live_price, last_closed):
    if atr <= 0: return None, "ATR نیست"
    if tier != "fresh": return None, f"فقط fresh (tier={tier})"
    cp = live_price if live_price is not None else last_closed
    zone_mid = (z_top + z_bot) / 2.0
    if abs(cp - zone_mid) > atr * SCALP_ZONE_CONFIRM_ATR:
        return None, f"قیمت {abs(cp - zone_mid) / atr:.2f}xATR از ناحیه"
    if direction == "BUY":
        entry = min(cp, z_top)
        if entry > cp + 0.05 * atr: entry = cp
        recent_lows = [p for i, p in m5["swing_lows"] if len(m5["bars"]) - 1 - i <= 8]
        if recent_lows: sl = min(recent_lows) - atr * 0.3
        else:
            m15_lows = [p for i, p in m15["swing_lows"] if len(m15["bars"]) - 1 - i <= 20]
            sl = (min(m15_lows) - atr * 0.5) if m15_lows else (z_bot - atr * 0.5)
        if entry - sl < atr * MIN_SL_ATR: sl = entry - atr * MIN_SL_ATR
        risk = entry - sl
        if risk <= 0: return None, "ریسک غیرمثبت"
        if risk > atr * SCALP_MAX_SL_ATR: return None, "SL بزرگ"
        tp1 = entry + risk * RR_TP1; tp2 = entry + risk * RR_TP2
    else:
        entry = max(cp, z_bot)
        if entry < cp - 0.05 * atr: entry = cp
        recent_highs = [p for i, p in m5["swing_highs"] if len(m5["bars"]) - 1 - i <= 8]
        if recent_highs: sl = max(recent_highs) + atr * 0.3
        else:
            m15_h = [p for i, p in m15["swing_highs"] if len(m15["bars"]) - 1 - i <= 20]
            sl = (max(m15_h) + atr * 0.5) if m15_h else (z_top + atr * 0.5)
        if sl - entry < atr * MIN_SL_ATR: sl = entry + atr * MIN_SL_ATR
        risk = sl - entry
        if risk <= 0: return None, "ریسک غیرمثبت"
        if risk > atr * SCALP_MAX_SL_ATR: return None, "SL بزرگ"
        tp1 = entry - risk * RR_TP1; tp2 = entry - risk * RR_TP2
    if live_price is not None and abs(entry - live_price) > atr * MAX_ENTRY_DISTANCE_ATR:
        return None, "ورود دور از قیمت"
    if direction == "BUY" and not (sl < entry < tp1 < tp2): return None, "هندسه BUY نامعتبر"
    if direction == "SELL" and not (sl > entry > tp1 > tp2): return None, "هندسه SELL نامعتبر"
    if (direction == "BUY" and (tp1 - entry) / risk < SCALP_RR_MIN): return None, "RR کم"
    if (direction == "SELL" and (entry - tp1) / risk < SCALP_RR_MIN): return None, "RR کم"
    return {"type": "SCALP", "direction": direction, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2,
            "score": score, "atr": atr, "sl_dist_atr": risk / atr, "rr1": abs(tp1 - entry) / risk,
            "rr2": abs(tp2 - entry) / risk, "zone": (z_bot, z_top, z_type), "m1_used": m1_opt is not None,
            "last_closed": cp}, ""


# ============================ SIGNAL LIFECYCLE ==============================
def signal_status_fa(s):
    return {"ACTIVE": "🟡 فعال", "FILLED": "🟢 پر شده", "TP1_HIT": "✅ TP1 (سود)", "STOPPED": "❌ SL (ضرر)",
            "EXPIRED": "⏰ منقضی", "CANCELLED_TP_FIRST": "🚫 لغو (TP1 اول)", "CANCELLED_DISTANCE": "🚫 لغو (دور)",
            "CANCELLED_STRUCTURE": "🚫 لغو (ساختار)"}.get(s, s)


def _prune_old_signals(state, now_utc):
    cutoff = now_utc - timedelta(hours=PRUNE_RESOLVED_AFTER_HOURS); pruned = []
    for sig in state.get("active_signals", []):
        if sig["status"] in ("ACTIVE", "FILLED"): pruned.append(sig); continue
        try:
            ca = sig.get("closed_at")
            if ca:
                cd = datetime.fromisoformat(ca)
                if cd.tzinfo is None: cd = cd.replace(tzinfo=timezone.utc)
                if cd < cutoff: continue
            pruned.append(sig)
        except Exception: pruned.append(sig)
    state["active_signals"] = pruned


def evaluate_active_signals(state, m5_bars, now_utc):
    _prune_old_signals(state, now_utc); reports = []
    for sig in state.get("active_signals", []):
        if sig["status"] not in ("ACTIVE", "FILLED"): continue
        try:
            ca = datetime.fromisoformat(sig["created_at"])
            if ca.tzinfo is None: ca = ca.replace(tzinfo=timezone.utc)
            ex = datetime.fromisoformat(sig["expires_at"])
            if ex.tzinfo is None: ex = ex.replace(tzinfo=timezone.utc)
        except Exception: continue
        side = sig["side"]; entry = sig["entry"]; sl = sig["sl"]; tp1 = sig["tp1"]; atr = sig.get("atr", 0)
        zt = sig.get("zone_top", entry); zb = sig.get("zone_bottom", entry)
        bars_since = [b for b in m5_bars if b["openTime"] >= ca]
        if now_utc > ex and sig["status"] == "ACTIVE":
            sig["status"] = "EXPIRED"; sig["closed_at"] = now_utc.isoformat()
            reports.append({"sig": sig, "msg": f"⏰ منقضی ({SIGNAL_TTL_MINUTES} دقیقه)", "remaining_min": 0}); continue
        if not bars_since:
            reports.append({"sig": sig, "msg": "⏳ منتظر کندل", "remaining_min": max(0, (ex - now_utc).total_seconds() / 60)}); continue
        filled = sig["status"] == "FILLED"; fi = None; tpi = None; sli = None; sbi = None
        for i, b in enumerate(bars_since):
            if side == "BUY":
                if not filled and b["low"] <= entry: filled = True; fi = i; sig["status"] = "FILLED"; sig["filled_at"] = b["openTime"].isoformat()
                if b["high"] >= tp1 and tpi is None: tpi = i
                if filled and b["low"] <= sl and sli is None: sli = i
                if not filled and sbi is None and atr > 0 and b["close"] < zb and abs(b["close"] - b["open"]) > atr * STRUCTURE_CANCEL_BODY_ATR: sbi = i
            else:
                if not filled and b["high"] >= entry: filled = True; fi = i; sig["status"] = "FILLED"; sig["filled_at"] = b["openTime"].isoformat()
                if b["low"] <= tp1 and tpi is None: tpi = i
                if filled and b["high"] >= sl and sli is None: sli = i
                if not filled and sbi is None and atr > 0 and b["close"] > zt and abs(b["close"] - b["open"]) > atr * STRUCTURE_CANCEL_BODY_ATR: sbi = i
        if TP_HIT_BEFORE_ENTRY_CANCEL and tpi is not None:
            if fi is None or tpi < fi:
                sig["status"] = "CANCELLED_TP_FIRST"; sig["closed_at"] = bars_since[tpi]["openTime"].isoformat()
                reports.append({"sig": sig, "msg": "🚫 لغو: TP1 قبل از ورود", "remaining_min": 0}); continue
        if sbi is not None and fi is None:
            sig["status"] = "CANCELLED_STRUCTURE"; sig["closed_at"] = bars_since[sbi]["openTime"].isoformat()
            reports.append({"sig": sig, "msg": "🚫 لغو: ساختار شکست", "remaining_min": 0}); continue
        if fi is None and atr > 0:
            lc = bars_since[-1]["close"]; zm = (zt + zb) / 2.0
            if abs(lc - zm) / atr > DISTANCE_CANCEL_ATR:
                sig["status"] = "CANCELLED_DISTANCE"; sig["closed_at"] = bars_since[-1]["openTime"].isoformat()
                reports.append({"sig": sig, "msg": "🚫 لغو: قیمت دور شد", "remaining_min": 0}); continue
        if fi is not None and sli is not None:
            sig["status"] = "STOPPED"; sig["closed_at"] = bars_since[sli]["openTime"].isoformat(); sig["result"] = "LOSS"
            reports.append({"sig": sig, "msg": "❌ SL خورد (ضرر)", "remaining_min": 0}); continue
        if fi is not None and tpi is not None:
            sig["status"] = "TP1_HIT"; sig["closed_at"] = bars_since[tpi]["openTime"].isoformat(); sig["result"] = "WIN"
            reports.append({"sig": sig, "msg": "✅ TP1 پر شد (سود)", "remaining_min": 0}); continue
        rem = max(0, (ex - now_utc).total_seconds() / 60)
        reports.append({"sig": sig, "msg": "🟢 ورود پر شده" if filled else f"⏳ در انتظار ({rem:.0f} دقیقه)", "remaining_min": rem})
    return reports


# ============================ STATE / DEDUP =================================
def signal_key(sig):
    return (sig.get("side", sig.get("direction")), round(sig["entry"], 2), round(sig["sl"], 2),
            round(sig["tp1"], 2), round(sig["tp2"], 2))


def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: pass
    return {"recent_signals": [], "recent_scalp_signals": [], "active_signals": []}


def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f: json.dump(state, f, ensure_ascii=False)
    except Exception: pass


def is_duplicate_signal(sig, state, now_utc):
    key = signal_key(sig); cutoff = now_utc - timedelta(minutes=SIGNAL_DEDUP_WINDOW_MIN); recent = []
    for item in state.get("recent_signals", []):
        try:
            ts = datetime.fromisoformat(item["ts"])
            if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
        except Exception: continue
        if ts >= cutoff: recent.append(item)
    state["recent_signals"] = recent
    for item in recent:
        if tuple(item["key"]) == key: return True, item["ts"]
    return False, None


def _new_active(sig, side, zt, zb, now_utc):
    ex = now_utc + timedelta(minutes=SIGNAL_TTL_MINUTES)
    return {"id": str(int(now_utc.timestamp() * 1000)), "type": sig["type"], "side": side, "entry": sig["entry"],
            "sl": sig["sl"], "tp1": sig["tp1"], "tp2": sig["tp2"], "zone_top": zt, "zone_bottom": zb,
            "atr": sig["atr"], "created_at": now_utc.isoformat(), "expires_at": ex.isoformat(),
            "status": "ACTIVE", "filled_at": None, "closed_at": None, "result": None}


def record_signal_v54(sig, state, now_utc):
    state.setdefault("recent_signals", []).append({"key": list(signal_key(sig)), "ts": now_utc.isoformat()})
    state.setdefault("active_signals", []).append(_new_active(sig, sig["side"], sig["zone_top"], sig["zone_bottom"], now_utc))
    save_state(state)


def load_recent_scalp_signals(state, now_utc):
    cutoff = now_utc - timedelta(minutes=SCALP_DEDUP_WINDOW_MIN); recent = []
    for item in state.get("recent_scalp_signals", []):
        try:
            ts = datetime.fromisoformat(item["time"])
            if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
        except Exception: continue
        if ts >= cutoff: recent.append({"direction": item["direction"], "zone_mid": item.get("zone_mid", 0.0), "time": ts})
    return recent


def record_scalp_signal_v54(sig, state, now_utc):
    state.setdefault("recent_scalp_signals", []).append({"direction": sig["direction"], "zone_mid": sig["zone_mid"], "time": sig["time"].isoformat()})
    zb, zt, _ = sig["zone"]
    state.setdefault("active_signals", []).append(_new_active(sig, sig["direction"], zt, zb, now_utc))
    save_state(state)


def is_duplicate_scalp(sig, recent, now_utc, atr):
    zm = sig["zone_mid"]; d = sig["direction"]
    for s in recent:
        if s["direction"] != d: continue
        if abs(s["zone_mid"] - zm) < atr * 0.5: return True, "همان ناحیه"
        if (now_utc - s["time"]).total_seconds() < SCALP_DEDUP_WINDOW_MIN * 60: return True, "بازه dedup"
    return False, None


def detect_scalp_opportunity(h1, m15, m5, m1_opt, d1, h4, mtf_obs, live_price, last_closed,
                             spread_ratio, recent_scalp, now_utc, d1_status, h4_status):
    atr = m5["atr"]
    if atr < SCALP_ATR_MIN_M5: return None, f"ATR {atr:.2f} کم"
    if atr > SCALP_ATR_MAX_M5: return None, f"ATR {atr:.2f} زیاد"
    direction = determine_scalp_direction(h1, m15, m5)
    if direction is None: return None, "بدون رویداد M5"
    target = "bullish" if direction == "BUY" else "bearish"
    d1_active = (d1_status in ("ok", "soft")) and (d1 is not None)
    h4_active = (h4_status in ("ok", "soft")) and (h4 is not None)
    if not d1_active and not h4_active: return None, "D1 و H4 غایب"
    h1_ok = (direction == "BUY" and h1["trend"] == "UP") or (direction == "SELL" and h1["trend"] == "DOWN")
    m15_ok = (direction == "BUY" and m15["trend"] == "UP") or (direction == "SELL" and m15["trend"] == "DOWN")
    if not (h1_ok or m15_ok): return None, "نه H1 نه M15 هم‌جهت"
    score, details, tier, (zt, zb, ztype) = score_scalp(direction, h1, m15, m5, m1_opt, d1, h4, mtf_obs, spread_ratio)
    if score < SCALP_MIN_SCORE: return None, f"امتیاز {score}<{SCALP_MIN_SCORE}"
    m1_ok, m1_detail = detect_m1_confirmation(m1_opt, target)
    if m1_ok: score = min(100, score + 5)
    if derive_setup_state(tier, m1_ok, m1_detail) == "SETUP_NONE": return None, f"tier={tier} (فقط fresh)"
    sig, err = build_scalp_signal(direction, m5, m1_opt, m15, atr, score, tier, zt, zb, ztype, live_price, last_closed)
    if sig is None: return None, f"build_scalp: {err}"
    sig["zone_mid"] = (zt + zb) / 2.0; sig["time"] = now_utc; sig["details"] = details; sig["reasons"] = details
    dup, reason = is_duplicate_scalp(sig, recent_scalp, now_utc, atr)
    if dup: return None, f"تکراری ({reason})"
    return {"type": "CONFIRMED", "signal": sig, "m1_detail": m1_detail}, ""


# ============================ VERDICT / RUN =================================
def dispatch_final_verdict(ctx):
    if ctx.get("confirmed_scalp") is not None:
        log("  ✅ CONFIRMED SCALP"); return "CONFIRMED_SCALP"
    if ctx.get("confirmed_normal") is not None:
        log("  ✅ CONFIRMED NORMAL"); return "CONFIRMED_NORMAL"
    log(f"  ❌ NO TRADE: {ctx.get('no_trade_reason', 'تأیید نشد')}")
    for v in (ctx.get("no_trade_vetoes") or []): log(f"    X {v}")
    return "NO_TRADE"


def run_once(loop_mode=False):
    _CACHE.clear()
    now_utc = datetime.now(timezone.utc)
    log(f"XAUUSD ANALYZER v5.5 | UTC {now_utc.strftime('%Y-%m-%d %H:%M:%S')} | Tehran {tehran_local(now_utc).strftime('%H:%M')}")
    st, reason, _ = market_status(now_utc)
    if st == "CLOSED":
        log(f"  بازار بسته — {reason}"); return
    session = current_session(now_utc); log(f"  سشن: {session}")
    tick = fetch_live_tick(SYMBOL); live_price = None
    if tick["status"] == "OK":
        live_price = tick["price"]
        stale, _, _, treason = assess_tick_freshness(tick, now_utc)
        log(f"  قیمت زنده: {live_price:.2f} [{SOURCE_NAME}]" + (f" ⚠ {treason}" if stale else ""))
    else:
        log(f"  قیمت زنده در دسترس نیست ({tick.get('reason', '?')})")
    results = {}; severities = {}; degraded = {}
    for tf_name, interval in TIMEFRAMES.items():
        try: raw = fetch_ohlc(SYMBOL, interval, LIMIT)
        except FetchError as e:
            log(f"  FAIL {tf_name}: {e}")
            if tf_name in REQUIRED_TFS: log("  NO TRADE"); return
            degraded[tf_name] = "absent"; continue
        closed, issues, meta, sev = normalize_and_validate_bars(raw, tf_name, now_utc)
        for iss in issues: log(f"  [DATA {tf_name}] {iss}")
        if sev == "hard" or not closed:
            if tf_name in REQUIRED_TFS: log(f"  FAIL {tf_name}: NO TRADE"); return
            degraded[tf_name] = "hard"; continue
        results[tf_name] = analyze_timeframe(tf_name, closed)
        severities[tf_name] = sev
        degraded[tf_name] = "ok" if sev == "ok" else ("soft" if sev == "soft" else sev)
    for tf in REQUIRED_TFS:
        if tf not in results: log(f"  {tf} نیست"); return
    h1 = results["H1"]; m15 = results["M15"]; m5 = results["M5"]; m1_opt = results.get("M1")
    d1 = results.get("D1"); h4 = results.get("H4")
    d1_status = degraded.get("D1", "absent"); h4_status = degraded.get("H4", "absent")
    log(f"  روند: D1={d1['trend'] if d1 else '-'} H4={h4['trend'] if h4 else '-'} H1={h1['trend']} M15={m15['trend']} M5={m5['trend']} | ATR_M5={m5['atr']:.2f}")
    if h1["atr"] <= 0 or m15["atr"] <= 0 or m5["atr"] <= 0:
        log("  ATR نامعتبر"); return
    state = load_state()
    evaluate_active_signals(state, m5["bars"], now_utc)
    pfp = live_price if live_price is not None else m5["bars"][-1]["close"]
    mtf_obs = build_mtf_order_blocks(results, degraded, pfp)
    spread_ratio = (SCALP_SPREAD_ESTIMATE / m5["atr"]) if m5["atr"] > 0 else None
    recent_scalp = load_recent_scalp_signals(state, now_utc)
    scalp_verdict, scalp_reason = detect_scalp_opportunity(h1, m15, m5, m1_opt, d1, h4, mtf_obs, live_price,
                                                           m5["bars"][-1]["close"], spread_ratio, recent_scalp,
                                                           now_utc, d1_status, h4_status)
    m5_zone_buy_ok = m5["premium_discount"]["zone"] in ("DISCOUNT", "EQUILIBRIUM")
    m5_zone_sell_ok = m5["premium_discount"]["zone"] in ("PREMIUM", "EQUILIBRIUM")
    m5_dir_ok = m5["trend"] != "SIDEWAYS"
    h1_stale = severities.get("H1") == "soft"
    b = score_and_veto(h1, m15, m5, h4, d1, mtf_obs, session, "BUY", h1_stale, m5_zone_buy_ok, m5_dir_ok, spread_ratio)
    s = score_and_veto(h1, m15, m5, h4, d1, mtf_obs, session, "SELL", h1_stale, m5_zone_sell_ok, m5_dir_ok, spread_ratio)
    log(f"  امتیاز BUY raw={b[0]} vetoes={len(b[5])} | SELL raw={s[0]} vetoes={len(s[5])} | scalp: {scalp_reason or 'OK'}")
    b_clean = (len(b[5]) == 0 and b[0] >= MIN_SCORE); s_clean = (len(s[5]) == 0 and s[0] >= MIN_SCORE)
    if b_clean and s_clean: chosen = ("BUY",) + b if b[0] >= s[0] else ("SELL",) + s
    elif b_clean: chosen = ("BUY",) + b
    elif s_clean: chosen = ("SELL",) + s
    elif b[0] >= s[0]: chosen = ("BUY",) + b
    else: chosen = ("SELL",) + s
    side, raw, final, bd, reasons, blockers, vetoes, tier, zone = chosen
    normal_signal = None; normal_blockers = []
    if not vetoes and final >= MIN_SCORE:
        last_bar = m5["bars"][-1]
        side_ok = (side == "BUY" and last_bar["close"] >= last_bar["open"]) or (side == "SELL" and last_bar["close"] <= last_bar["open"])
        if not side_ok:
            normal_blockers = blockers + ["⚠ کندل آخر مخالف جهت سیگنال"]
        else:
            sig, err = build_signal(side, m5, m5["atr"], tier, zone[0], zone[1], zone[2], live_price)
            if sig is not None:
                dup, _ = is_duplicate_signal(sig, state, now_utc)
                if not dup:
                    normal_signal = sig; record_signal_v54(sig, state, now_utc)
            else:
                normal_blockers = blockers + [f"build: {err}"]
    ctx = {"now_utc": now_utc, "live_price": live_price, "m5": m5, "confirmed_scalp": None, "confirmed_normal": None}
    if scalp_verdict is not None and scalp_verdict["type"] == "CONFIRMED": ctx["confirmed_scalp"] = scalp_verdict["signal"]
    if normal_signal is not None: ctx["confirmed_normal"] = {"signal": normal_signal, "reasons": reasons, "blockers": blockers}
    if vetoes: ctx["no_trade_reason"] = "VETO"; ctx["no_trade_vetoes"] = vetoes
    elif final < MIN_SCORE: ctx["no_trade_reason"] = f"امتیاز {final}<{MIN_SCORE}"
    elif normal_blockers: ctx["no_trade_reason"] = normal_blockers[-1]
    else: ctx["no_trade_reason"] = scalp_reason or "بدون ستاپ"
    verdict = dispatch_final_verdict(ctx)
    if verdict == "CONFIRMED_SCALP": record_scalp_signal_v54(ctx["confirmed_scalp"], state, now_utc)


def main(argv):
    try: run_once()
    except Exception as e:
        import traceback
        log(f"[FATAL] {type(e).__name__}: {e}"); traceback.print_exc()


if __name__ == "__main__":
    main(sys.argv[1:])
