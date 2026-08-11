-- Documents only one of its two columns. In the staging layer the
-- completeness rule is downgraded to a warning by a layer override.
select
    order_id,
    order_total
from {{ ref('raw_orders') }}
