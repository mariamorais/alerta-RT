-- 0002: RFC source mode + tax-reform classifier
ALTER TABLE sap_notes
    ADD COLUMN IF NOT EXISTS is_tax_reform BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS classification_score INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS matched_keywords TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'download';  -- download|rfc

CREATE INDEX IF NOT EXISTS idx_sap_notes_tax_reform
    ON sap_notes(is_tax_reform) WHERE is_tax_reform;

ALTER TABLE clients
    ADD COLUMN IF NOT EXISTS rfc_endpoint TEXT,           -- https://host/sap/bc/rest/zsnotes
    ADD COLUMN IF NOT EXISTS rfc_auth_user TEXT,
    ADD COLUMN IF NOT EXISTS rfc_auth_pass TEXT,          -- consider pgcrypto in prod
    ADD COLUMN IF NOT EXISTS rfc_sap_client TEXT,         -- SAP client / mandante (e.g. "100")
    ADD COLUMN IF NOT EXISTS alert_all BOOLEAN NOT NULL DEFAULT FALSE;
