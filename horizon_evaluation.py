"""Dondurulmuş vade kararlarının SGOV'a göre ileri testi."""
from datetime import date, timedelta
from radar import month


def evaluate(reports, prices, today):
    results = []
    last_exit = {}
    for day, report in sorted(reports, key=lambda item: item[0]):
        for asset in report["assets"]:
            symbol = asset["symbol"]
            if symbol == "SGOV":
                continue
            bars = prices.get(symbol, {})
            cash = prices.get("SGOV", {})
            for key, h in asset.get("horizons", {}).items():
                action = h.get("action")
                if action not in ("ALIM ADAYI","AZALTMA ADAYI") or h.get("confirmation") != "YÖN UYUMLU":
                    continue
                if day <= last_exit.get((symbol,key), date.min):
                    continue
                entries = [d for d in cash if day < d <= day+timedelta(days=5)]
                if not entries:
                    continue
                entry = min(entries)
                target = entry+timedelta(weeks=1) if key=="1H" else month(entry,{"1A":1,"3A":3,"1Y":12}[key])
                exits = [d for d in cash if target <= d < today and (d-target).days<=5]
                if not exits:
                    continue
                end = min(exits)
                if not all(series.get(d) for series in (bars,cash) for d in (entry,end)):
                    continue
                excess = 100*(bars[end][1]/bars[entry][0]-cash[end][1]/cash[entry][0])
                signed = excess if action=="ALIM ADAYI" else -excess
                results.append((key,action,signed))
                last_exit[symbol,key] = end
    return results


def extend_report(lines, observations):
    lines += ["", "## Dört vadenin karar doğruluğu", "", "Alım için fonun SGOV’u geçmesi, azaltma için SGOV’un fonu geçmesi başarı sayılır. Ölçüm sonraki seans açılışından vade dolduktan sonraki ilk seans kapanışına kadardır. Sonuçlar brüttür. BEKLE kararları puanlanmaz.", "", "|Vade|Karar|Doğru / tamamlanan|Ortalama yönlü fark (puan)|","|---|---|---:|---:|"]
    for key in ("1H","1A","3A","1Y"):
        for action in ("ALIM ADAYI","AZALTMA ADAYI"):
            values = [v for k,a,v in observations if (k,a)==(key,action)]
            avg = f"{sum(values)/len(values):.2f}" if values else "—"
            lines.append(f"|{key}|{action}|{sum(v>0 for v in values)} / {len(values)}|{avg}|")
