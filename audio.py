"""Yuklenen ses dosyasini (MP3/WAV) Asterisk'in bekledigi
8000Hz mono alaw formatina donusturur."""
import os
import shutil
import subprocess

from constants import ASTERISK_SOUND, UPLOAD_FOLDER
from logger import log


def prepare_audio(filepath):
    """MP3/WAV -> 8000Hz mono alaw -> Asterisk ses dizinine kopyala"""
    try:
        # Once WAV'a cevir
        wav_tmp = os.path.join(UPLOAD_FOLDER, "tmp_conv.wav")
        subprocess.run([
            "ffmpeg", "-i", filepath,
            "-ar", "8000", "-ac", "1",
            "-acodec", "pcm_s16le",
            wav_tmp, "-y"
        ], check=True, capture_output=True)

        # Sonra alaw'a cevir
        subprocess.run([
            "ffmpeg", "-i", wav_tmp,
            "-ar", "8000", "-ac", "1",
            "-f", "alaw",
            ASTERISK_SOUND, "-y"
        ], check=True, capture_output=True)

        # Izinleri ayarla
        os.chmod(ASTERISK_SOUND, 0o644)
        try:
            shutil.chown(ASTERISK_SOUND, "asterisk", "asterisk")
        except Exception:
            pass

        # Temizle
        if os.path.exists(wav_tmp):
            os.unlink(wav_tmp)

        log(f"Ses hazırlandı: {ASTERISK_SOUND}", "success")
        return True
    except Exception as e:
        log(f"Ses dönüşüm hatası: {e}", "error")
        return False
