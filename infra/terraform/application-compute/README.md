# Application compute

This root uses its own Azure Blob state key and reads shared resources through Azure data sources. It owns only the existing B1 Linux App Service/API, two `restart_policy = "Never"` ACI workers, and the frontend Container App after the documented handoff.

The checked-in `imports.tf` records the existing compute resources for plan-reviewed adoption. Do not apply it before completing the documented frontend handoff: the shared root must first detach the old frontend address with its `destroy = false` removed block. The ACI secure environment values are deliberately absent: Terraform must never contain database or fal credentials.

The worker target command uses `app.workers.aci_bootstrap`, which is included only in a backend image built from this revision or later. The current deployed image predates that script. Import/adoption is safe because ACI commands and environment settings are ignored until the live command is inventoried, but clean worker recreation is not approved until a bootstrap-enabled immutable image has been built and tested.
