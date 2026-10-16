def explain_factors(
    *,
    flood_zone_score: float,
    water_depth_score: float,
    rainfall_score: float,
    prediction_score: float,
    incident_score: float,
    confidence: float,
) -> str:
    factors = []
    if flood_zone_score > 0:
        factors.append("active flood-zone evidence")
    if water_depth_score > 0:
        factors.append("water-depth observations")
    if rainfall_score > 0:
        factors.append("recent rainfall")
    if prediction_score > 0:
        factors.append("flood prediction evidence")
    if incident_score > 0:
        factors.append("nearby incident evidence")
    if not factors:
        return "No current environmental evidence was associated with this edge; confidence is 0%."
    evidence = ", ".join(factors)
    return f"Risk is influenced by {evidence}; confidence is {confidence:.0%}."
