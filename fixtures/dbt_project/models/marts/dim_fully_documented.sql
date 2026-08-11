{{ config(tags=['internal']) }}
select
    customer_id as customer_key,
    customer_name
from {{ ref('stg_project_tagged_only') }}
