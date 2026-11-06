# Real data snapshot

What the server trains and advises from when `SHAMBA_DEMO=0`. `python -m shambasense.cli load-real`
loads it (the server's `bootstrap` does this automatically and removes any SYNTHETIC demo data).

| File | What | Source and licence |
| --- | --- | --- |
| `harveststat_kenya_study_counties.csv` | County area, production and yield, 1971-2024, for the four study counties and six crops | HarvestStat Africa (Lee et al., 2025, *Scientific Data*), compiled by FEWS NET from Ministry of Agriculture county statistics. [github.com/HarvestStat/HarvestStat-Africa](https://github.com/HarvestStat/HarvestStat-Africa), MIT licence |
| `climate_daily.csv.gz`, `locations.csv` | Daily rain and temperature for each county, averaged over its reference points, from 1981 | NASA POWER (community AG). "These data were obtained from the NASA Langley Research Center POWER Project funded through the NASA Earth Science Directorate Applied Science Program." |
| `soil_profile.csv` | Topsoil (0-30 cm) pH, organic carbon, nitrogen, clay, sand, CEC per county | ISRIC SoilGrids v2.0, CC BY 4.0 |
| `wfp_food_prices_kenya.csv` | WFP market prices for the study crops | World Food Programme VAM, via HDX, CC BY-IGO |
| `snapshot.json` | When the weather and soil were fetched, and their date range | |

Refresh the weather, soil and prices with the **Fetch open data** workflow (Actions tab), or by
changing `REFRESH`. Yields are cleaned on loading; the rules are in `shambasense/ingest/harveststat.py`.
