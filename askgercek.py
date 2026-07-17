import os
import time
import threading
import queue
import json
import secrets
from datetime import datetime
import pygetwindow as gw
from PIL import ImageGrab, ImageOps, ImageDraw, Image
import requests

# ==================== TELEGRAM AYARLARI ====================
TELEGRAM_TOKEN = "8114796003:AAH5rHIsMh1aQ_wGp69Bt8JFT8foL-eWZ4A"
TELEGRAM_CHAT_ID = "6154849380"
# ===========================================================

# ==================== RAILWAY AYARLARI ====================
RAILWAY_URL = "web-production-25440.up.railway.app"  # Ornegin: https://askgercek.railway.app
RAILWAY_API_KEY = "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"  # Sunucudaki API_SIFRE ile ayni olmali
# ===========================================================

# Programın ilk açılış zamanını Uptime hesabı için kaydediyoruz
PROGRAM_BASLANGIC_ZAMANI = time.time()

son_update_id = 0
gonderim_kuyrugu = queue.Queue()

def sync_queue_dosyasi():
    try:
        proje = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        proje = os.getcwd()
    return os.path.join(proje, "sync_queue.json")

def sync_queue_yukle():
    yol = sync_queue_dosyasi()
    if os.path.exists(yol):
        try:
            with open(yol, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"bekleyen_yuklemeler": [], "bekleyen_silmeler": []}

def sync_queue_kaydet(veri):
    try:
        with open(sync_queue_dosyasi(), "w", encoding="utf-8") as f:
            json.dump(veri, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def sync_queueye_yukleme_ekle(dosya_yolu, log_metni, sebep):
    veri = sync_queue_yukle()
    veri["bekleyen_yuklemeler"].append({
        "dosya_yolu": dosya_yolu,
        "log_metni": log_metni,
        "sebep": sebep,
        "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    sync_queue_kaydet(veri)

def sync_queueye_silme_ekle(dosya_adi):
    veri = sync_queue_yukle()
    veri["bekleyen_silmeler"].append({
        "dosya_adi": dosya_adi,
        "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    sync_queue_kaydet(veri)

def dosya_yukle_railway(dosya_yolu, log_metni, sebep):
    if not RAILWAY_URL or not RAILWAY_API_KEY:
        return False
    try:
        url = f"{RAILWAY_URL.rstrip('/')}/api/upload"
        with open(dosya_yolu, "rb") as f:
            cevap = requests.post(
                url,
                files={"dosya": f},
                data={"log_metni": log_metni, "sebep": sebep},
                headers={"X-API-KEY": RAILWAY_API_KEY},
                timeout=30
            )
        return cevap.status_code == 200 and cevap.json().get("ok")
    except Exception:
        return False

def pending_deletions_kontrol():
    if not RAILWAY_URL or not RAILWAY_API_KEY:
        return []
    try:
        url = f"{RAILWAY_URL.rstrip('/')}/api/pending-deletions"
        cevap = requests.get(url, headers={"X-API-KEY": RAILWAY_API_KEY}, timeout=15)
        if cevap.status_code == 200:
            return cevap.json().get("silinecekler", [])
    except Exception:
        pass
    return []

def confirm_deletions(ids):
    if not RAILWAY_URL or not RAILWAY_API_KEY or not ids:
        return False
    try:
        url = f"{RAILWAY_URL.rstrip('/')}/api/confirm-deletions"
        cevap = requests.post(url, json={"ids": ids}, headers={"X-API-KEY": RAILWAY_API_KEY}, timeout=15)
        return cevap.status_code == 200 and cevap.json().get("ok")
    except Exception:
        return False

def kayit_klasoru_al():
    try:
        proje_klasoru = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        proje_klasoru = os.getcwd()
        
    kayit_klasoru = os.path.join(proje_klasoru, "askgercek")
    if not os.path.exists(kayit_klasoru): 
        os.makedirs(kayit_klasoru)
    return kayit_klasoru

def aktif_pencere_basligi_al():
    try:
        aktif_pencere = gw.getActiveWindow()
        if aktif_pencere and aktif_pencere.title:
            return aktif_pencere.title
    except Exception:
        pass
    return "Masaustu / Bilinmeyen"

def pdf_kontrol_et(pencere_basligi):
    kritik_kelimeler = [".pdf", "acrobat", "reader", "foxit", "nitro", "pdf viewer"]
    baslik_kucuk = pencere_basligi.lower()
    return any(kelime in baslik_kucuk for kelime in kritik_kelimeler)

def yerel_ss_al_ve_kuyruga_ekle(sebep_metni="Oto"):
    try:
        kayit_klasoru = kayit_klasoru_al()
        su_anki_pencere = aktif_pencere_basligi_al()
        is_pdf = pdf_kontrol_et(su_anki_pencere)

        # === ekran görüntüsü ===
        ekran = ImageGrab.grab().convert("L")  # grayscale

        # === metin bilgisi ===
        zaman_metni = datetime.now().strftime("%H:%M:%S")
        pencere_metni = (
            su_anki_pencere[:50] + "..."
            if len(su_anki_pencere) > 50
            else su_anki_pencere
        )

        etiket = "🚨 [ÖNEMLİ-PDF]" if is_pdf else f"[{sebep_metni}]"
        log_metni = f"{etiket} ({zaman_metni}) {pencere_metni}"

        # === ekran üstüne yazı çiz ===
        draw = ImageDraw.Draw(ekran)
        draw.rectangle([(5, 5), (800, 30)], fill=0)
        draw.text((10, 8), log_metni, fill=255)

        # === daha az kalite kaybı (0.75 öneri) ===
        olcek = 0.75
        yeni_boyut = (
            int(ekran.width * olcek),
            int(ekran.height * olcek)
        )

        ekran_optimize = ekran.resize(
            yeni_boyut,
            Image.Resampling.LANCZOS
        )

        # === dosya isimleri ===
        benzersiz_id = datetime.now().strftime('%Y%m%d_%H%M%S_%f')

        dosya_yolu = os.path.join(kayit_klasoru, f"ekran_{benzersiz_id}.png")
        txt_yolu = os.path.join(kayit_klasoru, f"ekran_{benzersiz_id}.txt")

        # === kayıt ===
        ekran_optimize.save(dosya_yolu, optimize=True)

        with open(txt_yolu, "w", encoding="utf-8") as f:
            f.write(log_metni)

        # === kuyruğa ekle ===
        gonderim_kuyrugu.put({
            "dosya_yolu": dosya_yolu,
            "log_metni": log_metni,
            "sebep": sebep_metni
        })

        # === railway kuyruğuna ekle ===
        sync_queueye_yukleme_ekle(dosya_yolu, log_metni, sebep_metni)

        return is_pdf

    except Exception:
        return False

def diskten_kuyruga_yukle():
    try:
        kayit_klasoru = kayit_klasoru_al()
        if os.path.exists(kayit_klasoru):
            dosyalar = [os.path.join(kayit_klasoru, f) for f in os.listdir(kayit_klasoru) if f.endswith(".png")]
            dosyalar.sort()
            
            for dosya in dosyalar:
                gonderim_kuyrugu.put({
                    "dosya_yolu": dosya,
                    "log_metni": ""
                })
    except Exception:
        pass

# ==================== ARKA PLAN İŞÇİLERİ (THREADS) ====================

def kurye_telegram_gonderici():
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    
    while True:
        try:
            gorev = gonderim_kuyrugu.get()
            dosya_yolu = gorev["dosya_yolu"]
            txt_yolu = dosya_yolu.rsplit('.', 1)[0] + ".txt"

            if os.path.exists(txt_yolu):
                with open(txt_yolu, "r", encoding="utf-8") as f:
                    log_metni = f.read()
            else:
                log_metni = gorev.get("log_metni", "Ekran Goruntusu")

            if not ("BURAYA" in TELEGRAM_TOKEN):
                basarili_mi = False
                
                while not basarili_mi:
                    if not os.path.exists(dosya_yolu): 
                        break
                        
                    try:
                        with open(dosya_yolu, "rb") as foto:
                            cevap = requests.post(url, files={"photo": foto}, data={"chat_id": TELEGRAM_CHAT_ID, "caption": log_metni}, timeout=15)
                            
                        if cevap.status_code == 200:
                            basarili_mi = True
                        elif cevap.status_code == 429:
                            time.sleep(45)
                        else:
                            time.sleep(20)
                    except requests.exceptions.RequestException:
                        time.sleep(20)

                # Dosyalar web galeri icin diskte birakildi
                        
            gonderim_kuyrugu.task_done()
            
        except Exception:
            time.sleep(5)

def telegram_komut_dinleyici():
    global son_update_id
    if "BURAYA" in TELEGRAM_TOKEN: return

    url_updates = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    url_message = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    while True:
        try:
            params = {"offset": son_update_id + 1, "timeout": 10}
            yanit = requests.get(url_updates, params=params, timeout=15).json()
            
            if yanit.get("ok") and yanit.get("result"):
                for update in yanit["result"]:
                    son_update_id = update["update_id"]
                    mesaj = update.get("message", {})
                    metin = mesaj.get("text", "").strip()
                    chat_id = str(mesaj.get("chat", {}).get("id", ""))

                    if chat_id == TELEGRAM_CHAT_ID:
                        # 1. /ss KOMUTU
                        if metin == "/ss":
                            yerel_ss_al_ve_kuyruga_ekle(sebep_metni="MANUEL /SS")
                        
                        # 2. /durum KOMUTU
                        elif metin == "/durum":
                            # Uptime hesaplama (Saat:Dakika:Saniye cinsinden)
                            gecen_sure = int(time.time() - PROGRAM_BASLANGIC_ZAMANI)
                            saat = gecen_sure // 3600
                            dakika = (gecen_sure % 3600) // 60
                            saniye = gecen_sure % 60
                            uptime_metni = f"{saat}s {dakika}d {saniye}s"
                            
                            # Diskte bekleyen dosya sayısını hesaplama
                            try:
                                klasor = kayit_klasoru_al()
                                biriken_dosya_sayisi = len([f for f in os.listdir(klasor) if f.endswith(".png")])
                            except:
                                biriken_dosya_sayisi = 0
                                
                            durum_mesaji = (
                                f"🟢 **Sistem Aktif & Sorunsuz**\n\n"
                                f"⏱ **Kesintisiz Calisma Süresi:** {uptime_metni}\n"
                                f"📦 **Diskte Bekleyen Gorev (Kuyruk):** {biriken_dosya_sayisi} resim\n"
                                f"🖥 **Aktif Pencere:** {aktif_pencere_basligi_al()[:40]}"
                            )
                            
                            # Durum raporunu hafif bir text mesajı olarak Telegram'a gönderiyoruz
                            try:
                                requests.post(url_message, data={"chat_id": TELEGRAM_CHAT_ID, "text": durum_mesaji, "parse_mode": "Markdown"}, timeout=10)
                            except:
                                pass
                                
        except requests.exceptions.RequestException:
             time.sleep(5)
        except Exception:
            pass
        time.sleep(1)

# =======================================================================

def railway_sync_dongusu():
    while True:
        try:
            veri = sync_queue_yukle()

            # 1. Bekleyen yuklemeleri gerceklestir
            basarili_ids = []
            hala_bekleyen = []
            for gorev in veri.get("bekleyen_yuklemeler", []):
                dosya_yolu = gorev["dosya_yolu"]
                if not os.path.exists(dosya_yolu):
                    continue
                sonuc = dosya_yukle_railway(dosya_yolu, gorev.get("log_metni", ""), gorev.get("sebep", "BILINMEYEN"))
                if sonuc:
                    # Yukleme basarili → yerel dosyayi sil
                    try:
                        os.remove(dosya_yolu)
                        txt_yol = dosya_yolu.rsplit(".", 1)[0] + ".txt"
                        if os.path.exists(txt_yol):
                            os.remove(txt_yol)
                    except Exception:
                        pass
                else:
                    hala_bekleyen.append(gorev)

            veri["bekleyen_yuklemeler"] = hala_bekleyen

            # 2. Pending deletions kontrol et
            silinecekler = pending_deletions_kontrol()
            onaylanan_ids = []
            for item in silinecekler:
                dosya_adi = item.get("dosya_adi")
                dosya_id = item.get("id")
                # Yerel dosyayi sil (eğer hala varsa)
                kayit_klasoru = kayit_klasoru_al()
                yol = os.path.join(kayit_klasoru, dosya_adi)
                if os.path.exists(yol):
                    try:
                        os.remove(yol)
                        txt_yol = yol.rsplit(".", 1)[0] + ".txt"
                        if os.path.exists(txt_yol):
                            os.remove(txt_yol)
                    except Exception:
                        pass
                onaylanan_ids.append(dosya_id)

            # 3. Confirm et
            if onaylanan_ids:
                confirm_deletions(onaylanan_ids)

            # 4. Yerel silme kuyrugunu temizle (server tarafinda zaten silindi)
            veri["bekleyen_silmeler"] = []

            sync_queue_kaydet(veri)

        except Exception:
            pass

        time.sleep(30)

def ana_takip_dongusu():
    son_pencere_basligi = aktif_pencere_basligi_al()
    son_kayit_zamani = time.time()
    bekleme_suresi = 5 

    while True:
        try:
            su_anki_pencere = aktif_pencere_basligi_al()
            su_anki_zaman = time.time()
            
            ekranda_pdf_var_mi = pdf_kontrol_et(su_anki_pencere)
            pencere_degisti_mi = su_anki_pencere != son_pencere_basligi
            
            if ekranda_pdf_var_mi:
                bekleme_suresi = 2 
            
            zaman_doldu_mu = (su_anki_zaman - son_kayit_zamani) >= bekleme_suresi

            if pencere_degisti_mi or zaman_doldu_mu:
                sebep = "PENCERE" if pencere_degisti_mi else "SÜRE"
                yerel_ss_al_ve_kuyruga_ekle(sebep_metni=sebep)

                if not ekranda_pdf_var_mi:
                    if pencere_degisti_mi:
                        bekleme_suresi = 5
                    else:
                        bekleme_suresi = 20 

                son_pencere_basligi = su_anki_pencere
                son_kayit_zamani = time.time()

            time.sleep(0.2)
            
        except Exception:
            time.sleep(2)

if __name__ == "__main__":
    diskten_kuyruga_yukle()

    t_kurye = threading.Thread(target=kurye_telegram_gonderici, daemon=True)
    t_kurye.start()
    
    t_dinleyici = threading.Thread(target=telegram_komut_dinleyici, daemon=True)
    t_dinleyici.start()

    t_railway = threading.Thread(target=railway_sync_dongusu, daemon=True)
    t_railway.start()
    
    ana_takip_dongusu()
