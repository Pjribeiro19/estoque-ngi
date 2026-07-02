import streamlit as st
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from supabase import create_client, Client

# =============================================================================
# CONEXÃO COM O SUPABASE (Com tratamento de erro caso os Secrets estejam vazios)
# =============================================================================
supabase_disponivel = False
supabase: Client = None

if "supabase_url" in st.secrets and "supabase_key" in st.secrets:
    try:
        url: str = st.secrets["supabase_url"]
        key: str = st.secrets["supabase_key"]
        supabase = create_client(url, key)
        supabase_disponivel = True
    except Exception as e:
        st.error(f"Erro ao inicializar cliente do Supabase: {e}")
else:
    st.error("⚠️ ATENÇÃO: As chaves 'supabase_url' e 'supabase_key' não foram encontradas nos Secrets do Streamlit Cloud! Siga o passo a passo abaixo do código para corrigir.")

# =============================================================================
# CONFIGURAÇÕES DE E-MAIL
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

# --- CONFIGURAÇÃO VISUAL COMPLETA (CSS) ---
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
        font-weight: bold;
        border-radius: 6px;
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
    .card-metricas {
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 8px;
        border-left: 5px solid #1e5934;
        margin-bottom: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# --- INICIALIZAÇÃO DE SESSÕES ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"
if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = ""
if "PERFIL_USUARIO" not in st.session_state:
    st.session_state.PERFIL_USUARIO = ""
if "EMAIL_USUARIO_LOGADO" not in st.session_state:
    st.session_state.EMAIL_USUARIO_LOGADO = ""
if "LOGIN_USUARIO_LOGADO" not in st.session_state:
    st.session_state.LOGIN_USUARIO_LOGADO = ""

# --- FUNÇÃO DE LOGIN ---
def fazer_login(usuario_ou_email, senha):
    if not supabase_disponivel:
        return None
    try:
        resposta = supabase.table("usuarios").select("*").execute()
        if resposta.data:
            for user in resposta.data:
                if (user["usuario"].lower() == usuario_ou_email.lower() or user["email"].lower() == usuario_ou_email.lower()) and str(user["senha"]) == str(senha):
                    return user
        return None
    except Exception as e:
        st.error(f"Erro na consulta do banco de dados: {e}")
        return None

# =============================================================================
# FLUXO 1: TELA DE LOGIN / RECUPERAÇÃO DE SENHA
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
            st.markdown("<h2 style='text-align: center; color: #1e5934; font-family: sans-serif; margin-bottom:30px;'>Gestão de Almoxarifado<br>NGI Carajás</h2>", unsafe_allow_html=True)
            
            usuario_input = st.text_input("Usuário / E-mail", placeholder="admin@ngi.com", key="login_user")
            senha_input = st.text_input("Senha", type="password", placeholder="***", key="login_pass")
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Entrar no Sistema", type="primary", use_container_width=True):
                if not supabase_disponivel:
                    st.error("Banco de dados desconectado. Verifique as configurações do Streamlit Cloud.")
                elif usuario_input and senha_input:
                    user_validado = fazer_login(usuario_input, senha_input)
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
            email_recuperar = st.text_input("E-mail corporativo cadastrado:", placeholder="exemplo@icmbio.gov.br")

            if st.button("Enviar Instruções", type="primary", use_container_width=True):
                if email_recuperar.strip():
                    if EMAIL_REMETENTE == "configurar_no_secrets@email.com":
                        st.error("Erro: O servidor de e-mail automático não está configurado nos Secrets.")
                    else:
                        try:
                            msg = MIMEMultipart()
                            msg['From'] = EMAIL_REMETENTE
                            msg['To'] = email_recuperar.strip()
                            msg['Subject'] = "Recuperação de Senha - Almoxarifado NGI Carajás"
                            corpo_email = f"Olá,\n\nSua solicitação de recuperação foi recebida.\nUtilize a senha provisória padrão: 123 para acessar o sistema e altere-a no seu perfil."
                            msg.attach(MIMEText(corpo_email, 'plain'))
                            server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
                            server.starttls()
                            server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
                            server.sendmail(EMAIL_REMETENTE, email_recuperar.strip(), msg.as_string())
                            server.quit()
                            st.success("Instruções de recuperação enviadas para o e-mail!")
                        except Exception as e:
                            st.error(f"Erro ao enviar e-mail: {e}")
                else:
                    st.error("Digite um e-mail válido.")
            if st.button("Voltar para o Login", use_container_width=True):
                st.session_state.sub_tela_login = "login"
                st.rerun()

# =============================================================================
# FLUXO 2: SISTEMA PRINCIPAL (LOGADO)
# =============================================================================
else:
    # CARREGAMENTO DINÂMICO E SEGURO DO BANCO DE DADOS
    df_produtos = pd.DataFrame(columns=["id", "codigo", "item", "quantidade", "categoria", "valor_unitario"])
    lista_categorias = []
    df_coordenacoes = pd.DataFrame(columns=["id", "sigla", "nome"])
    df_usuarios = pd.DataFrame(columns=["id", "nome", "usuario", "email", "perfil"])
    df_movimentacoes = pd.DataFrame(columns=["id", "data", "tipo", "codigo", "item", "quantidade", "responsavel", "coordenacao"])

    if supabase_disponivel:
        try:
            p_res = supabase.table("produtos").select("*").execute().data
            if p_res: df_produtos = pd.DataFrame(p_res)
            
            c_res = supabase.table("categorias").select("nome").execute().data
            if c_res: lista_categorias = [c["nome"] for c in c_res]
            
            co_res = supabase.table("coordenacoes").select("*").execute().data
            if co_res: df_coordenacoes = pd.DataFrame(co_res)
            
            u_res = supabase.table("usuarios").select("id", "nome", "usuario", "email", "perfil").execute().data
            if u_res: df_usuarios = pd.DataFrame(u_res)
            
            m_res = supabase.table("movimentacoes").select("*").execute().data
            if m_res: df_movimentacoes = pd.DataFrame(m_res)
        except Exception as e:
            st.error(f"Erro ao atualizar tabelas em tempo real: {e}")

    # --- MENU LATERAL DE NAVEGAÇÃO ---
    with st.sidebar:
        st.markdown(f"#### 👤 {st.session_state.NOME_USUARIO_LOGADO}")
        st.caption(f"Perfil: {st.session_state.PERFIL_USUARIO.upper()}")
        st.write("---")
        
        # Menu completo preservando o escopo original do sistema
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
        escolha = st.radio("Navegação do Sistema", menu_opcoes, label_visibility="collapsed")
        
        st.write("---")
        st.caption("NGI Carajás - ICMBio © 2026")

    # --- 1. TELA: PAINEL GERAL ---
    if escolha == "🎛️ Painel Geral":
        st.title("🎛️ Painel Geral de Estoque")
        st.write("Visão unificada do estoque e dos indicadores de movimentação.")
        
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"<div class='card-metricas'><b>Total de Itens Cadastrados</b><h2>{len(df_produtos)}</h2></div>", unsafe_allow_html=True)
        with c2:
            esgotados = len(df_produtos[df_produtos['quantidade'] == 0]) if not df_produtos.empty else 0
            st.markdown(f"<div class='card-metricas'><b>Produtos Esgotados</b><h2>{esgotados}</h2></div>", unsafe_allow_html=True)
        with c3:
            st.markdown(f"<div class='card-metricas'><b>Movimentações Realizadas</b><h2>{len(df_movimentacoes)}</h2></div>", unsafe_allow_html=True)
            
        st.write("---")
        st.subheader("🔍 Filtros Avançados de Busca")
        col_f1, col_f2 = st.columns([2, 1])
        busca = col_f1.text_input("Buscar por Nome do Material ou Código Identificador:")
        cat_sel = col_f2.selectbox("Filtrar por Categoria Específica:", ["Todas"] + lista_categorias)
        
        df_filtrado = df_produtos.copy()
        if busca:
            df_filtrado = df_filtrado[df_filtrado['item'].str.contains(busca, case=False, na=False) | df_filtrado['codigo'].str.contains(busca, case=False, na=False)]
        if cat_sel != "Todas":
            df_filtrado = df_filtrado[df_filtrado['categoria'] == cat_sel]
            
        st.write("### 📋 Listagem de Estoque Atual")
        if df_filtrado.empty:
            st.info("Nenhum registro de material corresponde aos filtros aplicados.")
        else:
            st.dataframe(df_filtrado[["codigo", "item", "categoria", "quantidade", "valor_unitario"]], use_container_width=True, hide_index=True)

    # --- 2. TELA: CADASTRAR PRODUTO ---
    elif escolha == "➕ Cadastrar Produto":
        st.title("➕ Gerenciamento de Produtos")
        tab_novo, tab_editar = st.tabs(["➕ Cadastrar Novo Material", "✏️ Editar ou Remover Existente"])
        
        with tab_novo:
            if st.session_state.PERFIL_USUARIO != "administrador":
                st.warning("Apenas usuários administradores podem registrar novos materiais.")
            else:
                with st.form("form_novo_prod", clear_on_submit=True):
                    c_a, c_b = st.columns(2)
                    cod = c_a.text_input("Código do Produto / Código de Barras")
                    nome_it = c_b.text_input("Nome Descritivo do Material")
                    cat_it = c_a.selectbox("Selecione a Categoria Relacionada", lista_categorias) if lista_categorias else c_a.selectbox("Selecione", ["Nenhuma Categoria Cadastrada"])
                    val_unit = c_b.number_input("Valor Unitário Estimado (R$)", min_value=0.0, step=0.01)
                    
                    if st.form_submit_button("Gravar Produto no Banco", type="primary"):
                        if not lista_categorias:
                            st.error("Você deve criar ao menos uma categoria antes de registrar produtos.")
                        elif cod.strip() and nome_it.strip():
                            try:
                                supabase.table("produtos").insert({"codigo": cod.strip(), "item": nome_it.strip(), "quantidade": 0, "categoria": cat_it, "valor_unitario": val_unit}).execute()
                                st.success(f"Material '{nome_it}' inserido com saldo zerado!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro de restrição do Banco de Dados (Ex: Código Duplicado): {e}")
                        else:
                            st.error("Os campos Código e Nome são estritamente obrigatórios.")

        with tab_editar:
            if st.session_state.PERFIL_USUARIO != "administrador":
                st.warning("Seu nível de permissão não permite alterações estruturais de itens.")
            elif df_produtos.empty:
                st.info("Nenhum material disponível para edição.")
            else:
                prod_selecionado = st.selectbox("Selecione o produto para modificação:", df_produtos["item"].tolist())
                linha_prod = df_produtos[df_produtos["item"] == prod_selecionado].iloc[0]
                
                edit_cod = st.text_input("Código Identificador:", value=str(linha_prod["codigo"]))
                edit_item = st.text_input("Nome do Item:", value=str(linha_prod["item"]))
                edit_val = st.number_input("Valor Unitário Atualizado:", min_value=0.0, value=float(linha_prod["valor_unitario"]))
                
                c_eb1, c_eb2 = st.columns(2)
                if c_eb1.button("Salvar Alterações de Cadastro", type="primary"):
                    try:
                        supabase.table("produtos").update({"codigo": edit_cod, "item": edit_item, "valor_unitario": edit_val}).eq("id", int(linha_prod["id"])).execute()
                        st.success("Dados do produto atualizados com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro na atualização: {e}")
                        
                if c_eb2.button("❌ Remover Registro Permanentemente"):
                    try:
                        supabase.table("produtos").delete().eq("id", int(linha_prod["id"])).execute()
                        st.warning("O item foi removido permanentemente da base de dados.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Não é possível excluir produtos que já possuem movimentações atreladas: {e}")

    # --- 3. TELA: CADASTRAR CATEGORIA ---
    elif escolha == "🗂️ Cadastrar Categoria":
        st.title("🗂️ Gerenciamento de Categorias de Insumos")
        
        if st.session_state.PERFIL_USUARIO != "administrador":
            st.warning("Menu restrito a administradores.")
        else:
            c_cat1, c_cat2 = st.columns([1, 2])
            with c_cat1:
                nova_cat = st.text_input("Nome da Nova Categoria (Ex: Equipamentos):")
                if st.button("Adicionar Categoria", type="primary"):
                    if nova_cat.strip():
                        try:
                            supabase.table("categorias").insert({"nome": nova_cat.strip()}).execute()
                            st.success("Nova categoria inserida!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Esta categoria já existe ou ocorreu um erro: {e}")
                    else:
                        st.error("Insira um nome válido.")
            with c_cat2:
                st.write("### Categorias Ativas")
                if lista_categorias:
                    st.dataframe(pd.DataFrame(lista_categorias, columns=["Nome da Categoria"]), use_container_width=True, hide_index=True)
                else:
                    st.info("Nenhuma categoria cadastrada.")

    # --- 4. TELA: CADASTRAR USUÁRIO ---
    elif escolha == "👥 Cadastrar Usuário":
        st.title("👥 Controle e Gestão de Usuários do Sistema")
        
        if st.session_state.PERFIL_USUARIO != "administrador":
            st.warning("Apenas administradores de sistema podem gerenciar credenciais.")
        else:
            t_u1, t_u2 = st.tabs(["➕ Cadastrar Novo Usuário", "✏️ Visualizar e Remover Usuários"])
            
            with t_u1:
                with st.form("form_user", clear_on_submit=True):
                    n = st.text_input("Nome Completo do Servidor/Colaborador")
                    u = st.text_input("Nome de Usuário (Login curto, sem espaços)")
                    e = st.text_input("E-mail Funcional")
                    s = st.text_input("Senha de Acesso Inicial", type="password")
                    p = st.selectbox("Perfil de Acesso do Usuário", ["administrador", "usuario comum"])
                    
                    if st.form_submit_button("Salvar Novo Perfil de Usuário", type="primary"):
                        if n and u and e and s:
                            try:
                                supabase.table("usuarios").insert({"nome": n.strip(), "usuario": u.strip().lower(), "email": e.strip().lower(), "senha": s, "perfil": p}).execute()
                                st.success(f"Usuário {u} registrado com sucesso!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro: O login ou e-mail informado já está em uso por outro usuário. ({e})")
                        else:
                            st.error("Todos os campos do formulário de cadastro devem ser informados.")

            with t_u2:
                if not df_usuarios.empty:
                    st.dataframe(df_usuarios[["id", "nome", "usuario", "email", "perfil"]], use_container_width=True, hide_index=True)
                    sel_user = st.selectbox("Selecione o ID do usuário que deseja deletar do sistema:", df_usuarios["id"].tolist())
                    if st.button("❌ Revogar Acesso e Deletar Usuário"):
                        try:
                            supabase.table("usuarios").delete().eq("id", int(sel_user)).execute()
                            st.success("Acesso revogado com sucesso!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Falha ao deletar: {e}")

    # --- 5. TELA: CADASTRAR COORDENAÇÃO ---
    elif escolha == "🏢 Cadastrar Coordenação":
        st.title("🏢 Gerenciamento de Coordenações Setoriais")
        
        if st.session_state.PERFIL_USUARIO != "administrador":
            st.warning("Menu restrito para administradores.")
        else:
            co1, co2 = st.columns([1, 2])
            with co1:
                sigla = st.text_input("Sigla Setorial (Ex: COLOG)")
                nome_co = st.text_input("Nome da Coordenação por Extenso")
                if st.button("Cadastrar Coordenação Setorial", type="primary"):
                    if sigla.strip() and nome_co.strip():
                        try:
                            supabase.table("coordenacoes").insert({"sigla": sigla.strip().upper(), "nome": nome_co.strip()}).execute()
                            st.success("Setor cadastrado com êxito!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro: Sigla já existente no banco de dados. ({e})")
                    else:
                        st.error("Preencha todos os campos obrigatórios.")
            with co2:
                st.write("### Setores e Coordenações Mapeadas")
                if not df_coordenacoes.empty:
                    st.dataframe(df_coordenacoes[["sigla", "nome"]], use_container_width=True, hide_index=True)
                else:
                    st.info("Nenhuma coordenação registrada no momento.")

    # --- 6. TELA: MOVIMENTAÇÃO DE ESTOQUE ---
    elif escolha == "🔄 Movimentação de Entrada e Saída":
        st.title("🔄 Registro de Fluxos de Almoxarifado")
        tab_ent, tab_sai, tab_hist = st.tabs(["📥 Lançar Entrada de Material", "📤 Lançar Saída / Baixa de Material", "📜 Histórico de Movimentações"])
        
        with tab_ent:
            if df_produtos.empty:
                st.warning("Nenhum material cadastrado para receber incremento de estoque.")
            else:
                with st.form("form_ent", clear_on_submit=True):
                    prod_ent_nome = st.selectbox("Escolha o Material para Entrada:", df_produtos["item"].tolist(), key="sb_ent")
                    qtd_ent = st.number_input("Quantidade Adicionada:", min_value=1, step=1, key="num_ent")
                    if st.form_submit_button("Confirmar Entrada de Material", type="primary"):
                        linha = df_produtos[df_produtos["item"] == prod_ent_nome].iloc[0]
                        nova_qtd = int(linha["quantidade"]) + qtd_ent
                        
                        try:
                            supabase.table("produtos").update({"quantidade": nova_qtd}).eq("id", int(linha["id"])).execute()
                            supabase.table("movimentacoes").insert({
                                "data": datetime.today().strftime("%d/%m/%Y"),
                                "tipo": "Entrada",
                                "codigo": str(linha["codigo"]),
                                "item": prod_ent_nome,
                                "quantidade": qtd_ent,
                                "responsavel": st.session_state.NOME_USUARIO_LOGADO,
                                "coordenacao": "Almoxarifado"
                            }).execute()
                            st.success(f"Saldo do item '{prod_ent_nome}' atualizado com sucesso!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Falha crítica na transação de entrada: {e}")

        with tab_sai:
            if df_produtos.empty:
                st.warning("Não há materiais disponíveis no estoque.")
            else:
                with st.form("form_sai", clear_on_submit=True):
                    prod_sai_nome = st.selectbox("Escolha o Material para Retirada:", df_produtos["item"].tolist(), key="sb_sai")
                    qtd_sai = st.number_input("Quantidade Solicitada para Saída:", min_value=1, step=1, key="num_sai")
                    lista_sigs = df_coordenacoes["sigla"].tolist() if not df_coordenacoes.empty else ["Geral"]
                    dest = st.selectbox("Coordenação Destinatária / Beneficiária:", lista_sigs)
                    resp_ret = st.text_input("Nome do Servidor Responsável pela Retirada:")
                    
                    if st.form_submit_button("Confirmar Baixa de Material", type="primary"):
                        linha = df_produtos[df_produtos["item"] == prod_sai_nome].iloc[0]
                        if int(linha["quantidade"]) < qtd_sai:
                            st.error(f"Operação cancelada! O estoque atual deste item é de apenas {linha['quantidade']} unidades.")
                        elif not resp_ret.strip():
                            st.error("Informe obrigatoriamente quem está retirando o material.")
                        else:
                            nova_qtd = int(linha["quantidade"]) - qtd_sai
                            try:
                                supabase.table("produtos").update({"quantidade": nova_qtd}).eq("id", int(linha["id"])).execute()
                                supabase.table("movimentacoes").insert({
                                    "data": datetime.today().strftime("%d/%m/%Y"),
                                    "tipo": "Saída",
                                    "codigo": str(linha["codigo"]),
                                    "item": prod_sai_nome,
                                    "quantidade": qtd_sai,
                                    "responsavel": resp_ret.strip(),
                                    "coordenacao": dest
                                }).execute()
                                st.success("Saída processada e registrada no histórico!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao processar transação de saída: {e}")

        with tab_hist:
            st.subheader("Livro do Histórico de Movimentações")
            if df_movimentacoes.empty:
                st.info("Nenhuma movimentação registrada no histórico.")
            else:
                st.dataframe(df_movimentacoes[["data", "tipo", "codigo", "item", "quantidade", "responsavel", "coordenacao"]], use_container_width=True, hide_index=True)

    # --- 7. TELA: PERFIL ---
    elif escolha == "👤 Perfil":
        st.title("👤 Dados cadastrais do Meu Perfil")
        st.write("Gerencie ou confira as suas informações de acesso à plataforma.")
        
        st.info("💡 Caso queira trocar a sua senha de acesso, preencha o formulário seguro abaixo.")
        with st.form("form_perfil_senha"):
            st.text_input("Nome do Usuário", value=st.session_state.NOME_USUARIO_LOGADO, disabled=True)
            st.text_input("Identificador / Login", value=st.session_state.LOGIN_USUARIO_LOGADO, disabled=True)
            st.text_input("E-mail Funcional Vinculado", value=st.session_state.EMAIL_USUARIO_LOGADO, disabled=True)
            nova_senha = st.text_input("Cadastrar Nova Senha Particular:", type="password", placeholder="Digite a nova senha desejada")
            
            if st.form_submit_button("Alterar Senha de Acesso", type="primary"):
                if nova_senha.strip():
                    try:
                        # Busca o ID correto associado ao e-mail logado para atualizar
                        user_data = supabase.table("usuarios").select("id").eq("email", st.session_state.EMAIL_USUARIO_LOGADO).execute().data
                        if user_data:
                            user_id = user_data[0]["id"]
                            supabase.table("usuarios").update({"senha": nova_senha.strip()}).eq("id", user_id).execute()
                            st.success("Sua senha pessoal foi modificada com sucesso no banco de dados!")
                        else:
                            st.error("Erro ao identificar registro do usuário.")
                    except Exception as e:
                        st.error(f"Não foi possível salvar a nova senha: {e}")
                else:
                    st.error("A nova senha não pode ser um campo vazio.")

    # --- 8. TELA: SAIR ---
    elif escolha == "🚪 Sair":
        st.session_state.autenticado = False
        st.session_state.NOME_USUARIO_LOGADO = ""
        st.session_state.PERFIL_USUARIO = ""
        st.session_state.EMAIL_USUARIO_LOGADO = ""
        st.session_state.LOGIN_USUARIO_LOGADO = ""
        st.success("Sessão finalizada com sucesso.")
        st.rerun()
