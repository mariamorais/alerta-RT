# alerta-RT

Ingestão de SAP Notes (via Download API) + alerta por cliente baseado na versão/componentes do SAP.

## Arquitetura

```
APScheduler → discover (OData) → download_queue
                                  ↓
                          download (.sar) → SAPCAR → extractor → Postgres
                                                                  ↓
                                                        matcher → alerts → webhook
```

## Pré-requisitos

- Python 3.11+, Docker
- S-User SAP com autorização "SAP Notes Download API" + OAuth2 client credentials
- Binário `SAPCAR` (baixar manualmente do SAP Support, colocar em `./bin/SAPCAR`)

## Setup

```bash
cp env.example .env   # preencher credenciais S-User
docker compose up -d db
pip install -e .[dev]
python -m alerta_rt.main
```

Ou tudo em container:

```bash
docker compose up --build
```

## Cadastrar cliente

```sql
INSERT INTO clients (name, sap_release, sp_from, components, webhook_url)
VALUES ('ClienteX', '758', 'SP0004', ARRAY['SAP_BASIS','SAP_ABA'], 'https://hooks.exemplo/notes');
```

## Jobs

- `discover` — a cada `DISCOVER_INTERVAL_MIN` (default 30 min): consulta OData `NotesCollection` filtrando `ReleasedOn > last_run`.
- `download` — 60s: consome `download_queue`, baixa `.sar`, extrai via SAPCAR, grava em `sap_notes` + relacionadas.
- `deliver` — 30s: envia webhooks pendentes.

## Tabelas principais

- `sap_notes` — metadata + long_text + raw_xml + sha256 do .sar
- `sap_note_releases` — versão/SP aplicáveis (base do match)
- `sap_note_objects` — objetos ABAP corrigidos
- `sap_note_prereqs` — notas pré-requisito
- `clients` — cadastro multi-cliente (release + componentes + webhook)
- `alerts` — match (client × note), status pending/sent/failed
