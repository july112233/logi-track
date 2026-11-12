from pathlib import Path
from datetime import datetime
from fractions import Fraction
from io import BytesIO
from os import fsync
from sys import float_info
from tempfile import NamedTemporaryFile
from threading import Lock
import json

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)

# ============================================================
# LOGI-TRACK | Sistema de analisis de tiempos de pedidos
# Proyecto ABP - Algoritmo y Programacion
# ============================================================

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "pedidos.json"

ETAPAS = ["Picking", "Packing", "Despacho"]


# ----------------------- ALMACENAMIENTO -----------------------

def cargar_pedidos():
    """Lee y valida el historial. Solo un archivo inexistente equivale a cero pedidos."""
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except FileNotFoundError:
        return []

    if not isinstance(datos, list):
        raise ValueError("El historial debe contener una lista de pedidos.")

    for numero, pedido in enumerate(datos, start=1):
        if not isinstance(pedido, dict):
            raise ValueError(f"El registro {numero} debe ser un diccionario.")
        codigo = pedido.get("codigo")
        if type(codigo) is not int or codigo < 1:
            raise ValueError(f"El registro {numero} tiene un codigo invalido.")
        if not isinstance(pedido.get("fecha", ""), str):
            raise ValueError(f"El registro {numero} tiene una fecha invalida.")

        try:
            resultado = calcular_resultado_pedido(
                pedido.get("picking"), pedido.get("packing"),
                pedido.get("despacho"), pedido.get("objetivo")
            )
        except ValueError as error:
            raise ValueError(f"Registro {numero}: {error}") from error

        # Corrige los resultados antiguos en memoria, sin escribir al consultar.
        pedido.update(resultado)

    return datos


def guardar_pedidos(pedidos):
    """Reemplaza el historial solo cuando el archivo nuevo esta completo."""
    DATA_DIR.mkdir(exist_ok=True)
    ruta_temporal = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=DATA_DIR,
            prefix=".pedidos-", suffix=".tmp", delete=False
        ) as archivo:
            ruta_temporal = Path(archivo.name)
            json.dump(pedidos, archivo, ensure_ascii=False, indent=4, allow_nan=False)
            archivo.flush()
            fsync(archivo.fileno())

        ruta_temporal.replace(DATA_FILE)
        ruta_temporal = None
    finally:
        if ruta_temporal is not None:
            try:
                ruta_temporal.unlink(missing_ok=True)
            except OSError:
                # Conserva el error de guardado si tampoco se puede limpiar el temporal.
                pass


@st.cache_resource(show_spinner=False)
def bloqueo_pedidos():
    """Comparte el mismo bloqueo entre las sesiones de Streamlit."""
    return Lock()


# ----------------------- LOGICA DEL PROGRAMA -----------------------

def calcular_tiempo_total(picking, packing, despacho):
    # El texto conserva el valor decimal antes de la suma exacta.
    tiempos = [Fraction(str(tiempo)) for tiempo in (picking, packing, despacho)]
    return sum(tiempos)


def determinar_estado(tiempo_total, tiempo_objetivo):
    if Fraction(str(tiempo_total)) > Fraction(str(tiempo_objetivo)):
        return "RETRASADO"
    return "A TIEMPO"


def determinar_etapa_mayor(picking, packing, despacho):
    if picking >= packing and picking >= despacho:
        return "Picking"
    elif packing >= despacho:
        return "Packing"
    return "Despacho"


def calcular_resultado_pedido(picking, packing, despacho, objetivo):
    tiempos = (picking, packing, despacho, objetivo)
    if not all(
        type(tiempo) in (int, float) and 0 <= tiempo <= float_info.max
        for tiempo in tiempos
    ):
        raise ValueError("Los tiempos deben ser numeros finitos y no negativos.")
    if objetivo <= 0:
        raise ValueError("El tiempo objetivo debe ser mayor que cero.")

    total = calcular_tiempo_total(picking, packing, despacho)
    if total > float_info.max:
        raise ValueError("El tiempo total excede el rango que se puede guardar.")
    estado = determinar_estado(total, objetivo)

    return {
        "total": float(total),
        "estado": estado,
        "etapa_mayor": determinar_etapa_mayor(picking, packing, despacho)
    }


def crear_pedido(codigo, picking, packing, despacho, objetivo):
    """Construye el diccionario con los datos calculados del pedido."""
    return {
        "codigo": int(codigo),
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "picking": float(picking),
        "packing": float(packing),
        "despacho": float(despacho),
        "objetivo": float(objetivo),
        **calcular_resultado_pedido(picking, packing, despacho, objetivo)
    }


def calcular_indicadores(pedidos):
    """Calcula los indicadores generales a partir de la lista de pedidos."""
    if not pedidos:
        return None

    cantidad = len(pedidos)
    a_tiempo = 0
    retrasados = 0

    for pedido in pedidos:
        if pedido["estado"] == "A TIEMPO":
            a_tiempo += 1
        else:
            retrasados += 1

    promedios = {}
    for etapa in ETAPAS:
        suma_etapa = 0
        for pedido in pedidos:
            suma_etapa += Fraction(str(pedido[etapa.lower()]))
        promedios[etapa] = suma_etapa / cantidad

    etapa_mayor_promedio = max(promedios, key=promedios.get)
    # Con los mismos pedidos en cada etapa, los promedios se pueden sumar.
    promedio_total = sum(promedios.values())

    frecuencias = {}
    for etapa in ETAPAS:
        frecuencias[etapa] = 0

    for pedido in pedidos:
        frecuencias[pedido["etapa_mayor"]] += 1

    mayor_frecuencia = max(frecuencias.values())
    etapas_mas_frecuentes = [
        etapa for etapa, valor in frecuencias.items()
        if valor == mayor_frecuencia
    ]

    return {
        "cantidad": cantidad,
        "a_tiempo": a_tiempo,
        "retrasados": retrasados,
        "promedio_total": float(promedio_total),
        "porcentaje_retrasos": retrasados / cantidad * 100,
        "promedios_etapas": {
            etapa: float(promedio) for etapa, promedio in promedios.items()
        },
        "etapa_mayor_promedio": etapa_mayor_promedio,
        "frecuencias_etapas": frecuencias,
        "etapas_mas_frecuentes": etapas_mas_frecuentes
    }


def crear_dataframe(pedidos):
    columnas = [
        "codigo", "fecha", "picking", "packing", "despacho",
        "objetivo", "total", "estado", "etapa_mayor"
    ]
    return pd.DataFrame(pedidos, columns=columnas)


def crear_excel(pedidos, indicadores):
    buffer = BytesIO()
    df = crear_dataframe(pedidos)

    resumen = pd.DataFrame([
        ["Pedidos analizados", indicadores["cantidad"]],
        ["Pedidos a tiempo", indicadores["a_tiempo"]],
        ["Pedidos retrasados", indicadores["retrasados"]],
        ["Tiempo promedio total (min)", round(indicadores["promedio_total"], 2)],
        ["Porcentaje de retrasos (%)", round(indicadores["porcentaje_retrasos"], 2)],
        ["Etapa con mayor promedio", indicadores["etapa_mayor_promedio"]]
    ], columns=["Indicador", "Resultado"])

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Pedidos")
        resumen.to_excel(writer, index=False, sheet_name="Resumen")

    buffer.seek(0)
    return buffer.getvalue()


def crear_pdf(pedidos, indicadores):
    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm
    )

    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle(
        "TituloLogi",
        parent=estilos["Title"],
        textColor=colors.HexColor("#5631A8"),
        fontSize=22,
        spaceAfter=5
    )
    subtitulo = ParagraphStyle(
        "SubtituloLogi",
        parent=estilos["Normal"],
        textColor=colors.HexColor("#64748B"),
        fontSize=9,
        spaceAfter=12
    )

    elementos = [
        Paragraph("LOGI-TRACK", titulo),
        Paragraph(
            "Reporte de analisis de tiempos y rendimiento logistico",
            subtitulo
        ),
        Paragraph(
            f"<b>Pedidos analizados:</b> {indicadores['cantidad']} "
            f"&nbsp;&nbsp; <b>A tiempo:</b> {indicadores['a_tiempo']} "
            f"&nbsp;&nbsp; <b>Retrasados:</b> {indicadores['retrasados']}",
            estilos["Normal"]
        ),
        Spacer(1, 8),
        Paragraph(
            f"<b>Tiempo promedio:</b> {indicadores['promedio_total']:.2f} min "
            f"&nbsp;&nbsp; <b>Porcentaje de retrasos:</b> "
            f"{indicadores['porcentaje_retrasos']:.2f}%",
            estilos["Normal"]
        ),
        Spacer(1, 12),
        Paragraph("Detalle de pedidos", estilos["Heading2"])
    ]

    encabezados = [
        "Codigo", "Fecha", "Picking", "Packing", "Despacho",
        "Objetivo", "Total", "Estado", "Etapa mayor"
    ]
    filas = [encabezados]
    estilo_codigo = ParagraphStyle(
        "CodigoPedido", fontName="Helvetica", fontSize=8, leading=10,
        splitLongWords=1
    )

    for pedido in pedidos:
        filas.append([
            Paragraph(str(pedido["codigo"]), estilo_codigo),
            str(pedido.get("fecha", "")),
            f"{pedido['picking']:.2f}",
            f"{pedido['packing']:.2f}",
            f"{pedido['despacho']:.2f}",
            f"{pedido['objetivo']:.2f}",
            f"{pedido['total']:.2f}",
            pedido["estado"],
            pedido["etapa_mayor"]
        ])

    tabla = Table(
        filas,
        repeatRows=1,
        splitInRow=1,
        colWidths=[32*mm, 30*mm, 18*mm, 18*mm, 20*mm,
                   18*mm, 18*mm, 27*mm, 25*mm]
    )
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#5631A8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D8D3E8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F4F1FA")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6)
    ]))
    elementos.append(tabla)

    elementos.extend([
        Spacer(1, 14),
        Paragraph("Analisis por etapas", estilos["Heading2"])
    ])

    etapa_data = [["Etapa", "Tiempo promedio (min)", "Veces como etapa de mayor duracion"]]
    for etapa in ETAPAS:
        etapa_data.append([
            etapa,
            f"{indicadores['promedios_etapas'][etapa]:.2f}",
            str(indicadores["frecuencias_etapas"][etapa])
        ])

    tabla_etapas = Table(etapa_data, colWidths=[55*mm, 65*mm, 80*mm])
    tabla_etapas.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9E2F7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#35205F")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D8D3E8")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("PADDING", (0, 0), (-1, -1), 6)
    ]))
    elementos.append(tabla_etapas)

    documento.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()


# ----------------------- DISENO DE LA INTERFAZ -----------------------

st.set_page_config(
    page_title="LOGI-TRACK | Gestión logística",
    page_icon=":material/inventory_2:",
    layout="wide",
    initial_sidebar_state="auto"
)

st.markdown("""
<style>
:root {
    --lt-background: #F4F7FB;
    --lt-navy: #14213D;
    --lt-blue: #3157D5;
    --lt-blue-dark: #2544AC;
    --lt-teal: #14B8A6;
    --lt-ink: #182235;
    --lt-muted: #53637B;
    --lt-white: #FFFFFF;
    --lt-line: #DEE6F1;
    --lt-shadow: 0 2px 5px rgba(20, 33, 61, .035), 0 12px 28px rgba(20, 33, 61, .045);
    --lt-font: Inter, "Segoe UI", system-ui, sans-serif;
}

.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background: var(--lt-background);
    color: var(--lt-ink);
    color-scheme: light;
    font-family: var(--lt-font);
}

.stApp :is(h1, h2, h3, h4, p, button, input, label) {
    font-family: var(--lt-font);
}

[data-testid="stMainBlockContainer"] {
    max-width: 94rem;
    padding: 4.5rem clamp(1rem, 3.15vw, 3.5rem) 2.5rem;
}

[data-testid="stAppHeader"],
[data-testid="stHeader"] {
    background: rgba(244, 247, 251, .95);
}

[data-testid="stAppHeader"] button,
[data-testid="stHeader"] button,
[data-testid="stExpandSidebarButton"] {
    color: var(--lt-navy);
}

[data-testid="stMain"] [data-testid="stMarkdownContainer"] {
    color: var(--lt-ink);
}

[data-testid="stMain"] [data-testid="stCaptionContainer"] {
    color: var(--lt-muted);
}

[data-testid="stMain"] [data-testid="stWidgetLabel"] p {
    color: var(--lt-ink);
    font-weight: 650;
    font-size: .89rem;
}

.ui-icon {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    font-family: "Material Symbols Rounded", sans-serif;
    font-feature-settings: "liga";
    font-weight: normal;
    font-style: normal;
    font-size: 1.35rem;
    line-height: 1;
    letter-spacing: normal;
    text-transform: none;
    white-space: nowrap;
    overflow-wrap: normal;
    word-break: normal;
    direction: ltr;
    -webkit-font-smoothing: antialiased;
}

/* Barra lateral y navegación */
[data-testid="stSidebar"] {
    background: linear-gradient(168deg, #14213D 36%, #1A2C50 100%);
    border-right: 1px solid #243656;
    color: #F5F8FF;
}

[data-testid="stSidebarUserContent"] {
    padding-inline: 1rem;
}

[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button {
    color: #CFDBF0;
}

[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button:hover {
    color: var(--lt-white);
    background: rgba(255, 255, 255, .09);
}

.sidebar-brand {
    display: flex;
    align-items: center;
    gap: .8rem;
    margin: -.15rem 0 .9rem;
    color: #F7F9FF;
}

.sidebar-brand-icon {
    display: grid;
    flex: 0 0 2.75rem;
    place-items: center;
    width: 2.75rem;
    height: 2.75rem;
    border: 1px solid #5978E2;
    border-radius: .9rem;
    background: linear-gradient(145deg, #4269E2, #3157D5);
    box-shadow: 0 6px 16px rgba(7, 16, 43, .3);
    color: var(--lt-white);
}

.sidebar-brand-icon .ui-icon {
    font-size: 1.4rem;
}

.sidebar-brand-copy {
    display: grid;
    min-width: 0;
    gap: .15rem;
}

.sidebar-brand-copy :is(strong, h2, h3) {
    margin: 0;
    padding: 0;
    color: #F7F9FF;
    font-size: 1.16rem;
    font-weight: 760;
    letter-spacing: .025em;
    line-height: 1.14;
}

.sidebar-brand-copy :is(span, small, p) {
    margin: 0;
    color: #C7D4EC;
    font-size: .74rem;
    line-height: 1.4;
}

.sidebar-section {
    margin: .2rem 0 -.25rem;
    padding: 0 .6rem;
    color: #ADBEDC;
    font-size: .69rem;
    font-weight: 720;
    letter-spacing: .09em;
    text-transform: uppercase;
}

[data-testid="stSidebar"] :is([data-testid="stRadioGroup"], [role="radiogroup"]) {
    gap: .32rem;
}

[data-testid="stSidebar"] :is([data-testid="stRadioOption"], [data-baseweb="radio"]) {
    box-sizing: border-box;
    display: flex;
    align-items: center;
    width: 100%;
    min-height: 2.72rem;
    margin: 0;
    padding: .54rem .64rem;
    border: 1px solid transparent;
    border-radius: .66rem;
    color: #D4DFF3;
    cursor: pointer;
}

[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:first-child:not([data-testid="stMarkdownContainer"]) {
    display: none;
}

[data-testid="stSidebar"] :is([data-testid="stRadioOption"], [data-baseweb="radio"]) :is(p, [data-testid="stMarkdownContainer"]) {
    margin: 0;
    color: inherit;
    font-size: .87rem;
    font-weight: 625;
}

[data-testid="stSidebar"] :is([data-testid="stRadioOption"], [data-baseweb="radio"]):hover {
    background: rgba(255, 255, 255, .075);
    color: #FFFFFF;
}

[data-testid="stSidebar"] :is([data-testid="stRadioOption"], [data-baseweb="radio"]):is([data-selected], :has(input:checked)) {
    background: #284681;
    border-color: #4666AB;
    box-shadow: inset 3px 0 var(--lt-teal);
    color: #FFFFFF;
}

[data-testid="stSidebar"] :is([data-testid="stRadioOption"], [data-baseweb="radio"]):is([data-focus-visible], :has(input:focus-visible)) {
    outline: 2px solid #65DFD2;
    outline-offset: 2px;
}

.sidebar-project {
    padding: .95rem .8rem .2rem;
    border-top: 1px solid rgba(203, 218, 246, .20);
    color: #C5D2EA;
    font-size: .8rem;
}

.sidebar-project :is(strong, h3) {
    margin: 0;
    padding: 0;
    color: #EDF3FF;
    font-size: .84rem;
    font-weight: 700;
}

.sidebar-project :is(span, small, p) {
    margin: .28rem 0 0;
    color: #BCCCE8;
    font-size: .75rem;
    line-height: 1.48;
}

[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
    padding-inline: .8rem;
    color: #C5D2EA;
    font-size: .75rem;
}

[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
    color: inherit;
}

/* Encabezados y tarjetas */
.page-heading {
    isolation: isolate;
    display: flex;
    align-items: center;
    position: relative;
    min-height: 8.3rem;
    gap: clamp(.95rem, 2.2vw, 1.7rem);
    padding: clamp(1.15rem, 2.8vw, 2rem);
    overflow: hidden;
    border: 1px solid #DBE5F5;
    border-radius: 1rem;
    background: linear-gradient(108deg, #FFFFFF 48%, #EFF4FF 100%);
    box-shadow: var(--lt-shadow);
    color: var(--lt-ink);
}

.page-heading::after {
    content: "";
    position: absolute;
    z-index: -1;
    right: -3rem;
    top: 50%;
    width: min(30vw, 25rem);
    aspect-ratio: 1;
    transform: translateY(-50%);
    border-radius: 50%;
    background: repeating-radial-gradient(circle, transparent 0 20px, rgba(49, 87, 213, .10) 21px 22px);
    mask-image: linear-gradient(90deg, transparent 5%, #000 65%);
    pointer-events: none;
}

.page-heading__icon {
    display: grid;
    flex: 0 0 auto;
    place-items: center;
    width: clamp(2.7rem, 5.2vw, 3.65rem);
    aspect-ratio: 1;
    border: 1px solid #DCE6FC;
    border-radius: .95rem;
    background: #EAF0FF;
    color: #2A4CBE;
}

.page-heading__icon .ui-icon {
    font-size: clamp(1.35rem, 2.7vw, 1.9rem);
}

.page-heading__copy {
    max-width: 47rem;
    min-width: 0;
}

.page-heading__copy :is(h1, h2) {
    margin: 0;
    padding: 0;
    color: inherit;
    font-size: clamp(1.65rem, 3.25vw, 2.5rem);
    font-weight: 760;
    line-height: 1.13;
    letter-spacing: -.042em;
}

.page-heading__copy p {
    margin: .45rem 0 0;
    color: var(--lt-muted);
    font-size: clamp(.85rem, 1.3vw, 1rem);
    line-height: 1.48;
}

.page-heading--dashboard {
    min-height: 9.25rem;
    border-color: #203761;
    background: linear-gradient(118deg, #14213D 12%, #20395F 100%);
    color: #F7FAFF;
}

.page-heading--dashboard::after {
    background: repeating-radial-gradient(circle, transparent 0 20px, rgba(79, 189, 202, .21) 21px 22px);
}

.page-heading--dashboard .page-heading__icon {
    border-color: #4969AA;
    background: #29477C;
    color: #E4EEFF;
}

.page-heading--dashboard .page-heading__copy p {
    color: #D0DDF4;
}

.section-heading {
    min-width: 0;
}

.section-heading :is(h2, h3, .section-heading__title) {
    margin: 0;
    padding: 0;
    color: var(--lt-ink);
    font-size: 1.17rem;
    font-weight: 720;
    line-height: 1.3;
    letter-spacing: -.024em;
}

.section-heading :is(p, .section-heading__detail) {
    margin: .27rem 0 0;
    color: var(--lt-muted);
    font-size: .88rem;
    line-height: 1.48;
}

.kpi-card {
    --kpi-ink: #2A4CBE;
    --kpi-tint: #EEF2FF;
    position: relative;
    display: grid;
    align-content: center;
    min-height: 8.65rem;
    padding: .95rem 1.05rem;
    border: 1px solid var(--lt-line);
    border-radius: .9rem;
    background: var(--lt-white);
    box-shadow: var(--lt-shadow);
}

.kpi-card--success, .kpi-card--teal {
    --kpi-ink: #08786D;
    --kpi-tint: #E8F8F5;
}

.kpi-card--warning {
    --kpi-ink: #8D4F0C;
    --kpi-tint: #FFF3E4;
}

.kpi-card--danger {
    --kpi-ink: #A23645;
    --kpi-tint: #FCEEF0;
}

.kpi-icon {
    position: absolute;
    top: .88rem;
    right: .88rem;
    display: grid;
    place-items: center;
    width: 2.15rem;
    height: 2.15rem;
    border-radius: .65rem;
    background: var(--kpi-tint);
    color: var(--kpi-ink);
}

.kpi-icon .ui-icon {
    font-size: 1.2rem;
}

.kpi-label {
    max-width: calc(100% - 2.1rem);
    min-height: 1.3rem;
    color: #52627A;
    font-size: .83rem;
    font-weight: 675;
    line-height: 1.32;
}

.kpi-value {
    margin: .24rem 0 .22rem;
    color: var(--lt-ink);
    font-size: clamp(1.65rem, 2.95vw, 2.3rem);
    font-weight: 750;
    font-variant-numeric: tabular-nums;
    line-height: 1.06;
    letter-spacing: -.05em;
    overflow-wrap: anywhere;
}

.kpi-note {
    color: var(--lt-muted);
    font-size: .74rem;
    line-height: 1.34;
}

.st-key-chart_states,
.st-key-chart_stages,
.st-key-dashboard_empty,
.st-key-history_filters,
.st-key-history_table,
.st-key-stage_summary,
.st-key-analysis_promedios,
.st-key-analysis_frecuencias,
.st-key-analysis_recommendation,
.st-key-report_excel,
.st-key-report_pdf,
.st-key-report_preview,
[class*="st-key-empty_state"],
[data-testid="stForm"] {
    min-width: 0;
    padding: clamp(.85rem, 1.6vw, 1.22rem);
    border: 1px solid var(--lt-line);
    border-radius: .9rem;
    background: var(--lt-white);
    box-shadow: var(--lt-shadow);
}

.st-key-chart_states, .st-key-chart_stages {
    overflow: hidden;
}

.st-key-chart_states img, .st-key-chart_stages img {
    width: 100%;
    object-fit: contain;
}

.empty-state {
    display: flex;
    align-items: flex-start;
    gap: 1rem;
    padding: .5rem .15rem;
}

.empty-state__icon {
    display: grid;
    flex: 0 0 3.15rem;
    place-items: center;
    height: 3.15rem;
    border: 1px solid #D7E8F9;
    border-radius: .9rem;
    background: #E9F4FE;
    color: var(--lt-blue);
}

.empty-state__icon .ui-icon {
    font-size: 1.55rem;
}

.empty-state :is(h2, h3) {
    margin: 0;
    padding: 0;
    color: var(--lt-ink);
    font-size: 1.22rem;
    font-weight: 720;
    letter-spacing: -.025em;
}

.empty-state p {
    max-width: 40rem;
    margin: .4rem 0 0;
    color: var(--lt-muted);
    font-size: .91rem;
    line-height: 1.48;
}

.stage-label {
    display: flex;
    align-items: center;
    min-height: 2.5rem;
    gap: .58rem;
    margin: .15rem 0;
    padding: .57rem .65rem;
    border: 1px solid #E1E9F6;
    border-radius: .6rem;
    background: #F2F6FD;
    color: #244378;
    font-size: .88rem;
    font-weight: 700;
}

.stage-label__icon {
    display: grid;
    flex: 0 0 1.75rem;
    place-items: center;
    color: #3157D5;
}

.stage-label p {
    margin: 0;
    color: inherit;
}

.order-result {
    padding: clamp(.9rem, 2.2vw, 1.35rem);
    border: 1px solid #CFE7E4;
    border-left: 4px solid #0C8F82;
    border-radius: .85rem;
    background: #F7FCFB;
    box-shadow: var(--lt-shadow);
}

.order-result__head {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: .55rem;
    margin-bottom: .88rem;
    color: #0B6E65;
}

.order-result :is(h2, h3) {
    margin: 0;
    padding: 0;
    color: var(--lt-ink);
    font-size: 1.14rem;
    font-weight: 710;
}

.order-result__grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: .65rem;
}

.order-result__item {
    display: grid;
    align-content: start;
    justify-items: start;
    min-width: 0;
    gap: .34rem;
    padding: .72rem .8rem;
    border: 1px solid #DCEAE9;
    border-radius: .65rem;
    background: var(--lt-white);
}

.order-result__item :is(small, .order-result__label) {
    color: var(--lt-muted);
    font-size: .77rem;
    font-weight: 620;
}

.order-result__item :is(strong, .order-result__value) {
    color: var(--lt-ink);
    font-size: 1rem;
    font-variant-numeric: tabular-nums;
    overflow-wrap: anywhere;
}

.status-pill {
    display: inline-flex;
    align-items: center;
    gap: .35rem;
    padding: .23rem .55rem;
    border-radius: 999px;
    background: #EAF0FC;
    color: #244378;
    font-size: .72rem;
    font-weight: 750;
    line-height: 1.3;
    white-space: nowrap;
}

.status-pill--success {
    background: #DCF5EF;
    color: #075F56;
}

.status-pill--danger, .status-pill--warning {
    background: #FBE6E8;
    color: #8F2938;
}

.status-pill .ui-icon {
    font-size: .98rem;
}

.report-card-intro {
    display: flex;
    align-items: center;
    gap: .85rem;
    min-height: 4.35rem;
}

.report-card-icon {
    display: grid;
    flex: 0 0 3rem;
    place-items: center;
    height: 3rem;
    border-radius: .83rem;
    background: #EDF2FD;
    color: var(--lt-blue);
}

.report-card-icon .ui-icon {
    font-size: 1.55rem;
}

.report-card-icon--excel {
    background: #E5F6F2;
    color: #08786D;
}

.report-card-icon--pdf {
    background: #E9EEFF;
    color: #3157D5;
}

.report-card-copy :is(h2, h3, strong) {
    margin: 0;
    padding: 0;
    color: var(--lt-ink);
    font-size: 1.12rem;
    font-weight: 720;
    letter-spacing: -.02em;
}

.report-card-copy p {
    margin: .28rem 0 0;
    color: var(--lt-muted);
    font-size: .85rem;
    line-height: 1.48;
}

.st-key-analysis_recommendation {
    border-left: 4px solid #0C8F82;
    background: #F6FCFA;
}

/* Controles nativos, tablas y mensajes */
[data-testid="stMain"] :is([data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="select"] > div, [data-baseweb="select"] [role="combobox"]) {
    border-color: #CDD8EA;
    background: #FFFFFF;
    color: var(--lt-ink);
}

[data-testid="stMain"] :is([data-baseweb="input"], [data-baseweb="select"] > div) {
    border-radius: .62rem;
}

[data-testid="stMain"] :is([data-baseweb="input"], [data-baseweb="select"] > div):focus-within {
    border-color: var(--lt-blue);
    outline: 2px solid rgba(49, 87, 213, .26);
    outline-offset: 1px;
}

[data-testid="stMain"] :is(input, [role="combobox"]) {
    color: var(--lt-ink);
}

[data-testid="stMain"] input::placeholder {
    color: #63748B;
    opacity: 1;
}

/* Fuerza el tema claro en todos los niveles de los campos Streamlit/BaseWeb. */
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
[data-testid="stMain"] [data-testid="stNumberInput"],
[data-testid="stMain"] [data-testid="stTextInput"] {
    color-scheme: light !important;
}

[data-testid="stMain"] [data-baseweb="input"],
[data-testid="stMain"] [data-baseweb="base-input"],
[data-testid="stMain"] [data-testid="stNumberInput"] [data-baseweb="input"],
[data-testid="stMain"] [data-testid="stTextInput"] [data-baseweb="input"],
[data-testid="stMain"] [data-baseweb="input"] > div,
[data-testid="stMain"] [data-baseweb="base-input"] > input {
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    color: #182235 !important;
    border-color: #CDD8EA !important;
    color-scheme: light !important;
}

[data-testid="stMain"] [data-testid="stNumberInput"] input,
[data-testid="stMain"] [data-testid="stTextInput"] input,
[data-testid="stMain"] [data-baseweb="input"] input,
[data-testid="stMain"] input[type="number"],
[data-testid="stMain"] input[type="text"],
[data-testid="stMain"] textarea {
    appearance: none !important;
    background: #FFFFFF !important;
    background-color: #FFFFFF !important;
    color: #182235 !important;
    -webkit-text-fill-color: #182235 !important;
    caret-color: #3157D5 !important;
    color-scheme: light !important;
    opacity: 1 !important;
}

[data-testid="stMain"] input::placeholder,
[data-testid="stMain"] textarea::placeholder {
    color: #63748B !important;
    -webkit-text-fill-color: #63748B !important;
    opacity: 1 !important;
}

[data-testid="stMain"] :is([data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"]) {
    border-color: #DCE5F0;
    background: #F2F6FD;
    color: #26477D;
}

[data-testid="stMain"] :is([data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"]):hover:not(:disabled) {
    background: #E3EDFE;
    color: #2147B2;
}

[data-testid="stMain"] :is(.stButton, .stFormSubmitButton, [data-testid="stDownloadButton"]) button {
    min-height: 2.7rem;
    border: 1px solid #CAD8F4;
    border-radius: .64rem;
    background: #F0F4FF;
    color: #2446B7;
    font-size: .89rem;
    font-weight: 700;
    transition: background .16s ease, border-color .16s ease, box-shadow .16s ease;
}

[data-testid="stMain"] :is(.stButton, .stFormSubmitButton, [data-testid="stDownloadButton"]) button p {
    color: inherit;
}

[data-testid="stMain"] :is(.stButton, .stFormSubmitButton, [data-testid="stDownloadButton"]) button:hover:not(:disabled) {
    border-color: #A9BDF1;
    background: #E4EDFF;
    color: #1F3D9F;
}

[data-testid="stMain"] :is(.stFormSubmitButton button, .stButton button[kind="primary"], .stButton button[data-testid="stBaseButton-primary"], .st-key-report_pdf button) {
    border-color: var(--lt-blue);
    background: var(--lt-blue);
    color: var(--lt-white);
}

[data-testid="stMain"] :is(.stFormSubmitButton button, .stButton button[kind="primary"], .stButton button[data-testid="stBaseButton-primary"], .st-key-report_pdf button):hover:not(:disabled) {
    border-color: var(--lt-blue-dark);
    background: var(--lt-blue-dark);
    color: var(--lt-white);
}

[data-testid="stMain"] .st-key-report_excel button {
    border-color: #08776D;
    background: #08776D;
    color: var(--lt-white);
}

[data-testid="stMain"] .st-key-report_excel button:hover:not(:disabled) {
    border-color: #066157;
    background: #066157;
    color: var(--lt-white);
}

[data-testid="stMain"] :is(.stButton, .stFormSubmitButton, [data-testid="stDownloadButton"]) button:focus-visible {
    outline: 2px solid var(--lt-blue);
    outline-offset: 3px;
}

[data-testid="stMain"] [data-testid="stDataFrame"] {
    overflow: hidden;
    border: 1px solid #E1E8F2;
    border-radius: .65rem;
}

[data-testid="stMain"] [data-testid="stAlertContainer"] {
    border: 1px solid #D7E4FA;
    border-radius: .7rem;
    background: #EFF5FF;
    color: #23497C;
}

[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {
    border-color: #CBE9E0;
    background: #EAF9F4;
    color: #0A5C51;
}

[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {
    border-color: #F0DFBA;
    background: #FFF7E8;
    color: #724A12;
}

[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {
    border-color: #F2D3D8;
    background: #FEF0F2;
    color: #8C2637;
}

[data-testid="stMain"] [data-testid="stAlertContainer"] :is([data-testid="stMarkdownContainer"], p) {
    color: inherit;
}

.dashboard-footer {
    margin-top: .65rem;
    padding: .95rem 0 0;
    border-top: 1px solid #DCE5F1;
    color: var(--lt-muted);
    font-size: .77rem;
    text-align: center;
}

@media (max-width: 1140px) {
    .st-key-dashboard_kpis [data-testid="stHorizontalBlock"] {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .st-key-dashboard_kpis [data-testid="stColumn"] {
        width: 100% !important;
        min-width: 0 !important;
    }
}

@media (max-width: 930px) {
    [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(.st-key-chart_states, .st-key-chart_stages, .st-key-report_excel, .st-key-analysis_promedios) {
        flex-wrap: wrap;
    }

    [data-testid="stMain"] [data-testid="stHorizontalBlock"]:has(.st-key-chart_states, .st-key-chart_stages, .st-key-report_excel, .st-key-analysis_promedios) > [data-testid="stColumn"] {
        flex: 1 1 100%;
        width: 100% !important;
    }

    .order-result__grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 650px) {
    [data-testid="stMainBlockContainer"] {
        padding: 3.55rem .9rem 1.7rem;
    }

    [data-testid="stMain"] [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap;
    }

    [data-testid="stMain"] [data-testid="stColumn"] {
        flex: 1 1 100%;
        width: 100% !important;
        min-width: 0 !important;
    }

    .page-heading {
        min-height: 0;
        align-items: flex-start;
    }

    .page-heading::after {
        opacity: .55;
        width: 12rem;
    }

    .kpi-card {
        min-height: 7.75rem;
        padding: .76rem;
    }

    .kpi-icon {
        top: .68rem;
        right: .65rem;
        width: 1.7rem;
        height: 1.7rem;
    }

    .kpi-icon .ui-icon {
        font-size: 1rem;
    }

    .kpi-label {
        max-width: calc(100% - 1.55rem);
        font-size: .77rem;
    }

    .kpi-note {
        font-size: .71rem;
    }
}

@media (max-width: 360px) {
    .st-key-dashboard_kpis [data-testid="stHorizontalBlock"],
    .order-result__grid {
        grid-template-columns: minmax(0, 1fr);
    }
}

@media (prefers-reduced-motion: reduce) {
    [data-testid="stMain"] button {
        transition: none;
    }
}
</style>
""", unsafe_allow_html=True)


def icono(nombre):
    return f'<span class="ui-icon" aria-hidden="true">{nombre}</span>'


def encabezado(titulo, subtitulo, simbolo):
    st.markdown(
        f"""
        <div class="page-heading">
            <span class="page-heading__icon">{icono(simbolo)}</span>
            <div class="page-heading__copy">
                <h1>{titulo}</h1>
                <p>{subtitulo}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def titulo_seccion(titulo, detalle=""):
    descripcion = f'<p class="section-heading__detail">{detalle}</p>' if detalle else ""
    st.markdown(
        f'<div class="section-heading"><h2 class="section-heading__title">{titulo}</h2>'
        f'{descripcion}</div>',
        unsafe_allow_html=True
    )


def formatear_numero(valor, decimales=0):
    return f"{valor:,.{decimales}f}".translate(str.maketrans(",.", ".,"))


def tarjeta(etiqueta, valor, simbolo, nota, variante=""):
    st.markdown(
        f"""
        <div class="kpi-card {variante}">
            <div class="kpi-label">{etiqueta}</div>
            <span class="kpi-icon">{icono(simbolo)}</span>
            <div class="kpi-value">{valor}</div>
            <div class="kpi-note">{nota}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


def estado_vacio(titulo, detalle, simbolo):
    st.markdown(
        f"""
        <div class="empty-state">
            <span class="empty-state__icon">{icono(simbolo)}</span>
            <div>
                <h2>{titulo}</h2>
                <p>{detalle}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def mostrar_grafica(clave, titulo, figura, detalle=""):
    with st.container(key=clave, border=True):
        titulo_seccion(titulo, detalle)
        st.pyplot(figura, use_container_width=True)


def color_estado(estado):
    if estado == "A TIEMPO":
        return "color: #105F53; background-color: #DEF5EE;"
    if estado == "RETRASADO":
        return "color: #8B3441; background-color: #FBE8EB;"
    return ""


def mostrar_tabla_pedidos(df):
    tabla = df.style.map(color_estado, subset=["estado"]) if not df.empty else df
    st.dataframe(
        tabla,
        hide_index=True,
        use_container_width=True,
        column_config={
            "codigo": st.column_config.NumberColumn("Código", format="%d"),
            "fecha": st.column_config.TextColumn("Fecha de registro"),
            "picking": st.column_config.NumberColumn("Picking (min)", format="%.2f"),
            "packing": st.column_config.NumberColumn("Packing (min)", format="%.2f"),
            "despacho": st.column_config.NumberColumn("Despacho (min)", format="%.2f"),
            "objetivo": st.column_config.NumberColumn("Objetivo (min)", format="%.2f"),
            "total": st.column_config.NumberColumn("Total (min)", format="%.2f"),
            "estado": st.column_config.TextColumn("Estado"),
            "etapa_mayor": st.column_config.TextColumn("Etapa de mayor duración")
        }
    )


def campo_etapa(nombre, simbolo):
    st.markdown(
        f'<div class="stage-label"><span class="stage-label__icon">{icono(simbolo)}</span>'
        f'<strong>{nombre}</strong></div>',
        unsafe_allow_html=True
    )
    return st.number_input(
        f"Tiempo de {nombre.lower()} (minutos)", min_value=0.0, step=0.5, value=0.0
    )


def mostrar_resultado(nuevo_pedido):
    estado = nuevo_pedido["estado"]
    variante = "success" if estado == "A TIEMPO" else "danger"
    simbolo = "check_circle" if estado == "A TIEMPO" else "schedule"
    total = formatear_numero(nuevo_pedido["total"], 2)
    objetivo = formatear_numero(nuevo_pedido["objetivo"], 2)
    st.markdown(
        f"""
        <div class="order-result" role="status">
            <div class="order-result__head">
                <h2>Pedido {nuevo_pedido["codigo"]} registrado</h2>
                <span class="status-pill status-pill--{variante}">{icono(simbolo)}{estado}</span>
            </div>
            <div class="order-result__grid">
                <div class="order-result__item">
                    <span>Tiempo total</span><strong class="order-result__value">{total} min</strong>
                </div>
                <div class="order-result__item">
                    <span>Tiempo objetivo</span><strong class="order-result__value">{objetivo} min</strong>
                </div>
                <div class="order-result__item">
                    <span>Etapa de mayor duración</span>
                    <strong class="order-result__value">{nuevo_pedido["etapa_mayor"]}</strong>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def encabezado_reporte(titulo, detalle, simbolo, variante):
    st.markdown(
        f"""
        <div class="report-card-intro">
            <span class="report-card-icon report-card-icon--{variante}">{icono(simbolo)}</span>
            <div class="report-card-copy">
                <h2>{titulo}</h2>
                <p>{detalle}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def abrir_registro():
    st.session_state.sidebar_nav = "Registrar pedido"


def grafica_estados(indicadores):
    from matplotlib.ticker import MaxNLocator

    figura, eje = crear_lienzo_grafica("y")
    nombres = ["A tiempo", "Retrasados"]
    valores = [indicadores["a_tiempo"], indicadores["retrasados"]]
    barras = eje.bar(nombres, valores, width=0.46, color=["#14B8A6", "#C66B5E"])
    eje.set_ylabel("Pedidos", color="#53627B", labelpad=9, fontsize=10)
    eje.set_xlim(-0.55, len(nombres) - 0.45)
    eje.set_ylim(0, max(valores + [1]) * 1.28)
    eje.yaxis.set_major_locator(MaxNLocator(nbins=4, integer=True))
    eje.bar_label(
        barras, labels=[str(valor) for valor in valores], padding=6,
        color="#182235", fontsize=11, fontweight="bold"
    )
    return figura


def grafica_etapas(indicadores):
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    figura, eje = crear_lienzo_grafica("x")
    nombres = list(indicadores["promedios_etapas"].keys())
    valores = list(indicadores["promedios_etapas"].values())
    barras = eje.barh(nombres, valores, height=0.49, color=["#3157D5", "#5B78D9", "#738DDE"])
    eje.invert_yaxis()
    eje.set_xlabel("Minutos", color="#53627B", labelpad=8, fontsize=10)
    eje.set_xlim(0, (max(valores) or 1) * 1.28)
    eje.xaxis.set_major_locator(MaxNLocator(nbins=4))
    eje.xaxis.set_major_formatter(FuncFormatter(lambda valor, _: f"{valor:g}".replace(".", ",")))
    etiquetas = [
        (f"{valor:.3g}" if 0 < valor < 0.1 or valor >= 10000 else f"{valor:.1f}")
        .replace(".", ",")
        for valor in valores
    ]
    eje.bar_label(
        barras, labels=etiquetas,
        padding=6, color="#182235", fontsize=11, fontweight="bold"
    )
    return figura


# ----------------------- NAVEGACIÓN -----------------------

modulos = {
    "Panel principal": ":material/space_dashboard: Panel principal",
    "Registrar pedido": ":material/add_box: Registrar pedido",
    "Historial de pedidos": ":material/receipt_long: Historial de pedidos",
    "Analisis logistico": ":material/monitoring: Análisis logístico",
    "Reportes": ":material/description: Reportes"
}

with st.sidebar:
    st.markdown(
        f"""
        <div class="sidebar-brand">
            <span class="sidebar-brand-icon">{icono("inventory_2")}</span>
            <div class="sidebar-brand-copy">
                <strong>LOGI-TRACK</strong>
                <span>Gestión logística</span>
            </div>
        </div>
        <div class="sidebar-section">Módulos</div>
        """,
        unsafe_allow_html=True
    )
    pagina = st.radio(
        "Módulos de navegación",
        list(modulos),
        format_func=modulos.get,
        key="sidebar_nav",
        label_visibility="collapsed"
    )
    st.markdown(
        """
        <div class="sidebar-project">
            <strong>Proyecto ABP</strong>
            <span>Algoritmo y Programación</span>
            <span>Ingeniería Industrial</span>
        </div>
        """,
        unsafe_allow_html=True
    )
    contador_pedidos = st.empty()

try:
    with bloqueo_pedidos():
        pedidos = cargar_pedidos()
except (OSError, ValueError) as error:
    st.error(f"No se pudo leer el historial de pedidos. {error}")
    st.stop()

contador_pedidos.caption(f"Pedidos almacenados: {len(pedidos)}")


# ----------------------- PANEL PRINCIPAL -----------------------

if pagina == "Panel principal":
    encabezado(
        "Panel principal",
        "Consulta el cumplimiento de los pedidos y los tiempos de cada etapa logística.",
        "space_dashboard"
    )

    indicadores = calcular_indicadores(pedidos)
    resumen = indicadores or {"cantidad": 0, "a_tiempo": 0, "retrasados": 0}
    porcentaje = f'{formatear_numero(indicadores["porcentaje_retrasos"], 1)} %' if indicadores else "—"

    with st.container(key="dashboard_kpis"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            tarjeta("Pedidos registrados", formatear_numero(resumen["cantidad"]), "inventory_2", "Total en el historial")
        with c2:
            tarjeta("A tiempo", formatear_numero(resumen["a_tiempo"]), "task_alt", "Dentro del objetivo", "kpi-card--success")
        with c3:
            tarjeta("Retrasados", formatear_numero(resumen["retrasados"]), "schedule", "Superaron el objetivo", "kpi-card--danger")
        with c4:
            tarjeta("Tasa de retraso", porcentaje, "percent", "Sobre los pedidos registrados", "kpi-card--teal")

    if indicadores is None:
        with st.container(key="dashboard_empty", border=True):
            estado_vacio(
                "Aún no hay pedidos registrados",
                "Registra el primer pedido para ver el cumplimiento y los tiempos por etapa.",
                "inventory_2"
            )
            st.button("Registrar primer pedido", type="primary", on_click=abrir_registro)
    else:
        col1, col2 = st.columns(2)
        with col1:
            mostrar_grafica(
                "chart_states", "Cumplimiento de pedidos", grafica_estados(indicadores),
                "Cantidad de pedidos según su estado."
            )
        with col2:
            mostrar_grafica(
                "chart_stages", "Tiempo promedio por etapa", grafica_etapas(indicadores),
                "Minutos por pedido en picking, packing y despacho."
            )

        etapa = indicadores["etapa_mayor_promedio"]
        promedio = formatear_numero(indicadores["promedios_etapas"][etapa], 2)
        st.info(f"**{etapa}** tiene el mayor tiempo promedio: **{promedio} min**.")

        with st.container(key="recent_orders", border=True):
            titulo_seccion("Últimos pedidos", "Hasta cinco registros, del más reciente al más antiguo.")
            df = crear_dataframe(pedidos).tail(5).iloc[::-1]
            mostrar_tabla_pedidos(df)


# ----------------------- REGISTRO DE PEDIDOS -----------------------

elif pagina == "Registrar pedido":
    encabezado(
        "Registrar pedido",
        "Ingresa los tiempos para evaluar si el pedido cumplió su objetivo.",
        "add_box"
    )

    with st.form("order_form", clear_on_submit=True):
        titulo_seccion("Datos del pedido")
        col1, col2 = st.columns(2)
        with col1:
            codigo = st.number_input("Código del pedido", min_value=1, step=1, value=1)
        with col2:
            objetivo = st.number_input(
                "Tiempo objetivo (minutos)", min_value=0.1, step=0.5, value=20.0
            )

        titulo_seccion("Tiempos por etapa", "Ingresa la duración en minutos. Una etapa puede tomar cero minutos.")
        col1, col2, col3 = st.columns(3)
        with col1:
            picking = campo_etapa("Picking", "inventory_2")
        with col2:
            packing = campo_etapa("Packing", "package_2")
        with col3:
            despacho = campo_etapa("Despacho", "local_shipping")

        enviado = st.form_submit_button("Registrar y analizar pedido", type="primary")

    if enviado:
        try:
            nuevo_pedido = crear_pedido(
                codigo, picking, packing, despacho, objetivo
            )
            with bloqueo_pedidos():
                pedidos_actuales = cargar_pedidos()
                codigo_repetido = any(
                    pedido["codigo"] == nuevo_pedido["codigo"]
                    for pedido in pedidos_actuales
                )
                if not codigo_repetido:
                    pedidos_actuales.append(nuevo_pedido)
                    guardar_pedidos(pedidos_actuales)
        except (OSError, ValueError) as error:
            st.error(f"No se pudo registrar el pedido. {error}")
        else:
            if codigo_repetido:
                st.error("Ya existe un pedido con ese código. Ingresa uno diferente.")
            else:
                contador_pedidos.caption(f"Pedidos almacenados: {len(pedidos_actuales)}")
                mostrar_resultado(nuevo_pedido)


# ----------------------- HISTORIAL -----------------------

elif pagina == "Historial de pedidos":
    encabezado(
        "Historial de pedidos",
        "Busca pedidos por código, filtra por estado y exporta el resultado.",
        "receipt_long"
    )

    if not pedidos:
        with st.container(key="empty_state_history", border=True):
            estado_vacio(
                "El historial está vacío",
                "Los pedidos aparecerán aquí cuando completes el primer registro.",
                "receipt_long"
            )
    else:
        df = crear_dataframe(pedidos)

        with st.container(key="history_filters", border=True):
            titulo_seccion("Buscar y filtrar")
            col1, col2 = st.columns([2, 1])
            with col1:
                busqueda = st.text_input(
                    "Buscar por código de pedido", placeholder="Escribe todo o parte del código"
                )
            with col2:
                filtro = st.selectbox("Estado del pedido", ["Todos", "A TIEMPO", "RETRASADO"])

        if filtro != "Todos":
            df = df[df["estado"] == filtro]

        if busqueda.strip():
            coincide = df["codigo"].astype(str).str.contains(busqueda.strip(), regex=False)
            df = df[coincide]

        with st.container(key="history_table", border=True):
            detalle = f"Registros encontrados: {formatear_numero(len(df))}."
            if df.empty:
                detalle = "Ningún pedido coincide con los filtros."
            titulo_seccion("Pedidos registrados", detalle)
            mostrar_tabla_pedidos(df)
            st.download_button(
                "Descargar historial en CSV",
                data=df.to_csv(index=False).encode("utf-8-sig"),
                file_name="historial_logi_track.csv",
                mime="text/csv"
            )


# ----------------------- ANÁLISIS LOGÍSTICO -----------------------

elif pagina == "Analisis logistico":
    encabezado(
        "Análisis logístico",
        "Compara las etapas del proceso e identifica dónde se concentra el tiempo.",
        "monitoring"
    )

    indicadores = calcular_indicadores(pedidos)

    if indicadores is None:
        with st.container(key="empty_state_analysis", border=True):
            estado_vacio(
                "El análisis necesita pedidos",
                "Registra un pedido para calcular los promedios, las frecuencias y el cumplimiento.",
                "monitoring"
            )
    else:
        col1, col2 = st.columns(2)
        with col1:
            mostrar_grafica(
                "chart_stages", "Tiempo promedio por etapa", grafica_etapas(indicadores),
                "Minutos promedio de cada etapa."
            )
        with col2:
            mostrar_grafica(
                "chart_states", "Distribución de estados", grafica_estados(indicadores),
                "Pedidos dentro y fuera del tiempo objetivo."
            )

        etapa = indicadores["etapa_mayor_promedio"]
        promedio_etapa = indicadores["promedios_etapas"][etapa]
        recomendaciones = {
            "Picking": (
                "Revisa la ubicación de las autopartes, la organización del "
                "inventario y los recorridos durante la selección."
            ),
            "Packing": (
                "Revisa la disponibilidad de materiales de embalaje, la "
                "preparación de pedidos y la organización del puesto de trabajo."
            ),
            "Despacho": (
                "Revisa la programación de salidas, la organización de los "
                "pedidos terminados y la coordinación del transporte."
            )
        }

        with st.container(key="analysis_recommendation", border=True):
            titulo_seccion("Recomendación operativa")
            st.warning(
                f"**{etapa}** es la etapa con mayor tiempo promedio "
                f"(**{formatear_numero(promedio_etapa, 2)} min**)."
            )
            st.write(recomendaciones[etapa])

        with st.container(key="stage_summary"):
            col1, col2 = st.columns(2)
            with col1, st.container(key="analysis_promedios", border=True):
                titulo_seccion("Promedios por etapa")
                datos_promedio = pd.DataFrame(
                    list(indicadores["promedios_etapas"].items()),
                    columns=["Etapa", "Promedio (minutos)"]
                )
                st.dataframe(
                    datos_promedio, use_container_width=True, hide_index=True,
                    column_config={
                        "Promedio (minutos)": st.column_config.NumberColumn(format="%.2f min")
                    }
                )

            with col2, st.container(key="analysis_frecuencias", border=True):
                titulo_seccion("Frecuencia de mayor duración", "Veces que cada etapa fue la más larga de un pedido.")
                datos_frecuencia = pd.DataFrame(
                    list(indicadores["frecuencias_etapas"].items()),
                    columns=["Etapa", "Cantidad de pedidos"]
                )
                st.dataframe(
                    datos_frecuencia, use_container_width=True, hide_index=True,
                    column_config={
                        "Cantidad de pedidos": st.column_config.ProgressColumn(
                            "Pedidos", min_value=0, max_value=indicadores["cantidad"], format="%d"
                        )
                    }
                )


# ----------------------- REPORTES -----------------------

elif pagina == "Reportes":
    encabezado(
        "Reportes",
        "Descarga el detalle de los pedidos y los indicadores logísticos.",
        "description"
    )

    indicadores = calcular_indicadores(pedidos)

    if indicadores is None:
        with st.container(key="empty_state_reports", border=True):
            estado_vacio(
                "Aún no hay reportes disponibles",
                "Registra al menos un pedido para descargar los archivos Excel y PDF.",
                "description"
            )
    else:
        df = crear_dataframe(pedidos)
        col1, col2 = st.columns(2)

        with col1, st.container(key="report_excel", border=True):
            encabezado_reporte(
                "Reporte Excel", "Libro editable con las hojas Pedidos y Resumen.",
                "table_view", "excel"
            )
            excel = crear_excel(pedidos, indicadores)
            st.download_button(
                "Descargar Excel",
                data=excel,
                file_name="reporte_logi_track.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        with col2, st.container(key="report_pdf", border=True):
            encabezado_reporte(
                "Reporte PDF", "Documento con indicadores, detalle y análisis por etapas.",
                "picture_as_pdf", "pdf"
            )
            pdf = crear_pdf(pedidos, indicadores)
            st.download_button(
                "Descargar PDF",
                data=pdf,
                file_name="reporte_logi_track.pdf",
                mime="application/pdf"
            )

        with st.container(key="report_preview", border=True):
            titulo_seccion("Vista previa de pedidos", f"Pedidos incluidos: {formatear_numero(len(df))}.")
            mostrar_tabla_pedidos(df)
