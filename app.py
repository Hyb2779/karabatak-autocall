"""
SIP Otomatik Arama Paneli - giris noktasi.

Gercek mantik ayri modullere bolundu:
  constants.py        Sabit dosya yollari / AMI baglanti bilgileri
  extensions.py       Flask app + SocketIO nesneleri
  state.py            Calisma-zamani paylasilan durum (running/paused/vs.)
  logger.py           Panel log akisi
  settings_store.py   settings.json / results.json okuma-yazma
  auth.py             Giris/kimlik dogrulama
  asterisk_config.py  Asterisk sip.conf otomatik guncelleme
  audio.py            Ses dosyasi donusumu (ffmpeg)
  ami_client.py        Asterisk Manager Interface istemcisi
  call_engine.py       Ana arama motoru (eszamanli worker havuzu)
  routes.py            Tum HTTP route'lari

Bu dosya sadece bunlari bir araya getirip sunucuyu ayaga kaldirir.
"""
from extensions import app, socketio

# routes.py, @app.route dekoratorleriyle route'lari 'app' uzerine kaydeder.
# Import edilmesi yeterli, ayrica bir seye ihtiyac yok.
import routes  # noqa: F401,E402

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
