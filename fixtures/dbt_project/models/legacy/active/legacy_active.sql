-- Covered by an unexpired exemption, so it is skipped entirely.
select customer_id as legacy_id from {{ ref('raw_customers') }}
