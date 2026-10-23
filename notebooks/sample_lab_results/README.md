# Example data (not a measurement)

These CSVs are **synthetic**. They copy the column layout of `environment-1-coap-http/test.sh` and `environment-2-coap-mqtt/test.sh` so the notebook can be opened before any lab run exists.

- Not captured on a network, and not timed with Wireshark or `date`.
- 3 transactions per series, not the lab's 30.
- No `.pcapng` files.
- Do not paste these numbers into the TELE 6510 report.

Regenerate with:

```bash
python notebooks/iot_results.py write-example
```
