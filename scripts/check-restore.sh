#!/bin/sh
# Run against a quiescent acceptance database using standard PostgreSQL connection variables.
set -eu
: "${PGDATABASE:?Set PGDATABASE to the source database}"
umask 077
archive_dir=${1:-.backups}
mkdir -p "$archive_dir"
archive=$(mktemp "$archive_dir/yago-XXXXXXXX.dump")
restore_db="yago_restore_$(date +%Y%m%d_%H%M%S)_$$"
pg_dump --format=custom --file="$archive" "$PGDATABASE"
createdb --template=template0 "$restore_db"
pg_restore --exit-on-error --single-transaction --no-owner --dbname="$restore_db" "$archive"

fingerprint() {
    psql -XqAt -v ON_ERROR_STOP=1 -d "$1" <<'SQL'
SET timezone='UTC';
SELECT format(
  'SELECT %L, count(*), md5(coalesce(string_agg(h, '''' ORDER BY h), '''')) FROM (SELECT md5(to_jsonb(t)::text) h FROM %I.%I AS t) AS rows',
  tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname='public' ORDER BY tablename
\gexec
SQL
}
original=$(fingerprint "$PGDATABASE")
restored=$(fingerprint "$restore_db")
test -n "$original" && test "$original" = "$restored" || {
    echo "Source and restored table contents differ" >&2
    exit 1
}
echo "Verified all public tables. Archive: $archive. Restored database: $restore_db"
