.PHONY: dev-backend dev-frontend dev-agent client-install client-test build clean

dev-backend:
	cd backend && KSEFCIO_DEV=1 KSEF_API_URL=$${KSEF_API_URL:-https://api-test.ksef.mf.gov.pl/v2} uv run fastapi dev src/ksefcio/main.py

dev-frontend:
	cd frontend && npm run dev

dev-agent:
	@if [ -z "$(CERT)" ] || [ -z "$(KEY)" ]; then \
		echo "Usage: make dev-agent CERT=path/to/cert.pem KEY=path/to/key.pem [DAEMON=1] [SOCKET=path]"; \
		exit 2; \
	fi
	cd client && uv run ksefcio-agent --cert $(CERT) --key $(KEY) \
		$(if $(SOCKET),--socket $(SOCKET),) \
		$(if $(DAEMON),--daemon,)

client-install:
	cd client && uv sync

client-test:
	cd client && uv run pytest

build:
	docker compose build

clean:
	rm -rf backend/.venv backend/*.db frontend/node_modules frontend/dist client/.venv

-include Makefile.local
