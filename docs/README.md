# terminschleuder — functional documentation

This folder is the functional documentation for the terminschleuder backend: what the
system does, how its data is shaped, how the API behaves, and how clients authenticate and
discover events by location.

All pages are GitHub-renderable Markdown (diagrams use [Mermaid](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-markdown/creating-diagrams),
which GitHub renders inline).

## Contents

| Document | Scope |
| -------- | ----- |
| [Architecture](architecture.md) | High-level design, the "no host GIS" constraint, container layout, request lifecycle, project layout. |
| [Data model](data-model.md) | Entities, fields, and relationships (with an ER diagram). |
| [API reference](api-reference.md) | Every endpoint: params, request/response examples, status codes, errors, pagination. |
| [Authentication](authentication.md) | JWT, API keys, service/system users, groups, permissions, and event ownership. |
| [Geospatial & cities](geospatial.md) | PostGIS location storage, proximity search, `?near_city=`, the city catalog and seeding. |

> For the quickstart (running it locally), see the [top-level README](../README.md).