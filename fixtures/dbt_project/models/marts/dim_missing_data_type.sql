{{ config(tags=['internal']) }}
select distinct
    region_key,
    region_name
from {{ ref('raw_customers') }}
