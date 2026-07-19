# SIP Otomatik Arama Sistemi

## Kurulum

```bash
cd autocall
pip install -r requirements.txt
```

MP3 dosyası kullanacaksan **ffmpeg** de gerekli:
- Windows: https://ffmpeg.org/download.html → PATH'e ekle
- Linux: `sudo apt install ffmpeg`

## Yapılandırma

`config.py` dosyasını aç ve şu alanları doldur:

```python
SIP_SERVER   = "sip.provider.com"   # SIP sunucun
SIP_USERNAME = "1001"               # Kullanıcı adın
SIP_PASSWORD = "sifren"             # Şifren

NUMBERS_TO_CALL = [
    "905xxxxxxxxx",   # Aranacak numaralar
    "905yyyyyyyyy",
]

AUDIO_FILE = "ses.wav"   # WAV veya MP3 dosyan (autocall/ klasörüne koy)

DELAY_BETWEEN_CALLS = 5   # Aramalar arası bekleme (saniye)
WAIT_BEFORE_AUDIO   = 2   # Cevap sonrası ses başlamadan bekleme (saniye)
RING_TIMEOUT        = 30  # Cevap vermezse bu kadar sonra iptal (saniye)
```

## Çalıştırma

```bash
python autocall.py
```

## Dosya Yapısı

```
autocall/
├── autocall.py       # Ana program
├── config.py         # Ayarlar
├── requirements.txt  # Bağımlılıklar
├── ses.wav           # Ses dosyan (buraya koy)
└── README.md
```

---

## Not (18.07.2026)

Tek hat / sıralı arama sorunu tespit edilip çözüldü: `app.py` çoklu SIP hesabı
(round-robin) ve eşzamanlı worker-thread mimarisine (concurrency=60) geçirildi.
Test sonucu: iki hat üzerinden 60 eşzamanlı kanal sorunsuz açıldı.

Altyapı deneyimi NCS (Nitro Core Systems) çalışmalarından geldi. 🎯
