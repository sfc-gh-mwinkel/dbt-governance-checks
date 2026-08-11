{{ config(materialized='ephemeral', tags=['internal']) }}
select
    1 as session_id
