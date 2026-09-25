import json
import logging
import os
from prometheus_client import Counter, Histogram
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

REQUESTS = Counter(
    "banking_http_requests_total",
    "API traffic excluding probes",
    ["role", "route", "status"],
)
LATENCY = Histogram("banking_http_duration_seconds", "API latency", ["role", "route"])
PROCESSED = Counter("banking_messages_total", "Consumer results", ["role", "status"])


class JsonFormatter(logging.Formatter):
    def format(self, record):
        span = trace.get_current_span().get_span_context()
        return json.dumps(
            {
                "level": record.levelname,
                "service": os.getenv("ROLE", "api"),
                "message": record.getMessage(),
                "trace_id": format(span.trace_id, "032x"),
            }
        )


def setup(app, role):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("banking")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    provider = TracerProvider(
        resource=Resource.create({"service.name": f"banking-{role}"})
    )
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(insecure=True)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,ready,metrics")
    return trace.get_tracer("banking"), logger, provider
