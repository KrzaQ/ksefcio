.PHONY: dev-backend dev-frontend build clean

dev-backend:
	cd backend && KSEFCIO_DEV=1 KSEF_API_URL=$${KSEF_API_URL:-https://api-test.ksef.mf.gov.pl/v2} uv run fastapi dev src/ksefcio/main.py

dev-frontend:
	cd frontend && npm run dev

build:
	docker compose build

clean:
	rm -rf backend/.venv backend/*.db frontend/node_modules frontend/dist

-include Makefile.local
