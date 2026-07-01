import streamlit as st
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from streamlit_supabase_connection import SupabaseConnection

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

# --- CONEXÃO CONECTADA AO SUPABASE ---
try:
    conn = st.connection("supabase", type=SupabaseConnection)
except Exception as e:
    st.error(f"Erro ao inicializar conexão com o Supabase: {e}")
    st.stop()

# --- INICIALIZAÇÃO DO GERENCIAMENTO DE SESSÃO ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"

if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = ""

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
            usuario_input = st.text_input("Usuário / E-mail", placeholder="Digite seu e-mail cadastrado...").strip()
            senha_input = st.text_input("Senha", type="password", placeholder="Digite sua senha...").strip()
            st.markdown("<br>", unsafe_allow_html=True)
            
            if st.button("Entrar no Sistema", type="primary", use_container_width=True):
                if usuario_input and senha_input:
                    try:
                        # Busca o usuário direto na tabela 'usuarios' do Supabase
                        query = conn.table("usuarios").select("*").eq("email", usuario_input).eq("senha", senha_input).execute()
                        if query.data:
                            st.session_state.autenticado = True
                            st.session_state.NOME_USUARIO_LOGADO = query.data[0]['nome']
                            st.rerun()
                        else:
                            st.error("Usuário ou Senha incorretos!")
                    except Exception as e:
                        st.error(f"Erro ao conectar na autenticação: {e}")
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
            email_recuperar = st.text_input("E-mail corporativo", placeholder="exemplo@icmbio.gov.br").strip()

            if st.button("Enviar Instruções", type="primary", use_container_width=True):
                if email_recuperar:
                    try:
                        # Verifica se o e-mail existe no Supabase
                        check_user = conn.table("usuarios").select("*").eq("email", email_recuperar).execute()
                        if check_user.data:
                            msg = MIMEMultipart()
                            msg['From'] = EMAIL_REMETENTE
                            msg['To'] = email_recuperar
                            msg['Subject'] = "Recuperação de Senha - Sistema de Almoxarifado NGI Carajás"
                            
                            senha_recuperada = check_user.data[0]['senha']
                            corpo_email = f"""
                            Olá,
                            Recebemos uma solicitação de recuperação de acesso para o seu usuário.
                            Seus dados cadastrados para acesso ao Sistema de Gestão de Almoxarifado NGI Carajás são:
                            
                            Usuário: {email_recuperar}
                            Senha cadastrada: {senha_recuperada}
                            
                            Atenciosamente,
                            Suporte NGI Carajás / ICMBio
                            """
                            msg.attach(MIMEText(corpo_email, 'plain'))
                            server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
                            server.starttls()
                            server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
                            server.sendmail(EMAIL_REMETENTE, email_recuperar, msg.as_string())
                            server.quit()
                            st.success(f"Sucesso! Sua senha foi enviada para {email_recuperar}")
                        else:
                            st.error("E-mail não encontrado no banco de dados do sistema.")
                    except Exception as e:
                        st.error(f"Erro ao processar e-mail de recuperação: {e}")
                else:
                    st.warning("Por favor, digite um e-mail válido.")
            
            if st.button("Voltar para o Login", use_container_width=True):
                st.session_state.sub_tela_login = "login"
                st.rerun()

# =============================================================================
# FLUXO 2: SISTEMA PRINCIPAL (APÓS ESTAR AUTENTICADO)
# =============================================================================
else:
    # --- CARREGAMENTO CENTRALIZADO DE DADOS DO SUPABASE ---
    try:
        df_produtos = pd.DataFrame(conn.table("produtos").select("*").order("item").execute().data)
        df_categorias = pd.DataFrame(conn.table("categorias").select("*").order("nome").execute().data)
        df_usuarios = pd.DataFrame(conn.table("usuarios").select("*").order("nome").execute().data)
        df_coordenacoes = pd.DataFrame(conn.table("coordenacoes").select("*").order("sigla").execute().data)
        df_movimentacoes = pd.DataFrame(conn.table("movimentacoes").select("*").order("id", desc=True).execute().data)
    except Exception as e:
        st.error(f"Erro ao carregar dados do banco de dados: {e}")
        st.stop()

    lista_categorias = df_categorias["nome"].tolist() if not df_categorias.empty else []

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
            "🚪 Sair"
        ]
        escolha = st.radio("", menu_opcoes, label_visibility="collapsed")

    # --- TELA: PAINEL GERAL ---
    if escolha == "🎛️ Painel Geral":
        st.title("🎛️ Painel Geral de Estoque")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total de Itens Cadastrados", len(df_produtos))
        c2.metric("Produtos Esgotados", len(df_produtos[df_produtos['quantidade'].astype(int) == 0]) if not df_produtos.empty else 0)
        c3.metric("Movimentações Realizadas", len(df_movimentacoes))
        st.write("---")
        st.write("### 🔍 Ferramentas de Busca e Filtro")
        
        col_filtro1, col_filtro2 = st.columns([2, 1])
        termo_busca = col_filtro1.text_input("Buscar por Nome do Material ou Código:", placeholder="Digite para pesquisar...")
        categoria_selecionada = col_filtro2.selectbox("Filtrar por Categoria:", ["Todas"] + lista_categorias)
        
        df_filtrado = df_produtos.copy() if not df_produtos.empty else pd.DataFrame()
        if not df_filtrado.empty:
            if termo_busca:
                df_filtrado = df_filtrado[df_filtrado['item'].str.contains(termo_busca, case=False, na=False) | df_filtrado['codigo'].astype(str).str.contains(termo_busca, case=False, na=False)]
            if categoria_selecionada != "Todas":
                df_filtrado = df_filtrado[df_filtrado['categoria'] == categoria_selecionada]

        st.write("### 📋 Estoque Atualizado")
        if df_filtrado.empty:
            st.info("Nenhum material encontrado com os filtros aplicados.")
        else:
            df_display = df_filtrado.copy()[['codigo', 'item', 'quantidade', 'categoria', 'valor_unitario']]
            df_display["valor_unitario"] = df_display["valor_unitario"].astype(float)
            df_display["Valor Total"] = df_display["quantidade"] * df_display["valor_unitario"]
            df_display["valor_unitario"] = df_display["valor_unitario"].map("R$ {:.2f}".format)
            df_display["Valor Total"] = df_display["Valor Total"].map("R$ {:.2f}".format)

            def destacar_zerados(row):
                if int(row['quantidade']) == 0:
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
                nome_it = col_b.text_input("Nome do Material")
                cat_it = col_a.selectbox("Categoria", lista_categorias)
                val_unit = col_b.number_input("Valor Unitário (R$)", min_value=0.0, step=0.01, format="%.2f")
                st.caption("ℹ️ Novos materiais são registrados com saldo inicial 0. Adicione quantidades em 'Movimentação'.")
                if st.form_submit_button("Finalizar Cadastro", type="primary"):
                    if cod and nome_it:
                        try:
                            conn.table("produtos").insert({"codigo": cod, "item": nome_it, "quantidade": 0, "categoria": cat_it, "valor_unitario": float(val_unit)}).execute()
                            st.success(f"Sucesso! {nome_it} adicionado.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro! Código ou item já cadastrado no banco de dados.")
                    else:
                        st.error("Preencha todos os campos!")
                        
        with aba_gerenciar_prod:
            if not df_produtos.empty:
                idx_p = st.selectbox("Selecione para modificar:", df_produtos.index, format_func=lambda x: f"{df_produtos.loc[x, 'codigo']} - {df_produtos.loc[x, 'item']}")
                col_ed1, col_ed2 = st.columns(2)
                edit_cod = col_ed1.text_input("Código:", value=df_produtos.loc[idx_p, "codigo"])
                edit_item = col_ed2.text_input("Nome:", value=df_produtos.loc[idx_p, "item"])
                edit_qtd = col_ed1.number_input("Quantidade (Ajuste):", min_value=0, value=int(df_produtos.loc[idx_p, "quantidade"]))
                edit_cat = col_ed2.selectbox("Categoria:", lista_categorias, index=lista_categorias.index(df_produtos.loc[idx_p, "categoria"]) if df_produtos.loc[idx_p, "categoria"] in lista_categorias else 0)
                edit_val = st.number_input("Valor Unitário:", min_value=0.0, step=0.01, format="%.2f", value=float(df_produtos.loc[idx_p, "valor_unitario"]))
                
                col_b_prod1, col_b_prod2 = st.columns([1, 4])
                with col_b_prod1:
                    if st.button("Salvar Alterações", type="primary"):
                        conn.table("produtos").update({"codigo": edit_cod, "item": edit_item, "quantidade": edit_qtd, "categoria": edit_cat, "valor_unitario": float(edit_val)}).eq("id", int(df_produtos.loc[idx_p, "id"])).execute()
                        st.success("Modificado com sucesso!")
                        st.rerun()
                with col_b_prod2:
                    if st.button("❌ Excluir Produto"):
                        conn.table("produtos").delete().eq("id", int(df_produtos.loc[idx_p, "id"])).execute()
                        st.warning("Produto removido.")
                        st.rerun()

    # --- TELA: CADASTRAR CATEGORIA ---
    elif escolha == "🗂️ Cadastrar Categoria":
        st.title("🗂️ Gerenciamento de Categorias")
        aba_nova_cat, aba_gerenciar_cat = st.tabs(["➕ Nova Categoria", "✏️ Editar / Excluir Categorias"])
        
        with aba_nova_cat:
            col_cat1, col_cat2 = st.columns([1, 2])
            with col_cat1:
                nova_cat = st.text_input("Nome da Nova Categoria:")
                if st.button("Adicionar Categoria", type="primary"):
                    if nova_cat and nova_cat.strip():
                        try:
                            conn.table("categorias").insert({"nome": nova_cat.strip()}).execute()
                            st.success("Adicionada com sucesso!")
                            st.rerun()
                        except:
                            st.error("Esta categoria já está cadastrada.")
            with col_cat2:
                if not df_categorias.empty:
                    st.dataframe(df_categorias[['nome']].rename(columns={'nome': 'Categorias Ativas'}), use_container_width=True, hide_index=True)
                    
        with aba_gerenciar_cat:
            if not df_categorias.empty:
                cat_selecionada_idx = st.selectbox("Selecione a categoria para modificar:", df_categorias.index, format_func=lambda x: df_categorias.loc[x, "nome"])
                edit_nome_cat = st.text_input("Editar Nome:", value=df_categorias.loc[cat_selecionada_idx, "nome"])
                c_btn_cat1, c_btn_cat2 = st.columns([1, 4])
                with c_btn_cat1:
                    if st.button("Salvar Edição", type="primary"):
                        conn.table("categorias").update({"nome": edit_nome_cat.strip()}).eq("id", int(df_categorias.loc[cat_selecionada_idx, "id"])).execute()
                        st.success("Atualizado!")
                        st.rerun()
                with c_btn_cat2:
                    if st.button("❌ Excluir Categoria"):
                        conn.table("categorias").delete().eq("id", int(df_categorias.loc[cat_selecionada_idx, "id"])).execute()
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
                        try:
                            conn.table("usuarios").insert({"nome": n, "email": e, "senha": s if s else "123", "perfil": p}).execute()
                            st.success("Criado com sucesso!")
                            st.rerun()
                        except:
                            st.error("Erro! E-mail já cadastrado para outro usuário.")
                            
        with aba_edit:
            if not df_usuarios.empty:
                st.dataframe(df_usuarios[["nome", "email", "perfil"]], use_container_width=True, hide_index=True)
                idx = st.selectbox("Selecione o usuário para alterar:", df_usuarios.index, format_func=lambda x: df_usuarios.loc[x, "nome"])
                edit_n = st.text_input("Nome:", value=df_usuarios.loc[idx, "nome"])
                edit_e = st.text_input("E-mail:", value=df_usuarios.loc[idx, "email"])
                edit_s = st.text_input("Senha:", value=df_usuarios.loc[idx, "senha"], type="password")
                edit_p = st.selectbox("Perfil:", ["Administrador", "Usuário Comum"], index=0 if df_usuarios.loc[idx, "perfil"] == "Administrador" else 1)
                
                c_btn_u1, c_btn_u2 = st.columns([1, 4])
                with c_btn_u1:
                    if st.button("Atualizar Dados", type="primary"):
                        conn.table("usuarios").update({"nome": edit_n, "email": edit_e, "senha": edit_s, "perfil": edit_p}).eq("id", int(df_usuarios.loc[idx, "id"])).execute()
                        st.success("Atualizado!")
                        st.rerun()
                with c_btn_u2:
                    if st.button("❌ Excluir Usuário"):
                        conn.table("usuarios").delete().eq("id", int(df_usuarios.loc[idx, "id"])).execute()
                        st.warning("Usuário removido.")
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
                        try:
                            conn.table("coordenacoes").insert({"sigla": s_coord.upper(), "nome": nc}).execute()
                            st.success("Cadastrada!")
                            st.rerun()
                        except:
                            st.error("Esta Sigla já está em uso!")
                            
        with aba_c2:
            if not df_coordenacoes.empty:
                st.dataframe(df_coordenacoes[['sigla', 'nome']], use_container_width=True, hide_index=True)
                idx_c = st.selectbox("Selecione para editar:", df_coordenacoes.index, format_func=lambda x: df_coordenacoes.loc[x, "sigla"])
                edit_sigla = st.text_input("Sigla:", value=df_coordenacoes.loc[idx_c, "sigla"])
                edit_nc = st.text_input("Nome Completo:", value=df_coordenacoes.loc[idx_c, "nome"])
                
                c_btn_co1, c_btn_co2 = st.columns([1, 4])
                with c_btn_co1:
                    if st.button("Salvar Edição", type="primary"):
                        conn.table("coordenacoes").update({"sigla": edit_sigla.upper(), "nome": edit_nc}).eq("id", int(df_coordenacoes.loc[idx_c, "id"])).execute()
                        st.success("Salvo com sucesso!")
                        st.rerun()
                with c_btn_co2:
                    if st.button("❌ Excluir Coordenação"):
                        conn.table("coordenacoes").delete().eq("id", int(df_coordenacoes.loc[idx_c, "id"])).execute()
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
                    idx_prod_ent = col_e2.selectbox("Material:", df_produtos.index, format_func=lambda x: f"{df_produtos.loc[x, 'codigo']} - {df_produtos.loc[x, 'item']} (Saldo: {df_produtos.loc[x, 'quantidade']})")
                    qtd_entrada = st.number_input("Quantidade Entrada:", min_value=1, step=1)
                    if st.form_submit_button("Confirmar Entrada", type="primary"):
                        nova_qtd = int(df_produtos.loc[idx_prod_ent, "quantidade"]) + qtd_entrada
                        
                        # Atualiza estoque e insere registro de fluxo
                        conn.table("produtos").update({"quantidade": nova_qtd}).eq("id", int(df_produtos.loc[idx_prod_ent, "id"])).execute()
                        conn.table("movimentacoes").insert({
                            "data": data_entrada.strftime("%d/%m/%Y"), 
                            "tipo": "Entrada", 
                            "codigo": df_produtos.loc[idx_prod_ent, "codigo"], 
                            "item": df_produtos.loc[idx_prod_ent, "item"], 
                            "quantidade": qtd_entrada, 
                            "responsavel": "Almoxarifado", 
                            "coordenacao": "-"
                        }).execute()
                        st.success("Entrada registrada no banco!")
                        st.rerun()
            else:
                st.warning("Nenhum produto cadastrado para dar entrada.")

        with aba_saida:
            if not df_produtos.empty:
                with st.form("form_registrar_saida", clear_on_submit=True):
                    col_s1, col_s2 = st.columns(2)
                    data_saida = col_s1.date_input("Data:", value=datetime.today(), format="DD/MM/YYYY")
                    idx_prod_sai = col_s2.selectbox("Material:", df_produtos.index, format_func=lambda x: f"{df_produtos.loc[x, 'codigo']} - {df_produtos.loc[x, 'item']} (Saldo: {df_produtos.loc[x, 'quantidade']})")
                    qtd_saida = col_s1.number_input("Quantidade Saída:", min_value=1, step=1)
                    
                    lista_coord = df_coordenacoes["sigla"].tolist() if not df_coordenacoes.empty else ["-"]
                    coord_retirada = col_s2.selectbox("Destino:", lista_coord)
                    resp_retirada = st.text_input("Responsável pela Retirada:")
                    
                    if st.form_submit_button("Confirmar Saída", type="primary"):
                        qtd_disp = int(df_produtos.loc[idx_prod_sai, "quantidade"])
                        if not resp_retirada.strip():
                            st.error("Insira o nome do responsável pela retirada!")
                        elif qtd_saida > qtd_disp:
                            st.error(f"Estoque insuficiente! Disponível: {qtd_disp}")
                        else:
                            nova_qtd_saida = qtd_disp - qtd_saida
                            
                            # Atualiza estoque e insere registro de fluxo
                            conn.table("produtos").update({"quantidade": nova_qtd_saida}).eq("id", int(df_produtos.loc[idx_prod_sai, "id"])).execute()
                            conn.table("movimentacoes").insert({
                                "data": data_saida.strftime("%d/%m/%Y"), 
                                "tipo": "Saída", 
                                "codigo": df_produtos.loc[idx_prod_sai, "codigo"], 
                                "item": df_produtos.loc[idx_prod_sai, "item"], 
                                "quantidade": qtd_saida, 
                                "responsavel": resp_retirada.strip(), 
                                "coordenacao": coord_retirada
                            }).execute()
                            st.success("Saída registrada no banco!")
                            st.rerun()
            else:
                st.warning("Nenhum produto cadastrado para dar saída.")

        with aba_historico:
            st.write("### 📜 Registros de Fluxo")
            if df_movimentacoes.empty:
                st.info("Nenhuma movimentação registrada.")
            else:
                st.dataframe(df_movimentacoes
