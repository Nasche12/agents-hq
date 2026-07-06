// Wird vom belege-buchhaltung-Agent gepflegt. Nicht von Hand editieren.
window.BELEGE_DATA = {
  stand: "2026-07-05",
  monate: [
    {
      monat: "2026-06",
      einnahmen: 0,
      ausgaben: 21.90
    }
  ],
  projekte: [
    {
      name: "ferienhaus-tirol.at",
      einnahmen: 0,
      ausgaben: 21.90,
      belege: [
        {
          datum: "2026-06-14",
          aussteller: "Hetzner Online GmbH",
          betrag: 21.90,
          typ: "Ausgabe",
          nummer: "R2026-0614-889",
          datei: "2026-06-14_hetzner_gmbh_R2026-0614-889.txt"
        }
      ],
      verkaufsfertig: false,
      fehlend: []
    },
    {
      name: "mueller-gmbh.at",
      einnahmen: 0,
      ausgaben: 0,
      belege: [
        {
          datum: "2026-06-20",
          aussteller: "Müller GmbH",
          betrag: 850.00,
          typ: "Einnahme",
          nummer: "2026-042",
          datei: "2026-06-20_mueller_gmbh_2026-042_v1.txt",
          status: "konflikt"
        },
        {
          datum: "2026-06-20",
          aussteller: "Müller GmbH",
          betrag: 920.00,
          typ: "Einnahme",
          nummer: "2026-042",
          datei: "2026-06-20_mueller_gmbh_2026-042_v2.txt",
          status: "konflikt"
        }
      ],
      strittig: [850.00, 920.00],
      verkaufsfertig: false,
      fehlend: []
    }
  ],
  unklar: [
    {
      datei: "2026-06-20_kunde_mueller_rechnung.txt + 2026-06-20_kunde_mueller_rechnung_v2.txt",
      problem: "KONFLIKT: Rechnung 2026-042 doppelt mit 850,00 EUR vs 920,00 EUR - Sebastian entscheidet"
    },
    {
      datei: "2026-06-22_canva_beleg.txt",
      problem: "Rechnungsnummer und Projektzuordnung fehlen. In inbox belassen bis Klärung."
    }
  ]
};
