# Running SmartAWARE on Windows

A setup guide for a Windows laptop with no development tools installed.
Covers both repositories: this one (`smartaware-backend`) and
`smartaware-frontend`.

Everything runs through Docker except the website itself, so there is no
Python, PostgreSQL or Redis to install — and, importantly, no pgvector to
compile. See the appendix for why that matters.

## Requirements

- Windows 10 64-bit (version 2004+) or Windows 11
- An administrator account, ~10 GB free disk, one restart
- About 45 minutes

Commands are typed into **PowerShell**. To open it in a folder: open the
folder in File Explorer, hold Shift, right-click the empty space, and choose
*Open PowerShell window here*.

## 1. Install Docker Desktop

Download from <https://www.docker.com/products/docker-desktop/> (Windows,
AMD64). Accept every default, including "Use WSL 2 instead of Hyper-V".
Restart when asked, then launch Docker Desktop and wait for **Engine
running**. No Docker account is needed — skip the sign-in.

```powershell
docker --version
```

If WSL 2 is reported as incomplete, run `wsl --update` in an Administrator
PowerShell and restart.

## 2. Install Node.js

Download the **LTS** `.msi` from <https://nodejs.org/> and accept the
defaults. Close all PowerShell windows and open a new one afterwards, or
`npm` will not be on the PATH.

```powershell
node --version    # must be v20 or higher
```

## 3. Download the code

On GitHub, for each repo: **Code** → **Download ZIP**. Extract both into
`C:\smartaware` and strip the `-main` suffix GitHub adds, so you end up with:

```
C:\smartaware\smartaware-backend
C:\smartaware\smartaware-frontend
```

Windows often double-wraps extracted ZIPs. If you see
`smartaware-backend-main\smartaware-backend-main`, move the inner folder up.

## 4. Start the backend

Docker Desktop must be running.

```powershell
cd C:\smartaware\smartaware-backend
Copy-Item .env.example .env
docker compose up -d --build
```

`.env` is gitignored, so it is not in the download — that is where secrets
would live. The defaults in `.env.example` are complete for local use.

The first build takes 5-10 minutes. It is done when all five services report
`Started`.

## 5. Build the database

One time only. Run each command and wait for it to finish.

```powershell
docker compose exec api uv run python scripts/update.py
docker compose exec api uv run python scripts/create_admin.py --email you@example.com --generate
```

**The second command prints a generated password once.** Save it before
closing the window; the account is forced to change it at first login.

### Locked out of that account

If the address or the password is lost, nothing in the portal can help —
signing in is the thing that is not working. Ask the database instead:

```powershell
docker compose exec api uv run python scripts/reset_admin.py
```

That lists the Admin accounts and changes nothing, which is often the whole
fix: a forgotten address and a forgotten password are different losses. If the
address is enough, `--set-password` issues a new temporary one. If neither is
recoverable, `--delete --yes` removes the account and `create_admin.py` makes
the replacement.

Check <http://localhost:8000/docs> — the endpoint list means the API is up.

## 6. Start the website

In a second PowerShell window, which must stay open:

```powershell
cd C:\smartaware\smartaware-frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

`npm run gen:api` is not needed — `src/lib/api/schema.d.ts` is committed.

## 7. Open it

| Address | What it is |
|---|---|
| <http://localhost:3000> | Website, Customer Portal, Admin Portal |
| <http://localhost:8000/docs> | API, for checking backend health |

Two things are off by design, so no paid accounts are required:

- **Chatbot** returns 503 — `OPENAI_API_KEY` is blank in `.env`.
- **Email** is not sent — `USE_CONSOLE_EMAIL=true` prints it to the log.
  Read invite links with `docker compose logs api`.

## 8. Optional: turn on the chatbot

The chatbot is off until an OpenAI key is supplied, and it needs two things,
not one. Seeding loads the FAQ *text*, but not the embeddings the search runs
against — those are produced by the index job, which calls OpenAI.

Open `.env` in Notepad, set the key, and save:

```
OPENAI_API_KEY=sk-...
```

Then restart and build the index:

```powershell
docker compose restart api worker beat
docker compose exec api uv run python scripts/run_job.py reindex-faq
```

The job prints a JSON report. It embeds 15 short FAQ entries on
`text-embedding-3-small` — a fraction of a cent, once. Re-running it is safe:
the index is incremental and only touches entries edited since the last run.

Without the key the job stops with a clear message rather than a traceback,
and the chat endpoint returns a plain "temporarily unavailable" reply. A
database copied from another machine does not help: every question calls
OpenAI twice at the time it is asked — once to vectorise the question, once to
write the answer — so the key is required even when the embeddings are already
present.

## Updating after a `git pull`

```powershell
cd C:\smartaware\smartaware-backend
docker compose up -d --build
docker compose exec api uv run python scripts/update.py
```

That one command is the whole database side of a pull. It applies any
migrations, then seeds any reference rows that are missing, and prints what it
did. Re-running it is safe — on a database that is already current it applies
nothing and says so.

Skipping it is the usual cause of the website showing an error where content
should be: the code expects a column the database does not have yet.
`docker compose logs api` says so in as many words at startup, and
<http://localhost:8000/api/v1/health> reports `schema_status`.

It is also worth running after the very first `docker compose up`, in place of
the two commands in step 5 — the only thing it does not do is create your
administrator account, which it will tell you about.

Then, in the frontend folder, `npm install` and `npm run dev` again.

## Everyday use

```powershell
# start (Docker Desktop open first)
cd C:\smartaware\smartaware-backend  ; docker compose up -d
cd C:\smartaware\smartaware-frontend ; npm run dev

# stop - Ctrl+C the website window, then
cd C:\smartaware\smartaware-backend  ; docker compose down
```

`docker compose down` keeps the database. `docker compose down -v` erases it,
after which step 5 must be repeated.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `docker` not recognized | Docker Desktop is not running. Open it, wait for Engine running. |
| `npm` not recognized | Open a fresh PowerShell window. |
| WSL 2 incomplete | `wsl --update` in an Administrator PowerShell, then restart. |
| `port is already allocated` | Something else holds 5432/6379/8000, usually an existing PostgreSQL. Stop that service. |
| Port 3000 in use | `npm run dev -- -p 3001`, then add `http://localhost:3001` to `CORS_ALLOWED_ORIGINS` in `.env` and `docker compose restart api`. Sign-in fails otherwise. |
| Site loads but is empty | Step 5 was skipped. Re-run migrate and seed; both are idempotent. |

## Appendix: without Docker

Possible, but it trades two downloads for five plus a compiler.

| Component | On Windows |
|---|---|
| Python 3.12 | python.org installer |
| uv | `winget install astral-sh.uv` |
| PostgreSQL 17 | EDB installer; add `C:\Program Files\PostgreSQL\17\bin` to PATH manually |
| **pgvector** | **No prebuilt binaries.** Source build with Visual Studio C++ Build Tools and `nmake /F Makefile.win` |
| Redis | [Memurai](https://www.memurai.com/redis-windows) Developer Edition — native Windows service |

pgvector is the blocker: `migrations/versions/20260913_1103_initial_schema.py`
runs `CREATE EXTENSION vector`, so it cannot be skipped. There is also no
`make` on Windows, so every Makefile target must be typed out by hand, and
`db-create` will not run at all.

Middle ground — database in Docker, everything else native:

```powershell
docker compose up -d db
```

The container publishes to `localhost:5432`, so `.env.example` works
unchanged, exactly as it does against a Homebrew Postgres on macOS.
