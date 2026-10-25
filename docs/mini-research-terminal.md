# Jarvis Marktberichte

## Ablauf

1. **Aktie**, **ETF** oder **Krypto** wählen.
2. Name, Börsensymbol oder ISIN suchen und den richtigen Treffer auswählen.
   Börse und Währung beachten: dasselbe Unternehmen oder derselbe Fonds kann
   mehrere Notierungen und Anteilsklassen haben.
3. Zeitraum wählen und **Bericht erstellen**. Standard ist ein Jahr.
4. Zuerst die belegten Kernaussagen und Datenlücken lesen; Zahlen und Quellen
   bei Bedarf aufklappen. Vergleich und historische Auswertung sind Folgeaktionen.

## Was ein Bericht aussagt

Der Bericht beschreibt beobachtete Daten, keine Kaufentscheidung. Jede Kennzahl
gehört zu einer Quelle, einem Zeitraum und einer Einheit. Abrufzeit und
Beobachtungszeit sind verschieden: ein gerade abgerufener Jahresabschluss
beschreibt weiterhin das darin genannte Geschäftsjahr.

Ein Teilbericht bleibt nutzbar, ist aber keine vollständige Unternehmens- oder
Fondsprüfung. Fehlende, nicht unterstützte, veraltete und wegen eines
Anbieterfehlers nicht gelieferte Daten dürfen nicht als Null interpretiert werden.

### Aktien

Kursentwicklung und beobachtete Geschäftszahlen gehören zusammen. Bewertung,
Umsatzwachstum, Margen, Cashflow und Verschuldung sind nur aussagekräftig, wenn
Bezugsperioden, Einheiten und tatsächliche Datenabdeckung stimmen. Analysten-
schätzungen sind keine beobachteten Geschäftsergebnisse.

### ETFs

Ein Kurschart allein beschreibt weder die Fondspositionen noch die Gesamtkosten
oder das Konzentrationsrisiko. Die kostenlose Yahoo-Anbindung liefert
ETF-Stammdaten. Kleine lokale OpenBB-Fetcher ergänzen verfügbare Kostenquoten,
die zehn größten gemeldeten Positionen und Branchengewichte aus der bereits
installierten Yahoo-Bibliothek. Das ist kein vollständiges Portfolio; ein
Beobachtungsdatum wird von dieser Quelle nicht geliefert. Die Abrufzeit ist
kein Ersatz dafür. Kostenquoten können bei europäischen ETFs weiterhin fehlen.
Für **SPY** ergänzt eine feste, identitätsgeprüfte State-Street-Anbindung die
offiziellen Fondsangaben und die vollständige tägliche Positionsdatei. Index,
Anlageziel, Ausschüttungsrhythmus, Sponsor, Treuhänder, Fondsvermögen, NAV und
Ausschüttungsrendite werden mit ihren tatsächlichen Einheiten und
Beobachtungsdaten übernommen. Die 505 Positionen der geprüften Datei und die
Branchengewichte gelten für deren ausgewiesenen Stichtag; sie sind keine
Echtzeitpositionen. Die zusätzliche Herausgeberanbindung gilt bisher für SPY.
Yahoo-Zusatzangaben bleiben separat mit ihrer eigenen Quelle erhalten.
Die offizielle Anlageregion ist eine Klassifikation, keine prozentuale
Ländergewichtung. Sponsor und Treuhänder werden nicht als Emittent umgedeutet.
Länderverteilung, Replikation und Ausschüttungsregeln bleiben offen, wenn sie
nicht tatsächlich geliefert werden. Tracking Difference wird ohne geeignete
Gesamtrenditedaten des Fonds und des Referenzindex nicht berechnet.

### Krypto

Die installierten kostenlosen OpenBB-Kryptorouten liefern Kurs- und
Volumendaten. Ein lokaler typisierter OpenBB-Fetcher ergänzt beobachtete
Marktkapitalisierung sowie Umlauf-, Gesamt- und Maximalangebot, soweit Yahoo
diese liefert. Die Währung der Marktkapitalisierung wird separat übernommen;
Angebotszahlen werden nicht mit einer Währung oder einem Handelspaar beschriftet.
Aus Volumen oder Kurs allein lassen sich diese Werte nicht ableiten. Eine Kursauswertung
ist keine Prüfung von Tokenomics, Protokollsicherheit oder Verwahrungsrisiken.

## Vergleichsgrenzen

- Renditen aus Schlusskursen sind keine verifizierte Gesamtrendite inklusive
  Ausschüttungen. Eine vollständige Dividenden-/Split-Bereinigung ist nicht
  garantiert und wird nicht stillschweigend angenommen.
- Ohne Wechselkursdaten erfolgt keine Währungsumrechnung. Lokale Kursrenditen
  und die Rendite eines Schweizer Anlegers in CHF können voneinander abweichen.
- Historische Zusammenhänge und Korrelationen sind keine kausalen Belege und
  keine Prognosen.

## Betrieb

Die Oberfläche verwendet den vorhandenen geschützten Research-Zugang. Die
Standardberichte verwenden Yahoo, SEC und für SPY die öffentlichen Angaben von
State Street; ein vorhandener FMP-Schlüssel
aktiviert dafür keine Schlüssel-basierten Anbieter-Routen automatisch.
Die bestehende separate Makrokonfiguration bleibt erhalten. Freie
Quellen können begrenzt, verzögert oder vorübergehend nicht erreichbar sein.
Ein lokaler Test bestätigt weder eine Veröffentlichung noch den Datenstand
einer separat laufenden Instanz. Prüfresultate für diesen Ausbau stehen im
zugehörigen Implementierungsprotokoll.
