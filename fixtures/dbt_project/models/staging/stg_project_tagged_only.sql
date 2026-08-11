-- Declares no tags. Both required tag groups are satisfied purely by
-- dbt_project.yml inheritance, which a YAML-file-parsing implementation
-- would incorrectly report as a violation.
select
    1 as customer_id,
    'Acme' as customer_name
