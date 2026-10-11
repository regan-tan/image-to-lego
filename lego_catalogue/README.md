# LEGO catalogue

`parts.json` is the small, human-maintained source for verified LEGO part metadata. Run the following from the repository root after changing it:

```powershell
uv run --project backend python scripts/build_lego_catalogue.py
```

The generated runtime file is `backend/app/conversion/generated_part_catalogue.json`; application code reads that file, not this source file. `fitterEnabled` controls whether the current converter may place a part. Catalogue membership does not imply fitter support or current marketplace stock. LDraw and BrickLink IDs identify different external ecosystems and must not be assumed equal.
