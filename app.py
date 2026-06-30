from __future__ import annotations

import base64
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st


EMPRESA = "Sophi Personalizados Oficial"
DB_PATH = Path("banco") / "Sophi_erp.db"
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
DB_PATH.parent.mkdir(exist_ok=True)


def criar_icone_padrao():
    caminho = UPLOAD_DIR / "sophi_app_icon.png"
    if caminho.exists():
        return str(caminho)

    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (1024, 1024), "#000000")
        draw = ImageDraw.Draw(img)
        try:
            font_big = ImageFont.truetype("arial.ttf", 360)
            font_small = ImageFont.truetype("arial.ttf", 64)
        except Exception:
            font_big = ImageFont.load_default()
            font_small = ImageFont.load_default()
        texto = "S"
        bbox = draw.textbbox((0, 0), texto, font=font_big)
        draw.text(((1024 - (bbox[2] - bbox[0])) / 2, 245), texto, fill="#ffffff", font=font_big)
        subtitulo = "SOPHI"
        bbox2 = draw.textbbox((0, 0), subtitulo, font=font_small)
        draw.text(((1024 - (bbox2[2] - bbox2[0])) / 2, 700), subtitulo, fill="#ffffff", font=font_small)
        img.save(caminho)
        return str(caminho)
    except Exception:
        return "S"


# ============================================================
# UTILIDADES
# ============================================================

def conectar():
    return sqlite3.connect(DB_PATH)


def executar(sql, params=()):
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid


def consultar(sql, params=()):
    with conectar() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def n(valor, padrao=0.0):
    try:
        if valor is None or valor == "":
            return padrao
        if isinstance(valor, str):
            valor = valor.replace("R$", "").replace(".", "").replace(",", ".").strip()
        return float(valor)
    except Exception:
        return padrao


def real(valor):
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def real4(valor):
    # Mantido para compatibilidade, mas agora também mostra só 2 casas.
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def hoje_iso():
    return date.today().isoformat()


def obter_config(chave, padrao=""):
    padroes_forcados = {
        "valor_hora": "5",
        "margem_padrao": "50",
        "reserva_erro": "5",
        "custo_kwh": "250",
        "validade_orcamento": "7",
    }

    df = consultar("SELECT valor FROM configuracoes WHERE chave=?", (chave,))

    if df.empty:
        return padroes_forcados.get(chave, padrao)

    valor = str(df.iloc[0]["valor"]).strip()

    # Corrige automaticamente valores antigos que ficaram com muitos zeros.
    if chave in padroes_forcados:
        numero = n(valor, None)
        if numero is None:
            return padroes_forcados[chave]

        if chave == "valor_hora" and numero > 100:
            return "5"
        if chave == "margem_padrao" and numero > 500:
            return "50"
        if chave == "reserva_erro" and numero > 100:
            return "5"
        if chave == "custo_kwh" and numero > 100000:
            return "250"
        if chave == "validade_orcamento" and numero > 365:
            return "7"

        if float(numero).is_integer():
            return str(int(numero))
        return str(numero).replace(".", ",")

    return valor


def salvar_config(chave, valor):
    executar(
        "INSERT OR REPLACE INTO configuracoes(chave, valor) VALUES (?, ?)",
        (chave, str(valor)),
    )




def formatar_valores_tabela(df):
    """Deixa as tabelas mais limpas visualmente, com valores em 2 casas decimais."""
    if df is None or getattr(df, "empty", True):
        return df

    df = df.copy()

    palavras_valor = [
        "valor", "preco", "preço", "custo", "lucro", "subtotal",
        "total", "desconto", "frete", "mao_obra", "mão_obra",
        "energia", "desgaste"
    ]

    for col in df.columns:
        col_lower = str(col).lower()

        if any(p in col_lower for p in palavras_valor):
            try:
                df[col] = df[col].apply(lambda x: real(x) if str(x).strip() not in ["", "None", "nan"] else "")
            except Exception:
                pass

        elif "margem" in col_lower or "%" in col_lower:
            try:
                df[col] = df[col].apply(lambda x: f"{float(x):.2f}%".replace(".", ",") if str(x).strip() not in ["", "None", "nan"] else "")
            except Exception:
                pass

        elif "folhas_a4" in col_lower or "folhas a4" in col_lower:
            try:
                df[col] = df[col].apply(lambda x: f"{float(x):.0f}" if str(x).strip() not in ["", "None", "nan"] else "")
            except Exception:
                pass

    return df

def card(titulo, valor, subtitulo=""):
    # Garante exibição monetária sempre com 2 casas decimais.
    try:
        if isinstance(valor, str) and valor.strip().startswith("R$"):
            numero = valor.replace("R$", "").replace(".", "").replace(",", ".").strip()
            valor = real(float(numero))
    except Exception:
        pass

    st.markdown(
        f"""
        <div class="card">
            <div class="card-title">{titulo}</div>
            <div class="card-value">{valor}</div>
            <div class="card-subtitle">{subtitulo}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def salvar_upload(upload, nome_base):
    if upload is None:
        return ""
    ext = Path(upload.name).suffix.lower()
    caminho = UPLOAD_DIR / f"{nome_base}{ext}"
    caminho.write_bytes(upload.getbuffer())
    return str(caminho)


def imagem_base64(caminho):
    try:
        p = Path(caminho)
        if not p.exists():
            return ""
        return base64.b64encode(p.read_bytes()).decode("utf-8")
    except Exception:
        return ""




# ============================================================
# CÓDIGOS VISUAIS PROFISSIONAIS
# ============================================================

def codigo_visual(prefixo, id_valor, ano=None):
    try:
        numero = int(id_valor)
    except Exception:
        numero = 0

    if ano:
        return f"{prefixo}-{ano}-{numero:04d}"

    return f"{prefixo}-{numero:04d}"


def adicionar_codigo_visual(df, prefixo, coluna_id="id", nome_coluna="Código", ano=None):
    if df is None or getattr(df, "empty", True) or coluna_id not in df.columns:
        return df

    df = df.copy()
    if nome_coluna in df.columns:
        return df

    df.insert(
        0,
        nome_coluna,
        df[coluna_id].apply(lambda x: codigo_visual(prefixo, x, ano=ano))
    )
    return df


# ============================================================
# BANCO
# ============================================================

def criar_banco():
    executar("""
    CREATE TABLE IF NOT EXISTS categorias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT UNIQUE NOT NULL,
        ativo TEXT DEFAULT 'Sim'
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS insumos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        categoria TEXT NOT NULL,
        valor_pacote REAL DEFAULT 0,
        quantidade_pacote REAL DEFAULT 1,
        fornecedor TEXT,
        link_produto TEXT,
        ativo TEXT DEFAULT 'Sim'
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS tintas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        valor_kit REAL DEFAULT 0,
        rendimento_impressoes REAL DEFAULT 1,
        ativo TEXT DEFAULT 'Sim'
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS equipamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        valor_pago REAL DEFAULT 0,
        vida_util_meses REAL DEFAULT 24,
        producao_mensal REAL DEFAULT 500,
        potencia_w REAL DEFAULT 0,
        usa_energia TEXT DEFAULT 'Sim',
        ativo TEXT DEFAULT 'Sim'
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        categoria TEXT,
        qtd_por_lote REAL DEFAULT 1,
        receita_json TEXT,
        tintas_json TEXT,
        equipamentos_json TEXT,
        tempo_min REAL DEFAULT 0,
        valor_hora REAL DEFAULT 0,
        reserva_erro REAL DEFAULT 0,
        margem_lucro REAL DEFAULT 0,
        custo_insumos REAL DEFAULT 0,
        custo_tintas REAL DEFAULT 0,
        custo_equipamentos REAL DEFAULT 0,
        custo_mao_obra REAL DEFAULT 0,
        custo_total_lote REAL DEFAULT 0,
        custo_unitario REAL DEFAULT 0,
        preco_sugerido REAL DEFAULT 0,
        preco_escolhido REAL DEFAULT 0,
        lucro_unitario REAL DEFAULT 0,
        margem_real REAL DEFAULT 0,
        ativo TEXT DEFAULT 'Sim',
        foto TEXT
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS configuracoes (
        chave TEXT PRIMARY KEY,
        valor TEXT
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        whatsapp TEXT,
        instagram TEXT,
        email TEXT,
        cidade TEXT,
        endereco TEXT,
        aniversario TEXT,
        observacoes TEXT,
        ativo TEXT DEFAULT 'Sim',
        data_cadastro TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS orcamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER,
        cliente_nome TEXT,
        whatsapp TEXT,
        data_orcamento TEXT DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'Em orçamento',
        forma_pagamento TEXT,
        subtotal REAL DEFAULT 0,
        desconto REAL DEFAULT 0,
        frete REAL DEFAULT 0,
        total REAL DEFAULT 0,
        observacoes TEXT
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS orcamento_itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        orcamento_id INTEGER,
        produto TEXT,
        categoria TEXT,
        quantidade REAL DEFAULT 0,
        valor_unitario REAL DEFAULT 0,
        desconto REAL DEFAULT 0,
        total REAL DEFAULT 0
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS financeiro (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data TEXT DEFAULT CURRENT_DATE,
        tipo TEXT,
        descricao TEXT,
        categoria TEXT,
        forma_pagamento TEXT,
        valor REAL DEFAULT 0,
        origem TEXT,
        referencia_id INTEGER,
        observacoes TEXT
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS estoque (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data TEXT DEFAULT CURRENT_DATE,
        item TEXT,
        categoria TEXT,
        tipo_movimento TEXT,
        quantidade REAL DEFAULT 0,
        valor_unitario REAL DEFAULT 0,
        fornecedor TEXT,
        observacoes TEXT
    )
    """)


    executar("""
    CREATE TABLE IF NOT EXISTS laminacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        tipo TEXT DEFAULT 'Hot',
        largura_cm REAL DEFAULT 0,
        comprimento_m REAL DEFAULT 0,
        valor_pago REAL DEFAULT 0,
        folhas_a4 REAL DEFAULT 0,
        custo_metro REAL DEFAULT 0,
        custo_a4 REAL DEFAULT 0,
        observacoes TEXT,
        ativo TEXT DEFAULT 'Sim'
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS mantas_imas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        tipo TEXT DEFAULT 'Ímã',
        valor_pacote REAL DEFAULT 0,
        quantidade_pacote REAL DEFAULT 1,
        custo_unitario REAL DEFAULT 0,
        observacoes TEXT,
        ativo TEXT DEFAULT 'Sim'
    )
    """)


    executar("""
    CREATE TABLE IF NOT EXISTS historico_precos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data TEXT DEFAULT CURRENT_TIMESTAMP,
        tipo_item TEXT,
        item_id INTEGER,
        item_nome TEXT,
        campo TEXT,
        valor_antigo REAL DEFAULT 0,
        valor_novo REAL DEFAULT 0,
        observacoes TEXT
    )
    """)

    try:
        executar("ALTER TABLE produtos ADD COLUMN favorito TEXT DEFAULT 'Não'")
    except Exception:
        pass

    try:
        executar("ALTER TABLE produtos ADD COLUMN descricao_catalogo TEXT")
    except Exception:
        pass


    executar("""
    CREATE TABLE IF NOT EXISTS ordens_producao (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        orcamento_id INTEGER,
        codigo TEXT,
        cliente_nome TEXT,
        whatsapp TEXT,
        data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
        data_entrega TEXT,
        status TEXT DEFAULT 'Aguardando',
        itens_json TEXT,
        materiais_json TEXT,
        observacoes TEXT
    )
    """)

    configuracoes_padrao = {
        "nome_empresa": "Sophi Personalizados Oficial",
        "whatsapp": "",
        "instagram": "@sophipersonalizadosoficial",
        "email": "",
        "pix": "",
        "valor_hora": "5",
        "margem_padrao": "50",
        "reserva_erro": "5",
        "custo_kwh": "250",
        "validade_orcamento": "7",
        "logo_path": "",
        "catalogo_titulo": "Sophi Personalizados Oficial",
        "catalogo_slogan": "Eternizando momentos com presentes personalizados",
        "catalogo_descricao": "Confira nossos produtos personalizados e chame no WhatsApp para fazer seu pedido.",
        "catalogo_aviso": "Valores sujeitos à confirmação conforme personalização, material e prazo.",
        "catalogo_cor": "#000000",
    }

    for chave, valor in configuracoes_padrao.items():
        executar(
            "INSERT OR IGNORE INTO configuracoes(chave, valor) VALUES (?, ?)",
            (chave, valor),
        )

    # Categorias padrão: cria apenas uma vez.
    # Depois disso você pode adicionar, modificar e excluir livremente.
    categorias_ja_criadas = consultar(
        "SELECT valor FROM configuracoes WHERE chave='categorias_iniciais_criadas'"
    )

    if categorias_ja_criadas.empty:
        categorias = [
            "Papel",
            "Laminação",
            "Manta/Imã",
            "Embalagem",
            "Quadros/A4",
            "Moldura",
            "Adesivo",
            "Sacola",
            "Caixa",
            "Fita",
            "Brinde",
            "Acabamento",
            "Outro",
        ]

        for cat in categorias:
            executar("INSERT OR IGNORE INTO categorias(nome, ativo) VALUES (?, 'Sim')", (cat,))

        executar(
            "INSERT OR REPLACE INTO configuracoes(chave, valor) VALUES (?, ?)",
            ("categorias_iniciais_criadas", "Sim"),
        )

    if consultar("SELECT COUNT(*) AS total FROM equipamentos").iloc[0]["total"] == 0:
        equipamentos = [
            ("Computador", 2000.00, 24, 500, 80, "Sim", "Sim"),
            ("Silhouette Cameo 4", 1500.00, 24, 500, 20, "Sim", "Sim"),
            ("Guilhotina", 75.00, 36, 500, 0, "Não", "Sim"),
            ("Laminadora 6 em 1", 200.00, 24, 500, 450, "Sim", "Sim"),
            ("Impressora Epson L3250", 1200.00, 24, 500, 12, "Sim", "Sim"),
        ]
        for e in equipamentos:
            executar("""
            INSERT INTO equipamentos(
                nome, valor_pago, vida_util_meses, producao_mensal,
                potencia_w, usa_energia, ativo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, e)

    if consultar("SELECT COUNT(*) AS total FROM tintas").iloc[0]["total"] == 0:
        executar("""
        INSERT INTO tintas(nome, valor_kit, rendimento_impressoes, ativo)
        VALUES (?, ?, ?, ?)
        """, ("Tinta Epson Original", 180.00, 7500.00, "Sim"))


# ============================================================
# CÁLCULOS
# ============================================================

def custo_insumo(valor_pacote, quantidade_pacote):
    return n(valor_pacote) / max(n(quantidade_pacote, 1), 1)


def custo_tinta(valor_kit, rendimento):
    return n(valor_kit) / max(n(rendimento, 1), 1)


def custo_equipamento(row, minutos=1, custo_kwh=None):
    if custo_kwh is None:
        custo_kwh = n(obter_config("custo_kwh", "0.90"), 0.90)
    valor_pago = n(row["valor_pago"])
    vida = max(n(row["vida_util_meses"], 1), 1)
    producao = max(n(row["producao_mensal"], 1), 1)
    potencia = n(row["potencia_w"])
    usa = str(row["usa_energia"])

    desgaste_por_uso = valor_pago / vida / producao
    energia_por_minuto = (potencia / 1000) * custo_kwh / 60 if usa == "Sim" else 0

    return (desgaste_por_uso + energia_por_minuto) * minutos


def categorias_ativas():
    df = consultar("SELECT nome FROM categorias WHERE ativo='Sim' ORDER BY nome")
    return df["nome"].tolist()


def dataframe_mes(df, data_col, valor_col, ano):
    if df.empty:
        return pd.DataFrame({"Mês": list(range(1, 13)), "Total": [0.0] * 12})
    dados = df.copy()
    dados[data_col] = pd.to_datetime(dados[data_col], errors="coerce")
    dados = dados[dados[data_col].dt.year == ano]
    serie = dados.groupby(dados[data_col].dt.month)[valor_col].sum()
    out = pd.DataFrame({"Mês": list(range(1, 13))})
    out["Total"] = out["Mês"].map(serie).fillna(0.0)
    return out


def dataframe_dia(df, data_col, valor_col, ano):
    if df.empty:
        return pd.DataFrame({"Data": [], "Total": []})
    dados = df.copy()
    dados[data_col] = pd.to_datetime(dados[data_col], errors="coerce")
    dados = dados[dados[data_col].dt.year == ano]
    if dados.empty:
        return pd.DataFrame({"Data": [], "Total": []})
    serie = dados.groupby(dados[data_col].dt.date)[valor_col].sum()
    out = serie.reset_index()
    out.columns = ["Data", "Total"]
    return out


def gerar_html_orcamento(orc_id):
    orc = consultar("SELECT * FROM orcamentos WHERE id=?", (int(orc_id),))
    if orc.empty:
        return ""

    o = orc.iloc[0]
    try:
        ano_orc = pd.to_datetime(o["data_orcamento"], errors="coerce").year
        if pd.isna(ano_orc):
            ano_orc = datetime.now().year
    except Exception:
        ano_orc = datetime.now().year
    codigo_orcamento = codigo_visual("ORC", orc_id, ano=int(ano_orc))
    itens = consultar("SELECT * FROM orcamento_itens WHERE orcamento_id=?", (int(orc_id),))

    logo = obter_config("logo_path", "")
    logo_html = ""
    if logo and Path(logo).exists():
        b64 = imagem_base64(logo)
        ext = Path(logo).suffix.replace(".", "").lower() or "png"
        logo_html = f'<img src="data:image/{ext};base64,{b64}" class="logo">'

    linhas = ""
    for _, r in itens.iterrows():
        linhas += f"""
        <tr>
            <td class="produto">{r['produto']}</td>
            <td>{r['categoria'] or '-'}</td>
            <td class="center">{n(r['quantidade']):.0f}</td>
            <td class="right">{real(r['valor_unitario'])}</td>
            <td class="right">{real(r['desconto'])}</td>
            <td class="right strong">{real(r['total'])}</td>
        </tr>
        """

    empresa = obter_config("nome_empresa", EMPRESA)
    validade = obter_config("validade_orcamento", "7")
    try:
        prazo_entrega = (datetime.now().date() + timedelta(days=int(n(validade, 7)))).strftime("%d/%m/%Y")
    except Exception:
        prazo_entrega = (datetime.now().date() + timedelta(days=7)).strftime("%d/%m/%Y")
    instagram = obter_config("instagram", "")
    whatsapp = obter_config("whatsapp", "")
    pix = obter_config("pix", "")
    email = obter_config("email", "")

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{codigo_orcamento} - {empresa}</title>
<style>
* {{ 
    box-sizing: border-box; 
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
    color-adjust: exact !important;
}}
html {{
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
}}
body {{
    font-family: Arial, Helvetica, sans-serif;
    color: #111;
    margin: 0;
    background: #f3f3f3;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
}}
.page {{
    width: 210mm;
    min-height: 297mm;
    margin: 0 auto;
    background: #fff;
    padding: 20px 28px;
}}
.top {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    border-bottom: 2px solid #111;
    padding-bottom: 12px;
}}
.logo {{ max-height: 60px; max-width: 130px; object-fit: contain; }}
.brand h1 {{
    margin: 0;
    font-size: 25px;
    letter-spacing: .4px;
}}
.brand p {{
    margin: 5px 0 0;
    color: #555;
    font-size: 11px;
}}
.brand {{
    max-width: 540px;
}}
.badge .label {{
    font-size: 9px;
}}
.badge {{
    border: 2px solid #111;
    padding: 9px 12px;
    text-align: right;
    min-width: 145px;
}}
.badge .num {{
    font-size: 20px;
    font-weight: 800;
}}
.badge .status {{
    margin-top: 6px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
.section {{
    margin-top: 14px;
}}
.section-title {{
    background: #000000 !important;
    color: #ffffff !important;
    box-shadow: inset 0 0 0 1000px #000000 !important;
    padding: 7px 11px;
    margin: 14px 0 8px;
    font-size: 14px;
    font-weight: 800;
    letter-spacing: .2px;
}}
.grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
}}
.box {{
    border: 1px solid #ddd;
    border-radius: 10px;
    padding: 10px;
    background: #fafafa;
}}
.box p {{
    margin: 6px 0;
    font-size: 12px;
    line-height: 1.25;
}}
.label {{
    color: #777;
    font-size: 9.5px;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 4px;
}}
.value {{
    font-size: 13px;
    font-weight: 700;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 14px;
    font-size: 11px;
}}
th {{
    background: #000000 !important;
    color: #ffffff !important;
    box-shadow: inset 0 0 0 1000px #000000 !important;
    padding: 11px 9px;
    text-align: left;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: .5px;
}}
td {{
    border-bottom: 1px solid #e6e6e6;
    padding: 7px 7px;
}}
tr:nth-child(even) td {{ background: #fafafa; }}
.right {{ text-align: right; }}
.center {{ text-align: center; }}
.strong {{ font-weight: 800; }}
.produto {{ font-weight: 700; }}
.totals {{
    width: 285px;
    margin-left: auto;
    margin-top: 10px;
}}
.total-row {{
    display: flex;
    justify-content: space-between;
    padding: 5px 0;
    border-bottom: 1px solid #eee;
}}
.total-final {{
    margin-top: 7px;
    padding: 10px;
    background: #000000 !important;
    color: #ffffff !important;
    box-shadow: inset 0 0 0 1000px #000000 !important;
    border-radius: 10px;
    display: flex;
    justify-content: space-between;
    font-size: 18px;
    font-weight: 900;
}}
.obs {{
    min-height: 42px;
    white-space: pre-wrap;
}}
.footer {{
    margin-top: 18px;
    padding-top: 10px;
    border-top: 1px solid #ddd;
    font-size: 10px;
    color: #555;
    display: flex;
    justify-content: space-between;
    gap: 18px;
}}
button {{
    position: fixed;
    top: 18px;
    right: 18px;
    background: #111;
    color: #fff;
    border: none;
    padding: 12px 18px;
    border-radius: 10px;
    font-weight: 700;
    cursor: pointer;
}}
@media print {{
    * {{
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
        color-adjust: exact !important;
    }}
    body {{ background: #ffffff !important; }}
    @page {{ size: A4; margin: 8mm; }}
    .page {{ width: auto; min-height: auto; padding: 0; }}
    button {{ display: none; }}
    th, .total-final, .section-title {{
        background: #000000 !important;
        color: #ffffff !important;
        box-shadow: inset 0 0 0 1000px #000000 !important;
    }}
}}
</style>
</head>
<body>
<button onclick="window.print()">Imprimir / salvar em PDF</button>

<div class="page">
    <div class="top">
        <div class="brand">
            {logo_html}
            <h1>{empresa}</h1>
            <p>📷 {instagram} {(' | ' + whatsapp) if whatsapp else ''} {(' | ' + email) if email else ''}</p>
        </div>
        <div class="badge">
            <div class="label">Orçamento</div>
            <div class="num">{codigo_orcamento}</div>
            <div class="status">{o['status']}</div>
        </div>
    </div>

    <div class="section grid">
        <div class="box">
            <div class="label">Cliente</div>
            <div class="value">{o['cliente_nome']}</div>
            <p><b>WhatsApp:</b> {o['whatsapp'] or '-'}</p>
            <p><b>Data:</b> {o['data_orcamento']}</p><p><b>Prazo de entrega:</b> {prazo_entrega}</p>
        </div>
        <div class="box">
            <div class="label">Pagamento</div>
            <div class="value">{o['forma_pagamento'] or '-'}</div>
            <p><b>Validade:</b> {validade} dias</p>
            <p><b>Chave PIX/CNPJ:</b> {pix or '-'}</p>
        </div>
    </div>

    <div class="section">
        <div class="section-title">Itens do orçamento</div>
        <table>
            <thead>
                <tr>
                    <th>Produto</th>
                    <th>Categoria</th>
                    <th class="center">Qtd</th>
                    <th class="right">Unitário</th>
                    <th class="right">Desconto</th>
                    <th class="right">Total</th>
                </tr>
            </thead>
            <tbody>{linhas}</tbody>
        </table>
    </div>

    <div class="totals">
        <div class="total-row"><span>Subtotal</span><b>{real(o['subtotal'])}</b></div>
        <div class="total-row"><span>Desconto</span><b>{real(o['desconto'])}</b></div>
        <div class="total-row"><span>Frete</span><b>{real(o['frete'])}</b></div>
        <div class="total-final"><span>Total</span><span>{real(o['total'])}</span></div>
    </div>

    <div class="section box">
        <div class="section-title">Informações adicionais</div><div class="label">Observações</div>
        <div class="obs">{o['observacoes'] or 'Sem observações.'}</div>
    </div>

    <div class="footer">
        <div>Orçamento gerado pelo Sophi ERP. Valores sujeitos à confirmação conforme personalização, material e prazo.</div>
        <div><b>{empresa}</b><br>Obrigada pela preferência.</div>
    </div>
</div>
</body>
</html>"""
    return html



# ============================================================
# RECURSOS ERP 2.0 - PARTE INICIAL
# ============================================================

def registrar_historico_preco(tipo_item, item_id, item_nome, campo, valor_antigo, valor_novo, observacoes=""):
    try:
        if round(float(valor_antigo or 0), 2) == round(float(valor_novo or 0), 2):
            return

        executar("""
        INSERT INTO historico_precos(
            tipo_item, item_id, item_nome, campo,
            valor_antigo, valor_novo, observacoes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            str(tipo_item),
            int(item_id),
            str(item_nome),
            str(campo),
            n(valor_antigo),
            n(valor_novo),
            str(observacoes),
        ))
    except Exception:
        pass


def saldo_estoque():
    df = consultar("SELECT * FROM estoque")
    if df.empty:
        return pd.DataFrame(columns=["Item", "Categoria", "Saldo"])

    temp = df.copy()
    temp["qtd_assinada"] = temp.apply(
        lambda r: n(r["quantidade"]) if str(r["tipo_movimento"]) == "Entrada" else -n(r["quantidade"]),
        axis=1,
    )

    saldo = temp.groupby(["item", "categoria"])["qtd_assinada"].sum().reset_index()
    saldo.columns = ["Item", "Categoria", "Saldo"]
    return saldo


def produtos_favoritos_df():
    try:
        return consultar("""
        SELECT id, nome, categoria, preco_escolhido, preco_sugerido, custo_unitario, lucro_unitario, favorito
        FROM produtos
        WHERE ativo='Sim' AND favorito='Sim'
        ORDER BY nome
        """)
    except Exception:
        return pd.DataFrame()


def aniversariantes_mes_df():
    mes_atual = f"{datetime.now().month:02d}"
    clientes = consultar("""
    SELECT id, nome, whatsapp, aniversario
    FROM clientes
    WHERE ativo='Sim' AND aniversario IS NOT NULL AND aniversario != ''
    ORDER BY nome
    """)

    if clientes.empty:
        return clientes

    def aniversario_do_mes(valor):
        texto = str(valor).strip()
        partes = texto.replace("-", "/").split("/")
        if len(partes) >= 2:
            return partes[1].zfill(2) == mes_atual
        return False

    return clientes[clientes["aniversario"].apply(aniversario_do_mes)]


def painel_calculadora_rapida():
    with st.sidebar.expander("Calculadora rápida"):
        st.caption("Some custos rápidos sem precisar criar produto.")

        papel = st.number_input("Papel / item", min_value=0.0, value=0.0, step=0.01, format="%.2f", key="calc_papel")
        laminacao = st.number_input("Laminação", min_value=0.0, value=0.0, step=0.01, format="%.2f", key="calc_laminacao")
        ima = st.number_input("Ímã / manta", min_value=0.0, value=0.0, step=0.01, format="%.2f", key="calc_ima")
        embalagem = st.number_input("Embalagem", min_value=0.0, value=0.0, step=0.01, format="%.2f", key="calc_embalagem")
        outros = st.number_input("Outros", min_value=0.0, value=0.0, step=0.01, format="%.2f", key="calc_outros")

        total = papel + laminacao + ima + embalagem + outros
        st.metric("Custo rápido", real(total))


def mostrar_ficha_produto(produto_id):
    prod = consultar("SELECT * FROM produtos WHERE id=?", (int(produto_id),))
    if prod.empty:
        st.warning("Produto não encontrado.")
        return

    p = prod.iloc[0]

    st.subheader(f"Ficha completa: {p['nome']}")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        card("Código", codigo_visual("PROD", p["id"]))
    with c2:
        card("Custo unitário", real(p["custo_unitario"]))
    with c3:
        preco = n(p["preco_escolhido"]) if n(p["preco_escolhido"]) > 0 else n(p["preco_sugerido"])
        card("Preço venda", real(preco))
    with c4:
        card("Lucro", real(p["lucro_unitario"]), f"{n(p['margem_real']):.2f}%")

    foto = str(p.get("foto", "") or "")
    if foto and Path(foto).exists():
        st.image(foto, width=220)

    st.write(f"**Categoria:** {p.get('categoria', '') or '-'}")
    st.write(f"**Quantidade por lote/folha:** {p.get('qtd_por_lote', '')}")

    st.markdown("### Itens utilizados")
    try:
        receita = json.loads(p["receita_json"] or "[]")
        if receita:
            st.dataframe(formatar_valores_tabela(pd.DataFrame(receita)), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum item salvo.")
    except Exception:
        st.info("Não foi possível ler os itens utilizados.")

    st.markdown("### Tintas")
    try:
        tintas = json.loads(p["tintas_json"] or "[]")
        if tintas:
            st.dataframe(formatar_valores_tabela(pd.DataFrame(tintas)), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhuma tinta salva.")
    except Exception:
        st.info("Não foi possível ler as tintas.")

    st.markdown("### Equipamentos")
    try:
        equipamentos = json.loads(p["equipamentos_json"] or "[]")
        if equipamentos:
            st.dataframe(formatar_valores_tabela(pd.DataFrame(equipamentos)), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum equipamento salvo.")
    except Exception:
        st.info("Não foi possível ler os equipamentos.")

    st.markdown("### Histórico de preços")
    hist = consultar("""
    SELECT data, campo, valor_antigo, valor_novo, observacoes
    FROM historico_precos
    WHERE tipo_item='Produto' AND item_id=?
    ORDER BY id DESC
    """, (int(produto_id),))

    if hist.empty:
        st.caption("Ainda não há histórico de alterações de preço.")
    else:
        st.dataframe(formatar_valores_tabela(hist), use_container_width=True, hide_index=True)

    st.markdown("### Simulador de preço")
    simulador = st.number_input(
        "E se eu vender por...",
        min_value=0.0,
        value=float(preco or 0),
        step=0.10,
        format="%.2f",
        key=f"simulador_prod_{int(produto_id)}",
    )

    custo = n(p["custo_unitario"])
    lucro_sim = simulador - custo
    margem_sim = (lucro_sim / simulador * 100) if simulador > 0 else 0

    s1, s2, s3 = st.columns(3)
    with s1:
        card("Custo", real(custo))
    with s2:
        card("Lucro simulado", real(lucro_sim))
    with s3:
        card("Margem simulada", f"{margem_sim:.2f}%")



def tela_inicio():
    st.title("Painel Hoje")
    st.write("Resumo rápido para acompanhar a Sophi Personalizados Oficial sem abrir várias abas.")

    hoje = hoje_iso()
    ano = datetime.now().year

    orc = consultar("SELECT * FROM orcamentos")
    fin = consultar("SELECT * FROM financeiro")
    clientes = consultar("SELECT * FROM clientes")
    produtos = consultar("SELECT * FROM produtos")

    vendas_hoje = 0.0
    if not fin.empty:
        temp = fin.copy()
        temp["data"] = pd.to_datetime(temp["data"], errors="coerce").dt.date.astype(str)
        vendas_hoje = float(temp[(temp["data"] == hoje) & (temp["tipo"] == "Entrada")]["valor"].sum())

    aguardando = 0
    entregas_hoje = 0
    faturamento_mes = 0.0
    lucro_mes = 0.0
    margem_media = 0.0

    if not orc.empty:
        temp_orc = orc.copy()
        temp_orc["data_orcamento_dt"] = pd.to_datetime(temp_orc["data_orcamento"], errors="coerce")
        temp_orc["data_entrega_prevista"] = temp_orc["data_orcamento_dt"] + pd.to_timedelta(int(n(obter_config("validade_orcamento", "7"), 7)), unit="D")

        aguardando = len(temp_orc[temp_orc["status"].isin(["Em orçamento", "Aguardando pagamento"])])

        entregas_hoje = len(temp_orc[
            (temp_orc["data_entrega_prevista"].dt.date.astype(str) == hoje)
            & (~temp_orc["status"].isin(["Entregue", "Cancelado"]))
        ])

        mes_atual = datetime.now().month
        temp_mes = temp_orc[temp_orc["data_orcamento_dt"].dt.month == mes_atual]
        faturamento_mes = float(temp_mes["total"].sum())

    if not produtos.empty:
        lucro_mes = float(produtos["lucro_unitario"].fillna(0).sum())
        margem_media = float(produtos["margem_real"].fillna(0).mean()) if "margem_real" in produtos.columns else 0.0

    saldo = saldo_estoque()
    estoque_baixo = saldo[saldo["Saldo"] <= 5] if not saldo.empty else pd.DataFrame()

    aniversariantes = aniversariantes_mes_df()
    favoritos = produtos_favoritos_df()

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        card("Vendas hoje", real(vendas_hoje))
    with c2:
        card("Entregas hoje", str(entregas_hoje))
    with c3:
        card("Aguardando resposta", str(aguardando))
    with c4:
        card("Estoque baixo", str(len(estoque_baixo)))
    with c5:
        card("Aniversariantes", str(len(aniversariantes)))

    st.divider()

    st.subheader("Dashboard de lucro")
    d1, d2, d3 = st.columns(3)
    with d1:
        card("Faturamento do mês", real(faturamento_mes))
    with d2:
        card("Lucro estimado", real(lucro_mes))
    with d3:
        card("Margem média", f"{margem_media:.2f}%")

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Produtos favoritos")
        if favoritos.empty:
            st.info("Nenhum produto favorito ainda.")
        else:
            favoritos = adicionar_codigo_visual(favoritos, "PROD")
            st.dataframe(formatar_valores_tabela(favoritos), use_container_width=True, hide_index=True)

    with col2:
        st.subheader("Estoque baixo")
        if estoque_baixo.empty:
            st.success("Nenhum item crítico no estoque.")
        else:
            st.dataframe(formatar_valores_tabela(estoque_baixo), use_container_width=True, hide_index=True)

    st.subheader("Clientes aniversariantes do mês")
    if aniversariantes.empty:
        st.info("Nenhum aniversariante cadastrado neste mês.")
    else:
        aniversariantes = adicionar_codigo_visual(aniversariantes, "CLI")
        st.dataframe(aniversariantes, use_container_width=True, hide_index=True)

    st.divider()

    st.subheader("Últimos orçamentos")
    if orc.empty:
        st.info("Ainda não há orçamentos.")
    else:
        ultimos = consultar("""
        SELECT id, cliente_nome, status, forma_pagamento, total, data_orcamento
        FROM orcamentos
        ORDER BY id DESC
        LIMIT 8
        """)
        ultimos = adicionar_codigo_visual(ultimos, "ORC", ano=ano)
        st.dataframe(
            formatar_valores_tabela(ultimos),
            use_container_width=True,
            hide_index=True,
        )


def tela_configuracoes():
    st.title("Configurações")
    st.write("Aqui você controla os dados principais da Sophi Personalizados Oficial.")

    logo_atual = obter_config("logo_path", "")
    if logo_atual and Path(logo_atual).exists():
        st.image(logo_atual, width=160)

    logo_upload = st.file_uploader("Enviar logo da empresa", type=["png", "jpg", "jpeg", "webp"])
    if logo_upload is not None:
        caminho = salvar_upload(logo_upload, "logo_sophi")
        salvar_config("logo_path", caminho)
        st.success("Logo salva com sucesso.")
        st.rerun()

    with st.form("form_configuracoes"):
        st.subheader("Dados da empresa")
        nome_empresa = st.text_input("Nome da empresa", value=obter_config("nome_empresa", EMPRESA))
        instagram = st.text_input("Instagram", value=obter_config("instagram", "@sophipersonalizadosoficial"))
        whatsapp = st.text_input("WhatsApp", value=obter_config("whatsapp", ""))
        email = st.text_input("E-mail", value=obter_config("email", ""))
        pix = st.text_input("Chave PIX", value=obter_config("pix", ""))

        st.subheader("Valores padrão de cálculo")
        st.caption("Digite normal: 5 / 5,50 / 2,50. O sistema salva sem encher de zeros.")

        c1, c2, c3 = st.columns(3)
        valor_hora_txt = c1.text_input("Valor da sua hora (R$)", value=obter_config("valor_hora", "5"))
        margem_padrao_txt = c2.text_input("Margem padrão (%)", value=obter_config("margem_padrao", "50"))
        reserva_erro_txt = c3.text_input("Reserva de erro (%)", value=obter_config("reserva_erro", "5"))

        c4, c5 = st.columns(2)
        custo_kwh_txt = c4.text_input("Custo energia kWh (R$)", value=obter_config("custo_kwh", "250"))
        validade_txt = c5.text_input("Validade do orçamento em dias", value=obter_config("validade_orcamento", "7"))

        if st.form_submit_button("Salvar configurações"):
            salvar_config("nome_empresa", nome_empresa)
            salvar_config("instagram", instagram)
            salvar_config("whatsapp", whatsapp)
            salvar_config("email", email)
            salvar_config("pix", pix)
            salvar_config("valor_hora", int(n(valor_hora_txt, 5)) if n(valor_hora_txt, 5).is_integer() else n(valor_hora_txt, 5))
            salvar_config("margem_padrao", int(n(margem_padrao_txt, 50)) if n(margem_padrao_txt, 50).is_integer() else n(margem_padrao_txt, 50))
            salvar_config("reserva_erro", n(reserva_erro_txt, 5))
            salvar_config("custo_kwh", int(n(custo_kwh_txt, 250)) if n(custo_kwh_txt, 250).is_integer() else n(custo_kwh_txt, 250))
            salvar_config("validade_orcamento", int(n(validade_txt, 7)))
            st.success("Configurações salvas com sucesso.")
            st.rerun()


def tela_clientes():
    st.title("Clientes")
    st.write("Cadastre e acompanhe os clientes da Sophi Personalizados Oficial.")

    st.subheader("Cadastrar cliente")
    with st.form("form_cliente"):
        c1, c2 = st.columns(2)
        nome = c1.text_input("Nome do cliente")
        whatsapp = c2.text_input("WhatsApp")

        c3, c4 = st.columns(2)
        instagram = c3.text_input("Instagram")
        email = c4.text_input("E-mail")

        c5, c6 = st.columns(2)
        cidade = c5.text_input("Cidade")
        aniversario = c6.text_input("Aniversário", placeholder="Ex: 15/08")

        endereco = st.text_area("Endereço")
        observacoes = st.text_area("Observações")
        ativo = st.selectbox("Cliente ativo?", ["Sim", "Não"])

        if st.form_submit_button("Salvar cliente"):
            if not nome.strip():
                st.error("Digite o nome do cliente.")
            else:
                executar("""
                INSERT INTO clientes(
                    nome, whatsapp, instagram, email, cidade,
                    endereco, aniversario, observacoes, ativo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (nome, whatsapp, instagram, email, cidade, endereco, aniversario, observacoes, ativo))
                st.success("Cliente salvo com sucesso.")
                st.rerun()

    st.divider()
    st.subheader("Clientes cadastrados")
    busca_cliente = st.text_input("Pesquisar cliente")

    if busca_cliente.strip():
        termo = f"%{busca_cliente.strip()}%"
        df_clientes = consultar("""
        SELECT id, nome, whatsapp, instagram, email, cidade, aniversario, ativo, data_cadastro
        FROM clientes
        WHERE nome LIKE ? OR whatsapp LIKE ? OR instagram LIKE ? OR cidade LIKE ?
        ORDER BY id DESC
        """, (termo, termo, termo, termo))
    else:
        df_clientes = consultar("""
        SELECT id, nome, whatsapp, instagram, email, cidade, aniversario, ativo, data_cadastro
        FROM clientes
        ORDER BY id DESC
        """)

    df_clientes = adicionar_codigo_visual(df_clientes, "CLI")

    edited = st.data_editor(
        df_clientes,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="editor_clientes_profissional",
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        if st.button("Salvar alterações dos clientes"):
            for _, r in edited.iterrows():
                if str(r["nome"]).strip():
                    executar("""
                    UPDATE clientes
                    SET nome=?, whatsapp=?, instagram=?, email=?, cidade=?, aniversario=?, ativo=?
                    WHERE id=?
                    """, (
                        r["nome"], r["whatsapp"], r["instagram"], r["email"],
                        r["cidade"], r["aniversario"], r["ativo"], int(r["id"]),
                    ))
            st.success("Clientes atualizados.")
            st.rerun()
    with c2:
        id_excluir = st.number_input("ID para excluir", min_value=0, step=1, key="del_cliente_prof")
    with c3:
        st.write("")
        if st.button("Excluir cliente"):
            if id_excluir > 0:
                executar("DELETE FROM clientes WHERE id=?", (int(id_excluir),))
                st.success("Cliente excluído com sucesso.")
                st.rerun()
            else:
                st.warning("Digite um ID válido.")

    st.subheader("Ficha rápida do cliente")
    id_ficha = st.number_input("ID do cliente para ver ficha", min_value=0, step=1, key="id_ficha_cliente")
    if id_ficha > 0:
        cli = consultar("SELECT * FROM clientes WHERE id=?", (int(id_ficha),))
        if cli.empty:
            st.warning("Cliente não encontrado.")
        else:
            c = cli.iloc[0]
            orcs = consultar("SELECT COUNT(*) AS qtd, COALESCE(SUM(total),0) AS total FROM orcamentos WHERE cliente_id=?", (int(id_ficha),))
            qtd = int(orcs.iloc[0]["qtd"])
            total = float(orcs.iloc[0]["total"])
            a, b, ccol = st.columns(3)
            with a:
                card("Cliente", c["nome"], c["whatsapp"] or "")
            with b:
                card("Orçamentos", str(qtd), "Histórico")
            with ccol:
                card("Total gasto", real(total), "Soma de orçamentos")
            st.write(c["observacoes"] or "")

    st.divider()
    st.subheader("Linha do tempo do cliente")
    id_timeline = st.number_input("ID do cliente para linha do tempo", min_value=0, step=1, key="id_timeline_cliente")
    if id_timeline > 0:
        mostrar_linha_tempo_cliente(int(id_timeline))

def tela_cadastro_por_categoria(titulo, categoria_padrao):
    st.title(titulo)
    st.write(f"Cadastre, edite e exclua itens da categoria: {categoria_padrao}.")

    with st.form(f"form_{categoria_padrao}"):
        nome = st.text_input("Nome")
        c1, c2 = st.columns(2)
        valor_pacote = c1.number_input("Valor pago/pacote", min_value=0.0, step=0.01, format="%.2f")
        quantidade = c2.number_input("Quantidade no pacote", min_value=1.0, value=1.0, step=1.0)
        fornecedor = st.text_input("Fornecedor")
        link = st.text_input("Link do produto")
        ativo = st.selectbox("Ativo?", ["Sim", "Não"])
        st.metric("Custo unitário automático", real(custo_insumo(valor_pacote, quantidade)))

        if st.form_submit_button("Salvar"):
            if not nome.strip():
                st.error("Digite o nome.")
            else:
                executar("""
                INSERT INTO insumos(nome, categoria, valor_pacote, quantidade_pacote, fornecedor, link_produto, ativo)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (nome, categoria_padrao, valor_pacote, quantidade, fornecedor, link, ativo))
                st.success("Salvo com sucesso.")
                st.rerun()

    st.subheader("Cadastrados")
    df = consultar("SELECT * FROM insumos WHERE categoria=? ORDER BY id DESC", (categoria_padrao,))
    if not df.empty:
        df["custo_unitario"] = df.apply(lambda r: custo_insumo(r["valor_pacote"], r["quantidade_pacote"]), axis=1)

    prefixo_categoria = {"Papel": "PAP", "Embalagem": "EMB"}.get(categoria_padrao, "INS")
    df = adicionar_codigo_visual(df, prefixo_categoria)

    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key=f"editor_{categoria_padrao}",
        column_config={
            "valor_pacote": st.column_config.NumberColumn("Valor pacote", format="R$ %.2f"),
            "custo_unitario": st.column_config.NumberColumn("Custo unitário", format="R$ %.2f"),
        },
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        if st.button(f"Salvar modificações - {categoria_padrao}"):
            for _, r in edited.iterrows():
                if str(r.get("nome", "")).strip():
                    if pd.isna(r.get("id")):
                        executar("""
                        INSERT INTO insumos(nome, categoria, valor_pacote, quantidade_pacote, fornecedor, link_produto, ativo)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (str(r["nome"]).strip(), categoria_padrao, n(r.get("valor_pacote", 0)), max(n(r.get("quantidade_pacote", 1), 1), 1), str(r.get("fornecedor", "")), str(r.get("link_produto", "")), str(r.get("ativo", "Sim") or "Sim")))
                    else:
                        executar("""
                        UPDATE insumos SET nome=?, categoria=?, valor_pacote=?, quantidade_pacote=?, fornecedor=?, link_produto=?, ativo=? WHERE id=?
                        """, (str(r["nome"]).strip(), categoria_padrao, n(r.get("valor_pacote", 0)), max(n(r.get("quantidade_pacote", 1), 1), 1), str(r.get("fornecedor", "")), str(r.get("link_produto", "")), str(r.get("ativo", "Sim") or "Sim"), int(r["id"])))
            st.success("Alterações salvas.")
            st.rerun()

    with c2:
        del_id = st.number_input("ID para excluir", min_value=0, step=1, key=f"del_{categoria_padrao}")
    with c3:
        st.write("")
        if st.button(f"Excluir - {categoria_padrao}") and del_id:
            executar("DELETE FROM insumos WHERE id=?", (int(del_id),))
            st.success("Excluído.")
            st.rerun()

def tela_categorias():
    st.title("Categorias")
    st.write("Adicione, modifique e exclua categorias livremente. O sistema não recria categorias excluídas.")

    st.subheader("Adicionar categoria")
    c1, c2 = st.columns([3, 1])
    nova = c1.text_input("Nome da nova categoria")
    ativo_novo = c2.selectbox("Ativo?", ["Sim", "Não"], key="categoria_ativa_nova")

    if st.button("Adicionar categoria"):
        if nova.strip():
            executar("INSERT OR IGNORE INTO categorias(nome, ativo) VALUES (?, ?)", (nova.strip(), ativo_novo))
            st.success("Categoria criada.")
            st.rerun()
        else:
            st.warning("Digite o nome da categoria.")

    st.divider()
    st.subheader("Modificar categorias cadastradas")
    df = consultar("SELECT id, nome, ativo FROM categorias ORDER BY nome")

    df = adicionar_codigo_visual(df, "CAT")

    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="editor_categorias_modificar",
    )

    if st.button("Salvar modificações das categorias"):
        for _, r in edited.iterrows():
            if str(r.get("nome", "")).strip():
                if pd.isna(r.get("id")):
                    executar(
                        "INSERT OR IGNORE INTO categorias(nome, ativo) VALUES (?, ?)",
                        (str(r["nome"]).strip(), str(r.get("ativo", "Sim") or "Sim")),
                    )
                else:
                    executar(
                        "UPDATE categorias SET nome=?, ativo=? WHERE id=?",
                        (str(r["nome"]).strip(), str(r.get("ativo", "Sim") or "Sim"), int(r["id"])),
                    )
        st.success("Categorias atualizadas.")
        st.rerun()

    st.divider()
    st.subheader("Excluir categoria")
    st.caption("A categoria excluída não será recriada automaticamente.")
    id_excluir = st.number_input("ID da categoria para excluir", min_value=0, step=1, key="excluir_categoria_id")

    if st.button("Excluir categoria selecionada"):
        if id_excluir > 0:
            executar("DELETE FROM categorias WHERE id=?", (int(id_excluir),))
            st.success("Categoria excluída com sucesso.")
            st.rerun()
        else:
            st.warning("Digite um ID válido.")



def tela_embalagens():
    st.title("Embalagens")
    st.write("Cadastre embalagens com categoria para usar na precificação dos produtos.")

    st.subheader("Cadastrar embalagem")

    categorias = categorias_ativas()
    categorias_emb = [c for c in categorias if c] or ["Embalagem"]

    with st.form("form_embalagem_melhorada"):
        c1, c2 = st.columns(2)

        nome = c1.text_input("Nome da embalagem", placeholder="Ex: Sacola kraft P")
        categoria = c2.selectbox("Categoria", categorias_emb)

        c3, c4 = st.columns(2)

        valor_pacote = c3.number_input(
            "Valor do pacote",
            min_value=0.0,
            value=0.0,
            step=0.01,
            format="%.2f",
        )

        quantidade = c4.number_input(
            "Quantidade no pacote",
            min_value=1.0,
            value=1.0,
            step=1.0,
            format="%.0f",
        )

        fornecedor = st.text_input("Fornecedor")
        link = st.text_input("Link do produto")
        observacao = st.text_input("Observação", placeholder="Ex: envios pelos Correios")
        ativo = st.selectbox("Ativo?", ["Sim", "Não"])

        custo = custo_insumo(valor_pacote, quantidade)

        st.metric("Custo unitário", real(custo))

        if st.form_submit_button("Salvar embalagem"):
            if not nome.strip():
                st.error("Digite o nome da embalagem.")
            else:
                executar("""
                INSERT INTO insumos(
                    nome,
                    categoria,
                    valor_pacote,
                    quantidade_pacote,
                    fornecedor,
                    link_produto,
                    ativo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    nome,
                    categoria,
                    valor_pacote,
                    quantidade,
                    fornecedor,
                    link or observacao,
                    ativo,
                ))

                st.success("Embalagem salva com sucesso.")
                st.rerun()

    st.divider()

    st.subheader("Embalagens cadastradas")

    df = consultar("""
    SELECT
        id,
        nome,
        categoria,
        valor_pacote,
        quantidade_pacote,
        fornecedor,
        link_produto,
        ativo
    FROM insumos
    WHERE
        LOWER(categoria) LIKE '%embalagem%'
        OR LOWER(categoria) LIKE '%sacola%'
        OR LOWER(categoria) LIKE '%caixa%'
        OR LOWER(categoria) LIKE '%envelope%'
    ORDER BY id DESC
    """)

    if not df.empty:
        df["custo_unitario"] = df.apply(
            lambda r: custo_insumo(r["valor_pacote"], r["quantidade_pacote"]),
            axis=1,
        )

    df = adicionar_codigo_visual(df, "EMB")

    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "valor_pacote": st.column_config.NumberColumn("Valor pacote", format="R$ %.2f"),
            "custo_unitario": st.column_config.NumberColumn("Custo unitário", format="R$ %.2f"),
        },
        key="editor_embalagens_melhoradas",
    )

    c1, c2 = st.columns([2, 1])

    with c1:
        if st.button("Salvar alterações das embalagens"):
            ids_validos = []

            for _, r in edited.iterrows():
                rid = int(r["id"]) if "id" in r and str(r["id"]).strip() not in ["", "nan", "None"] else None
                nome = str(r.get("nome", "")).strip()

                if nome:
                    if rid:
                        executar("""
                        UPDATE insumos
                        SET nome=?, categoria=?, valor_pacote=?, quantidade_pacote=?,
                            fornecedor=?, link_produto=?, ativo=?
                        WHERE id=?
                        """, (
                            nome,
                            str(r.get("categoria", "Embalagem")),
                            n(r.get("valor_pacote", 0)),
                            max(n(r.get("quantidade_pacote", 1), 1), 1),
                            str(r.get("fornecedor", "")),
                            str(r.get("link_produto", "")),
                            str(r.get("ativo", "Sim")),
                            rid,
                        ))
                        ids_validos.append(rid)
                    else:
                        novo_id = executar("""
                        INSERT INTO insumos(
                            nome, categoria, valor_pacote, quantidade_pacote,
                            fornecedor, link_produto, ativo
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            nome,
                            str(r.get("categoria", "Embalagem")),
                            n(r.get("valor_pacote", 0)),
                            max(n(r.get("quantidade_pacote", 1), 1), 1),
                            str(r.get("fornecedor", "")),
                            str(r.get("link_produto", "")),
                            str(r.get("ativo", "Sim")),
                        ))
                        ids_validos.append(novo_id)

            st.success("Embalagens atualizadas.")
            st.rerun()

    with c2:
        id_excluir = st.number_input("ID para excluir", min_value=0, step=1, key="del_embalagem_melhorada")

        if st.button("Excluir embalagem"):
            if id_excluir > 0:
                executar("DELETE FROM insumos WHERE id=?", (int(id_excluir),))
                st.success("Embalagem excluída.")
                st.rerun()
            else:
                st.warning("Digite um ID válido.")


def tela_insumos():
    st.title("Insumos Gerais")
    st.subheader("Cadastrar insumo")
    categorias = categorias_ativas()

    with st.form("form_insumo"):
        c1, c2 = st.columns(2)
        nome = c1.text_input("Nome do insumo")
        categoria = c2.selectbox("Categoria", categorias)

        c3, c4 = st.columns(2)
        valor_pacote = c3.number_input("Valor do pacote", min_value=0.0, step=0.01, format="%.2f")
        quantidade = c4.number_input("Quantidade no pacote", min_value=1.0, value=1.0, step=1.0)

        fornecedor = st.text_input("Fornecedor")
        link = st.text_input("Link do produto")
        ativo = st.selectbox("Ativo?", ["Sim", "Não"])
        st.metric("Custo automático", real(custo_insumo(valor_pacote, quantidade)))

        if st.form_submit_button("Salvar insumo"):
            if not nome.strip():
                st.error("Coloque o nome do insumo.")
            else:
                executar("""
                INSERT INTO insumos(nome, categoria, valor_pacote, quantidade_pacote, fornecedor, link_produto, ativo)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (nome, categoria, valor_pacote, quantidade, fornecedor, link, ativo))
                st.success("Insumo salvo.")
                st.rerun()

    st.subheader("Insumos cadastrados")
    df = consultar("SELECT * FROM insumos ORDER BY id DESC")
    if not df.empty:
        df["custo_automatico"] = df.apply(lambda r: custo_insumo(r["valor_pacote"], r["quantidade_pacote"]), axis=1)

    df = adicionar_codigo_visual(df, "INS")

    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "valor_pacote": st.column_config.NumberColumn("Valor pacote", format="R$ %.2f"),
            "custo_automatico": st.column_config.NumberColumn("Custo automático", format="R$ %.2f"),
        },
        key="editor_insumos",
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        if st.button("Salvar Alterações dos insumos"):
            for _, r in edited.iterrows():
                if str(r.get("nome", "")).strip():
                    if pd.isna(r.get("id")):
                        executar("""
                        INSERT INTO insumos(nome, categoria, valor_pacote, quantidade_pacote, fornecedor, link_produto, ativo)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (r["nome"], r["categoria"], n(r["valor_pacote"]), max(n(r["quantidade_pacote"], 1), 1), r["fornecedor"], r["link_produto"], r["ativo"]))
                    else:
                        executar("""
                        UPDATE insumos SET nome=?, categoria=?, valor_pacote=?, quantidade_pacote=?, fornecedor=?, link_produto=?, ativo=? WHERE id=?
                        """, (r["nome"], r["categoria"], n(r["valor_pacote"]), max(n(r["quantidade_pacote"], 1), 1), r["fornecedor"], r["link_produto"], r["ativo"], int(r["id"])))
            st.success("Insumos atualizados.")
            st.rerun()

    with c2:
        del_id = st.number_input("ID para excluir", min_value=0, step=1, key="del_ins")
    with c3:
        st.write("")
        if st.button("Excluir insumo") and del_id:
            executar("DELETE FROM insumos WHERE id=?", (int(del_id),))
            st.success("Insumo excluído.")
            st.rerun()


def tela_tintas():
    st.title("Tintas")
    st.subheader("Cadastrar tinta")

    with st.form("form_tinta"):
        nome = st.text_input("Nome da tinta", value="Tinta Epson Original")
        c1, c2 = st.columns(2)
        valor_kit = c1.number_input("Valor do kit", min_value=0.0, value=180.00, step=0.01, format="%.2f")
        rendimento = c2.number_input("Rendimento em impressões", min_value=1.0, value=7500.0, step=1.0)
        ativo = st.selectbox("Ativo?", ["Sim", "Não"])
        st.metric("Custo por impressão", real(custo_tinta(valor_kit, rendimento)))

        if st.form_submit_button("Salvar tinta"):
            executar("INSERT INTO tintas(nome, valor_kit, rendimento_impressoes, ativo) VALUES (?, ?, ?, ?)",
                     (nome, valor_kit, rendimento, ativo))
            st.success("Tinta salva.")
            st.rerun()

    st.subheader("Tintas cadastradas")
    df = consultar("SELECT * FROM tintas ORDER BY id DESC")
    if not df.empty:
        df["custo_automatico"] = df.apply(lambda r: custo_tinta(r["valor_kit"], r["rendimento_impressoes"]), axis=1)

    df = adicionar_codigo_visual(df, "TIN")

    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "valor_kit": st.column_config.NumberColumn("Valor kit", format="R$ %.2f"),
            "custo_automatico": st.column_config.NumberColumn("Custo automático", format="R$ %.2f"),
        },
        key="editor_tintas",
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        if st.button("Salvar Alterações das tintas"):
            for _, r in edited.iterrows():
                if str(r.get("nome", "")).strip():
                    if pd.isna(r.get("id")):
                        executar("INSERT INTO tintas(nome, valor_kit, rendimento_impressoes, ativo) VALUES (?, ?, ?, ?)",
                                 (r["nome"], n(r["valor_kit"]), max(n(r["rendimento_impressoes"], 1), 1), r["ativo"]))
                    else:
                        executar("UPDATE tintas SET nome=?, valor_kit=?, rendimento_impressoes=?, ativo=? WHERE id=?",
                                 (r["nome"], n(r["valor_kit"]), max(n(r["rendimento_impressoes"], 1), 1), r["ativo"], int(r["id"])))
            st.success("Tintas atualizadas.")
            st.rerun()
    with c2:
        del_id = st.number_input("ID para excluir", min_value=0, step=1, key="del_tinta")
    with c3:
        st.write("")
        if st.button("Excluir tinta") and del_id:
            executar("DELETE FROM tintas WHERE id=?", (int(del_id),))
            st.success("Tinta excluída.")
            st.rerun()



def tela_laminacao():
    st.title("Laminação")
    st.write("Cadastre BOPP por metro e calcule automaticamente quantas folhas A4 rende.")

    AREA_A4_M2 = 0.21 * 0.297

    st.subheader("Cadastrar BOPP / Laminação")

    with st.form("form_laminacao"):
        c1, c2 = st.columns(2)
        nome = c1.text_input("Nome", placeholder="Ex: BOPP Brilho")
        tipo = c2.selectbox("Tipo", ["Hot", "Cold", "Térmica", "Fria", "Outro"])

        c3, c4, c5 = st.columns(3)
        largura_cm = c3.number_input("Largura da bobina (cm)", min_value=0.0, value=22.0, step=0.1, format="%.2f")
        comprimento_m = c4.number_input("Comprimento comprado (m)", min_value=0.0, value=10.0, step=0.1, format="%.2f")
        valor_pago = c5.number_input("Valor pago", min_value=0.0, value=0.0, step=0.01, format="%.2f")

        largura_m = largura_cm / 100
        area_total_m2 = largura_m * comprimento_m
        folhas_a4 = area_total_m2 / AREA_A4_M2 if area_total_m2 > 0 else 0
        custo_metro = valor_pago / comprimento_m if comprimento_m > 0 else 0
        custo_a4 = valor_pago / folhas_a4 if folhas_a4 > 0 else 0

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Área total", f"{area_total_m2:.2f} m²")
        r2.metric("Folhas A4 equivalentes", f"{folhas_a4:.0f}")
        r3.metric("Custo por metro", real(custo_metro))
        r4.metric("Custo por A4", real(custo_a4))

        c6, c7 = st.columns(2)
        observacoes = c6.text_input("Observação", placeholder="Ex: bobina 22cm x 10m")
        ativo = c7.selectbox("Ativo?", ["Sim", "Não"], key="ativo_laminacao")

        if st.form_submit_button("Salvar laminação"):
            if not nome.strip():
                st.error("Digite o nome da laminação.")
            else:
                executar("""
                INSERT INTO laminacoes (
                    nome, tipo, largura_cm, comprimento_m, valor_pago,
                    folhas_a4, custo_metro, custo_a4, observacoes, ativo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    nome, tipo, largura_cm, comprimento_m, valor_pago,
                    folhas_a4, custo_metro, custo_a4, observacoes, ativo
                ))
                st.success("Laminação salva com sucesso.")
                st.rerun()

    st.divider()
    st.subheader("Laminações cadastradas")

    df = consultar("""
    SELECT id, nome, tipo, largura_cm, comprimento_m, valor_pago,
           folhas_a4, custo_metro, custo_a4, observacoes, ativo
    FROM laminacoes
    ORDER BY id DESC
    """)

    df = adicionar_codigo_visual(df, "LAM")

    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "valor_pago": st.column_config.NumberColumn("Valor pago", format="R$ %.2f"),
            "folhas_a4": st.column_config.NumberColumn("Folhas A4", format="%.0f"),
            "custo_metro": st.column_config.NumberColumn("Custo por metro", format="R$ %.2f"),
            "custo_a4": st.column_config.NumberColumn("Custo por A4", format="R$ %.2f"),
        },
        key="editor_laminacoes",
    )

    c1, c2 = st.columns([2, 1])
    with c1:
        if st.button("Salvar alterações da laminação"):
            executar("DELETE FROM laminacoes")
            for _, r in edited.iterrows():
                nome = str(r.get("nome", "")).strip()
                if nome:
                    largura_cm = n(r.get("largura_cm", 0))
                    comprimento_m = n(r.get("comprimento_m", 0))
                    valor_pago = n(r.get("valor_pago", 0))
                    largura_m = largura_cm / 100
                    area_total_m2 = largura_m * comprimento_m
                    folhas_a4 = area_total_m2 / AREA_A4_M2 if area_total_m2 > 0 else 0
                    custo_metro = valor_pago / comprimento_m if comprimento_m > 0 else 0
                    custo_a4 = valor_pago / folhas_a4 if folhas_a4 > 0 else 0

                    executar("""
                    INSERT INTO laminacoes (
                        nome, tipo, largura_cm, comprimento_m, valor_pago,
                        folhas_a4, custo_metro, custo_a4, observacoes, ativo
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        nome, str(r.get("tipo", "Hot")), largura_cm, comprimento_m, valor_pago,
                        folhas_a4, custo_metro, custo_a4, str(r.get("observacoes", "")),
                        str(r.get("ativo", "Sim"))
                    ))
            st.success("Laminações atualizadas.")
            st.rerun()

    with c2:
        id_excluir = st.number_input("ID para excluir", min_value=0, step=1, key="del_laminacao")
        if st.button("Excluir laminação"):
            if id_excluir > 0:
                executar("DELETE FROM laminacoes WHERE id=?", (int(id_excluir),))
                st.success("Laminação excluída.")
                st.rerun()
            else:
                st.warning("Digite um ID válido.")


def tela_mantas_imas():
    st.title("Mantas / Ímã / Velcro")
    st.write("Cadastre manta ímã adesiva, velcro, manta adesiva e materiais de fixação.")

    st.subheader("Cadastrar material")

    with st.form("form_mantas_imas"):
        c1, c2 = st.columns(2)
        nome = c1.text_input("Nome", placeholder="Ex: Manta Ímã Adesiva A4")
        tipo = c2.selectbox("Tipo", ["Ímã", "Velcro", "Manta adesiva", "Manta imantada", "Fixação", "Outro"])

        c3, c4 = st.columns(2)
        valor_pacote = c3.number_input("Valor do pacote", min_value=0.0, value=0.0, step=0.01, format="%.2f")
        quantidade_pacote = c4.number_input("Quantidade no pacote", min_value=1.0, value=1.0, step=1.0, format="%.0f")

        custo_unitario = valor_pacote / max(quantidade_pacote, 1)
        st.metric("Custo unitário / A4", real(custo_unitario))

        c5, c6 = st.columns(2)
        observacoes = c5.text_input("Observação", placeholder="Ex: pacote com 5 folhas A4")
        ativo = c6.selectbox("Ativo?", ["Sim", "Não"], key="ativo_mantas_imas")

        if st.form_submit_button("Salvar material"):
            if not nome.strip():
                st.error("Digite o nome do material.")
            else:
                executar("""
                INSERT INTO mantas_imas (
                    nome, tipo, valor_pacote, quantidade_pacote,
                    custo_unitario, observacoes, ativo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    nome, tipo, valor_pacote, quantidade_pacote,
                    custo_unitario, observacoes, ativo
                ))
                st.success("Material salvo com sucesso.")
                st.rerun()

    st.divider()
    st.subheader("Materiais cadastrados")

    df = consultar("""
    SELECT id, nome, tipo, valor_pacote, quantidade_pacote,
           custo_unitario, observacoes, ativo
    FROM mantas_imas
    ORDER BY id DESC
    """)

    df = adicionar_codigo_visual(df, "MNT")

    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "valor_pacote": st.column_config.NumberColumn("Valor pacote", format="R$ %.2f"),
            "custo_unitario": st.column_config.NumberColumn("Custo unitário", format="R$ %.2f"),
        },
        key="editor_mantas_imas",
    )

    c1, c2 = st.columns([2, 1])
    with c1:
        if st.button("Salvar alterações de mantas / ímãs"):
            executar("DELETE FROM mantas_imas")
            for _, r in edited.iterrows():
                nome = str(r.get("nome", "")).strip()
                if nome:
                    valor = n(r.get("valor_pacote", 0))
                    qtd = max(n(r.get("quantidade_pacote", 1), 1), 1)
                    custo = valor / qtd
                    executar("""
                    INSERT INTO mantas_imas (
                        nome, tipo, valor_pacote, quantidade_pacote,
                        custo_unitario, observacoes, ativo
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        nome, str(r.get("tipo", "Ímã")), valor, qtd,
                        custo, str(r.get("observacoes", "")), str(r.get("ativo", "Sim"))
                    ))
            st.success("Materiais atualizados.")
            st.rerun()

    with c2:
        id_excluir = st.number_input("ID para excluir", min_value=0, step=1, key="del_mantas_imas")
        if st.button("Excluir material"):
            if id_excluir > 0:
                executar("DELETE FROM mantas_imas WHERE id=?", (int(id_excluir),))
                st.success("Material excluído.")
                st.rerun()
            else:
                st.warning("Digite um ID válido.")


def tela_equipamentos():
    st.title("Equipamentos")
    st.write("Cadastre equipamentos, energia, desgaste e custo por minuto.")

    st.subheader("Cadastrar equipamento")

    with st.form("form_equipamento"):
        nome = st.text_input("Nome do equipamento")

        c1, c2, c3 = st.columns(3)
        valor_pago = c1.number_input("Valor pago", min_value=0.0, step=0.01, format="%.2f")
        vida = c2.number_input("Vida útil em meses", min_value=1.0, value=36.0, step=1.0)
        producao = c3.number_input("Produção mensal estimada", min_value=1.0, value=500.0, step=1.0)

        c4, c5, c6 = st.columns(3)
        usa_energia = c4.selectbox("Usa energia?", ["Sim", "Não"])
        potencia = c5.number_input("Potência (W)", min_value=0.0, value=0.0, step=1.0)
        ativo = c6.selectbox("Ativo?", ["Sim", "Não"])

        custo_kwh = n(obter_config("custo_kwh", "1.00"), 1)
        desgaste = valor_pago / max(vida, 1) / max(producao, 1)
        energia_min = (potencia / 1000) * custo_kwh / 60 if usa_energia == "Sim" else 0
        custo_minuto = desgaste + energia_min

        r1, r2, r3 = st.columns(3)
        r1.metric("Desgaste por uso", real(desgaste))
        r2.metric("Energia por minuto", real(energia_min))
        r3.metric("Custo por minuto", real(custo_minuto))

        if st.form_submit_button("Salvar equipamento"):
            if not nome.strip():
                st.error("Coloque o nome do equipamento.")
            else:
                executar("""
                INSERT INTO equipamentos(
                    nome, valor_pago, vida_util_meses, producao_mensal,
                    potencia_w, usa_energia, ativo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (nome, valor_pago, vida, producao, potencia, usa_energia, ativo))
                st.success("Equipamento salvo.")
                st.rerun()

    st.divider()
    st.subheader("Equipamentos cadastrados")

    df = consultar("SELECT * FROM equipamentos ORDER BY id DESC")

    if not df.empty:
        custo_kwh = n(obter_config("custo_kwh", "1.00"), 1)
        df["desgaste_uso"] = df.apply(
            lambda r: n(r["valor_pago"]) / max(n(r["vida_util_meses"], 1), 1) / max(n(r["producao_mensal"], 1), 1),
            axis=1,
        )
        df["energia_minuto"] = df.apply(
            lambda r: ((n(r["potencia_w"]) / 1000) * custo_kwh / 60) if str(r["usa_energia"]) == "Sim" else 0,
            axis=1,
        )
        df["custo_minuto_total"] = df["desgaste_uso"] + df["energia_minuto"]

    df = adicionar_codigo_visual(df, "EQP")

    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "valor_pago": st.column_config.NumberColumn("Valor pago", format="R$ %.2f"),
            "desgaste_uso": st.column_config.NumberColumn("Desgaste/uso", format="R$ %.2f"),
            "energia_minuto": st.column_config.NumberColumn("Energia/min", format="R$ %.2f"),
            "custo_minuto_total": st.column_config.NumberColumn("Custo/min total", format="R$ %.2f"),
        },
        key="editor_equipamentos",
    )

    c1, c2 = st.columns([2, 1])
    with c1:
        if st.button("Salvar alterações dos equipamentos"):
            executar("DELETE FROM equipamentos")
            for _, r in edited.iterrows():
                if str(r.get("nome", "")).strip():
                    executar("""
                    INSERT INTO equipamentos(
                        nome, valor_pago, vida_util_meses, producao_mensal,
                        potencia_w, usa_energia, ativo
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        r.get("nome", ""), n(r.get("valor_pago", 0)),
                        max(n(r.get("vida_util_meses", 1), 1), 1),
                        max(n(r.get("producao_mensal", 1), 1), 1),
                        n(r.get("potencia_w", 0)), str(r.get("usa_energia", "Sim")),
                        str(r.get("ativo", "Sim"))
                    ))
            st.success("Equipamentos atualizados.")
            st.rerun()

    with c2:
        del_id = st.number_input("ID para excluir", min_value=0, step=1, key="del_eq")
        if st.button("Excluir equipamento"):
            if del_id > 0:
                executar("DELETE FROM equipamentos WHERE id=?", (int(del_id),))
                st.success("Equipamento excluído.")
                st.rerun()
            else:
                st.warning("Digite um ID válido.")



def seletor_insumo(linha):
    categorias = ["Todas"] + categorias_ativas()
    c1, c2, c3 = st.columns([2, 4, 1.2])
    categoria = c1.selectbox("Categoria", categorias, key=f"cat_ins_{linha}")

    if categoria == "Todas":
        df = consultar("SELECT * FROM insumos WHERE ativo='Sim' ORDER BY categoria, nome")
    else:
        df = consultar("SELECT * FROM insumos WHERE ativo='Sim' AND categoria=? ORDER BY nome", (categoria,))

    if df.empty:
        c2.selectbox("Insumo", ["Nenhum"], key=f"insumo_{linha}")
        c3.number_input("Qtd", min_value=0.0, value=0.0, key=f"qtd_ins_{linha}")
        return None

    opcoes = ["Nenhum"]
    mapa = {}

    for _, r in df.iterrows():
        custo = custo_insumo(r["valor_pacote"], r["quantidade_pacote"])
        label = f"{r['nome']} — {r['categoria']} — {real(custo)}"
        opcoes.append(label)
        mapa[label] = {"nome": r["nome"], "categoria": r["categoria"], "custo_unitario": custo}

    escolhido = c2.selectbox("Insumo", opcoes, key=f"insumo_{linha}")
    qtd = c3.number_input(
        "Qtd",
        min_value=0.0,
        value=1.0 if escolhido != "Nenhum" else 0.0,
        step=1.0,
        key=f"qtd_ins_{linha}",
    )

    if escolhido == "Nenhum" or qtd == 0:
        return None

    item = mapa[escolhido]
    item["qtd"] = qtd
    item["total"] = item["custo_unitario"] * qtd
    return item


def seletor_tinta(linha):
    df = consultar("SELECT * FROM tintas WHERE ativo='Sim' ORDER BY nome")
    c1, c2 = st.columns([4, 1.2])

    if df.empty:
        c1.selectbox("Tinta", ["Nenhuma"], key=f"tinta_{linha}")
        c2.number_input("Qtd", min_value=0.0, value=0.0, key=f"qtd_tinta_{linha}")
        return None

    opcoes = ["Nenhuma"]
    mapa = {}

    for _, r in df.iterrows():
        custo = custo_tinta(r["valor_kit"], r["rendimento_impressoes"])
        label = f"{r['nome']} — {real(custo)} por impressão"
        opcoes.append(label)
        mapa[label] = {"nome": r["nome"], "custo_unitario": custo}

    escolhido = c1.selectbox("Tinta", opcoes, key=f"tinta_{linha}")
    qtd = c2.number_input(
        "Qtd",
        min_value=0.0,
        value=1.0 if escolhido != "Nenhuma" else 0.0,
        step=1.0,
        key=f"qtd_tinta_{linha}",
    )

    if escolhido == "Nenhuma" or qtd == 0:
        return None

    item = mapa[escolhido]
    item["qtd"] = qtd
    item["total"] = item["custo_unitario"] * qtd
    return item




def embalagens_ativas():
    """Busca embalagens cadastradas para usar na precificação."""
    try:
        df = consultar("""
        SELECT id, nome, categoria, valor_pacote, quantidade_pacote, ativo
        FROM insumos
        WHERE ativo='Sim' AND (
            LOWER(categoria) LIKE '%embalagem%'
            OR LOWER(categoria) LIKE '%sacola%'
            OR LOWER(categoria) LIKE '%caixa%'
            OR LOWER(categoria) LIKE '%envelope%'
        )
        ORDER BY categoria, nome
        """)
        return df
    except Exception:
        return pd.DataFrame()


def seletor_embalagem_precificacao(linha):
    df = embalagens_ativas()

    c1, c2, c3 = st.columns([4, 2, 1.2])

    if df.empty:
        c1.selectbox("Embalagem", ["Nenhuma embalagem cadastrada"], key=f"emb_prec_{linha}")
        c2.text_input("Categoria", value="", disabled=True, key=f"emb_cat_{linha}")
        c3.number_input("Qtd", min_value=0.0, value=0.0, key=f"emb_qtd_{linha}")
        return None

    opcoes = ["Nenhuma"]
    mapa = {}

    for _, r in df.iterrows():
        custo = custo_insumo(r["valor_pacote"], r["quantidade_pacote"])
        label = f"{r['nome']} — {r['categoria']} — {real(custo)}"
        opcoes.append(label)
        mapa[label] = {
            "nome": r["nome"],
            "categoria": r["categoria"],
            "custo_unitario": custo,
        }

    escolhido = c1.selectbox("Embalagem", opcoes, key=f"emb_prec_{linha}")

    if escolhido == "Nenhuma":
        c2.text_input("Categoria", value="", disabled=True, key=f"emb_cat_{linha}")
        c3.number_input("Qtd", min_value=0.0, value=0.0, key=f"emb_qtd_{linha}")
        return None

    item = mapa[escolhido]

    c2.text_input("Categoria", value=item["categoria"], disabled=True, key=f"emb_cat_{linha}")

    qtd = c3.number_input(
        "Qtd",
        min_value=0.0,
        value=1.0,
        step=1.0,
        key=f"emb_qtd_{linha}",
    )

    if qtd <= 0:
        return None

    item["qtd"] = qtd
    item["total"] = item["custo_unitario"] * qtd
    return item


def tela_produtos():
    st.title("Produtos / Precificação")
    c1, c2, c3 = st.columns([3, 2, 1])
    nome = c1.text_input("Nome do produto")
    categoria_produto = c2.text_input("Categoria do produto")
    ativo = c3.selectbox("Ativo?", ["Sim", "Não"])
    favorito = st.checkbox("⭐ Marcar como favorito", value=False)

    foto_upload = st.file_uploader("Foto do produto", type=["png", "jpg", "jpeg", "webp"])
    descricao_catalogo = st.text_area("Descrição para catálogo público", placeholder="Texto curto que o cliente verá no catálogo.")

    qtd_por_lote = st.number_input("Quantidade produzida por folha/lote", min_value=1.0, value=1.0, step=1.0)

    st.subheader("Itens utilizados no produto")
    receita = []
    custo_insumos_total = 0.0

    for linha in range(1, 11):
        item = seletor_insumo(linha)
        if item:
            receita.append(item)
            custo_insumos_total += item["total"]

    st.subheader("Tintas usadas")
    tintas = []
    custo_tintas_total = 0.0

    for linha in range(1, 2):
        item = seletor_tinta(linha)
        if item:
            tintas.append(item)
            custo_tintas_total += item["total"]

    st.subheader("Embalagens utilizadas")

    embalagens_usadas = []
    custo_embalagens_total = 0.0

    usa_embalagens = st.checkbox("Vai utilizar embalagens neste produto?", value=False)

    if usa_embalagens:
        qtd_linhas_embalagens = st.number_input(
            "Quantidade de embalagens diferentes",
            min_value=1,
            max_value=10,
            value=1,
            step=1,
            key="qtd_linhas_embalagens",
        )

        for linha_emb in range(1, int(qtd_linhas_embalagens) + 1):
            item_emb = seletor_embalagem_precificacao(linha_emb)

            if item_emb:
                embalagens_usadas.append(item_emb)
                custo_embalagens_total += item_emb["total"]

    else:
        st.caption("Marque a opção acima se quiser somar embalagens no custo do produto.")


    st.subheader("Equipamentos usados")
    df_eq = consultar("SELECT * FROM equipamentos WHERE ativo='Sim' ORDER BY nome")
    tempo_min = st.number_input("Tempo de produção do lote em minutos", min_value=0.0, value=10.0, step=1.0)

    equipamentos = []
    custo_equip_total = 0.0

    if not df_eq.empty:
        cols = st.columns(3)
        for idx, (_, row) in enumerate(df_eq.iterrows()):
            with cols[idx % 3]:
                usar = st.checkbox(row["nome"], key=f"eq_{row['id']}")
                if usar:
                    custo = custo_equipamento(row, minutos=tempo_min)
                    equipamentos.append({"nome": row["nome"], "custo": custo})
                    custo_equip_total += custo
                    st.caption(real(custo))

    st.subheader("Mão de obra e precificação")
    c1, c2, c3 = st.columns(3)
    valor_hora = c1.number_input("Valor hora Mão de obra", min_value=0.0, value=n(obter_config("valor_hora", "5"), 5), step=0.01, format="%.2f")
    reserva = c2.number_input("Reserva de erro (%)", min_value=0.0, value=n(obter_config("reserva_erro", "5"), 5), step=0.1, format="%.2f")
    margem = c3.number_input("Margem desejada (%)", min_value=0.0, value=n(obter_config("margem_padrao", "50"), 50), step=0.1, format="%.2f")

    custo_mao_obra = tempo_min / 60 * valor_hora
    custo_lote_sem_reserva = custo_insumos_total + custo_embalagens_total + custo_tintas_total + custo_equip_total + custo_mao_obra
    custo_total_lote = custo_lote_sem_reserva * (1 + reserva / 100)
    custo_unitario = custo_total_lote / qtd_por_lote if qtd_por_lote else 0
    preco_sugerido = custo_unitario * (1 + margem / 100)

    preco_escolhido = st.number_input("Preço escolhido por mim", min_value=0.0, value=0.0, step=0.01, format="%.2f")
    preco_final = preco_escolhido if preco_escolhido > 0 else preco_sugerido
    lucro = preco_final - custo_unitario
    margem_real = lucro / preco_final * 100 if preco_final else 0

    st.subheader("Resumo automático")
    r1, r2, r3, r4 = st.columns(4)
    with r1:
        card("Insumos", real(custo_insumos_total))
    with r2:
        card("Tintas", real(custo_tintas_total))
    with r3:
        card("Equipamentos", real(custo_equip_total))
    with r4:
        card("Mão de obra", real(custo_mao_obra))

    r5, r6, r7, r8 = st.columns(4)
    with r5:
        card("Custo unitário", real(custo_unitario))
    with r6:
        card("Preço sugerido", real(preco_sugerido))
    with r7:
        card("Preço escolhido", real(preco_final))
    with r8:
        card("Lucro / Margem", real(lucro), f"{margem_real:.2f}%")

    receita_para_salvar = receita + embalagens_usadas

    if st.button("Salvar produto precificado"):
        if not nome.strip():
            st.error("Coloque o nome do produto.")
        else:
            foto_path = salvar_upload(foto_upload, f"produto_{nome.replace(' ', '_')}") if foto_upload else ""
            executar("""
            INSERT INTO produtos(
                nome, categoria, qtd_por_lote, receita_json, tintas_json,
                equipamentos_json, tempo_min, valor_hora, reserva_erro,
                margem_lucro, custo_insumos, custo_tintas, custo_equipamentos,
                custo_mao_obra, custo_total_lote, custo_unitario, preco_sugerido,
                preco_escolhido, lucro_unitario, margem_real, ativo, foto, favorito, descricao_catalogo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                nome, categoria_produto, qtd_por_lote,
                json.dumps(receita_para_salvar, ensure_ascii=False),
                json.dumps(tintas, ensure_ascii=False),
                json.dumps(equipamentos, ensure_ascii=False),
                tempo_min, valor_hora, reserva, margem,
                custo_insumos_total, custo_tintas_total, custo_equip_total, custo_mao_obra,
                custo_total_lote, custo_unitario, preco_sugerido, preco_final, lucro, margem_real,
                ativo, foto_path, "Sim" if favorito else "Não", descricao_catalogo,
            ))
            st.success("Produto salvo.")
            st.rerun()

    st.subheader("Produtos cadastrados")
    df = consultar("""
    SELECT id, nome, categoria, qtd_por_lote, custo_unitario, preco_sugerido,
           preco_escolhido, lucro_unitario, margem_real, favorito, ativo
    FROM produtos
    ORDER BY id DESC
    """)

    df = adicionar_codigo_visual(df, "PROD")



    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "custo_unitario": st.column_config.NumberColumn("Custo unitário", format="R$ %.2f"),
            "preco_sugerido": st.column_config.NumberColumn("Preço sugerido", format="R$ %.2f"),
            "preco_escolhido": st.column_config.NumberColumn("Preço escolhido", format="R$ %.2f"),
            "lucro_unitario": st.column_config.NumberColumn("Lucro unitário", format="R$ %.2f"),
            "margem_real": st.column_config.NumberColumn("Margem real", format="%.2f%%"),
        },
        key="editor_produtos",
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        if st.button("Salvar alterações dos produtos"):
            for _, r in edited.iterrows():
                antigo = consultar("SELECT preco_escolhido, preco_sugerido FROM produtos WHERE id=?", (int(r["id"]),))
                if not antigo.empty:
                    registrar_historico_preco("Produto", int(r["id"]), r["nome"], "preco_escolhido", antigo.iloc[0]["preco_escolhido"], n(r["preco_escolhido"]), "Alteração manual em Produtos")
                    registrar_historico_preco("Produto", int(r["id"]), r["nome"], "preco_sugerido", antigo.iloc[0]["preco_sugerido"], n(r["preco_sugerido"]), "Alteração manual em Produtos")

                executar("""
                UPDATE produtos
                SET nome=?, categoria=?, qtd_por_lote=?, custo_unitario=?,
                    preco_sugerido=?, preco_escolhido=?, lucro_unitario=?,
                    margem_real=?, favorito=?, ativo=?
                WHERE id=?
                """, (
                    r["nome"], r["categoria"], n(r["qtd_por_lote"]), n(r["custo_unitario"]),
                    n(r["preco_sugerido"]), n(r["preco_escolhido"]), n(r["lucro_unitario"]),
                    n(r["margem_real"]), r.get("favorito", "Não"), r["ativo"], int(r["id"]),
                ))
            st.success("Produtos atualizados.")
            st.rerun()
    with c2:
        del_id = st.number_input("ID para excluir", min_value=0, step=1, key="del_prod")
    with c3:
        st.write("")
        if st.button("Excluir produto") and del_id:
            executar("DELETE FROM produtos WHERE id=?", (int(del_id),))
            st.success("Produto excluído.")
            st.rerun()


    st.divider()
    st.subheader("Ficha completa do produto")

    produtos_ficha = consultar("""
    SELECT id, nome
    FROM produtos
    ORDER BY nome
    """)

    if produtos_ficha.empty:
        st.info("Cadastre um produto para visualizar a ficha completa.")
    else:
        mapa_produtos = {
            f"{codigo_visual('PROD', row['id'])} - {row['nome']}": int(row["id"])
            for _, row in produtos_ficha.iterrows()
        }
        escolhido = st.selectbox("Escolha um produto", list(mapa_produtos.keys()), key="produto_ficha_select")
        mostrar_ficha_produto(mapa_produtos[escolhido])


def tela_orcamentos():
    st.title("Orçamentos")
    st.write("Crie orçamentos vinculados aos clientes cadastrados.")

    clientes = consultar("SELECT id, nome, whatsapp, instagram, cidade FROM clientes WHERE ativo='Sim' ORDER BY nome")
    produtos = consultar("""
    SELECT id, nome, categoria, preco_escolhido, preco_sugerido
    FROM produtos
    WHERE ativo='Sim'
    ORDER BY nome
    """)

    if clientes.empty:
        st.warning("Cadastre um cliente antes de criar um orçamento.")
        return

    lista_clientes = [f"{int(row['id'])} - {row['nome']}" for _, row in clientes.iterrows()]
    st.subheader("Novo orçamento")
    cliente_escolhido = st.selectbox("Cliente", lista_clientes)
    cliente_id = int(cliente_escolhido.split(" - ")[0])
    cliente = clientes[clientes["id"] == cliente_id].iloc[0]

    ccli1, ccli2, ccli3 = st.columns(3)
    with ccli1:
        card("Cliente", cliente["nome"], "Selecionado")
    with ccli2:
        card("WhatsApp", cliente["whatsapp"] or "-", "Contato")
    with ccli3:
        card("Cidade", cliente["cidade"] or "-", "Local")

    st.divider()
    st.subheader("Itens do orçamento")

    if "qtd_itens_orcamento" not in st.session_state:
        st.session_state.qtd_itens_orcamento = 1

    c_add, c_remove, c_info = st.columns([1, 1, 3])
    with c_add:
        if st.button(f"+ Adicionar item {st.session_state.qtd_itens_orcamento + 1}"):
            if st.session_state.qtd_itens_orcamento < 20:
                st.session_state.qtd_itens_orcamento += 1
                st.rerun()
    with c_remove:
        if st.button("− Remover último item"):
            if st.session_state.qtd_itens_orcamento > 1:
                st.session_state.qtd_itens_orcamento -= 1
                st.rerun()
    with c_info:
        st.info(f"Itens adicionados: {st.session_state.qtd_itens_orcamento}")

    modo_manual = True
    if not produtos.empty:
        modo_manual = st.checkbox("Digitar produto manualmente", value=False)
    else:
        st.info("Você ainda não tem produtos cadastrados. O orçamento ficará em modo manual.")

    itens = []
    subtotal = 0.0

    for i in range(int(st.session_state.qtd_itens_orcamento)):
        with st.container(border=True):
            st.markdown(f"### Item {i + 1}")
            if modo_manual:
                c1, c2 = st.columns(2)
                produto = c1.text_input(f"Produto {i + 1}", key=f"orc_produto_manual_{i}")
                categoria = c2.text_input(f"Categoria {i + 1}", key=f"orc_categoria_manual_{i}")
                valor_padrao = 0.0
            else:
                c1, c2 = st.columns(2)
                opcoes = produtos["nome"].tolist()
                produto = c1.selectbox(f"Produto {i + 1}", opcoes, key=f"orc_produto_{i}")
                dados_produto = produtos[produtos["nome"] == produto].iloc[0]
                categoria = str(dados_produto["categoria"] or "")
                preco_escolhido = n(dados_produto["preco_escolhido"])
                preco_sugerido = n(dados_produto["preco_sugerido"])
                valor_padrao = preco_escolhido if preco_escolhido > 0 else preco_sugerido
                c2.text_input(f"Categoria {i + 1}", value=categoria, disabled=True, key=f"orc_categoria_{i}")

            c3, c4, c5, c6 = st.columns(4)
            quantidade = c3.number_input(f"Quantidade {i + 1}", min_value=0.0, value=1.0, step=1.0, key=f"orc_qtd_{i}")
            valor_unitario = c4.number_input(f"Valor unitário {i + 1}", min_value=0.0, value=float(valor_padrao), step=0.50, format="%.2f", key=f"orc_unit_{i}")
            desconto_item = c5.number_input(f"Desconto R$ {i + 1}", min_value=0.0, value=0.0, step=0.50, format="%.2f", key=f"orc_desc_{i}")
            total_item = max((quantidade * valor_unitario) - desconto_item, 0)
            c6.metric("Total", real(total_item))

            subtotal += total_item
            itens.append({
                "produto": produto, "categoria": categoria, "quantidade": quantidade,
                "valor_unitario": valor_unitario, "desconto": desconto_item, "total": total_item,
            })

    st.divider()
    st.subheader("Totais")
    c1, c2, c3, c4 = st.columns(4)
    desconto_geral = c1.number_input("Desconto geral R$", min_value=0.0, value=0.0, step=0.50, format="%.2f")
    frete = c2.number_input("Frete R$", min_value=0.0, value=0.0, step=0.50, format="%.2f")
    total_geral = max(subtotal - desconto_geral + frete, 0)
    c3.metric("Subtotal", real(subtotal))
    c4.metric("Total geral", real(total_geral))

    forma_pagamento = st.selectbox("Forma de pagamento", ["Pix", "Dinheiro", "Cartão de crédito", "Cartão de débito", "Mercado Pago", "Outro"])
    status = st.selectbox("Status", ["Em orçamento", "Aguardando pagamento", "Produção", "Finalizado", "Entregue", "Cancelado"])
    observacoes = st.text_area("Observações do orçamento")

    if st.button("Salvar orçamento"):
        itens_validos = [item for item in itens if str(item["produto"]).strip()]
        if not itens_validos:
            st.error("Adicione pelo menos um produto ao orçamento.")
        else:
            ultimo = executar("""
            INSERT INTO orcamentos(
                cliente_id, cliente_nome, whatsapp, status, forma_pagamento,
                subtotal, desconto, frete, total, observacoes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                int(cliente_id), str(cliente["nome"]), str(cliente["whatsapp"]), status,
                forma_pagamento, subtotal, desconto_geral, frete, total_geral, observacoes,
            ))

            for item in itens_validos:
                executar("""
                INSERT INTO orcamento_itens(
                    orcamento_id, produto, categoria, quantidade,
                    valor_unitario, desconto, total
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    int(ultimo), item["produto"], item["categoria"], item["quantidade"],
                    item["valor_unitario"], item["desconto"], item["total"],
                ))

                if status in ["Produção", "Finalizado", "Entregue"]:
                    executar("""
                    INSERT INTO estoque(data, item, categoria, tipo_movimento, quantidade, valor_unitario, fornecedor, observacoes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        hoje_iso(), item["produto"], item["categoria"], "Saída",
                        item["quantidade"], item["valor_unitario"], "",
                        f"Baixa automática orçamento #{ultimo}",
                    ))

            if status in ["Aguardando pagamento", "Produção", "Finalizado", "Entregue"]:
                executar("""
                INSERT INTO financeiro(data, tipo, descricao, categoria, forma_pagamento, valor, origem, referencia_id, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (hoje_iso(), "Entrada", f"Orçamento #{ultimo} - {cliente['nome']}", "Venda", forma_pagamento, total_geral, "Orçamento", int(ultimo), observacoes))

            garantir_ordem_producao(int(ultimo))
            st.success(f"Orçamento {codigo_visual('ORC', int(ultimo), ano=datetime.now().year)} salvo com sucesso.")
            st.rerun()

    st.divider()
    st.subheader("Orçamentos cadastrados")
    busca_orc = st.text_input("Pesquisar orçamento por cliente, WhatsApp ou status")

    if busca_orc.strip():
        termo = f"%{busca_orc.strip()}%"
        df_orc = consultar("""
        SELECT id, cliente_nome, whatsapp, status, forma_pagamento, subtotal, desconto, frete, total, data_orcamento
        FROM orcamentos
        WHERE cliente_nome LIKE ? OR whatsapp LIKE ? OR status LIKE ?
        ORDER BY id DESC
        """, (termo, termo, termo))
    else:
        df_orc = consultar("""
        SELECT id, cliente_nome, whatsapp, status, forma_pagamento, subtotal, desconto, frete, total, data_orcamento
        FROM orcamentos
        ORDER BY id DESC
        """)

    df_orc = adicionar_codigo_visual(df_orc, "ORC", ano=datetime.now().year)

    st.dataframe(
        df_orc,
        use_container_width=True,
        hide_index=True,
        column_config={
            "subtotal": st.column_config.NumberColumn("Subtotal", format="R$ %.2f"),
            "desconto": st.column_config.NumberColumn("Desconto", format="R$ %.2f"),
            "frete": st.column_config.NumberColumn("Frete", format="R$ %.2f"),
            "total": st.column_config.NumberColumn("Total", format="R$ %.2f"),
        },
    )

    st.subheader("Ver itens / Gerar PDF")
    id_ver = st.number_input("ID do orçamento", min_value=0, step=1, key="id_ver_orcamento")
    if id_ver > 0:
        itens_df = consultar("""
        SELECT produto, categoria, quantidade, valor_unitario, desconto, total
        FROM orcamento_itens
        WHERE orcamento_id = ?
        """, (int(id_ver),))
        st.dataframe(
            itens_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "valor_unitario": st.column_config.NumberColumn("Valor unitário", format="R$ %.2f"),
                "desconto": st.column_config.NumberColumn("Desconto", format="R$ %.2f"),
                "total": st.column_config.NumberColumn("Total", format="R$ %.2f"),
            },
        )

        html = gerar_html_orcamento(int(id_ver))
        if html:
            st.download_button(
                "Baixar orçamento profissional para imprimir/salvar PDF",
                data=html.encode("utf-8"),
                file_name=f"orcamento_{int(id_ver)}.html",
                mime="text/html",
            )

            etiqueta_html = criar_html_etiqueta(int(id_ver))
            if etiqueta_html:
                st.download_button(
                    "Baixar etiqueta do pedido",
                    data=etiqueta_html.encode("utf-8"),
                    file_name=f"etiqueta_{int(id_ver)}.html",
                    mime="text/html",
                )

    st.subheader("Excluir orçamento")
    id_excluir_orc = st.number_input("ID do orçamento para excluir", min_value=0, step=1, key="id_excluir_orcamento")
    if st.button("Excluir orçamento"):
        if id_excluir_orc > 0:
            executar("DELETE FROM orcamento_itens WHERE orcamento_id=?", (int(id_excluir_orc),))
            executar("DELETE FROM orcamentos WHERE id=?", (int(id_excluir_orc),))
            executar("DELETE FROM financeiro WHERE origem='Orçamento' AND referencia_id=?", (int(id_excluir_orc),))
            st.success("Orçamento excluído com sucesso.")
            st.rerun()
        else:
            st.warning("Digite o ID do orçamento.")

def tela_financeiro():
    st.title("Fluxo de Caixa")
    st.write("Controle entradas, saídas, saldo e movimentações. Você pode adicionar, modificar e excluir.")

    with st.form("form_financeiro"):
        c1, c2, c3 = st.columns(3)
        data = c1.text_input("Data", value=hoje_iso())
        tipo = c2.selectbox("Tipo", ["Entrada", "Saída"])
        valor = c3.number_input("Valor", min_value=0.0, step=0.01, format="%.2f")
        descricao = st.text_input("Descrição")
        categoria = st.text_input("Categoria", value="Venda" if tipo == "Entrada" else "Compra")
        forma_pagamento = st.selectbox("Forma de pagamento", ["Pix", "Dinheiro", "Cartão de crédito", "Cartão de débito", "Mercado Pago", "Outro"])
        observacoes = st.text_area("Observações")

        if st.form_submit_button("Salvar movimento"):
            if not descricao.strip():
                st.error("Digite a descrição.")
            else:
                executar("""
                INSERT INTO financeiro(data, tipo, descricao, categoria, forma_pagamento, valor, origem, referencia_id, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (data, tipo, descricao, categoria, forma_pagamento, valor, "Manual", None, observacoes))
                st.success("Movimento salvo.")
                st.rerun()

    df = consultar("SELECT * FROM financeiro ORDER BY data DESC, id DESC")
    entradas = float(df[df["tipo"] == "Entrada"]["valor"].sum()) if not df.empty else 0
    saidas = float(df[df["tipo"] == "Saída"]["valor"].sum()) if not df.empty else 0
    saldo = entradas - saidas

    c1, c2, c3 = st.columns(3)
    with c1:
        card("Entradas", real(entradas))
    with c2:
        card("Saídas", real(saidas))
    with c3:
        card("Saldo", real(saldo))

    if not df.empty:
        graf = df.copy()
        graf["data"] = pd.to_datetime(graf["data"], errors="coerce")
        diario = graf.groupby(["data", "tipo"])["valor"].sum().reset_index()
        pivot = diario.pivot(index="data", columns="tipo", values="valor").fillna(0)
        st.subheader("Entradas e saídas por dia")
        st.line_chart(pivot)

    st.subheader("Movimentos")
    df = adicionar_codigo_visual(df, "FIN")

    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="editor_financeiro",
        column_config={"valor": st.column_config.NumberColumn("Valor", format="R$ %.2f")},
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        if st.button("Salvar modificações do fluxo de caixa"):
            for _, r in edited.iterrows():
                if str(r.get("descricao", "")).strip():
                    if pd.isna(r.get("id")):
                        executar("""
                        INSERT INTO financeiro(data, tipo, descricao, categoria, forma_pagamento, valor, origem, referencia_id, observacoes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (str(r.get("data", hoje_iso())), str(r.get("tipo", "Entrada")), str(r.get("descricao", "")), str(r.get("categoria", "")), str(r.get("forma_pagamento", "")), n(r.get("valor", 0)), "Manual", None, str(r.get("observacoes", ""))))
                    else:
                        executar("""
                        UPDATE financeiro SET data=?, tipo=?, descricao=?, categoria=?, forma_pagamento=?, valor=?, observacoes=? WHERE id=?
                        """, (str(r.get("data", hoje_iso())), str(r.get("tipo", "Entrada")), str(r.get("descricao", "")), str(r.get("categoria", "")), str(r.get("forma_pagamento", "")), n(r.get("valor", 0)), str(r.get("observacoes", "")), int(r["id"])))
            st.success("Fluxo de caixa atualizado.")
            st.rerun()

    with c2:
        id_excluir = st.number_input("ID para excluir movimento", min_value=0, step=1)
    with c3:
        st.write("")
        if st.button("Excluir movimento"):
            if id_excluir > 0:
                executar("DELETE FROM financeiro WHERE id=?", (int(id_excluir),))
                st.success("Movimento excluído.")
                st.rerun()

def tela_estoque():
    st.title("Estoque Inteligente")
    st.write("Controle entradas, saídas e saldo automático. Você pode adicionar, modificar e excluir.")

    with st.form("form_estoque"):
        c1, c2, c3 = st.columns(3)
        data = c1.text_input("Data", value=hoje_iso())
        item = c2.text_input("Item")
        categoria = c3.selectbox("Categoria", categorias_ativas() or ["Outro"])
        c4, c5, c6 = st.columns(3)
        tipo_movimento = c4.selectbox("Movimento", ["Entrada", "Saída"])
        quantidade = c5.number_input("Quantidade", min_value=0.0, step=1.0)
        valor_unitario = c6.number_input("Valor unitário", min_value=0.0, step=0.01, format="%.2f")
        fornecedor = st.text_input("Fornecedor")
        observacoes = st.text_area("Observações")

        if st.form_submit_button("Salvar movimento de estoque"):
            if not item.strip():
                st.error("Digite o item.")
            else:
                executar("""
                INSERT INTO estoque(data, item, categoria, tipo_movimento, quantidade, valor_unitario, fornecedor, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (data, item, categoria, tipo_movimento, quantidade, valor_unitario, fornecedor, observacoes))
                st.success("Movimento salvo.")
                st.rerun()

    df = consultar("SELECT * FROM estoque ORDER BY data DESC, id DESC")
    st.subheader("Saldo por item")
    if df.empty:
        st.info("Ainda não há movimentações de estoque.")
    else:
        resumo = df.copy()
        resumo["qtd_assinada"] = resumo.apply(lambda r: n(r["quantidade"]) if r["tipo_movimento"] == "Entrada" else -n(r["quantidade"]), axis=1)
        saldo = resumo.groupby(["item", "categoria"])["qtd_assinada"].sum().reset_index()
        saldo.columns = ["Item", "Categoria", "Saldo"]
        saldo["Status"] = saldo["Saldo"].apply(lambda x: "Baixo" if x <= 5 else "OK")
        st.dataframe(saldo, use_container_width=True, hide_index=True)

    st.subheader("Movimentos de estoque")
    df = adicionar_codigo_visual(df, "EST")

    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="editor_estoque",
        column_config={"valor_unitario": st.column_config.NumberColumn("Valor unitário", format="R$ %.2f")},
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        if st.button("Salvar modificações do estoque"):
            for _, r in edited.iterrows():
                if str(r.get("item", "")).strip():
                    if pd.isna(r.get("id")):
                        executar("""
                        INSERT INTO estoque(data, item, categoria, tipo_movimento, quantidade, valor_unitario, fornecedor, observacoes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (str(r.get("data", hoje_iso())), str(r.get("item", "")), str(r.get("categoria", "")), str(r.get("tipo_movimento", "Entrada")), n(r.get("quantidade", 0)), n(r.get("valor_unitario", 0)), str(r.get("fornecedor", "")), str(r.get("observacoes", ""))))
                    else:
                        executar("""
                        UPDATE estoque SET data=?, item=?, categoria=?, tipo_movimento=?, quantidade=?, valor_unitario=?, fornecedor=?, observacoes=? WHERE id=?
                        """, (str(r.get("data", hoje_iso())), str(r.get("item", "")), str(r.get("categoria", "")), str(r.get("tipo_movimento", "Entrada")), n(r.get("quantidade", 0)), n(r.get("valor_unitario", 0)), str(r.get("fornecedor", "")), str(r.get("observacoes", "")), int(r["id"])))
            st.success("Estoque atualizado.")
            st.rerun()

    with c2:
        id_excluir = st.number_input("ID para excluir movimento", min_value=0, step=1, key="del_estoque")
    with c3:
        st.write("")
        if st.button("Excluir movimento de estoque"):
            if id_excluir > 0:
                executar("DELETE FROM estoque WHERE id=?", (int(id_excluir),))
                st.success("Movimento excluído.")
                st.rerun()




# ============================================================
# RECURSOS ERP 2.0 - PARTE FINAL
# ============================================================

def obter_whatsapp_limpo():
    numero = obter_config("whatsapp", "")
    return "".join([c for c in str(numero) if c.isdigit()])


def garantir_ordem_producao(orcamento_id):
    """Cria OP automaticamente para orçamento em produção/finalizado/entregue."""
    try:
        existe = consultar("SELECT id FROM ordens_producao WHERE orcamento_id=?", (int(orcamento_id),))
        if not existe.empty:
            return int(existe.iloc[0]["id"])

        orc = consultar("SELECT * FROM orcamentos WHERE id=?", (int(orcamento_id),))
        if orc.empty:
            return None

        o = orc.iloc[0]
        status = str(o["status"])

        if status not in ["Produção", "Finalizado", "Entregue", "ProduÃ§Ã£o"]:
            return None

        itens = consultar("""
        SELECT produto, categoria, quantidade, valor_unitario, desconto, total
        FROM orcamento_itens
        WHERE orcamento_id=?
        """, (int(orcamento_id),))

        itens_lista = itens.to_dict("records") if not itens.empty else []

        materiais = []
        try:
            for _, item in itens.iterrows():
                produto_nome = str(item["produto"])
                prod = consultar("SELECT receita_json, tintas_json, equipamentos_json FROM produtos WHERE nome=?", (produto_nome,))
                if not prod.empty:
                    p = prod.iloc[0]
                    for campo, tipo in [
                        ("receita_json", "Item"),
                        ("tintas_json", "Tinta"),
                        ("equipamentos_json", "Equipamento"),
                    ]:
                        try:
                            dados = json.loads(p[campo] or "[]")
                            for d in dados:
                                materiais.append({
                                    "tipo": tipo,
                                    "nome": d.get("nome", ""),
                                    "categoria": d.get("categoria", ""),
                                    "qtd": d.get("qtd", ""),
                                })
                        except Exception:
                            pass
        except Exception:
            pass

        try:
            data_entrega = (pd.to_datetime(o["data_orcamento"], errors="coerce") + pd.to_timedelta(int(n(obter_config("validade_orcamento", "7"), 7)), unit="D")).date().isoformat()
        except Exception:
            data_entrega = (datetime.now().date() + timedelta(days=7)).isoformat()

        op_id = consultar("SELECT COALESCE(MAX(id),0)+1 AS proximo FROM ordens_producao").iloc[0]["proximo"]
        codigo = codigo_visual("OP", int(op_id), ano=datetime.now().year)

        return executar("""
        INSERT INTO ordens_producao(
            orcamento_id, codigo, cliente_nome, whatsapp, data_entrega,
            status, itens_json, materiais_json, observacoes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            int(orcamento_id),
            codigo,
            str(o["cliente_nome"]),
            str(o["whatsapp"]),
            str(data_entrega),
            "Aguardando",
            json.dumps(itens_lista, ensure_ascii=False),
            json.dumps(materiais, ensure_ascii=False),
            str(o["observacoes"] or ""),
        ))

    except Exception:
        return None


def criar_html_etiqueta(orcamento_id):
    orc = consultar("SELECT * FROM orcamentos WHERE id=?", (int(orcamento_id),))
    if orc.empty:
        return ""

    o = orc.iloc[0]
    codigo = codigo_visual("ORC", int(orcamento_id), ano=datetime.now().year)
    empresa = obter_config("nome_empresa", EMPRESA)

    qr_texto = f"{codigo} - {o['cliente_nome']} - {o['whatsapp']}"
    try:
        import urllib.parse
        qr_url = "https://api.qrserver.com/v1/create-qr-code/?size=130x130&data=" + urllib.parse.quote(qr_texto)
    except Exception:
        qr_url = ""

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Etiqueta {codigo}</title>
<style>
body {{
    font-family: Arial, sans-serif;
    background: #fff;
    margin: 0;
    padding: 20px;
}}
.etiqueta {{
    width: 90mm;
    min-height: 55mm;
    border: 2px solid #111;
    border-radius: 10px;
    padding: 12px;
    display: flex;
    justify-content: space-between;
    gap: 12px;
}}
h1 {{
    font-size: 16px;
    margin: 0 0 8px;
}}
p {{
    margin: 4px 0;
    font-size: 12px;
}}
.codigo {{
    font-size: 14px;
    font-weight: 800;
    margin-top: 8px;
}}
.qr img {{
    width: 95px;
    height: 95px;
}}
@media print {{
    @page {{ size: auto; margin: 8mm; }}
    button {{ display: none; }}
}}
button {{
    margin-bottom: 12px;
    background: #111;
    color: #fff;
    border: 0;
    border-radius: 8px;
    padding: 10px 14px;
    font-weight: 700;
}}
</style>
</head>
<body>
<button onclick="window.print()">Imprimir etiqueta</button>
<div class="etiqueta">
    <div>
        <h1>{empresa}</h1>
        <p><b>Cliente:</b> {o['cliente_nome']}</p>
        <p><b>WhatsApp:</b> {o['whatsapp'] or '-'}</p>
        <p><b>Status:</b> {o['status']}</p>
        <p class="codigo">{codigo}</p>
    </div>
    <div class="qr">
        <img src="{qr_url}">
    </div>
</div>
</body>
</html>"""
    return html


def gerar_html_catalogo_publico():
    produtos = consultar("""
    SELECT id, nome, categoria, preco_escolhido, preco_sugerido, foto, ativo, descricao_catalogo
    FROM produtos
    WHERE ativo='Sim'
    ORDER BY categoria, nome
    """)

    empresa = obter_config("nome_empresa", EMPRESA)
    whatsapp = obter_whatsapp_limpo()
    instagram = obter_config("instagram", "")

    cards = ""

    if produtos.empty:
        cards = "<p>Nenhum produto ativo no catálogo no momento.</p>"
    else:
        for _, p in produtos.iterrows():
            preco = n(p["preco_escolhido"]) if n(p["preco_escolhido"]) > 0 else n(p["preco_sugerido"])
            foto_html = ""
            foto = str(p.get("foto", "") or "")

            if foto and Path(foto).exists():
                try:
                    b64 = imagem_base64(foto)
                    ext = Path(foto).suffix.replace(".", "").lower() or "png"
                    foto_html = f'<img class="foto" src="data:image/{ext};base64,{b64}">'
                except Exception:
                    foto_html = '<div class="semfoto">Sophi</div>'
            else:
                foto_html = '<div class="semfoto">Sophi</div>'

            mensagem = f"Olá, tenho interesse no produto {p['nome']} do catálogo da Sophi."
            link_wpp = f"https://wa.me/{whatsapp}?text={mensagem.replace(' ', '%20')}" if whatsapp else "#"
            descricao = str(p.get("descricao_catalogo", "") or "")

            cards += f"""
            <div class="card-produto">
                {foto_html}
                <div class="conteudo">
                    <div class="categoria">{p['categoria'] or ''}</div>
                    <h2>{p['nome']}</h2>
                    <p>{descricao}</p>
                    <div class="preco">{real(preco)}</div>
                    <a href="{link_wpp}" class="botao">Chamar no WhatsApp</a>
                </div>
            </div>
            """

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Catálogo - {empresa}</title>
<style>
body {{
    font-family: Arial, sans-serif;
    background: #f6f6f6;
    margin: 0;
    color: #111;
}}
header {{
    background: #000;
    color: #fff;
    padding: 28px 20px;
    text-align: center;
}}
header h1 {{
    margin: 0;
    font-size: 30px;
}}
header p {{
    margin: 8px 0 0;
    color: #ddd;
}}
.container {{
    max-width: 1100px;
    margin: 24px auto;
    padding: 0 16px;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 18px;
}}
.card-produto {{
    background: #fff;
    border-radius: 18px;
    overflow: hidden;
    box-shadow: 0 10px 28px rgba(0,0,0,.08);
}}
.foto {{
    width: 100%;
    height: 230px;
    object-fit: cover;
}}
.semfoto {{
    height: 230px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #111;
    color: #fff;
    font-size: 34px;
    font-weight: 800;
}}
.conteudo {{
    padding: 18px;
}}
.categoria {{
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #777;
    font-size: 11px;
    margin-bottom: 8px;
}}
h2 {{
    margin: 0 0 8px;
    font-size: 22px;
}}
p {{
    color: #555;
    min-height: 36px;
}}
.preco {{
    font-size: 24px;
    font-weight: 900;
    margin: 16px 0;
}}
.botao {{
    display: block;
    background: #000;
    color: #fff;
    text-decoration: none;
    text-align: center;
    padding: 12px;
    border-radius: 12px;
    font-weight: 800;
}}
footer {{
    text-align: center;
    padding: 25px;
    color: #777;
}}
</style>
</head>
<body>
<header>
    <h1>{empresa}</h1>
    <p>{instagram} • Catálogo de produtos personalizados</p>
</header>
<main class="container">
{cards}
</main>
<footer>Catálogo gerado pelo Sophi ERP.</footer>
</body>
</html>"""
    return html


def mostrar_linha_tempo_cliente(cliente_id):
    cli = consultar("SELECT * FROM clientes WHERE id=?", (int(cliente_id),))
    if cli.empty:
        st.warning("Cliente não encontrado.")
        return

    c = cli.iloc[0]
    orcs = consultar("""
    SELECT id, total, status, data_orcamento
    FROM orcamentos
    WHERE cliente_id=?
    ORDER BY data_orcamento ASC
    """, (int(cliente_id),))

    st.subheader(f"Linha do tempo: {c['nome']}")

    if orcs.empty:
        st.info("Este cliente ainda não possui orçamentos.")
        return

    total_gasto = float(orcs["total"].sum())
    ticket_medio = total_gasto / len(orcs) if len(orcs) else 0
    ultimo = pd.to_datetime(orcs["data_orcamento"], errors="coerce").max()

    dias_ultimo = ""
    try:
        dias = (datetime.now() - ultimo.to_pydatetime()).days
        dias_ultimo = f"Último pedido há {dias} dias"
    except Exception:
        dias_ultimo = "Último pedido sem data"

    t1, t2, t3 = st.columns(3)
    with t1:
        card("Total gasto", real(total_gasto))
    with t2:
        card("Ticket médio", real(ticket_medio))
    with t3:
        card("Pedidos", str(len(orcs)), dias_ultimo)

    for idx, row in orcs.iterrows():
        codigo = codigo_visual("ORC", int(row["id"]), ano=datetime.now().year)
        st.write(f"✔ **{codigo}** — {row['status']} — {real(row['total'])} — {row['data_orcamento']}")









def tela_catalogo():
    st.title("Catálogo público")
    st.write("Configure o catálogo profissional que seus clientes acessam pelo link público.")

    link_publico = link_catalogo_publico()

    c1, c2 = st.columns([2, 1])
    with c1:
        st.success("Seu catálogo público está ativo.")
        st.code(link_publico)
    with c2:
        st.link_button("Abrir catálogo", link_publico)

    st.divider()
    st.subheader("Personalização do catálogo")

    logo_atual = obter_config("logo_path", "")
    if logo_atual and Path(logo_atual).exists():
        st.caption("Logo atual")
        st.image(logo_atual, width=120)

    logo_upload = st.file_uploader("Trocar logo do catálogo", type=["png", "jpg", "jpeg", "webp"], key="logo_catalogo_upload")
    if logo_upload is not None:
        caminho = salvar_upload(logo_upload, "logo_sophi")
        salvar_config("logo_path", caminho)
        st.success("Logo do catálogo atualizada.")
        st.rerun()

    with st.form("form_catalogo_profissional"):
        c1, c2 = st.columns(2)

        titulo = c1.text_input(
            "Título do catálogo",
            value=obter_config("catalogo_titulo", obter_config("nome_empresa", EMPRESA)),
        )

        slogan = c2.text_input(
            "Slogan",
            value=obter_config("catalogo_slogan", "Eternizando momentos com presentes personalizados"),
        )

        descricao = st.text_area(
            "Texto de apresentação",
            value=obter_config("catalogo_descricao", "Confira nossos produtos personalizados e chame no WhatsApp para fazer seu pedido."),
        )

        c3, c4 = st.columns(2)

        cor = c3.text_input(
            "Cor principal",
            value=obter_config("catalogo_cor", "#000000"),
            help="Exemplo: #000000, #D8A7B1, #F4C2C2",
        )

        texto_botao = c4.text_input(
            "Texto do botão WhatsApp",
            value=obter_config("catalogo_botao", "Chamar no WhatsApp"),
        )

        aviso = st.text_input(
            "Aviso no rodapé",
            value=obter_config("catalogo_aviso", "Valores sujeitos à confirmação conforme personalização, material e prazo."),
        )

        if st.form_submit_button("Salvar catálogo"):
            salvar_config("catalogo_titulo", titulo)
            salvar_config("catalogo_slogan", slogan)
            salvar_config("catalogo_descricao", descricao)
            salvar_config("catalogo_cor", cor)
            salvar_config("catalogo_botao", texto_botao)
            salvar_config("catalogo_aviso", aviso)
            st.success("Configurações do catálogo salvas.")
            st.rerun()

    st.divider()
    st.subheader("Produtos ativos no catálogo")

    produtos = consultar("""
    SELECT id, nome, categoria, preco_escolhido, preco_sugerido, ativo, descricao_catalogo
    FROM produtos
    WHERE ativo='Sim'
    ORDER BY categoria, nome
    """)

    if produtos.empty:
        st.info("Nenhum produto ativo no catálogo.")
    else:
        produtos = adicionar_codigo_visual(produtos, "PROD")
        st.dataframe(formatar_valores_tabela(produtos), use_container_width=True, hide_index=True)

    st.info("Para editar foto, descrição e preço de cada item, vá em Produtos / Precificação.")


def tela_ordens_producao():
    st.title("Ordem de Produção")
    st.write("Controle o que precisa produzir sem precisar abrir cada orçamento.")

    st.subheader("Criar OPs pendentes automaticamente")

    if st.button("Buscar orçamentos em produção e criar OP"):
        orcs = consultar("""
        SELECT id FROM orcamentos
        WHERE status IN ('Produção', 'ProduÃ§Ã£o', 'Finalizado', 'Entregue')
        ORDER BY id DESC
        """)
        criadas = 0
        for _, row in orcs.iterrows():
            antes = consultar("SELECT id FROM ordens_producao WHERE orcamento_id=?", (int(row["id"]),))
            garantir_ordem_producao(int(row["id"]))
            depois = consultar("SELECT id FROM ordens_producao WHERE orcamento_id=?", (int(row["id"]),))
            if antes.empty and not depois.empty:
                criadas += 1
        st.success(f"{criadas} ordem(ns) de produção criada(s).")
        st.rerun()

    st.divider()

    df = consultar("""
    SELECT id, codigo, orcamento_id, cliente_nome, whatsapp, data_criacao, data_entrega, status, observacoes
    FROM ordens_producao
    ORDER BY id DESC
    """)

    st.subheader("Ordens cadastradas")

    if df.empty:
        st.info("Ainda não há ordens de produção.")
    else:
        edited = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            key="editor_ordens_producao",
            column_config={
                "status": st.column_config.SelectboxColumn(
                    "Status",
                    options=["Aguardando", "Produzindo", "Finalizado", "Entregue", "Cancelado"],
                )
            },
        )

        c1, c2 = st.columns([2, 1])
        with c1:
            if st.button("Salvar alterações das OPs"):
                for _, r in edited.iterrows():
                    if str(r.get("codigo", "")).strip():
                        executar("""
                        UPDATE ordens_producao
                        SET status=?, data_entrega=?, observacoes=?
                        WHERE id=?
                        """, (
                            str(r.get("status", "Aguardando")),
                            str(r.get("data_entrega", "")),
                            str(r.get("observacoes", "")),
                            int(r["id"]),
                        ))
                st.success("Ordens atualizadas.")
                st.rerun()

        with c2:
            id_excluir = st.number_input("ID para excluir OP", min_value=0, step=1, key="del_op")
            if st.button("Excluir OP"):
                if id_excluir > 0:
                    executar("DELETE FROM ordens_producao WHERE id=?", (int(id_excluir),))
                    st.success("OP excluída.")
                    st.rerun()

    st.divider()
    st.subheader("Ficha da OP")

    id_op = st.number_input("ID da OP para visualizar", min_value=0, step=1, key="ver_op")
    if id_op > 0:
        op = consultar("SELECT * FROM ordens_producao WHERE id=?", (int(id_op),))
        if op.empty:
            st.warning("OP não encontrada.")
        else:
            o = op.iloc[0]
            c1, c2, c3 = st.columns(3)
            with c1:
                card("OP", o["codigo"])
            with c2:
                card("Cliente", o["cliente_nome"])
            with c3:
                card("Status", o["status"])

            st.write(f"**WhatsApp:** {o['whatsapp'] or '-'}")
            st.write(f"**Entrega:** {o['data_entrega'] or '-'}")
            st.write(f"**Observações:** {o['observacoes'] or '-'}")

            st.markdown("### Produtos")
            try:
                itens = json.loads(o["itens_json"] or "[]")
                if itens:
                    st.dataframe(formatar_valores_tabela(pd.DataFrame(itens)), use_container_width=True, hide_index=True)
                else:
                    st.info("Nenhum item salvo.")
            except Exception:
                st.info("Não foi possível ler os itens.")

            st.markdown("### Materiais necessários")
            try:
                materiais = json.loads(o["materiais_json"] or "[]")
                if materiais:
                    st.dataframe(formatar_valores_tabela(pd.DataFrame(materiais)), use_container_width=True, hide_index=True)
                else:
                    st.info("Nenhum material encontrado automaticamente.")
            except Exception:
                st.info("Não foi possível ler os materiais.")




# ============================================================
# CATÁLOGO PÚBLICO POR LINK
# ============================================================

def detectar_pagina_publica():
    try:
        params = st.query_params
        pagina = str(params.get("pagina", "")).lower().strip()
        if pagina in ["catalogo", "catálogo", "catalog"]:
            return "catalogo"
    except Exception:
        try:
            params = st.experimental_get_query_params()
            pagina = str(params.get("pagina", [""])[0]).lower().strip()
            if pagina in ["catalogo", "catálogo", "catalog"]:
                return "catalogo"
        except Exception:
            pass
    return ""





def link_catalogo_publico():
    try:
        app_url = obter_config("catalogo_link_base", "").strip()
    except Exception:
        app_url = ""

    if app_url:
        if "?pagina=catalogo" in app_url:
            return app_url
        return app_url.rstrip("/") + "/?pagina=catalogo"

    return "https://sophipersonalizadosoficial.streamlit.app/?pagina=catalogo"

def tela_catalogo_publico_cliente():
    empresa = obter_config("catalogo_titulo", obter_config("nome_empresa", EMPRESA))
    slogan = obter_config("catalogo_slogan", "Eternizando momentos com presentes personalizados")
    descricao_topo = obter_config("catalogo_descricao", "Confira nossos produtos personalizados e chame no WhatsApp para fazer seu pedido.")
    aviso = obter_config("catalogo_aviso", "Valores sujeitos à confirmação conforme personalização, material e prazo.")
    cor = obter_config("catalogo_cor", "#000000") or "#000000"
    texto_botao = obter_config("catalogo_botao", "Chamar no WhatsApp") or "Chamar no WhatsApp"
    instagram = obter_config("instagram", "")
    whatsapp = obter_whatsapp_limpo()
    logo = obter_config("logo_path", "")

    logo_html = ""
    if logo and Path(logo).exists():
        try:
            b64 = imagem_base64(logo)
            ext = Path(logo).suffix.replace(".", "").lower() or "png"
            logo_html = f'<img class="catalogo-logo" src="data:image/{ext};base64,{b64}">'
        except Exception:
            logo_html = ""

    st.markdown(
        f"""
        <style>
        .stApp {{ background: #f7f7f7; }}
        .catalogo-hero {{
            background: {cor};
            color: #fff;
            border-radius: 0 0 30px 30px;
            padding: 38px 24px;
            text-align: center;
            margin: -1rem -1rem 30px -1rem;
        }}
        .catalogo-logo {{
            max-width: 155px;
            max-height: 95px;
            object-fit: contain;
            margin-bottom: 16px;
            background: #fff;
            border-radius: 18px;
            padding: 9px;
        }}
        .catalogo-hero h1 {{
            color: #fff !important;
            font-size: 40px !important;
            margin-bottom: 8px;
        }}
        .catalogo-hero p {{
            color: #eee;
            font-size: 15px;
            max-width: 760px;
            margin: 7px auto;
        }}
        .produto-card {{
            background: #fff;
            border-radius: 20px;
            padding: 16px;
            box-shadow: 0 10px 30px rgba(0,0,0,.08);
            border: 1px solid #eee;
            min-height: 100%;
            margin-bottom: 20px;
        }}
        .categoria {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: #777;
            margin-top: 8px;
        }}
        .preco {{
            font-size: 25px;
            font-weight: 900;
            margin: 12px 0;
        }}
        .botao-wpp {{
            display: block;
            background: {cor};
            color: #fff !important;
            padding: 12px 14px;
            border-radius: 12px;
            text-align: center;
            text-decoration: none;
            font-weight: 800;
            margin-top: 12px;
        }}
        .sem-foto {{
            height: 220px;
            background: #111;
            color: #fff;
            display:flex;
            align-items:center;
            justify-content:center;
            border-radius: 14px;
            font-size: 30px;
            font-weight: 900;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="catalogo-hero">
            {logo_html}
            <h1>{empresa}</h1>
            <p><b>{slogan}</b></p>
            <p>{descricao_topo}</p>
            <p>{instagram}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    produtos = consultar("""
    SELECT id, nome, categoria, preco_escolhido, preco_sugerido, foto, ativo, descricao_catalogo
    FROM produtos
    WHERE ativo='Sim'
    ORDER BY categoria, nome
    """)

    if produtos.empty:
        st.info("Nenhum produto disponível no catálogo no momento.")
        st.stop()

    busca = st.text_input("Buscar produto", placeholder="Digite o nome do produto")
    if busca.strip():
        termo = busca.strip().lower()
        produtos = produtos[
            produtos["nome"].astype(str).str.lower().str.contains(termo, na=False)
            | produtos["categoria"].astype(str).str.lower().str.contains(termo, na=False)
        ]

    categorias = ["Todas"] + sorted([c for c in produtos["categoria"].dropna().astype(str).unique().tolist() if c.strip()])
    categoria_sel = st.selectbox("Categoria", categorias)

    if categoria_sel != "Todas":
        produtos = produtos[produtos["categoria"].astype(str) == categoria_sel]

    cols = st.columns(3)

    for idx, (_, p) in enumerate(produtos.iterrows()):
        with cols[idx % 3]:
            foto = str(p.get("foto", "") or "")
            preco = n(p["preco_escolhido"]) if n(p["preco_escolhido"]) > 0 else n(p["preco_sugerido"])
            descricao = str(p.get("descricao_catalogo", "") or "")
            codigo = codigo_visual("PROD", int(p["id"]))

            mensagem = f"Olá, tenho interesse no produto {p['nome']} ({codigo}) do catálogo da Sophi."
            link = "#"
            if whatsapp:
                import urllib.parse
                link = f"https://wa.me/{whatsapp}?text={urllib.parse.quote(mensagem)}"

            st.markdown('<div class="produto-card">', unsafe_allow_html=True)

            if foto and Path(foto).exists():
                st.image(foto, use_container_width=True)
            else:
                st.markdown('<div class="sem-foto">Sophi</div>', unsafe_allow_html=True)

            st.markdown(
                f"""
                <div class="categoria">{p['categoria'] or ''}</div>
                <h3>{p['nome']}</h3>
                <p>{descricao}</p>
                <div class="preco">{real(preco)}</div>
                <a class="botao-wpp" href="{link}" target="_blank">{texto_botao}</a>
                """,
                unsafe_allow_html=True,
            )

            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        f"""
        <div style="text-align:center;color:#777;margin-top:35px;font-size:13px;">
            {aviso}
        </div>
        """,
        unsafe_allow_html=True,
    )

# ============================================================
# LOGIN / SEGURANÇA
# ============================================================

def obter_credenciais_login():
    try:
        login = st.secrets.get("login", {})
        usuario = str(login.get("usuario", "")).strip()
        senha = str(login.get("senha", "")).strip()
        return usuario, senha
    except Exception:
        return "", ""


def tela_login():
    st.markdown(
        """
        <style>
        .login-card {
            max-width: 430px;
            margin: 7vh auto 0 auto;
            background: #ffffff;
            border: 1px solid #e9e9e9;
            border-radius: 22px;
            padding: 34px 32px;
            box-shadow: 0 18px 45px rgba(0,0,0,0.08);
            text-align: center;
        }
        .login-title {
            font-family: 'Playfair Display', serif;
            font-size: 38px;
            font-weight: 700;
            color: #000000;
            margin-bottom: 4px;
        }
        .login-subtitle {
            font-size: 12px;
            letter-spacing: 2.2px;
            text-transform: uppercase;
            color: #777777;
            margin-bottom: 18px;
        }
        .login-caption {
            font-size: 13px;
            color: #777777;
            margin-bottom: 22px;
        }
        </style>
        <div class="login-card">
            <div class="login-title">Sophi ERP</div>
            <div class="login-subtitle">Personalizados Oficial</div>
            <div class="login-caption">Acesso restrito ao sistema</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    usuario_correto, senha_correta = obter_credenciais_login()

    if not usuario_correto or not senha_correta:
        st.error("Login ainda não configurado. Configure os Secrets do Streamlit com [login], usuario e senha.")
        st.stop()

    with st.form("form_login"):
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar")

        if entrar:
            if usuario.strip() == usuario_correto and senha.strip() == senha_correta:
                st.session_state["autenticado"] = True
                st.session_state["usuario_logado"] = usuario.strip()
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")


def exigir_login():
    if "autenticado" not in st.session_state:
        st.session_state["autenticado"] = False

    if not st.session_state["autenticado"]:
        tela_login()
        st.stop()


def botao_sair():
    st.sidebar.divider()
    st.sidebar.caption(f"Usuário: {st.session_state.get('usuario_logado', '')}")
    if st.sidebar.button("Sair"):
        st.session_state["autenticado"] = False
        st.session_state["usuario_logado"] = ""
        st.rerun()

# =========================
# APP
# =========================

# Página pública do catálogo: não exige login.
if detectar_pagina_publica() == "catalogo":
    criar_banco()
    st.set_page_config(
        page_title="Catálogo Sophi",
        page_icon="🛍️",
        layout="wide",
    )
    tela_catalogo_publico_cliente()
    st.stop()

criar_banco()

# Se você já tem categorias no banco, marca como inicializadas para não recriar depois que excluir.
try:
    _flag_cat = consultar("SELECT valor FROM configuracoes WHERE chave='categorias_iniciais_criadas'")
    if _flag_cat.empty:
        salvar_config("categorias_iniciais_criadas", "Sim")
except Exception:
    pass

# Corrige configurações antigas que ficaram salvas com muitos zeros.
for _chave, _padrao, _limite in [
    ("valor_hora", "5", 100),
    ("margem_padrao", "50", 500),
    ("reserva_erro", "5", 100),
    ("custo_kwh", "250", 100000),
    ("validade_orcamento", "7", 365),
]:
    try:
        if n(obter_config(_chave, _padrao), 0) > _limite:
            salvar_config(_chave, _padrao)
    except Exception:
        salvar_config(_chave, _padrao)

icone_config = obter_config("logo_path", "")
icone_app = icone_config if icone_config and Path(icone_config).exists() else criar_icone_padrao()

st.set_page_config(
    page_title="Sophi ERP",
    page_icon=icone_app,
    layout="wide",
)

# Ícone para navegador e atalho do iPhone/iOS.
try:
    _icon_path = Path(icone_app)
    if _icon_path.exists():
        _b64_icon = base64.b64encode(_icon_path.read_bytes()).decode("utf-8")
        st.markdown(
            f"""
            <link rel="apple-touch-icon" href="data:image/png;base64,{_b64_icon}">
            <link rel="icon" type="image/png" href="data:image/png;base64,{_b64_icon}">
            <meta name="apple-mobile-web-app-title" content="Sophi ERP">
            <meta name="apple-mobile-web-app-capable" content="yes">
            """,
            unsafe_allow_html=True,
        )
except Exception:
    pass

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: #ffffff; color: #111111; }
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #000000 0%, #151515 100%); }
section[data-testid="stSidebar"] * { color: #ffffff !important; }
h1 { font-family: 'Playfair Display', serif; font-size: 42px !important; color: #000000; }
.stButton button { background: #000000; color: #ffffff; border: none; border-radius: 10px; padding: 0.55rem 1rem; font-weight: 600; }
.card { background: #ffffff; border: 1px solid #e8e8e8; border-radius: 18px; padding: 18px 20px; box-shadow: 0 8px 24px rgba(0,0,0,0.045); min-height: 105px; }
.card-title { color: #777777; font-size: 13px; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 8px; }
.card-value { color: #000000; font-size: 26px; font-weight: 800; }
.card-subtitle { color: #777777; font-size: 12px; margin-top: 6px; }
[data-testid="stMetricValue"] { color: #000000 !important; }
</style>
""", unsafe_allow_html=True)

logo = obter_config("logo_path", "")
if logo and Path(logo).exists():
    st.sidebar.image(logo, width=120)

exigir_login()

st.sidebar.markdown("""
<div style="font-family:'Playfair Display',serif;font-size:30px;line-height:1;margin-top:10px;">
    Sophi
</div>
<div style="font-size:12px;letter-spacing:2.5px;text-transform:uppercase;margin-bottom:24px;">
    Personalizados Oficial
</div>
""", unsafe_allow_html=True)

botao_sair()

menu = st.sidebar.radio(
    "Menu",
    [
        "Dashboard",
        "Clientes",
        "Orçamentos",
        "Produtos / Precificação",
        "Papéis",
        "Embalagens",
        "Laminação",
        "Mantas / Ímã / Velcro",
        "Insumos",
        "Tintas",
        "Equipamentos",
        "Estoque",
        "Fluxo de Caixa",
        "Categorias",
        "Catálogo público",
        "Configurações",
    ],
)


if menu == "Dashboard":
    tela_inicio()
elif menu == "Clientes":
    tela_clientes()
elif menu == "Orçamentos":
    tela_orcamentos()
elif menu == "Ordem de Produção":
    tela_ordens_producao()
elif menu == "Produtos / Precificação":
    tela_produtos()
elif menu == "Papéis":
    tela_cadastro_por_categoria("Papéis", "Papel")
elif menu == "Embalagens":
    tela_embalagens()
elif menu == "Laminação":
    tela_laminacao()
elif menu == "Mantas / Ímã / Velcro":
    tela_mantas_imas()
elif menu == "Insumos":
    tela_insumos()
elif menu == "Tintas":
    tela_tintas()
elif menu == "Equipamentos":
    tela_equipamentos()
elif menu == "Estoque":
    tela_estoque()
elif menu == "Fluxo de Caixa":
    tela_financeiro()
elif menu == "Categorias":
    tela_categorias()
elif menu == "Catálogo público":
    tela_catalogo()
elif menu == "Configurações":
    tela_configuracoes()
