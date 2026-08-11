{{ config(tags=['internal']) }}
-- Returns three columns and documents none of them.
select
    1 as order_key,
    100 as order_total,
    'OPEN' as order_status
