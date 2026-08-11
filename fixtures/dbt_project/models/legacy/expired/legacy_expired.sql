-- Covered by an exemption that has expired, so the gate re-engages.
select customer_id as legacy_id from {{ ref('raw_customers') }}
