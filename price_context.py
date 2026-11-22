"""Vade fiyat getirileri, göreli güç ve araştırma modeli kayıtları."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from evaluate_rotation import prices
import json
from pathlib import Path
from horizons import boundary


def returns(bars, end, key):
    dates = sorted(d for d,v in bars.items() if v and d <= end)
    target = boundary(end,key,1)
    previous = [d for d in dates if d <= target]
    if not dates or not previous or (end-dates[-1]).days>4 or (target-previous[-1]).days>4:
        return None
    return 100*(bars[dates[-1]][1]/bars[previous[-1]][1]-1)


def enrich(rows, today):
    macro_files = sorted((Path(__file__).parent/"history").glob("????-??-??.json"))
    macro = {}
    if macro_files:
        macro = {r["id"]: r for r in json.loads(macro_files[-1].read_text()).get("indicators",[]) if not r.get("error") and not r.get("stale")}
    symbols = {r["symbol"] for r in rows} | {"SGOV","RSP"}
    series, errors = {}, {}
    def get(symbol):
        try:
            return symbol,prices(symbol,today-timedelta(days=400),today),None
        except Exception as exc:
            return symbol,{},type(exc).__name__
    with ThreadPoolExecutor(max_workers=4) as pool:
        for symbol,bars,error in pool.map(get,symbols):
            series[symbol]=bars
            if error:
                errors[symbol]=error
    # Ortak tarih, tamamlanmış son ABD seansı.
    common = sorted(d for d,v in series.get("SGOV",{}).items() if v)
    if not common:
        for row in rows:
            for h in row.get("horizons",{}).values():
                h.update(price_confirmation="Fiyat gözlemi eksik")
        return errors
    end = common[-1]
    for row in rows:
        row["price_asof"]=str(end)
        for key,h in row.get("horizons",{}).items():
            h["macro_context"] = {name: {"asof":macro[code]["period"],"change":macro[code].get("changes",{}).get(key)}
                                  for name,code in (("dollar","DTWEXBGS"),("real_yield","DFII10"))
                                  if code in macro and (today-date.fromisoformat(macro[code]["period"])).days<=10}
            value = returns(series.get(row["symbol"],{}),end,key)
            cash = returns(series["SGOV"],end,key)
            h["total_return_pct"]=value
            h["excess_sgov_pp"]=None if value is None or cash is None else value-cash
            if value is None or cash is None or (today-end).days>5:
                h["price_confirmation"]="TEYİTSİZ · fiyat verisi eksik/eski"
                continue
            excess=value-cash
            flow=h.get("net_usd_m")
            h["price_confirmation"]="YÖN UYUMLU" if flow is not None and flow*excess>0 else "TEYİTSİZ · fiyat yönü desteklemiyor"
            h["models"]={"price_only":"ALIM ADAYI" if excess>0 else "AZALTMA ADAYI",
                         "price_flow":"BEKLE"}
            if h.get("flow_aum_pct") is not None and flow*excess>0:
                h["models"]["price_flow"]=h["models"]["price_only"]
            if row["symbol"] in ("SPY","QQQ","DIA","IWM"):
                rsp=returns(series["RSP"],end,key)
                spy=returns(series.get("SPY",{}),end,key)
                h["breadth_rsp_spy_pp"]=None if rsp is None or spy is None else rsp-spy
            if row["symbol"]=="SLV":
                gold=returns(series.get("GLD",{}),end,key)
                h["silver_gold_pp"]=None if gold is None else value-gold
    for key in ("1H","1A","3A","1Y"):
        ranked=sorted((r for r in rows if r.get("horizons",{}).get(key,{}).get("excess_sgov_pp") is not None),key=lambda r:r["horizons"][key]["excess_sgov_pp"],reverse=True)
        for rank,row in enumerate(ranked,1):
            row["horizons"][key]["relative_rank"]=rank
            row["horizons"][key]["rank_count"]=len(ranked)
    return errors
