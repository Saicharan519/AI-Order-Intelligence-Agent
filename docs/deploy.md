# Deploying the demo (M11)

A temporary public demo on one small AWS server, at $0 on the AWS Free plan, with HTTPS from
a free DuckDNS name. Everything runs in Docker; the same commands work on any Linux server.

```
visitor ──https──> Caddy (ports 80, 443) ──> web (Next.js) ──> api (FastAPI) ──> db (Postgres)
                   the only public part       private Docker network only        localhost only
```

- **Caddy** gets a free certificate from Let's Encrypt and renews it by itself, redirects
  `http://` to `https://`, and adds security headers.
- **web** and **api** publish no port; the database listens on the server's localhost only.
- The images run as unprivileged users; secrets come from `.env` on the server, never from
  the images or the repository.

Who does what: steps marked **(you)** involve your accounts, card, keys or passwords, which only
you handle. Everything else is a command to paste.

## Before you start (the rules that keep it free)

- **AWS Free plan** (checked 2026-10-18): up to $200 in credits, for 6 months from the day the
  account is created, then the account closes (data kept 90 days, then erased). No charges
  unless you upgrade to a Paid plan. **Never click "Upgrade to Paid plan".** Create the account
  only when you are ready to launch: the 6 months start at sign-up.
- Expected use: a 2 GB server, its public IPv4 address and a 20 GB disk, about $20 a month in
  credits, so it can run all day for the whole 6 months. Check the credits widget on the
  console home page every week or two.
- The only real money is DeepSeek, already paid and capped in code ($1.90 total, $0.40 a
  day, $0.05 per user a day).

## 0. Rehearse on your laptop (optional, $0)

The exact images and Caddy, with model calls switched off and emails printed instead of sent,
as a separate Compose project with its own database. See `deploy/compose.rehearsal.yml` for
the commands; then open `https://localhost:8443` (the browser warns once about Caddy's local
certificate). Remove it with the `down -v` command in the same file.

## 1. AWS account (you)

1. Create the account at aws.amazon.com (Free plan). Then, signed in as the root user:
   **Security credentials → Assign MFA device** (an authenticator app). Do this first.
2. Top right, choose the region **Asia Pacific (Mumbai) `ap-south-1`**, and always work in it.
3. **Billing → Budgets → Create budget → "Zero spend budget"** with your email: AWS emails
   you if anything is ever billed.

## 2. A free name for HTTPS (you)

1. Sign in at https://www.duckdns.org (with Google or GitHub) and add a subdomain, for example
   `orderintel` → `orderintel.duckdns.org`. Leave the IP for now.
2. Keep the DuckDNS page open; you set the IP in step 4.

## 3. Launch the server (you, in the EC2 console)

**EC2 → Launch instance**:

| Setting | Value |
|---|---|
| Name | `orderintel` |
| Image | **Ubuntu Server 24.04 LTS** (64-bit x86) |
| Instance type | **t3.small** (2 GB; must show "Free plan eligible") |
| Key pair | **Create new key pair** → name `orderintel`, type ED25519, `.pem`. It downloads once: keep it safe, never commit it. |
| Network → Security group | Create one: **SSH (22) from My IP**; **HTTP (80) from Anywhere**; **HTTPS (443) from Anywhere** |
| Storage | **20 GiB gp3** |

Launch, then open the instance and copy its **Public IPv4 address**.

## 4. Point the name at the server (you)

On duckdns.org, put the server's public IPv4 address in your subdomain's box and press
**update ip**. Check from your laptop: `nslookup orderintel.duckdns.org` shows that address.

The address changes if you **stop and start** the instance (a reboot keeps it). If that
happens, update it on DuckDNS again.

## 5. Connect and install Docker

From your laptop, in the folder with the key (Git Bash):

```bash
chmod 400 orderintel.pem
ssh -i orderintel.pem ubuntu@<public-ip>
```

On the server:

```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker ubuntu
# 2 GB of swap: building the images needs more memory than running them.
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
exit
```

Connect again (so the `docker` group applies), then get the code:

```bash
ssh -i orderintel.pem ubuntu@<public-ip>
git clone https://github.com/Saicharan519/AI-Order-Intelligence-Agent.git orderintel
cd orderintel
```

## 6. The server's `.env` (you)

```bash
cp .env.example .env
chmod 600 .env          # readable only by you
nano .env
```

Fill in, with **new** values (not the ones on your laptop). For each password run
`openssl rand -base64 24` on the server and paste the result:

- `POSTGRES_PASSWORD`, `OI_OWNER_PASSWORD`, `OI_AGENT_PASSWORD`, `OI_TRACE_PASSWORD`,
  `OI_EVAL_PASSWORD`, `OI_INJTEST_PASSWORD`, `ACCESS_CODE`: each a different random value.
- `DEEPSEEK_API_KEY` and the model settings, as on your laptop.
- `MAIL_MODE=smtp`, `SMTP_USER`, `SMTP_PASSWORD` (your Gmail App Password).
- `SITE_ADDRESS=orderintel.duckdns.org` and `APP_URL=https://orderintel.duckdns.org`.
- Keep `LLM_ENABLED=true`, `LOGIN_CODE_REQUIRED=true`, the budget caps as they are.

Save with Ctrl+O, Enter, Ctrl+X.

## 7. Copy the dataset (from your laptop)

The Olist CSVs are not in the repository (they are not redistributed). From the project
folder on your laptop:

```bash
scp -i path/to/orderintel.pem data/raw/*.csv ubuntu@<public-ip>:~/orderintel/data/raw/
```

## 8. Build, create the database, load the data

On the server, in `~/orderintel`:

```bash
docker compose --profile app build                    # 5 to 15 minutes the first time
docker compose up -d db
docker compose --profile app run --rm --no-deps api python scripts/migrate.py
docker compose --profile app run --rm --no-deps -v "$PWD/data/raw:/app/data/raw:ro" api python scripts/load_data.py
```

The loader checks every table's row count (550,759 rows in total) and changes nothing if any
check fails.

## 9. Your admin account (you)

```bash
docker compose --profile app run --rm --no-deps api python scripts/create_admin.py --email you@example.com --name "Your Name"
```

It asks for the password with nothing shown on screen.

## 10. Start it

```bash
docker compose --profile app up -d
docker compose ps                 # db and api "healthy", web and caddy "Up"
docker compose logs caddy | grep -i certificate
```

Open `https://orderintel.duckdns.org`: the padlock should show, and you sign in with your
password and the code emailed to you. If the certificate does not come at once, check that
ports 80 and 443 are open in the security group and that DuckDNS shows the right IP; Caddy
retries by itself.

## 11. Smoke test (with the owner's approval: a few cents)

Ask two or three example questions in the web app and check the answers, the Evidence tab and
the budget in the sidebar. Then invite one friend and check that the email arrives.

## Running it

| Task | Command (in `~/orderintel`) |
|---|---|
| See what runs | `docker compose ps` |
| Logs | `docker compose logs -f --tail 100 api` (or `web`, `caddy`, `db`) |
| **Kill switch** (no model calls at all) | set `LLM_ENABLED=false` in `.env`, then `docker compose --profile app up -d api` |
| Update to the latest code | `git pull && docker compose --profile app up -d --build` |
| Restart everything | `docker compose --profile app restart` |
| Reboot the server | `sudo reboot` (the containers start again by themselves) |
| Disk use | `df -h` and `docker system df` |

A new migration after an update: `docker compose --profile app run --rm --no-deps api python scripts/migrate.py`.

## Teardown (before the 6 months end, or when the demo is over)

1. Download anything you want to keep (screenshots, the demo video is on your laptop).
2. **EC2 → Instances → the instance → Instance state → Terminate** (this deletes its disk).
3. **EC2 → Volumes** and **Elastic IPs**: nothing should be left.
4. Revoke the **Gmail App Password** (Google Account → Security → App passwords) and the
   **DeepSeek API key** used on the server.
5. Delete the subdomain on DuckDNS.
6. A day later, check **Billing** and the credits widget: no running resources, no charges.
