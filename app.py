import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import io
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import smtplib
import requests
import re
import socket
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import psycopg2
from psycopg2.extras import DictCursor
from streamlit_option_menu import option_menu
import os
import streamlit.components.v1 as components
import threading
import time
import uuid
from streamlit_cookies_controller import CookieController

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="SISTEMA DE GESTÃO DE ALMOXARIFADO NGI CARAJÁS", 
    page_icon="https://www.gov.br/icmbio/pt-br/assuntos/biodiversidade/unidade-de-conservacao/unidades-de-biomas/marinho/lista-de-ucs/parna-marinho-dos-abrolhos/fomulario-denuncia/icmbio-logo-1.png", 
    layout="wide"
)

# --- ESTILIZAÇÃO CSS COMPATÍVEL ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"], .stMarkdown, .stMarkdown p, .stMarkdown li,
    [data-testid="stWidgetLabel"] p, label, span, div, button,
    input, textarea, select, .stDataFrame, [data-testid="stMetricValue"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif !important;
    }

    h1, h2, h3, h4, h5, h6 {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif !important;
        font-weight: 600 !important;
        letter-spacing: -0.01em;
    }

    /* Preserva a fonte de ícones do Streamlit (Material Symbols), que a regra
       acima sobrescrevia e fazia aparecer o nome do ícone em texto. */
    [data-testid="stIconMaterial"],
    span[data-testid="stIconMaterial"],
    .material-symbols-rounded,
    .material-symbols-outlined,
    .material-icons {
        font-family: 'Material Symbols Rounded', 'Material Symbols Outlined', 'Material Icons' !important;
    }

    [data-testid="stSidebarNav"] {display: none;}
    [data-testid="stMainMenu"] {display: none;}
    [data-testid="stStatusWidget"] {display: none;}
    [data-testid="collapsedControl"] {display: flex !important; visibility: visible !important;}

    /* Recolher a barra lateral só faz sentido no celular (tela estreita).
       No computador, a barra fica sempre aberta - sem opção de recolher. */
    @media (min-width: 641px) {
        [data-testid*="ollapse"] {display: none !important;}
    }
    
    html, body, [data-testid="stWidgetLabel"] p, .stMarkdown p, label, span {
        color: var(--text-color) !important;
    }
    
    .nav-link span {
        color: var(--text-color) !important;
    }
    
    .nav-link.active span {
        color: white !important;
    }
    
    div.stButton > button:first-child[kind="primary"] {
        background-color: #4CAF50 !important;
        border-color: #4CAF50 !important;
        color: white !important;
    }
    div.stButton > button:first-child[kind="primary"]:hover {
        background-color: #43a047 !important;
        border-color: #43a047 !important;
    }
    
    .img-container {
        display: flex;
        justify-content: center;
        align-items: center;
        width: 100%;
        margin-bottom: 20px;
        background-color: white; 
        padding: 15px;
        border-radius: 8px;
    }

    .kpi-titulo-branco, .kpi-titulo-branco *,
    .stMarkdown .kpi-titulo-branco, .stMarkdown .kpi-titulo-branco *,
    .stMarkdown p.kpi-titulo-branco {
        color: #ffffff !important;
    }
    .kpi-valor-branco, .kpi-valor-branco *,
    .stMarkdown .kpi-valor-branco, .stMarkdown .kpi-valor-branco *,
    .stMarkdown p.kpi-valor-branco {
        color: #ffffff !important;
    }
    .kpi-valor-limao, .kpi-valor-limao *,
    .stMarkdown .kpi-valor-limao, .stMarkdown .kpi-valor-limao *,
    .stMarkdown h1.kpi-valor-limao {
        color: #C7E36B !important;
    }

    /* Cartões de indicadores (Painel Geral e Relatórios) - tamanho reduz
       automaticamente em telas de celular para não ficarem gigantes */
    .painel-kpi-card, .rel-kpi-card {
        padding: 18px;
    }
    .painel-kpi-valor, .rel-kpi-valor {
        font-size: 34px !important;
        margin: 8px 0 0 0 !important;
    }
    .painel-kpi-label {
        font-size: 13px;
    }
    @media (max-width: 640px) {
        .painel-kpi-card, .rel-kpi-card {
            padding: 12px !important;
            min-height: unset !important;
        }
        .painel-kpi-valor, .rel-kpi-valor {
            font-size: 20px !important;
            margin: 4px 0 0 0 !important;
        }
        .painel-kpi-label {
            font-size: 11px !important;
        }
    }
    </style>
""", unsafe_allow_html=True)

# =============================================================================
# CONTORNO: TÍTULO/ÍCONE DA ABA MOSTRANDO "STREAMLIT" ANTES DO NOME CERTO
# =============================================================================
# Limitação conhecida do Streamlit: o page_title/page_icon definidos via
# st.set_page_config só são aplicados por JavaScript DEPOIS que a página já
# carregou, então aparece rapidamente o nome/ícone padrão do Streamlit antes
# do nome do sistema. Isso edita o index.html interno do próprio Streamlit
# para já vir com o nome/ícone certos desde o primeiro carregamento.
# ATENÇÃO: mexe em arquivo interno da biblioteca. Se uma futura atualização
# do Streamlit mudar a estrutura desse arquivo, este trecho pode parar de
# funcionar (sem quebrar o sistema - só volta a mostrar "Streamlit" rapidamente).
@st.cache_resource(show_spinner=False)
def personalizar_titulo_inicial_streamlit():
    try:
        pasta_static = os.path.join(os.path.dirname(st.__file__), "static")
        caminho_index = os.path.join(pasta_static, "index.html")
        with open(caminho_index, "r", encoding="utf-8") as f:
            conteudo = f.read()

        titulo_novo = "Gestão de Almoxarifado NGI Carajás"
        icone_url = "https://www.gov.br/icmbio/pt-br/assuntos/biodiversidade/unidade-de-conservacao/unidades-de-biomas/marinho/lista-de-ucs/parna-marinho-dos-abrolhos/fomulario-denuncia/icmbio-logo-1.png"

        ja_processado = f"<title>{titulo_novo}</title>" in conteudo

        conteudo_novo = re.sub(r"<title>.*?</title>", f"<title>{titulo_novo}</title>", conteudo, count=1)

        # Embute a logo diretamente no HTML como "data URI" (a imagem em
        # forma de texto, dentro do próprio arquivo). Assim o ícone chega
        # junto com a primeira resposta da página - não existe uma segunda
        # requisição que possa demorar e deixar o ícone padrão aparecer.
        if not ja_processado:
            resposta_icone = requests.get(icone_url, timeout=10)
            if resposta_icone.status_code == 200:
                b64_icone = base64.b64encode(resposta_icone.content).decode("utf-8")
                data_uri_icone = f"data:image/png;base64,{b64_icone}"
                conteudo_novo = re.sub(
                    r'<link[^>]*rel=["\'][^"\']*icon[^"\']*["\'][^>]*>',
                    f'<link rel="icon" href="{data_uri_icone}">',
                    conteudo_novo, flags=re.IGNORECASE
                )

        if conteudo_novo != conteudo:
            with open(caminho_index, "w", encoding="utf-8") as f:
                f.write(conteudo_novo)
        return True
    except Exception as e:
        print(f"[TITULO INICIAL] Não foi possível personalizar: {e}")
        return False

personalizar_titulo_inicial_streamlit()

# =============================================================================
# CONFIGURAÇÃO DE TEMPO DE SESSÃO (LOGIN PERSISTE APÓS ATUALIZAR A PÁGINA)
# =============================================================================
# O usuário só é desconectado automaticamente após ficar esse tempo (em
# minutos) sem interagir com o sistema. Qualquer clique/ação renova o prazo.
SESSAO_DURACAO_MINUTOS = 60

# URL pública do sistema, usada para montar o link de redefinição de senha
# enviado por e-mail. Ajuste aqui caso o domínio mude no futuro.
URL_BASE_SISTEMA = "https://www.almoxarifadocarajas.com.br"
REDEFINICAO_SENHA_DURACAO_MINUTOS = 60

def converter_para_horario_br(dt_utc):
    """O banco de dados (Neon Postgres) e o servidor (Railway) guardam os
    horários em UTC. Esta função converte para o horário de Brasília
    (America/Sao_Paulo, UTC-3) antes de exibir na tela."""
    if dt_utc is None:
        return None
    return dt_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/Sao_Paulo"))

# Controlador de cookies do navegador (mantém o login sem sujar a URL)
cookie_controller = CookieController(key="cookie_controller_almoxarifado")

# =============================================================================
# CONEXÃO E INICIALIZAÇÃO AUTOMÁTICA DO BANCO DE DADOS (Neon Postgres)
# =============================================================================
@st.cache_resource(show_spinner=False)
def inicializar_banco_automatico():
    conn = None
    try:
        conn_string = os.environ.get("POSTGRES_URL") or st.secrets["postgres"]["url"]
        conn = psycopg2.connect(conn_string)
    except Exception as e:
        st.error(f"Erro ao conectar ao Neon Postgres: {e}")
        st.info("Verifique as credenciais na aba 'Variables' do Railway.")
        st.stop()
        
    cursor = conn.cursor()

    # Tabela de controle de inicialização única
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config_sistema (
            chave TEXT PRIMARY KEY,
            valor TEXT
        );
    """)

    # 1. Tabela de usuários
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            nome TEXT,
            email TEXT PRIMARY KEY,
            senha TEXT,
            perfil TEXT
        );
    """)

    # 2. Tabela de produtos (Almoxarifado Geral)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            codigo TEXT PRIMARY KEY,
            item TEXT,
            quantidade INTEGER,
            categoria TEXT,
            valor_unitario REAL
        );
    """)

    # 3. Tabela de coordenações
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS coordenacoes (
            sigla TEXT PRIMARY KEY,
            nome TEXT
        );
    """)

    # 4. Tabela de categorias
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            nome TEXT PRIMARY KEY
        );
    """)

    # 5. Tabela de movimentações (Almoxarifado Geral)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id SERIAL PRIMARY KEY,
            data TEXT,
            tipo TEXT,
            codigo TEXT,
            item TEXT,
            quantidade INTEGER,
            responsavel TEXT,
            coordenacao TEXT
        );
    """)

    # =========================================================================
    # NOVAS TABELAS PARA O MÓDULO INDEPENDENTE DE EMPRÉSTIMOS
    # =========================================================================
    # 6. Tabela de Itens de Empréstimo (Catálogo exclusivo)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emprestimo_itens (
            id SERIAL PRIMARY KEY,
            codigo TEXT UNIQUE,
            item TEXT NOT NULL,
            quantidade_total INTEGER NOT NULL DEFAULT 1,
            quantidade_disponivel INTEGER NOT NULL DEFAULT 1,
            observacao TEXT
        );
    """)

    # 7. Tabela de Registros de Empréstimos e Devoluções
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emprestimo_registros (
            id SERIAL PRIMARY KEY,
            item_id INTEGER REFERENCES emprestimo_itens(id),
            item_nome TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            pessoa TEXT NOT NULL,
            coordenacao TEXT NOT NULL,
            data_retirada DATE NOT NULL,
            data_prevista DATE NOT NULL,
            data_devolucao DATE,
            status TEXT NOT NULL DEFAULT 'EMPRESTADO', -- 'EMPRESTADO' ou 'DEVOLVIDO'
            responsavel_devolucao TEXT
        );
    """)

    # =========================================================================
    # NOVA TABELA PARA O MÓDULO DE SOLICITAÇÕES (USUÁRIO / ADMINISTRADOR)
    # =========================================================================
    # 8. Tabela de Solicitações (nome exclusivo para não colidir com uma
    # tabela "solicitacoes" pré-existente no banco, de outra origem/schema)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solicitacoes_almoxarifado (
            id SERIAL PRIMARY KEY,
            tipo TEXT NOT NULL, -- 'MATERIAL' ou 'EMPRESTIMO'
            referencia_codigo TEXT,
            item_nome TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            solicitante_nome TEXT NOT NULL,
            solicitante_email TEXT NOT NULL,
            coordenacao TEXT,
            data_solicitacao TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            data_retirada DATE,
            data_prevista DATE,
            atividade_associada TEXT,
            status TEXT NOT NULL DEFAULT 'PENDENTE', -- 'PENDENTE', 'APROVADA' ou 'REJEITADA'
            data_decisao TIMESTAMP,
            aprovador TEXT,
            observacao TEXT
        );
    """)

    # Migração idempotente: garante as colunas novas em bancos que já tinham
    # a tabela 'solicitacoes_almoxarifado' criada em uma versão anterior.
    cursor.execute("ALTER TABLE solicitacoes_almoxarifado ADD COLUMN IF NOT EXISTS data_retirada DATE;")
    cursor.execute("ALTER TABLE solicitacoes_almoxarifado ADD COLUMN IF NOT EXISTS atividade_associada TEXT;")
    cursor.execute("ALTER TABLE solicitacoes_almoxarifado ADD COLUMN IF NOT EXISTS justificativa_rejeicao TEXT;")
    cursor.execute("ALTER TABLE solicitacoes_almoxarifado ADD COLUMN IF NOT EXISTS termo_aceito BOOLEAN NOT NULL DEFAULT FALSE;")
    cursor.execute("ALTER TABLE solicitacoes_almoxarifado ADD COLUMN IF NOT EXISTS data_aceite_termo TIMESTAMP;")

    # =========================================================================
    # NOVA TABELA: SESSÕES DE LOGIN ATIVAS (mantém o login após atualizar a
    # página / F5; a sessão só expira de fato após período de inatividade)
    # =========================================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessoes_login (
            token TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            nome TEXT NOT NULL,
            perfil TEXT NOT NULL,
            expira_em TIMESTAMP NOT NULL
        );
    """)

    # =========================================================================
    # NOVA TABELA: TOKENS DE REDEFINIÇÃO DE SENHA (link único enviado por e-mail)
    # =========================================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recuperacoes_senha (
            token TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            expira_em TIMESTAMP NOT NULL,
            usado BOOLEAN NOT NULL DEFAULT FALSE
        );
    """)

    conn.commit()

    # Verifica se a carga inicial (seed) já foi realizada no passado
    cursor.execute("SELECT valor FROM config_sistema WHERE chave = 'seed_inicial';")
    seed_realizado = cursor.fetchone()

    if not seed_realizado:
        # Inserção inicial única de Usuários
        cursor.execute("SELECT COUNT(*) FROM usuarios;")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO usuarios (nome, email, senha, perfil) 
                VALUES ('Administrador Padrão', 'admin@ngi.com', '123', 'Administrador');
            """)

        # Inserção inicial única de Produtos
        cursor.execute("SELECT COUNT(*) FROM produtos;")
        if cursor.fetchone()[0] == 0:
            produtos_iniciais = [
                ("001", "Capacete de Segurança", 15, "EPI", 45.00),
                ("002", "Resma Papel A4", 0, "Material de Escritório", 28.50),
                ("003", "Luva de Raspa", 50, "EPI", 12.00)
            ]
            cursor.executemany("INSERT INTO produtos VALUES (%s, %s, %s, %s, %s);", produtos_iniciais)

        # Inserção inicial única de Coordenações
        cursor.execute("SELECT COUNT(*) FROM coordenacoes;")
        if cursor.fetchone()[0] == 0:
            cursor.executemany("INSERT INTO coordenacoes VALUES (%s, %s);", [
                ("COTEC", "Coordenação Técnica"),
                ("COLOG", "Coordenação de Logística")
            ])

        # Inserção inicial única de Categorias
        cursor.execute("SELECT COUNT(*) FROM categorias;")
        if cursor.fetchone()[0] == 0:
            cat_iniciais = [("EPI",), ("Material de Escritório",), ("Informática",), ("Limpeza",), ("Copa",)]
            cursor.executemany("INSERT INTO categorias VALUES (%s);", cat_iniciais)

        # Marca no banco que o seed inicial já foi finalizado
        cursor.execute("INSERT INTO config_sistema (chave, valor) VALUES ('seed_inicial', 'true');")
        conn.commit()
    
    return conn

def obter_conexao_saudavel():
    """Reaproveita a conexão cacheada, mas testa se ela ainda está viva.
    O Neon (Postgres serverless) fecha conexões ociosas automaticamente;
    se isso acontecer, reconecta do zero sem exigir ação manual."""
    conexao = inicializar_banco_automatico()
    try:
        cur_teste = conexao.cursor()
        cur_teste.execute("SELECT 1;")
        cur_teste.fetchone()
        cur_teste.close()
    except Exception:
        try:
            conexao.close()
        except Exception:
            pass
        inicializar_banco_automatico.clear()
        conexao = inicializar_banco_automatico()
    return conexao

conn = obter_conexao_saudavel()

# Carregamento seguro e global dos dados
try:
    df_produtos = pd.read_sql_query('SELECT codigo AS "Código", item AS "Item", quantidade AS "Quantidade", categoria AS "Categoria", valor_unitario AS "Valor Unitário" FROM produtos ORDER BY codigo ASC', conn)
    df_movimentacoes = pd.read_sql_query('SELECT data AS "Data", tipo AS "Tipo", codigo AS "Código", item AS "Item", quantidade AS "Quantidade", responsavel AS "Responsável", coordenacao AS "Coordenação" FROM movimentacoes', conn)
    df_coordenacoes = pd.read_sql_query('SELECT sigla AS "Sigla", nome AS "Nome" FROM coordenacoes', conn)
    df_cat_bruto = pd.read_sql_query("SELECT nome FROM categorias", conn)
    lista_categorias = df_cat_bruto["nome"].tolist()
except Exception as e:
    df_produtos = pd.DataFrame()
    df_movimentacoes = pd.DataFrame()
    df_coordenacoes = pd.DataFrame()
    lista_categorias = []

# =============================================================================
# CONFIGURAÇÕES SEGURAS DE E-MAIL (via API HTTP da Resend)
# =============================================================================
# O Railway bloqueia conexões SMTP tradicionais (portas 25/465/587) fora do
# plano Pro. Por isso o envio de e-mail é feito via API HTTP da Resend
# (porta 443, nunca bloqueada), em vez de smtplib.
try:
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY") or st.secrets["resend"]["api_key"]
    RESEND_REMETENTE = os.environ.get("RESEND_FROM_EMAIL") or st.secrets["resend"]["from_email"]
except Exception:
    RESEND_API_KEY = ""
    RESEND_REMETENTE = ""

# =============================================================================
# FUNÇÃO AUXILIAR: ENVIO DE E-MAIL DE NOTIFICAÇÃO (MÓDULO DE SOLICITAÇÃO)
# =============================================================================
def _gerar_texto_simples(html):
    """Converte o HTML do corpo do e-mail em uma versão em texto puro.
    E-mails que só têm HTML (sem versão em texto) são mais frequentemente
    marcados como spam pelos filtros anti-spam."""
    texto = re.sub(r"<br\s*/?>", "\n", html)
    texto = re.sub(r"</p>", "\n\n", texto)
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = texto.replace("&nbsp;", " ").strip()
    return texto

def enviar_email_notificacao(destinatario, assunto, corpo_html):
    if not RESEND_API_KEY or not RESEND_REMETENTE or not destinatario:
        print(f"[EMAIL] Envio ignorado - Resend não configurado ou destinatário vazio (destino={destinatario})")
        return False, "Envio de e-mail não configurado no sistema (variáveis RESEND_API_KEY / RESEND_FROM_EMAIL ausentes)."
    try:
        # Envelope profissional com cabeçalho/rodapé institucional - reforça
        # legitimidade do e-mail perante os filtros anti-spam.
        corpo_html_completo = f"""
        <div style="font-family: Arial, Helvetica, sans-serif; max-width: 560px; margin: 0 auto; color: #1a1a1a;">
            <div style="background-color: #4CAF50; padding: 18px 24px; border-radius: 8px 8px 0 0;">
                <h2 style="color: #ffffff; margin: 0; font-size: 17px; font-weight: 600;">Gestão de Almoxarifado NGI Carajás</h2>
            </div>
            <div style="padding: 24px; border: 1px solid #e5e5e5; border-top: none; font-size: 14px; line-height: 1.5;">
                {corpo_html}
            </div>
            <div style="padding: 16px 24px; font-size: 11px; color: #888888; line-height: 1.5;">
                <p style="margin: 0 0 4px 0;">Este é um e-mail automático do Sistema de Gestão de Almoxarifado. Por favor, não responda a esta mensagem.</p>
                <p style="margin: 0;">ICMBio - Instituto Chico Mendes de Conservação da Biodiversidade | NGI Carajás</p>
            </div>
        </div>
        """
        corpo_texto = _gerar_texto_simples(corpo_html_completo)

        resposta = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "from": RESEND_REMETENTE,
                "to": [destinatario],
                "subject": assunto,
                "html": corpo_html_completo,
                "text": corpo_texto
            },
            timeout=10
        )
        if resposta.status_code in (200, 201):
            print(f"[EMAIL] Enviado com sucesso para {destinatario} - Assunto: {assunto}")
            return True, None
        else:
            erro_msg = resposta.text
            print(f"[EMAIL] ERRO ao enviar para {destinatario}: {resposta.status_code} - {erro_msg}")
            return False, f"HTTP {resposta.status_code}: {erro_msg}"
    except Exception as e:
        print(f"[EMAIL] ERRO ao enviar para {destinatario}: {repr(e)}")
        return False, str(e)


# =============================================================================
# TRADUÇÃO DO CALENDÁRIO (st.date_input) PARA PORTUGUÊS
# =============================================================================
# O Streamlit não tem suporte nativo a idioma no calendário (limitação
# conhecida e documentada da própria ferramenta). Este script traduz os
# nomes de mês/dia visualmente, sem alterar o funcionamento do widget.
components.html("""
<script>
(function() {
    const traducaoMeses = {
        "January": "Janeiro", "February": "Fevereiro", "March": "Março",
        "April": "Abril", "May": "Maio", "June": "Junho",
        "July": "Julho", "August": "Agosto", "September": "Setembro",
        "October": "Outubro", "November": "Novembro", "December": "Dezembro"
    };
    const traducaoDiasAbrev = {
        "Su": "Dom", "Mo": "Seg", "Tu": "Ter", "We": "Qua",
        "Th": "Qui", "Fr": "Sex", "Sa": "Sáb"
    };
    const traducaoRotulos = { "Today": "Hoje", "Clear": "Limpar" };

    function traduzirTexto(texto) {
        if (traducaoMeses[texto]) return traducaoMeses[texto];
        if (traducaoDiasAbrev[texto]) return traducaoDiasAbrev[texto];
        if (traducaoRotulos[texto]) return traducaoRotulos[texto];
        return null;
    }

    function traduzirContainer(container) {
        const caminhador = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
        let no;
        while ((no = caminhador.nextNode())) {
            const original = no.nodeValue.trim();
            if (!original) continue;
            const traduzido = traduzirTexto(original);
            if (traduzido) {
                no.nodeValue = no.nodeValue.replace(original, traduzido);
            }
        }
    }

    function verificarCalendarios(doc) {
        const calendarios = doc.querySelectorAll('[data-baseweb="calendar"]');
        calendarios.forEach(traduzirContainer);
    }

    try {
        const docPai = window.parent.document;
        const observer = new MutationObserver(function() {
            verificarCalendarios(docPai);
        });
        observer.observe(docPai.body, { childList: true, subtree: true });
        verificarCalendarios(docPai);
    } catch (e) {
        // Ignora silenciosamente se não conseguir acessar o documento principal
    }
})();
</script>
""", height=0, width=0)

# Dicionário de estilo adaptativo para os menus horizontais
ESTILO_MENU_HORIZONTAL = {
    "container": {"padding": "0!important", "background-color": "transparent"},
    "icon": {"color": "#64748b", "font-size": "14px"}, 
    "nav-link": {
        "font-size": "14px", 
        "text-align": "center", 
        "margin": "0px 5px", 
        "color": "var(--text-color)",
        "--hover-color": "rgba(76, 175, 80, 0.12)"
    },
    "nav-link-selected": {
        "background-color": "#4CAF50", 
        "color": "white", 
        "font-weight": "500"
    },
}

# --- GERENCIAMENTO DE SESSÃO ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"

if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = ""

if "PERFIL_USUARIO_LOGADO" not in st.session_state:
    st.session_state.PERFIL_USUARIO_LOGADO = ""

if "EMAIL_USUARIO_LOGADO" not in st.session_state:
    st.session_state.EMAIL_USUARIO_LOGADO = ""

if "SESSION_TOKEN" not in st.session_state:
    st.session_state.SESSION_TOKEN = ""

# =============================================================================
# RESTAURAÇÃO AUTOMÁTICA DE SESSÃO (mantém o login após atualizar a página)
# =============================================================================
# Se o navegador ainda tem o cookie da sessão e ele não expirou no banco,
# o usuário é reconectado automaticamente sem precisar logar de novo.
if not st.session_state.autenticado:
    token_cookie = cookie_controller.get("session")

    # Na primeiríssima execução após abrir/atualizar a página, o componente
    # de cookies ainda pode não ter tido tempo de entregar o valor ao Python
    # (token_cookie viria vazio mesmo com o cookie presente no navegador).
    # Para evitar mostrar a tela de login por engano nesse instante, aguarda
    # um instante e tenta novamente antes de decidir.
    if token_cookie is None and not st.session_state.get("verificacao_cookie_feita"):
        st.session_state.verificacao_cookie_feita = True
        with st.spinner("Verificando sessão..."):
            time.sleep(0.6)
        st.rerun()

    if token_cookie:
        try:
            cursor_sessao = conn.cursor()
            cursor_sessao.execute(
                "SELECT email, nome, perfil, expira_em FROM sessoes_login WHERE token = %s;",
                (token_cookie,)
            )
            sessao_encontrada = cursor_sessao.fetchone()

            if sessao_encontrada:
                email_sessao, nome_sessao, perfil_sessao, expira_em_sessao = sessao_encontrada

                if expira_em_sessao > datetime.now():
                    # Sessão válida: reconecta o usuário e renova o prazo (sliding expiration)
                    st.session_state.autenticado = True
                    st.session_state.NOME_USUARIO_LOGADO = nome_sessao
                    st.session_state.PERFIL_USUARIO_LOGADO = perfil_sessao
                    st.session_state.EMAIL_USUARIO_LOGADO = email_sessao
                    st.session_state.SESSION_TOKEN = token_cookie

                    nova_expiracao = datetime.now() + timedelta(minutes=SESSAO_DURACAO_MINUTOS)
                    cursor_sessao.execute(
                        "UPDATE sessoes_login SET expira_em = %s WHERE token = %s;",
                        (nova_expiracao, token_cookie)
                    )
                    conn.commit()
                    try:
                        cookie_controller.set(
                            "session", token_cookie,
                            max_age=SESSAO_DURACAO_MINUTOS * 60,
                            expires=nova_expiracao,
                            same_site="lax"
                        )
                    except Exception:
                        pass
                else:
                    # Sessão expirada por inatividade: remove do banco e do cookie
                    cursor_sessao.execute("DELETE FROM sessoes_login WHERE token = %s;", (token_cookie,))
                    conn.commit()
                    cookie_controller.remove("session")
        except Exception:
            pass

# =============================================================================
# FLUXO 0: REDEFINIÇÃO DE SENHA (via link único enviado por e-mail)
# =============================================================================
token_redefinicao_url = st.query_params.get("reset")

if token_redefinicao_url and not st.session_state.autenticado:
    col_rd1, col_rd2, col_rd3 = st.columns([1, 1.2, 1])
    with col_rd2:
        st.write("<br><br>", unsafe_allow_html=True)
        st.markdown("""
            <div class="img-container">
                <img src="https://www.gov.br/icmbio/pt-br/assuntos/biodiversidade/unidade-de-conservacao/unidades-de-biomas/marinho/lista-de-ucs/parna-marinho-dos-abrolhos/fomulario-denuncia/icmbio-logo-1.png" width="280">
            </div>
        """, unsafe_allow_html=True)
        st.markdown("### 🔒 Criar Nova Senha")

        try:
            cursor_reset = conn.cursor()
            cursor_reset.execute(
                "SELECT email, expira_em, usado FROM recuperacoes_senha WHERE token = %s;",
                (token_redefinicao_url,)
            )
            registro_reset = cursor_reset.fetchone()
        except Exception:
            registro_reset = None

        if not registro_reset:
            st.error("Link de redefinição inválido.")
            if st.button("Solicitar novo link", use_container_width=True):
                st.query_params.clear()
                st.session_state.sub_tela_login = "esqueci"
                st.rerun()
        else:
            email_reset, expira_em_reset, usado_reset = registro_reset
            if usado_reset:
                st.error("Este link já foi utilizado. Solicite um novo.")
                if st.button("Solicitar novo link", use_container_width=True):
                    st.query_params.clear()
                    st.session_state.sub_tela_login = "esqueci"
                    st.rerun()
            elif expira_em_reset <= datetime.now():
                st.error("Este link expirou. Solicite um novo.")
                if st.button("Solicitar novo link", use_container_width=True):
                    st.query_params.clear()
                    st.session_state.sub_tela_login = "esqueci"
                    st.rerun()
            else:
                st.write(f"Definindo nova senha para: **{email_reset}**")
                nova_senha_reset = st.text_input("Nova senha", type="password")
                confirmar_senha_reset = st.text_input("Confirmar nova senha", type="password")

                if st.button("Salvar Nova Senha", type="primary", use_container_width=True):
                    if not nova_senha_reset or not confirmar_senha_reset:
                        st.warning("Preencha os dois campos de senha.")
                    elif nova_senha_reset != confirmar_senha_reset:
                        st.error("As senhas não coincidem.")
                    elif len(nova_senha_reset) < 4:
                        st.warning("A senha deve ter pelo menos 4 caracteres.")
                    else:
                        try:
                            cursor_reset.execute(
                                "UPDATE usuarios SET senha = %s WHERE LOWER(email) = %s;",
                                (nova_senha_reset, email_reset)
                            )
                            cursor_reset.execute(
                                "UPDATE recuperacoes_senha SET usado = TRUE WHERE token = %s;",
                                (token_redefinicao_url,)
                            )
                            conn.commit()
                            st.query_params.clear()
                            st.success("Senha redefinida com sucesso! Você já pode fazer login com a nova senha.")
                            if st.button("Ir para o Login", use_container_width=True):
                                st.session_state.sub_tela_login = "login"
                                st.rerun()
                        except Exception as ex_reset:
                            conn.rollback()
                            st.error(f"Erro ao redefinir a senha: {ex_reset}")
    st.stop()

# =============================================================================
# FLUXO 1: TELA DE LOGIN / RECUPERAÇÃO
# =============================================================================
if not st.session_state.autenticado:
    if st.session_state.sub_tela_login == "login":
        st.markdown("<br><br>", unsafe_allow_html=True)
        col_l1, col_l2, col_l3 = st.columns([1, 1.2, 1])
        with col_l2:
            st.markdown("""
                <div class="img-container">
                    <img src="https://www.gov.br/icmbio/pt-br/assuntos/biodiversidade/unidade-de-conservacao/unidades-de-biomas/marinho/lista-de-ucs/parna-marinho-dos-abrolhos/fomulario-denuncia/icmbio-logo-1.png" width="320">
                </div>
            """, unsafe_allow_html=True)
            
            st.markdown("<h2 style='text-align: center; color: #0B552B; margin-top: 10px; margin-bottom: 25px; font-family: sans-serif;'>Gestão de Almoxarifado<br>NGI Carajás</h2>", unsafe_allow_html=True)
            
            usuario_input = st.text_input("Usuário / E-mail")
            senha_input = st.text_input("Senha", type="password")
            st.markdown("<br>", unsafe_allow_html=True)
            
            if st.button("Entrar no Sistema", type="primary", use_container_width=True):
                if usuario_input and senha_input:
                    cursor = conn.cursor()
                    cursor.execute("SELECT nome, senha, perfil, email FROM usuarios WHERE LOWER(email) = %s;", (usuario_input.strip().lower(),))
                    resultado = cursor.fetchone()
                    
                    if resultado:
                        nome_banco, senha_banco, perfil_banco, email_banco = resultado
                        if str(senha_banco) == str(senha_input).strip():
                            st.session_state.autenticado = True
                            st.session_state.NOME_USUARIO_LOGADO = nome_banco
                            st.session_state.PERFIL_USUARIO_LOGADO = perfil_banco
                            st.session_state.EMAIL_USUARIO_LOGADO = email_banco

                            # Cria uma sessão persistente (mantém o login após atualizar a página)
                            novo_token = str(uuid.uuid4())
                            expira_em_novo = datetime.now() + timedelta(minutes=SESSAO_DURACAO_MINUTOS)
                            try:
                                cursor.execute("""
                                    INSERT INTO sessoes_login (token, email, nome, perfil, expira_em)
                                    VALUES (%s, %s, %s, %s, %s);
                                """, (novo_token, email_banco, nome_banco, perfil_banco, expira_em_novo))
                                conn.commit()
                                st.session_state.SESSION_TOKEN = novo_token
                                try:
                                    cookie_controller.set(
                                        "session", novo_token,
                                        max_age=SESSAO_DURACAO_MINUTOS * 60,
                                        expires=expira_em_novo,
                                        same_site="lax"
                                    )
                                except Exception:
                                    cookie_controller.set("session", novo_token)
                                # Dá tempo do navegador de fato gravar o cookie
                                # antes da tela recarregar (evita corrida entre
                                # o componente de cookie e o rerun).
                                time.sleep(0.4)
                            except Exception:
                                conn.rollback()

                            st.rerun()
                        else:
                            st.error("❌ Senha incorreta!")
                    else:
                        st.error("❌ Usuário ou E-mail não cadastrado!")
                else:
                    st.error("Por favor, preencha todos os campos!")
                    
            if st.button("Esqueci a senha", use_container_width=True):
                st.session_state.sub_tela_login = "esqueci"
                st.rerun()

    elif st.session_state.sub_tela_login == "esqueci":
        col_r1, col_r2, col_r3 = st.columns([1, 1.2, 1])
        with col_r2:
            st.write("<br><br>", unsafe_allow_html=True)
            st.markdown("### 🔑 Recuperar Acesso")
            email_recuperar = st.text_input("E-mail corporativo", placeholder="exemplo@icmbio.gov.br")

            if st.button("Enviar Instruções", type="primary", use_container_width=True):
                if email_recuperar.strip():
                    cursor = conn.cursor()
                    cursor.execute("SELECT nome FROM usuarios WHERE LOWER(email) = %s;", (email_recuperar.strip().lower(),))
                    resultado_recup = cursor.fetchone()
                    if resultado_recup:
                        nome_usuario_recup = resultado_recup[0]
                        email_normalizado = email_recuperar.strip().lower()

                        token_redefinicao = str(uuid.uuid4())
                        expira_redefinicao = datetime.now() + timedelta(minutes=REDEFINICAO_SENHA_DURACAO_MINUTOS)
                        try:
                            cursor.execute("""
                                INSERT INTO recuperacoes_senha (token, email, expira_em, usado)
                                VALUES (%s, %s, %s, FALSE);
                            """, (token_redefinicao, email_normalizado, expira_redefinicao))
                            conn.commit()

                            link_redefinicao = f"{URL_BASE_SISTEMA}/?reset={token_redefinicao}"

                            with st.spinner("Enviando..."):
                                sucesso_recup, erro_recup = enviar_email_notificacao(
                                    email_normalizado,
                                    "Redefinição de Senha - Sistema de Almoxarifado NGI Carajás",
                                    f"""
                                    <p>Olá, {nome_usuario_recup},</p>
                                    <p>Recebemos uma solicitação para redefinir a senha da sua conta no Sistema de Gestão de Almoxarifado.</p>
                                    <p>Para criar sua nova senha, clique no botão abaixo:</p>
                                    <p style="text-align: center; margin: 24px 0;">
                                        <a href="{link_redefinicao}" style="background-color: #4CAF50; color: #ffffff; padding: 12px 28px; border-radius: 6px; text-decoration: none; font-weight: 600; display: inline-block;">Criar Nova Senha</a>
                                    </p>
                                    <p>Ou copie e cole este link no seu navegador:<br>{link_redefinicao}</p>
                                    <p>Este link é válido por {REDEFINICAO_SENHA_DURACAO_MINUTOS} minutos. Se você não solicitou essa redefinição, pode ignorar este e-mail com segurança.</p>
                                    """
                                )
                            if sucesso_recup:
                                st.success(f"Sucesso! Enviamos um link de redefinição de senha para {email_normalizado}")
                            else:
                                st.error(f"Erro ao tentar enviar o e-mail: {erro_recup}")
                        except Exception as ex_recup:
                            conn.rollback()
                            st.error(f"Erro ao gerar o link de redefinição: {ex_recup}")
                    else:
                        st.error("Este e-mail não foi encontrado no sistema.")
                else:
                    st.warning("Por favor, digite um e-mail válido.")
            if st.button("Voltar para o Login", use_container_width=True):
                st.session_state.sub_tela_login = "login"
                st.rerun()

# =============================================================================
# FLUXO 2: SISTEMA PRINCIPAL (PÓS-AUTENTICAÇÃO)
# =============================================================================
else:
    # --- MENU LATERAL ---
    label_solicitacoes = "Solicitações"

    with st.sidebar:
        st.markdown(f"#### 👤 Olá, {st.session_state.NOME_USUARIO_LOGADO}")
        st.write("---")
        
        if st.session_state.PERFIL_USUARIO_LOGADO == "Usuário Comum":
            # ---------------------------------------------------------------
            # MENU RESTRITO - PERFIL USUÁRIO (MÓDULO DE SOLICITAÇÃO)
            # ---------------------------------------------------------------
            escolha = option_menu(
                menu_title=None,
                options=[
                    "Materiais Disponíveis",
                    "Empréstimo Disponível",
                    "Minhas Solicitações",
                    "Sair do Sistema"
                ],
                icons=["box-seam", "arrow-repeat", "clock-history", "box-arrow-right"],
                menu_icon="cast",
                default_index=0,
                styles={
                    "container": {"padding": "0!important", "background-color": "transparent"},
                    "icon": {"color": "#64748b", "font-size": "15px"}, 
                    "nav-link": {
                        "font-size": "14px", 
                        "text-align": "left", 
                        "margin": "0px", 
                        "color": "var(--text-color)",
                        "--hover-color": "rgba(76, 175, 80, 0.12)"
                    },
                    "nav-link-selected": {
                        "background-color": "#4CAF50", 
                        "color": "white", 
                        "font-weight": "500"
                    },
                }
            )
        else:
            # ---------------------------------------------------------------
            # MENU COMPLETO - PERFIL ADMINISTRADOR (MENU ORIGINAL + SOLICITAÇÕES)
            # ---------------------------------------------------------------
            try:
                cursor_badge = conn.cursor()
                cursor_badge.execute("SELECT COUNT(*) FROM solicitacoes_almoxarifado WHERE status = 'PENDENTE';")
                qtd_pendentes_badge = cursor_badge.fetchone()[0]
            except Exception:
                qtd_pendentes_badge = 0

            label_solicitacoes = f"Solicitações ({qtd_pendentes_badge})" if qtd_pendentes_badge > 0 else "Solicitações"

            escolha = option_menu(
                menu_title=None,
                options=[
                    "Painel Geral", 
                    "Empréstimo de Material",
                    "Cadastrar Produto", 
                    "Cadastrar Categoria", 
                    "Cadastrar Usuário", 
                    "Cadastrar Coordenação",
                    "Movimentação de Estoque",
                    label_solicitacoes,
                    "Relatórios",
                    "Sair do Sistema"
                ],
                icons=["grid", "arrow-repeat", "box", "folder", "person-plus", "building", "arrow-left-right", "bell", "bar-chart-line", "box-arrow-right"],
                menu_icon="cast",
                default_index=0,
                styles={
                    "container": {"padding": "0!important", "background-color": "transparent"},
                    "icon": {"color": "#64748b", "font-size": "15px"}, 
                    "nav-link": {
                        "font-size": "14px", 
                        "text-align": "left", 
                        "margin": "0px", 
                        "color": "var(--text-color)",
                        "--hover-color": "rgba(76, 175, 80, 0.12)"
                    },
                    "nav-link-selected": {
                        "background-color": "#4CAF50", 
                        "color": "white", 
                        "font-weight": "500"
                    },
                }
            )

    if escolha == "Sair do Sistema":
        if st.session_state.SESSION_TOKEN:
            try:
                cursor_logout = conn.cursor()
                cursor_logout.execute("DELETE FROM sessoes_login WHERE token = %s;", (st.session_state.SESSION_TOKEN,))
                conn.commit()
            except Exception:
                conn.rollback()
        cookie_controller.remove("session")
        st.session_state.autenticado = False
        st.session_state.NOME_USUARIO_LOGADO = ""
        st.session_state.PERFIL_USUARIO_LOGADO = ""
        st.session_state.EMAIL_USUARIO_LOGADO = ""
        st.session_state.SESSION_TOKEN = ""
        st.rerun()

    # --- TELA: PAINEL GERAL ---
    elif escolha == "Painel Geral":
        st.markdown("""
            <div style="background-color: #4CAF50; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
                <h1 style="color: white; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                    Painel Geral de Controle
                </h1>
                <p style="color: #E8F5E9; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Visão Geral de Saldos, Alertas de Materiais e Fluxo de Insumos NGI Carajás
                </p>
            </div>
        """, unsafe_allow_html=True)
        
        c1, c2, c3 = st.columns(3)
        total_itens = len(df_produtos) if not df_produtos.empty else 0
        produtos_esgotados = len(df_produtos[df_produtos['Quantidade'] == 0]) if not df_produtos.empty else 0
        total_movimentacoes = len(df_movimentacoes) if not df_movimentacoes.empty else 0
        
        c1.markdown(f"""
            <div class="painel-kpi-card" style="background-color: rgba(76, 175, 80, 0.08); border-left: 5px solid #4CAF50; border-radius: 4px;">
                <span class="painel-kpi-label" style="font-weight: 600; text-transform: uppercase;">Total de Itens Cadastrados</span>
                <h2 class="painel-kpi-valor" style="color: #4CAF50; font-weight: 700;">{total_itens}</h2>
            </div>
        """, unsafe_allow_html=True)
        
        cor_esgotados = "#c62828" if produtos_esgotados > 0 else "#4CAF50"
        bg_esgotados = "rgba(198, 40, 40, 0.08)" if produtos_esgotados > 0 else "rgba(76, 175, 80, 0.08)"
        
        c2.markdown(f"""
            <div class="painel-kpi-card" style="background-color: {bg_esgotados}; border-left: 5px solid {cor_esgotados}; border-radius: 4px;">
                <span class="painel-kpi-label" style="font-weight: 600; text-transform: uppercase;">Produtos Esgotados</span>
                <h2 class="painel-kpi-valor" style="color: {cor_esgotados}; font-weight: 700;">{produtos_esgotados}</h2>
            </div>
        """, unsafe_allow_html=True)
        
        c3.markdown(f"""
            <div class="painel-kpi-card" style="background-color: rgba(33, 150, 243, 0.08); border-left: 5px solid #2196F3; border-radius: 4px;">
                <span class="painel-kpi-label" style="font-weight: 600; text-transform: uppercase;">Movimentações Realizadas</span>
                <h2 class="painel-kpi-valor" style="color: #2196F3; font-weight: 700;">{total_movimentacoes}</h2>
            </div>
        """, unsafe_allow_html=True)
        
        st.markdown("<br><hr style='margin: 10px 0 25px 0; opacity: 0.15;'>", unsafe_allow_html=True)
        st.markdown('<h3 style="font-size: 18px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center;"><span style="display: inline-block; width: 6px; height: 18px; background-color: #4CAF50; margin-right: 8px; border-radius: 2px;"></span>Filtros de Consulta</h3>', unsafe_allow_html=True)
        
        col_filtro1, col_filtro2 = st.columns([2, 1])
        termo_busca = col_filtro1.text_input("Buscar por Nome do Material ou Código:", placeholder="Digite o termo para pesquisar...")
        categoria_selecionada = col_filtro2.selectbox("Filtrar por Categoria:", ["Todas"] + lista_categorias)
        
        df_filtrado = df_produtos.copy() if not df_produtos.empty else pd.DataFrame()
        if not df_filtrado.empty and termo_busca:
            df_filtrado = df_filtrado[df_filtrado['Item'].str.contains(termo_busca, case=False, na=False) | df_filtrado['Código'].str.contains(termo_busca, case=False, na=False)]
        if not df_filtrado.empty and categoria_selecionada != "Todas":
            df_filtrado = df_filtrado[df_filtrado['Categoria'] == categoria_selecionada]

        st.markdown("<br><h3 style='font-size: 18px; font-weight: 600; margin-bottom: 12px;'> Controle de Estoque</h3>", unsafe_allow_html=True)
        if df_filtrado.empty:
            st.info("Nenhum material encontrado com os filtros aplicados.")
        else:
            df_display = df_filtrado.copy()
            df_display["Valor Unitário"] = df_display["Valor Unitário"].astype(float)
            df_display["Valor Total"] = df_display["Quantidade"] * df_display["Valor Unitário"]
            df_display["Valor Unitário"] = df_display["Valor Unitário"].map("R$ {:.2f}".format)
            df_display["Valor Total"] = df_display["Valor Total"].map("R$ {:.2f}".format)

            def destacar_zerados(row):
                if row['Quantidade'] == 0:
                    return ['background-color: rgba(198, 40, 40, 0.12); color: #c62828; font-weight: bold;'] * len(row)
                return [''] * len(row)
                
            st.dataframe(df_display.style.apply(destacar_zerados, axis=1), use_container_width=True, hide_index=True)

    # =========================================================================
    # NOVA TELA: EMPRÉSTIMO DE MATERIAL (INDEPENDENTE)
    # =========================================================================
    elif escolha == "Empréstimo de Material":
        st.markdown("""
            <div style="background-color: #2E7D32; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
                <h1 style="color: white; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                    Gestão de Empréstimo de Material
                </h1>
                <p style="color: #E8F5E9; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Módulo independente de empréstimos, controle de devoluções e histórico
                </p>
            </div>
        """, unsafe_allow_html=True)

        sub_emp = option_menu(
            menu_title=None,
            options=[
                "Itens Disponíveis", 
                "Cadastrar Item Empréstimo", 
                "Registrar Saída (Empréstimo)", 
                "Registrar Devolução", 
                "Histórico de Movimentação"
            ],
            icons=["box-seam", "plus-circle", "box-arrow-right", "box-arrow-in-left", "journal-text"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )

        cursor = conn.cursor()

        # ---------------------------------------------------------------------
        # SUB-ABA 1: ITENS DISPONÍVEIS (PAINEL + EDITAR / EXCLUIR)
        # ---------------------------------------------------------------------
        if sub_emp == "Itens Disponíveis":
            st.subheader("Painel de Disponibilidade de Empréstimos")
            
            df_emp_itens = pd.read_sql_query("""
                SELECT 
                    id AS "ID",
                    codigo AS "Código", 
                    item AS "Item / Equipamento", 
                    quantidade_total AS "Qtd Total", 
                    quantidade_disponivel AS "Qtd Disponível",
                    (quantidade_total - quantidade_disponivel) AS "Emprestados",
                    observacao AS "Observações"
                FROM emprestimo_itens ORDER BY codigo ASC;
            """, conn)

            if df_emp_itens.empty:
                st.info("Nenhum item cadastrado no catálogo exclusivo de empréstimos ainda.")
            else:
                # Exibe a tabela ocultando a coluna técnica 'ID'
                df_exibir = df_emp_itens.drop(columns=["ID"])
                st.dataframe(df_exibir, use_container_width=True, hide_index=True)

                st.markdown("<hr style='margin: 25px 0 15px 0; opacity: 0.2;'>", unsafe_allow_html=True)
                st.markdown("### Gerenciar / Editar / Excluir Item de Empréstimo")

                # Seleção do item
                df_raw_emp = pd.read_sql_query("SELECT id, codigo, item, quantidade_total, quantidade_disponivel, observacao FROM emprestimo_itens ORDER BY codigo ASC;", conn)
                
                if not df_raw_emp.empty:
                    opcao_emp_sel = st.selectbox(
                        "Selecione o item para modificar ou excluir:",
                        df_raw_emp.index,
                        format_func=lambda x: f"{df_raw_emp.loc[x, 'item']} (Código: {df_raw_emp.loc[x, 'codigo'] or 'S/N'})"
                    )

                    id_emp_sel = int(df_raw_emp.loc[opcao_emp_sel, "id"])
                    cod_emp_sel = df_raw_emp.loc[opcao_emp_sel, "codigo"] or ""
                    nome_emp_sel = df_raw_emp.loc[opcao_emp_sel, "item"]
                    qtd_tot_sel = int(df_raw_emp.loc[opcao_emp_sel, "quantidade_total"])
                    qtd_disp_sel = int(df_raw_emp.loc[opcao_emp_sel, "quantidade_disponivel"])
                    obs_emp_sel = df_raw_emp.loc[opcao_emp_sel, "observacao"] or ""

                    col_ed_e1, col_ed_e2 = st.columns(2)
                    edit_cod_emp = col_ed_e1.text_input("Código / Patrimônio:", value=cod_emp_sel, key="ed_cod_emp")
                    edit_nome_emp = col_ed_e2.text_input("Nome do Item / Equipamento:", value=nome_emp_sel, key="ed_nome_emp")
                    
                    qtd_emprestados_atual = qtd_tot_sel - qtd_disp_sel
                    edit_qtd_tot = col_ed_e1.number_input("Quantidade Total em Acervo:", min_value=qtd_emprestados_atual, value=qtd_tot_sel, step=1, key="ed_qtd_tot_emp")
                    
                    if qtd_emprestados_atual > 0:
                        st.caption(f"Existem {qtd_emprestados_atual} unidade(s) emprestada(s) no momento. A quantidade total não pode ser menor que isso.")

                    edit_obs_emp = col_ed_e2.text_area("Observações / Descrição:", value=obs_emp_sel, key="ed_obs_emp")

                    col_btn_e1, col_btn_e2 = st.columns([1, 4])
                    
                    with col_btn_e1:
                        if st.button("Salvar Alterações", type="primary", key="btn_salvar_emp"):
                            if edit_nome_emp.strip():
                                nova_qtd_disp = edit_qtd_tot - qtd_emprestados_atual
                                try:
                                    cursor.execute("""
                                        UPDATE emprestimo_itens 
                                        SET codigo = %s, item = %s, quantidade_total = %s, quantidade_disponivel = %s, observacao = %s 
                                        WHERE id = %s;
                                    """, (edit_cod_emp.strip() if edit_cod_emp.strip() else None, edit_nome_emp.strip(), edit_qtd_tot, nova_qtd_disp, edit_obs_emp.strip(), id_emp_sel))
                                    conn.commit()
                                    st.success(f"Item '{edit_nome_emp}' atualizado com sucesso!")
                                    st.rerun()
                                except psycopg2.IntegrityError:
                                    conn.rollback()
                                    st.error("Erro: Já existe outro item registrado com este mesmo Código/Patrimônio.")
                            else:
                                st.error("O Nome do Item é obrigatório.")

                    with col_btn_e2:
                        if st.button("Excluir Item", key="btn_excluir_emp"):
                            cursor.execute("SELECT COUNT(*) FROM emprestimo_registros WHERE item_id = %s AND status = 'EMPRESTADO';", (id_emp_sel,))
                            tem_pendente = cursor.fetchone()[0]

                            if tem_pendente > 0:
                                st.error("Não é possível excluir este item pois existem unidades atualmente emprestadas pendentes de devolução.")
                            else:
                                try:
                                    cursor.execute("DELETE FROM emprestimo_registros WHERE item_id = %s;", (id_emp_sel,))
                                    cursor.execute("DELETE FROM emprestimo_itens WHERE id = %s;", (id_emp_sel,))
                                    conn.commit()
                                    st.warning(f"Item '{nome_emp_sel}' removido com sucesso!")
                                    st.rerun()
                                except Exception as err:
                                    conn.rollback()
                                    st.error(f"Erro ao tentar excluir: {err}")

        # ---------------------------------------------------------------------
        # SUB-ABA 2: CADASTRAR ITEM PARA EMPRÉSTIMO
        # ---------------------------------------------------------------------
        elif sub_emp == "Cadastrar Item Empréstimo":
            st.subheader("Cadastrar Novo Item no Catálogo de Empréstimos")
            st.caption("Nota: Itens cadastrados aqui são 100% independentes do estoque do Almoxarifado.")

            with st.form("form_cad_emp_item", clear_on_submit=True):
                col_e1, col_e2 = st.columns(2)
                cod_emp = col_e1.text_input("Código / Patrimônio (opcional)")
                item_emp = col_e2.text_input("Nome do Item / Equipamento*")
                qtd_total = col_e1.number_input("Quantidade Total em Acervo*", min_value=1, value=1, step=1)
                obs_emp = col_e2.text_area("Observações / Descrição", placeholder="Ex: Acompanha cabo de força e maleta")

                if st.form_submit_button("Cadastrar Item", type="primary"):
                    if item_emp.strip():
                        try:
                            cursor.execute("""
                                INSERT INTO emprestimo_itens (codigo, item, quantidade_total, quantidade_disponivel, observacao)
                                VALUES (%s, %s, %s, %s, %s);
                            """, (cod_emp.strip() if cod_emp else None, item_emp.strip(), qtd_total, qtd_total, obs_emp.strip()))
                            conn.commit()
                            st.success(f"Item '{item_emp}' cadastrado com sucesso para empréstimos!")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error("Erro: Já existe um item de empréstimo com este mesmo Código/Patrimônio.")
                    else:
                        st.error("O campo 'Nome do Item' é obrigatório!")

        # ---------------------------------------------------------------------
        # SUB-ABA 3: REGISTRAR SAÍDA (EMPRÉSTIMO)
        # ---------------------------------------------------------------------
        elif sub_emp == "Registrar Saída (Empréstimo)":
            st.subheader("Registrar Saída de Material Por Empréstimo")

            cursor.execute("SELECT id, item, quantidade_disponivel FROM emprestimo_itens WHERE quantidade_disponivel > 0 ORDER BY codigo ASC;")
            itens_disponiveis = cursor.fetchall()

            if not itens_disponiveis:
                st.warning("Não há itens disponíveis no catálogo de empréstimo no momento.")
            else:
                opcoes_itens = {f"{item[1]} (Disponível: {item[2]})": (item[0], item[1], item[2]) for item in itens_disponiveis}
                
                with st.form("form_registro_saida_emp", clear_on_submit=True):
                    item_selecionado_label = st.selectbox("Selecione o Item para Empréstimo*", list(opcoes_itens.keys()))
                    item_id, item_nome, max_qtd = opcoes_itens[item_selecionado_label]

                    col_s1, col_s2 = st.columns(2)
                    qtd_saida = col_s1.number_input("Quantidade*", min_value=1, max_value=max_qtd, value=1, step=1)
                    nome_pessoa = col_s2.text_input("Nome da Pessoa (Solicitante)*")

                    lista_siglas_coord = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["GERAL"]
                    coord_pessoa = col_s1.selectbox("Coordenação*", lista_siglas_coord)
                    
                    data_retirada = col_s2.date_input("Data de Retirada*", value=date.today(), format="DD/MM/YYYY")
                    data_prevista = col_s1.date_input("Data Prevista para Devolução*", value=date.today(), format="DD/MM/YYYY")

                    if st.form_submit_button("Confirmar Empréstimo", type="primary"):
                        if nome_pessoa.strip():
                            if data_prevista < data_retirada:
                                st.error("A data prevista de devolução não pode ser anterior à data de retirada!")
                            else:
                                cursor.execute("""
                                    INSERT INTO emprestimo_registros 
                                    (item_id, item_nome, quantidade, pessoa, coordenacao, data_retirada, data_prevista, status)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'EMPRESTADO');
                                """, (item_id, item_nome, qtd_saida, nome_pessoa.strip(), coord_pessoa, data_retirada, data_prevista))
                                
                                cursor.execute("""
                                    UPDATE emprestimo_itens 
                                    SET quantidade_disponivel = quantidade_disponivel - %s 
                                    WHERE id = %s;
                                """, (qtd_saida, item_id))
                                
                                conn.commit()
                                st.success(f"Empréstimo registrado com sucesso para {nome_pessoa}!")
                                st.rerun()
                        else:
                            st.error("Por favor, preencha o Nome da Pessoa!")

        # ---------------------------------------------------------------------
        # SUB-ABA 4: REGISTRAR DEVOLUÇÃO
        # ---------------------------------------------------------------------
        elif sub_emp == "Registrar Devolução":
            st.subheader("Registro de Devolução de Material")

            cursor.execute("""
                SELECT id, item_id, item_nome, quantidade, pessoa, data_retirada, data_prevista 
                FROM emprestimo_registros 
                WHERE status = 'EMPRESTADO'
                ORDER BY data_retirada ASC;
            """)
            emp_ativos = cursor.fetchall()

            if not emp_ativos:
                st.info("Nenhum empréstimo pendente de devolução no momento.")
            else:
                opcoes_dev = {
                    f"{e[2]} (Qtd: {e[3]}) - Emprestado para: {e[4]} (Retirada: {e[5].strftime('%d/%m/%Y')})": e
                    for e in emp_ativos
                }

                with st.form("form_registro_devolucao", clear_on_submit=True):
                    emp_selecionado_label = st.selectbox("Selecione o Empréstimo a ser Baixado*", list(opcoes_dev.keys()))
                    reg_id, item_id, item_nome, qtd, pessoa_orig, d_ret, d_prev = opcoes_dev[emp_selecionado_label]

                    col_d1, col_d2 = st.columns(2)
                    pessoa_devolvendo = col_d1.text_input("Nome de Quem Está Devolvendo*", value=pessoa_orig)
                    data_devolucao = col_d2.date_input("Data Real da Devolução*", value=date.today(), format="DD/MM/YYYY")

                    if st.form_submit_button("Confirmar Devolução", type="primary"):
                        if pessoa_devolvendo.strip():
                            cursor.execute("""
                                UPDATE emprestimo_registros 
                                SET status = 'DEVOLVIDO', data_devolucao = %s, responsavel_devolucao = %s 
                                WHERE id = %s;
                            """, (data_devolucao, pessoa_devolvendo.strip(), reg_id))

                            cursor.execute("""
                                UPDATE emprestimo_itens 
                                SET quantidade_disponivel = quantidade_disponivel + %s 
                                WHERE id = %s;
                            """, (qtd, item_id))

                            conn.commit()
                            st.success(f"Devolução do item '{item_nome}' realizada com sucesso!")
                            st.rerun()
                        else:
                            st.error("Preencha o nome da pessoa responsável pela devolução.")

        # ---------------------------------------------------------------------
        # SUB-ABA 5: HISTÓRICO DE MOVIMENTAÇÃO DE EMPRÉSTIMOS
        # ---------------------------------------------------------------------
        elif sub_emp == "Histórico de Movimentação":
            st.subheader("Histórico Completo de Empréstimos e Devoluções")

            df_hist_emp = pd.read_sql_query("""
                SELECT 
                    id AS "ID",
                    item_nome AS "Produto / Equipamento",
                    quantidade AS "Qtd",
                    pessoa AS "Solicitante",
                    coordenacao AS "Coordenação",
                    to_char(data_retirada, 'DD/MM/YYYY') AS "Data Retirada",
                    to_char(data_prevista, 'DD/MM/YYYY') AS "Previsão Devolução",
                    COALESCE(to_char(data_devolucao, 'DD/MM/YYYY'), '-') AS "Data Devolução Real",
                    status AS "Status",
                    COALESCE(responsavel_devolucao, '-') AS "Devolvido Por"
                FROM emprestimo_registros 
                ORDER BY id DESC;
            """, conn)

            if df_hist_emp.empty:
                st.info("Nenhuma movimentação de empréstimo registrada até o momento.")
            else:
                def destacar_status(val):
                    if val == 'EMPRESTADO':
                        return 'background-color: #fff3cd; color: #856404; font-weight: bold;'
                    elif val == 'DEVOLVIDO':
                        return 'background-color: #d4edda; color: #155724;'
                    return ''

                st.dataframe(df_hist_emp.style.map(destacar_status, subset=['Status']), use_container_width=True, hide_index=True)

    # =========================================================================
    # NOVO MÓDULO DE SOLICITAÇÃO — TELA (PERFIL USUÁRIO): MATERIAIS DISPONÍVEIS
    # =========================================================================
    elif escolha == "Materiais Disponíveis":
        st.markdown("""
            <div style="background-color: #4CAF50; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
                <h1 style="color: white; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                    Materiais Disponíveis no Almoxarifado
                </h1>
                <p style="color: #E8F5E9; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Consulte os itens em estoque e solicite a retirada de materiais
                </p>
            </div>
        """, unsafe_allow_html=True)

        if st.session_state.get("msg_sucesso_material"):
            st.success("Sua solicitação foi encaminhada com sucesso!")
            del st.session_state["msg_sucesso_material"]

        df_disp_material = df_produtos[df_produtos["Quantidade"] > 0].copy() if not df_produtos.empty else pd.DataFrame()

        if df_disp_material.empty:
            st.info("Nenhum material disponível em estoque no momento.")
        else:
            st.dataframe(df_disp_material.drop(columns=["Valor Unitário"]), use_container_width=True, hide_index=True)

            st.markdown("<hr style='margin: 25px 0 15px 0; opacity: 0.2;'>", unsafe_allow_html=True)
            st.markdown("### Nova Solicitação de Material")

            df_raw_prod_user = pd.read_sql_query("SELECT codigo, item, quantidade FROM produtos WHERE quantidade > 0 ORDER BY codigo ASC;", conn)
            lista_siglas_coord_user = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["GERAL"]

            with st.form("form_solicitar_material", clear_on_submit=True):
                opcao_sol_mat = st.selectbox(
                    "Selecione o Material:",
                    df_raw_prod_user.index,
                    format_func=lambda x: f"{df_raw_prod_user.loc[x, 'codigo']} - {df_raw_prod_user.loc[x, 'item']} (Saldo: {df_raw_prod_user.loc[x, 'quantidade']})"
                )
                qtd_sol_mat = st.number_input("Quantidade Desejada:", min_value=1, max_value=int(df_raw_prod_user.loc[opcao_sol_mat, "quantidade"]), value=1, step=1)
                coord_sol_mat = st.selectbox("Coordenação:", lista_siglas_coord_user)
                obs_sol_mat = st.text_area("Observações (opcional):")

                if st.form_submit_button("Enviar Solicitação", type="primary"):
                    cod_sel = df_raw_prod_user.loc[opcao_sol_mat, "codigo"]
                    nome_sel = df_raw_prod_user.loc[opcao_sol_mat, "item"]
                    try:
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO solicitacoes_almoxarifado 
                            (tipo, referencia_codigo, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, status, observacao)
                            VALUES ('MATERIAL', %s, %s, %s, %s, %s, %s, 'PENDENTE', %s);
                        """, (cod_sel, nome_sel, qtd_sol_mat, st.session_state.NOME_USUARIO_LOGADO, st.session_state.EMAIL_USUARIO_LOGADO, coord_sol_mat, obs_sol_mat.strip()))
                        conn.commit()
                        st.session_state["msg_sucesso_material"] = True
                        st.rerun()
                    except Exception as ex:
                        conn.rollback()
                        st.error(f"Erro ao enviar solicitação: {ex}")

    # =========================================================================
    # NOVO MÓDULO DE SOLICITAÇÃO — TELA (PERFIL USUÁRIO): EMPRÉSTIMO DISPONÍVEL
    # =========================================================================
    elif escolha == "Empréstimo Disponível":
        st.markdown("""
            <div style="background-color: #2E7D32; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
                <h1 style="color: white; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                    Itens Disponíveis para Empréstimo
                </h1>
                <p style="color: #E8F5E9; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Consulte os itens do catálogo de empréstimo e solicite a retirada
                </p>
            </div>
        """, unsafe_allow_html=True)

        if st.session_state.get("msg_sucesso_emprestimo"):
            st.success("Sua solicitação foi encaminhada com sucesso!")
            del st.session_state["msg_sucesso_emprestimo"]

        df_emp_disp_user = pd.read_sql_query("""
            SELECT 
                codigo AS "Código", 
                item AS "Item / Equipamento", 
                quantidade_disponivel AS "Qtd Disponível",
                observacao AS "Observações"
            FROM emprestimo_itens WHERE quantidade_disponivel > 0 ORDER BY codigo ASC;
        """, conn)

        if df_emp_disp_user.empty:
            st.info("Nenhum item disponível para empréstimo no momento.")
        else:
            st.dataframe(df_emp_disp_user, use_container_width=True, hide_index=True)

            st.markdown("<hr style='margin: 25px 0 15px 0; opacity: 0.2;'>", unsafe_allow_html=True)
            st.markdown("### Nova Solicitação de Empréstimo")

            df_raw_emp_user = pd.read_sql_query("SELECT id, codigo, item, quantidade_disponivel FROM emprestimo_itens WHERE quantidade_disponivel > 0 ORDER BY codigo ASC;", conn)
            lista_siglas_coord_emp_user = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["GERAL"]

            with st.form("form_solicitar_emprestimo", clear_on_submit=True):
                opcao_sol_emp = st.selectbox(
                    "Selecione o Item:",
                    df_raw_emp_user.index,
                    format_func=lambda x: f"{df_raw_emp_user.loc[x, 'item']} (Disponível: {df_raw_emp_user.loc[x, 'quantidade_disponivel']})"
                )
                qtd_sol_emp = st.number_input("Quantidade Desejada:", min_value=1, max_value=int(df_raw_emp_user.loc[opcao_sol_emp, "quantidade_disponivel"]), value=1, step=1)
                coord_sol_emp = st.selectbox("Coordenação:", lista_siglas_coord_emp_user)

                col_dt1, col_dt2 = st.columns(2)
                data_retirada_sol = col_dt1.date_input("Data de Retirada: *", value=date.today(), format="DD/MM/YYYY")
                data_prev_sol = col_dt2.date_input("Data de Devolução: *", value=date.today(), format="DD/MM/YYYY")

                atividade_sol_emp = st.text_input("Atividade Associada: *", placeholder="Ex: Vistoria de campo na trilha X")
                obs_sol_emp = st.text_area("Observações (opcional):")

                st.markdown("<hr style='margin: 20px 0 10px 0; opacity: 0.2;'>", unsafe_allow_html=True)
                with st.expander("📄 Termo de Responsabilidade - clique para ler"):
                    st.markdown("""
### TERMO DE RESPONSABILIDADE PELO EMPRÉSTIMO DE MATERIAIS

Ao solicitar o empréstimo de materiais por meio deste sistema, o(a) solicitante declara que leu, compreendeu e concorda com as condições estabelecidas neste Termo de Responsabilidade.

**1. DA UTILIZAÇÃO DO MATERIAL**

O material solicitado deverá ser utilizado exclusivamente para atividades institucionais e de acordo com sua finalidade, observando-se as orientações de utilização, segurança e conservação aplicáveis.

O(A) solicitante compromete-se a utilizar o material de forma adequada, zelando por sua integridade, conservação e segurança durante todo o período em que estiver sob sua responsabilidade.

**2. DAS RESPONSABILIDADES DO SOLICITANTE**

Ao receber o material, o(a) solicitante compromete-se a:

I – utilizar o material exclusivamente para a finalidade a que se destina;

II – zelar pela guarda, conservação, integridade e segurança do material enquanto estiver sob sua responsabilidade;

III – utilizar o material de acordo com suas características, finalidade e orientações fornecidas pela Administração;

IV – não ceder, emprestar, transferir ou disponibilizar o material a terceiros sem autorização;

V – devolver o material no prazo estabelecido e nas condições adequadas de uso, ressalvado o desgaste natural decorrente de sua utilização regular;

VI – comunicar imediatamente à Coordenação de Operação e Suporte qualquer ocorrência relacionada ao material, incluindo dano, avaria, perda, extravio, furto, roubo, mau funcionamento ou qualquer outra eventualidade;

VII – informar qualquer situação que possa comprometer a integridade, conservação ou funcionamento do material.

**3. DA RESPONSABILIDADE POR DANOS E MAU USO**

O(A) solicitante declara estar ciente de que será responsável pela adequada utilização, guarda e conservação do material durante o período em que estiver sob sua responsabilidade.

Em caso de dano, avaria ou perda decorrente de mau uso, utilização inadequada, negligência, imprudência ou descumprimento das orientações de utilização, o(a) solicitante deverá comunicar imediatamente o ocorrido à Coordenação de Operação e Suporte, para registro e avaliação das providências administrativas cabíveis.

A responsabilidade do(a) solicitante não se aplica a danos decorrentes do desgaste natural pelo uso regular, de defeitos preexistentes ou de falhas decorrentes do funcionamento normal do material.

As ocorrências serão analisadas pela Administração, considerando as circunstâncias do fato, as condições em que o material foi disponibilizado e a forma de utilização, para definição das providências cabíveis.

**4. DA COMUNICAÇÃO DE OCORRÊNCIAS**

Qualquer eventualidade envolvendo o material deverá ser comunicada imediatamente à Coordenação de Operação e Suporte.

A comunicação deverá ocorrer mesmo que o dano ou problema aparentemente não impeça a utilização do material, permitindo que a Administração registre a ocorrência e adote as providências necessárias.

Em caso de perda, extravio, furto ou roubo, o(a) solicitante deverá comunicar o fato imediatamente e fornecer as informações necessárias para o devido registro e apuração da ocorrência.

**5. DA DEVOLUÇÃO**

O material deverá ser devolvido dentro do prazo estabelecido na solicitação ou sempre que solicitado pela Administração.

No momento da devolução, o material poderá ser submetido à conferência quanto à sua integridade, funcionamento, conservação e demais condições de uso.

Constatada alguma ocorrência, a Administração poderá realizar a avaliação das condições do material e registrar as informações no sistema.

**6. DA CIÊNCIA E ACEITE**

O(A) solicitante declara estar ciente de que a solicitação de empréstimo somente será efetivada após a leitura e aceitação deste Termo.

Ao marcar a opção "Li e concordo com o Termo de Responsabilidade", o(a) solicitante declara que:

- leu integralmente este Termo;
- compreendeu suas responsabilidades;
- compromete-se a utilizar e conservar adequadamente o material;
- compromete-se a comunicar imediatamente qualquer eventualidade à Coordenação de Operação e Suporte;
- está ciente de que poderá ser responsabilizado(a), nos termos aplicáveis, por danos decorrentes de mau uso, utilização inadequada, negligência, imprudência ou descumprimento das orientações de utilização.

A aceitação eletrônica deste Termo ficará vinculada à respectiva solicitação de empréstimo, juntamente com o registro do usuário, data e horário do aceite.
                    """)
                aceite_termo = st.checkbox("Li e concordo com o Termo de Responsabilidade pelo Empréstimo de Materiais. *")

                if st.form_submit_button("Enviar Solicitação", type="primary"):
                    if not atividade_sol_emp.strip():
                        st.error("O campo 'Atividade Associada' é obrigatório!")
                    elif data_prev_sol < data_retirada_sol:
                        st.error("A Data de Devolução não pode ser anterior à Data de Retirada!")
                    elif not aceite_termo:
                        st.error("A solicitação de empréstimo somente será efetivada após a leitura e aceitação do Termo de Responsabilidade!")
                    else:
                        item_id_sel = int(df_raw_emp_user.loc[opcao_sol_emp, "id"])
                        nome_sel_emp = df_raw_emp_user.loc[opcao_sol_emp, "item"]
                        try:
                            cursor = conn.cursor()
                            cursor.execute("""
                                INSERT INTO solicitacoes_almoxarifado 
                                (tipo, referencia_codigo, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, data_retirada, data_prevista, atividade_associada, status, observacao, termo_aceito, data_aceite_termo)
                                VALUES ('EMPRESTIMO', %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDENTE', %s, TRUE, CURRENT_TIMESTAMP);
                            """, (str(item_id_sel), nome_sel_emp, qtd_sol_emp, st.session_state.NOME_USUARIO_LOGADO, st.session_state.EMAIL_USUARIO_LOGADO, coord_sol_emp, data_retirada_sol, data_prev_sol, atividade_sol_emp.strip(), obs_sol_emp.strip()))
                            conn.commit()
                            st.session_state["msg_sucesso_emprestimo"] = True
                            st.rerun()
                        except Exception as ex:
                            conn.rollback()
                            st.error(f"Erro ao enviar solicitação: {ex}")

    # =========================================================================
    # NOVO MÓDULO DE SOLICITAÇÃO — TELA (PERFIL USUÁRIO): MINHAS SOLICITAÇÕES
    # =========================================================================
    elif escolha == "Minhas Solicitações":
        st.title("Minhas Solicitações")

        df_minhas_sol = pd.read_sql_query("""
            SELECT 
                tipo AS "Tipo",
                item_nome AS "Item",
                quantidade AS "Quantidade",
                COALESCE(atividade_associada, '-') AS "Atividade Associada",
                COALESCE(to_char(data_retirada, 'DD/MM/YYYY'), '-') AS "Data de Retirada",
                COALESCE(to_char(data_prevista, 'DD/MM/YYYY'), '-') AS "Data de Devolução",
                to_char(data_solicitacao AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo', 'DD/MM/YYYY HH24:MI') AS "Data da Solicitação",
                status AS "Status",
                COALESCE(to_char(data_decisao AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo', 'DD/MM/YYYY HH24:MI'), '-') AS "Data da Decisão",
                COALESCE(justificativa_rejeicao, '-') AS "Justificativa da Reprovação"
            FROM solicitacoes_almoxarifado
            WHERE solicitante_email = %(email_usuario)s
            ORDER BY id DESC;
        """, conn, params={"email_usuario": st.session_state.EMAIL_USUARIO_LOGADO})

        if df_minhas_sol.empty:
            st.info("Você ainda não realizou nenhuma solicitação.")
        else:
            def destacar_status_sol(val):
                if val == 'PENDENTE':
                    return 'background-color: #fff3cd; color: #856404; font-weight: bold;'
                elif val == 'APROVADA':
                    return 'background-color: #d4edda; color: #155724; font-weight: bold;'
                elif val == 'REJEITADA':
                    return 'background-color: rgba(198, 40, 40, 0.12); color: #c62828; font-weight: bold;'
                return ''

            st.dataframe(df_minhas_sol.style.map(destacar_status_sol, subset=['Status']), use_container_width=True, hide_index=True)

    # =========================================================================
    # NOVO MÓDULO DE SOLICITAÇÃO — TELA (PERFIL ADMINISTRADOR): SOLICITAÇÕES
    # =========================================================================
    elif escolha == label_solicitacoes:
        st.markdown("""
            <div style="background-color: #4CAF50; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
                <h1 style="color: white; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                    Solicitações de Usuários
                </h1>
                <p style="color: #E8F5E9; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Analise, aprove ou rejeite as solicitações de materiais e empréstimos
                </p>
            </div>
        """, unsafe_allow_html=True)

        aba_solicitacao = option_menu(
            menu_title=None,
            options=["Pendentes", "Histórico"],
            icons=["hourglass-split", "journal-text"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )

        cursor = conn.cursor()

        if aba_solicitacao == "Pendentes":
            df_pendentes = pd.read_sql_query("""
                SELECT id, tipo, referencia_codigo, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, data_retirada, data_prevista, atividade_associada, observacao, termo_aceito, data_aceite_termo
                FROM solicitacoes_almoxarifado WHERE status = 'PENDENTE' ORDER BY id ASC;
            """, conn)

            if df_pendentes.empty:
                st.info("Nenhuma solicitação pendente no momento.")
            else:
                for _, sol in df_pendentes.iterrows():
                    tipo_label = "Material (Almoxarifado)" if sol["tipo"] == "MATERIAL" else "Empréstimo"
                    linha_datas = ""
                    linha_termo = ""
                    if sol["tipo"] == "EMPRESTIMO":
                        ret_fmt = sol["data_retirada"].strftime('%d/%m/%Y') if sol["data_retirada"] is not None else "-"
                        dev_fmt = sol["data_prevista"].strftime('%d/%m/%Y') if sol["data_prevista"] is not None else "-"
                        linha_datas = f"Retirada: {ret_fmt} | Devolução: {dev_fmt}<br>"
                        if sol["termo_aceito"] and sol["data_aceite_termo"] is not None:
                            linha_termo = f"✅ Termo de Responsabilidade aceito em {converter_para_horario_br(sol['data_aceite_termo']).strftime('%d/%m/%Y %H:%M')}<br>"
                    linha_atividade = f"Atividade Associada: {sol['atividade_associada']}<br>" if sol["atividade_associada"] else ""
                    linha_obs = f"Observações: {sol['observacao']}" if sol["observacao"] else ""

                    st.markdown(f"""
                        <div style="border: 1px solid rgba(76, 175, 80, 0.3); border-radius: 8px; padding: 15px; margin-bottom: 12px;">
                            <b>#{sol['id']} — {tipo_label}</b><br>
                            Item: {sol['item_nome']} | Quantidade: {sol['quantidade']}<br>
                            Solicitante: {sol['solicitante_nome']} ({sol['solicitante_email']}) | Coordenação: {sol['coordenacao'] or '-'}<br>
                            {linha_datas}{linha_termo}{linha_atividade}{linha_obs}
                        </div>
                    """, unsafe_allow_html=True)

                    just_rejeicao = st.text_area(
                        "Justificativa da Reprovação (obrigatória caso vá rejeitar):",
                        key=f"just_rejeitar_{sol['id']}",
                        placeholder="Descreva o motivo da reprovação desta solicitação..."
                    )

                    col_ap1, col_ap2, col_ap3 = st.columns([1, 1, 4])
                    with col_ap1:
                        if st.button("✅ Aprovar", key=f"aprovar_{sol['id']}", type="primary"):
                            try:
                                if sol["tipo"] == "MATERIAL":
                                    cursor.execute("SELECT quantidade FROM produtos WHERE codigo = %s;", (sol["referencia_codigo"],))
                                    res_prod = cursor.fetchone()
                                    if not res_prod or res_prod[0] < sol["quantidade"]:
                                        st.error("Saldo insuficiente em estoque para aprovar esta solicitação.")
                                    else:
                                        cursor.execute("UPDATE produtos SET quantidade = quantidade - %s WHERE codigo = %s;", (sol["quantidade"], sol["referencia_codigo"]))
                                        cursor.execute("""
                                            INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s);
                                        """, (date.today().strftime("%Y-%m-%d"), "Saída", sol["referencia_codigo"], sol["item_nome"], sol["quantidade"], sol["solicitante_nome"], sol["coordenacao"]))
                                        cursor.execute("""
                                            UPDATE solicitacoes_almoxarifado SET status = 'APROVADA', data_decisao = CURRENT_TIMESTAMP, aprovador = %s 
                                            WHERE id = %s;
                                        """, (st.session_state.NOME_USUARIO_LOGADO, sol["id"]))
                                        conn.commit()

                                        threading.Thread(
                                            target=enviar_email_notificacao,
                                            args=(
                                                sol["solicitante_email"],
                                                "Solicitação de Material Aprovada",
                                                f"""
                                                <p>Olá, {sol['solicitante_nome']},</p>
                                                <p>Sua solicitação do item <b>{sol['item_nome']}</b> (Quantidade: {sol['quantidade']}) foi <b>aprovada</b>.</p>
                                                <p>O material já está disponível para retirada no Almoxarifado.</p>
                                                <p>Atenciosamente,<br>Gestão de Almoxarifado NGI Carajás</p>
                                                """
                                            ),
                                            daemon=True
                                        ).start()
                                        st.success("Solicitação aprovada e usuário notificado por e-mail!")
                                        st.rerun()
                                else:
                                    cursor.execute("SELECT quantidade_disponivel FROM emprestimo_itens WHERE id = %s;", (int(sol["referencia_codigo"]),))
                                    res_emp = cursor.fetchone()
                                    if not res_emp or res_emp[0] < sol["quantidade"]:
                                        st.error("Saldo insuficiente disponível para aprovar este empréstimo.")
                                    else:
                                        cursor.execute("""
                                            INSERT INTO emprestimo_registros 
                                            (item_id, item_nome, quantidade, pessoa, coordenacao, data_retirada, data_prevista, status)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'EMPRESTADO');
                                        """, (int(sol["referencia_codigo"]), sol["item_nome"], sol["quantidade"], sol["solicitante_nome"], sol["coordenacao"], sol["data_retirada"] if sol["data_retirada"] is not None else date.today(), sol["data_prevista"]))
                                        cursor.execute("""
                                            UPDATE emprestimo_itens SET quantidade_disponivel = quantidade_disponivel - %s WHERE id = %s;
                                        """, (sol["quantidade"], int(sol["referencia_codigo"])))
                                        cursor.execute("""
                                            UPDATE solicitacoes_almoxarifado SET status = 'APROVADA', data_decisao = CURRENT_TIMESTAMP, aprovador = %s 
                                            WHERE id = %s;
                                        """, (st.session_state.NOME_USUARIO_LOGADO, sol["id"]))
                                        conn.commit()

                                        threading.Thread(
                                            target=enviar_email_notificacao,
                                            args=(
                                                sol["solicitante_email"],
                                                "Solicitação de Empréstimo Aprovada",
                                                f"""
                                                <p>Olá, {sol['solicitante_nome']},</p>
                                                <p>Sua solicitação de empréstimo do item <b>{sol['item_nome']}</b> (Quantidade: {sol['quantidade']}) foi <b>aprovada</b>.</p>
                                                <p>O item já está disponível para retirada no Almoxarifado.</p>
                                                <p>Atenciosamente,<br>Gestão de Almoxarifado NGI Carajás</p>
                                                """
                                            ),
                                            daemon=True
                                        ).start()
                                        st.success("Empréstimo aprovado e usuário notificado por e-mail!")
                                        st.rerun()
                            except Exception as ex:
                                conn.rollback()
                                st.error(f"Erro ao aprovar solicitação: {ex}")

                    with col_ap2:
                        if st.button("❌ Rejeitar", key=f"rejeitar_{sol['id']}"):
                            if not just_rejeicao.strip():
                                st.error("Para rejeitar, é obrigatório informar a Justificativa da Reprovação!")
                            else:
                                cursor.execute("""
                                    UPDATE solicitacoes_almoxarifado 
                                    SET status = 'REJEITADA', data_decisao = CURRENT_TIMESTAMP, aprovador = %s, justificativa_rejeicao = %s 
                                    WHERE id = %s;
                                """, (st.session_state.NOME_USUARIO_LOGADO, just_rejeicao.strip(), sol["id"]))
                                conn.commit()

                                threading.Thread(
                                    target=enviar_email_notificacao,
                                    args=(
                                        sol["solicitante_email"],
                                        "Solicitação Reprovada",
                                        f"""
                                        <p>Olá, {sol['solicitante_nome']},</p>
                                        <p>Sua solicitação do item <b>{sol['item_nome']}</b> (Quantidade: {sol['quantidade']}) foi <b>reprovada</b>.</p>
                                        <p><b>Justificativa:</b> {just_rejeicao.strip()}</p>
                                        <p>Atenciosamente,<br>Gestão de Almoxarifado NGI Carajás</p>
                                        """
                                    ),
                                    daemon=True
                                ).start()
                                st.warning("Solicitação rejeitada e usuário notificado por e-mail!")
                                st.rerun()

        elif aba_solicitacao == "Histórico":
            df_hist_sol = pd.read_sql_query("""
                SELECT 
                    tipo AS "Tipo",
                    item_nome AS "Item",
                    quantidade AS "Quantidade",
                    solicitante_nome AS "Solicitante",
                    solicitante_email AS "E-mail",
                    coordenacao AS "Coordenação",
                    COALESCE(atividade_associada, '-') AS "Atividade Associada",
                    COALESCE(to_char(data_retirada, 'DD/MM/YYYY'), '-') AS "Data de Retirada",
                    COALESCE(to_char(data_prevista, 'DD/MM/YYYY'), '-') AS "Data de Devolução",
                    to_char(data_solicitacao AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo', 'DD/MM/YYYY HH24:MI') AS "Data Solicitação",
                    status AS "Status",
                    COALESCE(aprovador, '-') AS "Decidido Por",
                    COALESCE(to_char(data_decisao AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo', 'DD/MM/YYYY HH24:MI'), '-') AS "Data Decisão",
                    COALESCE(justificativa_rejeicao, '-') AS "Justificativa da Reprovação"
                FROM solicitacoes_almoxarifado WHERE status != 'PENDENTE' ORDER BY id DESC;
            """, conn)

            if df_hist_sol.empty:
                st.info("Nenhuma solicitação decidida até o momento.")
            else:
                def destacar_status_hist(val):
                    if val == 'APROVADA':
                        return 'background-color: #d4edda; color: #155724; font-weight: bold;'
                    elif val == 'REJEITADA':
                        return 'background-color: rgba(198, 40, 40, 0.12); color: #c62828; font-weight: bold;'
                    return ''

                st.dataframe(df_hist_sol.style.map(destacar_status_hist, subset=['Status']), use_container_width=True, hide_index=True)

    # --- TELA: CADASTRAR PRODUTO ---
    elif escolha == "Cadastrar Produto":
        st.title("Gerenciamento de Produtos")
        aba_selecionada = option_menu(
            menu_title=None,
            options=["Novo Material", "Editar / Excluir Produtos"],
            icons=["plus-circle", "pencil-square"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )

        if aba_selecionada == "Novo Material":
            with st.form("form_novo_produto", clear_on_submit=True):
                col_a, col_b = st.columns(2)
                cod = col_a.text_input("Código")
                nome_it = col_b.text_input("Nome do Material")
                cat_it = col_a.selectbox("Categoria", lista_categorias)
                val_unit = col_b.number_input("Valor Unitário (R$)", min_value=0.0, step=0.01, format="%.2f")
                st.caption("Novos materiais são registrados com saldo inicial 0.")
                
                if st.form_submit_button("Finalizar Cadastro", type="primary"):
                    if cod and nome_it:
                        try:
                            cursor = conn.cursor()
                            cursor.execute("INSERT INTO produtos VALUES (%s, %s, %s, %s, %s);", (cod.strip(), nome_it.strip(), 0, cat_it, float(val_unit)))
                            conn.commit()
                            st.success(f"Sucesso! {nome_it} adicionado.")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error(f"Erro! Código {cod} já existe.")
                    else:
                        st.error("Preencha todos os campos!")

        elif aba_selecionada == "Editar / Excluir Produtos":
            if not df_produtos.empty:
                st.dataframe(df_produtos, use_container_width=True, hide_index=True)
                df_raw_prod = pd.read_sql_query("SELECT * FROM produtos", conn)
                opcao_selecionada = st.selectbox("Selecione para modificar:", df_raw_prod.index, format_func=lambda x: f"{df_raw_prod.loc[x, 'codigo']} - {df_raw_prod.loc[x, 'item']}")
                cod_atual = df_raw_prod.loc[opcao_selecionada, "codigo"]
                
                col_ed1, col_ed2 = st.columns(2)
                edit_cod = col_ed1.text_input("Código:", value=df_raw_prod.loc[opcao_selecionada, "codigo"])
                edit_item = col_ed2.text_input("Nome:", value=df_raw_prod.loc[opcao_selecionada, "item"])
                edit_qtd = col_ed1.number_input("Quantidade (Ajuste):", min_value=0, value=int(df_raw_prod.loc[opcao_selecionada, "quantidade"]))
                cat_atual = df_raw_prod.loc[opcao_selecionada, "categoria"]
                idx_cat_padrao = lista_categorias.index(cat_atual) if cat_atual in lista_categorias else 0
                edit_cat = col_ed2.selectbox("Categoria:", lista_categorias, index=idx_cat_padrao)
                edit_val = st.number_input("Valor Unitário:", min_value=0.0, step=0.01, format="%.2f", value=float(df_raw_prod.loc[opcao_selecionada, "valor_unitario"]))
                
                col_b_prod1, col_b_prod2 = st.columns([1, 4])
                with col_b_prod1:
                    if st.button("Salvar Alterações", type="primary"):
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE produtos 
                            SET codigo = %s, item = %s, quantidade = %s, categoria = %s, valor_unitario = %s 
                            WHERE codigo = %s;
                        """, (edit_cod.strip(), edit_item.strip(), edit_qtd, edit_cat, float(edit_val), cod_atual))
                        conn.commit()
                        st.success("Modificado com sucesso!")
                        st.rerun()

                with col_b_prod2:
                    if st.button("Excluir Produto"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM produtos WHERE codigo = %s;", (cod_atual,))
                        conn.commit()
                        st.warning("Removido com sucesso.")
                        st.rerun()

    # --- TELA: CADASTRAR CATEGORIA ---
    elif escolha == "Cadastrar Categoria":
        st.title("Gerenciamento de Categorias")
        aba_selecionada = option_menu(
            menu_title=None,
            options=["Nova Categoria", "Editar / Excluir Categorias"],
            icons=["plus-circle", "pencil-square"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )

        if aba_selecionada == "Nova Categoria":
            col_cat1, col_cat2 = st.columns([1, 2])
            with col_cat1:
                nova_cat = st.text_input("Nome da Nova Categoria:")
                if st.button("Adicionar Categoria", type="primary"):
                    if nova_cat and nova_cat.strip():
                        try:
                            cursor = conn.cursor()
                            cursor.execute("INSERT INTO categorias VALUES (%s);", (nova_cat.strip(),))
                            conn.commit()
                            st.success("Adicionada!")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error("Esta categoria já existe.")
            with col_cat2:
                st.dataframe(pd.DataFrame(lista_categorias, columns=["Categorias Ativas"]), use_container_width=True, hide_index=True)

        elif aba_selecionada == "Editar / Excluir Categorias":
            if lista_categorias:
                cat_selecionada = st.selectbox("Selecione a categoria:", lista_categorias)
                edit_nome_cat = st.text_input("Editar Nome:", value=cat_selecionada)
                c_btn_cat1, c_btn_cat2 = st.columns([1, 4])
                
                with c_btn_cat1:
                    if st.button("Salvar Edição", type="primary"):
                        cursor = conn.cursor()
                        cursor.execute("UPDATE categorias SET nome = %s WHERE nome = %s;", (edit_nome_cat.strip(), cat_selecionada))
                        conn.commit()
                        st.success("Atualizado!")
                        st.rerun()

                with c_btn_cat2:
                    if st.button("Excluir Categoria"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM categorias WHERE nome = %s;", (cat_selecionada,))
                        conn.commit()
                        st.warning("Removida.")
                        st.rerun()

    # --- TELA: CADASTRAR USUÁRIO ---
    elif escolha == "Cadastrar Usuário":
        st.title("Cadastrar Usuário")
        aba_selecionada = option_menu(
            menu_title=None,
            options=["Novo Usuário", "Editar / Excluir Usuários"],
            icons=["person-plus", "pencil-square"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )

        if aba_selecionada == "Novo Usuário":
            with st.form("cad_user", clear_on_submit=True):
                n = st.text_input("Nome")
                e = st.text_input("E-mail")
                s = st.text_input("Senha", type="password")
                p = st.selectbox("Perfil", ["Administrador", "Usuário Comum"])
                
                if st.form_submit_button("Salvar", type="primary"):
                    if n and e:
                        try:
                            cursor = conn.cursor()
                            cursor.execute("""
                                INSERT INTO usuarios (nome, email, senha, perfil) 
                                VALUES (%s, %s, %s, %s);
                            """, (n.strip(), e.strip().lower(), s if s else "123", p))
                            conn.commit()
                            st.success("Usuário registrado com sucesso!")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error("Este e-mail já está cadastrado.")
                    else:
                        st.error("Preencha o Nome e o E-mail!")

        elif aba_selecionada == "Editar / Excluir Usuários":
            df_raw_users = pd.read_sql_query("SELECT nome, email, perfil, senha FROM usuarios ORDER BY nome ASC", conn)
            if not df_raw_users.empty:
                st.dataframe(df_raw_users[["nome", "email", "perfil"]], use_container_width=True, hide_index=True)
                idx_user = st.selectbox("Selecione para editar:", df_raw_users.index, format_func=lambda x: f"{df_raw_users.loc[x, 'nome']} ({df_raw_users.loc[x, 'email']})")
                email_chave = df_raw_users.loc[idx_user, "email"]
                
                edit_n = st.text_input("Nome:", value=df_raw_users.loc[idx_user, "nome"])
                edit_e = st.text_input("E-mail:", value=df_raw_users.loc[idx_user, "email"])
                edit_s = st.text_input("Senha:", value=df_raw_users.loc[idx_user, "senha"], type="password")
                edit_p = st.selectbox("Perfil:", ["Administrador", "Usuário Comum"], index=0 if df_raw_users.loc[idx_user, "perfil"] == "Administrador" else 1)
                
                c_btn_u1, c_btn_u2 = st.columns([1, 4])
                with c_btn_u1:
                    if st.button("Atualizar Dados", type="primary"):
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE usuarios 
                            SET nome = %s, email = %s, senha = %s, perfil = %s 
                            WHERE email = %s;
                        """, (edit_n.strip(), edit_e.strip().lower(), edit_s, edit_p, email_chave))
                        conn.commit()
                        st.success("Atualizado!")
                        st.rerun()

                with c_btn_u2:
                    if st.button("Excluir Usuário"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM usuarios WHERE email = %s;", (email_chave,))
                        conn.commit()
                        st.warning("Removido.")
                        st.rerun()

    # --- TELA: CADASTRAR COORDENAÇÃO ---
    elif escolha == "Cadastrar Coordenação":
        st.title("Cadastrar Coordenação")
        aba_selecionada = option_menu(
            menu_title=None,
            options=["Nova Coordenação", "Editar / Excluir Coordenação"],
            icons=["building-add", "pencil-square"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )

        if aba_selecionada == "Nova Coordenação":
            with st.form("cad_coord", clear_on_submit=True):
                sigla_c = st.text_input("Sigla da Coordenação")
                nome_c = st.text_input("Nome Completo")
                
                if st.form_submit_button("Cadastrar", type="primary"):
                    if sigla_c and nome_c:
                        try:
                            cursor = conn.cursor()
                            cursor.execute("INSERT INTO coordenacoes VALUES (%s, %s);", (sigla_c.strip().upper(), nome_c.strip()))
                            conn.commit()
                            st.success("Coordenação registrada!")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error("Esta Sigla já está cadastrada.")
                    else:
                        st.error("Preencha todos os campos!")

        elif aba_selecionada == "Editar / Excluir Coordenação":
            if not df_coordenacoes.empty:
                st.dataframe(df_coordenacoes, use_container_width=True, hide_index=True)
                df_raw_coord = pd.read_sql_query("SELECT * FROM coordenacoes", conn)
                idx_coord = st.selectbox("Selecione para alterar:", df_raw_coord.index, format_func=lambda x: f"{df_raw_coord.loc[x, 'sigla']} - {df_raw_coord.loc[x, 'nome']}")
                sigla_chave = df_raw_coord.loc[idx_coord, "sigla"]
                
                edit_sigla = st.text_input("Sigla:", value=df_raw_coord.loc[idx_coord, "sigla"])
                edit_nome_c = st.text_input("Nome:", value=df_raw_coord.loc[idx_coord, "nome"])
                
                c_btn_c1, c_btn_c2 = st.columns([1, 4])
                with c_btn_c1:
                    if st.button("Salvar Alteração", type="primary"):
                        cursor = conn.cursor()
                        cursor.execute("UPDATE coordenacoes SET sigla = %s, nome = %s WHERE sigla = %s;", (edit_sigla.strip().upper(), edit_nome_c.strip(), sigla_chave))
                        conn.commit()
                        st.success("Atualizada!")
                        st.rerun()

                with c_btn_c2:
                    if st.button("Excluir Coordenação"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM coordenacoes WHERE sigla = %s;", (sigla_chave,))
                        conn.commit()
                        st.warning("Removida.")
                        st.rerun()

  
    # --- TELA: MOVIMENTAÇÃO DE ESTOQUE (3 ABAS CONFORME SOLICITADO) ---
    elif escolha == "Movimentação de Estoque":
        st.title("Movimentação de Estoque")
        
        aba_movimentacao = option_menu(
            menu_title=None,
            options=["Registro de Entrada", "Registro de Saída", "Histórico de Movimentação"],
            icons=["arrow-down-circle", "arrow-up-circle", ""], # Ícone de histórico removido completamente para não parecer IA
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )
        
        if df_produtos.empty:
            st.warning("Nenhum produto cadastrado para movimentar.")
        else:
            df_raw_prod = pd.read_sql_query("SELECT codigo, item, quantidade FROM produtos ORDER BY codigo ASC", conn)
            lista_siglas_coord = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["N/A"]
            
            # 1. ABA: REGISTRO DE ENTRADA
            if aba_movimentacao == "Registro de Entrada":
                with st.form("form_entrada", clear_on_submit=True):
                    col_e1, col_e2 = st.columns(2)
                    data_mov = col_e1.date_input("Data da Movimentação:", value=datetime.today(), format="DD/MM/YYYY").strftime("%Y-%m-%d")
                    opcao_prod = col_e2.selectbox(
                        "Selecione o Material:", 
                        df_raw_prod.index, 
                        format_func=lambda x: f"{df_raw_prod.loc[x, 'codigo']} - {df_raw_prod.loc[x, 'item']} (Saldo: {df_raw_prod.loc[x, 'quantidade']})"
                    )
                    qtd_mov = col_e1.number_input("Quantidade:", min_value=1, step=1, value=1)
                    
                    if st.form_submit_button("Registrar Entrada", type="primary"):
                        prod_codigo = df_raw_prod.loc[opcao_prod, "codigo"]
                        prod_nome = df_raw_prod.loc[opcao_prod, "item"]
                        prod_qtd_atual = int(df_raw_prod.loc[opcao_prod, "quantidade"])
                        nova_qtd = prod_qtd_atual + qtd_mov
                        
                        try:
                            cursor = conn.cursor()
                            cursor.execute("UPDATE produtos SET quantidade = %s WHERE codigo = %s;", (nova_qtd, prod_codigo))
                            cursor.execute("""
                                INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
                                VALUES (%s, %s, %s, %s, %s, %s, %s);
                            """, (data_mov, "Entrada", prod_codigo, prod_nome, qtd_mov, st.session_state.NOME_USUARIO_LOGADO, "Almoxarifado"))
                            conn.commit()
                            st.success(f"Entrada de {qtd_mov} un. de '{prod_nome}' registrada! Novo saldo: {nova_qtd}.")
                            st.rerun()
                        except Exception as ex:
                            conn.rollback()
                            st.error(f"Erro ao salvar entrada: {ex}")
            
            # 2. ABA: REGISTRO DE SAÍDA
            elif aba_movimentacao == "Registro de Saída":
                with st.form("form_saida", clear_on_submit=True):
                    col_s1, col_s2 = st.columns(2)
                    data_mov = col_s1.date_input("Data da Movimentação:", value=datetime.today(), format="DD/MM/YYYY").strftime("%Y-%m-%d")
                    opcao_prod = col_s2.selectbox(
                        "Selecione o Material:", 
                        df_raw_prod.index, 
                        format_func=lambda x: f"{df_raw_prod.loc[x, 'codigo']} - {df_raw_prod.loc[x, 'item']} (Saldo: {df_raw_prod.loc[x, 'quantidade']})"
                    )
                    qtd_mov = col_s1.number_input("Quantidade da Movimentação:", min_value=1, step=1, value=1)
                    resp_mov = col_s2.text_input("Nome da Pessoa Responsável pela Retirada:")
                    coord_mov = col_s1.selectbox("Coordenação Destino:", lista_siglas_coord)
                    
                    if st.form_submit_button("Registrar Saída", type="primary"):
                        if not resp_mov.strip():
                            st.error(" Por favor, digite o nome da pessoa responsável pela retirada.")
                        else:
                            prod_codigo = df_raw_prod.loc[opcao_prod, "codigo"]
                            prod_nome = df_raw_prod.loc[opcao_prod, "item"]
                            prod_qtd_atual = int(df_raw_prod.loc[opcao_prod, "quantidade"])
                            
                            if prod_qtd_atual >= qtd_mov:
                                nova_qtd = prod_qtd_atual - qtd_mov
                                try:
                                    cursor = conn.cursor()
                                    cursor.execute("UPDATE produtos SET quantidade = %s WHERE codigo = %s;", (nova_qtd, prod_codigo))
                                    cursor.execute("""
                                        INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                                    """, (data_mov, "Saída", prod_codigo, prod_nome, qtd_mov, resp_mov.strip(), coord_mov))
                                    conn.commit()
                                    st.success(f"Saída de {qtd_mov} un. de '{prod_nome}' registrada! Novo saldo: {nova_qtd}.")
                                    st.rerun()
                                except Exception as ex:
                                    conn.rollback()
                                    st.error(f"Erro ao salvar saída: {ex}")
                            else:
                                st.error(f"Saldo Insuficiente! O material possui apenas {prod_qtd_atual} unidades no estoque.")
            
            # 3. ABA: HISTÓRICO DE MOVIMENTAÇÃO
            elif aba_movimentacao == "Histórico de Movimentação":
                st.markdown("### Histórico de Movimentação")
                if not df_movimentacoes.empty:
                    st.dataframe(df_movimentacoes.sort_index(ascending=False), use_container_width=True, hide_index=True)
                else:
                    st.info("Nenhuma movimentação registrada até o momento.")

    # =========================================================================
    # NOVO MÓDULO: RELATÓRIOS / DASHBOARD (PERFIL ADMINISTRADOR)
    # =========================================================================
    elif escolha == "Relatórios":
        COR_CARD_FUNDO = "#0F3D1E"
        COR_ACCENT_LIMAO = "#C7E36B"
        COR_BARRA_LIMAO = "#9ACD32"
        COR_BARRA_VERDE_CLARO = "#7FB069"
        COR_TEXTO_CLARO = "#e8f0d8"

        st.markdown(f"""
            <div style="background-color: {COR_CARD_FUNDO}; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
                <h1 class="kpi-valor-limao" style="margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 700;">
                    Relatórios e Dashboard
                </h1>
                <p class="kpi-titulo-branco" style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Visão consolidada de Estoque, Solicitações, Movimentações e Empréstimos
                </p>
            </div>
        """, unsafe_allow_html=True)

        # ---------------------------------------------------------------
        # FILTRO DE PERÍODO (aplica-se a Solicitações e Movimentações)
        # ---------------------------------------------------------------
        col_filtro_rel, _ = st.columns([1, 2])
        filtro_periodo_rel = col_filtro_rel.selectbox(
            "Filtrar Solicitações e Movimentações por período:",
            ["Todo o Período", "Este Mês", "Este Trimestre", "Este Ano"]
        )

        hoje_rel = date.today()
        if filtro_periodo_rel == "Este Mês":
            data_inicio_rel = hoje_rel.replace(day=1)
        elif filtro_periodo_rel == "Este Trimestre":
            mes_inicio_trim = ((hoje_rel.month - 1) // 3) * 3 + 1
            data_inicio_rel = hoje_rel.replace(month=mes_inicio_trim, day=1)
        elif filtro_periodo_rel == "Este Ano":
            data_inicio_rel = hoje_rel.replace(month=1, day=1)
        else:
            data_inicio_rel = None

        cursor_rel = conn.cursor()

        # ---------------------------------------------------------------
        # CARTÕES DE KPI
        # ---------------------------------------------------------------
        total_itens_estoque_rel = int(df_produtos["Quantidade"].sum()) if not df_produtos.empty else 0
        if not df_produtos.empty:
            valor_total_estoque_rel = float((df_produtos["Quantidade"] * df_produtos["Valor Unitário"].astype(float)).sum())
        else:
            valor_total_estoque_rel = 0.0

        if data_inicio_rel:
            cursor_rel.execute("SELECT COUNT(*) FROM solicitacoes_almoxarifado WHERE data_solicitacao >= %s;", (data_inicio_rel,))
            total_sol_modulo = cursor_rel.fetchone()[0]
            cursor_rel.execute("SELECT COUNT(*) FROM movimentacoes WHERE tipo = 'Saída' AND data::date >= %s;", (data_inicio_rel,))
            total_saidas_como_sol = cursor_rel.fetchone()[0]
        else:
            cursor_rel.execute("SELECT COUNT(*) FROM solicitacoes_almoxarifado;")
            total_sol_modulo = cursor_rel.fetchone()[0]
            cursor_rel.execute("SELECT COUNT(*) FROM movimentacoes WHERE tipo = 'Saída';")
            total_saidas_como_sol = cursor_rel.fetchone()[0]
        total_solicitacoes_rel = total_sol_modulo + total_saidas_como_sol

        if data_inicio_rel:
            cursor_rel.execute("SELECT COUNT(*) FROM movimentacoes WHERE data::date >= %s;", (data_inicio_rel,))
        else:
            cursor_rel.execute("SELECT COUNT(*) FROM movimentacoes;")
        total_movimentacoes_rel = cursor_rel.fetchone()[0]

        def formatar_moeda_br(valor):
            return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        def renderizar_kpi(coluna, titulo, valor):
            coluna.markdown(f"""
                <div class="rel-kpi-card" style="background-color: {COR_CARD_FUNDO}; border-radius: 10px; text-align: center; min-height: 100px;">
                    <span class="kpi-titulo-branco" style="font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">{titulo}</span>
                    <h2 class="kpi-valor-branco" style="margin: 8px 0 0 0; font-size: 26px; font-weight: 700;">{valor}</h2>
                </div>
            """, unsafe_allow_html=True)

        def renderizar_kpi_duplo(coluna, titulo, rotulo1, valor1, rotulo2, valor2):
            coluna.markdown(f"""
                <div class="rel-kpi-card" style="background-color: {COR_CARD_FUNDO}; border-radius: 10px; text-align: center; min-height: 100px;">
                    <span class="kpi-titulo-branco" style="font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">{titulo}</span>
                    <div style="display: flex; justify-content: center; gap: 32px; margin-top: 10px;">
                        <div>
                            <div class="kpi-valor-limao" style="font-size: 22px; font-weight: 700;">{valor1}</div>
                            <div class="kpi-valor-branco" style="font-size: 11px; opacity: 0.85;">{rotulo1}</div>
                        </div>
                        <div>
                            <div class="kpi-valor-branco" style="font-size: 22px; font-weight: 700;">{valor2}</div>
                            <div class="kpi-valor-branco" style="font-size: 11px; opacity: 0.85;">{rotulo2}</div>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

        col_k1, col_k2, col_k3, col_k4 = st.columns(4)
        renderizar_kpi(col_k1, "Itens em Estoque", f"{total_itens_estoque_rel:,}".replace(",", "."))
        renderizar_kpi(col_k2, "Valor Total em Estoque", formatar_moeda_br(valor_total_estoque_rel))
        renderizar_kpi(col_k3, "Total de Solicitações", str(total_solicitacoes_rel))
        renderizar_kpi(col_k4, "Total de Movimentações", str(total_movimentacoes_rel))

        st.markdown("<br>", unsafe_allow_html=True)

        # ---------------------------------------------------------------
        # GRÁFICOS: MATERIAL POR CATEGORIA / SOLICITAÇÕES POR COORDENAÇÃO
        # ---------------------------------------------------------------
        def estilizar_grafico(fig, altura=300):
            fig.update_layout(
                paper_bgcolor=COR_CARD_FUNDO,
                plot_bgcolor=COR_CARD_FUNDO,
                font=dict(color=COR_TEXTO_CLARO, size=12),
                margin=dict(l=10, r=10, t=40, b=10),
                height=altura,
                xaxis=dict(showgrid=False, tickfont=dict(color=COR_TEXTO_CLARO)),
                yaxis=dict(showgrid=True, gridcolor="#1a5c2e", tickfont=dict(color=COR_TEXTO_CLARO)),
                showlegend=False
            )
            return fig

        col_g1, col_g2 = st.columns(2)
        altura_categoria = 300

        with col_g1:
            if not df_produtos.empty:
                resumo_cat_rel = df_produtos.groupby("Categoria")["Quantidade"].sum().sort_values(ascending=False)
                altura_categoria = max(300, 42 * len(resumo_cat_rel))
                fig_categoria = go.Figure(go.Bar(
                    x=resumo_cat_rel.values, y=resumo_cat_rel.index,
                    orientation="h",
                    marker_color=COR_BARRA_LIMAO,
                    text=resumo_cat_rel.values, textposition="outside", textfont=dict(color=COR_TEXTO_CLARO)
                ))
                fig_categoria.update_layout(title=dict(text="MATERIAL POR CATEGORIA", font=dict(color=COR_ACCENT_LIMAO, size=14)))
                fig_categoria.update_yaxes(autorange="reversed")
                fig_categoria.update_xaxes(showgrid=True, gridcolor="#1a5c2e")
                fig_categoria = estilizar_grafico(fig_categoria, altura=altura_categoria)
                st.plotly_chart(fig_categoria, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("Sem dados de estoque para exibir.")

        with col_g2:
            query_coord_rel = """
                SELECT coordenacao, COUNT(*) AS total FROM (
                    SELECT COALESCE(coordenacao, 'Não informado') AS coordenacao, data_solicitacao AS data_ref
                    FROM solicitacoes_almoxarifado
                    __FILTRO_SOLICITACAO__
                    UNION ALL
                    SELECT COALESCE(coordenacao, 'Não informado') AS coordenacao, data::date AS data_ref
                    FROM movimentacoes
                    WHERE tipo = 'Saída' __FILTRO_MOVIMENTACAO__
                ) unificado
                GROUP BY coordenacao ORDER BY total DESC;
            """
            params_coord_rel = []
            if data_inicio_rel:
                query_coord_rel = query_coord_rel.replace("__FILTRO_SOLICITACAO__", "WHERE data_solicitacao >= %s")
                query_coord_rel = query_coord_rel.replace("__FILTRO_MOVIMENTACAO__", "AND data::date >= %s")
                params_coord_rel = [data_inicio_rel, data_inicio_rel]
            else:
                query_coord_rel = query_coord_rel.replace("__FILTRO_SOLICITACAO__", "")
                query_coord_rel = query_coord_rel.replace("__FILTRO_MOVIMENTACAO__", "")
            df_coord_rel = pd.read_sql_query(query_coord_rel, conn, params=tuple(params_coord_rel) if params_coord_rel else None)

            if not df_coord_rel.empty:
                fig_coord = go.Figure(go.Bar(
                    x=df_coord_rel["coordenacao"], y=df_coord_rel["total"],
                    marker_color=COR_BARRA_VERDE_CLARO,
                    text=df_coord_rel["total"], textposition="outside", textfont=dict(color=COR_TEXTO_CLARO),
                    width=0.25 if len(df_coord_rel) <= 2 else None
                ))
                fig_coord.update_layout(title=dict(text="SOLICITAÇÕES POR COORDENAÇÃO", font=dict(color=COR_ACCENT_LIMAO, size=14)), bargap=0.6)
                fig_coord = estilizar_grafico(fig_coord, altura=altura_categoria)
                st.plotly_chart(fig_coord, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("Nenhuma solicitação ou saída no período selecionado.")

        st.markdown("<br>", unsafe_allow_html=True)

        # ---------------------------------------------------------------
        # MOVIMENTAÇÕES (ENTRADA X SAÍDA) E EMPRÉSTIMOS
        # ---------------------------------------------------------------
        query_mov_tipo = "SELECT tipo, COUNT(*) AS total FROM movimentacoes"
        params_mov_tipo = []
        if data_inicio_rel:
            query_mov_tipo += " WHERE data::date >= %s"
            params_mov_tipo.append(data_inicio_rel)
        query_mov_tipo += " GROUP BY tipo;"
        cursor_rel.execute(query_mov_tipo, tuple(params_mov_tipo))
        resultado_mov_tipo = dict(cursor_rel.fetchall())
        total_entradas_rel = resultado_mov_tipo.get("Entrada", 0)
        total_saidas_rel = resultado_mov_tipo.get("Saída", 0)

        cursor_rel.execute("SELECT COALESCE(SUM(quantidade_total), 0), COALESCE(SUM(quantidade_disponivel), 0) FROM emprestimo_itens;")
        total_catalogo_emp, total_disponivel_emp = cursor_rel.fetchone()
        total_catalogo_emp = int(total_catalogo_emp)
        total_disponivel_emp = int(total_disponivel_emp)
        total_emprestado_emp = total_catalogo_emp - total_disponivel_emp

        col_m1, col_m2 = st.columns(2)
        renderizar_kpi_duplo(col_m1, "Movimentações no Período", "Entradas", str(total_entradas_rel), "Saídas", str(total_saidas_rel))
        renderizar_kpi_duplo(col_m2, "Situação do Empréstimo", "Emprestado", str(total_emprestado_emp), "Disponível", str(total_disponivel_emp))

        st.markdown("<br><hr style='margin: 10px 0 20px 0; opacity: 0.15;'>", unsafe_allow_html=True)

        # ---------------------------------------------------------------
        # EXPORTAÇÃO EM EXCEL
        # ---------------------------------------------------------------
        st.markdown('<h3 style="font-size: 18px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center;"><span style="display: inline-block; width: 6px; height: 18px; background-color: #4CAF50; margin-right: 8px; border-radius: 2px;"></span>Exportar Relatório Geral</h3>', unsafe_allow_html=True)
        st.caption("Gera uma planilha Excel com abas separadas: Estoque, Movimentações, Solicitações e Empréstimos.")

        if st.button("Gerar Relatório em Excel", type="primary", icon=":material/table_view:"):
            with st.spinner("Gerando planilha..."):
                buffer_excel = io.BytesIO()
                with pd.ExcelWriter(buffer_excel, engine="openpyxl") as writer:
                    if not df_produtos.empty:
                        df_produtos.to_excel(writer, sheet_name="Estoque", index=False)
                    if not df_movimentacoes.empty:
                        df_movimentacoes.to_excel(writer, sheet_name="Movimentações", index=False)

                    df_export_sol = pd.read_sql_query("""
                        SELECT tipo AS "Tipo", item_nome AS "Item", quantidade AS "Quantidade",
                               solicitante_nome AS "Solicitante", solicitante_email AS "E-mail",
                               coordenacao AS "Coordenação", atividade_associada AS "Atividade",
                               to_char(data_solicitacao AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo', 'DD/MM/YYYY HH24:MI') AS "Data Solicitação",
                               status AS "Status",
                               COALESCE(aprovador, '-') AS "Decidido Por",
                               COALESCE(justificativa_rejeicao, '-') AS "Justificativa Reprovação"
                        FROM solicitacoes_almoxarifado ORDER BY id DESC;
                    """, conn)
                    if not df_export_sol.empty:
                        df_export_sol.to_excel(writer, sheet_name="Solicitações", index=False)

                    df_export_emp = pd.read_sql_query("""
                        SELECT item_nome AS "Item", quantidade AS "Quantidade", pessoa AS "Pessoa",
                               coordenacao AS "Coordenação", data_retirada AS "Data Retirada",
                               data_prevista AS "Previsão Devolução", data_devolucao AS "Devolução Real",
                               status AS "Status"
                        FROM emprestimo_registros ORDER BY id DESC;
                    """, conn)
                    if not df_export_emp.empty:
                        df_export_emp.to_excel(writer, sheet_name="Empréstimos", index=False)

                st.session_state["excel_relatorio_gerado"] = buffer_excel.getvalue()
                st.success("Planilha gerada com sucesso! Clique abaixo para baixar.")

        if st.session_state.get("excel_relatorio_gerado"):
            st.download_button(
                label="Baixar Relatorio_Almoxarifado.xlsx",
                data=st.session_state["excel_relatorio_gerado"],
                file_name=f"Relatorio_Almoxarifado_{date.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                icon=":material/download:"
            )
