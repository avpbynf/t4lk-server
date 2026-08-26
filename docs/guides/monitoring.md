# Monitoring guide

## Overview

T4lk server monitoring relies on structured logging, the `/health` endpoint,
and GPU metrics via nvidia-smi. OpenTelemetry tracing is a placeholder (not active).

## Health Endpoint

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

Response fields:
- `status`: "ok" (model loaded) or "degraded" (loading or error)
- `model_loaded`: boolean
- `device`: "cuda" or "cpu"
- `queue_size`: number of requests waiting for a GPU slot

## Log Format

Logs are emitted to stdout (Docker native). The application uses `logging.getLogger(__name__)`.

Each request is logged by `AccessLogMiddleware` with:
- HTTP method, path, status code, execution time
- STT metadata: audio duration, model name, language, queue wait time
- Trace ID (`X-Request-Id` header)

```bash
# View live logs
make logs

# Filter errors
docker logs t4lk-server 2>&1 | grep -E "ERROR|CRITICAL"
```

## GPU Monitoring

```bash
# GPU status inside the container
make gpu

# Host-level GPU monitoring
nvidia-smi
nvidia-smi dmon -s pucvmet  # continuous monitoring
```

Key metrics:
- GPU memory usage (should stay below 80% of VRAM)
- GPU utilization (spikes during transcription)
- Temperature (throttling above 83C on 4060)

## Response Headers

Each response includes tracing headers:

| Header | Description |
|--------|-------------|
| `X-Request-Id` | Unique request ID (hex 16 bytes) |
| `X-Execution-Time` | Total processing time (e.g. "1234.5ms") |

## OpenTelemetry (placeholder)

`rest/telemetry.py` contains a placeholder for OTel instrumentation.
Currently not active. When enabled, traces will be exported via OTLP.

| Variable | Description | Default |
|----------|-------------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector endpoint | not set |
| `OTEL_SERVICE_NAME` | Service name | t4lk-server |

## Alerting

No alerting is configured. The health endpoint can be polled by an
external monitoring system (uptime robot, Prometheus blackbox exporter).

Recommended alert conditions:
- Health endpoint returns non-200 for more than 2 minutes
- `queue_size` exceeds 5 for more than 5 minutes
- GPU temperature exceeds 85C
