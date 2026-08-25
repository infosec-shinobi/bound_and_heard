# MVP 9 Checklist

## Goal

Create an easy-to-deploy, secure, and recoverable application deployment model for self-hosted use.

## Source

Derived from `docs/ROADMAP.md` MVP 9 - Operationalize, with continuity from earlier local-first data preservation, write protection, scraping, enrichment, analytics, recaps, and recommendations.

## Chunk 1 - Deployment Scope And Decisions

- [ ] Decide supported deployment target for MVP 9: single-container SQLite, Compose with SQLite volume, or Compose with optional Postgres
- [ ] Decide whether Postgres remains future work or becomes an optional MVP 9 deployment path
- [ ] Define supported host assumptions: local machine, LAN server, NAS, or VPS
- [ ] Define required persistent paths for database, imports, scraped snapshots, browser profile, recaps, exports, and logs
- [ ] Define which paths may contain private Libby/account data
- [ ] Define default port and network exposure expectations
- [ ] Define upgrade compatibility expectations for migrations and data volumes
- [ ] Document operational assumptions before building deployment artifacts

## Chunk 2 - Container Image

- [ ] Add Dockerfile
- [ ] Use a slim Python base image or equivalent minimal runtime
- [ ] Install only runtime dependencies in the final image
- [ ] Install Playwright browser/runtime dependencies needed for Libby scraping if scraping is supported in-container
- [ ] Run the application as a non-root user
- [ ] Set a safe working directory and writable data directory
- [ ] Expose only the application port
- [ ] Add container labels or metadata if useful
- [ ] Keep image build reproducible from locked dependency inputs where practical
- [ ] Add tests or CI command to verify the image builds

## Chunk 3 - Runtime Configuration

- [ ] Document required environment variables
- [ ] Document optional environment variables and defaults
- [ ] Require `BOUND_AND_HEARD_ADMIN_PASSWORD` for write-enabled deployments
- [ ] Require or generate guidance for `BOUND_AND_HEARD_SESSION_SECRET`
- [ ] Support configuring `BOUND_AND_HEARD_DATABASE_URL`
- [ ] Support configuring imports, scraped, browser profile, recap, and export directories where applicable
- [ ] Provide `.env.example` or deployment env template without secrets
- [ ] Ensure missing admin password still starts read-only rather than insecurely write-enabled
- [ ] Add configuration validation or startup warnings for unsafe deployment settings

## Chunk 4 - Compose Deployment

- [ ] Add Docker Compose example
- [ ] Mount persistent application data volume
- [ ] Include environment variable template usage
- [ ] Include health check
- [ ] Include restart policy appropriate for self-hosting
- [ ] Avoid exposing unnecessary services or ports
- [ ] Add optional profile or notes for reverse proxy use
- [ ] Add startup instructions for first-run admin setup
- [ ] Add update instructions for pulling/rebuilding and restarting

## Chunk 5 - Startup, Health, And Migrations

- [ ] Add container startup command or entrypoint
- [ ] Run Alembic migrations safely at startup or document explicit migration command
- [ ] Avoid destructive schema/data operations during startup
- [ ] Add health endpoint if current routes are not appropriate for container health checks
- [ ] Ensure health check does not require admin login
- [ ] Log startup configuration summary without leaking secrets
- [ ] Log clear warnings for read-only mode and missing optional paths
- [ ] Add tests or smoke checks for migration/startup behavior

## Chunk 6 - Backup Strategy

- [ ] Identify all data needed for a complete backup
- [ ] Add backup script for SQLite database and local data directories
- [ ] Ensure backup script handles a running application safely or documents downtime requirement
- [ ] Include raw imports, scraped snapshots, browser profile, recaps, and exports when requested
- [ ] Exclude cache/temp files that are safe to regenerate
- [ ] Include manifest with timestamp, app version or git SHA, database URL/type, and included paths
- [ ] Support configurable backup destination
- [ ] Avoid writing secrets into backup logs
- [ ] Add tests or dry-run mode for backup script

## Chunk 7 - Restore Strategy

- [ ] Add restore script or documented restore procedure
- [ ] Validate backup manifest before restoring
- [ ] Stop or warn about running application before restore if needed
- [ ] Restore database and selected data directories predictably
- [ ] Preserve existing data by refusing overwrite unless explicitly confirmed
- [ ] Run migrations after restore when needed
- [ ] Add dry-run restore or verification mode
- [ ] Document full restore procedure from a fresh host
- [ ] Add tests or smoke checks for restore flow where practical

## Chunk 8 - Security Hardening

- [ ] Run container as non-root
- [ ] Keep secrets in environment variables or external secret files, not committed config
- [ ] Document strong admin password and session secret requirements
- [ ] Document private-network and reverse-proxy/TLS recommendations
- [ ] Avoid logging admin password, session secret, Libby cookies, or raw private scraped content
- [ ] Keep browser profile and scraped data in persistent private storage
- [ ] Document file permissions for mounted data directories
- [ ] Consider read-only root filesystem compatibility if practical
- [ ] Add dependency vulnerability scanning guidance if tooling is available

## Chunk 9 - Observability And Troubleshooting

- [ ] Document where application logs are written or streamed
- [ ] Document how to inspect container logs
- [ ] Document common startup failures and fixes
- [ ] Document common migration failures and recovery steps
- [ ] Document common Playwright/browser-profile deployment failures and fixes
- [ ] Document how to confirm the app is in read-only mode versus write-enabled mode
- [ ] Document health check behavior
- [ ] Add a lightweight operational smoke-test command

## Chunk 10 - Upgrade Workflow

- [ ] Document backup-before-upgrade workflow
- [ ] Document image pull or rebuild workflow
- [ ] Document migration behavior during upgrade
- [ ] Document rollback limitations after migrations
- [ ] Preserve persistent volumes across upgrades
- [ ] Add upgrade smoke test checklist
- [ ] Document how to verify app version or deployed build

## Chunk 11 - Tests And Verification

- [ ] Verify Docker image builds
- [ ] Verify Compose deployment starts locally
- [ ] Verify health check passes
- [ ] Verify app starts read-only when admin password is missing
- [ ] Verify app allows admin login when password and session secret are configured
- [ ] Verify mounted data persists after container restart
- [ ] Verify Alembic migrations run in deployment flow
- [ ] Verify backup script creates expected artifact and manifest
- [ ] Verify restore procedure can recover onto a fresh data directory
- [ ] Verify Playwright scraping setup still works or is clearly documented as host-only/manual if not supported in-container
- [ ] Verify full `pytest` pass

## Chunk 12 - Documentation

- [ ] Update README with container deployment quickstart
- [ ] Document Docker Compose deployment
- [ ] Document environment variables and secret handling
- [ ] Document persistent volume layout
- [ ] Document backup and restore workflows
- [ ] Document upgrade workflow
- [ ] Document security recommendations
- [ ] Document troubleshooting guidance
- [ ] Update architecture documentation for operational deployment model

## MVP 9 Done Criteria

- [ ] User can build or pull a container image for the app
- [ ] User can run the app through Docker Compose with persistent storage
- [ ] User can configure admin password, session secret, database URL, and data paths without editing code
- [ ] Container runs with secure defaults, including non-root runtime and no unnecessary exposed ports
- [ ] App starts in read-only mode when admin password is missing
- [ ] Health check reports whether the app is running
- [ ] Database migrations are handled safely in the deployment workflow
- [ ] User can create a backup of the database and selected local data directories
- [ ] User can restore a backup onto a fresh data directory or host
- [ ] User can upgrade the deployment without losing persistent data
- [ ] Deployment docs explain private data, secrets, reverse proxy/TLS, backups, restores, and troubleshooting
- [ ] Basic tests and deployment smoke checks pass
