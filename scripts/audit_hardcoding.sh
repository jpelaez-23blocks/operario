#!/bin/sh
# Fails if code (not docs/tests/challenge/transcripts) holds domain literals, hosts or secrets.
cd "$(dirname "$0")/.." || exit 2
fail=0
CODE="services packages infra scripts/*.py"
check() { # label, pattern
  if grep -rniE --include='*.py' --include='Dockerfile' --include='*.txt' "$2" $CODE 2>/dev/null; then echo "FOUND: $1"; fail=1; fi
}
check "domain literal" 'sigecom|pereira|distribuidora|papeler|ana torres|cl[ií]nica'
check "hardcoded host" 'railway\.app|fly\.dev|onrender\.com|wss?://[a-z0-9.-]+\.[a-z]{2,}'
check "secret-looking value" '(sk|or)-[a-z0-9_-]{20,}'
[ $fail -eq 0 ] && echo "audit clean"
exit $fail
