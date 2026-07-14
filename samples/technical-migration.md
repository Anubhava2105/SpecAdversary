# Legacy billing migration

Replace the nightly CSV billing process with event-driven billing. Stripe webhooks will enter a queue, a consumer calculates charges, and finance can review exceptions. The system must process 100,000 events daily and preserve a defensible audit trail. We need a staged migration, rollback plan, reconciliation checks, alerting, and a data retention policy.
