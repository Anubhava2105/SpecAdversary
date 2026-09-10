#!/bin/sh
# Release-step database migration: run BEFORE (re)starting web/worker
# processes, never inside them. Concurrent `alembic upgrade head` runs from
# horizontally scaled web replicas race on migration locks — a single
# one-shot invocation (compose `migrate` service, VM deploy script, or by
# hand here) owns schema changes.
set -eu
cd "$(dirname "$0")/.."
alembic upgrade head
