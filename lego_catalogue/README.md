# LEGO catalogue

`parts.json` is the small, human-maintained source for verified LEGO part metadata.
Each part's `verifiedColorIds` contains only canonical LDraw colour IDs for combinations
verified as manufactured in the BrickLink reference catalogue's **Known Colors** view.
The snapshot was checked on 2026-10-15 against the part pages identified by each record's
`bricklinkId`; the supported colour IDs are defined in `backend/app/conversion/colors.py`.

This is a catalogue-history assertion only: a verified pair was manufactured. It does not
mean the pair is currently sold by LEGO, listed on BrickLink or Rebrickable, in stock,
affordable, or available in a particular country. No runtime catalogue lookup or scraping occurs.

Canonical `partId` and `colorId` values remain the application's stable identities: part IDs come
from this catalogue and colour IDs use the `ldraw:` namespace. BrickLink part IDs are explicit
catalogue fields, while BrickLink colour IDs are explicit fields in
`backend/app/conversion/colors.py`; neither is inferred from a canonical ID. Converted LEGO-model
JSON carries these mappings when known so the browser can produce a verified-manufactured sourcing
CSV. The CSV is not a BrickLink wanted-list import and does not make any availability claim.

Run the following from the repository root after changing it:

```powershell
uv run --project backend python scripts/build_lego_catalogue.py
```

The generated runtime file is `backend/app/conversion/generated_part_catalogue.json`; application code reads that file, not this source file. The builder rejects unknown or duplicate `verifiedColorIds`, and fitter-enabled parts with no verified colours. `fitterEnabled` controls whether the current converter may place a part. Catalogue membership does not imply fitter support or current marketplace stock. LDraw and BrickLink IDs identify different external ecosystems and must not be assumed equal.
