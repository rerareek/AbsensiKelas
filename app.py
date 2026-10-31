import streamlit as st
import pandas as pd
from datetime import date, timedelta
from supabase import create_client

st.set_page_config(page_title="Absensi Kelas", page_icon="📋", layout="wide")

LEVELS = ["X", "XI", "XII"]
NOTES = ["-", "Terlambat", "Sakit", "Izin", "Alpa", "Lainnya"]
STATUSES = ["Hadir", "Terlambat", "Sakit", "Izin", "Alpa"]


@st.cache_resource
def get_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


sb = get_db()


# ---------- Auth sederhana (password bersama untuk guru) ----------
def login() -> bool:
    if st.session_state.get("ok"):
        return True
    st.title("📋 Absensi Kelas")
    pw = st.text_input("Password guru", type="password")
    if st.button("Masuk"):
        if pw == st.secrets["APP_PASSWORD"]:
            st.session_state.ok = True
            st.rerun()
        else:
            st.error("Password salah")
    return False


# ---------- Data helpers ----------
def get_classes() -> pd.DataFrame:
    r = sb.table("classes").select("*").order("level").order("name").execute().data
    return pd.DataFrame(r, columns=["id", "level", "name", "created_at"])


def get_students(class_id: int) -> pd.DataFrame:
    r = (sb.table("students").select("id,name").eq("class_id", class_id)
         .eq("active", True).order("name").execute().data)
    return pd.DataFrame(r, columns=["id", "name"])


def class_picker(prefix: str, allow_all=False):
    """Pilih tingkat lalu kelas. Return (level, class_row | None)."""
    classes = get_classes()
    if classes.empty:
        st.info("Belum ada kelas. Tambahkan dulu di menu **Kelola Kelas & Siswa**.")
        return None, None
    levels = ["Semua"] + LEVELS if allow_all else LEVELS
    c1, c2 = st.columns(2)
    level = c1.selectbox("Tingkat", levels, key=f"{prefix}_lv")
    sub = classes if level == "Semua" else classes[classes.level == level]
    names = (["Semua"] if allow_all else []) + sub.name.tolist()
    if not names:
        c2.warning("Belum ada kelas di tingkat ini.")
        return level, None
    cname = c2.selectbox("Kelas", names, key=f"{prefix}_cl")
    if cname == "Semua":
        return level, None
    row = sub[sub.name == cname].iloc[0]
    return level, row


def status_of(present: bool, note: str) -> str:
    if present:
        return "Terlambat" if note == "Terlambat" else "Hadir"
    return note if note in ("Sakit", "Izin") else "Alpa"


# ---------- Halaman: Absensi ----------
def page_absensi():
    st.header("Absensi Harian")
    level, cls = class_picker("abs")
    if cls is None:
        return
    d = st.date_input("Tanggal", value=date.today(), max_value=date.today())
    students = get_students(int(cls.id))
    if students.empty:
        st.info("Kelas ini belum punya siswa. Tambahkan di menu Kelola.")
        return

    saved = (sb.table("attendance").select("student_id,present,note")
             .eq("class_id", int(cls.id)).eq("date", str(d)).execute().data)
    saved = {s["student_id"]: s for s in saved}
    if saved:
        st.caption("✏️ Absensi tanggal ini sudah tersimpan; perubahan akan menimpa data lama.")

    df = pd.DataFrame({
        "student_id": students.id,
        "Nama": students.name,
        "Hadir": [saved.get(i, {}).get("present", False) for i in students.id],
        "Catatan": [saved.get(i, {}).get("note", "-") for i in students.id],
    })

    c1, c2, _ = st.columns([1, 1, 4])
    if c1.button("Semua hadir"):
        df["Hadir"] = True
        st.session_state["abs_df"] = df
    if c2.button("Reset"):
        st.session_state.pop("abs_df", None)

    key = f"{cls.id}-{d}"
    if st.session_state.get("abs_key") != key:
        st.session_state["abs_key"] = key
        st.session_state.pop("abs_df", None)
    base = st.session_state.get("abs_df", df)

    edited = st.data_editor(
        base, hide_index=True, use_container_width=True, key=f"ed-{key}-{len(base)}-{int(base.Hadir.sum())}",
        column_order=["Nama", "Hadir", "Catatan"],
        disabled=["Nama"],
        column_config={
            "Hadir": st.column_config.CheckboxColumn("Hadir"),
            "Catatan": st.column_config.SelectboxColumn("Catatan", options=NOTES, required=True),
        },
    )

    if st.button("💾 Simpan absensi", type="primary"):
        rows = []
        for _, r in edited.iterrows():
            note = r["Catatan"]
            if not r["Hadir"] and note == "-":
                note = "Alpa"  # tidak hadir tanpa keterangan
            rows.append({
                "student_id": int(r["student_id"]), "class_id": int(cls.id),
                "date": str(d), "present": bool(r["Hadir"]), "note": note,
            })
        sb.table("attendance").upsert(rows, on_conflict="student_id,date").execute()
        st.success(f"Tersimpan: {len(rows)} siswa, {d:%d %b %Y}")


# ---------- Halaman: Kelola ----------
def page_kelola():
    st.header("Kelola Kelas & Siswa")
    t1, t2, t3 = st.tabs(["Tambah kelas", "Tambah siswa", "Daftar / nonaktifkan siswa"])

    with t1:
        c1, c2 = st.columns(2)
        lv = c1.selectbox("Tingkat", LEVELS, key="nc_lv")
        nm = c2.text_input("Nama kelas (mis. A / IPA 1)", key="nc_nm")
        if st.button("Tambah kelas"):
            if nm.strip():
                try:
                    sb.table("classes").insert({"level": lv, "name": nm.strip()}).execute()
                    st.success(f"Kelas {lv} - {nm.strip()} ditambahkan")
                except Exception:
                    st.error("Kelas sudah ada atau terjadi kesalahan.")
            else:
                st.warning("Nama kelas wajib diisi.")

    with t2:
        level, cls = class_picker("ns")
        if cls is not None:
            names = st.text_area("Nama siswa (satu nama per baris)", height=200)
            if st.button("Simpan siswa"):
                lst = list(dict.fromkeys(n.strip() for n in names.splitlines() if n.strip()))
                if lst:
                    sb.table("students").upsert(
                        [{"class_id": int(cls.id), "name": n, "active": True} for n in lst],
                        on_conflict="class_id,name").execute()
                    st.success(f"{len(lst)} siswa disimpan di {cls.level} - {cls['name']}")

    with t3:
        level, cls = class_picker("ls")
        if cls is not None:
            s = get_students(int(cls.id))
            if s.empty:
                st.info("Belum ada siswa aktif.")
            else:
                pick = st.selectbox("Siswa", s.name.tolist())
                st.caption("Nonaktifkan jika siswa pindah/lulus. Riwayat absensinya tetap tersimpan.")
                if st.button("Nonaktifkan siswa"):
                    sid = int(s[s.name == pick].id.iloc[0])
                    sb.table("students").update({"active": False}).eq("id", sid).execute()
                    st.rerun()
                st.dataframe(s[["name"]].rename(columns={"name": "Nama"}), hide_index=True)


# ---------- Halaman: Dashboard ----------
def fetch_attendance(start, end):
    rows, i = [], 0
    while True:  # paginasi, karena Supabase membatasi 1000 baris/request
        r = (sb.table("attendance")
             .select("id,date,present,note,students(name),classes(level,name)")
             .gte("date", str(start)).lte("date", str(end))
             .order("id").range(i, i + 999).execute().data)
        rows += r
        if len(r) < 1000:
            break
        i += 1000
    return rows


def page_dashboard():
    st.header("Dashboard Kehadiran")
    level, cls = class_picker("db", allow_all=True)
    if level is None:
        return
    c1, c2, c3 = st.columns(3)
    mode = c1.radio("Periode", ["Mingguan", "Bulanan"], horizontal=True)
    start = c2.date_input("Dari", value=date.today() - timedelta(days=90))
    end = c3.date_input("Sampai", value=date.today())

    rows = fetch_attendance(start, end)
    if not rows:
        st.info("Belum ada data pada rentang ini.")
        return
    df = pd.json_normalize(rows).rename(columns={
        "students.name": "siswa", "classes.level": "tingkat", "classes.name": "kelas"})
    df["date"] = pd.to_datetime(df["date"])
    if level != "Semua":
        df = df[df.tingkat == level]
    if cls is not None:
        df = df[df.kelas == cls["name"]]
    if df.empty:
        st.info("Tidak ada data untuk filter ini.")
        return
    df["status"] = [status_of(p, n) for p, n in zip(df.present, df.note)]

    # Ringkasan
    tot = len(df)
    cnt = df.status.value_counts().reindex(STATUSES, fill_value=0)
    m = st.columns(6)
    m[0].metric("% Kehadiran", f"{(cnt['Hadir'] + cnt['Terlambat']) / tot * 100:.1f}%")
    for col, s in zip(m[1:], STATUSES):
        col.metric(s, int(cnt[s]))

    # Tren per periode
    freq = "W" if mode == "Mingguan" else "M"
    df["periode"] = df.date.dt.to_period(freq).dt.start_time
    ct = pd.crosstab(df.periode, df.status).reindex(columns=STATUSES, fill_value=0).sort_index()
    st.subheader(f"Akumulasi {mode.lower()}")
    chart = ct.copy()
    chart.index = chart.index.strftime("%d %b %Y" if freq == "W" else "%b %Y")
    st.bar_chart(chart)
    tbl = ct.copy()
    tbl["% Hadir"] = ((tbl.Hadir + tbl.Terlambat) / tbl.sum(axis=1) * 100).round(1)
    tbl.index = chart.index
    st.dataframe(tbl, use_container_width=True)

    # Per kelas
    st.subheader("Per kelas")
    pk = pd.crosstab([df.tingkat, df.kelas], df.status).reindex(columns=STATUSES, fill_value=0)
    pk["% Hadir"] = ((pk.Hadir + pk.Terlambat) / pk.sum(axis=1) * 100).round(1)
    st.dataframe(pk, use_container_width=True)

    # Per siswa
    st.subheader("Per siswa")
    ps = pd.crosstab([df.tingkat, df.kelas, df.siswa], df.status).reindex(columns=STATUSES, fill_value=0)
    ps["% Hadir"] = ((ps.Hadir + ps.Terlambat) / ps.sum(axis=1) * 100).round(1)
    st.dataframe(ps.sort_values("% Hadir"), use_container_width=True)
    st.download_button("⬇️ Unduh CSV (per siswa)", ps.to_csv().encode(), "rekap_siswa.csv", "text/csv")


# ---------- Main ----------
if login():
    page = st.sidebar.radio("Menu", ["Absensi", "Dashboard", "Kelola Kelas & Siswa"])
    if st.sidebar.button("Keluar"):
        st.session_state.clear()
        st.rerun()
    {"Absensi": page_absensi, "Dashboard": page_dashboard,
     "Kelola Kelas & Siswa": page_kelola}[page]()
