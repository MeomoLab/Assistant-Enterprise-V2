# Saor

**Prepare your enterprise application, your own way.**

Saor is an independent preparation tool for people exploring the Back to Work Enterprise Allowance (BTWEA) while planning a vegan food business. It is not part of Intreo, the Department of Social Protection or any Local Development Company. It does not guarantee approval and never submits your information.

## Start the demo

The demo uses fictional accounts and business data. It is seeded into a local database; a generated demo password is printed in the terminal and is not stored in this folder.

1. Use Python 3.15.0. Docker is also supported if available.
2. In a terminal, go to this `saor-poc` folder.
3. Create the local settings file and replace the placeholder secret:

   ```sh
   cp .env.example .env
   ```

   Set `SECRET_KEY` in `.env` to a long random value. The app refuses to start with the placeholder.
4. Create a virtual environment and install the pinned packages:

   ```sh
   python3.15 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
5. Create the database and load the fictional demo:

   ```sh
   .venv/bin/flask --app app db upgrade
   .venv/bin/flask --app app seed
   ```

   The seed prints three demo account emails and their shared demo-only password. The accounts are fictional. Keep the terminal output private while the demo is running.
6. Start Saor:

   ```sh
   .venv/bin/flask --app app run
   ```

7. Open [http://localhost:5000](http://localhost:5000) and sign in as the demo applicant.

To use Docker, create `.env` as above, then run `docker compose up --build`. In a second terminal run `docker compose exec web flask seed`. The database and uploads are stored under `instance/`.

## Main areas

- Roadmap and eligibility pre-check
- Business profile, market research and food guide
- Product costing, weekly capacity and a 24-month projection
- Indicative risk flags, pack checklist and copy helpers
- Read-only mentor sharing and a print-friendly dossier
- Administrator invitations recorded as `.eml` files in `instance/outbox/`; no email is sent

Rules and source links are kept in `config/`. The app labels indicative, unverified and LDC guidance items. The official process and eligibility decision remain with the relevant authorities.

Run the calculation checks with:

```sh
.venv/bin/python -m pytest
```

## Local data

The SQLite database, uploads, and invitation messages live in `instance/`. They are excluded by `.gitignore`. The app collects only the details needed for this demo. Do not enter real personal data. The privacy notice is a draft and needs owner review before any real pilot.

## Project map

```text
app/              Flask pages, models, access checks, calculations
config/           Scheme values, notices, roadmap, links and form helpers
migrations/       Database schema migration
seeds/            Fictional demo workspace
tests/            Small checks for the pure calculation rules
```

The privacy notice is a draft for owner review. Use only fictional data in this proof of concept.
