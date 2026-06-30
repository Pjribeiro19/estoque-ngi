import streamlit as st
import pandas as pd
from datetime import datetime

# Configuração da Página
st.set_page_config(
    page_title="Gestão de Almoxarifado - NGI Carajás", 
    page_icon="🌿", 
    layout="wide"
)

# -----------------------------------------------------------------------------
# BANCO DE DADOS EM MEMÓRIA (Session State)
# -----------------------------------------------------------------------------
if "produtos" not in st.session_state or not isinstance(st.session_state.produtos, pd.DataFrame):
    st.session_state.produtos = pd.DataFrame([
        {"Código": "001", "Item": "Capacete de Segurança", "Quantidade": 15, "Categoria": "EPI", "Valor Unitário": 45.00},
        {"Código": "002", "Item": "Resma Papel A4", "Quantidade": 0, "Categoria": "Material de Escritório", "Valor Unitário": 28.50},
        {"Código": "003", "Item": "Luva de Raspa", "Quantidade": 50, "Categoria": "EPI", "Valor Unitário": 12.00}
    ])

if "usuarios" not in st.session_state or not isinstance(st.session_state.usuarios, pd.DataFrame):
    st.session_state.usuarios = pd.DataFrame([
        {"Nome": "Administrador Padrão", "E-mail": "admin@ngi.com", "Senha": "123", "Perfil": "Administrador"}
    ])

if "coordenacoes" not in st.session_state or not isinstance(st.session_state.coordenacoes, pd.DataFrame):
    st.session_state.coordenacoes = pd.DataFrame([
        {"Sigla": "COTEC", "Nome": "Coordenação Técnica"},
        {"Sigla": "COLOG", "Nome": "Coordenação de Logística"}
    ])

if "categorias" not in st.session_state or not isinstance(st.session_state.categorias, list):
    st.session_state.categorias = ["EPI", "Material de Escritório", "Informática", "Limpeza", "Copa"]

if "movimentacoes" not in st.session_state or not isinstance(st.session_state.movimentacoes, pd.DataFrame):
    st.session_state.movimentacoes = pd.DataFrame(columns=[
        "Data", "Tipo", "Código", "Item", "Quantidade", "Responsável pela Retirada", "Coordenação"
    ])

# --- CONTROLADOR DE SESSÃO ---
if "usuario_logado" not in st.session_state:
    st.session_state.usuario_logado = None

if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"

# -----------------------------------------------------------------------------
# TELA DE ACESSO (CENTRALIZADA)
# -----------------------------------------------------------------------------
if st.session_state.usuario_logado is None:
    
    st.markdown("""
        <style>
        .stApp {
            background-color: #fcfbfe !important;
        }
        .login-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
            margin: 0 auto;
            max-width: 380px;
            padding-top: 5vh;
        }
        .logo-wrapper {
            display: flex;
            justify-content: center;
            margin-bottom: 15px;
            width: 100%;
        }
        .system-title {
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            color: #1e5934;
            font-size: 1.4rem;
            font-weight: 700;
            letter-spacing: 0.5px;
            margin-top: 10px;
            margin-bottom: 5px;
            text-align: center;
            width: 100%;
        }
        .system-subtitle {
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            color: #555555;
            font-size: 1.05rem;
            font-weight: 500;
            margin-bottom: 30px;
            text-align: center;
            width: 100%;
        }
        .forgot-wrapper {
            text-align: right;
            margin-top: -12px;
            margin-bottom: 20px;
            width: 100%;
        }
        .forgot-wrapper button {
            background: none !important;
            border: none !important;
            color: #666666 !important;
            font-size: 0.85rem !important;
            text-decoration: none !important;
            padding: 0 !important;
        }
        .forgot-wrapper button:hover {
            color: #1e5934 !important;
        }
        
        div.stButton > button:first-child[kind="primary"] {
            background-color: #1e5934 !important;
            border-color: #1e5934 !important;
            color: white !important;
        }
        div.stButton > button:first-child[kind="primary"]:hover {
            background-color: #143d23 !important;
            border-color: #143d23 !important;
        }
        
        [data-testid="stHeader"] { display: none !important; }
        </style>
    """, unsafe_allow_html=True)

    _, col_central, _ = st.columns([1.1, 1, 1.1])
    
    with col_central:
        st.markdown('<div class="login-container">', unsafe_allow_html=True)
        
        st.markdown('<div class="logo-wrapper">', unsafe_allow_html=True)
        logo_url = "https://www.gov.br/icmbio/pt-br/assuntos/biodiversidade/unidade-de-conservacao/unidades-de-biomas/marinho/lista-de-ucs/parna-marinho-dos-abrolhos/fomulario-denuncia/icmbio-logo-1.png/@@images/93d85e33-e72b-423a-bc35-5d1b1f09b402.png"
        st.image(logo_url, width=190)
        st.markdown('</div>', unsafe_allow_html=True)
            
        st.markdown('<div class="system-title">GESTÃO DE ALMOXARIFADO</div>', unsafe_allow_html=True)
        st.markdown('<div class="system-subtitle">NGI CARAJÁS</div>', unsafe_allow_html=True)
        
        if st.session_state.sub_tela_login == "login":
            login_email = st.text_input("E-mail corporativo", placeholder="E-mail", key="login_email_input", label_visibility="collapsed")
            login_senha = st.text_input("Senha", placeholder="Senha", type="password", key="login_senha_input", label_visibility="collapsed")
            
            st.markdown('<div class="forgot-wrapper">', unsafe_allow_html=True)
            if st.button("Esqueceu sua senha?", key="lnk_esqueci"):
                st.session_state.sub_tela_login = "esqueci"
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
            
            if st.button("Entrar", type="primary", use_container_width=True, key="btn_entrar_confirmar"):
                # .str.strip() previne erros de espaços invisíveis digitados no cadastro ou login
                usuario_valido = st.session_state.usuarios[
                    (st.session_state.usuarios["E-mail"].str.strip() == login_email.strip()) & 
                    (st.session_state.usuarios["Senha"].astype(str)
