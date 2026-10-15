# LEGO catalogue

`parts.json` is the small, human-maintained source for verified LEGO part metadata.
Each part's `verifiedColorIds` contains only canonical LDraw colour IDs for combinations
verified as manufactured in the BrickLink reference catalogue's **Known Colors** view.
The snapshot was checked on 2026-10-15 against the part pages identified by each record's
`bricklinkId`; the supported colour IDs are defined in `backend/app/conversion/colors.py`.

This is a catalogue-history assertion only: a verified pair was manufactured. It does not
mean the pair is currently sold by LEGO, listed on BrickLink or Rebrickable, in stock,
affordable, or available in a particular country. No runtime catalogue lookup or scraping occurs.

Run the following from the repository root after changing it:

```powershell
uv run --project backend python scripts/build_lego_catalogue.py
```

The generated runtime file is `backend/app/conversion/generated_part_catalogue.json`; application code reads that file, not this source file. The builder rejects unknown or duplicate `verifiedColorIds`, and fitter-enabled parts with no verified colours. `fitterEnabled` controls whether the current converter may place a part. Catalogue membership does not imply fitter support or current marketplace stock. LDraw and BrickLink IDs identify different external ecosystems and must not be assumed equal.
