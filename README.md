# Ev ilanı takip botu 🏠

Alanya (Konaklı, Payallar, merkez) — 2M–3.8M TL, min 50 m², bina yaşı ≤10,
zemin ve 1. kat hariç. Yeni ilan çıkınca Telegram'a bildirim gelir.

## Kurulum

1. Telegram'da kendi botuna bir mesaj at (ör. "merhaba") — bot chat ID'ni buradan otomatik bulur.
2. Repo → **Settings › Secrets and variables › Actions › New repository secret**
   - Ad: `TELEGRAM_BOT_TOKEN` · Değer: BotFather'ın verdiği token
3. **Actions** sekmesi → "Ev ilanı kontrol" → **Run workflow**.
   İlk çalışmada mevcut ilanlar kaydedilir ve "✅ ... izlemeye başladı" mesajı gelir.
   Sonrasında her 20 dakikada sadece **yeni** ilanlar gelir.

Arama linkleri `config.yaml` içinde hazır (Emlakjet, Hepsiemlak, Sahibinden).

## Notlar
- Bir site 3 kez üst üste okunamazsa Telegram'a ⚠️ uyarı gelir.
  Sahibinden GitHub sunucularını sık engeller; olursa o kısmı kendi Mac'inde çalıştırabiliriz.
- Kriterleri değiştirmek için `config.yaml`'ı düzenlemen yeterli.
- Test: `TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python bot.py test`
