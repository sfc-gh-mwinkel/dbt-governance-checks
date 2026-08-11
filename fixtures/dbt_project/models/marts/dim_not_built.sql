-- Excluded from the build on purpose, to simulate a model whose build failed.
-- It must be absent from catalog.json so the checker reports DOC009.
{{ config(tags=['internal']) }}
select distinct
    account_key
from {{ ref('raw_invoices') }}
