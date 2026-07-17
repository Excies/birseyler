import os
import sqlite3
import secrets
import hashlib
import time
import json
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template_string, send_file, jsonify,
    request, session, redirect, url_for
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

WEB_SIFRE = os.environ.get("WEB_SIFRE", "askgercek2026")
API_SIFRE = os.environ.get("API_SIFRE", "ag-api-gizli-key")

VERI_KLASORU = os.environ.get("VERI_KLASORU", os.path.join(os.path.dirname(os.path.abspath(__file__)), "veriler"))
DOSYA_KLASORU = os.path.join(VERI_KLASORU, "dosyalar")
DB_YOLU = os.path.join(VERI_KLASORU, "veritabani.db")

os.makedirs(DOSYA_KLASORU, exist_ok=True)

def db_al():
    conn = sqlite3.connect(DB_YOLU)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def db_baslat():
    conn = db_al()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dosyalar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dosya_adi TEXT NOT NULL,
            orijinal_adi TEXT,
            log_metni TEXT DEFAULT '',
            sebep TEXT DEFAULT 'BILINMEYEN',
            boyut REAL DEFAULT 0,
            tarih TEXT DEFAULT '',
            saat TEXT DEFAULT '',
            yuklendi TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            silindi INTEGER DEFAULT 0,
            silindi_zaman TIMESTAMP,
            onaylandi INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

db_baslat()

def giris_gerekli(f):
    @wraps(f)
    def sarmalanmis(*args, **kwargs):
        if not session.get("girisli"):
            return redirect(url_for("giris_sayfasi"))
        return f(*args, **kwargs)
    return sarmalanmis

def api_auth_gerekli(f):
    @wraps(f)
    def sarmalanmis(*args, **kwargs):
        sifre = request.headers.get("X-API-KEY") or request.args.get("api_key")
        if sifre != API_SIFRE:
            return jsonify({"hata": "Yetkisiz"}), 401
        return f(*args, **kwargs)
    return sarmalanmis

def dosya_ekle(dosya_adi, orijinal_adi, log_metni, sebep, boyut):
    now = datetime.now()
    conn = db_al()
    conn.execute(
        "INSERT INTO dosyalar (dosya_adi, orijinal_adi, log_metni, sebep, boyut, tarih, saat) VALUES (?,?,?,?,?,?,?)",
        (dosya_adi, orijinal_adi, log_metni, sebep, boyut, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"))
    )
    conn.commit()
    conn.close()

# ==================== SAYFALAR ====================

@app.route("/giris", methods=["GET", "POST"])
def giris_sayfasi():
    hata = None
    if request.method == "POST":
        girilen = request.form.get("sifre", "")
        if girilen == WEB_SIFRE:
            session["girisli"] = True
            return redirect(url_for("ana_sayfa"))
        hata = "Yanlis sifre"
    return render_template_string(LOGIN_HTML, hata=hata)

@app.route("/cikis")
def cikis():
    session.clear()
    return redirect(url_for("giris_sayfasi"))

@app.route("/")
@giris_gerekli
def ana_sayfa():
    return render_template_string(GALLERY_HTML)

# ==================== API ====================

@app.route("/api/dosyalar")
@giris_gerekli
def api_dosyalar():
    conn = db_al()
    satirlar = conn.execute(
        "SELECT * FROM dosyalar WHERE silindi=0 ORDER BY id DESC"
    ).fetchall()
    conn.close()

    dosyalar = [dict(s) for s in satirlar]

    ara = request.args.get("q", "").lower()
    sebep = request.args.get("sebep", "")
    tarih_bas = request.args.get("tarih_baslangic", "")
    tarih_bit = request.args.get("tarih_bitis", "")

    if ara:
        dosyalar = [d for d in dosyalar if ara in (d.get("log_metni") or "").lower() or ara in (d.get("orijinal_adi") or "").lower()]
    if sebep:
        dosyalar = [d for d in dosyalar if d.get("sebep") == sebep]
    if tarih_bas:
        dosyalar = [d for d in dosyalar if d.get("tarih", "") >= tarih_bas]
    if tarih_bit:
        dosyalar = [d for d in dosyalar if d.get("tarih", "") <= tarih_bit]

    toplam = len(dosyalar)
    toplam_mb = round(sum(d.get("boyut", 0) for d in dosyalar), 2)

    sayfa = int(request.args.get("sayfa", 1))
    sayfa_boyutu = int(request.args.get("sayfa_boyutu", 24))
    bas = (sayfa - 1) * sayfa_boyutu

    return jsonify({
        "dosyalar": dosyalar[bas:bas + sayfa_boyutu],
        "toplam": toplam,
        "toplam_mb": toplam_mb,
        "toplam_sayfa": max(1, (toplam + sayfa_boyutu - 1) // sayfa_boyutu),
        "sayfa": sayfa,
    })

@app.route("/api/goruntule/<dosya_adi>")
def api_goruntule(dosya_adi):
    if not session.get("girisli"):
        api_key = request.args.get("api_key")
        if api_key != API_SIFRE:
            return "Yetkisiz", 401
    yol = os.path.join(DOSYA_KLASORU, dosya_adi)
    if os.path.exists(yol):
        return send_file(yol, mimetype="image/png")
    return "Bulunamadi", 404

@app.route("/api/sil/<int:dosya_id>", methods=["DELETE"])
@giris_gerekli
def api_sil(dosya_id):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = db_al()
    conn.execute("UPDATE dosyalar SET silindi=1, silindi_zaman=? WHERE id=?", (now, dosya_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/toplu-sil", methods=["POST"])
@giris_gerekli
def api_toplu_sil():
    veri = request.get_json()
    ids = veri.get("ids", [])
    if not ids:
        return jsonify({"ok": False, "hata": "ID listesi bos"}), 400
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = db_al()
    conn.executemany("UPDATE dosyalar SET silindi=1, silindi_zaman=? WHERE id=?", [(now, i) for i in ids])
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "silinen": len(ids)})

# ==================== CLIENT API (askgercek.py kullanir) ====================

@app.route("/api/upload", methods=["POST"])
@api_auth_gerekli
def api_upload():
    if "dosya" not in request.files:
        return jsonify({"hata": "Dosya bulunamadi"}), 400

    dosya = request.files["dosya"]
    orijinal_adi = dosya.filename or "bilinmeyen.png"
    log_metni = request.form.get("log_metni", "")
    sebep = request.form.get("sebep", "BILINMEYEN")

    benzersiz = datetime.now().strftime("%Y%m%d_%H%M%S_") + secrets.token_hex(4) + ".png"
    kayit_yolu = os.path.join(DOSYA_KLASORU, benzersiz)
    dosya.save(kayit_yolu)

    boyut = round(os.path.getsize(kayit_yolu) / (1024 * 1024), 2)
    dosya_ekle(benzersiz, orijinal_adi, log_metni, sebep, boyut)

    return jsonify({"ok": True, "dosya_adi": benzersiz})

@app.route("/api/pending-deletions")
@api_auth_gerekli
def api_pending_deletions():
    conn = db_al()
    satirlar = conn.execute(
        "SELECT id, dosya_adi FROM dosyalar WHERE silindi=1 AND onaylandi=0"
    ).fetchall()
    conn.close()
    return jsonify({"silinecekler": [dict(s) for s in satirlar]})

@app.route("/api/confirm-deletions", methods=["POST"])
@api_auth_gerekli
def api_confirm_deletions():
    veri = request.get_json()
    ids = veri.get("ids", [])
    if not ids:
        return jsonify({"ok": False, "hata": "ID listesi bos"}), 400

    conn = db_al()
    satirlar = conn.execute(
        "SELECT id, dosya_adi FROM dosyalar WHERE id IN ({})".format(",".join("?" * len(ids))),
        ids
    ).fetchall()

    for s in satirlar:
        yol = os.path.join(DOSYA_KLASORU, s["dosya_adi"])
        if os.path.exists(yol):
            os.remove(yol)
        txt_yol = yol.rsplit(".", 1)[0] + ".txt"
        if os.path.exists(txt_yol):
            os.remove(txt_yol)

    conn.executemany("UPDATE dosyalar SET onaylandi=1 WHERE id=?", [(i,) for i in ids])
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "onaylanan": len(ids)})

@app.route("/api/durum")
@api_auth_gerekli
def api_durum():
    conn = db_al()
    toplam = conn.execute("SELECT COUNT(*) as s FROM dosyalar WHERE silindi=0").fetchone()["s"]
    bekleyen_silme = conn.execute("SELECT COUNT(*) as s FROM dosyalar WHERE silindi=1 AND onaylandi=0").fetchone()["s"]
    toplam_mb = conn.execute("SELECT COALESCE(SUM(boyut),0) as s FROM dosyalar WHERE silindi=0").fetchone()["s"]
    conn.close()
    return jsonify({
        "toplam_dosya": toplam,
        "bekleyen_silme": bekleyen_silme,
        "toplam_mb": round(toplam_mb, 2),
    })

# ==================== HTML SABLONLARI ====================

LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AskGercek - Giris</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh;display:flex;align-items:center;justify-content:center}
.login-box{background:#161b22;border:1px solid #30363d;border-radius:16px;padding:40px;width:100%;max-width:380px;text-align:center}
.login-box h1{font-size:24px;margin-bottom:8px;color:#fff}
.login-box p{color:#8b949e;font-size:14px;margin-bottom:28px}
.login-box input[type="password"]{width:100%;padding:12px 16px;background:#0d1117;border:1px solid #30363d;border-radius:10px;color:#c9d1d9;font-size:15px;outline:none;margin-bottom:16px;transition:border-color .2s}
.login-box input[type="password"]:focus{border-color:#58a6ff}
.login-box button{width:100%;padding:12px;background:#1f6feb;border:none;border-radius:10px;color:#fff;font-size:15px;font-weight:600;cursor:pointer;transition:opacity .2s}
.login-box button:hover{opacity:.85}
.hata{color:#f85149;font-size:13px;margin-bottom:12px}
.logo-icon{width:48px;height:48px;margin:0 auto 16px;color:#58a6ff}
</style>
</head>
<body>
<div class="login-box">
<svg class="logo-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
<h1>AskGercek</h1>
<p>Ekran goruntusu galerisine erisim icin sifrenizi girin</p>
{% if hata %}<div class="hata">{{ hata }}</div>{% endif %}
<form method="POST">
<input type="password" name="sifre" placeholder="Sifre" autofocus required>
<button type="submit">Giris Yap</button>
</form>
</div>
</body>
</html>"""

GALLERY_HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AskGercek Galeri</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--text2:#8b949e;--accent:#58a6ff;--accent2:#1f6feb;--danger:#f85149;--success:#3fb950;--warning:#d29922;--radius:12px}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
.header{background:var(--card);border-bottom:1px solid var(--border);padding:16px 24px;position:sticky;top:0;z-index:100}
.header-inner{max-width:1400px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
.logo{display:flex;align-items:center;gap:10px;font-size:20px;font-weight:700;color:#fff}
.logo svg{width:28px;height:28px}
.header-right{display:flex;align-items:center;gap:16px}
.stats{display:flex;gap:16px;font-size:13px;color:var(--text2)}
.stat{display:flex;align-items:center;gap:5px}
.stat-val{color:var(--accent);font-weight:600}
.cikis-btn{padding:6px 12px;background:transparent;border:1px solid var(--border);border-radius:8px;color:var(--text2);font-size:12px;cursor:pointer;text-decoration:none;transition:all .2s}
.cikis-btn:hover{border-color:var(--danger);color:var(--danger)}
.toolbar{max-width:1400px;margin:20px auto;padding:0 24px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.search-box{flex:1;min-width:250px;position:relative}
.search-box input{width:100%;padding:10px 14px 10px 38px;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-size:14px;outline:none;transition:border-color .2s}
.search-box input:focus{border-color:var(--accent)}
.search-box svg{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--text2);width:16px;height:16px}
.filter-btn{padding:8px 14px;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);color:var(--text2);font-size:13px;cursor:pointer;transition:all .2s}
.filter-btn:hover{border-color:var(--accent);color:var(--text)}
.filter-btn.active{background:var(--accent2);border-color:var(--accent2);color:#fff}
.date-input{padding:8px 12px;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-size:13px;outline:none;width:140px}
.date-input:focus{border-color:var(--accent)}
.btn{padding:8px 14px;border:none;border-radius:var(--radius);font-size:13px;cursor:pointer;display:flex;align-items:center;gap:6px;transition:opacity .2s}
.btn:hover{opacity:.85}
.btn-primary{background:var(--accent2);color:#fff}
.btn-danger{background:var(--danger);color:#fff}
.btn svg{width:14px;height:14px}
.main{max-width:1400px;margin:0 auto;padding:0 24px 40px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;cursor:pointer;transition:all .25s ease;position:relative}
.card:hover{border-color:var(--accent);transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.4)}
.card.selected{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent2)}
.card-img{width:100%;aspect-ratio:16/9;object-fit:cover;display:block;background:#000}
.card-body{padding:10px 12px}
.card-title{font-size:12px;color:var(--text2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:6px}
.card-meta{display:flex;justify-content:space-between;align-items:center}
.card-date{font-size:11px;color:var(--text2)}
.badge{font-size:10px;font-weight:600;padding:2px 8px;border-radius:20px;text-transform:uppercase}
.badge-OTO{background:rgba(139,148,158,.15);color:var(--text2)}
.badge-MANUEL{background:rgba(88,166,255,.15);color:var(--accent)}
.badge-PDF{background:rgba(248,81,73,.15);color:var(--danger)}
.badge-PENCERE{background:rgba(210,153,34,.15);color:var(--warning)}
.badge-SURE{background:rgba(63,185,80,.15);color:var(--success)}
.badge-BILINMEYEN{background:rgba(139,148,158,.1);color:var(--text2)}
.card-delete{position:absolute;top:8px;right:8px;width:28px;height:28px;border-radius:50%;background:rgba(248,81,73,.85);border:none;color:#fff;font-size:14px;cursor:pointer;display:none;align-items:center;justify-content:center;transition:background .2s}
.card:hover .card-delete{display:flex}
.card-delete:hover{background:var(--danger)}
.card-check{position:absolute;top:8px;left:8px;width:22px;height:22px;border-radius:6px;background:rgba(0,0,0,.6);border:2px solid rgba(255,255,255,.3);color:#fff;font-size:12px;cursor:pointer;display:none;align-items:center;justify-content:center;transition:all .2s}
.card:hover .card-check{display:flex}
.card-check.checked{display:flex;background:var(--accent2);border-color:var(--accent2)}
.pagination{display:flex;justify-content:center;align-items:center;gap:8px;margin-top:28px;flex-wrap:wrap}
.page-btn{padding:8px 14px;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);color:var(--text2);font-size:13px;cursor:pointer;transition:all .2s}
.page-btn:hover{border-color:var(--accent);color:var(--text)}
.page-btn.active{background:var(--accent2);border-color:var(--accent2);color:#fff}
.page-btn:disabled{opacity:.4;cursor:not-allowed}
.page-info{font-size:13px;color:var(--text2)}
.empty{text-align:center;padding:80px 20px;color:var(--text2)}
.empty svg{width:64px;height:64px;margin-bottom:16px;opacity:.3}
.empty h3{font-size:18px;color:var(--text);margin-bottom:8px}
.lightbox{position:fixed;inset:0;background:rgba(0,0,0,.92);z-index:200;display:none;align-items:center;justify-content:center;flex-direction:column;padding:20px}
.lightbox.open{display:flex}
.lightbox-img{max-width:90vw;max-height:80vh;object-fit:contain;border-radius:8px;box-shadow:0 0 60px rgba(0,0,0,.5)}
.lightbox-info{margin-top:14px;text-align:center;color:var(--text2);font-size:13px;max-width:80vw}
.lightbox-close{position:absolute;top:16px;right:20px;width:40px;height:40px;border-radius:50%;background:rgba(255,255,255,.1);border:none;color:#fff;font-size:20px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .2s}
.lightbox-close:hover{background:rgba(255,255,255,.25)}
.lightbox-nav{position:absolute;top:50%;transform:translateY(-50%);width:48px;height:48px;border-radius:50%;background:rgba(255,255,255,.08);border:none;color:#fff;font-size:22px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .2s}
.lightbox-nav:hover{background:rgba(255,255,255,.2)}
.lightbox-prev{left:16px}
.lightbox-next{right:16px}
.autorefresh{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text2)}
.autorefresh label{cursor:pointer;display:flex;align-items:center;gap:4px}
.autorefresh input{accent-color:var(--accent)}
.topbar{display:flex;gap:8px;align-items:center}
@media(max-width:600px){.header-inner{flex-direction:column;align-items:flex-start}.grid{grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px}.toolbar{flex-direction:column}.search-box{min-width:100%}}
</style>
</head>
<body>

<div class="header">
<div class="header-inner">
<div class="logo">
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
AskGercek Galeri
</div>
<div class="header-right">
<div class="stats">
<div class="stat">Toplam: <span class="stat-val" id="s-toplam">0</span></div>
<div class="stat">Boyut: <span class="stat-val" id="s-boyut">0 MB</span></div>
</div>
<a href="/cikis" class="cikis-btn">Cikis</a>
</div>
</div>
</div>

<div class="toolbar">
<div class="search-box">
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
<input type="text" id="arama" placeholder="Dosya adi veya icerik ara...">
</div>
<button class="filter-btn active" data-sebep="">Tumu</button>
<button class="filter-btn" data-sebep="OTO">Oto</button>
<button class="filter-btn" data-sebep="MANUEL">Manuel</button>
<button class="filter-btn" data-sebep="PDF">PDF</button>
<button class="filter-btn" data-sebep="PENCERE">Pencere</button>
<button class="filter-btn" data-sebep="SURE">Sure</button>
<input type="date" class="date-input" id="tarih-bas" title="Baslangic tarihi">
<input type="date" class="date-input" id="tarih-bit" title="Bitis tarihi">
<div class="topbar">
<div class="autorefresh">
<label><input type="checkbox" id="otomatik"> Otomatik</label>
</div>
<button class="btn btn-primary" id="yenile-btn">
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
Yenile
</button>
<button class="btn btn-danger" id="toplu-sil-btn" style="display:none">
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
Secilenleri Sil (<span id="secili-sayi">0</span>)
</button>
</div>
</div>

<div class="main">
<div class="grid" id="grid"></div>
<div class="pagination" id="pagination"></div>
</div>

<div class="lightbox" id="lightbox">
<button class="lightbox-close" id="lb-kapat">&times;</button>
<button class="lightbox-nav lightbox-prev" id="lb-prev">&#8249;</button>
<button class="lightbox-nav lightbox-next" id="lb-next">&#8250;</button>
<img class="lightbox-img" id="lb-img" src="">
<div class="lightbox-info" id="lb-info"></div>
</div>

<script>
let aktifSebep = "";
let aktifSayfa = 1;
let sayfaBoyutu = 24;
let lightboxIndex = -1;
let tumDosyalar = [];
let secilenler = new Set();
let aramaTimer = null;

const grid = document.getElementById("grid");
const pagination = document.getElementById("pagination");
const aramaInput = document.getElementById("arama");
const tarihBas = document.getElementById("tarih-bas");
const tarihBit = document.getElementById("tarih-bit");

async function dosyalariGetir() {
    const params = new URLSearchParams();
    params.set("sayfa", aktifSayfa);
    params.set("sayfa_boyutu", sayfaBoyutu);
    if (aktifSebep) params.set("sebep", aktifSebep);
    if (aramaInput.value.trim()) params.set("q", aramaInput.value.trim());
    if (tarihBas.value) params.set("tarih_baslangic", tarihBas.value);
    if (tarihBit.value) params.set("tarih_bitis", tarihBit.value);

    try {
        const res = await fetch("/api/dosyalar?" + params.toString());
        if (res.status === 401 || res.redirected) { window.location.href = "/giris"; return; }
        const data = await res.json();

        document.getElementById("s-toplam").textContent = data.toplam;
        document.getElementById("s-boyut").textContent = data.toplam_mb + " MB";

        if (data.dosyalar.length === 0) {
            grid.innerHTML = '<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg><h3>Henuz goruntu yok</h3><p>Client baglandiginda ekran goruntuleri burada gorunecek.</p></div>';
            pagination.innerHTML = "";
            return;
        }

        tumDosyalar = data.dosyalar;

        grid.innerHTML = data.dosyalar.map((d, i) => `
            <div class="card ${secilenler.has(d.id) ? 'selected' : ''}" data-index="${i}">
                <img class="card-img" src="/api/goruntule/${encodeURIComponent(d.dosya_adi)}" loading="lazy" alt="">
                <button class="card-check ${secilenler.has(d.id) ? 'checked' : ''}" onclick="event.stopPropagation();seciliAltern(${d.id})" title="Sec">&#10003;</button>
                <button class="card-delete" onclick="event.stopPropagation();tekSil(${d.id})" title="Sil">&times;</button>
                <div class="card-body">
                    <div class="card-title" title="${(d.log_metni||'').replace(/"/g,'&quot;')}">${d.log_metni || d.orijinal_adi || d.dosya_adi}</div>
                    <div class="card-meta">
                        <span class="card-date">${d.tarih} ${d.saat}</span>
                        <span class="badge badge-${d.sebep}">${d.sebep}</span>
                    </div>
                </div>
            </div>
        `).join("");

        grid.querySelectorAll(".card").forEach((card) => {
            card.addEventListener("click", (e) => {
                if (e.target.closest(".card-delete") || e.target.closest(".card-check")) return;
                lightboxIndex = parseInt(card.dataset.index);
                lightboxAc();
            });
        });

        if (data.toplam_sayfa <= 1) { pagination.innerHTML = ""; return; }
        let pHtml = `<button class="page-btn" onclick="sayfayaGit(${aktifSayfa-1})" ${aktifSayfa<=1?"disabled":""}>&#8249;</button>`;
        for (let s=1; s<=data.toplam_sayfa; s++) {
            if (s===1 || s===data.toplam_sayfa || Math.abs(s-aktifSayfa)<=2) {
                pHtml += `<button class="page-btn ${s===aktifSayfa?"active":""}" onclick="sayfayaGit(${s})">${s}</button>`;
            } else if (Math.abs(s-aktifSayfa)===3) {
                pHtml += `<span class="page-info">...</span>`;
            }
        }
        pHtml += `<button class="page-btn" onclick="sayfayaGit(${aktifSayfa+1})" ${aktifSayfa>=data.toplam_sayfa?"disabled":""}>&#8250;</button>`;
        pHtml += `<span class="page-info">${data.toplam} sonuc</span>`;
        pagination.innerHTML = pHtml;

    } catch (e) {
        grid.innerHTML = '<div class="empty"><h3>Baglanti hatasi</h3><p>Sunucu calisiyor mu?</p></div>';
    }
}

function sayfayaGit(sayfa) { aktifSayfa = sayfa; dosyalariGetir(); window.scrollTo({top:0,behavior:"smooth"}); }

async function tekSil(id) {
    if (!confirm("Silmek istediginize emin misiniz?")) return;
    await fetch("/api/sil/" + id, {method:"DELETE"});
    dosyalariGetir();
}

function seciliAltern(id) {
    if (secilenler.has(id)) secilenler.delete(id); else secilenler.add(id);
    seciliGuncelle();
    dosyalariGetir();
}

function seciliGuncelle() {
    const btn = document.getElementById("toplu-sil-btn");
    const sayi = document.getElementById("secili-sayi");
    sayi.textContent = secilenler.size;
    btn.style.display = secilenler.size > 0 ? "flex" : "none";
}

document.getElementById("toplu-sil-btn").addEventListener("click", async () => {
    if (!confirm(secilenler.size + " goruntuyu silmek istediginize emin misiniz?")) return;
    await fetch("/api/toplu-sil", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ids: [...secilenler]})
    });
    secilenler.clear();
    seciliGuncelle();
    dosyalariGetir();
});

function lightboxAc() {
    if (lightboxIndex < 0 || lightboxIndex >= tumDosyalar.length) return;
    const d = tumDosyalar[lightboxIndex];
    document.getElementById("lb-img").src = "/api/goruntule/" + encodeURIComponent(d.dosya_adi);
    document.getElementById("lb-info").innerHTML = `<strong>${d.log_metni || d.orijinal_adi || d.dosya_adi}</strong><br>${d.tarih} ${d.saat} &middot; ${d.boyut} MB &middot; <span class="badge badge-${d.sebep}">${d.sebep}</span>`;
    document.getElementById("lightbox").classList.add("open");
    document.body.style.overflow = "hidden";
}
function lightboxKapat() { document.getElementById("lightbox").classList.remove("open"); document.body.style.overflow = ""; }

document.getElementById("lb-kapat").addEventListener("click", lightboxKapat);
document.getElementById("lightbox").addEventListener("click", (e) => { if (e.target===e.currentTarget) lightboxKapat(); });
document.getElementById("lb-prev").addEventListener("click", (e) => { e.stopPropagation(); if (lightboxIndex>0){lightboxIndex--;lightboxAc();} });
document.getElementById("lb-next").addEventListener("click", (e) => { e.stopPropagation(); if (lightboxIndex<tumDosyalar.length-1){lightboxIndex++;lightboxAc();} });
document.addEventListener("keydown", (e) => {
    if (!document.getElementById("lightbox").classList.contains("open")) return;
    if (e.key==="Escape") lightboxKapat();
    if (e.key==="ArrowLeft" && lightboxIndex>0){lightboxIndex--;lightboxAc();}
    if (e.key==="ArrowRight" && lightboxIndex<tumDosyalar.length-1){lightboxIndex++;lightboxAc();}
});

document.querySelectorAll(".filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".filter-btn").forEach(b=>b.classList.remove("active"));
        btn.classList.add("active");
        aktifSebep = btn.dataset.sebep;
        aktifSayfa = 1;
        dosyalariGetir();
    });
});
aramaInput.addEventListener("input", () => { clearTimeout(aramaTimer); aramaTimer = setTimeout(()=>{aktifSayfa=1;dosyalariGetir();}, 300); });
tarihBas.addEventListener("change", () => { aktifSayfa=1; dosyalariGetir(); });
tarihBit.addEventListener("change", () => { aktifSayfa=1; dosyalariGetir(); });
document.getElementById("yenile-btn").addEventListener("click", dosyalariGetir);

let otomatikInterval = null;
document.getElementById("otomatik").addEventListener("change", (e) => {
    if (e.target.checked) { otomatikInterval = setInterval(dosyalariGetir, 5000); }
    else { clearInterval(otomatikInterval); }
});

dosyalariGetir();
</script>
</body>
</html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = "0.0.0.0" if os.environ.get("RAILWAY_STATIC_URL") else "127.0.0.1"
    print("=" * 50)
    print("  AskGercek Web Galeri")
    print(f"  http://{host}:{port}")
    print("=" * 50)
    app.run(host=host, port=port, debug=False)
