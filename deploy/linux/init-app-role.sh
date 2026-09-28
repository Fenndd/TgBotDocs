#!/bin/sh
# Official postgres entrypoint sources non-executable .sh files as the db user.
# Only a new, empty database volume executes this script. No secret enters argv.
# A subshell keeps options and the password out of the sourcing entrypoint.
(
set -eu
TGBOTDOCS_DATABASE_PASSWORD=$(cat /run/secrets/db_password)
test -n "$TGBOTDOCS_DATABASE_PASSWORD"
export TGBOTDOCS_DATABASE_PASSWORD
PGHOST= PGHOSTADDR= psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --no-password --no-psqlrc --set ON_ERROR_STOP=1 <<'SQL'
\getenv app_password TGBOTDOCS_DATABASE_PASSWORD
CREATE ROLE tgbotdocs LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    PASSWORD :'app_password';
ALTER DATABASE tgbotdocs OWNER TO tgbotdocs;
SQL
unset TGBOTDOCS_DATABASE_PASSWORD
)
