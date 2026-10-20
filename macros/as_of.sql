{# The reference "now" for every model. Fixed so a rebuild on another day gives
   the same numbers. Change `as_of` in dbt_project.yml after each data refresh. #}
{% macro as_of() %}cast('{{ var("as_of") }}' as timestamptz){% endmacro %}
