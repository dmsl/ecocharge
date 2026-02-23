#!/usr/bin/env bash
set -euo pipefail

#############################################
# EcoChargePlus - Apache + mod_wsgi + Certbot
# + idempotent vhosts + cron jobs (Ubuntu)
#############################################

# --------- CONFIG (edit if needed) ----------
DOMAIN="ecochargeplus.cs.ucy.ac.cy"
APP_DIR="/var/www/ecochargeplus"
VENV_DIR="${APP_DIR}/venv"                 # change to "${APP_DIR}/.venv" if you use .venv
WSGI_FILE="${APP_DIR}/ecocharge.wsgi"
APACHE_SITE="ecochargeplus"
APACHE_CONF="/etc/apache2/sites-available/${APACHE_SITE}.conf"
EMAIL=""                                   # optional: set your email for non-interactive Let's Encrypt
DB_PATH="${APP_DIR}/.data/MicroGrid.db"    # adjust if your app uses a different DB path
# -------------------------------------------

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Please run as root: sudo $0"
    exit 1
  fi
}

apache_reload_or_restart() {
  if systemctl is-active --quiet apache2; then
    systemctl reload apache2 || systemctl restart apache2
  else
    systemctl restart apache2
  fi
}

need_root

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y apache2 libapache2-mod-wsgi-py3 python3 python3-venv python3-pip \
  certbot python3-certbot-apache ssl-cert

echo "==> Enabling required Apache modules"
a2enmod wsgi ssl headers rewrite >/dev/null || true

echo "==> Creating/validating WSGI file"
if [[ ! -f "${WSGI_FILE}" ]]; then
  cat > "${WSGI_FILE}" <<EOF
import sys
import os

BASE_DIR = "${APP_DIR}"
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

os.environ.setdefault("FLASK_ENV", "production")

from app import app as application
EOF
fi

echo "==> Ensuring Python venv exists and dependencies are installed"
if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
if [[ -f "${APP_DIR}/requirements.txt" ]]; then
  "${VENV_DIR}/bin/python" -m pip install -r "${APP_DIR}/requirements.txt"
else
  "${VENV_DIR}/bin/python" -m pip install flask
fi

PYTHON_BIN="${VENV_DIR}/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="/usr/bin/python3"
fi

echo "==> Writing Apache vhost: ${APACHE_CONF}"
cat > "${APACHE_CONF}" <<EOF
# Auto-managed by EcoChargePlus setup script

WSGIDaemonProcess ${APACHE_SITE} \\
    python-home=${VENV_DIR} \\
    python-path=${APP_DIR}

WSGIProcessGroup ${APACHE_SITE}

<VirtualHost *:80>
    ServerName ${DOMAIN}
    Redirect permanent / https://${DOMAIN}/
</VirtualHost>

<VirtualHost *:443>
    ServerName ${DOMAIN}

    SSLEngine on
    # These files are created by Certbot. If not present yet, Apache would fail unless we temporarily swap to snakeoil.
    SSLCertificateFile /etc/letsencrypt/live/${DOMAIN}/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/${DOMAIN}/privkey.pem
    Include /etc/letsencrypt/options-ssl-apache.conf

    WSGIScriptAlias / ${WSGI_FILE}

    <Directory ${APP_DIR}>
        Require all granted
    </Directory>

    Alias /static/ ${APP_DIR}/static/
    <Directory ${APP_DIR}/static>
        Require all granted
    </Directory>

    ErrorLog \${APACHE_LOG_DIR}/${APACHE_SITE}_ssl_error.log
    CustomLog \${APACHE_LOG_DIR}/${APACHE_SITE}_ssl_access.log combined
</VirtualHost>
EOF

echo "==> Enabling site and disabling default (safe to re-run)"
a2ensite "${APACHE_SITE}.conf" >/dev/null || true
a2dissite 000-default.conf >/dev/null 2>&1 || true

echo "==> Ensuring DB and data directory are writable for SQLite WAL (if present)"
DB_DIR="$(dirname "${DB_PATH}")"
mkdir -p "${DB_DIR}"
chown -R www-data:www-data "${DB_DIR}" || true
chmod 775 "${DB_DIR}" || true
if [[ -f "${DB_PATH}" ]]; then
  chown www-data:www-data "${DB_PATH}" || true
  chmod 664 "${DB_PATH}" || true
  rm -f "${DB_PATH}-wal" "${DB_PATH}-shm" || true
fi

echo "==> If cert doesn't exist yet, temporarily use snakeoil so Apache can start"
if [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]] || [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/privkey.pem" ]]; then
  sed -i \
    -e "s#SSLCertificateFile /etc/letsencrypt/live/${DOMAIN}/fullchain.pem#SSLCertificateFile /etc/ssl/certs/ssl-cert-snakeoil.pem#g" \
    -e "s#SSLCertificateKeyFile /etc/letsencrypt/live/${DOMAIN}/privkey.pem#SSLCertificateKeyFile /etc/ssl/private/ssl-cert-snakeoil.key#g" \
    "${APACHE_CONF}"
fi

echo "==> Testing Apache config"
apache2ctl configtest

echo "==> Restarting Apache"
apache_reload_or_restart

echo "==> Obtaining/Installing Let's Encrypt certificate (if needed)"
if [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]] || [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/privkey.pem" ]]; then
  if [[ -n "${EMAIL}" ]]; then
    certbot --apache -d "${DOMAIN}" --non-interactive --agree-tos -m "${EMAIL}" || true
  else
    certbot --apache -d "${DOMAIN}" || true
  fi

  # Restore vhost to LE paths if cert exists now
  if [[ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]] && [[ -f "/etc/letsencrypt/live/${DOMAIN}/privkey.pem" ]]; then
    sed -i \
      -e "s#SSLCertificateFile /etc/ssl/certs/ssl-cert-snakeoil.pem#SSLCertificateFile /etc/letsencrypt/live/${DOMAIN}/fullchain.pem#g" \
      -e "s#SSLCertificateKeyFile /etc/ssl/private/ssl-cert-snakeoil.key#SSLCertificateKeyFile /etc/letsencrypt/live/${DOMAIN}/privkey.pem#g" \
      "${APACHE_CONF}"
    apache2ctl configtest
    apache_reload_or_restart
  else
    echo "WARNING: Certbot did not create a cert. Check DNS/ports and /var/log/letsencrypt/letsencrypt.log"
  fi
else
  echo "==> Let's Encrypt certificate already present for ${DOMAIN}"
fi

echo "==> Certbot renewal check (dry run)"
systemctl enable --now certbot.timer >/dev/null 2>&1 || true
certbot renew --dry-run || true

#############################################
# Cron jobs (idempotent) - MAIN install file
#############################################
echo "==> Setting up application cron jobs (idempotent)"

CRON_FILE="/etc/cron.d/ecochargeplus"
CRON_LOG_DIR="${APP_DIR}/logs"

mkdir -p "${CRON_LOG_DIR}"
chown -R www-data:www-data "${CRON_LOG_DIR}" || true
chmod 775 "${CRON_LOG_DIR}"

# Tidied schedules:
# - weather: top of every hour
# - forecast fetch: top of every 3 hours (NOT every minute)
# - solar production: top of every hour
cat > "${CRON_FILE}" <<EOF
# ================================
# EcoChargePlus Automated Cron Jobs
# Managed by setup script (rerunnable)
# ================================

SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Update real-time weather for each charger every hour
0 * * * * www-data ${PYTHON_BIN} ${APP_DIR}/update_weather.py >> ${CRON_LOG_DIR}/update_weather.log 2>&1

# Fetch daily 5-day/3-hour forecasts every 3 hours and log output
0 */3 * * * www-data DATABASE_FILE=${DB_PATH} ${PYTHON_BIN} ${APP_DIR}/daily_forecast_fetcher.py >> ${CRON_LOG_DIR}/daily_forecast.log 2>&1

# Save actual solar production for each microgrid once every hour
0 * * * * www-data DATABASE_FILE=${DB_PATH} ${PYTHON_BIN} ${APP_DIR}/save_actual_production.py >> ${CRON_LOG_DIR}/solar_production.log 2>&1
EOF

chmod 644 "${CRON_FILE}"
systemctl reload cron || systemctl restart cron

echo
echo "✅ Done."
echo "Site: https://${DOMAIN}"
echo "Apache logs:"
echo "  /var/log/apache2/${APACHE_SITE}_ssl_error.log"
echo "  /var/log/apache2/${APACHE_SITE}_ssl_access.log"
echo "Cron file: ${CRON_FILE}"
echo "Cron logs: ${CRON_LOG_DIR}/"

