#!/usr/bin/env bash
# Records the developer's approval of a PDLF gate in the ledger.
# Only the developer runs this. Cupcake blocks any agent from running it, and
# from writing to the ledger's gates table in any other way.
#
#   bash pdlf-gate.sh --check                      only proves the ledger answers; writes nothing
#   bash pdlf-gate.sh {slug} {gate} {run}          records {gate} as passed for that run
#
# {gate} is one of the seven gates of spec-gate-procedure. The gate's step row
# for the run must exist; a gate already passed for the run is never written twice.
set -euo pipefail

PSQL='C:\Program Files\PostgreSQL\15\bin\psql.exe'

sql() {
  powershell.exe -NoProfile -Command "& '$PSQL' -h 127.0.0.1 -p 5433 -U pdlf_agent -d pdlf -w -At -v ON_ERROR_STOP=1 -c \"$1\"; exit \$LASTEXITCODE" | tr -d '\r'
}

if [ "${1:-}" = "--check" ]; then
  [ "$(sql "SELECT 1")" = "1" ] && echo "ledger answers" && exit 0
  echo "ledger does not answer" >&2; exit 1
fi

if [ $# -ne 3 ]; then
  echo "Usage: bash pdlf-gate.sh {slug} {gate} {run}   or   bash pdlf-gate.sh --check" >&2; exit 2
fi
SLUG=$1; GATE=$2; RUN=$3

case "$GATE" in
  domain-locked) STEP=16 ;;
  concept-locked) STEP=21 ;;
  wireframes-approved) STEP=26 ;;
  architecture-verified) STEP=34 ;;
  build-verified) STEP=39 ;;
  production-released) STEP=44 ;;
  released) STEP=46 ;;
  *) echo "Unknown gate: $GATE" >&2; exit 2 ;;
esac
for v in "$SLUG" "$RUN"; do
  [[ "$v" =~ ^[a-z0-9-]+$ ]] || { echo "Not a valid name: $v" >&2; exit 2; }
done

ID=$(sql "SELECT id FROM steps WHERE project_slug = '$SLUG' AND step_number = '$STEP' AND run = '$RUN'")
[ -n "$ID" ] || { echo "No Step $STEP row for $SLUG, run $RUN: the gate's step has not started." >&2; exit 1; }

DONE=$(sql "SELECT count(*) FROM gates WHERE step_id = $ID AND gate_name = '$GATE' AND passed")
[ "$DONE" = "0" ] || { echo "$GATE is already passed for $SLUG, run $RUN. Nothing written." >&2; exit 1; }

sql "INSERT INTO gates (project_slug, step_id, gate_name, passed, approved_at, notes) VALUES ('$SLUG', $ID, '$GATE', true, now(), 'Approved by the developer with pdlf-gate.sh')" >/dev/null
echo "Recorded: $(sql "SELECT gate_name || ' passed for ' || project_slug || ', run $RUN, at ' || approved_at FROM gates WHERE step_id = $ID AND gate_name = '$GATE' AND passed")"
