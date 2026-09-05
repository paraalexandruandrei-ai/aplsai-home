from datetime import datetime, timezone
from io import BytesIO
import json

from flask import jsonify, send_file, session
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .rbac import has_permission


HEADER_FILL = PatternFill("solid", fgColor="536B45")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def _iso(value):
    return value.isoformat() if value else ""


def _join(value):
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return value if value is not None else ""


def _sheet(workbook, title, headers, rows):
    ws = workbook.create_sheet(title)
    ws.append(headers)
    for row in rows:
        ws.append(list(row))
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for index, column in enumerate(ws.columns, start=1):
        width = max((len(str(cell.value or "")) for cell in column), default=10) + 2
        ws.column_dimensions[get_column_letter(index)].width = min(max(width, 12), 42)
    return ws


def init_operational_export(app, app_module):
    if app.extensions.get("aplsai_operational_export"):
        return

    @app.get("/api/admin/operational-export.xlsx")
    def operational_export():
        uid = session.get("uid")
        actor = app_module.db.session.get(app_module.User, uid) if uid else None
        if not actor:
            return jsonify(error="Non autenticato."), 401
        if getattr(actor, "active", True) is False:
            session.clear()
            return jsonify(error="Account disattivato."), 401
        if not has_permission(actor.role, "staff_manage"):
            return jsonify(error="Permesso insufficiente."), 403

        wb = Workbook()
        wb.remove(wb.active)
        generated_at = datetime.now(timezone.utc)
        _sheet(wb, "Informazioni", ["Campo", "Valore"], [
            ("Pacchetto", "APLSAI HOME - Esportazione operativa"),
            ("Generato il", generated_at.isoformat()),
            ("Origine", "Area Admin APLSAI HOME"),
            ("Regola aggiornamento", "Usare gli ID come chiave; aggiornare le righe esistenti senza duplicarle."),
            ("Classificazione", "I dati di prova sono identificati e separati dai clienti reali."),
            ("Riservatezza", "Contiene dati personali: conservare in posizione protetta."),
        ])

        profiles = {p.user_id: p for p in app_module.ClientProfile.query.all()}
        clients = app_module.User.query.filter_by(role="client").order_by(app_module.User.id.asc()).all()
        _sheet(wb, "Clienti", [
            "ID cliente", "Nome", "Email", "Telefono", "Attivo", "Creato il",
            "Tipo dato", "Archiviato il", "Stato", "Strategia", "Ultimo contatto",
            "Ultima proposta", "N. proposte",
        ], [(
            u.id, u.name, u.email, u.phone, bool(getattr(u, "active", True)), _iso(u.created_at),
            "Prova" if bool(getattr(profiles.get(u.id), "is_test", False)) else "Reale",
            _iso(getattr(profiles.get(u.id), "archived_at", None)),
            profiles[u.id].status if u.id in profiles else "",
            profiles[u.id].preferred_strategy if u.id in profiles else "",
            _iso(profiles[u.id].last_contact_at) if u.id in profiles else "",
            _iso(profiles[u.id].last_proposal_at) if u.id in profiles else "",
            profiles[u.id].proposal_count or 0 if u.id in profiles else 0,
        ) for u in clients])

        profile_rows = []
        for client in clients:
            cp = profiles.get(client.id)
            try:
                data = json.loads(cp.profile_json) if cp else {}
            except (TypeError, ValueError):
                data = {}
            zone, budget, spaces = data.get("zone") or {}, data.get("budget") or {}, data.get("spaces") or {}
            profile_rows.append((
                client.id, zone.get("main", ""), zone.get("km", ""), budget.get("ideal", ""),
                budget.get("max", ""), budget.get("flex", ""), spaces.get("sqm", ""),
                spaces.get("beds", ""), spaces.get("baths", ""), _join(data.get("must")),
                data.get("timing", ""), _join(data.get("houseTypes")), _join(data.get("purchase")),
                data.get("style", ""), json.dumps(data, ensure_ascii=False),
            ))
        _sheet(wb, "Profili abitativi", [
            "ID cliente", "Tipo dato", "Archiviato il", "Zona principale", "Distanza km",
            "Budget ideale", "Budget massimo",
            "Flessibilità %", "Metratura", "Camere", "Bagni", "Indispensabili", "Tempistica",
            "Tipologie casa", "Stato acquisto", "Stile", "Profilo JSON originale",
        ], [(
            row[0],
            "Prova" if bool(getattr(profiles.get(row[0]), "is_test", False)) else "Reale",
            _iso(getattr(profiles.get(row[0]), "archived_at", None)),
            *row[1:],
        ) for row in profile_rows])

        _sheet(wb, "Immobili", [
            "ID immobile", "Riferimento", "Tipologia", "Indirizzo", "Zona", "Prezzo", "Mq",
            "Camere", "Bagni", "Piano", "Ascensore", "Esposizione", "Spazi esterni",
            "Parcheggio", "Stato manutentivo", "Classe energetica", "Stato impianti",
            "Disponibilità", "Vincoli conosciuti", "Trasformabilità", "Interventi ipotizzati",
            "Costo lavori minimo", "Costo lavori massimo", "Mesi minimi", "Mesi massimi",
            "Affidabilità dati", "Verifica tecnica", "Fonte", "Note", "Archiviato il",
            "Creato il", "Aggiornato il",
        ], [
            (
                p.id, p.ref, p.property_type, p.address, p.zone, p.price, p.sqm, p.beds,
                p.baths, p.floor, p.elevator, p.exposure, p.outdoor_spaces, p.parking,
                p.state, p.energy_class, p.systems_status, p.availability,
                p.known_constraints, p.transformation_status, p.planned_works,
                p.renovation_cost_min, p.renovation_cost_max, p.renovation_months_min,
                p.renovation_months_max, p.data_reliability, p.technical_verification,
                p.source, p.notes, _iso(p.archived_at), _iso(p.created_at), _iso(p.updated_at),
            )
            for p in app_module.Property.query.order_by(app_module.Property.id.asc()).all()
        ])

        property_ext = app.extensions.get("aplsai_property_profiles") or {}
        PropertyRevision = property_ext.get("PropertyRevision")
        revisions = PropertyRevision.query.order_by(PropertyRevision.property_id.asc(), PropertyRevision.version.asc()).all() if PropertyRevision else []
        _sheet(wb, "Storico immobili", [
            "ID revisione", "ID immobile", "Versione", "ID autore", "Motivo", "Data", "Fotografia JSON",
        ], [(
            row.id, row.property_id, row.version, row.changed_by_user_id,
            row.change_note, _iso(row.created_at), row.snapshot_json,
        ) for row in revisions])

        scenario_ext = app.extensions.get("aplsai_scenarios") or {}
        Scenario = scenario_ext.get("PropertyScenario")
        CostItem = scenario_ext.get("ScenarioCostItem")
        ScenarioRevision = scenario_ext.get("ScenarioRevision")
        scenarios = Scenario.query.order_by(Scenario.id.asc()).all() if Scenario else []
        scenario_dict = scenario_ext.get("scenario_dict")
        _sheet(wb, "Scenari", [
            "ID", "ID immobile", "Riferimento", "ID cliente", "Nome cliente", "Nome scenario",
            "Tipo", "Stato", "Descrizione", "Mq risultanti", "Camere risultanti",
            "Bagni risultanti", "Mesi minimi", "Mesi massimi", "Ipotesi", "Vincoli",
            "Validazione tecnica", "Versione", "Totale conosciuto minimo",
            "Totale conosciuto massimo", "Voci mancanti", "Archiviato il", "Aggiornato il",
        ], [(
            row.id, row.property_id, data.get("property_ref"), row.client_id, data.get("client_name"),
            row.name, row.scenario_type, row.status, row.description, row.projected_sqm,
            row.projected_beds, row.projected_baths, row.months_min, row.months_max,
            row.assumptions, row.constraints, row.technical_validation, row.version,
            data["totals"]["known_total_min"], data["totals"]["known_total_max"],
            ", ".join(data["totals"]["missing_categories"]), _iso(row.archived_at), _iso(row.updated_at),
        ) for row in scenarios for data in [scenario_dict(row)]])
        cost_items = CostItem.query.order_by(CostItem.scenario_id.asc(), CostItem.id.asc()).all() if CostItem else []
        _sheet(wb, "Costi scenari", [
            "ID voce", "ID scenario", "Categoria", "Descrizione", "Quantità", "Unità",
            "Prezzo unitario minimo", "Prezzo unitario massimo", "Totale minimo", "Totale massimo",
            "Fonte", "Affidabilità", "Creato il",
        ], [(
            row.id, row.scenario_id, row.category, row.description, row.quantity, row.unit,
            row.unit_price_min, row.unit_price_max, row.quantity * row.unit_price_min,
            row.quantity * row.unit_price_max, row.source, row.reliability, _iso(row.created_at),
        ) for row in cost_items])
        scenario_revisions = ScenarioRevision.query.order_by(ScenarioRevision.scenario_id.asc(), ScenarioRevision.version.asc()).all() if ScenarioRevision else []
        _sheet(wb, "Storico scenari", [
            "ID revisione", "ID scenario", "Versione", "ID autore", "Motivo", "Data", "Fotografia JSON",
        ], [(
            row.id, row.scenario_id, row.version, row.changed_by_user_id,
            row.change_note, _iso(row.created_at), row.snapshot_json,
        ) for row in scenario_revisions])

        feasibility_ext = app.extensions.get("aplsai_feasibility") or {}
        Analysis = feasibility_ext.get("FeasibilityAnalysis")
        AnalysisRevision = feasibility_ext.get("FeasibilityRevision")
        analysis_dict = feasibility_ext.get("analysis_dict")
        analyses = Analysis.query.order_by(Analysis.id.asc()).all() if Analysis else []
        _sheet(wb, "Fattibilità operazioni", [
            "ID", "ID immobile", "Riferimento", "ID scenario", "Scenario", "Nome analisi",
            "Stato", "Vendita attesa", "Altri ricavi", "Capitale AP", "Finanziamento esterno",
            "Risk Budget", "Margine obiettivo %", "Durata Base mesi", "Decisione",
            "Costi conosciuti Base", "Categorie mancanti", "Versione", "Note", "Aggiornato il",
        ], [(
            row.id, row.property_id, data.get("property_ref"), row.scenario_id, data.get("scenario_name"),
            row.name, row.status, row.expected_sale_value, row.other_income, row.ap_capital,
            row.external_financing, row.risk_budget, row.target_margin_percent,
            row.base_duration_months, data["results"]["decision"], data["results"]["known_cost_base"],
            ", ".join(data["results"]["missing_categories"]), row.version, row.notes, _iso(row.updated_at),
        ) for row in analyses for data in [analysis_dict(row)]])
        _sheet(wb, "Stress test", [
            "ID analisi", "Scenario rischio", "Riduzione ricavi %", "Aumento costi %",
            "Ritardo mesi", "Durata mesi", "Ricavi", "Costi", "Risultato",
            "Margine ricavi %", "Margine costi %", "ROI capitale AP %", "Perdita massima",
            "Risk Budget", "Stato rischio", "Fabbisogno cassa", "Capitale AP esposto",
            "Fabbisogno scoperto", "Prezzo massimo acquisto",
        ], [(
            row.id, case["label"], case["revenue_reduction_percent"], case["cost_increase_percent"],
            case["delay_months"], case["duration_months"], case["revenue"], case["total_cost"],
            case["profit"], case["margin_on_revenue_percent"], case["margin_on_cost_percent"],
            case["roi_ap_percent"], case["loss"], data["results"]["risk_budget"], case["risk_status"],
            case["estimated_peak_cash_need"], case["ap_exposure"], case["funding_gap"],
            case["maximum_acquisition_price"],
        ) for row in analyses for data in [analysis_dict(row)] for case in data["results"]["cases"]])
        analysis_revisions = AnalysisRevision.query.order_by(AnalysisRevision.analysis_id.asc(), AnalysisRevision.version.asc()).all() if AnalysisRevision else []
        _sheet(wb, "Storico fattibilità", [
            "ID revisione", "ID analisi", "Versione", "ID autore", "Motivo", "Data", "Fotografia JSON",
        ], [(
            row.id, row.analysis_id, row.version, row.changed_by_user_id,
            row.change_note, _iso(row.created_at), row.snapshot_json,
        ) for row in analysis_revisions])

        cash_ext = app.extensions.get("aplsai_cashflow") or {}
        CashPlan = cash_ext.get("CashFlowPlan")
        CashMovement = cash_ext.get("CashFlowMovement")
        CashRevision = cash_ext.get("CashFlowRevision")
        cash_serializer = cash_ext.get("plan_dict")
        cash_plans = CashPlan.query.order_by(CashPlan.id.asc()).all() if CashPlan else []
        _sheet(wb, "Piani di cassa", [
            "ID", "ID analisi", "Analisi", "Immobile", "Nome piano", "Mese iniziale",
            "Cassa iniziale", "Linea aggiuntiva", "Stato", "Decisione", "Versione",
            "Costi scenario", "Costi pianificati", "Da pianificare", "Sovrapianificato",
            "Archiviato il", "Aggiornato il", "Note",
        ], [(
            row.id, row.analysis_id, data.get("analysis_name"), data.get("property_ref"), row.name,
            row.start_month, row.opening_cash, row.additional_credit_limit, row.status,
            data["results"]["decision"], row.version,
            data["results"]["reconciliation"]["scenario_cost_max"],
            data["results"]["reconciliation"]["planned_cost_max"],
            data["results"]["reconciliation"]["remaining_to_schedule"],
            data["results"]["reconciliation"]["over_scheduled"],
            _iso(row.archived_at), _iso(row.updated_at), row.notes,
        ) for row in cash_plans for data in [cash_serializer(row)]])
        cash_movements = CashMovement.query.order_by(CashMovement.plan_id.asc(), CashMovement.month_index.asc()).all() if CashMovement else []
        _sheet(wb, "Movimenti di cassa", [
            "ID", "ID piano", "Mese progressivo", "Tipo", "Categoria", "Descrizione",
            "Importo minimo", "Importo massimo", "Fonte", "Affidabilità", "Automatico",
        ], [(
            row.id, row.plan_id, row.month_index, row.movement_type, row.category, row.description,
            row.amount_min, row.amount_max, row.source, row.reliability, bool(row.system_generated),
        ) for row in cash_movements])
        _sheet(wb, "Cassa mensile", [
            "ID piano", "Mese progressivo", "Mese", "Entrate min", "Entrate max",
            "Uscite min", "Uscite max", "Saldo prudente", "Saldo massimo",
        ], [(
            row.id, month["month_index"], month["month"], month["inflow_min"], month["inflow_max"],
            month["outflow_min"], month["outflow_max"], month["balance_min"], month["balance_max"],
        ) for row in cash_plans for data in [cash_serializer(row)] for month in data["results"]["months"]])
        _sheet(wb, "Stress di cassa", [
            "ID piano", "Scenario", "Saldo minimo", "Mese picco", "Fabbisogno aggiuntivo",
            "Linea disponibile", "Copertura", "Saldo finale",
        ], [(
            row.id, case["label"], case["minimum_balance"], case["peak_month"],
            case["additional_funding_need"], case["credit_limit"], case["coverage_status"],
            case["closing_balance"],
        ) for row in cash_plans for data in [cash_serializer(row)] for case in data["results"]["stress_cases"]])
        cash_revisions = CashRevision.query.order_by(CashRevision.plan_id.asc(), CashRevision.version.asc()).all() if CashRevision else []
        _sheet(wb, "Storico cassa", [
            "ID revisione", "ID piano", "Versione", "ID autore", "Motivo", "Data", "Fotografia JSON",
        ], [(
            row.id, row.plan_id, row.version, row.changed_by_user_id,
            row.change_note, _iso(row.created_at), row.snapshot_json,
        ) for row in cash_revisions])

        operations_ext = app.extensions.get("aplsai_operations") or {}
        Operation = operations_ext.get("ClientOperation")
        operations = Operation.query.order_by(Operation.client_id.asc()).all() if Operation else []
        _sheet(wb, "Pratiche", [
            "ID cliente", "Tipo dato", "Archiviato il", "Fase", "Stato finanziario",
            "Priorità", "Verificato il", "Prossima azione",
            "Scadenza", "Responsabile", "Motivo blocco", "Aggiornato il",
        ], [(
            op.client_id,
            "Prova" if bool(getattr(profiles.get(op.client_id), "is_test", False)) else "Reale",
            _iso(getattr(profiles.get(op.client_id), "archived_at", None)),
            op.phase, op.financial_state, op.to_dict().get("priority", ""),
            _iso(op.financial_verified_at), op.next_action, _iso(op.next_action_due_at),
            op.assigned_to, op.blocked_reason, _iso(op.updated_at),
        ) for op in operations])

        _sheet(wb, "Trattative", ["ID", "ID cliente", "ID immobile", "Riferimento", "Fase", "Aggiornato il"], [
            (d.id, d.client_id, d.property_id, d.ref, d.stage, _iso(d.updated_at))
            for d in app_module.Deal.query.order_by(app_module.Deal.id.asc()).all()
        ])
        _sheet(wb, "Referral", ["ID", "ID cliente", "Email invitato", "Codice", "Stato", "Premio", "Creato il"], [
            (r.id, r.owner_id, r.friend_email, r.code, r.status, r.reward, _iso(r.created_at))
            for r in app_module.Referral.query.order_by(app_module.Referral.id.asc()).all()
        ])
        _sheet(wb, "Documenti", ["ID", "ID cliente", "Titolo", "Riferimento documento", "Creato il"], [
            (d.id, d.client_id, d.title, d.url, _iso(d.created_at))
            for d in app_module.Document.query.order_by(app_module.Document.id.asc()).all()
        ])
        _sheet(wb, "Aggiornamenti", ["ID", "ID cliente", "Data", "Messaggio"], [
            (u.id, u.client_id, _iso(u.created_at), u.message)
            for u in app_module.Update.query.order_by(app_module.Update.id.asc()).all()
        ])
        staff = app_module.User.query.filter(app_module.User.role.in_(["staff", "operator", "partner"])).order_by(app_module.User.id.asc()).all()
        _sheet(wb, "Collaboratori", ["ID", "Nome", "Email", "Ruolo", "Attivo", "Creato il"], [
            (u.id, u.name, u.email, "admin" if u.role == "staff" else u.role, bool(getattr(u, "active", True)), _iso(u.created_at))
            for u in staff
        ])
        Audit = operations_ext.get("AuditEvent")
        events = Audit.query.order_by(Audit.id.asc()).all() if Audit else []
        _sheet(wb, "Audit", ["ID", "ID autore", "Azione", "Tipo oggetto", "ID oggetto", "Esito", "Dettaglio", "Data"], [
            (e.id, e.actor_user_id, e.action, e.object_type, e.object_id, e.outcome, e.detail, _iso(e.created_at))
            for e in events
        ])

        audit = operations_ext.get("audit")
        if audit:
            audit(actor, "operational_export", "system", "xlsx", "Pacchetto operativo scaricato")
            app_module.db.session.commit()

        stream = BytesIO()
        wb.save(stream)
        stream.seek(0)
        filename = f"APLSAI_HOME_Pacchetto_Operativo_{generated_at:%Y-%m-%d_%H%M}.xlsx"
        return send_file(
            stream,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            max_age=0,
        )

    app.extensions["aplsai_operational_export"] = {"installed": True}
