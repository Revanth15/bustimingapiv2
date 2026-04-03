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

| Step | Description | Endpoint / Action |
|------|-------------|------------------|
| 1 | Extract all available buses | `GET /extractBusRoutesData` |
| 2 | Extract bus services | `GET /getBusServicesData?overwrite=true` |
| 3 | Update bus stops | `GET /extractBusStops` |
| 4 | Extract raw bus route data | `GET /extractBusRoutesRawData` |
| 5 | Run comparison script | Execute Python script to compare latest vs outdated data |
| 6 | Generate polylines for new services | `POST /bus-routes/polylines` (use output list `c`) |
| 7 | Bulk update bus routes | `POST /bulkUpdateBusRoutes` (use response from Step 6) |
| 8 | Remove obsolete services | `DELETE /bus-routes` (use output list `d`) |

> ⚠️ **Order matters.** Running these out of sequence may result in incomplete or inconsistent data.

## 📌 Notes on Script Output

- `c` → **New bus services**  
  - Send this list to: `POST /bus-routes/polylines`

- `d` → **Removed / obsolete bus services**  
  - Send this list to: `DELETE /bus-routes`

---

## ⚙️ End-to-End Flow Summary

1. Refresh raw data (Steps 1–4)  
2. Run script to compute differences  
3. Generate and insert polylines for new services  
4. Remove outdated services 

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