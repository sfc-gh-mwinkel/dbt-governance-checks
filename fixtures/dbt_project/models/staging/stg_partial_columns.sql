-- Documents only one of its two columns. In the staging layer the
-- completeness rule is downgraded to a warning by a layer override.
select
    1 as order_id,
    100 as order_total
