.PHONY: install dev run test clean

# ── Backend ──
install:
	cd backend && pip install -e ".[dev]"

dev:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	cd backend && pytest tests/ -v

clean:
	rm -rf backend/data/*.db
	rm -rf backend/__pycache__ backend/app/**/__pycache__

# ── Frontend ──
fe-install:
	cd frontend && npm install

fe-dev:
	cd frontend && npm run dev

fe-build:
	cd frontend && npm run build

# ── Full Stack ──
all-install: install fe-install
all-dev:
	@echo "Run 'make dev' and 'make fe-dev' in separate terminals"
