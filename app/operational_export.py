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

        opportunity_ext = app.extensions.get("aplsai_opportunities") or {}
        Opportunity = opportunity_ext.get("PropertyOpportunity")
        OpportunityRevision = opportunity_ext.get("OpportunityRevision")
        opportunity_serializer = opportunity_ext.get("opportunity_dict")
        opportunities = Opportunity.query.order_by(Opportunity.id.asc()).all() if Opportunity else []
        opportunity_data = [(row, opportunity_serializer(row, include_details=True)) for row in opportunities] if opportunity_serializer else []
        _sheet(wb, "Opportunità immobiliari", [
            "ID", "Titolo", "Tipo fonte", "Fonte", "Collegamento", "Riferimento fonte",
            "Contatto", "Recapito", "Zona", "Indirizzo", "Prezzo", "Mq", "Tipologia",
            "Stato immobile", "Disponibilità", "Documenti", "Planimetria", "Analisi",
            "Affidabilità", "Fase opportunità", "Rischi", "Potenziale", "Decisione",
            "Nota decisionale", "Motivo esclusione", "Ultimo controllo", "ID immobile",
            "Versione", "Archiviata il", "Aggiornata il", "Note",
        ], [(
            row.id, row.title, row.source_type, row.source_name, row.source_url, row.external_ref,
            row.contact_name, row.contact_details, row.zone, row.address, row.price, row.sqm,
            row.property_type, row.state, row.availability, row.documents_status,
            row.planimetry_status, row.analysis_status, row.data_reliability, row.status,
            row.risks, row.potential, row.decision, row.decision_note, row.rejection_reason,
            row.last_checked_on.isoformat() if row.last_checked_on else "", row.linked_property_id,
            row.version, _iso(row.archived_at), _iso(row.updated_at), row.notes,
        ) for row in opportunities])
        _sheet(wb, "Compatibilità opportunità", [
            "ID opportunità", "Titolo", "ID cliente", "Cliente", "Esito preliminare", "Verifiche",
        ], [(
            row.id, row.title, match.get("client_id"), match.get("client_name"),
            match.get("recommendation"),
            "; ".join(f"{item.get('criterion')}: {item.get('status')}" for item in match.get("checks") or []),
        ) for row, data in opportunity_data for match in data.get("preliminary_matches", [])])
        opportunity_revisions = OpportunityRevision.query.order_by(OpportunityRevision.opportunity_id.asc(), OpportunityRevision.version.asc()).all() if OpportunityRevision else []
        _sheet(wb, "Storico opportunità", [
            "ID revisione", "ID opportunità", "Versione", "ID autore", "Motivo", "Data", "Fotografia JSON",
        ], [(
            row.id, row.opportunity_id, row.version, row.changed_by_user_id,
            row.change_note, _iso(row.created_at), row.snapshot_json,
        ) for row in opportunity_revisions])

        outreach_ext = app.extensions.get("aplsai_outreach") or {}
        Inquiry = outreach_ext.get("OpportunityInquiry")
        Reply = outreach_ext.get("InquiryReply")
        inquiries = Inquiry.query.order_by(Inquiry.id.asc()).all() if Inquiry else []
        _sheet(wb, "Richieste informazioni", [
            "ID richiesta", "ID opportunità", "Destinatario", "Email", "Verificato",
            "Oggetto", "Stato", "Dati richiesti JSON", "Domande aggiuntive JSON",
            "Approvata il", "Inviata il", "ID conversazione", "Creata il", "Aggiornata il",
        ], [(
            row.id, row.opportunity_id, row.recipient_name, row.recipient_email,
            bool(row.recipient_verified), row.subject, row.status, row.missing_fields_json,
            row.custom_questions_json, _iso(row.approved_at), _iso(row.sent_at),
            row.external_thread_id, _iso(row.created_at), _iso(row.updated_at),
        ) for row in inquiries])
        replies = Reply.query.order_by(Reply.inquiry_id.asc(), Reply.received_at.asc()).all() if Reply else []
        _sheet(wb, "Risposte immobili", [
            "ID risposta", "ID richiesta", "Email mittente", "Stato", "Ricevuta il",
            "Dati proposti JSON", "ID messaggio", "Esaminata il", "Testo risposta",
        ], [(
            row.id, row.inquiry_id, row.sender_email, row.status, _iso(row.received_at),
            row.extracted_json, row.source_message_id, _iso(row.reviewed_at), row.body,
        ) for row in replies])

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
        AnalysisDecision = feasibility_ext.get("FeasibilityDecision")
        analysis_dict = feasibility_ext.get("analysis_dict")
        analyses = Analysis.query.order_by(Analysis.id.asc()).all() if Analysis else []
        _sheet(wb, "Fattibilità operazioni", [
            "ID", "ID immobile", "Riferimento", "ID scenario", "Scenario", "Nome analisi",
            "Stato", "Vendita attesa", "Altri ricavi", "Capitale AP", "Finanziamento esterno",
            "Risk Budget", "Margine obiettivo %", "Durata Base mesi", "Decisione completa", "Decisione economica",
            "Costi conosciuti Base", "Preventivi CO 01 applicati", "Preventivi verificati", "Categorie mancanti", "Versione", "Note", "Aggiornato il",
        ], [(
            row.id, row.property_id, data.get("property_ref"), row.scenario_id, data.get("scenario_name"),
            row.name, row.status, row.expected_sale_value, row.other_income, row.ap_capital,
            row.external_financing, row.risk_budget, row.target_margin_percent,
            row.base_duration_months, data["results"]["decision"], data["results"].get("economic_decision"), data["results"]["known_cost_base"],
            data["results"].get("quote_basis", {}).get("applied", False), data["results"].get("quote_basis", {}).get("verified", 0),
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
        analysis_decisions = AnalysisDecision.query.order_by(AnalysisDecision.analysis_id.asc(), AnalysisDecision.id.asc()).all() if AnalysisDecision else []
        _sheet(wb, "Decisioni fattibilità", [
            "ID", "ID analisi", "Decisione", "Condizioni", "Evidenza", "Difetti residui",
            "Costo a finire", "ID decisore", "Versione analisi", "Data",
        ], [(
            row.id, row.analysis_id, row.decision, row.conditions, row.evidence_ref,
            row.residual_defects, row.cost_to_complete, row.decided_by_user_id,
            row.analysis_version, _iso(row.created_at),
        ) for row in analysis_decisions])

        investor_ext = app.extensions.get("aplsai_investors") or {}
        Investor = investor_ext.get("InvestorProfile")
        Commitment = investor_ext.get("InvestorCommitment")
        FundingPlan = investor_ext.get("InvestorFundingPlan")
        investor_serializer = investor_ext.get("investor_dict")
        commitment_serializer = investor_ext.get("commitment_dict")
        coverage_serializer = investor_ext.get("coverage_for_analysis")
        investors = Investor.query.order_by(Investor.id.asc()).all() if Investor else []
        _sheet(wb, "Investitori", [
            "ID", "Nome", "Email", "Telefono", "Tipo", "Capitale dichiarato",
            "Stato", "Verifica", "NDA firmato", "Capitale confermato",
            "Interesse non confermato", "Archiviato il", "Aggiornato il", "Note",
        ], [(
            row.id, row.name, row.email, row.phone, row.investor_type,
            row.available_capital, row.status, row.verification, bool(row.nda_signed),
            data.get("confirmed_capital"), data.get("interest_capital"),
            _iso(row.archived_at), _iso(row.updated_at), row.notes,
        ) for row in investors for data in [investor_serializer(row)]])
        commitments = Commitment.query.order_by(Commitment.analysis_id.asc(), Commitment.id.asc()).all() if Commitment else []
        _sheet(wb, "Impegni investitori", [
            "ID", "ID investitore", "Investitore", "ID analisi", "Importo", "Stato",
            "Conteggiato nella copertura", "Fonte", "Riferimento documento", "Creato il", "Note",
        ], [(
            row.id, row.investor_id, data.get("investor_name"), row.analysis_id,
            row.amount, row.status, data.get("counted_as_coverage"), row.source,
            row.document_reference, _iso(row.created_at), row.notes,
        ) for row in commitments for data in [commitment_serializer(row)]])
        funding_plans = FundingPlan.query.order_by(FundingPlan.analysis_id.asc()).all() if FundingPlan else []
        _sheet(wb, "Copertura investimenti", [
            "ID analisi", "Margine imprevisti %", "Stato piano", "Costo Base",
            "Capitale totale richiesto", "Capitale AP", "Finanziamento esterno",
            "Richiesto agli investitori", "Confermato", "Mancante", "Copertura %",
            "Decisione", "Aggiornato il", "Note",
        ], [(
            row.analysis_id, row.contingency_percent, row.status,
            data.get("total_cost_base"), data.get("gross_capital_required"),
            data.get("ap_capital"), data.get("external_financing"),
            data.get("investor_capital_required"), data.get("confirmed_investor_capital"),
            data.get("remaining_to_cover"), data.get("coverage_percent"), data.get("decision"),
            _iso(row.updated_at), row.notes,
        ) for row in funding_plans for analysis in [app_module.db.session.get(Analysis, row.analysis_id)]
          if analysis for data in [coverage_serializer(analysis)]])

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
        control_ext = app.extensions.get("aplsai_cash_controls") or {}
        CashControl = control_ext.get("CashControl")
        CashMilestone = control_ext.get("CashMilestone")
        CashControlEvent = control_ext.get("CashControlEvent")
        controls = CashControl.query.order_by(CashControl.plan_id.asc()).all() if CashControl else []
        _sheet(wb, "Controlli di cassa", [
            "ID", "ID piano", "Modalità", "Riserva imprevisti %", "Anticipazione %",
            "Titoli non quietanzati %", "Limite capitale proprio", "Mesi riserva",
            "Versione", "Aggiornato il", "Note",
        ], [(
            row.id, row.plan_id, row.mode, row.contingency_percent, row.advance_percent,
            row.unpaid_titles_percent, row.own_capital_limit, row.reserve_months,
            row.version, _iso(row.updated_at), row.notes,
        ) for row in controls])
        milestones = CashMilestone.query.order_by(CashMilestone.control_id.asc(), CashMilestone.number.asc()).all() if CashMilestone else []
        _sheet(wb, "SAL e pagamenti", [
            "ID", "ID controllo", "Numero", "Titolo", "Risultato verificabile", "Importo pianificato",
            "Scadenza", "Stato", "Evidenza", "Nota verifica", "Difetti critici", "Verificata il",
            "Stato pagamento", "Autorizzato il", "Importo pagato", "Riferimento pagamento", "Pagato il",
        ], [(
            row.id, row.control_id, row.number, row.title, row.deliverable, row.planned_amount,
            _iso(row.due_at), row.status, row.evidence_ref, row.verification_note, row.critical_defects,
            _iso(row.verified_at), row.payment_status, _iso(row.authorized_at), row.paid_amount,
            row.payment_reference, _iso(row.paid_at),
        ) for row in milestones])
        control_events = CashControlEvent.query.order_by(CashControlEvent.id.asc()).all() if CashControlEvent else []
        _sheet(wb, "Storico controlli cassa", ["ID", "ID controllo", "ID SAL", "ID autore", "Azione", "Nota", "Data"], [
            (row.id, row.control_id, row.milestone_id, row.actor_user_id, row.action, row.note, _iso(row.created_at))
            for row in control_events
        ])
        launch_ext = app.extensions.get("aplsai_launch_control") or {}
        OperationLaunch = launch_ext.get("OperationLaunch")
        LaunchCheck = launch_ext.get("LaunchCheck")
        LaunchEvent = launch_ext.get("LaunchEvent")
        launches = OperationLaunch.query.order_by(OperationLaunch.id.asc()).all() if OperationLaunch else []
        _sheet(wb, "Avvio operazioni", [
            "ID", "ID analisi", "ID responsabile", "Stato", "Decisione finale", "Verbale finale",
            "ID autorizzatore", "Autorizzato il", "Versione", "Creato il", "Aggiornato il",
        ], [(
            row.id, row.analysis_id, row.assigned_to_user_id, row.status, row.final_decision,
            row.final_note, row.authorized_by_user_id, _iso(row.authorized_at), row.version,
            _iso(row.created_at), _iso(row.updated_at),
        ) for row in launches])
        launch_checks = LaunchCheck.query.order_by(LaunchCheck.launch_id.asc(), LaunchCheck.code.asc()).all() if LaunchCheck else []
        _sheet(wb, "Controlli avvio", [
            "ID", "ID avvio", "Codice", "Controllo", "Risultato atteso", "Stato automatico",
            "Dettaglio automatico", "Evidenza", "Difetti residui", "Azione correttiva",
            "Verifica Admin", "Nota verifica", "ID verificatore", "Verificato il",
        ], [(
            row.id, row.launch_id, row.code, row.title, row.expected_result, row.automatic_status,
            row.automatic_detail, row.evidence_ref, row.residual_defects, row.corrective_action,
            row.verification_status, row.verification_note, row.verified_by_user_id, _iso(row.verified_at),
        ) for row in launch_checks])
        launch_events = LaunchEvent.query.order_by(LaunchEvent.id.asc()).all() if LaunchEvent else []
        _sheet(wb, "Storico avvii", ["ID", "ID avvio", "ID autore", "Azione", "Dettaglio", "Data"], [
            (row.id, row.launch_id, row.actor_user_id, row.action, row.detail, _iso(row.created_at)) for row in launch_events
        ])

        worksite_ext = app.extensions.get("aplsai_worksites") or {}
        WorksiteProject = worksite_ext.get("WorksiteProject")
        WorksitePhase = worksite_ext.get("WorksitePhase")
        WorksiteVariation = worksite_ext.get("WorksiteVariation")
        WorksiteEvent = worksite_ext.get("WorksiteEvent")
        worksite_serializer = worksite_ext.get("project_dict")
        worksites = WorksiteProject.query.order_by(WorksiteProject.id.asc()).all() if WorksiteProject else []
        _sheet(wb, "Cantieri", [
            "ID", "ID avvio", "ID analisi", "Nome", "Stato", "ID responsabile", "Validatore tecnico",
            "Budget iniziale", "Costi impegnati", "Spese effettive", "Costo a finire", "Varianti approvate",
            "Previsione finale", "Budget residuo", "Avanzamento %", "Segnalazioni", "Inizio previsto",
            "Fine prevista", "Inizio effettivo", "Fine effettiva", "Evidenza chiusura", "Verbale chiusura", "Versione",
        ], [(
            row.id, row.launch_id, row.analysis_id, row.name, row.status, row.responsible_user_id,
            row.technical_validator, data.get("initial_budget"), data.get("committed_cost"), data.get("spent_cost"),
            data.get("cost_to_complete"), data.get("approved_variations"), data.get("forecast_final_cost"),
            data.get("budget_remaining"), data.get("progress_percent"), "; ".join(data.get("alerts") or []),
            _iso(row.planned_start_at), _iso(row.planned_end_at), _iso(row.actual_start_at), _iso(row.actual_end_at),
            row.closing_evidence, row.closing_note, row.version,
        ) for row in worksites for data in [worksite_serializer(row) if worksite_serializer else {}]])
        phases = WorksitePhase.query.order_by(WorksitePhase.project_id.asc(), WorksitePhase.code.asc()).all() if WorksitePhase else []
        _sheet(wb, "Fasi cantiere", [
            "ID", "ID cantiere", "ID SAL", "Codice", "Titolo", "Descrizione", "ID responsabile", "Fornitore",
            "Contatto fornitore", "Inizio previsto", "Fine prevista", "Inizio effettivo", "Fine effettiva",
            "Costo previsto", "Costo impegnato", "Speso", "Costo a finire", "Avanzamento %", "Stato",
            "Soglia accettazione", "Esito prova", "Risultato osservato", "Evidenza", "Non conformità",
            "Difetti critici", "Difetti residui", "Azioni obbligatorie", "Responsabile azione", "Scadenza azione",
            "Condizioni passaggio", "Validazione tecnica", "Decisione Admin", "Nota Admin", "ID verificatore", "Verificato il",
        ], [(
            row.id, row.project_id, row.milestone_id, row.code, row.title, row.description, row.responsible_user_id,
            row.supplier_name, row.supplier_contact, _iso(row.planned_start_at), _iso(row.planned_end_at),
            _iso(row.actual_start_at), _iso(row.actual_end_at), row.planned_cost, row.committed_cost, row.spent_cost,
            row.cost_to_complete, row.progress_percent, row.status, row.acceptance_threshold, row.test_result,
            row.observed_result, row.evidence_ref, row.nonconformities, row.critical_defects, row.residual_defects,
            row.mandatory_actions, row.action_owner, _iso(row.action_due_at), row.transition_conditions,
            row.technical_validation, row.admin_decision, row.admin_note, row.verified_by_user_id, _iso(row.verified_at),
        ) for row in phases])
        variations = WorksiteVariation.query.order_by(WorksiteVariation.project_id.asc(), WorksiteVariation.code.asc()).all() if WorksiteVariation else []
        _sheet(wb, "Varianti cantiere", [
            "ID", "ID cantiere", "ID fase", "Codice", "Descrizione", "Motivo", "Impatto costo", "Ritardo giorni",
            "Impatto margine", "Evidenza", "Stato", "ID richiedente", "ID decisore", "Motivazione decisione", "Decisa il", "Creata il",
        ], [(row.id, row.project_id, row.phase_id, row.code, row.description, row.reason, row.cost_impact,
             row.delay_days, row.margin_impact, row.evidence_ref, row.status, row.requested_by_user_id,
             row.decided_by_user_id, row.decision_note, _iso(row.decided_at), _iso(row.created_at)) for row in variations])
        worksite_events = WorksiteEvent.query.order_by(WorksiteEvent.id.asc()).all() if WorksiteEvent else []
        _sheet(wb, "Storico cantieri", ["ID", "ID cantiere", "ID fase", "ID variante", "ID autore", "Azione", "Dettaglio", "Data"], [
            (row.id, row.project_id, row.phase_id, row.variation_id, row.actor_user_id, row.action, row.detail, _iso(row.created_at))
            for row in worksite_events
        ])

        delivery_ext = app.extensions.get("aplsai_deliveries") or {}
        OperationDelivery = delivery_ext.get("OperationDelivery")
        DeliveryCheck = delivery_ext.get("DeliveryCheck")
        DeliveryDefect = delivery_ext.get("DeliveryDefect")
        DeliveryEvent = delivery_ext.get("DeliveryEvent")
        delivery_serializer = delivery_ext.get("delivery_dict")
        deliveries = OperationDelivery.query.order_by(OperationDelivery.id.asc()).all() if OperationDelivery else []
        _sheet(wb, "Consegne", [
            "ID", "ID cantiere", "Cantiere", "Destinazione", "Destinatario", "Contatto", "Stato",
            "Documenti previsti", "Documenti completi", "Completezza %", "Riferimenti tecnici",
            "Chiavi previste", "Chiavi consegnate", "Garanzie", "Assistenza", "Costo previsto",
            "Costo acquisto", "Costo lavori", "Altri costi", "Costo effettivo", "Valore finale",
            "Margine finale", "Scostamento", "Spiegazione scostamento", "Comprensione %", "Soddisfazione %",
            "Evidenza consegna", "Verbale consegna", "Consegnata il", "Decisione finale", "Chiusa il", "Versione",
        ], [(
            row.id, row.worksite_id, data.get("worksite_name"), row.delivery_type, row.recipient_name,
            row.recipient_contact, row.status, row.required_documents, row.complete_documents,
            data.get("documents_percent"), row.technical_documents_ref, row.keys_expected, row.keys_delivered,
            row.warranty_ref, row.assistance_contact, row.planned_total_cost, row.acquisition_cost, row.work_cost,
            row.other_cost, data.get("actual_total_cost"), row.final_value, data.get("final_margin"),
            data.get("cost_variance"), row.variance_explanation, row.comprehension_percent,
            row.satisfaction_percent, row.handover_evidence, row.delivery_note, _iso(row.delivered_at),
            row.closing_note, _iso(row.closed_at), row.version,
        ) for row in deliveries for data in [delivery_serializer(row) if delivery_serializer else {}]])
        delivery_checks = DeliveryCheck.query.order_by(DeliveryCheck.delivery_id.asc(), DeliveryCheck.code.asc()).all() if DeliveryCheck else []
        _sheet(wb, "Controlli consegna", [
            "ID", "ID consegna", "Codice", "Controllo", "Risultato atteso", "Stato automatico",
            "Dettaglio automatico", "Evidenza", "Difetti residui", "Azioni obbligatorie", "Responsabile azione",
            "Verifica Admin", "Nota verifica", "ID verificatore", "Verificato il",
        ], [(row.id, row.delivery_id, row.code, row.title, row.expected_result, row.automatic_status,
             row.automatic_detail, row.evidence_ref, row.residual_defects, row.mandatory_actions,
             row.action_owner, row.verification_status, row.verification_note, row.verified_by_user_id,
             _iso(row.verified_at)) for row in delivery_checks])
        delivery_defects = DeliveryDefect.query.order_by(DeliveryDefect.delivery_id.asc(), DeliveryDefect.id.asc()).all() if DeliveryDefect else []
        _sheet(wb, "Difetti post-consegna", [
            "ID", "ID consegna", "Titolo", "Descrizione", "Gravità", "Stato", "ID responsabile", "Scadenza",
            "Evidenza soluzione", "Nota soluzione", "ID verificatore", "Verificato il", "Creato il", "Aggiornato il",
        ], [(row.id, row.delivery_id, row.title, row.description, row.severity, row.status,
             row.responsible_user_id, _iso(row.due_at), row.evidence_ref, row.resolution_note,
             row.verified_by_user_id, _iso(row.verified_at), _iso(row.created_at), _iso(row.updated_at))
            for row in delivery_defects])
        delivery_events = DeliveryEvent.query.order_by(DeliveryEvent.id.asc()).all() if DeliveryEvent else []
        _sheet(wb, "Storico consegne", ["ID", "ID consegna", "ID difetto", "ID autore", "Azione", "Dettaglio", "Data"], [
            (row.id, row.delivery_id, row.defect_id, row.actor_user_id, row.action, row.detail, _iso(row.created_at))
            for row in delivery_events
        ])

        partner_ext = app.extensions.get("aplsai_partners") or {}
        Partner = partner_ext.get("Partner")
        PartnerAssignment = partner_ext.get("PartnerAssignment")
        PartnerEvent = partner_ext.get("PartnerEvent")
        partner_serializer = partner_ext.get("partner_dict")
        assignment_serializer = partner_ext.get("assignment_dict")
        partners = Partner.query.order_by(Partner.id.asc()).all() if Partner else []
        _sheet(wb, "Rete partner", [
            "ID", "Nome", "Tipo", "Riferimento fiscale", "Referente", "Email", "Telefono",
            "Zone", "Specializzazioni", "Capacità", "Disponibilità", "Stato documenti", "Rif. documenti",
            "Stato NDA", "Rif. NDA", "Contratto", "Capitolato", "Offerta accettata", "Piano approvato",
            "Dichiarazione conflitti", "Note riservatezza", "Stato idoneità", "Motivazione decisione",
            "Evidenza decisione", "Deciso il", "Requisiti mancanti", "Incarichi", "Prestazioni misurate",
            "Totale preventivi", "Costo fornitore", "Scostamento", "Ritardo medio giorni",
            "Difetti critici", "Non conformità", "Qualità conforme", "Documenti conformi", "Attivo", "Versione",
        ], [(
            row.id, row.name, row.partner_type, row.tax_reference, row.contact_name, row.email, row.phone,
            row.zones, row.specialties, row.capacity_note, row.availability, row.documents_status, row.documents_ref,
            row.nda_status, row.nda_ref, row.contract_ref, row.specifications_ref, row.accepted_offer_ref,
            row.approved_plan_ref, row.conflict_declaration, row.confidentiality_note, row.status, row.decision_note,
            row.decision_evidence, _iso(row.decided_at), _join(data.get("qualification_missing", [])),
            indicators.get("assignments", 0), indicators.get("measured_assignments", 0),
            indicators.get("quoted_total", 0), indicators.get("supplier_cost_total", 0),
            indicators.get("cost_variance", 0), indicators.get("average_delay_days"),
            indicators.get("critical_defects", 0), indicators.get("nonconformities", 0),
            indicators.get("quality_conformity", 0), indicators.get("documentation_conformity", 0),
            bool(row.active), row.version,
        ) for row in partners for data in [partner_serializer(row) if partner_serializer else {}]
          for indicators in [data.get("indicators") or {}]])
        assignments = PartnerAssignment.query.order_by(PartnerAssignment.id.asc()).all() if PartnerAssignment else []
        _sheet(wb, "Prestazioni partner", [
            "ID", "ID partner", "Partner", "Ruolo", "Perimetro", "ID preventivo", "ID cantiere", "ID fase",
            "Assunzioni", "Esclusioni", "Dipendenze", "Preventivo", "Costo finale base", "Extra", "Costo ritardo",
            "Costo non conformità", "Costi operativi", "Costo fornitore", "Scostamento", "Fine promessa",
            "Fine effettiva", "Ritardo giorni", "Stato", "Qualità", "Documentazione", "Evidenza",
            "Difetti critici", "Non conformità", "Nota prestazione", "Accettata il", "Creata il", "Aggiornata il",
        ], [(
            row.id, row.partner_id, partner_names.get(row.partner_id, ""), row.role, row.scope, row.quote_id,
            row.worksite_id, row.phase_id, row.assumptions, row.exclusions, row.dependencies, row.quoted_cost,
            row.final_cost, row.extra_cost, row.delay_cost, row.nonconformity_cost, row.operational_cost,
            data.get("total_supplier_cost", 0), data.get("cost_variance", 0), _iso(row.promised_end_at),
            _iso(row.actual_end_at), data.get("delay_days"), row.status, row.quality_validation,
            row.documentation_validation, row.evidence_ref, row.critical_defects, row.nonconformities,
            row.performance_note, _iso(row.accepted_at), _iso(row.created_at), _iso(row.updated_at),
        ) for row in assignments for data in [assignment_serializer(row) if assignment_serializer else {}]
          for partner_names in [{p.id: p.name for p in partners}]])
        partner_events = PartnerEvent.query.order_by(PartnerEvent.id.asc()).all() if PartnerEvent else []
        _sheet(wb, "Storico partner", ["ID", "ID partner", "ID incarico", "ID autore", "Azione", "Dettaglio", "Data"], [
            (row.id, row.partner_id, row.assignment_id, row.actor_user_id, row.action, row.detail, _iso(row.created_at))
            for row in partner_events
        ])

        procurement_ext = app.extensions.get("aplsai_procurement") or {}
        ProcurementCase = procurement_ext.get("ProcurementCase")
        ProcurementOffer = procurement_ext.get("ProcurementOffer")
        ProcurementEvent = procurement_ext.get("ProcurementEvent")
        procurement_case_serializer = procurement_ext.get("case_dict")
        procurement_offer_serializer = procurement_ext.get("offer_dict")
        procurement_cases = ProcurementCase.query.order_by(ProcurementCase.id.asc()).all() if ProcurementCase else []
        procurement_case_names = {row.id: row.title for row in procurement_cases}
        procurement_case_types = {row.id: row.case_type for row in procurement_cases}
        _sheet(wb, "Confronti offerte", [
            "ID", "Titolo", "Tipo", "Riferimento requisiti", "Capitolato comune", "Quantità/perimetro",
            "Requisiti tecnici", "Budget", "Fonte budget", "Stato", "ID offerta scelta",
            "Motivazione decisione", "Evidenza decisione", "Deciso il", "Numero offerte", "Versione",
        ], [(
            row.id, row.title, row.case_type, row.requirement_ref, row.common_specification, row.quantity_scope,
            row.technical_requirements, row.budget_reference, row.budget_source, row.status, row.selected_offer_id,
            row.decision_note, row.decision_evidence, _iso(row.decided_at), len(data.get("offers", [])), row.version,
        ) for row in procurement_cases for data in [procurement_case_serializer(row) if procurement_case_serializer else {}]])
        procurement_offers = ProcurementOffer.query.order_by(ProcurementOffer.id.asc()).all() if ProcurementOffer else []
        _sheet(wb, "Offerte fornitori", [
            "ID", "ID confronto", "Confronto", "ID partner", "Partner", "Documento offerta", "Moduli/attività",
            "Risultati", "Durata giorni", "Giornate-uomo", "Profili/tariffe", "Tecnologie", "Dipendenze",
            "Esclusioni", "Assunzioni", "IVA", "Milestone/pagamenti", "Una tantum", "Canone mensile",
            "Manutenzione 24m", "Cloud 24m", "IA 24m", "Licenze 24m", "Terze parti 24m", "Subfornitori 24m",
            "Costi esclusi stimati", "Costo totale 24m", "Capacità", "Evidenza capacità", "Repository APLSAI",
            "Account APLSAI", "Documentazione trasferibile", "Terze parti separabili", "IA sostituibile",
            "Clausola uscita", "Protezioni mancanti", "Completezza", "Dati mancanti", "Aderenza funzionale",
            "Qualità tecnica", "IA e dati", "Sicurezza", "Proprietà codice/IP", "Squadra", "Tempi/capacità",
            "Valutazione TCO", "Risultato ponderato", "Fonte valutazione", "Stato verifica", "Nota verifica",
            "Incarichi attivi partner", "Quota incarichi attivi %", "Avviso concentrazione", "Verificata il",
        ], [(
            row.id, row.case_id, procurement_case_names.get(row.case_id, ""), row.partner_id, data.get("partner_name"),
            row.offer_ref, row.modules_detail, row.deliverables, row.duration_days, row.person_days, row.profiles_rates,
            row.technologies, row.dependencies, row.exclusions, row.assumptions, row.vat_note, row.payment_milestones,
            row.one_time_cost, row.recurring_monthly_cost, row.maintenance_24m, row.cloud_24m, row.ai_24m,
            row.licenses_24m, row.third_party_24m, row.subcontractors_24m, row.estimated_excluded_costs,
            data.get("tco_24m", 0), row.capacity_status, row.capacity_evidence, bool(row.repository_aplsai),
            bool(row.accounts_aplsai), bool(row.documentation_transferable), bool(row.third_party_separable),
            bool(row.ai_replaceable), bool(row.exit_clause), _join(data.get("lock_in_missing", [])),
            data.get("completeness"), _join(data.get("missing", [])), scores.get("functional_score"),
            scores.get("technical_score"), scores.get("ai_data_score"), scores.get("cybersecurity_score"),
            scores.get("ip_score"), scores.get("team_score"), scores.get("capacity_score"), scores.get("tco_score"),
            data.get("weighted_score"), row.score_evidence, row.review_status, row.review_note,
            concentration.get("active_assignments", 0), concentration.get("share_percent", 0),
            concentration.get("notice"), _iso(row.reviewed_at),
        ) for row in procurement_offers
          for data in [procurement_offer_serializer(row, procurement_case_types.get(row.case_id)) if procurement_offer_serializer else {}]
          for scores in [data.get("scores") or {}] for concentration in [data.get("concentration") or {}]])
        procurement_events = ProcurementEvent.query.order_by(ProcurementEvent.id.asc()).all() if ProcurementEvent else []
        _sheet(wb, "Storico confronti", ["ID", "ID confronto", "ID offerta", "ID autore", "Azione", "Dettaglio", "Data"], [
            (row.id, row.case_id, row.offer_id, row.actor_user_id, row.action, row.detail, _iso(row.created_at))
            for row in procurement_events
        ])

        portfolio_ext = app.extensions.get("aplsai_portfolio") or {}
        portfolio_serializer = portfolio_ext.get("portfolio_dict")
        portfolio = portfolio_serializer(include_history=True) if portfolio_serializer else {
            "settings": {}, "results": {"cases": [], "plans": [], "decision": "Non disponibile"}, "revisions": [],
        }
        portfolio_settings = portfolio.get("settings") or {}
        portfolio_results = portfolio.get("results") or {}
        _sheet(wb, "Portafoglio", [
            "Decisione", "Piani attivi", "Liquidità AP disponibile", "Riserva minima",
            "Tetto esposizione AP", "Massimo operazioni simultanee", "Versione limiti", "Note",
        ], [(
            portfolio_results.get("decision"), portfolio_results.get("active_plan_count", 0),
            portfolio_settings.get("available_liquidity"), portfolio_settings.get("minimum_liquidity_reserve"),
            portfolio_settings.get("max_ap_exposure"), portfolio_settings.get("max_concurrent_operations"),
            portfolio_settings.get("version", 0), portfolio_settings.get("notes", ""),
        )])
        _sheet(wb, "Stress portafoglio", [
            "Scenario", "Decisione", "Assorbimento massimo", "Esposizione AP massima",
            "Mese critico", "Operazioni simultanee massime", "Liquidità residua minima",
            "Fabbisogno massimo senza copertura", "Limiti superati", "Piani incompleti",
        ], [(
            case.get("label"), case.get("decision"), case.get("peak_cash_absorption"),
            case.get("peak_ap_exposure"), case.get("peak_month"), case.get("max_concurrent_operations"),
            case.get("minimum_remaining_liquidity"), case.get("maximum_uncovered_need"),
            ", ".join(case.get("breaches") or []), ", ".join(case.get("incomplete_plans") or []),
        ) for case in portfolio_results.get("cases", [])])
        _sheet(wb, "Portafoglio mensile", [
            "Scenario", "Mese", "Entrate", "Uscite", "Assorbimento complessivo",
            "Esposizione AP", "Credito utilizzato", "Fabbisogno senza copertura",
            "Liquidità residua", "Operazioni simultanee", "Piani attivi",
        ], [(
            case.get("label"), month.get("month"), month.get("inflows"), month.get("outflows"),
            month.get("gross_cash_absorption"), month.get("ap_exposure"), month.get("credit_used"),
            month.get("uncovered_need"), month.get("remaining_liquidity"),
            month.get("concurrent_operations"),
            ", ".join(item.get("name", "") for item in month.get("active_plans") or []),
        ) for case in portfolio_results.get("cases", []) for month in case.get("months", [])])
        _sheet(wb, "Storico portafoglio", [
            "ID revisione", "ID configurazione", "Versione", "ID autore", "Motivo", "Data", "Fotografia JSON",
        ], [(
            row.get("id"), row.get("settings_id"), row.get("version"), row.get("changed_by_user_id"),
            row.get("change_note"), row.get("created_at"), json.dumps(row.get("snapshot") or {}, ensure_ascii=False),
        ) for row in portfolio.get("revisions", [])])

        capacity_ext = app.extensions.get("aplsai_capacity") or {}
        capacity_serializer = capacity_ext.get("capacity_dict")
        capacity = capacity_serializer() if capacity_serializer else {"teams": [], "allocations": [], "results": {"months": []}}
        _sheet(wb, "Squadre operative", [
            "ID", "Nome", "Società o partner", "Specializzazione", "Responsabile",
            "Capacità mensile giornate-uomo", "Fonte", "Affidabilità", "Versione",
            "Archiviato il", "Aggiornato il", "Note",
        ], [(
            row.get("id"), row.get("name"), row.get("company"), row.get("specialty"),
            row.get("responsible"), row.get("monthly_capacity_days"), row.get("source"),
            row.get("reliability"), row.get("version"), row.get("archived_at"),
            row.get("updated_at"), row.get("notes"),
        ) for row in capacity.get("teams", [])])
        _sheet(wb, "Assegnazioni operative", [
            "ID", "ID squadra", "Squadra", "ID piano", "Operazione", "Immobile", "Mese",
            "Fase", "Giornate-uomo richieste", "Stato", "Dipendenza esterna",
            "Fonte", "Affidabilità", "Aggiornato il", "Note",
        ], [(
            row.get("id"), row.get("team_id"), row.get("team_name"), row.get("plan_id"),
            row.get("plan_name"), row.get("property_ref"), row.get("month"), row.get("phase"),
            row.get("required_worker_days"), row.get("status"), row.get("external_dependency"),
            row.get("source"), row.get("reliability"), row.get("updated_at"), row.get("notes"),
        ) for row in capacity.get("allocations", [])])
        _sheet(wb, "Capacità mensile", [
            "Mese", "ID squadra", "Squadra", "Società", "Capacità giornate-uomo",
            "Giornate-uomo impegnate", "Giornate-uomo residue", "Utilizzo %", "Stato",
        ], [(
            row.get("month"), row.get("team_id"), row.get("team_name"), row.get("company"),
            row.get("capacity_days"), row.get("used_days"), row.get("remaining_days"),
            row.get("utilization_percent"), row.get("status"),
        ) for row in (capacity.get("results") or {}).get("months", [])])
        TeamRevision = capacity_ext.get("TeamRevision")
        team_revisions = TeamRevision.query.order_by(TeamRevision.team_id.asc(), TeamRevision.version.asc()).all() if TeamRevision else []
        _sheet(wb, "Storico squadre", [
            "ID revisione", "ID squadra", "Versione", "ID autore", "Motivo", "Data", "Fotografia JSON",
        ], [(
            row.id, row.team_id, row.version, row.changed_by_user_id,
            row.change_note, _iso(row.created_at), row.snapshot_json,
        ) for row in team_revisions])

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
        transaction_ext = app.extensions.get("aplsai_transactions") or {}
        TransactionCase = transaction_ext.get("TransactionCase")
        TransactionRevision = transaction_ext.get("TransactionRevision")
        transaction_serializer = transaction_ext.get("transaction_dict")
        transaction_names = {user.id: user.name for user in app_module.User.query.all()}
        transactions = TransactionCase.query.order_by(TransactionCase.id.asc()).all() if TransactionCase else []
        _sheet(wb, "Percorso trattative", [
            "ID", "ID trattativa", "Fase calcolata", "ID cliente", "Cliente", "ID immobile",
            "Immobile", "Interesse", "Data interesse", "Caparra", "Stato caparra",
            "Riferimento caparra", "Preliminare", "Riferimento preliminare", "Trascritto il",
            "Cessione", "Riferimento cessione", "Lavori", "Verifica tecnica", "Verifica legale",
            "Chiusura", "Riferimento chiusura", "Data chiusura", "Prossima azione", "Scadenza",
            "ID responsabile", "Responsabile", "Passaggi mancanti", "Versione", "Note", "Aggiornato il",
        ], [(
            row.id, row.deal_id, data.get("stage"), data.get("client_id"), data.get("client_name"),
            data.get("property_id"), data.get("property_ref"), row.interest_status, _iso(row.interest_at),
            row.deposit_amount, row.deposit_status, row.deposit_reference, row.preliminary_status,
            row.preliminary_reference, _iso(row.transcribed_at), row.assignment_status,
            row.assignment_reference, row.works_status, row.technical_validation, row.legal_validation,
            row.closing_status, row.closing_reference, _iso(row.closing_at), row.next_action,
            _iso(row.next_action_due_at), row.assigned_to_user_id,
            transaction_names.get(row.assigned_to_user_id, ""), "; ".join(data.get("missing") or []),
            row.version, row.notes, _iso(row.updated_at),
        ) for row in transactions for data in [transaction_serializer(row) if transaction_serializer else {}]])
        transaction_revisions = TransactionRevision.query.order_by(TransactionRevision.transaction_id.asc(), TransactionRevision.version.asc()).all() if TransactionRevision else []
        _sheet(wb, "Storico trattative", [
            "ID", "ID percorso", "Versione", "ID autore", "Autore", "Motivo", "Data", "Fotografia JSON",
        ], [(
            row.id, row.transaction_id, row.version, row.changed_by_user_id,
            transaction_names.get(row.changed_by_user_id, ""), row.change_note,
            _iso(row.created_at), row.snapshot_json,
        ) for row in transaction_revisions])
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
        protocol_ext = app.extensions.get("aplsai_staff_protocol") or {}
        StaffRule = protocol_ext.get("StaffRule")
        Acknowledgement = protocol_ext.get("StaffRuleAcknowledgement")
        rules = StaffRule.query.order_by(StaffRule.sort_order.asc(), StaffRule.id.asc()).all() if StaffRule else []
        _sheet(wb, "Regole staff", [
            "ID", "Categoria", "Titolo", "Istruzioni", "Priorità", "Destinatari",
            "Obbligatoria", "Attiva", "Ordine", "Versione", "Aggiornata il",
        ], [(
            row.id, row.category, row.title, row.instructions, row.priority, row.audience,
            bool(row.mandatory), bool(row.active), row.sort_order, row.version, _iso(row.updated_at),
        ) for row in rules])
        acknowledgements = Acknowledgement.query.order_by(Acknowledgement.rule_id.asc(), Acknowledgement.user_id.asc()).all() if Acknowledgement else []
        _sheet(wb, "Prese visione staff", [
            "ID", "ID regola", "ID collaboratore", "Versione regola", "Versione attuale", "Valida", "Confermata il",
        ], [(
            row.id, row.rule_id, row.user_id, row.rule_version,
            next((rule.version for rule in rules if rule.id == row.rule_id), ""),
            bool(next((rule.version == row.rule_version for rule in rules if rule.id == row.rule_id), False)),
            _iso(row.acknowledged_at),
        ) for row in acknowledgements])
        tasks_ext = app.extensions.get("aplsai_work_tasks") or {}
        WorkTask = tasks_ext.get("WorkTask")
        WorkTaskUpdate = tasks_ext.get("WorkTaskUpdate")
        tasks = WorkTask.query.order_by(WorkTask.id.asc()).all() if WorkTask else []
        names = {user.id: user.name for user in app_module.User.query.all()}
        _sheet(wb, "Incarichi staff", [
            "ID", "Titolo", "Descrizione", "Categoria", "Priorità", "Stato",
            "ID responsabile", "Responsabile", "Scadenza", "Collegato a", "ID collegamento",
            "Risultato", "Motivo blocco", "Nota approvazione", "Completato il",
            "Approvato il", "ID approvatore", "Creato il", "Aggiornato il",
        ], [(
            row.id, row.title, row.description, row.category, row.priority, row.status,
            row.assigned_to_user_id, names.get(row.assigned_to_user_id, ""), _iso(row.due_at),
            row.link_type, row.link_id, row.completion_note, row.blocked_reason,
            row.approval_note, _iso(row.completed_at), _iso(row.approved_at),
            row.approved_by_user_id, _iso(row.created_at), _iso(row.updated_at),
        ) for row in tasks])
        task_updates = WorkTaskUpdate.query.order_by(WorkTaskUpdate.id.asc()).all() if WorkTaskUpdate else []
        _sheet(wb, "Aggiornamenti incarichi", [
            "ID", "ID incarico", "ID autore", "Autore", "Tipo", "Messaggio", "Data",
        ], [(
            row.id, row.task_id, row.author_user_id, names.get(row.author_user_id, ""),
            row.update_type, row.message, _iso(row.created_at),
        ) for row in task_updates])
        pilot_ext = app.extensions.get("aplsai_pilot_cases") or {}
        PilotCase = pilot_ext.get("PilotCase")
        PilotCheck = pilot_ext.get("PilotCheck")
        pilot_cases = PilotCase.query.order_by(PilotCase.code.asc()).all() if PilotCase else []
        _sheet(wb, "Casi Oro", [
            "ID", "Codice", "Titolo", "Obiettivo", "Stato", "ID cliente",
            "ID opportunità", "ID immobile", "ID scenario", "ID fattibilità",
            "ID responsabile", "Responsabile", "Note", "Creato il", "Aggiornato il",
        ], [(
            row.id, row.code, row.title, row.objective, row.status, row.client_id,
            row.opportunity_id, row.property_id, row.scenario_id, row.feasibility_id,
            row.assigned_to_user_id, names.get(row.assigned_to_user_id, ""), row.notes,
            _iso(row.created_at), _iso(row.updated_at),
        ) for row in pilot_cases])
        pilot_checks = PilotCheck.query.order_by(PilotCheck.code.asc()).all() if PilotCheck else []
        _sheet(wb, "Registro collaudo", [
            "ID", "ID Caso Oro", "Codice", "Prova", "Risultato atteso", "Esito",
            "Evidenza", "Risultato osservato", "ID esecutore", "Esecutore", "Eseguita il",
            "Verifica Admin", "Nota verifica", "ID verificatore", "Verificatore", "Verificata il",
        ], [(
            row.id, row.case_id, row.code, row.title, row.expected_result, row.status,
            row.evidence_ref, row.result_note, row.executed_by_user_id,
            names.get(row.executed_by_user_id, ""), _iso(row.executed_at),
            row.verification_status, row.verification_note, row.verified_by_user_id,
            names.get(row.verified_by_user_id, ""), _iso(row.verified_at),
        ) for row in pilot_checks])
        quote_ext = app.extensions.get("aplsai_quotes") or {}
        QuoteRequest = quote_ext.get("QuoteRequest")
        QuoteEvent = quote_ext.get("QuoteEvent")
        quotes = QuoteRequest.query.order_by(QuoteRequest.code.asc()).all() if QuoteRequest else []
        _sheet(wb, "Richieste preventivo", [
            "ID", "ID Caso Oro", "ID immobile", "Codice", "Categoria", "Stima v1.0",
            "Destinatario tipo", "Destinatario / società", "Email", "Destinatario verificato",
            "Stato invio", "Data invio", "Scadenza", "Data offerta", "Imponibile", "IVA",
            "Importo offerto", "Validità", "Tempi", "Modalità pagamento", "Responsabile offerta",
            "Completezza", "Esito verifica", "Documento richiesto", "Documento / percorso",
            "Note e condizioni", "Creato il", "Aggiornato il",
        ], [(
            row.id, row.pilot_case_id, row.property_id, row.code, row.category, row.estimate_v1,
            row.recipient_type, row.recipient_company, row.recipient_email, row.recipient_verified,
            row.send_status, _iso(row.sent_at), _iso(row.due_at), _iso(row.offer_at), row.offered_net,
            row.offered_vat, row.offered_total, row.validity, row.timing, row.payment_terms,
            row.offer_manager, row.completeness, row.verification_status, row.required_document,
            row.document_ref, row.notes, _iso(row.created_at), _iso(row.updated_at),
        ) for row in quotes])
        quote_events = QuoteEvent.query.order_by(QuoteEvent.id.asc()).all() if QuoteEvent else []
        _sheet(wb, "Storico preventivi", ["ID", "ID preventivo", "ID autore", "Azione", "Nota", "Data"], [
            (row.id, row.quote_id, row.actor_user_id, row.action, row.note, _iso(row.created_at))
            for row in quote_events
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
