# Duke of Tokyo monitor 🎤

Checkt elke minuut (via GitHub Actions) of de **Akihabara**-ruimte bij Duke of Tokyo Utrecht op **za 27 februari 2027** boekbaar is. Zo ja, dan stuurt hij een urgente pushmelding via [ntfy](https://ntfy.sh).

## Meldingen
| Melding | Wanneer |
|---|---|
| 🎤 **AKIHABARA VRIJ** (urgent) | Een slot met starttijd tussen 14:30 en 19:30 is boekbaar. Voorkeur: 15:45 → 14:45 → 17:00. Herhaalt elke 3 min zolang het vrij is. |
| 📅 Dag staat online, niet vrij | Eenmalig: 27 feb is vrijgegeven maar Akihabara is bezet. Meld je dan aan op de wachtlijst. |
| ⚠️ Monitor stuk | De API faalt 3x op rij. |
| 💓 Monitor draait | Elke dag rond 09:00. |

## Meldingen ontvangen
1. Installeer de **ntfy**-app (iOS / Android).
2. Abonneer je op het topic (staat lokaal in `.ntfy_topic`, en in GitHub als secret `NTFY_TOPIC`).
3. iOS: sta meldingen toe, inclusief *Tijdgevoelig*. Android: zet urgente meldingen aan.

## Stoppen na het boeken
GitHub → repo → **Actions** → *Duke of Tokyo monitor* → **⋯ → Disable workflow**.

## Testen
```bash
python3 monitor.py --test --dry-run          # 30 jan (Akihabara vrij), alleen printen
NTFY_TOPIC=$(cat .ntfy_topic) python3 monitor.py --test   # echte test-push
```
In GitHub: Actions → *Run workflow* → `test_date` = `2027-01-30`.

## Let op
GitHub zet geplande workflows uit na 60 dagen zonder commit. Nog niet geboekt rond 20 januari? Doe dan:
`git commit --allow-empty -m keepalive && git push`
