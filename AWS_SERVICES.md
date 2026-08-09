# AWS Services Checklist — Lowest-Cost Deployment (ECR + EC2)

Stradit Workforce ERP is a small internal app (single FastAPI service + Postgres). This guide lists
the **minimum AWS services** to create, sized as small as reasonably works, and wires up the
existing GitHub Actions pipeline (`.github/workflows/deploy.yml`) to build the Docker image, push it
to **ECR**, and deploy it to a single **EC2** box. No RDS, no load balancer, no NAT gateway — those
are the big line items on an AWS bill and this app doesn't need them at this scale.

For Nginx/SSL/domain and backup-script details, see [`DEPLOYMENT.md`](DEPLOYMENT.md) — this doc
only covers the AWS resources and the ECR/EC2 CI/CD path.

---

## 1. Architecture (single box, no managed DB)

```
 GitHub Actions (on push to main)
   │
   ├─ build image ──▶ Amazon ECR (private repo "emperp")
   │
   └─ ssh deploy ───▶ EC2 (t4g.small, Ubuntu 24.04, ARM)
                        ├─ container: app  (pulled from ECR)
                        └─ container: db   (postgres:16-alpine, local EBS volume)
```

Running Postgres in a container on the same box (instead of RDS) is what keeps this near the
lowest possible cost. Trade-off: no managed backups/HA — mitigate with the daily `pg_dump` cron
already documented in `DEPLOYMENT.md` §6, and consider an EBS snapshot lifecycle rule.

---

## 2. Services to create

| # | Service | What to create | Size / config | Est. cost |
|---|---|---|---|---|
| 1 | **EC2** | 1x instance, Ubuntu 24.04 LTS ARM | `t4g.small` (2 vCPU, 2 GB RAM) — see sizing note below | ~$12/mo |
| 2 | **EBS** | Root volume, gp3 | 20 GB | ~$1.60/mo |
| 3 | **Elastic IP** | 1x, associated to the instance | — | $0 (free while attached & instance running) |
| 4 | **ECR** | Private repository `emperp` | Lifecycle rule: keep last 5 tagged images, expire untagged after 1 day | ~$0.10/mo (<1 GB) |
| 5 | **Security Group** | `emperp-sg` | Inbound 22 (your IP only), 80/443 (0.0.0.0/0); Outbound all | Free |
| 6 | **IAM Role (EC2 instance profile)** | `EmpERP-EC2-Role` | Managed policy `AmazonEC2ContainerRegistryReadOnly` — lets the box pull from ECR with no stored keys | Free |
| 7 | **IAM OIDC provider** (if not already present in the account) | `token.actions.githubusercontent.com` | One-time per AWS account | Free |
| 8 | **IAM Role (GitHub Actions)** | `GitHubActionsECRPushRole` | Trust: GitHub OIDC, scoped to this repo/branch. Permission: push to the `emperp` ECR repo only | Free |
| 9 | **Route 53** (optional) | Hosted zone, if you want a real domain | Only if you have a domain | ~$0.50/mo |

**Total: roughly $14–$16/month** (or ~$0.50/mo cheaper without the Elastic IP if you're fine with the
public IP changing on restart). Skipped on purpose to save cost: RDS, ALB/NLB, NAT Gateway, S3
(uploads live on the EC2 volume — see note below), Secrets Manager (use plain `.env` on the box
instead — no service to pay for).

### Sizing note
- `t4g.micro` (1 GB RAM, ~$6/mo) is tighter but works if you keep Docker build off the box (build
  always happens in CI, never on the instance) — app + Postgres together generally want ≥1.5–2 GB
  headroom under load, so `t4g.small` is the safer "still cheap" choice for a live ERP.
- If your AWS account is **under 12 months old**, `t3.micro` (1 GB, x86) is free-tier eligible
  (750 hrs/month) — free for the first year, then ~$7.50/mo. Same RAM caveat as above applies.
- Don't go below `t4g.micro`/`t3.micro` — `nano` tiers (0.5 GB) will OOM under Postgres + Uvicorn.

---

## 3. One-time AWS setup

### 3.1 ECR repository
```bash
aws ecr create-repository \
  --repository-name emperp \
  --image-scanning-configuration scanOnPush=true \
  --region <AWS_REGION>
```

### 3.2 IAM role for GitHub Actions (OIDC — no stored AWS keys in GitHub)
Create the OIDC provider once per account (skip if it already exists):
```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea
```

Trust policy (`trust-policy.json`) — replace `<ACCOUNT_ID>`, `<GITHUB_ORG>/<REPO>`:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
      "StringLike": { "token.actions.githubusercontent.com:sub": "repo:<GITHUB_ORG>/<REPO>:ref:refs/heads/main" }
    }
  }]
}
```

Permission policy (`ecr-push-policy.json`) — replace `<REGION>`, `<ACCOUNT_ID>`:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*" },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability", "ecr:PutImage", "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"
      ],
      "Resource": "arn:aws:ecr:<REGION>:<ACCOUNT_ID>:repository/emperp"
    }
  ]
}
```

```bash
aws iam create-role --role-name GitHubActionsECRPushRole \
  --assume-role-policy-document file://trust-policy.json
aws iam put-role-policy --role-name GitHubActionsECRPushRole \
  --policy-name ecr-push --policy-document file://ecr-push-policy.json
```

### 3.3 IAM role for the EC2 instance (lets it pull from ECR — no keys needed)
```bash
aws iam create-role --role-name EmpERP-EC2-Role \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name EmpERP-EC2-Role \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
aws iam create-instance-profile --instance-profile-name EmpERP-EC2-Profile
aws iam add-role-to-instance-profile --instance-profile-name EmpERP-EC2-Profile --role-name EmpERP-EC2-Role
```

### 3.4 Launch the EC2 instance
- AMI: Ubuntu Server 24.04 LTS (ARM64 for `t4g.small`)
- Instance type: `t4g.small`
- Storage: 20 GB gp3
- Security group: `emperp-sg` (22 from your IP, 80/443 open)
- IAM instance profile: `EmpERP-EC2-Profile`
- Allocate and associate an Elastic IP

SSH in and do the one-time host setup:
```bash
# Install Docker + Compose plugin + AWS CLI
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
sudo apt-get install -y awscli
sudo mkdir -p /opt/emperp && sudo chown $USER:$USER /opt/emperp
```

Create `/opt/emperp/.env` on the box with the real production values (this file is **never**
committed or pushed by CI — it stays only on the server):
```ini
DATABASE_URL=postgresql+psycopg://emperp_user:CHANGE_ME@db:5432/emperp_db
JWT_SECRET_KEY=CHANGE_ME   # python -c "import secrets; print(secrets.token_urlsafe(64))"
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
FERNET_KEY=CHANGE_ME       # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOTP_ISSUER_NAME=EmpERP
SUPER_ADMIN_EMAIL=admin@yourcompany.com
SUPER_ADMIN_PASSWORD=CHANGE_ME
CORS_ORIGINS=https://erp.yourcompany.com
LOGIN_MAX_ATTEMPTS=5
LOGIN_LOCKOUT_WINDOW_MINUTES=15
EMAIL_BACKEND=console

# Postgres container credentials — must match DATABASE_URL above
POSTGRES_USER=emperp_user
POSTGRES_PASSWORD=CHANGE_ME
POSTGRES_DB=emperp_db
```

---

## 4. GitHub repository configuration

**Settings → Secrets and variables → Actions**

| Type | Name | Value |
|---|---|---|
| Variable | `AWS_REGION` | e.g. `ap-south-1` |
| Variable | `AWS_ROLE_ARN` | `arn:aws:iam::<ACCOUNT_ID>:role/GitHubActionsECRPushRole` |
| Variable | `ECR_REPOSITORY` | `emperp` |
| Variable | `EC2_USER` | `ubuntu` |
| Secret | `EC2_HOST` | Elastic IP / DNS of the instance |
| Secret | `EC2_SSH_PRIVATE_KEY` | Private key matching the `.pem` used to launch the instance |

---

## 5. The pipeline (already wired up)

- **CI** (`.github/workflows/ci.yml`) — lint (ruff) + pytest against a throwaway Postgres service, on
  every push/PR.
- **CD** (`.github/workflows/deploy.yml`) — on push to `main`:
  1. Assumes `GitHubActionsECRPushRole` via OIDC (no AWS keys stored in GitHub).
  2. Builds the image from the existing `Dockerfile` and pushes `:<git-sha>` and `:latest` to ECR.
  3. Copies `docker-compose.prod.yml` to `/opt/emperp/` on the EC2 box.
  4. SSHes in, logs Docker into ECR using the **instance's own IAM role** (no keys over the wire),
     pulls the new image, runs `docker compose up -d`, applies `alembic upgrade head`, and hits
     `/health` to confirm the deploy.

First deploy: after step 3.4 above, just push to `main` — the pipeline builds, pushes, and starts
the stack for you. No manual `docker compose up` needed on the box.

---

## 6. Keeping cost down

- Stop (not terminate) the instance outside business hours if this is an internal tool with known
  usage windows — billing pauses while stopped (EBS/EIP still bill a few cents).
- ECR lifecycle policy (keep last 5 images) avoids storage creep from every commit's image.
- Skip Route 53 entirely and just hit the Elastic IP or use a free DNS (e.g. a subdomain you
  already own) if you don't need a dedicated hosted zone.
- Revisit RDS only if/when you need automated backups or the box is memory-starved — it adds
  roughly $12–15/mo (`db.t4g.micro`) per the architecture in `DEPLOYMENT.md`.
