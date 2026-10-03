# Публікація FozPay на Hostinger (домен fozpay.online)

FozPay складається з трьох частин:

- **Backend** — FastAPI (Python), слухає порт `8001`
- **Frontend** — React (статична збірка `build/`)
- **База даних** — MongoDB

> ⚠️ **Важливо:** звичайний *shared*-хостинг Hostinger (тарифи Web/Premium/Business)
> **НЕ підходить** — там не можна запустити Python-процес і MongoDB.
> Потрібен **Hostinger VPS** (план KVM 2 і вище, мін. 2 ГБ RAM).
> Нижче — покрокова інструкція для **VPS з Ubuntu 22.04/24.04**.

---

## 0. Що знадобиться

- VPS Hostinger (Ubuntu 22.04), root-доступ по SSH
- Домен **fozpay.online**, A-запис якого вказує на IP вашого VPS
- Ключі інфраструктури: `ALCHEMY_KEY`, `TRONGRID_KEY`, `ONEINCH_KEY`
- **Сід-фразу гарячого гаманця вводити в `.env` НЕ треба** — її ви задасте
  після запуску прямо в адмінці (вона одразу зашифрується й збережеться в БД).

---

## 1. Домен fozpay.online → ваш VPS

1. У hPanel → **VPS** дізнайтесь публічний IP сервера.
2. У hPanel → **Домени → fozpay.online → DNS / Nameservers → Керувати DNS-записами**
   створіть/оновіть записи типу **A**:
   - `@`   → `IP_ВАШОГО_VPS`
   - `www` → `IP_ВАШОГО_VPS`
3. Зачекайте поширення DNS (зазвичай кілька хвилин, інколи до кількох годин).
   Перевірити: `ping fozpay.online` має віддавати IP вашого VPS.

## 2. Створення VPS і вхід по SSH

1. hPanel → **VPS → Створити** → план (мін. KVM 2, 2 ГБ RAM) → ОС **Ubuntu 22.04**.
2. Задайте root-пароль, дочекайтесь створення.
3. Підключіться:
   ```bash
   ssh root@IP_ВАШОГО_VPS
   ```

## 3. Базове ПЗ

```bash
apt update && apt upgrade -y
apt install -y git curl build-essential nginx
# Node.js 20 + yarn
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
npm install -g yarn
# Python 3.11
apt install -y python3 python3-pip python3-venv
```

## 4. MongoDB 7

```bash
curl -fsSL https://pgp.mongodb.com/server-7.0.asc | gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" > /etc/apt/sources.list.d/mongodb-org-7.0.list
apt update && apt install -y mongodb-org
systemctl enable --now mongod
systemctl status mongod   # має бути active (running)
```

## 5. Клонування коду

```bash
cd /opt
git clone https://github.com/maksymhumfk-commits/maks0707.git fozpay
cd fozpay
```

## 6. Backend (FastAPI)

```bash
cd /opt/fozpay/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 6.1 Згенеруйте секрети (на сервері)

```bash
python3 -c "import secrets; print('JWT_SECRET=' + secrets.token_hex(32))"
python3 -c "from cryptography.fernet import Fernet; print('MNEMONIC_ENC_KEY=' + Fernet.generate_key().decode())"
```

### 6.2 Створіть файл `/opt/fozpay/backend/.env`

```env
MONGO_URL="mongodb://localhost:27017"
DB_NAME="fozpay"
CORS_ORIGINS="https://fozpay.online,https://www.fozpay.online"
JWT_SECRET="<встав JWT_SECRET з кроку 6.1>"
MNEMONIC_ENC_KEY="<встав MNEMONIC_ENC_KEY з кроку 6.1>"
ADMIN_EMAIL="psymaks249@gmail.com"
ADMIN_PASSWORD="<надійний пароль адміна>"
FRONTEND_URL="https://fozpay.online"
ALCHEMY_KEY="alch_y1NyKVcAxqO7cBtqerlhc"
TRONGRID_KEY="88d466c5-cf5f-4eba-bec6-ef2ecc6caea9"
ONEINCH_KEY="TBLE2I9vfvUsAajjGRbI1sekv04MiflI"
```

> 🔐 **Про сід-фразу гарячого гаманця (найважливіше):**
> - **НЕ додавайте** `WALLET_MNEMONIC` у `.env`. Сід зберігається **зашифрованим
>   у базі** (AES/Fernet), а розшифрувати його можна лише ключем `MNEMONIC_ENC_KEY`,
>   який лежить тільки в цьому `.env`. Тож навіть повний дамп MongoDB **не дає**
>   зловмиснику доступу до гаманця без файлу `.env` сервера.
> - На першому запуску система згенерує тимчасовий сід (теж зашифрований).
>   Свій сід ви введете **після деплою** в адмінці (крок 10).
> - 🧷 **Зробіть резервну копію `MNEMONIC_ENC_KEY`** у надійному місці.
>   Якщо втратите цей ключ — зашифрований сід у БД стане **неможливо** розшифрувати,
>   і доступ до коштів гарячого гаманця буде втрачено.

### 6.3 Запуск як сервіс (systemd)

Створіть `/etc/systemd/system/fozpay-api.service`:

```ini
[Unit]
Description=FozPay API
After=network.target mongod.service

[Service]
WorkingDirectory=/opt/fozpay/backend
Environment=PATH=/opt/fozpay/backend/venv/bin
ExecStart=/opt/fozpay/backend/venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now fozpay-api
systemctl status fozpay-api        # active (running)
curl http://localhost:8001/api/    # {"message":"FozPay clone API","status":true}
```

## 7. Frontend (React)

```bash
cd /opt/fozpay/frontend
echo 'REACT_APP_BACKEND_URL=https://fozpay.online' > .env
yarn install
yarn build          # створить теку build/
```

Статику віддаватиме nginx із `/opt/fozpay/frontend/build`.

## 8. Nginx (reverse proxy + статика)

Створіть `/etc/nginx/sites-available/fozpay`:

```nginx
server {
    listen 80;
    server_name fozpay.online www.fozpay.online;

    # API → FastAPI
    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # React SPA
    root /opt/fozpay/frontend/build;
    index index.html;
    location / {
        try_files $uri /index.html;
    }
}
```

```bash
ln -s /etc/nginx/sites-available/fozpay /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

## 9. HTTPS (безкоштовний сертифікат Let's Encrypt)

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d fozpay.online -d www.fozpay.online
```

Certbot сам додасть 443 і перенаправлення з http на https. Сертифікат оновлюється автоматично.

> Після HTTPS переконайтесь, що в обох `.env` використано `https://fozpay.online`
> (а не http), інакше cookie-авторизація не працюватиме. Після зміни `.env`
> перезапустіть бекенд: `systemctl restart fozpay-api`.

## 10. Перша перевірка і введення власної сід-фрази

1. Відкрийте `https://fozpay.online` — має з'явитись головна сторінка FozPay.
2. Натисніть **Увійти** → увійдіть як адмін (`ADMIN_EMAIL` / `ADMIN_PASSWORD`).
3. (Рекомендовано) **Налаштування → Безпека** → увімкніть **2FA** для адміна.
4. Перейдіть у **Налаштування → Гарячий гаманець → блок «Безпека сід-фрази»**:
   - ви побачите позначку **«Зашифровано в БД ✓»** і попередження
     **«Згенеровано системою — замініть своїм»**;
   - натисніть **«Ввести свою сід-фразу»**, вставте свою BIP-39 фразу (12/24 слова),
     за потреби введіть код 2FA, і натисніть **«Зберегти (зашифрувати)»**;
   - сід одразу шифрується ключем `MNEMONIC_ENC_KEY` і зберігається в БД у полі
     `mnemonic_enc`; у відкритому вигляді він **ніде** не зберігається й не показується.
   - Після збереження адреси гарячого гаманця зміняться на похідні від вашого сіду.
5. У **Налаштування → Платформа** перевірте комісії (за замовчуванням 0).

> ✅ Саме завдяки цьому «не критично» отримати доступ до самого сервера/бази:
> без `MNEMONIC_ENC_KEY` з `.env` сід у БД — просто нечитабельний шифротекст.

## 11. Оновлення коду в майбутньому

```bash
cd /opt/fozpay && git pull
# backend
cd backend && source venv/bin/activate && pip install -r requirements.txt && systemctl restart fozpay-api
# frontend
cd ../frontend && yarn install && yarn build && systemctl reload nginx
```

---

### Резервне копіювання (важливо)

- **`/opt/fozpay/backend/.env`** — містить `MNEMONIC_ENC_KEY` (ключ до сіду) і `JWT_SECRET`.
  Зберігайте копію в надійному місці (менеджер паролів / офлайн).
- **Дамп MongoDB**: `mongodump --db fozpay --out /root/backup-$(date +%F)`.
  Сам дамп без `.env` **не** розкриває сід — це і є суть захисту.

### Часті проблеми

- **502 Bad Gateway** → бекенд не запущено: `systemctl status fozpay-api`, логи `journalctl -u fozpay-api -n 50`.
- **Сторінка входу не логінить (cookie)** → перевірте, що домен під HTTPS і що `FRONTEND_URL` (backend) та `REACT_APP_BACKEND_URL` (frontend) — обидва `https://fozpay.online`.
- **MongoDB не стартує** → `journalctl -u mongod -n 50`; перевірте вільне місце на диску.
- **«Некоректна сід-фраза (BIP-39)»** при збереженні → перевірте порядок слів і контрольну суму (12/15/18/21/24 слова з офіційного списку BIP-39).
- **Адреси гаманця «скинулись»** → ви не зберегли свій сід в адмінці, або було видалено документ `system/_id=wallet` у БД.
