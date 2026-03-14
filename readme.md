# BusSing API

Backend service for BusSing — handling bus routes, services, and stop data.

---

## 💻 Local Development

**1. Activate the virtual environment**

```bash
source .venv/bin/activate
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Save new dependencies** *(run this after installing new packages)*

```bash
pip freeze > requirements.txt
```

**4. Start the local server**

```bash
uvicorn main:app --reload
```

---

## 🔄 Refreshing Data

To keep bus data up to date, trigger the following endpoints **in this exact order**:

| Step | Description | Endpoint |
|------|-------------|----------|
| 1 | Extract all available buses | `GET /extractBusRoutesData` |
| 2 | Extract bus services | `GET /getBusServicesData?overwrite=true` |
| 3 | Update bus stops | `GET /extractBusStops` |

> ⚠️ **Order matters.** Running these out of sequence may result in incomplete or inconsistent data.

---

## 🚀 Deployment

This project deploys on [Fly.io](https://fly.io).

**1. Authenticate the Fly CLI** *(skip if already logged in)*

```bash
fly auth login
```

**2. Deploy**

```bash
fly deploy
```