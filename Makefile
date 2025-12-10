.PHONY: venv
venv:
	python3 -m venv .venv

.PHONY: install
install: venv
	source .venv/bin/activate && pip3 install -r api/requirements.txt

.PHONY: run
run:
	source .venv/bin/activate && cd api && uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

# SAM deployment
ENV ?= dev
STACK_NAME ?= sts

.PHONY: build-ui
build-ui:
	cd ui-react && npm run build
	rm -rf api/app/wwwroot/*
	cp -r ui-react/build/* api/app/wwwroot/

.PHONY: sam-build
sam-build: build-ui
	sam build

.PHONY: sam-deploy
sam-deploy: sam-build
	sam deploy --stack-name $(STACK_NAME) --parameter-overrides Environment=$(ENV) --capabilities CAPABILITY_NAMED_IAM --no-confirm-changeset --no-fail-on-empty-changeset --resolve-s3

.PHONY: deploy
deploy: sam-deploy