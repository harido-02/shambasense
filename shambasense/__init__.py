"""ShambaSense: machine learning crop recommendations for Kenyan farmers."""

import os

# Train on one CPU thread. The training tables are small (a few hundred rows), so threads
# add overhead rather than speed, and scikit-learn's thread pools hit a Python 3.11 bug on
# Windows ("concurrent send_bytes() calls are not supported"). Must run before numpy or
# scikit-learn are imported; set OMP_NUM_THREADS yourself to override.
os.environ.setdefault("OMP_NUM_THREADS", "1")

__version__ = "0.1.0"
