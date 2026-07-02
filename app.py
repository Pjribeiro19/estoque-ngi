import streamlit as st
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests  # Conexão direta via API HTTP para evitar o erro de DNS

# =============================================================================
# CONEXÃO DIRETA VIA API REST DO SUPABASE
# =============================================================================
supabase_disponivel = False
SUPABASE_URL = ""
SUPABASE_KEY = ""

if "supabase_url" in st.secrets and "supabase_key" in st.secrets:
    SUPABASE_URL = st.secrets["supabase_url"].strip().rstrip("/")
    SUPABASE_KEY = st.secrets["supabase_key"].strip()
    if SUPABASE_URL and SUPABASE_KEY:
        supabase_disponivel = True
else:
    st.error("⚠️ Parâmetros 'supabase_url' e 'supabase_key' ausentes nos Secrets do Streamlit Cloud.")

# Configuração de Headers para chamadas REST do Supabase
headers_auth = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# --- FUNÇÕES DE INTERAÇÃO DIRETA (HTTP REST) ---
def buscar_tabela(nome_tabela):
    if not supabase_disponivel:
        return []
    try:
        url = f"{SUPABASE_URL}/rest/v1/{nome_tabela}?select=*"
        resposta = requests.get(url, headers=headers_auth, timeout=10)
        if resposta.status_code == 200:
            return resposta.json()
        return []
    except:
        return []

def inserir_tabela(nome_tabela, dados):
    try:
        url = f"{SUPABASE_URL}/rest/v1/{nome_tabela}"
        resposta = requests.post(url, headers=headers_auth, json=dados, timeout=10)
        return resposta.status_code in [200, 201]
    except:
        return False

def atualizar_tabela(nome_tabela, dados, coluna_id, valor_id):
    try:
        url = f"{SUPABASE_URL}/rest/v1/{nome_tabela}?{coluna_id}=eq.{valor_id}"
        resposta = requests.patch(url, headers=headers_auth, json=dados, timeout=10)
        return resposta.status_code in [200, 204]
    except:
        return False

def deletar_tabela(nome_tabela, coluna_id, valor_id):
    try:
        url = f"{SUPABASE_URL}/rest/v1/{nome_tabela}?{coluna_id}=eq.{valor_id}"
        resposta = requests.delete(url, headers=headers_auth, timeout=10)
        return resposta.status_code in [200, 204]
    except:
        return False

# =============================================================================
# CONFIGURAÇÕES DE SERVIDOR DE E-MAIL
# =============================================================================
try:
    EMAIL_REMETENTE = st.secrets["gmail"]["email"]
    SENHA_REMETENTE = st.secrets["gmail"]["senha_app"]
except:
    EMAIL_REMETENTE = "configurar_no_secrets@email.com"
    SENHA_REMETENTE = "configurar_no_secrets"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORTA = 587

# --- CONFIGURAÇÃO VISUAL DA PÁGINA ---
st.set_page_config(
    page_title="SISTEMA DE GESTÃO DE ALMOXARIFADO NGI CARAJÁS", 
    page_icon="🌿", 
    layout="wide"
)

st.markdown("""
    <style>
    [data-testid="stSidebarNav"] {display: none;}
    [data-testid="stMainMenu"] {display: none;}
    [data-testid="stSidebar"] { background-color: #fcfaff !important; border-right: 1px solid #efe9f5; }
    div.stButton > button:first-child[kind="primary"] {
        background-color: #4CAF50 !important; border-color: #4CAF50 !important; color: white !important; font-weight: bold; border-radius: 6px;
    }
    div.stButton > button:first-child[kind="primary"]:hover { background-color: #43a047 !important; border-color: #43a047 !important; }
    .img-container { display: flex; justify-content: center; align-items: center; width: 100%; margin-bottom: 20px; }
    .card-metricas { background-color: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 5px solid #1e5934; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- CONTROLE DE SESSÃO ---
if "autenticado" not in st.session_state: st.session_state.autenticado = False
if "sub_tela_login" not in st.session_state: st.session_state.sub_tela_login = "login"
if "NOME_USUARIO_LOGADO" not in st.session_state: st.session_state.NOME_USUARIO_LOGADO = ""
if "PERFIL_USUARIO" not in st.session_state: st.session_state.PERFIL_USUARIO = ""
if "EMAIL_USUARIO_LOGADO" not in st.session_state: st.session_state.EMAIL_USUARIO_LOGADO = ""
if "LOGIN_USUARIO_LOGADO" not in st.session_state: st.session_state.LOGIN_USUARIO_LOGADO = ""

# --- FLUXO DE LOGIN INTEGRADO ---
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
            st.markdown("<h2 style='text-align: center; color: #1e5934; font-family: sans-serif; margin-bottom:30px;'>Gestão de Almoxarifado<br>NGI Carajás</h2>", unsafe_allow_html=True)
            
            usuario_input = st.text_input("Usuário / E-mail", placeholder="admin@ngi.com", key="login_user")
            senha_input = st.text_input("Senha", type="password", placeholder="***", key="login_pass")
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Entrar no Sistema", type="primary", use_container_width=True):
                lista_usuarios = buscar_tabela("usuarios")
                user_validado = None
                
                for user in lista_usuarios:
                    if (user["usuario"].lower() == usuario_input.lower() or user["email"].lower() == usuario_input.lower()) and str(user["senha"]) == str(senha_input):
                        user_validado = user
                        break
                
                if user_validado:
                    st.session_state.autenticado = True
                    st.session_state.NOME_USUARIO_LOGADO = user_validado["nome"]
                    st.session_state.PERFIL_USUARIO = user_validado["perfil"].lower()
                    st.session_state.EMAIL_USUARIO_LOGADO = user_validado["email"]
                    st.session_state.LOGIN_USUARIO_LOGADO = user_validado["usuario"]
                    st.success("Acesso autorizado!")
                    st.rerun()
                else:
                    st.error("Usuário ou senha incorretos!")
            
            if st.button("Esqueci a senha", use_container_width=True):
                st.session_state.sub_tela_login = "esqueci"
                st.rerun()

    elif st.session_state.sub_tela_login == "esqueci":
        col_r1, col_r2, col_r3 = st.columns([1, 1.2, 1])
        with col_r2:
            st.write("<br><br>", unsafe_allow_html=True)
            st.markdown("### 🔑 Recuperar Acesso")
            email_recuperar = st.text_input("E-mail corporativo cadastrado:", placeholder="exemplo@icmbio.gov.br")

            if st.button("Enviar Instruções", type="primary", use_container_width=True):
                if email_recuperar.strip():
                    try:
                        msg = MIMEMultipart()
                        msg['From'] = EMAIL_REMETENTE
                        msg['To'] = email_recuperar.strip()
                        msg['Subject'] = "Recuperação de Senha - Almoxarifado NGI Carajás"
                        corpo_email = "Olá,\n\nUtilize a senha provisória padrão: 123 para realizar o acesso."
                        msg.attach(MIMEText(corpo_email, 'plain'))
                        server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
                        server.starttls()
                        server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
                        server.sendmail(EMAIL_REMETENTE, email_recuperar.strip(), msg.as_string())
                        server.quit()
                        st.success("Instruções enviadas com sucesso!")
                    except Exception as e:
                        st.error(f"Erro ao disparar e-mail: {e}")
            if st.button("Voltar para o Login", use_container_width=True):
                st.session_state.sub_tela_login = "login"
                st.rerun()

# =============================================================================
# FLUXO DO SISTEMA PRINCIPAL (AUTENTICADO)
# =============================================================================
else:
    # Coleta de dados via API REST robusta
    prod_res = buscar_tabela("produtos")
    df_produtos = pd.DataFrame(prod_res) if prod_res else pd.DataFrame(columns=["id", "codigo", "item", "quantidade", "categoria", "valor_unitario"])
    
    cat_res = buscar_tabela("categorias")
    lista_categorias = [c["nome"] for c in cat_res] if cat_res else []
    
    co_res = buscar_tabela("coordenacoes")
    df_coordenacoes = pd.DataFrame(co_res) if co_res else pd.DataFrame(columns=["id", "sigla", "nome"])
    
    u_res = buscar_tabela("usuarios")
    df_usuarios = pd.DataFrame(u_res) if u_res else pd.DataFrame(columns=["id", "nome", "usuario", "email", "perfil"])
    
    m_res = buscar_tabela("movimentacoes")
    df_movimentacoes = pd.DataFrame(m_res) if m_res else pd.DataFrame(columns=["id", "data", "tipo", "codigo", "item", "quantidade", "responsavel", "coordenacao"])

    with st.sidebar:
        st.markdown(f"#### 👤 {st.session_state.NOME_USUARIO_LOGADO}")
        st.caption(f"Perfil: {st.session_state.PERFIL_USUARIO.upper()}")
        st.write("---")
        menu_opcoes = [
            "🎛️ Painel Geral", "➕ Cadastrar Produto", "🗂️ Cadastrar Categoria",
            "👥 Cadastrar Usuário", "🏢 Cadastrar Coordenação", "🔄 Movimentação de Entrada e Saída",
            "👤 Perfil", "🚪 Sair"
        ]
        escolha = st.radio("Menu", menu_opcoes, label_visibility="collapsed")

    # --- 1. PAINEL GERAL ---
    if escolha == "🎛️ Painel Geral":
        st.title("🎛️ Painel Geral de Estoque")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total de Itens", len(df_produtos))
        c2.metric("Produtos Esgotados", len(df_produtos[df_produtos['quantidade'] == 0]) if not df_produtos.empty else 0)
        c3.metric("Movimentações", len(df_movimentacoes))
        st.write("---")
        
        busca = st.text_input("Filtrar por nome ou código do material:")
        df_filtrado = df_produtos.copy()
        if busca:
            df_filtrado = df_filtrado[df_filtrado['item'].str.contains(busca, case=False, na=False) | df_filtrado['codigo'].str.contains(busca, case=False, na=False)]
        
        st.dataframe(df_filtrado, use_container_width=True, hide_index=True)

    # --- 2. CADASTRAR PRODUTO ---
    elif escolha == "➕ Cadastrar Produto":
        st.title("➕ Gerenciamento de Produtos")
        if st.session_state.PERFIL_USUARIO != "administrador":
            st.warning("Acesso restrito a administradores.")
        else:
            with st.form("form_prod", clear_on_submit=True):
                cod = st.text_input("Código do Produto")
                item = st.text_input("Nome do Material")
                cat = st.selectbox("Categoria", lista_categorias) if lista_categorias else st.selectbox("Categoria", ["Nenhuma"])
                val = st.number_input("Valor Unitário", min_value=0.0, step=0.01)
                if st.form_submit_button("Cadastrar", type="primary"):
                    if cod and item:
                        payload = {"codigo": cod.strip(), "item": item.strip(), "quantidade": 0, "categoria": cat, "valor_unitario": val}
                        if inserir_tabela("produtos", payload):
                            st.success("Produto cadastrado!")
                            st.rerun()
                        else:
                            st.error("Erro ao salvar produto.")

    # --- 3. CADASTRAR CATEGORIA ---
    elif escolha == "🗂️ Cadastrar Categoria":
        st.title("🗂️ Categorias")
        nova_cat = st.text_input("Nome da Nova Categoria:")
        if st.button("Adicionar", type="primary"):
            if nova_cat.strip() and inserir_tabela("categorias", {"nome": nova_cat.strip()}):
                st.success("Categoria cadastrada!")
                st.rerun()

    # --- 4. CADASTRAR USUÁRIO ---
    elif escolha == "👥 Cadastrar Usuário":
        st.title("👥 Usuários do Sistema")
        if st.session_state.PERFIL_USUARIO != "administrador":
            st.warning("Acesso restrito.")
        else:
            with st.form("form_u"):
                n = st.text_input("Nome")
                u = st.text_input("Usuário/Login")
                e = st.text_input("E-mail")
                s = st.text_input("Senha")
                p = st.selectbox("Perfil", ["administrador", "usuario comum"])
                if st.form_submit_button("Salvar"):
                    if inserir_tabela("usuarios", {"nome": n, "usuario": u.lower(), "email": e.lower(), "senha": s, "perfil": p}):
                        st.success("Usuário criado!")
                        st.rerun()

    # --- 5. CADASTRAR COORDENAÇÃO ---
    elif escolha == "🏢 Cadastrar Coordenação":
        st.title("🏢 Coordenações")
        sigla = st.text_input("Sigla (Ex: COTEC)")
        nome_co = st.text_input("Nome Completo")
        if st.button("Cadastrar", type="primary"):
            if sigla and nome_co and inserir_tabela("coordenacoes", {"sigla": sigla.upper(), "nome": nome_co}):
                st.success("Coordenação registrada!")
                st.rerun()

    # --- 6. MOVIMENTAÇÃO DE ESTOQUE ---
    elif escolha == "🔄 Movimentação de Entrada e Saída":
        st.title("🔄 Movimentações")
        t_ent, t_sai = st.tabs(["📥 Lançar Entrada", "📤 Lançar Saída"])
        
        with t_ent:
            if not df_produtos.empty:
                p_nome = st.selectbox("Material:", df_produtos["item"].tolist(), key="e1")
                qtd_e = st.number_input("Quantidade:", min_value=1, step=1, key="e2")
                if st.form_submit_button("Salvar Entrada") if False else st.button("Confirmar Entrada", type="primary"):
                    linha = df_produtos[df_produtos["item"] == p_nome].iloc[0]
                    nova_qtd = int(linha["quantidade"]) + qtd_e
                    atualizar_tabela("produtos", {"quantidade": nova_qtd}, "id", linha["id"])
                    inserir_tabela("movimentacoes", {"data": datetime.today().strftime("%d/%m/%Y"), "tipo": "Entrada", "codigo": str(linha["codigo"]), "item": p_nome, "quantidade": qtd_e, "responsavel": st.session_state.NOME_USUARIO_LOGADO, "coordenacao": "Almoxarifado"})
                    st.success("Entrada registrada!")
                    st.rerun()
                    
        with t_sai:
            if not df_produtos.empty:
                p_nome_s = st.selectbox("Material:", df_produtos["item"].tolist(), key="s1")
                qtd_s = st.number_input("Quantidade:", min_value=1, step=1, key="s2")
                setor = st.selectbox("Setor Destino:", df_coordenacoes["sigla"].tolist() if not df_coordenacoes.empty else ["Geral"])
                resp = st.text_input("Responsável pela Retirada:")
                if st.button("Confirmar Saída", type="primary"):
                    linha = df_produtos[df_produtos["item"] == p_nome_s].iloc[0]
                    if int(linha["quantidade"]) >= qtd_s:
                        nova_qtd = int(linha["quantidade"]) - qtd_s
                        atualizar_tabela("produtos", {"quantidade": nova_qtd}, "id", linha["id"])
                        inserir_tabela("movimentacoes", {"data": datetime.today().strftime("%d/%m/%Y"), "tipo": "Saída", "codigo": str(linha["codigo"]), "item": p_nome_s, "quantidade": qtd_s, "responsavel": resp, "coordenacao": setor})
                        st.success("Saída efetuada!")
                        st.rerun()
                    else:
                        st.error("Saldo insuficiente no almoxarifado.")

    # --- 7. PERFIL ---
    elif escolha == "👤 Perfil":
        st.title("👤 Meu Perfil")
        st.write(f"**Usuário:** {st.session_state.NOME_USUARIO_LOGADO}")
        st.write(f"**E-mail:** {st.session_state.EMAIL_USUARIO_LOGADO}")
        st.write(f"**Nível de Acesso:** {st.session_state.PERFIL_USUARIO.upper()}")

    # --- 8. SAIR ---
    elif escolha == "🚪 Sair":
        st.session_state.autenticado = False
        st.rerun()
