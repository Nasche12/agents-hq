# Schreib- & Kürzungs-Regeln für Captions, Hooks & Textbausteine

> Gemeinsame Text-Regel für alle Content-Agents (`video-producent`, `ki-influencer`,
> `content-recherche`). Ziel: Texte klingen nach einem Menschen, nicht nach einem LLM,
> das alles zu Roboter-Stakkato komprimiert hat. Kürzen heißt **weglassen**, nicht
> **zusammenpressen**.
>
> Marke schlägt diese Regel: Wo `config/influencer.json` (`stimme_ton`, `sprache`)
> oder ein Kunden-Kontext etwas anderes vorgibt, gewinnt der. Diese Datei ist der
> Default, nicht das Gesetz.

## Der Kern: kürzen wie ein Editor, nicht wie ein Kompressor

Wenn ein Text zu lang ist:

1. **Ganze Absätze/Sätze streichen, die denselben Punkt zweimal machen.** Redundanz raus.
2. **Füllphrasen trimmen** ("im Grunde genommen", "es ist wichtig zu verstehen, dass",
   "in der heutigen Zeit"). Weg damit — der Satz steht auch ohne.
3. **Was bleibt, bleibt ganz.** Einen natürlichen Satz NICHT zu einem abgehackten
   Fragment eindampfen, nur um Zeichen zu sparen. Lieber einen Gedanken ganz streichen
   als drei Gedanken zu Telegramm-Stil verstümmeln.
4. **Rhythmus, Ton und Persönlichkeit bleiben.** Die kleine Nebenbemerkung, die den Text
   menschlich macht, ist kein Füllmaterial — die bleibt.

Merksatz: **Absätze löschen, keine Sätze zerquetschen.**

## Woran man den Roboter-Text erkennt (und vermeidet)

- Alles gleich lang, gleicher Takt, kein Atem. → Satzlängen mischen. Ein kurzer Satz
  nach einem langen wirkt.
- Drei Aussagen mit Kommas/Slashes in einen Satz gestopft. → Trennen oder eine
  streichen.
- Jede Zeile fängt gleich an. → Variieren.
- Aufzählungs-Ton in Prosa ("schnell, einfach, günstig"). → Das ist eine Werbephrase,
  kein Satz. Konkret werden oder weglassen.
- Superlative ohne Beleg ("das beste", "revolutionär", "unglaublich"). → Raus, außer
  belegbar. (Siehe auch die „Nichts erfinden"-Regeln der Agents.)

## Für Captions (Social)

- **Erste Zeile ist der Hook** — sie muss allein stehen und neugierig machen. Kein
  Aufwärmen, kein "In diesem Video zeige ich dir…".
- **Eine Idee pro Caption.** Nicht zwei Botschaften reinquetschen.
- **CTA am Ende**, konkret und ruhig (aus `cta` der Config, wenn vorhanden). Kein
  marktschreierisches "JETZT SICHERN!!!".
- **Länge nach Plattform**, aber im Zweifel kürzer. Lieber 2 starke Zeilen als 6 mittlere.
- **Sprache** nach Zielgruppe/Config (Default Deutsch). Ton nicht verbiegen.

## Für Hooks (erste 2–3 Sekunden im Video / erste Caption-Zeile)

- Ein konkreter Moment, eine Spannung, eine offene Schleife. Keine Zusammenfassung.
- Aktiv, nicht erklärend. "Tür auf — und dann das." schlägt "In diesem Reel sieht man,
  wie die Tür aufgeht."

## Hashtags

- 5–10 Stück, passend zur Nische (bei `ki-influencer`/`content-recherche` aus dem
  Trend-Check). Kein Hashtag-Spam, keine erfundenen/irrelevanten Tags.

## Selbstprüfung vor „fertig" (Text)

- [ ] Kein Absatz sagt dasselbe zweimal.
- [ ] Kein natürlicher Satz wurde zu einem abgehackten Fragment zerquetscht.
- [ ] Erste Zeile funktioniert als eigenständiger Hook.
- [ ] Keine unbelegten Superlative / erfundenen Claims.
- [ ] Ton passt zu `stimme_ton`/Zielgruppe, nicht generisch-glatt.
