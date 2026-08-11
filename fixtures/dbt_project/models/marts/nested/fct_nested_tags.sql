-- Tags come from two levels of dbt_project.yml config (marts + nested),
-- proving additive inheritance across nested folders.
select
    invoice_id as transaction_id,
    invoice_amount as transaction_amount
from {{ ref('raw_invoices') }}
