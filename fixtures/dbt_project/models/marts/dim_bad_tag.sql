-- "confidental" is a misspelling of "confidential".
{{ config(tags=['confidental']) }}
select distinct
    vendor_key
from {{ ref('raw_invoices') }}
