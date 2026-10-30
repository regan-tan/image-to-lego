# Shared infrastructure

This root retains the existing remote state key and resource addresses for durable resources. All managed durable resources have `prevent_destroy`; application compute cannot delete the resource group, Blob artifacts, queues, ACR, Key Vault, identities, RBAC, logging, or the Container Apps environment.

Copy the ignored backend and variable templates locally, retaining the current backend key. Do not initialize a new state for this root. The current frontend address is intentionally detached with `destroy = false` only as part of the separately reviewed frontend handoff.
