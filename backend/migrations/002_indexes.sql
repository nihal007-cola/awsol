-- T22: indexes for the scoped ledger reads + snapshot lookups.
-- These back the queries introduced in T20/T21.

-- Ledger: version filter in move_stage + get_live_ledger_entries
CREATE INDEX IF NOT EXISTS idx_ledger_bo_version
    ON activity_ledger (buyer_order_id, version);

-- Ledger: type + status filters used everywhere
CREATE INDEX IF NOT EXISTS idx_ledger_bo_type_status
    ON activity_ledger (buyer_order_id, activity_type, status);

-- Ledger: poToken JSONB expression (GRN, RM Order, print-PO paths)
CREATE INDEX IF NOT EXISTS idx_ledger_po_token
    ON activity_ledger ((extra_data->>'poToken'));

-- Ledger: requirementKey JSONB expression (MR lookups)
CREATE INDEX IF NOT EXISTS idx_ledger_req_key
    ON activity_ledger ((extra_data->>'requirementKey'));

-- Snapshot: direct lookup by requirement_key (upsert + update path)
CREATE INDEX IF NOT EXISTS idx_snapshot_req
    ON inventory_snapshot (requirement_key);

-- Snapshot: per-order / per-FG aggregations (Issue RM, reports)
CREATE INDEX IF NOT EXISTS idx_snapshot_bo_fg
    ON inventory_snapshot (buyer_order_id, fg_key);
