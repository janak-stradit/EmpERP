# Enterprise Production Deployment Guide: Stradit Workforce ERP

This guide provides step-by-step instructions for deploying **Stradit Workforce ERP** to production environments, including Docker containerization, AWS cloud infrastructure setup, Nginx reverse proxy configuration, SSL certificates, database migrations, and CI/CD pipelines.

---

## Architecture Overview

```
                          [ Client Browsers / Mobile ]
                                       │
                                   (HTTPS :443)
                                       ▼
                       [ Nginx Reverse Proxy + SSL Certbot ]
                                       │
                                   (HTTP :8000)
                                       ▼
                    [ Gunicorn / Uvicorn (4 Workers) ]
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
     [ PostgreSQL Database (RDS / Docker) ]     [ Local / S3 Document Store ]
```

---

## 1. Prerequisites & Environment Setup

### Required System Dependencies
- **Docker** 24.0+ and **Docker Compose** 2.20+
- **Python** 3.12+ (for local/bare-metal deployment)
- **PostgreSQL** 16+
- **Nginx** & **Certbot** (for SSL termination)

### Production Environment Variables (`.env`)

Create a `.env` file in the project root directory:

```ini
# Production Environment Configuration
ENVIRONMENT=production
DEBUG=false

# Core Application Security
SECRET_KEY=generate-a-strong-64-character-random-hex-string
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480

# Database Configuration (PostgreSQL)
DATABASE_URL=postgresql+psycopg://emperp_user:YourSecurePassword123!@db:5432/emperp_db

# CORS Configuration (Set to your exact domain name)
CORS_ORIGINS=https://erp.yourcompany.com,https://app.yourcompany.com

# File Upload Settings
UPLOAD_DIR=/app/uploads
MAX_UPLOAD_SIZE_MB=10
```

---

## 2. Docker Deployment (Recommended)

### Local & Production Launch with Docker Compose

1. **Build and start all services**:
   ```bash
   docker compose up -d --build
   ```

2. **Verify running containers**:
   ```bash
   docker compose ps
   ```

3. **Run Alembic Database Migrations**:
   ```bash
   docker compose exec app alembic upgrade head
   ```

4. **Verify Application Health**:
   ```bash
   curl http://localhost:8000/health
   # Expected Output: {"status":"healthy","service":"Stradit Workforce ERP"}
   ```

5. **Stop containers**:
   ```bash
   docker compose down
   ```

---

## 3. Cost-Optimized AWS Cloud Architecture

For an enterprise internal ERP serving 50–500 employees, the following cost-optimized AWS setup provides high reliability and security while minimizing costs (~$20–$35/month):

| Service | Architecture Choice | Why This Setup | Monthly Cost (Est.) |
|---|---|---|---|
| **Compute** | 1x EC2 `t4g.small` (ARM / Graviton3), Ubuntu 24.04 LTS | ARM architecture offers 20% better performance per dollar than x86. Nginx + Docker Compose on-box. | ~$8 – $12 |
| **Database** | AWS RDS PostgreSQL `db.t4g.micro`, 20GB gp3 storage | Managed automated backups, point-in-time recovery, zero maintenance overhead. | ~$12 – $15 |
| **Storage** | AWS S3 Bucket (`emperp-documents-prod`) | Secure, durable document storage with Lifecycle policies to Glacier after 90 days. | < $1.00 |
| **Secrets** | AWS SSM Parameter Store (`SecureString`) | Free secure parameter storage (saves $0.40/secret/month vs Secrets Manager). | Free |
| **DNS & SSL** | Route 53 Hosted Zone + Certbot / Let's Encrypt | Automated free SSL certificates via Certbot cron on Nginx box. | ~$0.50 |

---

## 4. Nginx Reverse Proxy & SSL Setup

Create `/etc/nginx/sites-available/emperp.conf`:

```nginx
server {
    listen 80;
    server_name erp.yourcompany.com;

    # Redirect HTTP to HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name erp.yourcompany.com;

    ssl_certificate /etc/letsencrypt/live/erp.yourcompany.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/erp.yourcompany.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Security Headers
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "same-origin" always;

    # Client Upload Limit (10MB)
    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Static assets caching
    location /static/ {
        proxy_pass http://127.0.0.1:8000/static/;
        expires 7d;
        add_header Cache-Control "public, no-transform";
    }
}
```

### Enable Nginx site and obtain SSL Certificate:
```bash
sudo ln -s /etc/nginx/sites-available/emperp.conf /etc/nginx/sites-enabled/
sudo certbot --nginx -d erp.yourcompany.com
sudo systemctl reload nginx
```

---

## 5. CI/CD Pipeline (GitHub Actions)

### Continuous Integration (`.github/workflows/ci.yml`)
- Triggers on PRs and pushes to `main`.
- Launches a live PostgreSQL 16 container service.
- Runs `ruff check .` for code quality.
- Runs `pytest` test suite against the live test database.

### Continuous Deployment (`.github/workflows/deploy.yml`)
- Triggers automatically when code is merged into `main`.
- Builds the multi-stage production Docker image.
- Performs automated database migrations (`alembic upgrade head`).
- Restarts the container stack seamlessly with zero downtime.

---

## 6. Database Backups & Maintenance

### Automated Daily PostgreSQL Backup Script
Create `/usr/local/bin/emperp-db-backup.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/emperp"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
CONTAINER_NAME="emperp_db"
DB_USER="emperp_user"
DB_NAME="emperp_db"

mkdir -p $BACKUP_DIR
docker exec -t $CONTAINER_NAME pg_dump -U $DB_USER $DB_NAME | gzip > "$BACKUP_DIR/emperp_backup_$TIMESTAMP.sql.gz"

# Retain backups for 30 days
find $BACKUP_DIR -type f -name "*.sql.gz" -mtime +30 -delete
echo "Database backup completed: emperp_backup_$TIMESTAMP.sql.gz"
```

Make executable and schedule in crontab (`crontab -e`):
```cron
0 2 * * * /usr/local/bin/emperp-db-backup.sh >> /var/log/emperp-backup.log 2>&1
```

---

## 7. Verification Checklist

- [x] Dockerfile multi-stage build tested.
- [x] `docker-compose.yml` service orchestration verified.
- [x] `.github/workflows/ci.yml` linting & test suite configured.
- [x] `.github/workflows/deploy.yml` CD pipeline configured.
- [x] `/health` endpoint responsive.
- [x] Nginx reverse proxy & Let's Encrypt SSL instructions documented.
- [x] Database migration and backup procedures established.
