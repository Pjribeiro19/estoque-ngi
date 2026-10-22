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
import html
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


# Tema claro fixo: a configuração nativa acompanha o CSS e as tabelas.
st.set_option("client.toolbarMode", "minimal")
components.html("""<script>
(function () {
  try {
    const p = window.parent;
    let changed = false;
    for (let i = p.localStorage.length - 1; i >= 0; i--) {
      const key = p.localStorage.key(i);
      if (key && key.startsWith('stActiveTheme')) {
        const value = p.localStorage.getItem(key) || '';
        if (/dark|system/i.test(value)) {
          p.localStorage.removeItem(key);
          changed = true;
        }
      }
    }
    if (changed && !p.sessionStorage.getItem('ngi_light_fixed_v1')) {
      p.sessionStorage.setItem('ngi_light_fixed_v1', '1');
      p.location.reload();
    }
  } catch (e) { /* A configuração nativa continua sendo aplicada. */ }
})();
</script>""", height=0, width=0)

# --- ESTILIZAÇÃO CSS COMPATÍVEL ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"], .stMarkdown, .stMarkdown p, .stMarkdown li,
    [data-testid="stWidgetLabel"] p, label, span, div, button,
    input, textarea, select, .stDataFrame, [data-testid="stMetricValue"] {
        font-family: 'Manrope', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif !important;
    }

    h1, h2, h3, h4, h5, h6 {
        font-family: 'Manrope', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif !important;
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
    
    button[kind="primary"],
    button[kind="primaryFormSubmit"],
    div.stButton > button:first-child[kind="primary"],
    div.stFormSubmitButton > button:first-child[kind="primary"],
    div.stFormSubmitButton > button:first-child[kind="primaryFormSubmit"],
    [data-testid="baseButton-primary"],
    [data-testid="stBaseButton-primary"],
    [data-testid="baseButton-primaryFormSubmit"],
    [data-testid="stBaseButton-primaryFormSubmit"],
    [data-testid="stFormSubmitButton"] button {
        background-color: #147746 !important;
        border-color: #147746 !important;
        color: white !important;
    }
    button[kind="primary"]:hover,
    button[kind="primaryFormSubmit"]:hover,
    div.stButton > button:first-child[kind="primary"]:hover,
    div.stFormSubmitButton > button:first-child[kind="primary"]:hover,
    div.stFormSubmitButton > button:first-child[kind="primaryFormSubmit"]:hover,
    [data-testid="baseButton-primary"]:hover,
    [data-testid="stBaseButton-primary"]:hover,
    [data-testid="baseButton-primaryFormSubmit"]:hover,
    [data-testid="stBaseButton-primaryFormSubmit"]:hover,
    [data-testid="stFormSubmitButton"] button:hover {
        background-color: #0d6036 !important;
        border-color: #0d6036 !important;
    }

    /* Botões "Adicionar" (carrinho, categorias) - verde suave */
    [class*="st-key-btn_add_"] button {
        background-color: rgba(20, 119, 70, 0.14) !important;
        border-color: rgba(20, 119, 70, 0.45) !important;
        color: #145d3b !important;
    }
    [class*="st-key-btn_add_"] button:hover {
        background-color: rgba(20, 119, 70, 0.24) !important;
        border-color: #147746 !important;
    }

    /* Botões "Remover" (itens do carrinho, categorias) - cinza neutro */
    [class*="st-key-btn_remove_"] button {
        background-color: #eeeeee !important;
        border-color: #d5d5d5 !important;
        color: #555555 !important;
    }
    [class*="st-key-btn_remove_"] button:hover {
        background-color: #e0e0e0 !important;
        border-color: #bbbbbb !important;
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
        padding: 24px 26px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }
    .painel-kpi-valor, .rel-kpi-valor {
        font-size: 36px !important;
        margin: 10px 0 0 0 !important;
    }
    .painel-kpi-label {
        font-size: 13px;
        letter-spacing: 0.4px;
    }
    @media (max-width: 640px) {
        .painel-kpi-card, .rel-kpi-card {
            padding: 14px !important;
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
SESSAO_DURACAO_MINUTOS = 30

# URL pública do sistema, usada para montar o link de redefinição de senha
# enviado por e-mail. Ajuste aqui caso o domínio mude no futuro.
URL_BASE_SISTEMA = "https://www.almoxarifadocarajas.com.br"
REDEFINICAO_SENHA_DURACAO_MINUTOS = 60

# =============================================================================
# SENHAS CRIPTOGRAFADAS (PBKDF2-SHA256, biblioteca padrão do Python)
# =============================================================================
# A senha nunca fica gravada como texto no banco: guardamos apenas o "hash"
# (uma impressão digital irreversível) no formato:
#   pbkdf2_sha256$iteracoes$sal$hash
# Senhas antigas (texto puro) são convertidas automaticamente na inicialização.
PREFIXO_HASH_SENHA = "pbkdf2_sha256$"
ITERACOES_HASH_SENHA = 260000


def gerar_hash_senha(senha):
    import hashlib, secrets
    sal = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(senha).encode("utf-8"), sal.encode("utf-8"), ITERACOES_HASH_SENHA)
    return f"{PREFIXO_HASH_SENHA}{ITERACOES_HASH_SENHA}${sal}${digest.hex()}"


def senha_esta_criptografada(valor):
    return str(valor or "").startswith(PREFIXO_HASH_SENHA)


def verificar_senha(senha_digitada, senha_banco):
    """Confere a senha digitada com o valor salvo no banco."""
    import hashlib, hmac
    if senha_banco is None:
        return False
    senha_banco = str(senha_banco)
    if not senha_esta_criptografada(senha_banco):
        # Compatibilidade: registro ainda em texto puro (antes da migração).
        return hmac.compare_digest(senha_banco, str(senha_digitada))
    try:
        _, iteracoes, sal, esperado = senha_banco.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", str(senha_digitada).encode("utf-8"), sal.encode("utf-8"), int(iteracoes))
        return hmac.compare_digest(digest.hex(), esperado)
    except Exception:
        return False


def converter_para_horario_br(dt_utc):
    """O banco de dados (Neon Postgres) e o servidor (Railway) guardam os
    horários em UTC. Esta função converte para o horário de Brasília
    (America/Sao_Paulo, UTC-3) antes de exibir na tela."""
    if dt_utc is None:
        return None
    return dt_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/Sao_Paulo"))


# =============================================================================
# APRESENTAÇÃO VISUAL — sem consultas ou alterações no banco de dados
# =============================================================================
CSS_VISUAL_NGI = """
<style>
/* Tema visual NGI Carajás. Aplicado somente após a autenticação. */
[data-testid="stAppViewContainer"], .stApp {
    --text-color: #182b28; --background-color: #f6f8f7;
    --secondary-background-color: #edf3ef; --primary-color: #147746;
    background: #f6f8f7; color: #182b28;
}
[data-testid="stHeader"] { background: #f6f8f7; }
/* Aproveita a largura disponível, sem grandes margens junto ao menu. */
[data-testid="stMainBlockContainer"],
[data-testid="stMain"] .block-container, .main .block-container {
    width: 100%; max-width: none; margin-left: 0; margin-right: 0;
    padding: 2.5rem 2rem 3rem; box-sizing: border-box;
}
[data-testid="stSidebar"] {
    --text-color: #e3eee8; --background-color: #092e24;
    --secondary-background-color: #164335;
    background: #092e24; border-right: 1px solid #164335;
}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] { background: #092e24; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding: 1.6rem 1rem; }
[data-testid="stSidebar"] hr { border-color: #305145; }
[data-testid="stSidebar"] button { color: #e3eee8; }
.ngi-brand { display:flex; gap:12px; align-items:center; margin:0 4px 25px; }
.ngi-brand-icon { width:42px; height:42px; display:grid; place-items:center;
    border-radius:12px; background:#164b35; color:#7acb88; font-size:26px; }
.ngi-brand-name { font-size:21px; font-weight:800; color:#fff !important; letter-spacing:-.5px; }
.ngi-brand-subtitle { font-size:11px; color:#adc7ba !important; margin-top:3px; }
.ngi-profile { display:flex; gap:10px; align-items:center; padding:0 6px 16px;
    margin:0 0 20px; border-bottom:1px solid #305145; }
.ngi-avatar { flex:0 0 36px; height:36px; display:grid; place-items:center; background:#187746;
    color:white !important; border-radius:50%; font-weight:700; font-size:13px; }
.ngi-profile-name { color:#eff6f2 !important; font-size:13px; font-weight:600; overflow-wrap:anywhere; }
.ngi-profile-role { color:#a9c2b5 !important; font-size:11px; margin-top:3px; }
.ngi-page-header { background:transparent !important; padding:0 0 24px !important;
    border-radius:0 !important; margin-bottom:8px !important; border-bottom:1px solid #e0e7e3; }
.stMarkdown .ngi-page-header h1 { color:#122820 !important; font-size:30px !important;
    font-weight:800 !important; letter-spacing:-1px; padding:0; margin:0; line-height:1.25; }
.stMarkdown .ngi-page-header p { color:#6a7b73 !important; margin:9px 0 0 !important;
    font-size:14px !important; opacity:1 !important; }
.ngi-breadcrumb { font-size:12px; color:#718379 !important; margin-bottom:20px; }
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] input, [data-testid="stDateInput"] input {
    color:#182b28 !important; background:#fff; }
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {
    border-color:#dce5df; border-radius:8px; background:#fff; color:#182b28;
}
[data-testid="stButton"] button, [data-testid="stFormSubmitButton"] button,
[data-testid="stDownloadButton"] button { border-radius:8px; font-weight:600; min-height:40px; }
[data-testid="stButton"] button[kind="primary"],
[data-testid="stFormSubmitButton"] button,
[data-testid="baseButton-primary"], [data-testid="stBaseButton-primary"] {
    background:#147746 !important; border-color:#147746 !important; color:white !important;
}
[data-testid="stButton"] button[kind="primary"] p,
[data-testid="stFormSubmitButton"] button p { color:white !important; }
[data-testid="stButton"] button[kind="primary"]:hover,
[data-testid="stFormSubmitButton"] button:hover { background:#0d6036 !important; border-color:#0d6036 !important; }
[data-testid="stForm"], [data-testid="stVerticalBlockBorderWrapper"] > div {
    border-color:#e1e8e3; border-radius:12px;
}
[data-testid="stForm"] { background:#fff; padding:22px; }
[data-testid="stDataFrame"] { border:1px solid #e1e8e3; border-radius:10px; overflow:hidden; }
.painel-kpi-card, .rel-kpi-card { border-radius:12px !important; box-shadow:0 2px 8px #14382406; }
.livros-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:20px; margin:18px 0 26px; }
.livro-card { box-sizing:border-box; display:flex; flex-direction:column; min-width:0;
    height:340px; border:1px solid #e0e7e3; border-radius:12px; padding:14px;
    background:#fff; overflow:hidden; box-shadow:0 2px 6px #15372604; }
.livro-img-wrap { position:relative; flex:0 0 178px; height:178px; width:100%;
    border-radius:8px; overflow:hidden; display:flex; align-items:center; justify-content:center;
    background:linear-gradient(120deg,#f0f3ef,#f7f8f5); }
.livro-img-wrap img { display:block; max-width:calc(100% - 38px); max-height:154px;
    width:auto; height:auto; object-fit:contain; margin:auto; filter:drop-shadow(0 3px 5px #142d2020); }
.livro-img-placeholder { font-size:13px; color:#829187; }
.livro-info { padding:13px 2px 0; min-height:0; flex:1; }
.livro-titulo { font-size:14px; font-weight:700; color:#1c3027;
    line-height:1.45; height:41px; display:-webkit-box; -webkit-line-clamp:2;
    -webkit-box-orient:vertical; overflow:hidden; margin-bottom:7px; }
.livro-meta { font-size:12px; color:#839187; }
.livro-footer { flex:0 0 auto; font-size:13px; padding:12px 2px 0;
    border-top:1px solid #eef2ef; color:#54665b; display:flex; align-items:center; justify-content:space-between; gap:8px; }
.livro-footer strong { font-size:15px; }
.livro-status { position:absolute; top:9px; right:9px; padding:5px 8px;
    border-radius:7px; background:#e5f3ea; color:#17693f !important; font-size:10px; font-weight:700; }
.livro-status.is-empty { background:#fcebed; color:#b73042 !important; }
@media (min-width: 1000px) {
    [data-testid="stSidebar"] { min-width:270px; max-width:290px; }
}
@media (max-width: 1100px) { .livros-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width: 640px) {
    .livros-grid { grid-template-columns:minmax(0,1fr); gap:14px; }
    .livro-card { height:340px; }
    [data-testid="stMainBlockContainer"], .main .block-container { padding:2rem 1rem; }
    .stMarkdown .ngi-page-header h1 { font-size:25px !important; }
}

/* Indicadores do acervo: apresentação dos dados já carregados. */
.ngi-acervo-kpis { display:grid; grid-template-columns:repeat(3,minmax(0,1fr));
    gap:16px; margin:8px 0 18px; }
.ngi-acervo-kpi { display:flex; align-items:center; gap:16px; min-width:0;
    padding:18px 20px; background:#fff; border:1px solid #e0e7e3; border-radius:10px; }
.ngi-acervo-kpi-icon { display:grid; place-items:center; flex:0 0 48px; height:48px;
    background:#e8f4ed; color:#17693f; border-radius:10px; }
.ngi-acervo-kpi-icon svg { width:25px; height:25px; }
.ngi-acervo-kpi-value { color:#153d2c; font-size:24px; line-height:1.2; font-weight:800; }
.ngi-acervo-kpi-label { color:#718077; font-size:13px; margin-top:4px; }
.ngi-acervo-kpi-empty .ngi-acervo-kpi-icon { background:#fff0f1; color:#d6424e; }
.ngi-acervo-kpi-empty .ngi-acervo-kpi-value { color:#b73042; }
@media (max-width:900px) {
    .ngi-acervo-kpi { padding:14px 12px; gap:10px; }
    .ngi-acervo-kpi-value { font-size:22px; }
}
@media (max-width:640px) {
    .ngi-acervo-kpis { grid-template-columns:minmax(0,1fr); gap:10px; }
}

/* Painel geral: indicadores claros e consulta integrada. */
.ngi-painel-kpis { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:18px; margin:8px 0 22px; }
.ngi-painel-kpi { display:flex; align-items:center; gap:20px; padding:24px;
    min-height:132px; box-sizing:border-box; background:#fff; border:1px solid #e5ece7;
    border-radius:12px; box-shadow:0 3px 12px #15372605; }
.ngi-painel-icon { flex:0 0 64px; height:64px; display:grid; place-items:center;
    border-radius:13px; background:#eaf5e7; color:#17803f; }
.ngi-painel-icon svg { width:34px; height:34px; }
.ngi-painel-icon.alerta { background:#ffedef; color:#bd2535; }
.ngi-painel-icon.mov { background:#e6f7ed; color:#11794a; }
.ngi-painel-label { font-size:15px; color:#53675c; line-height:1.4; }
.ngi-painel-value { font-size:36px; font-weight:800; color:#147348; line-height:1.2; margin-top:8px; }
.ngi-painel-value.alerta { color:#bd2535; }
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .ngi-stock-heading) {
    background:#fff; border-radius:12px; padding:22px;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.ngi-stock-heading) > div {
    background:#fff; border-color:#e1e8e3; border-radius:12px;
}
.ngi-stock-heading { margin-bottom:6px; }
.stMarkdown .ngi-stock-heading h3 { padding:0; margin:0; font-size:23px; color:#172b22 !important; font-weight:800 !important; }
.stMarkdown .ngi-stock-heading p { margin:5px 0 12px; font-size:14px; color:#74867a !important; }
/* Carrinho de solicitação em 3 passos */
.ngi-passo { display:flex; align-items:center; gap:10px; font-size:15px; font-weight:700; color:#172b22; margin:10px 0 2px; }
.ngi-passo b { flex:0 0 26px; height:26px; border-radius:50%; background:#147746; color:#fff !important;
    display:grid; place-items:center; font-size:13px; }
.ngi-passo.off b { background:#dfe7e2; color:#5d7066 !important; }
.ngi-passo small { font-weight:500; color:#6a7b73 !important; font-size:13px; }
.ngi-carr-head, .ngi-carr-linha { display:grid; grid-template-columns:90px 1fr 70px; gap:8px; padding:8px 12px; }
.ngi-carr-head { font-size:12px; font-weight:700; color:#6a7b73 !important; border-bottom:1px solid #e1e8e3;
    text-transform:uppercase; letter-spacing:.3px; }
.ngi-carr-linha { margin-top:-16px; align-items:center; font-size:14px; min-height:40px; }
.ngi-carr-linha span:first-child { color:#147746 !important; font-weight:700; font-size:13px; }
.ngi-carr-linha span:last-child { font-weight:700; text-align:center; }
[class*="st-key-ngi_carrinho_box"] { background:#f8fbf9; border:1px solid #e1e8e3; border-radius:10px; padding:4px 6px; }
[class*="st-key-ngi_carrinho_box"] [data-testid="stHorizontalBlock"] { border-bottom:1px solid #edf1ee; }
[class*="st-key-ngi_carrinho_box"] [data-testid="stMarkdownContainer"] p { margin-bottom:0 !important; }
[class*="st-key-ngi_carrinho_box"] [class*="st-key-btn_remove_"] button { min-height:32px !important; padding:2px 10px !important; }
[data-testid="stBaseButton-primary"]:disabled { opacity:.45 !important; }
@media(max-width:640px) {
    .ngi-carr-head, .ngi-carr-linha { grid-template-columns:56px 1fr 40px; padding:6px 4px; }
}
@media(max-width:1100px) {
    .ngi-painel-kpi { gap:12px; padding:18px; }
    .ngi-painel-icon { flex-basis:48px; height:48px; }
    .ngi-painel-label { font-size:13px; }
}
@media(max-width:640px) {
    .ngi-painel-kpis { grid-template-columns:1fr; gap:10px; }
    .ngi-painel-kpi { min-height:96px; }
    .ngi-painel-value { font-size:28px; margin-top:4px; }
    [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .ngi-stock-heading) { padding:12px; }
}
</style>
"""

ESTILO_MENU_LATERAL_NGI = {
    "container": {"padding": "0!important", "background-color": "#092e24", "border-radius": "0"},
    "icon": {"color": "#afcdbd", "font-size": "17px"},
    "nav-link": {"font-family": "'Manrope', 'Segoe UI', sans-serif", "font-size": "13px",
                 "text-align": "left", "margin": "3px 0", "padding": "10px 12px",
                 "color": "#e3eee8", "border-radius": "7px", "--hover-color": "#164335"},
    "nav-link-selected": {"background-color": "#194b38", "color": "#ffffff",
                          "font-weight": "600", "border-left": "3px solid #55bd75"},
}

def renderizar_indicadores_painel_ngi(total_itens, produtos_esgotados, total_movimentacoes):
    """Apresentação dos três indicadores existentes, sem mudar seus cálculos."""
    itens = (
        ('Itens cadastrados', total_itens, '', '<path d="m12 3 9 5v9l-9 5-9-5V8l9-5Z"/><path d="m3 8 9 5 9-5M12 13v9M7.5 5.5l9 5"/>'),
        ('Produtos esgotados', produtos_esgotados, 'alerta' if produtos_esgotados > 0 else '', '<path d="m10.3 4-8 14a2 2 0 0 0 1.7 3h16a2 2 0 0 0 1.7-3l-8-14a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4m0 4h.01"/>'),
        ('Movimentações realizadas', total_movimentacoes, 'mov', '<path d="M7 20V4m-5 5 5-5 5 5M17 4v16m-5-5 5 5 5-5"/>'),
    )
    partes = ['<div class="ngi-painel-kpis">']
    for rotulo, valor, classe, desenho in itens:
        numero = format(int(valor), ',').replace(',', '.')
        partes.append(
            f'<div class="ngi-painel-kpi"><div class="ngi-painel-icon {classe}" aria-hidden="true">'
            f'<svg width="34" height="34" style="width:34px;height:34px;flex-shrink:0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round">{desenho}</svg></div>'
            f'<div><div class="ngi-painel-label">{rotulo}</div>'
            f'<div class="ngi-painel-value {classe}">{numero}</div></div></div>'
        )
    partes.append('</div>')
    st.markdown(''.join(partes), unsafe_allow_html=True)

def renderizar_indicadores_acervo_ngi(dados):
    """Resumo de leitura: usa somente o catálogo já consultado pela página."""
    quantidades = pd.to_numeric(dados['quantidade'], errors='coerce').fillna(0)
    totais = (len(dados), int(quantidades.clip(lower=0).sum()), int((quantidades <= 0).sum()))
    rotulos = ('títulos cadastrados', 'exemplares disponíveis', 'títulos sem estoque')
    desenhos = (
        '<path d="M12 5C9 3 5 3 3 4v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-2-1-6-1-9 1Z"/><path d="M12 5v15"/>',
        '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/>',
        '<path d="m10.3 4-8 14a2 2 0 0 0 1.7 3h16a2 2 0 0 0 1.7-3l-8-14a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4m0 4h.01"/>'
    )
    partes = ['<div class="ngi-acervo-kpis">']
    for indice, (total, rotulo, desenho) in enumerate(zip(totais, rotulos, desenhos)):
        classe = ' ngi-acervo-kpi-empty' if indice == 2 else ''
        valor = format(total, ',').replace(',', '.')
        partes.append(
            f'<div class="ngi-acervo-kpi{classe}"><div class="ngi-acervo-kpi-icon" aria-hidden="true">'
            f'<svg width="25" height="25" style="width:25px;height:25px;flex-shrink:0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round">{desenho}</svg></div>'
            f'<div><div class="ngi-acervo-kpi-value">{valor}</div>'
            f'<div class="ngi-acervo-kpi-label">{rotulo}</div></div></div>'
        )
    partes.append('</div>')
    st.markdown(''.join(partes), unsafe_allow_html=True)

def renderizar_catalogo_visual_ngi(dados):
    """Exibe os mesmos registros recebidos; não filtra nem modifica saldos."""
    # Paginação visual: a lista integral continua disponível para as solicitações.
    if dados.empty:
        return
    col_limite, col_pagina = st.columns([1, 1])
    limite = col_limite.selectbox("Itens por página", [12, 24, 48], key="ngi_livros_limite")
    paginas = max(1, (len(dados) + limite - 1) // limite)
    contexto = (limite, tuple(dados["codigo"].tolist()))
    if st.session_state.get("ngi_livros_contexto") != contexto:
        st.session_state.ngi_livros_pagina = 1
        st.session_state.ngi_livros_contexto = contexto
    st.session_state.ngi_livros_pagina = min(max(1, st.session_state.get("ngi_livros_pagina", 1)), paginas)
    pagina = col_pagina.selectbox("Página", range(1, paginas + 1), key="ngi_livros_pagina")
    dados = dados.iloc[(pagina - 1) * limite:pagina * limite].copy()
    fotos = fotos_catalogo_ngi("produtos_livros", dados["codigo"].tolist())
    dados["foto"] = [fotos.get(str(i)) for i in dados["codigo"]]
    st.caption(f"Página {pagina} de {paginas}")
    cards = ['<div class="livros-grid">']
    for _, item in dados.iterrows():
        titulo = html.escape(str(item['titulo']), quote=True)
        codigo = html.escape(str(item['codigo']), quote=True)
        tipo = html.escape(str(item['tipo']), quote=True) if pd.notna(item['tipo']) and str(item['tipo']).strip() else '-'
        if item['foto'] is not None:
            foto = bytes(item['foto'])
            mime = 'image/png' if foto[:8] == b'\x89PNG\r\n\x1a\n' else 'image/jpeg'
            imagem = f'<img src="data:{mime};base64,{base64.b64encode(foto).decode()}" alt="Capa: {titulo}" loading="lazy">'
        else:
            imagem = '<div class="livro-img-placeholder">Sem foto</div>'
        disponivel = item['quantidade'] > 0
        status = 'Disponível' if disponivel else 'Sem estoque'
        classe = '' if disponivel else ' is-empty'
        cor = '#167543' if disponivel else '#ba3445'
        quantidade = html.escape(str(item['quantidade']))
        cards.append(
            f'<article class="livro-card">'
            f'<div class="livro-img-wrap">{imagem}<div class="livro-status{classe}">{status}</div></div>'
            f'<div class="livro-info"><div class="livro-titulo" title="{titulo}">{titulo}</div>'
            f'<div class="livro-meta">Código: {codigo} · {tipo}</div></div>'
            f'<div class="livro-footer">Disponível: <strong style="color:{cor}">{quantidade}</strong></div>'
            '</article>'
        )
    cards.append('</div>')
    st.markdown(''.join(cards), unsafe_allow_html=True)


def foto_emprestimo_upload(arquivo):
    """Valida a imagem antes de armazená-la no catálogo."""
    if arquivo is None:
        return None
    dados = arquivo.getvalue()
    if len(dados) > 5 * 1024 * 1024:
        raise ValueError("A foto deve ter até 5 MB.")
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(dados)) as original:
        imagem = ImageOps.exif_transpose(original).convert("RGB")
        imagem.thumbnail((1000, 1000))
        destino = io.BytesIO()
        imagem.save(destino, format="JPEG", quality=85)
        return destino.getvalue()


def navegar_emprestimo(destino, item_id):
    st.session_state.ngi_emp_nav = destino
    st.session_state.ngi_emp_item_alvo = int(item_id)


def mudar_pagina_emprestimos(pagina):
    st.session_state.ngi_emp_pagina = pagina


def renderizar_catalogo_emprestimos(dados, solicitante=False):
    st.markdown("""<style>
    .ngi-emp-stats {display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:12px 0 22px}
    .ngi-emp-stat {background:white;border:1px solid #dce5df;border-radius:10px;padding:16px 20px}
    .ngi-emp-stat span {color:#63756b;font-size:13px}.ngi-emp-stat strong {display:block;color:#153d2a;font-size:27px}
    .ngi-emp-photo {height:145px;display:flex;align-items:center;justify-content:center;background:#f3f5f3;border-radius:8px;color:#7b8d82;overflow:hidden}
    .ngi-emp-photo img {width:100%;height:100%;object-fit:contain}
    .ngi-emp-name {font-size:14px;font-weight:700;color:#182e22;height:40px;line-height:20px;overflow:hidden;margin:5px 0}
    .ngi-emp-code {font-size:12px;color:#718077;margin-top:10px}
    .ngi-emp-counts {display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid #e5ebe7;padding:8px 0;gap:6px}
    .ngi-emp-counts span {font-size:11px;color:#617269}.ngi-emp-counts b {display:block;font-size:17px;color:#233e2d}
    .ngi-emp-details {height:96px;overflow:hidden;}
    .ngi-emp-return {height:36px;font-size:12px;line-height:18px;color:#6a7b73;}
    .ngi-emp-note {height:52px;overflow:auto;font-size:12px;line-height:17px;color:#6a7b73;overflow-wrap:anywhere;}
    .ngi-emp-status {font-size:12px;color:#276644;background:#e9f4e9;padding:3px 9px;border-radius:15px;display:inline-block;margin-bottom:5px}
    [class*="st-key-ngi_emp_card_"] {background:#fff;border-radius:10px;}
    [class*="st-key-ngi_emp_card_"] [data-testid="stVerticalBlock"] {gap:8px;}
    [class*="st-key-ngi_emp_card_"] button {min-height:32px !important;padding:4px 8px !important;}
    [class*="st-key-ngi_emp_card_"] button p {font-size:12px !important;}
    [class*="st-key-ngi_emp_card_"] svg {width:16px !important;height:16px !important;}
    @media(max-width:700px){.ngi-emp-stats{grid-template-columns:repeat(2,1fr)}}
    </style>""", unsafe_allow_html=True)
    total = int(dados['Qtd Total'].sum())
    disponivel = int(dados['Qtd Disponível'].sum())
    indicadores = [('Tipos de materiais', len(dados)), ('Total no acervo', total), ('Disponíveis', disponivel), ('Emprestados', total-disponivel)]
    st.markdown('<div class="ngi-emp-stats">'+''.join(f'<div class="ngi-emp-stat"><span>{nome}</span><strong>{valor}</strong></div>' for nome,valor in indicadores)+'</div>', unsafe_allow_html=True)
    st.subheader("Materiais para empréstimo")
    busca_col, modo_col = st.columns([3, 1])
    busca = busca_col.text_input("Buscar por nome ou código", key="ngi_emp_busca", placeholder="Digite o material ou o código...")
    modo = modo_col.radio("Visualização", ["Cartões", "Tabela"], horizontal=True, key="ngi_emp_modo")
    filtrados = dados
    if busca.strip():
        filtrados = dados[dados['Item / Equipamento'].fillna('').str.contains(busca.strip(), case=False, regex=False) | dados['Código'].fillna('').str.contains(busca.strip(), case=False, regex=False)]
    if filtrados.empty:
        st.info("Nenhum material encontrado.")
        return
    limite_col, pagina_col, anterior_col, proxima_col = st.columns([2, 2, 1, 1])
    limite = limite_col.selectbox("Itens por página", [8, 16, 24], key="ngi_emp_limite")
    paginas = max(1, (len(filtrados)+limite-1)//limite)
    contexto = (busca.strip(), limite)
    if st.session_state.get("ngi_emp_contexto") != contexto:
        st.session_state.ngi_emp_pagina = 1
        st.session_state.ngi_emp_contexto = contexto
    st.session_state.ngi_emp_pagina = min(max(1, st.session_state.get("ngi_emp_pagina", 1)), paginas)
    pagina = pagina_col.selectbox("Página", range(1, paginas+1), key="ngi_emp_pagina")
    anterior_col.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    proxima_col.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    anterior_col.button("Anterior", key="ngi_emp_anterior", use_container_width=True, disabled=pagina<=1, on_click=mudar_pagina_emprestimos, args=(pagina-1,))
    proxima_col.button("Próxima", key="ngi_emp_proxima", use_container_width=True, disabled=pagina>=paginas, on_click=mudar_pagina_emprestimos, args=(pagina+1,))
    visiveis = filtrados.iloc[(pagina-1)*limite:pagina*limite]
    st.caption(f"Exibindo {(pagina-1)*limite+1}–{min(pagina*limite,len(filtrados))} de {len(filtrados)} materiais · Página {pagina} de {paginas}")
    if modo == "Tabela":
        st.dataframe(visiveis.drop(columns=['ID','foto']), use_container_width=True, hide_index=True)
        return
    visiveis = visiveis.copy()
    fotos = fotos_catalogo_ngi("emprestimo_itens", visiveis["ID"].tolist())
    visiveis["foto"] = [fotos.get(int(i)) for i in visiveis["ID"]]
    for inicio in range(0, len(visiveis), 4):
        colunas = st.columns(4)
        for coluna, (_, item) in zip(colunas, visiveis.iloc[inicio:inicio+4].iterrows()):
            with coluna:
                with st.container(border=True, key=f"ngi_emp_card_{item['ID']}"):
                    nome = html.escape(str(item['Item / Equipamento']))
                    codigo = html.escape(str(item['Código'] or 'Sem código'))
                    foto = item['foto']
                    visual = 'Sem foto'
                    if foto is not None:
                        visual = '<img alt="'+nome+'" src="data:image/jpeg;base64,'+base64.b64encode(bytes(foto)).decode()+'">'
                    disponiveis = int(item['Qtd Disponível'])
                    status = 'Disponível' if disponiveis > 0 else 'Indisponível'
                    metricas = [('Total',int(item['Qtd Total'])),('Disponíveis',disponiveis),('Emprestados',int(item['Emprestados']))]
                    st.markdown(f'<div class="ngi-emp-photo">{visual}</div><div class="ngi-emp-code">{codigo}</div><div class="ngi-emp-name" title="{nome}">{nome}</div><div class="ngi-emp-status">{status}</div><div class="ngi-emp-counts">'+''.join(f'<div><span>{n}</span><b>{v}</b></div>' for n,v in metricas)+'</div>',unsafe_allow_html=True)
                    if solicitante:
                        previsao = item.get('Previsão de devolução')
                        texto_previsao = f"Devolução prevista: {previsao.strftime('%d/%m/%Y')}" if disponiveis <= 0 and pd.notna(previsao) else ""
                        observacao = item.get('Observações')
                        texto_obs = str(observacao).strip() if pd.notna(observacao) else ""
                        st.markdown('<div class="ngi-emp-details"><div class="ngi-emp-return">'+html.escape(texto_previsao)+'</div><div class="ngi-emp-note">'+html.escape(texto_obs if texto_obs else 'Sem observações')+'</div></div>', unsafe_allow_html=True)
                    else:
                        sair, editar = st.columns([3,1])
                        sair.button("Registrar saída", key=f"ngi_emp_saida_{item['ID']}", use_container_width=True, disabled=disponiveis<=0, on_click=navegar_emprestimo, args=("Registrar Saída (Empréstimo)",int(item['ID'])))
                        editar.button("Editar", key=f"ngi_emp_editar_{item['ID']}", use_container_width=True, on_click=navegar_emprestimo, args=("Itens Disponíveis",int(item['ID'])))
    st.caption(f"{len(filtrados)} materiais encontrados · página {pagina} de {paginas}")


def tipo_solicitacao_visual(sol):
    if sol.get("tipo") == "EMPRESTIMO":
        return "Empréstimo"
    return "Livro" if sol.get("origem_estoque") == "LIVROS" else "Material"


def selecionar_solicitacao_ngi(identificador=None):
    st.session_state.ngi_sol_aberta = identificador
    st.session_state.ngi_sol_fechada = identificador is None


def pagina_solicitacoes_ngi(pagina):
    st.session_state.ngi_sol_pagina = pagina
    st.session_state.ngi_sol_aberta = None
    st.session_state.ngi_sol_fechada = False


def indicadores_solicitacoes_ngi(dados):
    st.markdown('''<style>
    .ngi-sol-kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:0 0 12px}
    .ngi-sol-kpi{display:flex;align-items:center;gap:18px;padding:18px 20px;border:1px solid #dce9e1;border-radius:10px;background:#f0f7f3;min-height:96px;box-sizing:border-box}
    .ngi-sol-kpi:first-child{background:#fffbf1;border-color:#f1e6c7}.ngi-sol-kpi:last-child{background:#f2f6fc;border-color:#dde6f3}
    .ngi-sol-kpi-icon{width:46px;height:46px;flex:0 0 46px;display:grid;place-items:center;background:#e3f0e8;border-radius:9px}
    .ngi-sol-kpi:first-child .ngi-sol-kpi-icon{background:#fff3d7}.ngi-sol-kpi:last-child .ngi-sol-kpi-icon{background:#e6eefb}
    .ngi-sol-kpi svg{width:25px;height:25px;stroke:#185b3e;fill:none;stroke-width:1.7}
    .ngi-sol-kpi strong{display:block;font-size:28px;line-height:1.2;color:#172d24}.ngi-sol-kpi small{display:block;font-size:13px;color:#53645b;margin-top:5px}
    .st-key-ngi_sol_aba [role="radiogroup"]{gap:0;border-bottom:1px solid #dce6df;margin-bottom:6px}
    .st-key-ngi_sol_aba [role="radiogroup"] label{padding:9px 20px;margin:0;border-bottom:3px solid transparent;cursor:pointer}
    .st-key-ngi_sol_aba [role="radiogroup"] label:has(input:checked){border-color:#147746;background:white}
    .st-key-ngi_sol_aba [role="radiogroup"] label:has(input:checked) p{color:#145d3b !important;font-weight:700}
    .st-key-ngi_sol_aba [role="radiogroup"] label>div:first-child{display:none}
    .st-key-ngi_req_workspace{gap:14px}
    .st-key-ngi_req_table{background:#fff;border:1px solid #dfe7e2;border-radius:11px;overflow:hidden;gap:0!important}
    .st-key-ngi_req_table [data-testid="stVerticalBlock"]{gap:0}
    .st-key-ngi_req_header{background:#f8faf9;border-bottom:1px solid #e4ebe6;padding:12px 14px}
    .ngi-req-th{font-size:12px;font-weight:700;color:#55675d}
    [class*="st-key-ngi_req_row_"]{padding:5px 12px;border-bottom:1px solid #edf1ee;border-left:3px solid transparent}
    [class*="st-key-ngi_req_row_active_"]{background:#edf6f0;border-left-color:#147746}
    [class*="st-key-ngi_req_row_"] [data-testid="stHorizontalBlock"]{align-items:center;gap:9px!important}
    [class*="st-key-ngi_req_row_"] [data-testid="stButton"] button{border:none!important;background:transparent!important;box-shadow:none!important;min-height:42px!important;padding:4px 0!important;justify-content:flex-start;color:#244335!important;width:100%}
    [class*="st-key-ngi_req_row_"] [data-testid="stButton"] button p{font-size:12px!important;line-height:1.4;text-align:left}
    [class*="st-key-ngi_req_row_"] [data-testid="stButton"] button:hover{color:#147746!important;text-decoration:underline}
    .ngi-req-cell{font-size:12px;line-height:18px;color:#354d41;overflow-wrap:anywhere;padding:5px 0}
    .ngi-req-date{font-size:11px;color:#63766a;white-space:nowrap}
    .ngi-sol-tag{display:inline-block;padding:3px 7px;border-radius:5px;font-size:10px;line-height:17px;background:#e3f2e9;color:#155737!important;white-space:nowrap}
    .ngi-sol-tag.livro{background:#eaf1ff;color:#285293!important}.ngi-sol-tag.emprestimo{background:#efeafb;color:#66439a!important}
    .st-key-ngi_req_footer{padding:12px 14px;gap:8px!important}
    .st-key-ngi_req_footer [data-testid="stHorizontalBlock"]{align-items:center;gap:5px!important}
    .st-key-ngi_req_footer button{min-height:32px!important;padding:3px 7px!important}
    .st-key-ngi_req_footer button p{font-size:12px!important}
    .ngi-req-page-info{font-size:12px;color:#728178;white-space:nowrap}
    .st-key-ngi_req_detail{background:#fff;border:1px solid #dfe7e2;border-radius:11px;padding:18px;gap:12px!important}
    .st-key-ngi_req_detail [data-testid="stVerticalBlock"]{gap:12px}
    .ngi-req-detail-title{font-weight:700;color:#253b30;font-size:15px;padding-top:6px}
    .st-key-ngi_req_close button{border:0!important;background:transparent!important;min-height:28px!important;padding:0!important;color:#66796b!important}
    .ngi-req-id{display:flex;align-items:center;gap:14px;margin:0 0 15px}.ngi-req-id strong{font-size:28px;color:#182e23}.ngi-req-pending{background:#fff0d7;color:#8e560c!important;border-radius:16px;padding:4px 10px;font-size:11px}
    .ngi-req-person{font-weight:700;font-size:14px;color:#213d2c;margin-bottom:8px}
    .ngi-req-meta{font-size:12px;line-height:1.8;color:#65776b;overflow-wrap:anywhere}
    .ngi-req-divider{height:1px;background:#e7ece9;margin:16px 0}
    .ngi-req-item-label{font-size:12px;color:#6a7b71;margin-bottom:5px}.ngi-req-item{font-size:17px;font-weight:700;line-height:1.4;color:#1b3627;overflow-wrap:anywhere}
    .ngi-req-amounts{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:18px}.ngi-req-amount{border:1px solid #e1e8e3;border-radius:8px;padding:12px 10px;min-width:0}.ngi-req-amount small{font-size:11px;color:#687b6e;display:block}.ngi-req-amount strong{display:block;font-size:15px;margin-top:5px;color:#1c3828}
    .ngi-req-note{font-size:12px;line-height:1.6;color:#5f7365;margin-top:12px;overflow-wrap:anywhere}
    .ngi-req-note b{color:#294535}.ngi-req-hint{font-size:11px;color:#748277;margin:14px 0 0}
    .st-key-ngi_req_detail textarea{min-height:80px!important}
    .st-key-ngi_req_detail [data-testid="stWidgetLabel"] p{font-size:12px!important}
    .st-key-ngi_req_detail [data-testid="stButton"] button p{font-size:12px!important}
    @media(max-width:1100px){.ngi-sol-kpi{padding:14px;gap:10px}.ngi-sol-kpi strong{font-size:25px}.ngi-sol-kpi small{font-size:12px}.st-key-ngi_req_detail{padding:14px}}
    @media(max-width:760px){.ngi-sol-kpis{gap:7px}.ngi-sol-kpi{padding:12px 9px;gap:0;min-height:80px}.ngi-sol-kpi-icon{display:none}.ngi-sol-kpi small{font-size:10px}.ngi-sol-kpi strong{font-size:23px}
    .st-key-ngi_req_workspace>[data-testid="stHorizontalBlock"]{flex-wrap:wrap}.st-key-ngi_req_workspace>[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{width:100%!important;flex:1 1 100%!important;min-width:0!important}
    .st-key-ngi_req_table [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important}.st-key-ngi_req_table [data-testid="stColumn"]{min-width:0!important;width:auto!important}
    .ngi-req-cell{font-size:11px}.ngi-req-date{white-space:normal;font-size:10px}.ngi-sol-tag{font-size:9px;padding:2px 4px}.ngi-req-th{font-size:10px}
    [class*="st-key-ngi_req_row_"]{padding:4px 6px}[class*="st-key-ngi_req_row_"] [data-testid="stButton"] button p{font-size:10px!important}}
    @media(max-width:760px){
    .st-key-ngi_req_header [data-testid="stColumn"]:nth-child(4),
    [class*="st-key-ngi_req_row_"] [data-testid="stColumn"]:nth-child(4){display:none!important}
    .st-key-ngi_req_header [data-testid="stColumn"]:nth-child(3),
    [class*="st-key-ngi_req_row_"] [data-testid="stColumn"]:nth-child(3){flex:1.45 1 0!important}
    [class*="st-key-ngi_req_row_"] [data-testid="stButton"] button p{white-space:normal!important;overflow-wrap:anywhere!important}
    }
    </style>''', unsafe_allow_html=True)
    tipos = dados.apply(tipo_solicitacao_visual, axis=1) if not dados.empty else pd.Series(dtype=str)
    valores = [len(dados), int((tipos == 'Material').sum()), int(tipos.isin(['Livro', 'Empréstimo']).sum())]
    icones = ['<path d="M6 17h12l-2-3V9a4 4 0 0 0-8 0v5l-2 3ZM10 20h4"/>', '<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 5v9l9 5 9-5V8M12 13v9"/>', '<path d="M12 5C8 3 5 3 3 4v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1Zm0 0v15"/>']
    st.markdown('<div class="ngi-sol-kpis">' + ''.join(f'<div class="ngi-sol-kpi"><div class="ngi-sol-kpi-icon"><svg width="25" height="25" style="width:25px;height:25px;flex-shrink:0" viewBox="0 0 24 24">{icone}</svg></div><div><strong>{valor}</strong><small>{nome}</small></div></div>' for nome, valor, icone in zip(['Pendentes','Materiais','Livros e empréstimos'], valores, icones)) + '</div>', unsafe_allow_html=True)


def tabela_solicitacoes_ngi(dados):
    """Lista e painel lado a lado; devolve somente o pedido selecionado."""
    with st.container(key='ngi_req_workspace'):
        lista, detalhe = st.columns([1.9, 1], gap='medium')
    with lista:
        busca_col, tipo_col, coord_col = st.columns([2.3, 1.1, 1.2], gap='small')
        busca = busca_col.text_input('Buscar por número, item ou solicitante', key='ngi_sol_busca', placeholder='Buscar por nº, item ou solicitante...', label_visibility='collapsed')
        tipo = tipo_col.selectbox('Tipo', ['Todos os tipos','Material','Livro','Empréstimo'], key='ngi_sol_tipo', label_visibility='collapsed')
        coords = sorted({str(v) for v in dados['coordenacao'].dropna() if str(v).strip()})
        opcoes_coord = ['Todas as coordenações'] + coords
        if st.session_state.get('ngi_sol_coord') not in opcoes_coord:
            st.session_state.ngi_sol_coord = opcoes_coord[0]
        coord = coord_col.selectbox('Coordenação', opcoes_coord, key='ngi_sol_coord', label_visibility='collapsed')
        filtrados = dados.copy()
        filtrados['_tipo_visual'] = filtrados.apply(tipo_solicitacao_visual, axis=1) if not filtrados.empty else pd.Series(dtype=str)
        if busca.strip():
            textos = filtrados[['id','item_nome','solicitante_nome']].fillna('').astype(str).agg(' '.join, axis=1)
            filtrados = filtrados[textos.str.contains(busca.strip(), case=False, regex=False)]
        if tipo != 'Todos os tipos':
            filtrados = filtrados[filtrados['_tipo_visual'] == tipo]
        if coord != 'Todas as coordenações':
            filtrados = filtrados[filtrados['coordenacao'] == coord]
        filtrados = filtrados.sort_values(['data_solicitacao','id'], ascending=False, na_position='last')
        contexto = (busca, tipo, coord)
        if st.session_state.get('ngi_sol_filtro') != contexto:
            pagina_solicitacoes_ngi(1)
            st.session_state.ngi_sol_filtro = contexto
        if st.session_state.get('ngi_sol_limite') not in [8,16,32]:
            st.session_state.ngi_sol_limite = 8
        limite = st.session_state.ngi_sol_limite
        paginas = max(1, (len(filtrados) + limite - 1) // limite)
        pagina = min(max(1, st.session_state.get('ngi_sol_pagina',1)), paginas)
        st.session_state.ngi_sol_pagina = pagina
        inicio = (pagina - 1) * limite
        visiveis = filtrados.iloc[inicio:inicio + limite]
        aberta = st.session_state.get('ngi_sol_aberta')
        if aberta not in visiveis['id'].tolist():
            aberta = None
            if not visiveis.empty and not st.session_state.get('ngi_sol_fechada',False):
                aberta = int(visiveis.iloc[0]['id'])
            st.session_state.ngi_sol_aberta = aberta
        larguras = [2.0, 1.8, 1.0, 1.1, .24]
        with st.container(key='ngi_req_table'):
            with st.container(key='ngi_req_header'):
                for col, titulo in zip(st.columns(larguras, gap='small'), ['Pedido / Solicitante','Item solicitado','Tipo','Data','']):
                    col.markdown(f'<div class="ngi-req-th">{titulo}</div>', unsafe_allow_html=True)
            for _, sol in visiveis.iterrows():
                identificador = int(sol['id'])
                ativo = 'active_' if identificador == aberta else ''
                with st.container(key=f'ngi_req_row_{ativo}{identificador}'):
                    cols = st.columns(larguras, gap='small')
                    # Nome e número são texto simples: sem cerquilha nem HTML do usuário.
                    cols[0].button(f"{identificador} · {sol['solicitante_nome']}", key=f'ngi_sol_analisar_{identificador}', use_container_width=True, on_click=selecionar_solicitacao_ngi, args=(identificador,))
                    cols[1].markdown(f'<div class="ngi-req-cell">{html.escape(str(sol["item_nome"]))}</div>', unsafe_allow_html=True)
                    classe = {'Material':'material','Livro':'livro','Empréstimo':'emprestimo'}[sol['_tipo_visual']]
                    cols[2].markdown(f'<span class="ngi-sol-tag {classe}">{sol["_tipo_visual"]}</span>', unsafe_allow_html=True)
                    data = converter_para_horario_br(sol['data_solicitacao']).strftime('%d/%m · %H:%M') if pd.notna(sol['data_solicitacao']) else '—'
                    cols[3].markdown(f'<div class="ngi-req-date">{data}</div>', unsafe_allow_html=True)
                    cols[4].button('›', key=f'ngi_sol_abrir_{identificador}', help=f'Abrir solicitação {identificador}', on_click=selecionar_solicitacao_ngi, args=(identificador,))
            if visiveis.empty:
                st.info('Nenhuma solicitação encontrada com esses filtros.')
            with st.container(key='ngi_req_footer'):
                info, tamanho = st.columns([2,1], gap='small')
                info.markdown(f'<div class="ngi-req-page-info">{inicio + 1 if len(filtrados) else 0}–{min(inicio + limite, len(filtrados))} de {len(filtrados)} solicitações</div>', unsafe_allow_html=True)
                tamanho.selectbox('Solicitações por página', [8,16,32], key='ngi_sol_limite', format_func=lambda n:f'{n} por página', label_visibility='collapsed', on_change=pagina_solicitacoes_ngi, args=(1,))
                numeros = sorted({1, paginas, *range(max(1,pagina-1), min(paginas,pagina+1)+1)})
                if pagina == 1 and paginas >= 3:
                    numeros = sorted(set(numeros + [2,3]))
                botoes = [0]
                ultimo = 0
                for n in numeros:
                    if ultimo and n > ultimo+1:botoes.append(None)
                    botoes.append(n);ultimo=n
                botoes.append(-1)
                pag_cols = st.columns([max(1,10-len(botoes))]+[1]*len(botoes), gap='small')
                for col, n in zip(pag_cols[1:], botoes):
                    if n is None:col.markdown('<div class="ngi-req-page-info">…</div>', unsafe_allow_html=True)
                    elif n == 0:col.button('‹',key='ngi_sol_anterior',help='Página anterior',disabled=pagina<=1,on_click=pagina_solicitacoes_ngi,args=(pagina-1,))
                    elif n == -1:col.button('›',key='ngi_sol_proxima',help='Próxima página',disabled=pagina>=paginas,on_click=pagina_solicitacoes_ngi,args=(pagina+1,))
                    else:col.button(str(n),key=f'ngi_sol_pag_{n}',type='primary' if n==pagina else 'secondary',on_click=pagina_solicitacoes_ngi,args=(n,))
    with detalhe:
        painel = st.container(key='ngi_req_detail')
    with painel:
        cab, fechar = st.columns([7,1])
        cab.markdown('<div class="ngi-req-detail-title">Detalhes do pedido</div>',unsafe_allow_html=True)
        with fechar:
            with st.container(key='ngi_req_close'):
                st.button('×',key='ngi_sol_fechar',help='Fechar detalhes',disabled=aberta is None,on_click=selecionar_solicitacao_ngi)
        if aberta is None:
            st.caption('Selecione uma solicitação na lista para consultar os detalhes.')
    selecionada = dados[dados['id'] == aberta] if aberta is not None else dados.iloc[0:0]
    return selecionada, painel


def detalhes_solicitacao_ngi(sol, conn):
    """Resumo visual; consulta somente o saldo do item selecionado."""
    esc = lambda v: html.escape(str(v)) if v is not None and pd.notna(v) else '—'
    data = converter_para_horario_br(sol['data_solicitacao']).strftime('%d/%m/%Y às %H:%M') if pd.notna(sol['data_solicitacao']) else '—'
    st.markdown(f'<div class="ngi-req-id"><strong>{int(sol["id"])}</strong><span class="ngi-req-pending">Pendente</span></div><div class="ngi-req-person">{esc(sol["solicitante_nome"])}</div><div class="ngi-req-meta">Coordenação: {esc(sol["coordenacao"])}<br>Solicitado em {data}<br>{esc(sol["solicitante_email"])}</div><div class="ngi-req-divider"></div><div class="ngi-req-item-label">{tipo_solicitacao_visual(sol)} solicitado</div><div class="ngi-req-item">{esc(sol["item_nome"])}</div>', unsafe_allow_html=True)
    saldo = None
    cursor_saldo = conn.cursor()
    try:
        if sol['tipo'] == 'EMPRESTIMO':
            cursor_saldo.execute('SELECT quantidade_disponivel FROM emprestimo_itens WHERE id = %s;', (int(sol['referencia_codigo']),))
        else:
            tabela = {'BRIGADA':'produtos_brigada','LIVROS':'produtos_livros'}.get(sol.get('origem_estoque'),'produtos')
            cursor_saldo.execute(f'SELECT quantidade FROM {tabela} WHERE codigo = %s;', (sol['referencia_codigo'],))
        registro = cursor_saldo.fetchone()
        if registro is not None:saldo = registro[0]
    finally:
        cursor_saldo.close()
    quantidade = int(sol['quantidade'])
    quantidade_txt = f'{quantidade} unidade' + ('s' if quantidade != 1 else '')
    saldo_txt = f'{int(saldo)} unidade' + ('s' if int(saldo) != 1 else '') if saldo is not None else 'Item não encontrado'
    st.markdown(f'<div class="ngi-req-amounts"><div class="ngi-req-amount"><small>Quantidade solicitada</small><strong>{quantidade_txt}</strong></div><div class="ngi-req-amount"><small>Disponível em estoque</small><strong>{saldo_txt}</strong></div></div>', unsafe_allow_html=True)
    if sol['tipo'] == 'EMPRESTIMO':
        ret = sol['data_retirada'].strftime('%d/%m/%Y') if pd.notna(sol['data_retirada']) else '—'
        dev = sol['data_prevista'].strftime('%d/%m/%Y') if pd.notna(sol['data_prevista']) else '—'
        st.markdown(f'<div class="ngi-req-note"><b>Retirada:</b> {ret}<br><b>Devolução prevista:</b> {dev}</div>', unsafe_allow_html=True)
        if sol['termo_aceito'] and pd.notna(sol['data_aceite_termo']):
            aceite = converter_para_horario_br(sol['data_aceite_termo']).strftime('%d/%m/%Y %H:%M')
            st.markdown(f'<div class="ngi-req-note">Termo de Responsabilidade aceito em {aceite}</div>',unsafe_allow_html=True)
    for campo, nome in [('atividade_associada','Atividade associada'),('observacao','Observações do solicitante')]:
        if pd.notna(sol[campo]) and str(sol[campo]).strip():
            st.markdown(f'<div class="ngi-req-note"><b>{nome}:</b> {esc(sol[campo])}</div>',unsafe_allow_html=True)
    if tipo_solicitacao_visual(sol) != 'Material':
        foto_solicitacao_ngi(sol, conn)
    st.markdown('<div class="ngi-req-hint">Confira o item e a quantidade antes de aprovar.</div><div class="ngi-req-divider"></div>',unsafe_allow_html=True)


def foto_solicitacao_ngi(sol, conn):
    # Fotos existem apenas nos catálogos de livros e empréstimos.
    if sol['tipo']=='EMPRESTIMO':
        consulta='SELECT foto FROM emprestimo_itens WHERE id = %s;'
        parametro=int(sol['referencia_codigo'])
    elif sol.get('origem_estoque')=='LIVROS':
        consulta='SELECT foto FROM produtos_livros WHERE codigo = %s;'
        parametro=sol['referencia_codigo']
    else:
        return
    cursor_foto=conn.cursor()
    try:
        cursor_foto.execute(consulta,(parametro,))
        registro=cursor_foto.fetchone()
        if registro and registro[0]:st.image(bytes(registro[0]),width=150)
    finally:
        cursor_foto.close()

def renderizar_banner(titulo, subtitulo, cor="#147746"):
    """Cabeçalho padrão sem fundo colorido usado no topo de cada tela do
    sistema, para manter o visual consistente entre todos os módulos."""
    st.markdown(f"""
        <div class="ngi-page-header" style="background: transparent; padding: 0 0 24px; margin-bottom: 8px;">
            <h1 style="color: #122820; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                {titulo}
            </h1>
            <p style="color: #6a7b73; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                {subtitulo}
            </p>
        </div>
    """, unsafe_allow_html=True)


# =============================================================================
# CARRINHO DE SOLICITAÇÃO — visual padronizado em 3 passos
# (Materiais, Brigada, Livros e Empréstimo usam as mesmas funções)
# =============================================================================
def cabecalho_pedido_ngi(titulo, subtitulo):
    st.markdown(
        '<div class="ngi-stock-heading"><h3>' + html.escape(titulo) + '</h3><p>' +
        html.escape(subtitulo) + '</p></div>', unsafe_allow_html=True)


def passo_pedido_ngi(numero, texto, ativo=True, detalhe=""):
    complemento = f' <small>· {html.escape(detalhe)}</small>' if detalhe else ''
    st.markdown(
        f'<div class="ngi-passo{"" if ativo else " off"}"><b>{numero}</b>{html.escape(texto)}{complemento}</div>',
        unsafe_allow_html=True)


def texto_qtd_itens_ngi(quantidade):
    return f"{quantidade} {'item' if quantidade == 1 else 'itens'}"


def adicionar_item_carrinho_ngi(chave_carrinho, novo_item, saldo_maximo):
    """Inclui o item no carrinho. Se ele já estiver lá, soma a quantidade
    (sem passar do saldo disponível) em vez de repetir a linha."""
    carrinho = st.session_state.setdefault(chave_carrinho, [])
    campo_id = "item_id" if "item_id" in novo_item else "codigo"
    for existente in carrinho:
        if str(existente.get(campo_id)) == str(novo_item[campo_id]):
            soma = int(existente["quantidade"]) + int(novo_item["quantidade"])
            existente["quantidade"] = min(soma, int(saldo_maximo))
            if soma > int(saldo_maximo):
                st.toast(f'"{novo_item["item"]}": quantidade ajustada ao saldo disponível ({int(saldo_maximo)}).')
            else:
                st.toast(f'"{novo_item["item"]}": quantidade atualizada para {existente["quantidade"]}.')
            return
    carrinho.append(novo_item)
    st.toast(f'"{novo_item["item"]}" adicionado ao carrinho.')


def remover_item_carrinho_ngi(chave_carrinho, indice):
    carrinho = st.session_state.get(chave_carrinho, [])
    if 0 <= indice < len(carrinho):
        carrinho.pop(indice)


def renderizar_carrinho_ngi(chave_carrinho, prefixo_botao, mostrar_codigo=True):
    """Lista Código | Material | Qtd | Remover (sem recarregar a página duas vezes)."""
    carrinho = st.session_state.get(chave_carrinho, [])
    with st.container(key=f"ngi_carrinho_box_{prefixo_botao}"):
        cab, _ = st.columns([6, 1.1], vertical_alignment="center")
        cab.markdown(
            '<div class="ngi-carr-head"><span>' + ('Código' if mostrar_codigo else '') +
            '</span><span>Material</span><span style="text-align:center">Qtd</span></div>',
            unsafe_allow_html=True)
        for indice, item in enumerate(carrinho):
            col_item, col_botao = st.columns([6, 1.1], vertical_alignment="center")
            codigo = html.escape(str(item.get("codigo", ""))) if mostrar_codigo else ""
            col_item.markdown(
                f'<div class="ngi-carr-linha"><span>{codigo}</span><span>{html.escape(str(item["item"]))}</span>'
                f'<span>{int(item["quantidade"])}</span></div>', unsafe_allow_html=True)
            with col_botao:
                with st.container(key=f"btn_remove_{prefixo_botao}_{indice}"):
                    st.button("Remover", key=f"remover_{chave_carrinho}_{indice}", icon=":material/delete:",
                              use_container_width=True, on_click=remover_item_carrinho_ngi,
                              args=(chave_carrinho, indice))


def carrinho_vazio_ngi(prefixo, campos=("Coordenação:", "Observações (opcional):"), passo_carrinho=2):
    """Passos finais quando ainda não há itens: explica o que fazer."""
    passo_pedido_ngi(passo_carrinho, "Confira o carrinho", ativo=False, detalhe=texto_qtd_itens_ngi(0))
    st.info(f'Seu carrinho está vazio. Escolha um item no passo {passo_carrinho - 1} e clique em "Adicionar ao carrinho".')
    passo_pedido_ngi(passo_carrinho + 1, "Preencha os dados e envie", ativo=False)
    colunas = st.columns([1, 2])
    for coluna, rotulo in zip(colunas, campos):
        coluna.text_input(rotulo, value="", disabled=True, key=f"vazio_{prefixo}_{rotulo}")
    st.button("Enviar solicitação", type="primary", icon=":material/send:", disabled=True, key=f"enviar_vazio_{prefixo}")

# Controlador de cookies do navegador (mantém o login sem sujar a URL)
# Na primeira execução de cada aba o leitor de cookies é criado; nas seguintes,
# leitura_cookies_pendente indica se o navegador ainda não respondeu.
_primeira_leitura_cookies = "cookie_controller_almoxarifado" not in st.session_state
cookie_controller = CookieController(key="cookie_controller_almoxarifado")

# =============================================================================
# CONEXÃO E INICIALIZAÇÃO AUTOMÁTICA DO BANCO DE DADOS (Neon Postgres)
# =============================================================================
@st.cache_resource(show_spinner=False)
def inicializar_banco_automatico():
    conn = None
    try:
        conn_string = os.environ.get("POSTGRES_URL") or st.secrets["postgres"]["url"]
        conn = psycopg2.connect(conn_string, connect_timeout=10)
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

    cursor.execute("ALTER TABLE emprestimo_itens ADD COLUMN IF NOT EXISTS foto BYTEA;")

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
    cursor.execute("ALTER TABLE solicitacoes_almoxarifado ADD COLUMN IF NOT EXISTS lote_id TEXT;")

    # Colunas para o lembrete automático de devolução em atraso
    cursor.execute("ALTER TABLE emprestimo_registros ADD COLUMN IF NOT EXISTS email_pessoa TEXT;")
    cursor.execute("ALTER TABLE emprestimo_registros ADD COLUMN IF NOT EXISTS ultimo_lembrete_enviado DATE;")

    # =========================================================================
    # NOVO MÓDULO: MATERIAIS BRIGADA (estoque separado, acesso restrito)
    # =========================================================================
    cursor.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS coordenacao TEXT;")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos_brigada (
            codigo TEXT PRIMARY KEY,
            item TEXT,
            quantidade INTEGER,
            categoria TEXT,
            valor_unitario REAL
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes_brigada (
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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categorias_brigada (
            nome TEXT PRIMARY KEY
        );
    """)

    cursor.execute("ALTER TABLE solicitacoes_almoxarifado ADD COLUMN IF NOT EXISTS origem_estoque TEXT DEFAULT 'GERAL';")

    # =========================================================================
    # NOVO MÓDULO: LIVROS E PRODUTOS (com foto obrigatória)
    # =========================================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos_livros (
            codigo TEXT PRIMARY KEY,
            titulo TEXT NOT NULL,
            tipo TEXT,
            quantidade INTEGER NOT NULL DEFAULT 0,
            foto BYTEA
        );
    """)

    cursor.execute("ALTER TABLE produtos_livros ALTER COLUMN foto DROP NOT NULL;")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes_livros (
            id SERIAL PRIMARY KEY,
            data TEXT,
            tipo TEXT,
            codigo TEXT,
            titulo TEXT,
            quantidade INTEGER,
            responsavel TEXT,
            coordenacao TEXT
        );
    """)

    # =========================================================================
    # NOVA TABELA: CONTROLE DE EQUIPAMENTOS EMPRESTADOS (notebooks, desktops,
    # acessórios atribuídos por tempo indeterminado - módulo admin)
    # =========================================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipamentos_emprestados (
            id SERIAL PRIMARY KEY,
            nome_item TEXT NOT NULL,
            marca_modelo TEXT,
            numero_serie TEXT,
            patrimonio TEXT,
            solicitante_usuario TEXT NOT NULL,
            coordenacao TEXT,
            data_retirada DATE,
            data_prevista_devolucao TEXT,
            status TEXT NOT NULL DEFAULT 'Em uso',
            observacao TEXT,
            data_devolucao DATE,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)
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

    # Migração única: criptografa as senhas que ainda estão em texto puro.
    cursor.execute("SELECT email, senha FROM usuarios WHERE senha IS NOT NULL AND senha NOT LIKE 'pbkdf2_sha256$%%';")
    for email_migrar, senha_migrar in cursor.fetchall():
        cursor.execute("UPDATE usuarios SET senha = %s WHERE email = %s;", (gerar_hash_senha(senha_migrar), email_migrar))
    conn.commit()

    # Índices: deixam rápidas as consultas mais usadas (pendentes, minhas
    # solicitações, empréstimos em aberto, sessões). Criados uma única vez.
    for comando_indice in [
        "CREATE INDEX IF NOT EXISTS idx_sol_status ON solicitacoes_almoxarifado (status);",
        "CREATE INDEX IF NOT EXISTS idx_sol_email ON solicitacoes_almoxarifado (solicitante_email);",
        "CREATE INDEX IF NOT EXISTS idx_sol_lote ON solicitacoes_almoxarifado (lote_id);",
        "CREATE INDEX IF NOT EXISTS idx_emp_reg_item_status ON emprestimo_registros (item_id, status);",
        "CREATE INDEX IF NOT EXISTS idx_usuarios_email_lower ON usuarios (LOWER(email));",
        "CREATE INDEX IF NOT EXISTS idx_sessoes_expira ON sessoes_login (expira_em);",
    ]:
        cursor.execute(comando_indice)
    conn.commit()

    conn.close()
    return True

@st.cache_resource(show_spinner=False)
def pool_conexoes_ngi():
    """Inicialização uma vez por processo; cada execução usa sua conexão."""
    from psycopg2.pool import ThreadedConnectionPool
    inicializar_banco_automatico()
    dsn = os.environ.get("POSTGRES_URL") or st.secrets["postgres"]["url"]
    return ThreadedConnectionPool(1, 8, dsn, connect_timeout=10), threading.BoundedSemaphore(8)


@st.cache_resource(show_spinner=False)
def uso_conexoes_ngi():
    """Última vez (relógio interno) em que cada conexão do pool foi usada."""
    return {}


class ConexaoExecucaoNGI:
    """Conexão sob demanda, com rollback e devolução inclusive em st.rerun."""
    def __init__(self):
        self._conexao = None
        self._pool = None
        self._vagas = None

    def __enter__(self):
        return self

    def _obter(self):
        if self._conexao is not None:
            return self._conexao
        pool, vagas = pool_conexoes_ngi()
        if not vagas.acquire(timeout=15):
            raise RuntimeError("Muitos acessos simultâneos. Aguarde alguns segundos e tente novamente.")
        try:
            ultimo_uso = uso_conexoes_ngi()
            for tentativa in range(2):
                conexao = pool.getconn()
                try:
                    # Só reconecta antes da primeira consulta, nunca repete uma gravação.
                    # O teste (3 idas e voltas ao banco) só é feito se a conexão
                    # ficou parada por mais de 30 segundos.
                    if conexao.closed or time.monotonic() - ultimo_uso.get(id(conexao), 0) > 30:
                        with conexao.cursor() as teste:
                            teste.execute("SELECT 1;")
                        conexao.rollback()
                except Exception:
                    pool.putconn(conexao, close=True)
                    if tentativa:
                        raise
                    continue
                self._conexao, self._pool, self._vagas = conexao, pool, vagas
                return conexao
        except BaseException:
            vagas.release()
            raise

    def cursor(self, *args, **kwargs):
        return self._obter().cursor(*args, **kwargs)

    def commit(self):
        if self._conexao is not None:
            self._conexao.commit()
            limpar_caches_ngi()

    def rollback(self):
        if self._conexao is not None:
            self._conexao.rollback()
            _dados_execucao_ngi.clear()

    def __exit__(self, tipo, valor, traceback):
        if self._conexao is not None:
            descartar = bool(self._conexao.closed)
            try:
                if not descartar and self._conexao.info.transaction_status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                    self._conexao.rollback()
            except Exception:
                descartar = True
            finally:
                if descartar:
                    uso_conexoes_ngi().pop(id(self._conexao), None)
                else:
                    uso_conexoes_ngi()[id(self._conexao)] = time.monotonic()
                try:
                    self._pool.putconn(self._conexao, close=descartar)
                finally:
                    self._vagas.release()
                    self._conexao = None
        return False


# Este dicionário dura somente a execução atual, sem cache de saldo entre usuários.
_dados_execucao_ngi = {}


def dados_sob_demanda_ngi(nome):
    consultas = {
        "produtos": 'SELECT codigo AS "Código", item AS "Item", quantidade AS "Quantidade", categoria AS "Categoria", valor_unitario AS "Valor Unitário" FROM produtos ORDER BY codigo ASC',
        "movimentacoes": 'SELECT data AS "Data", tipo AS "Tipo", codigo AS "Código", item AS "Item", quantidade AS "Quantidade", responsavel AS "Responsável", coordenacao AS "Coordenação" FROM movimentacoes',
        "coordenacoes": 'SELECT sigla AS "Sigla", nome AS "Nome" FROM coordenacoes',
        "categorias": "SELECT nome FROM categorias",
    }
    if nome not in _dados_execucao_ngi:
        if nome in ("coordenacoes", "categorias"):
            # Mudam raramente: ficam em cache (renovado a cada gravação).
            resultado = _tabela_auxiliar_ngi(nome, consultas[nome]).copy()
        else:
            # Saldo de produtos: sempre lido do banco, sem cache entre usuários.
            resultado = pd.read_sql_query(consultas[nome], conn)
        _dados_execucao_ngi[nome] = resultado["nome"].tolist() if nome == "categorias" else resultado
    return _dados_execucao_ngi[nome]


def contar_movimentacoes_ngi():
    with conn.cursor() as cursor_contagem:
        cursor_contagem.execute("SELECT COUNT(*) FROM movimentacoes;")
        return int(cursor_contagem.fetchone()[0])


def miniatura_foto_ngi(foto):
    """Reduz a foto só para exibição nos cartões (a original continua no banco)."""
    from PIL import Image, ImageOps
    try:
        with Image.open(io.BytesIO(foto)) as original:
            imagem = ImageOps.exif_transpose(original)
            if imagem.mode in ("RGBA", "LA", "P"):
                imagem = imagem.convert("RGBA")
                fundo = Image.new("RGB", imagem.size, (255, 255, 255))
                fundo.paste(imagem, mask=imagem.split()[-1])
                imagem = fundo
            else:
                imagem = imagem.convert("RGB")
            imagem.thumbnail((360, 360))
            destino = io.BytesIO()
            imagem.save(destino, format="JPEG", quality=80, optimize=True)
            return destino.getvalue()
    except Exception:
        return foto


@st.cache_data(show_spinner=False, ttl=900, max_entries=300)
def _miniaturas_catalogo_ngi(tabela, ids):
    chave = {"emprestimo_itens": "id", "produtos_livros": "codigo"}[tabela]
    if not ids:
        return {}
    with conn.cursor() as cursor_fotos:
        cursor_fotos.execute(f"SELECT {chave}, foto FROM {tabela} WHERE {chave} = ANY(%s);", (list(ids),))
        return {identificador: miniatura_foto_ngi(bytes(foto)) if foto is not None else None for identificador, foto in cursor_fotos.fetchall()}


def fotos_catalogo_ngi(tabela, identificadores):
    """Miniaturas das fotos do catálogo. Ficam guardadas em cache e são
    renovadas automaticamente sempre que algo é gravado no banco."""
    chave = {"emprestimo_itens": "id", "produtos_livros": "codigo"}[tabela]
    ids = tuple(int(i) for i in identificadores) if chave == "id" else tuple(str(i) for i in identificadores)
    return _miniaturas_catalogo_ngi(tabela, ids)


@st.cache_data(show_spinner=False, ttl=600)
def _tabela_auxiliar_ngi(nome, consulta):
    return pd.read_sql_query(consulta, conn)


@st.cache_data(show_spinner=False, ttl=60)
def contar_pendentes_ngi():
    with conn.cursor() as cursor_badge:
        cursor_badge.execute("SELECT COUNT(*) FROM solicitacoes_almoxarifado WHERE status = 'PENDENTE';")
        return int(cursor_badge.fetchone()[0])


def limpar_caches_ngi():
    """Chamado a cada gravação: ninguém vê dado desatualizado."""
    _dados_execucao_ngi.clear()
    _miniaturas_catalogo_ngi.clear()
    _tabela_auxiliar_ngi.clear()
    contar_pendentes_ngi.clear()


@st.cache_resource(show_spinner=False)
def estado_lembretes_ngi():
    return {"lock": threading.Lock(), "proxima": 0.0, "executando": False}


def agendar_lembretes_ngi():
    """Executa lembretes fora da tela, em conexão exclusiva, sem usar APIs do Streamlit na thread."""
    estado = estado_lembretes_ngi()
    with estado["lock"]:
        if estado["executando"] or time.monotonic() < estado["proxima"]:
            return
        dsn = os.environ.get("POSTGRES_URL") or st.secrets["postgres"]["url"]
        estado["executando"] = True
        estado["proxima"] = time.monotonic() + 600

    def tarefa():
        conexao = None
        try:
            conexao = psycopg2.connect(dsn, connect_timeout=10)
            # Trava transacional evita duas instâncias enviarem o mesmo lote ao mesmo tempo.
            with conexao.cursor() as trava:
                trava.execute("SELECT pg_try_advisory_xact_lock(684217903);")
                pode_executar = trava.fetchone()[0]
            if pode_executar:
                verificar_e_notificar_emprestimos_atrasados(conexao)
        except Exception as erro:
            print(f"[LEMBRETE ATRASO] Falha no processamento em segundo plano: {type(erro).__name__}")
        finally:
            try:
                if conexao is not None:
                    conexao.close()
            finally:
                with estado["lock"]:
                    estado["executando"] = False
    try:
        threading.Thread(target=tarefa, name="ngi-lembretes", daemon=True).start()
    except Exception:
        with estado["lock"]:
            estado["executando"] = False
        raise


# =============================================================================
# MANTÉM O LOGIN APÓS ATUALIZAR A PÁGINA (F5)
# =============================================================================
# Antes, o cookie era gravado e a tela recarregava logo em seguida; o
# recarregamento removia o componente antes de o navegador gravar o cookie,
# e o F5 deslogava. Agora o componente de gravação fica na página enquanto o
# usuário está logado. A sessão vale SESSAO_DURACAO_MINUTOS sem uso e é
# renovada (banco + cookie) a cada 5 minutos de atividade.
def manter_sessao_ngi():
    token = st.session_state.get("SESSION_TOKEN")
    if not token:
        return
    agora = datetime.now()
    ultima = st.session_state.get("sessao_renovada_em")
    if ultima is None or "sessao_cookie_expira" not in st.session_state or (agora - ultima).total_seconds() > 300:
        nova_expiracao = agora + timedelta(minutes=SESSAO_DURACAO_MINUTOS)
        try:
            with conn.cursor() as cursor_renova:
                cursor_renova.execute("UPDATE sessoes_login SET expira_em = %s WHERE token = %s;", (nova_expiracao, token))
            conn.commit()
        except Exception:
            conn.rollback()
        st.session_state.sessao_renovada_em = agora
        st.session_state.sessao_cookie_expira = nova_expiracao
    try:
        # Mesmos argumentos a cada execução: o componente continua montado
        # e o navegador tem tempo de gravar o cookie.
        cookie_controller.set(
            "session", token,
            max_age=SESSAO_DURACAO_MINUTOS * 60,
            expires=st.session_state.sessao_cookie_expira,
            same_site="lax"
        )
    except Exception:
        pass


with ConexaoExecucaoNGI() as conn:

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
            <div style="background-color: #147746; padding: 18px 24px; border-radius: 8px 8px 0 0;">
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
    # LEMBRETE AUTOMÁTICO DE DEVOLUÇÃO EM ATRASO (roda no máximo 1x por dia)
    # =============================================================================
    def verificar_e_notificar_emprestimos_atrasados(conexao):
        try:
            cursor_atraso = conexao.cursor()

            # Trava de "1x por dia": guarda a última data em que essa verificação
            # rodou na tabela config_sistema, para não reenviar e-mails toda vez
            # que alguém abrir o sistema no mesmo dia.
            cursor_atraso.execute("SELECT valor FROM config_sistema WHERE chave = 'ultima_verificacao_atrasados';")
            resultado_config = cursor_atraso.fetchone()
            hoje_str = date.today().isoformat()

            if resultado_config and resultado_config[0] == hoje_str:
                return  # já rodou hoje

            cursor_atraso.execute("""
            SELECT er.id, er.item_nome, er.quantidade, er.pessoa,
                   COALESCE(er.email_pessoa, u.email) AS email_encontrado,
                   er.data_prevista
            FROM emprestimo_registros er
            LEFT JOIN usuarios u ON LOWER(u.nome) = LOWER(er.pessoa)
            WHERE er.status = 'EMPRESTADO'
              AND er.data_prevista < CURRENT_DATE
              AND (er.ultimo_lembrete_enviado IS NULL OR er.ultimo_lembrete_enviado < CURRENT_DATE)
              AND COALESCE(er.email_pessoa, u.email) IS NOT NULL;
        """)
            atrasados = cursor_atraso.fetchall()

            for reg_id, item_nome, quantidade, pessoa, email_pessoa, data_prevista in atrasados:
                dias_atraso = (date.today() - data_prevista).days
                sucesso, _ = enviar_email_notificacao(
                    email_pessoa,
                    "Lembrete: devolução de material em atraso",
                    f"""
                <p>Olá, {pessoa},</p>
                <p>Este é um lembrete automático de que o item abaixo, emprestado pelo Almoxarifado, está com a devolução em atraso:</p>
                <p><b>Item:</b> {item_nome}<br><b>Quantidade:</b> {quantidade}<br><b>Data prevista de devolução:</b> {data_prevista.strftime('%d/%m/%Y')} ({dias_atraso} dia(s) de atraso)</p>
                <p>Pedimos que providencie a devolução o quanto antes, ou entre em contato com a Coordenação de Operação e Suporte caso precise de mais prazo.</p>
                """
                )
                if sucesso:
                    cursor_atraso.execute(
                        "UPDATE emprestimo_registros SET ultimo_lembrete_enviado = CURRENT_DATE WHERE id = %s;",
                        (reg_id,)
                    )

            cursor_atraso.execute("""
            INSERT INTO config_sistema (chave, valor) VALUES ('ultima_verificacao_atrasados', %s)
            ON CONFLICT (chave) DO UPDATE SET valor = %s;
        """, (hoje_str, hoje_str))
            conexao.commit()
        except Exception as ex_atraso:
            conexao.rollback()
            print(f"[LEMBRETE ATRASO] Erro ao verificar empréstimos atrasados: {ex_atraso}")

    # Lembretes são agendados somente após autenticação, sem bloquear a tela.


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
        // Um único observador por página, e a tradução roda no máximo
        // uma vez por quadro de tela (antes rodava a cada mudança no DOM).
        if (window.parent.__ngiTradutorCalendario) {
            window.parent.__ngiTradutorCalendario.disconnect();
        }
        let agendado = false;
        const observer = new MutationObserver(function() {
            if (agendado) return;
            agendado = true;
            window.parent.requestAnimationFrame(function() {
                agendado = false;
                verificarCalendarios(docPai);
            });
        });
        observer.observe(docPai.body, { childList: true, subtree: true });
        window.parent.__ngiTradutorCalendario = observer;
        verificarCalendarios(docPai);
    } catch (e) {
        // Ignora silenciosamente se não conseguir acessar o documento principal
    }
})();
</script>
""", height=0, width=0)

    # Dicionário de estilo adaptativo para os menus horizontais
    ESTILO_MENU_HORIZONTAL = {
        "container": {"padding": "4px 0!important", "background-color": "transparent", "border-bottom": "1px solid #dfe7e1", "border-radius": "0"},
        "icon": {"color": "#688172", "font-size": "15px"},
        "nav-link": {"font-family": "'Manrope', 'Segoe UI', sans-serif", "font-size": "13px", "text-align": "center",
                     "margin": "0px 2px", "padding": "11px 8px", "color": "#61766a",
                     "border-radius": "0", "--hover-color": "#edf4ef"},
        "nav-link-selected": {"background-color": "#edf4ef", "color": "#126239", "font-weight": "600", "border-bottom": "3px solid #187746"},
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
        try:
            # Em conexões mais lentas o navegador demora a responder com os
            # cookies; o leitor continua na página até a resposta chegar
            # (antes ele sumia na segunda execução e o F5 deslogava).
            if not _primeira_leitura_cookies and not cookie_controller.getAll():
                cookie_controller.refresh()
            token_cookie = cookie_controller.get("session")
        except Exception:
            token_cookie = None

        # Na primeiríssima execução após abrir/atualizar a página, o componente
        # de cookies ainda pode não ter tido tempo de entregar o valor ao Python
        # (token_cookie viria vazio mesmo com o cookie presente no navegador).
        # Para evitar mostrar a tela de login por engano nesse instante, aguarda
        # um instante e tenta novamente antes de decidir.
        if token_cookie is None and not st.session_state.get("verificacao_cookie_feita"):
            st.session_state.verificacao_cookie_feita = True
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

                        cursor_sessao.execute("SELECT coordenacao FROM usuarios WHERE LOWER(email) = %s;", (email_sessao.lower(),))
                        resultado_coord_sessao = cursor_sessao.fetchone()
                        st.session_state.COORDENACAO_USUARIO_LOGADO = resultado_coord_sessao[0] if resultado_coord_sessao else None

                        nova_expiracao = datetime.now() + timedelta(minutes=SESSAO_DURACAO_MINUTOS)
                        cursor_sessao.execute(
                            "UPDATE sessoes_login SET expira_em = %s WHERE token = %s;",
                            (nova_expiracao, token_cookie)
                        )
                        conn.commit()
                        st.session_state.sessao_renovada_em = datetime.now()
                        st.session_state.sessao_cookie_expira = nova_expiracao
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

    # Um único espaço visual permite retirar a tela antiga por completo ao sair.
    tela_principal_ngi = st.empty()
    with tela_principal_ngi.container():
        if token_redefinicao_url and not st.session_state.autenticado:
            col_rd1, col_rd2, col_rd3 = st.columns([1, 1.2, 1])
            with col_rd2:
                st.write("<br><br>", unsafe_allow_html=True)
                st.markdown("""
            <div class="img-container">
                <img src="https://www.gov.br/icmbio/pt-br/assuntos/biodiversidade/unidade-de-conservacao/unidades-de-biomas/marinho/lista-de-ucs/parna-marinho-dos-abrolhos/fomulario-denuncia/icmbio-logo-1.png" width="280">
            </div>
        """, unsafe_allow_html=True)
                st.markdown('<h3 style="display: flex; align-items: center; gap: 8px;"><span class="material-symbols-rounded" style="font-size: 22px; color: #147746;">lock</span>Criar Nova Senha</h3>', unsafe_allow_html=True)

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
                                        (gerar_hash_senha(nova_senha_reset), email_reset)
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
                st.markdown('<style>\n/* Este tema existe somente na tela de login; não altera o sistema autenticado. */\n.stApp, [data-testid="stAppViewContainer"] {\n --text-color:#244238; --background-color:#fcfcfa; --secondary-background-color:#f1f4f1;\n --primary-color:#147746; background:#fcfcfa !important;\n}\n[data-testid="stHeader"], [data-testid="stSidebar"] { display:none; }\n[data-testid="stMainBlockContainer"], .main .block-container {\n width:45% !important; max-width:none !important; margin-left:55% !important;\n margin-right:0 !important; padding:36px clamp(28px,4vw,80px) !important;\n min-height:100vh; display:flex; flex-direction:column; justify-content:center; box-sizing:border-box;\n}\n.st-key-ngi_login_panel { width:100%; max-width:520px; margin:0 auto; }\n.ngi-login-hero { position:fixed; left:0; top:0; bottom:0; width:55%;\n background-color:#0b3024; background-position:center; background-size:cover;\n display:flex; flex-direction:column; justify-content:space-between;\n padding:42px clamp(32px,4vw,72px); box-sizing:border-box; z-index:1;\n}\n.ngi-login-brand { align-self:flex-start; display:flex; align-items:center; gap:12px;\n padding:12px 18px; border:1px solid #ffffff60; border-radius:16px;\n background:#ffffff12; color:#fff !important; font-size:18px; }\n.ngi-login-brand svg { width:28px; height:28px; }\n.ngi-login-message { margin-top:auto; padding-top:90px; }\n.ngi-login-eyebrow { color:#ebf6ee !important; font-size:12px; font-weight:600; letter-spacing:3px; margin-bottom:18px; }\n.stMarkdown .ngi-login-hero h1 { font-family:Georgia,\'Times New Roman\',serif !important;\n color:white !important; font-weight:600 !important; font-size:clamp(38px,4.7vw,76px) !important;\n line-height:1.04 !important; letter-spacing:-1.5px; padding:0; margin:0 0 20px; }\n.stMarkdown .ngi-login-hero p { color:#acdfbd !important; font-size:clamp(16px,1.5vw,23px);\n line-height:1.5; max-width:530px; margin:0; }\n.ngi-login-accent { width:54px; height:3px; background:#38ae76; margin:24px 0 36px; }\n.ngi-login-caption { color:#d5e8dc !important; font-size:11px; letter-spacing:2px; } .stApp .stMarkdown .ngi-login-hero .ngi-login-photo-credit, .stApp .stMarkdown .ngi-login-hero .ngi-login-photo-credit * { color:#ffffff !important; -webkit-text-fill-color:#ffffff !important; opacity:1 !important; font-size:12px !important; font-weight:500 !important; text-shadow:0 1px 3px #000 !important; }\n.ngi-login-heading { text-align:center; margin-bottom:16px; }\n.ngi-login-heading img { display:block; width:135px; height:auto; margin:0 auto 22px; }\n.stMarkdown .ngi-login-heading h2 { font-family:Georgia,\'Times New Roman\',serif !important;\n color:#0b3024 !important; font-size:clamp(30px,2.9vw,46px) !important;\n font-weight:700 !important; letter-spacing:-1px; margin:0 0 8px; padding:0; line-height:1.15; }\n.stMarkdown .ngi-login-heading p { color:#63766b !important; font-size:15px; margin:0; }\n.st-key-ngi_login_panel [data-testid="stForm"] { border:0 !important; padding:0 !important; background:transparent; }\n.st-key-ngi_login_panel [data-testid="stWidgetLabel"] p { color:#344f43 !important; font-weight:600; font-size:14px; }\n.st-key-ngi_login_panel [data-baseweb="input"] { border:1px solid #d3dcd5 !important; border-radius:10px; background:white; min-height:50px; }\n.st-key-ngi_login_panel input { background:transparent !important; color:#203d30 !important; font-size:15px; }\n.st-key-ngi_login_panel [data-baseweb="input"]:focus-within { border-color:#147746 !important; box-shadow:0 0 0 3px #14774615; }\n.st-key-ngi_login_panel [data-testid="stFormSubmitButton"] button { background:#147746 !important;\n border-color:#147746 !important; min-height:52px; border-radius:10px; box-shadow:0 6px 16px #0d573720; }\n.st-key-ngi_login_panel [data-testid="stFormSubmitButton"] button p { color:white !important; font-size:16px; font-weight:700; }\n.st-key-ngi_login_panel [data-testid="stFormSubmitButton"] button:hover { background:#0c6036 !important; }\n.st-key-ngi_login_panel [data-testid="stButton"] button { background:transparent !important;\n border:none !important; box-shadow:none !important; min-height:32px; padding:0; justify-content:flex-end; }\n.st-key-ngi_login_panel [data-testid="stButton"] button p { color:#187246 !important; font-size:13px; text-decoration:underline; }\n.stMarkdown .ngi-login-restricted { display:flex; gap:8px; align-items:center; justify-content:center;\n color:#7a897f !important; font-size:12px; margin:18px 0; }\n.ngi-login-restricted svg { width:16px; height:16px; }\n.stMarkdown .ngi-login-footer { border-top:1px solid #e1e7e2; padding-top:18px;\n text-align:center; color:#839087 !important; font-size:11px; margin-top:20px; }\n@media(max-width:850px) {\n .ngi-login-hero { position:relative; width:100%; min-height:260px; padding:24px; border-radius:0; }\n .ngi-login-message { padding-top:35px; }\n .stMarkdown .ngi-login-hero h1 { font-size:34px !important; max-width:470px; }\n .ngi-login-hero h1 br { display:none; }\n .ngi-login-eyebrow, .ngi-login-caption, .ngi-login-accent, .ngi-login-hero p { display:none; }\n [data-testid="stMainBlockContainer"], .main .block-container { width:100% !important;\n margin:0 !important; padding:0 0 28px !important; min-height:100vh; justify-content:flex-start; }\n .st-key-ngi_login_panel { padding:24px; box-sizing:border-box; }\n .ngi-login-heading img { width:100px; margin-bottom:16px; }\n .ngi-login-heading { margin-bottom:8px; }\n}\n@media(max-height:700px) and (min-width:851px) {\n .ngi-login-heading img { width:100px; margin-bottom:12px; }\n .ngi-login-footer { margin-top:10px !important; }\n .ngi-login-hero { padding-top:28px; padding-bottom:28px; }\n .ngi-login-message { padding-top:24px; }\n}\n</style>\n<style>\n/* Compatibilidade com os elementos internos das diferentes versões do Streamlit. */\n.ngi-login-hero h1 [data-heading-text], .ngi-login-hero h1 span {\n    color:#fff !important; font-family:Georgia,\'Times New Roman\',serif !important;\n}\n.ngi-login-heading h2 [data-heading-text], .ngi-login-heading h2 span {\n    color:#0b3024 !important; font-family:Georgia,\'Times New Roman\',serif !important;\n}\n.ngi-login-hero [data-testid="stHeaderActionElements"],\n.ngi-login-heading [data-testid="stHeaderActionElements"] { display:none; }\n.st-key-ngi_login_panel [data-testid="stTextInputRootElement"] {\n    border:1px solid #d3dcd5 !important; border-radius:10px; background:#fff !important; min-height:50px;\n}\n.st-key-ngi_login_panel [data-testid="stTextInputRootElement"]:focus-within {\n    border-color:#147746 !important; box-shadow:0 0 0 3px #14774615;\n}\n.stApp .st-key-ngi_login_panel [data-testid="stFormSubmitButton"] button[kind] {\n    background:#147746 !important; border-color:#147746 !important;\n}\n.stApp .st-key-ngi_login_panel [data-testid="stFormSubmitButton"] button[kind]:hover {\n    background:#0c6036 !important; border-color:#0c6036 !important;\n}\n</style>\n', unsafe_allow_html=True)
                st.markdown('<section class="ngi-login-hero" style="background-image:linear-gradient(180deg,rgba(5,31,24,.08) 15%,rgba(5,31,24,.4) 65%,rgba(5,31,24,.76)),url(data:image/webp;base64,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)"><div class="ngi-login-brand"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M20 3C6 1 2 8 5 16c8 4 17-1 15-13ZM3 21 17 7"/></svg>NGI Carajás</div><div class="ngi-login-message"><div class="ngi-login-eyebrow">GESTÃO DE ALMOXARIFADO</div><h1>Organização que <br>apoia a <br>conservação.</h1><p>Materiais, pessoas e recursos conectados ao cuidado com a natureza.</p><div class="ngi-login-accent"></div></div><div class="ngi-login-caption">Núcleo de Gestão Integrada de Carajás</div><span class="ngi-login-photo-credit" style="position:absolute;right:14px;bottom:12px;font-size:11px;line-height:1.4;font-weight:500;letter-spacing:0;color:#ffffff !important;-webkit-text-fill-color:#ffffff !important;opacity:1 !important;text-shadow:0 1px 3px rgba(0,0,0,.95);">Foto: João Marcos Rosa</span></section>', unsafe_allow_html=True)
                with st.container(key="ngi_login_panel"):
                    with st.container():
                        st.markdown('<div class="ngi-login-heading"><img src="data:image/webp;base64,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" alt="ICMBio — Instituto Chico Mendes de Conservação da Biodiversidade"><h2>Bem-vindo de volta</h2><p>Acesse o Sistema de Gestão de Almoxarifado</p></div>', unsafe_allow_html=True)

                        with st.form("form_login", clear_on_submit=False):
                            usuario_input = st.text_input("Usuário / E-mail")
                            senha_input = st.text_input("Senha", type="password")
                            st.markdown("<br>", unsafe_allow_html=True)

                            submeteu_login = st.form_submit_button("Entrar no Sistema", type="primary", use_container_width=True)

                        if submeteu_login:
                            if usuario_input and senha_input:
                                cursor = conn.cursor()
                                cursor.execute("SELECT nome, senha, perfil, email, coordenacao FROM usuarios WHERE LOWER(email) = %s;", (usuario_input.strip().lower(),))
                                resultado = cursor.fetchone()

                                if resultado:
                                    nome_banco, senha_banco, perfil_banco, email_banco, coordenacao_banco = resultado
                                    if verificar_senha(str(senha_input).strip(), senha_banco):
                                        if not senha_esta_criptografada(senha_banco):
                                            # Senha antiga em texto puro: criptografa no primeiro login.
                                            try:
                                                cursor.execute("UPDATE usuarios SET senha = %s WHERE email = %s;", (gerar_hash_senha(str(senha_input).strip()), email_banco))
                                                conn.commit()
                                            except Exception:
                                                conn.rollback()
                                        st.session_state.autenticado = True
                                        st.session_state.NOME_USUARIO_LOGADO = nome_banco
                                        st.session_state.PERFIL_USUARIO_LOGADO = perfil_banco
                                        st.session_state.EMAIL_USUARIO_LOGADO = email_banco
                                        st.session_state.COORDENACAO_USUARIO_LOGADO = coordenacao_banco

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
                                            # O cookie é gravado na próxima tela (já logada),
                                            # por manter_sessao_ngi(), que fica ativa na página.
                                            st.session_state.sessao_renovada_em = datetime.now()
                                            st.session_state.sessao_cookie_expira = expira_em_novo
                                        except Exception:
                                            conn.rollback()

                                        st.rerun()
                                    else:
                                        st.error("Senha incorreta!")
                                else:
                                    st.error("Usuário ou E-mail não cadastrado!")
                            else:
                                st.error("Por favor, preencha todos os campos!")

                        if st.button("Esqueci a senha", use_container_width=True):
                            st.session_state.sub_tela_login = "esqueci"
                            st.rerun()

                        st.markdown('<p class="ngi-login-restricted"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4m-4 4v3"/></svg>Acesso restrito a usuários cadastrados</p><p class="ngi-login-footer">ICMBio · NGI Carajás</p><div class="ngi-login-uc-logos" style="width:100%;margin:32px auto 0;text-align:center;"><img src="data:image/webp;base64,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" alt="Logos das unidades de conservação do NGI Carajás: Campos Ferruginosos, Carajás, Tapirapé-Aquiri, Igarapé Gelado, Itacaiúnas e Tapirapé" style="display:block;width:100%;max-width:100%;height:auto;object-fit:contain;margin:0 auto;" /></div>', unsafe_allow_html=True)

            elif st.session_state.sub_tela_login == "esqueci":
                col_r1, col_r2, col_r3 = st.columns([1, 1.2, 1])
                with col_r2:
                    st.write("<br><br>", unsafe_allow_html=True)
                    st.markdown('<h3 style="display: flex; align-items: center; gap: 8px;"><span class="material-symbols-rounded" style="font-size: 22px; color: #147746;">key</span>Recuperar Acesso</h3>', unsafe_allow_html=True)
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
                                        <a href="{link_redefinicao}" style="background-color: #147746; color: #ffffff; padding: 12px 28px; border-radius: 6px; text-decoration: none; font-weight: 600; display: inline-block;">Criar Nova Senha</a>
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
            agendar_lembretes_ngi()
            # --- MENU LATERAL ---
            label_solicitacoes = "Solicitações"

            st.markdown(CSS_VISUAL_NGI, unsafe_allow_html=True)
            with st.sidebar:
                st.markdown(
                    '<div class="ngi-profile"><div class="ngi-avatar">' +
                    html.escape(''.join(p[0] for p in str(st.session_state.NOME_USUARIO_LOGADO).split()[:2]).upper()) +
                    '</div><div><div class="ngi-profile-name">' + html.escape(str(st.session_state.NOME_USUARIO_LOGADO)) +
                    '</div><div class="ngi-profile-role">' + html.escape(str(st.session_state.PERFIL_USUARIO_LOGADO)) +
                    '</div></div></div>', unsafe_allow_html=True)

                st.markdown('<div class="ngi-brand"><div class="ngi-brand-icon">◈</div>'
                        '<div><div class="ngi-brand-name">NGI Carajás</div>'
                        '<div class="ngi-brand-subtitle">Gestão de Almoxarifado</div></div></div>', unsafe_allow_html=True)

                if st.session_state.PERFIL_USUARIO_LOGADO == "Usuário Comum":
                    # ---------------------------------------------------------------
                    # MENU RESTRITO - PERFIL USUÁRIO (MÓDULO DE SOLICITAÇÃO)
                    # ---------------------------------------------------------------
                    opcoes_menu_user = ["Materiais Disponíveis", "Empréstimo de Material", "Livros e Produtos"]
                    icones_menu_user = ["box-seam", "arrow-repeat", "book"]

                    coordenacao_logada_normalizada = (st.session_state.get("COORDENACAO_USUARIO_LOGADO") or "").strip().upper()
                    if coordenacao_logada_normalizada == "BRIGADA":
                        opcoes_menu_user.append("Materiais Brigada")
                        icones_menu_user.append("fire")

                    opcoes_menu_user += ["Minhas Solicitações", "Sair do Sistema"]
                    icones_menu_user += ["clock-history", "box-arrow-right"]

                    escolha = option_menu(
                        menu_title=None,
                        options=opcoes_menu_user,
                        icons=icones_menu_user,
                        menu_icon="cast",
                        default_index=0,
                        styles=ESTILO_MENU_LATERAL_NGI
                    )
                else:
                    # ---------------------------------------------------------------
                    # MENU COMPLETO - PERFIL ADMINISTRADOR (MENU ORIGINAL + SOLICITAÇÕES)
                    # ---------------------------------------------------------------
                    try:
                        qtd_pendentes_badge = contar_pendentes_ngi()
                    except Exception:
                        conn.rollback()
                        qtd_pendentes_badge = 0

                    label_solicitacoes = f"Solicitações ({qtd_pendentes_badge})" if qtd_pendentes_badge > 0 else "Solicitações"

                    escolha = option_menu(
                        menu_title=None,
                        options=[
                            "Painel Geral", 
                            "Materiais Disponíveis",
                            "Empréstimo de Material",
                            "Cadastrar Produto", 
                            "Materiais Brigada",
                            "Livros e Produtos",
                            "Cadastrar Categoria", 
                            "Cadastrar Usuário", 
                            "Cadastrar Coordenação",
                            "Movimentação de Estoque",
                            label_solicitacoes,
                            "Relatórios",
                            "Controle de Equipamentos Emprestados",
                            "Sair do Sistema"
                        ],
                        icons=["grid", "box-seam", "arrow-repeat", "box", "fire", "book", "folder", "person-plus", "building", "arrow-left-right", "bell", "bar-chart-line", "laptop", "box-arrow-right"],
                        menu_icon="cast",
                        default_index=0,
                        styles=ESTILO_MENU_LATERAL_NGI,
                        # Chave fixa: quando o número de pendentes muda (ex.: ao aprovar),
                        # o menu continua na tela atual em vez de voltar ao Painel Geral.
                        key="menu_lateral_admin_ngi"
                    )
                    if str(escolha or "").startswith("Solicitações"):
                        escolha = label_solicitacoes

            st.markdown('<div class="ngi-breadcrumb">NGI Carajás &nbsp; / &nbsp; ' + html.escape(str(escolha)) + '</div>', unsafe_allow_html=True)

            if escolha != "Sair do Sistema":
                manter_sessao_ngi()

            if escolha == "Sair do Sistema":
                tela_principal_ngi.empty()
                if st.session_state.SESSION_TOKEN:
                    try:
                        cursor_logout = conn.cursor()
                        cursor_logout.execute("DELETE FROM sessoes_login WHERE token = %s;", (st.session_state.SESSION_TOKEN,))
                        conn.commit()
                    except Exception:
                        conn.rollback()
                try:
                    cookie_controller.remove("session")
                except Exception:
                    pass
                st.session_state.autenticado = False
                st.session_state.NOME_USUARIO_LOGADO = ""
                st.session_state.PERFIL_USUARIO_LOGADO = ""
                st.session_state.EMAIL_USUARIO_LOGADO = ""
                st.session_state.SESSION_TOKEN = ""
                st.rerun()

            # --- TELA: PAINEL GERAL ---
            elif escolha == "Painel Geral":
                renderizar_banner("Painel geral de controle", "Visão geral do estoque e das movimentações do almoxarifado")
                total_itens = len(dados_sob_demanda_ngi("produtos")) if not dados_sob_demanda_ngi("produtos").empty else 0
                produtos_esgotados = len(dados_sob_demanda_ngi("produtos")[dados_sob_demanda_ngi("produtos")['Quantidade'] == 0]) if not dados_sob_demanda_ngi("produtos").empty else 0
                total_movimentacoes = contar_movimentacoes_ngi()
        
                renderizar_indicadores_painel_ngi(total_itens, produtos_esgotados, total_movimentacoes)

                with st.container(border=True):
                    st.markdown('<div class="ngi-stock-heading"><h3>Controle de estoque</h3><p>Consulte os materiais cadastrados</p></div>', unsafe_allow_html=True)
                    col_filtro1, col_filtro2 = st.columns([2, 1])
                    termo_busca = col_filtro1.text_input("Buscar por Nome do Material ou Código:", placeholder="Digite o termo para pesquisar...")
                    categoria_selecionada = col_filtro2.selectbox("Filtrar por Categoria:", ["Todas"] + dados_sob_demanda_ngi("categorias"))
        
                    df_filtrado = dados_sob_demanda_ngi("produtos").copy() if not dados_sob_demanda_ngi("produtos").empty else pd.DataFrame()
                    if not df_filtrado.empty and termo_busca:
                        df_filtrado = df_filtrado[df_filtrado['Item'].str.contains(termo_busca, case=False, na=False) | df_filtrado['Código'].str.contains(termo_busca, case=False, na=False)]
                    if not df_filtrado.empty and categoria_selecionada != "Todas":
                        df_filtrado = df_filtrado[df_filtrado['Categoria'] == categoria_selecionada]

                    if df_filtrado.empty:
                        st.info("Nenhum material encontrado com os filtros aplicados.")
                    else:
                        df_display = df_filtrado.copy()
                        df_display["Valor Unitário"] = df_display["Valor Unitário"].astype(float)
                        df_display["Valor Total"] = df_display["Quantidade"] * df_display["Valor Unitário"]
                        df_display["Valor Unitário"] = df_display["Valor Unitário"].map(lambda valor: "R$ " + format(valor, ",.2f").replace(",", "_").replace(".", ",").replace("_", "."))
                        df_display["Valor Total"] = df_display["Valor Total"].map(lambda valor: "R$ " + format(valor, ",.2f").replace(",", "_").replace(".", ",").replace("_", "."))

                        def destacar_zerados(row):
                            if row['Quantidade'] == 0:
                                return ['background-color: rgba(198, 40, 40, 0.12); color: #c62828; font-weight: bold;'] * len(row)
                            return [''] * len(row)
                
                        st.dataframe(df_display.style.set_properties(**{"background-color": "#ffffff", "color": "#334b3e"}).apply(destacar_zerados, axis=1), use_container_width=True, hide_index=True)

            # =========================================================================
            # NOVA TELA: EMPRÉSTIMO DE MATERIAL (INDEPENDENTE)
            # =========================================================================
            elif escolha == "Empréstimo de Material" and st.session_state.PERFIL_USUARIO_LOGADO != "Usuário Comum":
                st.markdown("""
            <div class="ngi-page-header" style="background: transparent; padding: 0 0 24px; margin-bottom: 8px;">
                <h1 style="color: #122820; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                    Gestão de Empréstimo de Material
                </h1>
                <p style="color: #6a7b73; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Módulo independente de empréstimos, controle de devoluções e histórico
                </p>
            </div>
        """, unsafe_allow_html=True)

                sub_emp = st.radio(
                    "Navegação de empréstimos",
                    ["Itens Disponíveis", "Cadastrar Item Empréstimo", "Registrar Saída (Empréstimo)",
                     "Registrar Devolução", "Histórico de Movimentação", "Fazer Solicitação"],
                    key="ngi_emp_nav", horizontal=True, label_visibility="collapsed"
                )

                cursor = conn.cursor()

                # ---------------------------------------------------------------------
                # SUB-ABA 1: ITENS DISPONÍVEIS (PAINEL + EDITAR / EXCLUIR)
                # ---------------------------------------------------------------------
                if sub_emp == "Itens Disponíveis":
            
                    df_emp_itens = pd.read_sql_query("""
                SELECT 
                    id AS "ID",
                    codigo AS "Código", 
                    item AS "Item / Equipamento", 
                    quantidade_total AS "Qtd Total", 
                    quantidade_disponivel AS "Qtd Disponível",
                    (quantidade_total - quantidade_disponivel) AS "Emprestados",
                    observacao AS "Observações", NULL::bytea AS foto
                FROM emprestimo_itens ORDER BY codigo ASC;
            """, conn)

                    if df_emp_itens.empty:
                        st.info("Nenhum item cadastrado no catálogo exclusivo de empréstimos ainda.")
                    else:
                        renderizar_catalogo_emprestimos(df_emp_itens)

                        st.markdown("<hr style='margin: 25px 0 15px 0; opacity: 0.2;'>", unsafe_allow_html=True)
                        st.markdown("### Gerenciar material")

                        # Seleção do item
                        df_raw_emp = pd.read_sql_query("SELECT id, codigo, item, quantidade_total, quantidade_disponivel, observacao FROM emprestimo_itens ORDER BY codigo ASC;", conn)
                
                        if not df_raw_emp.empty:
                            alvo_emp = st.session_state.pop("ngi_emp_item_alvo", None)
                            if alvo_emp is not None:
                                indices_emp = df_raw_emp.index[df_raw_emp['id'] == alvo_emp].tolist()
                                if indices_emp:
                                    st.session_state.ngi_emp_edicao = indices_emp[0]
                            opcao_emp_sel = st.selectbox(
                                "Selecione o item para modificar ou excluir:",
                                df_raw_emp.index,
                                key="ngi_emp_edicao",
                                format_func=lambda x: f"{df_raw_emp.loc[x, 'item']} (Código: {df_raw_emp.loc[x, 'codigo'] or 'S/N'})"
                            )

                            id_emp_sel = int(df_raw_emp.loc[opcao_emp_sel, "id"])
                            cod_emp_sel = df_raw_emp.loc[opcao_emp_sel, "codigo"] or ""
                            nome_emp_sel = df_raw_emp.loc[opcao_emp_sel, "item"]
                            qtd_tot_sel = int(df_raw_emp.loc[opcao_emp_sel, "quantidade_total"])
                            qtd_disp_sel = int(df_raw_emp.loc[opcao_emp_sel, "quantidade_disponivel"])
                            obs_emp_sel = df_raw_emp.loc[opcao_emp_sel, "observacao"] or ""

                            col_ed_e1, col_ed_e2 = st.columns(2)
                            edit_cod_emp = col_ed_e1.text_input("Código / Patrimônio:", value=cod_emp_sel, key=f"ed_cod_emp_{id_emp_sel}")
                            edit_nome_emp = col_ed_e2.text_input("Nome do Item / Equipamento:", value=nome_emp_sel, key=f"ed_nome_emp_{id_emp_sel}")
                    
                            qtd_emprestados_atual = qtd_tot_sel - qtd_disp_sel
                            edit_qtd_tot = col_ed_e1.number_input("Quantidade Total em Acervo:", min_value=qtd_emprestados_atual, value=qtd_tot_sel, step=1, key=f"ed_qtd_tot_emp_{id_emp_sel}")
                    
                            if qtd_emprestados_atual > 0:
                                st.caption(f"Existem {qtd_emprestados_atual} unidade(s) emprestada(s) no momento. A quantidade total não pode ser menor que isso.")

                            edit_obs_emp = col_ed_e2.text_area("Observações / Descrição:", value=obs_emp_sel, key=f"ed_obs_emp_{id_emp_sel}")

                            nova_foto_emp = st.file_uploader("Foto do material (opcional, até 5 MB)", type=["png", "jpg", "jpeg"], key=f"ngi_emp_foto_{id_emp_sel}")
                            remover_foto_emp = st.checkbox("Remover foto atual", key=f"ngi_emp_sem_foto_{id_emp_sel}")
                            foto_emp_bytes = None
                            foto_emp_valida = True
                            if nova_foto_emp is not None:
                                try:
                                    foto_emp_bytes = foto_emprestimo_upload(nova_foto_emp)
                                except Exception:
                                    foto_emp_valida = False
                                    st.error("Selecione uma imagem PNG ou JPEG válida, com até 5 MB.")

                            col_btn_e1, col_btn_e2 = st.columns([1, 4])
                    
                            with col_btn_e1:
                                if st.button("Salvar Alterações", type="primary", key="btn_salvar_emp", disabled=not foto_emp_valida):
                                    if edit_nome_emp.strip():
                                        nova_qtd_disp = edit_qtd_tot - qtd_emprestados_atual
                                        try:
                                            cursor.execute("""
                                        UPDATE emprestimo_itens 
                                        SET codigo = %s, item = %s, quantidade_total = %s, quantidade_disponivel = %s, observacao = %s 
                                        WHERE id = %s;
                                    """, (edit_cod_emp.strip() if edit_cod_emp.strip() else None, edit_nome_emp.strip(), edit_qtd_tot, nova_qtd_disp, edit_obs_emp.strip(), id_emp_sel))
                                            if foto_emp_bytes is not None:
                                                cursor.execute("UPDATE emprestimo_itens SET foto = %s WHERE id = %s;", (psycopg2.Binary(foto_emp_bytes), id_emp_sel))
                                            elif remover_foto_emp:
                                                cursor.execute("UPDATE emprestimo_itens SET foto = NULL WHERE id = %s;", (id_emp_sel,))
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

                        foto_cad_emp = st.file_uploader("Foto do material (opcional, até 5 MB)", type=["png", "jpg", "jpeg"], key="ngi_emp_foto_cadastro")
                        if st.form_submit_button("Cadastrar Item", type="primary"):
                            foto_cad_bytes = None
                            foto_cad_valida = True
                            try:
                                foto_cad_bytes = foto_emprestimo_upload(foto_cad_emp)
                            except Exception:
                                foto_cad_valida = False
                                st.error("Selecione uma imagem PNG ou JPEG válida, com até 5 MB.")
                            if item_emp.strip() and foto_cad_valida:
                                try:
                                    cursor.execute("""
                                INSERT INTO emprestimo_itens (codigo, item, quantidade_total, quantidade_disponivel, observacao, foto)
                                VALUES (%s, %s, %s, %s, %s, %s);
                            """, (cod_emp.strip() if cod_emp else None, item_emp.strip(), qtd_total, qtd_total, obs_emp.strip(), psycopg2.Binary(foto_cad_bytes) if foto_cad_bytes else None))
                                    conn.commit()
                                    st.success(f"Item '{item_emp}' cadastrado com sucesso para empréstimos!")
                                    st.rerun()
                                except psycopg2.IntegrityError:
                                    conn.rollback()
                                    st.error("Erro: Já existe um item de empréstimo com este mesmo Código/Patrimônio.")
                            elif not item_emp.strip():
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
                
                        cursor.execute("SELECT nome, email FROM usuarios ORDER BY nome ASC;")
                        usuarios_cadastrados = cursor.fetchall()
                        opcoes_usuarios = {f"{u[0]} ({u[1]})": (u[0], u[1]) for u in usuarios_cadastrados}

                        with st.form("form_registro_saida_emp", clear_on_submit=True):
                            alvo_saida_emp = st.session_state.pop("ngi_emp_item_alvo", None)
                            indice_saida_emp = next((i for i, valor in enumerate(opcoes_itens.values()) if valor[0] == alvo_saida_emp), 0)
                            item_selecionado_label = st.selectbox("Selecione o Item para Empréstimo*", list(opcoes_itens.keys()), index=indice_saida_emp)
                            item_id, item_nome, max_qtd = opcoes_itens[item_selecionado_label]

                            col_s1, col_s2 = st.columns(2)
                            qtd_saida = col_s1.number_input("Quantidade*", min_value=1, max_value=max_qtd, value=1, step=1)
                            pessoa_selecionada_label = col_s2.selectbox("Pessoa (Solicitante, já cadastrado no sistema)*", list(opcoes_usuarios.keys()) if opcoes_usuarios else ["Nenhum usuário cadastrado"])

                            lista_siglas_coord = dados_sob_demanda_ngi("coordenacoes")["Sigla"].tolist() if not dados_sob_demanda_ngi("coordenacoes").empty else ["GERAL"]
                            coord_pessoa = col_s1.selectbox("Coordenação*", lista_siglas_coord)
                    
                            data_retirada = col_s1.date_input("Data de Retirada*", value=date.today(), format="DD/MM/YYYY")
                            data_prevista = col_s2.date_input("Data Prevista para Devolução*", value=date.today(), format="DD/MM/YYYY")

                            if st.form_submit_button("Confirmar Empréstimo", type="primary"):
                                if opcoes_usuarios and pessoa_selecionada_label in opcoes_usuarios:
                                    nome_pessoa, email_pessoa_saida = opcoes_usuarios[pessoa_selecionada_label]
                                    if data_prevista < data_retirada:
                                        st.error("A data prevista de devolução não pode ser anterior à data de retirada!")
                                    else:
                                        cursor.execute("""
                                    INSERT INTO emprestimo_registros 
                                    (item_id, item_nome, quantidade, pessoa, coordenacao, data_retirada, data_prevista, status, email_pessoa)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'EMPRESTADO', %s);
                                """, (item_id, item_nome, qtd_saida, nome_pessoa, coord_pessoa, data_retirada, data_prevista, email_pessoa_saida))
                                
                                        cursor.execute("""
                                    UPDATE emprestimo_itens 
                                    SET quantidade_disponivel = quantidade_disponivel - %s 
                                    WHERE id = %s;
                                """, (qtd_saida, item_id))
                                
                                        conn.commit()
                                        st.success(f"Empréstimo registrado com sucesso para {nome_pessoa}!")
                                        st.rerun()
                                else:
                                    st.error("Nenhum usuário cadastrado disponível para seleção. Cadastre a pessoa em \"Cadastrar Usuário\" primeiro.")

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

                # ---------------------------------------------------------------------
                # SUB-ABA 6: FAZER SOLICITAÇÃO (ADMINISTRADOR SOLICITA PARA SI PRÓPRIO)
                # ---------------------------------------------------------------------
                elif sub_emp == "Fazer Solicitação":
                    st.subheader("Solicitar Empréstimo de Material")
                    st.caption("Sua solicitação seguirá o fluxo normal de aprovação, como qualquer outra.")
                    if st.session_state.pop("msg_sucesso_emprestimo_admin", False):
                        st.success("Sua solicitação foi encaminhada com sucesso!")

                    if "carrinho_emprestimo" not in st.session_state:
                        st.session_state.carrinho_emprestimo = []

                    df_todos_itens_emprestimo_admin = pd.read_sql_query("""
                SELECT ei.id, ei.codigo, ei.item, ei.quantidade_disponivel,
                       (SELECT MIN(er.data_prevista) FROM emprestimo_registros er WHERE er.item_id = ei.id AND er.status = 'EMPRESTADO') AS previsao_devolucao
                FROM emprestimo_itens ei
                ORDER BY ei.codigo ASC;
            """, conn)
                    lista_siglas_coord_admin = dados_sob_demanda_ngi("coordenacoes")["Sigla"].tolist() if not dados_sob_demanda_ngi("coordenacoes").empty else ["GERAL"]

                    if df_todos_itens_emprestimo_admin.empty:
                        st.info("Nenhum item cadastrado para empréstimo no momento.")
                    else:
                        def status_texto_emprestimo_admin(row):
                            if row["quantidade_disponivel"] > 0:
                                return f"Disponível ({row['quantidade_disponivel']})"
                            elif row["previsao_devolucao"] is not None:
                                return f"Em uso — devolução prevista: {row['previsao_devolucao'].strftime('%d/%m/%Y')}"
                            else:
                                return "Em uso"

                        def destacar_status_emprestimo_admin(val):
                            if val.startswith("Disponível"):
                                return 'background-color: #d4edda; color: #155724; font-weight: bold;'
                            elif val.startswith("Em uso"):
                                return 'background-color: #fff3cd; color: #856404; font-weight: bold;'
                            return ''

                        df_status_emp_admin = df_todos_itens_emprestimo_admin.copy()
                        df_status_emp_admin["Status"] = df_status_emp_admin.apply(status_texto_emprestimo_admin, axis=1)
                        df_status_emp_admin = df_status_emp_admin.rename(columns={"codigo": "Código", "item": "Item"})[["Código", "Item", "Status"]]
                        st.dataframe(df_status_emp_admin.style.map(destacar_status_emprestimo_admin, subset=['Status']), use_container_width=True, hide_index=True)
                        st.caption("Um item indisponível não aparece na lista de seleção abaixo — verifique aqui a previsão de devolução antes de planejar a retirada.")

                        with st.container(border=True):
                            cabecalho_pedido_ngi("Nova solicitação de empréstimo", "Siga os 4 passos. Todos os itens do carrinho seguem juntos em um único pedido.")
                            passo_pedido_ngi(1, "Informe o período e a coordenação")
                            col_dta1, col_dta2, col_dta3 = st.columns(3)
                            data_retirada_admin = col_dta1.date_input("Data de Retirada: *", value=date.today(), format="DD/MM/YYYY", key="data_retirada_admin")
                            data_prev_admin = col_dta2.date_input("Data de Devolução: *", value=date.today(), format="DD/MM/YYYY", key="data_prev_admin")
                            coord_sol_admin = col_dta3.selectbox("Coordenação:", lista_siglas_coord_admin, key="coord_carrinho_admin")

                            df_raw_emp_admin = df_todos_itens_emprestimo_admin[df_todos_itens_emprestimo_admin["quantidade_disponivel"] > 0].reset_index(drop=True)
                            passo_pedido_ngi(2, 'Escolha o item e clique em "Adicionar ao carrinho"')

                            if df_raw_emp_admin.empty:
                                st.warning("Nenhum item disponível para adicionar no momento — confira a previsão de devolução no catálogo acima.")
                            else:
                                col_add_a1, col_add_a2, col_add_a3 = st.columns([3, 1, 1.3])
                                opcao_sol_admin = col_add_a1.selectbox(
                                    "Item:",
                                    df_raw_emp_admin.index,
                                    format_func=lambda x: f"{df_raw_emp_admin.loc[x, 'item']} (Disponível: {df_raw_emp_admin.loc[x, 'quantidade_disponivel']})",
                                    key="select_emprestimo_admin"
                                )
                                qtd_sol_admin = col_add_a2.number_input("Quantidade:", min_value=1, max_value=int(df_raw_emp_admin.loc[opcao_sol_admin, "quantidade_disponivel"]), value=1, step=1, key="qtd_emprestimo_admin")
                                col_add_a3.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                                with col_add_a3:
                                    with st.container(key="btn_add_1"):
                                        clicou_add_1 = st.button("Adicionar ao carrinho", icon=":material/add_shopping_cart:", key="add_carrinho_admin", use_container_width=True)
                                if clicou_add_1:
                                    item_id_sel_admin = int(df_raw_emp_admin.loc[opcao_sol_admin, "id"])
                                    nome_sel_admin = df_raw_emp_admin.loc[opcao_sol_admin, "item"]
                                    adicionar_item_carrinho_ngi("carrinho_emprestimo", {"item_id": item_id_sel_admin, "item": nome_sel_admin, "quantidade": int(qtd_sol_admin)}, df_raw_emp_admin.loc[opcao_sol_admin, "quantidade_disponivel"])

                            if st.session_state.carrinho_emprestimo:
                                passo_pedido_ngi(3, "Confira o carrinho", detalhe=texto_qtd_itens_ngi(len(st.session_state.carrinho_emprestimo)))
                                renderizar_carrinho_ngi("carrinho_emprestimo", "1", mostrar_codigo=False)

                                passo_pedido_ngi(4, "Informe a atividade, aceite o termo e envie")
                                col_env_a1, col_env_a2 = st.columns([1, 1])
                                atividade_sol_admin = col_env_a1.text_input("Atividade Associada: *", placeholder="Ex: Vistoria de campo na trilha X", key="atividade_admin")
                                obs_sol_admin = col_env_a2.text_input("Observações (opcional):", key="obs_admin")

                                st.markdown("<hr style='margin: 20px 0 10px 0; opacity: 0.2;'>", unsafe_allow_html=True)
                                with st.expander("Termo de Responsabilidade - clique para ler", icon=":material/description:"):
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
                                aceite_termo_admin = st.checkbox("Li e concordo com o Termo de Responsabilidade pelo Empréstimo de Materiais. *", key="aceite_admin")

                                if st.button(f"Enviar solicitação ({texto_qtd_itens_ngi(len(st.session_state.carrinho_emprestimo))})", type="primary", icon=":material/send:", key="enviar_carrinho_admin"):
                                    if not atividade_sol_admin.strip():
                                        st.error("O campo 'Atividade Associada' é obrigatório!")
                                    elif data_prev_admin < data_retirada_admin:
                                        st.error("A Data de Devolução não pode ser anterior à Data de Retirada!")
                                    elif not aceite_termo_admin:
                                        st.error("A solicitação de empréstimo somente será efetivada após a leitura e aceitação do Termo de Responsabilidade!")
                                    else:
                                        try:
                                            lote_id_admin = str(uuid.uuid4())
                                            for item_carr_a in st.session_state.carrinho_emprestimo:
                                                cursor.execute("""
                                        INSERT INTO solicitacoes_almoxarifado 
                                        (tipo, referencia_codigo, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, data_retirada, data_prevista, atividade_associada, status, observacao, termo_aceito, data_aceite_termo, lote_id)
                                        VALUES ('EMPRESTIMO', %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDENTE', %s, TRUE, CURRENT_TIMESTAMP, %s);
                                    """, (str(item_carr_a["item_id"]), item_carr_a["item"], item_carr_a["quantidade"], st.session_state.NOME_USUARIO_LOGADO, st.session_state.EMAIL_USUARIO_LOGADO, coord_sol_admin, data_retirada_admin, data_prev_admin, atividade_sol_admin.strip(), obs_sol_admin.strip(), lote_id_admin))
                                            conn.commit()
                                            st.session_state.carrinho_emprestimo = []
                                            st.session_state["msg_sucesso_emprestimo_admin"] = True
                                            st.rerun()
                                        except Exception as ex_admin_sol:
                                            conn.rollback()
                                            st.error(f"Erro ao enviar solicitação: {ex_admin_sol}")
                            else:
                                carrinho_vazio_ngi("emprestimo_admin", campos=("Atividade Associada: *", "Observações (opcional):"), passo_carrinho=3)

            # =========================================================================
            # NOVO MÓDULO DE SOLICITAÇÃO — TELA (PERFIL USUÁRIO): MATERIAIS DISPONÍVEIS
            # =========================================================================
            elif escolha == "Materiais Disponíveis":
                st.markdown("""
            <div class="ngi-page-header" style="background: transparent; padding: 0 0 24px; margin-bottom: 8px;">
                <h1 style="color: #122820; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                    Materiais Disponíveis no Almoxarifado
                </h1>
                <p style="color: #6a7b73; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Consulte os itens em estoque e solicite a retirada de materiais
                </p>
            </div>
        """, unsafe_allow_html=True)

                if st.session_state.get("msg_sucesso_material"):
                    st.success("Sua solicitação foi encaminhada com sucesso!")
                    del st.session_state["msg_sucesso_material"]

                df_disp_material = dados_sob_demanda_ngi("produtos")[dados_sob_demanda_ngi("produtos")["Quantidade"] > 0].copy() if not dados_sob_demanda_ngi("produtos").empty else pd.DataFrame()

                if df_disp_material.empty:
                    st.info("Nenhum material disponível em estoque no momento.")
                else:
                    with st.container(border=True):
                        st.markdown('<div class="ngi-stock-heading"><h3>Estoque disponível</h3><p>Consulte os materiais. Para pedir, use a seção "Nova solicitação" logo abaixo.</p></div>', unsafe_allow_html=True)
                        lista_categorias_user = sorted(df_disp_material["Categoria"].dropna().unique().tolist())
                        col_filtro_u1, col_filtro_u2 = st.columns([2, 1])
                        termo_busca_user = col_filtro_u1.text_input("Buscar por Nome do Material ou Código:", placeholder="Digite o termo para pesquisar...", key="busca_material_user")
                        categoria_selecionada_user = col_filtro_u2.selectbox("Filtrar por Categoria:", ["Todas"] + lista_categorias_user, key="categoria_material_user")

                        df_disp_material_filtrado = df_disp_material.copy()
                        if termo_busca_user:
                            df_disp_material_filtrado = df_disp_material_filtrado[
                                df_disp_material_filtrado['Item'].str.contains(termo_busca_user, case=False, na=False, regex=False) |
                                df_disp_material_filtrado['Código'].str.contains(termo_busca_user, case=False, na=False, regex=False)
                            ]
                        if categoria_selecionada_user != "Todas":
                            df_disp_material_filtrado = df_disp_material_filtrado[df_disp_material_filtrado['Categoria'] == categoria_selecionada_user]

                        if df_disp_material_filtrado.empty:
                            st.info("Nenhum material encontrado com os filtros aplicados.")
                        else:
                            st.dataframe(df_disp_material_filtrado.drop(columns=["Valor Unitário"]), use_container_width=True, hide_index=True, height=min(36 * (len(df_disp_material_filtrado) + 1) + 3, 290))

                    if "carrinho_material" not in st.session_state:
                        st.session_state.carrinho_material = []

                    # Mesma lista já carregada acima (antes era uma segunda consulta ao banco).
                    df_raw_prod_user = df_disp_material.rename(columns={"Código": "codigo", "Item": "item", "Quantidade": "quantidade"})[["codigo", "item", "quantidade"]].sort_values("codigo").reset_index(drop=True)
                    lista_siglas_coord_user = dados_sob_demanda_ngi("coordenacoes")["Sigla"].tolist() if not dados_sob_demanda_ngi("coordenacoes").empty else ["GERAL"]

                    with st.container(border=True):
                        cabecalho_pedido_ngi("Nova solicitação", "Siga os 3 passos. Todos os itens do carrinho seguem juntos em um único pedido.")
                        passo_pedido_ngi(1, 'Escolha o material e clique em "Adicionar ao carrinho"')
                        col_add_m1, col_add_m2, col_add_m3 = st.columns([3, 1, 1.3])
                        opcao_sol_mat = col_add_m1.selectbox(
                            "Material:",
                            df_raw_prod_user.index,
                            format_func=lambda x: f"{df_raw_prod_user.loc[x, 'codigo']} - {df_raw_prod_user.loc[x, 'item']} (Saldo: {df_raw_prod_user.loc[x, 'quantidade']})",
                            key="select_material_carrinho"
                        )
                        qtd_sol_mat = col_add_m2.number_input("Quantidade:", min_value=1, max_value=int(df_raw_prod_user.loc[opcao_sol_mat, "quantidade"]), value=1, step=1, key="qtd_material_carrinho")
                        col_add_m3.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                        with col_add_m3:
                            with st.container(key="btn_add_2"):
                                clicou_add_2 = st.button("Adicionar ao carrinho", icon=":material/add_shopping_cart:", key="add_carrinho_material", use_container_width=True)
                        if clicou_add_2:
                            adicionar_item_carrinho_ngi("carrinho_material", {"codigo": df_raw_prod_user.loc[opcao_sol_mat, "codigo"], "item": df_raw_prod_user.loc[opcao_sol_mat, "item"], "quantidade": int(qtd_sol_mat)}, df_raw_prod_user.loc[opcao_sol_mat, "quantidade"])

                        if st.session_state.carrinho_material:
                            passo_pedido_ngi(2, "Confira o carrinho", detalhe=texto_qtd_itens_ngi(len(st.session_state.carrinho_material)))
                            renderizar_carrinho_ngi("carrinho_material", "2")

                            passo_pedido_ngi(3, "Informe a coordenação e envie")
                            col_env_m1, col_env_m2 = st.columns([1, 2])
                            coord_sol_mat = col_env_m1.selectbox("Coordenação:", lista_siglas_coord_user, key="coord_carrinho_material")
                            obs_sol_mat = col_env_m2.text_input("Observações (opcional):", placeholder="Ex.: retirar na quinta pela manhã", key="obs_carrinho_material")

                            if st.button(f"Enviar solicitação ({texto_qtd_itens_ngi(len(st.session_state.carrinho_material))})", type="primary", icon=":material/send:", key="enviar_carrinho_material"):
                                try:
                                    lote_id_novo = str(uuid.uuid4())
                                    cursor = conn.cursor()
                                    for item_carr in st.session_state.carrinho_material:
                                        cursor.execute("""
                                    INSERT INTO solicitacoes_almoxarifado 
                                    (tipo, referencia_codigo, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, status, observacao, lote_id)
                                    VALUES ('MATERIAL', %s, %s, %s, %s, %s, %s, 'PENDENTE', %s, %s);
                                """, (item_carr["codigo"], item_carr["item"], item_carr["quantidade"], st.session_state.NOME_USUARIO_LOGADO, st.session_state.EMAIL_USUARIO_LOGADO, coord_sol_mat, obs_sol_mat.strip(), lote_id_novo))
                                    conn.commit()
                                    st.session_state.carrinho_material = []
                                    st.session_state["msg_sucesso_material"] = True
                                    st.rerun()
                                except Exception as ex:
                                    conn.rollback()
                                    st.error(f"Erro ao enviar solicitação: {ex}")
                        else:
                            carrinho_vazio_ngi("material")

            # =========================================================================
            # NOVO MÓDULO: MATERIAIS BRIGADA — GESTÃO (ADMINISTRADOR)
            # =========================================================================
            elif escolha == "Materiais Brigada" and st.session_state.PERFIL_USUARIO_LOGADO != "Usuário Comum":
                renderizar_banner("Materiais Brigada", "Estoque próprio da Brigada, separado do almoxarifado geral")
                aba_brigada_admin = option_menu(
                    menu_title=None,
                    options=["Itens Disponíveis", "Cadastrar Item", "Gerenciar Categorias", "Registro de Entrada", "Registro de Saída", "Histórico de Movimentação", "Editar / Excluir Item"],
                    icons=["box-seam", "plus-circle", "tags", "arrow-down-circle", "arrow-up-circle", "journal-text", "pencil-square"],
                    orientation="horizontal",
                    styles=ESTILO_MENU_HORIZONTAL
                )

                df_raw_brig = pd.read_sql_query("SELECT * FROM produtos_brigada ORDER BY codigo ASC;", conn)
                lista_siglas_coord_brig = dados_sob_demanda_ngi("coordenacoes")["Sigla"].tolist() if not dados_sob_demanda_ngi("coordenacoes").empty else ["GERAL"]

                # ---------------------------------------------------------------
                # ABA 1: ITENS DISPONÍVEIS
                # ---------------------------------------------------------------
                if aba_brigada_admin == "Itens Disponíveis":
                    if df_raw_brig.empty:
                        st.info("Nenhum material cadastrado no estoque da Brigada ainda.")
                    else:
                        df_display_brig = df_raw_brig.rename(columns={"codigo": "Código", "item": "Item", "quantidade": "Quantidade", "categoria": "Categoria", "valor_unitario": "Valor Unitário"})
                        df_display_brig["Valor Unitário"] = df_display_brig["Valor Unitário"].map("R$ {:.2f}".format)
                        st.dataframe(df_display_brig, use_container_width=True, hide_index=True)

                # ---------------------------------------------------------------
                # ABA 2: CADASTRAR ITEM
                # ---------------------------------------------------------------
                elif aba_brigada_admin == "Cadastrar Item":
                    df_cat_brigada = pd.read_sql_query("SELECT nome FROM categorias_brigada ORDER BY nome ASC;", conn)
                    lista_categorias_brigada = df_cat_brigada["nome"].tolist()

                    with st.form("form_novo_produto_brigada", clear_on_submit=True):
                        col_ba, col_bb = st.columns(2)
                        cod_brig = col_ba.text_input("Código")
                        nome_it_brig = col_bb.text_input("Nome do Material")
                        cat_it_brig = col_ba.selectbox("Categoria", lista_categorias_brigada if lista_categorias_brigada else ["Nenhuma categoria cadastrada"])
                        val_unit_brig = col_bb.number_input("Valor Unitário (R$)", min_value=0.0, step=0.01, format="%.2f")
                        qtd_inicial_brig = st.number_input("Quantidade Inicial:", min_value=0, value=0, step=1)

                        if st.form_submit_button("Finalizar Cadastro", type="primary"):
                            if cod_brig and nome_it_brig:
                                try:
                                    cursor = conn.cursor()
                                    cursor.execute("INSERT INTO produtos_brigada VALUES (%s, %s, %s, %s, %s);", (cod_brig.strip(), nome_it_brig.strip(), int(qtd_inicial_brig), cat_it_brig, float(val_unit_brig)))
                                    conn.commit()
                                    st.success(f"Sucesso! {nome_it_brig} adicionado ao estoque da Brigada.")
                                    st.rerun()
                                except psycopg2.IntegrityError:
                                    conn.rollback()
                                    st.error(f"Erro! Código {cod_brig} já existe.")
                            else:
                                st.error("Preencha ao menos o Código e o Nome do Material!")

                # ---------------------------------------------------------------
                # ABA 3: GERENCIAR CATEGORIAS
                # ---------------------------------------------------------------
                elif aba_brigada_admin == "Gerenciar Categorias":
                    df_cat_brigada_aba = pd.read_sql_query("SELECT nome FROM categorias_brigada ORDER BY nome ASC;", conn)
                    lista_categorias_brigada_aba = df_cat_brigada_aba["nome"].tolist()

                    st.markdown("### Categorias atuais")
                    if lista_categorias_brigada_aba:
                        st.dataframe(
                            df_cat_brigada_aba.rename(columns={"nome": "Categoria"}),
                            use_container_width=True, hide_index=True,
                            height=min(450, max(120, 38 * (len(lista_categorias_brigada_aba) + 1))),
                        )
                        with st.expander("Excluir uma categoria"):
                            cat_existente_brig = st.selectbox("Categoria para excluir:", lista_categorias_brigada_aba, key="cat_brigada_excluir_visual")
                            if st.button("Excluir categoria selecionada", key=f"del_cat_brig_{cat_existente_brig}"):
                                cursor = conn.cursor()
                                cursor.execute("DELETE FROM categorias_brigada WHERE nome = %s;", (cat_existente_brig,))
                                conn.commit()
                                st.rerun()
                    else:
                        st.info("Nenhuma categoria cadastrada ainda.")

                    st.markdown("### Adicionar categoria")
                    nova_cat_brig = st.text_input("Nova categoria:", placeholder="Ex: EPI, Combate a Incêndio, Primeiros Socorros", key="nova_cat_brigada")
                    with st.container(key="btn_add_3"):
                        clicou_add_cat_brig = st.button("Adicionar Categoria", key="add_cat_brigada")
                    if clicou_add_cat_brig:
                        if nova_cat_brig and nova_cat_brig.strip():
                            try:
                                cursor = conn.cursor()
                                cursor.execute("INSERT INTO categorias_brigada VALUES (%s);", (nova_cat_brig.strip(),))
                                conn.commit()
                                st.success("Categoria adicionada!")
                                st.rerun()
                            except psycopg2.IntegrityError:
                                conn.rollback()
                                st.error("Esta categoria já existe.")

                # ---------------------------------------------------------------
                # ABA 4: REGISTRO DE ENTRADA
                # ---------------------------------------------------------------
                elif aba_brigada_admin == "Registro de Entrada":
                    if df_raw_brig.empty:
                        st.warning("Nenhum material cadastrado para movimentar.")
                    else:
                        with st.form("form_entrada_brigada", clear_on_submit=True):
                            col_be1, col_be2 = st.columns(2)
                            data_mov_brig = col_be1.date_input("Data da Movimentação:", value=datetime.today(), format="DD/MM/YYYY").strftime("%Y-%m-%d")
                            opcao_prod_brig_ent = col_be2.selectbox(
                                "Selecione o Material:",
                                df_raw_brig.index,
                                format_func=lambda x: f"{df_raw_brig.loc[x, 'codigo']} - {df_raw_brig.loc[x, 'item']} (Saldo: {df_raw_brig.loc[x, 'quantidade']})"
                            )
                            qtd_mov_brig_ent = col_be1.number_input("Quantidade:", min_value=1, step=1, value=1)

                            if st.form_submit_button("Registrar Entrada", type="primary"):
                                prod_codigo_brig = df_raw_brig.loc[opcao_prod_brig_ent, "codigo"]
                                prod_nome_brig = df_raw_brig.loc[opcao_prod_brig_ent, "item"]
                                nova_qtd_brig = int(df_raw_brig.loc[opcao_prod_brig_ent, "quantidade"]) + qtd_mov_brig_ent
                                try:
                                    cursor = conn.cursor()
                                    cursor.execute("UPDATE produtos_brigada SET quantidade = %s WHERE codigo = %s;", (nova_qtd_brig, prod_codigo_brig))
                                    cursor.execute("""
                                INSERT INTO movimentacoes_brigada (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
                                VALUES (%s, %s, %s, %s, %s, %s, %s);
                            """, (data_mov_brig, "Entrada", prod_codigo_brig, prod_nome_brig, qtd_mov_brig_ent, st.session_state.NOME_USUARIO_LOGADO, "Brigada"))
                                    conn.commit()
                                    st.success(f"Entrada de {qtd_mov_brig_ent} un. de '{prod_nome_brig}' registrada! Novo saldo: {nova_qtd_brig}.")
                                    st.rerun()
                                except Exception as ex_ent_brig:
                                    conn.rollback()
                                    st.error(f"Erro ao salvar entrada: {ex_ent_brig}")

                # ---------------------------------------------------------------
                # ABA 5: REGISTRO DE SAÍDA
                # ---------------------------------------------------------------
                elif aba_brigada_admin == "Registro de Saída":
                    if df_raw_brig.empty:
                        st.warning("Nenhum material cadastrado para movimentar.")
                    else:
                        with st.form("form_saida_brigada", clear_on_submit=True):
                            col_bs1, col_bs2 = st.columns(2)
                            data_mov_brig_s = col_bs1.date_input("Data da Movimentação:", value=datetime.today(), format="DD/MM/YYYY").strftime("%Y-%m-%d")
                            opcao_prod_brig_sai = col_bs2.selectbox(
                                "Selecione o Material:",
                                df_raw_brig.index,
                                format_func=lambda x: f"{df_raw_brig.loc[x, 'codigo']} - {df_raw_brig.loc[x, 'item']} (Saldo: {df_raw_brig.loc[x, 'quantidade']})",
                                key="select_saida_brigada"
                            )
                            qtd_mov_brig_sai = col_bs1.number_input("Quantidade da Movimentação:", min_value=1, step=1, value=1)
                            resp_mov_brig = col_bs2.text_input("Nome da Pessoa Responsável pela Retirada:")
                            coord_mov_brig = col_bs1.selectbox("Coordenação Destino:", lista_siglas_coord_brig)

                            if st.form_submit_button("Registrar Saída", type="primary"):
                                if not resp_mov_brig.strip():
                                    st.error("Por favor, digite o nome da pessoa responsável pela retirada.")
                                else:
                                    prod_codigo_brig_s = df_raw_brig.loc[opcao_prod_brig_sai, "codigo"]
                                    prod_nome_brig_s = df_raw_brig.loc[opcao_prod_brig_sai, "item"]
                                    prod_qtd_atual_brig = int(df_raw_brig.loc[opcao_prod_brig_sai, "quantidade"])

                                    if prod_qtd_atual_brig >= qtd_mov_brig_sai:
                                        nova_qtd_brig_s = prod_qtd_atual_brig - qtd_mov_brig_sai
                                        try:
                                            cursor = conn.cursor()
                                            cursor.execute("UPDATE produtos_brigada SET quantidade = %s WHERE codigo = %s;", (nova_qtd_brig_s, prod_codigo_brig_s))
                                            cursor.execute("""
                                        INSERT INTO movimentacoes_brigada (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                                    """, (data_mov_brig_s, "Saída", prod_codigo_brig_s, prod_nome_brig_s, qtd_mov_brig_sai, resp_mov_brig.strip(), coord_mov_brig))
                                            conn.commit()
                                            st.success(f"Saída de {qtd_mov_brig_sai} un. de '{prod_nome_brig_s}' registrada! Novo saldo: {nova_qtd_brig_s}.")
                                            st.rerun()
                                        except Exception as ex_sai_brig:
                                            conn.rollback()
                                            st.error(f"Erro ao salvar saída: {ex_sai_brig}")
                                    else:
                                        st.error(f"Saldo Insuficiente! O material possui apenas {prod_qtd_atual_brig} unidades no estoque.")

                # ---------------------------------------------------------------
                # ABA 6: HISTÓRICO DE MOVIMENTAÇÃO
                # ---------------------------------------------------------------
                elif aba_brigada_admin == "Histórico de Movimentação":
                    df_mov_brig = pd.read_sql_query("SELECT data AS Data, tipo AS Tipo, codigo AS Código, item AS Item, quantidade AS Quantidade, responsavel AS Responsável, coordenacao AS Coordenação FROM movimentacoes_brigada ORDER BY id DESC;", conn)
                    if df_mov_brig.empty:
                        st.info("Nenhuma movimentação registrada até o momento.")
                    else:
                        st.dataframe(df_mov_brig, use_container_width=True, hide_index=True)

                # ---------------------------------------------------------------
                # ABA 7: EDITAR / EXCLUIR ITEM
                # ---------------------------------------------------------------
                elif aba_brigada_admin == "Editar / Excluir Item":
                    if df_raw_brig.empty:
                        st.info("Nenhum material cadastrado no estoque da Brigada ainda.")
                    else:
                        opcao_brig_edit = st.selectbox("Selecione para modificar:", df_raw_brig.index, format_func=lambda x: f"{df_raw_brig.loc[x, 'codigo']} - {df_raw_brig.loc[x, 'item']}")
                        cod_atual_brig = df_raw_brig.loc[opcao_brig_edit, "codigo"]

                        col_edb1, col_edb2 = st.columns(2)
                        edit_cod_brig = col_edb1.text_input("Código:", value=df_raw_brig.loc[opcao_brig_edit, "codigo"])
                        edit_item_brig = col_edb2.text_input("Nome:", value=df_raw_brig.loc[opcao_brig_edit, "item"])
                        edit_qtd_brig = col_edb1.number_input("Quantidade (Ajuste):", min_value=0, value=int(df_raw_brig.loc[opcao_brig_edit, "quantidade"]))
                        df_cat_brigada_edit = pd.read_sql_query("SELECT nome FROM categorias_brigada ORDER BY nome ASC;", conn)
                        lista_categorias_brigada_edit = df_cat_brigada_edit["nome"].tolist()
                        cat_atual_brig_edit = df_raw_brig.loc[opcao_brig_edit, "categoria"]
                        if cat_atual_brig_edit and cat_atual_brig_edit not in lista_categorias_brigada_edit:
                            lista_categorias_brigada_edit = [cat_atual_brig_edit] + lista_categorias_brigada_edit
                        idx_cat_brig_edit = lista_categorias_brigada_edit.index(cat_atual_brig_edit) if cat_atual_brig_edit in lista_categorias_brigada_edit else 0
                        edit_cat_brig = col_edb2.selectbox("Categoria:", lista_categorias_brigada_edit if lista_categorias_brigada_edit else ["Nenhuma categoria cadastrada"], index=idx_cat_brig_edit)
                        edit_val_brig = st.number_input("Valor Unitário:", min_value=0.0, step=0.01, format="%.2f", value=float(df_raw_brig.loc[opcao_brig_edit, "valor_unitario"] or 0))

                        col_bbtn1, col_bbtn2 = st.columns([1, 4])
                        with col_bbtn1:
                            if st.button("Salvar Alterações", type="primary"):
                                cursor = conn.cursor()
                                cursor.execute("""
                            UPDATE produtos_brigada 
                            SET codigo = %s, item = %s, quantidade = %s, categoria = %s, valor_unitario = %s 
                            WHERE codigo = %s;
                        """, (edit_cod_brig.strip(), edit_item_brig.strip(), edit_qtd_brig, edit_cat_brig.strip(), float(edit_val_brig), cod_atual_brig))
                                conn.commit()
                                st.success("Modificado com sucesso!")
                                st.rerun()

                        with col_bbtn2:
                            if st.button("Excluir Produto"):
                                cursor = conn.cursor()
                                cursor.execute("DELETE FROM produtos_brigada WHERE codigo = %s;", (cod_atual_brig,))
                                conn.commit()
                                st.warning("Removido com sucesso.")
                                st.rerun()

            # =========================================================================
            # NOVO MÓDULO: MATERIAIS BRIGADA — SOLICITAÇÃO (USUÁRIO DA COORDENAÇÃO BRIGADA)
            # =========================================================================
            elif escolha == "Materiais Brigada" and st.session_state.PERFIL_USUARIO_LOGADO == "Usuário Comum":
                if (st.session_state.get("COORDENACAO_USUARIO_LOGADO") or "").strip().upper() != "BRIGADA":
                    st.error("Acesso restrito à coordenação Brigada.")
                else:
                    renderizar_banner("Materiais Brigada", "Estoque próprio da Brigada, separado do almoxarifado geral")

                    if st.session_state.get("msg_sucesso_brigada"):
                        st.success("Sua solicitação foi encaminhada com sucesso!")
                        del st.session_state["msg_sucesso_brigada"]

                    df_disp_brigada = pd.read_sql_query("SELECT codigo, item, quantidade, categoria, valor_unitario FROM produtos_brigada WHERE quantidade > 0 ORDER BY codigo ASC;", conn)

                    if df_disp_brigada.empty:
                        st.info("Nenhum material disponível no estoque da Brigada no momento.")
                    else:
                        st.markdown('<h3 style="font-size: 18px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center;"><span style="display: inline-block; width: 6px; height: 18px; background-color: #147746; margin-right: 8px; border-radius: 2px;"></span>Filtros de Consulta</h3>', unsafe_allow_html=True)

                        termo_busca_brig = st.text_input("Buscar por Nome do Material ou Código:", placeholder="Digite o termo para pesquisar...", key="busca_material_brigada")
                        df_disp_brigada_filtrado = df_disp_brigada.copy()
                        if termo_busca_brig:
                            df_disp_brigada_filtrado = df_disp_brigada_filtrado[
                                df_disp_brigada_filtrado['item'].str.contains(termo_busca_brig, case=False, na=False) |
                                df_disp_brigada_filtrado['codigo'].str.contains(termo_busca_brig, case=False, na=False)
                            ]

                        st.markdown("<br>", unsafe_allow_html=True)
                        st.dataframe(df_disp_brigada_filtrado.rename(columns={"codigo": "Código", "item": "Item", "quantidade": "Quantidade", "categoria": "Categoria"}).drop(columns=["valor_unitario"]), use_container_width=True, hide_index=True)

                        if "carrinho_brigada" not in st.session_state:
                            st.session_state.carrinho_brigada = []

                        with st.container(border=True):
                            cabecalho_pedido_ngi("Nova solicitação de material da Brigada", "Siga os 3 passos. Todos os itens do carrinho seguem juntos em um único pedido.")
                            passo_pedido_ngi(1, 'Escolha o material e clique em "Adicionar ao carrinho"')

                            col_add_br1, col_add_br2, col_add_br3 = st.columns([3, 1, 1.3])
                            opcao_sol_brig = col_add_br1.selectbox(
                                "Material:",
                                df_disp_brigada.index,
                                format_func=lambda x: f"{df_disp_brigada.loc[x, 'codigo']} - {df_disp_brigada.loc[x, 'item']} (Saldo: {df_disp_brigada.loc[x, 'quantidade']})",
                                key="select_material_brigada"
                            )
                            qtd_sol_brig = col_add_br2.number_input("Quantidade:", min_value=1, max_value=int(df_disp_brigada.loc[opcao_sol_brig, "quantidade"]), value=1, step=1, key="qtd_material_brigada")
                            col_add_br3.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                            with col_add_br3:
                                with st.container(key="btn_add_4"):
                                    clicou_add_4 = st.button("Adicionar ao carrinho", icon=":material/add_shopping_cart:", key="add_carrinho_brigada", use_container_width=True)
                            if clicou_add_4:
                                cod_sel_brig = df_disp_brigada.loc[opcao_sol_brig, "codigo"]
                                nome_sel_brig = df_disp_brigada.loc[opcao_sol_brig, "item"]
                                adicionar_item_carrinho_ngi("carrinho_brigada", {"codigo": cod_sel_brig, "item": nome_sel_brig, "quantidade": int(qtd_sol_brig)}, df_disp_brigada.loc[opcao_sol_brig, "quantidade"])

                            if st.session_state.carrinho_brigada:
                                passo_pedido_ngi(2, "Confira o carrinho", detalhe=texto_qtd_itens_ngi(len(st.session_state.carrinho_brigada)))
                                renderizar_carrinho_ngi("carrinho_brigada", "3")

                                passo_pedido_ngi(3, "Adicione uma observação, se precisar, e envie")
                                obs_sol_brig = st.text_input("Observações (opcional):", placeholder="Ex.: material para a operação de sábado", key="obs_carrinho_brigada")

                                if st.button(f"Enviar solicitação ({texto_qtd_itens_ngi(len(st.session_state.carrinho_brigada))})", type="primary", icon=":material/send:", key="enviar_carrinho_brigada"):
                                    try:
                                        lote_id_brig = str(uuid.uuid4())
                                        cursor = conn.cursor()
                                        for item_carr_br in st.session_state.carrinho_brigada:
                                            cursor.execute("""
                                    INSERT INTO solicitacoes_almoxarifado 
                                    (tipo, referencia_codigo, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, status, observacao, lote_id, origem_estoque)
                                    VALUES ('MATERIAL', %s, %s, %s, %s, %s, 'Brigada', 'PENDENTE', %s, %s, 'BRIGADA');
                                """, (item_carr_br["codigo"], item_carr_br["item"], item_carr_br["quantidade"], st.session_state.NOME_USUARIO_LOGADO, st.session_state.EMAIL_USUARIO_LOGADO, obs_sol_brig.strip(), lote_id_brig))
                                        conn.commit()
                                        st.session_state.carrinho_brigada = []
                                        st.session_state["msg_sucesso_brigada"] = True
                                        st.rerun()
                                    except Exception as ex_brig:
                                        conn.rollback()
                                        st.error(f"Erro ao enviar solicitação: {ex_brig}")
                            else:
                                carrinho_vazio_ngi("brigada", campos=("Observações (opcional):",))

            # =========================================================================
            # NOVO MÓDULO: LIVROS E PRODUTOS — GESTÃO (ADMINISTRADOR)
            # =========================================================================
            elif escolha == "Livros e Produtos" and st.session_state.PERFIL_USUARIO_LOGADO != "Usuário Comum":
                renderizar_banner("Livros e Produtos", "Catálogo de livros e livretos disponíveis, com foto de referência")
                df_raw_livros = pd.read_sql_query("SELECT codigo, titulo, tipo, quantidade, NULL::bytea AS foto FROM produtos_livros ORDER BY titulo ASC;", conn)
                renderizar_indicadores_acervo_ngi(df_raw_livros)

                aba_livros_admin = option_menu(
                    menu_title=None,
                    options=["Itens Disponíveis", "Cadastrar Item", "Registro de Entrada", "Registro de Saída", "Histórico de Movimentação", "Editar / Excluir Item"],
                    icons=["images", "plus-circle", "arrow-down-circle", "arrow-up-circle", "journal-text", "pencil-square"],
                    orientation="horizontal",
                    styles=ESTILO_MENU_HORIZONTAL
                )

                lista_siglas_coord_livros = dados_sob_demanda_ngi("coordenacoes")["Sigla"].tolist() if not dados_sob_demanda_ngi("coordenacoes").empty else ["GERAL"]

                # ---------------------------------------------------------------
                # ABA 1: ITENS DISPONÍVEIS (GRADE COM FOTOS)
                # ---------------------------------------------------------------
                if aba_livros_admin == "Itens Disponíveis":
                    if df_raw_livros.empty:
                        st.info("Nenhum livro ou produto cadastrado ainda.")
                    else:
                        renderizar_catalogo_visual_ngi(df_raw_livros)

                # ---------------------------------------------------------------
                # ABA 2: CADASTRAR ITEM (FOTO OBRIGATÓRIA)
                # ---------------------------------------------------------------
                elif aba_livros_admin == "Cadastrar Item":
                    with st.form("form_novo_livro", clear_on_submit=True):
                        col_lv1, col_lv2 = st.columns(2)
                        cod_livro = col_lv1.text_input("Código")
                        titulo_livro = col_lv2.text_input("Título do Livro/Livreto")
                        tipo_livro = col_lv1.selectbox("Tipo:", ["Livro", "Livreto"])
                        qtd_inicial_livro = col_lv2.number_input("Quantidade Inicial:", min_value=0, value=0, step=1)
                        foto_livro = st.file_uploader("Foto de Referência: *", type=["png", "jpg", "jpeg"], help="Obrigatório - anexe uma foto do livro/livreto.")

                        if st.form_submit_button("Finalizar Cadastro", type="primary"):
                            if not (cod_livro and titulo_livro):
                                st.error("Preencha ao menos o Código e o Título!")
                            elif foto_livro is None:
                                st.error("A foto de referência é obrigatória para cadastrar um item.")
                            else:
                                try:
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        "INSERT INTO produtos_livros (codigo, titulo, tipo, quantidade, foto) VALUES (%s, %s, %s, %s, %s);",
                                        (cod_livro.strip(), titulo_livro.strip(), tipo_livro, int(qtd_inicial_livro), psycopg2.Binary(foto_livro.getvalue()))
                                    )
                                    conn.commit()
                                    st.success(f"Sucesso! '{titulo_livro}' adicionado ao catálogo.")
                                    st.rerun()
                                except psycopg2.IntegrityError:
                                    conn.rollback()
                                    st.error(f"Erro! Código {cod_livro} já existe.")

                # ---------------------------------------------------------------
                # ABA 3: REGISTRO DE ENTRADA
                # ---------------------------------------------------------------
                elif aba_livros_admin == "Registro de Entrada":
                    if df_raw_livros.empty:
                        st.warning("Nenhum item cadastrado para movimentar.")
                    else:
                        with st.form("form_entrada_livros", clear_on_submit=True):
                            col_le1, col_le2 = st.columns(2)
                            data_mov_livro = col_le1.date_input("Data da Movimentação:", value=datetime.today(), format="DD/MM/YYYY").strftime("%Y-%m-%d")
                            opcao_livro_ent = col_le2.selectbox(
                                "Selecione o Item:",
                                df_raw_livros.index,
                                format_func=lambda x: f"{df_raw_livros.loc[x, 'codigo']} - {df_raw_livros.loc[x, 'titulo']} (Saldo: {df_raw_livros.loc[x, 'quantidade']})"
                            )
                            qtd_mov_livro_ent = col_le1.number_input("Quantidade:", min_value=1, step=1, value=1)

                            if st.form_submit_button("Registrar Entrada", type="primary"):
                                cod_livro_ent = df_raw_livros.loc[opcao_livro_ent, "codigo"]
                                titulo_livro_ent = df_raw_livros.loc[opcao_livro_ent, "titulo"]
                                nova_qtd_livro = int(df_raw_livros.loc[opcao_livro_ent, "quantidade"]) + qtd_mov_livro_ent
                                try:
                                    cursor = conn.cursor()
                                    cursor.execute("UPDATE produtos_livros SET quantidade = %s WHERE codigo = %s;", (nova_qtd_livro, cod_livro_ent))
                                    cursor.execute("""
                                INSERT INTO movimentacoes_livros (data, tipo, codigo, titulo, quantidade, responsavel, coordenacao)
                                VALUES (%s, %s, %s, %s, %s, %s, %s);
                            """, (data_mov_livro, "Entrada", cod_livro_ent, titulo_livro_ent, qtd_mov_livro_ent, st.session_state.NOME_USUARIO_LOGADO, "-"))
                                    conn.commit()
                                    st.success(f"Entrada de {qtd_mov_livro_ent} un. de '{titulo_livro_ent}' registrada! Novo saldo: {nova_qtd_livro}.")
                                    st.rerun()
                                except Exception as ex_ent_livro:
                                    conn.rollback()
                                    st.error(f"Erro ao salvar entrada: {ex_ent_livro}")

                # ---------------------------------------------------------------
                # ABA 4: REGISTRO DE SAÍDA
                # ---------------------------------------------------------------
                elif aba_livros_admin == "Registro de Saída":
                    if df_raw_livros.empty:
                        st.warning("Nenhum item cadastrado para movimentar.")
                    else:
                        with st.form("form_saida_livros", clear_on_submit=True):
                            col_ls1, col_ls2 = st.columns(2)
                            data_mov_livro_s = col_ls1.date_input("Data da Movimentação:", value=datetime.today(), format="DD/MM/YYYY").strftime("%Y-%m-%d")
                            opcao_livro_sai = col_ls2.selectbox(
                                "Selecione o Item:",
                                df_raw_livros.index,
                                format_func=lambda x: f"{df_raw_livros.loc[x, 'codigo']} - {df_raw_livros.loc[x, 'titulo']} (Saldo: {df_raw_livros.loc[x, 'quantidade']})",
                                key="select_saida_livros"
                            )
                            qtd_mov_livro_sai = col_ls1.number_input("Quantidade da Movimentação:", min_value=1, step=1, value=1)
                            resp_mov_livro = col_ls2.text_input("Nome da Pessoa Responsável pela Retirada:")
                            coord_mov_livro = col_ls1.selectbox("Coordenação Destino:", lista_siglas_coord_livros)

                            if st.form_submit_button("Registrar Saída", type="primary"):
                                if not resp_mov_livro.strip():
                                    st.error("Por favor, digite o nome da pessoa responsável pela retirada.")
                                else:
                                    cod_livro_sai = df_raw_livros.loc[opcao_livro_sai, "codigo"]
                                    titulo_livro_sai = df_raw_livros.loc[opcao_livro_sai, "titulo"]
                                    qtd_atual_livro = int(df_raw_livros.loc[opcao_livro_sai, "quantidade"])

                                    if qtd_atual_livro >= qtd_mov_livro_sai:
                                        nova_qtd_livro_s = qtd_atual_livro - qtd_mov_livro_sai
                                        try:
                                            cursor = conn.cursor()
                                            cursor.execute("UPDATE produtos_livros SET quantidade = %s WHERE codigo = %s;", (nova_qtd_livro_s, cod_livro_sai))
                                            cursor.execute("""
                                        INSERT INTO movimentacoes_livros (data, tipo, codigo, titulo, quantidade, responsavel, coordenacao)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                                    """, (data_mov_livro_s, "Saída", cod_livro_sai, titulo_livro_sai, qtd_mov_livro_sai, resp_mov_livro.strip(), coord_mov_livro))
                                            conn.commit()
                                            st.success(f"Saída de {qtd_mov_livro_sai} un. de '{titulo_livro_sai}' registrada! Novo saldo: {nova_qtd_livro_s}.")
                                            st.rerun()
                                        except Exception as ex_sai_livro:
                                            conn.rollback()
                                            st.error(f"Erro ao salvar saída: {ex_sai_livro}")
                                    else:
                                        st.error(f"Saldo Insuficiente! O item possui apenas {qtd_atual_livro} unidades no estoque.")

                # ---------------------------------------------------------------
                # ABA 5: HISTÓRICO DE MOVIMENTAÇÃO
                # ---------------------------------------------------------------
                elif aba_livros_admin == "Histórico de Movimentação":
                    df_mov_livros = pd.read_sql_query("SELECT data AS Data, tipo AS Tipo, codigo AS Código, titulo AS Título, quantidade AS Quantidade, responsavel AS Responsável, coordenacao AS Coordenação FROM movimentacoes_livros ORDER BY id DESC;", conn)
                    if df_mov_livros.empty:
                        st.info("Nenhuma movimentação registrada até o momento.")
                    else:
                        st.dataframe(df_mov_livros, use_container_width=True, hide_index=True)

                # ---------------------------------------------------------------
                # ABA 6: EDITAR / EXCLUIR ITEM
                # ---------------------------------------------------------------
                elif aba_livros_admin == "Editar / Excluir Item":
                    if df_raw_livros.empty:
                        st.info("Nenhum livro ou produto cadastrado ainda.")
                    else:
                        opcao_livro_edit = st.selectbox("Selecione para modificar:", df_raw_livros.index, format_func=lambda x: f"{df_raw_livros.loc[x, 'codigo']} - {df_raw_livros.loc[x, 'titulo']}")
                        cod_atual_livro = df_raw_livros.loc[opcao_livro_edit, "codigo"]

                        foto_livro_atual = fotos_catalogo_ngi("produtos_livros", [cod_atual_livro]).get(cod_atual_livro)
                        if foto_livro_atual is not None:
                            st.image(foto_livro_atual, width=180)

                        col_edl1, col_edl2 = st.columns(2)
                        edit_cod_livro = col_edl1.text_input("Código:", value=df_raw_livros.loc[opcao_livro_edit, "codigo"])
                        edit_titulo_livro = col_edl2.text_input("Título:", value=df_raw_livros.loc[opcao_livro_edit, "titulo"])
                        lista_tipo_livro = ["Livro", "Livreto"]
                        tipo_atual_livro = df_raw_livros.loc[opcao_livro_edit, "tipo"]
                        idx_tipo_livro = lista_tipo_livro.index(tipo_atual_livro) if tipo_atual_livro in lista_tipo_livro else 0
                        edit_tipo_livro = col_edl1.selectbox("Tipo:", lista_tipo_livro, index=idx_tipo_livro)
                        edit_qtd_livro = col_edl2.number_input("Quantidade (Ajuste):", min_value=0, value=int(df_raw_livros.loc[opcao_livro_edit, "quantidade"]))
                        nova_foto_livro = st.file_uploader("Substituir Foto (opcional):", type=["png", "jpg", "jpeg"], key=f"nova_foto_{cod_atual_livro}")
                        remover_foto_livro = st.checkbox("Remover foto atual (ficar sem foto)", key=f"remover_foto_{cod_atual_livro}")

                        col_lbtn1, col_lbtn2 = st.columns([1, 4])
                        with col_lbtn1:
                            if st.button("Salvar Alterações", type="primary"):
                                cursor = conn.cursor()
                                if nova_foto_livro is not None:
                                    cursor.execute("""
                                UPDATE produtos_livros 
                                SET codigo = %s, titulo = %s, tipo = %s, quantidade = %s, foto = %s 
                                WHERE codigo = %s;
                            """, (edit_cod_livro.strip(), edit_titulo_livro.strip(), edit_tipo_livro, edit_qtd_livro, psycopg2.Binary(nova_foto_livro.getvalue()), cod_atual_livro))
                                elif remover_foto_livro:
                                    cursor.execute("""
                                UPDATE produtos_livros 
                                SET codigo = %s, titulo = %s, tipo = %s, quantidade = %s, foto = NULL 
                                WHERE codigo = %s;
                            """, (edit_cod_livro.strip(), edit_titulo_livro.strip(), edit_tipo_livro, edit_qtd_livro, cod_atual_livro))
                                else:
                                    cursor.execute("""
                                UPDATE produtos_livros 
                                SET codigo = %s, titulo = %s, tipo = %s, quantidade = %s 
                                WHERE codigo = %s;
                            """, (edit_cod_livro.strip(), edit_titulo_livro.strip(), edit_tipo_livro, edit_qtd_livro, cod_atual_livro))
                                conn.commit()
                                st.success("Modificado com sucesso!")
                                st.rerun()

                        with col_lbtn2:
                            if st.button("Excluir Item"):
                                cursor = conn.cursor()
                                cursor.execute("DELETE FROM produtos_livros WHERE codigo = %s;", (cod_atual_livro,))
                                conn.commit()
                                st.warning("Removido com sucesso.")
                                st.rerun()

            # =========================================================================
            # NOVO MÓDULO: LIVROS E PRODUTOS — SOLICITAÇÃO (TODOS OS USUÁRIOS)
            # =========================================================================
            elif escolha == "Livros e Produtos" and st.session_state.PERFIL_USUARIO_LOGADO == "Usuário Comum":
                renderizar_banner("Livros e Produtos", "Catálogo de livros e livretos disponíveis, com foto de referência")

                if st.session_state.get("msg_sucesso_livros"):
                    st.success("Sua solicitação foi encaminhada com sucesso!")
                    del st.session_state["msg_sucesso_livros"]

                # Resumo completo do acervo, inclusive títulos sem estoque.
                # A seleção para solicitar continua restrita aos itens disponíveis.
                df_resumo_livros_solicitante = pd.read_sql_query("SELECT quantidade FROM produtos_livros;", conn)
                renderizar_indicadores_acervo_ngi(df_resumo_livros_solicitante)

                df_disp_livros = pd.read_sql_query("SELECT codigo, titulo, tipo, quantidade, NULL::bytea AS foto FROM produtos_livros WHERE quantidade > 0 ORDER BY titulo ASC;", conn)

                if df_disp_livros.empty:
                    st.info("Nenhum livro ou produto disponível no momento.")
                else:
                    aba_catalogo_livros, aba_solicitar_livros = st.tabs(["Itens disponíveis", "Fazer solicitação (carrinho)"])
                    with aba_catalogo_livros:
                        st.caption('Para pedir, abra a aba "Fazer solicitação (carrinho)" logo acima.')
                        renderizar_catalogo_visual_ngi(df_disp_livros)

                    with aba_solicitar_livros:
                        if "carrinho_livros" not in st.session_state:
                            st.session_state.carrinho_livros = []

                        with st.container(border=True):
                            cabecalho_pedido_ngi("Nova solicitação de livros/produtos", "Siga os 3 passos. Todos os itens do carrinho seguem juntos em um único pedido.")
                            passo_pedido_ngi(1, 'Escolha o item e clique em "Adicionar ao carrinho"')
                            col_add_lv1, col_add_lv2, col_add_lv3 = st.columns([3, 1, 1.3])
                            opcao_sol_livro = col_add_lv1.selectbox(
                                "Item:",
                                df_disp_livros.index,
                                format_func=lambda x: f"{df_disp_livros.loc[x, 'titulo']} (Disponível: {df_disp_livros.loc[x, 'quantidade']})",
                                key="select_livro_carrinho"
                            )
                            qtd_sol_livro = col_add_lv2.number_input("Quantidade:", min_value=1, max_value=int(df_disp_livros.loc[opcao_sol_livro, "quantidade"]), value=1, step=1, key="qtd_livro_carrinho")
                            col_add_lv3.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                            with col_add_lv3:
                                with st.container(key="btn_add_5"):
                                    clicou_add_5 = st.button("Adicionar ao carrinho", icon=":material/add_shopping_cart:", key="add_carrinho_livro", use_container_width=True)
                            if clicou_add_5:
                                cod_sel_livro = df_disp_livros.loc[opcao_sol_livro, "codigo"]
                                titulo_sel_livro = df_disp_livros.loc[opcao_sol_livro, "titulo"]
                                adicionar_item_carrinho_ngi("carrinho_livros", {"codigo": cod_sel_livro, "item": titulo_sel_livro, "quantidade": int(qtd_sol_livro)}, df_disp_livros.loc[opcao_sol_livro, "quantidade"])

                            if st.session_state.carrinho_livros:
                                passo_pedido_ngi(2, "Confira o carrinho", detalhe=texto_qtd_itens_ngi(len(st.session_state.carrinho_livros)))
                                renderizar_carrinho_ngi("carrinho_livros", "4")

                                passo_pedido_ngi(3, "Informe a coordenação, a justificativa e envie")
                                lista_siglas_coord_livro_user = dados_sob_demanda_ngi("coordenacoes")["Sigla"].tolist() if not dados_sob_demanda_ngi("coordenacoes").empty else ["GERAL"]
                                col_env_lv1, col_env_lv2 = st.columns([1, 2])
                                coord_sol_livro = col_env_lv1.selectbox("Coordenação: *", lista_siglas_coord_livro_user, key="coord_carrinho_livro")
                                justificativa_sol_livro = col_env_lv2.text_area("Justificativa: *", placeholder="Explique o motivo da solicitação (ex: atividade de educação ambiental, distribuição em evento, etc.)", key="obs_carrinho_livro")

                                if st.button(f"Enviar solicitação ({texto_qtd_itens_ngi(len(st.session_state.carrinho_livros))})", type="primary", icon=":material/send:", key="enviar_carrinho_livro"):
                                    if not justificativa_sol_livro.strip():
                                        st.error("A Justificativa é obrigatória para solicitar livros/livretos!")
                                    else:
                                        try:
                                            lote_id_livro = str(uuid.uuid4())
                                            cursor = conn.cursor()
                                            for item_carr_lv in st.session_state.carrinho_livros:
                                                cursor.execute("""
                                        INSERT INTO solicitacoes_almoxarifado 
                                        (tipo, referencia_codigo, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, status, observacao, lote_id, origem_estoque)
                                        VALUES ('MATERIAL', %s, %s, %s, %s, %s, %s, 'PENDENTE', %s, %s, 'LIVROS');
                                    """, (item_carr_lv["codigo"], item_carr_lv["item"], item_carr_lv["quantidade"], st.session_state.NOME_USUARIO_LOGADO, st.session_state.EMAIL_USUARIO_LOGADO, coord_sol_livro, justificativa_sol_livro.strip(), lote_id_livro))
                                            conn.commit()
                                            st.session_state.carrinho_livros = []
                                            st.session_state["msg_sucesso_livros"] = True
                                            st.rerun()
                                        except Exception as ex_livro:
                                            conn.rollback()
                                            st.error(f"Erro ao enviar solicitação: {ex_livro}")
                            else:
                                carrinho_vazio_ngi("livros", campos=("Coordenação: *", "Justificativa: *"))

            # =========================================================================
            # NOVO MÓDULO DE SOLICITAÇÃO — TELA (PERFIL USUÁRIO): EMPRÉSTIMO DISPONÍVEL
            # =========================================================================
            elif escolha in ("Empréstimo de Material", "Solicitar Empréstimo") and (
                (escolha == "Empréstimo de Material" and st.session_state.PERFIL_USUARIO_LOGADO == "Usuário Comum") or
                (escolha == "Solicitar Empréstimo" and st.session_state.PERFIL_USUARIO_LOGADO != "Usuário Comum")
            ):
                st.markdown("""
            <div class="ngi-page-header" style="background: transparent; padding: 0 0 24px; margin-bottom: 8px;">
                <h1 style="color: #122820; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                    Itens Disponíveis para Empréstimo
                </h1>
                <p style="color: #6a7b73; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Consulte os itens do catálogo de empréstimo e solicite a retirada
                </p>
            </div>
        """, unsafe_allow_html=True)

                if st.session_state.get("msg_sucesso_emprestimo"):
                    st.success("Sua solicitação foi encaminhada com sucesso!")
                    del st.session_state["msg_sucesso_emprestimo"]

                df_todos_itens_emprestimo = pd.read_sql_query("""
            SELECT ei.id, ei.codigo, ei.item, ei.quantidade_total, ei.quantidade_disponivel, ei.observacao, NULL::bytea AS foto,
                   (SELECT MIN(er.data_prevista) FROM emprestimo_registros er WHERE er.item_id = ei.id AND er.status = 'EMPRESTADO') AS previsao_devolucao
            FROM emprestimo_itens ei
            ORDER BY ei.codigo ASC;
        """, conn)

                if df_todos_itens_emprestimo.empty:
                    st.info("Nenhum item cadastrado para empréstimo no momento.")
                else:
                    df_emp_disp_user = df_todos_itens_emprestimo.rename(columns={
                        "id": "ID", "codigo": "Código", "item": "Item / Equipamento",
                        "quantidade_total": "Qtd Total", "quantidade_disponivel": "Qtd Disponível",
                        "observacao": "Observações", "previsao_devolucao": "Previsão de devolução"
                    }).copy()
                    df_emp_disp_user["Emprestados"] = df_emp_disp_user["Qtd Total"] - df_emp_disp_user["Qtd Disponível"]
                    aba_emp_catalogo, aba_emp_solicitar = st.tabs(["Itens disponíveis", "Fazer solicitação (carrinho)"])
                    with aba_emp_catalogo:
                        renderizar_catalogo_emprestimos(df_emp_disp_user, solicitante=True)
                        st.caption("Para pedir, abra a aba \"Fazer solicitação (carrinho)\" logo acima. Itens indisponíveis podem ser consultados no catálogo, mas não podem ser adicionados à solicitação.")
                    with aba_emp_solicitar:
                        if "carrinho_emprestimo" not in st.session_state:
                            st.session_state.carrinho_emprestimo = []

                        with st.container(border=True):
                            cabecalho_pedido_ngi("Nova solicitação de empréstimo", "Siga os 4 passos. Todos os itens do carrinho seguem juntos em um único pedido.")
                            passo_pedido_ngi(1, "Informe o período e a coordenação")
                            lista_siglas_coord_emp_user = dados_sob_demanda_ngi("coordenacoes")["Sigla"].tolist() if not dados_sob_demanda_ngi("coordenacoes").empty else ["GERAL"]

                            col_dt1, col_dt2, col_dt3 = st.columns(3)
                            data_retirada_sol = col_dt1.date_input("Data de Retirada: *", value=date.today(), format="DD/MM/YYYY", key="data_retirada_carrinho_emp")
                            data_prev_sol = col_dt2.date_input("Data de Devolução: *", value=date.today(), format="DD/MM/YYYY", key="data_prev_carrinho_emp")
                            coord_sol_emp = col_dt3.selectbox("Coordenação:", lista_siglas_coord_emp_user, key="coord_carrinho_emp")

                            df_raw_emp_user = df_todos_itens_emprestimo[df_todos_itens_emprestimo["quantidade_disponivel"] > 0].reset_index(drop=True)
                            passo_pedido_ngi(2, 'Escolha o item e clique em "Adicionar ao carrinho"')

                            if df_raw_emp_user.empty:
                                st.warning("Nenhum item disponível para adicionar no momento — confira a previsão de devolução no catálogo acima.")
                            else:
                                col_add_e1, col_add_e2, col_add_e3 = st.columns([3, 1, 1.3])
                                opcao_sol_emp = col_add_e1.selectbox(
                                    "Item:",
                                    df_raw_emp_user.index,
                                    format_func=lambda x: f"{df_raw_emp_user.loc[x, 'item']} (Disponível: {df_raw_emp_user.loc[x, 'quantidade_disponivel']})",
                                    key="select_emprestimo_carrinho"
                                )
                                qtd_sol_emp = col_add_e2.number_input("Quantidade:", min_value=1, max_value=int(df_raw_emp_user.loc[opcao_sol_emp, "quantidade_disponivel"]), value=1, step=1, key="qtd_emprestimo_carrinho")
                                col_add_e3.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                                with col_add_e3:
                                    with st.container(key="btn_add_6"):
                                        clicou_add_6 = st.button("Adicionar ao carrinho", icon=":material/add_shopping_cart:", key="add_carrinho_emprestimo", use_container_width=True)
                                if clicou_add_6:
                                    item_id_sel = int(df_raw_emp_user.loc[opcao_sol_emp, "id"])
                                    nome_sel_emp = df_raw_emp_user.loc[opcao_sol_emp, "item"]
                                    adicionar_item_carrinho_ngi("carrinho_emprestimo", {"item_id": item_id_sel, "item": nome_sel_emp, "quantidade": int(qtd_sol_emp)}, df_raw_emp_user.loc[opcao_sol_emp, "quantidade_disponivel"])

                            if st.session_state.carrinho_emprestimo:
                                passo_pedido_ngi(3, "Confira o carrinho", detalhe=texto_qtd_itens_ngi(len(st.session_state.carrinho_emprestimo)))
                                renderizar_carrinho_ngi("carrinho_emprestimo", "5", mostrar_codigo=False)

                                passo_pedido_ngi(4, "Informe a atividade, aceite o termo e envie")
                                col_env_e1, col_env_e2 = st.columns([1, 1])
                                atividade_sol_emp = col_env_e1.text_input("Atividade Associada: *", placeholder="Ex: Vistoria de campo na trilha X", key="atividade_carrinho_emp")
                                obs_sol_emp = col_env_e2.text_input("Observações (opcional):", key="obs_carrinho_emp")

                                st.markdown("<hr style='margin: 20px 0 10px 0; opacity: 0.2;'>", unsafe_allow_html=True)
                                with st.expander("Termo de Responsabilidade - clique para ler", icon=":material/description:"):
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
                                aceite_termo = st.checkbox("Li e concordo com o Termo de Responsabilidade pelo Empréstimo de Materiais. *", key="aceite_carrinho_emp")

                                if st.button(f"Enviar solicitação ({texto_qtd_itens_ngi(len(st.session_state.carrinho_emprestimo))})", type="primary", icon=":material/send:", key="enviar_carrinho_emp"):
                                    if not atividade_sol_emp.strip():
                                        st.error("O campo 'Atividade Associada' é obrigatório!")
                                    elif data_prev_sol < data_retirada_sol:
                                        st.error("A Data de Devolução não pode ser anterior à Data de Retirada!")
                                    elif not aceite_termo:
                                        st.error("A solicitação de empréstimo somente será efetivada após a leitura e aceitação do Termo de Responsabilidade!")
                                    else:
                                        try:
                                            lote_id_novo = str(uuid.uuid4())
                                            cursor = conn.cursor()
                                            for item_carr_e in st.session_state.carrinho_emprestimo:
                                                cursor.execute("""
                                    INSERT INTO solicitacoes_almoxarifado 
                                    (tipo, referencia_codigo, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, data_retirada, data_prevista, atividade_associada, status, observacao, termo_aceito, data_aceite_termo, lote_id)
                                    VALUES ('EMPRESTIMO', %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDENTE', %s, TRUE, CURRENT_TIMESTAMP, %s);
                                """, (str(item_carr_e["item_id"]), item_carr_e["item"], item_carr_e["quantidade"], st.session_state.NOME_USUARIO_LOGADO, st.session_state.EMAIL_USUARIO_LOGADO, coord_sol_emp, data_retirada_sol, data_prev_sol, atividade_sol_emp.strip(), obs_sol_emp.strip(), lote_id_novo))
                                            conn.commit()
                                            st.session_state.carrinho_emprestimo = []
                                            st.session_state["msg_sucesso_emprestimo"] = True
                                            st.rerun()
                                        except Exception as ex:
                                            conn.rollback()
                                            st.error(f"Erro ao enviar solicitação: {ex}")
                            else:
                                carrinho_vazio_ngi("emprestimo", campos=("Atividade Associada: *", "Observações (opcional):"), passo_carrinho=3)


                # =========================================================================
                # NOVO MÓDULO DE SOLICITAÇÃO — TELA (PERFIL USUÁRIO): MINHAS SOLICITAÇÕES
            # =========================================================================
            elif escolha == "Minhas Solicitações":
                renderizar_banner("Minhas Solicitações", "Acompanhe o status das suas solicitações de material e empréstimo")

                df_minhas_sol = pd.read_sql_query("""
            SELECT 
                id,
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
                    df_pendentes_usuario = df_minhas_sol[df_minhas_sol["Status"] == "PENDENTE"]

                    if not df_pendentes_usuario.empty:
                        st.markdown('<h3 style="font-size: 18px; font-weight: 600; margin-bottom: 4px;">Solicitações Pendentes</h3>', unsafe_allow_html=True)
                        st.caption("Você pode cancelar uma solicitação enquanto ela ainda estiver pendente de aprovação.")
                        for _, sol_u in df_pendentes_usuario.iterrows():
                            col_su1, col_su2 = st.columns([5, 1])
                            with col_su1:
                                st.markdown(f"**Solicitação Nº {int(sol_u['id'])} — {sol_u['Tipo']}** · {sol_u['Item']} (Qtd: {sol_u['Quantidade']}) · Solicitado em {sol_u['Data da Solicitação']}")
                            with col_su2:
                                if st.button("Cancelar", key=f"cancelar_sol_{int(sol_u['id'])}"):
                                    try:
                                        cursor = conn.cursor()
                                        cursor.execute("""
                                    UPDATE solicitacoes_almoxarifado
                                    SET status = 'CANCELADA', data_decisao = CURRENT_TIMESTAMP
                                    WHERE id = %s AND solicitante_email = %s AND status = 'PENDENTE';
                                """, (int(sol_u['id']), st.session_state.EMAIL_USUARIO_LOGADO))
                                        conn.commit()
                                        st.success("Solicitação cancelada com sucesso.")
                                        st.rerun()
                                    except Exception as ex_cancel:
                                        conn.rollback()
                                        st.error(f"Erro ao cancelar: {ex_cancel}")
                        st.markdown("<hr style='margin: 15px 0 20px 0; opacity: 0.2;'>", unsafe_allow_html=True)

                    st.markdown('<h3 style="font-size: 18px; font-weight: 600; margin-bottom: 12px;">Histórico Completo</h3>', unsafe_allow_html=True)

                    def destacar_status_sol(val):
                        if val == 'PENDENTE':
                            return 'background-color: #fff3cd; color: #856404; font-weight: bold;'
                        elif val == 'APROVADA':
                            return 'background-color: #d4edda; color: #155724; font-weight: bold;'
                        elif val == 'REJEITADA':
                            return 'background-color: rgba(198, 40, 40, 0.12); color: #c62828; font-weight: bold;'
                        elif val == 'CANCELADA':
                            return 'background-color: rgba(120, 120, 120, 0.12); color: #555555; font-weight: bold;'
                        return ''

                    st.dataframe(df_minhas_sol.drop(columns=["id"]).style.map(destacar_status_sol, subset=['Status']), use_container_width=True, hide_index=True)

            # =========================================================================
            # NOVO MÓDULO DE SOLICITAÇÃO — TELA (PERFIL ADMINISTRADOR): SOLICITAÇÕES
            # =========================================================================
            elif escolha == label_solicitacoes:
                st.markdown("""
            <div class="ngi-page-header" style="background: transparent; padding: 0 0 24px; margin-bottom: 8px;">
                <h1 style="color: #122820; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                    Solicitações
                </h1>
                <p style="color: #6a7b73; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Analise os pedidos sem sair da lista.
                </p>
            </div>
        """, unsafe_allow_html=True)

                df_pendentes = pd.read_sql_query("""
            SELECT id, tipo, referencia_codigo, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, data_solicitacao, data_retirada, data_prevista, atividade_associada, observacao, termo_aceito, data_aceite_termo, origem_estoque
            FROM solicitacoes_almoxarifado WHERE status = 'PENDENTE' ORDER BY id ASC;
        """, conn)
                indicadores_solicitacoes_ngi(df_pendentes)
                aba_solicitacao = st.radio("Visualização de solicitações", ["Pendentes", "Histórico"], horizontal=True, label_visibility="collapsed", key="ngi_sol_aba")
                cursor = conn.cursor()
                if aba_solicitacao == "Pendentes":

                    if df_pendentes.empty:
                        st.info("Nenhuma solicitação pendente no momento.")
                    else:
                        df_para_analisar, painel_detalhe = tabela_solicitacoes_ngi(df_pendentes)
                        with painel_detalhe:
                            for _, sol in df_para_analisar.iterrows():
                                detalhes_solicitacao_ngi(sol, conn)
                                just_rejeicao = st.text_area(
                                    "Justificativa (obrigatória para rejeitar)",
                                    key=f"just_rejeitar_{sol['id']}",
                                    placeholder="Informe o motivo caso precise rejeitar...",
                                    height=80,
                                )
                                col_ap1, col_ap2 = st.columns([1.65, 1])
                                with col_ap1:
                                    if st.button("Aprovar solicitação", key=f"aprovar_{sol['id']}", type="primary", icon=":material/check:", use_container_width=True):
                                        try:
                                            if sol["tipo"] == "MATERIAL":
                                                origem_sol = sol.get("origem_estoque")
                                                if origem_sol == "BRIGADA":
                                                    tabela_estoque, tabela_movimentacao, coluna_item_mov = "produtos_brigada", "movimentacoes_brigada", "item"
                                                elif origem_sol == "LIVROS":
                                                    tabela_estoque, tabela_movimentacao, coluna_item_mov = "produtos_livros", "movimentacoes_livros", "titulo"
                                                else:
                                                    tabela_estoque, tabela_movimentacao, coluna_item_mov = "produtos", "movimentacoes", "item"
                                                cursor.execute(f"SELECT quantidade FROM {tabela_estoque} WHERE codigo = %s;", (sol["referencia_codigo"],))
                                                res_prod = cursor.fetchone()
                                                if not res_prod or res_prod[0] < sol["quantidade"]:
                                                    st.error("Saldo insuficiente em estoque para aprovar esta solicitação.")
                                                else:
                                                    cursor.execute(f"UPDATE {tabela_estoque} SET quantidade = quantidade - %s WHERE codigo = %s;", (sol["quantidade"], sol["referencia_codigo"]))
                                                    cursor.execute(f"""
                                                INSERT INTO {tabela_movimentacao} (data, tipo, codigo, {coluna_item_mov}, quantidade, responsavel, coordenacao)
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
                                                (item_id, item_nome, quantidade, pessoa, coordenacao, data_retirada, data_prevista, status, email_pessoa)
                                                VALUES (%s, %s, %s, %s, %s, %s, %s, 'EMPRESTADO', %s);
                                            """, (int(sol["referencia_codigo"]), sol["item_nome"], sol["quantidade"], sol["solicitante_nome"], sol["coordenacao"], sol["data_retirada"] if sol["data_retirada"] is not None else date.today(), sol["data_prevista"], sol["solicitante_email"]))
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
                                    if st.button("Rejeitar", key=f"rejeitar_{sol['id']}", icon=":material/close:", use_container_width=True):
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
                            elif val == 'CANCELADA':
                                return 'background-color: rgba(120, 120, 120, 0.12); color: #555555; font-weight: bold;'
                            return ''

                        st.dataframe(df_hist_sol.style.map(destacar_status_hist, subset=['Status']), use_container_width=True, hide_index=True)

            # --- TELA: CADASTRAR PRODUTO ---
            elif escolha == "Cadastrar Produto":
                renderizar_banner("Gerenciamento de Produtos", "Cadastre, edite ou exclua os produtos do estoque")
                # Navegação nativa: dispensa o carregamento do componente externo nesta tela.
                aba_selecionada = st.radio(
                    "Opções de gerenciamento de produtos",
                    options=["Novo Material", "Editar / Excluir Produtos"],
                    index=0,
                    horizontal=True,
                    key="ngi_gerenciamento_produtos_aba_nativa",
                    label_visibility="collapsed",
                )

                if aba_selecionada == "Novo Material":
                    with st.form("form_novo_produto", clear_on_submit=True):
                        col_a, col_b = st.columns(2)
                        cod = col_a.text_input("Código")
                        nome_it = col_b.text_input("Nome do Material")
                        cat_it = col_a.selectbox("Categoria", dados_sob_demanda_ngi("categorias"))
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
                    if not dados_sob_demanda_ngi("produtos").empty:
                        st.dataframe(dados_sob_demanda_ngi("produtos"), use_container_width=True, hide_index=True)
                        df_raw_prod = pd.read_sql_query("SELECT * FROM produtos", conn)
                        opcao_selecionada = st.selectbox("Selecione para modificar:", df_raw_prod.index, format_func=lambda x: f"{df_raw_prod.loc[x, 'codigo']} - {df_raw_prod.loc[x, 'item']}")
                        cod_atual = df_raw_prod.loc[opcao_selecionada, "codigo"]
                
                        col_ed1, col_ed2 = st.columns(2)
                        edit_cod = col_ed1.text_input("Código:", value=df_raw_prod.loc[opcao_selecionada, "codigo"])
                        edit_item = col_ed2.text_input("Nome:", value=df_raw_prod.loc[opcao_selecionada, "item"])
                        edit_qtd = col_ed1.number_input("Quantidade (Ajuste):", min_value=0, value=int(df_raw_prod.loc[opcao_selecionada, "quantidade"]))
                        cat_atual = df_raw_prod.loc[opcao_selecionada, "categoria"]
                        idx_cat_padrao = dados_sob_demanda_ngi("categorias").index(cat_atual) if cat_atual in dados_sob_demanda_ngi("categorias") else 0
                        edit_cat = col_ed2.selectbox("Categoria:", dados_sob_demanda_ngi("categorias"), index=idx_cat_padrao)
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
                renderizar_banner("Gerenciamento de Categorias", "Organize as categorias usadas para classificar os produtos")
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
                        with st.container(key="btn_add_7"):
                            clicou_add_7 = st.button("Adicionar Categoria")
                        if clicou_add_7:
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
                        st.dataframe(pd.DataFrame(dados_sob_demanda_ngi("categorias"), columns=["Categorias Ativas"]), use_container_width=True, hide_index=True)

                elif aba_selecionada == "Editar / Excluir Categorias":
                    if dados_sob_demanda_ngi("categorias"):
                        cat_selecionada = st.selectbox("Selecione a categoria:", dados_sob_demanda_ngi("categorias"))
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
                renderizar_banner("Cadastrar Usuário", "Gerencie os usuários com acesso ao sistema")
                aba_selecionada = option_menu(
                    menu_title=None,
                    options=["Novo Usuário", "Editar / Excluir Usuários"],
                    icons=["person-plus", "pencil-square"],
                    orientation="horizontal",
                    styles=ESTILO_MENU_HORIZONTAL
                )

                if aba_selecionada == "Novo Usuário":
                    lista_coord_user = dados_sob_demanda_ngi("coordenacoes")["Sigla"].tolist() if not dados_sob_demanda_ngi("coordenacoes").empty else ["GERAL"]
                    with st.form("cad_user", clear_on_submit=True):
                        n = st.text_input("Nome")
                        e = st.text_input("E-mail")
                        s = st.text_input("Senha", type="password")
                        p = st.selectbox("Perfil", ["Administrador", "Usuário Comum"])
                        coord_novo_user = st.selectbox("Coordenação:", lista_coord_user, help="Coordenação à qual a pessoa está vinculada. Algumas telas do sistema (como Materiais Brigada) só ficam visíveis para coordenações específicas.")
                
                        if st.form_submit_button("Salvar", type="primary"):
                            if n and e:
                                try:
                                    senha_final = s if s else "123"
                                    cursor = conn.cursor()
                                    cursor.execute("""
                                INSERT INTO usuarios (nome, email, senha, perfil, coordenacao) 
                                VALUES (%s, %s, %s, %s, %s);
                            """, (n.strip(), e.strip().lower(), gerar_hash_senha(senha_final), p, coord_novo_user))
                                    conn.commit()

                                    if p == "Administrador":
                                        lista_funcionalidades = """
                                • Acessar todas as funcionalidades do sistema;<br>
                                • Cadastrar e gerenciar produtos, categorias, usuários e coordenações;<br>
                                • Registrar movimentações de estoque (entradas e saídas);<br>
                                • Gerenciar empréstimos de materiais;<br>
                                • Aprovar ou rejeitar solicitações de usuários;<br>
                                • Acessar relatórios e dashboards completos do sistema.
                                """
                                    else:
                                        lista_funcionalidades = """
                                • Realizar solicitações de itens disponíveis no estoque do Almoxarifado;<br>
                                • Solicitar o empréstimo de materiais disponíveis;<br>
                                • Acompanhar suas solicitações diretamente pelo sistema.
                                """

                                    with st.spinner("Enviando e-mail de boas-vindas..."):
                                        sucesso_boas_vindas, erro_boas_vindas = enviar_email_notificacao(
                                            e.strip().lower(),
                                            "Seu acesso ao Sistema de Gestão de Almoxarifado NGI Carajás",
                                            f"""
                                    <p>Olá, {n.strip()}!</p>
                                    <p>Seja bem-vindo(a)!</p>
                                    <p>Seu acesso ao sistema foi criado com sucesso. A partir de agora, você poderá:</p>
                                    <p>{lista_funcionalidades}</p>
                                    <p><b>Login:</b> {e.strip().lower()}<br><b>Senha:</b> {senha_final}</p>
                                    <p>Acesse o sistema pelo link: <a href="{URL_BASE_SISTEMA}">{URL_BASE_SISTEMA}</a></p>
                                    <p>Recomendamos que altere sua senha no primeiro acesso.</p>
                                    <p>Em caso de dúvidas, estamos à disposição. Seja bem-vindo(a)!</p>
                                    """
                                        )

                                    if sucesso_boas_vindas:
                                        st.success("Usuário registrado com sucesso! E-mail de boas-vindas enviado.")
                                    else:
                                        st.warning(f"Usuário registrado, mas o e-mail de boas-vindas falhou. Erro técnico: {erro_boas_vindas}")
                                    st.rerun()
                                except psycopg2.IntegrityError:
                                    conn.rollback()
                                    st.error("Este e-mail já está cadastrado.")
                            else:
                                st.error("Preencha o Nome e o E-mail!")

                elif aba_selecionada == "Editar / Excluir Usuários":
                    df_raw_users = pd.read_sql_query("SELECT nome, email, perfil, senha, coordenacao FROM usuarios ORDER BY nome ASC", conn)
                    if not df_raw_users.empty:
                        st.dataframe(df_raw_users[["nome", "email", "perfil", "coordenacao"]], use_container_width=True, hide_index=True)
                        idx_user = st.selectbox("Selecione para editar:", df_raw_users.index, format_func=lambda x: f"{df_raw_users.loc[x, 'nome']} ({df_raw_users.loc[x, 'email']})")
                        email_chave = df_raw_users.loc[idx_user, "email"]
                
                        edit_n = st.text_input("Nome:", value=df_raw_users.loc[idx_user, "nome"])
                        edit_e = st.text_input("E-mail:", value=df_raw_users.loc[idx_user, "email"])
                        edit_s = st.text_input("Nova senha:", value="", type="password", key=f"edit_senha_{email_chave}", help="A senha atual fica guardada criptografada e não pode ser exibida. Deixe em branco para manter a senha atual.")
                        edit_p = st.selectbox("Perfil:", ["Administrador", "Usuário Comum"], index=0 if df_raw_users.loc[idx_user, "perfil"] == "Administrador" else 1)

                        lista_coord_edit_user = dados_sob_demanda_ngi("coordenacoes")["Sigla"].tolist() if not dados_sob_demanda_ngi("coordenacoes").empty else ["GERAL"]
                        coord_atual_user = df_raw_users.loc[idx_user, "coordenacao"]
                        idx_coord_edit_user = lista_coord_edit_user.index(coord_atual_user) if coord_atual_user in lista_coord_edit_user else 0
                        edit_coord_user = st.selectbox("Coordenação:", lista_coord_edit_user, index=idx_coord_edit_user)
                
                        c_btn_u1, c_btn_u2 = st.columns([1, 4])
                        with c_btn_u1:
                            if st.button("Atualizar Dados", type="primary"):
                                cursor = conn.cursor()
                                senha_gravar = gerar_hash_senha(edit_s) if edit_s else df_raw_users.loc[idx_user, "senha"]
                                cursor.execute("""
                            UPDATE usuarios 
                            SET nome = %s, email = %s, senha = %s, perfil = %s, coordenacao = %s 
                            WHERE email = %s;
                        """, (edit_n.strip(), edit_e.strip().lower(), senha_gravar, edit_p, edit_coord_user, email_chave))
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
                renderizar_banner("Cadastrar Coordenação", "Gerencie as coordenações utilizadas nas solicitações e movimentações")
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
                    if not dados_sob_demanda_ngi("coordenacoes").empty:
                        st.dataframe(dados_sob_demanda_ngi("coordenacoes"), use_container_width=True, hide_index=True)
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
                renderizar_banner("Movimentação de Estoque", "Registre entradas e saídas, e consulte o histórico de movimentações")
        
                aba_movimentacao = option_menu(
                    menu_title=None,
                    options=["Registro de Entrada", "Registro de Saída", "Histórico de Movimentação"],
                    icons=["arrow-down-circle", "arrow-up-circle", ""], # Ícone de histórico removido completamente para não parecer IA
                    orientation="horizontal",
                    styles=ESTILO_MENU_HORIZONTAL
                )
        
                if dados_sob_demanda_ngi("produtos").empty:
                    st.warning("Nenhum produto cadastrado para movimentar.")
                else:
                    df_raw_prod = pd.read_sql_query("SELECT codigo, item, quantidade FROM produtos ORDER BY codigo ASC", conn)
                    lista_siglas_coord = dados_sob_demanda_ngi("coordenacoes")["Sigla"].tolist() if not dados_sob_demanda_ngi("coordenacoes").empty else ["N/A"]
            
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
                        if not dados_sob_demanda_ngi("movimentacoes").empty:
                            st.dataframe(dados_sob_demanda_ngi("movimentacoes").sort_index(ascending=False), use_container_width=True, hide_index=True)
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
            <div class="ngi-page-header" style="background: transparent; padding: 0 0 24px; margin-bottom: 8px;">
                <h1 style="color: #122820; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 700;">
                    Relatórios e Dashboard
                </h1>
                <p style="color: #6a7b73; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
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
                total_itens_estoque_rel = int(dados_sob_demanda_ngi("produtos")["Quantidade"].sum()) if not dados_sob_demanda_ngi("produtos").empty else 0
                if not dados_sob_demanda_ngi("produtos").empty:
                    valor_total_estoque_rel = float((dados_sob_demanda_ngi("produtos")["Quantidade"] * dados_sob_demanda_ngi("produtos")["Valor Unitário"].astype(float)).sum())
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
                    if not dados_sob_demanda_ngi("produtos").empty:
                        resumo_cat_rel = dados_sob_demanda_ngi("produtos").groupby("Categoria")["Quantidade"].sum().sort_values(ascending=False)
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
                st.markdown('<h3 style="font-size: 18px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center;"><span style="display: inline-block; width: 6px; height: 18px; background-color: #147746; margin-right: 8px; border-radius: 2px;"></span>Exportar Relatório Geral</h3>', unsafe_allow_html=True)
                st.caption("Gera uma planilha Excel com abas separadas: Estoque, Movimentações, Solicitações e Empréstimos.")

                if st.button("Gerar Relatório em Excel", type="primary", icon=":material/table_view:"):
                    with st.spinner("Gerando planilha..."):
                        buffer_excel = io.BytesIO()
                        with pd.ExcelWriter(buffer_excel, engine="openpyxl") as writer:
                            if not dados_sob_demanda_ngi("produtos").empty:
                                dados_sob_demanda_ngi("produtos").to_excel(writer, sheet_name="Estoque", index=False)
                            if not dados_sob_demanda_ngi("movimentacoes").empty:
                                dados_sob_demanda_ngi("movimentacoes").to_excel(writer, sheet_name="Movimentações", index=False)

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

            # =========================================================================
            # NOVO MÓDULO: CONTROLE DE EQUIPAMENTOS EMPRESTADOS (PERFIL ADMINISTRADOR)
            # =========================================================================
            elif escolha == "Controle de Equipamentos Emprestados":
                renderizar_banner("Controle de Equipamentos Emprestados", "Registre e acompanhe notebooks, desktops e acessórios emprestados por tempo indeterminado")
                aba_equipamento = option_menu(
                    menu_title=None,
                    options=["Novo Registro", "Consultar / Editar / Excluir"],
                    icons=["plus-circle", "pencil-square"],
                    orientation="horizontal",
                    styles=ESTILO_MENU_HORIZONTAL
                )

                lista_coord_equip = dados_sob_demanda_ngi("coordenacoes")["Sigla"].tolist() if not dados_sob_demanda_ngi("coordenacoes").empty else []

                if aba_equipamento == "Novo Registro":
                    col_eq7, col_eq8 = st.columns(2)
                    data_retirada_eq = col_eq7.date_input("Data da Retirada:", value=date.today(), format="DD/MM/YYYY", key="data_retirada_novo_equip")

                    periodo_indeterminado_eq = col_eq8.checkbox("Período Indeterminado", key="periodo_indeterminado_novo_equip")
                    if periodo_indeterminado_eq:
                        col_eq8.date_input("Data de Devolução:", value=None, format="DD/MM/YYYY", disabled=True, key="data_devolucao_novo_equip_disabled")
                        data_prevista_eq = "Indeterminado"
                    else:
                        data_prevista_eq_bruta = col_eq8.date_input("Data de Devolução:", value=date.today(), format="DD/MM/YYYY", key="data_devolucao_novo_equip")
                        data_prevista_eq = data_prevista_eq_bruta.strftime("%d/%m/%Y")

                    with st.form("form_novo_equipamento", clear_on_submit=True):
                        col_eq1, col_eq2 = st.columns(2)
                        nome_item_eq = col_eq1.text_input("Nome do Item: *", placeholder="Ex: Notebook, Desktop completo, Apoio de punho")
                        marca_modelo_eq = col_eq2.text_input("Marca/Modelo:")

                        col_eq3, col_eq4 = st.columns(2)
                        numero_serie_eq = col_eq3.text_input("Nº de Série: *", placeholder="Ex: PE9013216028 (ou N/A)")
                        patrimonio_eq = col_eq4.text_input("Patrimônio:", placeholder="Ex: PA 100")

                        col_eq5, col_eq6 = st.columns(2)
                        solicitante_eq = col_eq5.text_input("Solicitante/Usuário: *")
                        coordenacao_eq = col_eq6.selectbox("Coordenação:", lista_coord_equip if lista_coord_equip else ["GERAL"])

                        data_devolucao_eq = None

                        status_eq = st.selectbox("Status:", ["Em uso", "Devolvido"])
                        observacao_eq = st.text_area("Observação (opcional):", placeholder="Preencher se o material foi entregue ou devolvido com alguma avaria.")

                        if st.form_submit_button("Salvar Registro", type="primary"):
                            if nome_item_eq.strip() and solicitante_eq.strip() and numero_serie_eq.strip():
                                try:
                                    cursor = conn.cursor()
                                    cursor.execute("""
                                INSERT INTO equipamentos_emprestados
                                (nome_item, marca_modelo, numero_serie, patrimonio, solicitante_usuario, coordenacao, data_retirada, data_prevista_devolucao, status, data_devolucao, observacao)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                            """, (
                                        nome_item_eq.strip(), marca_modelo_eq.strip(), numero_serie_eq.strip(), patrimonio_eq.strip(),
                                        solicitante_eq.strip(), coordenacao_eq, data_retirada_eq, data_prevista_eq, status_eq, data_devolucao_eq, observacao_eq.strip()
                                    ))
                                    conn.commit()
                                    st.success("Registrado com sucesso!")
                                    st.rerun()
                                except Exception as ex_equip:
                                    conn.rollback()
                                    st.error(f"Erro ao salvar registro: {ex_equip}")
                            else:
                                st.error("Preencha o Nome do Item, Nº de Série e o Solicitante/Usuário!")

                elif aba_equipamento == "Consultar / Editar / Excluir":
                    df_raw_equip = pd.read_sql_query("SELECT * FROM equipamentos_emprestados ORDER BY id DESC;", conn)

                    if df_raw_equip.empty:
                        st.info("Nenhum equipamento registrado até o momento.")
                    else:
                        st.markdown('<h3 style="font-size: 18px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center;"><span style="display: inline-block; width: 6px; height: 18px; background-color: #147746; margin-right: 8px; border-radius: 2px;"></span>Filtros de Consulta</h3>', unsafe_allow_html=True)

                        col_feq1, col_feq2, col_feq3 = st.columns(3)
                        busca_equip = col_feq1.text_input("Buscar por Item, Solicitante ou Patrimônio:", placeholder="Digite para pesquisar...")
                        filtro_coord_equip = col_feq2.selectbox("Filtrar por Coordenação:", ["Todas"] + sorted(df_raw_equip["coordenacao"].dropna().unique().tolist()))
                        filtro_status_equip = col_feq3.selectbox("Filtrar por Status:", ["Todos", "Em uso", "Devolvido"])

                        df_filtrado_equip = df_raw_equip.copy()
                        if busca_equip:
                            df_filtrado_equip = df_filtrado_equip[
                                df_filtrado_equip["nome_item"].str.contains(busca_equip, case=False, na=False) |
                                df_filtrado_equip["solicitante_usuario"].str.contains(busca_equip, case=False, na=False) |
                                df_filtrado_equip["patrimonio"].str.contains(busca_equip, case=False, na=False)
                            ]
                        if filtro_coord_equip != "Todas":
                            df_filtrado_equip = df_filtrado_equip[df_filtrado_equip["coordenacao"] == filtro_coord_equip]
                        if filtro_status_equip != "Todos":
                            df_filtrado_equip = df_filtrado_equip[df_filtrado_equip["status"] == filtro_status_equip]

                        st.markdown("<br>", unsafe_allow_html=True)
                        df_exibir_equip = df_filtrado_equip.rename(columns={
                            "nome_item": "Nome do Item", "marca_modelo": "Marca/Modelo", "numero_serie": "Nº de Série",
                            "patrimonio": "Patrimônio", "solicitante_usuario": "Solicitante/Usuário", "coordenacao": "Coordenação",
                            "data_retirada": "Data da Retirada", "data_prevista_devolucao": "Data Prevista Devolução",
                            "status": "Status", "observacao": "Observação", "data_devolucao": "Data da Devolução"
                        })[["id", "Nome do Item", "Marca/Modelo", "Nº de Série", "Patrimônio", "Solicitante/Usuário", "Coordenação", "Data da Retirada", "Data Prevista Devolução", "Status", "Data da Devolução", "Observação"]]

                        def destacar_status_equip(val):
                            if val == 'Em uso':
                                return 'background-color: #d4edda; color: #155724; font-weight: bold;'
                            elif val == 'Devolvido':
                                return 'background-color: rgba(120, 120, 120, 0.12); color: #555555; font-weight: bold;'
                            return ''

                        st.dataframe(
                            df_exibir_equip.drop(columns=["id"]).style.map(destacar_status_equip, subset=['Status']),
                            use_container_width=True, hide_index=True
                        )

                        if df_filtrado_equip.empty:
                            st.info("Nenhum equipamento encontrado com os filtros aplicados.")
                        else:
                            st.markdown("<br>", unsafe_allow_html=True)
                            st.markdown('<h3 style="font-size: 18px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center;"><span style="display: inline-block; width: 6px; height: 18px; background-color: #147746; margin-right: 8px; border-radius: 2px;"></span>Editar / Excluir Registro</h3>', unsafe_allow_html=True)

                            df_filtrado_equip_idx = df_filtrado_equip.reset_index(drop=True)
                            opcao_equip = st.selectbox(
                                "Selecione o registro:",
                                df_filtrado_equip_idx.index,
                                format_func=lambda x: f"Registro Nº {df_filtrado_equip_idx.loc[x, 'id']} - {df_filtrado_equip_idx.loc[x, 'nome_item']} ({df_filtrado_equip_idx.loc[x, 'solicitante_usuario']})"
                            )
                            id_equip_atual = int(df_filtrado_equip_idx.loc[opcao_equip, "id"])
                            reg = df_filtrado_equip_idx.loc[opcao_equip]

                            col_ee1, col_ee2 = st.columns(2)
                            edit_nome_item = col_ee1.text_input("Nome do Item:", value=reg["nome_item"] or "")
                            edit_marca_modelo = col_ee2.text_input("Marca/Modelo:", value=reg["marca_modelo"] or "")

                            col_ee3, col_ee4 = st.columns(2)
                            edit_numero_serie = col_ee3.text_input("Nº de Série:", value=reg["numero_serie"] or "")
                            edit_patrimonio = col_ee4.text_input("Patrimônio:", value=reg["patrimonio"] or "")

                            col_ee5, col_ee6 = st.columns(2)
                            edit_solicitante = col_ee5.text_input("Solicitante/Usuário:", value=reg["solicitante_usuario"] or "")
                            idx_coord_atual = lista_coord_equip.index(reg["coordenacao"]) if reg["coordenacao"] in lista_coord_equip else 0
                            edit_coordenacao = col_ee6.selectbox("Coordenação:", lista_coord_equip if lista_coord_equip else ["GERAL"], index=idx_coord_atual, key=f"edit_coord_{id_equip_atual}")

                            edit_data_prevista = st.text_input("Data Prevista para Devolução:", value=reg["data_prevista_devolucao"] or "Indeterminado")

                            lista_status_equip = ["Em uso", "Devolvido"]
                            idx_status_atual = lista_status_equip.index(reg["status"]) if reg["status"] in lista_status_equip else 0
                            edit_status = st.selectbox("Status:", lista_status_equip, index=idx_status_atual, key=f"edit_status_{id_equip_atual}")

                            edit_devolucao_indeterminada = st.checkbox("Data de devolução indeterminada", value=(reg["data_devolucao"] is None), key=f"edit_dev_indet_{id_equip_atual}")
                            if not edit_devolucao_indeterminada:
                                valor_data_devolucao = reg["data_devolucao"] if reg["data_devolucao"] is not None else date.today()
                                edit_data_devolucao = st.date_input("Data da Devolução:", value=valor_data_devolucao, format="DD/MM/YYYY", key=f"edit_data_dev_{id_equip_atual}")
                            else:
                                edit_data_devolucao = None

                            edit_observacao = st.text_area("Observação:", value=reg["observacao"] or "", key=f"edit_obs_{id_equip_atual}")

                            col_be1, col_be2 = st.columns([1, 4])
                            with col_be1:
                                if st.button("Salvar Alterações", type="primary"):
                                    cursor = conn.cursor()
                                    cursor.execute("""
                                UPDATE equipamentos_emprestados
                                SET nome_item = %s, marca_modelo = %s, numero_serie = %s, patrimonio = %s,
                                    solicitante_usuario = %s, coordenacao = %s, data_prevista_devolucao = %s,
                                    status = %s, data_devolucao = %s, observacao = %s
                                WHERE id = %s;
                            """, (
                                        edit_nome_item.strip(), edit_marca_modelo.strip(), edit_numero_serie.strip(), edit_patrimonio.strip(),
                                        edit_solicitante.strip(), edit_coordenacao, edit_data_prevista.strip(),
                                        edit_status, edit_data_devolucao, edit_observacao.strip(), id_equip_atual
                                    ))
                                    conn.commit()
                                    st.success("Registro atualizado com sucesso!")
                                    st.rerun()
                            with col_be2:
                                if st.button("Excluir Registro"):
                                    cursor = conn.cursor()
                                    cursor.execute("DELETE FROM equipamentos_emprestados WHERE id = %s;", (id_equip_atual,))
                                    conn.commit()
                                    st.warning("Registro removido com sucesso.")
                                    st.rerun()
