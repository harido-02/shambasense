# ShambaSense

ShambaSense recommends which crops a Kenyan farmer should plant in the coming season, when to plant them, how much they are likely to harvest and what they are likely to earn. It combines soil data, seasonal rainfall forecasts, a machine learning yield model trained on county crop statistics, and market prices.

**Live:** https://shambasense.onrender.com (admin dashboard at `/admin`). The hosted copy runs on synthetic test data until real KilimoSTAT yields are loaded, and Render's free plan sleeps after 15 minutes without visitors, so the first visit can take about a minute.

Farmers reach it three ways:

- **Web app**, installable on any phone from the browser (works offline with the last results).
- **Android app** (APK), built from the same interface with Capacitor.
- **USSD menu** for basic phones, through Africa's Talking.

Inside the app: crop advice with a season calendar, farmer accounts (phone number + PIN), saved farms, SMS planting reminders, market price trends, a 14-day weather forecast, advice history and feedback, all in English and Kiswahili. An **admin dashboard** at `/admin` shows usage, feedback and SMS, takes KMD seasonal outlooks and retrains the model.

Final-year Computing Science project, Riara University, 2026. Study area: Trans Nzoia, Nakuru, Meru and Machakos counties. Crops: maize, beans, Irish potatoes, sorghum, green grams and tomatoes.

## How it works

1. **Data pipeline.** Daily weather from NASA POWER (and Kenya Meteorological Department stations where supplied), topsoil properties from SoilGrids, county yields from the Ministry of Agriculture's KilimoSTAT, prices from KAMIS, and seasonal outlooks from KMD or ECMWF SEAS5. Everything is stored in SQLite or PostgreSQL.
2. **Features.** For each county, year and crop: rainfall, rainy days, longest dry spell and temperature over the crop's own growing period (from the onset of rains to maturity), the onset delay, topsoil pH, organic carbon, nitrogen, CEC and texture, and an FAO EcoCrop-style suitability score.
3. **Yield model.** Gradient-boosted quantile regression (scikit-learn) predicts the 10th, 50th and 90th percentile of yield relative to each crop's average. It is evaluated by leave-one-year-out and leave-one-county-out cross-validation against a county-average baseline, ridge regression and a random forest, and its intervals are calibrated to cover 80% of outcomes.
4. **Recommendation.** Every past season at the farm becomes a scenario. Each scenario is weighted by how likely the seasonal outlook makes its rainfall tercile, the model predicts every crop's yield in each scenario, and Monte Carlo sampling turns these into yield and profit ranges and a probability of loss. Crops are ranked by suitability and risk first, then by expected gross margin. Each recommendation explains itself: the limiting factor, the main model drivers, the price and the risk.

## Quick start (demo on synthetic data)

**Windows:** double-click `run_demo.bat` (or run it from Anaconda Prompt). The first run installs everything and trains the demo model in about five minutes, then opens the app in your browser.

Manual setup needs Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Load the **synthetic** test data, train, and serve, using a separate demo database:

```bash
# macOS / Linux
export DATABASE_URL=sqlite:///data/demo.db
# Windows PowerShell
$env:DATABASE_URL = "sqlite:///data/demo.db"

python -m shambasense.cli ingest-sample
python -m shambasense.cli train
python -m shambasense.cli serve
```

Open http://127.0.0.1:8000 for the web app and http://127.0.0.1:8000/docs for the API. A yellow banner marks demo mode. **Never report results from synthetic data**; it exists only so the system can be built and tested before real data arrives.

## Real data workflow

Use the default database (unset `DATABASE_URL`, or point it at PostgreSQL).

```bash
python -m shambasense.cli ingest-live                       # NASA POWER + SoilGrids for all four counties (internet)
python -m shambasense.cli load-yields data/raw/kilimostat.csv --format kilimostat
python -m shambasense.cli load-yields data/raw/county_yields.csv           # anything transcribed from reports
python -m shambasense.cli load-kmd data/raw/kmd_stations.csv              # optional, improves rainfall
python -m shambasense.cli load-prices data/raw/kamis.csv
python -m shambasense.cli load-costs data/raw/costs.csv
python -m shambasense.cli load-outlooks data/raw/kmd_outlook.csv
python -m shambasense.cli status                            # check what is loaded
python -m shambasense.cli build-dataset                     # writes data/processed/training_table.csv
python -m shambasense.cli train                             # cross-validates, trains, saves, draws figures
python -m shambasense.cli recommend --county machakos --season short_rains
```

Column layouts for every file are in `data/templates/`. Loaders match column names loosely, convert units (90 kg bags, acres, kg/ha) and log anything they skip.

Before reporting results, check the crop requirement ranges in `config/crops.yaml` against FAO EcoCrop and KALRO guides and set `verified: true`, and confirm the reference coordinates in `config/counties.yaml`.

## Accounts, reminders and the admin dashboard

- Farmers create an account with a Kenyan mobile number and a 4-digit PIN. PINs are stored as salted scrypt hashes; five wrong PINs lock the account for 15 minutes.
- Create an administrator: `python -m shambasense.cli create-admin --phone 07XXXXXXXX --pin XXXX`, then sign in at `/admin`. On a hosted server, set `ADMIN_PHONE` and `ADMIN_PIN` instead.
- SMS reminders go out three days before the usual start of the planting rains. Set `AT_USERNAME` and `AT_API_KEY` (Africa's Talking; `sandbox` for testing) to send them; without keys they are logged in the dashboard but not sent. The server checks for due reminders every hour; `python -m shambasense.cli send-reminders` or the dashboard button sends them on demand.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Status, whether a model is loaded, and whether it was trained on real or synthetic data |
| GET | `/api/counties`, `/api/crops` | Study counties and crop requirements |
| POST | `/api/recommend` | Advice for `{lat, lon}` or `{county}`, with optional `season`, `year`, `lang` (`en`/`sw`) and an `outlook` override for what-if analysis |
| GET | `/api/recommend` | Same, with query parameters (used by the web app) |
| GET | `/api/outlook/{county}` | The seasonal outlook in use and the rainfall terciles it refers to |
| GET | `/api/model` | Training data summary, cross-validation metrics, feature importance |
| GET | `/api/prices`, `/api/prices/summary` | Monthly price series per crop; latest price and 12-month change for every crop |
| GET | `/api/weather` | 14-day rain and temperature forecast for a point or county |
| POST | `/api/auth/register`, `/api/auth/login`, `/api/auth/logout` | Phone + PIN accounts (bearer token) |
| GET/PATCH | `/api/me`, `/api/me/history` | Profile, language, SMS opt-in, past advice |
| GET/POST/PATCH/DELETE | `/api/farms`, `/api/farms/{id}/advice`, `/api/farms/{id}/reminders` | Saved farms, their advice and SMS reminders |
| GET/POST | `/api/admin/*` | Dashboard statistics, feedback, users, SMS log, outlooks, retraining (administrators only) |
| POST | `/api/admin/outlook` | Enter a KMD outlook (header `X-Admin-Token`) |
| POST | `/api/feedback` | Record what a farmer planted and how it went |
| POST | `/ussd` | Africa's Talking USSD callback |

Full schemas are at `/docs` when the server is running.

## USSD (Africa's Talking sandbox)

1. Create a sandbox app at africastalking.com and a USSD channel (for example `*384*1234#`).
2. Expose the server with a public HTTPS URL (deploy it, or run `ngrok http 8000` locally).
3. Set the channel's callback URL to `https://<your-host>/ussd`.
4. Dial the code in the sandbox simulator: choose a language, a county and a season; the reply lists the top three crops with expected bags per acre and the planting window.

Phone numbers are never stored; logs keep only a salted hash, in line with the Data Protection Act, 2019.

## Deploy online (Render, free)

1. Put this folder in a GitHub repository.
2. Sign in to [render.com](https://render.com) with GitHub, choose **New → Blueprint**, pick the repository and apply. `render.yaml` creates the web service and a PostgreSQL database.
3. In the web service's **Environment**, set `ADMIN_PHONE` and `ADMIN_PIN` (and Africa's Talking keys when you have them), then redeploy.
4. The app is live at `https://<service-name>.onrender.com`; the dashboard is at `/admin`.

The Docker image trains the demo model while it builds, and every start runs `bootstrap`, which loads data and creates the admin account if they are missing. `SHAMBA_DEMO=1` keeps the hosted copy on the synthetic test data; set it to `0` after loading real yields and retraining from the dashboard. Render's free service sleeps after 15 minutes without visitors (the first visit then takes about a minute), and its free database expires after 30 days.

**Docker on any machine:** `cp .env.example .env`, set the passwords, then `docker compose up -d`.

## Android app

`mobile/` packages the web app with [Capacitor](https://capacitorjs.com). The GitHub workflow `.github/workflows/android.yml` builds the APK on every push and publishes it on the **android-latest** release:

1. In the GitHub repository, add the variable `SHAMBA_API_BASE` (Settings → Secrets and variables → Actions → Variables) with the hosted address, `https://shambasense.onrender.com`. Until it is set, the workflow skips automatic builds.
2. Run the **Android APK** workflow (Actions tab), or push a change.
3. Download `ShambaSense.apk` from the release on an Android phone and open it; allow installing from this source when asked.

To build locally instead, install Node 22, JDK 21 and Android Studio, then: `cd mobile && npm ci && SHAMBA_API_BASE=https://… npm run sync && npx cap open android`.

## Tests

```bash
python -m pytest -q
```

51 tests cover suitability rules, onset detection, API parsers, file loaders, the model, the recommendation engine, accounts and PIN lockout, farms, reminders and SMS, prices, weather, the admin API, the web app files, the REST API and the USSD flow, on an isolated synthetic database. Set `TEST_DATABASE_URL` to run them against PostgreSQL. GitHub Actions runs them on every push.

## Project layout

```
config/            settings, counties, crop requirements
shambasense/
  ingest/          NASA POWER, SoilGrids, Open-Meteo, agency file loaders, synthetic data
  features/        onset of rains, growing-period weather, training table
  models/          suitability rules, quantile yield model, evaluation
  recommend/       location, seasonal outlook, ranking engine, English/Kiswahili text
  services/        accounts, SMS, reminders, prices, weather, admin
  api/             FastAPI app, routes, USSD handler
  cli.py           command line for the whole pipeline
web/               installable web app and admin dashboard (no build step)
mobile/            Android app (Capacitor) and its icons
.github/workflows/ tests and the Android APK build
render.yaml        one-click hosting on Render
tests/             pytest suite
data/templates/    CSV layouts for agency data
reports/figures/   evaluation charts written by `train`
```

## Data sources and attribution

- NASA POWER: "These data were obtained from the NASA Langley Research Center POWER Project funded through the NASA Earth Science Directorate Applied Science Program."
- SoilGrids v2.0, ISRIC World Soil Information (CC BY 4.0).
- ECMWF SEAS5 seasonal forecasts via Open-Meteo (CC BY 4.0).
- KilimoSTAT, Ministry of Agriculture and Livestock Development.
- KAMIS, Kenya Agricultural Market Information System.
- Kenya Meteorological Department station data and seasonal outlooks.
- Crop requirement ranges adapted from FAO EcoCrop (to be verified).

## Known limitations

- County yields are annual and county-wide, so the model learns between-year and between-county differences, not field-level ones. Predictions for a specific point use that point's weather and soil but a model trained at county scale.
- Most crops in the study area are rain-fed; tomatoes are often irrigated, which the model does not represent.
- Seasonal forecasts have modest skill in East Africa; ShambaSense treats them as odds, never as certainties.
- Kiswahili text should be checked by a fluent speaker before release.
