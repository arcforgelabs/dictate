"""Dictate: local-only desktop dictation."""

import os

# Dictate makes no analytics calls, and neither may the libraries it bundles.
# Forced rather than defaulted so a variable left in the user's shell cannot
# switch them back on. Hugging Face Hub (the Parakeet model download):
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
# ONNX Runtime (Parakeet) builds in Microsoft's 1DS telemetry client: it keeps a
# device ID and an event queue under ~/.cache/Microsoft/DeveloperTools and uploads
# to mobile.events.data.microsoft.com. This switch stops both.
os.environ["ORT_DISABLE_TELEMETRY"] = "1"
