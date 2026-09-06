import base64
import json
import os
import secrets
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken
from flask import jsonify, redirect, request, session

from . import db
from .rbac import has_permission


GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
)
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_URL = "https://gmail.googleapis.com/gmail/v1/users/me"


def init_gmail_integration(app, app_module):
    if app.extensions.get("aplsai_gmail"):
        return

    outreach = app.extensions.get("aplsai_outreach") or {}
    OpportunityInquiry = outreach.get("OpportunityInquiry")
    InquiryReply = outreach.get("InquiryReply")
    inquiry_dict = outreach.get("inquiry_dict")
    if not OpportunityInquiry or not InquiryReply or not inquiry_dict:
        raise RuntimeError("Il modulo contatti deve essere inizializzato prima di Gmail.")

    class GmailConnection(db.Model):
        __tablename__ = "gmail_connection"
        id = db.Column(db.Integer, primary_key=True)
        email = db.Column(db.String(254), nullable=False, unique=True)
        encrypted_refresh_token = db.Column(db.Text, nullable=False)
        connected_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        last_sync_at = db.Column(db.DateTime(timezone=True))

    with app.app_context():
        db.create_all()

    def staff_user(permission):
        uid = session.get("uid")
        actor = db.session.get(app_module.User, uid) if uid else None
        if not actor:
            return None, (jsonify(error="Non autenticato."), 401)
        if getattr(actor, "active", True) is False:
            session.clear()
            return None, (jsonify(error="Account disattivato."), 401)
        if not has_permission(actor.role, permission):
            return None, (jsonify(error="Permesso insufficiente."), 403)
        return actor, None

    def audit(actor, action, object_id="gmail", detail=""):
        fn = (app.extensions.get("aplsai_operations") or {}).get("audit")
        if fn:
            fn(actor, action, "gmail_connection", object_id, detail)

    def official_email():
        return app_module.clean_email(os.environ.get("APLSAI_OFFICIAL_EMAIL") or "aplsaihome.srl@gmail.com")

    def oauth_configured():
        return all(
            os.environ.get(key)
            for key in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GMAIL_TOKEN_ENCRYPTION_KEY")
        )

    def redirect_uri():
        configured = (os.environ.get("GOOGLE_OAUTH_REDIRECT_URI") or "").strip()
        if configured:
            return configured
        return request.url_root.rstrip("/") + "/api/admin/gmail/callback"

    def fernet():
        raw = (os.environ.get("GMAIL_TOKEN_ENCRYPTION_KEY") or "").encode("ascii")
        if not raw:
            raise RuntimeError("Chiave di cifratura Gmail non configurata.")
        try:
            return Fernet(raw)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Chiave di cifratura Gmail non valida.") from exc

    def encrypt_token(token):
        return fernet().encrypt(token.encode("utf-8")).decode("ascii")

    def decrypt_token(value):
        try:
            return fernet().decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Collegamento Gmail non leggibile: riconnettere l’account.") from exc

    def http_json(url, method="GET", data=None, headers=None, timeout=25):
        payload = None if data is None else json.dumps(data).encode("utf-8")
        request_headers = {"Accept": "application/json", **(headers or {})}
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
        req = Request(url, data=payload, headers=request_headers, method=method)
        try:
            with urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8"))
                message = detail.get("error_description") or detail.get("error", {}).get("message") or str(detail)
            except Exception:
                message = str(exc)
            raise RuntimeError(f"Google Gmail: {message}") from exc
        except URLError as exc:
            raise RuntimeError("Google Gmail non raggiungibile. Riprovare.") from exc

    def form_post(url, values):
        req = Request(
            url,
            data=urlencode(values).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=25) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8"))
                message = detail.get("error_description") or detail.get("error") or str(detail)
            except Exception:
                message = str(exc)
            raise RuntimeError(f"Autorizzazione Google: {message}") from exc
        except URLError as exc:
            raise RuntimeError("Google non raggiungibile. Riprovare.") from exc

    def connection():
        return GmailConnection.query.filter_by(email=official_email()).first()

    def access_token():
        row = connection()
        if not row:
            raise RuntimeError("La casella Gmail ufficiale non è ancora collegata al sito.")
        result = form_post(GOOGLE_TOKEN_URL, {
            "client_id": os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""),
            "client_secret": os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""),
            "refresh_token": decrypt_token(row.encrypted_refresh_token),
            "grant_type": "refresh_token",
        })
        token = result.get("access_token")
        if not token:
            raise RuntimeError("Google non ha restituito un accesso valido. Riconnettere Gmail.")
        return token

    def gmail_request(path, method="GET", data=None, params=None):
        url = f"{GMAIL_API_URL}/{path.lstrip('/')}"
        if params:
            url += "?" + urlencode(params)
        return http_json(url, method=method, data=data, headers={"Authorization": f"Bearer {access_token()}"})

    def send_plain_email(recipient, subject, body):
        recipient = app_module.clean_email(recipient)
        if not app_module.valid_email(recipient):
            raise RuntimeError("Indirizzo email del cliente non valido.")
        message = EmailMessage()
        message["From"] = f"APLSAI HOME <{official_email()}>"
        message["To"] = recipient
        message["Reply-To"] = official_email()
        message["Subject"] = app_module.clean_text(subject, 200)
        message.set_content(app_module.clean_text(body, 12000))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        return gmail_request("messages/send", method="POST", data={"raw": raw})

    def send_inquiry_now(inquiry, actor):
        if not inquiry.recipient_verified or not app_module.valid_email(inquiry.recipient_email):
            raise RuntimeError("Destinatario non verificato.")
        message = EmailMessage()
        message["From"] = f"APLSAI HOME <{official_email()}>"
        message["To"] = inquiry.recipient_email
        message["Reply-To"] = official_email()
        message["Subject"] = inquiry.subject
        message.set_content(inquiry.body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
        sent = gmail_request("messages/send", method="POST", data={"raw": raw})
        inquiry.status = "Inviata"
        inquiry.external_thread_id = app_module.clean_text(sent.get("threadId"), 255)
        inquiry.sent_at = datetime.now(timezone.utc)
        inquiry.updated_at = inquiry.sent_at
        audit(actor, "gmail_send", inquiry.id, f"recipient={inquiry.recipient_email}; message={sent.get('id', '')}")
        db.session.commit()
        return sent

    def status_payload():
        row = connection()
        return {
            "official_email": official_email(),
            "configured": oauth_configured(),
            "connected": bool(row),
            "connected_email": row.email if row else "",
            "connected_at": row.connected_at.isoformat() if row and row.connected_at else None,
            "last_sync_at": row.last_sync_at.isoformat() if row and row.last_sync_at else None,
        }

    def decode_header_value(value):
        try:
            return str(make_header(decode_header(value or "")))
        except Exception:
            return value or ""

    def message_headers(payload):
        return {
            item.get("name", "").lower(): decode_header_value(item.get("value", ""))
            for item in (payload or {}).get("headers", [])
        }

    def message_text(payload):
        def walk(part):
            mime = part.get("mimeType", "")
            body = part.get("body") or {}
            data = body.get("data")
            if mime == "text/plain" and data:
                try:
                    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
                except Exception:
                    return ""
            for child in part.get("parts") or []:
                found = walk(child)
                if found:
                    return found
            if data and mime.startswith("text/"):
                try:
                    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
                except Exception:
                    return ""
            return ""
        return app_module.clean_text(walk(payload), 12000)

    @app.get("/api/admin/gmail/status")
    def gmail_status():
        actor, denied = staff_user("outreach_read")
        if denied:
            return denied
        return jsonify(gmail=status_payload())

    @app.get("/api/admin/gmail/connect")
    def gmail_connect():
        actor, denied = staff_user("outreach_approve")
        if denied:
            return denied
        if not oauth_configured():
            return jsonify(error="Configurazione Google incompleta: inserire Client ID e Client Secret nel servizio."), 503
        state = secrets.token_urlsafe(32)
        session["gmail_oauth_state"] = state
        query = urlencode({
            "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
            "redirect_uri": redirect_uri(),
            "response_type": "code",
            "scope": " ".join(GMAIL_SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "login_hint": official_email(),
            "state": state,
        })
        audit(actor, "gmail_connect_start")
        db.session.commit()
        return redirect(f"{GOOGLE_AUTHORIZE_URL}?{query}")

    @app.get("/api/admin/gmail/callback")
    def gmail_callback():
        actor, denied = staff_user("outreach_approve")
        if denied:
            return denied
        expected_state = session.pop("gmail_oauth_state", None)
        if not expected_state or not secrets.compare_digest(expected_state, request.args.get("state", "")):
            return jsonify(error="Autorizzazione Google scaduta o non valida."), 400
        if request.args.get("error"):
            return redirect("/?gmail=denied")
        code = request.args.get("code", "")
        if not code:
            return jsonify(error="Google non ha restituito il codice di autorizzazione."), 400
        try:
            tokens = form_post(GOOGLE_TOKEN_URL, {
                "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
                "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri(),
            })
            token = tokens.get("access_token")
            refresh = tokens.get("refresh_token")
            if not token:
                raise RuntimeError("Google non ha restituito un accesso valido.")
            profile = http_json(
                f"{GMAIL_API_URL}/profile",
                headers={"Authorization": f"Bearer {token}"},
            )
            email = app_module.clean_email(profile.get("emailAddress"))
            if email != official_email():
                return jsonify(error=f"Account non autorizzato. Collegare esclusivamente {official_email()}."), 409
            row = connection()
            if not row:
                if not refresh:
                    raise RuntimeError("Google non ha restituito il permesso permanente. Ripetere il collegamento.")
                row = GmailConnection(email=email, encrypted_refresh_token=encrypt_token(refresh))
                db.session.add(row)
            elif refresh:
                row.encrypted_refresh_token = encrypt_token(refresh)
            row.updated_at = datetime.now(timezone.utc)
            audit(actor, "gmail_connect_complete", email, "OAuth Google completato")
            db.session.commit()
            return redirect("/?gmail=connected")
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 502

    @app.post("/api/admin/gmail/disconnect")
    def gmail_disconnect():
        actor, denied = staff_user("outreach_approve")
        if denied:
            return denied
        row = connection()
        if row:
            db.session.delete(row)
            audit(actor, "gmail_disconnect", official_email())
            db.session.commit()
        return jsonify(gmail=status_payload())

    @app.post("/api/staff/inquiries/<int:inquiry_id>/send-email")
    def gmail_send_inquiry(inquiry_id):
        actor, denied = staff_user("outreach_approve")
        if denied:
            return denied
        inquiry = db.session.get(OpportunityInquiry, inquiry_id)
        if not inquiry:
            return jsonify(error="Richiesta non trovata."), 404
        if inquiry.status != "Approvata":
            return jsonify(error="Il messaggio deve essere approvato prima dell’invio."), 409
        if not inquiry.recipient_verified or not app_module.valid_email(inquiry.recipient_email):
            return jsonify(error="Destinatario non verificato."), 409
        try:
            sent = send_inquiry_now(inquiry, actor)
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 502
        return jsonify(inquiry=inquiry_dict(inquiry, include_replies=True), gmail_message_id=sent.get("id", ""))

    @app.post("/api/admin/gmail/sync")
    def gmail_sync():
        actor, denied = staff_user("outreach_approve")
        if denied:
            return denied
        if not connection():
            return jsonify(error="Collegare prima la casella Gmail ufficiale."), 409
        try:
            listing = gmail_request("messages", params={
                "q": f"newer_than:90d -from:{official_email()}",
                "maxResults": 100,
            })
            inquiries = OpportunityInquiry.query.filter(
                OpportunityInquiry.external_thread_id != ""
            ).all()
            by_thread = {row.external_thread_id: row for row in inquiries}
            imported = 0
            ignored = 0
            for summary in listing.get("messages") or []:
                source_id = app_module.clean_text(summary.get("id"), 255)
                if not source_id or InquiryReply.query.filter_by(source_message_id=source_id).first():
                    ignored += 1
                    continue
                message = gmail_request(f"messages/{source_id}", params={"format": "full"})
                inquiry = by_thread.get(message.get("threadId", ""))
                if not inquiry:
                    ignored += 1
                    continue
                headers = message_headers(message.get("payload") or {})
                sender = app_module.clean_email(parseaddr(headers.get("from", ""))[1])
                body = message_text(message.get("payload") or {})
                if not body or sender == official_email():
                    ignored += 1
                    continue
                reply = InquiryReply(
                    inquiry_id=inquiry.id,
                    sender_email=sender,
                    body=body,
                    extracted_json=json.dumps(outreach["extract_reply"](body), ensure_ascii=False),
                    source_message_id=source_id,
                )
                db.session.add(reply)
                inquiry.status = "Risposta ricevuta"
                inquiry.updated_at = datetime.now(timezone.utc)
                imported += 1
            row = connection()
            row.last_sync_at = datetime.now(timezone.utc)
            audit(actor, "gmail_sync", official_email(), f"imported={imported}; ignored={ignored}")
            db.session.commit()
            return jsonify(imported=imported, ignored=ignored, gmail=status_payload())
        except RuntimeError as exc:
            db.session.rollback()
            return jsonify(error=str(exc)), 502

    @app.post("/api/admin/clients/<int:client_id>/send-welcome-email")
    def gmail_send_client_welcome(client_id):
        actor, denied = staff_user("outreach_approve")
        if denied:
            return denied
        client = db.session.get(app_module.User, client_id)
        profile = app_module.ClientProfile.query.filter_by(user_id=client_id).first() if client else None
        if not client or client.role != "client" or not profile:
            return jsonify(error="Cliente non trovato."), 404
        try:
            sent = send_plain_email(
                client.email,
                "APLSAI HOME – richiesta ricevuta e presa in carico",
                app_module.client_welcome_message(client.name),
            )
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 502
        db.session.add(app_module.Update(client_id=client.id, message="Conferma di presa in carico inviata via email."))
        audit(actor, "gmail_client_welcome", client.id, f"recipient={client.email}; message={sent.get('id', '')}")
        db.session.commit()
        return jsonify(sent=True, email=client.email)

    app.extensions["aplsai_gmail"] = {
        "GmailConnection": GmailConnection,
        "status_payload": status_payload,
        "encrypt_token": encrypt_token,
        "decrypt_token": decrypt_token,
        "send_plain_email": send_plain_email,
        "send_inquiry_now": send_inquiry_now,
    }
