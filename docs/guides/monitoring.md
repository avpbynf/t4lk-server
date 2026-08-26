# Monitoring guide

What the server tells you about itself while it runs: the health endpoint, the log
line per request, and the card underneath.

---

## Health

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

| Field | Meaning |
|---|---|
| `status` | `ok` when the model is loaded, `degraded` while it loads or after it failed |
| `model_loaded` | whether inference can happen at all |
| `device` | `cuda` or `cpu`, whichever the settings resolved to |
| `queue_size` | requests waiting for a GPU slot |

It needs no token, which is what lets a monitor poll it without being given a secret,
and what lets a client check reachability before it holds one.

`queue_size` is the one to watch. A single card serialises the work, so a queue that
does not drain means requests are timing out against `GPU_TIMEOUT` and answering 503,
not that the server is idle.

## Logs

Everything goes to stdout, which is where Docker expects it, through
`logging.getLogger(__name__)`. `AccessLogMiddleware` writes one line per request
carrying the method, the path, the status, the execution time, the trace id, and the
transcription metadata: audio duration, model, language, and how long the request
waited for the GPU.

```bash
make logs                                            # follow
docker logs talk-server 2>&1 | grep -E "ERROR|CRITICAL"
```

Two headers come back on every response, and they are what ties a log line to a
request:

| Header | Contents |
|---|---|
| `X-Request-Id` | The trace id, 16 hex bytes |
| `X-Execution-Time` | Total processing time, as `1234.5ms` |

## GPU

```bash
make gpu                    # nvidia-smi inside the container
nvidia-smi dmon -s pucvmet  # continuous, on the host
```

Three numbers matter. Memory should stay clear of the ceiling, because the failure when
it does not is a CUDA out-of-memory in the middle of a transcription rather than a
refusal at startup. Utilisation spikes during inference and sits at nothing between
requests, so a flat line under load means the requests are not reaching the engine.
Temperature matters on a small card: a 4060 throttles above 83C, and a throttled card
turns a latency problem into a queue problem.

## OpenTelemetry

`rest/telemetry.py` is a placeholder and nothing is instrumented. The two variables it
would read are named here so that turning it on later is a matter of setting them
rather than of finding out what they are called.

| Variable | Purpose | Default |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector endpoint | not set |
| `OTEL_SERVICE_NAME` | Service name | `talk-server` |

## Alerting

There is none. `/health` is public and cheap, so an external prober is the whole
answer: uptime monitors and the Prometheus blackbox exporter both work against it
without credentials.

Three conditions are worth waking somebody rather than drawing a graph: `/health`
failing for more than a couple of minutes, `queue_size` staying above five for more
than five, and the GPU sitting above 85C. Each of them means requests are already
failing, not that they are about to.
