#!/usr/bin/env bash
# `make verify-backup` (ticket T0.4 "Done when"): proves a backup can actually be restored.
#
# 1. Takes a fresh dump (same code path as the daily run).
# 2. Starts a throwaway postgres:16 container that shares nothing with the real one.
# 3. Restores the dump into it.
# 4. Compares the row count of every table with the live database. Any difference fails.
#
# Needs `make up` (the live database must be running). The throwaway container is always
# removed, even on failure.
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1  # stop Git Bash rewriting /tmp/... arguments into Windows paths

# Row count of every table outside the system schemas, one "schema.table|count" per line.
# query_to_xml runs a count(*) per table inside a single SQL statement.
COUNT_SQL="
SELECT table_schema || '.' || table_name || '|' ||
       (xpath('/row/n/text()',
              query_to_xml(format('SELECT count(*) AS n FROM %I.%I', table_schema, table_name),
                           false, true, '')))[1]::text
FROM information_schema.tables
WHERE table_type = 'BASE TABLE' AND table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY 1;"

echo "== 1. dump"
docker compose run --rm --build collector python -m tracker.core.backup dump
dump_file=$(ls -t backups/daily/tracker_*.dump | head -n 1)
echo "using $dump_file"

echo "== 2. throwaway postgres:16"
container="tracker-verify-$$"
trap 'docker rm -f "$container" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$container" -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=tracker \
  postgres:16 >/dev/null
# -h 127.0.0.1: during first start the image runs a temporary socket-only server; waiting for
# TCP means waiting for the real one.
for _ in $(seq 60); do
  docker exec "$container" pg_isready -q -h 127.0.0.1 -U postgres -d tracker && break
  sleep 1
done
docker exec "$container" pg_isready -q -h 127.0.0.1 -U postgres -d tracker

echo "== 3. restore"
docker cp "$dump_file" "$container:/tmp/backup.dump"
docker exec "$container" pg_restore --exit-on-error --no-owner --no-acl \
  -U postgres -d tracker /tmp/backup.dump

echo "== 4. compare row counts"
live=$(docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' \
  <<<"$COUNT_SQL")
restored=$(docker exec -i "$container" psql -U postgres -d tracker -At <<<"$COUNT_SQL")

if diff <(echo "$live") <(echo "$restored"); then
  echo "$live" | awk -F'|' '{ printf "  %-28s %s\n", $1, $2 }'
  echo "OK: $(echo "$live" | wc -l) tables, identical row counts after restore"
else
  echo "FAIL: row counts differ (< live, > restored). A run during the check also causes this."
  exit 1
fi
