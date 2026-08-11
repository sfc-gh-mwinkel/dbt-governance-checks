-- Consumes the ephemeral model, so a real build exercises ephemeral inlining.
{{ config(tags=['internal']) }}
select
    invoice_id,
    invoice_amount
from {{ ref('int_ephemeral_documented') }}
