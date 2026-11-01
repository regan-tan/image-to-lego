# ADR-007: Container Apps frontend hosting

## Status

Accepted for the Azure for Students development subscription

## Context

ADR-004 selected Azure Static Web Apps for the React/Vite frontend. The current Azure for Students
subscription has an `Allowed resource deployment regions` policy that permits Japan East, Malaysia
West, Indonesia Central, Central India, and Korea Central. Azure reports Static Web Apps control-plane
availability only in Central US, East US 2, West US 2, West Europe, and East Asia. There is no overlap,
so the Static Web Apps resource would be denied by policy.

## Decision

Supersede only the frontend-hosting portion of ADR-004 for this subscription. Host the built React/Vite
SPA in a fourth Azure Container App in the existing Container Apps environment. The container uses
Nginx, public HTTPS ingress, a 0.25 vCPU/0.5 GiB limit, and a zero-to-one replica range. It pulls from
the same Basic ACR using a dedicated identity that has only `AcrPull`.

Nginx serves the SPA fallback for client-side routes and proxies `/api` internally to the FastAPI
Container App by its Container Apps service-discovery name. Its runtime-generated configuration file
contains only browser-visible settings: the `/api` base path and optional Supabase URL/publishable key.

## Consequences

This keeps the deployment in one permitted region and avoids introducing another hosting product. It
adds a small Container Apps consumption charge when the frontend is active, rather than using the
Static Web Apps Free tier. The frontend is no longer built by Static Web Apps; its image must be built
and pushed to ACR before the application-stage Terraform apply. A future subscription with an eligible
Static Web Apps region may revisit this decision through a new ADR.
