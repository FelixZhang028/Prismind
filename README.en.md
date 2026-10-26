<p align="center">
  <img src="landing/public/brand/prismind-icon-512.png" alt="Prismind logo" width="96" />
</p>

<h1 align="center">Prismind · Data Research Workbench</h1>

<p align="center">Turn investment ideas into research you can verify.</p>

<p align="center">
  <a href="https://getprismind.com"><strong>Use it online: getprismind.com</strong></a>
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <a href="README.en.md"><strong>English</strong></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/Vue-3-4FC08D?logo=vuedotjs&logoColor=white" alt="Vue 3" />
  <img src="https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPL--3.0-blue" alt="GPL 3.0" /></a>
</p>

> The website is in Chinese, and the detailed documents in `docs/` are written in Chinese. The Chinese README is the reference version.

## 🖥️ Screenshots

These screenshots show the running application (2026-10-22).

**Brand homepage**

![Prismind homepage](docs/images/homepage.png)

**Workspace home: market overview, your stock pool and the data calendar**

![Workspace home](docs/images/workspace.png)

## 📖 About

Prismind (镜思) is a research workbench for China's A-share market, built with **Vue 3 and FastAPI**. It brings data updates, stock screening, strategy building, factor evaluation, backtesting and AI-assisted research into one workflow, so researchers can record and test their own ideas. No coding is needed: strategies and screening conditions are set with forms or a one-sentence description.

| Workspace | Capabilities |
| --- | --- |
| AI research | AI Researcher organizes one stock's price history, valuation, financial reports and risks from local data, and the AI writes its reading only from that data, with the evidence for each point; the AI chat in the corner answers questions across stocks and shows the data it used |
| Stock screening | Set your own conditions and ranking to find the stocks that match on the latest trading day; the AI can describe what the group has in common and its risk signals; backtest the same conditions over the last 1–5 years |
| My strategies | Rule-based strategies from a template, a one-sentence description, or a form |
| Factor research | Factor library, single-factor evaluation, combined research |
| Backtest and validation | Backtests, parameter optimization, out-of-sample validation, trade verification; optimization and walk-forward validation are simulated previews for now |
| Research records | Past research results and comparisons |
| Data | Data overview, data updates, stock pool |
| System | Account (nickname, password, delete account), points and daily check-in, settings (defaults, export all your data) |

**Limits:** backtests and factor evaluation need market data downloaded first. Text AI needs an OpenAI-compatible service (for example DeepSeek or OpenRouter) configured on the server, and the Jev decision model can be configured separately; without them the AI results are not shown. WeKnora document Q&A needs a separately deployed service. The project is for research and simulation and never trades real money.

## ⚠️ Disclaimer

- Prismind is a research tool that organizes and describes historical data. **It is not investment advice**, does not recommend stocks and does not forecast prices.
- Backtest and factor results come from historical data and do not indicate future performance. AI-written content can be wrong; check it against the original data.
- Market and financial data come from public sources such as BaoStock and AkShare and may be delayed or wrong; follow each source's terms of use.
- The site's terms of service, privacy policy and risk notice are at [getprismind.com/legal.html](https://getprismind.com/legal.html).

## 🚀 Quick Start

**You need** Python 3.11+, Node.js 18+ and Git. Any ordinary computer is enough to try it; to download the whole market and update it daily, use 8 GB of memory or more (the full-market update peaks at about 5 GB) and keep 20 GB of disk free (about 1 GB of market data, plus run records and backups).

```bash
git clone https://github.com/FelixZhang028/Prismind.git
cd Prismind
```

**1. Set up the administrator:** copy `dashboard/backend/.env.example` to `.env` in the same folder and fill in `FELLOWQUANT_ADMIN_EMAIL` and `FELLOWQUANT_ADMIN_PASSWORD` (at least 12 characters). The backend creates the administrator on its first start; there is no public default password. Only administrators can download market data and manage users.

**2. Start it**

**Windows:** run `start.bat` from the project root. The first run checks and installs dependencies; then open `http://127.0.0.1:5273`. Press any key to stop the services the script started.

**Manual start / macOS / Linux:**

```bash
# Terminal 1: backend
cd dashboard/backend
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
# Terminal 2: website and workspace, from the project root
cd landing
npm ci
npm run dev -- --host 127.0.0.1
```

**3. Start using it:** sign in as the administrator, open “数据管理 → 数据更新” (Data → Updates) to download market data, then create strategies and run backtests. The admin console runs from `admin/` with `npm ci` and `npm run dev` (port 5175). With `start.bat`, the API docs are at `http://127.0.0.1:8000/docs`.

> Signing up needs a code sent to the email address by default. `start.bat` turns this off on your own computer, so sign-up works without a mail service. When starting manually, add `FELLOWQUANT_SIGNUP_EMAIL_CODE=off` to `.env`, or set up mail (see [configuration](docs/CONFIGURATION.md)). Never turn it off on a public site.

## ⚙️ Common Settings

Settings live in `dashboard/backend/.env`, which the backend reads at start and which is not committed. AI models and keys, AI limits, points, daily updates and mail can also be changed by an administrator in the admin console (“系统设置”, System settings); those take effect immediately and take precedence over `.env`. The `FELLOWQUANT_` prefix is the project's earlier name and has been kept.

| Setting | Purpose |
| --- | --- |
| `APP_SECRET` | Signs login tokens and encrypts keys saved in the admin console; generated and saved locally when blank. Move it together with the data when changing servers |
| `FELLOWQUANT_ADMIN_EMAIL` / `FELLOWQUANT_ADMIN_PASSWORD` | Creates the first administrator; the initial password needs at least 12 characters |
| `FELLOWQUANT_AI_BASE_URL` / `FELLOWQUANT_AI_MODEL` / `FELLOWQUANT_AI_API_KEY` | Text AI model (any OpenAI-compatible service such as DeepSeek); with OpenRouter, set only `OPENROUTER_API_KEY` |
| `FELLOWQUANT_AI_DAILY_TOTAL` | Most AI calls per day for the whole site (default 500), to keep costs in check |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM` | Mail for sign-up and password reset codes (163 mail: `smtp.163.com`, port 465, password is the authorization code) |
| `FELLOWQUANT_REGISTRATION` / `FELLOWQUANT_INVITE_CODES` | Sign-up mode and invite codes, usually set in the admin console |
| `FELLOWQUANT_DAILY_UPDATE` / `FELLOWQUANT_BAOSTOCK_INTERVAL` | Automatic full-market update after each trading day (on by default), and the gap between BaoStock requests |
| `FELLOWQUANT_BACKUP_DIR` | Where the daily backup of the account database and login key goes; preferably another disk |

All settings (AI limits, points rules, compute limits, backups, rate limits and more) and the Jev and WeKnora notes are in **[configuration](docs/CONFIGURATION.md)** (Chinese).

## 🌐 Deployment

The live site [getprismind.com](https://getprismind.com) runs on a Linux cloud server behind Nginx with https. Preparing a server, moving data, deploying and rolling back with one `scripts/deploy.sh` command, and switching the domain are described in **[deploying to a cloud server](docs/DEPLOY_SERVER.md)**.

Before going live, check at least: `APP_SECRET`, the administrator account, the AI model key, `FELLOWQUANT_AI_DAILY_TOTAL`, the sign-up mode, mail (sign-up verifies the email address), `FELLOWQUANT_CLIENT_IP_HEADER` and the backup folder. Run the backend as a single process (limits and background jobs live in that process); do not start several workers.

| Document (Chinese) | Contents |
| --- | --- |
| [Deploying to a cloud server](docs/DEPLOY_SERVER.md) | Server setup, moving data, deploy and roll back, switching the domain, daily checks |
| [Running and maintenance](docs/OPERATIONS.md) | Daily data updates, compute limits, accounts and security, single-process serving, temporarily publishing from your own PC with Cloudflare Tunnel, terms and privacy policy |
| [Admin console](docs/ADMIN.md) | Users, sign-up and invite codes, banned words, points and redeem codes, data updates, system settings, audit log |
| [Configuration](docs/CONFIGURATION.md) | Every setting, Jev and WeKnora |
| [Jev guide](docs/JEV_USAGE.md) | Decision model setup, web usage, API examples and troubleshooting |

## ❓ FAQ

**Sign-up says the site has no mail service configured:** sign-up verifies the email address. Fill in “系统设置 → 邮件服务” (System settings → Mail) in the admin console and send a test email; for trying it on your own PC, see the note in Quick Start.

**The code email does not arrive:** check the spam folder, then send a test email from the admin console and check the server, port and authorization code (163 and QQ mail need the authorization code, not the login password).

**A data update says “黑名单用户” (blacklisted):** BaoStock temporarily blocks servers that make too many requests. The job stops and does not retry that day; raise `FELLOWQUANT_BAOSTOCK_INTERVAL` (for example to 0.5) and try again the next day.

**`start.bat` says a port is in use:** another program holds port 8000 or 5273. The script stops processes it left behind itself; if it is another program, close it first.

**No AI reading appears:** the server has no AI model key yet, or today's free uses and points are used up. Administrators can click “测试文本模型” (Test text model) under “系统设置 → AI 模型”.

## 🧩 Project Structure

```text
.
├── landing/              # Vue website, sign-in, workspace and legal pages
├── admin/                # Admin console (served under /admin/ in production)
├── dashboard/
│   └── backend/
│       ├── app/          # FastAPI routes, authentication and database
│       ├── quant_platform/  # Quant research, WeKnora and Jev adapters
│       ├── trading_agents/  # AI research workflows
│       ├── configs/      # Data source, strategy and risk configuration
│       └── tests/        # Regression tests
├── deploy/server/        # Server service, Nginx configuration and install scripts
├── docs/                 # Deployment, operations, admin and configuration docs, screenshots
├── scripts/start.ps1    # Windows local development: start and clean up services
├── scripts/serve.ps1 / serve.sh  # Build the web pages and serve them from the backend
├── scripts/deploy.sh    # Deploy to the cloud server
├── scripts/tunnel.ps1   # Publish from your own PC with Cloudflare Tunnel (fallback)
└── start.bat
```

## 🧪 Development and Verification

```bash
cd dashboard/backend
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall -q app quant_platform trading_agents
```

Run `npm ci`, `node --test tests/*.test.js` and `npm run build` in `landing/` and `admin/`. Regression tests cover trade verification, external API contracts, account-isolated configuration, authentication, sign-up codes, points and password reset. External services and mail are mocked, so tests cost nothing and send no email.

## 🤝 Contributing

Issues, feature suggestions and pull requests are welcome on [GitHub](https://github.com/FelixZhang028/Prismind/issues). Please include reproduction steps, expected behavior and actual behavior, and run the tests above before sending code. Report security problems privately as described in [SECURITY.md](SECURITY.md), not in a public issue.

Thanks to AlphaQuant for the research foundation, and to [BaoStock](http://baostock.com/), [AkShare](https://github.com/akfamily/akshare), [WeKnora](https://github.com/Tencent/WeKnora) and [OpenRouter](https://openrouter.ai/) for data and integrations.

## 📬 Contact

Email: prismind_ai@163.com

## 📄 License

Licensed under the [GNU GPL v3](LICENSE).
