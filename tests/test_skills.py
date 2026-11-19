from kzjobs.config import Settings
from kzjobs.transform.skills import SkillMatcher


def matcher() -> SkillMatcher:
    return SkillMatcher.from_csv(Settings().skills_csv)


def test_finds_skills_in_free_text_with_aliases():
    found = matcher().find("Опыт с Postgres, Spark и Airflow. Знание k8s приветствуется")
    assert {"PostgreSQL", "Spark", "Airflow", "Kubernetes"} <= set(found)


def test_symbols_are_not_partial_matches():
    found = matcher().find("We use c++ and c# daily")
    assert {"C++", "C#"} <= set(found)
    assert "C" not in found


def test_java_does_not_match_javascript():
    found = matcher().find("Frontend on JavaScript")
    assert "JavaScript" in found and "Java" not in found


def test_exact_only_alias_ignores_free_text():
    m = matcher()
    assert "Go" not in m.find("Ready to go the extra mile, R&D team")
    assert "R" not in m.find("R&D team")
    assert "Go" in m.find("backend", key_skills=["Go"])
    assert "R" in m.find("analytics", key_skills=["R"])


def test_result_is_sorted_and_unique():
    found = matcher().find("python PYTHON Python sql")
    assert found == sorted(set(found))
