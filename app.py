import streamlit as st
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from supabase import create_client, Client

# =============================================================================
# CONEXÃO COM O SUPABASE (Puxando dos Secrets do Streamlit)
# =============================================================================
try:
    url: str = st.secrets["supabase_url"]
    key: str = st.secrets["supabase_key"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error(f"Erro ao conectar com as credenciais do Supabase. Verifique os Secrets: {e}")

# =============================================================================
# CONFIGURAÇÕES DE E-MAIL (Puxando dos Secrets do Streamlit)
# =============================================================================
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

# --- CONFIGURAÇÃO VISUAL (CSS) ---
st.markdown("""
    <style>
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
    }
    </style>
""", unsafe_allow_html=True)

# --- INICIALIZAÇÃO DE SESSÃO DO STREAMLIT ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"

if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = ""

if "PERFIL_USUARIO" not in st.session_state:
    st.session_state.PERFIL_USUARIO = ""

# --- FUNÇÃO SEGURO DE LOGIN ---
def fazer_login(usuario_ou_email, senha):
    try:
        resposta = supabase.table("usuarios").select("*").execute()
        if resposta.data:
            for user in resposta.data:
                # Compara sem diferenciar maiúsculas/minúsculas
                if (user["usuario"].lower() == usuario_ou_email.lower() or user["email"].lower() == usuario_ou_email.lower()) and str(user["senha"]) == str(senha):
                    return user
        return None
    except Exception as e:
        st.error(f"Erro na consulta do banco: {e}")
        return None

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
            st.markdown("<h2 style='text-align: center; color: #1e5934; font-family: sans-serif;'>Gestão de Almoxarifado<br>NGI Carajás</h2>", unsafe_allow_html=True)
            
            usuario_input = st.text_input("Usuário / E-mail", placeholder="admin@ngi.com")
            senha_input = st.text_input("Senha", type="password", placeholder="***")
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Entrar no Sistema", type="primary", use_container_width=True):
                if usuario_input and senha_input:
                    user_validado = fazer_login(usuario_input, senha_input)
                    if user_validado:
                        st.session_state.autenticado = True
                        st.session_state.NOME_USUARIO_LOGADO = user_validado["nome"]
                        st.session_state.PERFIL_USUARIO = user_validado["perfil"].lower()
                        st.success("Acesso autorizado!")
                        st.rerun()
                    else:
                        st.error("Usuário ou senha incorretos!")
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
                    if EMAIL_REMETENTE == "configurar_no_secrets@email.com":
                        st.error("Erro de configuração de e-mail nos Secrets do Streamlit.")
                    else:
                        try:
                            msg = MIMEMultipart()
                            msg['From'] = EMAIL_REMETENTE
                            msg['To'] = email_recuperar.strip()
                            msg['Subject'] = "Recuperação de Senha - Almoxarifado NGI Carajás"
                            corpo_email = f"Olá, utilize a senha provisória padrão: 123 para acessar o sistema."
                            msg.attach(MIMEText(corpo_email, 'plain'))
                            server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
                            server.starttls()
                            server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
                            server.sendmail(EMAIL_REMETENTE, email_recuperar.strip(), msg.as_string())
                            server.quit()
                            st.success("Instruções de recuperação enviadas!")
                        except Exception as e:
                            st.error(f"Erro ao enviar: {e}")
            if st.button("Voltar para o Login", use_container_width=True):
                st.session_state.sub_tela_login = "login"
                st.rerun()

# =============================================================================
# FLUXO 2: SISTEMA PRINCIPAL (AUTENTICADO COM SUPABASE)
# =============================================================================
else:
    # CARREGAMENTO EM TEMPO REAL DOS DADOS DO SUPABASE
    try:
        produtos_db = supabase.table("produtos").select("*").execute().data
        df_produtos = pd.DataFrame(produtos_db) if produtos_db else pd.DataFrame(columns=["id", "codigo", "item", "quantidade", "categoria", "valor_unitario"])
        
        categorias_db = supabase.table("categorias").select("nome").execute().data
        lista_categorias = [c["nome"] for c in categorias_db] if categorias_db else []
        
        coordenacoes_db = supabase.table("coordenacoes").select("*").execute().data
        df_coordenacoes = pd.DataFrame(coordenacoes_db) if coordenacoes_db else pd.DataFrame(columns=["id", "sigla", "nome"])
        
        usuarios_db = supabase.table("usuarios").select("id", "nome", "usuario", "email", "perfil").execute().data
        df_usuarios = pd.DataFrame(usuarios_db) if usuarios_db else pd.DataFrame(columns=["id", "nome", "usuario", "email", "perfil"])
        
        mov_db = supabase.table("movimentacoes").select("*").execute().data
        df_movimentacoes = pd.DataFrame(mov_db) if mov_db else pd.DataFrame(columns=["id", "data", "tipo", "codigo", "item", "quantidade", "responsavel", "coordenacao"])
    except Exception as e:
        st.error(f"Erro ao sincronizar tabelas do banco: {e}")

    # --- BARRA LATERAL ---
    with st.sidebar:
        st.markdown(f"#### 👤 Olá, {st.session_state.NOME_USUARIO_LOGADO}")
        st.caption(f"Perfil: {st.session_state.PERFIL_USUARIO.upper()}")
        st.write("---")
        menu_opcoes = [
            "🎛️ Painel Geral",
            "➕ Cadastrar Produto",
            "🗂️ Cadastrar Categoria",
            "👥 Cadastrar Usuário",
            "🏢 Cadastrar Coordenação",
            "🔄 Movimentação de Entrada e Saída",
            "👤 Perfil",
            "🚪 Sair"
        ]
        escolha = st.radio("", menu_opcoes, label_visibility="collapsed")

    # --- TELA 1: PAINEL GERAL ---
    if escolha == "🎛️ Painel Geral":
        st.title("🎛️ Painel Geral de Estoque")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total de Itens Cadastrados", len(df_produtos))
        c2.metric("Produtos Esgotados", len(df_produtos[df_produtos['quantidade'] == 0]) if not df_produtos.empty else 0)
        c3.metric("Movimentações Realizadas", len(df_movimentacoes))
        st.write("---")
        
        st.write("### 🔍 Filtros de Busca")
        col_f1, col_f2 = st.columns([2, 1])
        busca = col_f1.text_input("Buscar por Nome ou Código:")
        cat_sel = col_f2.selectbox("Filtrar por Categoria:", ["Todas"] + lista_categorias)
        
        df_filtrado = df_produtos.copy()
        if busca:
            df_filtrado = df_filtrado[df_filtrado['item'].str.contains(busca, case=False, na=False) | df_filtrado['codigo'].str.contains(busca, case=False, na=False)]
        if cat_sel != "Todas":
            df_filtrado = df_filtrado[df_filtrado['categoria'] == cat_sel]
            
        st.write("### 📋 Estoque Atualizado")
        if df_filtrado.empty:
            st.info("Nenhum material encontrado.")
        else:
            st.dataframe(df_filtrado, use_container_width=True, hide_index=True)

    # --- TELA 2: CADASTRAR PRODUTO ---
    elif escolha == "➕ Cadastrar Produto":
        st.title("➕ Gerenciamento de Produtos")
        tab_novo, tab_editar = st.tabs(["➕ Novo Material", "✏️ Editar / Excluir"])
        
        with tab_novo:
            with st.form("form_novo_prod", clear_on_submit=True):
                c_a, c_b = st.columns(2)
                cod = c_a.text_input("Código")
                nome_it = c_b.text_input("Nome do Material")
                cat_it = c_a.selectbox("Categoria", lista_categorias)
                val_unit = c_b.number_input("Valor Unitário (R$)", min_value=0.0, step=0.01)
                if st.form_submit_button("Finalizar Cadastro", type="primary"):
                    if cod and nome_it:
                        try:
                            supabase.table("produtos").insert({"codigo": cod, "item": nome_it, "quantidade": 0, "categoria": cat_it, "valor_unitario": val_unit}).execute()
                            st.success("Cadastrado com sucesso!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao inserir produto: {e}")
                    else:
                        st.error("Preencha todos os campos obrigatórios!")

        with tab_editar:
            if not df_produtos.empty:
                prod_selecionado = st.selectbox("Selecione o produto para alterar:", df_produtos["item"].tolist())
                linha_prod = df_produtos[df_produtos["item"] == prod_selecionado].iloc[0]
                
                edit_cod = st.text_input("Código:", value=str(linha_prod["codigo"]))
                edit_item = st.text_input("Nome do Material:", value=str(linha_prod["item"]))
                edit_val = st.number_input("Valor Unitário:", min_value=0.0, value=float(linha_prod["valor_unitario"]))
                
                c_eb1, c_eb2 = st.columns(2)
                if c_eb1.button("Salvar Alterações", type="primary"):
                    supabase.table("produtos").update({"codigo": edit_cod, "item": edit_item, "valor_unitario": edit_val}).eq("id", int(linha_prod["id"])).execute()
                    st.success("Atualizado!")
                    st.rerun()
                if c_eb2.button("❌ Excluir Produto"):
                    supabase.table("produtos").delete().eq("id", int(linha_prod["id"])).execute()
                    st.warning("Excluído!")
                    st.rerun()

    # --- TELA 3: CADASTRAR CATEGORIA ---
    elif escolha == "🗂️ Cadastrar Categoria":
        st.title("🗂️ Gerenciamento de Categorias")
        c_cat1, c_cat2 = st.columns([1, 2])
        with c_cat1:
            nova_cat = st.text_input("Nome da Nova Categoria:")
            if st.button("Adicionar Categoria", type="primary"):
                if nova_cat.strip():
                    try:
                        supabase.table("categorias").insert({"nome": nova_cat.strip()}).execute()
                        st.success("Categoria adicionada!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro: {e}")
        with c_cat2:
            st.dataframe(pd.DataFrame(lista_categorias, columns=["Categorias Ativas"]), use_container_width=True)

    # --- TELA 4: CADASTRAR USUÁRIO ---
    elif escolha == "👥 Cadastrar Usuário":
        st.title("👥 Controle de Usuários")
        t_u1, t_u2 = st.tabs(["➕ Novo Usuário", "✏️ Gerenciar Usuários"])
        
        with t_u1:
            with st.form("form_user", clear_on_submit=True):
                n = st.text_input("Nome Completo")
                u = st.text_input("Login de Usuário (Ex: admin)")
                e = st.text_input("E-mail")
                s = st.text_input("Senha", type="password")
                p = st.selectbox("Perfil", ["administrador", "usuario comum"])
                if st.form_submit_button("Salvar Usuário", type="primary"):
                    if n and u and e and s:
                        try:
                            supabase.table("usuarios").insert({"nome": n, "usuario": u, "email": e, "senha": s, "perfil": p}).execute()
                            st.success("Usuário criado!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro: {e}")

        with t_u2:
            if not df_usuarios.empty:
                st.dataframe(df_usuarios, use_container_width=True, hide_index=True)
                sel_user = st.selectbox("Remover Usuário por ID:", df_usuarios["id"].tolist())
                if st.button("❌ Excluir Usuário Selecionado"):
                    supabase.table("usuarios").delete().eq("id", int(sel_user)).execute()
                    st.success("Removido!")
                    st.rerun()

    # --- TELA 5: CADASTRAR COORDENAÇÃO ---
    elif escolha == "🏢 Cadastrar Coordenação":
        st.title("🏢 Gerenciamento de Coordenações")
        co1, co2 = st.columns([1, 2])
        with co1:
            sigla = st.text_input("Sigla da Coordenação (Ex: COTEC)")
            nome_co = st.text_input("Nome Completo")
            if st.button("Cadastrar Coordenação", type="primary"):
                if sigla and nome_co:
                    try:
                        supabase.table("coordenacoes").insert({"sigla": sigla.upper(), "nome": nome_co}).execute()
                        st.success("Coordenação registrada!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro: {e}")
        with co2:
            st.dataframe(df_coordenacoes, use_container_width=True, hide_index=True)

    # --- TELA 6: MOVIMENTAÇÃO DE ESTOQUE ---
    elif escolha == "🔄 Movimentação de Entrada e Saída":
        st.title("🔄 Movimentações de Estoque")
        tab_ent, tab_sai, tab_hist = st.tabs(["📥 Registrar Entrada", "📤 Registrar Saída", "📜 Histórico"])
        
        with tab_ent:
            if df_produtos.empty:
                st.warning("Nenhum produto cadastrado.")
            else:
                with st.form("form_ent", clear_on_submit=True):
                    prod_ent_nome = st.selectbox("Selecione o Material:", df_produtos["item"].tolist())
                    qtd_ent = st.number_input("Quantidade da Entrada:", min_value=1, step=1)
                    if st.form_submit_button("Confirmar Entrada", type="primary"):
                        linha = df_produtos[df_produtos["item"] == prod_ent_nome].iloc[0]
                        nova_qtd = int(linha["quantidade"]) + qtd_ent
                        
                        supabase.table("produtos").update({"quantidade": nova_qtd}).eq("id", int(linha["id"])).execute()
                        supabase.table("movimentacoes").insert({
                            "data": datetime.today().strftime("%d/%m/%Y"),
                            "tipo": "Entrada",
                            "codigo": str(linha["codigo"]),
                            "item": prod_ent_nome,
                            "quantidade": qtd_ent,
                            "responsavel": "Almoxarifado",
                            "coordenacao": "-"
                        }).execute()
                        st.success("Entrada salva!")
                        st.rerun()

        with tab_sai:
            if df_produtos.empty:
                st.warning("Nenhum produto cadastrado.")
            else:
                with st.form("form_sai", clear_on_submit=True):
                    prod_sai_nome = st.selectbox("Selecione o Material:", df_produtos["item"].tolist())
                    qtd_sai = st.number_input("Quantidade da Saída:", min_value=1, step=1)
                    lista_sigs = df_coordenacoes["sigla"].tolist() if not df_coordenacoes.empty else ["Geral"]
                    dest = st.selectbox("Destino / Coordenação:", lista_sigs)
                    resp_ret = st.text_input("Responsável pela Retirada:")
                    
                    if st.form_submit_button("Confirmar Saída", type="primary"):
                        linha = df_produtos[df_produtos["item"] == prod_sai_nome].iloc[0]
                        if int(linha["quantidade"]) < qtd_sai:
                            st.error("Estoque insuficiente!")
                        elif not resp_ret.strip():
                            st.error("Preencha o responsável pela retirada.")
                        else:
                            nova_qtd = int(linha["quantidade"]) - qtd_sai
                            supabase.table("produtos").update({"quantidade": nova_qtd}).eq("id", int(linha["id"])).execute()
                            supabase.table("movimentacoes").insert({
                                "data": datetime.today().strftime("%d/%m/%Y"),
                                "tipo": "Saída",
                                "codigo": str(linha["codigo"]),
                                "item": prod_sai_nome,
                                "quantidade": qtd_sai,
                                "responsavel": resp_ret,
                                "coordenacao": dest
                            }).execute()
                            st.success("Saída salva!")
                            st.rerun()

        with tab_hist:
            st.dataframe(df_movimentacoes, use_container_width=True, hide_index=True)

    # --- TELA 7: PERFIL ---
    elif escolha == "👤 Perfil":
        st.title("👤 Meu Perfil")
        st.write(f"**Usuário Atual:** {st.session_state.NOME_USUARIO_LOGADO}")
        st.write(f"**Permissão:** {st.session_state.PERFIL_USUARIO.upper()}")
        st.write("**Lotação:** NGI Carajás / ICMBio")

    # --- TELA 8: SAIR ---
    elif escolha == "🚪 Sair":
        st.session_state.autenticado = False
        st.session_state.NOME_USUARIO_LOGADO = ""
        st.session_state.PERFIL_USUARIO = ""
        st.rerun()
