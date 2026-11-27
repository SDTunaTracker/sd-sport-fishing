from src.surf import spots as S


def test_ralphs_is_a_point_loma_reef_on_a_se_facing_mop_point():
    cfg = next(c for c in S.spot_configs() if c["id"] == "ralphs")
    assert cfg["type"] == "reef" and cfg["mopKm"] < 0.5
    normal = next(m["normal"] for m in S.mop_table() if m["id"] == cfg["mop"])
    assert 110 <= normal <= 160          # inside the tip of Point Loma, facing SE
    assert S.area_of(cfg["lat"], "ralphs") == "PB–Point Loma"   # not Coronado, despite its latitude
    assert "Boat access" in cfg["note"]


def test_area_of_without_override_uses_latitude():
    assert S.area_of(32.68) == "Coronado–Imperial Beach"
    assert S.area_of(32.75) == "PB–Point Loma"
