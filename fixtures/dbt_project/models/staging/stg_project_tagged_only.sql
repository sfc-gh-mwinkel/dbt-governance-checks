-- Declares no tags. Both required tag groups are satisfied purely by
-- dbt_project.yml inheritance, which a YAML-file-parsing implementation
-- would incorrectly report as a violation.
select
    customer_id,
    customer_name
from {{ ref('raw_customers') }}
