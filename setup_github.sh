#!/usr/bin/env bash
# Eenmalig: maakt de publieke GitHub-repo aan, zet het ntfy-topic als secret en pusht.
# Vooraf: `gh auth login` met je PERSOONLIJKE GitHub-account.
set -euo pipefail
cd "$(dirname "$0")"

echo "Ingelogd als: $(gh api user --jq .login)"
read -r -p "Is dit je persoonlijke account? [j/N] " ok
[[ "$ok" == "j" || "$ok" == "J" ]] || { echo "Log eerst in met: gh auth login"; exit 1; }

gh repo create dukeoftokyo-monitor --public --source=. --remote=origin --push
gh secret set NTFY_TOPIC --body "$(cat .ntfy_topic)"
gh workflow run monitor.yml -f test_date=2027-01-30
echo "Klaar. Test-run gestart; je zou binnen ~1 min een [TEST]-push moeten krijgen."
echo "Volg de runs met: gh run list --workflow monitor.yml"
