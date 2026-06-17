from origami import skill


def test_parse_single_levels():
    assert skill.parse("Simple").low == skill.SIMPLE
    assert skill.parse("Intermediate").low == skill.INTERMEDIATE
    assert skill.parse("Complex").high == skill.COMPLEX


def test_parse_compound_levels_not_swallowed():
    d = skill.parse("Super complex")
    assert d.low == skill.SUPER_COMPLEX and d.high == skill.SUPER_COMPLEX

    d = skill.parse("High intermediate")
    assert d.low == skill.HIGH_INTERMEDIATE and d.high == skill.HIGH_INTERMEDIATE

    d = skill.parse("Low intermediate")
    assert d.low == skill.LOW_INTERMEDIATE


def test_parse_range():
    d = skill.parse("From simple to complex")
    assert d.low == skill.SIMPLE
    assert d.high == skill.COMPLEX
    assert "Simple" in d.label and "Complex" in d.label


def test_parse_unknown():
    d = skill.parse(None)
    assert not d.is_known
    assert skill.parse("").label == "Unknown"
    assert skill.parse("xyzzy").label == "Unknown"


def test_buckets():
    assert skill.parse("Simple").buckets == {skill.BUCKET_SIMPLE}
    assert skill.parse("Intermediate").buckets == {skill.BUCKET_INTERMEDIATE}
    assert skill.parse("From simple to complex").buckets == set(skill.BUCKETS)


def test_matches_bucket():
    inter = skill.parse("Intermediate")
    assert inter.matches_bucket(skill.BUCKET_INTERMEDIATE)
    assert not inter.matches_bucket(skill.BUCKET_SIMPLE)

    rng = skill.parse("simple to complex")
    assert rng.matches_bucket(skill.BUCKET_INTERMEDIATE)

    # Unknown difficulty matches any bucket (never silently dropped).
    assert skill.parse(None).matches_bucket(skill.BUCKET_COMPLEX)
