"""
OpenTelemetry setup for SigNoz — sends logs, metrics, and traces.

Usage: call setup_telemetry() at startup, then use otel_logger for structured logs.
"""

import logging
import os

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

OTEL_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

_meter = None


def setup_telemetry():
    """Initialize OTel providers and attach log handler to Python logging."""
    global _meter

    resource = Resource.create({
        "service.name": "candle-feeder",
        "service.version": "1.0.0",
        "deployment.environment": os.environ.get("ENVIRONMENT", "production"),
    })

    # --- Metrics ---
    metric_exporter = OTLPMetricExporter(endpoint=f"{OTEL_ENDPOINT}/v1/metrics")
    metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=15000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
    _meter = metrics.get_meter("candle-feeder", "1.0.0")

    # --- Logs ---
    log_exporter = OTLPLogExporter(endpoint=f"{OTEL_ENDPOINT}/v1/logs")
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(logger_provider)

    # Attach OTel handler to root logger — sends logs to SigNoz
    # Console handler must already be set up (by feeder.py basicConfig)
    # so this ADDS the OTel handler alongside it
    otel_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    logging.getLogger().addHandler(otel_handler)

    # Ensure console output isn't lost — add StreamHandler if missing
    root = logging.getLogger()
    has_console = any(isinstance(h, logging.StreamHandler) and not isinstance(h, LoggingHandler) for h in root.handlers)
    if not has_console:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S"
        ))
        root.addHandler(console)


def get_meter():
    """Return the OTel meter for creating custom metrics."""
    return _meter


# --- Custom metrics (created after setup_telemetry) ---

_new_bars_counter = None
_poll_duration = None
_cache_depth_gauge = None
_cache_depth_callback = None


def init_metrics():
    """Create custom metrics — call after setup_telemetry()."""
    global _new_bars_counter, _poll_duration, _cache_depth_gauge

    m = get_meter()
    if not m:
        return

    _new_bars_counter = m.create_counter(
        "candle_feeder.new_bars",
        description="New bars detected",
        unit="bars",
    )

    _poll_duration = m.create_histogram(
        "candle_feeder.poll_duration",
        description="Time for one full polling cycle",
        unit="s",
    )

    _cache_depth_gauge = m.create_observable_gauge(
        "candle_feeder.cache_depth",
        description="Number of candles per cache file",
        unit="candles",
        callbacks=[_observe_cache_depth],
    )


def record_new_bar(symbol, timeframe):
    if _new_bars_counter:
        _new_bars_counter.add(1, {"symbol": symbol, "timeframe": timeframe})


def record_poll_duration(duration_s):
    if _poll_duration:
        _poll_duration.record(duration_s)


# Cache depth observation (called by OTel on metric export)
_cache_depth_data = {}


def update_cache_depths(depths):
    """Called by feeder.py to update cache depth data for the gauge."""
    global _cache_depth_data
    _cache_depth_data = depths


def _observe_cache_depth(options):
    from opentelemetry.metrics import Observation
    for key, count in _cache_depth_data.items():
        parts = key.rsplit("_", 1)
        if len(parts) == 2:
            yield Observation(count, {"symbol": parts[0], "timeframe": parts[1]})
