# Saor project notes

- Keep scheme facts in `config/` and label their source, check date and confidence.
- Never put passwords, keys, real personal data or invitation tokens in source files.
- The BTWEA allowance is personal support, never business turnover.
- Preserve the exact trading and Revenue timing notices in `config/texts.yaml`.
- Treat all eligibility, risk and projection results as indicative.
- Business rules belong in `app/services/`; route handlers should save inputs and render pages.
- Use Python 3.15.0, Flask 3 and pinned dependencies from `requirements.txt`.
- Invitations are saved locally as `.eml` files. Do not add real email sending.
- Local database, uploads and outbox data are inside ignored `instance/`.

Run `flask --app app db upgrade`, `flask --app app seed`, and `flask --app app run` after installing requirements and setting a local `.env`.
