-- Tags come from two levels of dbt_project.yml config (marts + nested),
-- proving additive inheritance across nested folders.
select
    1 as transaction_id,
    250 as transaction_amount
