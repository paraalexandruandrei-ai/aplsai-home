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
            ("Riservatezza", "Contiene dati personali: conservare in posizione protetta."),
        ])

        profiles = {p.user_id: p for p in app_module.ClientProfile.query.all()}
        clients = app_module.User.query.filter_by(role="client").order_by(app_module.User.id.asc()).all()
        _sheet(wb, "Clienti", [
            "ID cliente", "Nome", "Email", "Telefono", "Attivo", "Creato il",
            "Stato", "Strategia", "Ultimo contatto", "Ultima proposta", "N. proposte",
        ], [(
            u.id, u.name, u.email, u.phone, bool(getattr(u, "active", True)), _iso(u.created_at),
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
            "ID cliente", "Zona principale", "Distanza km", "Budget ideale", "Budget massimo",
            "Flessibilità %", "Metratura", "Camere", "Bagni", "Indispensabili", "Tempistica",
            "Tipologie casa", "Stato acquisto", "Stile", "Profilo JSON originale",
        ], profile_rows)

        _sheet(wb, "Immobili", ["ID immobile", "Riferimento", "Zona", "Prezzo", "Mq", "Camere", "Bagni", "Stato", "Fonte", "Creato il"], [
            (p.id, p.ref, p.zone, p.price, p.sqm, p.beds, p.baths, p.state, p.source, _iso(p.created_at))
            for p in app_module.Property.query.order_by(app_module.Property.id.asc()).all()
        ])

        operations_ext = app.extensions.get("aplsai_operations") or {}
        Operation = operations_ext.get("ClientOperation")
        operations = Operation.query.order_by(Operation.client_id.asc()).all() if Operation else []
        _sheet(wb, "Pratiche", [
            "ID cliente", "Fase", "Stato finanziario", "Priorità", "Verificato il", "Prossima azione",
            "Scadenza", "Responsabile", "Motivo blocco", "Aggiornato il",
        ], [(
            op.client_id, op.phase, op.financial_state, op.to_dict().get("priority", ""),
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
