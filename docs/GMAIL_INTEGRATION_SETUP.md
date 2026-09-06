# Collegamento Gmail ufficiale

Casella prevista: `aplsaihome.srl@gmail.com`.

## Funzioni incluse

- autorizzazione Google OAuth 2.0 senza password nel sito;
- token di rinnovo cifrato nel database;
- invio reale solo dopo verifica del destinatario e approvazione Admin;
- registrazione dell'identificativo conversazione Gmail;
- acquisizione delle risposte nella richiesta immobile collegata;
- estrazione prudenziale dei dati, sempre soggetta a conferma umana;
- registro delle operazioni di collegamento, invio e sincronizzazione.

## Variabili del servizio

- `APLSAI_OFFICIAL_EMAIL=aplsaihome.srl@gmail.com`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI=https://aplsai-home.onrender.com/api/admin/gmail/callback`
- `GMAIL_TOKEN_ENCRYPTION_KEY` (chiave Fernet generata in modo casuale)

Le credenziali Google e la chiave di cifratura devono restare esclusivamente tra i segreti del servizio Render. Non inserirle nel repository, nei documenti o nelle chat.

## Configurazione Google Cloud

1. Creare o selezionare un progetto controllato da APLSAI HOME.
2. Abilitare Gmail API.
3. Configurare la schermata consenso OAuth per uso esterno in modalità test iniziale.
4. Inserire `aplsaihome.srl@gmail.com` tra gli utenti di prova.
5. Creare un client OAuth di tipo Applicazione web.
6. Registrare esattamente l'URI di reindirizzamento riportato sopra.
7. Copiare Client ID e Client Secret nei segreti Render.
8. Dall'area Admin, sezione Contatti immobili, premere `Collega tramite Google` e autorizzare la casella ufficiale.

## Controllo operativo

1. Creare una richiesta da un'opportunità con destinatario verificato.
2. Inviarla all'approvazione e approvarla come Admin.
3. Premere `Invia ora da aplsaihome.srl@gmail.com`.
4. Rispondere alla mail da un indirizzo di prova.
5. Premere `Controlla nuove risposte`.
6. Verificare che la risposta compaia nella richiesta e confermare manualmente gli eventuali dati riconosciuti.

