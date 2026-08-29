# Azure Container App API

The current Static Web Apps managed API remains production until this container
revision passes its direct health, Tailscale, LINE callback, and linked-backend
smoke tests.

## GitHub repository variables

Create these repository-level variables (not environment-only variables, because
the deploy job checks them before it starts):

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `ACR_LOGIN_SERVER` = `a9acr.azurecr.io`
- `AZURE_CONTAINER_APP_NAME` = `a9badminton`
- `AZURE_RESOURCE_GROUP` = `badminton`

The federated identity needs `AcrPush` on `a9acr` and `Container Apps
Contributor` on `a9badminton` or its resource group. The Container App's own
managed identity needs `AcrPull` on the registry.

## First image deployment

The `Container App API` workflow builds every pull request. On `main`, it signs
in with OIDC, pushes `badminton-api:<full-git-sha>`, updates the app, enables
HTTPS ingress on port 80, and verifies `/api/health`.

The workflow intentionally skips Azure deployment until all six variables
exist. It never uses a mutable `latest` tag.

## Secrets and Tailscale revision

Create every secret referenced by `revision.template.yaml` in the Container App.
Do not commit secret values. Replace `IMAGE_TAG` with an image SHA already present
in ACR, then apply the two-container revision:

```bash
az containerapp update \
  --name a9badminton \
  --resource-group badminton \
  --yaml infra/container-app/revision.template.yaml
```

The API uses the Tailscale userspace HTTP proxy at `127.0.0.1:1055` only for the
private HTTP gateway. LINE, Azure Storage, GitHub, and Tavily HTTPS calls remain
direct. Restrict `tag:azure-container-apps` in the tailnet ACL to
`nv-ws-tommy:8791`.
