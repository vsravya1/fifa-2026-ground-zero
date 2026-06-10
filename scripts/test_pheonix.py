"""
test_phoenix.py - Fixed endpoint with /v1/traces
Run: python test_phoenix.py
"""
import os
from dotenv import load_dotenv
load_dotenv()

from phoenix.otel import register

space   = os.getenv("ARIZE_SPACE_KEY")
api_key = os.getenv("ARIZE_API_KEY")

print(f"Space:    {space}")
print(f"API Key:  {api_key[:8]}..." if api_key else "API Key: NOT SET")
print(f"Endpoint: https://app.phoenix.arize.com/s/{space}/v1/traces")
print()

tp = register(
    project_name="fifa-2026-ground-zero",
    api_key=api_key,
    endpoint=f"https://app.phoenix.arize.com/s/{space}/v1/traces",
)

tracer = tp.get_tracer("fifa-agent")

with tracer.start_as_current_span("fifa-incident-agent") as span:
    span.set_attribute("openinference.span.kind", "AGENT")
    span.set_attribute("input.value",       "Gate 7 crowd surge — 12 signals in 3 mins")
    span.set_attribute("output.value",      "Deploy 3 volunteers to Gate 7. Open overflow.")
    span.set_attribute("incident.venue",    "ATT Stadium Dallas")
    span.set_attribute("incident.gate",     "Gate 7")
    span.set_attribute("incident.type",     "crowd_surge")
    span.set_attribute("incident.severity", "P1")
    span.set_attribute("agent.confidence",  0.92)
    span.set_attribute("agent.routed_to",   "Stadium Security Lead")

tp.force_flush()
print("✅ Span sent! Check Phoenix → Tracing for 'fifa-incident-agent'")