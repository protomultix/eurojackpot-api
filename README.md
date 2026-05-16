# Eurojackpot Static API

A small GitHub template that builds a static JSON/CSV API for Eurojackpot results.
GitHub Actions downloads the LOTTO Bayern archive, parses the draw numbers, and publishes the files through GitHub Pages.

Data source:

```text
https://www.lotto-bayern.de/static/gamebroker_2/de/download_files/archiv_eurojackpot.zip
```

Not affiliated with LOTTO Bayern. Data is provided without warranty: `Alle Angaben ohne Gewähr`.

## API

```text
/api/latest.json
/api/draws.json
/api/draws.csv
/api/stats.json
/api/by-date/YYYY-MM-DD.json
/api/meta.json
/api/openapi.json
```

Example:

```bash
curl https://<your-github-username>.github.io/<repo-name>/api/latest.json
```

## Setup

1. Create a new GitHub repository.
2. Copy these files into it.
3. Go to **Settings → Pages** and select **GitHub Actions** as the source.
4. Run **Actions → Update Eurojackpot API → Run workflow**.

Your API will be available at:

```text
https://<your-github-username>.github.io/<repo-name>/api/latest.json
```

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/update_eurojackpot.py
python -m http.server 8000 --directory public
```

Open:

```text
http://localhost:8000/api/latest.json
```

## Configuration

The default start date is set in `.github/workflows/update-api.yml`:

```yaml
env:
  START_DATE: "2022-03-25"
```
