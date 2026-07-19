#!/bin/bash
# Ubuntu sunucuya kurulum scripti
# Çalıştırma: bash deploy.sh

set -e

echo "=== SIP Otomatik Arama - Kurulum ==="

# Güncelle ve gerekli paketleri kur
sudo apt update
sudo apt install -y python3 python3-pip python3-venv ffmpeg

# Proje klasörü
APP_DIR="/opt/autocall"
sudo mkdir -p $APP_DIR
sudo cp -r . $APP_DIR
sudo chown -R $USER:$USER $APP_DIR

cd $APP_DIR

# Virtual environment
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# uploads klasörü
mkdir -p uploads

# Systemd servis dosyasını kopyala
sudo cp autocall.service /etc/systemd/system/autocall.service

# Servisi etkinleştir ve başlat
sudo systemctl daemon-reload
sudo systemctl enable autocall
sudo systemctl start autocall

# 5000 portunu aç
sudo ufw allow 5000/tcp 2>/dev/null || true

echo ""
echo "=== Kurulum tamamlandı ==="
echo "Panel: http://$(curl -s ifconfig.me):5000"
echo ""
echo "Servis durumu: sudo systemctl status autocall"
echo "Loglar:        sudo journalctl -u autocall -f"
