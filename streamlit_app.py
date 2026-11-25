from pathlib import Path
from datetime import date
import streamlit as st
from dashboard_data import read_report, latest_macro, coverage_rows, method_rows, native_rows, historical_rows, macro_rows, rotation_rows, continuity_rows, display_frame

def table(rows, empty="Henüz kayıt yok."):
    if rows:
        st.dataframe(display_frame(rows), hide_index=True, width="stretch")
    else:
        st.info(empty)


st.set_page_config(page_title="Küresel Sermaye Radarı", layout="wide")
st.title("Küresel Sermaye Radarı")
ROOT = Path(__file__).parent / "history"
data, primary_error = read_report(ROOT, "rotation/latest.json")
if primary_error:
    st.error(primary_error)
st.caption("Ana gözlem · " + str(data.get("seen_at") or "Kayıt yok") + " · Akışlar seçili ABD fonlarında milyon USD.")
assets = data.get("assets", [])
continuity = data.get("continuity", {})
cols = st.columns(3)
cols[0].metric("Birincil kaynak hatası", f"{sum(bool(a.get('error')) for a in assets)}/{len(assets)}")
cols[1].metric("Alternatif gözlem", continuity.get("alternative_count", "—"))
cols[2].metric("Alternatif veri yok", continuity.get("unavailable_count", "—"))
if any(a.get("error") for a in assets):
    st.warning("Birincil akış kaynağı kullanılamıyor. Eski akış değerleri yalnız referanstır; alternatif araştırma verisi aşağıda ayrıdır. Üretim kararı değiştirilmedi.")
key = st.radio("Yatırım vadesi", ["1H","1A","3A","1Y"], horizontal=True,
               format_func={"1H":"1 hafta","1A":"1 ay","3A":"3 ay","1Y":"1 yıl"}.get)
try:
    expired = (date.today()-date.fromisoformat((data.get("seen_at") or "")[:10])).days > 7
except ValueError:
    expired = True
if expired:
    st.warning("Rapor güncellenmemiş. Kararlar son gözlem tarihine aittir.")
rows = rotation_rows(assets, key, expired)
table(rows)
st.caption("— veri yok veya hesaplanamıyor demektir; sıfır değildir. Eksik veri açıklaması ve kaynak tarihini kontrol edin.")
st.caption("Yatay, ölçülen para hareketinin küçük olduğunu gösterir. Fiyat oynaklığı veya gelecek getiri tahmini vermez.")

continuity = data.get("continuity",{})
if continuity:
    st.subheader("Alternatif veri kaynakları · araştırma")
    st.caption("Birincil kaynak ayrı kalır. Alternatif veri üretim kararı veya onaylanmış strateji değildir.")
    st.write("Durum: "+continuity.get("status","UNAVAILABLE"))
    table(continuity_rows(assets, continuity, key, expired))



st.header("Bağımsız araştırma ve veri sağlığı")
st.caption("Her bölüm kendi son kaydını gösterir; farklı kaynakların tarihleri ve yöntemleri birleştirilmez. Boş değer sıfır değildir. Araştırma, üretim kararı veya kabul edilmiş strateji değildir.")

def report(relative):
    obj, error = read_report(ROOT, relative)
    if error:
        st.warning(error)
    return obj


native, methods, history, macro, validation = st.tabs([
    "Vadeli / native kaynaklar", "Yöntem ve ileri test", "Tarihsel kapsam", "Makro", "Veri sağlığı"
])
with native:
    nr = report("native_research/results.json")
    st.caption("Native araştırma değerlendirmesi · " + str(nr.get("evaluated_at", "Kayıt yok")))
    sources = report("native_research/native_latest.json")
    table(native_rows(sources))
    st.caption("WTI alternatif fiyatları resmî uzlaşma fiyatı değildir. Bono ihalesi TBF3 pozisyonu değildir. Kotasyon spreadi gerçekleşmiş işlem maliyeti değildir.")
    if sources:
        selected = st.selectbox("Kaynak ayrıntısı", list(sources))
        st.json(sources[selected], expanded=False)
with methods:
    nr = report("native_research/results.json")
    ar = report("adaptive_results.json")
    native_forward = nr.get("prospective", {})
    adaptive_forward = ar.get("prospective", {})
    exploratory = nr.get("exploratory", {})
    c = st.columns(3)
    c[0].metric("ETFIQ keşif kohortu", len(exploratory))
    c[1].metric("ETFIQ ileri değerlendirme", len(native_forward))
    c[2].metric("Birincil ileri değerlendirme", len(adaptive_forward))
    st.caption("ETFIQ değerlendirmesi · " + str(nr.get("evaluated_at", "Kayıt yok")))
    st.caption("Birincil Adaptive V2 · " + str(ar.get("evaluated_at", "Kayıt yok")))
    st.caption("M00–M12: ölçülebilen bağımsız dönemler ve SGOV'a göre yönsel puanlar. Bunlar gerçekleşebilir portföy getirisi değildir. Güncel vintage replay keşif amaçlıdır; ileri test veya üretim onayı değildir.")
    table(coverage_rows(nr))
    st.subheader("ETFIQ keşif sonuçları · seçili vade")
    table(method_rows(exploratory, key), "Bu vadede kullanılabilir keşif sonucu yok.")
    st.subheader("ETFIQ ileri sonuçları · seçili vade")
    table(method_rows(native_forward, key), "Bu vadede sonuçlanmış ileri değerlendirme yok.")
    st.subheader("Birincil Adaptive V2 · keşif / ileri")
    table(method_rows(ar.get("exploratory_current_vintage", {}), key), "Birincil keşif sonucu yok.")
    table(method_rows(adaptive_forward, key), "Birincil ileri değerlendirme yok.")
    with st.expander("Ham değerlendirme, maliyet varsayımları ve politika"):
        st.json({"native": nr, "adaptive": ar}, expanded=False)
with history:
    extended = report("native_research/extended_history/results.json")
    st.caption("Son tarihsel araştırma · " + str(extended.get("evaluated_at", "Kayıt yok")))
    st.caption("Aylık kayıtlar günlük seriye dönüştürülmez; kesintili geçmiş, kesintisiz günlük veri değildir.")
    table(historical_rows(extended))
    st.subheader("İlk görülen AUM gözlemleri")
    aum = report("native_research/aum_observations.json")
    table([{"Fon": symbol, "AUM tarihi": day, "AUM USD": item.get("value"), "İlk görülme UTC": item.get("first_seen"), "Kaynak tarihi": item.get("source_date")} for symbol, days in aum.items() for day, item in sorted(days.items())])
with macro:
    mr, error = latest_macro(ROOT)
    if error:
        st.warning(error)
    st.caption("Makro gözlem · " + str(mr.get("as_of", "Kayıt yok")))
    table(macro_rows(mr))
    st.subheader("Beklentiler")
    table([{"Gösterge": name, "Dönem": item.get("period"), "Değer": item.get("value"), "Durum": "Kaynak hatası" if item.get("error") else ("Eski" if item.get("stale") else "Gözlem"), "Hata": item.get("error")} for name, item in mr.get("expectations", {}).items()])
    with st.expander("Beklenti kaynağı ayrıntıları"):
        st.json(mr.get("expectations", {}), expanded=False)
with validation:
    vr = report("validation.json")
    st.caption("Son denetim · " + str(vr.get("checked_at", "Kayıt yok")))
    table([{"Fon": item.get("asset"), "Akış tarihi": item.get("flow_date"), "Kaynak hatası": item.get("source_error"), "Önbellek": item.get("cached"), "Eski": item.get("stale"), "Eksik vadeler": ", ".join(item.get("missing_horizons", [])), "CFTC tarihi": item.get("cot_date")} for item in vr.get("assets", [])])
    st.subheader("Açık entegrasyonlar")
    for item in vr.get("open_integrations", []):
        st.write("• " + item)
    st.caption(str(vr.get("selection", "")))
    st.subheader("Alternatif kaynak ayrıntıları")
    for symbol, result in continuity.get("assets", {}).items():
        with st.expander(symbol + " · " + str(result.get("status", "—"))):
            st.json(result, expanded=False)

