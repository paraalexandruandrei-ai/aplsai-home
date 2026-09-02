# APLSAI HOME — Privacy Data Map V1

## Obiettivo
Definire quali dati APLSAI raccoglie, perché, dove vengono usati e per quanto tempo devono restare disponibili. È una base tecnica/organizzativa da validare con il professionista privacy prima della beta reale.

## Principio di minimizzazione
APLSAI raccoglie solo i dati necessari al percorso casa e alla gestione della pratica. Evitare dati finanziari dettagliati, documenti non necessari e note libere contenenti informazioni eccedenti.

## Categorie dati

### 1. Dati account
- nome;
- email;
- telefono/WhatsApp;
- password solo come hash;
- data creazione account;
- stato account/sessione.

Finalità tecnica: autenticazione, comunicazioni operative, gestione account.

### 2. Profilo ricerca casa
- zona e raggio;
- budget ideale/massimo;
- metratura;
- camere/bagni;
- tipologie preferite;
- requisiti;
- tempistica;
- stile/strategia.

Finalità: ricerca, matching, proposta e coordinamento del percorso.

### 3. Prontezza finanziaria sintetica
Solo stato operativo:
- da_verificare;
- mutuo_da_richiedere;
- pre_delibera;
- mutuo_deliberato;
- capitale_dichiarato;
- capitale_verificato.

Non conservare nel profilo ordinario saldo bancario, estratti conto o patrimonio dettagliato.

### 4. Dati operativi pratica
- fase;
- prossima azione;
- scadenza;
- responsabile;
- stato/blocco;
- cronologia aggiornamenti;
- proposte e trattative.

Finalità: gestione del servizio e tracciabilità operativa.

### 5. Immobili
- riferimenti;
- zona;
- prezzo;
- caratteristiche;
- fonte;
- stato disponibilità/verifica;
- collegamenti a pratiche.

### 6. Documenti
In produzione i file sensibili devono essere in storage privato. Nel database conservare solo metadati necessari: cliente/pratica, titolo, tipo, stato, identificativo storage, data e autorizzazioni.

### 7. Audit e sicurezza
- utente/autore;
- evento;
- oggetto;
- timestamp;
- esito;
- informazioni tecniche minime necessarie alla sicurezza.

Mai registrare password, token, segreti o contenuto integrale di documenti nei log.

## Visibilità per ruolo
Cliente: propri dati e documenti condivisi.
Operatore: dati necessari alle pratiche autorizzate.
Partner/professionista: solo pratica assegnata e dati strettamente necessari all'incarico.
Admin: accesso amministrativo controllato e tracciato.

## Conservazione — impostazione tecnica iniziale
I tempi definitivi devono essere validati in base alle basi giuridiche e agli obblighi applicabili. L'applicazione deve comunque supportare:
- cancellazione/anonimizzazione di account non più necessari;
- conservazione separata di ciò che deve restare per obblighi legali;
- scadenza dei documenti temporanei;
- cancellazione di sessioni e token non più validi;
- retention configurabile degli audit log.

## Diritti e operazioni da supportare
Prima della beta reale predisporre un processo per:
- accesso ai propri dati;
- rettifica;
- cancellazione quando applicabile;
- limitazione/opposizione quando applicabile;
- esportazione dei dati in formato leggibile;
- revoca dei consensi ove il trattamento dipenda dal consenso.

## Sicurezza minima associata
- HTTPS;
- password hash robuste;
- sessioni protette;
- controllo accessi lato server;
- backup cifrati/protetti;
- storage privato documenti;
- audit;
- segreti fuori dal repository;
- test periodici di autorizzazione.

## Nota
Questo documento è una mappa tecnica/organizzativa, non sostituisce l'informativa privacy, il registro dei trattamenti o la valutazione professionale degli adempimenti GDPR applicabili ad APLSAI.
