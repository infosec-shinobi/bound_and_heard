#!/bin/sh
set -eu

mkdir -p /app/data

alembic upgrade head

exec "$@"
