# Infrastructure

`terraform/` now separates durable shared Azure resources from application compute. Azure changes
remain manual and out of CI. Follow its [Terraform guide](terraform/README.md) and the
[compute lifecycle runbook](../docs/deployment/azure-terraform-lifecycle.md) before any import,
state handoff, teardown, or recreation.
