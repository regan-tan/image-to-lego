# LEGO catalogue

`parts.json` is the small, human-maintained source for verified LEGO part metadata.
Each part's `verifiedColorIds` contains only canonical LDraw colour IDs for combinations
verified as manufactured in the BrickLink reference catalogue's **Known Colors** view.
The snapshot was checked on 2026-10-15 against the part pages identified by each record's
`bricklinkId`; part `15068` was added from the same **Known Colors** view on 2026-10-16 and
the 41769/41770 wedge pair was checked on 2026-10-17.
The supported colour IDs are defined in `backend/app/conversion/colors.py`.

For `15068`, the retrieved record was BrickLink's
[Slope, Curved 2 x 2 x 2/3](https://www.bricklink.com/v2/catalog/catalogitem.page?P=15068)
catalogue page (Item No. `15068`). The checked-in IDs are the complete intersection of that
page's **Known Colors** list with the project's versioned canonical colour catalogue. This is a
manual, versioned source snapshot: updating it means revisiting that exact Known Colors view,
mapping its names through `colors.py`'s explicit BrickLink colour IDs, and checking in the
resulting `verifiedColorIds`; the application never scrapes BrickLink at runtime.

For the wedge pair, the retrieved records were BrickLink's
[41769 right wedge plate](https://www.bricklink.com/v2/catalog/catalogitem.page?P=41769) and
[41770 left wedge plate](https://www.bricklink.com/v2/catalog/catalogitem.page?P=41770). Each
record's supported IDs are the complete intersection of its **Known Colors** list with the
project's canonical palette: `ldraw:0`, `ldraw:15`, `ldraw:71`, `ldraw:72`, `ldraw:4`,
`ldraw:320`, `ldraw:25`, `ldraw:14`, `ldraw:19`, `ldraw:70`, `ldraw:2`, `ldraw:288`,
`ldraw:27`, `ldraw:1`, and `ldraw:272`. Dark Brown (`ldraw:308`) and every palette colour not
in those two Known Colors lists remain unsupported.

This is a catalogue-history assertion only: a verified pair was manufactured. It does not
mean the pair is currently sold by LEGO, listed on BrickLink or Rebrickable, in stock,
affordable, or available in a particular country. No runtime catalogue lookup or scraping occurs.

Canonical `partId` and `colorId` values remain the application's stable identities: part IDs come
from this catalogue and colour IDs use the `ldraw:` namespace. BrickLink part IDs are explicit
catalogue fields, while BrickLink colour IDs are explicit fields in
`backend/app/conversion/colors.py`; neither is inferred from a canonical ID. Converted LEGO-model
JSON carries these mappings when known so the browser can produce a verified-manufactured sourcing
CSV. The CSV is not a BrickLink wanted-list import and does not make any availability claim.

`ldrawId` is the explicit visual-source identity, not an alias for `partId` or `bricklinkId`.
For example, catalogue identities `41769` and `41770` render from LDraw's non-chamfer source
variants `41769a` and `41770a` respectively; the LDraw `b` files are separate chamfered visual
variants. See `part_geometry/README.md` for the source decision. Both catalogue entries remain
source-only with `fitterEnabled: false`.

Run the following from the repository root after changing it:

```powershell
uv run --project backend python scripts/build_lego_catalogue.py
```

The generated runtime file is `backend/app/conversion/generated_part_catalogue.json`; application code reads that file, not this source file. The builder rejects unknown or duplicate `verifiedColorIds`, and fitter-enabled parts with no verified colours. `fitterEnabled` controls whether the current converter may place a part. Catalogue membership does not imply fitter support or current marketplace stock. LDraw and BrickLink IDs identify different external ecosystems and must not be assumed equal.
