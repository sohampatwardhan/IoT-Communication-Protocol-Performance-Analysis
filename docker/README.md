# Container lab

The service map, the one-command bring-up, the sweep, and the Docker Desktop / `tc netem` limits are in the [Containerized lab](../README.md#containerized-lab) section of the repository README.

```bash
docker compose up -d --build --wait
LOSS_PCTS="0 3 5 10" TRANSACTIONS=30 SLEEP_S=1 SWEEP=both sh docker/sweep.sh
```

`docker/test_coap_server.py` and `docker/test_summary.sh` do not need a running engine.
