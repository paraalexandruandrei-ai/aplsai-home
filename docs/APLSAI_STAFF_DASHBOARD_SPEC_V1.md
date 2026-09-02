# APLSAI HOME — Area Staff / Cabina di Regia V1

## Obiettivo
L'Area Staff non deve essere un semplice archivio. Deve mostrare cosa richiede attenzione oggi, perché, chi deve intervenire e quale sia la prossima azione.

## Schermata iniziale — Oggi
Ordine consigliato:
1. azioni scadute o urgenti;
2. clienti ad alta prontezza con opportunità compatibili;
3. clienti con capitale pronto/verificato o mutuo deliberato;
4. opportunità nuove da analizzare;
5. pratiche bloccate;
6. clienti senza aggiornamenti da troppo tempo;
7. scadenze documentali/operative.

Ogni riga deve avere: cliente/pratica, fase, priorità, motivo, responsabile, ultima attività, prossima azione, eventuale scadenza.

## Scheda cliente
### Identità minima
Nome, contatto, data ingresso, stato ricerca. Dati personali non necessari non devono essere mostrati.

### Ricerca
Zona/raggio, budget, spazi, requisiti, tempi, tipologie, stile, strategia scelta.

### Prontezza finanziaria
Campo strutturato separato dal profilo immobiliare:
- da_verificare;
- mutuo_da_richiedere;
- pre_delibera;
- mutuo_deliberato;
- capitale_dichiarato;
- capitale_verificato.

Mostrare anche: data ultima verifica, chi ha aggiornato lo stato e, se necessario, una nota sintetica non sensibile.

### Priorità operativa
Mostrare livello (es. alta/media/normale) e motivi leggibili. Non mostrare formule proprietarie o pesi interni al cliente/partner.

### Prossima azione
Un solo campo principale con: tipo azione, responsabile, data prevista/scadenza, stato, nota breve.

### Opportunità
Shortlist con compatibilità, criticità, stato verifica e motivazione. Separare compatibilità attuale da potenziale dopo trasformazione.

### Cronologia
Eventi significativi: registrazione, qualificazione, cambi stato, verifiche, proposte, documenti, risposte cliente, avanzamenti.

## Scheda immobile
Riferimento, fonte, zona, prezzo, metratura, caratteristiche, stato, disponibilità, eventuale trasformabilità, verifiche eseguite, pratiche/clienti collegati.

Non trattare come verificato ciò che proviene solo da inserimento preliminare.

## Coda Opportunità
Ogni nuovo immobile passa idealmente per:
Nuovo → Da verificare → Verificato → In matching → Proposto → In trattativa / Scartato / Non disponibile.

## Coda Pratiche
Filtri minimi:
- oggi;
- urgenti;
- alta prontezza finanziaria;
- senza prossima azione;
- bloccate;
- senza aggiornamenti;
- per responsabile;
- per fase.

## Regola anti-abbandono
Una pratica non può restare indefinitamente senza prossima azione. Il sistema deve evidenziare i clienti attivi senza aggiornamenti entro una soglia configurabile.

## Partner
Il partner non usa la stessa dashboard completa dell'Admin. Deve ricevere una vista limitata alla pratica assegnata e alle sole informazioni necessarie all'incarico.

## Audit
Le azioni staff rilevanti devono essere registrate: autore, azione, oggetto, data/ora, esito. Non registrare password, token o segreti.

## Indicatori dashboard
- clienti attivi;
- da qualificare;
- alta prontezza finanziaria;
- azioni da fare oggi;
- pratiche bloccate;
- opportunità da verificare;
- proposte aperte;
- operazioni in avanzamento;
- tempo medio senza aggiornamento.

## Regola UX
La dashboard deve essere leggibile in pochi secondi. Colori e punteggi sono supporti visivi; ogni priorità importante deve avere anche una motivazione testuale.
