# terminschleuder — functional documentation

This folder is the functional documentation for the terminschleuder backend: what the
system does, how its data is shaped, how the API behaves, and how clients authenticate and
discover events by location.

All pages are GitHub-renderable Markdown (diagrams use [Mermaid](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-markdown/creating-diagrams),
which GitHub renders inline).

## Contents

| Document | Scope |
| -------- | ----- |
| [User manual](user-manual.md) | Use-case-driven guide for operators and extractor integrators: curating events, setting up ingestion, reviewing & promoting observations, lifecycle. Start here if you *work with* the app. |
| [Architecture](architecture.md) | High-level design, the "no host GIS" constraint, container layout, the public + extractor request lifecycles, project layout. |
| [Data model](data-model.md) | Entities, fields, and relationships (with an ER diagram): events, organizations, event sources, ingestion runs, observations, provenance. |
| [API reference](api-reference.md) | Every endpoint: params, request/response examples, status codes, errors, pagination — including the `/api/ingestion/` extractor surface. |
| [Authentication](authentication.md) | JWT, API keys, service/system users, groups, permissions, the `ingestion` group, and event ownership. |
| [Geospatial & cities](geospatial.md) | PostGIS location storage, proximity search (online excluded), `?near_city=`, the city catalog and seeding. |
| [Admin backoffice](admin.md) | The `admin` app: custom `AdminSite` at `/`, service-account & API-key issuance, organizations, sources, ingestion runs, observation promotion, event lifecycle. |

> For the quickstart (running it locally), see the [top-level README](../README.md).