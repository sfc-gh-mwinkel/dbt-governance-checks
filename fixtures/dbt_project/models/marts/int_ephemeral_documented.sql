-- Ephemeral, so it is inlined into its consumers and never materialized.
-- It therefore has no catalog entry and must not be penalised for that.
{{ config(materialized='ephemeral', tags=['internal']) }}
select
    session_id,
    invoice_id,
    invoice_amount
from {{ ref('raw_invoices') }}
