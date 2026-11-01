# Azure Terraform

Use one independent root at a time:

| Root | State | Ownership |
| --- | --- | --- |
| [`shared/`](shared/README.md) | Existing shared key, unchanged | Durable Azure resources and Container Apps environment |
| [`application-compute/`](application-compute/README.md) | `image-to-lego-dev-application-compute.tfstate` | App Service API, two ACI workers, frontend Container App |

The old stage switch was removed because a default value could plan deletion of the live frontend. The exact handoff/import and teardown procedure is in [the lifecycle runbook](../../docs/deployment/azure-terraform-lifecycle.md). It is documentation only: none of those commands have been executed from this repository change.
