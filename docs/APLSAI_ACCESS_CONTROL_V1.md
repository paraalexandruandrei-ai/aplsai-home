# APLSAI HOME — Access Control & Data Minimization V1

## Obiettivo
Definire chi può vedere e modificare cosa dentro APLSAI HOME prima della beta con clienti reali.

Principio: **collaborazione aperta, proprietà centrale**. Partner e professionisti accedono solo alle informazioni necessarie per il loro incarico; dati strategici, relazione cliente e governance restano sotto controllo APLSAI.

## Ruoli previsti

### 1. Admin APLSAI
Accesso completo alle funzioni operative necessarie:
- clienti;
- immobili;
- matching;
- trattative/proposte;
- documenti;
- referral;
- gestione utenti staff;
- configurazioni e audit.

L'admin non deve usare credenziali condivise tra più persone.

### 2. Operatore APLSAI
Accesso operativo ma non amministrativo:
- vede clienti assegnati o autorizzati;
- inserisce/aggiorna immobili;
- esegue matching;
- registra avanzamenti e proposte;
- condivide documenti con i clienti;
- non può modificare ruoli, segreti, configurazioni di sicurezza o utenti admin.

### 3. Professionista / Partner
Accesso minimo e limitato all'incarico:
- vede solo pratica/immobile assegnato;
- vede i dati cliente strettamente necessari;
- non accede all'intero elenco clienti;
- non vede dati strategici APLSAI non necessari;
- non può esportare database, cambiare ruoli o vedere altre pratiche.

Esempi: tecnico, progettista, impresa, broker, consulente, agenzia partner.

### 4. Cliente
Accesso esclusivamente ai propri dati:
- proprio profilo;
- stato ricerca;
- aggiornamenti;
- proposte ricevute;
- documenti condivisi con lui;
- referral propri;
- preferenze e stato ricerca.

Un cliente non deve mai poter leggere o modificare dati di altri clienti cambiando un ID nella richiesta.

## Dati finanziari: minimizzazione
Per il motore di priorità APLSAI non è necessario salvare saldo bancario, estratti conto o patrimonio dettagliato nel profilo ordinario.

Usare uno stato sintetico di prontezza finanziaria, per esempio:
- `capitale_verificato` — fondi disponibili verificati tramite processo autorizzato;
- `capitale_dichiarato` — cliente dichiara budget pronto ma verifica non completata;
- `mutuo_deliberato` — finanziamento deliberato;
- `pre_delibera` — verifica bancaria avanzata/pre-delibera;
- `mutuo_da_richiedere` — percorso finanziario ancora da completare;
- `da_verificare` — stato non ancora chiarito.

Lo stato di prontezza aumenta la priorità operativa ma **non modifica artificialmente la compatibilità di un immobile**.

## Regole documenti
- In V1 il database salva metadati e link, non file sensibili nel repository GitHub.
- I link devono essere HTTPS quando possibile.
- Nessuna password o token deve essere inserita nel titolo, URL o note.
- In produzione i documenti sensibili dovranno vivere in storage privato con accesso autenticato e URL temporanei, non in link pubblici permanenti.
- Ogni documento deve essere associato a uno specifico cliente/pratica.

## Audit minimo prima della beta
Registrare almeno gli eventi sensibili:
- login staff riuscito/fallito;
- creazione/modifica immobile;
- condivisione documento;
- creazione proposta;
- cambio stato cliente;
- modifica ruolo/permessi;
- accessi amministrativi rilevanti.

L'audit non deve registrare password o segreti.

## Principio least privilege
Ogni endpoint server deve controllare il permesso. Nascondere un pulsante nel frontend non è una protezione sufficiente.

Ordine di verifica:
1. sessione valida;
2. ruolo valido;
3. permesso per l'azione;
4. autorizzazione sulla specifica risorsa/pratica;
5. validazione input;
6. registrazione audit quando necessario.

## Gate prima di beta reale
- repository GitHub privato;
- credenziali admin individuali e forti;
- nessuna credenziale di fallback nel codice;
- PostgreSQL di produzione verificato e backup definiti;
- ruoli Admin/Operatore/Partner implementati lato server;
- test di accesso incrociato cliente-cliente e partner-partner;
- storage documenti privato;
- informativa privacy e basi giuridiche definite con professionista competente;
- procedura cancellazione/esportazione dati;
- audit log minimo attivo.
