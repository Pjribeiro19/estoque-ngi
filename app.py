import streamlit as st
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from streamlit_gsheets import GSheetsConnection

# =============================================================================
# CONFIGURAÇÕES SEGURAS DE E-MAIL (Puxando dos Secrets do Streamlit)
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

# --- FORÇA A BARRA LATERAL A FICAR SEMPRE ABERTA NO CELULAR ---
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
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
        color: #333333 !important;
        font-weight: 500;
        padding: 12px 16px;
        border-radius: 4px;
        margin-bottom: 2px;
        transition: all 0.2s ease;
    }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover {
        background-color: #e2eed7 !important;
        color: #1e5934 !important;
        cursor: pointer;
    }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] input:checked + div {
        background-color: #cce2b4 !important;
        border-radius: 4px;
        color: #1e5934 !important;
        font-weight: bold !important;
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

# --- INICIALIZAÇÃO DA CONEXÃO GOOGLE SHEETS AUTOMÁTICA VIA SECRETS ---
# Carrega automaticamente as credenciais em formato estruturado limpo definidas no Passo 1
conn = st.connection("gsheets", type=GSheetsConnection)

# --- INICIALIZAÇÃO DO GERENCIAMENTO DE SESSÃO ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"

if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = ""


# =============================================================================
# FUNÇÕES DE PERSISTÊNCIA (LEITURA E ESCRITA NO GOOGLE SHEETS)
# =============================================================================
def ler_aba(nome_aba):
    try:
        return conn.read(worksheet=nome_aba, ttl=0).dropna(how="all")
    except Exception as e:
        st.error(f"Erro ao ler do banco de dados (Aba: {nome_aba}): {e}")
        return pd.DataFrame()

def salvar_aba(nome_aba, df_atualizado):
    try:
        conn.update(worksheet=nome_aba, data=df_atualizado)
        return True
    except Exception as e:
        st.error(f"Erro ao salvar na planilha (Aba: {nome_aba}): {e}")
        return False


# =============================================================================
# FLUXO 1: FLUXO DE LOGIN (SE NÃO ESTIVER AUTENTICADO)
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
            st.markdown("<h2 style='text-align: center; color: #1e5934; margin-top: 10px; margin-bottom: 25px; font-family: sans-serif;'>Gestão de Almoxarifado<br>NGI Carajás</h2>", unsafe_allow_html=True)
            usuario_input = st.text_input("Usuário / E-mail", placeholder="Digite seu usuário...").strip()
            senha_input = st.text_input("Senha", type="password", placeholder="Digite sua senha...").strip()
            st.markdown("<br>", unsafe_allow_html=True)
            
            if st.button("Entrar no Sistema", type="primary", use_container_width=True):
                if usuario_input and senha_input:
                    df_usuarios = ler_aba("usuários")
                    if not df_usuarios.empty:
                        user_match = df_usuarios[
                            (df_usuarios['E-mail'].astype(str) == usuario_input) & 
                            (df_usuarios['Senha'].astype(str) == senha_input)
                        ]
                        
                        if not user_match.empty:
                            st.session_state.autenticado = True
                            st.session_state.NOME_USUARIO_LOGADO = user_match.iloc[0]['Nome']
                            st.rerun()
                        else:
                            st.error("Usuário ou Senha incorretos!")
                    else:
                        st.error("Erro ao carregar a lista de usuários.")
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
            st.markdown("<p style='font-size: 0.9rem; color: gray;'>Insira seu e-mail corporativo cadastrado para recuperar a senha.</p>", unsafe_allow_html=True)
            email_recuperar = st.text_input("E-mail corporativo", placeholder="exemplo@icmbio.gov.br")

            if st.button("Enviar Instruções", type="primary", use_container_width=True):
                if email_recuperar.strip():
                    if EMAIL_REMETENTE == "configurar_no_secrets@email.com":
                        st.error("Erro de configuração: As credenciais de e-mail não foram inseridas nos Secrets do Streamlit.")
                    else:
                        try:
                            msg = MIMEMultipart()
                            msg['From'] = EMAIL_REMETENTE
                            msg['To'] = email_recuperar.strip()
                            msg['Subject'] = "Recuperação de Senha - Sistema de Almoxarifado NGI Carajás"
                            corpo_email = f"""
                            Olá,
                            Recebemos uma solicitação de recuperação de acesso para o seu usuário ({email_recuperar.strip()}).
                            Para acessar o Sistema de Gestão de Almoxarifado NGI Carajás, utilize os dados de acesso padrão provisórios:
                            Link de acesso: https://almoxarifado-carajas.streamlit.app/
                            Sua senha provisória de contingência é: 123
                            Por favor, altere sua senha no menu 'Perfil' assim que efetuar o login com sucesso.
                            Atenciosamente,
                            Suporte NGI Carajás / ICMBio
                            """
                            msg.attach(MIMEText(corpo_email, 'plain'))
                            server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
                            server.starttls()
                            server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
                            server.sendmail(EMAIL_REMETENTE, email_recuperar.strip(), msg.as_string())
                            server.quit()
                            st.success(f"Sucesso! Instruções de recuperação enviadas para {email_recuperar}")
                        except Exception as e:
                            st.error(f"Erro ao tentar enviar o e-mail: {e}")
                else:
                    st.warning("Por favor, digite um e-mail válido.")
            if st.button("Voltar para o Login", use_container_width=True):
                st.session_state.sub_tela_login = "login"
                st.rerun()

# =============================================================================
# FLUXO 2: SISTEMA PRINCIPAL (APÓS ESTAR AUTENTICADO)
# =============================================================================
else:
    # Carga inicial dinâmica de tabelas úteis
    df_produtos = ler_aba("produtos")
    df_categorias = ler_aba("categorias")
    df_usuarios = ler_aba("usuários")
    df_coordenacoes = ler_aba("coordenadas")
    df_movimentacoes = ler_aba("movimentações")

    lista_categorias = df_categorias["Categorias"].dropna().tolist() if not df_categorias.empty else ["Geral"]

    with st.sidebar:
        st.markdown(f"#### 👤 Olá, {st.session_state.NOME_USUARIO_LOGADO}")
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

    # --- TELA: PAINEL GERAL ---
    if escolha == "🎛️ Painel Geral":
        st.title("🎛️ Painel Geral de Estoque")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total de Itens Cadastrados", len(df_produtos))
        c2.metric("Produtos Esgotados", len(df_produtos[df_produtos['Quantidade'].astype(int) == 0]) if not df_produtos.empty else 0)
        c3.metric("Movimentações Realizadas", len(df_movimentacoes))
        st.write("---")
        st.write("### 🔍 Ferramentas de Busca e Filtro")
        col_filtro1, col_filtro2 = st.columns([2, 1])
        termo_busca = col_filtro1.text_input("Buscar por Nome do Material ou Código:", placeholder="Digite para pesquisar...")
        categoria_selecionada = col_filtro2.selectbox("Filtrar por Categoria:", ["Todas"] + lista_categorias)
        
        df_filtrado = df_produtos.copy() if not df_produtos.empty else pd.DataFrame()
        
        if not df_filtrado.empty:
            if termo_busca:
                df_filtrado = df_filtrado[df_filtrado['Item'].str.contains(termo_busca, case=False, na=False) | df_filtrado['Código'].astype(str).str.contains(termo_busca, case=False, na=False)]
            if categoria_selecionada != "Todas":
                df_filtrado = df_filtrado[df_filtrado['Categoria'] == categoria_selecionada]

        st.write("### 📋 Estoque Atualizado")
        if df_filtrado.empty:
            st.info("Nenhum material encontrado com os filtros aplicados.")
        else:
            df_display = df_filtrado.copy()
            df_display["Quantidade"] = df_display["Quantidade"].astype(int)
            df_display["Valor Unitário"] = df_display["Valor Unitário"].astype(float)
            df_display["Valor Total"] = df_display["Quantidade"] * df_display["Valor Unitário"]
            df_display["Valor Unitário"] = df_display["Valor Unitário"].map("R$ {:.2f}".format)
            df_display["Valor Total"] = df_display["Valor Total"].map("R$ {:.2f}".format)

            def destacar_zerados(row):
                if int(row['Quantidade']) == 0:
                    return ['background-color: #ffebee; color: #c62828; font-weight: bold'] * len(row)
                return [''] * len(row)
            st.dataframe(df_display.style.apply(destacar_zerados, axis=1), use_container_width=True, hide_index=True)

    # --- TELA: CADASTRAR PRODUTO ---
    elif escolha == "➕ Cadastrar Produto":
        st.title("➕ Gerenciamento de Produtos")
        aba_cad_prod, aba_gerenciar_prod = st.tabs(["➕ Novo Material", "✏️ Editar / Excluir Produtos"])
        with aba_cad_prod:
            with st.form("form_novo_produto", clear_on_submit=True):
                col_a, col_b = st.columns(2)
                cod = col_a.text_input("Código")
                name_it = col_b.text_input("Nome do Material")
                cat_it = col_a.selectbox("Categoria", lista_categorias)
                val_unit = col_b.number_input("Valor Unitário (R$)", min_value=0.0, step=0.01, format="%.2f")
                st.caption("ℹ️ Novos materiais são registrados com saldo inicial 0. Adicione quantidades in 'Movimentação'.")
                if st.form_submit_button("Finalizar Cadastro", type="primary"):
                    if cod and name_it:
                        if not df_produtos.empty and str(cod) in df_produtos["Código"].astype(str).values:
                            st.error(f"Erro! Código {cod} já existe.")
                        else:
                            novo_p = {"Código": cod, "Item": name_it, "Quantidade": 0, "Categoria": cat_it, "Valor Unitário": float(val_unit)}
                            df_produtos = pd.concat([df_produtos, pd.DataFrame([novo_p])], ignore_index=True)
                            if salvar_aba("produtos", df_produtos):
                                st.success(f"Sucesso! {name_it} adicionado.")
                                st.rerun()
                    else:
                        st.error("Preencha todos os campos!")
        with aba_gerenciar_prod:
            if not df_produtos.empty:
                st.dataframe(df_produtos, use_container_width=True, hide_index=True)
                idx_p = st.selectbox("Selecione para modificar:", df_produtos.index, format_func=lambda x: f"{df_produtos.loc[x, 'Código']} - {df_produtos.loc[x, 'Item']}", key="sb_prod_edit")
                col_ed1, col_ed2 = st.columns(2)
                edit_cod = col_ed1.text_input("Código:", value=df_produtos.loc[idx_p, "Código"], key="edit_cod")
                edit_item = col_ed2.text_input("Nome:", value=df_produtos.loc[idx_p, "Item"], key="edit_item")
                edit_qtd = col_ed1.number_input("Quantidade (Ajuste):", min_value=0, value=int(df_produtos.loc[idx_p, "Quantidade"]), key="edit_qtd")
                
                cat_atual = df_produtos.loc[idx_p, "Categoria"]
                idx_cat_atual = lista_categorias.index(cat_atual) if cat_atual in lista_categorias else 0
                edit_cat = col_ed2.selectbox("Categoria:", lista_categorias, index=idx_cat_atual, key="edit_cat")
                
                edit_val = st.number_input("Valor Unitário:", min_value=0.0, step=0.01, format="%.2f", value=float(df_produtos.loc[idx_p, "Valor Unitário"]), key="edit_val")
                col_b_prod1, col_b_prod2 = st.columns([1, 4])
                with col_b_prod1:
                    if st.button("Salvar Alterações", type="primary", key="btn_save_prod"):
                        df_produtos.loc[idx_p] = [edit_cod, edit_item, edit_qtd, edit_cat, float(edit_val)]
                        if salvar_aba("produtos", df_produtos):
                            st.success("Modificado com sucesso!")
                            st.rerun()
                with col_b_prod2:
                    if st.button("❌ Excluir Produto", key="btn_del_prod"):
                        df_produtos = df_produtos.drop(idx_p).reset_index(drop=True)
                        if salvar_aba("produtos", df_produtos):
                            st.warning("Removido com sucesso.")
                            st.rerun()

    # --- TELA: CADASTRAR CATEGORIA ---
    elif escolha == "🗂️ Cadastrar Categoria":
        st.title("🗂️ Gerenciamento de Categorias")
        aba_nova_cat, aba_gerenciar_cat = st.tabs(["➕ Nova Categoria", "✏️ Editar / Excluir Categorias"])
        with aba_nova_cat:
            col_cat1, col_cat2 = st.columns([1, 2])
            with col_cat1:
                nova_cat = st.text_input("Nome da Nova Categoria:", key="input_nova_cat")
                if st.button("Adicionar Categoria", type="primary", key="btn_add_cat"):
                    if nova_cat and nova_cat.strip() not in lista_categorias:
                        nova_linha = pd.DataFrame([{"Categorias": nova_cat.strip()}])
                        df_categorias = pd.concat([df_categorias, nova_linha], ignore_index=True)
                        if salvar_aba("categorias", df_categorias):
                            st.success("Adicionada!")
                            st.rerun()
            with col_cat2:
                st.dataframe(df_categorias, use_container_width=True, hide_index=True)
        with aba_gerenciar_cat:
            if not df_categorias.empty:
                cat_selecionada_idx = st.selectbox("Selecione:", df_categorias.index, format_func=lambda x: df_categorias.loc[x, "Categorias"], key="sb_cat_edit")
                edit_nome_cat = st.text_input("Editar Nome:", value=df_categorias.loc[cat_selecionada_idx, "Categorias"], key="edit_nome_cat")
                c_btn_cat1, c_btn_cat2 = st.columns([1, 4])
                with c_btn_cat1:
                    if st.button("Salvar Edição", type="primary", key="btn_save_cat"):
                        df_categorias.loc[cat_selecionada_idx, "Categorias"] = edit_nome_cat.strip()
                        if salvar_aba("categorias", df_categorias):
                            st.success("Atualizado!")
                            st.rerun()
                with c_btn_cat2:
                    if st.button("❌ Excluir Categoria", key="btn_del_cat"):
                        df_categorias = df_categorias.drop(cat_selecionada_idx).reset_index(drop=True)
                        if salvar_aba("categorias", df_categorias):
                            st.warning("Removida.")
                            st.rerun()

    # --- TELA: CADASTRAR USUÁRIO ---
    elif escolha == "👥 Cadastrar Usuário":
        st.title("👥 Cadastrar Usuário")
        aba_cad, aba_edit = st.tabs(["➕ Novo Usuário", "✏️ Editar / Excluir Usuários"])
        with aba_cad:
            with st.form("cad_user", clear_on_submit=True):
                n = st.text_input("Nome")
                e = st.text_input("E-mail")
                s = st.text_input("Senha", type="password")
                p = st.selectbox("Perfil", ["Administrador", "Usuário Comum"])
                if st.form_submit_button("Salvar", type="primary"):
                    if n and e:
                        new_u = {"Nome": n, "E-mail": e, "Senha": s if s else "123", "Perfil": p}
                        df_usuarios = pd.concat([df_usuarios, pd.DataFrame([new_u])], ignore_index=True)
                        if salvar_aba("usuários", df_usuarios):
                            st.success("Criado com sucesso!")
                            st.rerun()
        with aba_edit:
            if not df_usuarios.empty:
                st.dataframe(df_usuarios[["Nome", "E-mail", "Perfil"]], use_container_width=True, hide_index=True)
                idx = st.selectbox("Selecione:", df_usuarios.index, format_func=lambda x: df_usuarios.loc[x, "Nome"], key="sb_user_edit")
                edit_n = st.text_input("Nome:", value=df_usuarios.loc[idx, "Nome"], key="edit_n")
                edit_e = st.text_input("E-mail:", value=df_usuarios.loc[idx, "E-mail"], key="edit_e")
                edit_s = st.text_input("Senha:", value=df_usuarios.loc[idx, "Senha"], type="password", key="edit_s")
                
                perfil_atual = df_usuarios.loc[idx, "Perfil"]
                idx_perfil = 0 if perfil_atual == "Administrador" else 1
                edit_p = st.selectbox("Perfil:", ["Administrador", "Usuário Comum"], index=idx_perfil, key="edit_p")
                
                c_btn_u1, c_btn_u2 = st.columns([1, 4])
                with c_btn_u1:
                    if st.button("Atualizar Dados", type="primary", key="btn_save_user"):
                        df_usuarios.loc[idx] = [edit_n, edit_e, edit_s, edit_p]
                        if salvar_aba("usuários", df_usuarios):
                            st.success("Atualizado!")
                            st.rerun()
                with c_btn_u2:
                    if st.button("❌ Excluir Usuário", key="btn_del_user"):
                        df_usuarios = df_usuarios.drop(idx).reset_index(drop=True)
                        if salvar_aba("usuários", df_usuarios):
                            st.warning("Removido.")
                            st.rerun()

    # --- TELA: CADASTRAR COORDENAÇÃO ---
    elif escolha == "🏢 Cadastrar Coordenação":
        st.title("🏢 Cadastrar Coordenação")
        aba_c1, aba_c2 = st.tabs(["➕ Nova Coordenação", "✏️ Editar / Excluir Coordenação"])
        with aba_c1:
            with st.form("cad_coord", clear_on_submit=True):
                s_coord = st.text_input("Sigla")
                nc = st.text_input("Nome da Coordenação")
                if st.form_submit_button("Cadastrar", type="primary"):
                    if s_coord and nc:
                        nova_coord = {"Sigla": s_coord.upper(), "Nome": nc}
                        df_coordenacoes = pd.concat([df_coordenacoes, pd.DataFrame([nova_coord])], ignore_index=True)
                        if salvar_aba("coordenadas", df_coordenacoes):
                            st.success("Cadastrada!")
                            st.rerun()
        with aba_c2:
            if not df_coordenacoes.empty:
                st.dataframe(df_coordenacoes, use_container_width=True, hide_index=True)
                idx_c = st.selectbox("Selecione:", df_coordenacoes.index, format_func=lambda x: df_coordenacoes.loc[x, "Sigla"], key="sb_coord_edit")
                edit_sigla = st.text_input("Sigla:", value=df_coordenacoes.loc[idx_c, "Sigla"], key="edit_sigla")
                edit_nc = st.text_input("Nome:", value=df_coordenacoes.loc[idx_c, "Nome"], key="edit_nc")
                c_btn_co1, c_btn_co2 = st.columns([1, 4])
                with c_btn_co1:
                    if st.button("Salvar Edição", type="primary", key="btn_save_coord"):
                        df_coordenacoes.loc[idx_c] = [edit_sigla.upper(), edit_nc]
                        if salvar_aba("coordenadas", df_coordenacoes):
                            st.success("Salvo!")
                            st.rerun()
                with c_btn_co2:
                    if st.button("❌ Excluir Coordenação", key="btn_del_coord"):
                        df_coordenacoes = df_coordenacoes.drop(idx_c).reset_index(drop=True)
                        if salvar_aba("coordenadas", df_coordenacoes):
                            st.warning("Removida.")
                            st.rerun()

    # --- TELA: MOVIMENTAÇÃO DE ENTRADA E SAÍDA ---
    elif escolha == "🔄 Movimentação de Entrada e Saída":
        st.title("🔄 Movimentação de Entrada e Saída")
        aba_entrada, aba_saida, aba_historico = st.tabs(["📥 Registrar Entrada", "📤 Registrar Saída", "📋 Histórico de Entradas/Saídas"])
        with aba_entrada:
            if not df_produtos.empty:
                with st.form("form_registrar_entrada", clear_on_submit=True):
                    col_e1, col_e2 = st.columns(2)
                    data_entrada = col_e1.date_input("Data:", value=datetime.today(), format="DD/MM/YYYY")
                    idx_prod_ent = col_e2.selectbox("Material:", df_produtos.index, format_func=lambda x: f"{df_produtos.loc[x, 'Código']} - {df_produtos.loc[x, 'Item']} (Saldo: {df_produtos.loc[x, 'Quantidade']})")
                    qtd_entrada = st.number_input("Quantidade Entrada:", min_value=1, step=1)
                    if st.form_submit_button("Confirmar Entrada", type="primary"):
                        df_produtos.loc[idx_prod_ent, "Quantidade"] = int(df_produtos.loc[idx_prod_ent, "Quantidade"]) + qtd_entrada
                        nova_mov = {"Data": data_entrada.strftime("%d/%m/%Y"), "Tipo": "Entrada", "Código": df_produtos.loc[idx_prod_ent, "Código"], "Item": df_produtos.loc[idx_prod_ent, "Item"], "Quantidade": qtd_entrada, "Responsável pela Retirada": "Almoxarifado", "Coordenação": "-"}
                        df_movimentacoes = pd.concat([df_movimentacoes, pd.DataFrame([nova_mov])], ignore_index=True)
                        
                        if salvar_aba("produtos", df_produtos) and salvar_aba("movimentações", df_movimentacoes):
                            st.success("Entrada registrada com sucesso!")
                            st.rerun()
            else:
                st.info("Nenhum material cadastrado para receber entradas.")
        with aba_saida:
            if not df_produtos.empty:
                with st.form("form_registrar_saida", clear_on_submit=True):
                    col_s1, col_s2 = st.columns(2)
                    data_saida = col_s1.date_input("Data:", value=datetime.today(), format="DD/MM/YYYY")
                    idx_prod_sai = col_s2.selectbox("Material:", df_produtos.index, format_func=lambda x: f"{df_produtos.loc[x, 'Código']} - {df_produtos.loc[x, 'Item']} (Saldo: {df_produtos.loc[x, 'Quantidade']})")
                    qtd_saida = col_s1.number_input("Quantidade Saída:", min_value=1, step=1)
                    lista_coord = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["Sem Coordenações"]
                    coord_retirada = col_s2.selectbox("Destino:", lista_coord)
                    resp_retirada = st.text_input("Responsável pela Retirada:")
                    if st.form_submit_button("Confirmar Saída", type="primary"):
                        qtd_disp = int(df_produtos.loc[idx_prod_sai, "Quantidade"])
                        if not resp_retirada.strip():
                            st.error("Insira o nome do responsável!")
                        elif qtd_saida > qtd_disp:
                            st.error(f"Estoque insuficiente! Disponível: {qtd_disp}")
                        else:
                            df_produtos.loc[idx_prod_sai, "Quantidade"] = qtd_disp - qtd_saida
                            nova_mov_saida = {"Data": data_saida.strftime("%d/%m/%Y"), "Tipo": "Saída", "Código": df_produtos.loc[idx_prod_sai, "Código"], "Item": df_produtos.loc[idx_prod_sai, "Item"], "Quantidade": qtd_saida, "Responsável pela Retirada": resp_retirada.strip(), "Coordenação": coord_retirada}
                            df_movimentacoes = pd.concat([df_movimentacoes, pd.DataFrame([nova_mov_saida])], ignore_index=True)
                            
                            if salvar_aba("produtos", df_produtos) and salvar_aba("movimentações", df_movimentacoes):
                                st.success("Saída registrada!")
                                st.rerun()
            else:
                st.info("Nenhum material em estoque para saídas.")
        with aba_historico:
            st.write("### 📜 Registros de Fluxo")
            if df_movimentacoes.empty:
                st.info("Nenhuma movimentação registrada.")
            else:
                st.dataframe(df_movimentacoes, use_container_width=True, hide_index=True)

    # --- TELA: PERFIL ---
    elif escolha == "👤 Perfil":
        st.title("👤 Meu Perfil")
        st.write(f"**Usuário Atual:** {st.session_state.NOME_USUARIO_LOGADO}")
        st.write("**Lotação:** NGI Carajás / ICMBio")

    # --- TELA: SAIR ---
    elif escolha == "🚪 Sair":
        st.session_state.autenticado = False
        st.session_state.sub_tela_login = "login"
        st.session_state.NOME_USUARIO_LOGADO = ""
        st.rerun()
