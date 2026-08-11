{{ config(tags=['internal']) }}
select distinct
    product_key,
    product_name
from {{ ref('raw_orders') }}
