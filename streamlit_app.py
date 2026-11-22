import json
from pathlib import Path
from datetime import date
import streamlit as st

st.set_page_config(page_title="Küresel Sermaye Radarı", layout="wide")
st.title("Küresel Sermaye Radarı")
data = json.loads((Path(__file__).parent/"history/rotation/latest.json").read_text())
st.caption("Araştırma gözlemi · " + data["seen_at"][:10] + " · Akışlar seçili ABD fonlarında milyon USD.")
key = st.radio("Yatırım vadesi", ["1H","1A","3A","1Y"], horizontal=True,
               format_func={"1H":"1 hafta","1A":"1 ay","3A":"3 ay","1Y":"1 yıl"}.get)
expired = (date.today()-date.fromisoformat(data["seen_at"][:10])).days > 7
if expired:
    st.warning("Rapor güncellenmemiş. Kararlar son gözlem tarihine aittir.")
rows = []
for asset in data["assets"]:
    h = asset.get("horizons",{}).get(key,{})
    rows.append({"Varlık":asset["asset"],"Fon":asset["symbol"],"Net milyon USD":h.get("net_usd_m"),
                 "Akış":h.get("strength","Veri eksik"),"Geçmiş dönem":h.get("reference_count"),
                 "Yüzdelik":h.get("magnitude_percentile"),"Vadeli teyit":h.get("confirmation","TEYİTSİZ"),
                 "Karar":"BEKLE · rapor eski" if expired else h.get("action","BEKLE"),"Akış tarihi":asset.get("flow_asof"),"Vadeli tarih":h.get("cot_end")})
st.dataframe(rows,hide_index=True,width="stretch")
st.caption("Yatay, ölçülen para hareketinin küçük olduğunu gösterir. Fiyat oynaklığı veya gelecek getiri tahmini vermez.")
