# APLSAI HOME — Specifica Matching & Priorità V1

## Stato
Documento interno di progettazione. Non contiene segreti, credenziali o codice proprietario del futuro motore.

## Obiettivo
Il motore APLSAI deve distinguere due concetti diversi:

1. **Compatibilità immobile-cliente**: quanto una specifica casa risponde alle esigenze del cliente.
2. **Priorità operativa cliente**: quanto una pratica è pronta, concreta e veloce da portare a chiusura.

Un cliente prioritario non riceve automaticamente immobili incompatibili. La priorità serve a ordinare il lavoro dello staff tra clienti con opportunità concretamente compatibili.

## 1. Compatibilità immobile-cliente

### A. Requisiti vincolanti
Prima del punteggio vanno controllati i requisiti che possono rendere una proposta non idonea:
- budget massimo, considerando solo la flessibilità dichiarata;
- area geografica e raggio massimo accettato;
- metratura minima;
- eventuali requisiti indispensabili realmente non negoziabili;
- tipologie di immobile accettate;
- modalità di acquisto compatibili.

Se un requisito realmente vincolante fallisce, il motore deve segnalarlo esplicitamente e non mascherarlo con un punteggio alto ottenuto altrove.

### B. Preferenze ponderate
Dopo i vincoli si calcola la qualità della corrispondenza su:
- zona preferita;
- prezzo rispetto al budget ideale;
- metratura e distribuzione;
- camere e bagni;
- caratteristiche desiderate;
- tipologia;
- stato dell'immobile;
- stile e potenziale di trasformazione.

### C. Potenziale APLSAI
Un immobile non perfetto nello stato attuale può diventare altamente compatibile se è trasformabile in modo realistico.
Il motore dovrà quindi distinguere:
- compatibilità attuale;
- compatibilità dopo intervento;
- costo stimato della trasformazione;
- compatibilità finale con il budget complessivo.

Questo è un elemento centrale del concetto di **Casa Possibile**.

## 2. Priorità operativa del cliente

La priorità cliente è separata dal matching della casa.

### Prontezza finanziaria
È un segnale forte di probabilità e velocità di chiusura:

- **Capitale proprio già disponibile / budget pronto** → priorità molto alta.
- **Mutuo già deliberato o disponibilità finanziaria formalmente confermata** → priorità alta.
- **Pre-delibera / verifica bancaria avanzata** → priorità medio-alta.
- **Mutuo da richiedere ma profilo già verificato** → priorità normale.
- **Situazione finanziaria ancora da verificare** → priorità ridotta finché non viene chiarita.

La prontezza finanziaria non può trasformare una casa incompatibile in una proposta valida. Agisce sulla priorità operativa e sulla probabilità di chiusura.

### Altri segnali di priorità
- completezza del profilo;
- tempistica dichiarata;
- disponibilità a più tipologie/zone quando coerente con le esigenze;
- presenza di un'opportunità con matching elevato;
- stato attivo della ricerca;
- risposta alle comunicazioni e avanzamento documentale;
- tempo trascorso senza una proposta valida, per evitare che clienti meno facili vengano dimenticati.

## 3. Output per Area Staff

Per ogni cliente lo staff dovrà vedere almeno:
- stato ricerca;
- livello di prontezza finanziaria;
- priorità operativa;
- motivo sintetico della priorità;
- migliori opportunità compatibili;
- eventuali blocchi da risolvere;
- ultima attività;
- prossima azione consigliata.

Per ogni abbinamento cliente-immobile:
- punteggio compatibilità;
- requisiti soddisfatti;
- requisiti critici/non soddisfatti;
- margine rispetto al budget;
- potenziale di trasformazione;
- spiegazione leggibile del perché APLSAI lo propone.

## 4. Principi di governance del motore

- Il punteggio supporta la decisione; non sostituisce la verifica professionale.
- I criteri devono essere tracciabili e spiegabili allo staff.
- Dati finanziari e personali devono essere minimizzati e protetti.
- Il motore non deve discriminare sulla base di caratteristiche personali non pertinenti alla fattibilità dell'operazione.
- Le attività riservate a professionisti abilitati restano in capo ai relativi professionisti/partner.

## 5. Evoluzione prevista

V1: regole strutturate e spiegabili.

V2: stime più evolute di trasformabilità, costi, tempi e probabilità di chiusura.

V3: componente di intelligenza artificiale che assiste l'analisi, apprende dai risultati operativi e propone opportunità, mantenendo controlli, tracciabilità e supervisione umana.
