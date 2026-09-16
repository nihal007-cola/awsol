# awsol — Deployment Status

## Goal
Harden `awsv3` ERP for AWS deployment supporting 15+ concurrent users.

## Local hardening: COMPLETE (T00–T30)

### Completed
- T00–T03   Fork, Postgres local, requirements pinned
- T04–T08   Security: JWT fail-fast, auth on all mutating routes, login rate limit, CORS, secrets untracked
- T09–T14   Correctness: crud fixes, hardcoded paths, dup routes, RM inspection FK
- T15–T19   Concurrency: row locks, sequence counters, pool sizing, gunicorn workers
- T20–T23   Performance: scoped ledger reads, SQL aggregate fix, indexes, Alembic baseline
- T24–T26   Observability: logging, request middleware, DB health check
- T27–T30   Deploy artifacts: Dockerfile, .dockerignore, docker-compose, Locust load test

### Load test result
15 concurrent users, 5 minutes, 2220 requests:
- 0.00% failures
- p95 = 50 ms
- p99 = 87 ms
- RPS sustained = 7.4

### Pending
- T31–T36   AWS infrastructure (RDS, ECS/EC2, ALB, Secrets Manager, CloudWatch, WAF)
- T37–T42   Cleanup (dead code, WORKFLOW_STAGES consolidation, app.js split)

## Reproduce locally
    cd awsol
    docker compose up -d
    curl http://127.0.0.1:8000/utils/health

## Reproduce load test
    cd awsol
    locust -f locustfile.py --headless -u 15 -r 3 -t 5m --host http://127.0.0.1:8000
