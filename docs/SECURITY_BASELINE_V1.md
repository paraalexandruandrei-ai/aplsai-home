# APLSAI HOME — Security Baseline V1

## Obiettivo
Definire il livello minimo di sicurezza richiesto prima di utilizzare APLSAI HOME con clienti reali.

## Controlli già presenti
- password memorizzate come hash;
- sessione server con cookie HttpOnly;
- cookie Secure in produzione;
- SameSite=Lax;
- scadenza sessione;
- controllo ruoli client/staff sulle API riservate;
- validazione input principali;
- limite dimensione richieste;
- limitazione tentativi login;
- header di sicurezza HTTP;
- assenza di credenziali admin predefinite nel codice;
- segreti operativi gestiti tramite variabili ambiente Render.

## Controlli obbligatori prima della beta reale

### 1. Repository
- [ ] Rendere `aplsai-home` PRIVATO prima di inserire logica proprietaria del motore APLSAI.
- [ ] Verificare che nessun commit storico contenga password, URL completi con credenziali, token o chiavi API.
- [ ] Proteggere il branch `main` quando inizierà a lavorare più di una persona.

### 2. Admin / Staff
- [ ] Configurare `ADMIN_EMAIL` tramite Render Environment.
- [ ] Configurare `ADMIN_PASSWORD` con password lunga e unica tramite Render Environment.
- [ ] Eliminare o sostituire l'admin di test eventualmente già creato nel database.
- [ ] Introdurre successivamente autenticazione a due fattori per lo staff.
- [ ] Registrare le principali azioni staff in un audit log.

### 3. Clienti
- [ ] Aggiungere recupero password sicuro tramite token a scadenza.
- [ ] Verifica email prima delle funzioni più sensibili.
- [ ] Logout da tutte le sessioni in caso di cambio password.
- [ ] Gestione cancellazione account / richiesta dati.

### 4. Database
- [ ] Verificare connessione PostgreSQL end-to-end.
- [ ] Forzare SSL/TLS per le connessioni esterne.
- [ ] Nessuna credenziale database nel repository.
- [ ] Backup verificato e procedura di ripristino documentata.
- [ ] Passare da database gratuito/temporaneo a piano di produzione prima del lancio commerciale.

### 5. Dati personali / GDPR
- [ ] Definire quali dati sono realmente necessari per la ricerca casa.
- [ ] Evitare di raccogliere dati finanziari non necessari.
- [ ] Distinguere "modalità finanziaria" da documentazione bancaria sensibile.
- [ ] Informativa privacy disponibile prima della registrazione.
- [ ] Base giuridica e consensi separati ove necessari.
- [ ] Tempi di conservazione definiti.
- [ ] Procedura per accesso, rettifica, portabilità e cancellazione.
- [ ] Registro fornitori/sub-responsabili (hosting, email, analytics, AI, storage documenti).

### 6. Documenti
- [ ] Non usare URL pubblici non protetti per documenti riservati.
- [ ] Storage privato con link firmati/scadenza.
- [ ] Controllo autorizzazione per ogni download.
- [ ] Antivirus/scansione file quando verrà abilitato upload reale.
- [ ] Limiti tipo file e dimensione.

### 7. Frontend
- [x] Nessun risultato di ricerca per `localStorage` / `sessionStorage` nel repository corrente.
- [ ] Verifica manuale che autenticazione e dati cliente arrivino sempre dal backend.
- [ ] Eliminare eventuali credenziali/test UI residue.
- [ ] Messaggi errore senza dettagli interni del server.

### 8. Produzione
- [ ] Dominio definitivo HTTPS.
- [ ] Monitoraggio uptime/errori.
- [ ] Alert per errori 5xx e anomalie login.
- [ ] Log senza password, token o dati personali superflui.
- [ ] Piano incident response minimo: chi blocca il servizio, chi ruota le credenziali, chi informa i soggetti coinvolti.

## Gate di rilascio Beta
La beta con utenti esterni può iniziare solo quando sono verdi almeno:

1. repository privato;
2. credenziali staff definitive;
3. PostgreSQL verificato e backup disponibile;
4. privacy/informativa minima pubblicata;
5. autenticazione client/staff testata;
6. documenti sensibili non esposti pubblicamente;
7. test autorizzazioni: client non può accedere a staff e viceversa;
8. test completo PC + mobile senza errori critici.

## Nota
Questa baseline riduce il rischio tecnico, ma non sostituisce una revisione specialistica di cybersecurity e GDPR prima di una crescita significativa del servizio.
