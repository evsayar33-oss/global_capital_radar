"""Beş seanslık ileri test. Her varlığın çakışmayan gözlemlerini kullanır."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from radar import read

ROOT = Path(__file__).resolve().parent
NY = ZoneInfo("America/New_York")


def prices(symbol, start, today):
    query = urlencode({"period1":int(datetime.combine(start, datetime.min.time(), NY).timestamp()),
                       "period2":int(datetime.combine(today, datetime.min.time(), NY).timestamp()),
                       "interval":"1d"})
    chart = json.loads(read(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"))["chart"]["result"][0]
    if chart["meta"]["symbol"] != symbol:
        raise ValueError("Fiyat sembolü eşleşmedi")
    quote = chart["indicators"]["quote"][0]
    adjusted = chart["indicators"]["adjclose"][0]["adjclose"]
    bars = {}
    for ts, op, cl, adj in zip(chart["timestamp"], quote["open"], quote["close"], adjusted, strict=True):
        d = datetime.fromtimestamp(ts,NY).date()
        if None in (op, cl, adj) or min(op, cl, adj) <= 0:
            bars[d] = None
        else:
            bars[d] = (op*adj/cl, adj)
    return bars


def measure(bars, cash, signal_day):
    dates = sorted(d for d in cash if d > signal_day)[:5]
    if len(dates) < 5 or any(not bars.get(d) or not cash[d] for d in dates):
        return None
    first, last = dates[0], dates[-1]
    if (first-signal_day).days > 5 or (last-first).days > 9:
        return None
    def change(series):
        return 100*(series[last][1]/series[first][0]-1)
    return dict(entry=str(first), exit=str(last), return_pct=round(change(bars),4),
                cash_return_pct=round(change(cash),4), excess_pp=round(change(bars)-change(cash),4))


def main():
    folder = ROOT/"history"/"rotation"
    ledger = folder/"outcomes.json"
    results = json.loads(ledger.read_text()) if ledger.exists() else {}
    now = datetime.now(timezone.utc)
    today = now.astimezone(NY).date()
    pending = []
    for path in sorted(folder.glob("2*.json")):
        report = json.loads(path.read_text())
        day = datetime.fromisoformat(report["seen_at"]).astimezone(NY).date()
        if (today-day).days < 8:
            continue
        for r in report["assets"]:
            key = r["symbol"]+"/"+str(day)
            if key not in results and r["status"] in ("ALIM ADAYI","AZALTMA ADAYI","BEKLE","GİRİŞ İZLE","ÇIKIŞ İZLE"):
                pending.append((day,key,r))
    errors = {}
    if pending:
        start = min(d for d,_,_ in pending)
        series = {}
        for sym in sorted({"SGOV"} | {r["symbol"] for _,_,r in pending}):
            try:
                series[sym] = prices(sym,start,today)
            except Exception as exc:
                errors[sym] = str(exc)
        for day,key,r in pending:
            sym = r["symbol"]
            if any(v["symbol"]==sym and v["decision_day"] <= str(day) <= v["exit"] for v in results.values()):
                continue
            outcome = measure(series.get(sym,{}),series.get("SGOV",{}),day)
            if outcome:
                results[key] = dict(symbol=sym,status=r["status"],decision_day=str(day),**outcome)
    temp = ledger.with_suffix(".tmp")
    temp.write_text(json.dumps(results,indent=2,ensure_ascii=False))
    temp.replace(ledger)
    lines = ["# Beş seanslık ileri test", "", "İlk sonraki seansın açılışından beşinci seansın kapanışına. Aynı varlığın örtüşen gözlemleri alınmaz. Fark kısa vadeli bono fonu SGOV getirisinin üzerindedir. Tutarlar brüt getiridir.", ""]
    if not results:
        lines.append("Henüz sonuçlanmış gözlem yok.")
    else:
        lines += ["|Etiket|Gözlem|Ortalama fon getirisi %|SGOV üzerinde ortalama fark (puan)|","|---|---:|---:|---:|"]
        for status in sorted({v["status"] for v in results.values()}):
            group = [v for v in results.values() if v["status"]==status]
            lines.append(f"|{status}|{len(group)}|{sum(v['return_pct'] for v in group)/len(group):.2f}|{sum(v['excess_pp'] for v in group)/len(group):.2f}|")
    if errors:
        lines.append("Fiyat kaynağı erişim sorunu: "+", ".join(errors))
    (ROOT/"FORWARD.md").write_text("\n".join(lines)+"\n")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
