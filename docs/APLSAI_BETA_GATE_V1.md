# APLSAI HOME — Beta Readiness Gate V1

## Obiettivo
Definire in modo verificabile quando APLSAI HOME può passare da prototipo pubblico a beta controllata con clienti reali.

## Gate A — Infrastruttura
- servizio web stabile e raggiungibile in HTTPS;
- PostgreSQL come unica fonte dati operativa;
- connessione database verificata con SSL/TLS;
- backup e procedura di ripristino definiti;
- segreti solo in variabili d'ambiente;
- repository GitHub privato prima di introdurre logica proprietaria.

## Gate B — Identità e accessi
- password clienti con requisiti minimi lato server;
- sessioni sicure, HttpOnly, Secure, SameSite;
- scadenza sessioni;
- rate limiting login;
- nessuna credenziale di fallback nel codice;
- credenziali individuali per Admin/Operatori;
- ruoli Admin, Operatore, Partner e Cliente controllati lato server;
- autorizzazione per singola pratica/risorsa, non solo per ruolo.

## Gate C — Dati cliente
- nessun profilo reale salvato in localStorage/sessionStorage;
- validazione server di email, telefono, budget, immobili e documenti;
- minimizzazione dei dati finanziari;
- stato di prontezza finanziaria sintetico;
- procedura di cancellazione/esportazione dati;
- informativa privacy e basi giuridiche validate prima della beta pubblica.

## Gate D — Documenti
- niente file sensibili nel repository;
- niente link pubblici permanenti per documenti riservati;
- storage privato;
- URL temporanei o download autenticato;
- ogni documento associato a un cliente/pratica;
- audit di chi condivide o consulta i documenti sensibili.

## Gate E — Audit minimo
Registrare almeno:
- login staff riusciti;
- login staff bloccati/falliti in forma non sensibile;
- creazione/modifica immobile;
- creazione proposta;
- condivisione documento;
- cambio stato cliente;
- cambio prontezza finanziaria;
- modifica ruolo/permesso;
- operazioni amministrative rilevanti.

Campi minimi dell'audit:
- timestamp UTC;
- user/staff ID;
- ruolo;
- azione;
- tipo risorsa;
- ID risorsa;
- esito;
- indirizzo IP ridotto/normalizzato quando necessario;
- nessuna password, token, segreto o contenuto documentale.

## Gate F — Test sicurezza
Prima di accettare clienti reali devono passare almeno questi test:
1. Cliente A non può leggere Cliente B modificando un ID.
2. Cliente non può chiamare endpoint Staff.
3. Operatore non può eseguire azioni Admin.
4. Partner non può vedere clienti/pratiche non assegnate.
5. Sessione scaduta non dà accesso ai dati.
6. Logout invalida la sessione corrente.
7. Troppi login errati attivano il blocco temporaneo.
8. Input HTML/script non viene eseguito nelle dashboard.
9. Documento privato non è accessibile senza autorizzazione.
10. Accesso diretto a endpoint protetti senza sessione restituisce 401/403.

## Gate G — Operatività APLSAI
- Area Cliente mostra dati server reali;
- Area Staff mostra dati server reali;
- creazione immobile funziona end-to-end;
- proposta cliente-immobile viene registrata;
- stato cliente viene aggiornato;
- prontezza finanziaria viene registrata come stato sintetico;
- matching e priorità restano concetti distinti;
- ogni proposta ha motivazione leggibile per lo staff.

## Stato attuale sintetico
### Già impostato
- HTTPS Render;
- SECRET_KEY obbligatoria in produzione;
- cookie sicuri;
- sessione con durata limitata;
- rate limiting login;
- header HTTP di sicurezza;
- validazione input base;
- rimozione credenziali admin predefinite;
- backend API separato da browser storage;
- specifica matching/priorità;
- specifica access control e minimizzazione.

### Ancora da chiudere
- repository privato;
- verifica PostgreSQL via SSL/TLS e backup;
- ruoli granulari lato server;
- audit log persistente;
- prontezza finanziaria come campo operativo strutturato;
- storage documenti privato;
- test automatici/integrazione dei permessi;
- privacy/GDPR operativa;
- dominio e configurazione produzione definitiva.

## Regola di rilascio
La beta con clienti reali non parte finché i Gate A–F non sono sostanzialmente verdi. Le funzioni commerciali possono essere sviluppate in parallelo, ma non devono abbassare i requisiti di sicurezza.
