REPO_ROOT := $(shell git -C "$(ARTIFACTS_DIR)" rev-parse --show-toplevel)

build-DRResyncLambda:
	pip install -r requirements.txt -t $(ARTIFACTS_DIR) \
		--platform manylinux2014_x86_64 \
		--python-version 3.13 \
		--implementation cp \
		--only-binary=:all:
	cp -r *.py $(ARTIFACTS_DIR)/
	mkdir -p $(ARTIFACTS_DIR)/app
	cp $(REPO_ROOT)/api/app/__init__.py $(ARTIFACTS_DIR)/app/
	cp $(REPO_ROOT)/api/app/validation.py $(ARTIFACTS_DIR)/app/
	cp -r $(REPO_ROOT)/api/app/awssdk $(ARTIFACTS_DIR)/app/
	cp -r $(REPO_ROOT)/api/app/models $(ARTIFACTS_DIR)/app/
