#!/usr/bin/env bash
# Accept the paper trade log only if it is exactly what the bot is allowed to write.
#
#   validate_paper_log.sh NEW OLD OUT
#
# NEW  the log to check
# OLD  the log as committed in the repository
# OUT  where to write the cleaned copy (LF line endings, trailing newline)
#
# Rules: regular file under 2 MB, printable ASCII only, exact header, every row
# matches the field formats, every committed row is unchanged, at most one new row.
set -euo pipefail

NEW="$1"; OLD="$2"; OUT="$3"
HEADER="date,config_id,source,outcome,shares,entry,stop,target,exit,profit,R,shares_5k,profit_5k,sim_outcome,sim_R,logged_at"
NUM='-?[0-9]{0,7}(\.[0-9]{1,5})?'
ROW="^[0-9]{4}-[0-9]{2}-[0-9]{2},[0-9a-f]{8},[a-z-]{1,20}/[a-z-]{1,20},[a-z_]{1,24},${NUM},${NUM},${NUM},${NUM},${NUM},${NUM},${NUM},${NUM},${NUM},[a-z_]{0,24},${NUM},[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}Z$"

fail() { echo "::error::paper log rejected: $1"; exit 1; }

[ ! -L "$NEW" ] && [ -f "$NEW" ] || fail "missing or not a regular file"
[ "$(stat -c %s "$NEW")" -le 2000000 ] || fail "larger than 2 MB"

# Normalise to LF with every line terminated, so line counts cannot be off by one.
normalise() { tr -d '\r' < "$1" | awk '{ print }'; }
new_clean="$(mktemp)"; old_clean="$(mktemp)"
normalise "$NEW" > "$new_clean"
normalise "$OLD" > "$old_clean"

if LC_ALL=C grep -q '[^ -~]' "$new_clean"; then fail "contains characters outside printable ASCII"; fi
[ "$(head -n 1 "$new_clean")" = "$HEADER" ] || fail "unexpected header"
if tail -n +2 "$new_clean" | grep -Evq "$ROW"; then fail "a row does not match the expected format"; fi

old_n="$(awk 'END { print NR }' "$old_clean")"
new_n="$(awk 'END { print NR }' "$new_clean")"
[ "$new_n" -ge "$old_n" ] || fail "rows were removed"
[ "$(( new_n - old_n ))" -le 1 ] || fail "more than one new row"
if ! head -n "$old_n" "$new_clean" | cmp -s - "$old_clean"; then fail "earlier rows were changed"; fi

cp "$new_clean" "$OUT"
echo "paper log accepted: $new_n lines ($(( new_n - old_n )) new)"
