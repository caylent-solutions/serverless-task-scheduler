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
	cd ui-vite && npm run build

.PHONY: sam-build
sam-build:
	sam build

.PHONY: upload-ui
upload-ui:
	@S3_BUCKET=$$(aws cloudformation describe-stacks --stack-name $(STACK_NAME) --query "Stacks[0].Outputs[?OutputKey=='StaticFilesBucketName'].OutputValue" --output text); \
	if [ -z "$$S3_BUCKET" ]; then \
		echo "Error: Could not retrieve S3 bucket name from stack outputs"; \
		exit 1; \
	fi; \
	echo "Uploading UI files to S3 bucket: $$S3_BUCKET"; \
	aws s3 sync ui-vite/build/ s3://$$S3_BUCKET/ --delete --cache-control "public, max-age=31536000" --exclude "index.html"; \
	aws s3 cp ui-vite/build/index.html s3://$$S3_BUCKET/index.html --cache-control "no-cache, no-store, must-revalidate"

.PHONY: sam-deploy
sam-deploy: sam-build
	sam deploy --stack-name $(STACK_NAME) --parameter-overrides Environment=$(ENV) --capabilities CAPABILITY_NAMED_IAM --no-confirm-changeset --no-fail-on-empty-changeset --resolve-s3

.PHONY: deploy
deploy: sam-deploy upload-ui