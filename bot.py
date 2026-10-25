"""
Ev ilanı takip botu
Emlakjet, Hepsiemlak ve Sahibinden arama sayfalarını izler,
kriterlere uyan YENİ ilanları Telegram'a gönderir.
"""
import json
import os
import re
import sys
import time
import random
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import yaml
from bs4 import BeautifulSoup

try:  # Tarayıcı taklidi: bot korumalarına takılma ihtimalini düşürür
    from curl_cffi import requests as http
    IMPERSONATE = {"impersonate": "chrome"}
except ImportError:  # pragma: no cover
    import requests as http
    IMPERSONATE = {}

ROOT = Path(__file__).parent
SEEN_FILE = ROOT / "seen.json"
CONFIG_FILE = ROOT / "config.yaml"

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Her sitede ilan linkinin kalıbı (id'yi yakalar)
LINK_PATTERNS = {
    "emlakjet": re.compile(r"/ilan/[a-z0-9\-]+-(\d{5,})/?$"),
    "hepsiemlak": re.compile(r"^/[a-z0-9\-]+/[a-z\-]+/(\d+-\d+)/?$"),
    "sahibinden": re.compile(r"/ilan/[a-z0-9\-]+/(\d{6,})/detay"),
}
BASES = {
    "emlakjet": "https://www.emlakjet.com",
    "hepsiemlak": "https://www.hepsiemlak.com",
    "sahibinden": "https://www.sahibinden.com",
}


# ─── Yardımcılar ────────────────────────────────────────────────
def norm(s: str) -> str:
    """Türkçe karakter + büyük/küçük harf farkını yok say."""
    s = s.replace("İ", "i").replace("I", "ı").lower()
    tr = str.maketrans("çğıöşü", "cgiosu")
    s = s.translate(tr)
    s = unicodedata.normalize("NFKD", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_price(text: str):
    m = re.search(r"(\d{1,3}(?:[.\s]\d{3})+|\d{6,})\s*(?:TL|₺)", text)
    if not m:
        m = re.search(r"(?:TL|₺)\s*(\d{1,3}(?:[.\s]\d{3})+)", text)
    if not m:
        return None
    return int(re.sub(r"\D", "", m.group(1)))


def parse_m2(text: str):
    vals = [int(v) for v in re.findall(r"(\d{2,4})\s*m(?:²|2)\b", text)]
    return max(vals) if vals else None  # brüt genelde büyük olan


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def fetch(url: str) -> str:
    r = http.get(url, headers=HEADERS, timeout=30, **IMPERSONATE)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.text


def looks_blocked(html: str) -> bool:
    h = html.lower()
    return any(k in h for k in (
        "cf-challenge", "captcha", "olağandışı erişim", "unusual traffic",
        "access denied", "just a moment",
    ))


# ─── Liste sayfası ──────────────────────────────────────────────
def extract_listings(site: str, html: str, page_url: str):
    soup = BeautifulSoup(html, "html.parser")
    pat = LINK_PATTERNS[site]
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0]
        path = re.sub(r"^https?://[^/]+", "", href)
        m = pat.search(path)
        if not m:
            continue
        lid = f"{site}:{m.group(1)}"
        # İlan kartını bul: linkten yukarı çık, metni yeterince dolu olana kadar
        # (başka bir ilanın linkini içeren üst kutuya çıkma)
        card = a
        for _ in range(6):
            parent = card.parent
            if parent is None or parent.name in ("body", "html"):
                break
            other = any(
                (mm := pat.search(re.sub(r"^https?://[^/]+", "", x["href"].split("?")[0])))
                and mm.group(1) != m.group(1)
                for x in parent.find_all("a", href=True)
            )
            if other:
                break
            card = parent
            if len(card.get_text(" ", strip=True)) > 60:
                break
        text = card.get_text(" ", strip=True)
        img = card.find("img")
        img_url = None
        if img:
            img_url = img.get("data-src") or img.get("src")
            if img_url and img_url.startswith("data:"):
                img_url = None
        title = a.get("title") or a.get_text(" ", strip=True) or text[:80]
        prev = found.get(lid)
        if prev is None or len(text) > len(prev["text"]):
            found[lid] = {
                "id": lid,
                "site": site,
                "url": urljoin(BASES[site], path),
                "title": title[:150],
                "text": text,
                "image": urljoin(page_url, img_url) if img_url else None,
            }
    return list(found.values())


# ─── Detay sayfası ──────────────────────────────────────────────
def field_from_detail(text_lines, labels):
    """'Bina Yaşı' gibi bir etiketin hemen yanındaki/altındaki değeri bulur."""
    nl = [norm(x) for x in text_lines]
    for lab in labels:
        n = norm(lab)
        for i, line in enumerate(nl):
            if line == n or line.startswith(n + " ") or line.startswith(n + ":"):
                rest = line[len(n):].strip(" :")
                if rest:
                    return rest
                for j in range(i + 1, min(i + 3, len(nl))):
                    if nl[j]:
                        return nl[j]
    return None


def detail_info(url: str):
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
    age = field_from_detail(lines, ["Bina Yaşı", "Binanın Yaşı"])
    floor = field_from_detail(lines, ["Bulunduğu Kat", "Kat Sayısı / Bulunduğu Kat", "Bulunduğu Kat Sayısı"])
    m2 = field_from_detail(lines, ["m² (Brüt)", "Brüt Metrekare", "Brüt m²", "m2 (Brüt)"])
    price_text = field_from_detail(lines, ["Fiyat", "İlan Fiyatı"])
    loc = field_from_detail(lines, ["Mahalle", "Konum"])
    age_n = None
    if age is not None:
        if "sifir" in age or age.startswith("0"):
            age_n = 0
        else:
            mm = re.search(r"\d+", age)
            age_n = int(mm.group()) if mm else None
    m2_n = None
    if m2:
        mm = re.search(r"\d+", m2)
        m2_n = int(mm.group()) if mm else None
    return {
        "age": age_n,
        "floor": floor,
        "m2": m2_n,
        "price": parse_price(price_text + " TL") if price_text else None,
        "location": loc,
        "full_text": norm(" ".join(lines[:400])),
    }


# ─── Filtre ─────────────────────────────────────────────────────
def floor_excluded(floor: str, excluded) -> bool:
    f = norm(floor)
    f_digits = re.sub(r"[^\d]", "", f)
    for ex in excluded:
        e = norm(ex)
        if e.isdigit():
            # "1", "1. kat", "1.kat" eşleşsin; "11", "10" eşleşmesin
            if f_digits == e and not re.search(r"\d+\s*-\s*\d+", f):
                return True
        elif re.search(r"(?<!\d)" + re.escape(e), f):
            return True
    return False


def check(listing, info, flt, send_if_unknown):
    """(geçti_mi, sebep) döner."""
    price = (info or {}).get("price") or parse_price(listing["text"])
    m2 = (info or {}).get("m2") or parse_m2(listing["text"])

    if price is not None and not (flt["price_min"] <= price <= flt["price_max"]):
        return False, f"fiyat {price:,}"
    if m2 is not None and m2 < flt["m2_min"]:
        return False, f"{m2} m²"

    if info:
        if info["age"] is not None and info["age"] > flt["building_age_max"]:
            return False, f"bina yaşı {info['age']}"
        if info["floor"] and floor_excluded(info["floor"], flt["excluded_floors"]):
            return False, f"kat {info['floor']}"
        unknown = info["age"] is None or not info["floor"]
        if unknown and not send_if_unknown:
            return False, "bina yaşı/kat bilinmiyor"

    kws = [norm(k) for k in flt.get("location_keywords") or []]
    if kws:
        hay = norm(listing["text"] + " " + listing["title"] + " " + ((info or {}).get("location") or ""))
        if not any(re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", hay) for k in kws):
            return False, "konum"

    listing["price"] = price
    listing["m2"] = m2
    return True, ""


# ─── Telegram ───────────────────────────────────────────────────
def resolve_chat_id(state):
    """TELEGRAM_CHAT_ID verilmemişse bota mesaj atan kişinin chat id'sini bul."""
    global TG_CHAT
    if TG_CHAT:
        return
    if state.get("chat_id"):
        TG_CHAT = str(state["chat_id"])
        return
    if not TG_TOKEN:
        return
    dbg = state["telegram_debug"] = {"token_len": len(TG_TOKEN), "token_has_space": TG_TOKEN != TG_TOKEN.strip()}
    try:
        me = http.get(f"https://api.telegram.org/bot{TG_TOKEN.strip()}/getMe", timeout=30).json()
        dbg["getMe"] = {"ok": me.get("ok"), "username": (me.get("result") or {}).get("username"),
                        "error": me.get("description")}
        r = http.get(f"https://api.telegram.org/bot{TG_TOKEN.strip()}/getUpdates", timeout=30)
        data = r.json()
        dbg["getUpdates"] = {"ok": data.get("ok"), "count": len(data.get("result") or []),
                             "error": data.get("description")}
        for u in reversed(data.get("result", [])):
            msg = u.get("message") or u.get("edited_message") or {}
            cid = (msg.get("chat") or {}).get("id")
            if cid:
                TG_CHAT = str(cid)
                state["chat_id"] = cid
                print("Chat ID bulundu.")
                return
        print("Chat ID bulunamadı: Telegram'da bota bir mesaj at.")
    except Exception as e:
        dbg["exception"] = repr(e)[:200]
        print("getUpdates hatası:", e)


def tg_send(text, image=None):
    if not (TG_TOKEN and TG_CHAT):
        print("[telegram kapalı]", text)
        return
    base = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        if image:
            r = http.post(f"{base}/sendPhoto", data={
                "chat_id": TG_CHAT, "photo": image, "caption": text, "parse_mode": "HTML"}, timeout=30)
            if r.status_code == 200:
                return
        http.post(f"{base}/sendMessage", data={
            "chat_id": TG_CHAT, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": "false"}, timeout=30)
    except Exception as e:
        print("Telegram hatası:", e)


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_msg(l, info):
    parts = [f"🏠 <b>{esc(l['title'])}</b>"]
    if l.get("price"):
        parts.append(f"💰 {l['price']:,} TL".replace(",", "."))
    meta = []
    if l.get("m2"):
        meta.append(f"{l['m2']} m²")
    if info and info.get("floor"):
        meta.append(f"Kat: {info['floor']}")
    if info and info.get("age") is not None:
        meta.append(f"Bina yaşı: {info['age']}")
    if meta:
        parts.append("📐 " + " · ".join(meta))
    parts.append(f"🔗 <a href=\"{l['url']}\">İlanı aç</a> ({l['site']})")
    return "\n".join(parts)


# ─── Ana akış ───────────────────────────────────────────────────
def main():
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    flt = cfg["filters"]
    send_unknown = cfg.get("send_if_unknown", True)
    state = load_json(SEEN_FILE, {"seen": {}, "errors": {}})
    seen = state.setdefault("seen", {})
    errors = state.setdefault("errors", {})
    resolve_chat_id(state)
    if TG_TOKEN and not TG_CHAT:
        print("Telegram chat bulunamadı; bota mesaj atınca bildirimler başlar.")
        SEEN_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=0), encoding="utf-8")
        return
    inited = set(state.setdefault("initialized", []))
    any_first = False

    sent = 0
    for s in cfg["searches"]:
        url = (s.get("url") or "").strip()
        if not url:
            continue
        site, name = s["site"], s.get("name", s["site"])
        try:
            html = fetch(url)
            if looks_blocked(html):
                raise RuntimeError("bot korumasına takıldı")
            listings = extract_listings(site, html, url)
            if not listings:
                raise RuntimeError("sayfada ilan bulunamadı (site yapısı değişmiş olabilir)")
            errors.pop(name, None)
        except Exception as e:
            print(f"{name}: HATA {e}")
            n = errors.get(name, 0) + 1
            errors[name] = n
            if n == 3:  # 3 kez üst üste başarısızsa bir kere haber ver
                tg_send(f"⚠️ {esc(name)} kontrol edilemiyor: {esc(str(e))}")
            continue

        first_run = url not in inited  # yeni eklenen arama: mevcut ilanları sadece kaydet
        if first_run:
            inited.add(url)
            any_first = True
        new = [l for l in listings if l["id"] not in seen]
        print(f"{name}: {len(listings)} ilan, {len(new)} yeni")
        for l in new:
            seen[l["id"]] = int(time.time())
            if first_run:
                continue  # ilk çalışmada mevcut ilanları sadece kaydet
            ok, why = check(l, None, flt, True)  # karttaki bilgilerle ön eleme
            if not ok:
                print(f"  elendi ({why}): {l['url']}")
                continue
            info = None
            try:
                time.sleep(random.uniform(1.5, 3.5))
                info = detail_info(l["url"])
            except Exception as e:
                print("  detay alınamadı:", l["url"], e)
            ok, why = check(l, info, flt, send_unknown)
            if ok:
                tg_send(format_msg(l, info), l.get("image"))
                sent += 1
            else:
                print(f"  elendi ({why}): {l['url']}")
        time.sleep(random.uniform(2, 5))

    state["initialized"] = sorted(inited)
    if any_first:
        tg_send(f"✅ Ev botu yeni aramayı izlemeye başladı. Şu an {len(seen)} ilan kayıtlı; "
                "bundan sonra çıkan yeni ilanlar buraya gelecek.")

    # 60 günden eski kayıtları temizle
    cutoff = time.time() - 60 * 86400
    state["seen"] = {k: v for k, v in seen.items() if v > cutoff}
    SEEN_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"Bitti. {sent} bildirim gönderildi.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        resolve_chat_id({})
        tg_send("👋 Test mesajı: ev botu Telegram'a ulaşabiliyor.")
    else:
        main()
