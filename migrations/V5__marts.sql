-- Analytical layer. Materialized views are refreshed by the last Airflow task.

-- Share of vacancies (published that week) that mention each skill.
CREATE MATERIALIZED VIEW mart.skill_demand_weekly AS
WITH cur AS (
    SELECT vacancy_id, published_at
    FROM core.vacancy_version
    WHERE is_current
),
totals AS (
    SELECT date_trunc('week', published_at)::date AS week, count(*) AS total
    FROM cur
    GROUP BY 1
)
SELECT t.week,
       s.name                                         AS skill,
       s.category                                     AS category,
       count(*)                                       AS vacancies,
       round(100.0 * count(*) / t.total, 1)           AS share_pct
FROM cur c
JOIN core.vacancy_skill vs USING (vacancy_id)
JOIN core.skill s          USING (skill_id)
JOIN totals t              ON t.week = date_trunc('week', c.published_at)::date
GROUP BY t.week, s.name, s.category, t.total;

CREATE INDEX ix_mart_skill_week ON mart.skill_demand_weekly (week, skill);

-- Salary distribution per professional role (KZT, midpoint of the range).
CREATE MATERIALIZED VIEW mart.salary_by_role AS
SELECT COALESCE(role_name, 'unknown')                                        AS role_name,
       count(*)                                                              AS vacancies_with_salary,
       round(percentile_cont(0.25) WITHIN GROUP (ORDER BY salary_mid_kzt)::numeric, 0) AS p25_kzt,
       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY salary_mid_kzt)::numeric, 0) AS median_kzt,
       round(percentile_cont(0.75) WITHIN GROUP (ORDER BY salary_mid_kzt)::numeric, 0) AS p75_kzt
FROM core.vacancy_version
WHERE is_current AND salary_mid_kzt IS NOT NULL
GROUP BY COALESCE(role_name, 'unknown');

-- Convenience view for the API and BI tools.
CREATE VIEW mart.vacancy_current AS
SELECT v.vacancy_id, v.title, e.name AS employer, v.area_name, v.role_name,
       v.experience, v.employment, v.schedule,
       v.salary_from, v.salary_to, v.salary_currency, v.salary_gross,
       v.salary_mid_kzt, v.salary_flag, v.published_at, v.archived, v.url,
       v.valid_from AS version_valid_from,
       COALESCE(array_agg(s.name ORDER BY s.name) FILTER (WHERE s.name IS NOT NULL), '{}') AS skills
FROM core.vacancy_version v
LEFT JOIN core.employer e       ON e.employer_id = v.employer_id
LEFT JOIN core.vacancy_skill vs ON vs.vacancy_id = v.vacancy_id
LEFT JOIN core.skill s          ON s.skill_id = vs.skill_id
WHERE v.is_current
GROUP BY v.version_id, e.name;
