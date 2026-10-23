# Container lab

The service map, the one-command bring-up, the sweep, and the Docker Desktop / `tc netem` limits are in the [Containerized lab](../README.md#containerized-lab) section of the repository README.

The image is Alpine and contains only the harness: CoAP, HTTP, MQTT, `tc netem`, tshark, and the sweep scripts. `mosquitto_pub` and `mosquitto_sub` come from the Alpine `eclipse-mosquitto:2` image, not Alpine's `mosquitto-clients` 2.0 package, because that package waits about a second after a QoS 1 or 2 handshake. Jupyter, the notebook, and pandas/matplotlib are not in the image. Run Jupyter on the host against `lab_results/`. Host packages are [`requirements-analysis.txt`](../requirements-analysis.txt). Alpine packages for the image are [`requirements-harness.txt`](requirements-harness.txt).

```bash
docker compose up -d --build --wait
LOSS_PCTS="0 3 5 10" TRANSACTIONS=30 SLEEP_S=1 SWEEP=both sh docker/sweep.sh
```

`docker/test_coap_server.py` and `docker/test_summary.sh` do not need a running engine.
