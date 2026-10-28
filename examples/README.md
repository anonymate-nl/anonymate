# Voorbeelden: herleidbaarheid van KITE-datasets

Herleidbaarheidstoetsen met AnonyMate op openbare woningdatasets van KITE, het Kennis- en
Dataplatform Individuele Technieken van RVO. Elk voorbeeld is gemaakt als privéproject door de maker
van AnonyMate. De rapporten zijn naar de bronhouders gegaan; beslissen over de publicatie is aan hen.
*Worked examples of re-identification assessments on public Dutch home-energy datasets (in Dutch).*

| map | dataset | rapport |
|---|---|---|
| [`dacs-hw/`](dacs-hw/) | DACS-HW | [`docs/herleidbaarheid.md`](dacs-hw/docs/herleidbaarheid.md) |
| [`dph/`](dph/) | Demoproject Hybride | [`docs/herleidbaarheid.md`](dph/docs/herleidbaarheid.md) |
| [`warmingup/`](warmingup/) | WarmingUP How Low Can You Go | [`docs/herleidbaarheid.md`](warmingup/docs/herleidbaarheid.md) |
| [`wattopia/`](wattopia/) | Woningprestaties (Wattopia) | [`docs/herleidbaarheid.md`](wattopia/docs/herleidbaarheid.md) |

Per map staan het rapport, de scripts die de invoer maken en de scenario's (`*.toml`). De data zelf
staat er niet in: de scripts lezen de uitvoer van de preprocessing van de dataset (onder
`data/`), en de uitvoer per woning blijft buiten git (zie [`.gitignore`](.gitignore)). Hoe je een
voorbeeld opnieuw draait, staat onder "Reproduceren" in elk rapport.
