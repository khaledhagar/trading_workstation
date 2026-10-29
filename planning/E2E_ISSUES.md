# E2E Issues

Product bugs found by the Playwright suite in `test/`. Owner per `TEAM_CONTRACTS.md` §1.

| ID | Scenario | Expected | Actual | Owner | Status |
|----|----------|----------|--------|-------|--------|
| E2E-1 | Docker compose run (all UI specs) | Playwright container loads the app at `BASE_URL` | `ERR_SSL_PROTOCOL_ERROR at http://app:8000/`: Chromium HSTS-preloads the `.app` TLD, so the `app` service hostname is forced to HTTPS. 9 passed / 27 failed | devops-engineer (`test/docker-compose.test.yml`: rename service) | fixed — service renamed `trading-workstation`; compose run 36/36 |
