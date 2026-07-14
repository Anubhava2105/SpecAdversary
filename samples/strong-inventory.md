# Offline-first inventory counts for independent grocers

## Problem
Store managers spend 6-10 hours each week reconciling shelf counts. Barcode scans are unreliable in walk-in coolers with weak Wi-Fi.

## Users
Independent grocers with 2-10 locations. Initial buyers are operations managers; primary users are store associates.

## Solution
An Android app records barcode scans and manual quantity adjustments offline, then syncs an append-only audit log when online. A web dashboard flags count variance above 8% for manager review.

## Technology
Kotlin Android client, local SQLite queue, FastAPI sync API, Postgres, and S3 audit-log snapshots. Sync is idempotent using client-generated event IDs.

## Business model
$199 per store per month, plus $0.02 per SKU over 5,000. Pilot 10 stores for 60 days; success means reducing weekly reconciliation time by 30% with less than 1% sync conflicts.

## Risks
Employees may resist a new counting workflow. We will train one store champion per location and retain paper-count fallback during the pilot.
