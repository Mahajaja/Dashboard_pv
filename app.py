import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google import genai
import json
import pymssql

# ==========================================
# 1. CONFIGURACIÓN INICIAL DE LA APP
# ==========================================
st.set_page_config(
    page_title="Green Gold - Vehículos",
    layout="wide",
    initial_sidebar_state="expanded"
)

config_plotly = {'displayModeBar': False}

# Diccionario Global de Meses
meses_espanol = {
    1: 'Ene', 2: 'Feb', 3: 'Mar', 4: 'Abr', 5: 'May', 6: 'Jun',
    7: 'Jul', 8: 'Ago', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dic'
}

# CLAVE DE LA API PARA ANÁLISIS AI
API_KEY = st.secrets["GEMINI_API_KEY"]
client = genai.Client(api_key=API_KEY)

# ENCABEZADO DE LA APLICACIÓN
col_logo, col_titulo = st.columns([1, 8])
with col_logo:
    try:
        st.image("GREEN GOLD.png", width=80)
    except:
        pass
with col_titulo:
    st.title("Dashboard Parque Vehicular")


# --- FUNCIÓN DE CLASIFICACIÓN DE CATEGORÍAS SEGÚN SIGLAS ---
def obtener_categoria_vehiculo(vehiculo_str):
    if pd.isna(vehiculo_str):
        return "Otro"
    
    veh_upper = str(vehiculo_str).upper().strip()
    
    if veh_upper.startswith(('VP', 'MF')):
        return "Vehículos Particulares"
    elif veh_upper.startswith('VA'):
        return "Vehículos Administrativos"
    elif veh_upper.startswith('VH'):
        return "Vehículos Campo"
    elif veh_upper.startswith('VT'):
        return "Camiones"
    elif veh_upper.startswith(('MTO', 'CT')):
        return "Motos"
    elif veh_upper.startswith('RZR'):
        return "Razer's"
    else:
        return "Otros"


# --- FUNCIÓN PARA IDENTIFICAR EL SISTEMA MECÁNICO AFECTADO ---
def identificar_sistema_mecanico(row):
    """
    Analiza el motivo de la solicitud y las observaciones para agrupar el gasto por subsistema.
    """
    texto = f"{str(row.get('motivo_solicitud', ''))} {str(row.get('observacion', ''))}".upper()
    
    if any(k in texto for k in ['FRENO', 'BALATA', 'DISCO', 'CALIPER', 'LIQUIDO FRENO']):
        return 'Frenos'
    elif any(k in texto for k in ['MOTOR', 'ACEITE', 'FILTRO', 'AFINACI', 'BUJIA', 'FUG', 'ANTICONGELANTE', 'BOMBA AGUA']):
        return 'Motor / Afinación'
    elif any(k in texto for k in ['LLANTA', 'NEUMATICO', 'PUNCH', 'TALACHA', 'VALVULA', 'ROTA']):
        return 'Llantas / Neumáticos'
    elif any(k in texto for k in ['SUSPENS', 'AMORTIGUAD', 'BUJE', 'DIRECC', 'ALIGN', 'BALANCEO', 'HORQUILLA', 'TERMINAL']):
        return 'Suspensión / Dirección'
    elif any(k in texto for k in ['ELECTR', 'BATERI', 'MARCHA', 'FARO', 'FOCO', 'FUSIBLE', 'ALTENADOR', 'CALAVERA']):
        return 'Sistema Eléctrico'
    elif any(k in texto for k in ['CLIMA', 'AIRE', 'COMPRESOR', 'GAS', 'AC']):
        return 'Aire Acondicionado'
    elif row.get('categoria_gasto') == 'Accesorio':
        return 'Accesorios / Equipamiento'
    else:
        return 'Otros / Mantenimiento Vario'


# --- FUNCIÓN PARA GENERAR EL HTML DE LAS CARDS ---
def create_card(icon_class, title, value, color="#2F9946"):
    return f"""
    <div class="metric-card" style="--card-color: {color};">
        <div class="metric-icon">
            <i class="fa-solid {icon_class}"></i>
        </div>
        <div class="metric-content">
            <div class="metric-title">{title}</div>
            <div class="metric-value">{value}</div>
        </div>
    </div>
    """

# --- 2. CARGA DE DATOS / CONEXION SQL ---
@st.cache_data(ttl=600)
def carga_datos_vehiculos():
    dict_veh = {}
    server = st.secrets["DB_SERVER"]
    user = st.secrets["DB_USER"]
    password = st.secrets["DB_PASSWORD"]
    database = st.secrets["DB_NAME"]

    try:
        conn = pymssql.connect(server, user, password, database)

        # 1. SERVICIOS
        query_serv = """
        SELECT 
            s.id_servicio,
            s.folio_registro,
            s.hora_registro,
            s.fecha_registro,
            (v.no_economico + ' ' + v.vehiculo) As Vehiculo,
            s.tipo As Tipo_Servicio,
            s.km,
            s.fecha_entrega,
            s.observacion,
            (e.nombre + ' ' + e.apellido_paterno + ' ' + e.apellido_materno) As Usuario,
            s.Estatus,
            s.Motivo_Solicitud,
            os.Nombre_Externo As Proveedor,
            os.CostoFinalServicio As Costo
        FROM SERVICIO s
        INNER JOIN VEHICULO v ON s.id_vehiculo = v.id_vehiculo
        INNER JOIN USUARIO u ON s.id_usuario = u.id_usuario
        INNER JOIN EMPLEADO e ON u.id_empleado = e.id_empleado
        LEFT JOIN Orden_Servicio os ON os.id_servicio = s.id_servicio
        """
        df_serv = pd.read_sql(query_serv, conn)
        df_serv.columns = [col.lower().strip() for col in df_serv.columns]
        df_serv['categoria_gasto'] = 'Servicio'
        df_serv['costo'] = pd.to_numeric(df_serv['costo'], errors='coerce').fillna(0)
        df_serv['km'] = pd.to_numeric(df_serv['km'], errors='coerce').fillna(0)

        # 2. ACCESORIOS
        query_acc = """
        SELECT 
            a.id_accesorio,
            a.folio_registro,
            a.hora_registro,
            a.fecha_registro,
            (v.no_economico + ' ' + v.vehiculo) As Vehiculo,
            a.accesorio,
            a.motivo As Motivo_Solicitud,
            a.observacion,
            (e.nombre + ' ' + e.apellido_paterno + ' ' + e.apellido_materno) As Usuario,
            a.Estatus,
            oa.Nombre_Externo As Proveedor,
            oa.CostoFinalAccesorio As Costo
        FROM ACCESORIO a
        INNER JOIN VEHICULO v ON a.id_vehiculo = v.id_vehiculo
        INNER JOIN USUARIO u ON a.id_usuario = u.id_usuario
        INNER JOIN EMPLEADO e ON u.id_empleado = e.id_empleado
        LEFT JOIN Orden_Accesorio oa ON oa.id_accesorio = a.id_accesorio 
        """
        df_acc = pd.read_sql(query_acc, conn)
        df_acc.columns = [col.lower().strip() for col in df_acc.columns]
        df_acc['categoria_gasto'] = 'Accesorio'
        df_acc['tipo_servicio'] = 'Compra Accesorio'
        df_acc['costo'] = pd.to_numeric(df_acc['costo'], errors='coerce').fillna(0)
        df_acc['km'] = 0

        # UNIFICACIÓN DE SERVICIOS Y ACCESORIOS
        df_total = pd.concat([df_serv, df_acc], ignore_index=True)
        df_total['fecha_registro'] = pd.to_datetime(df_total['fecha_registro'], format='mixed', errors='coerce')
        df_total = df_total.dropna(subset=['fecha_registro'])

        df_total['proveedor'] = df_total['proveedor'].fillna('No Especificado').astype(str).str.strip()
        df_total['tipo_servicio'] = df_total['tipo_servicio'].fillna('Otro').astype(str).str.strip()
        df_total['año'] = df_total['fecha_registro'].dt.year
        df_total['mes_sort'] = df_total['fecha_registro'].dt.to_period('M')
        df_total['mes_nombre'] = df_total['fecha_registro'].dt.month.map(meses_espanol) + '-' + df_total['fecha_registro'].dt.strftime('%y')
        df_total['categoria_vehiculo'] = df_total['vehiculo'].apply(obtener_categoria_vehiculo)

        df_total['sistema_afectado'] = df_total.apply(identificar_sistema_mecanico, axis=1)

        # 3. CHECKLIST / REVISIONES
        query_chk = """
        SELECT 
            c.id_checklist,
            c.folio_registro,
            c.hora_registro,
            c.fecha_registro,
            (v.no_economico + ' ' + v.vehiculo) As Vehiculo,
            (e.nombre + ' ' + e.apellido_paterno + ' ' + e.apellido_materno) As Usuario,
            c.cofre, c.bateria, c.estado_motor, c.fascia_delantera, c.parabrisas,
            c.faro_derecho, c.faro_izquierdo, c.llanta_delanteraDer, c.llanta_delanteraIzq,
            c.llanta_traseraDer, c.llanta_traseraIzq, c.observacion
        FROM CHECKLIST c
        INNER JOIN VEHICULO v ON c.id_vehiculo = v.id_vehiculo
        INNER JOIN USUARIO u ON c.id_usuario = u.id_usuario
        INNER JOIN EMPLEADO e ON u.id_empleado = e.id_empleado
        """
        df_chk = pd.read_sql(query_chk, conn)
        df_chk.columns = [col.lower().strip() for col in df_chk.columns]
        df_chk['fecha_registro'] = pd.to_datetime(df_chk['fecha_registro'], format='mixed', errors='coerce')
        df_chk = df_chk.dropna(subset=['fecha_registro'])
        df_chk['año'] = df_chk['fecha_registro'].dt.year
        df_chk['mes_sort'] = df_chk['fecha_registro'].dt.to_period('M')
        df_chk['mes_nombre'] = df_chk['fecha_registro'].dt.month.map(meses_espanol) + '-' + df_chk['fecha_registro'].dt.strftime('%y')
        df_chk['categoria_vehiculo'] = df_chk['vehiculo'].apply(obtener_categoria_vehiculo)

        # Conteo de puntos con daño o revisión
        columnas_puntos = [col for col in df_chk.columns if col not in ['id_checklist', 'folio_registro', 'hora_registro', 'fecha_registro', 'vehiculo', 'usuario', 'observacion', 'año', 'mes_sort', 'mes_nombre', 'categoria_vehiculo']]
        def contar_incidencias(row):
            valores = [str(row[col]).upper().strip() for col in columnas_puntos if pd.notna(row[col])]
            return sum(1 for v in valores if v in ['DAÑADO', 'DANADO', 'REVISAR'])

        df_chk['puntos_atencion'] = df_chk.apply(contar_incidencias, axis=1)

        dict_veh["unificado"] = df_total
        dict_veh["checklists"] = df_chk

        conn.close()

    except Exception as connection_error:
        st.error(f"Error al cargar datos del módulo de vehículos: {connection_error}")
        return {}
    
    return dict_veh

dict_veh = carga_datos_vehiculos()

# --- FUNCIÓN IA GEMINI OPTIMIZADA ---
def analizar_salud_vehiculo_ia(df_vehiculo, vehiculo_nombre):
    if df_vehiculo.empty:
        return None

    df_servicios_mec = df_vehiculo[df_vehiculo['categoria_gasto'] == 'Servicio'].copy()
    if df_servicios_mec.empty:
        df_servicios_mec = df_vehiculo.copy()

    reportes = ""
    df_limpio = df_servicios_mec[['tipo_servicio', 'motivo_solicitud', 'observacion', 'costo']].tail(35)

    for idx, row in df_limpio.iterrows():
        tipo = row['tipo_servicio'] if pd.notna(row['tipo_servicio']) else "N/A"
        mtv = row['motivo_solicitud'] if pd.notna(row['motivo_solicitud']) else "Sin motivo especificado"
        obs = row['observacion'] if pd.notna(row['observacion']) and row['observacion'] != "" else "Sin observaciones adicionales"
        reportes += f"• [Tipo: {tipo}] Motivo: {mtv} | Obs Taller: {obs} | Costo: ${row['costo']:,.2f}\n"

    prompt = f"""
    Eres un Master en Mecánica Automotriz y Gestor de Flotas Industriales. 
    Analiza el historial de entradas al taller y órdenes de servicio de la unidad: '{vehiculo_nombre}'.

    HISTORIAL DE ENTRADAS AL TALLER Y REPARACIONES:
    {reportes}

    TAREA:
    Identifica las fallas mecánicas reales, síntomas, piezas reemplazadas o problemas recurrentes.

    Responde ÚNICAMENTE con un formato JSON estricto con esta estructura exacta:
    {{
        "Diagnostico_General": "Resumen técnico detallado de la salud mecánica del vehículo en 2 o 3 oraciones.",
        "Nivel_Riesgo": "BAJO / MEDIO / ALTO",
        "Recomendacion_Reemplazo": "MANTENER EN OPERACIÓN / EVALUAR SUSTITUCIÓN / SUSTITUIR A CORTO PLAZO",
        "Principales_Problemas": [
            "Descripción clara del Problema 1",
            "Descripción clara del Problema 2",
            "Descripción clara del Problema 3"
        ]
    }}
    """

    try:
        response = client.models.generate_content(model="gemini-3.1-flash-lite", contents=prompt)
        texto_limpio = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(texto_limpio)
    except Exception as e:
        st.error(f"Error en la auditoría técnica de IA: {e}")
        return None


# --- ESTILOS CSS ---
st.markdown("""
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
    span[data-baseweb="tag"] { background-color: #247A38 !important; color: #FFFFFF !important; border-radius: 6px !important; border: none !important; font-weight: 500 !important; padding: 4px 8px !important; }
    span[data-baseweb="tag"] span[role="button"] { color: #FFFFFF !important; }
    span[data-baseweb="tag"] span[role="button"]:hover { background-color: rgba(255, 255, 255, 0.2) !important; border-radius: 50% !important; }

    div[data-baseweb="select"] > div { background-color: #0E1117 !important; border: none !important; box-shadow: none !important; border-radius: 8px !important; }
    div[data-baseweb="select"]:hover > div, div[data-baseweb="select"]:focus-within > div { border: none !important; box-shadow: none !important; }

    ul[data-baseweb="menu"] { background-color: #161B22 !important; border: 1px solid #247A38 !important; }
    li[data-baseweb="option"] { color: #FFFFFF !important; }
    li[data-baseweb="option"]:hover, li[data-baseweb="option"][aria-selected="true"] { background-color: #247A38 !important; color: #FFFFFF !important; }
    div[data-baseweb="select"] svg { fill: #9CA3AF !important; }

    div[data-baseweb="checkbox"] input:checked + div { background-color: #2F9946 !important; border-color: #2F9946 !important; }
    .stSidebar .stMarkdown h1, .stSidebar .stMarkdown h2, .stSidebar .stMarkdown h3 { color: #2F9946 !important; }

    div[data-testid="stTabs"] { margin-top: 10px !important; }
    button[data-baseweb="tab"] { background-color: transparent !important; border: none !important; padding: 8px 16px !important; }
    button[data-baseweb="tab"] p { font-size: 18px !important; font-weight: 600 !important; color: #D1D5DB !important; transition: color 0.2s ease-in-out !important; }
    button[data-baseweb="tab"]:hover p { color: #2F9946 !important; }
    button[data-baseweb="tab"][aria-selected="true"] p { color: #2F9946 !important; font-weight: bold !important; }
    div[data-baseweb="tab-highlight"] { background-color: #2F9946 !important; height: 3px !important; }

    .metric-card {
        background-color: #12161A !important; border-radius: 10px !important; padding: 16px 20px !important;
        display: flex !important; align-items: center !important; gap: 18px !important;
        border-left: 5px solid var(--card-color, #2F9946) !important; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4) !important;
        transition: all 0.3s ease-in-out !important; cursor: pointer !important; margin-bottom: 10px !important;
    }
    .metric-card:hover { transform: translateY(-4px) !important; background-color: #1A2026 !important; box-shadow: 0 8px 20px rgba(47, 153, 70, 0.35), -3px 0 12px var(--card-color, #2F9946) !important; }
    .metric-icon { font-size: 2rem !important; color: var(--card-color, #2F9946) !important; display: flex !important; align-items: center !important; justify-content: center !important; }
    .metric-content { display: flex !important; flex-direction: column !important; }
    .metric-title { color: #9CA3AF !important; font-size: 0.75rem !important; font-weight: 700 !important; text-transform: uppercase !important; }
    .metric-value { color: #FFFFFF !important; font-size: 1.5rem !important; font-weight: 800 !important; margin-top: 2px !important; }

    /* ==========================================================
       COMBO SELECTOR PRINCIPAL (GRADIENTE VERDE CON TRANSPARENCIA)
    ========================================================== */

    /* B) Fondo en Degradado Verde Transparente (Sin Bordes) */
    div[data-testid="stMainBlockContainer"] div[data-baseweb="select"] > div,
    div[data-testid="stVerticalBlock"] div[data-baseweb="select"] > div {
        background: linear-gradient(135deg, rgba(36, 80, 56, 0.35) 0%, rgba(14, 17, 23, 0.75) 100%) !important;
        border: none !important;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3) !important;
        border-radius: 10px !important;
        backdrop-filter: blur(8px) !important; /* Efecto cristal esmerilado */
        transition: all 0.3s ease-in-out !important;
    }

    /* C) Efecto Hover (El degradado se vuelve más intenso al pasar el mouse) */
    div[data-testid="stMainBlockContainer"] div[data-baseweb="select"]:hover > div,
    div[data-testid="stMainBlockContainer"] div[data-baseweb="select"]:focus-within > div {
        background: linear-gradient(135deg, rgba(47, 153, 70, 0.55) 0%, rgba(18, 22, 28, 0.85) 100%) !important;
        border: none !important;
        box-shadow: 0 6px 20px rgba(47, 153, 70, 0.25) !important;
        transform: translateY(-1px) !important;
    }

    /* Color brillante para el texto del vehículo seleccionado */
    div[data-testid="stMainBlockContainer"] div[data-baseweb="select"] div[aria-selected="true"],
    div[data-testid="stMainBlockContainer"] div[data-baseweb="select"] input {
        color: #FFFFFF !important;
        font-weight: 600 !important;
    }
</style>
""", unsafe_allow_html=True)


# --- 3. FILTROS EN SIDEBAR ---
df_veh_unificado = dict_veh.get("unificado", pd.DataFrame())

if not df_veh_unificado.empty:
    st.sidebar.markdown("### 🎯 Filtros de Datos")
    
    años_disponibles = sorted(df_veh_unificado['año'].unique(), reverse=True)
    f_año = st.sidebar.multiselect("Año:", años_disponibles, default=años_disponibles)

    meses_disponibles = df_veh_unificado[df_veh_unificado['año'].isin(f_año)]['mes_nombre'].unique().tolist()
    f_mes = st.sidebar.multiselect("Mes:", meses_disponibles, default=meses_disponibles)

    cat_disponibles = sorted(df_veh_unificado['categoria_vehiculo'].unique().tolist())
    f_cat = st.sidebar.multiselect("Categoría de Vehículo:", cat_disponibles, default=cat_disponibles)

    df_base_filtrada = df_veh_unificado[
        (df_veh_unificado['año'].isin(f_año)) &
        (df_veh_unificado['mes_nombre'].isin(f_mes)) &
        (df_veh_unificado['categoria_vehiculo'].isin(f_cat))
    ].copy()

    # SELECTOR DE VEHÍCULO
    col_sel_veh, col_info_veh = st.columns([2, 3])
    lista_vehiculos = sorted(df_base_filtrada['vehiculo'].unique().tolist())
    opciones_vehiculo = ["TODOS LOS VEHÍCULOS (VISTA GENERAL)"] + lista_vehiculos
    
    with col_sel_veh:
        vehiculo_sel = st.selectbox("🎯 Selecciona un Vehículo:", opciones_vehiculo)

    if vehiculo_sel == "TODOS LOS VEHÍCULOS (VISTA GENERAL)":
        df_veh_filtrado = df_base_filtrada.copy()
    else:
        df_veh_filtrado = df_base_filtrada[df_base_filtrada['vehiculo'] == vehiculo_sel].copy()

    # DECLARACIÓN DE LAS 3 PESTAÑAS
    #tab_ficha, tab_checklists, tab_ia = st.tabs([
    #    "🚘 Control Vehicular", 
    #    "📋 Revisiones e Inspecciones Físicas", 
    #    "🧠 Diagnóstico y Salud Vehicular (IA)"
    #])

    tab_ficha, tab_checklists = st.tabs([
        "🚘 Control Vehicular", 
        "📋 Revisiones e Inspecciones Físicas"
    ])

    # =========================================================
    # PESTAÑA 1: FICHA TÉCNICA Y CONTROL DE FLOTA
    # =========================================================
    with tab_ficha:
        if not df_veh_filtrado.empty:
            col_v1, col_v2, col_v3, col_v4 = st.columns(4)

            gasto_total = df_veh_filtrado['costo'].sum()
            gasto_servicios = df_veh_filtrado[df_veh_filtrado['categoria_gasto'] == 'Servicio']['costo'].sum()
            gasto_accesorios = df_veh_filtrado[df_veh_filtrado['categoria_gasto'] == 'Accesorio']['costo'].sum()

            # 🟢 Métrica de Sistema con Mayor Gasto
            #if gasto_total > 0:
                #top_sistema = df_veh_filtrado.groupby('sistema_afectado')['costo'].sum().idxmax()
                #top_sistema_monto = df_veh_filtrado.groupby('sistema_afectado')['costo'].sum().max()
                #pct_top_sistema = (top_sistema_monto / gasto_total * 100)
                #card_sistema_txt = f"{top_sistema} ({pct_top_sistema:.0f}%)"
            #else:
                #card_sistema_txt = "Sin Gastos"

            df_solo_serv = df_veh_filtrado[df_veh_filtrado['categoria_gasto'] == 'Servicio']
            total_servs = len(df_solo_serv)
            serv_preventivos = len(df_solo_serv[df_solo_serv['tipo_servicio'].astype(str).str.upper().str.contains('PREVENTIV', na=False)])
            serv_correctivos = len(df_solo_serv[df_solo_serv['tipo_servicio'].astype(str).str.upper().str.contains('CORRECTIV', na=False)])

            pct_prev = (serv_preventivos / total_servs * 100) if total_servs > 0 else 0.0
            pct_corr = (serv_correctivos / total_servs * 100) if total_servs > 0 else 0.0

            with col_v1:
                st.markdown(create_card("fa-sack-dollar", "Gasto Total Acumulado", f"${gasto_total:,.2f}", color="#2F9946"), unsafe_allow_html=True)
            with col_v2:
                st.markdown(create_card("fa-screwdriver-wrench", "Gasto en Servicios", f"${gasto_servicios:,.2f}", color="#4EA8DE"), unsafe_allow_html=True)
            with col_v3:
                st.markdown(create_card("fa-cart-shopping", "Gasto en Accesorios", f"${gasto_accesorios:,.2f}", color="#F4A261"), unsafe_allow_html=True)
            with col_v4:
                #st.markdown(create_card("fa-gears", "Mayor Impacto Financiero", card_sistema_txt, color="#E63946"), unsafe_allow_html=True)
                st.markdown(create_card("fa-shield-halved", "% Preventivo vs Correctivo", f"{pct_prev:.0f}% / {pct_corr:.0f}%", color="#E63946"), unsafe_allow_html=True)

            st.divider()

            # --- 📊 1. GRÁFICA PRINCIPAL A ANCHO COMPLETO: FLUJO MENSUAL (EJE DUAL) ---
            veh_hist_data = df_veh_filtrado.groupby(['mes_sort', 'mes_nombre']).agg(
                solicitudes=('categoria_gasto', 'count'), costo_total=('costo', 'sum')
            ).reset_index().sort_values('mes_sort')

            fig_veh_hist = go.Figure()
            fig_veh_hist.add_trace(go.Bar(
                x=veh_hist_data['mes_nombre'], y=veh_hist_data['solicitudes'], name="Solicitudes Atendidas",
                marker_color='#80ED99', hovertemplate="📋 Solicitudes: %{y}<extra></extra>"
            ))
            fig_veh_hist.add_trace(go.Scatter(
                x=veh_hist_data['mes_nombre'], y=veh_hist_data['costo_total'], name="Inversión Total ($)", yaxis="y2",
                mode='lines+markers', line=dict(color='#E63946', width=3), marker=dict(size=8, color='#E63946'),
                hovertemplate="💰 Inversión: $%{y:,.2f}<extra></extra>"
            ))
            fig_veh_hist.update_layout(
                title=dict(text="<b>📅 Flujo Mensual: Solicitudes Atendidas vs. Tendencia de Costos</b>", font=dict(size=16, color="white")),
                template="plotly_dark", hovermode="x unified", margin=dict(l=10, r=10, t=50, b=10),
                xaxis=dict(title="Mes"), yaxis=dict(title="Número de Solicitudes", showgrid=True, gridcolor='#222222'),
                yaxis2=dict(title="Inversión ($)", overlaying="y", side="right", tickprefix="$", showgrid=False),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )

            # Renderizamos la gráfica mensual abarcando los 2 espacios superiores
            st.plotly_chart(fig_veh_hist, use_container_width=True, config=config_plotly)
            st.write("") # Espaciado sutil

            # 2. Top 10 Proveedores
            veh_prov_data = df_veh_filtrado.groupby('proveedor')['costo'].sum().nlargest(10).reset_index().sort_values('costo')
            fig_veh_prov = go.Figure(go.Bar(
                y=veh_prov_data['proveedor'], x=veh_prov_data['costo'], orientation='h', marker_color='#2A9D8F',
                text=[f"${c:,.2f}" for c in veh_prov_data['costo']], textposition='outside', cliponaxis=False,
                hovertemplate="🏬 <b>Proveedor:</b> %{y}<br>💰 <b>Monto Facturado:</b> $%{x:,.2f}<extra></extra>"
            ))
            fig_veh_prov.update_layout(
                title=dict(text="<b>🏬 Top 10 Proveedores de Servicios y Accesorios</b>", font=dict(size=16, color="white")),
                template="plotly_dark", margin=dict(l=10, r=130, t=50, b=10),
                xaxis=dict(title="Inversión ($)", tickprefix="$", range=[0, veh_prov_data['costo'].max() * 1.35 if not veh_prov_data.empty else 1000])
            )

            # --- 🔀 ACOMODO DINÁMICO SEGÚN EL FILTRO DE VEHÍCULO ---
            col_b1, col_b2 = st.columns(2)

            if vehiculo_sel == "TODOS LOS VEHÍCULOS (VISTA GENERAL)":
                # --- CASO A: VISTA GENERAL (TODOS LOS VEHÍCULOS) ---
                
                # Top 10 Vehículos con Mayor Inversión
                veh_top_gastos = df_veh_filtrado.groupby('vehiculo').agg(
                    costo_total=('costo', 'sum'), solicitudes=('categoria_gasto', 'count')
                ).nlargest(10, 'costo_total').sort_values('costo_total')

                fig_top_veh = go.Figure(go.Bar(
                    y=veh_top_gastos.index, x=veh_top_gastos['costo_total'], orientation='h', marker_color='#E63946',
                    text=[f"${c:,.2f}" for c in veh_top_gastos['costo_total']], textposition='outside', cliponaxis=False,
                    customdata=veh_top_gastos['solicitudes'].values,
                    hovertemplate="🚘 <b>Vehículo:</b> %{y}<br>💰 <b>Inversión Total:</b> $%{x:,.2f}<br>📋 <b># Solicitudes:</b> %{customdata} registros<extra></extra>"
                ))
                fig_top_veh.update_layout(
                    title=dict(text="<b>🚘 Top 10 Vehículos con Mayor Inversión Acumulada</b>", font=dict(size=16, color="white")),
                    template="plotly_dark", margin=dict(l=10, r=130, t=50, b=10),
                    xaxis=dict(title="Inversión ($)", tickprefix="$", range=[0, veh_top_gastos['costo_total'].max() * 1.35 if not veh_top_gastos.empty else 1000])
                )

                with col_b1:
                    st.plotly_chart(fig_top_veh, use_container_width=True, config=config_plotly)
                with col_b2:
                    st.plotly_chart(fig_veh_prov, use_container_width=True, config=config_plotly)

            else:
                # --- CASO B: VEHÍCULO ESPECÍFICO ---
                
                # Gastos por Sistema Mecánico (ADAPTADA A BARRAS HORIZONTALES 📊)
                veh_sistemas = df_veh_filtrado.groupby('sistema_afectado')['costo'].sum().reset_index().sort_values('costo')

                fig_veh_sistemas_bar = go.Figure(go.Bar(
                    y=veh_sistemas['sistema_afectado'], x=veh_sistemas['costo'], orientation='h', marker_color='#F4A261',
                    text=[f"${c:,.2f}" for c in veh_sistemas['costo']], textposition='outside', cliponaxis=False,
                    hovertemplate="⚙️ <b>Sistema:</b> %{y}<br>💰 <b>Monto Invertido:</b> $%{x:,.2f}<extra></extra>"
                ))
                fig_veh_sistemas_bar.update_layout(
                    title=dict(text="<b>🛠️ Distribución del Gasto por Sistema Mecánico / Pieza</b>", font=dict(size=16, color="white")),
                    template="plotly_dark", margin=dict(l=10, r=120, t=50, b=10),
                    xaxis=dict(title="Inversión ($)", tickprefix="$", range=[0, veh_sistemas['costo'].max() * 1.35 if not veh_sistemas.empty else 1000])
                )

                with col_b1:
                    st.plotly_chart(fig_veh_prov, use_container_width=True, config=config_plotly)
                with col_b2:
                    st.plotly_chart(fig_veh_sistemas_bar, use_container_width=True, config=config_plotly)

        else:
            st.warning("⚠️ No se encontraron registros de servicios o accesorios para los filtros seleccionados.")

    # =========================================================
    # PESTAÑA 2: REVISIONES E INSPECCIONES FÍSICAS (CHECKLIST)
    # =========================================================
    with tab_checklists:
        df_chk_raw = dict_veh.get("checklists", pd.DataFrame())

        if not df_chk_raw.empty:
            df_chk_filt = df_chk_raw[
                (df_chk_raw['año'].isin(f_año)) &
                (df_chk_raw['mes_nombre'].isin(f_mes)) &
                (df_chk_raw['categoria_vehiculo'].isin(f_cat))
            ].copy()

            if vehiculo_sel != "TODOS LOS VEHÍCULOS (VISTA GENERAL)":
                df_chk_filt = df_chk_filt[df_chk_filt['vehiculo'] == vehiculo_sel].copy()

            col_r1, col_r2, col_r3, col_r4 = st.columns(4)

            total_revisiones = len(df_chk_filt)
            vehiculos_totales_categoria = set(df_base_filtrada['vehiculo'].unique())
            vehiculos_con_revision = set(df_chk_filt['vehiculo'].unique())
            vehiculos_sin_revision = list(vehiculos_totales_categoria - vehiculos_con_revision)
            cant_sin_revision = len(vehiculos_sin_revision)
            ultima_fecha_str = df_chk_filt['fecha_registro'].max().strftime('%d/%m/%Y') if not df_chk_filt.empty else "Sin Registro"
            total_danos = df_chk_filt['puntos_atencion'].sum() if not df_chk_filt.empty else 0

            with col_r1:
                st.markdown(create_card("fa-clipboard-check", "Revisiones Realizadas", f"{total_revisiones} Inspecciones", color="#2A9D8F"), unsafe_allow_html=True)
            with col_r2:
                st.markdown(create_card("fa-triangle-exclamation", "Unidades Sin Revisión", f"{cant_sin_revision} Vehículos", color="#E63946" if cant_sin_revision > 0 else "#2F9946"), unsafe_allow_html=True)
            with col_r3:
                st.markdown(create_card("fa-calendar-day", "Última Inspección", ultima_fecha_str, color="#4EA8DE"), unsafe_allow_html=True)
            with col_r4:
                st.markdown(create_card("fa-car-burst", "Puntos a Reparar / Dañados", f"{total_danos} Anomalías", color="#F4A261"), unsafe_allow_html=True)

            st.divider()

            col_tabla_chk, col_alerta_sin = st.columns([2, 1])
            with col_tabla_chk:
                st.markdown("##### 🔍 Resumen de Revisiones por Vehículo")
                if not df_chk_filt.empty:
                    resumen_chk = df_chk_filt.groupby('vehiculo').agg(
                        Revisiones=('id_checklist', 'count'),
                        Ultima_Revision=('fecha_registro', 'max'),
                        Detecciones_Danado=('puntos_atencion', 'sum')
                    ).reset_index().sort_values('Revisiones', ascending=False)
                    resumen_chk['Ultima_Revision'] = resumen_chk['Ultima_Revision'].dt.strftime('%d/%m/%Y')

                    st.dataframe(
                        resumen_chk,
                        column_config={
                            "vehiculo": "Vehículo",
                            "Revisiones": st.column_config.NumberColumn("# Revisiones", format="%d 📋"),
                            "Ultima_Revision": "Última Fecha",
                            "Detecciones_Danado": st.column_config.NumberColumn("Puntos Dañados/Revisar", format="%d ⚠️")
                        },
                        use_container_width=True, hide_index=True, height=280
                    )
                else:
                    st.info("No hay revisiones en el periodo seleccionado.")

            with col_alerta_sin:
                st.markdown("##### 🚨 Vehículos Pendientes de Inspección")
                if vehiculos_sin_revision:
                    df_sin_rev = pd.DataFrame({'Vehículos Sin Inspeccionar': vehiculos_sin_revision})
                    st.dataframe(df_sin_rev, use_container_width=True, hide_index=True, height=280)
                else:
                    st.success("🎉 ¡Todos los vehículos filtrados cuentan con al menos una revisión registrada!")
        else:
            st.warning("⚠️ No se encontraron registros de checklists en la base de datos.")

    # =========================================================
    # PESTAÑA 3: DIAGNÓSTICO Y SALUD VEHICULAR (IA)
    # =========================================================
    #with tab_ia:
    #    st.markdown("### 🧠 Auditoría Mecánica de Flota asistida por Gemini IA")
    #    col_btn_ia_v, col_info_ia_v = st.columns([1, 3])
    #    with col_btn_ia_v:
    #        btn_audit_veh = st.button("🚀 Auditar Vehículo con Gemini", use_container_width=True, key="btn_ia_vehiculo")
    #    with col_info_ia_v:
    #        st.info("Gemini evalúa los motivos de mantenimientos correctivos y costos acumulados para sugerir si la unidad requiere reemplazo.")

    #    if btn_audit_veh:
    #        with st.spinner("Analizando expediente técnico con Gemini..."):
    #            res_ia_v = analizar_salud_vehiculo_ia(df_veh_filtrado, vehiculo_sel)
    #            if res_ia_v:
    #                st.session_state['res_ia_vehiculo'] = res_ia_v

    #    if 'res_ia_vehiculo' in st.session_state:
    #        diag = st.session_state['res_ia_vehiculo']
    #        st.divider()
            
    #        c_d1, c_d2, c_d3 = st.columns([2, 1, 1])
    #        with c_d1:
    #            st.info(f"**🔍 Diagnóstico Técnico:** {diag.get('Diagnostico_General')}")
    #        with c_d2:
    #            nivel_r = diag.get('Nivel_Riesgo', 'MEDIO')
    #            color_r = "🔴" if nivel_r == "ALTO" else ("🟡" if nivel_r == "MEDIO" else "🟢")
    #            st.metric("Nivel de Riesgo Operativo", f"{color_r} {nivel_r}")
    #        with c_d3:
    #            st.metric("Dictamen de Unidad", diag.get('Recomendacion_Reemplazo', 'N/D'))

    #        st.markdown("##### 🛠️ Principales Fallas y Motivos de Entrada al Taller:")
    #        for prob in diag.get('Principales_Problemas', []):
    #            st.markdown(f"• 🔧 **{prob}**")

else:
    st.warning("⚠️ No se pudieron cargar los datos de vehículos desde la base de datos.")
