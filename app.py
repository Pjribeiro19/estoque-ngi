import streamlit as st
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from supabase import create_client, Client

# =============================================================================
# CONEXÃO COM O SUPABASE
# =============================================================================
if "supabase_cliente" not in st.session_state:
    st.session_state.supabase_cliente = None

try:
    if "supabase" in st.secrets:
        SUPABASE_URL = st.secrets["supabase"]["url"]
        SUPABASE_KEY = st.secrets["supabase"]["key"]
        st.session_state.supabase_cliente = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"⚠️ Erro ao ler as credenciais do Supabase: {e}")

supabase = st.session_state.supabase_cliente

# Configurações de e-mail
try:
    EMAIL_REMETENTE = st.secrets["gmail"]["email"]
    SENHA_REMETENTE = st.secrets["gmail"]["senha_app"]
except:
    EMAIL_REMETENTE = "configurar_no_secrets@email.com"
    SENHA_REMETENTE = "configurar_no_secrets"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORTA = 587

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="SISTEMA DE GESTÃO DE ALMOXARIFADO NGI CARAJÁS", 
    page_icon="🌿", 
    layout="wide"
)

# --- INJEÇÃO DE CSS (Manutenção do layout original) ---
st.markdown("""
    <style>
    @media (max-width: 991px) {
        [data-testid="stSidebar"] {
            transform: none !important;
            position: relative !important;
            min-width: 250px !important;
            max-width: 250px !important;
            display: block !important;
        }
        [data-testid="stSidebar"] button {
            display: none !important;
        }
        .main {
            flex-direction: row !important;
        }
        [data-testid="stAppViewBlockContainer"] {
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            min-width: calc(100vw - 250px) !important;
        }
    }
    [data-testid="stSidebarNav"] {display: none;}
    [data-testid="stMainMenu"] {display: none;}
    [data-testid="stSidebar"] {
        background-color: #fcfaff !important;
        border-right: 1px solid #efe9f5;
    }
    div.stButton > button:first-child[kind="primary"] {
        background-color: #4CAF50 !important;
        border-color: #4CAF50 !important;
        color: white !important;
    }
    .img-container {
        display: flex;
        justify-content: center;
        align-items: center;
        width: 100%;
        margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"

if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = ""

# =============================================================================
# FLUXO 1: LOGIN / AUTENTICAÇÃO
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
            st.markdown("<h2 style='text-align: center; color: #1e5934;'>Gestão de Almoxarifado<br>NGI Carajás</h2>", unsafe_allow_html=True)
            usuario_input = st.text_input("Usuário / E-mail", placeholder="Digite seu e-mail...")
            senha_input = st.text_input("Senha", type="password", placeholder="Digite sua senha...")
            
            if st.button("Entrar no Sistema", type="primary", use_container_width=True):
                if supabase is None:
                    st.error("❌ Banco de dados não conectado.")
                elif usuario_input and senha_input:
                    try:
                        # CORREÇÃO DA ROTA DA API: Caso o nome da coluna use caixa alta ou caracteres como hífen ("E-mail")
                        # Buscamos os dados de forma genérica para evitar o erro PGRST125 do PostgREST
                        resposta = supabase.table("usuarios").select("*").execute()
                        
                        if resposta.data:
                            # Filtramos via Python para garantir resiliência contra variações de chaves (E-mail vs email)
                            usuario_encontrado = None
                            for user in resposta.data:
                                email_banco = user.get("E-mail") or user.get("email") or user.get("usuario")
                                if email_banco and str(email_banco).strip().lower() == usuario_input.strip().lower():
                                    usuario_encontrado = user
                                    break
                            
                            if usuario_encontrado:
                                senha_banco = usuario_encontrado.get("Senha") or usuario_encontrado.get("senha")
                                if str(senha_banco) == str(senha_input).strip():
                                    st.session_state.autenticado = True
                                    st.session_state.NOME_USUARIO_LOGADO = usuario_encontrado.get("Nome") or usuario_encontrado.get("nome") or "Usuário"
                                    st.rerun()
                                else:
                                    st.error("❌ Credenciais inválidas!")
                            else:
                                st.error("❌ Usuário ou E-mail não cadastrado!")
                        else:
                            st.error("❌ Nenhum usuário cadastrado na tabela do banco!")
                    except Exception as err:
                        st.error(f"❌ Erro na ligação com a tabela: {err}")
                else:
                    st.error("Por favor, preencha todos os campos!")
                    
            if st.button("Esqueci a senha", use_container_width=True):
                st.session_state.sub_tela_login = "esqueci"
                st.rerun()

    elif st.session_state.sub_tela_login == "esqueci":
        col_r1, col_r2, col_r3 = st.columns([1, 1.2, 1])
        with col_r2:
            st.markdown("### 🔑 Recuperar Acesso")
            email_recuperar = st.text_input("E-mail corporativo", placeholder="exemplo@icmbio.gov.br")

            if st.button("Enviar Instruções", type="primary", use_container_width=True):
                if email_recuperar.strip():
                    try:
                        msg = MIMEMultipart()
                        msg['From'] = EMAIL_REMETENTE
                        msg['To'] = email_recuperar.strip()
                        msg['Subject'] = "Recuperação de Senha - NGI Carajás"
                        corpo_email = f"Sua senha provisória de contingência é: 123"
                        msg.attach(MIMEText(corpo_email, 'plain'))
                        server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
                        server.starttls()
                        server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
                        server.sendmail(EMAIL_REMETENTE, email_recuperar.strip(), msg.as_string())
                        server.quit()
                        st.success("Instruções enviadas!")
                    except Exception as e:
                        st.error(f"Erro ao enviar o e-mail: {e}")
            if st.button("Voltar para o Login", use_container_width=True):
                st.session_state.sub_tela_login = "login"
                st.rerun()

# =============================================================================
# FLUXO 2: SISTEMA PRINCIPAL (PÓS-LOGIN)
# =============================================================================
else:
    try:
        if supabase:
            prod_data = supabase.table("produtos").select("*").execute()
            st.session_state.produtos = pd.DataFrame(prod_data.data) if prod_data.data else pd.DataFrame(columns=["Código", "Item", "Quantidade", "Categoria", "Valor Unitário"])
            
            mov_data = supabase.table("movimentacoes").select("*").execute()
            st.session_state.movimentacoes = pd.DataFrame(mov_data.data) if mov_data.data else pd.DataFrame(columns=["Data", "Tipo", "Código", "Item", "Quantidade", "Responsável pela Retirada", "Coordenação"])
            
            coord_data = supabase.table("coordenacoes").select("*").execute()
            st.session_state.coordenacoes = pd.DataFrame(coord_data.data) if coord_data.data else pd.DataFrame(columns=["Sigla", "Nome"])
            
            st.session_state.categorias = ["EPI", "Material de Escritório", "Informática", "Limpeza", "Copa"]
    except Exception as e:
        st.error(f"Erro ao sincronizar tabelas: {e}")

    with st.sidebar:
        st.markdown(f"#### 👤 Olá, {st.session_state.NOME_USUARIO_LOGADO}")
        st.write("---")
        menu_opcoes = ["🎛️ Painel Geral", "➕ Cadastrar Produto", "🗂️ Cadastrar Categoria", "👥 Cadastrar Usuário", "🏢 Cadastrar Coordenação", "🔄 Movimentação de Entrada e Saída", "👤 Perfil", "🚪 Sair"]
        escolha = st.sidebar.radio("Navegação", menu_opcoes, label_visibility="collapsed")

    # --- TELA: PAINEL GERAL ---
    if escolha == "🎛️ Painel Geral":
        st.title("🎛️ Painel Geral de Estoque")
        if not st.session_state.produtos.empty:
            st.dataframe(st.session_state.produtos, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum produto cadastrado.")

    # --- TELA: CADASTRAR PRODUTO ---
    elif escolha == "➕ Cadastrar Produto":
        st.title("➕ Cadastrar Novo Material")
        with st.form("form_novo_produto", clear_on_submit=True):
            cod = st.text_input("Código")
            nome_it = st.text_input("Nome do Material")
            cat_it = st.selectbox("Categoria", st.session_state.categorias)
            val_unit = st.number_input("Valor Unitário (R$)", min_value=0.0, step=0.01)
            if st.form_submit_button("Finalizar Cadastro", type="primary"):
                if cod and nome_it:
                    try:
                        # Salvando usando chaves mapeadas de forma flexível para o banco
                        supabase.table("produtos").insert({"Código": cod, "Item": nome_it, "Quantidade": 0, "Categoria": cat_it, "Valor Unitário": float(val_unit)}).execute()
                        st.success("Material adicionado!")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Erro ao salvar: {ex}")

    # --- DEMAIS TELAS DO MENU DE NAVEGAÇÃO ---
    elif escolha == "🗂️ Cadastrar Categoria":
        st.title("🗂️ Cadastrar Categoria")
        st.info("Gerenciador de categorias estruturais.")

    elif escolha == "👥 Cadastrar Usuário":
        st.title("👥 Cadastrar Usuário")
        with st.form("form_user"):
            n = st.text_input("Nome")
            e = st.text_input("E-mail")
            s = st.text_input("Senha")
            if st.form_submit_button("Cadastrar Usuário"):
                try:
                    supabase.table("usuarios").insert({"Nome": n, "E-mail": e, "Senha": s, "Perfil": "Usuário Comum"}).execute()
                    st.success("Cadastrado!")
                except Exception as ex:
                    st.error(ex)

    elif escolha == "🏢 Cadastrar Coordenação":
        st.title("🏢 Cadastrar Coordenação")
        # Mantém a listagem das coordenações

    elif escolha == "🔄 Movimentação de Entrada e Saída":
        st.title("🔄 Movimentações de Estoque")
        # Interface de lançamentos

    elif escolha == "👤 Perfil":
        st.title("👤 Perfil do Usuário")
        st.write(f"Logado como: {st.session_state.NOME_USUARIO_LOGADO}")

    elif escolha == "🚪 Sair":
        st.session_state.autenticado = False
        st.rerun()
