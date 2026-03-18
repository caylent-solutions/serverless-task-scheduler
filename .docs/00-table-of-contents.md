# Serverless Task Scheduler - System Documentation

## Overview

A multi-part deep dive into the Serverless Task Scheduler (STS) -- a multi-tenant AWS serverless platform for scheduling and executing tasks across Lambda, ECS, and Step Functions.

---

## Table of Contents

### [Part 1: System Overview](01-overview.md)

High-level introduction to the platform: what it does, core concepts (targets, tenants, mappings, schedules), the three main components (UI, API, Executor), technology stack, and deployment model.

**Key topics:** Multi-tenancy, alias-based target resolution, serverless architecture benefits

---

### [Part 2: Executor Step Function](02-executor-step-function.md)

Deep dive into the Step Functions execution engine: the three-phase flow (preprocessing, execution, postprocessing), dynamic target type routing via Choice state, the Parallel state error handling pattern, and payload merging.

**Key topics:** Target mapping/indirection, dynamic routing, CloudWatch log URL generation, redrive mechanism, Redrive Monitor State Machine for Step Functions targets

---

### [Part 3: Security Model](03-security-model.md)

The defense-in-depth security architecture: five security layers (authentication, authorization, IAM roles, data isolation, audit trail), the three-tier IAM role model (API, Scheduler, Executor), and DynamoDB tenant isolation patterns.

**Key topics:** Cognito JWT authentication, tenant access control, least-privilege IAM roles, composite partition keys for data isolation

---

### [Part 4: API Routes](04-api-routes.md)

Complete API reference organized by domain: authentication, target management (admin), tenant CRUD, target mapping CRUD, schedule management, execution history, redrive, and user management. Includes request/response examples.

**Key topics:** RESTful route design, tenant-scoped authorization, one-time execution via `at()` schedule expression, API Gateway dual routing (API + static files)

---

### [Part 5: DR Failover Process](05-dr-failover.md)

Active-passive multi-region disaster recovery: how alias-based scheduling enables seamless failover, the DR Resync Lambda (enable/disable/validate modes), regional vs global table strategy, step-by-step failover and failback procedures.

**Key topics:** DynamoDB Global Tables, EventBridge schedule lifecycle, regional Targets table design, target registration in DR region

---

### [Part 6: UI User Guide - Target Mapping & Redrive](06-ui-user-guide.md)

Hands-on guide to the web UI focusing on the two most important workflows: configuring target mappings (aliases with default payloads) and redriving failed executions. Covers schedule management, execution history, and troubleshooting.

**Key topics:** Target alias configuration, default payload merging, one-time execution via `at()` schedule, redrive workflow, Step Functions redrive monitor, schedule expressions

---

## Architecture Diagrams

The [img/](img/) directory contains screenshots and diagrams referenced throughout this documentation. Add your own screenshots to this folder:

| Filename | Used In | Description |
|----------|---------|-------------|
| `architecture-overview.png` | Part 1 | High-level architecture diagram (from `architecture-diagram.drawio`) |
| `executor-step-function.png` | Part 2 | Step Functions workflow visualization |
| `security-model.png` | Part 3 | Security layers and IAM role relationships |
| `dr-architecture.png` | Part 5 | Multi-region DR layout |
| `ui-overview.png` | Part 6 | Main UI dashboard screenshot |
| `ui-mapping-list.png` | Part 6 | Target alias mapping list view |
| `ui-execute-dialog.png` | Part 6 | One-time schedule (`at()`) creation dialog |
| `ui-execution-history.png` | Part 6 | Execution history modal |
| `ui-redrive-button.png` | Part 6 | Redrive action on a failed execution |

> **Tip:** Export diagrams from `architecture-diagram.drawio` (at the project root) using draw.io and place the PNGs in `.docs/img/`.

---

## Source Material

- [README.md](../README.md) -- Quick start and project overview
- [DISASTER_RECOVERY.md](../DISASTER_RECOVERY.md) -- Operational DR runbook
- [REDRIVE_DESIGN.md](../REDRIVE_DESIGN.md) -- Step Functions redrive monitor design document
- [task-execution/README.md](../task-execution/README.md) -- Executor engine component reference
- [architecture-diagram.drawio](../architecture-diagram.drawio) -- Architecture diagrams (draw.io)
