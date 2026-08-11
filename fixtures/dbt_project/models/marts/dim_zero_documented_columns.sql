{{ config(tags=['internal']) }}
-- Returns three columns and documents none of them.
select
    order_id as order_key,
    order_total,
    order_status
from {{ ref('raw_orders') }}
