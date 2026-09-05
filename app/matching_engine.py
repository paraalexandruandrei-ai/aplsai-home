import re
import unicodedata


ENGINE_VERSION = "APL-MATCH-2.0"


def _number(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _money_status(total, ideal, maximum, extended):
    if total is None:
        return 12, "da_verificare", "Totale non calcolabile con i dati disponibili."
    if total <= ideal:
        return 30, "entro_ideale", "Entro il budget ideale."
    if total <= maximum:
        return 27, "entro_massimo", "Entro il budget massimo."
    if total <= extended:
        return 20, "con_flessibilita", "Compatibile soltanto usando la flessibilità dichiarata."
    return 0, "fuori_budget", "Supera il budget massimo anche con la flessibilità."


def _space_points(actual, requested, weight):
    actual = max(0, _number(actual, 0))
    requested = max(0, _number(requested, 0))
    if requested == 0 or actual >= requested:
        return weight, "compatibile"
    ratio = actual / requested if requested else 1
    return round(weight * ratio, 1), "non_compatibile"


def _potential_space(current_points, weight, transformable):
    if current_points >= weight or not transformable:
        return current_points
    # Non inventa nuove superfici o vani: riconosce solo un potenziale parziale,
    # che resta subordinato a un progetto tecnico con misure risultanti.
    return round(current_points + (weight - current_points) * 0.6, 1)


def _must_have_result(name, prop, transformable):
    key = _norm(name)
    layout_feature = any(token in key for token in ("studio", "cucina", "ripostiglio"))
    can_transform = transformable and layout_feature
    current = None
    explanation = "Dato specifico non presente nella scheda immobile."
    if "ascensore" in key:
        current = prop.get("elevator")
        explanation = "Ascensore presente." if current is True else ("Ascensore assente." if current is False else "Presenza ascensore da verificare.")
    elif "terrazzo" in key or "esterno" in key:
        value = _norm(prop.get("outdoor_spaces"))
        current = True if value and value != "da verificare" else None
        explanation = "Spazio esterno indicato nella scheda." if current else "Spazio esterno da verificare."
    elif "posto auto" in key or "garage" in key:
        value = _norm(prop.get("parking"))
        current = True if value and value != "da verificare" else None
        explanation = "Parcheggio indicato nella scheda." if current else "Parcheggio da verificare."
    elif "luminos" in key:
        value = _norm(prop.get("exposure"))
        current = None
        explanation = "Esposizione presente, ma luminosità da verificare sul posto." if value else "Esposizione e luminosità da verificare."
    else:
        searchable = _norm(" ".join([prop.get("planned_works") or "", prop.get("notes") or ""]))
        current = True if key and key in searchable else None
        explanation = "Caratteristica indicata nelle note." if current else "Caratteristica da verificare con rilievo o progetto."

    if current is True:
        return 1.0, 1.0, "compatibile", "compatibile", explanation
    if current is False:
        potential = 0.6 if can_transform else 0.0
        return 0.0, potential, "non_compatibile", "da_verificare" if can_transform else "non_compatibile", explanation
    potential = 0.5 if can_transform else 0.25
    return 0.25, potential, "da_verificare", "da_verificare", explanation


def evaluate_match(client, prop):
    budget = client.get("budget") or {}
    spaces = client.get("spaces") or {}
    ideal = max(0, _number(budget.get("ideal"), 0))
    maximum = max(ideal, _number(budget.get("max"), ideal))
    flex = max(0, _number(budget.get("flex"), 0))
    extended = maximum * (1 + flex / 100)
    price = max(0, _number(prop.get("price"), 0))
    work_min = _number(prop.get("renovation_cost_min"))
    work_max = _number(prop.get("renovation_cost_max"))
    work_relevant = bool(_norm(prop.get("planned_works"))) or "ristruttur" in _norm(prop.get("state"))
    costs_complete = work_min is not None and work_max is not None
    potential_min = price + work_min if costs_complete else (price if not work_relevant else None)
    potential_max = price + work_max if costs_complete else (price if not work_relevant else None)

    current_budget_points, current_budget_status, current_budget_text = _money_status(price, ideal, maximum, extended)
    potential_budget_points, potential_budget_status, potential_budget_text = _money_status(potential_max, ideal, maximum, extended)

    transformation = _norm(prop.get("transformation_status"))
    transformable = transformation in {"trasformabile", "parzialmente trasformabile"}
    criteria = [{
        "key": "budget", "label": "Budget", "weight": 30,
        "current_points": current_budget_points, "potential_points": potential_budget_points,
        "current_status": current_budget_status, "potential_status": potential_budget_status,
        "explanation": f"Acquisto: {current_budget_text} Acquisto più lavori: {potential_budget_text}",
    }]

    requested_zone = _norm((client.get("zone") or {}).get("main"))
    property_zone = _norm(prop.get("zone"))
    zone_ok = bool(requested_zone and property_zone and (requested_zone in property_zone or property_zone in requested_zone))
    zone_points = 20 if zone_ok else 8
    criteria.append({
        "key": "zone", "label": "Zona", "weight": 20,
        "current_points": zone_points, "potential_points": zone_points,
        "current_status": "compatibile" if zone_ok else "da_verificare",
        "potential_status": "compatibile" if zone_ok else "da_verificare",
        "explanation": "Zona coerente con la ricerca." if zone_ok else "Distanza reale dalla zona richiesta da verificare.",
    })

    for key, label, weight in (("sqm", "Metratura", 15), ("beds", "Camere", 10), ("baths", "Bagni", 5)):
        current_points, current_status = _space_points(prop.get(key), spaces.get(key), weight)
        potential_points = _potential_space(current_points, weight, transformable)
        criteria.append({
            "key": key, "label": label, "weight": weight,
            "current_points": current_points, "potential_points": potential_points,
            "current_status": current_status,
            "potential_status": current_status if potential_points == current_points else "da_verificare",
            "explanation": (
                f"Disponibili {prop.get(key) or 0}; richiesti almeno {spaces.get(key) or 0}."
                + (" Il recupero parziale ipotizzato richiede un progetto con misure risultanti." if potential_points > current_points else "")
            ),
        })

    requested_types = [_norm(value) for value in client.get("houseTypes", [])]
    property_type = _norm(prop.get("property_type"))
    type_ok = any(value == property_type or value in property_type or property_type in value for value in requested_types if value and property_type)
    type_partial = not type_ok and property_type == "appartamento" and any(value in {"attico superattico", "loft"} for value in requested_types)
    type_points = 10 if type_ok else (5 if type_partial else 0)
    criteria.append({
        "key": "property_type", "label": "Tipologia", "weight": 10,
        "current_points": type_points, "potential_points": type_points,
        "current_status": "compatibile" if type_ok else ("parziale" if type_partial else "non_compatibile"),
        "potential_status": "compatibile" if type_ok else ("parziale" if type_partial else "non_compatibile"),
        "explanation": "Tipologia richiesta." if type_ok else ("Tipologia collegata, ma non coincidente." if type_partial else "Tipologia diversa da quelle selezionate."),
    })

    must_items = client.get("must") or []
    must_current = must_potential = 1.0
    must_status_current = must_status_potential = "compatibile"
    must_explanations = []
    if must_items:
        evaluations = [_must_have_result(item, prop, transformable) for item in must_items]
        must_current = sum(item[0] for item in evaluations) / len(evaluations)
        must_potential = sum(item[1] for item in evaluations) / len(evaluations)
        statuses_current = {item[2] for item in evaluations}
        statuses_potential = {item[3] for item in evaluations}
        must_status_current = "compatibile" if statuses_current == {"compatibile"} else ("non_compatibile" if "non_compatibile" in statuses_current else "da_verificare")
        must_status_potential = "compatibile" if statuses_potential == {"compatibile"} else ("non_compatibile" if "non_compatibile" in statuses_potential else "da_verificare")
        must_explanations = [f"{name}: {result[4]}" for name, result in zip(must_items, evaluations)]
    criteria.append({
        "key": "must_have", "label": "Caratteristiche indispensabili", "weight": 10,
        "current_points": round(10 * must_current, 1), "potential_points": round(10 * must_potential, 1),
        "current_status": must_status_current, "potential_status": must_status_potential,
        "explanation": " ".join(must_explanations) if must_explanations else "Nessuna caratteristica indispensabile indicata.",
    })

    current_score = round(sum(item["current_points"] for item in criteria))
    potential_score = round(sum(item["potential_points"] for item in criteria))
    verifications = ["Oneri accessori e imposte non inclusi nel totale calcolato.", "Costi finanziari non inclusi nel totale calcolato."]
    if work_relevant and not costs_complete:
        verifications.append("Inserire l’intervallo completo dei costi dei lavori.")
    if transformable:
        verifications.append("Validare la trasformazione con rilievo e progetto tecnico.")
    if _norm(prop.get("technical_verification")) != "verificato":
        verifications.append("Verifica tecnica dell’immobile non completata.")
    if _norm(prop.get("data_reliability")) != "verificato":
        verifications.append("Affidabilità dei dati non ancora verificata.")

    confidence_values = {"da verificare": 25, "dichiarato": 45, "documentato": 75, "verificato": 100}
    confidence = confidence_values.get(_norm(prop.get("data_reliability")), 25)
    if _norm(prop.get("technical_verification")) != "verificato":
        confidence = min(confidence, 60)
    if work_relevant and not costs_complete:
        confidence = min(confidence, 40)

    best_score = max(current_score, potential_score)
    if current_score >= 80 and current_budget_status != "fuori_budget":
        recommendation = "Compatibilità attuale alta"
    elif potential_score >= 70 and potential_score > current_score and potential_budget_status != "fuori_budget":
        recommendation = "Potenziale interessante dopo verifica"
    elif best_score >= 55:
        recommendation = "Da approfondire"
    else:
        recommendation = "Non prioritario"

    return {
        "engine_version": ENGINE_VERSION,
        "score": best_score,
        "score_current": current_score,
        "score_potential": potential_score,
        "recommendation": recommendation,
        "confidence": confidence,
        "criteria": criteria,
        "economics": {
            "purchase_price": price,
            "works_min": work_min,
            "works_max": work_max,
            "known_total_min": potential_min,
            "known_total_max": potential_max,
            "budget_ideal": ideal,
            "budget_max": maximum,
            "budget_with_flex": round(extended, 2),
            "current_status": current_budget_status,
            "potential_status": potential_budget_status,
            "excluded_items": ["Oneri accessori e imposte", "Costi finanziari"],
        },
        "verifications": verifications,
        "reason": f"Attuale {current_score}/100 · Potenziale {potential_score}/100 · {recommendation}",
    }
