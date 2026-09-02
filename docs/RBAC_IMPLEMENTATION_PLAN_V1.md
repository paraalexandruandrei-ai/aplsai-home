# APLSAI HOME — Ruoli e Permessi Server V1

## Obiettivo
Passare dall'attuale ruolo unico `staff` a un modello a privilegi minimi senza rompere la beta esistente.

## Ruoli
### Admin
Controllo completo operativo e di configurazione. Gestisce utenti interni, ruoli, audit, configurazioni e visibilità completa autorizzata.

### Operatore
Gestisce clienti, pratiche, immobili, proposte, prossime azioni e documenti operativi pertinenti. Non gestisce segreti, configurazioni critiche, ruoli Admin o audit di sicurezza completo.

### Partner
Accesso esclusivamente alle pratiche assegnate e alle informazioni/documenti necessari all'incarico. Nessuna lista clienti globale, nessun database strategico completo, nessun accesso al motore proprietario o alle configurazioni.

### Cliente
Accesso esclusivamente al proprio profilo, aggiornamenti e documenti autorizzati.

## Strategia di migrazione sicura
L'attuale valore `staff` viene temporaneamente interpretato come `admin` per mantenere compatibilità. Non si cambia immediatamente la colonna `User.role` in produzione finché le migrazioni versionate non sono operative.

Si introduce una funzione di autorizzazione centrale:
- `require_permission(permission)`
- risolve il ruolo effettivo;
- controlla una matrice di permessi;
- per Partner richiede anche verifica dell'assegnazione alla pratica.

## Permessi V1
- dashboard_full: Admin, Operatore
- client_read_all: Admin, Operatore
- client_update_operation: Admin, Operatore
- property_create: Admin, Operatore
- matching_run: Admin, Operatore
- proposal_create: Admin, Operatore
- document_share: Admin, Operatore
- audit_read: Admin
- staff_manage: Admin
- assigned_case_read: Partner
- assigned_document_read: Partner
- own_profile_read: Cliente

## Assegnazioni Partner
Tabella futura `case_assignment`:
- id
- partner_user_id
- client_id/practice_id
- assignment_type
- status
- created_by
- created_at
- expires_at opzionale

Ogni endpoint Partner deve verificare l'assegnazione server-side. Nascondere un pulsante nel browser non costituisce autorizzazione.

## Principio fail-closed
Se ruolo, permesso o assegnazione non sono riconosciuti, l'accesso viene negato. Nessun fallback permissivo.

## Audit
Registrare almeno:
- creazione/revoca assegnazione partner;
- modifica ruolo;
- accesso a documenti sensibili quando appropriato;
- modifiche operative importanti.

## Gate prima dell'attivazione Partner
1. repository privato;
2. migrazioni database versionate;
3. account individuali, niente credenziali condivise;
4. matrice permessi testata;
5. `case_assignment` attiva;
6. archivio documenti privato;
7. test incrociati Partner A / pratica B.

## Test obbligatori
- Cliente non accede a `/api/staff/*`;
- Operatore non legge audit completo se riservato Admin;
- Partner non vede elenco clienti globale;
- Partner assegnato alla pratica A può vedere solo dati autorizzati della A;
- Partner non assegnato riceve 403;
- ruolo sconosciuto riceve 403;
- sessione scaduta riceve 401.
