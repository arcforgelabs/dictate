"""Dictate: local-only desktop dictation."""

import os

# Dictate makes no analytics calls, and neither may the libraries it bundles.
# pyannote.audio 4.x ships ``metrics_enabled: true`` and posts usage spans to
# otel.pyannote.ai unless this is set before it is imported; it only enables on
# "true"/"1", so "0" is final. Forced rather than defaulted so a variable left in
# the user's shell cannot switch it back on. Hugging Face Hub telemetry likewise.
os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
