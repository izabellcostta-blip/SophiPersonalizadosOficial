from __future__ import annotations

import base64
import json
import sqlite3
import shutil
import html
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

try:
    from supabase import create_client
except Exception:
    create_client = None


EMPRESA = "Sophi Personalizados Oficial"
# Usa o banco existente sem trocar maiúscula/minúscula.
# Isso evita o Streamlit/Linux criar um banco vazio só porque o arquivo se chama Sophi_erp.db.
DB_PATH_MIN = Path("banco") / "sophi_erp.db"
DB_PATH_MAI = Path("banco") / "Sophi_erp.db"

# Banco fixo e seguro:
# se o banco com S maiúsculo já existir, usa ele; senão usa o minúsculo.
# Isso evita abrir banco vazio por diferença de maiúscula/minúscula.
if DB_PATH_MAI.exists():
    DB_PATH = DB_PATH_MAI
else:
    DB_PATH = DB_PATH_MIN

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
DB_PATH.parent.mkdir(exist_ok=True)



# ============================================================
# SINCRONIZAÇÃO DO BANCO NA NUVEM - SUPABASE STORAGE
# ============================================================
# Objetivo: manter o app idêntico, mas impedir que os dados sumam
# quando o Streamlit Cloud reiniciar. O app continua usando SQLite,
# porém baixa o banco da nuvem ao abrir e envia uma cópia atualizada
# após alterações importantes.

SUPABASE_BUCKET_PADRAO = "sophi-erp"
SUPABASE_DB_ARQUIVO = "Sophi_erp.db"
_SYNC_NUVEM_ATIVO = False
_ULTIMO_UPLOAD_NUVEM = None


def supabase_configurado():
    try:
        return bool(st.secrets.get("SUPABASE_URL")) and bool(st.secrets.get("SUPABASE_KEY")) and create_client is not None
    except Exception:
        return False


def cliente_supabase():
    if not supabase_configurado():
        return None
    try:
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except Exception:
        return None


def bucket_supabase():
    try:
        return st.secrets.get("SUPABASE_BUCKET", SUPABASE_BUCKET_PADRAO)
    except Exception:
        return SUPABASE_BUCKET_PADRAO


def baixar_banco_da_nuvem():
    """Baixa o banco salvo no Supabase Storage antes do app criar tabelas."""
    global _SYNC_NUVEM_ATIVO
    sb = cliente_supabase()
    if sb is None:
        return False
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        dados = sb.storage.from_(bucket_supabase()).download(SUPABASE_DB_ARQUIVO)
        if dados:
            DB_PATH.write_bytes(dados)
            _SYNC_NUVEM_ATIVO = True
            return True
    except Exception:
        # Primeira execução: ainda não existe banco na nuvem. O app cria e depois envia.
        _SYNC_NUVEM_ATIVO = True
        return False
    return False


def enviar_banco_para_nuvem(force=False):
    """Envia o banco local para o Supabase Storage com proteção contra upload excessivo."""
    global _ULTIMO_UPLOAD_NUVEM
    if not _SYNC_NUVEM_ATIVO:
        return False
    if not DB_PATH.exists() or DB_PATH.stat().st_size <= 0:
        return False

    agora = datetime.now()
    if not force and _ULTIMO_UPLOAD_NUVEM is not None:
        if (agora - _ULTIMO_UPLOAD_NUVEM).total_seconds() < 5:
            return False

    sb = cliente_supabase()
    if sb is None:
        return False

    try:
        conteudo = DB_PATH.read_bytes()
        try:
            sb.storage.from_(bucket_supabase()).update(
                SUPABASE_DB_ARQUIVO,
                conteudo,
                {"content-type": "application/octet-stream", "upsert": "true"},
            )
        except Exception:
            sb.storage.from_(bucket_supabase()).upload(
                SUPABASE_DB_ARQUIVO,
                conteudo,
                {"content-type": "application/octet-stream", "upsert": "true"},
            )
        _ULTIMO_UPLOAD_NUVEM = agora
        return True
    except Exception:
        return False


baixar_banco_da_nuvem()

def backup_banco_automatico():
    """Cria backup automático do banco sem apagar nada."""
    try:
        if not DB_PATH.exists() or DB_PATH.stat().st_size <= 0:
            return
        pasta = Path("backups")
        pasta.mkdir(exist_ok=True)

        # Evita criar dezenas de backups em cada rerun do Streamlit.
        existentes = sorted(pasta.glob("Sophi_erp_backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        agora = datetime.now()
        if existentes:
            ultimo = datetime.fromtimestamp(existentes[0].stat().st_mtime)
            if (agora - ultimo).total_seconds() < 30 * 60:
                return

        destino = pasta / f"Sophi_erp_backup_{agora.strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(DB_PATH, destino)
    except Exception:
        pass


backup_banco_automatico()


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
        lastrowid = cur.lastrowid
    enviar_banco_para_nuvem()
    return lastrowid


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






# ============================================================
# DATAS EM FORMATO BRASILEIRO
# ============================================================

def data_br(valor):
    """Converte datas salvas como AAAA-MM-DD ou timestamp para DD/MM/AAAA."""
    try:
        if valor is None:
            return ""
        texto = str(valor).strip()
        if texto in ["", "None", "nan", "NaT"]:
            return ""

        dt = pd.to_datetime(texto, errors="coerce")
        if pd.isna(dt):
            return texto

        return dt.strftime("%d/%m/%Y")
    except Exception:
        return str(valor)


def data_hora_br(valor):
    """Converte data/hora para DD/MM/AAAA HH:MM."""
    try:
        if valor is None:
            return ""
        texto = str(valor).strip()
        if texto in ["", "None", "nan", "NaT"]:
            return ""

        dt = pd.to_datetime(texto, errors="coerce")
        if pd.isna(dt):
            return texto

        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(valor)


def data_iso(valor):
    """Converte DD/MM/AAAA para AAAA-MM-DD antes de salvar."""
    try:
        texto = str(valor).strip()
        if not texto:
            return ""

        if "/" in texto:
            partes = texto.split("/")
            if len(partes) == 3:
                dia, mes, ano = partes
                return f"{int(ano):04d}-{int(mes):02d}-{int(dia):02d}"

        dt = pd.to_datetime(texto, errors="coerce")
        if pd.isna(dt):
            return texto

        return dt.strftime("%Y-%m-%d")
    except Exception:
        return str(valor)


def hoje_br():
    return datetime.now().strftime("%d/%m/%Y")


def daqui_dias_br(dias=7):
    return (datetime.now().date() + timedelta(days=int(dias))).strftime("%d/%m/%Y")


def formatar_datas_dataframe(df):
    """Formata colunas de data para exibição em DD/MM/AAAA."""
    if df is None or getattr(df, "empty", True):
        return df

    df = df.copy()

    palavras_data = [
        "data", "vencimento", "pagamento", "recebimento", "entrega",
        "cadastro", "criacao", "criação", "upload", "emissao", "emissão",
        "aniversario", "aniversário", "validade", "ultimo", "último"
    ]

    for col in df.columns:
        col_lower = str(col).lower()

        if any(p in col_lower for p in palavras_data):
            try:
                if "hora" in col_lower and "data" not in col_lower:
                    continue

                # aniversário muitas vezes vem como 15/08; mantém se não tiver ano.
                if "anivers" in col_lower:
                    df[col] = df[col].apply(lambda x: str(x) if str(x).count("/") == 1 else data_br(x))
                elif "criacao" in col_lower or "criação" in col_lower or "upload" in col_lower or "ultimo" in col_lower or "último" in col_lower:
                    df[col] = df[col].apply(data_hora_br)
                else:
                    df[col] = df[col].apply(data_br)
            except Exception:
                pass

    return df


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
    st.markdown(
        f"""
        <div class="sophi-card">
            <div class="sophi-card-top">
                <div class="sophi-card-title">{titulo}</div>
            </div>
            <div class="sophi-card-value">{valor}</div>
            <div class="sophi-card-subtitle">{subtitulo}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )



def salvar_upload(upload, nome_base):
    if upload is None:
        return ""

    # Garante que a pasta das fotos existe antes de salvar.
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    nome_limpo = "".join(
        c for c in str(nome_base).replace(" ", "_")
        if c.isalnum() or c in ("_", "-")
    ).strip("_")

    if not nome_limpo:
        nome_limpo = "produto"

    ext = Path(upload.name).suffix.lower()
    if ext == "":
        ext = ".jpg"

    caminho = UPLOAD_DIR / f"{nome_limpo}{ext}"

    contador = 1
    while caminho.exists():
        caminho = UPLOAD_DIR / f"{nome_limpo}_{contador}{ext}"
        contador += 1

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


def salvar_upload_produto_data_uri(upload):
    """Salva foto de produto direto no banco como data:image.
    Assim o catálogo público funciona também no Streamlit Cloud,
    sem depender da pasta uploads existir depois do deploy/reboot.
    """
    if upload is None:
        return ""
    try:
        ext = Path(upload.name).suffix.lower().replace(".", "") or "jpeg"
        if ext == "jpg":
            ext = "jpeg"
        if ext not in ["png", "jpeg", "webp"]:
            ext = "jpeg"
        b64 = base64.b64encode(upload.getbuffer()).decode("utf-8")
        return f"data:image/{ext};base64,{b64}"
    except Exception:
        # fallback antigo: salva em arquivo, se algo impedir base64
        return salvar_upload(upload, "produto_foto")


def foto_produto_data_uri(valor):
    """Aceita foto salva como data:image ou como caminho de arquivo antigo."""
    foto = str(valor or "").strip()
    if not foto:
        return ""
    if foto.startswith("data:image"):
        return foto
    candidatos = [Path(foto), UPLOAD_DIR / foto, Path("uploads") / Path(foto).name]
    for caminho in candidatos:
        try:
            if caminho.exists() and caminho.is_file() and caminho.stat().st_size > 0:
                ext = caminho.suffix.lower().replace(".", "") or "jpeg"
                if ext == "jpg":
                    ext = "jpeg"
                if ext not in ["png", "jpeg", "webp"]:
                    ext = "jpeg"
                b64 = base64.b64encode(caminho.read_bytes()).decode("utf-8")
                return f"data:image/{ext};base64,{b64}"
        except Exception:
            pass
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


    # Migração automática: campos editáveis e catálogo dos produtos
    campos_produtos_extra = {
        "favorito": "TEXT DEFAULT 'Não'",
        "descricao_catalogo": "TEXT",
        "status_catalogo": "TEXT DEFAULT 'Disponível'",
    }
    for coluna, tipo_coluna in campos_produtos_extra.items():
        try:
            executar(f"ALTER TABLE produtos ADD COLUMN {coluna} {tipo_coluna}")
        except Exception:
            pass

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


    # Campos extras para prazo/entrega do orçamento
    campos_entrega_orcamento = {
        "data_prevista_entrega": "TEXT",
        "hora_prevista_entrega": "TEXT",
        "tipo_entrega": "TEXT",
        "endereco_entrega": "TEXT",
        "responsavel_entrega": "TEXT",
        "prioridade_entrega": "TEXT DEFAULT 'Normal'",
        "observacoes_entrega": "TEXT",
    }

    for coluna, tipo_coluna in campos_entrega_orcamento.items():
        try:
            executar(f"ALTER TABLE orcamentos ADD COLUMN {coluna} {tipo_coluna}")
        except Exception:
            pass

    executar("""
    CREATE TABLE IF NOT EXISTS custos_fixos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        categoria TEXT DEFAULT 'Outros',
        valor_mensal REAL DEFAULT 0,
        percentual_empresa REAL DEFAULT 100,
        ativo TEXT DEFAULT 'Sim',
        observacoes TEXT,
        data_cadastro TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Campos internos de precificação. Migração segura: não apaga dados existentes.
    for _col, _tipo in {
        "qtd_por_folha": "REAL DEFAULT 1",
        "custo_fixos": "REAL DEFAULT 0",
    }.items():
        try:
            executar(f"ALTER TABLE produtos ADD COLUMN {_col} {_tipo}")
        except Exception:
            pass

    executar("""
    CREATE TABLE IF NOT EXISTS vendas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero TEXT,
        data TEXT DEFAULT CURRENT_TIMESTAMP,
        cliente_id INTEGER,
        cliente_nome TEXT,
        cliente_whatsapp TEXT,
        origem TEXT DEFAULT 'Venda direta',
        status TEXT DEFAULT 'Pago',
        status_producao TEXT DEFAULT 'Aguardando',
        forma_pagamento TEXT,
        subtotal REAL DEFAULT 0,
        desconto REAL DEFAULT 0,
        acrescimo REAL DEFAULT 0,
        frete REAL DEFAULT 0,
        taxa_cartao REAL DEFAULT 0,
        total REAL DEFAULT 0,
        valor_recebido REAL DEFAULT 0,
        troco REAL DEFAULT 0,
        saldo_pendente REAL DEFAULT 0,
        data_entrega TEXT,
        observacoes TEXT,
        cancelada TEXT DEFAULT 'Não',
        motivo_cancelamento TEXT,
        operador TEXT,
        data_criacao TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Migrações seguras do PDV profissional. Não apagam vendas existentes.
    for _col, _tipo in {
        "data_cancelamento": "TEXT",
        "valor_estornado": "REAL DEFAULT 0",
        "motivo_cancelamento": "TEXT",
        "cancelada": "TEXT DEFAULT 'Não'",
        "data_atualizacao": "TEXT",
    }.items():
        try:
            executar(f"ALTER TABLE vendas ADD COLUMN {_col} {_tipo}")
        except Exception:
            pass

    executar("""
    CREATE TABLE IF NOT EXISTS venda_itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venda_id INTEGER,
        produto_id INTEGER,
        produto TEXT NOT NULL,
        quantidade REAL DEFAULT 1,
        valor_unitario REAL DEFAULT 0,
        custo_unitario REAL DEFAULT 0,
        desconto REAL DEFAULT 0,
        total REAL DEFAULT 0,
        observacoes TEXT
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS caixa_movimentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data TEXT DEFAULT CURRENT_TIMESTAMP,
        tipo TEXT,
        descricao TEXT,
        forma_pagamento TEXT,
        valor REAL DEFAULT 0,
        venda_id INTEGER,
        operador TEXT,
        observacoes TEXT
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS caixa_sessoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data_abertura TEXT DEFAULT CURRENT_TIMESTAMP,
        data_fechamento TEXT,
        operador TEXT,
        saldo_inicial REAL DEFAULT 0,
        saldo_final_informado REAL DEFAULT 0,
        saldo_final_calculado REAL DEFAULT 0,
        diferenca REAL DEFAULT 0,
        status TEXT DEFAULT 'Aberto',
        observacoes TEXT
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS venda_pagamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venda_id INTEGER,
        forma_pagamento TEXT,
        valor REAL DEFAULT 0,
        taxa REAL DEFAULT 0,
        parcelas INTEGER DEFAULT 1,
        data TEXT DEFAULT CURRENT_TIMESTAMP,
        observacoes TEXT
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


    try:
        executar("ALTER TABLE produtos ADD COLUMN status_catalogo TEXT DEFAULT 'Disponível'")
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


    executar("""
    CREATE TABLE IF NOT EXISTS kits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        categoria TEXT,
        descricao TEXT,
        status TEXT DEFAULT 'Disponível',
        favorito TEXT DEFAULT 'Não',
        destaque_catalogo TEXT DEFAULT 'Sim',
        foto TEXT,
        itens_json TEXT,
        custo_total REAL DEFAULT 0,
        preco_sugerido REAL DEFAULT 0,
        preco_promocional REAL DEFAULT 0,
        lucro REAL DEFAULT 0,
        margem REAL DEFAULT 0,
        ativo TEXT DEFAULT 'Sim',
        data_cadastro TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS historico_kits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kit_id INTEGER,
        data TEXT DEFAULT CURRENT_TIMESTAMP,
        acao TEXT,
        observacoes TEXT
    )
    """)


    # Migração automática das Ordens de Produção para bancos já existentes.
    # Se a tabela foi criada antes sem alguma coluna, o sistema adiciona sem apagar seus dados.
    migracoes_op = {
        "codigo": "TEXT",
        "orcamento_id": "INTEGER",
        "cliente_nome": "TEXT",
        "whatsapp": "TEXT",
        "data_criacao": "TEXT DEFAULT CURRENT_TIMESTAMP",
        "data_entrega": "TEXT",
        "prioridade": "TEXT DEFAULT 'Normal'",
        "status": "TEXT DEFAULT 'Aguardando'",
        "itens_json": "TEXT",
        "materiais_json": "TEXT",
        "checklist_json": "TEXT",
        "observacoes": "TEXT",
        "ativo": "TEXT DEFAULT 'Sim'",
    }

    for coluna, tipo in migracoes_op.items():
        try:
            executar(f"ALTER TABLE ordens_producao ADD COLUMN {coluna} {tipo}")
        except Exception:
            pass

    try:
        executar("""
        UPDATE ordens_producao
        SET codigo = 'OP-' || strftime('%Y','now') || '-' || printf('%04d', id)
        WHERE codigo IS NULL OR codigo = ''
        """)
    except Exception:
        pass



    executar("""
    CREATE TABLE IF NOT EXISTS estoque_reservas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        op_id INTEGER,
        item_nome TEXT,
        categoria TEXT,
        quantidade REAL DEFAULT 0,
        status TEXT DEFAULT 'Reservado',
        data TEXT DEFAULT CURRENT_TIMESTAMP,
        observacoes TEXT
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS estoque_consumo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        op_id INTEGER,
        data TEXT DEFAULT CURRENT_TIMESTAMP,
        item_nome TEXT,
        categoria TEXT,
        quantidade REAL DEFAULT 0,
        tipo TEXT DEFAULT 'Baixa automática',
        observacoes TEXT
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS estoque_minimo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_nome TEXT UNIQUE,
        categoria TEXT,
        estoque_minimo REAL DEFAULT 5,
        observacoes TEXT
    )
    """)


    executar("""
    CREATE TABLE IF NOT EXISTS contas_pagar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        descricao TEXT NOT NULL,
        fornecedor TEXT,
        categoria TEXT,
        centro_custo TEXT,
        forma_pagamento TEXT,
        valor REAL DEFAULT 0,
        data_emissao TEXT DEFAULT CURRENT_DATE,
        data_vencimento TEXT,
        data_pagamento TEXT,
        status TEXT DEFAULT 'Pendente',
        recorrente TEXT DEFAULT 'Não',
        observacoes TEXT,
        ativo TEXT DEFAULT 'Sim'
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS contas_receber (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        descricao TEXT NOT NULL,
        cliente_id INTEGER,
        cliente_nome TEXT,
        categoria TEXT,
        forma_pagamento TEXT,
        valor REAL DEFAULT 0,
        valor_recebido REAL DEFAULT 0,
        data_emissao TEXT DEFAULT CURRENT_DATE,
        data_vencimento TEXT,
        data_recebimento TEXT,
        status TEXT DEFAULT 'Pendente',
        origem TEXT,
        referencia_id INTEGER,
        observacoes TEXT,
        ativo TEXT DEFAULT 'Sim'
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS centros_custo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT UNIQUE NOT NULL,
        tipo TEXT DEFAULT 'Despesa',
        ativo TEXT DEFAULT 'Sim',
        observacoes TEXT
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS categorias_financeiras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT UNIQUE NOT NULL,
        tipo TEXT DEFAULT 'Despesa',
        ativo TEXT DEFAULT 'Sim',
        observacoes TEXT
    )
    """)

    # Padrões iniciais do financeiro profissional
    centros_padrao = [
        ("Impressão", "Despesa"),
        ("Embalagens", "Despesa"),
        ("Marketing", "Despesa"),
        ("Equipamentos", "Despesa"),
        ("Entregas", "Despesa"),
        ("Insumos", "Despesa"),
        ("Produtos para kits", "Despesa"),
        ("Administrativo", "Despesa"),
        ("Vendas", "Receita"),
        ("Outros", "Despesa"),
    ]

    for nome_centro, tipo_centro in centros_padrao:
        executar("""
        INSERT OR IGNORE INTO centros_custo(nome, tipo, ativo)
        VALUES (?, ?, 'Sim')
        """, (nome_centro, tipo_centro))

    categorias_fin_padrao = [
        ("Venda", "Receita"),
        ("Encomenda", "Receita"),
        ("Kit", "Receita"),
        ("Papel", "Despesa"),
        ("Tinta", "Despesa"),
        ("BOPP / Laminação", "Despesa"),
        ("Embalagem", "Despesa"),
        ("Manta / Ímã", "Despesa"),
        ("Energia", "Despesa"),
        ("Internet", "Despesa"),
        ("Marketing", "Despesa"),
        ("Entrega / Motoboy", "Despesa"),
        ("Equipamento", "Despesa"),
        ("Fornecedor", "Despesa"),
        ("Outros", "Despesa"),
    ]

    for nome_cat, tipo_cat in categorias_fin_padrao:
        executar("""
        INSERT OR IGNORE INTO categorias_financeiras(nome, tipo, ativo)
        VALUES (?, ?, 'Sim')
        """, (nome_cat, tipo_cat))


    executar("""
    CREATE TABLE IF NOT EXISTS crm_interacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER,
        cliente_nome TEXT,
        data TEXT DEFAULT CURRENT_TIMESTAMP,
        tipo TEXT,
        canal TEXT,
        descricao TEXT,
        status TEXT DEFAULT 'Registrado',
        proximo_contato TEXT,
        observacoes TEXT
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS crm_fidelidade (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER UNIQUE,
        cliente_nome TEXT,
        pontos REAL DEFAULT 0,
        nivel TEXT DEFAULT 'Novo',
        total_gasto REAL DEFAULT 0,
        total_pedidos INTEGER DEFAULT 0,
        ultima_compra TEXT,
        observacoes TEXT
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS crm_cupons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT UNIQUE NOT NULL,
        descricao TEXT,
        tipo TEXT DEFAULT 'Percentual',
        valor REAL DEFAULT 0,
        minimo_compra REAL DEFAULT 0,
        validade TEXT,
        ativo TEXT DEFAULT 'Sim',
        observacoes TEXT
    )
    """)


    executar("""
    CREATE TABLE IF NOT EXISTS agenda_tarefas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo TEXT NOT NULL,
        tipo TEXT DEFAULT 'Tarefa',
        cliente_id INTEGER,
        cliente_nome TEXT,
        referencia_tipo TEXT,
        referencia_id INTEGER,
        data TEXT,
        hora TEXT,
        prioridade TEXT DEFAULT 'Normal',
        status TEXT DEFAULT 'Pendente',
        descricao TEXT,
        observacoes TEXT,
        ativo TEXT DEFAULT 'Sim',
        data_criacao TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS entregas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER,
        cliente_nome TEXT,
        whatsapp TEXT,
        referencia_tipo TEXT,
        referencia_id INTEGER,
        codigo TEXT,
        data_entrega TEXT,
        hora_entrega TEXT,
        tipo_entrega TEXT DEFAULT 'Retirada',
        endereco TEXT,
        taxa_entrega REAL DEFAULT 0,
        status TEXT DEFAULT 'Pendente',
        responsavel TEXT,
        observacoes TEXT,
        ativo TEXT DEFAULT 'Sim',
        data_criacao TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)


    executar("""
    CREATE TABLE IF NOT EXISTS automacoes_erp (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        tipo TEXT DEFAULT 'Alerta',
        regra TEXT,
        canal TEXT DEFAULT 'ERP',
        mensagem TEXT,
        ativo TEXT DEFAULT 'Sim',
        ultima_execucao TEXT,
        observacoes TEXT
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS alertas_erp (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data TEXT DEFAULT CURRENT_TIMESTAMP,
        tipo TEXT,
        origem TEXT,
        referencia_id INTEGER,
        titulo TEXT,
        mensagem TEXT,
        prioridade TEXT DEFAULT 'Normal',
        status TEXT DEFAULT 'Novo',
        acao_sugerida TEXT,
        link_interno TEXT
    )
    """)

    automacoes_padrao = [
        ("Estoque baixo", "Alerta", "estoque_baixo", "ERP", "Avisar quando itens estiverem abaixo do mínimo.", "Sim"),
        ("Contas atrasadas", "Alerta", "contas_atrasadas", "ERP", "Avisar quando contas a pagar ou receber estiverem atrasadas.", "Sim"),
        ("Entregas de hoje", "Alerta", "entregas_hoje", "ERP", "Avisar entregas programadas para hoje.", "Sim"),
        ("OP atrasada", "Alerta", "op_atrasada", "ERP", "Avisar ordens de produção atrasadas.", "Sim"),
        ("Follow-up orçamento", "Alerta", "followup_orcamento", "ERP", "Avisar orçamentos aguardando resposta.", "Sim"),
        ("Aniversariantes", "Alerta", "aniversariantes", "ERP", "Avisar clientes aniversariantes do mês.", "Sim"),
    ]

    for auto in automacoes_padrao:
        executar("""
        INSERT OR IGNORE INTO automacoes_erp(nome, tipo, regra, canal, mensagem, ativo)
        VALUES (?, ?, ?, ?, ?, ?)
        """, auto)


    executar("""
    CREATE TABLE IF NOT EXISTS biblioteca_arquivos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        tipo TEXT DEFAULT 'Arte',
        categoria TEXT,
        produto_relacionado TEXT,
        cliente_id INTEGER,
        cliente_nome TEXT,
        caminho_arquivo TEXT,
        formato TEXT,
        tags TEXT,
        favorito TEXT DEFAULT 'Não',
        status TEXT DEFAULT 'Ativo',
        observacoes TEXT,
        data_upload TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    executar("""
    CREATE TABLE IF NOT EXISTS biblioteca_modelos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        tipo TEXT DEFAULT 'Template',
        categoria TEXT,
        tamanho TEXT,
        descricao TEXT,
        caminho_arquivo TEXT,
        tags TEXT,
        favorito TEXT DEFAULT 'Não',
        status TEXT DEFAULT 'Ativo',
        observacoes TEXT,
        data_cadastro TEXT DEFAULT CURRENT_TIMESTAMP
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
        "producao_media_mensal": "5000",
        "logo_path": "",
        "catalogo_titulo": "Sophi Personalizados Oficial",
        "catalogo_slogan": "Eternizando momentos com presentes personalizados",
        "catalogo_descricao": "Confira nossos produtos personalizados e chame no WhatsApp para fazer seu pedido.",
        "catalogo_aviso": "Valores sujeitos à confirmação conforme personalização, material e prazo.",
        "catalogo_cor": "#000000",
        "catalogo_cnpj": "",
        "catalogo_endereco": "",
        "catalogo_email": "",
        "catalogo_pix": "",
        "catalogo_horario": "Atendimento de segunda a sábado",
        "catalogo_aceita_pix": "Sim",
        "catalogo_aceita_cartao": "Sim",
        "catalogo_parcelamento": "Consulte condições",
        "catalogo_sinal": "Sinal para confirmação da encomenda",
        "catalogo_prazo": "Prazo de produção combinado no atendimento",
        "catalogo_info_extra": "Produtos personalizados sob encomenda.",
        "catalogo_mostrar_status": "Sim",
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


def custo_equipamento(row, quantidade_lote=1, minutos=0, incluir_energia=False, custo_kwh=None):
    """
    Calcula o custo de equipamento de forma correta para precificação.

    Regra principal:
    - Depreciação/desgaste é por unidade produzida:
      valor_pago / vida_util_meses / producao_mensal.
    - Depois multiplica pela quantidade total do lote.

    Energia NÃO entra automaticamente no desgaste, para não inflar a precificação.
    Se quiser usar energia, ative incluir_energia=True e mantenha custo_kwh em R$/kWh.
    """
    if custo_kwh is None:
        custo_kwh = n(obter_config("custo_kwh", "1"), 1)

    valor_pago = n(row["valor_pago"])
    vida = max(n(row["vida_util_meses"], 1), 1)
    producao = max(n(row["producao_mensal"], 1), 1)
    potencia = n(row["potencia_w"])
    usa = str(row["usa_energia"])

    quantidade_lote = max(n(quantidade_lote, 1), 1)
    minutos = max(n(minutos, 0), 0)

    desgaste_por_unidade = valor_pago / vida / producao
    desgaste_total = desgaste_por_unidade * quantidade_lote

    energia_total = 0
    if incluir_energia and usa == "Sim":
        energia_total = (potencia / 1000) * custo_kwh * (minutos / 60)

    return desgaste_total + energia_total


def resumo_custos_fixos():
    """Retorna custos fixos mensais ativos, parcela da empresa e custo rateado por unidade."""
    try:
        df = consultar("SELECT * FROM custos_fixos WHERE ativo='Sim' ORDER BY categoria, nome")
    except Exception:
        df = pd.DataFrame()

    producao_mensal = max(n(obter_config("producao_media_mensal", "5000"), 5000), 1)
    total_mensal_empresa = 0.0
    detalhes = []

    if not df.empty:
        for _, row in df.iterrows():
            valor = n(row.get("valor_mensal", 0))
            percentual = min(max(n(row.get("percentual_empresa", 100), 100), 0), 100)
            parcela = valor * percentual / 100
            por_unidade = parcela / producao_mensal
            total_mensal_empresa += parcela
            detalhes.append({
                "nome": str(row.get("nome", "")),
                "categoria": str(row.get("categoria", "Outros")),
                "valor_mensal": valor,
                "percentual_empresa": percentual,
                "parcela_empresa": parcela,
                "custo_unidade": por_unidade,
            })

    return {
        "producao_mensal": producao_mensal,
        "total_mensal_empresa": total_mensal_empresa,
        "custo_fixo_unidade": total_mensal_empresa / producao_mensal,
        "detalhes": detalhes,
    }


def custo_fixo_do_lote(quantidade_lote):
    resumo = resumo_custos_fixos()
    return resumo["custo_fixo_unidade"] * max(n(quantidade_lote, 0), 0)


def tela_custos_fixos():
    st.title("Custos Fixos da Empresa")
    st.write("Cadastre as despesas mensais e informe qual percentual realmente pertence à empresa. O ERP rateia esses valores pela produção média mensal.")

    producao_atual = max(n(obter_config("producao_media_mensal", "5000"), 5000), 1)
    c1, c2 = st.columns([1, 2])
    nova_producao = c1.number_input("Produção média mensal (unidades)", min_value=1.0, value=float(producao_atual), step=100.0)
    c2.info("Exemplo: conta de luz da casa de R$250,00 e uso empresarial de 40% = R$100,00 rateados entre os produtos.")
    if st.button("Salvar produção média mensal"):
        salvar_config("producao_media_mensal", nova_producao)
        st.success("Produção média mensal atualizada.")
        st.rerun()

    st.subheader("Adicionar custo fixo")
    with st.form("form_novo_custo_fixo", clear_on_submit=True):
        a, b, c = st.columns(3)
        nome = a.text_input("Nome", placeholder="Energia elétrica")
        categoria = b.selectbox("Categoria", ["Casa / Empresa", "Software", "Administrativo", "Comunicação", "Aluguel", "Outros"])
        valor = c.number_input("Valor mensal", min_value=0.0, step=0.01, format="%.2f")
        d, e = st.columns(2)
        percentual = d.number_input("Percentual usado pela empresa (%)", min_value=0.0, max_value=100.0, value=100.0, step=5.0)
        observacoes = e.text_input("Observações")
        salvar = st.form_submit_button("Adicionar custo fixo")
        if salvar:
            if not nome.strip():
                st.error("Informe o nome do custo.")
            else:
                executar("""
                    INSERT INTO custos_fixos(nome, categoria, valor_mensal, percentual_empresa, ativo, observacoes)
                    VALUES (?, ?, ?, ?, 'Sim', ?)
                """, (nome.strip(), categoria, valor, percentual, observacoes))
                st.success("Custo fixo adicionado.")
                st.rerun()

    resumo = resumo_custos_fixos()
    r1, r2, r3 = st.columns(3)
    with r1: card("Custos fixos da empresa / mês", real(resumo["total_mensal_empresa"]))
    with r2: card("Produção média mensal", f"{resumo['producao_mensal']:.0f} un")
    with r3: card("Custo fixo por unidade", real4(resumo["custo_fixo_unidade"]))

    df = consultar("SELECT * FROM custos_fixos ORDER BY ativo DESC, categoria, nome")
    if df.empty:
        st.info("Nenhum custo fixo cadastrado.")
        return

    exib = df.copy()
    exib["Parcela da empresa"] = exib["valor_mensal"] * exib["percentual_empresa"] / 100
    exib["Custo por unidade"] = exib["Parcela da empresa"] / resumo["producao_mensal"]
    st.dataframe(formatar_valores_tabela(exib[["id", "nome", "categoria", "valor_mensal", "percentual_empresa", "Parcela da empresa", "Custo por unidade", "ativo"]]), use_container_width=True, hide_index=True)

    st.subheader("Editar ou excluir")
    mapa = {f"{int(r['id'])} - {r['nome']}": int(r['id']) for _, r in df.iterrows()}
    escolhido = st.selectbox("Selecione", list(mapa.keys()))
    rid = mapa[escolhido]
    row = df[df["id"] == rid].iloc[0]
    with st.form(f"editar_custo_{rid}"):
        x1, x2, x3 = st.columns(3)
        nome_e = x1.text_input("Nome", value=str(row["nome"]))
        valor_e = x2.number_input("Valor mensal", min_value=0.0, value=float(n(row["valor_mensal"])), step=0.01, format="%.2f")
        perc_e = x3.number_input("Percentual empresa (%)", min_value=0.0, max_value=100.0, value=float(n(row["percentual_empresa"],100)), step=5.0)
        ativo_e = st.selectbox("Ativo?", ["Sim", "Não"], index=0 if str(row["ativo"]) == "Sim" else 1)
        salvar_e = st.form_submit_button("Salvar alterações")
        if salvar_e:
            executar("UPDATE custos_fixos SET nome=?, valor_mensal=?, percentual_empresa=?, ativo=? WHERE id=?", (nome_e, valor_e, perc_e, ativo_e, rid))
            st.success("Custo atualizado.")
            st.rerun()
    if st.button("Excluir custo selecionado", type="secondary"):
        executar("DELETE FROM custos_fixos WHERE id=?", (rid,))
        st.success("Custo excluído.")
        st.rerun()


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




# ============================================================
# CORREÇÃO DE DATA/HORA BRASILEIRA
# ============================================================

def agora_brasil():
    try:
        return datetime.now(ZoneInfo("America/Sao_Paulo"))
    except Exception:
        return datetime.now()


def agora_iso_brasil():
    return agora_brasil().strftime("%Y-%m-%d %H:%M:%S")


def data_br_segura(valor):
    try:
        if valor is None:
            return ""
        texto = str(valor).strip()
        if texto in ["", "None", "nan", "NaT"]:
            return ""

        # Se já estiver em DD/MM/AAAA, mantém correto.
        if "/" in texto:
            partes = texto.split(" ")[0].split("/")
            if len(partes) == 3:
                dia, mes, ano = partes
                return f"{int(dia):02d}/{int(mes):02d}/{int(ano):04d}"

        # Banco deve estar em AAAA-MM-DD.
        dt = pd.to_datetime(texto, errors="coerce", dayfirst=False)
        if pd.isna(dt):
            return texto

        return dt.strftime("%d/%m/%Y")
    except Exception:
        return str(valor)


def data_hora_br_segura(valor):
    try:
        if valor is None:
            return ""
        texto = str(valor).strip()
        if texto in ["", "None", "nan", "NaT"]:
            return ""

        # Se já vier BR com hora, usa dayfirst.
        if "/" in texto:
            dt = pd.to_datetime(texto, errors="coerce", dayfirst=True)
            if pd.notna(dt):
                return dt.strftime("%d/%m/%Y às %H:%M")
            return texto

        # Banco deve estar em AAAA-MM-DD HH:MM:SS.
        dt = pd.to_datetime(texto, errors="coerce", dayfirst=False)
        if pd.isna(dt):
            return texto

        return dt.strftime("%d/%m/%Y às %H:%M")
    except Exception:
        return str(valor)


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
            <p><b>Data:</b> {data_hora_br_segura(o['data_orcamento'])}</p><p><b>Prazo de entrega:</b> {prazo_entrega}</p>
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
    st.title("Dashboard")
    st.write("Resumo rápido e clicável para acompanhar a Sophi Personalizados Oficial.")

    hoje = hoje_iso()
    mes_atual = hoje[:7]

    # Status que contam como venda real.
    status_venda = ["Pago", "Produção", "Embalagem", "Pronto", "Saiu para entrega", "Finalizado", "Entregue"]
    status_pendentes = ["Em orçamento", "Aprovado", "Aguardando pagamento"]

    # =========================
    # VENDAS REAIS
    # =========================
    placeholders_venda = ",".join(["?"] * len(status_venda))
    params_mes = tuple(status_venda) + (f"{mes_atual}%",)
    params_hoje = tuple(status_venda) + (f"{hoje}%",)

    try:
        vendas_mes = consultar(f"""
        SELECT id, cliente_nome, whatsapp, status, total, data_orcamento, forma_pagamento
        FROM orcamentos
        WHERE status IN ({placeholders_venda})
          AND data_orcamento LIKE ?
        ORDER BY id DESC
        """, params_mes)
    except Exception:
        vendas_mes = pd.DataFrame()

    try:
        vendas_hoje = consultar(f"""
        SELECT id, cliente_nome, whatsapp, status, total, data_orcamento, forma_pagamento
        FROM orcamentos
        WHERE status IN ({placeholders_venda})
          AND data_orcamento LIKE ?
        ORDER BY id DESC
        """, params_hoje)
    except Exception:
        vendas_hoje = pd.DataFrame()

    faturamento_mes = float(vendas_mes["total"].sum()) if not vendas_mes.empty and "total" in vendas_mes.columns else 0.0
    faturamento_hoje = float(vendas_hoje["total"].sum()) if not vendas_hoje.empty and "total" in vendas_hoje.columns else 0.0

    # Lucro realizado baseado nos itens de orçamentos realmente vendidos.
    try:
        ids_venda = vendas_mes["id"].astype(int).tolist() if not vendas_mes.empty else []
        if ids_venda:
            placeholders_ids = ",".join(["?"] * len(ids_venda))
            itens_venda = consultar(f"""
            SELECT oi.orcamento_id, oi.produto, oi.quantidade, oi.total,
                   p.custo_unitario, p.preco_escolhido, p.preco_sugerido
            FROM orcamento_itens oi
            LEFT JOIN produtos p ON p.nome = oi.produto
            WHERE oi.orcamento_id IN ({placeholders_ids})
            """, tuple(ids_venda))
        else:
            itens_venda = pd.DataFrame()
    except Exception:
        itens_venda = pd.DataFrame()

    if not itens_venda.empty:
        itens_venda["custo_estimado"] = itens_venda.apply(lambda r: n(r.get("quantidade", 0)) * n(r.get("custo_unitario", 0)), axis=1)
        itens_venda["lucro_estimado"] = itens_venda.apply(lambda r: n(r.get("total", 0)) - n(r.get("custo_estimado", 0)), axis=1)
        lucro_realizado = float(itens_venda["lucro_estimado"].sum())
    else:
        lucro_realizado = 0.0

    margem_media = (lucro_realizado / faturamento_mes * 100) if faturamento_mes else 0.0

    # =========================
    # ORÇAMENTOS PENDENTES / POTENCIAIS
    # =========================
    placeholders_pend = ",".join(["?"] * len(status_pendentes))
    try:
        orc_pendentes = consultar(f"""
        SELECT id, cliente_nome, whatsapp, status, total, data_orcamento, forma_pagamento
        FROM orcamentos
        WHERE status IN ({placeholders_pend})
        ORDER BY id DESC
        """, tuple(status_pendentes))
    except Exception:
        orc_pendentes = pd.DataFrame()

    total_potencial = float(orc_pendentes["total"].sum()) if not orc_pendentes.empty and "total" in orc_pendentes.columns else 0.0

    try:
        ids_pend = orc_pendentes["id"].astype(int).tolist() if not orc_pendentes.empty else []
        if ids_pend:
            placeholders_ids_p = ",".join(["?"] * len(ids_pend))
            itens_pend = consultar(f"""
            SELECT oi.orcamento_id, oi.produto, oi.quantidade, oi.total,
                   p.custo_unitario
            FROM orcamento_itens oi
            LEFT JOIN produtos p ON p.nome = oi.produto
            WHERE oi.orcamento_id IN ({placeholders_ids_p})
            """, tuple(ids_pend))
        else:
            itens_pend = pd.DataFrame()
    except Exception:
        itens_pend = pd.DataFrame()

    if not itens_pend.empty:
        itens_pend["custo_estimado"] = itens_pend.apply(lambda r: n(r.get("quantidade", 0)) * n(r.get("custo_unitario", 0)), axis=1)
        itens_pend["lucro_potencial"] = itens_pend.apply(lambda r: n(r.get("total", 0)) - n(r.get("custo_estimado", 0)), axis=1)
        lucro_potencial = float(itens_pend["lucro_potencial"].sum())
    else:
        lucro_potencial = 0.0

    # =========================
    # OUTROS INDICADORES
    # =========================
    try:
        entregas_hoje = consultar("""
        SELECT id, codigo, cliente_nome, whatsapp, data_entrega, hora_entrega, tipo_entrega, status
        FROM entregas
        WHERE ativo='Sim'
          AND data_entrega=?
          AND status NOT IN ('Entregue', 'Cancelado')
        ORDER BY hora_entrega
        """, (hoje,))
    except Exception:
        entregas_hoje = pd.DataFrame()

    try:
        resumo_estoque = resumo_estoque_inteligente()
        estoque_baixo = resumo_estoque[resumo_estoque["disponivel"] <= resumo_estoque["estoque_minimo"]] if not resumo_estoque.empty else pd.DataFrame()
    except Exception:
        estoque_baixo = pd.DataFrame()

    try:
        aniversariantes = aniversariantes_periodo()
    except Exception:
        aniversariantes = pd.DataFrame()

    # =========================
    # CARDS PRINCIPAIS
    # =========================
    st.markdown("### Vendas reais")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        card("Vendas hoje", real(faturamento_hoje), "Somente pedidos pagos/em produção/concluídos")
    with c2:
        card("Faturamento do mês", real(faturamento_mes), "Vendas reais do mês")
    with c3:
        card("Lucro realizado", real(lucro_realizado), "Baseado nas vendas reais")
    with c4:
        card("Margem média", f"{margem_media:.2f}%", "Lucro / faturamento")

    st.markdown("### Orçamentos e oportunidades")
    o1, o2, o3, o4 = st.columns(4)
    with o1:
        card("Aguardando resposta", str(len(orc_pendentes)), "Orçamentos não vendidos")
    with o2:
        card("Valor potencial", real(total_potencial), "Total ainda em negociação")
    with o3:
        card("Lucro potencial", real(lucro_potencial), "Se todos fecharem")
    with o4:
        aprovados = len(orc_pendentes[orc_pendentes["status"] == "Aprovado"]) if not orc_pendentes.empty and "status" in orc_pendentes.columns else 0
        card("Aprovados sem venda", str(aprovados), "Falta pagamento/produção")

    st.markdown("### Operação")
    p1, p2, p3 = st.columns(3)
    with p1:
        card("Entregas hoje", str(len(entregas_hoje)), "Clique abaixo para ver")
    with p2:
        card("Estoque baixo", str(len(estoque_baixo)), "Itens abaixo do mínimo")
    with p3:
        card("Aniversariantes", str(len(aniversariantes)), "Clientes do mês")

    st.divider()

    # =========================
    # DETALHES CLICÁVEIS
    # =========================
    st.subheader("Detalhes dos valores")
    st.caption("Abra cada bloco para conferir de onde vêm os números do Dashboard.")

    with st.expander("💰 Ver vendas reais do mês"):
        if vendas_mes.empty:
            st.info("Nenhuma venda real no mês. Orçamentos ainda não contam como venda.")
        else:
            dfv = vendas_mes.copy()
            dfv["codigo"] = dfv["id"].apply(lambda x: codigo_visual("ORC", x, ano=datetime.now().year))
            st.dataframe(
                formatar_valores_tabela(dfv[["codigo", "cliente_nome", "status", "forma_pagamento", "total", "data_orcamento"]]),
                use_container_width=True,
                hide_index=True,
            )
            st.write(f"**Total vendido:** {real(faturamento_mes)}")

    with st.expander("📈 Ver lucro realizado por produto"):
        if itens_venda.empty:
            st.info("Nenhum item vendido encontrado para calcular lucro.")
        else:
            st.dataframe(
                formatar_valores_tabela(itens_venda[["orcamento_id", "produto", "quantidade", "total", "custo_estimado", "lucro_estimado"]]),
                use_container_width=True,
                hide_index=True,
            )
            st.write(f"**Lucro realizado estimado:** {real(lucro_realizado)}")

    with st.expander("📋 Ver orçamentos aguardando resposta / potencial"):
        if orc_pendentes.empty:
            st.success("Nenhum orçamento pendente.")
        else:
            dfp = orc_pendentes.copy()
            dfp["codigo"] = dfp["id"].apply(lambda x: codigo_visual("ORC", x, ano=datetime.now().year))
            st.dataframe(
                formatar_valores_tabela(dfp[["codigo", "cliente_nome", "whatsapp", "status", "total", "data_orcamento"]]),
                use_container_width=True,
                hide_index=True,
            )
            st.write(f"**Valor potencial:** {real(total_potencial)}")
            st.write(f"**Lucro potencial estimado:** {real(lucro_potencial)}")

            if "tela_mensagens_whatsapp" in globals():
                st.info("Para cobrar ou enviar mensagem pronta, use a aba Mensagens WhatsApp.")

    with st.expander("🚚 Ver entregas de hoje"):
        if entregas_hoje.empty:
            st.success("Nenhuma entrega pendente para hoje.")
        else:
            st.dataframe(formatar_valores_tabela(entregas_hoje), use_container_width=True, hide_index=True)

    with st.expander("📦 Ver itens com estoque baixo"):
        if estoque_baixo.empty:
            st.success("Nenhum item crítico no estoque.")
        else:
            st.dataframe(formatar_valores_tabela(estoque_baixo), use_container_width=True, hide_index=True)

    with st.expander("🎂 Ver aniversariantes do mês"):
        if aniversariantes.empty:
            st.info("Nenhum aniversariante encontrado neste mês.")
        else:
            st.dataframe(formatar_valores_tabela(aniversariantes), use_container_width=True, hide_index=True)

    st.divider()

    # Mantém blocos úteis antigos caso existam dados.
    st.subheader("Produtos favoritos")
    try:
        favs = consultar("""
        SELECT nome, categoria, preco_escolhido
        FROM produtos
        WHERE favorito='Sim'
        ORDER BY nome
        LIMIT 10
        """)
        if favs.empty:
            st.info("Nenhum produto favorito ainda.")
        else:
            st.dataframe(formatar_valores_tabela(favs), use_container_width=True, hide_index=True)
    except Exception:
        st.info("Nenhum produto favorito ainda.")
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



# ============================================================
# TAREFAS DO DIA
# ============================================================




# ============================================================
# TAREFAS DO DIA
# ============================================================

def garantir_tarefas_dia():
    executar("""
    CREATE TABLE IF NOT EXISTS tarefas_dia (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo TEXT,
        cliente TEXT,
        whatsapp TEXT,
        tipo TEXT,
        prioridade TEXT DEFAULT 'Normal',
        status TEXT DEFAULT 'Pendente',
        data_tarefa TEXT DEFAULT CURRENT_DATE,
        prazo TEXT,
        observacoes TEXT,
        criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
        concluido_em TEXT
    )
    """)


def tela_tarefas_dia():
    garantir_tarefas_dia()

    st.title("Tarefas do Dia")
    st.write("Anote e acompanhe tudo que precisa resolver hoje: WhatsApp, orçamento, arte, pagamento, produção, entrega e pós-venda.")

    hoje = datetime.now().strftime("%Y-%m-%d")

    tarefas_hoje = consultar("""
    SELECT *
    FROM tarefas_dia
    WHERE data_tarefa=? AND COALESCE(status, 'Pendente') <> 'Concluída'
    ORDER BY id DESC
    """, (hoje,))

    tarefas_pendentes = consultar("""
    SELECT *
    FROM tarefas_dia
    WHERE COALESCE(status, 'Pendente') <> 'Concluída'
    ORDER BY data_tarefa, id DESC
    """)

    c1, c2, c3 = st.columns(3)
    c1.metric("Tarefas de hoje", len(tarefas_hoje))
    c2.metric("Pendentes", len(tarefas_pendentes))
    c3.metric(
        "Urgentes",
        len(tarefas_pendentes[tarefas_pendentes["prioridade"] == "Urgente"])
        if not tarefas_pendentes.empty and "prioridade" in tarefas_pendentes.columns
        else 0
    )

    st.divider()

    st.subheader("Nova tarefa")
    with st.form("nova_tarefa_form"):
        col1, col2 = st.columns(2)
        titulo = col1.text_input("O que precisa fazer?", placeholder="Ex: responder cliente sobre orçamento da arte")
        cliente = col2.text_input("Cliente", placeholder="Nome do cliente")

        col3, col4 = st.columns(2)
        whatsapp = col3.text_input("WhatsApp", placeholder="Ex: 13999999999")
        tipo = col4.selectbox(
            "Tipo",
            [
                "Responder WhatsApp",
                "Enviar orçamento",
                "Criar arte",
                "Ajustar arte",
                "Aguardando aprovação",
                "Solicitar pagamento",
                "Conferir comprovante",
                "Produção",
                "Entrega / retirada",
                "Pós-venda",
                "Outro",
            ],
        )

        col5, col6, col7 = st.columns(3)
        prioridade = col5.selectbox("Prioridade", ["Normal", "Alta", "Urgente", "Baixa"])
        data_tarefa = col6.date_input("Data", value=datetime.now().date())
        prazo = col7.text_input("Prazo/horário", placeholder="Ex: até 18h")

        observacoes = st.text_area("Observações", placeholder="Detalhes da pendência, resposta, arte, prazo ou pedido.")

        salvar = st.form_submit_button("Salvar tarefa")
        if salvar:
            if not titulo.strip():
                st.error("Digite a tarefa.")
            else:
                executar("""
                INSERT INTO tarefas_dia(titulo, cliente, whatsapp, tipo, prioridade, status, data_tarefa, prazo, observacoes)
                VALUES (?, ?, ?, ?, ?, 'Pendente', ?, ?, ?)
                """, (titulo, cliente, whatsapp, tipo, prioridade, str(data_tarefa), prazo, observacoes))
                st.success("Tarefa salva.")
                st.rerun()

    st.divider()

    st.subheader("Lista de tarefas")
    filtro = st.radio("Mostrar", ["Hoje", "Todas pendentes", "Concluídas"], horizontal=True)

    if filtro == "Hoje":
        df = tarefas_hoje
    elif filtro == "Todas pendentes":
        df = tarefas_pendentes
    else:
        df = consultar("SELECT * FROM tarefas_dia WHERE status='Concluída' ORDER BY concluido_em DESC LIMIT 200")

    if df.empty:
        st.info("Nenhuma tarefa encontrada.")
        return

    for _, t in df.iterrows():
        with st.container(border=True):
            st.markdown(f"### {t['titulo']}")

            linha = []
            if str(t.get("cliente", "") or "").strip():
                linha.append(f"Cliente: {t.get('cliente')}")
            if str(t.get("tipo", "") or "").strip():
                linha.append(f"Tipo: {t.get('tipo')}")
            if str(t.get("prioridade", "") or "").strip():
                linha.append(f"Prioridade: {t.get('prioridade')}")
            if str(t.get("status", "") or "").strip():
                linha.append(f"Status: {t.get('status')}")
            if str(t.get("prazo", "") or "").strip():
                linha.append(f"Prazo: {t.get('prazo')}")
            if linha:
                st.write(" | ".join(linha))

            if str(t.get("observacoes", "") or "").strip():
                st.caption(t.get("observacoes"))

            b1, b2, b3, b4 = st.columns(4)

            with b1:
                if st.button("Concluir", key=f"tarefa_concluir_{int(t['id'])}", use_container_width=True):
                    executar("UPDATE tarefas_dia SET status='Concluída', concluido_em=CURRENT_TIMESTAMP WHERE id=?", (int(t["id"]),))
                    st.rerun()

            with b2:
                if st.button("Em andamento", key=f"tarefa_andamento_{int(t['id'])}", use_container_width=True):
                    executar("UPDATE tarefas_dia SET status='Em andamento' WHERE id=?", (int(t["id"]),))
                    st.rerun()

            with b3:
                numero = str(t.get("whatsapp", "") or "")
                if numero.strip():
                    msg = "Olá " + str(t.get("cliente") or "") + "! 🤍\\n\\nPassando para falar sobre: " + str(t.get("titulo") or "") + "\\n\\nEquipe Sophi Personalizados Oficial"
                    link = link_whatsapp(numero, msg)
                    if link:
                        st.link_button("WhatsApp", link, use_container_width=True)

            with b4:
                if st.button("Excluir", key=f"tarefa_excluir_{int(t['id'])}", use_container_width=True):
                    executar("DELETE FROM tarefas_dia WHERE id=?", (int(t["id"]),))
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

        r1, r2, r3 = st.columns(3)
        r1.metric("Desgaste por unidade", real(desgaste))
        r2.metric("Energia por minuto", real(energia_min))
        r3.metric("Obs.", "Energia separada")

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
        df["desgaste_unidade"] = df.apply(
            lambda r: n(r["valor_pago"]) / max(n(r["vida_util_meses"], 1), 1) / max(n(r["producao_mensal"], 1), 1),
            axis=1,
        )
        df["energia_minuto"] = df.apply(
            lambda r: ((n(r["potencia_w"]) / 1000) * custo_kwh / 60) if str(r["usa_energia"]) == "Sim" else 0,
            axis=1,
        )
        df["observacao_calculo"] = "Depreciação por unidade; energia separada"

    df = adicionar_codigo_visual(df, "EQP")

    edited = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "valor_pago": st.column_config.NumberColumn("Valor pago", format="R$ %.2f"),
            "desgaste_unidade": st.column_config.NumberColumn("Desgaste por unidade", format="R$ %.4f"),
            "energia_minuto": st.column_config.NumberColumn("Energia/min", format="R$ %.4f"),
            "observacao_calculo": st.column_config.TextColumn("Cálculo"),
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
    st.title("Precificação e Produtos Internos")
    st.write("Calcule preços, salve históricos internos e reutilize produtos em orçamentos. O catálogo público fica no Offstore.")

    # Garante campos novos em bancos antigos.
    for coluna, tipo_coluna in {
        "favorito": "TEXT DEFAULT 'Não'",
        "descricao_catalogo": "TEXT",
        "status_catalogo": "TEXT DEFAULT 'Disponível'",
    }.items():
        try:
            executar(f"ALTER TABLE produtos ADD COLUMN {coluna} {tipo_coluna}")
        except Exception:
            pass

    abas = st.tabs(["Novo produto", "Editar produto", "Lista / preços", "Ficha completa"])

    with abas[0]:
        st.subheader("Cadastrar novo produto")

        c1, c2, c3 = st.columns([3, 2, 1])
        nome = c1.text_input("Nome do produto")
        categoria_produto = c2.text_input("Categoria do produto")
        ativo = c3.selectbox("Ativo?", ["Sim", "Não"])
        favorito = False
        status_catalogo = "Uso interno"
        foto_upload = None
        descricao_catalogo = ""
        st.caption("Cadastro interno para precificação e orçamento. Fotos e descrições públicas ficam no Offstore.")

        c_qtd1, c_qtd2 = st.columns(2)
        qtd_total_lote = c_qtd1.number_input("Quantidade total do lote", min_value=1.0, value=1000.0, step=1.0)
        qtd_por_folha = c_qtd2.number_input("Quantidade produzida por folha A4", min_value=1.0, value=10.0, step=1.0)
        folhas_estimadas = int((qtd_total_lote + qtd_por_folha - 1) // qtd_por_folha)
        st.caption(f"Para {qtd_total_lote:.0f} unidades, usando {qtd_por_folha:.0f} por folha, você vai usar aproximadamente {folhas_estimadas} folhas A4.")
        qtd_por_lote = qtd_total_lote

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
                        custo = custo_equipamento(row, quantidade_lote=qtd_total_lote, minutos=tempo_min, incluir_energia=False)
                        equipamentos.append({"nome": row["nome"], "custo": custo, "quantidade_lote": qtd_total_lote})
                        custo_equip_total += custo
                        st.caption(real(custo))

        st.subheader("Mão de obra e precificação")
        c1, c2, c3 = st.columns(3)
        valor_hora = c1.number_input("Valor hora Mão de obra", min_value=0.0, value=n(obter_config("valor_hora", "5"), 5), step=0.01, format="%.2f")
        reserva = c2.number_input("Reserva de erro (%)", min_value=0.0, value=n(obter_config("reserva_erro", "5"), 5), step=0.1, format="%.2f")
        margem = c3.number_input("Margem desejada (%)", min_value=0.0, value=n(obter_config("margem_padrao", "50"), 50), step=0.1, format="%.2f")

        custo_mao_obra = tempo_min / 60 * valor_hora

        # Custos fixos são rateados por UNIDADE DE PRODUÇÃO, e não necessariamente
        # por cada peça final. Para produtos que rendem várias peças por folha A4
        # (cartões, tags, adesivos etc.), a base padrão é a quantidade de folhas.
        resumo_fixos = resumo_custos_fixos()
        incluir_custos_fixos = st.checkbox(
            "Incluir custos fixos nesta precificação?",
            value=True,
            help="Desmarque apenas para simulações sem despesas mensais da empresa.",
        )

        base_rateio_fixos = st.selectbox(
            "Como ratear os custos fixos neste produto?",
            ["Por folhas A4 utilizadas", "Por unidades finais do lote", "Quantidade manual de unidades de produção"],
            index=0,
            help=(
                "Para cartões, tags e adesivos, normalmente use folhas A4. "
                "Exemplo: 1.000 cartões, 10 por folha = 100 unidades de produção."
            ),
        )

        if base_rateio_fixos == "Por folhas A4 utilizadas":
            unidades_rateio_fixos = float(folhas_estimadas)
            descricao_rateio_fixos = f"{folhas_estimadas} folhas A4"
        elif base_rateio_fixos == "Por unidades finais do lote":
            unidades_rateio_fixos = float(qtd_total_lote)
            descricao_rateio_fixos = f"{qtd_total_lote:.0f} unidades finais"
        else:
            unidades_rateio_fixos = st.number_input(
                "Quantidade de unidades de produção para o rateio",
                min_value=0.0,
                value=float(folhas_estimadas),
                step=1.0,
                help="Informe quantas folhas, ciclos, peças-base ou lotes internos foram realmente produzidos.",
            )
            descricao_rateio_fixos = f"{unidades_rateio_fixos:.0f} unidades de produção"

        custo_fixos_total = (
            resumo_fixos["custo_fixo_unidade"] * unidades_rateio_fixos
            if incluir_custos_fixos
            else 0.0
        )

        st.caption(
            f"Custos fixos rateados: {real(custo_fixos_total)} no lote — "
            f"{real4(resumo_fixos['custo_fixo_unidade'])} por unidade de produção × "
            f"{descricao_rateio_fixos}."
        )

        custo_lote_sem_reserva = custo_insumos_total + custo_embalagens_total + custo_tintas_total + custo_equip_total + custo_fixos_total + custo_mao_obra
        reserva_valor_lote = custo_lote_sem_reserva * (reserva / 100)
        custo_total_lote = custo_lote_sem_reserva + reserva_valor_lote
        custo_unitario = custo_total_lote / qtd_total_lote if qtd_total_lote else 0

        preco_sugerido_lote = custo_total_lote * (1 + margem / 100)
        preco_sugerido = preco_sugerido_lote / qtd_total_lote if qtd_total_lote else 0

        preco_escolhido_lote = st.number_input("Preço escolhido do lote inteiro", min_value=0.0, value=0.0, step=0.01, format="%.2f")
        preco_final_lote = preco_escolhido_lote if preco_escolhido_lote > 0 else preco_sugerido_lote
        preco_final = preco_final_lote / qtd_total_lote if qtd_total_lote else 0
        lucro_lote = preco_final_lote - custo_total_lote
        lucro = preco_final - custo_unitario
        margem_real = lucro_lote / preco_final_lote * 100 if preco_final_lote else 0

        st.subheader("Resumo automático")
        r1, r2, r3, r4, rfix = st.columns(5)
        with r1:
            card("Insumos", real(custo_insumos_total))
        with r2:
            card("Tintas", real(custo_tintas_total))
        with r3:
            card("Equipamentos", real(custo_equip_total))
        with r4:
            card("Custos fixos", real(custo_fixos_total), descricao_rateio_fixos if incluir_custos_fixos else "Não incluídos")
        with rfix:
            card("Mão de obra", real(custo_mao_obra))

        r5, r6, r7, r8 = st.columns(4)
        with r5:
            card("Custo por unidade", real(custo_unitario))
        with r6:
            card("Preço sugerido unidade", real(preco_sugerido))
        with r7:
            card("Preço escolhido unidade", real(preco_final))
        with r8:
            card("Lucro unidade / Margem", real(lucro), f"{margem_real:.2f}%")

        r9, r10, r11, r12 = st.columns(4)
        with r9:
            card("Custo total do lote", real(custo_total_lote))
        with r10:
            card("Preço sugerido lote", real(preco_sugerido_lote))
        with r11:
            card("Preço escolhido lote", real(preco_final_lote))
        with r12:
            card("Lucro total", real(lucro_lote), f"{margem_real:.2f}%")

        receita_para_salvar = receita + embalagens_usadas

        if st.button("Salvar produto precificado"):
            if not nome.strip():
                st.error("Coloque o nome do produto.")
            else:
                foto_path = salvar_upload_produto_data_uri(foto_upload) if foto_upload else ""
                favorito_txt = "Sim" if favorito else "Não"

                # Salvar produto com segurança: usa somente colunas existentes no banco
                # e cria as colunas novas do catálogo se estiverem faltando.
                for _coluna, _tipo in {
                    "ativo": "TEXT DEFAULT 'Sim'",
                    "foto": "TEXT",
                    "descricao_catalogo": "TEXT",
                    "favorito": "TEXT DEFAULT 'Não'",
                    "status_catalogo": "TEXT DEFAULT 'Disponível'",
                }.items():
                    try:
                        executar(f"ALTER TABLE produtos ADD COLUMN {_coluna} {_tipo}")
                    except Exception:
                        pass

                dados_produto = {
                    "nome": nome,
                    "categoria": categoria_produto,
                    "qtd_por_lote": qtd_por_lote,
                    "qtd_por_folha": qtd_por_folha,
                    "receita_json": json.dumps(receita_para_salvar, ensure_ascii=False),
                    "tintas_json": json.dumps(tintas, ensure_ascii=False),
                    "equipamentos_json": json.dumps(equipamentos, ensure_ascii=False),
                    "tempo_min": tempo_min,
                    "valor_hora": valor_hora,
                    "reserva_erro": reserva,
                    "margem_lucro": margem,
                    "custo_insumos": custo_insumos_total,
                    "custo_tintas": custo_tintas_total,
                    "custo_equipamentos": custo_equip_total,
                    "custo_fixos": custo_fixos_total,
                    "custo_mao_obra": custo_mao_obra,
                    "custo_total_lote": custo_total_lote,
                    "custo_unitario": custo_unitario,
                    "preco_sugerido": preco_sugerido,
                    "preco_escolhido": preco_final,
                    "lucro_unitario": lucro,
                    "margem_real": margem_real,
                    "ativo": ativo,
                    "foto": foto_path,
                    "favorito": favorito_txt,
                    "status_catalogo": status_catalogo,
                    "descricao_catalogo": descricao_catalogo,
                }

                try:
                    colunas_banco = consultar("PRAGMA table_info(produtos)")["name"].tolist()
                except Exception:
                    colunas_banco = []

                dados_produto = {k: v for k, v in dados_produto.items() if k in colunas_banco}

                colunas = ", ".join(dados_produto.keys())
                placeholders = ", ".join(["?"] * len(dados_produto))
                valores = tuple(dados_produto.values())

                executar(
                    f"INSERT INTO produtos ({colunas}) VALUES ({placeholders})",
                    valores
                )
                st.success("Produto salvo.")
                st.rerun()

    with abas[1]:
        st.subheader("Editar produto existente")

        produtos_edit = consultar("""
        SELECT *
        FROM produtos
        ORDER BY nome
        """)

        if produtos_edit.empty:
            st.info("Nenhum produto cadastrado ainda.")
        else:
            mapa = {
                f"{codigo_visual('PROD', row['id'])} - {row['nome']}": int(row["id"])
                for _, row in produtos_edit.iterrows()
            }

            escolhido = st.selectbox("Escolha o produto para editar", list(mapa.keys()), key="produto_editar_select")
            produto_id = mapa[escolhido]
            p = consultar("SELECT * FROM produtos WHERE id=?", (int(produto_id),)).iloc[0]

            with st.form(f"form_editar_produto_{produto_id}"):
                c1, c2, c3 = st.columns([3, 2, 1])
                nome_edit = c1.text_input("Nome do produto", value=str(p.get("nome", "") or ""))
                categoria_edit = c2.text_input("Categoria", value=str(p.get("categoria", "") or ""))
                ativo_edit = c3.selectbox("Ativo?", ["Sim", "Não"], index=0 if str(p.get("ativo", "Sim")) == "Sim" else 1)

                c4, c5, c6 = st.columns(3)
                qtd_edit = c4.number_input("Quantidade por folha/lote", min_value=0.0, value=float(n(p.get("qtd_por_lote", 1), 1)), step=1.0)
                tempo_edit = c5.number_input("Tempo de produção do lote (min)", min_value=0.0, value=float(n(p.get("tempo_min", 0))), step=1.0)
                valor_hora_edit = c6.number_input("Valor hora mão de obra", min_value=0.0, value=float(n(p.get("valor_hora", 0))), step=0.01, format="%.2f")

                c7, c8, c9 = st.columns(3)
                reserva_edit = c7.number_input("Reserva de erro (%)", min_value=0.0, value=float(n(p.get("reserva_erro", 0))), step=0.1, format="%.2f")
                margem_lucro_edit = c8.number_input("Margem desejada (%)", min_value=0.0, value=float(n(p.get("margem_lucro", 0))), step=0.1, format="%.2f")
                status_atual = str(p.get("status_catalogo", "Disponível") or "Disponível")
                status_opcoes = ["Disponível", "Esgotado", "Sob encomenda"]
                status_catalogo_edit = c9.selectbox("Status no catálogo", status_opcoes, index=status_opcoes.index(status_atual) if status_atual in status_opcoes else 0)

                favorito_edit = st.selectbox("Favorito?", ["Não", "Sim"], index=1 if str(p.get("favorito", "Não")) == "Sim" else 0)

                descricao_edit = st.text_area(
                    "Descrição para catálogo público",
                    value=str(p.get("descricao_catalogo", "") or ""),
                    height=120,
                    help="Essa descrição aparece no catálogo público do cliente.",
                )

                st.markdown("#### Custos e preços")
                c10, c11, c12, c13 = st.columns(4)
                custo_insumos_edit = c10.number_input("Custo insumos", min_value=0.0, value=float(n(p.get("custo_insumos", 0))), step=0.01, format="%.2f")
                custo_tintas_edit = c11.number_input("Custo tintas", min_value=0.0, value=float(n(p.get("custo_tintas", 0))), step=0.01, format="%.2f")
                custo_equip_edit = c12.number_input("Custo equipamentos", min_value=0.0, value=float(n(p.get("custo_equipamentos", 0))), step=0.01, format="%.2f")
                custo_mao_obra_edit = c13.number_input("Custo mão de obra", min_value=0.0, value=float(n(p.get("custo_mao_obra", 0))), step=0.01, format="%.2f")

                recalcular = st.checkbox("Recalcular custo total, unitário, lucro e margem automaticamente", value=True)

                if recalcular:
                    custo_total_lote_edit = (custo_insumos_edit + custo_tintas_edit + custo_equip_edit + custo_mao_obra_edit) * (1 + reserva_edit / 100)
                    custo_unitario_edit = custo_total_lote_edit / qtd_edit if qtd_edit else 0
                    preco_sugerido_edit = custo_unitario_edit * (1 + margem_lucro_edit / 100)
                    preco_escolhido_base = float(n(p.get("preco_escolhido", 0)))
                    preco_escolhido_edit = st.number_input("Preço escolhido/final", min_value=0.0, value=preco_escolhido_base, step=0.01, format="%.2f")
                    preco_final_edit = preco_escolhido_edit if preco_escolhido_edit > 0 else preco_sugerido_edit
                    lucro_edit = preco_final_edit - custo_unitario_edit
                    margem_real_edit = lucro_edit / preco_final_edit * 100 if preco_final_edit else 0
                    st.caption(f"Custo unitário recalculado: {real(custo_unitario_edit)} | Preço sugerido: {real(preco_sugerido_edit)} | Lucro: {real(lucro_edit)} | Margem: {margem_real_edit:.2f}%")
                else:
                    c14, c15, c16, c17 = st.columns(4)
                    custo_total_lote_edit = c14.number_input("Custo total lote", min_value=0.0, value=float(n(p.get("custo_total_lote", 0))), step=0.01, format="%.2f")
                    custo_unitario_edit = c15.number_input("Custo unitário", min_value=0.0, value=float(n(p.get("custo_unitario", 0))), step=0.01, format="%.2f")
                    preco_sugerido_edit = c16.number_input("Preço sugerido", min_value=0.0, value=float(n(p.get("preco_sugerido", 0))), step=0.01, format="%.2f")
                    preco_escolhido_edit = c17.number_input("Preço escolhido/final", min_value=0.0, value=float(n(p.get("preco_escolhido", 0))), step=0.01, format="%.2f")
                    preco_final_edit = preco_escolhido_edit if preco_escolhido_edit > 0 else preco_sugerido_edit
                    lucro_edit = preco_final_edit - custo_unitario_edit
                    margem_real_edit = lucro_edit / preco_final_edit * 100 if preco_final_edit else 0

                st.markdown("#### Receita técnica salva")
                receita_texto = st.text_area("Insumos/embalagens utilizados (JSON)", value=str(p.get("receita_json", "") or "[]"), height=140)
                tintas_texto = st.text_area("Tintas utilizadas (JSON)", value=str(p.get("tintas_json", "") or "[]"), height=100)
                equipamentos_texto = st.text_area("Equipamentos utilizados (JSON)", value=str(p.get("equipamentos_json", "") or "[]"), height=100)

                foto_atual = str(p.get("foto", "") or "")
                st.text_input("Caminho da foto atual", value=foto_atual, disabled=True)
                nova_foto = st.file_uploader("Trocar foto do produto", type=["png", "jpg", "jpeg", "webp"], key=f"foto_edit_{produto_id}")

                b1, b2, b3 = st.columns(3)
                salvar = b1.form_submit_button("💾 Salvar alterações")
                duplicar = b2.form_submit_button("📄 Duplicar produto")
                excluir = b3.form_submit_button("🗑️ Excluir produto")

            if salvar:
                foto_path_edit = salvar_upload_produto_data_uri(nova_foto) if nova_foto else foto_atual
                antigo = consultar("SELECT nome, preco_escolhido, preco_sugerido, descricao_catalogo FROM produtos WHERE id=?", (int(produto_id),))
                if not antigo.empty:
                    try:
                        registrar_historico_preco("Produto", int(produto_id), nome_edit, "preco_escolhido", antigo.iloc[0]["preco_escolhido"], n(preco_escolhido_edit), "Alteração completa em Editar produto")
                        registrar_historico_preco("Produto", int(produto_id), nome_edit, "preco_sugerido", antigo.iloc[0]["preco_sugerido"], n(preco_sugerido_edit), "Alteração completa em Editar produto")
                    except Exception:
                        pass

                executar("""
                UPDATE produtos
                SET nome=?, categoria=?, qtd_por_lote=?, receita_json=?, tintas_json=?,
                    equipamentos_json=?, tempo_min=?, valor_hora=?, reserva_erro=?,
                    margem_lucro=?, custo_insumos=?, custo_tintas=?, custo_equipamentos=?,
                    custo_mao_obra=?, custo_total_lote=?, custo_unitario=?, preco_sugerido=?,
                    preco_escolhido=?, lucro_unitario=?, margem_real=?, ativo=?, foto=?,
                    favorito=?, status_catalogo=?, descricao_catalogo=?
                WHERE id=?
                """, (
                    nome_edit, categoria_edit, qtd_edit, receita_texto, tintas_texto,
                    equipamentos_texto, tempo_edit, valor_hora_edit, reserva_edit,
                    margem_lucro_edit, custo_insumos_edit, custo_tintas_edit, custo_equip_edit,
                    custo_mao_obra_edit, custo_total_lote_edit, custo_unitario_edit, preco_sugerido_edit,
                    preco_escolhido_edit, lucro_edit, margem_real_edit, ativo_edit, foto_path_edit,
                    favorito_edit, status_catalogo_edit, descricao_edit, int(produto_id),
                ))
                st.success("Produto atualizado com sucesso.")
                st.rerun()

            if duplicar:
                novo_nome = f"{nome_edit} - cópia"
                executar("""
                INSERT INTO produtos(
                    nome, categoria, qtd_por_lote, receita_json, tintas_json,
                    equipamentos_json, tempo_min, valor_hora, reserva_erro,
                    margem_lucro, custo_insumos, custo_tintas, custo_equipamentos,
                    custo_mao_obra, custo_total_lote, custo_unitario, preco_sugerido,
                    preco_escolhido, lucro_unitario, margem_real, ativo, foto,
                    favorito, status_catalogo, descricao_catalogo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    novo_nome, categoria_edit, qtd_edit, receita_texto, tintas_texto,
                    equipamentos_texto, tempo_edit, valor_hora_edit, reserva_edit,
                    margem_lucro_edit, custo_insumos_edit, custo_tintas_edit, custo_equip_edit,
                    custo_mao_obra_edit, custo_total_lote_edit, custo_unitario_edit, preco_sugerido_edit,
                    preco_escolhido_edit, lucro_edit, margem_real_edit, ativo_edit, foto_atual,
                    favorito_edit, status_catalogo_edit, descricao_edit,
                ))
                st.success(f"Produto duplicado como: {novo_nome}")
                st.rerun()

            if excluir:
                executar("DELETE FROM produtos WHERE id=?", (int(produto_id),))
                st.success("Produto excluído.")
                st.rerun()

    with abas[2]:
        st.subheader("Lista rápida de produtos e preços")
        df = consultar("""
        SELECT id, nome, categoria, qtd_por_lote, custo_unitario, preco_sugerido,
               preco_escolhido, lucro_unitario, margem_real, favorito, ativo,
               descricao_catalogo
        FROM produtos
        ORDER BY id DESC
        """)

        if df.empty:
            st.info("Nenhum produto cadastrado.")
        else:
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
                    "descricao_catalogo": st.column_config.TextColumn("Descrição catálogo", width="large"),
                },
                key="editor_produtos",
            )

            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                if st.button("Salvar alterações rápidas dos produtos"):
                    for _, r in edited.iterrows():
                        antigo = consultar("SELECT preco_escolhido, preco_sugerido FROM produtos WHERE id=?", (int(r["id"]),))
                        if not antigo.empty:
                            try:
                                registrar_historico_preco("Produto", int(r["id"]), r["nome"], "preco_escolhido", antigo.iloc[0]["preco_escolhido"], n(r["preco_escolhido"]), "Alteração rápida em Produtos")
                                registrar_historico_preco("Produto", int(r["id"]), r["nome"], "preco_sugerido", antigo.iloc[0]["preco_sugerido"], n(r["preco_sugerido"]), "Alteração rápida em Produtos")
                            except Exception:
                                pass
                        executar("""
                        UPDATE produtos
                        SET nome=?, categoria=?, qtd_por_lote=?, custo_unitario=?,
                            preco_sugerido=?, preco_escolhido=?, lucro_unitario=?,
                            margem_real=?, favorito=?, ativo=?, descricao_catalogo=?
                        WHERE id=?
                        """, (
                            r["nome"], r["categoria"], n(r["qtd_por_lote"]), n(r["custo_unitario"]),
                            n(r["preco_sugerido"]), n(r["preco_escolhido"]), n(r["lucro_unitario"]),
                            n(r["margem_real"]), r.get("favorito", "Não"), "Disponível",
                            r["ativo"], r.get("descricao_catalogo", ""), int(r["id"]),
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

    with abas[3]:
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
    produtos = consultar_produtos_catalogo_seguro()

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
                produto_id_preco = int(dados_produto["id"])
                categoria = str(dados_produto["categoria"] or "")
                preco_escolhido = n(dados_produto["preco_escolhido"])
                preco_sugerido = n(dados_produto["preco_sugerido"])
                valor_padrao = preco_escolhido if preco_escolhido > 0 else preco_sugerido
                c2.text_input(f"Categoria {i + 1}", value=categoria, disabled=True, key=f"orc_categoria_{i}_{produto_id_preco}")

            c3, c4, c5, c6 = st.columns(4)
            quantidade = c3.number_input(f"Quantidade {i + 1}", min_value=0.0, value=1.0, step=1.0, key=f"orc_qtd_{i}")
            chave_valor_unitario = f"orc_unit_{i}"
            if not modo_manual:
                try:
                    chave_valor_unitario = f"orc_unit_{i}_{produto_id_preco}"
                except Exception:
                    chave_valor_unitario = f"orc_unit_{i}"

            valor_unitario = c4.number_input(
                f"Valor unitário {i + 1}",
                min_value=0.0,
                value=float(valor_padrao),
                step=0.50,
                format="%.2f",
                key=chave_valor_unitario,
            )
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


    st.divider()
    st.subheader("Entrega / prazo do pedido")
    st.caption("Essa data vai alimentar Produção, Agenda, Entregas e Portal do Cliente.")

    e1, e2, e3 = st.columns(3)
    data_prevista_entrega = e1.text_input(
        "Data prevista de entrega",
        value=daqui_dias_br(7),
        key="novo_orc_data_entrega",
    )
    hora_prevista_entrega = e2.text_input(
        "Horário previsto",
        placeholder="Ex: 14:00",
        key="novo_orc_hora_entrega",
    )
    tipo_entrega_orc = e3.selectbox(
        "Tipo de entrega",
        ["Retirada", "Entrega própria", "Motoboy", "Correios", "Uber/99", "Outro"],
        key="novo_orc_tipo_entrega",
    )

    e4, e5 = st.columns(2)
    prioridade_entrega = e4.selectbox(
        "Prioridade",
        ["Normal", "Urgente", "Expressa", "Baixa"],
        key="novo_orc_prioridade_entrega",
    )
    responsavel_entrega = e5.text_input(
        "Responsável pela entrega",
        placeholder="Ex: Maiara / Motoboy / Cliente retira",
        key="novo_orc_responsavel_entrega",
    )

    endereco_entrega = st.text_area(
        "Endereço de entrega",
        key="novo_orc_endereco_entrega",
    )
    observacoes_entrega = st.text_area(
        "Observações da entrega",
        key="novo_orc_obs_entrega",
    )

    forma_pagamento = st.selectbox("Forma de pagamento", ["Pix", "Dinheiro", "Cartão de crédito", "Cartão de débito", "Mercado Pago", "Outro"])
    status = st.selectbox("Status", ["Em orçamento", "Aprovado", "Aguardando pagamento", "Pago", "Produção", "Embalagem", "Pronto", "Saiu para entrega", "Entregue", "Cancelado"])
    observacoes = st.text_area("Observações do orçamento")

    if st.button("Salvar orçamento"):
        itens_validos = [item for item in itens if str(item["produto"]).strip()]
        if not itens_validos:
            st.error("Adicione pelo menos um produto ao orçamento.")
        else:
            ultimo = executar("""
            INSERT INTO orcamentos(
                cliente_id, cliente_nome, whatsapp, data_orcamento, status, forma_pagamento,
                subtotal, desconto, frete, total, observacoes,
                data_prevista_entrega, hora_prevista_entrega, tipo_entrega,
                endereco_entrega, responsavel_entrega, prioridade_entrega, observacoes_entrega
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                int(cliente_id), str(cliente["nome"]), str(cliente["whatsapp"]), agora_iso_brasil(), status,
                forma_pagamento, subtotal, desconto_geral, frete, total_geral, observacoes,
                data_iso(data_prevista_entrega), hora_prevista_entrega, tipo_entrega_orc,
                endereco_entrega, responsavel_entrega, prioridade_entrega, observacoes_entrega,
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

            if status in ["Pago", "Produção", "Finalizado", "Entregue"]:
                executar("""
                INSERT INTO financeiro(data, tipo, descricao, categoria, forma_pagamento, valor, origem, referencia_id, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (hoje_iso(), "Entrada", f"Orçamento #{ultimo} - {cliente['nome']}", "Venda", forma_pagamento, total_geral, "Orçamento", int(ultimo), observacoes))

            garantir_ordem_producao(int(ultimo))
            if status in ["Produção", "ProduÃ§Ã£o", "Finalizado", "Entregue"]:
                criar_op_de_orcamento(int(ultimo), prioridade="Normal", observacoes_extra="Criada automaticamente ao salvar orçamento.")
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
            formatar_valores_tabela(itens_df),
            use_container_width=True,
            hide_index=True,
            column_config={
                "valor_unitario": st.column_config.NumberColumn("Valor unitário", format="R$ %.2f"),
                "desconto": st.column_config.NumberColumn("Desconto", format="R$ %.2f"),
                "total": st.column_config.NumberColumn("Total", format="R$ %.2f"),
            },
        )

        orc_status_df = consultar("""
        SELECT status, total, cliente_nome, forma_pagamento, observacoes,
               data_prevista_entrega, hora_prevista_entrega, tipo_entrega,
               endereco_entrega, responsavel_entrega, prioridade_entrega, observacoes_entrega
        FROM orcamentos
        WHERE id=?
        """, (int(id_ver),))

        if not orc_status_df.empty:
            st.markdown("### Alterar status e entrega do orçamento")
            status_atual = str(orc_status_df.iloc[0]["status"])
            opcoes_status = status_fluxo_pedido()
            try:
                idx_status = opcoes_status.index(status_atual)
            except Exception:
                idx_status = 0

            novo_status_orc = st.selectbox(
                "Status do pedido",
                opcoes_status,
                index=idx_status,
                key=f"status_orc_existente_{int(id_ver)}",
            )

            st.markdown(linha_tempo_pedido_html(novo_status_orc), unsafe_allow_html=True)

            st.markdown("#### Entrega / prazo")
            d1, d2, d3 = st.columns(3)
            data_prevista_edit = d1.text_input(
                "Data prevista",
                value=data_br(orc_status_df.iloc[0].get("data_prevista_entrega", "") or ""),
                key=f"edit_data_entrega_{int(id_ver)}",
            )
            hora_prevista_edit = d2.text_input(
                "Horário",
                value=str(orc_status_df.iloc[0].get("hora_prevista_entrega", "") or ""),
                key=f"edit_hora_entrega_{int(id_ver)}",
            )

            tipos_entrega = ["Retirada", "Entrega própria", "Motoboy", "Correios", "Uber/99", "Outro"]
            tipo_atual = str(orc_status_df.iloc[0].get("tipo_entrega", "") or "Retirada")
            tipo_idx = tipos_entrega.index(tipo_atual) if tipo_atual in tipos_entrega else 0
            tipo_entrega_edit = d3.selectbox(
                "Tipo",
                tipos_entrega,
                index=tipo_idx,
                key=f"edit_tipo_entrega_{int(id_ver)}",
            )

            d4, d5 = st.columns(2)
            prioridades = ["Normal", "Urgente", "Expressa", "Baixa"]
            prioridade_atual = str(orc_status_df.iloc[0].get("prioridade_entrega", "") or "Normal")
            prioridade_idx = prioridades.index(prioridade_atual) if prioridade_atual in prioridades else 0
            prioridade_edit = d4.selectbox(
                "Prioridade",
                prioridades,
                index=prioridade_idx,
                key=f"edit_prioridade_entrega_{int(id_ver)}",
            )
            responsavel_edit = d5.text_input(
                "Responsável",
                value=str(orc_status_df.iloc[0].get("responsavel_entrega", "") or ""),
                key=f"edit_responsavel_entrega_{int(id_ver)}",
            )

            endereco_edit = st.text_area(
                "Endereço de entrega",
                value=str(orc_status_df.iloc[0].get("endereco_entrega", "") or ""),
                key=f"edit_endereco_entrega_{int(id_ver)}",
            )
            obs_entrega_edit = st.text_area(
                "Observações de entrega",
                value=str(orc_status_df.iloc[0].get("observacoes_entrega", "") or ""),
                key=f"edit_obs_entrega_{int(id_ver)}",
            )

            if st.button("Atualizar status e entrega do orçamento", key=f"btn_atualizar_status_orc_{int(id_ver)}"):
                executar("""
                UPDATE orcamentos
                SET status=?,
                    data_prevista_entrega=?,
                    hora_prevista_entrega=?,
                    tipo_entrega=?,
                    endereco_entrega=?,
                    responsavel_entrega=?,
                    prioridade_entrega=?,
                    observacoes_entrega=?
                WHERE id=?
                """, (
                    novo_status_orc,
                    data_iso(data_prevista_edit),
                    hora_prevista_edit,
                    tipo_entrega_edit,
                    endereco_edit,
                    responsavel_edit,
                    prioridade_edit,
                    obs_entrega_edit,
                    int(id_ver),
                ))

                aplicar_fluxo_status_orcamento(int(id_ver), novo_status_orc)
                st.success("Status e entrega atualizados com sucesso.")
                st.rerun()


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
                    "Baixar etiqueta da encomenda com QR do portal",
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
        st.dataframe(formatar_valores_tabela(saldo), use_container_width=True, hide_index=True)

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

    # O QR Code agora abre o Portal do Cliente/status do pedido.
    try:
        token = gerar_token_portal("Orçamento", int(orcamento_id))
    except Exception:
        token = ""

    try:
        base_url = obter_config("catalogo_link_base", "").strip()
    except Exception:
        base_url = ""

    if not base_url:
        base_url = "https://sophipersonalizadosoficial.streamlit.app"

    base_url = base_url.split("?")[0].rstrip("/")
    portal_url = f"{base_url}/?portal=cliente&token={token}" if token else f"{base_url}/?portal=cliente"

    try:
        import urllib.parse
        qr_url = "https://api.qrserver.com/v1/create-qr-code/?size=130x130&data=" + urllib.parse.quote(portal_url)
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
.link {{
    font-size: 8px;
    max-width: 48mm;
    word-break: break-all;
    color: #555;
    margin-top: 5px;
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
        <p class="link">QR: Portal do Cliente / Status do Pedido</p>
    </div>
    <div class="qr">
        <img src="{qr_url}">
    </div>
</div>
</body>
</html>"""
    return html





# ============================================================
# VISUAL LIMPO PARA CATÁLOGO / PORTAL PÚBLICO
# ============================================================

def aplicar_visual_publico_limpo():
    st.markdown("""
    <style>
    #MainMenu {visibility: hidden !important; display: none !important;}
    header {visibility: hidden !important; display: none !important;}
    footer {visibility: hidden !important; display: none !important;}
    [data-testid="stToolbar"] {display: none !important;}
    [data-testid="stDecoration"] {display: none !important;}
    [data-testid="stStatusWidget"] {display: none !important;}
    [data-testid="stHeader"] {display: none !important;}
    [data-testid="stFooter"] {display: none !important;}
    .stDeployButton, [data-testid="stDeployButton"],
    .st-emotion-cache-1dp5vir,
    .st-emotion-cache-1avcm0n,
    .st-emotion-cache-zq5wmm {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 3rem !important;
    }
    a[href^="#"] {display: none !important;}
    </style>
    """, unsafe_allow_html=True)


def gerar_html_catalogo_publico():
    produtos = consultar_produtos_catalogo_seguro()

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












# ============================================================
# MÓDULO 1 — KITS
# ============================================================

def buscar_itens_para_kit(tipo):
    try:
        if tipo in ["Insumo", "Brinde", "Embalagem", "Papel"]:
            if tipo == "Embalagem":
                return consultar("""
                SELECT id, nome, categoria, valor_pacote, quantidade_pacote
                FROM insumos
                WHERE ativo='Sim' AND (
                    LOWER(categoria) LIKE '%embalagem%'
                    OR LOWER(categoria) LIKE '%sacola%'
                    OR LOWER(categoria) LIKE '%caixa%'
                    OR LOWER(categoria) LIKE '%envelope%'
                )
                ORDER BY categoria, nome
                """)
            if tipo == "Papel":
                return consultar("""
                SELECT id, nome, categoria, valor_pacote, quantidade_pacote
                FROM insumos
                WHERE ativo='Sim' AND LOWER(categoria) LIKE '%papel%'
                ORDER BY categoria, nome
                """)
            if tipo == "Brinde":
                return consultar("""
                SELECT id, nome, categoria, valor_pacote, quantidade_pacote
                FROM insumos
                WHERE ativo='Sim' AND LOWER(categoria) LIKE '%brinde%'
                ORDER BY categoria, nome
                """)
            return consultar("""
            SELECT id, nome, categoria, valor_pacote, quantidade_pacote
            FROM insumos
            WHERE ativo='Sim'
            ORDER BY categoria, nome
            """)

        if tipo == "Produto":
            return consultar("""
            SELECT id, nome, categoria, custo_unitario AS valor_pacote, 1 AS quantidade_pacote
            FROM produtos
            WHERE ativo='Sim'
            ORDER BY categoria, nome
            """)

        if tipo == "Laminação":
            return consultar("""
            SELECT id, nome, tipo AS categoria, custo_a4 AS valor_pacote, 1 AS quantidade_pacote
            FROM laminacoes
            WHERE ativo='Sim'
            ORDER BY tipo, nome
            """)

        if tipo == "Manta / Ímã":
            return consultar("""
            SELECT id, nome, tipo AS categoria, custo_unitario AS valor_pacote, 1 AS quantidade_pacote
            FROM mantas_imas
            WHERE ativo='Sim'
            ORDER BY tipo, nome
            """)

        if tipo == "Tinta":
            return consultar("""
            SELECT id, nome, 'Tinta' AS categoria, valor_kit, rendimento_impressoes
            FROM tintas
            WHERE ativo='Sim'
            ORDER BY nome
            """)

        return pd.DataFrame()

    except Exception:
        return pd.DataFrame()


def seletor_item_kit(linha):
    tipos = ["Insumo", "Produto", "Embalagem", "Papel", "Laminação", "Manta / Ímã", "Tinta", "Brinde", "Manual"]

    c1, c2, c3, c4 = st.columns([1.7, 4, 1.2, 1.3])
    tipo = c1.selectbox("Tipo", tipos, key=f"kit_tipo_{linha}")

    if tipo == "Manual":
        nome = c2.text_input("Item manual", key=f"kit_manual_nome_{linha}", placeholder="Ex: Bombom Nestlé")
        qtd = c3.number_input("Qtd", min_value=0.0, value=1.0, step=1.0, key=f"kit_manual_qtd_{linha}")
        custo_unit = c4.number_input("Custo un.", min_value=0.0, value=0.0, step=0.01, format="%.2f", key=f"kit_manual_custo_{linha}")

        if not nome.strip() or qtd <= 0:
            return None

        return {
            "tipo": tipo,
            "id": None,
            "nome": nome,
            "categoria": "Manual",
            "qtd": qtd,
            "custo_unitario": custo_unit,
            "total": qtd * custo_unit,
        }

    df = buscar_itens_para_kit(tipo)

    if df.empty:
        c2.selectbox("Item", ["Nenhum cadastrado"], key=f"kit_item_{linha}")
        c3.number_input("Qtd", min_value=0.0, value=0.0, key=f"kit_qtd_{linha}")
        c4.text_input("Total", value=real(0), disabled=True, key=f"kit_custo_{linha}")
        return None

    opcoes = ["Nenhum"]
    mapa = {}

    for _, r in df.iterrows():
        if tipo == "Tinta":
            custo = custo_tinta(r["valor_kit"], r["rendimento_impressoes"])
        else:
            custo = custo_insumo(r["valor_pacote"], r["quantidade_pacote"])

        label = f"{r['nome']} — {r['categoria']} — {real(custo)}"
        opcoes.append(label)
        mapa[label] = {
            "tipo": tipo,
            "id": int(r["id"]),
            "nome": r["nome"],
            "categoria": r["categoria"],
            "custo_unitario": custo,
        }

    escolhido = c2.selectbox("Item", opcoes, key=f"kit_item_{linha}")

    qtd = c3.number_input(
        "Qtd",
        min_value=0.0,
        value=1.0 if escolhido != "Nenhum" else 0.0,
        step=1.0,
        key=f"kit_qtd_{linha}",
    )

    if escolhido == "Nenhum" or qtd <= 0:
        c4.text_input("Total", value=real(0), disabled=True, key=f"kit_custo_{linha}")
        return None

    item = mapa[escolhido]
    item["qtd"] = qtd
    item["total"] = item["custo_unitario"] * qtd
    c4.text_input("Total", value=real(item["total"]), disabled=True, key=f"kit_custo_{linha}")

    return item


def codigo_kit(kit_id):
    try:
        return codigo_visual("KIT", int(kit_id))
    except Exception:
        return f"KIT-{int(kit_id):04d}"


def registrar_historico_kit(kit_id, acao, observacoes=""):
    try:
        executar("""
        INSERT INTO historico_kits(kit_id, acao, observacoes)
        VALUES (?, ?, ?)
        """, (int(kit_id), str(acao), str(observacoes)))
    except Exception:
        pass


def calcular_preco_kit(custo_total, margem):
    return n(custo_total) * (1 + n(margem) / 100)







def garantir_tabela_producao():
    """Garante que a tabela de produção tenha todas as colunas, mesmo em banco antigo."""
    try:
        executar("""
        CREATE TABLE IF NOT EXISTS ordens_producao (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        )
        """)
    except Exception:
        pass

    colunas = {
        "codigo": "TEXT",
        "orcamento_id": "INTEGER",
        "cliente_nome": "TEXT",
        "whatsapp": "TEXT",
        "data_criacao": "TEXT DEFAULT CURRENT_TIMESTAMP",
        "data_entrega": "TEXT",
        "prioridade": "TEXT DEFAULT 'Normal'",
        "status": "TEXT DEFAULT 'Aguardando'",
        "itens_json": "TEXT",
        "materiais_json": "TEXT",
        "checklist_json": "TEXT",
        "observacoes": "TEXT",
        "ativo": "TEXT DEFAULT 'Sim'",
    }

    for coluna, tipo in colunas.items():
        try:
            executar(f"ALTER TABLE ordens_producao ADD COLUMN {coluna} {tipo}")
        except Exception:
            pass

    try:
        executar("""
        UPDATE ordens_producao
        SET codigo = 'OP-' || strftime('%Y','now') || '-' || printf('%04d', id)
        WHERE codigo IS NULL OR codigo = ''
        """)
    except Exception:
        pass

    try:
        executar("""
        CREATE TABLE IF NOT EXISTS historico_producao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER,
            data TEXT DEFAULT CURRENT_TIMESTAMP,
            acao TEXT,
            observacoes TEXT
        )
        """)
    except Exception:
        pass


def tela_producao():
    garantir_tabela_producao()
    st.title("Produção")
    st.write("Central de produção com Ordem de Produção, checklist, prioridade, prazos e ficha para impressão.")

    abas = st.tabs(["Painel de produção", "Criar OP", "Ficha da OP", "Histórico"])

    with abas[0]:
        st.subheader("Painel de produção")

        ops = consultar("""
        SELECT id, orcamento_id, cliente_nome, whatsapp, data_criacao,
               data_entrega, prioridade, status, observacoes
        FROM ordens_producao
        WHERE ativo='Sim'
        ORDER BY
            CASE prioridade
                WHEN 'Urgente' THEN 1
                WHEN 'Normal' THEN 2
                WHEN 'Baixa' THEN 3
                ELSE 4
            END,
            data_entrega ASC,
            id DESC
        """)

        if ops.empty:
            st.info("Ainda não há ordens de produção.")
        else:
            ops["codigo"] = ops["id"].apply(codigo_op_seguro)
            hoje = datetime.now().date()

            atrasadas = 0
            entregas_hoje = 0
            produzindo = 0
            aguardando = 0

            for _, r in ops.iterrows():
                try:
                    d = pd.to_datetime(r["data_entrega"], errors="coerce").date()
                    if d < hoje and r["status"] not in ["Entregue", "Cancelado"]:
                        atrasadas += 1
                    if d == hoje and r["status"] not in ["Entregue", "Cancelado"]:
                        entregas_hoje += 1
                except Exception:
                    pass

                if r["status"] == "Produzindo":
                    produzindo += 1
                if r["status"] == "Aguardando":
                    aguardando += 1

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                card("Aguardando", str(aguardando))
            with c2:
                card("Produzindo", str(produzindo))
            with c3:
                card("Entregas hoje", str(entregas_hoje))
            with c4:
                card("Atrasadas", str(atrasadas))

            st.divider()

            filtro_status = st.selectbox("Filtrar por status", ["Todos", "Aguardando", "Produzindo", "Finalizado", "Entregue", "Cancelado"])
            filtro_prioridade = st.selectbox("Filtrar por prioridade", ["Todas", "Urgente", "Normal", "Baixa"])

            df_view = ops.copy()

            if filtro_status != "Todos":
                df_view = df_view[df_view["status"] == filtro_status]

            if filtro_prioridade != "Todas":
                df_view = df_view[df_view["prioridade"] == filtro_prioridade]

            edited = st.data_editor(
                df_view,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="editor_ops",
                column_config={
                    "status": st.column_config.SelectboxColumn(
                        "Status",
                        options=["Aguardando", "Produzindo", "Finalizado", "Entregue", "Cancelado"],
                    ),
                    "prioridade": st.column_config.SelectboxColumn(
                        "Prioridade",
                        options=["Urgente", "Normal", "Baixa"],
                    ),
                },
            )

            c1, c2 = st.columns([2, 1])
            with c1:
                if st.button("Salvar alterações das OPs"):
                    for _, r in edited.iterrows():
                        if str(r.get("codigo", "")).strip():
                            executar("""
                            UPDATE ordens_producao
                            SET data_entrega=?, prioridade=?, status=?, observacoes=?
                            WHERE id=?
                            """, (
                                str(r.get("data_entrega", "")),
                                str(r.get("prioridade", "Normal")),
                                str(r.get("status", "Aguardando")),
                                str(r.get("observacoes", "")),
                                int(r["id"]),
                            ))
                            registrar_historico_producao(int(r["id"]), "OP atualizada", f"Status: {r.get('status', '')}")
                    st.success("Produção atualizada.")
                    st.rerun()

            with c2:
                id_cancelar = st.number_input("ID para cancelar/excluir", min_value=0, step=1, key="cancelar_op")
                if st.button("Cancelar OP"):
                    if id_cancelar > 0:
                        executar("UPDATE ordens_producao SET ativo='Não', status='Cancelado' WHERE id=?", (int(id_cancelar),))
                        registrar_historico_producao(int(id_cancelar), "OP cancelada", "Cancelada pelo painel.")
                        st.success("OP cancelada.")
                        st.rerun()

    with abas[1]:
        st.subheader("Criar OP manualmente ou a partir de orçamento")

        orcs = consultar("""
        SELECT id, cliente_nome, whatsapp, status, total, data_orcamento
        FROM orcamentos
        ORDER BY id DESC
        """)

        if orcs.empty:
            st.info("Ainda não há orçamentos para gerar OP.")
        else:
            opcoes = []
            mapa = {}

            for _, r in orcs.iterrows():
                label = f"ORC-{int(r['id']):04d} | {r['cliente_nome']} | {real(r['total'])} | {r['status']}"
                opcoes.append(label)
                mapa[label] = int(r["id"])

            escolhido = st.selectbox("Escolha um orçamento", opcoes)

            c1, c2 = st.columns(2)
            prioridade = c1.selectbox("Prioridade", ["Normal", "Urgente", "Baixa"])
            data_entrega = c2.text_input("Data de entrega", value=(datetime.now().date() + timedelta(days=7)).isoformat())

            obs = st.text_area("Observações extras da produção")

            if st.button("Criar Ordem de Produção"):
                orc_id = mapa[escolhido]
                op_id = criar_op_de_orcamento(orc_id, prioridade=prioridade, data_entrega=data_entrega, observacoes_extra=obs)

                if op_id:
                    st.success(f"OP criada: {codigo_op(op_id)}")
                    st.rerun()
                else:
                    st.error("Não foi possível criar OP. Talvez ela já exista para este orçamento.")

    with abas[2]:
        st.subheader("Ficha da Ordem de Produção")

        ops = consultar("""
        SELECT id, cliente_nome, status, prioridade, data_entrega
        FROM ordens_producao
        WHERE ativo='Sim'
        ORDER BY id DESC
        """)

        if ops.empty:
            st.info("Nenhuma OP cadastrada.")
        else:
            ops["codigo"] = ops["id"].apply(codigo_op_seguro)
            mapa = {
                f"{row['codigo']} | {row['cliente_nome']} | {row['status']}": int(row["id"])
                for _, row in ops.iterrows()
            }

            escolhido = st.selectbox("Escolha uma OP", list(mapa.keys()), key="select_ficha_op")
            op_id = mapa[escolhido]

            op = consultar("SELECT * FROM ordens_producao WHERE id=?", (int(op_id),))

            if not op.empty:
                o = op.iloc[0]

                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    card("OP", o["codigo"])
                with c2:
                    card("Cliente", o["cliente_nome"])
                with c3:
                    card("Status", o["status"])
                with c4:
                    card("Prioridade", o["prioridade"])

                st.write(f"**WhatsApp:** {o['whatsapp'] or '-'}")
                st.write(f"**Orçamento:** #{o['orcamento_id'] or '-'}")
                st.write(f"**Data de entrega:** {o['data_entrega'] or '-'}")
                st.write(f"**Observações:** {o['observacoes'] or '-'}")

                st.markdown("### Checklist da produção")

                try:
                    checklist = json.loads(o["checklist_json"] or "{}")
                except Exception:
                    checklist = checklist_padrao_producao()

                novo_checklist = {}

                cks = st.columns(3)
                for idx, (nome_check, valor) in enumerate(checklist.items()):
                    with cks[idx % 3]:
                        novo_checklist[nome_check] = st.checkbox(nome_check, value=bool(valor), key=f"check_{op_id}_{nome_check}")

                if st.button("Salvar checklist da OP"):
                    novo_status = status_por_checklist(novo_checklist)
                    executar("""
                    UPDATE ordens_producao
                    SET checklist_json=?, status=?
                    WHERE id=?
                    """, (
                        json.dumps(novo_checklist, ensure_ascii=False),
                        novo_status,
                        int(op_id),
                    ))
                    registrar_historico_producao(int(op_id), "Checklist atualizado", f"Novo status: {novo_status}")

                    if novo_status == "Entregue":
                        try:
                            baixar_estoque_op(int(op_id))
                        except Exception:
                            pass

                    st.success("Checklist salvo.")
                    st.rerun()

                st.markdown("### Itens do pedido")
                try:
                    itens = json.loads(o["itens_json"] or "[]")
                    if itens:
                        st.dataframe(formatar_valores_tabela(pd.DataFrame(itens)), use_container_width=True, hide_index=True)
                    else:
                        st.info("Nenhum item salvo.")
                except Exception:
                    st.warning("Não foi possível ler os itens.")

                st.markdown("### Materiais necessários")
                try:
                    materiais = json.loads(o["materiais_json"] or "[]")
                    if materiais:
                        st.dataframe(formatar_valores_tabela(pd.DataFrame(materiais)), use_container_width=True, hide_index=True)
                    else:
                        st.info("Nenhum material encontrado automaticamente.")
                except Exception:
                    st.warning("Não foi possível ler os materiais.")

                html = gerar_html_ficha_producao(int(op_id))
                if html:
                    st.download_button(
                        "Baixar ficha de produção para imprimir",
                        data=html.encode("utf-8"),
                        file_name=f"ficha_producao_{codigo_op_seguro(o['id'])}.html",
                        mime="text/html",
                    )

    with abas[3]:
        st.subheader("Histórico de produção")

        hist = consultar("""
        SELECT
            h.data,
            COALESCE(o.codigo, 'OP-' || strftime('%Y','now') || '-' || printf('%04d', o.id)) AS codigo,
            o.cliente_nome,
            h.acao,
            h.observacoes
        FROM historico_producao h
        LEFT JOIN ordens_producao o ON o.id = h.op_id
        ORDER BY h.id DESC
        LIMIT 300
        """)

        if hist.empty:
            st.info("Sem histórico ainda.")
        else:
            if "op_id" in hist.columns:
                hist["codigo"] = hist["op_id"].apply(lambda x: codigo_op_seguro(x) if pd.notna(x) else "")
                cols = ["data", "codigo", "cliente_nome", "acao", "observacoes"]
                hist = hist[[c for c in cols if c in hist.columns]]
            st.dataframe(hist, use_container_width=True, hide_index=True)



def _numero_venda(nid):
    return f"VD-{datetime.now().year}-{int(nid):05d}"


def _html_comprovante_termico(venda_id, largura_mm=80):
    venda = consultar("SELECT * FROM vendas WHERE id=?", (int(venda_id),))
    itens = consultar("SELECT * FROM venda_itens WHERE venda_id=? ORDER BY id", (int(venda_id),))
    if venda.empty:
        return ""
    v = venda.iloc[0]
    empresa = obter_config("nome_empresa", EMPRESA)
    whatsapp = obter_config("whatsapp", "")
    instagram = obter_config("instagram", "")
    endereco = obter_config("catalogo_endereco", "")
    pix = obter_config("pix", "")
    logo = obter_config("logo_path", "")
    logo_html = ""
    if logo and Path(logo).exists():
        b64 = imagem_base64(logo)
        ext = Path(logo).suffix.replace('.', '').lower() or 'png'
        logo_html = f'<img src="data:image/{ext};base64,{b64}" style="max-width:90px;max-height:60px;filter:grayscale(1);">'
    linhas = ""
    for _, r in itens.iterrows():
        linhas += f"""
        <tr><td colspan="3"><b>{html.escape(str(r['produto']))}</b></td></tr>
        <tr><td>{n(r['quantidade']):.0f} x {real(r['valor_unitario'])}</td><td></td><td class="right">{real(r['total'])}</td></tr>
        """
    saldo = n(v.get('saldo_pendente', 0))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
    @page{{size:{largura_mm}mm auto;margin:2mm}} body{{font-family:Arial,sans-serif;width:{largura_mm-6}mm;margin:0 auto;font-size:11px;color:#000}}
    .center{{text-align:center}} .right{{text-align:right}} .sep{{border-top:1px dashed #000;margin:7px 0}} table{{width:100%;border-collapse:collapse}} td{{padding:2px 0;vertical-align:top}}
    .total{{font-size:16px;font-weight:800}} .small{{font-size:9px}} button{{margin:10px 0;padding:8px;width:100%}} @media print{{button{{display:none}}}}
    </style></head><body><button onclick="window.print()">Imprimir</button><div class="center">{logo_html}<br><b>{html.escape(empresa)}</b><br><span class="small">Desde 2018</span><br>{html.escape(whatsapp)}<br>{html.escape(instagram)}<br>{html.escape(endereco)}</div>
    <div class="sep"></div><b>VENDA:</b> {html.escape(str(v.get('numero','')))}<br><b>DATA/HORA DA VENDA:</b> {data_hora_br_segura(v.get('data_criacao','')) or data_hora_br_segura(v.get('data',''))}<br><b>EMISSÃO:</b> {agora_brasil().strftime('%d/%m/%Y %H:%M')}<br><b>CLIENTE:</b> {html.escape(str(v.get('cliente_nome','Consumidor')))}<br><b>ORIGEM:</b> {html.escape(str(v.get('origem','')))}
    <div class="sep"></div><table>{linhas}</table><div class="sep"></div>
    <table><tr><td>Subtotal</td><td class="right">{real(v.get('subtotal',0))}</td></tr><tr><td>Desconto</td><td class="right">-{real(v.get('desconto',0))}</td></tr><tr><td>Acréscimo/Frete</td><td class="right">{real(n(v.get('acrescimo',0))+n(v.get('frete',0)))}</td></tr><tr><td class="total">TOTAL</td><td class="right total">{real(v.get('total',0))}</td></tr><tr><td>Recebido</td><td class="right">{real(v.get('valor_recebido',0))}</td></tr><tr><td>Troco</td><td class="right">{real(v.get('troco',0))}</td></tr>{f'<tr><td><b>Saldo pendente</b></td><td class="right"><b>{real(saldo)}</b></td></tr>' if saldo>0 else ''}</table>
    <div class="sep"></div><b>Pagamento:</b> {html.escape(str(v.get('forma_pagamento','')))}<br><b>Produção:</b> {html.escape(str(v.get('status_producao','')))}<br><b>Entrega:</b> {data_br_segura(v.get('data_entrega','')) or '-'}<br><br><div class="center">Obrigada pela preferência! 🖤<br>{('PIX: '+html.escape(pix)) if pix else ''}</div></body></html>"""


def _html_etiqueta_pedido(venda_id, largura_mm=50, altura_mm=30):
    venda = consultar("SELECT * FROM vendas WHERE id=?", (int(venda_id),))
    itens = consultar("SELECT * FROM venda_itens WHERE venda_id=? ORDER BY id", (int(venda_id),))
    if venda.empty:
        return ""
    v=venda.iloc[0]
    resumo=', '.join([f"{n(r['quantidade']):.0f}x {r['produto']}" for _,r in itens.iterrows()])
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>@page{{size:{largura_mm}mm {altura_mm}mm;margin:1.5mm}}body{{font-family:Arial;width:{largura_mm-4}mm;height:{altura_mm-4}mm;margin:0;font-size:9px;overflow:hidden}}.big{{font-size:13px;font-weight:800}}.sep{{border-top:1px solid #000;margin:3px 0}}button{{font-size:10px}}@media print{{button{{display:none}}}}</style></head><body><button onclick="window.print()">Imprimir</button><div class="big">{html.escape(str(v.get('numero','')))}</div><b>{html.escape(str(v.get('cliente_nome','Consumidor')))}</b><br>{html.escape(str(v.get('cliente_whatsapp','')))}<div class="sep"></div>{html.escape(resumo[:180])}<div class="sep"></div><b>Entrega:</b> {data_br_segura(v.get('data_entrega','')) or '-'} | <b>{html.escape(str(v.get('status_producao','')))}</b><br>{html.escape(str(v.get('observacoes',''))[:100])}</body></html>"""


def _cancelar_venda_profissional(venda_id, motivo, operador=""):
    """Cancela a venda sem apagar histórico e estorna os lançamentos vinculados."""
    venda = consultar("SELECT * FROM vendas WHERE id=?", (int(venda_id),))
    if venda.empty:
        return False, "Venda não encontrada."
    v = venda.iloc[0]
    if str(v.get("cancelada", "Não")) == "Sim" or str(v.get("status", "")) == "Cancelado":
        return False, "Essa venda já está cancelada."

    agora = agora_iso_brasil()
    recebido = n(v.get("valor_recebido", 0))
    numero = str(v.get("numero", venda_id))

    executar(
        """UPDATE vendas
           SET status='Cancelado', status_producao='Cancelado', cancelada='Sim',
               motivo_cancelamento=?, data_cancelamento=?, data_atualizacao=?,
               valor_estornado=?
           WHERE id=?""",
        (motivo.strip(), agora, agora, recebido, int(venda_id)),
    )

    # Cancela contas pendentes e a ordem de produção, preservando o histórico.
    try:
        executar(
            "UPDATE contas_receber SET status='Cancelado', observacoes=COALESCE(observacoes,'') || ? WHERE referencia_id=? AND origem='PDV'",
            (f"\nVenda cancelada: {motivo}", int(venda_id)),
        )
    except Exception:
        pass
    try:
        executar(
            "UPDATE ordens_producao SET status='Cancelado', ativo='Não', observacoes=COALESCE(observacoes,'') || ? WHERE codigo=? OR id=?",
            (f"\nVenda cancelada: {motivo}", f"OP-{agora_brasil().year}-{int(venda_id):04d}", int(venda_id)),
        )
    except Exception:
        pass

    # Não apaga a entrada original: cria um estorno rastreável.
    if recebido > 0:
        executar(
            "INSERT INTO financeiro(data,tipo,descricao,categoria,forma_pagamento,valor,origem,referencia_id,observacoes) VALUES (?,?,?,?,?,?,?,?,?)",
            (hoje_iso(), "Saída", f"Estorno venda {numero}", "Estorno de venda", str(v.get("forma_pagamento", "")), recebido, "PDV", int(venda_id), motivo),
        )
        executar(
            "INSERT INTO caixa_movimentos(tipo,descricao,forma_pagamento,valor,venda_id,operador,observacoes) VALUES (?,?,?,?,?,?,?)",
            ("Saída", f"Estorno venda {numero}", str(v.get("forma_pagamento", "")), recebido, int(venda_id), operador, motivo),
        )
    return True, f"Venda {numero} cancelada e registrada no histórico."


def _caixa_aberto_atual():
    try:
        df = consultar("SELECT * FROM caixa_sessoes WHERE status='Aberto' ORDER BY id DESC LIMIT 1")
        return None if df.empty else df.iloc[0]
    except Exception:
        return None


def _registrar_pagamento_venda(venda_id, forma, valor, taxa=0, parcelas=1, observacoes=""):
    if n(valor) <= 0:
        return
    executar(
        "INSERT INTO venda_pagamentos(venda_id,forma_pagamento,valor,taxa,parcelas,observacoes) VALUES (?,?,?,?,?,?)",
        (int(venda_id), forma, n(valor), n(taxa), int(parcelas or 1), observacoes),
    )


def tela_vendas_pdv():
    logo = obter_config("logo_path", "")
    logo_html = ""
    if logo and Path(logo).exists():
        logo_html = f'<img src="data:image/png;base64,{imagem_base64(logo)}" class="pdv-logo">'
    caixa_atual = _caixa_aberto_atual()
    caixa_status = "ABERTO" if caixa_atual is not None else "FECHADO"
    caixa_classe = "aberto" if caixa_atual is not None else "fechado"

    st.markdown(f"""
    <style>
    .pdv-hero{{background:linear-gradient(135deg,#030303,#202020);color:#fff;padding:18px 22px;border-radius:20px;margin-bottom:14px;box-shadow:0 14px 35px rgba(0,0,0,.2);display:flex;align-items:center;justify-content:space-between;gap:16px}}
    .pdv-brand{{display:flex;align-items:center;gap:14px}} .pdv-logo{{width:64px;height:64px;object-fit:contain;border-radius:50%;background:#fff;padding:4px}}
    .pdv-hero h1{{margin:0;font-family:'Playfair Display',serif;font-size:32px}} .pdv-hero p{{margin:4px 0 0;color:#d8d8d8}}
    .caixa-pill{{padding:8px 13px;border-radius:999px;font-weight:900;font-size:12px;letter-spacing:1px}} .caixa-pill.aberto{{background:#d9ffe5;color:#08752f}} .caixa-pill.fechado{{background:#ffe1e1;color:#a90000}}
    .pdv-total{{background:#050505;color:#fff;padding:18px;border-radius:18px;text-align:center;box-shadow:0 10px 25px rgba(0,0,0,.15)}}
    .pdv-total .label{{font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:#bbb}} .pdv-total .value{{font-size:38px;font-weight:900;margin-top:4px}}
    .pdv-card{{border:1px solid #e8e8e8;border-radius:16px;padding:14px;background:#fff;box-shadow:0 7px 18px rgba(0,0,0,.04)}}
    .pdv-status{{display:inline-block;padding:5px 10px;border-radius:999px;font-size:12px;font-weight:800;background:#efefef}}
    .item-total{{font-weight:900;font-size:15px}} .muted{{color:#777;font-size:12px}}
    </style>
    <div class="pdv-hero"><div class="pdv-brand">{logo_html}<div><h1>PDV Sophi Personalizados</h1><p>Frente de caixa • pedidos personalizados • pagamentos • impressão térmica • etiquetas</p></div></div><span class="caixa-pill {caixa_classe}">CAIXA {caixa_status}</span></div>
    """, unsafe_allow_html=True)

    abas = st.tabs(["🛒 FRENTE DE CAIXA", "📋 VENDAS", "💵 CAIXA", "🖨 COMPROVANTES / ETIQUETAS"])

    with abas[0]:
        if "pdv_itens" not in st.session_state:
            st.session_state.pdv_itens = []

        # Pós-venda imediato
        ultima = st.session_state.get("ultima_venda_id")
        if ultima:
            vv = consultar("SELECT * FROM vendas WHERE id=?", (int(ultima),))
            if not vv.empty:
                v = vv.iloc[0]
                st.success(f"Venda {v['numero']} concluída • Total {real(v['total'])}")
                q1, q2, q3, q4 = st.columns(4)
                html80 = _html_comprovante_termico(int(ultima), 80)
                q1.download_button("🖨 Comprovante 80 mm", html80, file_name=f"comprovante_{v['numero']}_80mm.html", mime="text/html", use_container_width=True)
                html58 = _html_comprovante_termico(int(ultima), 58)
                q2.download_button("🧾 Comprovante 58 mm", html58, file_name=f"comprovante_{v['numero']}_58mm.html", mime="text/html", use_container_width=True)
                etq = _html_etiqueta_pedido(int(ultima), 50, 30)
                q3.download_button("🏷 Etiqueta 50×30", etq, file_name=f"etiqueta_{v['numero']}.html", mime="text/html", use_container_width=True)
                if q4.button("Nova venda", use_container_width=True):
                    st.session_state.pop("ultima_venda_id", None); st.rerun()
                st.divider()

        # Cliente e origem
        clientes = consultar("SELECT id,nome,whatsapp FROM clientes WHERE ativo='Sim' ORDER BY nome")
        c1, c2, c3, c4 = st.columns([2,1.3,1.2,1])
        cliente_opts = ["Consumidor / cadastro rápido"] + ([str(x) for x in clientes["nome"].tolist()] if not clientes.empty else [])
        cliente_sel = c1.selectbox("Cliente", cliente_opts, key="pdv_cliente_sel")
        if cliente_sel != "Consumidor / cadastro rápido" and not clientes.empty:
            cr = clientes[clientes["nome"] == cliente_sel].iloc[0]
            cliente_nome = cliente_sel
            cliente_whatsapp = c2.text_input("WhatsApp", value=str(cr.get("whatsapp", "") or ""), key="pdv_whatsapp_cad")
            cliente_id = int(cr["id"])
        else:
            cliente_nome = c1.text_input("Nome rápido", placeholder="Consumidor ou nome", key="pdv_cliente_manual")
            cliente_whatsapp = c2.text_input("WhatsApp", key="pdv_whatsapp_manual")
            cliente_id = None
        origem = c3.selectbox("Canal", ["Offstore", "WhatsApp", "Instagram", "Shopee", "iFood", "Venda direta"], key="pdv_origem")
        c4.text_input("Operador", value=st.session_state.get("usuario_logado", ""), disabled=True)

        esquerda, direita = st.columns([1.7, 1], gap="large")
        with esquerda:
            st.markdown("### Adicionar produtos e serviços")
            modo = st.radio("Modo de inclusão", ["Produto cadastrado", "Item manual"], horizontal=True, key="pdv_modo")
            produtos = consultar("SELECT id,nome,preco_escolhido,preco_sugerido,custo_unitario,ativo FROM produtos WHERE ativo='Sim' ORDER BY nome")
            if modo == "Produto cadastrado":
                busca = st.text_input("🔎 Buscar produto", placeholder="Digite o nome", key="pdv_busca")
                if busca and not produtos.empty:
                    produtos = produtos[produtos["nome"].astype(str).str.contains(busca, case=False, na=False)]
                if produtos.empty:
                    st.info("Nenhum produto cadastrado. Use Item manual.")
                    nome_prod=""; pid=None; preco_padrao=0; custo_padrao=0
                else:
                    mapa={}
                    for _,r in produtos.iterrows():
                        valor=n(r["preco_escolhido"]) or n(r["preco_sugerido"])
                        label=f"{r['nome']} • {real(valor)}"; mapa[label]=r
                    escolha=st.selectbox("Produto", list(mapa.keys()), key="pdv_produto_cad")
                    r=mapa[escolha]; nome_prod=str(r["nome"]); pid=int(r["id"])
                    preco_padrao=n(r["preco_escolhido"]) or n(r["preco_sugerido"]); custo_padrao=n(r["custo_unitario"])
            else:
                nome_prod=st.text_input("Descrição do item", placeholder="Ex.: Box presenteável personalizada", key="pdv_nome_manual")
                pid=None; preco_padrao=0; custo_padrao=0

            a,b,c=st.columns([1,1,1])
            qtd=a.number_input("Quantidade", min_value=0.01, value=1.0, step=1.0, key="pdv_qtd")
            preco=b.number_input("Valor unitário", min_value=0.0, value=float(preco_padrao), step=0.01, format="%.2f", key=f"pdv_preco_{modo}_{nome_prod}")
            desc_item=c.number_input("Desconto item", min_value=0.0, value=0.0, step=0.01, format="%.2f", key="pdv_desc_item")
            obs_item=st.text_area("Personalização / observações do item", height=70, key="pdv_obs_item")
            baixar_estoque=st.checkbox("Reservar/baixar estoque quando houver ficha de materiais", value=modo=="Produto cadastrado", key="pdv_baixar_estoque")
            badd,bclear=st.columns([2,1])
            if badd.button("➕ ADICIONAR AO CARRINHO", type="primary", use_container_width=True):
                total_item=max(qtd*preco-desc_item,0)
                if not str(nome_prod).strip(): st.error("Informe o produto.")
                elif preco<=0: st.error("Informe o valor unitário.")
                else:
                    st.session_state.pdv_itens.append({"produto_id":pid,"produto":str(nome_prod).strip(),"quantidade":qtd,"valor_unitario":preco,"custo_unitario":custo_padrao,"desconto":desc_item,"total":total_item,"observacoes":obs_item,"baixar_estoque":baixar_estoque})
                    st.rerun()
            if bclear.button("🗑 LIMPAR CARRINHO", use_container_width=True): st.session_state.pdv_itens=[]; st.rerun()

            st.markdown("### Carrinho")
            if not st.session_state.pdv_itens:
                st.info("Carrinho vazio.")
            for i,item in enumerate(st.session_state.pdv_itens):
                with st.container(border=True):
                    x1,x2,x3,x4,x5=st.columns([2.8,.7,1,1,.45])
                    x1.markdown(f"**{html.escape(str(item['produto']))}**<br><span class='muted'>{html.escape(str(item.get('observacoes','')))}</span>", unsafe_allow_html=True)
                    nq=x2.number_input("Qtd",min_value=.01,value=float(item["quantidade"]),step=1.0,key=f"cart_qtd_{i}",label_visibility="collapsed")
                    nv=x3.number_input("Unit.",min_value=0.0,value=float(item["valor_unitario"]),step=.01,format="%.2f",key=f"cart_val_{i}",label_visibility="collapsed")
                    nd=x4.number_input("Desc.",min_value=0.0,value=float(item.get("desconto",0)),step=.01,format="%.2f",key=f"cart_desc_{i}",label_visibility="collapsed")
                    item["quantidade"]=nq; item["valor_unitario"]=nv; item["desconto"]=nd; item["total"]=max(nq*nv-nd,0)
                    if x5.button("✕",key=f"cart_del_{i}"): st.session_state.pdv_itens.pop(i); st.rerun()
                    st.markdown(f"<div class='item-total'>Total: {real(item['total'])}</div>",unsafe_allow_html=True)

        with direita:
            st.markdown("### Fechamento")
            subtotal=sum(n(x["total"]) for x in st.session_state.pdv_itens)
            d1,d2=st.columns(2)
            desconto=d1.number_input("Desconto geral",min_value=0.0,value=0.0,step=.01,format="%.2f",key="pdv_desc_geral")
            acrescimo=d2.number_input("Urgência / acréscimo",min_value=0.0,value=0.0,step=.01,format="%.2f",key="pdv_acrescimo")
            frete=st.number_input("Frete / entrega",min_value=0.0,value=0.0,step=.01,format="%.2f",key="pdv_frete")
            total=max(subtotal-desconto+acrescimo+frete,0)
            st.markdown(f'<div class="pdv-total"><div class="label">TOTAL DA VENDA</div><div class="value">{real(total)}</div></div>',unsafe_allow_html=True)

            forma=st.radio("Pagamento",["Pix","Dinheiro","Débito","Crédito","Misto","Pendente"],horizontal=True,key="pdv_forma")
            pagamentos=[]; taxa_cartao=0.0; parcelas=1
            if forma=="Misto":
                m1,m2=st.columns(2)
                pix=m1.number_input("Pix",min_value=0.0,value=0.0,step=.01,format="%.2f")
                dinheiro=m2.number_input("Dinheiro",min_value=0.0,value=0.0,step=.01,format="%.2f")
                m3,m4=st.columns(2)
                cartao=m3.number_input("Cartão",min_value=0.0,value=0.0,step=.01,format="%.2f")
                taxa_pct=m4.number_input("Taxa cartão (%)",min_value=0.0,value=0.0,step=.1,format="%.2f")
                taxa_cartao=cartao*taxa_pct/100
                pagamentos=[("Pix",pix,0,1),("Dinheiro",dinheiro,0,1),("Cartão",cartao,taxa_cartao,1)]
                recebido=pix+dinheiro+cartao
            elif forma=="Crédito":
                p1,p2=st.columns(2)
                parcelas=p1.number_input("Parcelas",min_value=1,value=1,step=1)
                taxa_pct=p2.number_input("Taxa (%)",min_value=0.0,value=0.0,step=.1,format="%.2f")
                recebido=st.number_input("Valor recebido/confirmado",min_value=0.0,value=float(total),step=.01,format="%.2f")
                taxa_cartao=recebido*taxa_pct/100; pagamentos=[("Crédito",recebido,taxa_cartao,parcelas)]
            elif forma=="Pendente":
                recebido=st.number_input("Entrada/sinal",min_value=0.0,value=0.0,step=.01,format="%.2f"); pagamentos=[("Entrada",recebido,0,1)]
            else:
                recebido=st.number_input("Valor recebido",min_value=0.0,value=float(total),step=.01,format="%.2f")
                pagamentos=[(forma,recebido,0,1)]
            troco=max(recebido-total,0) if forma=="Dinheiro" else 0
            valor_aplicado=min(recebido,total)
            saldo=max(total-valor_aplicado,0)
            status="Pago" if saldo<=.009 else ("Parcial" if valor_aplicado>0 else "Pendente")
            k1,k2,k3=st.columns(3); k1.metric("Recebido",real(valor_aplicado)); k2.metric("Saldo",real(saldo)); k3.metric("Troco",real(troco))
            st.caption(f"Taxas: {real(taxa_cartao)} • Líquido previsto: {real(valor_aplicado-taxa_cartao)} • {status}")
            status_prod=st.selectbox("Status do pedido",["Aguardando","Em produção","Pronto","Entregue","Não se aplica"])
            data_entrega=st.date_input("Previsão de entrega",value=date.today())
            observacoes=st.text_area("Observações gerais",height=80)
            salvar_cliente=st.checkbox("Salvar cliente no cadastro",value=False,disabled=cliente_id is not None)

            if caixa_atual is None:
                st.warning("O caixa está fechado. Abra-o na aba CAIXA antes de finalizar vendas.")
            if st.button("✅ FINALIZAR VENDA",use_container_width=True,type="primary",disabled=caixa_atual is None):
                if not st.session_state.pdv_itens: st.error("Adicione pelo menos um item.")
                else:
                    operador=st.session_state.get("usuario_logado",""); agora_local=agora_iso_brasil()
                    nome_final=cliente_nome.strip() if str(cliente_nome).strip() else "Consumidor"
                    if salvar_cliente and nome_final!="Consumidor":
                        try: cliente_id=executar("INSERT INTO clientes(nome,whatsapp,ativo) VALUES (?,?,'Sim')",(nome_final,cliente_whatsapp))
                        except Exception: cliente_id=None
                    venda_id=executar("""INSERT INTO vendas(data,data_criacao,data_atualizacao,cliente_id,cliente_nome,cliente_whatsapp,origem,status,status_producao,forma_pagamento,subtotal,desconto,acrescimo,frete,taxa_cartao,total,valor_recebido,troco,saldo_pendente,data_entrega,observacoes,operador,cancelada) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'Não')""",
                        (agora_local,agora_local,agora_local,cliente_id,nome_final,cliente_whatsapp,origem,status,status_prod,forma,subtotal,desconto,acrescimo,frete,taxa_cartao,total,valor_aplicado,troco,saldo,data_entrega.isoformat(),observacoes,operador))
                    numero=_numero_venda(venda_id); executar("UPDATE vendas SET numero=? WHERE id=?",(numero,venda_id))
                    for x in st.session_state.pdv_itens:
                        executar("INSERT INTO venda_itens(venda_id,produto_id,produto,quantidade,valor_unitario,custo_unitario,desconto,total,observacoes) VALUES (?,?,?,?,?,?,?,?,?)",(venda_id,x["produto_id"],x["produto"],x["quantidade"],x["valor_unitario"],x["custo_unitario"],x["desconto"],x["total"],x["observacoes"]))
                    for fp,val,taxa,parc in pagamentos: _registrar_pagamento_venda(venda_id,fp,min(n(val),total),taxa,parc)
                    if valor_aplicado>0:
                        executar("INSERT INTO financeiro(data,tipo,descricao,categoria,forma_pagamento,valor,origem,referencia_id,observacoes) VALUES (?,?,?,?,?,?,?,?,?)",(hoje_iso(),"Entrada",f"Venda {numero}","Venda",forma,valor_aplicado,"PDV",venda_id,observacoes))
                        executar("INSERT INTO caixa_movimentos(tipo,descricao,forma_pagamento,valor,venda_id,operador,observacoes) VALUES ('Entrada',?,?,?,?,?,?)",(f"Venda {numero}",forma,valor_aplicado,venda_id,operador,observacoes))
                    if saldo>0:
                        executar("INSERT INTO contas_receber(descricao,cliente_nome,categoria,forma_pagamento,valor,valor_recebido,data_emissao,data_vencimento,status,origem,referencia_id,observacoes,ativo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'Sim')",(f"Saldo venda {numero}",nome_final,"Venda",forma,total,valor_aplicado,hoje_iso(),data_entrega.isoformat(),"Pendente","PDV",venda_id,observacoes))
                    executar("INSERT INTO ordens_producao(codigo,cliente_nome,whatsapp,data_entrega,status,itens_json,observacoes,ativo) VALUES (?,?,?,?,?,?,?,'Sim')",(f"OP-{agora_brasil().year}-{venda_id:04d}",nome_final,cliente_whatsapp,data_entrega.isoformat(),status_prod,json.dumps(st.session_state.pdv_itens,ensure_ascii=False),observacoes))
                    st.session_state.pdv_itens=[]; st.session_state["ultima_venda_id"]=venda_id; st.rerun()

    with abas[1]:
        vendas=consultar("SELECT * FROM vendas ORDER BY id DESC")
        if vendas.empty: st.info("Nenhuma venda registrada.")
        else:
            ativas=vendas[vendas["status"].astype(str)!="Cancelado"]
            c1,c2,c3,c4,c5=st.columns(5)
            c1.metric("Vendas",len(vendas)); c2.metric("Faturamento",real(ativas["total"].sum() if not ativas.empty else 0)); c3.metric("Recebido",real(ativas["valor_recebido"].sum() if not ativas.empty else 0)); c4.metric("A receber",real(ativas["saldo_pendente"].sum() if not ativas.empty else 0)); c5.metric("Canceladas",len(vendas[vendas["status"]=="Cancelado"]))
            f1,f2,f3=st.columns(3); status_f=f1.selectbox("Status",["Todos","Pago","Parcial","Pendente","Cancelado"]); origem_f=f2.selectbox("Origem",["Todas"]+sorted(vendas["origem"].dropna().astype(str).unique().tolist())); busca=f3.text_input("Buscar cliente ou venda")
            vf=vendas.copy()
            if status_f!="Todos": vf=vf[vf["status"]==status_f]
            if origem_f!="Todas": vf=vf[vf["origem"]==origem_f]
            if busca: vf=vf[vf.astype(str).apply(lambda r:r.str.contains(busca,case=False,na=False).any(),axis=1)]
            cols=["numero","data_criacao","cliente_nome","origem","status","status_producao","forma_pagamento","total","valor_recebido","saldo_pendente"]
            st.dataframe(formatar_valores_tabela(vf[[c for c in cols if c in vf.columns]]),use_container_width=True,hide_index=True)
            if not vf.empty:
                mapa={f"{r['numero']} • {r['cliente_nome']} • {real(r['total'])} • {r['status']}":int(r['id']) for _,r in vf.iterrows()}; vid=mapa[st.selectbox("Selecionar venda",list(mapa.keys()))]
                vv=consultar("SELECT * FROM vendas WHERE id=?",(vid,)).iloc[0]; its=consultar("SELECT * FROM venda_itens WHERE venda_id=?",(vid,)); pags=consultar("SELECT * FROM venda_pagamentos WHERE venda_id=?",(vid,))
                st.markdown(f"### {vv['numero']} <span class='pdv-status'>{vv['status']}</span>",unsafe_allow_html=True)
                i1,i2,i3=st.columns(3); i1.write(f"**Cliente:** {vv['cliente_nome']}  \n**WhatsApp:** {vv['cliente_whatsapp'] or '-'}"); i2.write(f"**Data:** {data_hora_br_segura(vv['data_criacao'])}  \n**Origem:** {vv['origem']}"); i3.write(f"**Total:** {real(vv['total'])}  \n**Recebido:** {real(vv['valor_recebido'])}")
                if not its.empty: st.dataframe(formatar_valores_tabela(its[["produto","quantidade","valor_unitario","desconto","total","observacoes"]]),use_container_width=True,hide_index=True)
                if not pags.empty: st.dataframe(formatar_valores_tabela(pags[["forma_pagamento","valor","taxa","parcelas","data"]]),use_container_width=True,hide_index=True)
                u1,u2=st.columns(2); op_pg=["Pago","Parcial","Pendente","Cancelado"]; op_pr=["Aguardando","Em produção","Pronto","Entregue","Não se aplica","Cancelado"]
                novo_status=u1.selectbox("Pagamento",op_pg,index=op_pg.index(str(vv["status"])) if str(vv["status"]) in op_pg else 0,key=f"vs_{vid}"); novo_prod=u2.selectbox("Produção",op_pr,index=op_pr.index(str(vv["status_producao"])) if str(vv["status_producao"]) in op_pr else 0,key=f"vp_{vid}")
                if st.button("Salvar alterações",key=f"salvar_v_{vid}"): executar("UPDATE vendas SET status=?,status_producao=?,data_atualizacao=? WHERE id=?",(novo_status,novo_prod,agora_iso_brasil(),vid)); st.success("Venda atualizada."); st.rerun()
                st.divider(); st.markdown("#### Cancelar venda")
                if str(vv.get("status",""))=="Cancelado" or str(vv.get("cancelada","Não"))=="Sim": st.error(f"Cancelada em {data_hora_br_segura(vv.get('data_cancelamento',''))}. Motivo: {vv.get('motivo_cancelamento','')}")
                else:
                    motivos=["Cliente desistiu","Pagamento não realizado","Erro de lançamento","Produto indisponível","Outro"]
                    motivo_padrao=st.selectbox("Motivo",motivos,key=f"motivo_padrao_{vid}"); motivo_extra=st.text_area("Detalhes",key=f"motivo_extra_{vid}"); confirmar=st.checkbox("Confirmo o cancelamento e os estornos",key=f"conf_cancel_{vid}")
                    if st.button("🚫 CANCELAR VENDA",type="secondary",key=f"cancelar_venda_{vid}"):
                        motivo=f"{motivo_padrao}: {motivo_extra}".strip(": ")
                        if not confirmar: st.error("Confirme o cancelamento.")
                        else:
                            ok,msg=_cancelar_venda_profissional(vid,motivo,st.session_state.get("usuario_logado","")); (st.success if ok else st.error)(msg)
                            if ok: st.rerun()

    with abas[2]:
        st.markdown("### Abertura e fechamento de caixa")
        caixa=_caixa_aberto_atual()
        if caixa is None:
            with st.form("abrir_caixa"):
                saldo_ini=st.number_input("Saldo inicial",min_value=0.0,value=0.0,step=.01,format="%.2f"); obs=st.text_input("Observações")
                if st.form_submit_button("🔓 ABRIR CAIXA"):
                    executar("INSERT INTO caixa_sessoes(operador,saldo_inicial,status,observacoes) VALUES (?,?,'Aberto',?)",(st.session_state.get("usuario_logado",""),saldo_ini,obs)); st.success("Caixa aberto."); st.rerun()
        else:
            mov=consultar("SELECT * FROM caixa_movimentos WHERE datetime(data)>=datetime(?) ORDER BY id DESC",(str(caixa['data_abertura']),))
            entradas=n(mov[mov["tipo"].isin(["Entrada","Suprimento"])]["valor"].sum()) if not mov.empty else 0; saidas=n(mov[mov["tipo"].isin(["Saída","Sangria"])]["valor"].sum()) if not mov.empty else 0
            calculado=n(caixa["saldo_inicial"])+entradas-saidas
            a,b,c,d=st.columns(4); a.metric("Saldo inicial",real(caixa["saldo_inicial"])); b.metric("Entradas",real(entradas)); c.metric("Saídas",real(saidas)); d.metric("Saldo calculado",real(calculado))
            with st.form("mov_caixa"):
                m1,m2,m3=st.columns(3); tipo=m1.selectbox("Tipo",["Entrada","Saída","Sangria","Suprimento"]); desc=m2.text_input("Descrição"); val=m3.number_input("Valor",min_value=0.0,step=.01,format="%.2f"); forma_m=st.selectbox("Forma",["Pix","Dinheiro","Débito","Crédito","Transferência","Outro"])
                if st.form_submit_button("Registrar movimento"): executar("INSERT INTO caixa_movimentos(tipo,descricao,forma_pagamento,valor,operador) VALUES (?,?,?,?,?)",(tipo,desc,forma_m,val,st.session_state.get("usuario_logado",""))); st.rerun()
            with st.form("fechar_caixa"):
                contado=st.number_input("Saldo contado no caixa",min_value=0.0,value=float(calculado),step=.01,format="%.2f"); obs_f=st.text_input("Observações do fechamento")
                if st.form_submit_button("🔒 FECHAR CAIXA"):
                    executar("UPDATE caixa_sessoes SET data_fechamento=?,saldo_final_informado=?,saldo_final_calculado=?,diferenca=?,status='Fechado',observacoes=COALESCE(observacoes,'')||? WHERE id=?",(agora_iso_brasil(),contado,calculado,contado-calculado,"\n"+obs_f,int(caixa["id"]))); st.success("Caixa fechado."); st.rerun()
            if not mov.empty: st.dataframe(formatar_valores_tabela(mov),use_container_width=True,hide_index=True)

    with abas[3]:
        st.markdown("### Comprovantes térmicos e etiquetas")
        vendas=consultar("SELECT id,numero,cliente_nome,total,status FROM vendas ORDER BY id DESC LIMIT 300")
        if vendas.empty: st.info("Finalize uma venda para imprimir.")
        else:
            mapa={f"{r['numero']} • {r['cliente_nome']} • {real(r['total'])} • {r['status']}":int(r['id']) for _,r in vendas.iterrows()}; vid=mapa[st.selectbox("Venda",list(mapa.keys()),key="imp_venda")]
            largura=st.selectbox("Bobina",[80,58],format_func=lambda x:f"{x} mm"); html_rec=_html_comprovante_termico(vid,largura)
            st.download_button("Baixar comprovante HTML",html_rec,file_name=f"comprovante_{vid}.html",mime="text/html",use_container_width=True); st.components.v1.html(html_rec,height=620,scrolling=True)
            st.divider(); t1,t2=st.columns(2); lw=t1.selectbox("Largura etiqueta",[40,50,100]); ah=t2.selectbox("Altura etiqueta",[30,50,150]); html_etq=_html_etiqueta_pedido(vid,lw,ah)
            st.download_button("Baixar etiqueta HTML",html_etq,file_name=f"etiqueta_{vid}.html",mime="text/html",use_container_width=True); st.components.v1.html(html_etq,height=280,scrolling=True)

def tela_kits():
    st.title("Kits")
    st.write("Monte kits completos com produtos, embalagens, brindes e materiais. O ERP calcula custo, preço, lucro e margem automaticamente.")

    abas = st.tabs(["Cadastrar / montar kit", "Kits cadastrados", "Ficha do kit"])

    with abas[0]:
        st.subheader("Dados do kit")

        c1, c2, c3 = st.columns([2.2, 1.5, 1])
        nome = c1.text_input("Nome do kit", placeholder="Ex: Kit Café da Manhã")
        categoria = c2.text_input("Categoria", placeholder="Ex: Cestas / Presentes")
        status = c3.selectbox("Status", ["Disponível", "Sob encomenda", "Esgotado"])

        descricao = st.text_area("Descrição do kit para catálogo e orçamento", placeholder="Descreva o que acompanha o kit.")

        c4, c5, c6 = st.columns(3)
        favorito = c4.selectbox("Favorito?", ["Não", "Sim"])
        destaque_catalogo = c5.selectbox("Aparecer no catálogo?", ["Sim", "Não"])
        ativo = c6.selectbox("Kit ativo?", ["Sim", "Não"])

        foto_upload = st.file_uploader("Foto do kit", type=["png", "jpg", "jpeg", "webp"], key="foto_kit_upload")

        st.divider()
        st.subheader("Montador de kit")

        if "qtd_itens_kit" not in st.session_state:
            st.session_state.qtd_itens_kit = 3

        b1, b2, b3 = st.columns([1.4, 1.4, 3])
        with b1:
            if st.button(f"+ Adicionar item {st.session_state.qtd_itens_kit + 1}"):
                if st.session_state.qtd_itens_kit < 30:
                    st.session_state.qtd_itens_kit += 1
                    st.rerun()
        with b2:
            if st.button("− Remover último item"):
                if st.session_state.qtd_itens_kit > 1:
                    st.session_state.qtd_itens_kit -= 1
                    st.rerun()
        with b3:
            st.info(f"Itens no kit: {st.session_state.qtd_itens_kit}")

        itens = []
        custo_total = 0.0

        for linha in range(1, int(st.session_state.qtd_itens_kit) + 1):
            with st.container(border=True):
                st.markdown(f"**Item {linha}**")
                item = seletor_item_kit(linha)
                if item:
                    itens.append(item)
                    custo_total += n(item["total"])

        st.divider()
        st.subheader("Precificação do kit")

        c7, c8, c9, c10 = st.columns(4)

        margem = c7.number_input(
            "Margem desejada (%)",
            min_value=0.0,
            value=n(obter_config("margem_padrao", "50"), 50),
            step=0.1,
            format="%.2f",
        )

        preco_sugerido = calcular_preco_kit(custo_total, margem)

        preco_promocional = c8.number_input(
            "Preço promocional / escolhido",
            min_value=0.0,
            value=0.0,
            step=0.10,
            format="%.2f",
        )

        preco_final = preco_promocional if preco_promocional > 0 else preco_sugerido
        lucro = preco_final - custo_total
        margem_real = lucro / preco_final * 100 if preco_final > 0 else 0

        with c9:
            st.metric("Custo total", real(custo_total))
        with c10:
            st.metric("Preço sugerido", real(preco_sugerido))

        r1, r2, r3 = st.columns(3)
        with r1:
            card("Preço final", real(preco_final))
        with r2:
            card("Lucro", real(lucro))
        with r3:
            card("Margem", f"{margem_real:.2f}%")

        if itens:
            st.subheader("Resumo dos itens do kit")
            st.dataframe(formatar_valores_tabela(pd.DataFrame(itens)), use_container_width=True, hide_index=True)

        if st.button("Salvar kit"):
            if not nome.strip():
                st.error("Digite o nome do kit.")
            elif not itens:
                st.error("Adicione pelo menos um item ao kit.")
            else:
                foto_path = salvar_upload(foto_upload, f"kit_{nome.replace(' ', '_')}") if foto_upload else ""

                kit_id = executar("""
                INSERT INTO kits(
                    nome, categoria, descricao, status, favorito, destaque_catalogo,
                    foto, itens_json, custo_total, preco_sugerido, preco_promocional,
                    lucro, margem, ativo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    nome, categoria, descricao, status, favorito, destaque_catalogo,
                    foto_path, json.dumps(itens, ensure_ascii=False),
                    custo_total, preco_sugerido, preco_promocional,
                    lucro, margem_real, ativo,
                ))

                registrar_historico_kit(kit_id, "Kit criado", f"Custo {real(custo_total)} | Preço {real(preco_final)}")
                st.success(f"Kit {codigo_kit(kit_id)} salvo com sucesso.")
                st.rerun()

    with abas[1]:
        st.subheader("Kits cadastrados")

        df = consultar("""
        SELECT id, nome, categoria, status, favorito, destaque_catalogo,
               custo_total, preco_sugerido, preco_promocional, lucro, margem, ativo, data_cadastro
        FROM kits
        ORDER BY id DESC
        """)

        if df.empty:
            st.info("Nenhum kit cadastrado ainda.")
        else:
            try:
                df = adicionar_codigo_visual(df, "KIT")
            except Exception:
                df["codigo"] = df["id"].apply(codigo_kit)

            edited = st.data_editor(
                df,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="editor_kits",
                column_config={
                    "custo_total": st.column_config.NumberColumn("Custo total", format="R$ %.2f"),
                    "preco_sugerido": st.column_config.NumberColumn("Preço sugerido", format="R$ %.2f"),
                    "preco_promocional": st.column_config.NumberColumn("Preço promocional", format="R$ %.2f"),
                    "lucro": st.column_config.NumberColumn("Lucro", format="R$ %.2f"),
                    "margem": st.column_config.NumberColumn("Margem", format="%.2f%%"),
                    "status": st.column_config.SelectboxColumn("Status", options=["Disponível", "Sob encomenda", "Esgotado"]),
                    "favorito": st.column_config.SelectboxColumn("Favorito", options=["Sim", "Não"]),
                    "destaque_catalogo": st.column_config.SelectboxColumn("Catálogo", options=["Sim", "Não"]),
                    "ativo": st.column_config.SelectboxColumn("Ativo", options=["Sim", "Não"]),
                },
            )

            c1, c2 = st.columns([2, 1])

            with c1:
                if st.button("Salvar alterações dos kits"):
                    for _, r in edited.iterrows():
                        if str(r.get("nome", "")).strip():
                            executar("""
                            UPDATE kits
                            SET nome=?, categoria=?, status=?, favorito=?, destaque_catalogo=?,
                                custo_total=?, preco_sugerido=?, preco_promocional=?,
                                lucro=?, margem=?, ativo=?
                            WHERE id=?
                            """, (
                                str(r.get("nome", "")),
                                str(r.get("categoria", "")),
                                str(r.get("status", "Disponível")),
                                str(r.get("favorito", "Não")),
                                str(r.get("destaque_catalogo", "Sim")),
                                n(r.get("custo_total", 0)),
                                n(r.get("preco_sugerido", 0)),
                                n(r.get("preco_promocional", 0)),
                                n(r.get("lucro", 0)),
                                n(r.get("margem", 0)),
                                str(r.get("ativo", "Sim")),
                                int(r["id"]),
                            ))
                            registrar_historico_kit(int(r["id"]), "Kit atualizado", "Alteração manual na tabela de kits.")
                    st.success("Kits atualizados.")
                    st.rerun()

            with c2:
                id_excluir = st.number_input("ID para excluir kit", min_value=0, step=1, key="del_kit")
                if st.button("Excluir kit"):
                    if id_excluir > 0:
                        executar("DELETE FROM historico_kits WHERE kit_id=?", (int(id_excluir),))
                        executar("DELETE FROM kits WHERE id=?", (int(id_excluir),))
                        st.success("Kit excluído.")
                        st.rerun()
                    else:
                        st.warning("Digite um ID válido.")

    with abas[2]:
        st.subheader("Ficha completa do kit")

        kits = consultar("SELECT id, nome FROM kits ORDER BY nome")

        if kits.empty:
            st.info("Nenhum kit cadastrado.")
        else:
            mapa = {f"{codigo_kit(row['id'])} - {row['nome']}": int(row["id"]) for _, row in kits.iterrows()}
            escolhido = st.selectbox("Escolha um kit", list(mapa.keys()), key="ficha_kit_select")
            kit_id = mapa[escolhido]

            kit = consultar("SELECT * FROM kits WHERE id=?", (int(kit_id),))

            if kit.empty:
                st.warning("Kit não encontrado.")
            else:
                k = kit.iloc[0]

                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    card("Código", codigo_kit(k["id"]))
                with c2:
                    card("Custo", real(k["custo_total"]))
                with c3:
                    preco = n(k["preco_promocional"]) if n(k["preco_promocional"]) > 0 else n(k["preco_sugerido"])
                    card("Preço", real(preco))
                with c4:
                    card("Lucro", real(k["lucro"]), f"{n(k['margem']):.2f}%")

                foto = str(k.get("foto", "") or "")
                if foto and Path(foto).exists():
                    st.image(foto, width=260)

                st.write(f"**Nome:** {k['nome']}")
                st.write(f"**Categoria:** {k['categoria'] or '-'}")
                st.write(f"**Status:** {k['status']}")
                st.write(f"**Descrição:** {k['descricao'] or '-'}")

                st.markdown("### Itens do kit")
                try:
                    itens = json.loads(k["itens_json"] or "[]")
                    if itens:
                        st.dataframe(formatar_valores_tabela(pd.DataFrame(itens)), use_container_width=True, hide_index=True)
                    else:
                        st.info("Nenhum item salvo.")
                except Exception:
                    st.warning("Não foi possível ler os itens do kit.")

                st.markdown("### Simulador de preço do kit")
                preco_base = n(k["preco_promocional"]) if n(k["preco_promocional"]) > 0 else n(k["preco_sugerido"])
                sim = st.number_input("E se eu vender este kit por...", min_value=0.0, value=float(preco_base), step=0.10, format="%.2f", key=f"sim_kit_{kit_id}")

                custo = n(k["custo_total"])
                lucro_sim = sim - custo
                margem_sim = lucro_sim / sim * 100 if sim > 0 else 0

                s1, s2, s3 = st.columns(3)
                with s1:
                    card("Custo", real(custo))
                with s2:
                    card("Lucro simulado", real(lucro_sim))
                with s3:
                    card("Margem simulada", f"{margem_sim:.2f}%")

                st.markdown("### Histórico do kit")
                hist = consultar("""
                SELECT data, acao, observacoes
                FROM historico_kits
                WHERE kit_id=?
                ORDER BY id DESC
                """, (int(kit_id),))

                if hist.empty:
                    st.caption("Sem histórico ainda.")
                else:
                    st.dataframe(hist, use_container_width=True, hide_index=True)


def tela_catalogo():
    st.title("Personalização do catálogo")
    st.write("Configure todas as informações que aparecem para seus clientes no link público.")

    link_publico = link_catalogo_publico()

    c1, c2 = st.columns([2, 1])
    with c1:
        st.success("Seu catálogo público está ativo.")
        st.code(link_publico)
    with c2:
        st.link_button("Abrir catálogo", link_publico)

    st.divider()

    logo_atual = obter_config("logo_path", "")
    if logo_atual and Path(logo_atual).exists():
        st.caption("Logo atual")
        st.image(logo_atual, width=130)

    logo_upload = st.file_uploader("Trocar logo do catálogo", type=["png", "jpg", "jpeg", "webp"], key="logo_catalogo_upload")
    if logo_upload is not None:
        caminho = salvar_upload(logo_upload, "logo_sophi")
        salvar_config("logo_path", caminho)
        st.success("Logo do catálogo atualizada.")
        st.rerun()

    with st.form("form_catalogo_completo"):
        st.subheader("Identidade do catálogo")
        c1, c2 = st.columns(2)
        titulo = c1.text_input("Título do catálogo", value=obter_config("catalogo_titulo", obter_config("nome_empresa", EMPRESA)))
        slogan = c2.text_input("Slogan", value=obter_config("catalogo_slogan", "Eternizando momentos com presentes personalizados"))

        texto_apresentacao = st.text_area("Texto de apresentação", value=obter_config("catalogo_descricao", "Confira nossos produtos personalizados e chame no WhatsApp para fazer seu pedido."))

        c3, c4 = st.columns(2)
        cor = c3.text_input("Cor principal", value=obter_config("catalogo_cor", "#000000"))
        texto_botao = c4.text_input("Texto do botão WhatsApp", value=obter_config("catalogo_botao", "Chamar no WhatsApp"))

        st.subheader("Informações da empresa")
        c5, c6 = st.columns(2)
        cnpj = c5.text_input("CNPJ", value=obter_config("catalogo_cnpj", ""))
        endereco = c6.text_input("Endereço", value=obter_config("catalogo_endereco", ""))

        c7, c8 = st.columns(2)
        email = c7.text_input("E-mail", value=obter_config("catalogo_email", obter_config("email", "")))
        pix = c8.text_input("Chave PIX", value=obter_config("catalogo_pix", obter_config("pix", "")))

        horario = st.text_input("Horário de atendimento", value=obter_config("catalogo_horario", "Atendimento de segunda a sábado"))

        st.subheader("Pagamento e encomendas")
        c9, c10, c11 = st.columns(3)
        aceita_pix = c9.selectbox("Aceita Pix?", ["Sim", "Não"], index=0 if obter_config("catalogo_aceita_pix", "Sim") == "Sim" else 1)
        aceita_cartao = c10.selectbox("Aceita cartão?", ["Sim", "Não"], index=0 if obter_config("catalogo_aceita_cartao", "Sim") == "Sim" else 1)
        mostrar_status = c11.selectbox("Mostrar status do produto?", ["Sim", "Não"], index=0 if obter_config("catalogo_mostrar_status", "Sim") == "Sim" else 1)

        parcelamento = st.text_input("Parcelamento / cartões", value=obter_config("catalogo_parcelamento", "Consulte condições"))
        sinal = st.text_input("Sinal / reserva", value=obter_config("catalogo_sinal", "Sinal para confirmação da encomenda"))
        prazo = st.text_input("Prazo de produção", value=obter_config("catalogo_prazo", "Prazo de produção combinado no atendimento"))

        st.subheader("Rodapé e avisos")
        aviso = st.text_input("Aviso no rodapé", value=obter_config("catalogo_aviso", "Valores sujeitos à confirmação conforme personalização, material e prazo."))
        info_extra = st.text_area("Informação extra", value=obter_config("catalogo_info_extra", "Produtos personalizados sob encomenda."))

        if st.form_submit_button("Salvar personalização do catálogo"):
            salvar_config("catalogo_titulo", titulo)
            salvar_config("catalogo_slogan", slogan)
            salvar_config("catalogo_descricao", texto_apresentacao)
            salvar_config("catalogo_cor", cor)
            salvar_config("catalogo_botao", texto_botao)
            salvar_config("catalogo_cnpj", cnpj)
            salvar_config("catalogo_endereco", endereco)
            salvar_config("catalogo_email", email)
            salvar_config("catalogo_pix", pix)
            salvar_config("catalogo_horario", horario)
            salvar_config("catalogo_aceita_pix", aceita_pix)
            salvar_config("catalogo_aceita_cartao", aceita_cartao)
            salvar_config("catalogo_mostrar_status", mostrar_status)
            salvar_config("catalogo_parcelamento", parcelamento)
            salvar_config("catalogo_sinal", sinal)
            salvar_config("catalogo_prazo", prazo)
            salvar_config("catalogo_aviso", aviso)
            salvar_config("catalogo_info_extra", info_extra)
            st.success("Catálogo atualizado com sucesso.")
            st.rerun()

    st.divider()
    st.subheader("Produtos ativos no catálogo")

    produtos = consultar_produtos_catalogo_seguro()

    if produtos.empty:
        st.info("Nenhum produto ativo no catálogo.")
    else:
        produtos = adicionar_codigo_visual(produtos, "PROD")
        st.dataframe(formatar_valores_tabela(produtos), use_container_width=True, hide_index=True)

    st.info("Para editar foto, preço, descrição e status de cada produto, vá em Produtos / Precificação.")


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



# ============================================================
# PORTAL DO CLIENTE + CATÁLOGO COM CARRINHO
# ============================================================

def garantir_pedidos_catalogo():
    executar("""
    CREATE TABLE IF NOT EXISTS pedidos_catalogo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER,
        produto_nome TEXT,
        categoria TEXT,
        preco REAL DEFAULT 0,
        cliente_nome TEXT,
        whatsapp TEXT,
        quantidade REAL DEFAULT 1,
        observacoes TEXT,
        status TEXT DEFAULT 'Novo',
        data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
        origem TEXT DEFAULT 'Catálogo',
        total REAL DEFAULT 0,
        codigo TEXT
    )
    """)
    for coluna, tipo_coluna in {
        "total": "REAL DEFAULT 0",
        "codigo": "TEXT",
        "origem": "TEXT DEFAULT 'Catálogo'",
    }.items():
        try:
            executar(f"ALTER TABLE pedidos_catalogo ADD COLUMN {coluna} {tipo_coluna}")
        except Exception:
            pass


def garantir_pedidos_catalogo_itens():
    garantir_pedidos_catalogo()
    executar("""
    CREATE TABLE IF NOT EXISTS pedidos_catalogo_itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pedido_catalogo_id INTEGER,
        produto_id INTEGER,
        produto_nome TEXT,
        categoria TEXT,
        quantidade REAL DEFAULT 1,
        valor_unitario REAL DEFAULT 0,
        total REAL DEFAULT 0
    )
    """)


def codigo_pedido_catalogo(pid):
    try:
        return codigo_visual("CAT", int(pid), ano=datetime.now().year)
    except Exception:
        return f"CAT-{int(pid):04d}"


def obter_app_url_padrao():
    try:
        url = obter_config("app_url", "")
        if str(url or "").strip():
            return str(url).strip().rstrip("/")
    except Exception:
        pass
    return "https://seuapp.streamlit.app"


def gerar_link_portal_orcamento(orc_id, base_url=None):
    base_url = (base_url or obter_app_url_padrao()).rstrip("/")
    try:
        token = gerar_token_portal("Orçamento", int(orc_id))
    except TypeError:
        token = gerar_token_portal(int(orc_id))
    return f"{base_url}/?portal=cliente&token={token}"


def mensagem_portal_cliente(cliente_nome, codigo, status, total, link):
    nome = cliente_nome or "cliente"
    texto = (
        f"Olá {nome}! 🤍\n\n"
        f"Você pode acompanhar o status do seu pedido pelo link abaixo:\n\n"
        f"Pedido: {codigo}\n"
        f"Status atual: {status}\n"
        f"Valor: {total}\n\n"
        f"Acompanhar pedido:\n{link}\n\n"
        f"Sempre que atualizarmos o status, você poderá conferir por esse mesmo link. ✨\n\n"
        f"Equipe Sophi Personalizados Oficial"
    )
    try:
        return limpar_texto_whatsapp(texto)
    except Exception:
        return texto


def mensagem_pedido_catalogo(cliente_nome, itens_texto, total, observacoes=""):
    nome = cliente_nome or "cliente"
    obs = f"\n\nObservações: {observacoes}" if str(observacoes or "").strip() else ""
    texto = (
        f"Olá {nome}! 🤍\n\n"
        f"Recebemos sua solicitação pelo catálogo da Sophi Personalizados Oficial:\n\n"
        f"{itens_texto}\n\n"
        f"Total estimado: {real(total)}"
        f"{obs}\n\n"
        f"Vou conferir disponibilidade, personalização e prazo e já te retorno por aqui. ✨"
    )
    try:
        return limpar_texto_whatsapp(texto)
    except Exception:
        return texto


def catalogo_carrinho_inicial():
    if "catalogo_carrinho" not in st.session_state:
        st.session_state["catalogo_carrinho"] = []


def adicionar_item_carrinho_catalogo(produto_id, nome, categoria, preco, quantidade):
    catalogo_carrinho_inicial()
    carrinho = st.session_state["catalogo_carrinho"]
    for item in carrinho:
        if int(item["produto_id"]) == int(produto_id):
            item["quantidade"] = n(item["quantidade"]) + n(quantidade)
            item["total"] = n(item["quantidade"]) * n(item["preco"])
            st.session_state["catalogo_carrinho"] = carrinho
            return
    carrinho.append({
        "produto_id": int(produto_id),
        "nome": str(nome),
        "categoria": str(categoria or ""),
        "preco": n(preco),
        "quantidade": n(quantidade),
        "total": n(preco) * n(quantidade),
    })
    st.session_state["catalogo_carrinho"] = carrinho


def remover_item_carrinho_catalogo(indice):
    catalogo_carrinho_inicial()
    carrinho = st.session_state["catalogo_carrinho"]
    if 0 <= int(indice) < len(carrinho):
        carrinho.pop(int(indice))
    st.session_state["catalogo_carrinho"] = carrinho


def limpar_carrinho_catalogo():
    st.session_state["catalogo_carrinho"] = []


def total_carrinho_catalogo():
    catalogo_carrinho_inicial()
    return sum(n(item.get("total", 0)) for item in st.session_state["catalogo_carrinho"])


def bloco_carrinho_catalogo_publico():
    garantir_pedidos_catalogo_itens()
    catalogo_carrinho_inicial()

    st.markdown("---")
    st.subheader("🛒 Comprar pelo catálogo")
    st.write("Escolha os produtos, envie sua solicitação e a Sophi confirma prazo, personalização e pagamento pelo WhatsApp.")

    produtos = consultar_produtos_catalogo_seguro()

    if produtos.empty:
        st.info("Nenhum produto disponível para compra no momento.")
        return

    c1, c2, c3 = st.columns([3, 1, 1])
    opcoes = {}
    for _, pr in produtos.iterrows():
        preco = n(pr.get("preco_escolhido", 0)) or n(pr.get("preco_sugerido", 0))
        status = str("Disponível" or "Disponível")
        opcoes[f"{pr['nome']} | {real(preco)} | {status}"] = int(pr["id"])

    produto_escolhido = c1.selectbox("Produto", list(opcoes.keys()), key="cat_carrinho_produto")
    produto_id = opcoes[produto_escolhido]
    pr = produtos[produtos["id"] == produto_id].iloc[0]
    preco = n(pr.get("preco_escolhido", 0)) or n(pr.get("preco_sugerido", 0))
    quantidade = c2.number_input("Qtd", min_value=1, value=1, step=1, key="cat_carrinho_qtd")
    c3.write("")
    c3.write("")
    if c3.button("Adicionar", use_container_width=True, key="cat_add_carrinho"):
        adicionar_item_carrinho_catalogo(produto_id, pr["nome"], pr.get("categoria", ""), preco, quantidade)
        st.success("Produto adicionado ao carrinho.")
        st.rerun()

    carrinho = st.session_state.get("catalogo_carrinho", [])
    if not carrinho:
        st.info("Seu carrinho está vazio.")
        return

    st.markdown("### Seu carrinho")
    for i, item in enumerate(carrinho):
        citem1, citem2, citem3 = st.columns([4, 2, 1])
        citem1.write(f"**{item['nome']}**  \nQtd: {item['quantidade']} | Unitário: {real(item['preco'])}")
        citem2.write(f"**{real(item['total'])}**")
        if citem3.button("Remover", key=f"remover_cat_{i}"):
            remover_item_carrinho_catalogo(i)
            st.rerun()

    total = total_carrinho_catalogo()
    st.metric("Total estimado", real(total))

    if st.button("Limpar carrinho", key="limpar_carrinho_catalogo"):
        limpar_carrinho_catalogo()
        st.rerun()

    st.markdown("### Finalizar solicitação")
    with st.form("checkout_catalogo_publico"):
        nome_cliente = st.text_input("Seu nome")
        whatsapp_cliente = st.text_input("Seu WhatsApp")
        observacoes = st.text_area("Observações / personalização", placeholder="Ex: tema, nome, data, cores, prazo desejado...")
        enviar = st.form_submit_button("Enviar solicitação de pedido")

        if enviar:
            if not nome_cliente.strip() or not whatsapp_cliente.strip():
                st.error("Preencha seu nome e WhatsApp.")
            elif not carrinho:
                st.error("Seu carrinho está vazio.")
            else:
                pedido_id = executar("""
                INSERT INTO pedidos_catalogo(
                    produto_id, produto_nome, categoria, preco, cliente_nome,
                    whatsapp, quantidade, observacoes, status, total, origem
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (None, "Pedido com múltiplos itens", "Carrinho", total, nome_cliente, whatsapp_cliente, len(carrinho), observacoes, "Novo", total, "Catálogo"))

                codigo = codigo_pedido_catalogo(int(pedido_id))
                try:
                    executar("UPDATE pedidos_catalogo SET codigo=? WHERE id=?", (codigo, int(pedido_id)))
                except Exception:
                    pass

                linhas = []
                for item in carrinho:
                    linhas.append(f"- {item['nome']} | Qtd: {item['quantidade']} | {real(item['total'])}")
                    executar("""
                    INSERT INTO pedidos_catalogo_itens(
                        pedido_catalogo_id, produto_id, produto_nome, categoria,
                        quantidade, valor_unitario, total
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (int(pedido_id), int(item["produto_id"]), str(item["nome"]), str(item.get("categoria", "")), n(item["quantidade"]), n(item["preco"]), n(item["total"])))

                msg = mensagem_pedido_catalogo(nome_cliente, "\n".join(linhas), total, observacoes)
                limpar_carrinho_catalogo()
                st.success(f"Solicitação enviada com sucesso! Código: {codigo}")
                st.info("A Sophi recebeu seu pedido no ERP e vai te chamar no WhatsApp.")

                link = link_whatsapp(whatsapp_cliente, msg)
                if link:
                    st.link_button("Abrir WhatsApp com minha solicitação", link, use_container_width=True)


def tela_pedidos_catalogo():
    st.title("Pedidos do Catálogo")
    st.write("Solicitações que os clientes enviaram pelo catálogo virtual.")

    garantir_pedidos_catalogo_itens()
    pedidos = consultar("SELECT * FROM pedidos_catalogo ORDER BY id DESC LIMIT 500")

    if pedidos.empty:
        st.info("Nenhuma solicitação recebida pelo catálogo ainda.")
        return

    if "total" not in pedidos.columns:
        pedidos["total"] = pedidos.apply(lambda r: n(r.get("preco", 0)) * n(r.get("quantidade", 1)), axis=1)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        card("Novos", str(len(pedidos[pedidos["status"] == "Novo"])))
    with c2:
        card("Em atendimento", str(len(pedidos[pedidos["status"] == "Em atendimento"])))
    with c3:
        card("Aprovados", str(len(pedidos[pedidos["status"] == "Aprovado"])))
    with c4:
        card("Potencial", real(pedidos["total"].apply(n).sum()))

    st.dataframe(formatar_valores_tabela(pedidos), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Atender solicitação")

    mapa = {
        f"{codigo_pedido_catalogo(r['id'])} | {r['cliente_nome']} | {r['produto_nome']} | {r['status']}": int(r["id"])
        for _, r in pedidos.iterrows()
    }
    escolhido = st.selectbox("Escolha uma solicitação", list(mapa.keys()))
    pid = mapa[escolhido]
    p = pedidos[pedidos["id"] == pid].iloc[0]

    itens = consultar("SELECT * FROM pedidos_catalogo_itens WHERE pedido_catalogo_id=? ORDER BY id", (int(pid),))
    total_pedido = n(p.get("total", 0))
    if total_pedido <= 0:
        total_pedido = itens["total"].apply(n).sum() if not itens.empty else n(p.get("preco", 0)) * n(p.get("quantidade", 1))

    c1, c2, c3 = st.columns(3)
    c1.metric("Cliente", str(p["cliente_nome"]))
    c2.metric("Itens", str(len(itens) if not itens.empty else 1))
    c3.metric("Total estimado", real(total_pedido))
    st.write(f"**WhatsApp:** {p['whatsapp']}")
    st.write(f"**Observações:** {p.get('observacoes', '')}")

    if itens.empty:
        itens_texto = f"- {p['produto_nome']} | Qtd: {p['quantidade']} | {real(n(p['preco']) * n(p['quantidade']))}"
        st.write(itens_texto)
    else:
        st.dataframe(formatar_valores_tabela(itens), use_container_width=True, hide_index=True)
        itens_texto = "\n".join([f"- {it['produto_nome']} | Qtd: {it['quantidade']} | {real(it['total'])}" for _, it in itens.iterrows()])

    
    codigo_cat = codigo_pedido_catalogo(int(pid))
    if itens.empty:
        itens_texto_wpp = f"- {p['produto_nome']} | Qtd: {p['quantidade']} | {real(n(p['preco']) * n(p['quantidade']))}"
    else:
        itens_texto_wpp = "\n".join([
            f"- {it['produto_nome']} | Qtd: {it['quantidade']} | {real(it['total'])}"
            for _, it in itens.iterrows()
        ])

    botoes_whatsapp_pedido_catalogo(p, codigo_cat, itens_texto_wpp, total_pedido)


    
    codigo_cat_wpp = codigo_pedido_catalogo(int(pid))
    if itens.empty:
        itens_texto_recebido = f"- {p['produto_nome']} | Qtd: {p['quantidade']} | {real(n(p['preco']) * n(p['quantidade']))}"
    else:
        itens_texto_recebido = "\n".join([
            f"- {it['produto_nome']} | Qtd: {it['quantidade']} | {real(it['total'])}"
            for _, it in itens.iterrows()
        ])

    botao_recebemos_pedido_catalogo(p, codigo_cat_wpp, itens_texto_recebido, total_pedido)


    
    codigo_cat_msg = codigo_pedido_catalogo(int(pid))
    botao_whatsapp_catalogo_online(
        p.get("whatsapp", ""),
        p.get("cliente_nome", "cliente"),
        codigo_cat_msg,
        real(total_pedido),
        pix_empresa(),
        "",
    )


    opcoes_status = ["Novo", "Em atendimento", "Aprovado", "Transformado em orçamento", "Cancelado"]
    status_atual = str(p["status"])
    novo_status = st.selectbox("Status", opcoes_status, index=opcoes_status.index(status_atual) if status_atual in opcoes_status else 0, key=f"status_pedido_catalogo_{pid}")

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("Salvar status", use_container_width=True):
            executar("UPDATE pedidos_catalogo SET status=? WHERE id=?", (novo_status, int(pid)))
            st.success("Status atualizado.")
            st.rerun()

    with b2:
        msg = mensagem_pedido_catalogo(p["cliente_nome"], itens_texto, total_pedido, p.get("observacoes", ""))
        link = link_whatsapp(p["whatsapp"], msg)
        if link:
            st.link_button("Responder no WhatsApp", link, use_container_width=True)

    with b3:
        if st.button("Transformar em orçamento", use_container_width=True):
            cliente = consultar("SELECT id FROM clientes WHERE whatsapp=? LIMIT 1", (str(p["whatsapp"]),))
            if cliente.empty:
                cliente_id = executar("INSERT INTO clientes(nome, whatsapp, ativo) VALUES (?, ?, ?)", (str(p["cliente_nome"]), str(p["whatsapp"]), "Sim"))
            else:
                cliente_id = int(cliente.iloc[0]["id"])

            orc_id = executar("""
            INSERT INTO orcamentos(cliente_id, cliente_nome, whatsapp, status, forma_pagamento, subtotal, desconto, frete, total, observacoes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (int(cliente_id), str(p["cliente_nome"]), str(p["whatsapp"]), "Em orçamento", "A combinar", total_pedido, 0, 0, total_pedido, f"Solicitação criada pelo catálogo. Observações: {p.get('observacoes', '')}"))

            if itens.empty:
                total_item = n(p["preco"]) * n(p["quantidade"])
                executar("INSERT INTO orcamento_itens(orcamento_id, produto, categoria, quantidade, valor_unitario, desconto, total) VALUES (?, ?, ?, ?, ?, ?, ?)", (int(orc_id), str(p["produto_nome"]), str(p.get("categoria", "")), n(p["quantidade"]), n(p["preco"]), 0, total_item))
            else:
                for _, it in itens.iterrows():
                    executar("INSERT INTO orcamento_itens(orcamento_id, produto, categoria, quantidade, valor_unitario, desconto, total) VALUES (?, ?, ?, ?, ?, ?, ?)", (int(orc_id), str(it["produto_nome"]), str(it.get("categoria", "")), n(it["quantidade"]), n(it["valor_unitario"]), 0, n(it["total"])))

            executar("UPDATE pedidos_catalogo SET status='Transformado em orçamento' WHERE id=?", (int(pid),))
            st.success(f"Orçamento criado: {codigo_visual('ORC', int(orc_id), ano=datetime.now().year)}")
            st.rerun()



def consultar_produtos_catalogo_seguro():
    """Consulta produtos do catálogo sem quebrar quando o banco antigo não tem algumas colunas."""
    try:
        colunas = consultar("PRAGMA table_info(produtos)")
        nomes = set(colunas["name"].tolist()) if not colunas.empty and "name" in colunas.columns else set()
    except Exception:
        nomes = set()

    campos = []
    for campo in ["id", "nome", "categoria", "descricao", "preco_escolhido", "preco_sugerido", "foto", "ativo"]:
        if campo in nomes:
            campos.append(campo)

    if not campos:
        return pd.DataFrame()

    where = "WHERE ativo='Sim'" if "ativo" in nomes else ""
    order = "ORDER BY categoria, nome" if "categoria" in nomes else "ORDER BY nome"

    df = consultar(f"SELECT {', '.join(campos)} FROM produtos {where} {order}")

    for campo, padrao in {
        "categoria": "",
        "descricao": "",
        "preco_escolhido": 0,
        "preco_sugerido": 0,
        "foto": "",
        "foto": "",
        "ativo": "Sim",
        "status_catalogo": "Disponível",
        "descricao_catalogo": "",
    }.items():
        if campo not in df.columns:
            df[campo] = padrao

    # Também coloca os kits cadastrados no catálogo online.
    # Eles ficam como itens com id negativo para não misturar com os produtos.
    try:
        kits_df = consultar("SELECT * FROM kits ORDER BY nome")
    except Exception:
        kits_df = pd.DataFrame()

    if not kits_df.empty:
        if "ativo" in kits_df.columns:
            kits_df = kits_df[kits_df["ativo"].astype(str).str.strip().str.lower() != "não"]

        def _coluna_kit(nome_coluna, padrao=""):
            if nome_coluna in kits_df.columns:
                return kits_df[nome_coluna]
            return pd.Series([padrao] * len(kits_df))

        preco_promocional = _coluna_kit("preco_promocional", 0).apply(n)
        preco_por = _coluna_kit("preco_por", 0).apply(n)
        preco_sugerido_kit = _coluna_kit("preco_sugerido", 0).apply(n)
        preco_final = preco_promocional.where(preco_promocional > 0, preco_por)
        preco_final = preco_final.where(preco_final > 0, preco_sugerido_kit)

        kits_catalogo = pd.DataFrame({
            "id": -_coluna_kit("id", 0).apply(lambda x: int(n(x))).abs(),
            "nome": _coluna_kit("nome", "Kit Presente"),
            "categoria": _coluna_kit("categoria", "Kits Presente"),
            "descricao": _coluna_kit("descricao", "Kit presente personalizado completo."),
            "preco_escolhido": preco_final,
            "preco_sugerido": preco_sugerido_kit,
            "foto": _coluna_kit("foto", ""),
            "ativo": "Sim",
            "status_catalogo": "Disponível",
            "descricao_catalogo": _coluna_kit("descricao", "Kit presente personalizado completo."),
            "tipo_item": "kit",
        })

        if "tipo_item" not in df.columns:
            df["tipo_item"] = "produto"

        df = pd.concat([df, kits_catalogo], ignore_index=True)

    return df




def config_valor_multiplas_chaves(chaves, padrao=""):
    for chave in chaves:
        try:
            valor = obter_config(chave, "")
            if str(valor or "").strip():
                return str(valor).strip()
        except Exception:
            pass
    return padrao


def obter_logo_catalogo_base64():
    caminhos = []
    for chave in ["logo", "logo_empresa", "logo_catalogo", "caminho_logo"]:
        try:
            valor = obter_config(chave, "")
            if str(valor or "").strip():
                caminhos.append(Path(str(valor).strip()))
        except Exception:
            pass

    caminhos += [
        UPLOAD_DIR / "logo.png",
        UPLOAD_DIR / "logo_empresa.png",
        UPLOAD_DIR / "sophi_app_icon.png",
        Path("assets") / "logo.png",
        Path("assets") / "logo_empresa.png",
    ]

    for caminho in caminhos:
        try:
            if caminho.exists() and caminho.is_file():
                import base64
                ext = caminho.suffix.lower().replace(".", "") or "png"
                data = base64.b64encode(caminho.read_bytes()).decode("utf-8")
                return f"data:image/{ext};base64,{data}"
        except Exception:
            pass
    return ""


def dados_catalogo_empresa():
    return {
        "nome": config_valor_multiplas_chaves(["nome_catalogo", "nome_empresa", "empresa"], EMPRESA),
        "subtitulo": config_valor_multiplas_chaves(
            ["subtitulo_catalogo", "frase_catalogo", "slogan_catalogo", "slogan"],
            "Personalizados feitos com carinho para eternizar momentos.",
        ),
        "descricao": config_valor_multiplas_chaves(
            ["descricao_catalogo", "texto_catalogo", "sobre_catalogo"],
            "Escolha seus personalizados, monte seu carrinho e envie sua solicitação. A confirmação de prazo, personalização e pagamento será feita pelo WhatsApp.",
        ),
        "whatsapp": config_valor_multiplas_chaves(["whatsapp", "telefone", "contato_whatsapp"], ""),
        "instagram": config_valor_multiplas_chaves(["instagram", "instagram_catalogo"], ""),
        "prazo": config_valor_multiplas_chaves(["prazo_catalogo", "prazo_producao", "prazo"], "Prazo conforme personalização e agenda."),
        "pagamento": config_valor_multiplas_chaves(["pagamento_catalogo", "formas_pagamento"], "Pix, cartão e demais condições combinadas pelo WhatsApp."),
        "logo": obter_logo_catalogo_base64(),
    }


def html_hero_catalogo_empresa():
    dados = dados_catalogo_empresa()
    logo_html = ""
    if dados["logo"]:
        logo_html = f'<img src="{dados["logo"]}" style="width:92px;height:92px;object-fit:contain;border-radius:22px;background:#fff;padding:8px;margin-bottom:12px;">'
    else:
        logo_html = '<div style="width:92px;height:92px;border-radius:22px;background:#fff;color:#111;display:flex;align-items:center;justify-content:center;font-size:42px;font-weight:900;margin-bottom:12px;">S</div>'

    info = []
    if dados["whatsapp"]:
        info.append(f"WhatsApp: {dados['whatsapp']}")
    if dados["instagram"]:
        info.append(f"Instagram: {dados['instagram']}")
    if dados["prazo"]:
        info.append(f"Prazo: {dados['prazo']}")
    if dados["pagamento"]:
        info.append(f"Pagamento: {dados['pagamento']}")

    info_html = "".join([f'<span class="shop-badge">{i}</span>' for i in info])

    return f"""
    <div class="shop-hero">
        {logo_html}
        <h1>{dados['nome']}</h1>
        <p><b>{dados['subtitulo']}</b></p>
        <p>{dados['descricao']}</p>
        {info_html}
    </div>
    """




# ============================================================
# AJUSTE FINAL — CATÁLOGO CENTRALIZADO + LOGO + PEDIDOS
# ============================================================

APP_URL_OFICIAL = "https://sophipersonalizadosoficial.streamlit.app"

def obter_config_flex(chaves, padrao=""):
    for chave in chaves:
        try:
            v = obter_config(chave, "")
            if str(v or "").strip():
                return str(v).strip()
        except Exception:
            pass
    return padrao


def procurar_logo_catalogo():
    candidatos = []

    for chave in [
        "logo_catalogo",
        "catalogo_logo",
        "logo_empresa",
        "empresa_logo",
        "logo",
        "caminho_logo",
        "logo_atual",
    ]:
        try:
            v = obter_config(chave, "")
            if str(v or "").strip():
                candidatos.append(Path(str(v).strip()))
                candidatos.append(UPLOAD_DIR / str(v).strip())
        except Exception:
            pass

    candidatos += [
        UPLOAD_DIR / "sophi_app_icon.png",
        UPLOAD_DIR / "logo_catalogo.png",
        UPLOAD_DIR / "logo_empresa.png",
        UPLOAD_DIR / "logo.png",
        Path("uploads") / "sophi_app_icon.png",
        Path("uploads") / "logo_catalogo.png",
        Path("uploads") / "logo_empresa.png",
        Path("uploads") / "logo.png",
        Path("assets") / "logo.png",
        Path("assets") / "logo_empresa.png",
    ]

    # procura imagens recentes em uploads, porque o nome salvo pode estar diferente
    try:
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            candidatos.extend(sorted(UPLOAD_DIR.glob(ext), key=lambda p: p.stat().st_mtime, reverse=True)[:10])
    except Exception:
        pass

    for caminho in candidatos:
        try:
            if caminho and caminho.exists() and caminho.is_file():
                return caminho
        except Exception:
            pass
    return None


def logo_catalogo_data_uri():
    caminho = procurar_logo_catalogo()
    if not caminho:
        return ""
    try:
        import base64
        ext = caminho.suffix.lower().replace(".", "")
        if ext == "jpg":
            ext = "jpeg"
        if ext not in ["png", "jpeg", "webp"]:
            ext = "png"
        data = base64.b64encode(caminho.read_bytes()).decode("utf-8")
        return f"data:image/{ext};base64,{data}"
    except Exception:
        return ""


def dados_catalogo_empresa_final():
    return {
        "nome": obter_config_flex(["nome_catalogo", "nome_empresa", "empresa"], EMPRESA),
        "subtitulo": obter_config_flex(
            ["subtitulo_catalogo", "frase_catalogo", "slogan_catalogo", "slogan"],
            "Personalizados feitos com carinho para eternizar momentos.",
        ),
        "descricao": obter_config_flex(
            ["descricao_catalogo", "texto_catalogo", "sobre_catalogo"],
            "Escolha seus personalizados, monte seu carrinho e envie sua solicitação.",
        ),
        "whatsapp": obter_config_flex(["whatsapp", "telefone", "contato_whatsapp"], "(13) 99211-2108"),
        "instagram": obter_config_flex(["instagram", "instagram_catalogo"], "@sophipersonalizadosoficial"),
        "prazo": obter_config_flex(["prazo_catalogo", "prazo_producao", "prazo"], "Prazo conforme personalização."),
        "pagamento": obter_config_flex(["pagamento_catalogo", "formas_pagamento"], "Pagamento combinado pelo WhatsApp."),
        "logo": logo_catalogo_data_uri(),
    }


def css_catalogo_loja():
    st.markdown("""
    <style>
    .main .block-container {
        max-width: 1180px;
        padding-top: 1.5rem;
    }
    .shop-hero {
        max-width: 980px;
        margin: 0 auto 28px auto;
        text-align: center;
        background: radial-gradient(circle at top, #303030 0%, #111111 58%, #050505 100%);
        border-radius: 30px;
        padding: 34px 28px;
        color: white;
        box-shadow: 0 22px 60px rgba(0,0,0,.22);
    }
    .shop-logo {
        width: 112px;
        height: 112px;
        object-fit: contain;
        border-radius: 50%;
        background: white;
        padding: 8px;
        margin: 0 auto 14px auto;
        display: block;
        box-shadow: 0 10px 28px rgba(255,255,255,.18);
    }
    .shop-logo-fallback {
        width: 112px;
        height: 112px;
        border-radius: 50%;
        background: white;
        color: #111;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 52px;
        font-weight: 900;
        margin: 0 auto 14px auto;
    }
    .shop-hero h1 {
        font-size: 38px;
        margin: 0;
        font-weight: 950;
        letter-spacing: -1px;
    }
    .shop-hero p {
        opacity: .92;
        font-size: 16px;
        max-width: 760px;
        margin: 10px auto 0 auto;
    }
    .shop-badges {
        margin-top: 18px;
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        justify-content: center;
    }
    .shop-badge {
        display: inline-block;
        background: rgba(255,255,255,.14);
        border: 1px solid rgba(255,255,255,.25);
        border-radius: 999px;
        padding: 8px 14px;
        font-weight: 700;
        font-size: 13px;
    }
    .shop-card {
        background: #fff;
        border: 1px solid #ececec;
        border-radius: 22px;
        padding: 18px;
        box-shadow: 0 10px 30px rgba(0,0,0,.05);
        height: 100%;
        margin-bottom: 18px;
    }
    .shop-img {
        width: 100%;
        aspect-ratio: 1 / 1;
        object-fit: cover;
        border-radius: 16px;
        display: block;
        margin-bottom: 12px;
        background: #f4f4f4;
    }
    .shop-semfoto {
        width: 100%;
        aspect-ratio: 1 / 1;
        border-radius: 16px;
        margin-bottom: 12px;
        background: #f4f4f4;
        color: #999;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        font-size: 14px;
    }
    .shop-cat {
        text-transform: uppercase;
        letter-spacing: 2px;
        font-size: 11px;
        color: #8a8a8a;
        font-weight: 800;
    }
    .shop-name {
        font-size: 22px;
        font-weight: 900;
        color: #161616;
        margin-top: 4px;
        min-height: 54px;
    }
    .shop-desc {
        color: #626262;
        font-size: 14px;
        min-height: 46px;
    }
    .shop-price {
        font-size: 28px;
        font-weight: 950;
        color: #161616;
        margin: 12px 0;
    }
    .cart-box {
        max-width: 980px;
        margin: 24px auto 0 auto;
        background: #fff;
        border: 1px solid #e7e2e6;
        border-radius: 24px;
        padding: 22px;
        box-shadow: 0 15px 42px rgba(0,0,0,.07);
    }
    .cart-title {
        font-size: 26px;
        font-weight: 900;
        margin-bottom: 8px;
        text-align: center;
    }
    .cart-line {
        background: #fafafa;
        border: 1px solid #eee;
        border-radius: 16px;
        padding: 12px;
        margin-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)
    st.markdown('\n    <style>\n    .shop-badges {max-width: 820px; margin-left:auto; margin-right:auto;}\n    .shop-badge {white-space: normal; max-width: 100%; line-height: 1.35;}\n    </style>\n', unsafe_allow_html=True)


def html_hero_catalogo_empresa():
    d = dados_catalogo_empresa_final()
    if d["logo"]:
        logo_html = f'<img class="shop-logo" src="{d["logo"]}">'
    else:
        logo_html = '<div class="shop-logo-fallback">S</div>'

    badges = []
    if d["whatsapp"]:
        badges.append(f"WhatsApp: {d['whatsapp']}")
    if d["instagram"]:
        badges.append(f"Instagram: {d['instagram']}")
    if d["prazo"]:
        badges.append(f"Prazo: {d['prazo']}")
    if d["pagamento"]:
        badges.append(f"Pagamento: {d['pagamento']}")

    badges_html = "".join([f'<span class="shop-badge">{b}</span>' for b in badges])

    return f"""
    <div class="shop-hero">
        {logo_html}
        <h1>{d['nome']}</h1>
        <p><b>{d['subtitulo']}</b></p>
        <p>{d['descricao']}</p>
        <div class="shop-badges">{badges_html}</div>
    </div>
    """


def tela_catalogo_publico_cliente():
    garantir_pedidos_catalogo_itens()
    css_catalogo_loja()
    catalogo_carrinho_inicial()

    produtos = consultar_produtos_catalogo_seguro()

    kits = pd.DataFrame()

    st.markdown(html_hero_catalogo_empresa(), unsafe_allow_html=True)

    if produtos.empty and kits.empty:
        st.info("Nenhum produto ou kit disponível no catálogo no momento.")
        return

    st.markdown("<div class='produtos-wrap'><h2 style='text-align:center;margin:20px 0 22px 0;'>Produtos disponíveis</h2></div>", unsafe_allow_html=True)

    cols = st.columns(3)
    for idx, (_, pr) in enumerate(produtos.iterrows()):
        with cols[idx % 3]:
            preco = n(pr.get("preco_escolhido", 0)) or n(pr.get("preco_sugerido", 0))
            descricao = str(pr.get("descricao", "") or "Produto personalizado sob encomenda.")
            categoria = str(pr.get("categoria", "") or "Personalizados")
            nome = str(pr.get("nome", "Produto"))
            tipo_item = str(pr.get("tipo_item", "produto") or "produto")

            foto_uri = foto_produto_data_uri(pr.get("foto", ""))
            if foto_uri:
                st.markdown(
                    f'<img src="{foto_uri}" style="width:100%;max-width:230px;aspect-ratio:1/1;object-fit:cover;border-radius:18px;margin:0 auto 10px auto;display:block;">',
                    unsafe_allow_html=True,
                )

            descricao_html = html.escape(descricao).replace("\n", "<br>")
            if tipo_item != "kit":
                descricao_html = html.escape(descricao[:140])

            st.markdown(f"""
            <div class="shop-card">
                <div class="shop-cat">{html.escape(categoria)}</div>
                <div class="shop-name">{html.escape(nome)}</div>
                <div class="shop-desc">{descricao_html}</div>
                <div class="shop-price">{real(preco)}</div>
            </div>
            """, unsafe_allow_html=True)

            qtd = st.number_input(
                "Quantidade",
                min_value=1,
                value=1,
                step=1,
                key=f"qtd_shop_{int(pr['id'])}",
            )

            if st.button("Adicionar ao carrinho", key=f"add_shop_{int(pr['id'])}", use_container_width=True):
                adicionar_item_carrinho_catalogo(pr["id"], nome, categoria, preco, qtd)
                st.success("Produto adicionado ao carrinho.")
                st.rerun()

    carrinho = st.session_state.get("catalogo_carrinho", [])

    st.markdown('<div class="cart-box">', unsafe_allow_html=True)
    st.markdown('<div class="cart-title">🛒 Seu carrinho</div>', unsafe_allow_html=True)

    if not carrinho:
        st.info("Seu carrinho está vazio. Adicione um produto ou kit acima.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    for i, item in enumerate(carrinho):
        c1, c2, c3 = st.columns([4, 2, 1])
        with c1:
            st.markdown(
                f'<div class="cart-line"><b>{item["nome"]}</b><br>Qtd: {item["quantidade"]} | Unitário: {real(item["preco"])}</div>',
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(f"**{real(item['total'])}**")
        with c3:
            if st.button("Remover", key=f"remover_cat_{i}"):
                remover_item_carrinho_catalogo(i)
                st.rerun()

    total = total_carrinho_catalogo()
    st.metric("Total estimado", real(total))

    if st.button("Limpar carrinho", key="limpar_carrinho_catalogo"):
        limpar_carrinho_catalogo()
        st.rerun()

    st.markdown("### Finalizar solicitação")
    with st.form("checkout_catalogo_publico"):
        nome_cliente = st.text_input("Seu nome")
        whatsapp_cliente = st.text_input("Seu WhatsApp")
        observacoes = st.text_area(
            "Observações / personalização",
            placeholder="Ex: tema, nome, data, cores, prazo desejado...",
        )
        enviar = st.form_submit_button("Enviar pedido para a Sophi")

        if enviar:
            if not nome_cliente.strip() or not whatsapp_cliente.strip():
                st.error("Preencha seu nome e WhatsApp.")
            elif not carrinho:
                st.error("Seu carrinho está vazio.")
            else:
                pedido_id = executar("""
                INSERT INTO pedidos_catalogo(
                    produto_id, produto_nome, categoria, preco, cliente_nome,
                    whatsapp, quantidade, observacoes, status, total, origem
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    None,
                    "Pedido com múltiplos itens",
                    "Carrinho",
                    total,
                    nome_cliente,
                    whatsapp_cliente,
                    len(carrinho),
                    observacoes,
                    "Novo",
                    total,
                    "Catálogo",
                ))

                codigo = codigo_pedido_catalogo(int(pedido_id))
                try:
                    executar("UPDATE pedidos_catalogo SET codigo=? WHERE id=?", (codigo, int(pedido_id)))
                except Exception:
                    pass

                for item in carrinho:
                    executar("""
                    INSERT INTO pedidos_catalogo_itens(
                        pedido_catalogo_id, produto_id, produto_nome, categoria,
                        quantidade, valor_unitario, total
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        int(pedido_id),
                        int(item["produto_id"]),
                        str(item["nome"]),
                        str(item.get("categoria", "")),
                        n(item["quantidade"]),
                        n(item["preco"]),
                        n(item["total"]),
                    ))

                limpar_carrinho_catalogo()
                st.success(f"Pedido enviado com sucesso! Código: {codigo}")
                st.info("Seu pedido chegou no ERP da Sophi. Vamos chamar você no WhatsApp para confirmar prazo e pagamento.")
    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# MÓDULO 2 — PRODUÇÃO / ORDEM DE PRODUÇÃO
# ============================================================

def codigo_op(op_id):
    try:
        return codigo_visual("OP", int(op_id), ano=datetime.now().year)
    except Exception:
        return f"OP-{datetime.now().year}-{int(op_id):04d}"

def codigo_op_seguro(op_id):
    try:
        return f"OP-{datetime.now().year}-{int(op_id):04d}"
    except Exception:
        return "OP"


def checklist_padrao_producao():
    return {
        "Imprimir": False,
        "Laminar": False,
        "Cortar": False,
        "Montar kit": False,
        "Embalar": False,
        "Etiqueta": False,
        "Entregar": False,
    }


def registrar_historico_producao(op_id, acao, observacoes=""):
    try:
        executar("""
        INSERT INTO historico_producao(op_id, acao, observacoes)
        VALUES (?, ?, ?)
        """, (int(op_id), str(acao), str(observacoes)))
    except Exception:
        pass


def obter_itens_orcamento_para_op(orcamento_id):
    try:
        itens = consultar("""
        SELECT produto, categoria, quantidade, valor_unitario, desconto, total
        FROM orcamento_itens
        WHERE orcamento_id=?
        """, (int(orcamento_id),))
        if itens.empty:
            return []
        return itens.to_dict("records")
    except Exception:
        return []


def obter_materiais_para_op(itens):
    materiais = []

    try:
        for item in itens:
            produto_nome = str(item.get("produto", ""))

            prod = consultar("""
            SELECT receita_json, tintas_json, equipamentos_json
            FROM produtos
            WHERE nome=?
            LIMIT 1
            """, (produto_nome,))

            if not prod.empty:
                p = prod.iloc[0]
                for campo, tipo in [
                    ("receita_json", "Item utilizado"),
                    ("tintas_json", "Tinta"),
                    ("equipamentos_json", "Equipamento"),
                ]:
                    try:
                        dados = json.loads(p[campo] or "[]")
                        for d in dados:
                            materiais.append({
                                "origem": produto_nome,
                                "tipo": tipo,
                                "nome": d.get("nome", ""),
                                "categoria": d.get("categoria", ""),
                                "qtd": d.get("qtd", ""),
                            })
                    except Exception:
                        pass

            kit = consultar("""
            SELECT itens_json
            FROM kits
            WHERE nome=?
            LIMIT 1
            """, (produto_nome,))

            if not kit.empty:
                try:
                    dados_kit = json.loads(kit.iloc[0]["itens_json"] or "[]")
                    for d in dados_kit:
                        materiais.append({
                            "origem": produto_nome,
                            "tipo": "Kit",
                            "nome": d.get("nome", ""),
                            "categoria": d.get("categoria", ""),
                            "qtd": d.get("qtd", ""),
                        })
                except Exception:
                    pass

    except Exception:
        pass

    return materiais


def criar_op_de_orcamento(orcamento_id, prioridade="Normal", data_entrega="", observacoes_extra=""):
    try:
        existe = consultar("SELECT id FROM ordens_producao WHERE orcamento_id=? AND ativo='Sim'", (int(orcamento_id),))
        if not existe.empty:
            return int(existe.iloc[0]["id"])

        orc = consultar("SELECT * FROM orcamentos WHERE id=?", (int(orcamento_id),))
        if orc.empty:
            return None

        o = orc.iloc[0]
        itens = obter_itens_orcamento_para_op(int(orcamento_id))
        materiais = obter_materiais_para_op(itens)

        if not data_entrega:
            try:
                validade = int(n(obter_config("validade_orcamento", "7"), 7))
                data_entrega = (datetime.now().date() + timedelta(days=validade)).isoformat()
            except Exception:
                data_entrega = (datetime.now().date() + timedelta(days=7)).isoformat()

        op_id_previsto = consultar("SELECT COALESCE(MAX(id),0)+1 AS proximo FROM ordens_producao").iloc[0]["proximo"]
        codigo = codigo_op(int(op_id_previsto))

        op_id = executar("""
        INSERT INTO ordens_producao(
            codigo, orcamento_id, cliente_nome, whatsapp, data_entrega,
            prioridade, status, itens_json, materiais_json, checklist_json, observacoes, ativo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            codigo,
            int(orcamento_id),
            str(o.get("cliente_nome", "")),
            str(o.get("whatsapp", "")),
            str(data_entrega),
            str(prioridade),
            "Aguardando",
            json.dumps(itens, ensure_ascii=False),
            json.dumps(materiais, ensure_ascii=False),
            json.dumps(checklist_padrao_producao(), ensure_ascii=False),
            str(o.get("observacoes", "") or "") + ("\n" + observacoes_extra if observacoes_extra else ""),
            "Sim",
        ))

        registrar_historico_producao(op_id, "OP criada", f"Criada a partir do orçamento #{orcamento_id}")
        return op_id

    except Exception as e:
        return None


def status_por_checklist(checklist):
    try:
        if not checklist:
            return "Aguardando"
        valores = list(checklist.values())
        if all(valores):
            return "Entregue" if checklist.get("Entregar") else "Finalizado"
        if any(valores):
            return "Produzindo"
        return "Aguardando"
    except Exception:
        return "Aguardando"


def gerar_html_ficha_producao(op_id):
    op = consultar("SELECT * FROM ordens_producao WHERE id=?", (int(op_id),))
    if op.empty:
        return ""

    o = op.iloc[0]
    empresa = obter_config("nome_empresa", EMPRESA)

    try:
        itens = json.loads(o["itens_json"] or "[]")
    except Exception:
        itens = []

    try:
        materiais = json.loads(o["materiais_json"] or "[]")
    except Exception:
        materiais = []

    try:
        checklist = json.loads(o["checklist_json"] or "{}")
    except Exception:
        checklist = checklist_padrao_producao()

    linhas_itens = ""
    for item in itens:
        linhas_itens += f"""
        <tr>
            <td>{item.get('produto','')}</td>
            <td>{item.get('categoria','')}</td>
            <td>{item.get('quantidade','')}</td>
        </tr>
        """

    linhas_materiais = ""
    for m in materiais:
        linhas_materiais += f"""
        <tr>
            <td>{m.get('origem','')}</td>
            <td>{m.get('tipo','')}</td>
            <td>{m.get('nome','')}</td>
            <td>{m.get('qtd','')}</td>
        </tr>
        """

    checklist_html = ""
    for nome, feito in checklist.items():
        marca = "☑" if feito else "☐"
        checklist_html += f"<div class='check'>{marca} {nome}</div>"

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Ficha de Produção {codigo_op_seguro(o['id'])}</title>
<style>
body {{
    font-family: Arial, sans-serif;
    background: #fff;
    color: #111;
    padding: 20px;
}}
.page {{
    max-width: 900px;
    margin: 0 auto;
}}
.header {{
    border-bottom: 3px solid #111;
    padding-bottom: 12px;
    margin-bottom: 18px;
    display: flex;
    justify-content: space-between;
}}
h1 {{
    margin: 0;
    font-size: 28px;
}}
.badge {{
    border: 2px solid #111;
    border-radius: 10px;
    padding: 10px 14px;
    font-weight: 800;
}}
.grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
}}
.box {{
    border: 1px solid #ddd;
    border-radius: 12px;
    padding: 12px;
    margin-bottom: 12px;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 8px;
}}
th {{
    background: #000;
    color: #fff;
    text-align: left;
    padding: 8px;
}}
td {{
    border-bottom: 1px solid #eee;
    padding: 7px;
}}
.check {{
    font-size: 17px;
    margin: 8px 0;
}}
button {{
    position: fixed;
    top: 16px;
    right: 16px;
    background: #111;
    color: #fff;
    border: 0;
    border-radius: 10px;
    padding: 12px 18px;
    font-weight: 800;
}}
@media print {{
    button {{ display:none; }}
}}
</style>
</head>
<body>
<button onclick="window.print()">Imprimir</button>
<div class="page">
    <div class="header">
        <div>
            <h1>{empresa}</h1>
            <p>Ficha de produção</p>
        </div>
        <div class="badge">{codigo_op_seguro(o['id'])}</div>
    </div>

    <div class="grid">
        <div class="box">
            <b>Cliente:</b> {o['cliente_nome']}<br>
            <b>WhatsApp:</b> {o['whatsapp'] or '-'}<br>
            <b>Orçamento:</b> #{o['orcamento_id'] or '-'}
        </div>
        <div class="box">
            <b>Status:</b> {o['status']}<br>
            <b>Prioridade:</b> {o['prioridade']}<br>
            <b>Entrega:</b> {o['data_entrega'] or '-'}
        </div>
    </div>

    <div class="box">
        <h2>Checklist</h2>
        {checklist_html}
    </div>

    <div class="box">
        <h2>Itens do pedido</h2>
        <table>
            <thead><tr><th>Produto/Kit</th><th>Categoria</th><th>Qtd</th></tr></thead>
            <tbody>{linhas_itens}</tbody>
        </table>
    </div>

    <div class="box">
        <h2>Materiais necessários</h2>
        <table>
            <thead><tr><th>Origem</th><th>Tipo</th><th>Material</th><th>Qtd</th></tr></thead>
            <tbody>{linhas_materiais}</tbody>
        </table>
    </div>

    <div class="box">
        <h2>Observações</h2>
        <p>{o['observacoes'] or '-'}</p>
    </div>
</div>
</body>
</html>"""
    return html




# ============================================================
# MÓDULO 3 — ESTOQUE INTELIGENTE
# ============================================================

def garantir_tabelas_estoque_inteligente():
    try:
        executar("""
        CREATE TABLE IF NOT EXISTS estoque_reservas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER,
            item_nome TEXT,
            categoria TEXT,
            quantidade REAL DEFAULT 0,
            status TEXT DEFAULT 'Reservado',
            data TEXT DEFAULT CURRENT_TIMESTAMP,
            observacoes TEXT
        )
        """)
    except Exception:
        pass

    try:
        executar("""
        CREATE TABLE IF NOT EXISTS estoque_consumo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER,
            data TEXT DEFAULT CURRENT_TIMESTAMP,
            item_nome TEXT,
            categoria TEXT,
            quantidade REAL DEFAULT 0,
            tipo TEXT DEFAULT 'Baixa automática',
            observacoes TEXT
        )
        """)
    except Exception:
        pass

    try:
        executar("""
        CREATE TABLE IF NOT EXISTS estoque_minimo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_nome TEXT UNIQUE,
            categoria TEXT,
            estoque_minimo REAL DEFAULT 5,
            observacoes TEXT
        )
        """)
    except Exception:
        pass


def saldo_estoque_item(item_nome):
    try:
        df = consultar("""
        SELECT tipo_movimento, quantidade
        FROM estoque
        WHERE item=?
        """, (str(item_nome),))

        if df.empty:
            return 0.0

        entrada = float(df[df["tipo_movimento"] == "Entrada"]["quantidade"].sum())
        saida = float(df[df["tipo_movimento"] == "Saída"]["quantidade"].sum())
        saida += float(df[df["tipo_movimento"] == "SaÃ­da"]["quantidade"].sum())
        return entrada - saida
    except Exception:
        return 0.0


def reservado_estoque_item(item_nome):
    try:
        df = consultar("""
        SELECT COALESCE(SUM(quantidade),0) AS total
        FROM estoque_reservas
        WHERE item_nome=? AND status='Reservado'
        """, (str(item_nome),))
        return float(df.iloc[0]["total"]) if not df.empty else 0.0
    except Exception:
        return 0.0


def disponivel_estoque_item(item_nome):
    return saldo_estoque_item(item_nome) - reservado_estoque_item(item_nome)


def materiais_op(op_id):
    op = consultar("SELECT materiais_json FROM ordens_producao WHERE id=?", (int(op_id),))
    if op.empty:
        return []

    try:
        dados = json.loads(op.iloc[0]["materiais_json"] or "[]")
    except Exception:
        dados = []

    materiais = []
    for m in dados:
        nome = str(m.get("nome", "")).strip()
        if not nome:
            continue
        qtd = n(m.get("qtd", 1), 1)
        if qtd <= 0:
            qtd = 1
        materiais.append({
            "nome": nome,
            "categoria": str(m.get("categoria", "") or m.get("tipo", "")),
            "qtd": qtd,
            "origem": str(m.get("origem", "")),
        })
    return materiais


def reservar_estoque_op(op_id):
    garantir_tabelas_estoque_inteligente()

    ja = consultar("""
    SELECT COUNT(*) AS total
    FROM estoque_reservas
    WHERE op_id=? AND status='Reservado'
    """, (int(op_id),))

    if not ja.empty and int(ja.iloc[0]["total"]) > 0:
        return False, "Esta OP já possui materiais reservados."

    mats = materiais_op(op_id)
    if not mats:
        return False, "Nenhum material encontrado automaticamente nesta OP."

    faltas = []
    for m in mats:
        disponivel = disponivel_estoque_item(m["nome"])
        if disponivel < n(m["qtd"]):
            faltas.append({
                "item": m["nome"],
                "necessario": n(m["qtd"]),
                "disponivel": disponivel,
                "falta": n(m["qtd"]) - disponivel,
            })

    if faltas:
        return False, faltas

    for m in mats:
        executar("""
        INSERT INTO estoque_reservas(op_id, item_nome, categoria, quantidade, status, observacoes)
        VALUES (?, ?, ?, ?, 'Reservado', ?)
        """, (
            int(op_id),
            m["nome"],
            m["categoria"],
            n(m["qtd"]),
            f"Reserva automática OP {codigo_op_seguro(op_id)}",
        ))

    try:
        registrar_historico_producao(int(op_id), "Estoque reservado", "Materiais reservados automaticamente.")
    except Exception:
        pass

    return True, "Materiais reservados com sucesso."


def baixar_estoque_op(op_id):
    garantir_tabelas_estoque_inteligente()

    reservas = consultar("""
    SELECT *
    FROM estoque_reservas
    WHERE op_id=? AND status='Reservado'
    """, (int(op_id),))

    if reservas.empty:
        return False, "Não há materiais reservados para baixar nesta OP."

    for _, r in reservas.iterrows():
        executar("""
        INSERT INTO estoque(data, item, categoria, tipo_movimento, quantidade, valor_unitario, fornecedor, observacoes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            hoje_iso(),
            str(r["item_nome"]),
            str(r["categoria"]),
            "Saída",
            n(r["quantidade"]),
            0,
            "",
            f"Baixa automática {codigo_op_seguro(op_id)}",
        ))

        executar("""
        INSERT INTO estoque_consumo(op_id, item_nome, categoria, quantidade, tipo, observacoes)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            int(op_id),
            str(r["item_nome"]),
            str(r["categoria"]),
            n(r["quantidade"]),
            "Baixa automática",
            f"Consumo da {codigo_op_seguro(op_id)}",
        ))

    executar("""
    UPDATE estoque_reservas
    SET status='Baixado'
    WHERE op_id=? AND status='Reservado'
    """, (int(op_id),))

    try:
        registrar_historico_producao(int(op_id), "Estoque baixado", "Materiais baixados automaticamente.")
    except Exception:
        pass

    return True, "Baixa automática realizada com sucesso."


def resumo_estoque_inteligente():
    try:
        mov = consultar("""
        SELECT item, categoria,
               SUM(CASE WHEN tipo_movimento='Entrada' THEN quantidade ELSE 0 END) AS entradas,
               SUM(CASE WHEN tipo_movimento='Saída' OR tipo_movimento='SaÃ­da' THEN quantidade ELSE 0 END) AS saidas
        FROM estoque
        GROUP BY item, categoria
        ORDER BY item
        """)

        if mov.empty:
            return pd.DataFrame()

        reservas = consultar("""
        SELECT item_nome, COALESCE(SUM(quantidade),0) AS reservado
        FROM estoque_reservas
        WHERE status='Reservado'
        GROUP BY item_nome
        """)

        minimos = consultar("""
        SELECT item_nome, estoque_minimo
        FROM estoque_minimo
        """)

        mov["saldo"] = mov["entradas"].fillna(0) - mov["saidas"].fillna(0)

        mapa_reserva = {}
        if not reservas.empty:
            mapa_reserva = dict(zip(reservas["item_nome"], reservas["reservado"]))

        mapa_min = {}
        if not minimos.empty:
            mapa_min = dict(zip(minimos["item_nome"], minimos["estoque_minimo"]))

        mov["reservado"] = mov["item"].map(mapa_reserva).fillna(0)
        mov["disponivel"] = mov["saldo"] - mov["reservado"]
        mov["estoque_minimo"] = mov["item"].map(mapa_min).fillna(5)

        def status(row):
            if n(row["disponivel"]) <= 0:
                return "🔴 Crítico"
            if n(row["disponivel"]) <= n(row["estoque_minimo"]):
                return "🟠 Atenção"
            return "🟢 Normal"

        mov["status"] = mov.apply(status, axis=1)
        return mov

    except Exception:
        return pd.DataFrame()


def tela_estoque_inteligente():
    garantir_tabelas_estoque_inteligente()

    st.title("Estoque Inteligente")
    st.write("Controle reservas, baixas automáticas, materiais faltando e lista de compras.")

    abas = st.tabs(["Resumo", "Reservas por OP", "Baixa automática", "Estoque mínimo", "Consumo"])

    with abas[0]:
        st.subheader("Resumo inteligente do estoque")

        resumo = resumo_estoque_inteligente()

        if resumo.empty:
            st.info("Ainda não há movimentações de estoque.")
        else:
            criticos = len(resumo[resumo["status"].astype(str).str.contains("Crítico", na=False)])
            atencao = len(resumo[resumo["status"].astype(str).str.contains("Atenção", na=False)])
            normal = len(resumo[resumo["status"].astype(str).str.contains("Normal", na=False)])

            c1, c2, c3 = st.columns(3)
            with c1:
                card("Crítico", str(criticos))
            with c2:
                card("Atenção", str(atencao))
            with c3:
                card("Normal", str(normal))

            st.dataframe(
                formatar_valores_tabela(resumo),
                use_container_width=True,
                hide_index=True,
            )

            compras = resumo[resumo["disponivel"] <= resumo["estoque_minimo"]].copy()
            st.subheader("Lista de compras automática")
            if compras.empty:
                st.success("Nenhum item abaixo do mínimo.")
            else:
                compras["comprar_sugerido"] = (compras["estoque_minimo"] - compras["disponivel"]).clip(lower=0)
                st.dataframe(
                    compras[["item", "categoria", "disponivel", "estoque_minimo", "comprar_sugerido", "status"]],
                    use_container_width=True,
                    hide_index=True,
                )

    with abas[1]:
        st.subheader("Reservar materiais de uma OP")

        ops = consultar("""
        SELECT id, cliente_nome, status, prioridade, data_entrega
        FROM ordens_producao
        WHERE ativo='Sim'
        ORDER BY id DESC
        """)

        if ops.empty:
            st.info("Nenhuma OP cadastrada.")
        else:
            ops["codigo"] = ops["id"].apply(codigo_op_seguro)
            mapa = {
                f"{r['codigo']} | {r['cliente_nome']} | {r['status']}": int(r["id"])
                for _, r in ops.iterrows()
            }

            escolhido = st.selectbox("Escolha a OP", list(mapa.keys()), key="reserva_op_select")
            op_id = mapa[escolhido]

            mats = materiais_op(op_id)
            if mats:
                st.markdown("### Materiais necessários")
                df_mats = pd.DataFrame(mats)
                df_mats["saldo"] = df_mats["nome"].apply(saldo_estoque_item)
                df_mats["reservado"] = df_mats["nome"].apply(reservado_estoque_item)
                df_mats["disponivel"] = df_mats["nome"].apply(disponivel_estoque_item)
                df_mats["falta"] = df_mats.apply(lambda r: max(n(r["qtd"]) - n(r["disponivel"]), 0), axis=1)
                st.dataframe(formatar_valores_tabela(df_mats), use_container_width=True, hide_index=True)

                if st.button("Reservar materiais desta OP"):
                    ok, msg = reservar_estoque_op(op_id)

                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        if isinstance(msg, list):
                            st.error("Não é possível reservar. Existem materiais faltando:")
                            st.dataframe(pd.DataFrame(msg), use_container_width=True, hide_index=True)
                        else:
                            st.warning(msg)
            else:
                st.warning("Esta OP não possui materiais identificados automaticamente.")

            st.markdown("### Reservas ativas")
            reservas = consultar("""
            SELECT id, op_id, item_nome, categoria, quantidade, status, data, observacoes
            FROM estoque_reservas
            WHERE status='Reservado'
            ORDER BY id DESC
            """)
            if reservas.empty:
                st.info("Nenhuma reserva ativa.")
            else:
                reservas["codigo_op"] = reservas["op_id"].apply(codigo_op_seguro)
                st.dataframe(formatar_valores_tabela(reservas), use_container_width=True, hide_index=True)

    with abas[2]:
        st.subheader("Baixa automática por OP")

        ops = consultar("""
        SELECT id, cliente_nome, status, prioridade, data_entrega
        FROM ordens_producao
        WHERE ativo='Sim'
        ORDER BY id DESC
        """)

        if ops.empty:
            st.info("Nenhuma OP cadastrada.")
        else:
            ops["codigo"] = ops["id"].apply(codigo_op_seguro)
            mapa = {
                f"{r['codigo']} | {r['cliente_nome']} | {r['status']}": int(r["id"])
                for _, r in ops.iterrows()
            }

            escolhido = st.selectbox("Escolha a OP para baixar estoque", list(mapa.keys()), key="baixa_op_select")
            op_id = mapa[escolhido]

            reservas = consultar("""
            SELECT item_nome, categoria, quantidade, status
            FROM estoque_reservas
            WHERE op_id=?
            ORDER BY id
            """, (int(op_id),))

            if reservas.empty:
                st.warning("Esta OP ainda não tem reserva. Reserve primeiro na aba Reservas por OP.")
            else:
                st.dataframe(formatar_valores_tabela(reservas), use_container_width=True, hide_index=True)

                if st.button("Dar baixa automática desta OP"):
                    ok, msg = baixar_estoque_op(op_id)
                    if ok:
                        executar("UPDATE ordens_producao SET status='Entregue' WHERE id=?", (int(op_id),))
                        st.success(msg)
                        st.rerun()
                    else:
                        st.warning(msg)

    with abas[3]:
        st.subheader("Configurar estoque mínimo")

        resumo = resumo_estoque_inteligente()
        itens = []
        if not resumo.empty:
            itens = resumo["item"].astype(str).tolist()

        with st.form("form_estoque_minimo"):
            item = st.selectbox("Item", itens if itens else [""])
            categoria = ""
            if item and not resumo.empty:
                linha = resumo[resumo["item"] == item]
                if not linha.empty:
                    categoria = str(linha.iloc[0]["categoria"])

            minimo = st.number_input("Estoque mínimo", min_value=0.0, value=5.0, step=1.0)
            obs = st.text_input("Observação")

            if st.form_submit_button("Salvar estoque mínimo"):
                if item:
                    executar("""
                    INSERT OR REPLACE INTO estoque_minimo(item_nome, categoria, estoque_minimo, observacoes)
                    VALUES (?, ?, ?, ?)
                    """, (item, categoria, minimo, obs))
                    st.success("Estoque mínimo salvo.")
                    st.rerun()

        df_min = consultar("SELECT * FROM estoque_minimo ORDER BY item_nome")
        if df_min.empty:
            st.info("Nenhum mínimo configurado.")
        else:
            st.dataframe(df_min, use_container_width=True, hide_index=True)

    with abas[4]:
        st.subheader("Histórico de consumo de materiais")

        consumo = consultar("""
        SELECT data, op_id, item_nome, categoria, quantidade, tipo, observacoes
        FROM estoque_consumo
        ORDER BY id DESC
        LIMIT 500
        """)

        if consumo.empty:
            st.info("Ainda não há consumo registrado.")
        else:
            consumo["codigo_op"] = consumo["op_id"].apply(codigo_op_seguro)
            st.dataframe(formatar_valores_tabela(consumo), use_container_width=True, hide_index=True)

        st.subheader("Materiais mais consumidos")
        ranking = consultar("""
        SELECT item_nome, categoria, COALESCE(SUM(quantidade),0) AS quantidade_total
        FROM estoque_consumo
        GROUP BY item_nome, categoria
        ORDER BY quantidade_total DESC
        LIMIT 30
        """)

        if ranking.empty:
            st.info("Sem dados para ranking.")
        else:
            st.dataframe(formatar_valores_tabela(ranking), use_container_width=True, hide_index=True)




# ============================================================
# MÓDULO 4A — FINANCEIRO PROFISSIONAL
# ============================================================

def garantir_financeiro_profissional():
    try:
        executar("""
        CREATE TABLE IF NOT EXISTS contas_pagar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            fornecedor TEXT,
            categoria TEXT,
            centro_custo TEXT,
            forma_pagamento TEXT,
            valor REAL DEFAULT 0,
            data_emissao TEXT DEFAULT CURRENT_DATE,
            data_vencimento TEXT,
            data_pagamento TEXT,
            status TEXT DEFAULT 'Pendente',
            recorrente TEXT DEFAULT 'Não',
            observacoes TEXT,
            ativo TEXT DEFAULT 'Sim'
        )
        """)
    except Exception:
        pass

    try:
        executar("""
        CREATE TABLE IF NOT EXISTS contas_receber (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            cliente_id INTEGER,
            cliente_nome TEXT,
            categoria TEXT,
            forma_pagamento TEXT,
            valor REAL DEFAULT 0,
            valor_recebido REAL DEFAULT 0,
            data_emissao TEXT DEFAULT CURRENT_DATE,
            data_vencimento TEXT,
            data_recebimento TEXT,
            status TEXT DEFAULT 'Pendente',
            origem TEXT,
            referencia_id INTEGER,
            observacoes TEXT,
            ativo TEXT DEFAULT 'Sim'
        )
        """)
    except Exception:
        pass

    try:
        executar("""
        CREATE TABLE IF NOT EXISTS centros_custo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL,
            tipo TEXT DEFAULT 'Despesa',
            ativo TEXT DEFAULT 'Sim',
            observacoes TEXT
        )
        """)
    except Exception:
        pass

    try:
        executar("""
        CREATE TABLE IF NOT EXISTS categorias_financeiras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL,
            tipo TEXT DEFAULT 'Despesa',
            ativo TEXT DEFAULT 'Sim',
            observacoes TEXT
        )
        """)
    except Exception:
        pass


def codigo_conta(prefixo, id_valor):
    try:
        return codigo_visual(prefixo, int(id_valor))
    except Exception:
        return f"{prefixo}-{int(id_valor):04d}"


def categorias_financeiras_ativas(tipo=None):
    try:
        if tipo:
            df = consultar("""
            SELECT nome FROM categorias_financeiras
            WHERE ativo='Sim' AND tipo=?
            ORDER BY nome
            """, (tipo,))
        else:
            df = consultar("""
            SELECT nome FROM categorias_financeiras
            WHERE ativo='Sim'
            ORDER BY nome
            """)
        return df["nome"].tolist()
    except Exception:
        return ["Outros"]


def centros_custo_ativos(tipo=None):
    try:
        if tipo:
            df = consultar("""
            SELECT nome FROM centros_custo
            WHERE ativo='Sim' AND tipo=?
            ORDER BY nome
            """, (tipo,))
        else:
            df = consultar("""
            SELECT nome FROM centros_custo
            WHERE ativo='Sim'
            ORDER BY nome
            """)
        return df["nome"].tolist()
    except Exception:
        return ["Outros"]


def status_financeiro(data_vencimento, valor=0, valor_pago=0, status_atual="Pendente"):
    try:
        if status_atual in ["Pago", "Recebido", "Cancelado"]:
            return status_atual

        if n(valor_pago) > 0 and n(valor_pago) < n(valor):
            return "Parcial"

        if n(valor_pago) >= n(valor) and n(valor) > 0:
            return "Recebido"

        if data_vencimento:
            venc = pd.to_datetime(data_vencimento, errors="coerce")
            if pd.notna(venc) and venc.date() < datetime.now().date():
                return "Atrasado"

        return status_atual or "Pendente"
    except Exception:
        return status_atual or "Pendente"


def sincronizar_orcamentos_contas_receber():
    """Cria contas a receber a partir de orçamentos que ainda não foram lançados."""
    try:
        orcs = consultar("""
        SELECT id, cliente_id, cliente_nome, forma_pagamento, total, data_orcamento, status, observacoes
        FROM orcamentos
        WHERE status IN ('Aguardando pagamento', 'Produção', 'ProduÃ§Ã£o', 'Finalizado', 'Entregue')
        ORDER BY id DESC
        """)

        criadas = 0

        for _, o in orcs.iterrows():
            existe = consultar("""
            SELECT id FROM contas_receber
            WHERE origem='Orçamento' AND referencia_id=? AND ativo='Sim'
            """, (int(o["id"]),))

            if not existe.empty:
                continue

            try:
                data_venc = (pd.to_datetime(o["data_orcamento"], errors="coerce") + pd.to_timedelta(3, unit="D")).date().isoformat()
            except Exception:
                data_venc = (datetime.now().date() + timedelta(days=3)).isoformat()

            status = "Recebido" if str(o["status"]) in ["Produção", "ProduÃ§Ã£o", "Finalizado", "Entregue"] else "Pendente"
            valor_recebido = n(o["total"]) if status == "Recebido" else 0

            executar("""
            INSERT INTO contas_receber(
                descricao, cliente_id, cliente_nome, categoria, forma_pagamento,
                valor, valor_recebido, data_emissao, data_vencimento, data_recebimento,
                status, origem, referencia_id, observacoes, ativo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f"Orçamento #{int(o['id'])} - {o['cliente_nome']}",
                int(o["cliente_id"]) if pd.notna(o["cliente_id"]) else None,
                str(o["cliente_nome"]),
                "Venda",
                str(o.get("forma_pagamento", "")),
                n(o["total"]),
                valor_recebido,
                hoje_iso(),
                data_venc,
                hoje_iso() if status == "Recebido" else "",
                status,
                "Orçamento",
                int(o["id"]),
                str(o.get("observacoes", "") or ""),
                "Sim",
            ))
            criadas += 1

        return criadas

    except Exception:
        return 0


def tela_financeiro_profissional():
    garantir_financeiro_profissional()

    st.title("Financeiro Profissional")
    st.write("Controle contas a pagar, contas a receber, centros de custo e categorias financeiras.")

    abas = st.tabs([
        "Painel",
        "Contas a receber",
        "Contas a pagar",
        "Centros de custo",
        "Categorias financeiras",
    ])

    with abas[0]:
        st.subheader("Resumo financeiro")

        receber = consultar("SELECT * FROM contas_receber WHERE ativo='Sim'")
        pagar = consultar("SELECT * FROM contas_pagar WHERE ativo='Sim'")

        hoje_data = datetime.now().date()

        total_receber = float(receber[receber["status"].isin(["Pendente", "Parcial", "Atrasado"])]["valor"].sum()) if not receber.empty else 0
        recebido = float(receber[receber["status"].isin(["Recebido"])]["valor_recebido"].sum()) if not receber.empty else 0

        total_pagar = float(pagar[pagar["status"].isin(["Pendente", "Parcial", "Atrasado"])]["valor"].sum()) if not pagar.empty else 0
        pago = float(pagar[pagar["status"].isin(["Pago"])]["valor"].sum()) if not pagar.empty else 0

        atrasado_receber = 0
        atrasado_pagar = 0

        if not receber.empty:
            temp = receber.copy()
            temp["venc"] = pd.to_datetime(temp["data_vencimento"], errors="coerce")
            atrasado_receber = len(temp[(temp["venc"].dt.date < hoje_data) & (~temp["status"].isin(["Recebido", "Cancelado"]))])

        if not pagar.empty:
            temp = pagar.copy()
            temp["venc"] = pd.to_datetime(temp["data_vencimento"], errors="coerce")
            atrasado_pagar = len(temp[(temp["venc"].dt.date < hoje_data) & (~temp["status"].isin(["Pago", "Cancelado"]))])

        saldo_previsto = total_receber - total_pagar

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            card("A receber", real(total_receber))
        with c2:
            card("Recebido", real(recebido))
        with c3:
            card("A pagar", real(total_pagar))
        with c4:
            card("Pago", real(pago))
        with c5:
            card("Saldo previsto", real(saldo_previsto))

        a1, a2 = st.columns(2)
        with a1:
            card("Recebimentos atrasados", str(atrasado_receber))
        with a2:
            card("Pagamentos atrasados", str(atrasado_pagar))

        st.divider()

        if st.button("Sincronizar orçamentos com contas a receber"):
            qtd = sincronizar_orcamentos_contas_receber()
            st.success(f"{qtd} conta(s) a receber criada(s) a partir dos orçamentos.")
            st.rerun()

        st.subheader("Próximos vencimentos")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### A receber")
            if receber.empty:
                st.info("Nenhuma conta a receber.")
            else:
                prox = receber[~receber["status"].isin(["Recebido", "Cancelado"])].copy()
                prox = prox.sort_values("data_vencimento").head(10)
                st.dataframe(formatar_valores_tabela(prox), use_container_width=True, hide_index=True)

        with col2:
            st.markdown("### A pagar")
            if pagar.empty:
                st.info("Nenhuma conta a pagar.")
            else:
                prox = pagar[~pagar["status"].isin(["Pago", "Cancelado"])].copy()
                prox = prox.sort_values("data_vencimento").head(10)
                st.dataframe(formatar_valores_tabela(prox), use_container_width=True, hide_index=True)

    with abas[1]:
        st.subheader("Contas a receber")

        clientes = consultar("SELECT id, nome FROM clientes WHERE ativo='Sim' ORDER BY nome")
        lista_clientes = ["Sem cliente"]
        mapa_clientes = {"Sem cliente": (None, "")}

        if not clientes.empty:
            for _, c in clientes.iterrows():
                label = f"{int(c['id'])} - {c['nome']}"
                lista_clientes.append(label)
                mapa_clientes[label] = (int(c["id"]), str(c["nome"]))

        with st.form("form_contas_receber"):
            c1, c2 = st.columns(2)
            descricao = c1.text_input("Descrição", placeholder="Ex: Pedido cliente Maria")
            cliente_sel = c2.selectbox("Cliente", lista_clientes)

            c3, c4, c5 = st.columns(3)
            categoria = c3.selectbox("Categoria", categorias_financeiras_ativas("Receita") or ["Venda"])
            forma = c4.selectbox("Forma de pagamento", ["Pix", "Dinheiro", "Cartão de crédito", "Cartão de débito", "Mercado Pago", "Outro"])
            valor = c5.number_input("Valor", min_value=0.0, step=0.01, format="%.2f")

            c6, c7, c8 = st.columns(3)
            valor_recebido = c6.number_input("Valor recebido", min_value=0.0, step=0.01, format="%.2f")
            vencimento = c7.text_input("Data vencimento", value=(datetime.now().date() + timedelta(days=3)).isoformat())
            recebimento = c8.text_input("Data recebimento", value=hoje_iso() if valor_recebido > 0 else "")

            status = st.selectbox("Status", ["Pendente", "Parcial", "Recebido", "Atrasado", "Cancelado"])
            observacoes = st.text_area("Observações")

            if st.form_submit_button("Salvar conta a receber"):
                if not descricao.strip():
                    st.error("Digite a descrição.")
                else:
                    cliente_id, cliente_nome = mapa_clientes[cliente_sel]

                    status_final = status
                    if valor_recebido >= valor and valor > 0:
                        status_final = "Recebido"
                    elif valor_recebido > 0:
                        status_final = "Parcial"

                    executar("""
                    INSERT INTO contas_receber(
                        descricao, cliente_id, cliente_nome, categoria, forma_pagamento,
                        valor, valor_recebido, data_emissao, data_vencimento, data_recebimento,
                        status, origem, referencia_id, observacoes, ativo
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        descricao, cliente_id, cliente_nome, categoria, forma,
                        valor, valor_recebido, hoje_iso(), vencimento, recebimento,
                        status_final, "Manual", None, observacoes, "Sim",
                    ))

                    if status_final == "Recebido":
                        executar("""
                        INSERT INTO financeiro(data, tipo, descricao, categoria, forma_pagamento, valor, origem, referencia_id, observacoes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            recebimento or hoje_iso(),
                            "Entrada",
                            descricao,
                            categoria,
                            forma,
                            valor_recebido,
                            "Conta a receber",
                            None,
                            observacoes,
                        ))

                    st.success("Conta a receber salva.")
                    st.rerun()

        df = consultar("SELECT * FROM contas_receber WHERE ativo='Sim' ORDER BY data_vencimento ASC, id DESC")

        if df.empty:
            st.info("Nenhuma conta a receber cadastrada.")
        else:
            for idx, r in df.iterrows():
                novo_status = status_financeiro(r["data_vencimento"], r["valor"], r["valor_recebido"], r["status"])
                if novo_status != r["status"]:
                    executar("UPDATE contas_receber SET status=? WHERE id=?", (novo_status, int(r["id"])))
            df = consultar("SELECT * FROM contas_receber WHERE ativo='Sim' ORDER BY data_vencimento ASC, id DESC")
            df = adicionar_codigo_visual(df, "REC")

            edited = st.data_editor(
                df,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="editor_contas_receber",
                column_config={
                    "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                    "valor_recebido": st.column_config.NumberColumn("Recebido", format="R$ %.2f"),
                    "status": st.column_config.SelectboxColumn("Status", options=["Pendente", "Parcial", "Recebido", "Atrasado", "Cancelado"]),
                },
            )

            c1, c2 = st.columns([2, 1])
            with c1:
                if st.button("Salvar alterações - contas a receber"):
                    for _, r in edited.iterrows():
                        if str(r.get("descricao", "")).strip():
                            executar("""
                            UPDATE contas_receber
                            SET descricao=?, cliente_nome=?, categoria=?, forma_pagamento=?,
                                valor=?, valor_recebido=?, data_vencimento=?, data_recebimento=?,
                                status=?, observacoes=?
                            WHERE id=?
                            """, (
                                str(r.get("descricao", "")),
                                str(r.get("cliente_nome", "")),
                                str(r.get("categoria", "")),
                                str(r.get("forma_pagamento", "")),
                                n(r.get("valor", 0)),
                                n(r.get("valor_recebido", 0)),
                                str(r.get("data_vencimento", "")),
                                str(r.get("data_recebimento", "")),
                                str(r.get("status", "Pendente")),
                                str(r.get("observacoes", "")),
                                int(r["id"]),
                            ))
                    st.success("Contas a receber atualizadas.")
                    st.rerun()

            with c2:
                id_del = st.number_input("ID para excluir recebimento", min_value=0, step=1, key="del_receber")
                if st.button("Excluir recebimento"):
                    if id_del > 0:
                        executar("UPDATE contas_receber SET ativo='Não' WHERE id=?", (int(id_del),))
                        st.success("Conta a receber excluída.")
                        st.rerun()

    with abas[2]:
        st.subheader("Contas a pagar")

        with st.form("form_contas_pagar"):
            c1, c2 = st.columns(2)
            descricao = c1.text_input("Descrição", placeholder="Ex: Compra papel fotográfico")
            fornecedor = c2.text_input("Fornecedor")

            c3, c4, c5 = st.columns(3)
            categoria = c3.selectbox("Categoria", categorias_financeiras_ativas("Despesa") or ["Outros"])
            centro = c4.selectbox("Centro de custo", centros_custo_ativos("Despesa") or ["Outros"])
            forma = c5.selectbox("Forma de pagamento", ["Pix", "Dinheiro", "Cartão de crédito", "Cartão de débito", "Boleto", "Mercado Pago", "Outro"])

            c6, c7, c8 = st.columns(3)
            valor = c6.number_input("Valor", min_value=0.0, step=0.01, format="%.2f")
            vencimento = c7.text_input("Data vencimento", value=(datetime.now().date() + timedelta(days=7)).isoformat())
            pagamento = c8.text_input("Data pagamento", value="")

            c9, c10 = st.columns(2)
            status = c9.selectbox("Status", ["Pendente", "Pago", "Atrasado", "Cancelado"])
            recorrente = c10.selectbox("Recorrente?", ["Não", "Sim"])

            observacoes = st.text_area("Observações", key="obs_pagar")

            if st.form_submit_button("Salvar conta a pagar"):
                if not descricao.strip():
                    st.error("Digite a descrição.")
                else:
                    executar("""
                    INSERT INTO contas_pagar(
                        descricao, fornecedor, categoria, centro_custo, forma_pagamento,
                        valor, data_emissao, data_vencimento, data_pagamento,
                        status, recorrente, observacoes, ativo
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        descricao, fornecedor, categoria, centro, forma,
                        valor, hoje_iso(), vencimento, pagamento,
                        status, recorrente, observacoes, "Sim",
                    ))

                    if status == "Pago":
                        executar("""
                        INSERT INTO financeiro(data, tipo, descricao, categoria, forma_pagamento, valor, origem, referencia_id, observacoes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            pagamento or hoje_iso(),
                            "Saída",
                            descricao,
                            categoria,
                            forma,
                            valor,
                            "Conta a pagar",
                            None,
                            observacoes,
                        ))

                    st.success("Conta a pagar salva.")
                    st.rerun()

        df = consultar("SELECT * FROM contas_pagar WHERE ativo='Sim' ORDER BY data_vencimento ASC, id DESC")

        if df.empty:
            st.info("Nenhuma conta a pagar cadastrada.")
        else:
            for idx, r in df.iterrows():
                novo_status = status_financeiro(r["data_vencimento"], r["valor"], r["valor"] if r["status"] == "Pago" else 0, r["status"])
                if novo_status != r["status"]:
                    executar("UPDATE contas_pagar SET status=? WHERE id=?", (novo_status, int(r["id"])))
            df = consultar("SELECT * FROM contas_pagar WHERE ativo='Sim' ORDER BY data_vencimento ASC, id DESC")
            df = adicionar_codigo_visual(df, "PAG")

            edited = st.data_editor(
                df,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="editor_contas_pagar",
                column_config={
                    "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                    "status": st.column_config.SelectboxColumn("Status", options=["Pendente", "Pago", "Atrasado", "Cancelado"]),
                    "recorrente": st.column_config.SelectboxColumn("Recorrente", options=["Sim", "Não"]),
                },
            )

            c1, c2 = st.columns([2, 1])
            with c1:
                if st.button("Salvar alterações - contas a pagar"):
                    for _, r in edited.iterrows():
                        if str(r.get("descricao", "")).strip():
                            executar("""
                            UPDATE contas_pagar
                            SET descricao=?, fornecedor=?, categoria=?, centro_custo=?, forma_pagamento=?,
                                valor=?, data_vencimento=?, data_pagamento=?,
                                status=?, recorrente=?, observacoes=?
                            WHERE id=?
                            """, (
                                str(r.get("descricao", "")),
                                str(r.get("fornecedor", "")),
                                str(r.get("categoria", "")),
                                str(r.get("centro_custo", "")),
                                str(r.get("forma_pagamento", "")),
                                n(r.get("valor", 0)),
                                str(r.get("data_vencimento", "")),
                                str(r.get("data_pagamento", "")),
                                str(r.get("status", "Pendente")),
                                str(r.get("recorrente", "Não")),
                                str(r.get("observacoes", "")),
                                int(r["id"]),
                            ))
                    st.success("Contas a pagar atualizadas.")
                    st.rerun()

            with c2:
                id_del = st.number_input("ID para excluir pagamento", min_value=0, step=1, key="del_pagar")
                if st.button("Excluir pagamento"):
                    if id_del > 0:
                        executar("UPDATE contas_pagar SET ativo='Não' WHERE id=?", (int(id_del),))
                        st.success("Conta a pagar excluída.")
                        st.rerun()

    with abas[3]:
        st.subheader("Centros de custo")

        with st.form("form_centros_custo"):
            c1, c2 = st.columns(2)
            nome = c1.text_input("Nome do centro de custo")
            tipo = c2.selectbox("Tipo", ["Despesa", "Receita"])
            obs = st.text_input("Observação")
            if st.form_submit_button("Adicionar centro de custo"):
                if nome.strip():
                    executar("""
                    INSERT OR IGNORE INTO centros_custo(nome, tipo, ativo, observacoes)
                    VALUES (?, ?, 'Sim', ?)
                    """, (nome.strip(), tipo, obs))
                    st.success("Centro de custo salvo.")
                    st.rerun()

        df = consultar("SELECT * FROM centros_custo ORDER BY tipo, nome")
        edited = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            key="editor_centros_custo",
            column_config={
                "tipo": st.column_config.SelectboxColumn("Tipo", options=["Despesa", "Receita"]),
                "ativo": st.column_config.SelectboxColumn("Ativo", options=["Sim", "Não"]),
            },
        )

        if st.button("Salvar centros de custo"):
            for _, r in edited.iterrows():
                if str(r.get("nome", "")).strip():
                    if pd.isna(r.get("id")):
                        executar("""
                        INSERT OR IGNORE INTO centros_custo(nome, tipo, ativo, observacoes)
                        VALUES (?, ?, ?, ?)
                        """, (str(r["nome"]), str(r.get("tipo", "Despesa")), str(r.get("ativo", "Sim")), str(r.get("observacoes", ""))))
                    else:
                        executar("""
                        UPDATE centros_custo SET nome=?, tipo=?, ativo=?, observacoes=? WHERE id=?
                        """, (str(r["nome"]), str(r.get("tipo", "Despesa")), str(r.get("ativo", "Sim")), str(r.get("observacoes", "")), int(r["id"])))
            st.success("Centros atualizados.")
            st.rerun()

    with abas[4]:
        st.subheader("Categorias financeiras")

        with st.form("form_categorias_financeiras"):
            c1, c2 = st.columns(2)
            nome = c1.text_input("Nome da categoria financeira")
            tipo = c2.selectbox("Tipo", ["Despesa", "Receita"], key="tipo_cat_fin")
            obs = st.text_input("Observação", key="obs_cat_fin")
            if st.form_submit_button("Adicionar categoria financeira"):
                if nome.strip():
                    executar("""
                    INSERT OR IGNORE INTO categorias_financeiras(nome, tipo, ativo, observacoes)
                    VALUES (?, ?, 'Sim', ?)
                    """, (nome.strip(), tipo, obs))
                    st.success("Categoria financeira salva.")
                    st.rerun()

        df = consultar("SELECT * FROM categorias_financeiras ORDER BY tipo, nome")
        edited = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            key="editor_categorias_financeiras",
            column_config={
                "tipo": st.column_config.SelectboxColumn("Tipo", options=["Despesa", "Receita"]),
                "ativo": st.column_config.SelectboxColumn("Ativo", options=["Sim", "Não"]),
            },
        )

        if st.button("Salvar categorias financeiras"):
            for _, r in edited.iterrows():
                if str(r.get("nome", "")).strip():
                    if pd.isna(r.get("id")):
                        executar("""
                        INSERT OR IGNORE INTO categorias_financeiras(nome, tipo, ativo, observacoes)
                        VALUES (?, ?, ?, ?)
                        """, (str(r["nome"]), str(r.get("tipo", "Despesa")), str(r.get("ativo", "Sim")), str(r.get("observacoes", ""))))
                    else:
                        executar("""
                        UPDATE categorias_financeiras SET nome=?, tipo=?, ativo=?, observacoes=? WHERE id=?
                        """, (str(r["nome"]), str(r.get("tipo", "Despesa")), str(r.get("ativo", "Sim")), str(r.get("observacoes", "")), int(r["id"])))
            st.success("Categorias financeiras atualizadas.")
            st.rerun()




# ============================================================
# MÓDULO 4B — DASHBOARD FINANCEIRO / DRE / RELATÓRIOS
# ============================================================

def periodo_datas_financeiro(ano, mes=None):
    if mes and mes != "Ano inteiro":
        meses = {
            "Janeiro": 1, "Fevereiro": 2, "Março": 3, "Abril": 4,
            "Maio": 5, "Junho": 6, "Julho": 7, "Agosto": 8,
            "Setembro": 9, "Outubro": 10, "Novembro": 11, "Dezembro": 12,
        }
        m = meses.get(mes, datetime.now().month)
        inicio = date(int(ano), m, 1)
        if m == 12:
            fim = date(int(ano) + 1, 1, 1) - timedelta(days=1)
        else:
            fim = date(int(ano), m + 1, 1) - timedelta(days=1)
        return inicio.isoformat(), fim.isoformat()

    return date(int(ano), 1, 1).isoformat(), date(int(ano), 12, 31).isoformat()


def dados_financeiros_periodo(inicio, fim):
    receber = consultar("""
    SELECT *
    FROM contas_receber
    WHERE ativo='Sim'
      AND COALESCE(data_vencimento, data_emissao) BETWEEN ? AND ?
    """, (inicio, fim))

    pagar = consultar("""
    SELECT *
    FROM contas_pagar
    WHERE ativo='Sim'
      AND COALESCE(data_vencimento, data_emissao) BETWEEN ? AND ?
    """, (inicio, fim))

    fluxo = consultar("""
    SELECT *
    FROM financeiro
    WHERE data BETWEEN ? AND ?
    """, (inicio, fim))

    orcs = consultar("""
    SELECT *
    FROM orcamentos
    WHERE date(data_orcamento) BETWEEN ? AND ?
    """, (inicio, fim))

    return receber, pagar, fluxo, orcs


def calcular_dre_simples(inicio, fim):
    receber, pagar, fluxo, orcs = dados_financeiros_periodo(inicio, fim)

    receita_bruta = 0.0
    recebido = 0.0
    custos_produtos = 0.0
    despesas = 0.0

    if not receber.empty:
        receita_bruta = float(receber["valor"].fillna(0).sum())
        recebido = float(receber["valor_recebido"].fillna(0).sum())

    if not fluxo.empty:
        entradas_fluxo = float(fluxo[fluxo["tipo"] == "Entrada"]["valor"].fillna(0).sum())
        saidas_fluxo = float(fluxo[fluxo["tipo"].isin(["Saída", "SaÃ­da"])]["valor"].fillna(0).sum())
        receita_bruta = max(receita_bruta, entradas_fluxo)
        despesas += saidas_fluxo

    if not pagar.empty:
        despesas += float(pagar[pagar["status"].isin(["Pago", "Pendente", "Parcial", "Atrasado"])]["valor"].fillna(0).sum())

    if not orcs.empty:
        # Estimativa de custo dos pedidos usando produtos salvos quando possível.
        try:
            itens = consultar("""
            SELECT oi.produto, oi.quantidade, p.custo_unitario
            FROM orcamento_itens oi
            LEFT JOIN produtos p ON p.nome = oi.produto
            LEFT JOIN orcamentos o ON o.id = oi.orcamento_id
            WHERE date(o.data_orcamento) BETWEEN ? AND ?
            """, (inicio, fim))
            if not itens.empty:
                custos_produtos = float((itens["quantidade"].fillna(0) * itens["custo_unitario"].fillna(0)).sum())
        except Exception:
            custos_produtos = 0.0

    lucro_bruto = receita_bruta - custos_produtos
    lucro_liquido = lucro_bruto - despesas
    margem_bruta = (lucro_bruto / receita_bruta * 100) if receita_bruta > 0 else 0
    margem_liquida = (lucro_liquido / receita_bruta * 100) if receita_bruta > 0 else 0

    return {
        "receita_bruta": receita_bruta,
        "recebido": recebido,
        "custos_produtos": custos_produtos,
        "despesas": despesas,
        "lucro_bruto": lucro_bruto,
        "lucro_liquido": lucro_liquido,
        "margem_bruta": margem_bruta,
        "margem_liquida": margem_liquida,
    }


def tabela_fluxo_previsto(inicio, fim):
    receber = consultar("""
    SELECT data_vencimento AS data, 'Entrada prevista' AS tipo, descricao, valor AS valor, status
    FROM contas_receber
    WHERE ativo='Sim' AND data_vencimento BETWEEN ? AND ?
    """, (inicio, fim))

    pagar = consultar("""
    SELECT data_vencimento AS data, 'Saída prevista' AS tipo, descricao, valor * -1 AS valor, status
    FROM contas_pagar
    WHERE ativo='Sim' AND data_vencimento BETWEEN ? AND ?
    """, (inicio, fim))

    partes = []
    if not receber.empty:
        partes.append(receber)
    if not pagar.empty:
        partes.append(pagar)

    if not partes:
        return pd.DataFrame(columns=["data", "tipo", "descricao", "valor", "status", "saldo_acumulado"])

    df = pd.concat(partes, ignore_index=True)
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df = df.sort_values("data")
    df["saldo_acumulado"] = df["valor"].fillna(0).cumsum()
    return df


def exportar_relatorio_financeiro_html(inicio, fim, dre, fluxo_previsto):
    empresa = obter_config("nome_empresa", EMPRESA)

    linhas_fluxo = ""
    if fluxo_previsto is not None and not fluxo_previsto.empty:
        for _, r in fluxo_previsto.iterrows():
            try:
                data_txt = pd.to_datetime(r["data"]).strftime("%d/%m/%Y")
            except Exception:
                data_txt = str(r["data"])
            linhas_fluxo += f"""
            <tr>
                <td>{data_txt}</td>
                <td>{r.get('tipo','')}</td>
                <td>{r.get('descricao','')}</td>
                <td class="right">{real(r.get('valor',0))}</td>
                <td>{r.get('status','')}</td>
                <td class="right">{real(r.get('saldo_acumulado',0))}</td>
            </tr>
            """

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Relatório Financeiro - {empresa}</title>
<style>
body {{ font-family: Arial, sans-serif; color:#111; padding:24px; }}
h1 {{ margin:0; }}
.header {{ border-bottom:3px solid #111; padding-bottom:14px; margin-bottom:18px; }}
.grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }}
.card {{ border:1px solid #ddd; border-radius:12px; padding:12px; }}
.label {{ font-size:11px; text-transform:uppercase; color:#777; }}
.value {{ font-size:22px; font-weight:900; margin-top:6px; }}
table {{ width:100%; border-collapse:collapse; margin-top:18px; }}
th {{ background:#000; color:#fff; padding:8px; text-align:left; }}
td {{ border-bottom:1px solid #eee; padding:7px; }}
.right {{ text-align:right; }}
button {{ position:fixed; right:18px; top:18px; background:#111; color:#fff; border:0; border-radius:8px; padding:10px 16px; font-weight:800; }}
@media print {{ button {{ display:none; }} }}
</style>
</head>
<body>
<button onclick="window.print()">Imprimir / salvar PDF</button>
<div class="header">
    <h1>{empresa}</h1>
    <p>Relatório financeiro de {inicio} até {fim}</p>
</div>

<div class="grid">
    <div class="card"><div class="label">Receita Bruta</div><div class="value">{real(dre['receita_bruta'])}</div></div>
    <div class="card"><div class="label">Custos</div><div class="value">{real(dre['custos_produtos'])}</div></div>
    <div class="card"><div class="label">Despesas</div><div class="value">{real(dre['despesas'])}</div></div>
    <div class="card"><div class="label">Lucro Líquido</div><div class="value">{real(dre['lucro_liquido'])}</div></div>
</div>

<h2>DRE Simplificada</h2>
<table>
<tr><th>Indicador</th><th class="right">Valor</th></tr>
<tr><td>Receita bruta</td><td class="right">{real(dre['receita_bruta'])}</td></tr>
<tr><td>Recebido</td><td class="right">{real(dre['recebido'])}</td></tr>
<tr><td>Custos dos produtos</td><td class="right">{real(dre['custos_produtos'])}</td></tr>
<tr><td>Lucro bruto</td><td class="right">{real(dre['lucro_bruto'])}</td></tr>
<tr><td>Despesas operacionais</td><td class="right">{real(dre['despesas'])}</td></tr>
<tr><td>Lucro líquido</td><td class="right">{real(dre['lucro_liquido'])}</td></tr>
<tr><td>Margem líquida</td><td class="right">{dre['margem_liquida']:.2f}%</td></tr>
</table>

<h2>Fluxo previsto</h2>
<table>
<tr><th>Data</th><th>Tipo</th><th>Descrição</th><th class="right">Valor</th><th>Status</th><th class="right">Saldo acumulado</th></tr>
{linhas_fluxo}
</table>

</body>
</html>"""
    return html


def tela_dashboard_financeiro():
    garantir_financeiro_profissional()

    st.title("Dashboard Financeiro")
    st.write("DRE, fluxo previsto, gráficos, alertas e relatório financeiro.")

    anos = list(range(2026, 2031))
    meses = [
        "Ano inteiro", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ]

    c1, c2 = st.columns(2)
    ano = c1.selectbox("Ano", anos, index=0, key="dash_fin_ano")
    mes = c2.selectbox("Período", meses, key="dash_fin_mes")

    inicio, fim = periodo_datas_financeiro(ano, mes)
    dre = calcular_dre_simples(inicio, fim)
    receber, pagar, fluxo, orcs = dados_financeiros_periodo(inicio, fim)

    st.divider()

    st.subheader("Indicadores principais")

    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        card("Receita bruta", real(dre["receita_bruta"]))
    with k2:
        card("Recebido", real(dre["recebido"]))
    with k3:
        card("Despesas", real(dre["despesas"]))
    with k4:
        card("Lucro líquido", real(dre["lucro_liquido"]))
    with k5:
        card("Margem líquida", f"{dre['margem_liquida']:.2f}%")

    st.subheader("Alertas financeiros")

    hoje = datetime.now().date()
    alertas = []

    if not receber.empty:
        temp = receber.copy()
        temp["venc"] = pd.to_datetime(temp["data_vencimento"], errors="coerce")
        atrasados = temp[(temp["venc"].dt.date < hoje) & (~temp["status"].isin(["Recebido", "Cancelado"]))]
        if not atrasados.empty:
            alertas.append(f"🔴 {len(atrasados)} recebimento(s) atrasado(s).")

        proximos = temp[(temp["venc"].dt.date >= hoje) & (temp["venc"].dt.date <= hoje + timedelta(days=7)) & (~temp["status"].isin(["Recebido", "Cancelado"]))]
        if not proximos.empty:
            alertas.append(f"🟡 {len(proximos)} recebimento(s) vencendo em até 7 dias.")

    if not pagar.empty:
        temp = pagar.copy()
        temp["venc"] = pd.to_datetime(temp["data_vencimento"], errors="coerce")
        atrasados = temp[(temp["venc"].dt.date < hoje) & (~temp["status"].isin(["Pago", "Cancelado"]))]
        if not atrasados.empty:
            alertas.append(f"🔴 {len(atrasados)} conta(s) a pagar atrasada(s).")

        proximos = temp[(temp["venc"].dt.date >= hoje) & (temp["venc"].dt.date <= hoje + timedelta(days=7)) & (~temp["status"].isin(["Pago", "Cancelado"]))]
        if not proximos.empty:
            alertas.append(f"🟠 {len(proximos)} conta(s) a pagar vencendo em até 7 dias.")

    if dre["lucro_liquido"] < 0:
        alertas.append("🔴 Lucro líquido negativo neste período.")

    if not alertas:
        st.success("Nenhum alerta financeiro crítico no período.")
    else:
        for alerta in alertas:
            st.warning(alerta)

    st.divider()

    st.subheader("DRE simplificada")

    dre_df = pd.DataFrame([
        {"Indicador": "Receita bruta", "Valor": dre["receita_bruta"]},
        {"Indicador": "Recebido", "Valor": dre["recebido"]},
        {"Indicador": "Custos dos produtos", "Valor": dre["custos_produtos"]},
        {"Indicador": "Lucro bruto", "Valor": dre["lucro_bruto"]},
        {"Indicador": "Despesas operacionais", "Valor": dre["despesas"]},
        {"Indicador": "Lucro líquido", "Valor": dre["lucro_liquido"]},
        {"Indicador": "Margem bruta (%)", "Valor": dre["margem_bruta"]},
        {"Indicador": "Margem líquida (%)", "Valor": dre["margem_liquida"]},
    ])

    st.dataframe(formatar_valores_tabela(dre_df), use_container_width=True, hide_index=True)

    chart_df = dre_df[dre_df["Indicador"].isin(["Receita bruta", "Custos dos produtos", "Despesas operacionais", "Lucro líquido"])].copy()
    st.bar_chart(chart_df.set_index("Indicador"))

    st.divider()

    st.subheader("Fluxo de caixa previsto")

    fluxo_previsto = tabela_fluxo_previsto(inicio, fim)

    if fluxo_previsto.empty:
        st.info("Sem contas previstas para o período.")
    else:
        st.dataframe(formatar_valores_tabela(fluxo_previsto), use_container_width=True, hide_index=True)

        graf = fluxo_previsto.copy()
        graf["data"] = pd.to_datetime(graf["data"], errors="coerce")
        graf = graf.dropna(subset=["data"])
        if not graf.empty:
            serie = graf.groupby("data")["saldo_acumulado"].last()
            st.line_chart(serie)

    st.divider()

    st.subheader("Despesas por centro de custo")

    if pagar.empty:
        st.info("Sem despesas cadastradas no período.")
    else:
        centro = pagar.groupby("centro_custo")["valor"].sum().reset_index().sort_values("valor", ascending=False)
        st.dataframe(formatar_valores_tabela(centro), use_container_width=True, hide_index=True)
        st.bar_chart(centro.set_index("centro_custo"))

    st.divider()

    st.subheader("Receitas por categoria")

    if receber.empty:
        st.info("Sem receitas cadastradas no período.")
    else:
        receita_cat = receber.groupby("categoria")["valor"].sum().reset_index().sort_values("valor", ascending=False)
        st.dataframe(formatar_valores_tabela(receita_cat), use_container_width=True, hide_index=True)
        st.bar_chart(receita_cat.set_index("categoria"))

    st.divider()

    st.subheader("Exportar relatório")

    html = exportar_relatorio_financeiro_html(inicio, fim, dre, fluxo_previsto)

    st.download_button(
        "Baixar relatório financeiro em HTML/PDF",
        data=html.encode("utf-8"),
        file_name=f"relatorio_financeiro_{inicio}_a_{fim}.html",
        mime="text/html",
    )

    if not fluxo_previsto.empty:
        csv = fluxo_previsto.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Baixar fluxo previsto em CSV",
            data=csv,
            file_name=f"fluxo_previsto_{inicio}_a_{fim}.csv",
            mime="text/csv",
        )




# ============================================================
# MÓDULO 5 — CRM INTELIGENTE / CLIENTES VIP
# ============================================================

def garantir_crm():
    try:
        executar("""
        CREATE TABLE IF NOT EXISTS crm_interacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER,
            cliente_nome TEXT,
            data TEXT DEFAULT CURRENT_TIMESTAMP,
            tipo TEXT,
            canal TEXT,
            descricao TEXT,
            status TEXT DEFAULT 'Registrado',
            proximo_contato TEXT,
            observacoes TEXT
        )
        """)
    except Exception:
        pass

    try:
        executar("""
        CREATE TABLE IF NOT EXISTS crm_fidelidade (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER UNIQUE,
            cliente_nome TEXT,
            pontos REAL DEFAULT 0,
            nivel TEXT DEFAULT 'Novo',
            total_gasto REAL DEFAULT 0,
            total_pedidos INTEGER DEFAULT 0,
            ultima_compra TEXT,
            observacoes TEXT
        )
        """)
    except Exception:
        pass

    try:
        executar("""
        CREATE TABLE IF NOT EXISTS crm_cupons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            descricao TEXT,
            tipo TEXT DEFAULT 'Percentual',
            valor REAL DEFAULT 0,
            minimo_compra REAL DEFAULT 0,
            validade TEXT,
            ativo TEXT DEFAULT 'Sim',
            observacoes TEXT
        )
        """)
    except Exception:
        pass


def nivel_cliente(total_gasto, total_pedidos):
    total_gasto = n(total_gasto)
    total_pedidos = int(n(total_pedidos))

    if total_gasto >= 2000 or total_pedidos >= 15:
        return "Diamante"
    if total_gasto >= 1000 or total_pedidos >= 8:
        return "Ouro"
    if total_gasto >= 500 or total_pedidos >= 4:
        return "Prata"
    if total_pedidos >= 1:
        return "Bronze"
    return "Novo"


def sincronizar_fidelidade_clientes():
    garantir_crm()

    clientes = consultar("""
    SELECT id, nome
    FROM clientes
    WHERE ativo='Sim'
    ORDER BY nome
    """)

    if clientes.empty:
        return 0

    atualizados = 0

    for _, c in clientes.iterrows():
        orcs = consultar("""
        SELECT total, data_orcamento, status
        FROM orcamentos
        WHERE cliente_id=?
          AND status NOT IN ('Cancelado')
        ORDER BY data_orcamento DESC
        """, (int(c["id"]),))

        total_gasto = float(orcs["total"].fillna(0).sum()) if not orcs.empty else 0.0
        total_pedidos = len(orcs) if not orcs.empty else 0
        ultima_compra = ""
        if not orcs.empty:
            try:
                ultima_compra = str(orcs.iloc[0]["data_orcamento"])
            except Exception:
                ultima_compra = ""

        pontos = total_gasto // 10
        nivel = nivel_cliente(total_gasto, total_pedidos)

        executar("""
        INSERT OR REPLACE INTO crm_fidelidade(
            cliente_id, cliente_nome, pontos, nivel,
            total_gasto, total_pedidos, ultima_compra, observacoes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT observacoes FROM crm_fidelidade WHERE cliente_id=?), ''))
        """, (
            int(c["id"]),
            str(c["nome"]),
            pontos,
            nivel,
            total_gasto,
            total_pedidos,
            ultima_compra,
            int(c["id"]),
        ))

        atualizados += 1

    return atualizados


def aniversariantes_periodo():
    clientes = consultar("""
    SELECT id, nome, whatsapp, aniversario
    FROM clientes
    WHERE ativo='Sim' AND aniversario IS NOT NULL AND aniversario != ''
    ORDER BY nome
    """)

    if clientes.empty:
        return clientes

    mes_atual = datetime.now().month

    def mes_aniv(valor):
        try:
            texto = str(valor).replace("-", "/").strip()
            partes = texto.split("/")
            if len(partes) >= 2:
                return int(partes[1]) == mes_atual
        except Exception:
            pass
        return False

    return clientes[clientes["aniversario"].apply(mes_aniv)]


def dias_desde(data_txt):
    try:
        d = pd.to_datetime(data_txt, errors="coerce")
        if pd.isna(d):
            return ""
        return (datetime.now() - d.to_pydatetime()).days
    except Exception:
        return ""


def gerar_mensagem_cliente(cliente_nome, tipo, extra=""):
    if tipo == "Pós-venda":
        return f"Olá {cliente_nome}, tudo bem? Passando para saber se deu tudo certo com o seu pedido da Sophi Personalizados. 🤍"
    if tipo == "Aniversário":
        return f"Olá {cliente_nome}! A Sophi Personalizados deseja um feliz aniversário cheio de momentos especiais. 🎂✨"
    if tipo == "Reativação":
        return f"Olá {cliente_nome}, tudo bem? Passando para te mostrar as novidades da Sophi Personalizados. Temos novas opções de presentes personalizados. 🤍"
    if tipo == "VIP":
        return f"Olá {cliente_nome}! Você é uma cliente especial para a Sophi Personalizados. Preparamos condições especiais para o seu próximo pedido. ✨"
    return f"Olá {cliente_nome}, tudo bem? {extra}"


def tela_crm_inteligente():
    garantir_crm()

    st.title("CRM Inteligente")
    st.write("Acompanhe clientes, histórico, fidelidade, aniversários, pós-venda e ranking de melhores clientes.")

    abas = st.tabs([
        "Painel CRM",
        "Ficha do cliente",
        "Interações",
        "Fidelidade / VIP",
        "Cupons",
        "Pós-venda",
    ])

    with abas[0]:
        st.subheader("Resumo de relacionamento")

        if st.button("Atualizar fidelidade dos clientes"):
            qtd = sincronizar_fidelidade_clientes()
            st.success(f"{qtd} cliente(s) atualizado(s) no CRM.")
            st.rerun()

        fidelidade = consultar("SELECT * FROM crm_fidelidade ORDER BY total_gasto DESC")
        clientes = consultar("SELECT * FROM clientes WHERE ativo='Sim'")
        anivers = aniversariantes_periodo()

        total_clientes = len(clientes)
        clientes_vip = len(fidelidade[fidelidade["nivel"].isin(["Ouro", "Diamante"])]) if not fidelidade.empty else 0
        total_gasto = float(fidelidade["total_gasto"].fillna(0).sum()) if not fidelidade.empty else 0
        ticket_medio = total_gasto / total_clientes if total_clientes else 0

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            card("Clientes ativos", str(total_clientes))
        with c2:
            card("Clientes VIP", str(clientes_vip))
        with c3:
            card("Total vendido", real(total_gasto))
        with c4:
            card("Ticket médio", real(ticket_medio))

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Ranking de clientes")
            if fidelidade.empty:
                st.info("Atualize a fidelidade para gerar ranking.")
            else:
                rank = fidelidade.head(15).copy()
                rank = adicionar_codigo_visual(rank, "CLI", coluna_id="cliente_id", nome_coluna="Código")
                st.dataframe(formatar_valores_tabela(rank), use_container_width=True, hide_index=True)

        with col2:
            st.subheader("Aniversariantes do mês")
            if anivers.empty:
                st.info("Nenhum aniversariante neste mês.")
            else:
                anivers = adicionar_codigo_visual(anivers, "CLI")
                st.dataframe(anivers, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Clientes sem compra recente")

        if fidelidade.empty:
            st.info("Sem dados ainda.")
        else:
            temp = fidelidade.copy()
            temp["dias_sem_compra"] = temp["ultima_compra"].apply(dias_desde)
            temp = temp[temp["dias_sem_compra"].apply(lambda x: isinstance(x, int) and x >= 30)]
            if temp.empty:
                st.success("Nenhum cliente parado há mais de 30 dias.")
            else:
                st.dataframe(formatar_valores_tabela(temp.sort_values("dias_sem_compra", ascending=False)), use_container_width=True, hide_index=True)

    with abas[1]:
        st.subheader("Ficha completa do cliente")

        clientes = consultar("SELECT id, nome, whatsapp FROM clientes WHERE ativo='Sim' ORDER BY nome")

        if clientes.empty:
            st.info("Nenhum cliente cadastrado.")
        else:
            mapa = {
                f"{codigo_visual('CLI', row['id'])} - {row['nome']}": int(row["id"])
                for _, row in clientes.iterrows()
            }

            escolhido = st.selectbox("Escolha um cliente", list(mapa.keys()), key="crm_ficha_cliente")
            cliente_id = mapa[escolhido]

            cli = consultar("SELECT * FROM clientes WHERE id=?", (int(cliente_id),))
            fid = consultar("SELECT * FROM crm_fidelidade WHERE cliente_id=?", (int(cliente_id),))
            orcs = consultar("""
            SELECT id, status, forma_pagamento, total, data_orcamento
            FROM orcamentos
            WHERE cliente_id=?
            ORDER BY id DESC
            """, (int(cliente_id),))
            inter = consultar("""
            SELECT data, tipo, canal, descricao, status, proximo_contato, observacoes
            FROM crm_interacoes
            WHERE cliente_id=?
            ORDER BY id DESC
            """, (int(cliente_id),))

            if cli.empty:
                st.warning("Cliente não encontrado.")
            else:
                c = cli.iloc[0]

                total_gasto = float(orcs["total"].fillna(0).sum()) if not orcs.empty else 0
                qtd_pedidos = len(orcs)
                ticket = total_gasto / qtd_pedidos if qtd_pedidos else 0

                nivel = "Novo"
                pontos = 0
                if not fid.empty:
                    nivel = fid.iloc[0]["nivel"]
                    pontos = fid.iloc[0]["pontos"]

                k1, k2, k3, k4, k5 = st.columns(5)
                with k1:
                    card("Cliente", codigo_visual("CLI", c["id"]))
                with k2:
                    card("Nível", str(nivel), f"{pontos:.0f} ponto(s)")
                with k3:
                    card("Pedidos", str(qtd_pedidos))
                with k4:
                    card("Total gasto", real(total_gasto))
                with k5:
                    card("Ticket médio", real(ticket))

                st.write(f"**Nome:** {c['nome']}")
                st.write(f"**WhatsApp:** {c['whatsapp'] or '-'}")
                st.write(f"**Instagram:** {c['instagram'] or '-'}")
                st.write(f"**Cidade:** {c['cidade'] or '-'}")
                st.write(f"**Aniversário:** {c['aniversario'] or '-'}")
                st.write(f"**Observações:** {c['observacoes'] or '-'}")

                st.markdown("### Linha do tempo de pedidos")
                if orcs.empty:
                    st.info("Nenhum pedido/orçamento ainda.")
                else:
                    for _, r in orcs.iterrows():
                        st.write(f"✔ **{codigo_visual('ORC', r['id'], ano=datetime.now().year)}** — {r['status']} — {real(r['total'])} — {r['data_orcamento']}")

                st.markdown("### Interações registradas")
                if inter.empty:
                    st.info("Nenhuma interação registrada.")
                else:
                    st.dataframe(inter, use_container_width=True, hide_index=True)

    with abas[2]:
        st.subheader("Registrar interação com cliente")

        clientes = consultar("SELECT id, nome FROM clientes WHERE ativo='Sim' ORDER BY nome")

        if clientes.empty:
            st.info("Cadastre clientes primeiro.")
        else:
            mapa = {
                f"{codigo_visual('CLI', row['id'])} - {row['nome']}": (int(row["id"]), str(row["nome"]))
                for _, row in clientes.iterrows()
            }

            with st.form("form_crm_interacao"):
                escolhido = st.selectbox("Cliente", list(mapa.keys()))
                tipo = st.selectbox("Tipo", ["Atendimento", "Pós-venda", "Orçamento", "Reclamação", "Elogio", "Aniversário", "Reativação", "Outro"])
                canal = st.selectbox("Canal", ["WhatsApp", "Instagram", "E-mail", "Telefone", "Presencial", "Outro"])
                descricao = st.text_area("Descrição")
                status = st.selectbox("Status", ["Registrado", "Aguardando resposta", "Resolvido", "Pendente"])
                proximo = st.text_input("Próximo contato", placeholder="AAAA-MM-DD")
                obs = st.text_area("Observações internas")

                if st.form_submit_button("Salvar interação"):
                    cliente_id, cliente_nome = mapa[escolhido]
                    executar("""
                    INSERT INTO crm_interacoes(
                        cliente_id, cliente_nome, tipo, canal, descricao,
                        status, proximo_contato, observacoes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        cliente_id, cliente_nome, tipo, canal, descricao,
                        status, proximo, obs,
                    ))
                    st.success("Interação registrada.")
                    st.rerun()

        st.subheader("Histórico de interações")
        inter = consultar("""
        SELECT id, cliente_nome, data, tipo, canal, descricao, status, proximo_contato, observacoes
        FROM crm_interacoes
        ORDER BY id DESC
        LIMIT 300
        """)
        if inter.empty:
            st.info("Nenhuma interação ainda.")
        else:
            st.dataframe(inter, use_container_width=True, hide_index=True)

    with abas[3]:
        st.subheader("Fidelidade e clientes VIP")

        if st.button("Recalcular fidelidade agora"):
            qtd = sincronizar_fidelidade_clientes()
            st.success(f"{qtd} cliente(s) recalculado(s).")
            st.rerun()

        fid = consultar("SELECT * FROM crm_fidelidade ORDER BY total_gasto DESC")

        if fid.empty:
            st.info("Ainda não há dados de fidelidade.")
        else:
            fid = adicionar_codigo_visual(fid, "CLI", coluna_id="cliente_id", nome_coluna="Código")
            st.dataframe(formatar_valores_tabela(fid), use_container_width=True, hide_index=True)

            st.markdown("### Clientes por nível")
            agrupado = fid.groupby("nivel")["cliente_id"].count().reset_index()
            agrupado.columns = ["Nível", "Clientes"]
            st.bar_chart(agrupado.set_index("Nível"))

            st.info("Regra atual: Bronze = 1 pedido, Prata = R$500 ou 4 pedidos, Ouro = R$1000 ou 8 pedidos, Diamante = R$2000 ou 15 pedidos.")

    with abas[4]:
        st.subheader("Cupons")

        with st.form("form_cupom_crm"):
            c1, c2, c3 = st.columns(3)
            codigo = c1.text_input("Código do cupom", placeholder="PROMO10")
            tipo = c2.selectbox("Tipo", ["Percentual", "Valor fixo"])
            valor = c3.number_input("Valor", min_value=0.0, step=0.01, format="%.2f")

            c4, c5 = st.columns(2)
            minimo = c4.number_input("Mínimo de compra", min_value=0.0, step=0.01, format="%.2f")
            validade = c5.text_input("Validade", placeholder="AAAA-MM-DD")

            descricao = st.text_input("Descrição")
            ativo = st.selectbox("Ativo?", ["Sim", "Não"], key="cupom_ativo")
            obs = st.text_area("Observações do cupom")

            if st.form_submit_button("Salvar cupom"):
                if not codigo.strip():
                    st.error("Digite o código do cupom.")
                else:
                    executar("""
                    INSERT OR REPLACE INTO crm_cupons(
                        codigo, descricao, tipo, valor, minimo_compra,
                        validade, ativo, observacoes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        codigo.upper().strip(), descricao, tipo, valor,
                        minimo, validade, ativo, obs,
                    ))
                    st.success("Cupom salvo.")
                    st.rerun()

        cupons = consultar("SELECT * FROM crm_cupons ORDER BY id DESC")
        if cupons.empty:
            st.info("Nenhum cupom cadastrado.")
        else:
            st.dataframe(formatar_valores_tabela(cupons), use_container_width=True, hide_index=True)

    with abas[5]:
        st.subheader("Mensagens rápidas e pós-venda")

        clientes = consultar("SELECT id, nome, whatsapp FROM clientes WHERE ativo='Sim' ORDER BY nome")

        if clientes.empty:
            st.info("Nenhum cliente cadastrado.")
        else:
            mapa = {
                f"{codigo_visual('CLI', row['id'])} - {row['nome']}": (int(row["id"]), str(row["nome"]), str(row["whatsapp"] or ""))
                for _, row in clientes.iterrows()
            }

            escolhido = st.selectbox("Cliente", list(mapa.keys()), key="msg_cliente_crm")
            tipo_msg = st.selectbox("Tipo de mensagem", ["Pós-venda", "Aniversário", "Reativação", "VIP", "Personalizada"])
            extra = st.text_area("Texto extra / personalizado")

            cliente_id, cliente_nome, whatsapp = mapa[escolhido]
            msg = gerar_mensagem_cliente(cliente_nome, tipo_msg, extra)

            if tipo_msg == "Personalizada" and extra.strip():
                msg = gerar_mensagem_cliente(cliente_nome, "Personalizada", extra)

            st.text_area("Mensagem pronta", value=msg, height=150)

            numero = "".join([c for c in whatsapp if c.isdigit()])
            if numero:
                import urllib.parse
                link = f"https://wa.me/55{numero}?text={urllib.parse.quote(msg)}" if not numero.startswith("55") else f"https://wa.me/{numero}?text={urllib.parse.quote(msg)}"
                st.link_button("Abrir WhatsApp com mensagem", link)
            else:
                st.warning("Cliente sem WhatsApp cadastrado.")

            if st.button("Registrar mensagem como interação"):
                executar("""
                INSERT INTO crm_interacoes(
                    cliente_id, cliente_nome, tipo, canal, descricao,
                    status, proximo_contato, observacoes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    cliente_id, cliente_nome, tipo_msg, "WhatsApp", msg,
                    "Registrado", "", "Mensagem gerada pelo CRM.",
                ))
                st.success("Mensagem registrada no histórico do cliente.")
                st.rerun()




# ============================================================
# MÓDULO 6 — AGENDA / ENTREGAS / TAREFAS
# ============================================================

def garantir_agenda_entregas():
    try:
        executar("""
        CREATE TABLE IF NOT EXISTS agenda_tarefas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            tipo TEXT DEFAULT 'Tarefa',
            cliente_id INTEGER,
            cliente_nome TEXT,
            referencia_tipo TEXT,
            referencia_id INTEGER,
            data TEXT,
            hora TEXT,
            prioridade TEXT DEFAULT 'Normal',
            status TEXT DEFAULT 'Pendente',
            descricao TEXT,
            observacoes TEXT,
            ativo TEXT DEFAULT 'Sim',
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
    except Exception:
        pass

    try:
        executar("""
        CREATE TABLE IF NOT EXISTS entregas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER,
            cliente_nome TEXT,
            whatsapp TEXT,
            referencia_tipo TEXT,
            referencia_id INTEGER,
            codigo TEXT,
            data_entrega TEXT,
            hora_entrega TEXT,
            tipo_entrega TEXT DEFAULT 'Retirada',
            endereco TEXT,
            taxa_entrega REAL DEFAULT 0,
            status TEXT DEFAULT 'Pendente',
            responsavel TEXT,
            observacoes TEXT,
            ativo TEXT DEFAULT 'Sim',
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
    except Exception:
        pass


def codigo_entrega(entrega_id):
    try:
        return codigo_visual("ENT", int(entrega_id))
    except Exception:
        return f"ENT-{int(entrega_id):04d}"


def codigo_tarefa(tarefa_id):
    try:
        return codigo_visual("AGE", int(tarefa_id))
    except Exception:
        return f"AGE-{int(tarefa_id):04d}"


def sincronizar_op_com_agenda():
    garantir_agenda_entregas()

    try:
        ops = consultar("""
        SELECT id, cliente_nome, whatsapp, data_entrega, prioridade, status, observacoes
        FROM ordens_producao
        WHERE ativo='Sim'
        ORDER BY id DESC
        """)
    except Exception:
        return 0, 0

    criadas_tarefas = 0
    criadas_entregas = 0

    if ops.empty:
        return 0, 0

    for _, op in ops.iterrows():
        op_id = int(op["id"])
        data_entrega = str(op.get("data_entrega", "") or "")
        cliente_nome = str(op.get("cliente_nome", "") or "")
        whatsapp = str(op.get("whatsapp", "") or "")
        prioridade = str(op.get("prioridade", "Normal") or "Normal")
        status_op = str(op.get("status", "Aguardando") or "Aguardando")

        existe_tarefa = consultar("""
        SELECT id FROM agenda_tarefas
        WHERE referencia_tipo='OP' AND referencia_id=? AND ativo='Sim'
        """, (op_id,))

        if existe_tarefa.empty:
            executar("""
            INSERT INTO agenda_tarefas(
                titulo, tipo, cliente_nome, referencia_tipo, referencia_id,
                data, hora, prioridade, status, descricao, observacoes, ativo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f"Produzir {codigo_op_seguro(op_id)} - {cliente_nome}",
                "Produção",
                cliente_nome,
                "OP",
                op_id,
                data_entrega or hoje_iso(),
                "",
                prioridade,
                "Concluída" if status_op in ["Entregue", "Finalizado"] else "Pendente",
                f"Produção vinculada à {codigo_op_seguro(op_id)}",
                str(op.get("observacoes", "") or ""),
                "Sim",
            ))
            criadas_tarefas += 1

        existe_entrega = consultar("""
        SELECT id FROM entregas
        WHERE referencia_tipo='OP' AND referencia_id=? AND ativo='Sim'
        """, (op_id,))

        if existe_entrega.empty:
            entrega_id_prev = consultar("SELECT COALESCE(MAX(id),0)+1 AS prox FROM entregas").iloc[0]["prox"]
            executar("""
            INSERT INTO entregas(
                cliente_nome, whatsapp, referencia_tipo, referencia_id, codigo,
                data_entrega, hora_entrega, tipo_entrega, endereco, taxa_entrega,
                status, responsavel, observacoes, ativo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cliente_nome,
                whatsapp,
                "OP",
                op_id,
                codigo_entrega(int(entrega_id_prev)),
                data_entrega or hoje_iso(),
                "",
                "Retirada",
                "",
                0,
                "Entregue" if status_op == "Entregue" else "Pendente",
                "",
                f"Entrega vinculada à {codigo_op_seguro(op_id)}",
                "Sim",
            ))
            criadas_entregas += 1

    return criadas_tarefas, criadas_entregas


def sincronizar_orcamentos_com_agenda():
    garantir_agenda_entregas()

    try:
        orcs = consultar("""
        SELECT id, cliente_id, cliente_nome, whatsapp, data_orcamento, status, observacoes
        FROM orcamentos
        WHERE status NOT IN ('Cancelado')
        ORDER BY id DESC
        """)
    except Exception:
        return 0

    criadas = 0

    if orcs.empty:
        return 0

    for _, o in orcs.iterrows():
        orc_id = int(o["id"])

        existe = consultar("""
        SELECT id FROM agenda_tarefas
        WHERE referencia_tipo='Orçamento' AND referencia_id=? AND tipo='Follow-up' AND ativo='Sim'
        """, (orc_id,))

        if not existe.empty:
            continue

        try:
            data_follow = (pd.to_datetime(o["data_orcamento"], errors="coerce") + pd.to_timedelta(2, unit="D")).date().isoformat()
        except Exception:
            data_follow = (datetime.now().date() + timedelta(days=2)).isoformat()

        executar("""
        INSERT INTO agenda_tarefas(
            titulo, tipo, cliente_id, cliente_nome, referencia_tipo, referencia_id,
            data, hora, prioridade, status, descricao, observacoes, ativo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            f"Follow-up orçamento ORC-{orc_id:04d} - {o['cliente_nome']}",
            "Follow-up",
            int(o["cliente_id"]) if pd.notna(o["cliente_id"]) else None,
            str(o["cliente_nome"]),
            "Orçamento",
            orc_id,
            data_follow,
            "",
            "Normal",
            "Pendente",
            "Entrar em contato para saber se o cliente vai fechar o orçamento.",
            str(o.get("observacoes", "") or ""),
            "Sim",
        ))
        criadas += 1

    return criadas


def dataframe_agenda_periodo(inicio, fim):
    garantir_agenda_entregas()

    tarefas = consultar("""
    SELECT id, titulo, tipo, cliente_nome, referencia_tipo, referencia_id,
           data, hora, prioridade, status, descricao, observacoes
    FROM agenda_tarefas
    WHERE ativo='Sim' AND data BETWEEN ? AND ?
    ORDER BY data ASC, hora ASC, id DESC
    """, (inicio, fim))

    entregas_df = consultar("""
    SELECT id, codigo, cliente_nome, whatsapp, data_entrega AS data, hora_entrega AS hora,
           tipo_entrega, endereco, taxa_entrega, status, responsavel, observacoes
    FROM entregas
    WHERE ativo='Sim' AND data_entrega BETWEEN ? AND ?
    ORDER BY data_entrega ASC, hora_entrega ASC, id DESC
    """, (inicio, fim))

    return tarefas, entregas_df


def status_agenda_visual(status):
    s = str(status)
    if s in ["Concluída", "Entregue", "Finalizado"]:
        return "🟢 " + s
    if s in ["Atrasado", "Pendente"]:
        return "🟡 " + s
    if s in ["Cancelado"]:
        return "🔴 " + s
    return "🔵 " + s


def tela_agenda_entregas():
    garantir_agenda_entregas()

    st.title("Agenda e Entregas")
    st.write("Organize produção, entregas, follow-ups, tarefas e calendário da Sophi Personalizados.")

    abas = st.tabs([
        "Hoje",
        "Calendário",
        "Tarefas",
        "Entregas",
        "Sincronizar",
    ])

    with abas[0]:
        st.subheader("Painel de hoje")

        hoje = hoje_iso()
        tarefas, entregas_df = dataframe_agenda_periodo(hoje, hoje)

        atrasadas = consultar("""
        SELECT *
        FROM agenda_tarefas
        WHERE ativo='Sim'
          AND data < ?
          AND status NOT IN ('Concluída', 'Cancelado')
        ORDER BY data ASC
        """, (hoje,))

        entregas_atrasadas = consultar("""
        SELECT *
        FROM entregas
        WHERE ativo='Sim'
          AND data_entrega < ?
          AND status NOT IN ('Entregue', 'Cancelado')
        ORDER BY data_entrega ASC
        """, (hoje,))

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            card("Tarefas hoje", str(len(tarefas)))
        with c2:
            card("Entregas hoje", str(len(entregas_df)))
        with c3:
            card("Tarefas atrasadas", str(len(atrasadas)))
        with c4:
            card("Entregas atrasadas", str(len(entregas_atrasadas)))

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### Tarefas de hoje")
            if tarefas.empty:
                st.info("Nenhuma tarefa para hoje.")
            else:
                tarefas["status_visual"] = tarefas["status"].apply(status_agenda_visual)
                st.dataframe(formatar_valores_tabela(tarefas), use_container_width=True, hide_index=True)

        with col2:
            st.markdown("### Entregas de hoje")
            if entregas_df.empty:
                st.info("Nenhuma entrega para hoje.")
            else:
                entregas_df["status_visual"] = entregas_df["status"].apply(status_agenda_visual)
                st.dataframe(formatar_valores_tabela(entregas_df), use_container_width=True, hide_index=True)

        st.divider()

        st.subheader("Pendências atrasadas")

        if atrasadas.empty and entregas_atrasadas.empty:
            st.success("Nenhuma pendência atrasada.")
        else:
            if not atrasadas.empty:
                st.markdown("#### Tarefas atrasadas")
                st.dataframe(atrasadas, use_container_width=True, hide_index=True)
            if not entregas_atrasadas.empty:
                st.markdown("#### Entregas atrasadas")
                st.dataframe(formatar_valores_tabela(entregas_atrasadas), use_container_width=True, hide_index=True)

    with abas[1]:
        st.subheader("Calendário por período")

        c1, c2 = st.columns(2)
        inicio = c1.text_input("Data inicial", value=hoje_iso())
        fim = c2.text_input("Data final", value=(datetime.now().date() + timedelta(days=7)).isoformat())

        tarefas, entregas_df = dataframe_agenda_periodo(inicio, fim)

        st.markdown("### Tarefas no período")
        if tarefas.empty:
            st.info("Nenhuma tarefa no período.")
        else:
            tarefas["codigo"] = tarefas["id"].apply(codigo_tarefa)
            st.dataframe(formatar_valores_tabela(tarefas), use_container_width=True, hide_index=True)

        st.markdown("### Entregas no período")
        if entregas_df.empty:
            st.info("Nenhuma entrega no período.")
        else:
            st.dataframe(formatar_valores_tabela(entregas_df), use_container_width=True, hide_index=True)

        st.markdown("### Visão diária")
        partes = []
        if not tarefas.empty:
            t = tarefas.copy()
            t["origem"] = "Tarefa"
            t["titulo_resumo"] = t["titulo"]
            partes.append(t[["data", "origem", "titulo_resumo", "cliente_nome", "status"]])
        if not entregas_df.empty:
            e = entregas_df.copy()
            e["origem"] = "Entrega"
            e["titulo_resumo"] = e["tipo_entrega"] + " - " + e["cliente_nome"].astype(str)
            partes.append(e[["data", "origem", "titulo_resumo", "cliente_nome", "status"]])

        if partes:
            agenda = pd.concat(partes, ignore_index=True)
            agenda = agenda.sort_values("data")
            for data_ag, grupo in agenda.groupby("data"):
                st.markdown(f"#### {data_ag}")
                for _, r in grupo.iterrows():
                    st.write(f"• **{r['origem']}** — {r['titulo_resumo']} — {r['cliente_nome']} — {r['status']}")

    with abas[2]:
        st.subheader("Criar tarefa")

        clientes = consultar("SELECT id, nome FROM clientes WHERE ativo='Sim' ORDER BY nome")
        cliente_opcoes = ["Sem cliente"]
        cliente_mapa = {"Sem cliente": (None, "")}

        if not clientes.empty:
            for _, c in clientes.iterrows():
                label = f"{codigo_visual('CLI', c['id'])} - {c['nome']}"
                cliente_opcoes.append(label)
                cliente_mapa[label] = (int(c["id"]), str(c["nome"]))

        with st.form("form_tarefa_agenda"):
            c1, c2 = st.columns(2)
            titulo = c1.text_input("Título da tarefa")
            tipo = c2.selectbox("Tipo", ["Tarefa", "Produção", "Entrega", "Follow-up", "Compra", "Cliente", "Outro"])

            cliente_sel = st.selectbox("Cliente", cliente_opcoes)

            c3, c4, c5 = st.columns(3)
            data = c3.text_input("Data", value=hoje_iso())
            hora = c4.text_input("Hora", placeholder="Ex: 14:30")
            prioridade = c5.selectbox("Prioridade", ["Normal", "Urgente", "Baixa"])

            status = st.selectbox("Status", ["Pendente", "Em andamento", "Concluída", "Cancelado"])
            descricao = st.text_area("Descrição")
            observacoes = st.text_area("Observações")

            if st.form_submit_button("Salvar tarefa"):
                if not titulo.strip():
                    st.error("Digite o título da tarefa.")
                else:
                    cliente_id, cliente_nome = cliente_mapa[cliente_sel]
                    executar("""
                    INSERT INTO agenda_tarefas(
                        titulo, tipo, cliente_id, cliente_nome, data, hora,
                        prioridade, status, descricao, observacoes, ativo
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        titulo, tipo, cliente_id, cliente_nome, data, hora,
                        prioridade, status, descricao, observacoes, "Sim",
                    ))
                    st.success("Tarefa salva.")
                    st.rerun()

        st.divider()
        st.subheader("Tarefas cadastradas")

        df = consultar("""
        SELECT *
        FROM agenda_tarefas
        WHERE ativo='Sim'
        ORDER BY data ASC, hora ASC, id DESC
        """)

        if df.empty:
            st.info("Nenhuma tarefa cadastrada.")
        else:
            df["codigo"] = df["id"].apply(codigo_tarefa)
            edited = st.data_editor(
                df,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="editor_agenda_tarefas",
                column_config={
                    "status": st.column_config.SelectboxColumn("Status", options=["Pendente", "Em andamento", "Concluída", "Cancelado"]),
                    "prioridade": st.column_config.SelectboxColumn("Prioridade", options=["Urgente", "Normal", "Baixa"]),
                    "tipo": st.column_config.SelectboxColumn("Tipo", options=["Tarefa", "Produção", "Entrega", "Follow-up", "Compra", "Cliente", "Outro"]),
                },
            )

            c1, c2 = st.columns([2, 1])
            with c1:
                if st.button("Salvar alterações das tarefas"):
                    for _, r in edited.iterrows():
                        if str(r.get("titulo", "")).strip():
                            executar("""
                            UPDATE agenda_tarefas
                            SET titulo=?, tipo=?, cliente_nome=?, data=?, hora=?,
                                prioridade=?, status=?, descricao=?, observacoes=?
                            WHERE id=?
                            """, (
                                str(r.get("titulo", "")),
                                str(r.get("tipo", "")),
                                str(r.get("cliente_nome", "")),
                                str(r.get("data", "")),
                                str(r.get("hora", "")),
                                str(r.get("prioridade", "Normal")),
                                str(r.get("status", "Pendente")),
                                str(r.get("descricao", "")),
                                str(r.get("observacoes", "")),
                                int(r["id"]),
                            ))
                    st.success("Tarefas atualizadas.")
                    st.rerun()

            with c2:
                id_del = st.number_input("ID para excluir tarefa", min_value=0, step=1, key="del_tarefa")
                if st.button("Excluir tarefa"):
                    if id_del > 0:
                        executar("UPDATE agenda_tarefas SET ativo='Não' WHERE id=?", (int(id_del),))
                        st.success("Tarefa excluída.")
                        st.rerun()

    with abas[3]:
        st.subheader("Criar entrega")

        clientes = consultar("SELECT id, nome, whatsapp, endereco FROM clientes WHERE ativo='Sim' ORDER BY nome")
        cliente_opcoes = ["Sem cliente"]
        cliente_mapa = {"Sem cliente": (None, "", "", "")}

        if not clientes.empty:
            for _, c in clientes.iterrows():
                label = f"{codigo_visual('CLI', c['id'])} - {c['nome']}"
                cliente_opcoes.append(label)
                cliente_mapa[label] = (int(c["id"]), str(c["nome"]), str(c["whatsapp"] or ""), str(c["endereco"] or ""))

        with st.form("form_entrega_agenda"):
            cliente_sel = st.selectbox("Cliente", cliente_opcoes, key="entrega_cliente")
            cliente_id, cliente_nome, whatsapp, endereco_padrao = cliente_mapa[cliente_sel]

            c1, c2, c3 = st.columns(3)
            data_entrega = c1.text_input("Data entrega", value=hoje_iso())
            hora_entrega = c2.text_input("Hora entrega", placeholder="Ex: 16:00")
            tipo_entrega = c3.selectbox("Tipo de entrega", ["Retirada", "Motoboy", "Correios", "Uber/99", "Entrega própria", "Outro"])

            endereco = st.text_area("Endereço", value=endereco_padrao)
            c4, c5, c6 = st.columns(3)
            taxa = c4.number_input("Taxa entrega", min_value=0.0, step=0.01, format="%.2f")
            status = c5.selectbox("Status", ["Pendente", "Separado", "Saiu para entrega", "Entregue", "Cancelado"])
            responsavel = c6.text_input("Responsável")

            obs = st.text_area("Observações da entrega")

            if st.form_submit_button("Salvar entrega"):
                entrega_id_prev = consultar("SELECT COALESCE(MAX(id),0)+1 AS prox FROM entregas").iloc[0]["prox"]
                executar("""
                INSERT INTO entregas(
                    cliente_id, cliente_nome, whatsapp, referencia_tipo, referencia_id,
                    codigo, data_entrega, hora_entrega, tipo_entrega, endereco,
                    taxa_entrega, status, responsavel, observacoes, ativo
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    cliente_id, cliente_nome, whatsapp, "Manual", None,
                    codigo_entrega(int(entrega_id_prev)),
                    data_entrega, hora_entrega, tipo_entrega, endereco,
                    taxa, status, responsavel, obs, "Sim",
                ))
                st.success("Entrega salva.")
                st.rerun()

        st.divider()
        st.subheader("Entregas cadastradas")

        df = consultar("""
        SELECT *
        FROM entregas
        WHERE ativo='Sim'
        ORDER BY data_entrega ASC, hora_entrega ASC, id DESC
        """)

        if df.empty:
            st.info("Nenhuma entrega cadastrada.")
        else:
            edited = st.data_editor(
                df,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="editor_entregas",
                column_config={
                    "taxa_entrega": st.column_config.NumberColumn("Taxa", format="R$ %.2f"),
                    "status": st.column_config.SelectboxColumn("Status", options=["Pendente", "Separado", "Saiu para entrega", "Entregue", "Cancelado"]),
                    "tipo_entrega": st.column_config.SelectboxColumn("Tipo", options=["Retirada", "Motoboy", "Correios", "Uber/99", "Entrega própria", "Outro"]),
                },
            )

            c1, c2 = st.columns([2, 1])
            with c1:
                if st.button("Salvar alterações das entregas"):
                    for _, r in edited.iterrows():
                        if str(r.get("cliente_nome", "")).strip():
                            executar("""
                            UPDATE entregas
                            SET cliente_nome=?, whatsapp=?, data_entrega=?, hora_entrega=?,
                                tipo_entrega=?, endereco=?, taxa_entrega=?, status=?,
                                responsavel=?, observacoes=?
                            WHERE id=?
                            """, (
                                str(r.get("cliente_nome", "")),
                                str(r.get("whatsapp", "")),
                                str(r.get("data_entrega", "")),
                                str(r.get("hora_entrega", "")),
                                str(r.get("tipo_entrega", "")),
                                str(r.get("endereco", "")),
                                n(r.get("taxa_entrega", 0)),
                                str(r.get("status", "Pendente")),
                                str(r.get("responsavel", "")),
                                str(r.get("observacoes", "")),
                                int(r["id"]),
                            ))
                    st.success("Entregas atualizadas.")
                    st.rerun()

            with c2:
                id_del = st.number_input("ID para excluir entrega", min_value=0, step=1, key="del_entrega")
                if st.button("Excluir entrega"):
                    if id_del > 0:
                        executar("UPDATE entregas SET ativo='Não' WHERE id=?", (int(id_del),))
                        st.success("Entrega excluída.")
                        st.rerun()

        st.subheader("Mensagem rápida de entrega")

        if not df.empty:
            mapa_ent = {
                f"{row['codigo']} - {row['cliente_nome']} - {row['status']}": int(row["id"])
                for _, row in df.iterrows()
            }
            escolha = st.selectbox("Escolha entrega para mensagem", list(mapa_ent.keys()))
            ent_id = mapa_ent[escolha]
            ent = consultar("SELECT * FROM entregas WHERE id=?", (int(ent_id),))

            if not ent.empty:
                e = ent.iloc[0]
                msg = f"Olá {e['cliente_nome']}, sua encomenda da Sophi Personalizados está com status: {e['status']}. Data prevista: {e['data_entrega']}."
                st.text_area("Mensagem", value=msg, height=110)
                numero = "".join([c for c in str(e["whatsapp"]) if c.isdigit()])
                if numero:
                    import urllib.parse
                    link = f"https://wa.me/55{numero}?text={urllib.parse.quote(msg)}" if not numero.startswith("55") else f"https://wa.me/{numero}?text={urllib.parse.quote(msg)}"
                    st.link_button("Abrir WhatsApp", link)

    with abas[4]:
        st.subheader("Sincronizar agenda automaticamente")

        st.write("Crie tarefas e entregas automaticamente com base nas Ordens de Produção e Orçamentos.")

        c1, c2 = st.columns(2)

        with c1:
            if st.button("Sincronizar OPs com Agenda/Entregas"):
                tarefas, entregas_novas = sincronizar_op_com_agenda()
                st.success(f"{tarefas} tarefa(s) e {entregas_novas} entrega(s) criadas.")
                st.rerun()

        with c2:
            if st.button("Criar follow-ups dos orçamentos"):
                qtd = sincronizar_orcamentos_com_agenda()
                st.success(f"{qtd} follow-up(s) criado(s).")
                st.rerun()

        st.info("Essa sincronização não duplica registros que já existem.")




# ============================================================
# MÓDULO 7 — RELATÓRIOS INTELIGENTES / BI
# ============================================================

def periodo_relatorio_bi():
    anos = list(range(2026, 2031))
    meses = [
        "Ano inteiro", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ]

    c1, c2 = st.columns(2)
    ano = c1.selectbox("Ano do relatório", anos, index=0, key="bi_ano")
    mes = c2.selectbox("Mês", meses, key="bi_mes")

    try:
        return periodo_datas_financeiro(ano, mes)
    except Exception:
        if mes == "Ano inteiro":
            return date(int(ano), 1, 1).isoformat(), date(int(ano), 12, 31).isoformat()

        mapa = {
            "Janeiro": 1, "Fevereiro": 2, "Março": 3, "Abril": 4,
            "Maio": 5, "Junho": 6, "Julho": 7, "Agosto": 8,
            "Setembro": 9, "Outubro": 10, "Novembro": 11, "Dezembro": 12,
        }

        m = mapa.get(mes, datetime.now().month)
        inicio = date(int(ano), m, 1)
        fim = date(int(ano) + 1, 1, 1) - timedelta(days=1) if m == 12 else date(int(ano), m + 1, 1) - timedelta(days=1)
        return inicio.isoformat(), fim.isoformat()


def bi_orcamentos_periodo(inicio, fim):
    try:
        return consultar("""
        SELECT *
        FROM orcamentos
        WHERE date(data_orcamento) BETWEEN ? AND ?
        ORDER BY data_orcamento DESC
        """, (inicio, fim))
    except Exception:
        return pd.DataFrame()


def bi_itens_periodo(inicio, fim):
    try:
        return consultar("""
        SELECT
            oi.produto,
            oi.categoria,
            oi.quantidade,
            oi.valor_unitario,
            oi.desconto,
            oi.total,
            o.data_orcamento,
            o.status,
            o.cliente_nome
        FROM orcamento_itens oi
        LEFT JOIN orcamentos o ON o.id = oi.orcamento_id
        WHERE date(o.data_orcamento) BETWEEN ? AND ?
        """, (inicio, fim))
    except Exception:
        return pd.DataFrame()


def bi_produtos_lucro(inicio, fim):
    itens = bi_itens_periodo(inicio, fim)

    if itens.empty:
        return pd.DataFrame()

    try:
        produtos = consultar_produtos_catalogo_seguro()
    except Exception:
        produtos = pd.DataFrame()

    df = itens.copy()

    if not produtos.empty:
        df = df.merge(produtos, left_on="produto", right_on="nome", how="left", suffixes=("", "_prod"))
    else:
        df["custo_unitario"] = 0

    df["custo_unitario"] = df["custo_unitario"].fillna(0)
    df["custo_total_estimado"] = df["quantidade"].fillna(0) * df["custo_unitario"].fillna(0)
    df["lucro_estimado"] = df["total"].fillna(0) - df["custo_total_estimado"]
    df["margem_estimada"] = df.apply(lambda r: (n(r["lucro_estimado"]) / n(r["total"]) * 100) if n(r["total"]) > 0 else 0, axis=1)

    resumo = df.groupby(["produto", "categoria"]).agg(
        quantidade=("quantidade", "sum"),
        faturamento=("total", "sum"),
        custo_estimado=("custo_total_estimado", "sum"),
        lucro_estimado=("lucro_estimado", "sum"),
    ).reset_index()

    resumo["margem_estimada"] = resumo.apply(
        lambda r: (n(r["lucro_estimado"]) / n(r["faturamento"]) * 100) if n(r["faturamento"]) > 0 else 0,
        axis=1
    )

    return resumo.sort_values("faturamento", ascending=False)


def bi_clientes_ranking(inicio, fim):
    try:
        df = consultar("""
        SELECT
            cliente_id,
            cliente_nome,
            COUNT(id) AS qtd_orcamentos,
            SUM(total) AS total_gasto,
            MAX(data_orcamento) AS ultima_compra
        FROM orcamentos
        WHERE date(data_orcamento) BETWEEN ? AND ?
          AND status NOT IN ('Cancelado')
        GROUP BY cliente_id, cliente_nome
        ORDER BY total_gasto DESC
        """, (inicio, fim))
        if df.empty:
            return df
        df["ticket_medio"] = df.apply(lambda r: n(r["total_gasto"]) / max(n(r["qtd_orcamentos"], 1), 1), axis=1)
        return df
    except Exception:
        return pd.DataFrame()


def bi_producao_periodo(inicio, fim):
    try:
        return consultar("""
        SELECT *
        FROM ordens_producao
        WHERE date(data_criacao) BETWEEN ? AND ?
        ORDER BY id DESC
        """, (inicio, fim))
    except Exception:
        return pd.DataFrame()


def bi_estoque_consumo_periodo(inicio, fim):
    try:
        return consultar("""
        SELECT item_nome, categoria, SUM(quantidade) AS quantidade_total
        FROM estoque_consumo
        WHERE date(data) BETWEEN ? AND ?
        GROUP BY item_nome, categoria
        ORDER BY quantidade_total DESC
        """, (inicio, fim))
    except Exception:
        return pd.DataFrame()


def bi_html_relatorio_completo(inicio, fim, dados):
    empresa = obter_config("nome_empresa", EMPRESA)

    def linhas_tabela(df, cols):
        if df is None or df.empty:
            return "<tr><td colspan='10'>Sem dados.</td></tr>"
        linhas = ""
        for _, r in df.head(30).iterrows():
            linhas += "<tr>"
            for c in cols:
                val = r.get(c, "")
                if isinstance(val, (int, float)):
                    if any(p in c.lower() for p in ["valor", "total", "faturamento", "lucro", "custo", "gasto", "ticket"]):
                        val = real(val)
                    else:
                        val = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                linhas += f"<td>{val}</td>"
            linhas += "</tr>"
        return linhas

    prod = dados.get("produtos", pd.DataFrame())
    cli = dados.get("clientes", pd.DataFrame())
    consumo = dados.get("consumo", pd.DataFrame())

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Relatório BI - {empresa}</title>
<style>
body {{ font-family: Arial, sans-serif; color:#111; padding:24px; }}
.header {{ border-bottom:3px solid #111; padding-bottom:14px; margin-bottom:18px; }}
h1 {{ margin:0; font-size:30px; }}
.grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:18px 0; }}
.card {{ border:1px solid #ddd; border-radius:12px; padding:12px; }}
.label {{ color:#777; font-size:11px; text-transform:uppercase; }}
.value {{ font-size:22px; font-weight:900; }}
table {{ width:100%; border-collapse:collapse; margin:12px 0 24px; font-size:12px; }}
th {{ background:#000; color:#fff; padding:8px; text-align:left; }}
td {{ border-bottom:1px solid #eee; padding:7px; }}
button {{ position:fixed; right:18px; top:18px; background:#111; color:#fff; border:0; border-radius:8px; padding:10px 16px; font-weight:800; }}
@media print {{ button {{ display:none; }} }}
</style>
</head>
<body>
<button onclick="window.print()">Imprimir / salvar PDF</button>

<div class="header">
<h1>{empresa}</h1>
<p>Relatório Inteligente / BI — {inicio} até {fim}</p>
</div>

<div class="grid">
<div class="card"><div class="label">Faturamento</div><div class="value">{real(dados.get('faturamento',0))}</div></div>
<div class="card"><div class="label">Lucro estimado</div><div class="value">{real(dados.get('lucro',0))}</div></div>
<div class="card"><div class="label">Pedidos</div><div class="value">{dados.get('pedidos',0)}</div></div>
<div class="card"><div class="label">Ticket médio</div><div class="value">{real(dados.get('ticket',0))}</div></div>
</div>

<h2>Produtos mais vendidos / lucrativos</h2>
<table>
<tr><th>Produto</th><th>Categoria</th><th>Qtd</th><th>Faturamento</th><th>Custo</th><th>Lucro</th><th>Margem</th></tr>
{linhas_tabela(prod, ['produto','categoria','quantidade','faturamento','custo_estimado','lucro_estimado','margem_estimada'])}
</table>

<h2>Clientes que mais compraram</h2>
<table>
<tr><th>Cliente</th><th>Pedidos</th><th>Total gasto</th><th>Ticket médio</th><th>Última compra</th></tr>
{linhas_tabela(cli, ['cliente_nome','qtd_orcamentos','total_gasto','ticket_medio','ultima_compra'])}
</table>

<h2>Materiais mais consumidos</h2>
<table>
<tr><th>Item</th><th>Categoria</th><th>Quantidade</th></tr>
{linhas_tabela(consumo, ['item_nome','categoria','quantidade_total'])}
</table>

</body>
</html>"""
    return html


def tela_relatorios_inteligentes():
    st.title("Relatórios Inteligentes")
    st.write("BI da Sophi Personalizados: vendas, lucro, produtos, clientes, produção, estoque e exportação.")

    inicio, fim = periodo_relatorio_bi()

    abas = st.tabs([
        "Visão geral",
        "Produtos",
        "Clientes",
        "Produção",
        "Estoque",
        "Exportar",
    ])

    orcs = bi_orcamentos_periodo(inicio, fim)
    itens = bi_itens_periodo(inicio, fim)
    produtos_lucro = bi_produtos_lucro(inicio, fim)
    clientes_rank = bi_clientes_ranking(inicio, fim)
    producao = bi_producao_periodo(inicio, fim)
    consumo = bi_estoque_consumo_periodo(inicio, fim)

    faturamento = float(orcs["total"].fillna(0).sum()) if not orcs.empty else 0.0
    pedidos = len(orcs) if not orcs.empty else 0
    ticket = faturamento / pedidos if pedidos else 0
    lucro_estimado = float(produtos_lucro["lucro_estimado"].fillna(0).sum()) if not produtos_lucro.empty else 0.0
    margem_geral = lucro_estimado / faturamento * 100 if faturamento else 0

    with abas[0]:
        st.subheader("Visão geral do período")

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            card("Faturamento", real(faturamento))
        with c2:
            card("Lucro estimado", real(lucro_estimado))
        with c3:
            card("Margem estimada", f"{margem_geral:.2f}%")
        with c4:
            card("Pedidos", str(pedidos))
        with c5:
            card("Ticket médio", real(ticket))

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Vendas por status")
            if orcs.empty:
                st.info("Sem vendas no período.")
            else:
                status_df = orcs.groupby("status")["total"].sum().reset_index()
                st.dataframe(formatar_valores_tabela(status_df), use_container_width=True, hide_index=True)
                st.bar_chart(status_df.set_index("status"))

        with col2:
            st.subheader("Vendas por forma de pagamento")
            if orcs.empty:
                st.info("Sem vendas no período.")
            else:
                pag_df = orcs.groupby("forma_pagamento")["total"].sum().reset_index()
                st.dataframe(formatar_valores_tabela(pag_df), use_container_width=True, hide_index=True)
                st.bar_chart(pag_df.set_index("forma_pagamento"))

        st.divider()

        st.subheader("Evolução diária de faturamento")
        if orcs.empty:
            st.info("Sem dados para gráfico diário.")
        else:
            temp = orcs.copy()
            temp["data"] = pd.to_datetime(temp["data_orcamento"], errors="coerce").dt.date
            diario = temp.groupby("data")["total"].sum().reset_index()
            st.line_chart(diario.set_index("data"))

    with abas[1]:
        st.subheader("Produtos mais vendidos e mais lucrativos")

        if produtos_lucro.empty:
            st.info("Sem produtos vendidos no período.")
        else:
            st.markdown("### Ranking por faturamento")
            st.dataframe(formatar_valores_tabela(produtos_lucro), use_container_width=True, hide_index=True)

            top_fat = produtos_lucro.sort_values("faturamento", ascending=False).head(10)
            st.bar_chart(top_fat.set_index("produto")["faturamento"])

            st.markdown("### Ranking por lucro estimado")
            top_lucro = produtos_lucro.sort_values("lucro_estimado", ascending=False).head(10)
            st.dataframe(formatar_valores_tabela(top_lucro), use_container_width=True, hide_index=True)
            st.bar_chart(top_lucro.set_index("produto")["lucro_estimado"])

            st.markdown("### Produtos com margem baixa")
            baixa = produtos_lucro[produtos_lucro["margem_estimada"] < 30].copy()
            if baixa.empty:
                st.success("Nenhum produto com margem abaixo de 30%.")
            else:
                st.warning("Atenção: produtos com margem abaixo de 30%.")
                st.dataframe(formatar_valores_tabela(baixa), use_container_width=True, hide_index=True)

    with abas[2]:
        st.subheader("Clientes e relacionamento")

        if clientes_rank.empty:
            st.info("Sem clientes com compras no período.")
        else:
            st.markdown("### Clientes que mais compraram")
            st.dataframe(formatar_valores_tabela(clientes_rank), use_container_width=True, hide_index=True)
            st.bar_chart(clientes_rank.head(10).set_index("cliente_nome")["total_gasto"])

            st.markdown("### Clientes com ticket alto")
            alto = clientes_rank.sort_values("ticket_medio", ascending=False).head(15)
            st.dataframe(formatar_valores_tabela(alto), use_container_width=True, hide_index=True)

    with abas[3]:
        st.subheader("Produção")

        if producao.empty:
            st.info("Sem OPs no período.")
        else:
            producao["codigo_visual"] = producao["id"].apply(codigo_op_seguro)
            c1, c2, c3 = st.columns(3)
            with c1:
                card("OPs criadas", str(len(producao)))
            with c2:
                card("Entregues", str(len(producao[producao["status"] == "Entregue"])))
            with c3:
                card("Em aberto", str(len(producao[~producao["status"].isin(["Entregue", "Cancelado"])])))

            status_prod = producao.groupby("status")["id"].count().reset_index()
            status_prod.columns = ["Status", "Quantidade"]
            st.dataframe(status_prod, use_container_width=True, hide_index=True)
            st.bar_chart(status_prod.set_index("Status"))

            st.markdown("### OPs do período")
            st.dataframe(producao, use_container_width=True, hide_index=True)

    with abas[4]:
        st.subheader("Estoque e consumo")

        if consumo.empty:
            st.info("Sem consumo de materiais no período.")
        else:
            st.markdown("### Materiais mais consumidos")
            st.dataframe(formatar_valores_tabela(consumo), use_container_width=True, hide_index=True)
            st.bar_chart(consumo.head(15).set_index("item_nome")["quantidade_total"])

        try:
            resumo = resumo_estoque_inteligente()
        except Exception:
            resumo = pd.DataFrame()

        st.markdown("### Situação atual do estoque")
        if resumo.empty:
            st.info("Sem resumo de estoque.")
        else:
            criticos = resumo[resumo["status"].astype(str).str.contains("Crítico|Atenção", na=False)]
            if criticos.empty:
                st.success("Nenhum item crítico ou em atenção.")
            else:
                st.warning("Itens que precisam de atenção:")
                st.dataframe(formatar_valores_tabela(criticos), use_container_width=True, hide_index=True)

    with abas[5]:
        st.subheader("Exportar relatório completo")

        dados = {
            "faturamento": faturamento,
            "lucro": lucro_estimado,
            "pedidos": pedidos,
            "ticket": ticket,
            "produtos": produtos_lucro,
            "clientes": clientes_rank,
            "consumo": consumo,
        }

        html = bi_html_relatorio_completo(inicio, fim, dados)

        st.download_button(
            "Baixar relatório BI em HTML/PDF",
            data=html.encode("utf-8"),
            file_name=f"relatorio_bi_{inicio}_a_{fim}.html",
            mime="text/html",
        )

        if not produtos_lucro.empty:
            st.download_button(
                "Baixar produtos em CSV",
                data=produtos_lucro.to_csv(index=False).encode("utf-8"),
                file_name=f"bi_produtos_{inicio}_a_{fim}.csv",
                mime="text/csv",
            )

        if not clientes_rank.empty:
            st.download_button(
                "Baixar clientes em CSV",
                data=clientes_rank.to_csv(index=False).encode("utf-8"),
                file_name=f"bi_clientes_{inicio}_a_{fim}.csv",
                mime="text/csv",
            )

        if not consumo.empty:
            st.download_button(
                "Baixar consumo em CSV",
                data=consumo.to_csv(index=False).encode("utf-8"),
                file_name=f"bi_consumo_{inicio}_a_{fim}.csv",
                mime="text/csv",
            )




# ============================================================
# MÓDULO 8 — PORTAL DO CLIENTE
# ============================================================

def garantir_portal_cliente():
    executar("""
    CREATE TABLE IF NOT EXISTS portal_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT,
        referencia_id INTEGER,
        token TEXT UNIQUE,
        ativo TEXT DEFAULT 'Sim',
        data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
        validade TEXT,
        acessos INTEGER DEFAULT 0,
        ultimo_acesso TEXT
    )
    """)
    executar("""
    CREATE TABLE IF NOT EXISTS portal_mensagens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT,
        cliente_nome TEXT,
        data TEXT DEFAULT CURRENT_TIMESTAMP,
        mensagem TEXT,
        status TEXT DEFAULT 'Nova'
    )
    """)


def gerar_token_portal(tipo, referencia_id):
    garantir_portal_cliente()
    import secrets

    existente = consultar("""
    SELECT token FROM portal_tokens
    WHERE tipo=? AND referencia_id=? AND ativo='Sim'
    ORDER BY id DESC LIMIT 1
    """, (str(tipo), int(referencia_id)))

    if not existente.empty:
        return str(existente.iloc[0]["token"])

    token = secrets.token_urlsafe(12)
    validade = (datetime.now().date() + timedelta(days=30)).isoformat()

    executar("""
    INSERT INTO portal_tokens(tipo, referencia_id, token, ativo, validade)
    VALUES (?, ?, ?, 'Sim', ?)
    """, (str(tipo), int(referencia_id), token, validade))

    return token


def tela_portal_cliente_publico():
    aplicar_visual_publico_limpo()
    garantir_portal_cliente()

    try:
        token = st.query_params.get("token", "")
    except Exception:
        token = ""

    st.title("Portal do Cliente")
    st.write("Acompanhe seu pedido da Sophi Personalizados.")

    if not token:
        st.error("Link inválido.")
        st.stop()

    token_df = consultar("""
    SELECT * FROM portal_tokens
    WHERE token=? AND ativo='Sim'
    LIMIT 1
    """, (str(token),))

    if token_df.empty:
        st.error("Link inválido ou expirado.")
        st.stop()

    try:
        executar("""
        UPDATE portal_tokens
        SET acessos=COALESCE(acessos,0)+1, ultimo_acesso=CURRENT_TIMESTAMP
        WHERE token=?
        """, (str(token),))
    except Exception:
        pass

    t = token_df.iloc[0]
    ref_id = int(t["referencia_id"])
    tipo = str(t["tipo"])

    if tipo == "Orçamento":
        orc = consultar("SELECT * FROM orcamentos WHERE id=?", (ref_id,))
    else:
        op = consultar("SELECT * FROM ordens_producao WHERE id=?", (ref_id,))
        if op.empty:
            orc = pd.DataFrame()
        else:
            orc_id = op.iloc[0].get("orcamento_id", None)
            orc = consultar("SELECT * FROM orcamentos WHERE id=?", (int(orc_id),)) if pd.notna(orc_id) else pd.DataFrame()

    if orc.empty:
        st.warning("Pedido não encontrado.")
        st.stop()

    o = orc.iloc[0]

    st.subheader(f"Olá, {o.get('cliente_nome', 'cliente')} 🤍")

    c1, c2, c3 = st.columns(3)
    with c1:
        card("Status", str(o.get("status", "")))
    with c2:
        card("Total", real(o.get("total", 0)))
    with c3:
        card("Orçamento", codigo_visual("ORC", o.get("id", 0), ano=datetime.now().year))

    itens = consultar("""
    SELECT produto, categoria, quantidade, valor_unitario, desconto, total
    FROM orcamento_itens
    WHERE orcamento_id=?
    """, (int(o["id"]),))

    st.subheader("Itens do pedido")
    if itens.empty:
        st.info("Nenhum item encontrado.")
    else:
        st.dataframe(formatar_valores_tabela(itens), use_container_width=True, hide_index=True)

    st.subheader("Produção")
    try:
        op = consultar("""
        SELECT * FROM ordens_producao
        WHERE orcamento_id=? AND ativo='Sim'
        ORDER BY id DESC LIMIT 1
        """, (int(o["id"]),))
    except Exception:
        op = pd.DataFrame()

    if op.empty:
        st.info("Produção ainda não iniciada.")
    else:
        opr = op.iloc[0]
        st.write(f"**OP:** {codigo_op_seguro(opr['id'])}")
        st.write(f"**Status:** {opr.get('status', '-')}")
        st.write(f"**Previsão:** {opr.get('data_entrega', '-')}")
        try:
            checklist = json.loads(opr.get("checklist_json", "{}") or "{}")
            for nome, feito in checklist.items():
                st.write(("✅ " if feito else "⬜ ") + nome)
        except Exception:
            pass

    st.subheader("Entrega")
    try:
        entrega = consultar("""
        SELECT * FROM entregas
        WHERE referencia_tipo='OP'
          AND referencia_id IN (SELECT id FROM ordens_producao WHERE orcamento_id=?)
          AND ativo='Sim'
        ORDER BY id DESC LIMIT 1
        """, (int(o["id"]),))
    except Exception:
        entrega = pd.DataFrame()

    if entrega.empty:
        st.info("Entrega ainda não cadastrada.")
    else:
        e = entrega.iloc[0]
        st.write(f"**Código:** {e.get('codigo', '-')}")
        st.write(f"**Status:** {e.get('status', '-')}")
        st.write(f"**Data:** {e.get('data_entrega', '-')}")
        st.write(f"**Tipo:** {e.get('tipo_entrega', '-')}")

    st.subheader("Falar com a Sophi")
    whatsapp = obter_config("whatsapp", "")
    if whatsapp:
        import urllib.parse
        numero = "".join([c for c in whatsapp if c.isdigit()])
        msg = f"Olá, estou acompanhando meu pedido pelo portal."
        link = f"https://wa.me/55{numero}?text={urllib.parse.quote(msg)}" if numero and not numero.startswith("55") else f"https://wa.me/{numero}?text={urllib.parse.quote(msg)}"
        st.link_button("Chamar no WhatsApp", link)


def tela_portal_cliente_admin():
    garantir_portal_cliente()

    st.title("Portal do Cliente")
    st.write("Gere links para o cliente acompanhar orçamento, produção e entrega.")

    abas = st.tabs(["Gerar link", "Links gerados"])

    with abas[0]:
        orcs = consultar("""
        SELECT id, cliente_nome, whatsapp, status, total
        FROM orcamentos
        ORDER BY id DESC
        LIMIT 500
        """)

        if orcs.empty:
            st.info("Nenhum orçamento encontrado.")
        else:
            mapa = {
                f"{codigo_visual('ORC', r['id'], ano=datetime.now().year)} | {r['cliente_nome']} | {real(r['total'])} | {r['status']}": int(r["id"])
                for _, r in orcs.iterrows()
            }
            esc = st.selectbox("Escolha o orçamento", list(mapa.keys()))
            orc_id = mapa[esc]
            o = orcs[orcs["id"] == orc_id].iloc[0]
            codigo = codigo_visual("ORC", int(orc_id), ano=datetime.now().year)

            base_url = st.text_input("Link principal do seu app", value=obter_app_url_padrao())
            if st.button("Gerar link do portal", use_container_width=True):
                link = gerar_link_portal_orcamento(int(orc_id), base_url)
                st.session_state["portal_link_gerado"] = link
                st.session_state["portal_orc_id_gerado"] = int(orc_id)
                st.success("Link gerado.")

            link = st.session_state.get("portal_link_gerado", "")
            if link and st.session_state.get("portal_orc_id_gerado") == int(orc_id):
                st.code(link)
                msg = mensagem_portal_cliente(o["cliente_nome"], codigo, str(o["status"]), real(o["total"]), link)
                msg_final = st.text_area("Mensagem pronta para WhatsApp", value=msg, height=180, key=f"msg_portal_{orc_id}")
                link_wpp = link_whatsapp(o["whatsapp"], msg_final)
                if link_wpp:
                    st.link_button("Enviar portal no WhatsApp", link_wpp, use_container_width=True)
                else:
                    st.warning("Este orçamento não tem WhatsApp cadastrado.")
                st.link_button("Abrir portal do cliente", link, use_container_width=True)

    with abas[1]:
        try:
            toks = consultar("SELECT * FROM portal_tokens ORDER BY id DESC LIMIT 500")
        except Exception:
            toks = pd.DataFrame()
        if toks.empty:
            st.info("Nenhum link gerado.")
        else:
            st.dataframe(formatar_valores_tabela(toks), use_container_width=True, hide_index=True)

# ============================================================
# MÓDULO 9 — CENTRAL DE AUTOMAÇÃO / ALERTAS INTELIGENTES
# ============================================================

def garantir_automacoes_erp():
    try:
        executar("""
        CREATE TABLE IF NOT EXISTS automacoes_erp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            tipo TEXT DEFAULT 'Alerta',
            regra TEXT,
            canal TEXT DEFAULT 'ERP',
            mensagem TEXT,
            ativo TEXT DEFAULT 'Sim',
            ultima_execucao TEXT,
            observacoes TEXT
        )
        """)
    except Exception:
        pass

    try:
        executar("""
        CREATE TABLE IF NOT EXISTS alertas_erp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT DEFAULT CURRENT_TIMESTAMP,
            tipo TEXT,
            origem TEXT,
            referencia_id INTEGER,
            titulo TEXT,
            mensagem TEXT,
            prioridade TEXT DEFAULT 'Normal',
            status TEXT DEFAULT 'Novo',
            acao_sugerida TEXT,
            link_interno TEXT
        )
        """)
    except Exception:
        pass

    automacoes_padrao = [
        ("Estoque baixo", "Alerta", "estoque_baixo", "ERP", "Avisar quando itens estiverem abaixo do mínimo.", "Sim"),
        ("Contas atrasadas", "Alerta", "contas_atrasadas", "ERP", "Avisar quando contas a pagar ou receber estiverem atrasadas.", "Sim"),
        ("Entregas de hoje", "Alerta", "entregas_hoje", "ERP", "Avisar entregas programadas para hoje.", "Sim"),
        ("OP atrasada", "Alerta", "op_atrasada", "ERP", "Avisar ordens de produção atrasadas.", "Sim"),
        ("Follow-up orçamento", "Alerta", "followup_orcamento", "ERP", "Avisar orçamentos aguardando resposta.", "Sim"),
        ("Aniversariantes", "Alerta", "aniversariantes", "ERP", "Avisar clientes aniversariantes do mês.", "Sim"),
    ]

    for auto in automacoes_padrao:
        try:
            executar("""
            INSERT OR IGNORE INTO automacoes_erp(nome, tipo, regra, canal, mensagem, ativo)
            VALUES (?, ?, ?, ?, ?, ?)
            """, auto)
        except Exception:
            pass


def alerta_existe(tipo, origem, referencia_id, titulo):
    try:
        df = consultar("""
        SELECT id
        FROM alertas_erp
        WHERE tipo=? AND origem=? AND COALESCE(referencia_id,0)=COALESCE(?,0)
          AND titulo=? AND status IN ('Novo', 'Lido')
        LIMIT 1
        """, (str(tipo), str(origem), int(referencia_id or 0), str(titulo)))
        return not df.empty
    except Exception:
        return False


def criar_alerta_erp(tipo, origem, referencia_id, titulo, mensagem, prioridade="Normal", acao_sugerida="", link_interno=""):
    garantir_automacoes_erp()

    if alerta_existe(tipo, origem, referencia_id or 0, titulo):
        return False

    executar("""
    INSERT INTO alertas_erp(
        tipo, origem, referencia_id, titulo, mensagem,
        prioridade, status, acao_sugerida, link_interno
    )
    VALUES (?, ?, ?, ?, ?, ?, 'Novo', ?, ?)
    """, (
        str(tipo),
        str(origem),
        int(referencia_id or 0),
        str(titulo),
        str(mensagem),
        str(prioridade),
        str(acao_sugerida),
        str(link_interno),
    ))

    return True


def automacao_ativa(regra):
    garantir_automacoes_erp()
    try:
        df = consultar("""
        SELECT ativo FROM automacoes_erp
        WHERE regra=?
        LIMIT 1
        """, (str(regra),))
        if df.empty:
            return True
        return str(df.iloc[0]["ativo"]) == "Sim"
    except Exception:
        return True


def executar_automacoes_erp():
    garantir_automacoes_erp()
    criados = 0
    hoje = datetime.now().date()
    hoje_txt = hoje.isoformat()

    # 1) Estoque baixo
    if automacao_ativa("estoque_baixo"):
        try:
            resumo = resumo_estoque_inteligente()
        except Exception:
            resumo = pd.DataFrame()

        if not resumo.empty:
            baixos = resumo[resumo["disponivel"] <= resumo["estoque_minimo"]]
            for _, r in baixos.iterrows():
                prioridade = "Alta" if n(r["disponivel"]) <= 0 else "Normal"
                ok = criar_alerta_erp(
                    "Estoque",
                    "Estoque Inteligente",
                    0,
                    f"Estoque baixo: {r['item']}",
                    f"O item {r['item']} está com disponível {r['disponivel']} e mínimo {r['estoque_minimo']}.",
                    prioridade,
                    "Verificar compra ou reposição do material.",
                    "Estoque Inteligente",
                )
                criados += 1 if ok else 0

    # 2) Contas atrasadas
    if automacao_ativa("contas_atrasadas"):
        try:
            pagar = consultar("""
            SELECT id, descricao, valor, data_vencimento, status
            FROM contas_pagar
            WHERE ativo='Sim'
              AND status NOT IN ('Pago', 'Cancelado')
              AND data_vencimento < ?
            """, (hoje_txt,))
        except Exception:
            pagar = pd.DataFrame()

        for _, r in pagar.iterrows():
            ok = criar_alerta_erp(
                "Financeiro",
                "Contas a pagar",
                int(r["id"]),
                f"Conta a pagar atrasada: {r['descricao']}",
                f"A conta {r['descricao']} venceu em {r['data_vencimento']} no valor de {real(r['valor'])}.",
                "Alta",
                "Verificar pagamento da conta.",
                "Financeiro Profissional",
            )
            criados += 1 if ok else 0

        try:
            receber = consultar("""
            SELECT id, descricao, cliente_nome, valor, data_vencimento, status
            FROM contas_receber
            WHERE ativo='Sim'
              AND status NOT IN ('Recebido', 'Cancelado')
              AND data_vencimento < ?
            """, (hoje_txt,))
        except Exception:
            receber = pd.DataFrame()

        for _, r in receber.iterrows():
            ok = criar_alerta_erp(
                "Financeiro",
                "Contas a receber",
                int(r["id"]),
                f"Recebimento atrasado: {r['cliente_nome']}",
                f"O recebimento {r['descricao']} venceu em {r['data_vencimento']} no valor de {real(r['valor'])}.",
                "Alta",
                "Entrar em contato com o cliente.",
                "Financeiro Profissional",
            )
            criados += 1 if ok else 0

    # 3) Entregas de hoje
    if automacao_ativa("entregas_hoje"):
        try:
            ent = consultar("""
            SELECT id, codigo, cliente_nome, status, data_entrega, tipo_entrega
            FROM entregas
            WHERE ativo='Sim'
              AND data_entrega=?
              AND status NOT IN ('Entregue', 'Cancelado')
            """, (hoje_txt,))
        except Exception:
            ent = pd.DataFrame()

        for _, r in ent.iterrows():
            ok = criar_alerta_erp(
                "Entrega",
                "Entregas",
                int(r["id"]),
                f"Entrega hoje: {r['cliente_nome']}",
                f"Entrega {r.get('codigo','')} para {r['cliente_nome']} está marcada para hoje. Tipo: {r['tipo_entrega']}.",
                "Normal",
                "Separar pedido e confirmar entrega.",
                "Agenda e Entregas",
            )
            criados += 1 if ok else 0

    # 4) OP atrasada
    if automacao_ativa("op_atrasada"):
        try:
            ops = consultar("""
            SELECT id, cliente_nome, status, data_entrega, prioridade
            FROM ordens_producao
            WHERE ativo='Sim'
              AND data_entrega < ?
              AND status NOT IN ('Entregue', 'Cancelado', 'Finalizado')
            """, (hoje_txt,))
        except Exception:
            ops = pd.DataFrame()

        for _, r in ops.iterrows():
            ok = criar_alerta_erp(
                "Produção",
                "Ordem de Produção",
                int(r["id"]),
                f"OP atrasada: {codigo_op_seguro(r['id'])}",
                f"A OP {codigo_op_seguro(r['id'])} de {r['cliente_nome']} está atrasada. Previsão era {r['data_entrega']}.",
                "Alta",
                "Verificar produção e atualizar prazo.",
                "Produção",
            )
            criados += 1 if ok else 0

    # 5) Follow-up orçamento
    if automacao_ativa("followup_orcamento"):
        try:
            limite = (hoje - timedelta(days=2)).isoformat()
            orcs = consultar("""
            SELECT id, cliente_nome, whatsapp, status, total, data_orcamento
            FROM orcamentos
            WHERE date(data_orcamento) <= ?
              AND status IN ('Em orçamento', 'Em orÃ§amento', 'Aguardando pagamento')
            ORDER BY id DESC
            """, (limite,))
        except Exception:
            orcs = pd.DataFrame()

        for _, r in orcs.iterrows():
            ok = criar_alerta_erp(
                "Comercial",
                "Orçamento",
                int(r["id"]),
                f"Follow-up orçamento: {r['cliente_nome']}",
                f"O orçamento {codigo_visual('ORC', r['id'], ano=datetime.now().year)} de {r['cliente_nome']} está aguardando resposta.",
                "Normal",
                "Enviar mensagem de follow-up pelo WhatsApp.",
                "Orçamentos",
            )
            criados += 1 if ok else 0

    # 6) Aniversariantes
    if automacao_ativa("aniversariantes"):
        try:
            anivers = aniversariantes_periodo()
        except Exception:
            anivers = pd.DataFrame()

        if not anivers.empty:
            for _, r in anivers.iterrows():
                ok = criar_alerta_erp(
                    "CRM",
                    "Aniversário",
                    int(r["id"]),
                    f"Aniversariante do mês: {r['nome']}",
                    f"O cliente {r['nome']} faz aniversário neste mês. WhatsApp: {r.get('whatsapp','')}.",
                    "Baixa",
                    "Enviar mensagem de aniversário ou cupom especial.",
                    "CRM Inteligente",
                )
                criados += 1 if ok else 0

    try:
        executar("UPDATE automacoes_erp SET ultima_execucao=CURRENT_TIMESTAMP WHERE ativo='Sim'")
    except Exception:
        pass

    return criados


def mensagem_whatsapp_alerta(alerta):
    titulo = str(alerta.get("titulo", ""))
    mensagem = str(alerta.get("mensagem", ""))
    acao = str(alerta.get("acao_sugerida", ""))
    return f"Alerta Sophi ERP%0A%0A{titulo}%0A{mensagem}%0A%0AAção sugerida: {acao}"


def tela_central_automacao():
    garantir_automacoes_erp()

    st.title("Central de Automação")
    st.write("Alertas inteligentes, painel executivo e ações rápidas do Sophi ERP.")

    abas = st.tabs([
        "Painel executivo",
        "Alertas",
        "Automações",
        "Ações rápidas",
    ])

    with abas[0]:
        st.subheader("Painel executivo")

        if st.button("Executar automações agora"):
            novos = executar_automacoes_erp()
            st.success(f"{novos} novo(s) alerta(s) gerado(s).")
            st.rerun()

        alertas = consultar("""
        SELECT *
        FROM alertas_erp
        WHERE status IN ('Novo', 'Lido')
        ORDER BY
            CASE prioridade
                WHEN 'Alta' THEN 1
                WHEN 'Normal' THEN 2
                WHEN 'Baixa' THEN 3
                ELSE 4
            END,
            id DESC
        """)

        qtd_alta = len(alertas[alertas["prioridade"] == "Alta"]) if not alertas.empty else 0
        qtd_total = len(alertas) if not alertas.empty else 0

        try:
            ops_abertas = consultar("""
            SELECT COUNT(*) AS total FROM ordens_producao
            WHERE ativo='Sim' AND status NOT IN ('Entregue', 'Cancelado')
            """).iloc[0]["total"]
        except Exception:
            ops_abertas = 0

        try:
            entregas_hoje = consultar("""
            SELECT COUNT(*) AS total FROM entregas
            WHERE ativo='Sim' AND data_entrega=? AND status NOT IN ('Entregue', 'Cancelado')
            """, (hoje_iso(),)).iloc[0]["total"]
        except Exception:
            entregas_hoje = 0

        try:
            contas_atrasadas = consultar("""
            SELECT COUNT(*) AS total FROM contas_pagar
            WHERE ativo='Sim' AND status NOT IN ('Pago', 'Cancelado') AND data_vencimento < ?
            """, (hoje_iso(),)).iloc[0]["total"]
        except Exception:
            contas_atrasadas = 0

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            card("Alertas ativos", str(qtd_total))
        with c2:
            card("Alertas alta prioridade", str(qtd_alta))
        with c3:
            card("OPs abertas", str(ops_abertas))
        with c4:
            card("Entregas hoje", str(entregas_hoje))

        c5, c6 = st.columns(2)
        with c5:
            card("Contas atrasadas", str(contas_atrasadas))
        with c6:
            try:
                resumo = resumo_estoque_inteligente()
                baixo = len(resumo[resumo["disponivel"] <= resumo["estoque_minimo"]]) if not resumo.empty else 0
            except Exception:
                baixo = 0
            card("Estoque em atenção", str(baixo))

        st.divider()

        st.subheader("Alertas principais")
        if alertas.empty:
            st.success("Nenhum alerta ativo no momento.")
        else:
            st.dataframe(alertas.head(15), use_container_width=True, hide_index=True)

    with abas[1]:
        st.subheader("Gerenciar alertas")

        alertas = consultar("""
        SELECT *
        FROM alertas_erp
        ORDER BY id DESC
        LIMIT 500
        """)

        if alertas.empty:
            st.info("Nenhum alerta gerado ainda.")
        else:
            filtro_status = st.selectbox("Filtrar status", ["Todos", "Novo", "Lido", "Resolvido", "Arquivado"])
            filtro_prioridade = st.selectbox("Filtrar prioridade", ["Todas", "Alta", "Normal", "Baixa"])

            df = alertas.copy()
            if filtro_status != "Todos":
                df = df[df["status"] == filtro_status]
            if filtro_prioridade != "Todas":
                df = df[df["prioridade"] == filtro_prioridade]

            edited = st.data_editor(
                df,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="editor_alertas_erp",
                column_config={
                    "status": st.column_config.SelectboxColumn("Status", options=["Novo", "Lido", "Resolvido", "Arquivado"]),
                    "prioridade": st.column_config.SelectboxColumn("Prioridade", options=["Alta", "Normal", "Baixa"]),
                },
            )

            c1, c2 = st.columns([2, 1])
            with c1:
                if st.button("Salvar alterações dos alertas"):
                    for _, r in edited.iterrows():
                        executar("""
                        UPDATE alertas_erp
                        SET status=?, prioridade=?, acao_sugerida=?
                        WHERE id=?
                        """, (
                            str(r.get("status", "Novo")),
                            str(r.get("prioridade", "Normal")),
                            str(r.get("acao_sugerida", "")),
                            int(r["id"]),
                        ))
                    st.success("Alertas atualizados.")
                    st.rerun()

            with c2:
                if st.button("Arquivar alertas resolvidos"):
                    executar("UPDATE alertas_erp SET status='Arquivado' WHERE status='Resolvido'")
                    st.success("Alertas resolvidos arquivados.")
                    st.rerun()

    with abas[2]:
        st.subheader("Configurar automações")

        autos = consultar("""
        SELECT *
        FROM automacoes_erp
        ORDER BY id ASC
        """)

        if autos.empty:
            st.info("Nenhuma automação cadastrada.")
        else:
            edited = st.data_editor(
                autos,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="editor_automacoes_erp",
                column_config={
                    "ativo": st.column_config.SelectboxColumn("Ativo", options=["Sim", "Não"]),
                    "tipo": st.column_config.SelectboxColumn("Tipo", options=["Alerta", "Ação", "Lembrete"]),
                    "canal": st.column_config.SelectboxColumn("Canal", options=["ERP", "WhatsApp manual", "E-mail manual"]),
                },
            )

            if st.button("Salvar automações"):
                for _, r in edited.iterrows():
                    if str(r.get("nome", "")).strip():
                        if pd.isna(r.get("id")):
                            executar("""
                            INSERT INTO automacoes_erp(nome, tipo, regra, canal, mensagem, ativo, observacoes)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (
                                str(r.get("nome", "")),
                                str(r.get("tipo", "Alerta")),
                                str(r.get("regra", "")),
                                str(r.get("canal", "ERP")),
                                str(r.get("mensagem", "")),
                                str(r.get("ativo", "Sim")),
                                str(r.get("observacoes", "")),
                            ))
                        else:
                            executar("""
                            UPDATE automacoes_erp
                            SET nome=?, tipo=?, regra=?, canal=?, mensagem=?, ativo=?, observacoes=?
                            WHERE id=?
                            """, (
                                str(r.get("nome", "")),
                                str(r.get("tipo", "Alerta")),
                                str(r.get("regra", "")),
                                str(r.get("canal", "ERP")),
                                str(r.get("mensagem", "")),
                                str(r.get("ativo", "Sim")),
                                str(r.get("observacoes", "")),
                                int(r["id"]),
                            ))
                st.success("Automações salvas.")
                st.rerun()

    with abas[3]:
        st.subheader("Ações rápidas")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### Criar tarefas automáticas")
            if st.button("Sincronizar OPs com Agenda"):
                try:
                    tarefas, entregas = sincronizar_op_com_agenda()
                    st.success(f"{tarefas} tarefa(s) e {entregas} entrega(s) criadas.")
                except Exception as e:
                    st.error(f"Não foi possível sincronizar: {e}")

            if st.button("Criar follow-ups de orçamentos"):
                try:
                    qtd = sincronizar_orcamentos_com_agenda()
                    st.success(f"{qtd} follow-up(s) criado(s).")
                except Exception as e:
                    st.error(f"Não foi possível criar follow-ups: {e}")

            if st.button("Atualizar fidelidade dos clientes"):
                try:
                    qtd = sincronizar_fidelidade_clientes()
                    st.success(f"{qtd} cliente(s) atualizado(s).")
                except Exception as e:
                    st.error(f"Não foi possível atualizar fidelidade: {e}")

        with col2:
            st.markdown("### Gerar alertas")
            if st.button("Verificar estoque, financeiro, produção e CRM"):
                novos = executar_automacoes_erp()
                st.success(f"{novos} novo(s) alerta(s) gerado(s).")

            st.markdown("### Mensagem WhatsApp de alerta")
            alertas_novos = consultar("""
            SELECT *
            FROM alertas_erp
            WHERE status IN ('Novo', 'Lido')
            ORDER BY id DESC
            LIMIT 50
            """)

            if alertas_novos.empty:
                st.info("Nenhum alerta ativo para mensagem.")
            else:
                mapa = {
                    f"{r['id']} - {r['titulo']}": int(r["id"])
                    for _, r in alertas_novos.iterrows()
                }

                esc = st.selectbox("Escolha alerta", list(mapa.keys()))
                aid = mapa[esc]
                alerta = alertas_novos[alertas_novos["id"] == aid].iloc[0].to_dict()
                msg = mensagem_whatsapp_alerta(alerta)
                st.text_area("Mensagem pronta", value=msg.replace("%0A", "\n"), height=160)




# ============================================================
# MÓDULO 10 — BIBLIOTECA DE ARTES / TEMPLATES
# ============================================================

def garantir_biblioteca_artes():
    try:
        executar("""
        CREATE TABLE IF NOT EXISTS biblioteca_arquivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            tipo TEXT DEFAULT 'Arte',
            categoria TEXT,
            produto_relacionado TEXT,
            cliente_id INTEGER,
            cliente_nome TEXT,
            caminho_arquivo TEXT,
            formato TEXT,
            tags TEXT,
            favorito TEXT DEFAULT 'Não',
            status TEXT DEFAULT 'Ativo',
            observacoes TEXT,
            data_upload TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
    except Exception:
        pass

    try:
        executar("""
        CREATE TABLE IF NOT EXISTS biblioteca_modelos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            tipo TEXT DEFAULT 'Template',
            categoria TEXT,
            tamanho TEXT,
            descricao TEXT,
            caminho_arquivo TEXT,
            tags TEXT,
            favorito TEXT DEFAULT 'Não',
            status TEXT DEFAULT 'Ativo',
            observacoes TEXT,
            data_cadastro TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
    except Exception:
        pass


def salvar_upload_biblioteca(upload, prefixo):
    if upload is None:
        return ""

    try:
        BIB_DIR = Path("uploads") / "biblioteca"
        BIB_DIR.mkdir(parents=True, exist_ok=True)
        ext = Path(upload.name).suffix.lower()
        nome_limpo = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(upload.name).stem)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        caminho = BIB_DIR / f"{prefixo}_{timestamp}_{nome_limpo}{ext}"
        caminho.write_bytes(upload.getbuffer())
        return str(caminho)
    except Exception:
        return salvar_upload(upload, prefixo)


def codigo_biblioteca(id_valor):
    try:
        return codigo_visual("ART", int(id_valor))
    except Exception:
        return f"ART-{int(id_valor):04d}"


def codigo_modelo(id_valor):
    try:
        return codigo_visual("MOD", int(id_valor))
    except Exception:
        return f"MOD-{int(id_valor):04d}"


def preview_arquivo_biblioteca(caminho):
    try:
        if not caminho or not Path(caminho).exists():
            st.caption("Arquivo não encontrado no servidor.")
            return

        ext = Path(caminho).suffix.lower()

        if ext in [".png", ".jpg", ".jpeg", ".webp"]:
            st.image(caminho, use_container_width=True)
        else:
            st.caption(f"Arquivo salvo: {Path(caminho).name}")
            with open(caminho, "rb") as f:
                st.download_button(
                    "Baixar arquivo",
                    data=f.read(),
                    file_name=Path(caminho).name,
                    mime="application/octet-stream",
                    key=f"download_{caminho}",
                )
    except Exception:
        st.caption("Não foi possível exibir o arquivo.")


def buscar_biblioteca(termo="", categoria="", tipo="", favoritos=False):
    sql = """
    SELECT *
    FROM biblioteca_arquivos
    WHERE status != 'Excluído'
    """
    params = []

    if termo.strip():
        like = f"%{termo.strip()}%"
        sql += " AND (nome LIKE ? OR tags LIKE ? OR cliente_nome LIKE ? OR produto_relacionado LIKE ? OR observacoes LIKE ?)"
        params.extend([like, like, like, like, like])

    if categoria and categoria != "Todas":
        sql += " AND categoria=?"
        params.append(categoria)

    if tipo and tipo != "Todos":
        sql += " AND tipo=?"
        params.append(tipo)

    if favoritos:
        sql += " AND favorito='Sim'"

    sql += " ORDER BY favorito DESC, id DESC"

    try:
        return consultar(sql, tuple(params))
    except Exception:
        return pd.DataFrame()


def tela_biblioteca_artes():
    garantir_biblioteca_artes()

    st.title("Biblioteca de Artes")
    st.write("Organize artes, templates, mockups, arquivos de cliente, modelos de produção e referências da Sophi.")

    abas = st.tabs([
        "Adicionar arquivo",
        "Buscar biblioteca",
        "Modelos / Templates",
        "Favoritos",
        "Organização",
    ])

    with abas[0]:
        st.subheader("Adicionar arte ou arquivo")

        clientes = consultar("SELECT id, nome FROM clientes WHERE ativo='Sim' ORDER BY nome")
        cliente_opcoes = ["Sem cliente"]
        mapa_clientes = {"Sem cliente": (None, "")}

        if not clientes.empty:
            for _, c in clientes.iterrows():
                label = f"{codigo_visual('CLI', c['id'])} - {c['nome']}"
                cliente_opcoes.append(label)
                mapa_clientes[label] = (int(c["id"]), str(c["nome"]))

        produtos = consultar("SELECT nome FROM produtos WHERE ativo='Sim' ORDER BY nome")
        lista_produtos = ["Sem produto"]
        if not produtos.empty:
            lista_produtos += produtos["nome"].astype(str).tolist()

        upload = st.file_uploader(
            "Enviar arquivo",
            type=["png", "jpg", "jpeg", "webp", "pdf", "svg", "studio3", "zip", "psd", "ai"],
            key="upload_biblioteca_arte",
        )

        with st.form("form_biblioteca_arquivo"):
            c1, c2, c3 = st.columns(3)
            nome = c1.text_input("Nome da arte/arquivo", placeholder="Ex: Arte Spotify casal")
            tipo = c2.selectbox("Tipo", ["Arte", "Mockup", "Template", "Foto cliente", "Arquivo de corte", "PDF", "Referência", "Outro"])
            categoria = c3.selectbox("Categoria", categorias_ativas() or ["Outro"])

            c4, c5 = st.columns(2)
            produto_rel = c4.selectbox("Produto relacionado", lista_produtos)
            cliente_sel = c5.selectbox("Cliente", cliente_opcoes)

            tags = st.text_input("Tags", placeholder="Ex: spotify, polaroid, casal, preto")
            favorito = st.selectbox("Favorito?", ["Não", "Sim"])
            observacoes = st.text_area("Observações")

            if st.form_submit_button("Salvar na biblioteca"):
                if not nome.strip():
                    st.error("Digite o nome do arquivo.")
                elif upload is None:
                    st.error("Envie um arquivo.")
                else:
                    cliente_id, cliente_nome = mapa_clientes[cliente_sel]
                    caminho = salvar_upload_biblioteca(upload, "arte")
                    formato = Path(caminho).suffix.lower().replace(".", "") if caminho else ""

                    executar("""
                    INSERT INTO biblioteca_arquivos(
                        nome, tipo, categoria, produto_relacionado, cliente_id, cliente_nome,
                        caminho_arquivo, formato, tags, favorito, status, observacoes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        nome,
                        tipo,
                        categoria,
                        "" if produto_rel == "Sem produto" else produto_rel,
                        cliente_id,
                        cliente_nome,
                        caminho,
                        formato,
                        tags,
                        favorito,
                        "Ativo",
                        observacoes,
                    ))

                    st.success("Arquivo salvo na biblioteca.")
                    st.rerun()

    with abas[1]:
        st.subheader("Buscar na biblioteca")

        c1, c2, c3, c4 = st.columns([2, 1.2, 1.2, 1])
        termo = c1.text_input("Buscar por nome, tag, cliente ou produto")
        categoria = c2.selectbox("Categoria", ["Todas"] + (categorias_ativas() or []), key="busca_cat_bib")
        tipo = c3.selectbox("Tipo", ["Todos", "Arte", "Mockup", "Template", "Foto cliente", "Arquivo de corte", "PDF", "Referência", "Outro"], key="busca_tipo_bib")
        fav = c4.checkbox("Só favoritos")

        df = buscar_biblioteca(termo, categoria, tipo, fav)

        if df.empty:
            st.info("Nenhum arquivo encontrado.")
        else:
            df_view = df.copy()
            df_view["codigo"] = df_view["id"].apply(codigo_biblioteca)

            st.dataframe(
                df_view[[
                    "codigo", "id", "nome", "tipo", "categoria", "produto_relacionado",
                    "cliente_nome", "formato", "tags", "favorito", "status", "data_upload"
                ]],
                use_container_width=True,
                hide_index=True,
            )

            st.divider()
            st.subheader("Pré-visualizar arquivo")

            mapa = {
                f"{codigo_biblioteca(r['id'])} - {r['nome']}": int(r["id"])
                for _, r in df.iterrows()
            }

            escolhido = st.selectbox("Escolha um arquivo", list(mapa.keys()))
            item_id = mapa[escolhido]
            item = df[df["id"] == item_id].iloc[0]

            st.write(f"**Nome:** {item['nome']}")
            st.write(f"**Tipo:** {item['tipo']}")
            st.write(f"**Categoria:** {item['categoria']}")
            st.write(f"**Produto:** {item['produto_relacionado'] or '-'}")
            st.write(f"**Cliente:** {item['cliente_nome'] or '-'}")
            st.write(f"**Tags:** {item['tags'] or '-'}")
            st.write(f"**Observações:** {item['observacoes'] or '-'}")

            preview_arquivo_biblioteca(str(item["caminho_arquivo"]))

    with abas[2]:
        st.subheader("Modelos e templates")

        upload_modelo = st.file_uploader(
            "Enviar template/modelo",
            type=["png", "jpg", "jpeg", "webp", "pdf", "svg", "studio3", "zip", "psd", "ai"],
            key="upload_modelo_biblioteca",
        )

        with st.form("form_modelo_biblioteca"):
            c1, c2, c3 = st.columns(3)
            nome = c1.text_input("Nome do modelo", placeholder="Ex: Template Polaroid 6x8")
            tipo = c2.selectbox("Tipo do modelo", ["Template", "Mockup", "Arquivo de corte", "PDF", "SVG", "Outro"])
            categoria = c3.selectbox("Categoria do modelo", categorias_ativas() or ["Outro"])

            tamanho = st.text_input("Tamanho", placeholder="Ex: 6x8 cm / A4 / 5x15 cm")
            descricao = st.text_area("Descrição do modelo")
            tags = st.text_input("Tags do modelo", placeholder="Ex: polaroid, a4, corte")
            favorito = st.selectbox("Favorito?", ["Não", "Sim"], key="fav_modelo_bib")
            obs = st.text_area("Observações do modelo")

            if st.form_submit_button("Salvar modelo"):
                if not nome.strip():
                    st.error("Digite o nome do modelo.")
                elif upload_modelo is None:
                    st.error("Envie o arquivo do modelo.")
                else:
                    caminho = salvar_upload_biblioteca(upload_modelo, "modelo")
                    executar("""
                    INSERT INTO biblioteca_modelos(
                        nome, tipo, categoria, tamanho, descricao,
                        caminho_arquivo, tags, favorito, status, observacoes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        nome, tipo, categoria, tamanho, descricao,
                        caminho, tags, favorito, "Ativo", obs,
                    ))
                    st.success("Modelo salvo.")
                    st.rerun()

        st.divider()
        modelos = consultar("""
        SELECT *
        FROM biblioteca_modelos
        WHERE status != 'Excluído'
        ORDER BY favorito DESC, id DESC
        """)

        if modelos.empty:
            st.info("Nenhum modelo cadastrado.")
        else:
            modelos["codigo"] = modelos["id"].apply(codigo_modelo)
            st.dataframe(modelos, use_container_width=True, hide_index=True)

            mapa_mod = {
                f"{codigo_modelo(r['id'])} - {r['nome']}": int(r["id"])
                for _, r in modelos.iterrows()
            }

            esc = st.selectbox("Pré-visualizar modelo", list(mapa_mod.keys()))
            mid = mapa_mod[esc]
            m = modelos[modelos["id"] == mid].iloc[0]
            preview_arquivo_biblioteca(str(m["caminho_arquivo"]))

    with abas[3]:
        st.subheader("Favoritos")

        artes_fav = consultar("""
        SELECT *
        FROM biblioteca_arquivos
        WHERE favorito='Sim' AND status != 'Excluído'
        ORDER BY id DESC
        """)

        modelos_fav = consultar("""
        SELECT *
        FROM biblioteca_modelos
        WHERE favorito='Sim' AND status != 'Excluído'
        ORDER BY id DESC
        """)

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### Artes favoritas")
            if artes_fav.empty:
                st.info("Nenhuma arte favorita.")
            else:
                artes_fav["codigo"] = artes_fav["id"].apply(codigo_biblioteca)
                st.dataframe(artes_fav, use_container_width=True, hide_index=True)

        with col2:
            st.markdown("### Modelos favoritos")
            if modelos_fav.empty:
                st.info("Nenhum modelo favorito.")
            else:
                modelos_fav["codigo"] = modelos_fav["id"].apply(codigo_modelo)
                st.dataframe(modelos_fav, use_container_width=True, hide_index=True)

    with abas[4]:
        st.subheader("Organização e edição rápida")

        st.markdown("### Artes / arquivos")

        arquivos = consultar("""
        SELECT id, nome, tipo, categoria, produto_relacionado, cliente_nome,
               tags, favorito, status, observacoes, data_upload
        FROM biblioteca_arquivos
        ORDER BY id DESC
        """)

        if arquivos.empty:
            st.info("Nenhum arquivo para organizar.")
        else:
            edited = st.data_editor(
                arquivos,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="editor_biblioteca_arquivos",
                column_config={
                    "tipo": st.column_config.SelectboxColumn("Tipo", options=["Arte", "Mockup", "Template", "Foto cliente", "Arquivo de corte", "PDF", "Referência", "Outro"]),
                    "favorito": st.column_config.SelectboxColumn("Favorito", options=["Sim", "Não"]),
                    "status": st.column_config.SelectboxColumn("Status", options=["Ativo", "Arquivado", "Excluído"]),
                },
            )

            if st.button("Salvar organização das artes"):
                for _, r in edited.iterrows():
                    if str(r.get("nome", "")).strip():
                        executar("""
                        UPDATE biblioteca_arquivos
                        SET nome=?, tipo=?, categoria=?, produto_relacionado=?,
                            cliente_nome=?, tags=?, favorito=?, status=?, observacoes=?
                        WHERE id=?
                        """, (
                            str(r.get("nome", "")),
                            str(r.get("tipo", "")),
                            str(r.get("categoria", "")),
                            str(r.get("produto_relacionado", "")),
                            str(r.get("cliente_nome", "")),
                            str(r.get("tags", "")),
                            str(r.get("favorito", "Não")),
                            str(r.get("status", "Ativo")),
                            str(r.get("observacoes", "")),
                            int(r["id"]),
                        ))
                st.success("Biblioteca atualizada.")
                st.rerun()

        st.divider()

        st.markdown("### Modelos / templates")

        modelos = consultar("""
        SELECT id, nome, tipo, categoria, tamanho, descricao,
               tags, favorito, status, observacoes, data_cadastro
        FROM biblioteca_modelos
        ORDER BY id DESC
        """)

        if modelos.empty:
            st.info("Nenhum modelo para organizar.")
        else:
            edited_m = st.data_editor(
                modelos,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="editor_biblioteca_modelos",
                column_config={
                    "tipo": st.column_config.SelectboxColumn("Tipo", options=["Template", "Mockup", "Arquivo de corte", "PDF", "SVG", "Outro"]),
                    "favorito": st.column_config.SelectboxColumn("Favorito", options=["Sim", "Não"]),
                    "status": st.column_config.SelectboxColumn("Status", options=["Ativo", "Arquivado", "Excluído"]),
                },
            )

            if st.button("Salvar organização dos modelos"):
                for _, r in edited_m.iterrows():
                    if str(r.get("nome", "")).strip():
                        executar("""
                        UPDATE biblioteca_modelos
                        SET nome=?, tipo=?, categoria=?, tamanho=?, descricao=?,
                            tags=?, favorito=?, status=?, observacoes=?
                        WHERE id=?
                        """, (
                            str(r.get("nome", "")),
                            str(r.get("tipo", "")),
                            str(r.get("categoria", "")),
                            str(r.get("tamanho", "")),
                            str(r.get("descricao", "")),
                            str(r.get("tags", "")),
                            str(r.get("favorito", "Não")),
                            str(r.get("status", "Ativo")),
                            str(r.get("observacoes", "")),
                            int(r["id"]),
                        ))
                st.success("Modelos atualizados.")
                st.rerun()





def tela_catalogo_publico():
    tela_catalogo()

# ============================================================
# MENU ORGANIZADO — TELAS AGRUPADAS
# ============================================================

def tela_clientes_crm():
    st.title("Clientes / CRM")
    abas = st.tabs(["Clientes", "CRM Inteligente"])
    with abas[0]:
        tela_clientes()
    with abas[1]:
        tela_crm_inteligente()


def tela_producao_agenda():
    st.title("Produção / Agenda")
    abas = st.tabs(["Produção", "Agenda e Entregas"])
    with abas[0]:
        tela_producao()
    with abas[1]:
        tela_agenda_entregas()


def tela_materiais():
    st.title("Materiais")
    st.write("Cadastre e organize todos os materiais usados na produção.")

    abas = st.tabs([
        "Papéis",
        "Embalagens",
        "Laminação",
        "Mantas / Ímã / Velcro",
        "Insumos",
        "Tintas",
        "Equipamentos",
        "Categorias",
    ])

    with abas[0]:
        tela_cadastro_por_categoria("Papéis", "Papel")
    with abas[1]:
        tela_embalagens()
    with abas[2]:
        tela_laminacao()
    with abas[3]:
        tela_mantas_imas()
    with abas[4]:
        tela_insumos()
    with abas[5]:
        tela_tintas()
    with abas[6]:
        tela_equipamentos()
    with abas[7]:
        tela_categorias()


def tela_estoque_unificado():
    st.title("Estoque")
    abas = st.tabs(["Movimentos", "Estoque Inteligente"])
    with abas[0]:
        tela_estoque()
    with abas[1]:
        tela_estoque_inteligente()


def tela_financeiro_unificado():
    st.title("Financeiro")
    abas = st.tabs(["Financeiro Profissional", "Dashboard Financeiro", "Fluxo de Caixa"])
    with abas[0]:
        tela_financeiro_profissional()
    with abas[1]:
        tela_dashboard_financeiro()
    with abas[2]:
        tela_financeiro()


def tela_catalogo_portal():
    st.title("Catálogo / Portal")
    abas = st.tabs(["Catálogo público", "Portal do Cliente"])
    with abas[0]:
        tela_catalogo_publico()
    with abas[1]:
        tela_portal_cliente_admin()




# ============================================================
# FLUXO DE ENTREGA NO ORÇAMENTO
# ============================================================

def garantir_campos_entrega_orcamento():
    campos = {
        "data_prevista_entrega": "TEXT",
        "hora_prevista_entrega": "TEXT",
        "tipo_entrega": "TEXT",
        "endereco_entrega": "TEXT",
        "responsavel_entrega": "TEXT",
        "prioridade_entrega": "TEXT DEFAULT 'Normal'",
        "observacoes_entrega": "TEXT",
    }

    for coluna, tipo_coluna in campos.items():
        try:
            executar(f"ALTER TABLE orcamentos ADD COLUMN {coluna} {tipo_coluna}")
        except Exception:
            pass


def status_fluxo_pedido():
    return [
        "Em orçamento",
        "Aprovado",
        "Aguardando pagamento",
        "Pago",
        "Produção",
        "Embalagem",
        "Pronto",
        "Saiu para entrega",
        "Entregue",
        "Cancelado",
    ]


def linha_tempo_pedido_html(status_atual):
    etapas = status_fluxo_pedido()
    if status_atual not in etapas:
        status_atual = "Em orçamento"

    atual = etapas.index(status_atual)

    html = """
    <style>
    .timeline-pedido {display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 18px;}
    .timeline-step {border:1px solid #ddd;border-radius:999px;padding:8px 12px;font-size:12px;font-weight:800;background:#fff;color:#777;}
    .timeline-step.done {background:#000;color:#fff;border-color:#000;}
    .timeline-step.cancel {background:#7a0d0d;color:#fff;border-color:#7a0d0d;}
    </style>
    <div class="timeline-pedido">
    """

    for i, etapa in enumerate(etapas):
        cls = "done" if i <= atual else ""
        if status_atual == "Cancelado" and etapa == "Cancelado":
            cls = "cancel"
        html += f'<div class="timeline-step {cls}">{etapa}</div>'

    html += "</div>"
    return html


def criar_ou_atualizar_entrega_do_orcamento(orcamento_id):
    garantir_campos_entrega_orcamento()
    try:
        garantir_agenda_entregas()
    except Exception:
        pass

    orc = consultar("SELECT * FROM orcamentos WHERE id=?", (int(orcamento_id),))
    if orc.empty:
        return None

    o = orc.iloc[0]
    data_entrega = str(o.get("data_prevista_entrega", "") or "").strip()

    if not data_entrega:
        return None

    hora_entrega = str(o.get("hora_prevista_entrega", "") or "")
    tipo_entrega = str(o.get("tipo_entrega", "") or "Retirada")
    endereco = str(o.get("endereco_entrega", "") or "")
    responsavel = str(o.get("responsavel_entrega", "") or "")
    obs_entrega = str(o.get("observacoes_entrega", "") or "")
    status_orc = str(o.get("status", "") or "")

    status_entrega = "Pendente"
    if status_orc == "Saiu para entrega":
        status_entrega = "Saiu para entrega"
    elif status_orc == "Entregue":
        status_entrega = "Entregue"
    elif status_orc == "Cancelado":
        status_entrega = "Cancelado"

    op_id = None
    try:
        op = consultar("""
        SELECT id FROM ordens_producao
        WHERE orcamento_id=? AND ativo='Sim'
        ORDER BY id DESC LIMIT 1
        """, (int(orcamento_id),))
        if not op.empty:
            op_id = int(op.iloc[0]["id"])
    except Exception:
        pass

    if op_id:
        existe = consultar("""
        SELECT id FROM entregas
        WHERE referencia_tipo='OP' AND referencia_id=? AND ativo='Sim'
        ORDER BY id DESC LIMIT 1
        """, (op_id,))
    else:
        existe = consultar("""
        SELECT id FROM entregas
        WHERE referencia_tipo='Orçamento' AND referencia_id=? AND ativo='Sim'
        ORDER BY id DESC LIMIT 1
        """, (int(orcamento_id),))

    referencia_tipo = "OP" if op_id else "Orçamento"
    referencia_id = op_id if op_id else int(orcamento_id)

    if existe.empty:
        try:
            proximo = consultar("SELECT COALESCE(MAX(id),0)+1 AS prox FROM entregas").iloc[0]["prox"]
            codigo = codigo_entrega(int(proximo))
        except Exception:
            proximo = 0
            codigo = f"ENT-{int(orcamento_id):04d}"

        entrega_id = executar("""
        INSERT INTO entregas(
            cliente_id, cliente_nome, whatsapp, referencia_tipo, referencia_id,
            codigo, data_entrega, hora_entrega, tipo_entrega, endereco,
            taxa_entrega, status, responsavel, observacoes, ativo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            int(o["cliente_id"]) if "cliente_id" in o.index and pd.notna(o["cliente_id"]) else None,
            str(o.get("cliente_nome", "")),
            str(o.get("whatsapp", "")),
            referencia_tipo,
            referencia_id,
            codigo,
            data_entrega,
            hora_entrega,
            tipo_entrega,
            endereco,
            n(o.get("frete", 0)),
            status_entrega,
            responsavel,
            f"Entrega criada pelo orçamento #{int(orcamento_id)}. {obs_entrega}",
            "Sim",
        ))
        return entrega_id

    entrega_id = int(existe.iloc[0]["id"])
    executar("""
    UPDATE entregas
    SET data_entrega=?, hora_entrega=?, tipo_entrega=?, endereco=?,
        taxa_entrega=?, status=?, responsavel=?, observacoes=?
    WHERE id=?
    """, (
        data_entrega,
        hora_entrega,
        tipo_entrega,
        endereco,
        n(o.get("frete", 0)),
        status_entrega,
        responsavel,
        f"Entrega atualizada pelo orçamento #{int(orcamento_id)}. {obs_entrega}",
        entrega_id,
    ))
    return entrega_id


def criar_ou_atualizar_tarefa_entrega_do_orcamento(orcamento_id):
    garantir_campos_entrega_orcamento()
    try:
        garantir_agenda_entregas()
    except Exception:
        pass

    orc = consultar("SELECT * FROM orcamentos WHERE id=?", (int(orcamento_id),))
    if orc.empty:
        return None

    o = orc.iloc[0]
    data_entrega = str(o.get("data_prevista_entrega", "") or "").strip()

    if not data_entrega:
        return None

    existe = consultar("""
    SELECT id FROM agenda_tarefas
    WHERE referencia_tipo='Orçamento' AND referencia_id=? AND tipo='Entrega' AND ativo='Sim'
    ORDER BY id DESC LIMIT 1
    """, (int(orcamento_id),))

    status_orc = str(o.get("status", "") or "")
    status_tarefa = "Pendente"
    if status_orc in ["Pronto", "Saiu para entrega"]:
        status_tarefa = "Em andamento"
    elif status_orc == "Entregue":
        status_tarefa = "Concluída"
    elif status_orc == "Cancelado":
        status_tarefa = "Cancelado"

    titulo = f"Entrega {codigo_visual('ORC', int(orcamento_id), ano=datetime.now().year)} - {o.get('cliente_nome','')}"

    if existe.empty:
        tarefa_id = executar("""
        INSERT INTO agenda_tarefas(
            titulo, tipo, cliente_id, cliente_nome, referencia_tipo, referencia_id,
            data, hora, prioridade, status, descricao, observacoes, ativo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            titulo,
            "Entrega",
            int(o["cliente_id"]) if "cliente_id" in o.index and pd.notna(o["cliente_id"]) else None,
            str(o.get("cliente_nome", "")),
            "Orçamento",
            int(orcamento_id),
            data_entrega,
            str(o.get("hora_prevista_entrega", "") or ""),
            str(o.get("prioridade_entrega", "") or "Normal"),
            status_tarefa,
            f"Entrega prevista do orçamento #{int(orcamento_id)}",
            str(o.get("observacoes_entrega", "") or ""),
            "Sim",
        ))
        return tarefa_id

    tarefa_id = int(existe.iloc[0]["id"])
    executar("""
    UPDATE agenda_tarefas
    SET titulo=?, data=?, hora=?, prioridade=?, status=?, observacoes=?
    WHERE id=?
    """, (
        titulo,
        data_entrega,
        str(o.get("hora_prevista_entrega", "") or ""),
        str(o.get("prioridade_entrega", "") or "Normal"),
        status_tarefa,
        str(o.get("observacoes_entrega", "") or ""),
        tarefa_id,
    ))
    return tarefa_id


def aplicar_fluxo_status_orcamento(orcamento_id, novo_status):
    garantir_campos_entrega_orcamento()
    orc = consultar("SELECT * FROM orcamentos WHERE id=?", (int(orcamento_id),))

    if orc.empty:
        return

    o = orc.iloc[0]

    if novo_status in ["Pago", "Produção", "Embalagem", "Pronto", "Saiu para entrega", "Finalizado", "Entregue"]:
        try:
            fin_existe = consultar("SELECT id FROM financeiro WHERE origem='Orçamento' AND referencia_id=? LIMIT 1", (int(orcamento_id),))
            if fin_existe.empty:
                executar("""
                INSERT INTO financeiro(data, tipo, descricao, categoria, forma_pagamento, valor, origem, referencia_id, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    hoje_iso(),
                    "Entrada",
                    f"Orçamento #{int(orcamento_id)} - {o.get('cliente_nome','')}",
                    "Venda",
                    str(o.get("forma_pagamento", "")),
                    n(o.get("total", 0)),
                    "Orçamento",
                    int(orcamento_id),
                    str(o.get("observacoes", "") or ""),
                ))
        except Exception:
            pass

    if novo_status in ["Produção", "Embalagem", "Pronto", "Saiu para entrega", "Finalizado", "Entregue"]:
        try:
            criar_op_de_orcamento(
                int(orcamento_id),
                prioridade=str(o.get("prioridade_entrega", "") or "Normal"),
                data_entrega=str(o.get("data_prevista_entrega", "") or ""),
                observacoes_extra="Criada/atualizada pelo fluxo do orçamento.",
            )
        except Exception:
            pass

    try:
        if novo_status == "Produção":
            executar("UPDATE ordens_producao SET status='Produzindo' WHERE orcamento_id=? AND ativo='Sim'", (int(orcamento_id),))
        elif novo_status in ["Pronto", "Finalizado"]:
            executar("UPDATE ordens_producao SET status='Finalizado' WHERE orcamento_id=? AND ativo='Sim'", (int(orcamento_id),))
        elif novo_status == "Entregue":
            executar("UPDATE ordens_producao SET status='Entregue' WHERE orcamento_id=? AND ativo='Sim'", (int(orcamento_id),))
    except Exception:
        pass

    try:
        criar_ou_atualizar_entrega_do_orcamento(int(orcamento_id))
        criar_ou_atualizar_tarefa_entrega_do_orcamento(int(orcamento_id))
    except Exception:
        pass




# ============================================================
# CENTRAL DE MENSAGENS WHATSAPP
# ============================================================



# ============================================================
# EMOJIS SEGUROS PARA WHATSAPP
# ============================================================

def emoji_seguro(nome):
    emojis = {
        "coracao": "\U0001F90D",
        "brilho": "\u2728",
        "caminhao": "\U0001F69A",
        "bolo": "\U0001F382",
        "caixa": "\U0001F4E6",
        "dinheiro": "\U0001F4B3",
        "check": "\u2705",
        "alerta": "\u26A0\uFE0F",
        "sorriso": "\U0001F60A",
    }
    return emojis.get(nome, "")


def limpar_texto_whatsapp(texto):
    texto = str(texto or "")
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = texto.replace("\uFFFD", "")
    texto = texto.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    texto = texto.replace("\ufeff", "")
    return texto




# ============================================================
# WHATSAPP — EMOJIS E TEXTOS SEGUROS
# ============================================================

def emoji_seguro(nome):
    emojis = {
        "coracao": "\U0001F90D",
        "roxo": "\U0001F49C",
        "brilho": "\u2728",
        "caminhao": "\U0001F69A",
        "bolo": "\U0001F382",
        "caixa": "\U0001F4E6",
        "dinheiro": "\U0001F4B3",
        "check": "\u2705",
        "festa": "\U0001F389",
        "oracao": "\U0001F64F",
        "sorriso": "\U0001F60A",
        "ferramenta": "\U0001F6E0\U0000FE0F",
        "calendario": "\U0001F4C5",
    }
    return emojis.get(nome, "")


def limpar_texto_whatsapp(texto):
    texto = str(texto or "")
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = texto.replace("\uFFFD", "")
    texto = texto.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    texto = texto.replace("\ufeff", "")
    return texto


def aplicar_variaveis_mensagem(modelo, nome="", codigo="", valor="", data="", link="", pix=""):
    texto = str(modelo or "")
    texto = texto.replace("{nome}", str(nome or "cliente"))
    texto = texto.replace("{id}", str(codigo or ""))
    texto = texto.replace("{valor}", str(valor or ""))
    texto = texto.replace("{data}", str(data or ""))
    texto = texto.replace("{link}", str(link or ""))
    texto = texto.replace("{pix}", str(pix or pix_empresa()))
    try:
        return limpar_texto_whatsapp(texto)
    except Exception:
        return texto


def limpar_numero_whatsapp(numero):
    numero = "".join([c for c in str(numero or "") if c.isdigit()])
    if not numero:
        return ""
    if numero.startswith("55"):
        return numero
    return "55" + numero


def link_whatsapp(numero, mensagem):
    try:
        import urllib.parse
        numero_limpo = limpar_numero_whatsapp(numero)
        if not numero_limpo:
            return ""

        texto = limpar_texto_whatsapp(mensagem)
        texto_codificado = urllib.parse.quote(texto, safe="", encoding="utf-8", errors="strict")
        return f"https://wa.me/{numero_limpo}?text={texto_codificado}"
    except Exception:
        return ""




# ============================================================
# MODELOS EDITÁVEIS DE WHATSAPP
# ============================================================

def garantir_modelos_whatsapp():
    executar("""
    CREATE TABLE IF NOT EXISTS whatsapp_modelos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT UNIQUE,
        mensagem TEXT,
        ativo TEXT DEFAULT 'Sim',
        atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    modelos_padrao = modelos_whatsapp_padrao()
    for tipo, mensagem in modelos_padrao.items():
        existe = consultar("SELECT id FROM whatsapp_modelos WHERE tipo=?", (tipo,))
        if existe.empty:
            executar("""
            INSERT INTO whatsapp_modelos(tipo, mensagem, ativo)
            VALUES (?, ?, ?)
            """, (tipo, mensagem, "Sim"))


def modelos_whatsapp_padrao():
    return {
        "Orçamento enviado": (
            "Olá {nome}, tudo bem? 😊\n\n"
            "Segue seu orçamento {id} no valor de {valor}.\n\n"
            "Qualquer dúvida, estou à disposição para ajustar o que for necessário. ✨\n\n"
            "Equipe Sophi Personalizados Oficial 💜"
        ),
        "Orçamento aprovado": (
            "Olá {nome}! 😊\n\n"
            "Seu orçamento {id} foi aprovado com sucesso! 🎉\n\n"
            "Para darmos continuidade, o próximo passo é a confirmação do pagamento.\n\n"
            "Assim que confirmado, seu pedido entra na nossa fila de produção. 🛠️\n\n"
            "Valor total: {valor} 💰\n\n"
            "Aguardamos sua confirmação! 🙏\n\n"
            "Equipe Sophi Personalizados Oficial 💜"
        ),
        "Solicitar pagamento / Pix": (
            "Olá {nome}, tudo bem? 😊\n\n"
            "Para confirmar seu pedido {id}, segue o valor e os dados para pagamento:\n\n"
            "Valor total: {valor} 💰\n"
            "Pix: {pix}\n\n"
            "Após o pagamento, por gentileza envie o comprovante por aqui.\n\n"
            "Assim que confirmado, seu pedido entra na nossa fila de produção. ✨\n\n"
            "Equipe Sophi Personalizados Oficial 💜"
        ),
        "Pagamento recebido": (
            "Olá {nome}! 💳\n\n"
            "Pagamento recebido com sucesso referente ao pedido {id}.\n\n"
            "Muito obrigada pela confiança! Seu pedido agora seguirá para produção. ✨\n\n"
            "Equipe Sophi Personalizados Oficial 💜"
        ),
        "Pedido em produção": (
            "Olá {nome}! ✨\n\n"
            "Passando para avisar que seu pedido {id} já entrou em produção.\n\n"
            "Estamos preparando tudo com muito cuidado para entregar do jeitinho combinado. 🤍"
        ),
        "Pedido em embalagem": (
            "Olá {nome}! 📦\n\n"
            "Seu pedido {id} já saiu da produção e está na etapa de acabamento/embalagem.\n\n"
            "Está quase tudo pronto! ✨"
        ),
        "Pedido pronto": (
            "Olá {nome}! ✅\n\n"
            "Seu pedido {id} está pronto.\n\n"
            "Podemos combinar a retirada ou a forma de entrega conforme combinado. 🤍"
        ),
        "Saiu para entrega": (
            "Olá {nome}! 🚚\n\n"
            "Seu pedido {id} saiu para entrega.\n\n"
            "Assim que for entregue, te aviso por aqui. 🤍"
        ),
        "Pedido entregue": (
            "Olá {nome}! ✅\n\n"
            "Seu pedido {id} foi entregue.\n\n"
            "Muito obrigada pela confiança na Sophi Personalizados Oficial. Esperamos que tenha amado cada detalhe! ✨"
        ),
        "Entrega prevista": (
            "Olá {nome}! 📅\n\n"
            "Sua entrega referente ao pedido {id} está prevista para {data}.\n\n"
            "Qualquer alteração no prazo, te aviso por aqui. 🤍"
        ),
        "Pós-venda": (
            "Olá {nome}, tudo bem? 🤍\n\n"
            "Passando para saber se deu tudo certo com seu pedido.\n\n"
            "Sua opinião é muito importante para nós. Se puder, me conta se você gostou. ✨"
        ),
        "Aniversário": (
            "Olá {nome}! 🎂✨\n\n"
            "A Sophi Personalizados Oficial deseja um feliz aniversário, cheio de amor, saúde e momentos especiais.\n\n"
            "Que seu dia seja lindo e inesquecível! 💜"
        ),
        "Recompra / cliente parado": (
            "Olá {nome}, tudo bem? 🤍\n\n"
            "Passando para te mostrar que temos novidades lindas na Sophi Personalizados Oficial.\n\n"
            "Temos opções de presentes personalizados, fotos, lembranças e produtos feitos para eternizar momentos especiais. ✨"
        ),
        "Promoção / novidade": (
            "Olá {nome}! ✨\n\n"
            "Temos novidades especiais na Sophi Personalizados Oficial.\n\n"
            "Se quiser, posso te enviar algumas opções personalizadas e valores promocionais disponíveis no momento. 💜"
        ),
    }


def obter_modelo_whatsapp(tipo):
    garantir_modelos_whatsapp()
    df = consultar("SELECT mensagem FROM whatsapp_modelos WHERE tipo=?", (tipo,))
    if not df.empty:
        return str(df.iloc[0]["mensagem"] or "")
    return modelos_whatsapp_padrao().get(tipo, "Olá {nome}, tudo bem? 😊")


def salvar_modelo_whatsapp(tipo, mensagem):
    garantir_modelos_whatsapp()
    existe = consultar("SELECT id FROM whatsapp_modelos WHERE tipo=?", (tipo,))
    if existe.empty:
        executar("""
        INSERT INTO whatsapp_modelos(tipo, mensagem, ativo, atualizado_em)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (tipo, mensagem, "Sim"))
    else:
        executar("""
        UPDATE whatsapp_modelos
        SET mensagem=?, atualizado_em=CURRENT_TIMESTAMP
        WHERE tipo=?
        """, (mensagem, tipo))


def restaurar_modelo_whatsapp(tipo):
    padrao = modelos_whatsapp_padrao().get(tipo, "Olá {nome}, tudo bem? 😊")
    salvar_modelo_whatsapp(tipo, padrao)
    return padrao


def pix_empresa():
    opcoes = [
        "pix",
        "chave_pix",
        "catalogo_pix",
        "pix_principal",
        "dados_pix",
    ]
    for chave in opcoes:
        try:
            valor = obter_config(chave, "")
            if str(valor or "").strip():
                return str(valor).strip()
        except Exception:
            pass
    return "INFORME SUA CHAVE PIX NAS CONFIGURAÇÕES"


def aplicar_variaveis_mensagem(modelo, nome="", codigo="", valor="", data="", link="", pix=""):
    texto = str(modelo or "")
    texto = texto.replace("{nome}", str(nome or "cliente"))
    texto = texto.replace("{id}", str(codigo or ""))
    texto = texto.replace("{valor}", str(valor or ""))
    texto = texto.replace("{data}", str(data or ""))
    texto = texto.replace("{link}", str(link or ""))
    texto = texto.replace("{pix}", str(pix or pix_empresa()))
    try:
        return limpar_texto_whatsapp(texto)
    except Exception:
        return texto


def template_mensagem_whatsapp(tipo, cliente_nome="", codigo="", status="", data_entrega="", total="", empresa="Sophi Personalizados Oficial"):
    nome = cliente_nome or "cliente"
    codigo = codigo or ""
    total = total or ""
    data_txt = data_br(data_entrega) if data_entrega else ""
    modelo = obter_modelo_whatsapp(tipo)
    return aplicar_variaveis_mensagem(
        modelo,
        nome=nome,
        codigo=codigo,
        valor=total,
        data=data_txt,
        pix=pix_empresa(),
    )


def tipo_mensagem_por_status(status):
    status = str(status or "").strip()

    mapa = {
        "Em orçamento": "Orçamento enviado",
        "Aprovado": "Orçamento aprovado",
        "Aguardando pagamento": "Orçamento aprovado",
        "Pago": "Pagamento recebido",
        "Produção": "Pedido em produção",
        "ProduÃ§Ã£o": "Pedido em produção",
        "Embalagem": "Pedido em embalagem",
        "Pronto": "Pedido pronto",
        "Saiu para entrega": "Saiu para entrega",
        "Entregue": "Pedido entregue",
        "Finalizado": "Pedido pronto",
        "Cancelado": "Pós-venda",
    }

    return mapa.get(status, "Orçamento enviado")



# ============================================================
# UI PREMIUM — MENSAGENS WHATSAPP
# ============================================================

def aplicar_css_mensagens_whatsapp():
    st.markdown("""
    <style>
    .wpp-page {
        background: #fff;
        border: 1px solid rgba(20,20,20,0.07);
        border-radius: 26px;
        padding: 26px;
        box-shadow: 0 18px 45px rgba(0,0,0,0.06);
        margin-bottom: 22px;
    }
    .wpp-title-row {
        display:flex;
        gap:16px;
        align-items:center;
        margin-bottom: 8px;
    }
    .wpp-icon {
        width:56px;
        height:56px;
        border-radius:20px;
        background:#25D366;
        display:flex;
        align-items:center;
        justify-content:center;
        color:#fff;
        font-size:30px;
        font-weight:900;
        box-shadow: 0 14px 25px rgba(37,211,102,.24);
    }
    .wpp-title {
        font-size:34px;
        font-weight:900;
        letter-spacing:-1px;
        color:#111827;
        margin:0;
    }
    .wpp-subtitle {
        color:#667085;
        margin-top:2px;
        font-size:15px;
    }
    .wpp-card {
        background:#fff;
        border:1px solid #edf0f3;
        border-radius:22px;
        padding:22px;
        box-shadow:0 14px 32px rgba(0,0,0,.045);
        height:100%;
    }
    .wpp-card h3 {
        margin-top:0;
        color:#111827;
        font-size:21px;
    }
    .wpp-active {
        background:#ecfdf3;
        border:1px solid #abefc6;
        border-radius:16px;
        padding:14px;
        color:#027a48;
        font-weight:700;
        margin:16px 0;
    }
    .var-pill {
        display:inline-block;
        border:1px solid #d6bbfb;
        background:#f9f5ff;
        color:#6941c6;
        padding:6px 10px;
        border-radius:10px;
        margin:3px;
        font-weight:800;
        font-size:13px;
    }
    .phone-frame {
        border-radius:24px;
        overflow:hidden;
        border:1px solid #e5e7eb;
        background:#f7f0e8;
        min-height:560px;
        box-shadow:0 16px 35px rgba(0,0,0,.06);
    }
    .phone-header {
        background:#075e54;
        color:#fff;
        padding:16px;
        font-weight:800;
        display:flex;
        gap:12px;
        align-items:center;
    }
    .phone-avatar {
        width:42px;
        height:42px;
        border-radius:999px;
        background:#e8f5e9;
        display:flex;
        align-items:center;
        justify-content:center;
        color:#075e54;
        font-weight:900;
    }
    .phone-body {
        padding:28px;
        min-height:430px;
        background:
            radial-gradient(circle at 10% 20%, rgba(255,255,255,.65), transparent 16%),
            linear-gradient(135deg, #f7efe6, #f4eadf);
    }
    .bubble {
        background:#dcf8c6;
        padding:18px;
        border-radius:14px 14px 4px 14px;
        margin-left:auto;
        max-width:88%;
        white-space:pre-wrap;
        line-height:1.55;
        color:#1f2937;
        font-size:15px;
        box-shadow:0 4px 16px rgba(0,0,0,.08);
    }
    .bubble-time {
        text-align:right;
        color:#667085;
        font-size:12px;
        margin-top:8px;
    }
    .info-preview {
        background:#eff8ff;
        border:1px solid #b2ddff;
        border-radius:16px;
        padding:14px;
        color:#175cd3;
        margin-top:16px;
    }
    div[data-testid="stTextArea"] textarea {
        border-radius:16px !important;
        min-height: 320px !important;
        font-size:15px !important;
        line-height:1.55 !important;
    }
    </style>
    """, unsafe_allow_html=True)


def render_preview_whatsapp(nome, mensagem):
    nome = nome or "Cliente"
    msg = limpar_texto_whatsapp(mensagem)
    st.markdown(f"""
    <div class="phone-frame">
        <div class="phone-header">
            <div class="phone-avatar">S</div>
            <div>
                <div>Sophi Personalizados</div>
                <div style="font-size:12px;opacity:.85;font-weight:500;">online</div>
            </div>
        </div>
        <div class="phone-body">
            <div class="bubble">{msg}</div>
            <div class="bubble-time">10:30 ✓✓</div>
        </div>
    </div>
    """, unsafe_allow_html=True)





def garantir_modelo_portal_cliente():
    try:
        garantir_modelos_whatsapp()
        tipo = "Portal do Cliente"
        mensagem = (
            "Olá {nome}! 🤍\n\n"
            "Você pode acompanhar o status do seu pedido em tempo real pelo link abaixo:\n\n"
            "Pedido: {id}\n"
            "Status atual: {status}\n"
            "Valor: {valor}\n\n"
            "Acompanhar meu pedido:\n{link}\n\n"
            "Sempre que atualizarmos seu pedido no sistema, esse mesmo link será atualizado automaticamente. ✨\n\n"
            "Equipe Sophi Personalizados Oficial"
        )
        existe = consultar("SELECT id FROM whatsapp_modelos WHERE tipo=?", (tipo,))
        if existe.empty:
            salvar_modelo_whatsapp(tipo, mensagem)
    except Exception:
        pass




# ============================================================
# CORREÇÃO FINAL WHATSAPP: CATÁLOGO ONLINE + PORTAL ÚNICO
# ============================================================

APP_URL_OFICIAL = "https://sophipersonalizadosoficial.streamlit.app"

def modelo_pedido_recebido_catalogo_online():
    return (
        "🛒 Pedido recebido - Catálogo Online\n\n"
        "Olá, {nome}! 🤍\n\n"
        "Recebemos seu pedido realizado em nossa loja online e ele já chegou em nosso sistema. ✨\n\n"
        "📋 Pedido: {id}\n"
        "💰 Valor total: {valor}\n\n"
        "Para iniciarmos a produção, é necessário efetuar o pagamento via Pix:\n\n"
        "💳 Pix:\n"
        "{pix}\n\n"
        "Após realizar o pagamento, envie o comprovante por este WhatsApp para confirmarmos a transação.\n\n"
        "Assim que o pagamento for confirmado, seu pedido será liberado para produção. 💖\n\n"
        "🔗 Você também pode acompanhar o status do seu pedido pelo portal:\n"
        "{link}\n\n"
        "Equipe Sophi Personalizados Oficial 💜"
    )


def garantir_modelo_catalogo_online():
    try:
        garantir_modelos_whatsapp()
    except Exception:
        pass

    try:
        executar("""
        CREATE TABLE IF NOT EXISTS whatsapp_modelos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT UNIQUE,
            mensagem TEXT,
            ativo TEXT DEFAULT 'Sim',
            atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
    except Exception:
        pass

    try:
        existe = consultar("SELECT id FROM whatsapp_modelos WHERE tipo=?", ("Pedido recebido - Catálogo Online",))
        if existe.empty:
            executar("""
            INSERT INTO whatsapp_modelos(tipo, mensagem, ativo, atualizado_em)
            VALUES (?, ?, 'Sim', CURRENT_TIMESTAMP)
            """, ("Pedido recebido - Catálogo Online", modelo_pedido_recebido_catalogo_online()))
    except Exception:
        pass


def obter_link_portal_orcamento_seguro(orc_id):
    try:
        return gerar_link_portal_orcamento(int(orc_id), APP_URL_OFICIAL)
    except Exception:
        try:
            token = gerar_token_portal("Orçamento", int(orc_id))
        except TypeError:
            token = gerar_token_portal(int(orc_id))
        return f"{APP_URL_OFICIAL}/?portal=cliente&token={token}"


def montar_mensagem_catalogo_online(nome, codigo, valor, pix="", link=""):
    texto = modelo_pedido_recebido_catalogo_online()
    return (
        texto
        .replace("{nome}", str(nome or "cliente"))
        .replace("{id}", str(codigo or ""))
        .replace("{valor}", str(valor or ""))
        .replace("{pix}", str(pix or pix_empresa()))
        .replace("{link}", str(link or ""))
    )


def link_whatsapp_catalogo_online(numero, nome, codigo, valor, pix="", link=""):
    msg = montar_mensagem_catalogo_online(nome, codigo, valor, pix, link)
    try:
        msg = limpar_texto_whatsapp(msg)
    except Exception:
        pass
    return link_whatsapp(numero, msg)


def botao_whatsapp_catalogo_online(numero, nome, codigo, valor, pix="", link=""):
    link_wpp = link_whatsapp_catalogo_online(numero, nome, codigo, valor, pix, link)
    if link_wpp:
        st.link_button("🛒 Enviar pedido recebido - Catálogo Online", link_wpp, use_container_width=True)
    else:
        st.warning("WhatsApp não cadastrado para este cliente.")


def botao_portal_cliente_unico(numero, nome, codigo, status, valor, link):
    texto = (
        f"Olá, {nome}! 🤍\n\n"
        f"Você pode acompanhar o status do seu pedido em tempo real pelo link abaixo:\n\n"
        f"📋 Pedido: {codigo}\n"
        f"📌 Status atual: {status}\n"
        f"💰 Valor: {valor}\n\n"
        f"🔗 Portal do cliente:\n{link}\n\n"
        f"Equipe Sophi Personalizados Oficial 💜"
    )
    try:
        texto = limpar_texto_whatsapp(texto)
    except Exception:
        pass
    link_wpp = link_whatsapp(numero, texto)
    if link_wpp:
        st.link_button("🔗 Enviar Portal do Cliente", link_wpp, use_container_width=True)


def tela_mensagens_whatsapp():
    garantir_modelo_catalogo_online()
    garantir_modelo_portal_cliente()
    garantir_modelos_whatsapp()
    aplicar_css_mensagens_whatsapp()

    st.markdown("""
    <div class="wpp-page">
        <div class="wpp-title-row">
            <div class="wpp-icon">☎</div>
            <div>
                <h1 class="wpp-title">Mensagens WhatsApp</h1>
                <div class="wpp-subtitle">Edite, salve e envie mensagens prontas com emojis, Pix e preview.</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    abas = st.tabs(["Modelos por pedido", "Por cliente", "Editar modelos", "Aniversariantes", "Clientes parados"])

    with abas[0]:
        orcs = consultar("""
        SELECT id, cliente_nome, whatsapp, status, total, data_orcamento,
               data_prevista_entrega, tipo_entrega
        FROM orcamentos
        ORDER BY id DESC
        LIMIT 500
        """)

        if orcs.empty:
            st.info("Nenhum orçamento encontrado.")
        else:
            mapa = {
                f"{codigo_visual('ORC', r['id'], ano=datetime.now().year)} | {r['cliente_nome']} | {r['status']} | {real(r['total'])}": int(r["id"])
                for _, r in orcs.iterrows()
            }

            escolhido = st.selectbox("Escolha o pedido", list(mapa.keys()), key="msg_wpp_orc")
            orc_id = mapa[escolhido]
            o = orcs[orcs["id"] == orc_id].iloc[0]
            codigo = codigo_visual("ORC", int(o["id"]), ano=datetime.now().year)

            opcoes_msg_pedido = [
                "Orçamento enviado",
                "Orçamento aprovado",
                "Solicitar pagamento / Pix",
                "Pagamento recebido",
                "Pedido em produção",
                "Pedido em embalagem",
                "Pedido pronto",
                "Saiu para entrega",
                "Pedido entregue",
                "Entrega prevista",
                "Pós-venda",
                "Promoção / novidade",
                "Pedido recebido - Catálogo Online",
                "Portal do Cliente",
            ]

            try:
                sugestao_status = tipo_mensagem_por_status(o.get("status", ""))
            except Exception:
                sugestao_status = "Orçamento enviado"

            idx_sugestao = opcoes_msg_pedido.index(sugestao_status) if sugestao_status in opcoes_msg_pedido else 0

            col_editor, col_preview = st.columns([1, 1], gap="large")

            with col_editor:
                st.markdown('<div class="wpp-card">', unsafe_allow_html=True)
                st.markdown("### Modelos de Mensagens")
                st.caption("Selecione o tipo, edite o texto se quiser e salve como padrão.")

                tipo = st.selectbox(
                    "Modelo",
                    opcoes_msg_pedido,
                    index=idx_sugestao,
                    key=f"tipo_msg_pedido_{orc_id}_{o.get('status', '')}",
                )

                st.markdown(f'<div class="wpp-active">✅ Ativo — sugestão pelo status: {o.get("status", "")}</div>', unsafe_allow_html=True)

                st.markdown("### Editar mensagem")
                st.caption("Variáveis disponíveis:")
                st.markdown(
                    '<span class="var-pill">{nome}</span><span class="var-pill">{id}</span><span class="var-pill">{valor}</span><span class="var-pill">{data}</span><span class="var-pill">{pix}</span><span class="var-pill">{link}</span>',
                    unsafe_allow_html=True,
                )

                modelo_base = obter_modelo_whatsapp(tipo)
                mensagem_modelo_editada = st.text_area(
                    "Modelo salvo/editável",
                    value=modelo_base,
                    height=330,
                    key=f"modelo_wpp_edit_{tipo}",
                    help="Edite aqui e clique em Salvar modelo. Pode usar emojis do WhatsApp normalmente.",
                )

                b1, b2 = st.columns(2)
                with b1:
                    if st.button("Salvar modelo", key=f"salvar_modelo_{tipo}", use_container_width=True):
                        salvar_modelo_whatsapp(tipo, mensagem_modelo_editada)
                        st.success("Modelo salvo com sucesso.")
                        st.rerun()
                with b2:
                    if st.button("Restaurar padrão", key=f"restaurar_modelo_{tipo}", use_container_width=True):
                        restaurar_modelo_whatsapp(tipo)
                        st.success("Modelo restaurado.")
                        st.rerun()

                link_portal_cliente = gerar_link_portal_orcamento(int(orc_id), APP_URL_OFICIAL)
                status_atual_cliente = str(o.get("status", ""))
                if tipo == "Portal do Cliente":
                    mensagem_modelo_editada = obter_modelo_whatsapp("Portal do Cliente")

                mensagem_editada = aplicar_variaveis_mensagem(
                    mensagem_modelo_editada,
                    nome=o["cliente_nome"],
                    codigo=codigo,
                    valor=real(o["total"]),
                    data=data_br(o.get("data_prevista_entrega", "")) if o.get("data_prevista_entrega", "") else "",
                    pix=pix_empresa(),
                    link=link_portal_cliente,
                ).replace("{status}", status_atual_cliente)

                with st.expander("Mensagem final antes de enviar"):
                    mensagem_final_editavel = st.text_area(
                        "Mensagem final",
                        value=mensagem_editada,
                        height=220,
                        key=f"msg_final_pedido_{orc_id}_{tipo}",
                        help="Essa edição é só para este envio. Para deixar permanente, edite e salve o modelo acima.",
                    )
                if "mensagem_final_editavel" not in locals():
                    mensagem_final_editavel = mensagem_editada

                link = link_whatsapp(o["whatsapp"], mensagem_final_editavel)
                if link:
                    st.link_button("Enviar no WhatsApp", link, use_container_width=True)
                    try:
                        link_portal_unico = obter_link_portal_orcamento_seguro(int(orc_id))
                        botao_portal_cliente_unico(o["whatsapp"], o["cliente_nome"], codigo, str(o["status"]), real(o["total"]), link_portal_unico)
                        botao_whatsapp_catalogo_online(o["whatsapp"], o["cliente_nome"], codigo, real(o["total"]), pix_empresa(), link_portal_unico)
                    except Exception:
                        pass
                    
                else:
                    st.warning("Este pedido não tem WhatsApp cadastrado.")

                q1, q2, q3, q4, q5 = st.columns(5)
                atalhos = [
                    ("Pix", "Solicitar pagamento / Pix", q1),
                    ("Pago", "Pagamento recebido", q2),
                    ("Produção", "Pedido em produção", q3),
                    ("Pronto", "Pedido pronto", q4),
                    ("Entregue", "Pedido entregue", q5),
                ]
                for label_atalho, tipo_atalho, coluna_atalho in atalhos:
                    with coluna_atalho:
                        msg_atalho = template_mensagem_whatsapp(
                            tipo_atalho,
                            cliente_nome=o["cliente_nome"],
                            codigo=codigo,
                            status=o["status"],
                            data_entrega=o.get("data_prevista_entrega", ""),
                            total=real(o["total"]),
                            empresa=obter_config("nome_empresa", EMPRESA),
                        )
                        link_atalho = link_whatsapp(o["whatsapp"], msg_atalho)
                        if link_atalho:
                            st.link_button(label_atalho, link_atalho)

                with st.expander("Atualizar status do pedido"):
                    status_opcoes_rapidas = ["Em orçamento", "Aprovado", "Aguardando pagamento", "Pago", "Produção", "Embalagem", "Pronto", "Saiu para entrega", "Entregue", "Cancelado"]
                    status_atual_pedido = str(o.get("status", "Em orçamento") or "Em orçamento")
                    idx_status_rapido = status_opcoes_rapidas.index(status_atual_pedido) if status_atual_pedido in status_opcoes_rapidas else 0

                    novo_status_rapido = st.selectbox(
                        "Novo status do pedido",
                        status_opcoes_rapidas,
                        index=idx_status_rapido,
                        key=f"novo_status_msg_{orc_id}",
                    )

                    if st.button("Atualizar status do pedido", key=f"btn_status_msg_{orc_id}"):
                        executar("UPDATE orcamentos SET status=? WHERE id=?", (novo_status_rapido, int(orc_id)))
                        try:
                            aplicar_fluxo_status_orcamento(int(orc_id), novo_status_rapido)
                        except Exception:
                            pass
                        st.success("Status atualizado.")
                        try:
                            link_portal = gerar_link_portal_orcamento(int(orc_id), obter_app_url_padrao())
                            msg_portal = mensagem_portal_cliente(o["cliente_nome"], codigo, novo_status_rapido, real(o["total"]), link_portal)
                            st.session_state[f"portal_wpp_pos_status_{orc_id}"] = link_whatsapp(o["whatsapp"], msg_portal)
                        except Exception:
                            pass
                        st.rerun()

                portal_pos_status = st.session_state.get(f"portal_wpp_pos_status_{orc_id}", "")
                if portal_pos_status:
                    st.link_button("Enviar portal do cliente no WhatsApp", portal_pos_status, use_container_width=True)

                if st.button("Registrar mensagem no CRM", key="registrar_msg_pedido"):
                    try:
                        executar("""
                        INSERT INTO crm_interacoes(
                            cliente_nome, tipo, canal, descricao, status, observacoes
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            str(o["cliente_nome"]),
                            tipo,
                            "WhatsApp",
                            mensagem_final_editavel,
                            "Registrado",
                            f"Mensagem gerada pelo pedido {codigo}",
                        ))
                        st.success("Mensagem registrada no CRM.")
                    except Exception:
                        st.info("Mensagem gerada. O CRM não registrou porque a tabela de interações não está disponível.")

                st.markdown("</div>", unsafe_allow_html=True)

            with col_preview:
                st.markdown('<div class="wpp-card">', unsafe_allow_html=True)
                st.markdown("### Preview da mensagem")
                st.caption("Veja como a mensagem será enviada.")
                render_preview_whatsapp(o["cliente_nome"], mensagem_final_editavel)
                st.markdown("""
                <div class="info-preview">
                    <b>Preview</b><br>
                    Esta é uma visualização da mensagem antes de abrir no WhatsApp.
                </div>
                """, unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

    with abas[1]:
        clientes = consultar("""
        SELECT id, nome, whatsapp, aniversario, cidade
        FROM clientes
        WHERE ativo='Sim'
        ORDER BY nome
        """)

        if clientes.empty:
            st.info("Nenhum cliente cadastrado.")
        else:
            mapa_cli = {
                f"{codigo_visual('CLI', r['id'])} | {r['nome']} | {r['whatsapp'] or '-'}": int(r["id"])
                for _, r in clientes.iterrows()
            }

            escolhido = st.selectbox("Escolha o cliente", list(mapa_cli.keys()), key="msg_wpp_cliente")
            cliente_id = mapa_cli[escolhido]
            c = clientes[clientes["id"] == cliente_id].iloc[0]

            tipo = st.selectbox(
                "Tipo de mensagem",
                ["Aniversário", "Recompra / cliente parado", "Promoção / novidade", "Pós-venda"],
                key=f"tipo_msg_cliente_{cliente_id}",
            )

            col_editor, col_preview = st.columns([1, 1], gap="large")
            with col_editor:
                st.markdown('<div class="wpp-card">', unsafe_allow_html=True)
                st.markdown("### Editar modelo do cliente")
                modelo_base = obter_modelo_whatsapp(tipo)
                modelo_edit = st.text_area("Modelo", value=modelo_base, height=330, key=f"modelo_cliente_{cliente_id}_{tipo}")
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("Salvar modelo", key=f"salvar_modelo_cliente_{tipo}", use_container_width=True):
                        salvar_modelo_whatsapp(tipo, modelo_edit)
                        st.success("Modelo salvo.")
                        st.rerun()
                with b2:
                    if st.button("Restaurar padrão", key=f"restaurar_modelo_cliente_{tipo}", use_container_width=True):
                        restaurar_modelo_whatsapp(tipo)
                        st.success("Modelo restaurado.")
                        st.rerun()

                mensagem_editada = aplicar_variaveis_mensagem(modelo_edit, nome=c["nome"], pix=pix_empresa())
                link = link_whatsapp(c["whatsapp"], mensagem_editada)
                if link:
                    st.link_button("Enviar no WhatsApp", link, use_container_width=True)
                else:
                    st.warning("Este cliente não tem WhatsApp cadastrado.")
                st.markdown("</div>", unsafe_allow_html=True)

            with col_preview:
                st.markdown('<div class="wpp-card">', unsafe_allow_html=True)
                st.markdown("### Preview da mensagem")
                render_preview_whatsapp(c["nome"], mensagem_editada)
                st.markdown("</div>", unsafe_allow_html=True)

    with abas[2]:
        st.subheader("Editar todos os modelos")
        garantir_modelos_whatsapp()
        modelos = consultar("SELECT tipo, mensagem, ativo, atualizado_em FROM whatsapp_modelos ORDER BY tipo")
        if modelos.empty:
            st.info("Nenhum modelo encontrado.")
        else:
            tipo_modelo = st.selectbox("Modelo para editar", list(modelos["tipo"]), key="editar_todos_modelos")
            atual = modelos[modelos["tipo"] == tipo_modelo].iloc[0]
            texto = st.text_area("Mensagem do modelo", value=str(atual["mensagem"] or ""), height=360, key=f"modelo_global_{tipo_modelo}")
            st.caption("Use {nome}, {id}, {valor}, {data}, {pix} e {link}. Pode colar emojis do WhatsApp aqui.")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Salvar este modelo", key=f"salvar_global_{tipo_modelo}", use_container_width=True):
                    salvar_modelo_whatsapp(tipo_modelo, texto)
                    st.success("Modelo salvo.")
                    st.rerun()
            with c2:
                if st.button("Restaurar padrão deste modelo", key=f"restaurar_global_{tipo_modelo}", use_container_width=True):
                    restaurar_modelo_whatsapp(tipo_modelo)
                    st.success("Modelo restaurado.")
                    st.rerun()

    with abas[3]:
        try:
            anivers = aniversariantes_periodo()
        except Exception:
            anivers = pd.DataFrame()

        if anivers.empty:
            st.info("Nenhum aniversariante neste mês.")
        else:
            st.dataframe(formatar_valores_tabela(anivers), use_container_width=True, hide_index=True)

    with abas[4]:
        st.info("Use esta aba para campanhas de recompra e clientes sem compra recente.")
        try:
            fid = consultar("SELECT * FROM crm_fidelidade ORDER BY ultima_compra ASC")
        except Exception:
            fid = pd.DataFrame()

        if fid.empty:
            st.info("Atualize a fidelidade no CRM para gerar clientes parados.")
        else:
            fid["dias_sem_compra"] = fid["ultima_compra"].apply(dias_desde)
            st.dataframe(formatar_valores_tabela(fid), use_container_width=True, hide_index=True)

# ============================================================
# LOGIN PREMIUM
# ============================================================

def aplicar_css_login_premium():
    st.markdown("""
    <style>
    .stApp {
        background:
            radial-gradient(circle at top left, rgba(255, 212, 226, 0.45), transparent 28%),
            radial-gradient(circle at bottom right, rgba(210, 210, 210, 0.35), transparent 25%),
            linear-gradient(135deg, #fbfaf8 0%, #f5f1ec 100%) !important;
    }

    [data-testid="stSidebar"] {
        display: none !important;
    }

    header, footer, #MainMenu {
        visibility: hidden !important;
        display: none !important;
    }

    .block-container {
        max-width: 760px !important;
        padding-top: 4rem !important;
    }

    .login-wrap {
        display: flex;
        justify-content: center;
        align-items: center;
        margin-top: 10px;
    }

    .login-card {
        width: 430px;
        background: rgba(255,255,255,0.86);
        border: 1px solid rgba(20,20,20,0.08);
        border-radius: 34px;
        padding: 34px 34px 28px 34px;
        box-shadow: 0 26px 70px rgba(0,0,0,0.10);
        text-align: center;
        backdrop-filter: blur(10px);
    }

    .login-logo {
        width: 92px;
        height: 92px;
        border-radius: 28px;
        background: linear-gradient(145deg, #050505, #222);
        color: white;
        display: inline-flex;
        justify-content: center;
        align-items: center;
        font-family: Georgia, serif;
        font-size: 34px;
        font-weight: 700;
        margin-bottom: 20px;
        box-shadow: 0 18px 36px rgba(0,0,0,0.18);
    }

    .login-title {
        font-family: Georgia, serif;
        font-size: 38px;
        font-weight: 800;
        color: #161616;
        margin: 0;
        line-height: 1;
    }

    .login-sub {
        letter-spacing: 3px;
        text-transform: uppercase;
        color: #777;
        font-size: 11px;
        margin-top: 8px;
        margin-bottom: 8px;
    }

    .login-caption {
        color: #8a8a8a;
        font-size: 13px;
        margin-bottom: 22px;
    }

    div[data-testid="stTextInput"] input {
        border-radius: 16px !important;
        border: 1px solid #e6ded5 !important;
        padding: 12px 14px !important;
        background: #fff !important;
    }

    .stButton button {
        width: 100%;
        border-radius: 16px !important;
        background: linear-gradient(135deg, #050505, #1e1e1e) !important;
        color: white !important;
        border: 0 !important;
        font-weight: 800 !important;
        padding: 0.75rem 1rem !important;
        box-shadow: 0 16px 32px rgba(0,0,0,0.16);
    }
    </style>
    """, unsafe_allow_html=True)


def topo_login_premium():
    # Mantido apenas para compatibilidade. O login já possui cabeçalho próprio.
    return

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
    aplicar_css_login_premium()
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




# ============================================================
# LOJA ONLINE + PORTAL DO CLIENTE — VERSÃO FINAL
# ============================================================

APP_URL_OFICIAL = "https://sophipersonalizadosoficial.streamlit.app"

def obter_app_url_padrao():
    return APP_URL_OFICIAL


def garantir_pedidos_catalogo():
    executar("""
    CREATE TABLE IF NOT EXISTS pedidos_catalogo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER,
        produto_nome TEXT,
        categoria TEXT,
        preco REAL DEFAULT 0,
        cliente_nome TEXT,
        whatsapp TEXT,
        quantidade REAL DEFAULT 1,
        observacoes TEXT,
        status TEXT DEFAULT 'Novo',
        data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
        origem TEXT DEFAULT 'Catálogo',
        total REAL DEFAULT 0,
        codigo TEXT
    )
    """)
    for coluna, tipo_coluna in {
        "total": "REAL DEFAULT 0",
        "codigo": "TEXT",
        "origem": "TEXT DEFAULT 'Catálogo'",
    }.items():
        try:
            executar(f"ALTER TABLE pedidos_catalogo ADD COLUMN {coluna} {tipo_coluna}")
        except Exception:
            pass


def garantir_pedidos_catalogo_itens():
    garantir_pedidos_catalogo()
    executar("""
    CREATE TABLE IF NOT EXISTS pedidos_catalogo_itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pedido_catalogo_id INTEGER,
        produto_id INTEGER,
        produto_nome TEXT,
        categoria TEXT,
        quantidade REAL DEFAULT 1,
        valor_unitario REAL DEFAULT 0,
        total REAL DEFAULT 0
    )
    """)


def codigo_pedido_catalogo(pid):
    try:
        return codigo_visual("CAT", int(pid), ano=datetime.now().year)
    except Exception:
        return f"CAT-{int(pid):04d}"


def gerar_link_portal_orcamento(orc_id, base_url=None):
    base_url = (base_url or APP_URL_OFICIAL).rstrip("/")
    try:
        token = gerar_token_portal("Orçamento", int(orc_id))
    except TypeError:
        token = gerar_token_portal(int(orc_id))
    return f"{base_url}/?portal=cliente&token={token}"


def mensagem_portal_cliente(cliente_nome, codigo, status, total, link):
    nome = cliente_nome or "cliente"
    texto = (
        f"Olá {nome}! 🤍\n\n"
        f"Você pode acompanhar o status do seu pedido em tempo real pelo link abaixo:\n\n"
        f"Pedido: {codigo}\n"
        f"Status atual: {status}\n"
        f"Valor: {total}\n\n"
        f"Acompanhar meu pedido:\n{link}\n\n"
        f"Sempre que atualizarmos seu pedido no sistema, esse mesmo link será atualizado automaticamente. ✨\n\n"
        f"Equipe Sophi Personalizados Oficial"
    )
    try:
        return limpar_texto_whatsapp(texto)
    except Exception:
        return texto


def mensagem_pedido_catalogo(cliente_nome, itens_texto, total, observacoes=""):
    nome = cliente_nome or "cliente"
    obs = f"\n\nObservações: {observacoes}" if str(observacoes or "").strip() else ""
    texto = (
        f"Olá {nome}! 🤍\n\n"
        f"Recebemos sua solicitação pelo catálogo online da Sophi Personalizados Oficial:\n\n"
        f"{itens_texto}\n\n"
        f"Total estimado: {real(total)}"
        f"{obs}\n\n"
        f"Vou conferir disponibilidade, personalização e prazo e já te retorno pelo WhatsApp. ✨"
    )
    try:
        return limpar_texto_whatsapp(texto)
    except Exception:
        return texto


def consultar_produtos_catalogo_seguro():
    try:
        colunas = consultar("PRAGMA table_info(produtos)")
        nomes = set(colunas["name"].tolist()) if not colunas.empty and "name" in colunas.columns else set()
    except Exception:
        nomes = set()

    campos = []
    for campo in ["id", "nome", "categoria", "descricao", "preco_escolhido", "preco_sugerido", "foto", "ativo"]:
        if campo in nomes:
            campos.append(campo)

    if not campos:
        return pd.DataFrame()

    where = "WHERE ativo='Sim'" if "ativo" in nomes else ""
    order = "ORDER BY categoria, nome" if "categoria" in nomes else "ORDER BY nome"
    df = consultar(f"SELECT {', '.join(campos)} FROM produtos {where} {order}")

    for campo, padrao in {
        "categoria": "Personalizados",
        "descricao": "",
        "preco_escolhido": 0,
        "preco_sugerido": 0,
        "foto": "",
        "foto": "",
        "ativo": "Sim",
        "status_catalogo": "Disponível",
        "descricao_catalogo": "",
    }.items():
        if campo not in df.columns:
            df[campo] = padrao
    kits = consultar("""
    SELECT
        -id AS id,
        nome,
        categoria,
        'Kit presente personalizado completo.' AS descricao,
        preco_por AS preco_escolhido,
        preco_sugerido,
        '' AS foto,
        'Sim' AS ativo,
        status AS status_catalogo,
        catalogo AS destaque_catalogo
    FROM kits
    ORDER BY nome
    """)

    if not kits.empty:
        df = pd.concat([df, kits], ignore_index=True)
    return df


def catalogo_carrinho_inicial():
    if "catalogo_carrinho" not in st.session_state:
        st.session_state["catalogo_carrinho"] = []


def adicionar_item_carrinho_catalogo(produto_id, nome, categoria, preco, quantidade):
    catalogo_carrinho_inicial()
    carrinho = st.session_state["catalogo_carrinho"]
    for item in carrinho:
        if int(item["produto_id"]) == int(produto_id):
            item["quantidade"] = n(item["quantidade"]) + n(quantidade)
            item["total"] = n(item["quantidade"]) * n(item["preco"])
            st.session_state["catalogo_carrinho"] = carrinho
            return
    carrinho.append({
        "produto_id": int(produto_id),
        "nome": str(nome),
        "categoria": str(categoria or "Personalizados"),
        "preco": n(preco),
        "quantidade": n(quantidade),
        "total": n(preco) * n(quantidade),
    })
    st.session_state["catalogo_carrinho"] = carrinho


def remover_item_carrinho_catalogo(indice):
    catalogo_carrinho_inicial()
    carrinho = st.session_state["catalogo_carrinho"]
    if 0 <= int(indice) < len(carrinho):
        carrinho.pop(int(indice))
    st.session_state["catalogo_carrinho"] = carrinho


def limpar_carrinho_catalogo():
    st.session_state["catalogo_carrinho"] = []


def total_carrinho_catalogo():
    catalogo_carrinho_inicial()
    return sum(n(item.get("total", 0)) for item in st.session_state["catalogo_carrinho"])


def css_catalogo_loja():
    st.markdown("""
    <style>
    .shop-hero {
        background: linear-gradient(135deg, #111111 0%, #2b2b2b 55%, #f4e7f0 100%);
        border-radius: 28px;
        padding: 34px;
        color: white;
        margin-bottom: 22px;
        box-shadow: 0 20px 55px rgba(0,0,0,.18);
    }
    .shop-hero h1 {
        font-size: 38px;
        margin: 0;
        font-weight: 900;
        letter-spacing: -1px;
    }
    .shop-hero p {
        opacity: .88;
        font-size: 16px;
        max-width: 720px;
        margin-top: 8px;
    }
    .shop-badge {
        display: inline-block;
        background: rgba(255,255,255,.14);
        border: 1px solid rgba(255,255,255,.25);
        border-radius: 999px;
        padding: 8px 14px;
        margin: 5px 5px 0 0;
        font-weight: 700;
        font-size: 13px;
    }
    .shop-card {
        background: #fff;
        border: 1px solid #ececec;
        border-radius: 22px;
        padding: 18px;
        box-shadow: 0 10px 30px rgba(0,0,0,.05);
        height: 100%;
        margin-bottom: 18px;
    }
    .shop-img {
        width: 100%;
        aspect-ratio: 1 / 1;
        object-fit: cover;
        border-radius: 16px;
        display: block;
        margin-bottom: 12px;
        background: #f4f4f4;
    }
    .shop-semfoto {
        width: 100%;
        aspect-ratio: 1 / 1;
        border-radius: 16px;
        margin-bottom: 12px;
        background: #f4f4f4;
        color: #999;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        font-size: 14px;
    }
    .shop-cat {
        text-transform: uppercase;
        letter-spacing: 2px;
        font-size: 11px;
        color: #8a8a8a;
        font-weight: 800;
    }
    .shop-name {
        font-size: 22px;
        font-weight: 900;
        color: #161616;
        margin-top: 4px;
        min-height: 54px;
    }
    .shop-desc {
        color: #626262;
        font-size: 14px;
        min-height: 46px;
    }
    .shop-price {
        font-size: 28px;
        font-weight: 950;
        color: #161616;
        margin: 12px 0;
    }
    .cart-box {
        background: #fff;
        border: 1px solid #e7e2e6;
        border-radius: 24px;
        padding: 22px;
        box-shadow: 0 15px 42px rgba(0,0,0,.07);
        margin-top: 18px;
    }
    .cart-title {
        font-size: 26px;
        font-weight: 900;
        margin-bottom: 8px;
    }
    .cart-line {
        background: #fafafa;
        border: 1px solid #eee;
        border-radius: 16px;
        padding: 12px;
        margin-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)


def bloco_carrinho_catalogo_publico():
    garantir_pedidos_catalogo_itens()
    catalogo_carrinho_inicial()
    css_catalogo_loja()

    produtos = consultar_produtos_catalogo_seguro()
    st.write("DEBUG catálogo:", produtos[["id", "nome", "categoria"]])

    st.markdown("""
    <div class="shop-hero">
        <h1>Catálogo Sophi Personalizados</h1>
        <p>Escolha seus personalizados, monte seu carrinho e envie sua solicitação. A confirmação de prazo, personalização e pagamento será feita pelo WhatsApp.</p>
        <span class="shop-badge">🤍 Feito sob encomenda</span>
        <span class="shop-badge">✨ Personalizados exclusivos</span>
        <span class="shop-badge">🛒 Solicitação pelo catálogo</span>
    </div>
    """, unsafe_allow_html=True)

    if produtos.empty:
        st.info("Nenhum produto disponível para compra no momento.")
        return

    st.subheader("Produtos disponíveis")
    cols = st.columns(3)
    for idx, (_, pr) in enumerate(produtos.iterrows()):
        with cols[idx % 3]:
            preco = n(pr.get("preco_escolhido", 0)) or n(pr.get("preco_sugerido", 0))
            descricao = str(pr.get("descricao", "") or "Produto personalizado sob encomenda.")
            categoria = str(pr.get("categoria", "") or "Personalizados")
            nome = str(pr.get("nome", "Produto"))
            st.markdown(f"""
            <div class="shop-card">
                <div class="shop-cat">{categoria}</div>
                <div class="shop-name">{nome}</div>
                <div class="shop-desc">{descricao[:120]}</div>
                <div class="shop-price">{real(preco)}</div>
            </div>
            """, unsafe_allow_html=True)
            qtd = st.number_input("Qtd", min_value=1, value=1, step=1, key=f"qtd_shop_{int(pr['id'])}")
            if st.button("Adicionar ao carrinho", key=f"add_shop_{int(pr['id'])}", use_container_width=True):
                adicionar_item_carrinho_catalogo(pr["id"], nome, categoria, preco, qtd)
                st.success("Adicionado ao carrinho.")
                st.rerun()

    carrinho = st.session_state.get("catalogo_carrinho", [])
    st.markdown('<div class="cart-box">', unsafe_allow_html=True)
    st.markdown('<div class="cart-title">🛒 Seu carrinho</div>', unsafe_allow_html=True)

    if not carrinho:
        st.info("Seu carrinho está vazio. Adicione um produto ou kit acima.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    for i, item in enumerate(carrinho):
        c1, c2, c3 = st.columns([4, 2, 1])
        with c1:
            st.markdown(f'<div class="cart-line"><b>{item["nome"]}</b><br>Qtd: {item["quantidade"]} | Unitário: {real(item["preco"])}</div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f"**{real(item['total'])}**")
        with c3:
            if st.button("Remover", key=f"remover_cat_{i}"):
                remover_item_carrinho_catalogo(i)
                st.rerun()

    total = total_carrinho_catalogo()
    st.metric("Total estimado", real(total))

    if st.button("Limpar carrinho", key="limpar_carrinho_catalogo"):
        limpar_carrinho_catalogo()
        st.rerun()

    st.markdown("### Finalizar solicitação")
    with st.form("checkout_catalogo_publico"):
        nome_cliente = st.text_input("Seu nome")
        whatsapp_cliente = st.text_input("Seu WhatsApp")
        observacoes = st.text_area("Observações / personalização", placeholder="Ex: tema, nome, data, cores, prazo desejado...")
        enviar = st.form_submit_button("Enviar pedido para a Sophi")

        if enviar:
            if not nome_cliente.strip() or not whatsapp_cliente.strip():
                st.error("Preencha seu nome e WhatsApp.")
            elif not carrinho:
                st.error("Seu carrinho está vazio.")
            else:
                pedido_id = executar("""
                INSERT INTO pedidos_catalogo(
                    produto_id, produto_nome, categoria, preco, cliente_nome,
                    whatsapp, quantidade, observacoes, status, total, origem
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (None, "Pedido com múltiplos itens", "Carrinho", total, nome_cliente, whatsapp_cliente, len(carrinho), observacoes, "Novo", total, "Catálogo"))

                codigo = codigo_pedido_catalogo(int(pedido_id))
                try:
                    executar("UPDATE pedidos_catalogo SET codigo=? WHERE id=?", (codigo, int(pedido_id)))
                except Exception:
                    pass

                linhas = []
                for item in carrinho:
                    linhas.append(f"- {item['nome']} | Qtd: {item['quantidade']} | {real(item['total'])}")
                    executar("""
                    INSERT INTO pedidos_catalogo_itens(
                        pedido_catalogo_id, produto_id, produto_nome, categoria,
                        quantidade, valor_unitario, total
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (int(pedido_id), int(item["produto_id"]), str(item["nome"]), str(item.get("categoria", "")), n(item["quantidade"]), n(item["preco"]), n(item["total"])))

                limpar_carrinho_catalogo()
                st.success(f"Pedido enviado com sucesso! Código: {codigo}")
                st.info("Seu pedido chegou no ERP da Sophi. Vamos chamar você no WhatsApp para confirmar prazo e pagamento.")
    st.markdown("</div>", unsafe_allow_html=True)


def tela_pedidos_catalogo():
    st.title("Pedidos do Catálogo")
    st.write("Pedidos que os clientes enviaram pelo catálogo online.")

    garantir_pedidos_catalogo_itens()
    pedidos = consultar("SELECT * FROM pedidos_catalogo ORDER BY id DESC LIMIT 500")

    if pedidos.empty:
        st.info("Nenhum pedido recebido pelo catálogo ainda.")
        return

    if "total" not in pedidos.columns:
        pedidos["total"] = pedidos.apply(lambda r: n(r.get("preco", 0)) * n(r.get("quantidade", 1)), axis=1)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        card("Novos", str(len(pedidos[pedidos["status"] == "Novo"])))
    with c2:
        card("Em atendimento", str(len(pedidos[pedidos["status"] == "Em atendimento"])))
    with c3:
        card("Aprovados", str(len(pedidos[pedidos["status"] == "Aprovado"])))
    with c4:
        card("Valor potencial", real(pedidos["total"].apply(n).sum()))

    st.dataframe(formatar_valores_tabela(pedidos), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Aprovar / atender pedido")

    mapa = {
        f"{codigo_pedido_catalogo(r['id'])} | {r['cliente_nome']} | {real(r['total'])} | {r['status']}": int(r["id"])
        for _, r in pedidos.iterrows()
    }

    escolhido = st.selectbox("Escolha o pedido do catálogo", list(mapa.keys()))
    pid = mapa[escolhido]
    p = pedidos[pedidos["id"] == pid].iloc[0]
    itens = consultar("SELECT * FROM pedidos_catalogo_itens WHERE pedido_catalogo_id=? ORDER BY id", (int(pid),))

    total_pedido = n(p.get("total", 0))
    if total_pedido <= 0:
        total_pedido = itens["total"].apply(n).sum() if not itens.empty else n(p.get("preco", 0)) * n(p.get("quantidade", 1))

    a, b, c = st.columns(3)
    a.metric("Cliente", str(p["cliente_nome"]))
    b.metric("WhatsApp", str(p["whatsapp"]))
    c.metric("Total", real(total_pedido))

    st.write(f"**Observações:** {p.get('observacoes', '')}")

    if itens.empty:
        itens_texto = f"- {p['produto_nome']} | Qtd: {p['quantidade']} | {real(n(p['preco']) * n(p['quantidade']))}"
        st.write(itens_texto)
    else:
        st.dataframe(formatar_valores_tabela(itens), use_container_width=True, hide_index=True)
        itens_texto = "\n".join([f"- {it['produto_nome']} | Qtd: {it['quantidade']} | {real(it['total'])}" for _, it in itens.iterrows()])

    status_opcoes = ["Novo", "Em atendimento", "Aprovado", "Transformado em orçamento", "Cancelado"]
    status_atual = str(p.get("status", "Novo"))
    novo_status = st.selectbox("Status", status_opcoes, index=status_opcoes.index(status_atual) if status_atual in status_opcoes else 0)

    c1, c2, c3 = st.columns(3)

    with c1:
        if st.button("Salvar status", use_container_width=True):
            executar("UPDATE pedidos_catalogo SET status=? WHERE id=?", (novo_status, int(pid)))
            st.success("Status atualizado.")
            st.rerun()

    with c2:
        msg = mensagem_pedido_catalogo(p["cliente_nome"], itens_texto, total_pedido, p.get("observacoes", ""))
        link = link_whatsapp(p["whatsapp"], msg)
        if link:
            st.link_button("Responder no WhatsApp", link, use_container_width=True)

    with c3:
        if st.button("Transformar em orçamento", use_container_width=True):
            cliente = consultar("SELECT id FROM clientes WHERE whatsapp=? LIMIT 1", (str(p["whatsapp"]),))
            if cliente.empty:
                cliente_id = executar("INSERT INTO clientes(nome, whatsapp, ativo) VALUES (?, ?, ?)", (str(p["cliente_nome"]), str(p["whatsapp"]), "Sim"))
            else:
                cliente_id = int(cliente.iloc[0]["id"])

            orc_id = executar("""
            INSERT INTO orcamentos(cliente_id, cliente_nome, whatsapp, status, forma_pagamento, subtotal, desconto, frete, total, observacoes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (int(cliente_id), str(p["cliente_nome"]), str(p["whatsapp"]), "Em orçamento", "A combinar", total_pedido, 0, 0, total_pedido, f"Pedido criado pelo catálogo. Observações: {p.get('observacoes', '')}"))

            if itens.empty:
                total_item = n(p["preco"]) * n(p["quantidade"])
                executar("INSERT INTO orcamento_itens(orcamento_id, produto, categoria, quantidade, valor_unitario, desconto, total) VALUES (?, ?, ?, ?, ?, ?, ?)", (int(orc_id), str(p["produto_nome"]), str(p.get("categoria", "")), n(p["quantidade"]), n(p["preco"]), 0, total_item))
            else:
                for _, it in itens.iterrows():
                    executar("INSERT INTO orcamento_itens(orcamento_id, produto, categoria, quantidade, valor_unitario, desconto, total) VALUES (?, ?, ?, ?, ?, ?, ?)", (int(orc_id), str(it["produto_nome"]), str(it.get("categoria", "")), n(it["quantidade"]), n(it["valor_unitario"]), 0, n(it["total"])))

            executar("UPDATE pedidos_catalogo SET status='Transformado em orçamento' WHERE id=?", (int(pid),))
            st.success(f"Orçamento criado: {codigo_visual('ORC', int(orc_id), ano=datetime.now().year)}")
            st.rerun()


def tela_portal_cliente_admin():
    garantir_portal_cliente()

    st.title("Portal do Cliente")
    st.write("Gere o link para o cliente acompanhar o pedido em tempo real.")

    orcs = consultar("""
    SELECT id, cliente_nome, whatsapp, status, total
    FROM orcamentos
    ORDER BY id DESC
    LIMIT 500
    """)

    if orcs.empty:
        st.info("Nenhum orçamento encontrado.")
        return

    mapa = {
        f"{codigo_visual('ORC', r['id'], ano=datetime.now().year)} | {r['cliente_nome']} | {real(r['total'])} | {r['status']}": int(r["id"])
        for _, r in orcs.iterrows()
    }

    esc = st.selectbox("Escolha o orçamento", list(mapa.keys()), key="portal_cliente_orcamento")
    orc_id = mapa[esc]
    o = orcs[orcs["id"] == orc_id].iloc[0]
    codigo = codigo_visual("ORC", int(orc_id), ano=datetime.now().year)

    link = gerar_link_portal_orcamento(int(orc_id), APP_URL_OFICIAL)
    msg = mensagem_portal_cliente(o["cliente_nome"], codigo, str(o["status"]), real(o["total"]), link)

    st.markdown("### Link do portal")
    st.code(link)
    st.text_area("Mensagem pronta para enviar ao cliente", value=msg, height=190, key=f"portal_msg_pronta_{orc_id}")

    link_wpp = link_whatsapp(o["whatsapp"], msg)
    if link_wpp:
        st.link_button("Enviar portal no WhatsApp", link_wpp, use_container_width=True)
    else:
        st.warning("Este orçamento não tem WhatsApp cadastrado.")

    st.link_button("Abrir portal do cliente", link, use_container_width=True)



# ============================================================
# CORREÇÃO FINAL CATÁLOGO + MENU PEDIDOS
# ============================================================

APP_URL_OFICIAL = "https://sophipersonalizadosoficial.streamlit.app"

def obter_config_flex(chaves, padrao=""):
    for chave in chaves:
        try:
            v = obter_config(chave, "")
            if str(v or "").strip():
                return str(v).strip()
        except Exception:
            pass
    return padrao


def dados_catalogo_empresa_final():
    return {
        "nome": obter_config_flex(["nome_catalogo", "nome_empresa", "empresa"], EMPRESA),
        "subtitulo": obter_config_flex(
            ["subtitulo_catalogo", "frase_catalogo", "slogan_catalogo", "slogan"],
            "Personalizados feitos com carinho para eternizar momentos.",
        ),
        "descricao": obter_config_flex(
            ["descricao_catalogo", "texto_catalogo", "sobre_catalogo"],
            "Escolha seus personalizados, monte seu carrinho e envie sua solicitação.",
        ),
        "whatsapp": obter_config_flex(["whatsapp", "telefone", "contato_whatsapp"], "(13) 99211-2108"),
        "instagram": obter_config_flex(["instagram", "instagram_catalogo"], "@sophipersonalizadosoficial"),
        "prazo": obter_config_flex(["prazo_catalogo", "prazo_producao", "prazo"], "Prazo conforme personalização."),
        "pagamento": obter_config_flex(["pagamento_catalogo", "formas_pagamento"], "Pagamento combinado pelo WhatsApp."),
    }


def garantir_pedidos_catalogo():
    executar("""
    CREATE TABLE IF NOT EXISTS pedidos_catalogo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER,
        produto_nome TEXT,
        categoria TEXT,
        preco REAL DEFAULT 0,
        cliente_nome TEXT,
        whatsapp TEXT,
        quantidade REAL DEFAULT 1,
        observacoes TEXT,
        status TEXT DEFAULT 'Novo',
        data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
        origem TEXT DEFAULT 'Catálogo',
        total REAL DEFAULT 0,
        codigo TEXT
    )
    """)
    for coluna, tipo_coluna in {
        "total": "REAL DEFAULT 0",
        "codigo": "TEXT",
        "origem": "TEXT DEFAULT 'Catálogo'",
    }.items():
        try:
            executar(f"ALTER TABLE pedidos_catalogo ADD COLUMN {coluna} {tipo_coluna}")
        except Exception:
            pass


def garantir_pedidos_catalogo_itens():
    garantir_pedidos_catalogo()
    executar("""
    CREATE TABLE IF NOT EXISTS pedidos_catalogo_itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pedido_catalogo_id INTEGER,
        produto_id INTEGER,
        produto_nome TEXT,
        categoria TEXT,
        quantidade REAL DEFAULT 1,
        valor_unitario REAL DEFAULT 0,
        total REAL DEFAULT 0
    )
    """)


def codigo_pedido_catalogo(pid):
    try:
        return codigo_visual("CAT", int(pid), ano=datetime.now().year)
    except Exception:
        return f"CAT-{int(pid):04d}"


def consultar_produtos_catalogo_seguro():
    """Busca itens para a loja online: produtos + kits cadastrados.

    Importante: esta função NÃO muda o banco e NÃO apaga dados.
    Ela só junta os produtos e os kits em uma mesma lista para o catálogo.
    """
    # ---------- Produtos ----------
    try:
        colunas = consultar("PRAGMA table_info(produtos)")
        nomes = set(colunas["name"].tolist()) if not colunas.empty and "name" in colunas.columns else set()
    except Exception:
        nomes = set()

    campos = []
    for campo in ["id", "nome", "categoria", "descricao", "descricao_catalogo", "preco_escolhido", "preco_sugerido", "foto", "ativo", "status_catalogo"]:
        if campo in nomes:
            campos.append(campo)

    if campos:
        where = "WHERE ativo='Sim'" if "ativo" in nomes else ""
        order = "ORDER BY categoria, nome" if "categoria" in nomes else "ORDER BY nome"
        df = consultar(f"SELECT {', '.join(campos)} FROM produtos {where} {order}")
    else:
        df = pd.DataFrame()

    for campo, padrao in {
        "id": 0,
        "nome": "",
        "categoria": "Personalizados",
        "descricao": "",
        "preco_escolhido": 0,
        "preco_sugerido": 0,
        "foto": "",
        "ativo": "Sim",
        "status_catalogo": "Disponível",
        "descricao_catalogo": "",
    }.items():
        if campo not in df.columns:
            df[campo] = padrao

    # ---------- Kits ----------
    try:
        kits_raw = consultar("SELECT * FROM kits ORDER BY nome")
    except Exception:
        kits_raw = pd.DataFrame()

    if not kits_raw.empty:
        linhas_kits = []
        for _, k in kits_raw.iterrows():
            status = str(k.get("status", "Disponível") or "Disponível")
            ativo = str(k.get("ativo", "Sim") or "Sim")
            destaque = str(k.get("destaque_catalogo", "Sim") or "Sim")
            favorito = str(k.get("favorito", "Não") or "Não")

            # Só esconde se estiver claramente desativado/cancelado.
            if ativo.lower() in ["não", "nao", "no", "0", "false"]:
                continue
            if status.lower() in ["cancelado", "inativo", "indisponível", "indisponivel"]:
                continue
            # Se existir destaque_catalogo, respeita. Se não existir, mostra.
            if destaque.lower() in ["não", "nao", "no", "0", "false"]:
                continue

            preco = n(k.get("preco_promocional", 0))
            if preco <= 0:
                preco = n(k.get("preco_por", 0))
            if preco <= 0:
                preco = n(k.get("preco_sugerido", 0))
            if preco <= 0:
                preco = n(k.get("custo_total", 0))

            descricao = str(k.get("descricao", "") or "").strip()
            if not descricao:
                try:
                    itens_json = str(k.get("itens_json", "") or "").strip()
                    if itens_json:
                        itens = json.loads(itens_json)
                        if isinstance(itens, list):
                            nomes_itens = []
                            for it in itens:
                                if isinstance(it, dict):
                                    nomes_itens.append(str(it.get("nome") or it.get("produto") or it.get("item") or "Item"))
                                else:
                                    nomes_itens.append(str(it))
                            descricao = "Contém: " + ", ".join(nomes_itens)
                except Exception:
                    pass
            if not descricao:
                descricao = "Kit presente personalizado completo."

            linhas_kits.append({
                "id": -abs(int(k.get("id", 0) or 0)),  # ID negativo para não misturar com produto
                "nome": str(k.get("nome", "Kit") or "Kit"),
                "categoria": str(k.get("categoria", "Kits Presente") or "Kits Presente"),
                "descricao": descricao,
                "descricao_catalogo": descricao,
                "preco_escolhido": preco,
                "preco_sugerido": n(k.get("preco_sugerido", preco)),
                "foto": str(k.get("foto", "") or ""),
                "ativo": "Sim",
                "status_catalogo": "Disponível",
                "destaque_catalogo": "Sim",
                "tipo_item": "kit",
            })

        if linhas_kits:
            kits_df = pd.DataFrame(linhas_kits)
            if "tipo_item" not in df.columns:
                df["tipo_item"] = "produto"
            df = pd.concat([df, kits_df], ignore_index=True)

    if "tipo_item" not in df.columns:
        df["tipo_item"] = "produto"

    return df

def catalogo_carrinho_inicial():
    if "catalogo_carrinho" not in st.session_state:
        st.session_state["catalogo_carrinho"] = []


def adicionar_item_carrinho_catalogo(produto_id, nome, categoria, preco, quantidade):
    catalogo_carrinho_inicial()
    carrinho = st.session_state["catalogo_carrinho"]
    for item in carrinho:
        if int(item["produto_id"]) == int(produto_id):
            item["quantidade"] = n(item["quantidade"]) + n(quantidade)
            item["total"] = n(item["quantidade"]) * n(item["preco"])
            st.session_state["catalogo_carrinho"] = carrinho
            return
    carrinho.append({
        "produto_id": int(produto_id),
        "nome": str(nome),
        "categoria": str(categoria or "Personalizados"),
        "preco": n(preco),
        "quantidade": n(quantidade),
        "total": n(preco) * n(quantidade),
    })
    st.session_state["catalogo_carrinho"] = carrinho


def remover_item_carrinho_catalogo(indice):
    catalogo_carrinho_inicial()
    carrinho = st.session_state["catalogo_carrinho"]
    if 0 <= int(indice) < len(carrinho):
        carrinho.pop(int(indice))
    st.session_state["catalogo_carrinho"] = carrinho


def limpar_carrinho_catalogo():
    st.session_state["catalogo_carrinho"] = []


def total_carrinho_catalogo():
    catalogo_carrinho_inicial()
    return sum(n(item.get("total", 0)) for item in st.session_state["catalogo_carrinho"])


def css_catalogo_loja():
    st.markdown("""
    <style>
    .main .block-container {max-width: 1080px; padding-top: 1.5rem;}
    .shop-hero {
        max-width: 900px;
        margin: 0 auto 28px auto;
        text-align: center;
        background: linear-gradient(135deg, #111 0%, #2b2b2b 70%, #f4edf2 100%);
        border-radius: 28px;
        padding: 38px 26px;
        color: white;
        box-shadow: 0 18px 55px rgba(0,0,0,.18);
    }
    .shop-logo-fallback {
        width: 86px;height:86px;border-radius:50%;background:white;color:#111;
        display:flex;align-items:center;justify-content:center;font-size:40px;font-weight:900;
        margin:0 auto 16px auto;
    }
    .shop-hero h1 {font-size:36px;margin:0;font-weight:950;letter-spacing:-1px;}
    .shop-hero p {opacity:.92;font-size:16px;max-width:720px;margin:10px auto 0 auto;}
    .shop-badges {margin-top:18px;display:flex;gap:8px;flex-wrap:wrap;justify-content:center;}
    .shop-badge {display:inline-block;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.25);border-radius:999px;padding:8px 14px;font-weight:700;font-size:13px;}
    .shop-card {background:#fff;border:1px solid #ececec;border-radius:22px;padding:18px;box-shadow:0 10px 30px rgba(0,0,0,.05);height:100%;margin-bottom:18px;}
    .shop-cat {text-transform:uppercase;letter-spacing:2px;font-size:11px;color:#8a8a8a;font-weight:800;}
    .shop-name {font-size:22px;font-weight:900;color:#161616;margin-top:4px;min-height:54px;}
    .shop-desc {color:#626262;font-size:14px;min-height:46px;}
    .shop-price {font-size:28px;font-weight:950;color:#161616;margin:12px 0;}
    .cart-box {max-width:900px;margin:24px auto 0 auto;background:#fff;border:1px solid #e7e2e6;border-radius:24px;padding:22px;box-shadow:0 15px 42px rgba(0,0,0,.07);}
    .cart-title {font-size:26px;font-weight:900;margin-bottom:8px;text-align:center;}
    .cart-line {background:#fafafa;border:1px solid #eee;border-radius:16px;padding:12px;margin-bottom:10px;}
    </style>
    """, unsafe_allow_html=True)


def html_hero_catalogo_empresa():
    d = dados_catalogo_empresa_final()
    badges = []
    if d["whatsapp"]:
        badges.append(f"WhatsApp: {d['whatsapp']}")
    if d["instagram"]:
        badges.append(f"Instagram: {d['instagram']}")
    if d["prazo"]:
        badges.append(f"Prazo: {d['prazo']}")
    if d["pagamento"]:
        badges.append(f"Pagamento: {d['pagamento']}")
    badges_html = "".join([f'<span class="shop-badge">{b}</span>' for b in badges])
    return f"""
    <div class="shop-hero">
        <div class="shop-logo-fallback">S</div>
        <h1>{d['nome']}</h1>
        <p><b>{d['subtitulo']}</b></p>
        <p>{d['descricao']}</p>
        <div class="shop-badges">{badges_html}</div>
    </div>
    """


def tela_catalogo_publico_cliente():
    garantir_pedidos_catalogo_itens()
    css_catalogo_loja()
    catalogo_carrinho_inicial()
    produtos = consultar_produtos_catalogo_seguro()

    st.markdown(html_hero_catalogo_empresa(), unsafe_allow_html=True)

    if produtos.empty:
        st.info("Nenhum produto disponível no catálogo no momento.")
        return

    st.markdown("<div class='produtos-wrap'><h2 style='text-align:center;margin:20px 0 22px 0;'>Produtos disponíveis</h2></div>", unsafe_allow_html=True)
    cols = st.columns(3)
    for idx, (_, pr) in enumerate(produtos.iterrows()):
        with cols[idx % 3]:
            preco = n(pr.get("preco_escolhido", 0)) or n(pr.get("preco_sugerido", 0))
            descricao = str(pr.get("descricao_catalogo", "") or pr.get("descricao", "") or "Produto personalizado sob encomenda.")
            categoria = str(pr.get("categoria", "") or "Personalizados")
            nome = str(pr.get("nome", "Produto"))
            foto_src = foto_produto_data_uri(pr.get("foto", ""))
            foto_html = f'<img class="shop-img" src="{foto_src}" alt="{nome}">' if foto_src else '<div class="shop-semfoto">Sem foto</div>'
            tipo_item = str(pr.get("tipo_item", "produto") or "produto")
            descricao_card = descricao if tipo_item == "kit" else descricao[:140]
            botao_label = "Adicionar kit ao carrinho" if tipo_item == "kit" else "Adicionar ao carrinho"
            msg_sucesso = "Kit adicionado ao carrinho." if tipo_item == "kit" else "Produto adicionado ao carrinho."

            st.markdown(f"""
            <div class="shop-card">
                {foto_html}
                <div class="shop-cat">{categoria}</div>
                <div class="shop-name">{nome}</div>
                <div class="shop-desc">{descricao_card}</div>
                <div class="shop-price">{real(preco)}</div>
            </div>
            """, unsafe_allow_html=True)
            qtd = st.number_input("Quantidade", min_value=1, value=1, step=1, key=f"qtd_shop_{int(pr['id'])}")
            if st.button(botao_label, key=f"add_shop_{int(pr['id'])}", use_container_width=True):
                adicionar_item_carrinho_catalogo(pr["id"], nome, categoria, preco, qtd)
                st.success(msg_sucesso)
                st.rerun()

    carrinho = st.session_state.get("catalogo_carrinho", [])
    st.markdown('<div class="cart-box">', unsafe_allow_html=True)
    st.markdown('<div class="cart-title">🛒 Seu carrinho</div>', unsafe_allow_html=True)

    if not carrinho:
        st.info("Seu carrinho está vazio. Adicione um produto ou kit acima.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    for i, item in enumerate(carrinho):
        c1, c2, c3 = st.columns([4, 2, 1])
        with c1:
            st.markdown(f'<div class="cart-line"><b>{item["nome"]}</b><br>Qtd: {item["quantidade"]} | Unitário: {real(item["preco"])}</div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f"**{real(item['total'])}**")
        with c3:
            if st.button("Remover", key=f"remover_cat_{i}"):
                remover_item_carrinho_catalogo(i)
                st.rerun()

    total = total_carrinho_catalogo()
    st.metric("Total estimado", real(total))

    if st.button("Limpar carrinho", key="limpar_carrinho_catalogo"):
        limpar_carrinho_catalogo()
        st.rerun()

    st.markdown("### Finalizar solicitação")
    with st.form("checkout_catalogo_publico"):
        nome_cliente = st.text_input("Seu nome")
        whatsapp_cliente = st.text_input("Seu WhatsApp")
        observacoes = st.text_area("Observações / personalização", placeholder="Ex: tema, nome, data, cores, prazo desejado...")
        enviar = st.form_submit_button("Enviar pedido para a Sophi")
        if enviar:
            if not nome_cliente.strip() or not whatsapp_cliente.strip():
                st.error("Preencha seu nome e WhatsApp.")
            elif not carrinho:
                st.error("Seu carrinho está vazio.")
            else:
                pedido_id = executar("""
                INSERT INTO pedidos_catalogo(produto_id, produto_nome, categoria, preco, cliente_nome, whatsapp, quantidade, observacoes, status, total, origem)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (None, "Pedido com múltiplos itens", "Carrinho", total, nome_cliente, whatsapp_cliente, len(carrinho), observacoes, "Novo", total, "Catálogo"))
                codigo = codigo_pedido_catalogo(int(pedido_id))
                try:
                    executar("UPDATE pedidos_catalogo SET codigo=? WHERE id=?", (codigo, int(pedido_id)))
                except Exception:
                    pass
                for item in carrinho:
                    executar("""
                    INSERT INTO pedidos_catalogo_itens(pedido_catalogo_id, produto_id, produto_nome, categoria, quantidade, valor_unitario, total)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (int(pedido_id), int(item["produto_id"]), str(item["nome"]), str(item.get("categoria", "")), n(item["quantidade"]), n(item["preco"]), n(item["total"])))
                limpar_carrinho_catalogo()
                st.success(f"Pedido enviado com sucesso! Código: {codigo}")
                st.info("Seu pedido chegou no ERP da Sophi. Vamos chamar você no WhatsApp para confirmar prazo e pagamento.")
    st.markdown("</div>", unsafe_allow_html=True)


def tela_pedidos_catalogo():
    st.title("Pedidos do Catálogo")
    st.write("Pedidos enviados pelos clientes no catálogo online.")

    garantir_pedidos_catalogo_itens()
    pedidos = consultar("SELECT * FROM pedidos_catalogo ORDER BY id DESC LIMIT 500")
    if pedidos.empty:
        st.info("Nenhum pedido recebido pelo catálogo ainda.")
        return

    if "total" not in pedidos.columns:
        pedidos["total"] = pedidos.apply(lambda r: n(r.get("preco", 0)) * n(r.get("quantidade", 1)), axis=1)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Novos", len(pedidos[pedidos["status"] == "Novo"]))
    c2.metric("Em atendimento", len(pedidos[pedidos["status"] == "Em atendimento"]))
    c3.metric("Aprovados", len(pedidos[pedidos["status"] == "Aprovado"]))
    c4.metric("Potencial", real(pedidos["total"].apply(n).sum()))

    st.dataframe(formatar_valores_tabela(pedidos), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Atender pedido")

    mapa = {f"{codigo_pedido_catalogo(r['id'])} | {r['cliente_nome']} | {real(r.get('total', 0))} | {r['status']}": int(r["id"]) for _, r in pedidos.iterrows()}
    escolhido = st.selectbox("Escolha o pedido", list(mapa.keys()))
    pid = mapa[escolhido]
    p = pedidos[pedidos["id"] == pid].iloc[0]
    itens = consultar("SELECT * FROM pedidos_catalogo_itens WHERE pedido_catalogo_id=? ORDER BY id", (int(pid),))

    total_pedido = n(p.get("total", 0))
    if total_pedido <= 0:
        total_pedido = itens["total"].apply(n).sum() if not itens.empty else n(p.get("preco", 0)) * n(p.get("quantidade", 1))

    st.write(f"**Cliente:** {p['cliente_nome']}")
    st.write(f"**WhatsApp:** {p['whatsapp']}")
    st.write(f"**Observações:** {p.get('observacoes', '')}")
    st.metric("Total do pedido", real(total_pedido))

    if itens.empty:
        st.write(f"- {p['produto_nome']} | Qtd: {p['quantidade']} | {real(n(p['preco']) * n(p['quantidade']))}")
    else:
        st.dataframe(formatar_valores_tabela(itens), use_container_width=True, hide_index=True)

    opcoes = ["Novo", "Em atendimento", "Aprovado", "Transformado em orçamento", "Cancelado"]
    status_atual = str(p.get("status", "Novo"))
    novo_status = st.selectbox("Status", opcoes, index=opcoes.index(status_atual) if status_atual in opcoes else 0)

    if st.button("Salvar status", use_container_width=True):
        executar("UPDATE pedidos_catalogo SET status=? WHERE id=?", (novo_status, int(pid)))
        st.success("Status atualizado.")
        st.rerun()

    st.divider()
    if st.button("Transformar em orçamento", use_container_width=True):
        # Cria/usa cliente pelo WhatsApp
        cliente_id = None
        try:
            cliente_df = consultar("SELECT id FROM clientes WHERE whatsapp=? LIMIT 1", (str(p.get("whatsapp", "") or ""),))
            if not cliente_df.empty:
                cliente_id = int(cliente_df.iloc[0]["id"])
        except Exception:
            cliente_df = pd.DataFrame()

        if cliente_id is None:
            cliente_id = executar(
                "INSERT INTO clientes(nome, whatsapp, ativo) VALUES (?, ?, ?)",
                (str(p.get("cliente_nome", "") or "Cliente do catálogo"), str(p.get("whatsapp", "") or ""), "Sim")
            )

        obs_orc = f"Pedido vindo do catálogo. Código: {codigo_pedido_catalogo(int(pid))}. Observações: {p.get('observacoes', '')}"

        orc_id = executar("""
        INSERT INTO orcamentos(
            cliente_id, cliente_nome, whatsapp, status, forma_pagamento,
            subtotal, desconto, frete, total, observacoes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            int(cliente_id),
            str(p.get("cliente_nome", "") or "Cliente do catálogo"),
            str(p.get("whatsapp", "") or ""),
            "Em orçamento",
            "A combinar",
            n(total_pedido),
            0,
            0,
            n(total_pedido),
            obs_orc
        ))

        if itens.empty:
            executar("""
            INSERT INTO orcamento_itens(
                orcamento_id, produto, categoria, quantidade,
                valor_unitario, desconto, total
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                int(orc_id),
                str(p.get("produto_nome", "Pedido do catálogo")),
                str(p.get("categoria", "")),
                n(p.get("quantidade", 1)),
                n(p.get("preco", 0)),
                0,
                n(total_pedido)
            ))
        else:
            for _, it in itens.iterrows():
                executar("""
                INSERT INTO orcamento_itens(
                    orcamento_id, produto, categoria, quantidade,
                    valor_unitario, desconto, total
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    int(orc_id),
                    str(it.get("produto_nome", "")),
                    str(it.get("categoria", "")),
                    n(it.get("quantidade", 1)),
                    n(it.get("valor_unitario", 0)),
                    0,
                    n(it.get("total", 0))
                ))

        try:
            executar("UPDATE pedidos_catalogo SET status=? WHERE id=?", ("Transformado em orçamento", int(pid)))
        except Exception:
            pass

        st.success(f"Pedido transformado em orçamento: ORC-{int(orc_id):04d}")
        st.info("Agora ele aparece na aba Orçamentos e também pode ser usado na aba Mensagens WhatsApp.")
        st.rerun()




# ============================================================
# CORREÇÃO LOGO CATÁLOGO + LAYOUT PRODUTOS
# ============================================================

def logo_catalogo_data_uri_corrigida():
    caminhos = []

    # tenta pegar o arquivo salvo nas configurações
    for chave in ["logo_catalogo", "catalogo_logo", "logo_empresa", "empresa_logo", "logo", "caminho_logo", "logo_atual"]:
        try:
            v = obter_config(chave, "")
            if str(v or "").strip():
                valor = str(v).strip()
                caminhos.append(Path(valor))
                caminhos.append(UPLOAD_DIR / valor)
                caminhos.append(Path("uploads") / valor)
        except Exception:
            pass

    # pega qualquer logo/imagem recente do uploads
    try:
        for ext in ["*.png", "*.jpg", "*.jpeg", "*.webp"]:
            caminhos.extend(sorted(UPLOAD_DIR.glob(ext), key=lambda p: p.stat().st_mtime, reverse=True))
    except Exception:
        pass

    caminhos.extend([
        UPLOAD_DIR / "sophi_app_icon.png",
        UPLOAD_DIR / "logo_catalogo.png",
        UPLOAD_DIR / "logo_empresa.png",
        UPLOAD_DIR / "logo.png",
        Path("assets") / "logo.png",
    ])

    for c in caminhos:
        try:
            if c.exists() and c.is_file() and c.stat().st_size > 0:
                import base64
                ext = c.suffix.lower().replace(".", "")
                if ext == "jpg":
                    ext = "jpeg"
                if ext not in ["png", "jpeg", "webp"]:
                    ext = "png"
                data = base64.b64encode(c.read_bytes()).decode("utf-8")
                return f"data:image/{ext};base64,{data}"
        except Exception:
            pass
    return ""


def css_catalogo_loja():
    st.markdown("""
    <style>
    .main .block-container {
        max-width: 1100px;
        padding-top: 1.5rem;
    }
    .shop-hero {
        max-width: 880px;
        margin: 0 auto 30px auto;
        text-align: center;
        background: linear-gradient(135deg, #101010 0%, #242424 70%, #eee4eb 100%);
        border-radius: 28px;
        padding: 34px 26px 30px 26px;
        color: white;
        box-shadow: 0 18px 55px rgba(0,0,0,.18);
    }
    .shop-logo {
        width: 118px;
        height: 118px;
        object-fit: contain;
        border-radius: 50%;
        background: #fff;
        padding: 8px;
        margin: 0 auto 16px auto;
        display: block;
        box-shadow: 0 10px 28px rgba(255,255,255,.18);
    }
    .shop-logo-fallback {
        width: 92px;
        height: 92px;
        border-radius: 50%;
        background: #fff;
        color: #111;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 42px;
        font-weight: 900;
        margin: 0 auto 16px auto;
    }
    .shop-hero h1 {
        font-size: 34px;
        margin: 0;
        font-weight: 950;
        letter-spacing: -1px;
    }
    .shop-hero p {
        opacity: .92;
        font-size: 15px;
        max-width: 720px;
        margin: 10px auto 0 auto;
    }
    .shop-badges {
        margin-top: 18px;
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        justify-content: center;
    }
    .shop-badge {
        display: inline-block;
        background: rgba(255,255,255,.14);
        border: 1px solid rgba(255,255,255,.25);
        border-radius: 999px;
        padding: 8px 13px;
        font-weight: 700;
        font-size: 12px;
    }
    .produtos-wrap {
        max-width: 980px;
        margin: 0 auto;
    }
    .shop-card {
        background: #fff;
        border: 1px solid #ececec;
        border-radius: 22px;
        padding: 18px;
        box-shadow: 0 10px 30px rgba(0,0,0,.05);
        min-height: 210px;
        margin-bottom: 18px;
        overflow: hidden;
    }
    .shop-img {
        width: 100%;
        aspect-ratio: 1 / 1;
        object-fit: cover;
        border-radius: 16px;
        display: block;
        margin-bottom: 12px;
        background: #f4f4f4;
    }
    .shop-semfoto {
        width: 100%;
        aspect-ratio: 1 / 1;
        border-radius: 16px;
        margin-bottom: 12px;
        background: #f4f4f4;
        color: #999;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        font-size: 14px;
    }
    .shop-cat {
        text-transform: uppercase;
        letter-spacing: 2px;
        font-size: 11px;
        color: #8a8a8a;
        font-weight: 800;
    }
    .shop-name {
        font-size: 22px;
        font-weight: 900;
        color: #161616;
        margin-top: 4px;
        min-height: 34px;
        word-break: break-word;
    }
    .shop-desc {
        color: #626262;
        font-size: 14px;
        min-height: 42px;
        word-break: break-word;
    }
    .shop-price {
        font-size: 28px;
        font-weight: 950;
        color: #161616;
        margin: 12px 0 4px 0;
    }
    .cart-box {
        max-width: 880px;
        margin: 24px auto 0 auto;
        background: #fff;
        border: 1px solid #e7e2e6;
        border-radius: 24px;
        padding: 22px;
        box-shadow: 0 15px 42px rgba(0,0,0,.07);
    }
    .cart-title {
        font-size: 26px;
        font-weight: 900;
        margin-bottom: 8px;
        text-align: center;
    }
    .cart-line {
        background: #fafafa;
        border: 1px solid #eee;
        border-radius: 16px;
        padding: 12px;
        margin-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)


def html_hero_catalogo_empresa():
    d = dados_catalogo_empresa_final()
    logo = logo_catalogo_data_uri_corrigida()
    if logo:
        logo_html = f'<img class="shop-logo" src="{logo}">'
    else:
        logo_html = '<div class="shop-logo-fallback">S</div>'

    badges = []
    if d["whatsapp"]:
        badges.append(f"WhatsApp: {d['whatsapp']}")
    if d["instagram"]:
        badges.append(f"Instagram: {d['instagram']}")
    if d["prazo"]:
        badges.append(f"Prazo: {d['prazo']}")
    if d["pagamento"]:
        badges.append(f"Pagamento: {d['pagamento']}")

    badges_html = "".join([f'<span class="shop-badge">{b}</span>' for b in badges])

    return f"""
    <div class="shop-hero">
        {logo_html}
        <h1>{d['nome']}</h1>
        <p><b>{d['subtitulo']}</b></p>
        <p>{d['descricao']}</p>
        <div class="shop-badges">{badges_html}</div>
    </div>
    """



# ============================================================
# NOTIFICAÇÃO + WHATSAPP PEDIDOS DO CATÁLOGO
# ============================================================

def notificar_pedidos_catalogo_novos():
    try:
        garantir_pedidos_catalogo()
        df = consultar("SELECT COUNT(*) AS total FROM pedidos_catalogo WHERE status='Novo'")
        total = int(df.iloc[0]["total"]) if not df.empty else 0
        if total > 0:
            st.sidebar.warning(f"🛒 {total} pedido(s) novo(s) do catálogo")
            try:
                st.toast(f"Você tem {total} pedido(s) novo(s) do catálogo 🛒")
            except Exception:
                pass
    except Exception:
        pass


def mensagem_catalogo_recebido(nome, codigo, itens_texto, total):
    texto = (
        f"Olá {nome}! 🤍\n\n"
        f"Recebemos seu pedido pelo nosso catálogo online.\n\n"
        f"Pedido: {codigo}\n"
        f"Itens:\n{itens_texto}\n\n"
        f"Total estimado: {real(total)}\n\n"
        f"Vamos conferir os detalhes, personalização e prazo para te confirmar tudo por aqui. ✨"
    )
    try:
        return limpar_texto_whatsapp(texto)
    except Exception:
        return texto


def mensagem_catalogo_aprovacao(nome, codigo, total):
    texto = (
        f"Olá {nome}! 🤍\n\n"
        f"Seu pedido {codigo} foi conferido e está pronto para aprovação.\n\n"
        f"Valor total: {real(total)}\n\n"
        f"Confirmando por aqui, seguimos para a etapa de pagamento e produção. ✨"
    )
    try:
        return limpar_texto_whatsapp(texto)
    except Exception:
        return texto


def mensagem_catalogo_pagamento(nome, codigo, total):
    texto = (
        f"Olá {nome}! 🤍\n\n"
        f"Para darmos andamento ao pedido {codigo}, falta apenas a confirmação do pagamento.\n\n"
        f"Valor total: {real(total)}\n\n"
        f"Assim que confirmado, seu pedido entra na nossa fila de produção. ✨"
    )
    try:
        return limpar_texto_whatsapp(texto)
    except Exception:
        return texto


def mensagem_catalogo_producao(nome, codigo):
    texto = (
        f"Olá {nome}! 🤍\n\n"
        f"Seu pedido {codigo} já foi encaminhado para produção.\n\n"
        f"Vamos te mantendo informado(a) sobre as próximas etapas por aqui. ✨"
    )
    try:
        return limpar_texto_whatsapp(texto)
    except Exception:
        return texto


def mensagem_catalogo_pronto(nome, codigo):
    texto = (
        f"Olá {nome}! 🤍\n\n"
        f"Seu pedido {codigo} está pronto! ✨\n\n"
        f"Agora vamos combinar a retirada ou entrega da melhor forma para você."
    )
    try:
        return limpar_texto_whatsapp(texto)
    except Exception:
        return texto


def botoes_whatsapp_pedido_catalogo(p, codigo, itens_texto, total_pedido):
    numero = p.get("whatsapp", "")
    nome = p.get("cliente_nome", "cliente")

    mensagens = {
        "Recebemos seu pedido": mensagem_catalogo_recebido(nome, codigo, itens_texto, total_pedido),
        "Enviar para aprovação": mensagem_catalogo_aprovacao(nome, codigo, total_pedido),
        "Solicitar pagamento": mensagem_catalogo_pagamento(nome, codigo, total_pedido),
        "Pedido em produção": mensagem_catalogo_producao(nome, codigo),
        "Pedido pronto": mensagem_catalogo_pronto(nome, codigo),
    }

    st.markdown("### Mensagens prontas no WhatsApp")
    cols = st.columns(2)
    for i, (label, msg) in enumerate(mensagens.items()):
        link = link_whatsapp(numero, msg)
        with cols[i % 2]:
            if link:
                st.link_button(label, link, use_container_width=True)
            else:
                st.warning("WhatsApp não cadastrado.")




# ============================================================
# AJUSTE FINAL — DADOS COMPLETOS DO CATÁLOGO + MSG PEDIDO
# ============================================================

def obter_config_flex(chaves, padrao=""):
    for chave in chaves:
        try:
            valor = obter_config(chave, "")
            if str(valor or "").strip():
                return str(valor).strip()
        except Exception:
            pass
    return padrao


def dados_catalogo_empresa_final():
    return {
        "nome": obter_config_flex(["nome_catalogo", "nome_empresa", "empresa"], EMPRESA),
        "subtitulo": obter_config_flex(
            ["subtitulo_catalogo", "frase_catalogo", "slogan_catalogo", "slogan"],
            "Personalizados feitos com carinho para eternizar momentos.",
        ),
        "descricao": obter_config_flex(
            ["descricao_catalogo", "texto_catalogo", "sobre_catalogo"],
            "Escolha seus personalizados, monte seu carrinho e envie sua solicitação.",
        ),
        "whatsapp": obter_config_flex(["whatsapp", "telefone", "contato_whatsapp"], "(13) 99211-2108"),
        "instagram": obter_config_flex(["instagram", "instagram_catalogo"], "@sophipersonalizadosoficial"),
        "email": obter_config_flex(["email", "email_empresa", "email_catalogo"], ""),
        "endereco": obter_config_flex(["endereco", "endereco_empresa", "endereco_catalogo"], ""),
        "pix": obter_config_flex(["pix", "chave_pix", "pix_empresa", "chave_pix_empresa"], ""),
        "prazo": obter_config_flex(["prazo_catalogo", "prazo_producao", "prazo"], "Prazo conforme personalização."),
        "pagamento": obter_config_flex(["pagamento_catalogo", "formas_pagamento"], "Pagamento combinado pelo WhatsApp."),
        "retirada": obter_config_flex(["retirada", "local_retirada", "retirada_catalogo"], ""),
        "entrega": obter_config_flex(["entrega", "entrega_catalogo", "taxa_entrega"], ""),
    }


def html_hero_catalogo_empresa():
    d = dados_catalogo_empresa_final()

    # usa a função de logo já existente, se houver
    logo = ""
    try:
        logo = logo_catalogo_data_uri_corrigida()
    except Exception:
        try:
            logo = logo_catalogo_data_uri()
        except Exception:
            logo = ""

    if logo:
        logo_html = f'<img class="shop-logo" src="{logo}">'
    else:
        logo_html = '<div class="shop-logo-fallback">S</div>'

    badges = []
    if d["whatsapp"]:
        badges.append(f"WhatsApp: {d['whatsapp']}")
    if d["instagram"]:
        badges.append(f"Instagram: {d['instagram']}")
    if d["email"]:
        badges.append(f"E-mail: {d['email']}")
    if d["endereco"]:
        badges.append(f"Endereço: {d['endereco']}")
    if d["pix"]:
        badges.append(f"Pix: {d['pix']}")
    if d["prazo"]:
        badges.append(f"Prazo: {d['prazo']}")
    if d["pagamento"]:
        badges.append(f"Pagamento: {d['pagamento']}")
    if d["retirada"]:
        badges.append(f"Retirada: {d['retirada']}")
    if d["entrega"]:
        badges.append(f"Entrega: {d['entrega']}")

    badges_html = "".join([f'<span class="shop-badge">{b}</span>' for b in badges])

    return f"""
    <div class="shop-hero">
        {logo_html}
        <h1>{d['nome']}</h1>
        <p><b>{d['subtitulo']}</b></p>
        <p>{d['descricao']}</p>
        <div class="shop-badges">{badges_html}</div>
    </div>
    """


def mensagem_catalogo_recebido(nome, codigo, itens_texto, total):
    texto = (
        f"Olá {nome}! 🤍\n\n"
        f"Recebemos seu pedido pelo nosso catálogo online. ✨\n\n"
        f"Pedido: {codigo}\n"
        f"Itens:\n{itens_texto}\n\n"
        f"Total estimado: {real(total)}\n\n"
        f"Vamos conferir os detalhes, personalização e prazo. Em seguida te retorno por aqui para confirmação, pagamento e produção.\n\n"
        f"Equipe Sophi Personalizados Oficial"
    )
    try:
        return limpar_texto_whatsapp(texto)
    except Exception:
        return texto


def botao_recebemos_pedido_catalogo(p, codigo, itens_texto, total_pedido):
    st.markdown("### WhatsApp do cliente")
    msg_recebido = mensagem_catalogo_recebido(
        p.get("cliente_nome", "cliente"),
        codigo,
        itens_texto,
        total_pedido,
    )
    link_recebido = link_whatsapp(p.get("whatsapp", ""), msg_recebido)
    if link_recebido:
        st.link_button("Enviar: recebemos seu pedido", link_recebido, use_container_width=True)
    else:
        st.warning("Esse pedido não tem WhatsApp cadastrado.")



# ============================================================
# FINAL: LOJA TODA PRETA + BOTÃO RECEBEMOS PEDIDO
# ============================================================

def css_catalogo_loja():
    st.markdown("""
    <style>
    .main .block-container {
        max-width: 1100px;
        padding-top: 1.5rem;
    }
    .shop-hero {
        max-width: 900px;
        margin: 0 auto 30px auto;
        text-align: center;
        background: #050505 !important;
        border: 1px solid #222;
        border-radius: 28px;
        padding: 34px 26px 30px 26px;
        color: #ffffff !important;
        box-shadow: 0 18px 55px rgba(0,0,0,.22);
    }
    .shop-logo {
        width: 118px;
        height: 118px;
        object-fit: contain;
        border-radius: 50%;
        background: #ffffff;
        padding: 8px;
        margin: 0 auto 16px auto;
        display: block;
    }
    .shop-logo-fallback {
        width: 92px;
        height: 92px;
        border-radius: 50%;
        background: #ffffff;
        color: #111111;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 42px;
        font-weight: 900;
        margin: 0 auto 16px auto;
    }
    .shop-hero h1 {
        color: #ffffff !important;
        font-size: 34px;
        margin: 0;
        font-weight: 950;
        letter-spacing: -1px;
    }
    .shop-hero p {
        color: #ffffff !important;
        opacity: .96;
        font-size: 15px;
        max-width: 720px;
        margin: 10px auto 0 auto;
    }
    .shop-badges {
        margin-top: 18px;
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        justify-content: center;
        max-width: 820px;
        margin-left: auto;
        margin-right: auto;
    }
    .shop-badge {
        color: #ffffff !important;
        display: inline-block;
        background: #111111 !important;
        border: 1px solid #ffffff55;
        border-radius: 999px;
        padding: 8px 13px;
        font-weight: 700;
        font-size: 12px;
        white-space: normal;
        max-width: 100%;
        line-height: 1.35;
    }
    .produtos-wrap {
        max-width: 980px;
        margin: 0 auto;
    }
    .shop-card {
        background: #ffffff;
        border: 1px solid #ececec;
        border-radius: 22px;
        padding: 18px;
        box-shadow: 0 10px 30px rgba(0,0,0,.05);
        min-height: 210px;
        margin-bottom: 18px;
        overflow: hidden;
    }
    .shop-img {
        width: 100%;
        aspect-ratio: 1 / 1;
        object-fit: cover;
        border-radius: 16px;
        display: block;
        margin-bottom: 12px;
        background: #f4f4f4;
    }
    .shop-semfoto {
        width: 100%;
        aspect-ratio: 1 / 1;
        border-radius: 16px;
        margin-bottom: 12px;
        background: #f4f4f4;
        color: #999;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        font-size: 14px;
    }
    .shop-cat {
        text-transform: uppercase;
        letter-spacing: 2px;
        font-size: 11px;
        color: #8a8a8a;
        font-weight: 800;
    }
    .shop-name {
        font-size: 22px;
        font-weight: 900;
        color: #161616;
        margin-top: 4px;
        min-height: 34px;
        word-break: break-word;
    }
    .shop-desc {
        color: #626262;
        font-size: 14px;
        min-height: 42px;
        word-break: break-word;
    }
    .shop-price {
        font-size: 28px;
        font-weight: 950;
        color: #161616;
        margin: 12px 0 4px 0;
    }
    .cart-box {
        max-width: 880px;
        margin: 24px auto 0 auto;
        background: #ffffff;
        border: 1px solid #e7e2e6;
        border-radius: 24px;
        padding: 22px;
        box-shadow: 0 15px 42px rgba(0,0,0,.07);
    }
    .cart-title {
        font-size: 26px;
        font-weight: 900;
        margin-bottom: 8px;
        text-align: center;
    }
    .cart-line {
        background: #fafafa;
        border: 1px solid #eeeeee;
        border-radius: 16px;
        padding: 12px;
        margin-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)


def mensagem_catalogo_recebido(nome, codigo, itens_texto, total):
    texto = (
        f"Olá {nome}! 🤍\n\n"
        f"Recebemos seu pedido pelo nosso catálogo online. ✨\n\n"
        f"Pedido: {codigo}\n"
        f"Itens:\n{itens_texto}\n\n"
        f"Total estimado: {real(total)}\n\n"
        f"Vamos conferir os detalhes, personalização e prazo. Em seguida te retorno por aqui para confirmação, pagamento e produção.\n\n"
        f"Equipe Sophi Personalizados Oficial"
    )
    try:
        return limpar_texto_whatsapp(texto)
    except Exception:
        return texto


def botao_recebemos_pedido_catalogo(p, codigo, itens_texto, total_pedido):
    st.markdown("### WhatsApp do cliente")
    msg_recebido = mensagem_catalogo_recebido(
        p.get("cliente_nome", "cliente"),
        codigo,
        itens_texto,
        total_pedido,
    )
    link_recebido = link_whatsapp(p.get("whatsapp", ""), msg_recebido)
    if link_recebido:
        st.link_button("📲 Enviar mensagem: recebemos seu pedido", link_recebido, use_container_width=True)
    else:
        st.warning("Esse pedido não tem WhatsApp cadastrado.")

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
    enviar_banco_para_nuvem(force=True)
    st.set_page_config(
        page_title="Catálogo Sophi",
        page_icon="🛍️",
        layout="wide",
    )
    tela_catalogo_publico_cliente()
    st.stop()

criar_banco()
enviar_banco_para_nuvem(force=True)

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
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700;800&family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    --sophi-black: #070707;
    --sophi-charcoal: #111111;
    --sophi-soft-black: #1a1a1a;
    --sophi-white: #ffffff;
    --sophi-offwhite: #fbfaf8;
    --sophi-border: #e9e5df;
    --sophi-muted: #777777;
    --sophi-accent: #d83f5f;
    --sophi-gold: #c8a45d;
    --sophi-shadow: 0 18px 45px rgba(0,0,0,0.08);
}

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

.stApp {
    background:
        radial-gradient(circle at top right, rgba(216,63,95,0.08), transparent 28%),
        linear-gradient(180deg, #fffdfb 0%, #f8f6f2 100%);
    color: #111111;
}

section[data-testid="stSidebar"] {
    background:
        radial-gradient(circle at top left, rgba(255,255,255,0.10), transparent 25%),
        linear-gradient(180deg, #050505 0%, #121212 55%, #1c1c1c 100%) !important;
    border-right: 1px solid rgba(255,255,255,0.08);
}

section[data-testid="stSidebar"] * {
    color: #ffffff !important;
}

section[data-testid="stSidebar"] img {
    border-radius: 18px;
    margin-bottom: 16px;
    filter: drop-shadow(0 12px 28px rgba(0,0,0,0.35));
}

section[data-testid="stSidebar"] [role="radiogroup"] label {
    border-radius: 14px;
    padding: 8px 10px;
    margin: 2px 0;
    transition: all .18s ease;
}

section[data-testid="stSidebar"] [role="radiogroup"] label:hover {
    background: rgba(255,255,255,0.08);
    transform: translateX(2px);
}

section[data-testid="stSidebar"] [role="radiogroup"] label[data-baseweb="radio"] > div:first-child {
    border-color: rgba(255,255,255,0.55) !important;
}

h1 {
    font-family: 'Playfair Display', serif;
    font-size: 46px !important;
    font-weight: 800 !important;
    color: #111111;
    letter-spacing: -0.6px;
    margin-bottom: 0.2rem !important;
}

h2, h3 {
    letter-spacing: -0.3px;
}

[data-testid="stMarkdownContainer"] p {
    color: #5f5f5f;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 10px;
    border-bottom: 1px solid var(--sophi-border);
}

.stTabs [data-baseweb="tab"] {
    background: rgba(255,255,255,0.75);
    border: 1px solid var(--sophi-border);
    border-radius: 16px 16px 0 0;
    padding: 12px 18px;
    font-weight: 700;
}

.stTabs [aria-selected="true"] {
    background: #ffffff !important;
    border-top: 3px solid var(--sophi-accent) !important;
    box-shadow: 0 -8px 24px rgba(0,0,0,0.04);
}

.sophi-card {
    background:
        linear-gradient(180deg, rgba(255,255,255,0.96), rgba(255,255,255,0.88));
    border: 1px solid rgba(20,20,20,0.08);
    border-radius: 24px;
    padding: 20px 22px;
    box-shadow: var(--sophi-shadow);
    min-height: 118px;
    position: relative;
    overflow: hidden;
}

.sophi-card::before {
    content: "";
    position: absolute;
    width: 96px;
    height: 96px;
    border-radius: 999px;
    right: -38px;
    top: -42px;
    background: radial-gradient(circle, rgba(216,63,95,0.14), transparent 68%);
}

.sophi-card-title {
    color: #777777;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: .12em;
    font-weight: 800;
    margin-bottom: 10px;
}

.sophi-card-value {
    color: #111111;
    font-size: 30px;
    line-height: 1.05;
    font-weight: 900;
    letter-spacing: -0.8px;
}

.sophi-card-subtitle {
    color: #7a7a7a;
    font-size: 12px;
    margin-top: 9px;
}

.card {
    background: #ffffff;
    border: 1px solid rgba(20,20,20,0.08);
    border-radius: 24px;
    padding: 20px 22px;
    box-shadow: var(--sophi-shadow);
    min-height: 118px;
}

.card-title {
    color: #777777;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: .12em;
    margin-bottom: 10px;
    font-weight: 800;
}

.card-value {
    color: #111111;
    font-size: 30px;
    font-weight: 900;
    letter-spacing: -0.8px;
}

.card-subtitle {
    color: #777777;
    font-size: 12px;
    margin-top: 8px;
}

.stButton button, .stDownloadButton button, div[data-testid="stLinkButton"] a {
    background: linear-gradient(135deg, #050505 0%, #1b1b1b 100%) !important;
    color: #ffffff !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 14px !important;
    padding: 0.68rem 1.1rem !important;
    font-weight: 800 !important;
    box-shadow: 0 12px 28px rgba(0,0,0,0.16);
    transition: all .18s ease;
}

.stButton button:hover, .stDownloadButton button:hover, div[data-testid="stLinkButton"] a:hover {
    transform: translateY(-1px);
    box-shadow: 0 16px 35px rgba(0,0,0,0.22);
}

input, textarea, select, [data-baseweb="select"] > div {
    border-radius: 14px !important;
}

[data-testid="stDataFrame"] {
    border-radius: 18px;
    overflow: hidden;
    border: 1px solid var(--sophi-border);
    box-shadow: 0 12px 28px rgba(0,0,0,0.04);
}

[data-testid="stMetricValue"] {
    color: #111111 !important;
    font-weight: 900 !important;
}

hr {
    border-color: var(--sophi-border);
}

.sophi-hero {
    background:
        radial-gradient(circle at top right, rgba(216,63,95,0.18), transparent 24%),
        linear-gradient(135deg, #050505 0%, #191919 72%, #2a1d20 100%);
    border-radius: 30px;
    padding: 30px 34px;
    margin: 8px 0 24px 0;
    box-shadow: 0 22px 50px rgba(0,0,0,0.18);
    color: #fff;
}

.sophi-hero h1 {
    color: #fff !important;
    margin: 0 !important;
    font-size: 48px !important;
}

.sophi-hero p {
    color: rgba(255,255,255,0.78) !important;
    margin-top: 8px;
    font-size: 15px;
}

.sophi-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: rgba(255,255,255,0.10);
    border: 1px solid rgba(255,255,255,0.18);
    color: #fff;
    padding: 8px 12px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 800;
    letter-spacing: .08em;
    text-transform: uppercase;
    margin-bottom: 12px;
}

div[data-testid="stAlert"] {
    border-radius: 18px;
    border: 1px solid rgba(0,0,0,0.06);
}

</style>
""", unsafe_allow_html=True)


logo = obter_config("logo_path", "")
if logo and Path(logo).exists():
    st.sidebar.image(logo, width=120)


# Acesso público do Portal do Cliente sem login.
try:
    if st.query_params.get("portal", "") == "cliente":
        tela_portal_cliente_publico()
        st.stop()
except Exception:
    pass


exigir_login()

st.sidebar.markdown("""
<div style="padding:10px 4px 18px 4px;">
    <div style="font-family:'Playfair Display',serif;font-size:34px;line-height:.95;font-weight:800;">
        Sophi
    </div>
    <div style="font-size:11px;letter-spacing:3px;text-transform:uppercase;margin-top:6px;color:rgba(255,255,255,.72)!important;">
        Personalizados Oficial
    </div>
    <div style="height:1px;background:rgba(255,255,255,.12);margin-top:18px;"></div>
</div>
""", unsafe_allow_html=True)

botao_sair()
# Catálogo público desativado: vendas são registradas internamente após Offstore/WhatsApp.

menu = st.sidebar.radio(
    "Menu",
    [
        "🛒 Vendas / PDV",
        "🏠 Dashboard",
        "✅ Tarefas do Dia",
        "👥 Clientes / CRM",
        "💬 Mensagens WhatsApp",
        "📝 Orçamentos",
        "🏭 Produção / Agenda",
        "🏷 Precificação",
        "🏠 Custos Fixos",
        "🧾 Materiais",
        "📦 Estoque",
        "💰 Financeiro",
        "📊 Relatórios",
        "⚡ Central de Automação",
        "🖼 Biblioteca de Artes",
        "⚙ Configurações",
    ],
)



# Limpa os emojis do menu para comparar apenas o nome da tela
# IMPORTANTE: não resetar menu_limpo depois da primeira limpeza, senão
# "✅ Tarefas do Dia" não entra no elif e a tela fica em branco.
menu_limpo = str(menu)
for _icone in ["✅ ", "🏠 ", "👥 ", "💬 ", "📝 ", "🧾 ", "🏭 ", "🏷️ ", "🏷 ", "📋 ", "🎁 ", "📦 ", "💰 ", "📊 ", "⚡ ", "🛒 ", "🧺 ", "🖼️ ", "🖼 ", "⚙️ ", "⚙ "]:
    menu_limpo = menu_limpo.replace(_icone, "")
menu_limpo = menu_limpo.strip()

if menu_limpo == "Dashboard":
    tela_inicio()
elif menu_limpo == "Tarefas do Dia":
    tela_tarefas_dia()
elif menu_limpo == "Clientes / CRM":
    tela_clientes_crm()
elif menu_limpo == "Mensagens WhatsApp":
    tela_mensagens_whatsapp()
elif menu_limpo == "Orçamentos":
    tela_orcamentos()
elif menu_limpo == "Produção / Agenda":
    tela_producao_agenda()
elif menu_limpo == "Precificação":
    tela_produtos()
elif menu_limpo == "Custos Fixos":
    tela_custos_fixos()
elif menu_limpo == "Materiais":
    tela_materiais()
elif menu_limpo == "Vendas / PDV":
    tela_vendas_pdv()
elif menu_limpo == "Estoque":
    tela_estoque_unificado()
elif menu_limpo == "Financeiro":
    tela_financeiro_unificado()
elif menu_limpo == "Relatórios":
    tela_relatorios_inteligentes()
elif menu_limpo == "Central de Automação":
    tela_central_automacao()
elif menu_limpo == "Biblioteca de Artes":
    tela_biblioteca_artes()
elif menu_limpo == "Configurações":
    tela_configuracoes()

