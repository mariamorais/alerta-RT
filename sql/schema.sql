-- alerta-RT core schema
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS sync_state (
    job_name       TEXT PRIMARY KEY,
    last_run_at    TIMESTAMPTZ NOT NULL,
    last_cursor    TEXT
);

CREATE TABLE IF NOT EXISTS sap_notes (
    note_number    TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    component      TEXT,
    priority       TEXT,
    category       TEXT,
    released_on    TIMESTAMPTZ,
    version        INT,
    long_text      TEXT,
    raw_xml        TEXT,
    sar_path       TEXT,
    sar_sha256     TEXT,
    ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sap_notes_component ON sap_notes(component);
CREATE INDEX IF NOT EXISTS idx_sap_notes_released_on ON sap_notes(released_on DESC);
CREATE INDEX IF NOT EXISTS idx_sap_notes_title_trgm ON sap_notes USING gin (title gin_trgm_ops);

CREATE TABLE IF NOT EXISTS sap_note_releases (
    note_number    TEXT REFERENCES sap_notes(note_number) ON DELETE CASCADE,
    software_component TEXT NOT NULL,
    release        TEXT NOT NULL,
    sp_from        TEXT,
    sp_to          TEXT,
    PRIMARY KEY (note_number, software_component, release, sp_from)
);
CREATE INDEX IF NOT EXISTS idx_releases_lookup
    ON sap_note_releases(software_component, release);

CREATE TABLE IF NOT EXISTS sap_note_objects (
    id             BIGSERIAL PRIMARY KEY,
    note_number    TEXT REFERENCES sap_notes(note_number) ON DELETE CASCADE,
    obj_type       TEXT,
    obj_name       TEXT,
    version_from   TEXT,
    version_to     TEXT
);
CREATE INDEX IF NOT EXISTS idx_objects_note ON sap_note_objects(note_number);

CREATE TABLE IF NOT EXISTS sap_note_prereqs (
    note_number    TEXT REFERENCES sap_notes(note_number) ON DELETE CASCADE,
    prereq_note    TEXT NOT NULL,
    PRIMARY KEY (note_number, prereq_note)
);

CREATE TABLE IF NOT EXISTS clients (
    id             BIGSERIAL PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    sap_release    TEXT NOT NULL,       -- e.g. SAP_BASIS 758
    sap_sp         TEXT,                -- e.g. SP0004
    components     TEXT[] NOT NULL DEFAULT '{}',
    webhook_url    TEXT,
    active         BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS alerts (
    id             BIGSERIAL PRIMARY KEY,
    client_id      BIGINT REFERENCES clients(id) ON DELETE CASCADE,
    note_number    TEXT REFERENCES sap_notes(note_number) ON DELETE CASCADE,
    matched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at   TIMESTAMPTZ,
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending|sent|failed
    attempts       INT NOT NULL DEFAULT 0,
    UNIQUE (client_id, note_number)
);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status) WHERE status <> 'sent';

CREATE TABLE IF NOT EXISTS download_queue (
    note_number    TEXT PRIMARY KEY,
    object_key     TEXT,
    enqueued_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempts       INT NOT NULL DEFAULT 0,
    last_error     TEXT
);
