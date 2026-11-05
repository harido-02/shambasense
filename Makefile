PY ?= python

.PHONY: install demo test serve live train

install:
	$(PY) -m pip install -r requirements.txt

# Full system on SYNTHETIC data in data/demo.db (for development and the demo only)
demo:
	DATABASE_URL=sqlite:///data/demo.db $(PY) -m shambasense.cli ingest-sample
	DATABASE_URL=sqlite:///data/demo.db $(PY) -m shambasense.cli train
	DATABASE_URL=sqlite:///data/demo.db $(PY) -m shambasense.cli serve

# Real open data for the four counties (needs internet)
live:
	$(PY) -m shambasense.cli ingest-live

train:
	$(PY) -m shambasense.cli train

serve:
	$(PY) -m shambasense.cli serve

test:
	$(PY) -m pytest -q
