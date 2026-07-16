MONTH := $(shell date +%Y-%m)
PY    := python3

.PHONY: refresh ingest score enrich demo test install clean

install:
	$(PY) -m pip install -r requirements.txt

## Full monthly run: download data, normalize, score, write CSV + diff
refresh:
	$(PY) -m wp4rescue refresh --month $(MONTH)

## Same, plus polite URL liveness checks (S3) — slow by design (1 req/2s)
enrich:
	$(PY) -m wp4rescue refresh --month $(MONTH) --enrich

ingest:
	$(PY) -m wp4rescue ingest --month $(MONTH)

score:
	$(PY) -m wp4rescue score --month $(MONTH)

## End-to-end smoke test on bundled synthetic data (no network)
demo:
	$(PY) -m wp4rescue demo

test:
	$(PY) -m pytest tests/ -q

clean:
	rm -f data/wp4.db
