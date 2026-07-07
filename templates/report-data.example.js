/* BEISPIEL — zeigt das exakte Format, das der wochenreport-Agent pro Woche schreibt.
   Kopie landet als reports/JJJJ-KW/report-data.js neben einer Kopie von report.html.
   JEDE Zahl stammt aus einer Umami-API-Response — hier nur Demo-Werte.
   prev = dieselben Kennzahlen der Vorwoche (für den %-Vergleich).
   Weglassen einer Kennzahl => "–" im Report; kein Raten. */
window.REPORT_DATA = {
  woche: "KW 27/2026",
  zeitraum: "30.06.–06.07.2026",
  erstellt: "07.07.2026",
  quelle: "analytics.naschberger.info",
  sites: [
    {
      name: "ferienhaus-tirol.at",
      url: "https://ferienhaus-tirol.at",
      visitors: 1240, pageviews: 4380, avg_duration: 142, bounce_rate: 38.2,
      prev: { visitors: 980, pageviews: 3510, avg_duration: 150, bounce_rate: 41.0 },
      top_pages: [
        { t: "/", n: 1810 }, { t: "/wohnungen", n: 940 }, { t: "/preise", n: 720 },
        { t: "/anfrage", n: 510 }, { t: "/umgebung", n: 400 }
      ],
      top_sources: [
        { t: "google", n: 2100 }, { t: "direkt", n: 1200 }, { t: "booking.com", n: 640 },
        { t: "instagram", n: 260 }, { t: "bing", n: 180 }
      ],
      outlier: "Besucher +26,5 %: fast vollständig über google (organisch, Seite /wohnungen). Wochentagsspitze Do–Fr."
    },
    {
      name: "mueller-gmbh.at",
      url: "https://mueller-gmbh.at",
      visitors: 310, pageviews: 720, avg_duration: 95, bounce_rate: 52.4,
      prev: { visitors: 330, pageviews: 780, avg_duration: 92, bounce_rate: 50.1 },
      top_pages: [
        { t: "/", n: 300 }, { t: "/leistungen", n: 180 }, { t: "/kontakt", n: 120 },
        { t: "/ueber-uns", n: 80 }, { t: "/impressum", n: 40 }
      ],
      top_sources: [
        { t: "direkt", n: 380 }, { t: "google", n: 240 }, { t: "linkedin", n: 60 }
      ],
      outlier: null
    }
  ]
};
