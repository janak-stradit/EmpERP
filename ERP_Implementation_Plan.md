# Employee ERP System — Phase-wise Implementation Plan

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend API | Python 3.11+ FastAPI |
| Database | PostgreSQL 15+ |
| Frontend | Bootstrap 5 + jQuery 3.7 |
| Auth & 2FA | PyOTP + TOTP (Google Authenticator / Authy compatible) |
| ORM | SQLAlchemy 2.0 + Alembic |
| Deployment | AWS EC2 (t3.micro / t3.small) + Nginx + Gunicorn + Uvicorn |
| File Storage | Local filesystem (mounted EBS) or S3 (optional Phase 4) |
| SSL | Let's Encrypt (Certbot) |
| Process Manager | systemd + Supervisor |

---

## User Roles & Hierarchy

| Role | Description |
|------|-------------|
| **Super Admin** | Full system access, tenant/company management, global settings |
| **Admin** | Company-level admin, user management, policy configuration |
| **HR** | Employee onboarding, leave approvals, KRA/PMS reviews, document verification |
| **Employee** | Self-service portal — apply leave, view KRA, upload documents, mark attendance |

---

## Module Overview

1. **Authentication & Authorization** — JWT + RBAC + 2FA/MFA
2. **Leave Management** — Leave types, balance tracking, approval workflow, calendar view
3. **KRA (Key Result Areas)** — Goal setting, weightage, periodic review cycles
4. **Performance Management System (PMS)** — Appraisal cycles, 360° feedback, rating scales, normalization
5. **Onboarding** — Checklists, task assignments, document collection, progress tracking
6. **Employee Documents** — Upload, categorize, expiry alerts, access control
7. **Time, Attendance & Leave** — Clock-in/out, timesheets, attendance reports, shift mapping

---

## Non-Functional Requirements (Enterprise Hardening Baseline)

These apply across all phases, not just Phase 1. Scope: single-company deployment, hardened to production/enterprise standards — not multi-tenant SaaS isolation (the `companies` table exists structurally for future-proofing, but no cross-tenant isolation logic is required now).

### Security Baseline
- **Password storage**: bcrypt, cost factor 12, via the `bcrypt` library directly (not `passlib`, which is unmaintained and breaks on modern `bcrypt` releases).
- **Transport & secrets**: TLS everywhere in production (Let's Encrypt, Phase 6); secrets loaded from `.env` locally via `pydantic-settings`, never committed; upgrade path to AWS Secrets Manager / SSM Parameter Store noted for the AWS phase.
- **Encryption at rest**: TOTP secrets encrypted with Fernet (symmetric, key in `.env`/secrets manager); document a key-rotation procedure (re-encrypt on rotation, keep previous key available during a grace window).
- **AuthN/AuthZ**: JWT access (15 min) + refresh (7 days, hashed at rest in `refresh_tokens`), RBAC enforced via a `require_role()` dependency reading the role claim. HS256 is sufficient for a single-process API; document upgrade to RS256/JWKS if the API is ever split into multiple services that need to verify tokens without sharing the signing secret.
- **Account lockout**: 5 failed attempts per IP per 15 minutes (via `login_attempts`), returns HTTP 429; every attempt (success/fail) is recorded.
- **Audit immutability**: `audit_logs` rows are append-only at the application layer (no update/delete endpoints exposed) and, in production, the DB application role should be granted `INSERT`/`SELECT` only on `audit_logs` (no `UPDATE`/`DELETE`) so a compromised app credential cannot tamper with history.
- **Input validation & injection defense**: Pydantic schemas validate all request bodies; SQLAlchemy ORM/parameterized queries throughout — no raw string-interpolated SQL; Jinja2 auto-escaping + CSP headers for XSS; CSRF protection on state-changing HTML-form endpoints.
- **Headers & CORS**: HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, a baseline CSP; CORS origins restricted via `.env` (defaults to `localhost` in dev).
- **Rate limiting**: applied to authentication endpoints at minimum; broaden to other write-heavy endpoints if abuse is observed.

### Data Protection & Retention
- **Backups**: daily automated `pg_dump` (Phase 6 automates this; locally, a manual/scripted dump is sufficient for dev). Target RPO ≤ 24h, RTO ≤ 4h once on AWS.
- **PII handling**: employee PII (bank details, ID documents) treated as sensitive — access logged via `audit_logs`, file downloads access-controlled by role/ownership.
- **Retention**: soft-delete (`deleted_at`) on major entities rather than hard delete, so records remain available for audit/restore within a defined retention window (policy to be finalized with the business — default proposal: 3 years post-termination for employee records, unless legally required longer).

### Testing & Quality
- **Test strategy**: unit tests for security/business logic (hashing, TOTP, JWT, leave/KRA calculations), integration tests for API flows against a real Postgres instance (not mocked), target ≥ 70% coverage on `app/` by Phase 3.
- **Linting**: `ruff` for style/lint consistency.
- **CI outline** (to formalize once a git remote exists): lint → unit+integration tests → build → (later) deploy on merge to main.

### Observability & Operations
- **Logging**: structured (JSON) application logs; no secrets/PII in logs.
- **Health checks**: `/health` (liveness, no auth) now; `/ready` (checks DB connectivity) added once background jobs (accrual cron, etc.) exist.
- **Environment strategy**: `.env` per environment (dev/staging/prod), never shared between them; `DATABASE_URL` and all secrets injected via environment, not hardcoded.

### Performance & Scalability Targets
- API p95 response time < 300ms for CRUD endpoints under expected single-company load (< 500 employees, < 50 concurrent users).
- Scale-up path: t3.micro → t3.small → add read replica / Redis caching only if concurrency or reporting load demands it (avoid premature infrastructure).

---

## Phase 1: Foundation & Auth (Weeks 1–3)

### Goal
Establish project skeleton, database schema foundation, and secure authentication with 2FA.

### Deliverables
- FastAPI project structure with layered architecture (API → Service → Repository → Model)
- PostgreSQL database setup with initial schema
- User model with role-based fields
- JWT-based login/logout with access + refresh tokens
- TOTP-based 2FA (QR code setup, verify, backup codes)
- Password hashing (bcrypt), rate limiting on auth endpoints
- Bootstrap + jQuery login page with 2FA step
- Super Admin seed script
- EC2 provisioning guide (t3.micro, Ubuntu 22.04 LTS)
- Nginx reverse proxy + SSL (Let's Encrypt)
- systemd service for FastAPI app

### Database Tables (Phase 1)
- `users` — id, email, password_hash, full_name, role, is_active, is_2fa_enabled, totp_secret, created_at, updated_at
- `login_attempts` — id, user_id, ip_address, attempted_at, success
- `refresh_tokens` — id, user_id, token_hash, expires_at, revoked
- `companies` — id, name, domain, settings_json, created_at (for multi-tenancy prep)
- `audit_logs` — id, user_id, action, entity_type, entity_id, timestamp, ip_address

### Key Decisions
- Use **PyOTP** for TOTP generation; compatible with Google Authenticator
- Store TOTP secrets encrypted at rest (Fernet from cryptography library); rotate the Fernet key by re-encrypting stored secrets during a maintenance window, keeping the previous key available until rotation completes
- Rate limit: 5 attempts per IP per 15 minutes on login (429 on exceed), backed by the `login_attempts` table — no Redis dependency needed at this scale
- JWT access token expiry: 15 minutes; refresh token: 7 days; algorithm **HS256** (single-process API); revisit RS256/JWKS only if the API is split into multiple verifying services
- Password hashing via **bcrypt** directly (cost factor 12) — not `passlib`, which is unmaintained and incompatible with current `bcrypt` releases
- `audit_logs` are append-only from the application's perspective — no update/delete routes; production DB role should have `INSERT`/`SELECT` only on this table
- Secrets (`DATABASE_URL`, JWT signing key, Fernet key) come from `.env` via `pydantic-settings`; never hardcoded, never committed

### Local Development Setup
Until the AWS phase (Phase 6), development runs against a local PostgreSQL instance.

- **Base connection**: `postgresql://postgres:root@localhost:5432/` (default `postgres` superuser db)
- **Dedicated app database**: `emp_erp`, created once via `scripts/create_database.py`
- **App connection string** (`.env`): `DATABASE_URL=postgresql+psycopg://postgres:root@localhost:5432/emp_erp`
- **`.env.example`** documents all required variables: `DATABASE_URL`, `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, `FERNET_KEY`, `TOTP_ISSUER_NAME`, `SUPER_ADMIN_EMAIL`, `SUPER_ADMIN_PASSWORD`, `CORS_ORIGINS`
- **Migrations**: `alembic revision --autogenerate -m "message"` to generate, `alembic upgrade head` to apply
- **Run the app**: `uvicorn app.main:app --reload` (docs at `/docs`, health at `/health`)
- **Seed the first user**: `python scripts/seed_super_admin.py` (idempotent — skips if a super admin already exists)

### EC2 Spec (Phase 1–3, later AWS deployment target)
- **Instance**: t3.micro (2 vCPU, 1 GB RAM) — free tier eligible for 12 months
- **Storage**: 20 GB gp3 EBS
- **OS**: Ubuntu 22.04 LTS
- **Cost**: ~$8–10/month (if not free tier)

---

## Phase 2: Core HR Modules (Weeks 4–7)

### Goal
Build Employee profile management, Onboarding, and Document modules.

### Deliverables
- Employee profile CRUD (personal info, contact, emergency contacts, bank details)
- Department & Designation master data management
- Onboarding module:
  - Onboarding template with configurable task checklists
  - Task assignment to HR/Employee with due dates
  - Progress dashboard (% completion)
  - Email notifications (SMTP / AWS SES)
- Employee Document module:
  - Document categories (ID Proof, Address Proof, Education, Experience, etc.)
  - Upload with file type & size validation
  - Expiry date tracking with alert flags
  - Document approval workflow (HR verifies)
  - Download with access control
- Admin dashboard (Bootstrap) for HR/Admin to manage above
- Employee self-service portal pages

### Database Tables (Phase 2)
- `employees` — id, user_id, company_id, employee_code, department_id, designation_id, joining_date, probation_end_date, status
- `departments` — id, company_id, name, head_employee_id
- `designations` — id, company_id, name, level
- `onboarding_templates` — id, company_id, name, description
- `onboarding_tasks` — id, template_id, title, description, assigned_to_role, due_days, is_mandatory
- `employee_onboardings` — id, employee_id, template_id, status, started_at, completed_at
- `employee_onboarding_tasks` — id, onboarding_id, task_id, status, assigned_to_user_id, due_date, completed_at, notes
- `document_categories` — id, company_id, name, is_mandatory
- `employee_documents` — id, employee_id, category_id, file_path, file_name, file_size, mime_type, uploaded_at, expiry_date, status, verified_by, verified_at

### Key Decisions
- File uploads stored in `/var/www/erp/uploads/` with subfolders by company_id/employee_id
- Max file size: 10 MB per file
- Allowed types: PDF, JPG, PNG, DOC, DOCX
- Soft delete on all major entities (deleted_at column)

---

## Phase 3: Time, Attendance & Leave (Weeks 8–11)

### Goal
Implement attendance tracking and comprehensive leave management.

### Deliverables
- Attendance module:
  - Clock-in / Clock-out API (with IP & geolocation capture)
  - Daily attendance log with status (Present, Absent, Late, Half-day, On-leave)
  - Timesheet view (daily/weekly/monthly)
  - Shift master (general, night, flexible) and employee-shift mapping
  - Regularization request for missed punches
- Leave Management module:
  - Leave type master (CL, SL, EL/PL, Comp-off, LOP, etc.) — configurable per company
  - Leave balance initialization and accrual rules (monthly/yearly/carry-forward)
  - Leave application with date range, reason, attachment
  - Multi-level approval workflow (Reporting Manager → HR)
  - Leave calendar view (team + personal)
  - Leave balance dashboard
  - Comp-off credit and utilization tracking
- Email notifications on leave apply/approve/reject
- Attendance reports (HR/Admin view)

### Database Tables (Phase 3)
- `shifts` — id, company_id, name, start_time, end_time, grace_period_minutes, is_night_shift
- `employee_shifts` — id, employee_id, shift_id, effective_from, effective_to
- `attendance_logs` — id, employee_id, date, clock_in, clock_out, clock_in_ip, clock_out_ip, status, work_hours, regularization_id
- `attendance_regularizations` — id, employee_id, date, requested_clock_in, requested_clock_out, reason, status, approved_by, approved_at
- `leave_types` — id, company_id, name, code, max_days, carry_forward_allowed, encashment_allowed, color_code
- `leave_balances` — id, employee_id, leave_type_id, year, total_allocated, used, carried_forward, encashed, lapsed
- `leave_applications` — id, employee_id, leave_type_id, from_date, to_date, days, reason, attachment_path, status, applied_at, approved_by, approved_at, rejection_reason
- `leave_approval_history` — id, leave_id, action_by, action, action_at, comments

### Key Decisions
- Accrual runs via a daily cron job (APScheduler or Linux cron calling FastAPI endpoint)
- Attendance status auto-calculated at end of day via cron
- Leave approval: Employee → Reporting Manager → HR (configurable)
- Comp-off auto-credited when work on holiday/weekend is approved

---

## Phase 4: KRA & Performance Management System (Weeks 12–16)

### Goal
Build goal-setting (KRA) and full appraisal cycle (PMS) with review workflows.

### Deliverables
- KRA Module:
  - KRA template creation (Admin/HR)
  - KRA assignment to employees per review cycle
  - KRA items with weightage (%), target description, measurement criteria
  - Employee self-rating, Manager rating, final score calculation
  - KRA status tracking (Draft → Submitted → Reviewed → Approved)
- PMS Module:
  - Appraisal cycle management (start date, end date, review stages)
  - 360° feedback configuration (Peer, Subordinate, Self, Manager)
  - Rating scale master (1–5 with behavioral descriptors)
  - Performance evaluation form per employee
  - Normalization & bell curve analysis (HR view)
  - Promotion & increment recommendation flags
  - Final scorecard PDF generation (optional Phase 5)
- Review meeting scheduling and notes
- Competency framework (skills, behavioral competencies)

### Database Tables (Phase 4)
- `appraisal_cycles` — id, company_id, name, start_date, end_date, status, review_stages_json
- `kra_templates` — id, company_id, name, description, is_default
- `kra_template_items` — id, template_id, title, description, default_weightage, measurement_criteria
- `employee_kras` — id, employee_id, cycle_id, template_id, status, overall_score, submitted_at, reviewed_at
- `employee_kra_items` — id, employee_kra_id, title, description, weightage, target, employee_rating, employee_comment, manager_rating, manager_comment, score
- `pms_evaluations` — id, employee_id, cycle_id, evaluator_id, evaluator_role, status, submitted_at
- `pms_evaluation_items` — id, evaluation_id, competency_id, rating, comment
- `competencies` — id, company_id, name, category, description
- `rating_scales` — id, company_id, name, min_score, max_score, description
- `promotion_recommendations` — id, employee_id, cycle_id, recommended_by, recommended_designation_id, reason, status

### Key Decisions
- KRA weightage must sum to 100% per employee
- Overall score = Σ(item_score × weightage/100)
- PMS stages: Goal Setting → Self Assessment → Manager Review → HR Review → Finalization
- Bell curve analysis computed in Python (pandas) and displayed as chart (Chart.js)

---

## Phase 5: Reporting, Notifications & Polish (Weeks 17–19)

### Goal
Add reports, bulk operations, notifications, and UI/UX polish.

### Deliverables
- Reports module:
  - Attendance summary report (monthly/employee/department)
  - Leave utilization report
  - KRA/PMS completion status report
  - Employee headcount & turnover analytics
  - Document expiry report
- Notification system:
  - In-app notification bell
  - Email digests (daily/weekly configurable)
  - Notification templates (configurable by Admin)
- Bulk operations:
  - Bulk employee import via CSV/Excel
  - Bulk leave balance update
  - Bulk KRA assignment
- UI/UX polish:
  - Responsive Bootstrap layouts for all modules
  - DataTables with server-side pagination
  - Date range pickers, select2 dropdowns
  - Loading spinners, toast notifications (toastr.js)
  - Print-friendly views
- Performance optimization:
  - Database indexing on frequently queried columns
  - Query optimization with SQLAlchemy eager loading
  - API response caching (Redis optional — skip if memory constrained)

### Database Tables (Phase 5)
- `notifications` — id, user_id, type, title, message, is_read, created_at, action_url
- `notification_settings` — id, user_id, email_enabled, digest_frequency, module_preferences_json
- `report_templates` — id, company_id, name, query_sql, parameters_json, format

---

## Phase 6: Deployment Hardening & Go-Live (Weeks 20–21)

### Goal
Production readiness, security hardening, and deployment.

### Deliverables
- Security:
  - CORS properly configured
  - SQL injection prevention (SQLAlchemy ORM used throughout)
  - XSS prevention (Jinja2 auto-escaping, CSP headers)
  - CSRF protection on state-changing endpoints
  - Secure headers (HSTS, X-Frame-Options, X-Content-Type-Options)
  - Fail2ban for SSH + Nginx brute force protection
  - Automated DB backups (daily pg_dump to S3 or EBS snapshot)
- Monitoring:
  - Uptime check (simple health endpoint `/health`)
  - Log rotation (logrotate)
  - Optional: CloudWatch agent for basic metrics
- Deployment automation:
  - Deployment script (bash) for zero-downtime updates
  - Environment-based configuration (.env files)
- Documentation:
  - API documentation (auto-generated FastAPI /docs)
  - User manual (HR, Employee, Admin workflows)
  - Deployment runbook

### EC2 Optimization for Low Cost
- Use **t3.micro** with swap file (2 GB) to handle memory spikes
- PostgreSQL tuned for low memory (`shared_buffers=256MB`, `effective_cache_size=512MB`)
- Nginx serves static files directly; Gunicorn workers = 2 (formula: 2×CPU + 1, capped at 2 for 1GB RAM)
- Enable t3 unlimited mode cautiously (watch CPU credits)
- Consider **t3.small** (2 GB RAM) if concurrent users > 50

---

## Project Folder Structure (Recommended)

This repository root **is** the project root (no wrapper directory):

```
EmpERP/
├── alembic/                    # Database migrations
├── app/
│   ├── api/
│   │   ├── v1/
│   │   │   ├── auth.py
│   │   │   ├── users.py
│   │   │   ├── employees.py
│   │   │   ├── leave.py
│   │   │   ├── attendance.py
│   │   │   ├── kra.py
│   │   │   ├── pms.py
│   │   │   ├── onboarding.py
│   │   │   ├── documents.py
│   │   │   └── reports.py
│   │   └── deps.py             # Dependencies (DB session, current_user)
│   ├── core/
│   │   ├── config.py           # Settings from env
│   │   ├── security.py         # Password hashing, JWT, 2FA
│   │   └── logging.py
│   ├── db/
│   │   ├── base.py             # SQLAlchemy base
│   │   └── session.py          # Engine & session factory
│   ├── models/                 # SQLAlchemy models
│   ├── schemas/                # Pydantic schemas
│   ├── services/               # Business logic layer
│   ├── repositories/           # DB access layer
│   ├── utils/                  # Helpers, email, file handling
│   └── main.py                 # FastAPI app factory
├── static/                     # CSS, JS, images
│   ├── css/
│   ├── js/
│   └── uploads/                # User uploads
├── templates/                  # Jinja2 HTML templates
│   ├── base.html
│   ├── auth/
│   ├── admin/
│   ├── hr/
│   └── employee/
├── tests/                      # pytest suite
├── scripts/
│   ├── create_database.py      # one-off: creates the emp_erp database
│   ├── seed_super_admin.py
│   ├── deploy.sh
│   └── backup.sh
├── .env.example
├── requirements.txt
├── alembic.ini
└── README.md
```

---

## Milestone Checklist

| Phase | Milestone | Acceptance Criteria |
|-------|-----------|---------------------|
| 1 | Auth system live | Login with 2FA works, roles enforced, deployed on EC2 with SSL |
| 2 | HR core ready | Employee CRUD, onboarding flow, document upload/verify functional |
| 3 | T&A + Leave live | Clock-in/out, leave apply/approve, balance tracking works |
| 4 | KRA/PMS ready | Full appraisal cycle configurable and executable end-to-end |
| 5 | Reports & polish | All reports generate correctly, UI responsive, bulk import works |
| 6 | Production go-live | Security audit passed, backups automated, documentation complete |

---

## Estimated Timeline

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Phase 1 | 3 weeks | Week 3 |
| Phase 2 | 4 weeks | Week 7 |
| Phase 3 | 4 weeks | Week 11 |
| Phase 4 | 5 weeks | Week 16 |
| Phase 5 | 3 weeks | Week 19 |
| Phase 6 | 2 weeks | Week 21 |

**Total: ~5 months** (1 developer full-time, or 2 developers ~2.5 months)

---

## Cost Estimate (Monthly, Post Free Tier)

| Service | Spec | Cost (USD) |
|---------|------|------------|
| EC2 | t3.micro | ~$8–10 |
| EBS | 20 GB gp3 | ~$1.60 |
| Data Transfer | Light usage | ~$1–2 |
| Route 53 (optional) | 1 hosted zone | ~$0.50 |
| **Total** | | **~$12–15/month** |

> If user count grows beyond 50 concurrent, upgrade to **t3.small** (~$16/month).

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Memory exhaustion on t3.micro | Add 2 GB swap, limit Gunicorn workers, optimize queries |
| File storage growth | Implement file size limits, periodic cleanup, migrate to S3 in Phase 5 |
| Database corruption | Daily automated backups, test restore monthly |
| 2FA lockout | Generate and store 10 backup codes per user at 2FA setup |
| Concurrent leave approval race condition | Use PostgreSQL row-level locking (`SELECT FOR UPDATE`) |

---

## Next Steps (Immediate Actions)

1. **Provision EC2**: Launch t3.micro Ubuntu 22.04, configure security groups (22, 80, 443)
2. **Install dependencies**: Python 3.11, PostgreSQL 15, Nginx, Git
3. **Initialize project**: Create FastAPI skeleton, configure Alembic, set up .env
4. **Create first migration**: `users`, `companies`, `audit_logs`
5. **Build login page**: Bootstrap form → 2FA verification → Dashboard redirect
6. **Seed Super Admin**: Run script to create first super admin user
7. **Configure Nginx + SSL**: Point domain, obtain Let's Encrypt certificate

---

*Document Version: 1.1 — added enterprise hardening NFRs, deepened Phase 1 security decisions, added local development setup*
*Last Updated: 2026-07-29*
*Target Deployment: Local PostgreSQL for development now; AWS EC2 (cost-optimized) from Phase 6*
