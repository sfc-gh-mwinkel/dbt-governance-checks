-- Appears in no YAML file at all, so patch_path is null.
{{ config(tags=['internal']) }}
select
    invoice_id as orphan_key
from {{ ref('raw_invoices') }}
