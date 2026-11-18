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
# O ícone da aba (favicon) fica no próprio repositório: static/favicon.png.
# Antes ele vinha de um link do site gov.br; quando o link falhava, o ícone sumia.
import os as _os_favicon
CAMINHO_FAVICON = _os_favicon.path.join(_os_favicon.path.dirname(_os_favicon.path.abspath(__file__)), "static", "favicon.png")
st.set_page_config(
    page_title="SISTEMA DE GESTÃO DE ALMOXARIFADO NGI CARAJÁS", 
    page_icon=CAMINHO_FAVICON if _os_favicon.path.exists(CAMINHO_FAVICON) else "🌳", 
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
        data_uri_icone = ""
        if os.path.exists(CAMINHO_FAVICON):
            with open(CAMINHO_FAVICON, "rb") as arquivo_icone:
                data_uri_icone = "data:image/png;base64," + base64.b64encode(arquivo_icone.read()).decode("utf-8")
        # Reprocessa sempre que o arquivo static/favicon.png for trocado.
        ja_processado = f"<title>{titulo_novo}</title>" in conteudo and (not data_uri_icone or f'href="{data_uri_icone}"' in conteudo)

        conteudo_novo = re.sub(r"<title>.*?</title>", f"<title>{titulo_novo}</title>", conteudo, count=1)

        # Embute a logo diretamente no HTML como "data URI" (a imagem em
        # forma de texto, dentro do próprio arquivo). Assim o ícone chega
        # junto com a primeira resposta da página - não existe uma segunda
        # requisição que possa demorar e deixar o ícone padrão aparecer.
        if not ja_processado and data_uri_icone:
            if True:
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


# Senhas fáceis demais: quem entrar com uma delas é obrigado a criar outra.
SENHAS_FRACAS_NGI = {
    "123", "1234", "12345", "123456", "1234567", "12345678", "123456789",
    "000000", "111111", "123123", "654321", "abc123", "senha", "senha123",
    "admin", "admin123", "ngi", "ngi123", "icmbio", "icmbio123", "carajas", "qwerty",
}
TAMANHO_MINIMO_SENHA_NGI = 6


def senha_fraca_ngi(senha):
    senha = str(senha or "").strip()
    return len(senha) < TAMANHO_MINIMO_SENHA_NGI or senha.lower() in SENHAS_FRACAS_NGI


def problema_nova_senha_ngi(senha, confirmacao):
    """Devolve a mensagem de erro da nova senha, ou None se estiver tudo certo."""
    senha = str(senha or "")
    if not senha or not confirmacao:
        return "Preencha os dois campos de senha."
    if senha != confirmacao:
        return "As senhas não coincidem."
    if len(senha.strip()) < TAMANHO_MINIMO_SENHA_NGI:
        return f"A senha deve ter pelo menos {TAMANHO_MINIMO_SENHA_NGI} caracteres."
    if senha.strip().lower() in SENHAS_FRACAS_NGI:
        return "Essa senha é muito fácil de adivinhar. Escolha outra."
    return None


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
/* Quadro "Suas devoluções" (empréstimos em aberto do solicitante) */
.ngi-pend { border:1px solid #cfe3d6; background:#f1f8f3; border-left:4px solid #147746; border-radius:10px; padding:14px 16px; margin:4px 0 14px; }
.ngi-pend b { display:block; font-size:15px; color:#123d28 !important; }
.ngi-pend > span { display:block; font-size:13px; color:#5c6f64 !important; margin-top:3px; }
.ngi-pend.prazo { background:#fffaf0; border-color:#f0dfb8; border-left-color:#c58a00; }
.ngi-pend.atraso { background:#fff4f4; border-color:#f2caca; border-left-color:#c62828; }
.ngi-pend.atraso b { color:#9f1f1f !important; }
.ngi-pend table { width:100%; border-collapse:collapse; margin-top:10px; font-size:13px; background:#fff; border-radius:8px; overflow:hidden; }
.ngi-pend th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.3px; color:#6a7b73 !important; padding:7px 10px; border-bottom:1px solid #e6ece8; }
.ngi-pend td { padding:8px 10px; border-bottom:1px solid #f0f3f1; color:#1c3027 !important; }
.ngi-pend .c { text-align:center; }
.ngi-pend-tag { font-size:12px; font-weight:700; padding:3px 9px; border-radius:20px; white-space:nowrap; background:#e8f4ed; color:#17693f !important; }
.ngi-pend-tag.hoje { background:#fff1d6; color:#8a5a00 !important; }
.ngi-pend-tag.atraso { background:#fde4e4; color:#b42323 !important; }
@media(max-width:640px) { .ngi-pend th:nth-child(3), .ngi-pend td:nth-child(3) { display:none; }
    .ngi-pend { padding:12px; } .ngi-pend table { table-layout:fixed; font-size:12px; }
    .ngi-pend th, .ngi-pend td { padding:6px; overflow-wrap:anywhere; } .ngi-pend th:nth-child(2) { width:38px; }
    .ngi-pend-tag { white-space:normal; display:inline-block; line-height:1.3; } }
[data-testid="stDownloadButton"] button[kind="primary"] { background:#147746 !important; border-color:#147746 !important; }
[data-testid="stDownloadButton"] button[kind="primary"]:hover { background:#0d6036 !important; border-color:#0d6036 !important; }
[data-testid="stDownloadButton"] button[kind="primary"] p,
[data-testid="stDownloadButton"] button[kind="primary"] span { color:#ffffff !important; }
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

# =============================================================================
# MENU LATERAL DO ADMINISTRADOR (com o grupo "Cadastros" que abre e fecha)
# =============================================================================
# Cada item: (texto exibido, valor de "escolha" usado nas telas, ícone)
GRUPO_CADASTROS_NGI = [
    ("Produtos", "Cadastrar Produto"),
    ("Categorias", "Cadastrar Categoria"),
    ("Coordenações", "Cadastrar Coordenação"),
    ("Usuários", "Cadastrar Usuário"),
]

CSS_MENU_ADMIN_NGI = """
<style>
section[data-testid="stSidebar"] [class*="st-key-ngi_nav_"] button {
    background: transparent !important; border: 0 !important; border-left: 3px solid transparent !important;
    border-radius: 7px !important; justify-content: flex-start !important; text-align: left !important;
    padding: 9px 12px !important; min-height: 40px !important; margin: 1px 0 !important; box-shadow: none !important;
}
section[data-testid="stSidebar"] [class*="st-key-ngi_nav_"] button > div,
section[data-testid="stSidebar"] [class*="st-key-ngi_nav_"] button > div > span {
    width: 100% !important; justify-content: flex-start !important; text-align: left !important;
}
section[data-testid="stSidebar"] [class*="st-key-ngi_nav_"] button [data-testid="stMarkdownContainer"] { flex: 1 1 auto; text-align: left !important; }
section[data-testid="stSidebar"] [class*="st-key-ngi_nav_"] button p {
    color: #e3eee8 !important; font-size: 13px !important; font-weight: 500 !important; text-align: left !important;
}
section[data-testid="stSidebar"] [class*="st-key-ngi_nav_"] button [data-testid="stIconMaterial"] {
    color: #afcdbd !important; font-size: 19px !important; margin-right: 6px !important;
}
section[data-testid="stSidebar"] [class*="st-key-ngi_nav_"] button:hover { background: #164335 !important; }
section[data-testid="stSidebar"] [class*="st-key-ngi_nav_on_"] button {
    background: #194b38 !important; border-left-color: #55bd75 !important;
}
section[data-testid="stSidebar"] [class*="st-key-ngi_nav_on_"] button p { color: #ffffff !important; font-weight: 700 !important; }
/* cabeçalho do grupo: seta à direita */
section[data-testid="stSidebar"] [class*="st-key-ngi_nav_grupo"] button { position: relative; }
section[data-testid="stSidebar"] [class*="st-key-ngi_nav_grupo"] button::after {
    content: ""; position: absolute; right: 14px; top: 50%; width: 7px; height: 7px;
    border-right: 2px solid #cfe0d6; border-bottom: 2px solid #cfe0d6; transform: translateY(-70%) rotate(45deg);
}
section[data-testid="stSidebar"] [class*="st-key-ngi_nav_grupo_aberto"] button::after { transform: translateY(-20%) rotate(-135deg); }
/* subitens: recuo e linha vertical à esquerda */
section[data-testid="stSidebar"] [class*="st-key-ngi_subnav"] {
    margin: 2px 0 6px 21px; padding-left: 14px; border-left: 1px solid #2c5a49; gap: 0 !important;
}
section[data-testid="stSidebar"] [class*="st-key-ngi_subnav"] button { min-height: 36px !important; padding: 7px 12px !important; }
section[data-testid="stSidebar"] [class*="st-key-ngi_navsep"] { border-top: 1px solid #234e40; margin: 10px 0 6px; }
section[data-testid="stSidebar"] [class*="st-key-ngi_menu_admin"] { gap: 0 !important; }
</style>
"""


def _selecionar_menu_admin_ngi(valor):
    st.session_state.menu_admin_escolha = valor


def _alternar_cadastros_ngi():
    st.session_state.menu_cadastros_aberto = not st.session_state.get("menu_cadastros_aberto", False)


def menu_lateral_admin_ngi(label_solicitacoes):
    """Desenha o menu do administrador e devolve a tela escolhida."""
    if "menu_admin_escolha" not in st.session_state:
        st.session_state.menu_admin_escolha = "Painel Geral"
    escolha_atual = st.session_state.menu_admin_escolha
    if str(escolha_atual).startswith("Solicitações"):
        escolha_atual = st.session_state.menu_admin_escolha = label_solicitacoes
    valores_cadastro = [valor for _, valor in GRUPO_CADASTROS_NGI]
    if "menu_cadastros_aberto" not in st.session_state:
        st.session_state.menu_cadastros_aberto = escolha_atual in valores_cadastro

    st.markdown(CSS_MENU_ADMIN_NGI, unsafe_allow_html=True)

    def item(texto, valor, icone, chave):
        ativo = escolha_atual == valor
        with st.container(key=f"ngi_nav_{'on_' if ativo else ''}{chave}"):
            st.button(texto, key=f"botao_menu_{chave}", icon=icone, use_container_width=True,
                      on_click=_selecionar_menu_admin_ngi, args=(valor,))

    with st.container(key="ngi_menu_admin"):
        item("Painel Geral", "Painel Geral", ":material/grid_view:", "painel")
        item("Materiais Disponíveis", "Materiais Disponíveis", ":material/inventory_2:", "materiais")
        item("Empréstimo de Material", "Empréstimo de Material", ":material/sync:", "emprestimo")
        item("Materiais Brigada", "Materiais Brigada", ":material/local_fire_department:", "brigada")
        item("Materiais Pesquisa", "Materiais Pesquisa", ":material/travel_explore:", "pesquisa")
        item("Livros e Produtos", "Livros e Produtos", ":material/menu_book:", "livros")

        item("Movimentação de Estoque", "Movimentação de Estoque", ":material/swap_horiz:", "movimentacao")
        item(label_solicitacoes, label_solicitacoes, ":material/notifications:", "solicitacoes")
        item("Relatórios", "Relatórios", ":material/bar_chart:", "relatorios")

        aberto = st.session_state.menu_cadastros_aberto
        with st.container(key=f"ngi_nav_grupo_{'aberto' if aberto else 'fechado'}"):
            st.button("Cadastros", key="botao_menu_cadastros", icon=":material/format_list_bulleted:",
                      use_container_width=True, on_click=_alternar_cadastros_ngi)
        if aberto:
            with st.container(key="ngi_subnav_cadastros"):
                for texto, valor in GRUPO_CADASTROS_NGI:
                    item(texto, valor, None, "cad_" + valor.split()[-1].lower())

        st.container(key="ngi_navsep_sair", height=1, border=False)
        item("Sair", "Sair do Sistema", ":material/logout:", "sair")

    return escolha_atual

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
            tabela = {'BRIGADA':'produtos_brigada','PESQUISA':'produtos_pesquisa','LIVROS':'produtos_livros'}.get(sol.get('origem_estoque'),'produtos')
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


def pendencias_devolucao_ngi(email, nome):
    """Empréstimos ainda não devolvidos da pessoa logada (por e-mail; nome como reserva)."""
    return pd.read_sql_query("""
        SELECT item_nome, quantidade, data_retirada, data_prevista
        FROM emprestimo_registros
        WHERE status = 'EMPRESTADO'
          AND (LOWER(email_pessoa) = LOWER(%(email)s)
               OR (email_pessoa IS NULL AND LOWER(pessoa) = LOWER(%(nome)s)))
        ORDER BY data_prevista ASC, id ASC;
    """, conn, params={"email": email or "", "nome": nome or ""})


def painel_pendencias_devolucao_ngi(email, nome):
    """Quadro "Suas devoluções": mostra o que a pessoa ainda precisa devolver."""
    pendencias = pendencias_devolucao_ngi(email, nome)
    if pendencias.empty:
        st.markdown('<div class="ngi-pend ok"><b>Você não tem devoluções pendentes.</b>'
                    '<span>Nenhum item emprestado em seu nome no momento.</span></div>', unsafe_allow_html=True)
        return
    hoje = date.today()
    linhas, atrasados = [], 0
    for _, reg in pendencias.iterrows():
        prevista = reg["data_prevista"]
        dias = (prevista - hoje).days if pd.notna(prevista) else None
        if dias is None:
            situacao, classe = "Sem data prevista", ""
        elif dias < 0:
            situacao, classe = f"Atrasado há {-dias} dia{'s' if -dias != 1 else ''}", "atraso"
            atrasados += 1
        elif dias == 0:
            situacao, classe = "Vence hoje", "hoje"
        else:
            situacao, classe = f"No prazo · faltam {dias} dia{'s' if dias != 1 else ''}", "prazo"
        retirada = reg["data_retirada"].strftime("%d/%m/%Y") if pd.notna(reg["data_retirada"]) else "—"
        devolucao = prevista.strftime("%d/%m/%Y") if pd.notna(prevista) else "—"
        linhas.append(
            f'<tr><td>{html.escape(str(reg["item_nome"]))}</td><td class="c">{int(reg["quantidade"])}</td>'
            f'<td>{retirada}</td><td>{devolucao}</td><td><span class="ngi-pend-tag {classe}">{situacao}</span></td></tr>')
    total = len(pendencias)
    if atrasados:
        titulo = f"Você tem {atrasados} {'devolução' if atrasados == 1 else 'devoluções'} em atraso"
        texto = "Providencie a devolução ou fale com a Coordenação de Operação e Suporte se precisar de mais prazo."
        classe_box = "atraso"
    else:
        titulo = f"Você tem {total} {'item emprestado' if total == 1 else 'itens emprestados'}, dentro do prazo"
        texto = "Lembre-se de devolver até a data prevista."
        classe_box = "prazo"
    st.markdown(
        f'<div class="ngi-pend {classe_box}"><b>{titulo}</b><span>{texto}</span>'
        '<table><thead><tr><th>Item</th><th class="c">Qtd</th><th>Retirada</th><th>Devolução prevista</th><th>Situação</th></tr></thead>'
        f'<tbody>{"".join(linhas)}</tbody></table></div>', unsafe_allow_html=True)


def carrinho_vazio_ngi(prefixo, campos=("Coordenação:", "Observações (opcional):"), passo_carrinho=2):
    """Passos finais quando ainda não há itens: explica o que fazer."""
    passo_pedido_ngi(passo_carrinho, "Confira o carrinho", ativo=False, detalhe=texto_qtd_itens_ngi(0))
    st.info(f'Seu carrinho está vazio. Escolha um item no passo {passo_carrinho - 1} e clique em "Adicionar ao carrinho".')
    passo_pedido_ngi(passo_carrinho + 1, "Preencha os dados e envie", ativo=False)
    colunas = st.columns([1, 2])
    for coluna, rotulo in zip(colunas, campos):
        coluna.text_input(rotulo, value="", disabled=True, key=f"vazio_{prefixo}_{rotulo}")
    st.button("Enviar solicitação", type="primary", icon=":material/send:", disabled=True, key=f"enviar_vazio_{prefixo}")

def formulario_solicitacao_livros_ngi(df_disp_livros):
    """Carrinho de solicitação de livros/produtos. Usado pelo usuário comum
    (aba "Fazer solicitação") e pelo administrador (menu "Fazer Solicitação")."""
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


# =============================================================================
# ESTOQUES SETORIAIS (Materiais Brigada, Materiais Pesquisa...)
# =============================================================================
# Os dois módulos funcionam igual: estoque próprio, categorias, entradas,
# saídas, histórico e pedidos só para a coordenação dona do estoque.
# O código é um só; o que muda de um para outro fica na configuração abaixo.
# Para criar um novo estoque setorial: crie as 3 tabelas na inicialização,
# acrescente uma configuração aqui e um item no menu.
ESTOQUE_BRIGADA_NGI = {
    "chave": "brigada",
    "titulo": "Materiais Brigada",
    "subtitulo": "Estoque próprio da Brigada, separado do almoxarifado geral",
    "nome_estoque": "estoque da Brigada",
    "coordenacao": "BRIGADA",            # quem pode pedir (coordenação do usuário)
    "coordenacao_pedido": "Brigada",     # como o pedido aparece em Solicitações
    "origem": "BRIGADA",                 # usado na aprovação para baixar o estoque certo
    "rotulo_movimentacao": "Brigada",
    "tabelas": ("produtos_brigada", "movimentacoes_brigada", "categorias_brigada"),
    "titulo_pedido": "Nova solicitação de material da Brigada",
    "exemplo_categorias": "Ex: EPI, Combate a Incêndio, Primeiros Socorros",
    "exemplo_observacao": "Ex.: material para a operação de sábado",
    "prefixo_botoes": "3",
    "chave_botao_adicionar": "btn_add_4",
}

ESTOQUE_PESQUISA_NGI = {
    "chave": "pesquisa",
    "titulo": "Materiais Pesquisa",
    "subtitulo": "Estoque próprio de materiais de pesquisa (COLMOP), separado do almoxarifado geral",
    "nome_estoque": "estoque de Pesquisa",
    "coordenacao": "COLMOP",
    "coordenacao_pedido": "COLMOP",
    "origem": "PESQUISA",
    "rotulo_movimentacao": "Pesquisa",
    "tabelas": ("produtos_pesquisa", "movimentacoes_pesquisa", "categorias_pesquisa"),
    "titulo_pedido": "Nova solicitação de material de pesquisa",
    "exemplo_categorias": "Ex: Coleta, Campo, Laboratório, Monitoramento",
    "exemplo_observacao": "Ex.: material para a campanha de campo da próxima semana",
    "prefixo_botoes": "6",
    "chave_botao_adicionar": "btn_add_7",
}


def estoque_setorial_admin_ngi(cfg):
    """Tela do administrador: gestão do estoque setorial."""
    T_PROD, T_MOV, T_CAT = cfg["tabelas"]
    cursor = conn.cursor()
    renderizar_banner(cfg["titulo"], cfg["subtitulo"])
    aba_admin = option_menu(
        menu_title=None,
        options=["Itens Disponíveis", "Cadastrar Item", "Gerenciar Categorias", "Registro de Entrada", "Registro de Saída", "Histórico de Movimentação", "Editar / Excluir Item"],
        icons=["box-seam", "plus-circle", "tags", "arrow-down-circle", "arrow-up-circle", "journal-text", "pencil-square"],
        orientation="horizontal",
        styles=ESTILO_MENU_HORIZONTAL
    )

    df_raw_brig = pd.read_sql_query(f"SELECT * FROM {T_PROD} ORDER BY codigo ASC;", conn)
    lista_siglas_coord_brig = dados_sob_demanda_ngi("coordenacoes")["Sigla"].tolist() if not dados_sob_demanda_ngi("coordenacoes").empty else ["GERAL"]

    # ---------------------------------------------------------------
    # ABA 1: ITENS DISPONÍVEIS
    # ---------------------------------------------------------------
    if aba_admin == "Itens Disponíveis":
        if df_raw_brig.empty:
            st.info(f"Nenhum material cadastrado no {cfg['nome_estoque']} ainda.")
        else:
            df_display_brig = df_raw_brig.rename(columns={"codigo": "Código", "item": "Item", "quantidade": "Quantidade", "categoria": "Categoria", "valor_unitario": "Valor Unitário"})
            df_display_brig["Valor Unitário"] = df_display_brig["Valor Unitário"].map("R$ {:.2f}".format)
            st.dataframe(df_display_brig, use_container_width=True, hide_index=True)

    # ---------------------------------------------------------------
    # ABA 2: CADASTRAR ITEM
    # ---------------------------------------------------------------
    elif aba_admin == "Cadastrar Item":
        df_cat = pd.read_sql_query(f"SELECT nome FROM {T_CAT} ORDER BY nome ASC;", conn)
        lista_categorias = df_cat["nome"].tolist()

        with st.form(f"form_novo_produto_{cfg['chave']}", clear_on_submit=True):
            col_ba, col_bb = st.columns(2)
            cod_brig = col_ba.text_input("Código")
            nome_it_brig = col_bb.text_input("Nome do Material")
            cat_it_brig = col_ba.selectbox("Categoria", lista_categorias if lista_categorias else ["Nenhuma categoria cadastrada"])
            val_unit_brig = col_bb.number_input("Valor Unitário (R$)", min_value=0.0, step=0.01, format="%.2f")
            qtd_inicial_brig = st.number_input("Quantidade Inicial:", min_value=0, value=0, step=1)

            if st.form_submit_button("Finalizar Cadastro", type="primary"):
                if cod_brig and nome_it_brig:
                    try:
                        cursor = conn.cursor()
                        cursor.execute(f"INSERT INTO {T_PROD} VALUES (%s, %s, %s, %s, %s);", (cod_brig.strip(), nome_it_brig.strip(), int(qtd_inicial_brig), cat_it_brig, float(val_unit_brig)))
                        conn.commit()
                        st.success(f"Sucesso! {nome_it_brig} adicionado ao {cfg['nome_estoque']}.")
                        st.rerun()
                    except psycopg2.IntegrityError:
                        conn.rollback()
                        st.error(f"Erro! Código {cod_brig} já existe.")
                else:
                    st.error("Preencha ao menos o Código e o Nome do Material!")

    # ---------------------------------------------------------------
    # ABA 3: GERENCIAR CATEGORIAS
    # ---------------------------------------------------------------
    elif aba_admin == "Gerenciar Categorias":
        df_cat_aba = pd.read_sql_query(f"SELECT nome FROM {T_CAT} ORDER BY nome ASC;", conn)
        lista_categorias_aba = df_cat_aba["nome"].tolist()

        st.markdown("### Categorias atuais")
        if lista_categorias_aba:
            st.dataframe(
                df_cat_aba.rename(columns={"nome": "Categoria"}),
                use_container_width=True, hide_index=True,
                height=min(450, max(120, 38 * (len(lista_categorias_aba) + 1))),
            )
            with st.expander("Excluir uma categoria"):
                cat_existente_brig = st.selectbox("Categoria para excluir:", lista_categorias_aba, key=f"cat_{cfg['chave']}_excluir_visual")
                if st.button("Excluir categoria selecionada", key=f"del_cat_brig_{cat_existente_brig}"):
                    cursor = conn.cursor()
                    cursor.execute(f"DELETE FROM {T_CAT} WHERE nome = %s;", (cat_existente_brig,))
                    conn.commit()
                    st.rerun()
        else:
            st.info("Nenhuma categoria cadastrada ainda.")

        st.markdown("### Adicionar categoria")
        nova_cat_brig = st.text_input("Nova categoria:", placeholder=cfg["exemplo_categorias"], key=f"nova_cat_{cfg['chave']}")
        with st.container(key="btn_add_3"):
            clicou_add_cat_brig = st.button("Adicionar Categoria", key=f"add_cat_{cfg['chave']}")
        if clicou_add_cat_brig:
            if nova_cat_brig and nova_cat_brig.strip():
                try:
                    cursor = conn.cursor()
                    cursor.execute(f"INSERT INTO {T_CAT} VALUES (%s);", (nova_cat_brig.strip(),))
                    conn.commit()
                    st.success("Categoria adicionada!")
                    st.rerun()
                except psycopg2.IntegrityError:
                    conn.rollback()
                    st.error("Esta categoria já existe.")

    # ---------------------------------------------------------------
    # ABA 4: REGISTRO DE ENTRADA
    # ---------------------------------------------------------------
    elif aba_admin == "Registro de Entrada":
        if df_raw_brig.empty:
            st.warning("Nenhum material cadastrado para movimentar.")
        else:
            with st.form(f"form_entrada_{cfg['chave']}", clear_on_submit=True):
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
                        cursor.execute(f"UPDATE {T_PROD} SET quantidade = %s WHERE codigo = %s;", (nova_qtd_brig, prod_codigo_brig))
                        cursor.execute(f"""
                    INSERT INTO {T_MOV} (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                """, (data_mov_brig, "Entrada", prod_codigo_brig, prod_nome_brig, qtd_mov_brig_ent, st.session_state.NOME_USUARIO_LOGADO, cfg["rotulo_movimentacao"]))
                        conn.commit()
                        st.success(f"Entrada de {qtd_mov_brig_ent} un. de '{prod_nome_brig}' registrada! Novo saldo: {nova_qtd_brig}.")
                        st.rerun()
                    except Exception as ex_ent_brig:
                        conn.rollback()
                        st.error(f"Erro ao salvar entrada: {ex_ent_brig}")

    # ---------------------------------------------------------------
    # ABA 5: REGISTRO DE SAÍDA
    # ---------------------------------------------------------------
    elif aba_admin == "Registro de Saída":
        if df_raw_brig.empty:
            st.warning("Nenhum material cadastrado para movimentar.")
        else:
            with st.form(f"form_saida_{cfg['chave']}", clear_on_submit=True):
                col_bs1, col_bs2 = st.columns(2)
                data_mov_brig_s = col_bs1.date_input("Data da Movimentação:", value=datetime.today(), format="DD/MM/YYYY").strftime("%Y-%m-%d")
                opcao_prod_brig_sai = col_bs2.selectbox(
                    "Selecione o Material:",
                    df_raw_brig.index,
                    format_func=lambda x: f"{df_raw_brig.loc[x, 'codigo']} - {df_raw_brig.loc[x, 'item']} (Saldo: {df_raw_brig.loc[x, 'quantidade']})",
                    key=f"select_saida_{cfg['chave']}"
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
                                cursor.execute(f"UPDATE {T_PROD} SET quantidade = %s WHERE codigo = %s;", (nova_qtd_brig_s, prod_codigo_brig_s))
                                cursor.execute(f"""
                            INSERT INTO {T_MOV} (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
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
    elif aba_admin == "Histórico de Movimentação":
        df_mov_brig = pd.read_sql_query(f"SELECT data AS Data, tipo AS Tipo, codigo AS Código, item AS Item, quantidade AS Quantidade, responsavel AS Responsável, coordenacao AS Coordenação FROM {T_MOV} ORDER BY id DESC;", conn)
        if df_mov_brig.empty:
            st.info("Nenhuma movimentação registrada até o momento.")
        else:
            st.dataframe(df_mov_brig, use_container_width=True, hide_index=True)

    # ---------------------------------------------------------------
    # ABA 7: EDITAR / EXCLUIR ITEM
    # ---------------------------------------------------------------
    elif aba_admin == "Editar / Excluir Item":
        if df_raw_brig.empty:
            st.info(f"Nenhum material cadastrado no {cfg['nome_estoque']} ainda.")
        else:
            opcao_brig_edit = st.selectbox("Selecione para modificar:", df_raw_brig.index, format_func=lambda x: f"{df_raw_brig.loc[x, 'codigo']} - {df_raw_brig.loc[x, 'item']}")
            cod_atual_brig = df_raw_brig.loc[opcao_brig_edit, "codigo"]

            col_edb1, col_edb2 = st.columns(2)
            edit_cod_brig = col_edb1.text_input("Código:", value=df_raw_brig.loc[opcao_brig_edit, "codigo"])
            edit_item_brig = col_edb2.text_input("Nome:", value=df_raw_brig.loc[opcao_brig_edit, "item"])
            edit_qtd_brig = col_edb1.number_input("Quantidade (Ajuste):", min_value=0, value=int(df_raw_brig.loc[opcao_brig_edit, "quantidade"]))
            df_cat_edit = pd.read_sql_query(f"SELECT nome FROM {T_CAT} ORDER BY nome ASC;", conn)
            lista_categorias_edit = df_cat_edit["nome"].tolist()
            cat_atual_brig_edit = df_raw_brig.loc[opcao_brig_edit, "categoria"]
            if cat_atual_brig_edit and cat_atual_brig_edit not in lista_categorias_edit:
                lista_categorias_edit = [cat_atual_brig_edit] + lista_categorias_edit
            idx_cat_brig_edit = lista_categorias_edit.index(cat_atual_brig_edit) if cat_atual_brig_edit in lista_categorias_edit else 0
            edit_cat_brig = col_edb2.selectbox("Categoria:", lista_categorias_edit if lista_categorias_edit else ["Nenhuma categoria cadastrada"], index=idx_cat_brig_edit)
            edit_val_brig = st.number_input("Valor Unitário:", min_value=0.0, step=0.01, format="%.2f", value=float(df_raw_brig.loc[opcao_brig_edit, "valor_unitario"] or 0))

            col_bbtn1, col_bbtn2 = st.columns([1, 4])
            with col_bbtn1:
                if st.button("Salvar Alterações", type="primary"):
                    cursor = conn.cursor()
                    cursor.execute(f"""
                UPDATE {T_PROD} 
                SET codigo = %s, item = %s, quantidade = %s, categoria = %s, valor_unitario = %s 
                WHERE codigo = %s;
            """, (edit_cod_brig.strip(), edit_item_brig.strip(), edit_qtd_brig, edit_cat_brig.strip(), float(edit_val_brig), cod_atual_brig))
                    conn.commit()
                    st.success("Modificado com sucesso!")
                    st.rerun()

            with col_bbtn2:
                if st.button("Excluir Produto"):
                    cursor = conn.cursor()
                    cursor.execute(f"DELETE FROM {T_PROD} WHERE codigo = %s;", (cod_atual_brig,))
                    conn.commit()
                    st.warning("Removido com sucesso.")
                    st.rerun()


def estoque_setorial_usuario_ngi(cfg):
    """Tela do usuário da coordenação dona do estoque: consulta e pedido."""
    T_PROD, T_MOV, T_CAT = cfg["tabelas"]
    CARRINHO = f"carrinho_{cfg['chave']}"
    MSG_SUCESSO = f"msg_sucesso_{cfg['chave']}"
    cursor = conn.cursor()
    if (st.session_state.get("COORDENACAO_USUARIO_LOGADO") or "").strip().upper() != cfg["coordenacao"]:
        st.error(f"Acesso restrito à coordenação {cfg['coordenacao']}.")
    else:
        renderizar_banner(cfg["titulo"], cfg["subtitulo"])

        if st.session_state.get(MSG_SUCESSO):
            st.success("Sua solicitação foi encaminhada com sucesso!")
            del st.session_state[MSG_SUCESSO]

        df_disp = pd.read_sql_query(f"SELECT codigo, item, quantidade, categoria, valor_unitario FROM {T_PROD} WHERE quantidade > 0 ORDER BY codigo ASC;", conn)

        if df_disp.empty:
            st.info(f"Nenhum material disponível no {cfg['nome_estoque']} no momento.")
        else:
            st.markdown('<h3 style="font-size: 18px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center;"><span style="display: inline-block; width: 6px; height: 18px; background-color: #147746; margin-right: 8px; border-radius: 2px;"></span>Filtros de Consulta</h3>', unsafe_allow_html=True)

            termo_busca_brig = st.text_input("Buscar por Nome do Material ou Código:", placeholder="Digite o termo para pesquisar...", key=f"busca_material_{cfg['chave']}")
            df_disp_filtrado = df_disp.copy()
            if termo_busca_brig:
                df_disp_filtrado = df_disp_filtrado[
                    df_disp_filtrado['item'].str.contains(termo_busca_brig, case=False, na=False) |
                    df_disp_filtrado['codigo'].str.contains(termo_busca_brig, case=False, na=False)
                ]

            st.markdown("<br>", unsafe_allow_html=True)
            st.dataframe(df_disp_filtrado.rename(columns={"codigo": "Código", "item": "Item", "quantidade": "Quantidade", "categoria": "Categoria"}).drop(columns=["valor_unitario"]), use_container_width=True, hide_index=True)

            if CARRINHO not in st.session_state:
                st.session_state[CARRINHO] = []

            with st.container(border=True):
                cabecalho_pedido_ngi(cfg["titulo_pedido"], "Siga os 3 passos. Todos os itens do carrinho seguem juntos em um único pedido.")
                passo_pedido_ngi(1, 'Escolha o material e clique em "Adicionar ao carrinho"')

                col_add_br1, col_add_br2, col_add_br3 = st.columns([3, 1, 1.3])
                opcao_sol_brig = col_add_br1.selectbox(
                    "Material:",
                    df_disp.index,
                    format_func=lambda x: f"{df_disp.loc[x, 'codigo']} - {df_disp.loc[x, 'item']} (Saldo: {df_disp.loc[x, 'quantidade']})",
                    key=f"select_material_{cfg['chave']}"
                )
                qtd_sol_brig = col_add_br2.number_input("Quantidade:", min_value=1, max_value=int(df_disp.loc[opcao_sol_brig, "quantidade"]), value=1, step=1, key=f"qtd_material_{cfg['chave']}")
                col_add_br3.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                with col_add_br3:
                    with st.container(key=cfg["chave_botao_adicionar"]):
                        clicou_add_4 = st.button("Adicionar ao carrinho", icon=":material/add_shopping_cart:", key=f"add_carrinho_{cfg['chave']}", use_container_width=True)
                if clicou_add_4:
                    cod_sel_brig = df_disp.loc[opcao_sol_brig, "codigo"]
                    nome_sel_brig = df_disp.loc[opcao_sol_brig, "item"]
                    adicionar_item_carrinho_ngi(CARRINHO, {"codigo": cod_sel_brig, "item": nome_sel_brig, "quantidade": int(qtd_sol_brig)}, df_disp.loc[opcao_sol_brig, "quantidade"])

                if st.session_state[CARRINHO]:
                    passo_pedido_ngi(2, "Confira o carrinho", detalhe=texto_qtd_itens_ngi(len(st.session_state[CARRINHO])))
                    renderizar_carrinho_ngi(CARRINHO, cfg["prefixo_botoes"])

                    passo_pedido_ngi(3, "Adicione uma observação, se precisar, e envie")
                    obs_sol_brig = st.text_input("Observações (opcional):", placeholder=cfg["exemplo_observacao"], key=f"obs_carrinho_{cfg['chave']}")

                    if st.button(f"Enviar solicitação ({texto_qtd_itens_ngi(len(st.session_state[CARRINHO]))})", type="primary", icon=":material/send:", key=f"enviar_carrinho_{cfg['chave']}"):
                        try:
                            lote_id_brig = str(uuid.uuid4())
                            cursor = conn.cursor()
                            for item_carr_br in st.session_state[CARRINHO]:
                                cursor.execute("""
                        INSERT INTO solicitacoes_almoxarifado 
                        (tipo, referencia_codigo, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, status, observacao, lote_id, origem_estoque)
                        VALUES ('MATERIAL', %s, %s, %s, %s, %s, %s, 'PENDENTE', %s, %s, %s);
                    """, (item_carr_br["codigo"], item_carr_br["item"], item_carr_br["quantidade"], st.session_state.NOME_USUARIO_LOGADO, st.session_state.EMAIL_USUARIO_LOGADO, cfg["coordenacao_pedido"], obs_sol_brig.strip(), lote_id_brig, cfg["origem"]))
                            conn.commit()
                            st.session_state[CARRINHO] = []
                            st.session_state[MSG_SUCESSO] = True
                            st.rerun()
                        except Exception as ex_brig:
                            conn.rollback()
                            st.error(f"Erro ao enviar solicitação: {ex_brig}")
                else:
                    carrinho_vazio_ngi(cfg["chave"], campos=("Observações (opcional):",))


def tela_trocar_senha_obrigatoria_ngi():
    """Quem entrou com senha fraca cria uma nova antes de usar o sistema."""
    _, col_centro, _ = st.columns([1, 1.3, 1])
    with col_centro:
        st.markdown("<div style='height:40px'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown(
                '<div class="ngi-stock-heading"><h3>Crie uma nova senha</h3>'
                f'<p>Olá, {html.escape(str(st.session_state.get("NOME_USUARIO_LOGADO", "")))}. Sua senha atual é muito fácil de adivinhar. '
                f'Para proteger o sistema, crie uma senha nova com pelo menos {TAMANHO_MINIMO_SENHA_NGI} caracteres antes de continuar.</p></div>',
                unsafe_allow_html=True)
            with st.form("form_troca_senha_obrigatoria"):
                nova = st.text_input("Nova senha", type="password")
                confirmacao = st.text_input("Confirmar nova senha", type="password")
                salvar = st.form_submit_button("Salvar e continuar", type="primary", use_container_width=True)
            if salvar:
                problema = problema_nova_senha_ngi(nova, confirmacao)
                if problema:
                    st.error(problema)
                else:
                    try:
                        with conn.cursor() as cursor_troca:
                            cursor_troca.execute(
                                "UPDATE usuarios SET senha = %s, trocar_senha = FALSE WHERE LOWER(email) = %s;",
                                (gerar_hash_senha(nova.strip()), str(st.session_state.EMAIL_USUARIO_LOGADO).lower()))
                        conn.commit()
                        st.session_state.TROCAR_SENHA_OBRIGATORIO = False
                        st.toast("Senha alterada com sucesso!")
                        st.rerun()
                    except Exception as erro_troca:
                        conn.rollback()
                        st.error(f"Não foi possível salvar a nova senha: {erro_troca}")
            if st.button("Sair do sistema", use_container_width=True, key="sair_troca_senha"):
                try:
                    with conn.cursor() as cursor_sair:
                        cursor_sair.execute("DELETE FROM sessoes_login WHERE token = %s;", (st.session_state.get("SESSION_TOKEN", ""),))
                    conn.commit()
                except Exception:
                    conn.rollback()
                try:
                    cookie_controller.remove("session")
                except Exception:
                    pass
                for chave in ("NOME_USUARIO_LOGADO", "PERFIL_USUARIO_LOGADO", "EMAIL_USUARIO_LOGADO", "SESSION_TOKEN"):
                    st.session_state[chave] = ""
                st.session_state.autenticado = False
                st.session_state.TROCAR_SENHA_OBRIGATORIO = False
                st.rerun()


# Tabelas que NÃO entram no backup (dados temporários de login).
TABELAS_FORA_DO_BACKUP_NGI = {"sessoes_login", "recuperacoes_senha", "config_sistema", "backups_sistema"}
BACKUPS_GUARDADOS_NGI = 7          # quantos backups diários ficam guardados no sistema
HORA_BACKUP_AUTOMATICO_NGI = 6     # a partir de que hora (Brasília) o backup do dia é feito


def gerar_backup_excel_ngi(conexao, gerado_por="Backup automático"):
    """Uma aba por tabela do banco. Fica de fora: fotos, senhas e sessões.
    Recebe a conexão para poder rodar também em segundo plano (sem tela)."""
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    with conexao.cursor() as cursor_bkp:
        cursor_bkp.execute("""
            SELECT table_name, column_name, data_type FROM information_schema.columns
            WHERE table_schema = 'public' ORDER BY table_name, ordinal_position;
        """)
        colunas_por_tabela = {}
        for tabela, coluna, tipo in cursor_bkp.fetchall():
            if tabela in TABELAS_FORA_DO_BACKUP_NGI or tipo == "bytea":
                continue
            if tabela == "usuarios" and coluna == "senha":
                continue
            colunas_por_tabela.setdefault(tabela, []).append(coluna)
    resumo = []
    destino = io.BytesIO()
    with pd.ExcelWriter(destino, engine="openpyxl") as writer:
        pd.DataFrame().to_excel(writer, sheet_name="Resumo", index=False)
        for tabela, colunas in colunas_por_tabela.items():
            lista = ", ".join('"' + c.replace('"', '""') + '"' for c in colunas)
            df_tabela = pd.read_sql_query(f'SELECT {lista} FROM "{tabela}";', conexao)
            for coluna in df_tabela.columns:
                if isinstance(df_tabela[coluna].dtype, pd.DatetimeTZDtype):
                    df_tabela[coluna] = df_tabela[coluna].dt.tz_localize(None)
            df_tabela.to_excel(writer, sheet_name=tabela[:31], index=False)
            ws = writer.sheets[tabela[:31]]
            for indice, coluna in enumerate(df_tabela.columns, start=1):
                celula = ws.cell(row=1, column=indice)
                celula.font = Font(bold=True, color="FFFFFF")
                celula.fill = PatternFill("solid", fgColor="147746")
                ws.column_dimensions[get_column_letter(indice)].width = min(45, max(12, len(str(coluna)) + 4))
            ws.freeze_panes = "A2"
            resumo.append((tabela, len(df_tabela)))
        ws_resumo = writer.sheets["Resumo"]
        agora_br = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
        ws_resumo["A1"] = "Backup do SIGAL — NGI Carajás"
        ws_resumo["A1"].font = Font(bold=True, size=14, color="147746")
        ws_resumo["A2"] = f"Gerado em {agora_br} ({gerado_por})"
        ws_resumo["A3"] = "Não incluídos por segurança: fotos, senhas e sessões de login."
        ws_resumo["A5"], ws_resumo["B5"] = "Tabela", "Registros"
        ws_resumo["A5"].font = ws_resumo["B5"].font = Font(bold=True)
        for linha, (tabela, total) in enumerate(resumo, start=6):
            ws_resumo.cell(row=linha, column=1, value=tabela)
            ws_resumo.cell(row=linha, column=2, value=total)
        ws_resumo.column_dimensions["A"].width = 32
        ws_resumo.column_dimensions["B"].width = 12
    return destino.getvalue(), sum(total for _, total in resumo), len(resumo)


def painel_backup_ngi():
    """Mostra os backups automáticos (feitos todo dia, sem ninguém precisar clicar)."""
    with st.container(border=True):
        st.markdown('<div class="ngi-stock-heading"><h3>Backup automático</h3>'
                    f'<p>Todo dia, a partir das {HORA_BACKUP_AUTOMATICO_NGI}h, o sistema gera sozinho um Excel com todas as tabelas, '
                    'envia por e-mail e guarda aqui os últimos ' + str(BACKUPS_GUARDADOS_NGI) + ' dias. '
                    'Fotos, senhas e sessões de login não entram no arquivo.</p></div>', unsafe_allow_html=True)
        try:
            df_bkp = pd.read_sql_query(
                "SELECT id, criado_em, tabelas, registros, enviado_para, situacao_email FROM backups_sistema ORDER BY criado_em DESC;", conn)
        except Exception:
            conn.rollback()
            df_bkp = pd.DataFrame()
        if df_bkp.empty:
            st.info("O primeiro backup automático será feito hoje, a partir das "
                    f"{HORA_BACKUP_AUTOMATICO_NGI}h (ou nos próximos minutos, se já passou desse horário).")
            return
        ultimo = df_bkp.iloc[0]
        quando = pd.to_datetime(ultimo["criado_em"])
        situacao = str(ultimo["situacao_email"] or "")
        texto_email = f"enviado para {ultimo['enviado_para']}" if situacao == "enviado" else f"e-mail não enviado ({situacao})"
        st.caption(f"Último backup: {quando.strftime('%d/%m/%Y às %H:%M')} · {int(ultimo['tabelas'])} tabelas, "
                   f"{int(ultimo['registros'])} registros · {texto_email}.")
        col_sel, col_bt = st.columns([2, 1], vertical_alignment="bottom")
        opcao = col_sel.selectbox(
            "Baixar um backup guardado:", df_bkp.index,
            format_func=lambda x: pd.to_datetime(df_bkp.loc[x, "criado_em"]).strftime("%d/%m/%Y às %H:%M"),
            key="backup_escolhido")
        id_bkp = int(df_bkp.loc[opcao, "id"])
        if st.session_state.get("backup_baixar_id") != id_bkp:
            with conn.cursor() as cursor_arq:
                cursor_arq.execute("SELECT arquivo FROM backups_sistema WHERE id = %s;", (id_bkp,))
                registro = cursor_arq.fetchone()
            st.session_state.backup_baixar_id = id_bkp
            st.session_state.backup_baixar_dados = bytes(registro[0]) if registro and registro[0] is not None else b""
        col_bt.download_button(
            "Baixar (Excel)", data=st.session_state.backup_baixar_dados,
            file_name=f"Backup_SIGAL_{pd.to_datetime(df_bkp.loc[opcao, 'criado_em']).strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:", type="primary", use_container_width=True, key="baixar_backup",
            disabled=not st.session_state.backup_baixar_dados)


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
    # Backups automáticos diários (guarda os 7 mais recentes)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backups_sistema (
            id SERIAL PRIMARY KEY,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            arquivo BYTEA,
            tabelas INTEGER,
            registros INTEGER,
            enviado_para TEXT,
            situacao_email TEXT
        );
    """)
    # Marca quem precisa trocar a senha no próximo acesso (senha fraca).
    cursor.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS trocar_senha BOOLEAN DEFAULT FALSE;")

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
    # NOVO MÓDULO: MATERIAIS PESQUISA (estoque separado, acesso restrito à COLMOP)
    # =========================================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos_pesquisa (
            codigo TEXT PRIMARY KEY,
            item TEXT,
            quantidade INTEGER,
            categoria TEXT,
            valor_unitario REAL
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes_pesquisa (
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
        CREATE TABLE IF NOT EXISTS categorias_pesquisa (
            nome TEXT PRIMARY KEY
        );
    """)

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
    return {"lock": threading.Lock(), "iniciado": False}


INTERVALO_ROTINAS_NGI = 1800   # segundos entre uma verificação e outra (30 min)


def agendar_lembretes_ngi():
    """Liga, uma única vez por servidor, o relógio interno que roda sozinho em
    segundo plano: lembrete de devolução em atraso e backup diário.
    Não depende de ninguém estar usando o sistema depois que ele subiu."""
    estado = estado_lembretes_ngi()
    with estado["lock"]:
        if estado["iniciado"]:
            return
        dsn = os.environ.get("POSTGRES_URL") or st.secrets["postgres"]["url"]
        estado["iniciado"] = True

    def rodar_uma_vez():
        conexao = None
        try:
            conexao = psycopg2.connect(dsn, connect_timeout=10)
            # Trava: se houver mais de um servidor, só um executa por vez.
            with conexao.cursor() as trava:
                trava.execute("SELECT pg_try_advisory_lock(684217903);")
                pode_executar = trava.fetchone()[0]
            conexao.commit()
            if pode_executar:
                try:
                    verificar_e_notificar_emprestimos_atrasados(conexao)
                    executar_backup_automatico_ngi(conexao)
                finally:
                    with conexao.cursor() as trava:
                        trava.execute("SELECT pg_advisory_unlock(684217903);")
                    conexao.commit()
        except Exception as erro:
            print(f"[ROTINAS] Falha no processamento em segundo plano: {type(erro).__name__}: {erro}")
        finally:
            if conexao is not None:
                try:
                    conexao.close()
                except Exception:
                    pass

    def relogio():
        time.sleep(20)   # deixa o sistema terminar de subir
        while True:
            rodar_uma_vez()
            time.sleep(INTERVALO_ROTINAS_NGI)

    try:
        threading.Thread(target=relogio, name="ngi-rotinas", daemon=True).start()
    except Exception:
        with estado["lock"]:
            estado["iniciado"] = False
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

    def enviar_email_notificacao(destinatario, assunto, corpo_html, anexos=None):
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
                    "text": corpo_texto,
                    **({"attachments": [
                        {"filename": nome_anexo, "content": base64.b64encode(conteudo_anexo).decode("utf-8")}
                        for nome_anexo, conteudo_anexo in anexos
                    ]} if anexos else {})
                },
                timeout=60 if anexos else 10
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

    # =============================================================================
    # BACKUP AUTOMÁTICO DIÁRIO (roda sozinho, 1x por dia, em segundo plano)
    # =============================================================================
    # Destino do e-mail: variável BACKUP_EMAILS no Render (vários e-mails
    # separados por vírgula). Sem ela, vai para todos os administradores.
    def destinatarios_backup_ngi(conexao):
        configurados = os.environ.get("BACKUP_EMAILS", "")
        if not configurados:
            try:
                configurados = st.secrets["backup"]["emails"]
            except Exception:
                configurados = ""
        lista = [e.strip() for e in str(configurados).replace(";", ",").split(",") if e.strip()]
        if lista:
            return lista
        with conexao.cursor() as cursor_dest:
            cursor_dest.execute("SELECT email FROM usuarios WHERE perfil = 'Administrador' AND email IS NOT NULL AND email <> 'admin@ngi.com';")
            return [linha[0] for linha in cursor_dest.fetchall()]

    def executar_backup_automatico_ngi(conexao, forcar=False):
        agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
        hoje_str = agora.date().isoformat()
        try:
            with conexao.cursor() as cursor_bkp:
                # O relógio pode rodar antes da primeira tela criar as tabelas.
                cursor_bkp.execute("""
                    CREATE TABLE IF NOT EXISTS backups_sistema (
                        id SERIAL PRIMARY KEY, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP, arquivo BYTEA,
                        tabelas INTEGER, registros INTEGER, enviado_para TEXT, situacao_email TEXT);
                """)
                cursor_bkp.execute("CREATE TABLE IF NOT EXISTS config_sistema (chave TEXT PRIMARY KEY, valor TEXT);")
                conexao.commit()
                cursor_bkp.execute("SELECT valor FROM config_sistema WHERE chave = 'ultimo_backup_automatico';")
                registro = cursor_bkp.fetchone()
            conexao.rollback()
            if not forcar and ((registro and registro[0] == hoje_str) or agora.hour < HORA_BACKUP_AUTOMATICO_NGI):
                return False

            arquivo, registros, tabelas = gerar_backup_excel_ngi(conexao)
            nome_arquivo = f"Backup_SIGAL_{agora.strftime('%Y%m%d_%H%M')}.xlsx"

            destinos = destinatarios_backup_ngi(conexao)
            enviados, falhas = [], []
            for destino in destinos:
                sucesso, erro = enviar_email_notificacao(
                    destino,
                    f"Backup diário do SIGAL — {agora.strftime('%d/%m/%Y')}",
                    f"""
                <p>Segue em anexo o backup automático do Sistema de Gestão de Almoxarifado (SIGAL), gerado em
                {agora.strftime('%d/%m/%Y às %H:%M')}.</p>
                <p><b>Tabelas:</b> {tabelas}<br><b>Registros:</b> {registros}</p>
                <p>Guarde este arquivo em local seguro. Fotos, senhas e sessões de login não fazem parte do backup.</p>
                """,
                    anexos=[(nome_arquivo, arquivo)]
                )
                (enviados if sucesso else falhas).append(destino if sucesso else f"{destino}: {erro}")
            if not destinos:
                situacao = "sem destinatário configurado"
            elif falhas and not enviados:
                situacao = "falha: " + "; ".join(falhas)[:300]
            else:
                situacao = "enviado"

            with conexao.cursor() as cursor_bkp:
                cursor_bkp.execute(
                    "INSERT INTO backups_sistema (criado_em, arquivo, tabelas, registros, enviado_para, situacao_email) VALUES (%s, %s, %s, %s, %s, %s);",
                    (agora.replace(tzinfo=None), psycopg2.Binary(arquivo), tabelas, registros, ", ".join(enviados) or "—", situacao))
                cursor_bkp.execute(
                    "DELETE FROM backups_sistema WHERE id NOT IN (SELECT id FROM backups_sistema ORDER BY criado_em DESC LIMIT %s);",
                    (BACKUPS_GUARDADOS_NGI,))
                cursor_bkp.execute("""
                INSERT INTO config_sistema (chave, valor) VALUES ('ultimo_backup_automatico', %s)
                ON CONFLICT (chave) DO UPDATE SET valor = %s;
            """, (hoje_str, hoje_str))
            conexao.commit()
            print(f"[BACKUP] Backup diário gerado ({tabelas} tabelas, {registros} registros) - e-mail: {situacao}")
            return True
        except Exception as erro_bkp:
            conexao.rollback()
            print(f"[BACKUP] Erro no backup automático: {erro_bkp}")
            return False

    # Lembretes e backup rodam em segundo plano (ver agendar_lembretes_ngi).
    # O relógio é ligado no primeiro acesso ao sistema (inclusive na tela de login).
    try:
        agendar_lembretes_ngi()
    except Exception as erro_relogio:
        print(f"[ROTINAS] Não foi possível iniciar o relógio interno: {erro_relogio}")


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

                        cursor_sessao.execute("SELECT coordenacao, COALESCE(trocar_senha, FALSE) FROM usuarios WHERE LOWER(email) = %s;", (email_sessao.lower(),))
                        resultado_coord_sessao = cursor_sessao.fetchone()
                        st.session_state.COORDENACAO_USUARIO_LOGADO = resultado_coord_sessao[0] if resultado_coord_sessao else None
                        st.session_state.TROCAR_SENHA_OBRIGATORIO = bool(resultado_coord_sessao[1]) if resultado_coord_sessao else False

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
                <img src="app/static/logo_icmbio.webp" width="280">
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
                            problema_reset = problema_nova_senha_ngi(nova_senha_reset, confirmar_senha_reset)
                            if problema_reset:
                                st.error(problema_reset)
                            else:
                                try:
                                    cursor_reset.execute(
                                        "UPDATE usuarios SET senha = %s, trocar_senha = FALSE WHERE LOWER(email) = %s;",
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
                st.markdown('<style>\n/* Este tema existe somente na tela de login; não altera o sistema autenticado. */\n.stApp, [data-testid="stAppViewContainer"] {\n --text-color:#244238; --background-color:#fcfcfa; --secondary-background-color:#f1f4f1;\n --primary-color:#147746; background:#fcfcfa !important;\n}\n[data-testid="stHeader"], [data-testid="stSidebar"] { display:none; }\n[data-testid="stMainBlockContainer"], .main .block-container {\n width:45% !important; max-width:none !important; margin-left:55% !important;\n margin-right:0 !important; padding:36px clamp(28px,4vw,80px) !important;\n min-height:100vh; display:flex; flex-direction:column; justify-content:center; box-sizing:border-box;\n}\n.st-key-ngi_login_panel { width:100%; max-width:520px; margin:0 auto; }\n.ngi-login-hero { position:fixed; left:0; top:0; bottom:0; width:55%;\n background-color:#0b3024; background-position:center; background-size:cover;\n display:flex; flex-direction:column; justify-content:space-between;\n padding:42px clamp(32px,4vw,72px); box-sizing:border-box; z-index:1;\n}\n.ngi-login-brand { align-self:flex-start; display:flex; align-items:center; gap:12px;\n padding:12px 18px; border:1px solid #ffffff60; border-radius:16px;\n background:#ffffff12; color:#fff !important; font-size:18px; }\n.ngi-login-brand svg { width:28px; height:28px; }\n.ngi-login-message { margin-top:auto; padding-top:90px; }\n.ngi-login-eyebrow { color:#ebf6ee !important; font-size:12px; font-weight:600; letter-spacing:3px; margin-bottom:18px; }\n.stMarkdown .ngi-login-hero h1 { font-family:Georgia,\'Times New Roman\',serif !important;\n color:white !important; font-weight:600 !important; font-size:clamp(38px,4.7vw,76px) !important;\n line-height:1.04 !important; letter-spacing:-1.5px; padding:0; margin:0 0 20px; }\n.stMarkdown .ngi-login-hero p { color:#acdfbd !important; font-size:clamp(16px,1.5vw,23px);\n line-height:1.5; max-width:530px; margin:0; }\n.ngi-login-accent { width:54px; height:3px; background:#38ae76; margin:24px 0 36px; }\n.ngi-login-caption { color:#d5e8dc !important; font-size:11px; letter-spacing:2px; } .stApp .stMarkdown .ngi-login-hero .ngi-login-photo-credit, .stApp .stMarkdown .ngi-login-hero .ngi-login-photo-credit * { color:#ffffff !important; -webkit-text-fill-color:#ffffff !important; opacity:1 !important; font-size:12px !important; font-weight:500 !important; text-shadow:0 1px 3px #000 !important; }\n.ngi-login-heading { text-align:center; margin-bottom:16px; }\n.ngi-login-heading img { display:block; width:135px; height:auto; margin:0 auto 22px; }\n.stMarkdown .ngi-login-heading h2 { font-family:Georgia,\'Times New Roman\',serif !important;\n color:#0b3024 !important; font-size:clamp(30px,2.9vw,46px) !important;\n font-weight:700 !important; letter-spacing:-1px; margin:0 0 8px; padding:0; line-height:1.15; }\n.stMarkdown .ngi-login-heading p { color:#63766b !important; font-size:15px; margin:0; }\n.stApp .stMarkdown .ngi-login-heading h2 .ngi-login-sigla { color:#147746 !important; }\n.st-key-ngi_login_panel [data-testid="stForm"] { border:0 !important; padding:0 !important; background:transparent; }\n.st-key-ngi_login_panel [data-testid="stWidgetLabel"] p { color:#344f43 !important; font-weight:600; font-size:14px; }\n.st-key-ngi_login_panel [data-baseweb="input"] { border:1px solid #d3dcd5 !important; border-radius:10px; background:white; min-height:50px; }\n.st-key-ngi_login_panel input { background:transparent !important; color:#203d30 !important; font-size:15px; }\n.st-key-ngi_login_panel [data-baseweb="input"]:focus-within { border-color:#147746 !important; box-shadow:0 0 0 3px #14774615; }\n.st-key-ngi_login_panel [data-testid="stFormSubmitButton"] button { background:#147746 !important;\n border-color:#147746 !important; min-height:52px; border-radius:10px; box-shadow:0 6px 16px #0d573720; }\n.st-key-ngi_login_panel [data-testid="stFormSubmitButton"] button p { color:white !important; font-size:16px; font-weight:700; }\n.st-key-ngi_login_panel [data-testid="stFormSubmitButton"] button:hover { background:#0c6036 !important; }\n.st-key-ngi_login_panel [data-testid="stButton"] button { background:transparent !important;\n border:none !important; box-shadow:none !important; min-height:32px; padding:0; justify-content:flex-end; }\n.st-key-ngi_login_panel [data-testid="stButton"] button p { color:#187246 !important; font-size:13px; text-decoration:underline; }\n.stMarkdown .ngi-login-restricted { display:flex; gap:8px; align-items:center; justify-content:center;\n color:#7a897f !important; font-size:12px; margin:18px 0; }\n.ngi-login-restricted svg { width:16px; height:16px; }\n.stMarkdown .ngi-login-footer { border-top:1px solid #e1e7e2; padding-top:18px;\n text-align:center; color:#839087 !important; font-size:11px; margin-top:20px; }\n@media(max-width:850px) {\n .ngi-login-hero { position:relative; width:100%; min-height:260px; padding:24px; border-radius:0; }\n .ngi-login-message { padding-top:35px; }\n .stMarkdown .ngi-login-hero h1 { font-size:34px !important; max-width:470px; }\n .ngi-login-hero h1 br { display:none; }\n .ngi-login-eyebrow, .ngi-login-caption, .ngi-login-accent, .ngi-login-hero p { display:none; }\n [data-testid="stMainBlockContainer"], .main .block-container { width:100% !important;\n margin:0 !important; padding:0 0 28px !important; min-height:100vh; justify-content:flex-start; }\n .st-key-ngi_login_panel { padding:24px; box-sizing:border-box; }\n .ngi-login-heading img { width:100px; margin-bottom:16px; }\n .ngi-login-heading { margin-bottom:8px; }\n}\n@media(max-height:700px) and (min-width:851px) {\n .ngi-login-heading img { width:100px; margin-bottom:12px; }\n .ngi-login-footer { margin-top:10px !important; }\n .ngi-login-hero { padding-top:28px; padding-bottom:28px; }\n .ngi-login-message { padding-top:24px; }\n}\n</style>\n<style>\n/* Compatibilidade com os elementos internos das diferentes versões do Streamlit. */\n.ngi-login-hero h1 [data-heading-text], .ngi-login-hero h1 span {\n    color:#fff !important; font-family:Georgia,\'Times New Roman\',serif !important;\n}\n.ngi-login-heading h2 [data-heading-text], .ngi-login-heading h2 span {\n    color:#0b3024 !important; font-family:Georgia,\'Times New Roman\',serif !important;\n}\n.ngi-login-hero [data-testid="stHeaderActionElements"],\n.ngi-login-heading [data-testid="stHeaderActionElements"] { display:none; }\n.st-key-ngi_login_panel [data-testid="stTextInputRootElement"] {\n    border:1px solid #d3dcd5 !important; border-radius:10px; background:#fff !important; min-height:50px;\n}\n.st-key-ngi_login_panel [data-testid="stTextInputRootElement"]:focus-within {\n    border-color:#147746 !important; box-shadow:0 0 0 3px #14774615;\n}\n.stApp .st-key-ngi_login_panel [data-testid="stFormSubmitButton"] button[kind] {\n    background:#147746 !important; border-color:#147746 !important;\n}\n.stApp .st-key-ngi_login_panel [data-testid="stFormSubmitButton"] button[kind]:hover {\n    background:#0c6036 !important; border-color:#0c6036 !important;\n}\n</style>\n', unsafe_allow_html=True)
                st.markdown('<section class="ngi-login-hero" style="background-image:linear-gradient(180deg,rgba(5,31,24,.08) 15%,rgba(5,31,24,.4) 65%,rgba(5,31,24,.76)),url(app/static/login_floresta.webp)"><div class="ngi-login-brand"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M20 3C6 1 2 8 5 16c8 4 17-1 15-13ZM3 21 17 7"/></svg>NGI Carajás</div><div class="ngi-login-message"><div class="ngi-login-eyebrow">GESTÃO DE ALMOXARIFADO</div><h1>Organização que <br>apoia a <br>conservação.</h1><p>Materiais, pessoas e recursos conectados ao cuidado com a natureza.</p><div class="ngi-login-accent"></div></div><div class="ngi-login-caption">Núcleo de Gestão Integrada de Carajás</div><span class="ngi-login-photo-credit" style="position:absolute;right:14px;bottom:12px;font-size:11px;line-height:1.4;font-weight:500;letter-spacing:0;color:#ffffff !important;-webkit-text-fill-color:#ffffff !important;opacity:1 !important;text-shadow:0 1px 3px rgba(0,0,0,.95);">Foto: João Marcos Rosa</span></section>', unsafe_allow_html=True)
                with st.container(key="ngi_login_panel"):
                    with st.container():
                        st.markdown('<div class="ngi-login-heading"><img src="app/static/logo_icmbio.webp" alt="ICMBio — Instituto Chico Mendes de Conservação da Biodiversidade"><h2>Bem-vindo de volta ao <span class="ngi-login-sigla">SIGAL</span></h2><p>Sistema de Gestão de Almoxarifado do NGI Carajás</p></div>', unsafe_allow_html=True)

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

                                        # Senha fraca (ex.: 123): obriga a criar uma nova antes de usar o sistema.
                                        precisa_trocar = senha_fraca_ngi(senha_input)
                                        st.session_state.TROCAR_SENHA_OBRIGATORIO = precisa_trocar
                                        try:
                                            cursor.execute("UPDATE usuarios SET trocar_senha = %s WHERE email = %s;", (precisa_trocar, email_banco))
                                            conn.commit()
                                        except Exception:
                                            conn.rollback()

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

                        st.markdown('<p class="ngi-login-restricted"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4m-4 4v3"/></svg>Acesso restrito a usuários cadastrados</p><p class="ngi-login-footer">ICMBio · NGI Carajás</p><div class="ngi-login-uc-logos" style="width:100%;margin:32px auto 0;text-align:center;"><img src="app/static/logos_unidades.webp" alt="Logos das unidades de conservação do NGI Carajás: Campos Ferruginosos, Carajás, Tapirapé-Aquiri, Igarapé Gelado, Itacaiúnas e Tapirapé" style="display:block;width:100%;max-width:100%;height:auto;object-fit:contain;margin:0 auto;" /></div>', unsafe_allow_html=True)

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
            # --- MENU LATERAL ---
            label_solicitacoes = "Solicitações"

            st.markdown(CSS_VISUAL_NGI, unsafe_allow_html=True)

            # Senha fraca: só libera o sistema depois de criar uma senha nova.
            if st.session_state.get("TROCAR_SENHA_OBRIGATORIO"):
                manter_sessao_ngi()
                tela_trocar_senha_obrigatoria_ngi()
                st.stop()

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
                    if coordenacao_logada_normalizada == "COLMOP":
                        opcoes_menu_user.append("Materiais Pesquisa")
                        icones_menu_user.append("binoculars")

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

                    escolha = menu_lateral_admin_ngi(label_solicitacoes)

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
                # O próximo login começa de novo pelo Painel Geral.
                st.session_state.pop("menu_admin_escolha", None)
                st.session_state.pop("menu_cadastros_aberto", None)
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

                        painel_pendencias_devolucao_ngi(st.session_state.EMAIL_USUARIO_LOGADO, st.session_state.NOME_USUARIO_LOGADO)

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
            # ESTOQUES SETORIAIS: MATERIAIS BRIGADA E MATERIAIS PESQUISA
            # (código único em estoque_setorial_admin_ngi / estoque_setorial_usuario_ngi)
            # =========================================================================
            elif escolha == "Materiais Brigada" and st.session_state.PERFIL_USUARIO_LOGADO != "Usuário Comum":
                estoque_setorial_admin_ngi(ESTOQUE_BRIGADA_NGI)

            elif escolha == "Materiais Brigada" and st.session_state.PERFIL_USUARIO_LOGADO == "Usuário Comum":
                estoque_setorial_usuario_ngi(ESTOQUE_BRIGADA_NGI)

            elif escolha == "Materiais Pesquisa" and st.session_state.PERFIL_USUARIO_LOGADO != "Usuário Comum":
                estoque_setorial_admin_ngi(ESTOQUE_PESQUISA_NGI)

            elif escolha == "Materiais Pesquisa" and st.session_state.PERFIL_USUARIO_LOGADO == "Usuário Comum":
                estoque_setorial_usuario_ngi(ESTOQUE_PESQUISA_NGI)


            # =========================================================================
            # NOVO MÓDULO: LIVROS E PRODUTOS — GESTÃO (ADMINISTRADOR)
            # =========================================================================
            elif escolha == "Livros e Produtos" and st.session_state.PERFIL_USUARIO_LOGADO != "Usuário Comum":
                renderizar_banner("Livros e Produtos", "Catálogo de livros e livretos disponíveis, com foto de referência")
                df_raw_livros = pd.read_sql_query("SELECT codigo, titulo, tipo, quantidade, NULL::bytea AS foto FROM produtos_livros ORDER BY titulo ASC;", conn)
                renderizar_indicadores_acervo_ngi(df_raw_livros)

                aba_livros_admin = option_menu(
                    menu_title=None,
                    options=["Itens Disponíveis", "Fazer Solicitação", "Cadastrar Item", "Registro de Entrada", "Registro de Saída", "Histórico de Movimentação", "Editar / Excluir Item"],
                    icons=["images", "cart-plus", "plus-circle", "arrow-down-circle", "arrow-up-circle", "journal-text", "pencil-square"],
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
                # FAZER SOLICITAÇÃO (administrador pedindo para si, mesmo fluxo
                # de aprovação do usuário comum)
                # ---------------------------------------------------------------
                elif aba_livros_admin == "Fazer Solicitação":
                    st.caption("Sua solicitação seguirá o fluxo normal de aprovação, como qualquer outra.")
                    if st.session_state.get("msg_sucesso_livros"):
                        st.success("Sua solicitação foi encaminhada com sucesso!")
                        del st.session_state["msg_sucesso_livros"]
                    df_disp_livros_admin = df_raw_livros[df_raw_livros["quantidade"] > 0].reset_index(drop=True)
                    if df_disp_livros_admin.empty:
                        st.info("Nenhum livro ou produto disponível no momento.")
                    else:
                        formulario_solicitacao_livros_ngi(df_disp_livros_admin)

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
                        formulario_solicitacao_livros_ngi(df_disp_livros)

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

                        painel_pendencias_devolucao_ngi(st.session_state.EMAIL_USUARIO_LOGADO, st.session_state.NOME_USUARIO_LOGADO)

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
                                                elif origem_sol == "PESQUISA":
                                                    tabela_estoque, tabela_movimentacao, coluna_item_mov = "produtos_pesquisa", "movimentacoes_pesquisa", "item"
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
                        coord_novo_user = st.selectbox("Coordenação:", lista_coord_user, help="Coordenação à qual a pessoa está vinculada. Algumas telas do sistema (como Materiais Brigada e Materiais Pesquisa) só ficam visíveis para coordenações específicas.")
                
                        if st.form_submit_button("Salvar", type="primary"):
                            if n and e:
                                try:
                                    senha_final = s if s else "123"
                                    cursor = conn.cursor()
                                    cursor.execute("""
                                INSERT INTO usuarios (nome, email, senha, perfil, coordenacao, trocar_senha) 
                                VALUES (%s, %s, %s, %s, %s, %s);
                            """, (n.strip(), e.strip().lower(), gerar_hash_senha(senha_final), p, coord_novo_user, senha_fraca_ngi(senha_final)))
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
                                if edit_s:
                                    # Senha nova fraca definida pelo administrador: a pessoa troca no próximo acesso.
                                    cursor.execute("UPDATE usuarios SET trocar_senha = %s WHERE email = %s;", (senha_fraca_ngi(edit_s), edit_e.strip().lower()))
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

                painel_backup_ngi()

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
