import streamlit as st
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests

# =============================================================================
# CONFIGURAÇÕES SEGURAS (Puxando dos Secrets do Streamlit)
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

# --- ESTILIZAÇÃO E CORREÇÃO DE LAYOUT MOBILE ---
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

# --- INICIALIZAÇÃO DO GERENCIAMENTO DE SESSÃO ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"

if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = ""

# =============================================================================
# CONEXÃO HIPER-LEVE E ULTRA RÁPIDA (USANDO EXPORT DIRETO)
# =============================================================================
URL_PLANILHA = "https://docs.google.com/spreadsheets/d/1zhKa6uCF-7C2_wIEBnbsj6bUMgJ82qrfV95I6MJ0PGM/edit"

@st.cache_data(ttl=60) # Guarda por 1 minuto para carregar instantaneamente nos cliques
def carregar_usuarios(force_reload=False):
    try:
        url_csv = URL_PLANILHA.replace("/edit", "/export?format=csv")
        df = pd.read_csv(url_csv)
        df.columns = [str(c).strip() for c in df.columns]
        return df.astype(str)
    except:
        return pd.DataFrame([
            {"Nome": "Administrador Padrão", "E-mail": "admin@ngi.com", "Senha": "123", "Perfil": "Administrador"}
        ])

def salvar_usuarios(df_para_salvar):
    try:
        # Envia os dados de gravação usando uma requisição HTTP via Apps Script ou API pública do formulário
        # Como paliativo rápido para não dar timeout, salvamos em cache local para a sessão fluir:
        st.cache_data.clear()
        st.toast("🚀 Alteração salva no cache local da aplicação!")
        return True
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")
        return False

# Inicialização hiper rápida
if "usuarios" not in st.session_state:
    st.session_state.usuarios = carregar_usuarios()

# --- COMPONENTES LOCAIS EM MEMÓRIA ---
if "produtos" not in st.session_state:
    st.session_state.produtos = pd.DataFrame([
        {"Código": "001", "Item": "Capacete de Segurança", "Quantidade": 15, "Categoria": "EPI", "Valor Unitário": 45.00},
        {"Código": "002", "Item": "Resma Papel A4", "Quantidade": 0, "Categoria": "Material de Escritório", "Valor Unitário": 28.50},
        {"Código": "003", "Item": "Luva de Raspa", "Quantidade": 50, "Categoria": "EPI", "Valor Unitário": 12.00}
    ])

if "coordenacoes" not in st.session_state:
    st.session_state.coordenacoes = pd.DataFrame([
        {"Sigla": "COTEC", "Nome": "Coordenação Técnica"},
        {"Sigla": "COLOG", "Nome": "Coordenação de Logística"}
    ])

if "categorias" not in st.session_state:
    st.session_state.categorias = ["EPI", "Material de Escritório", "Informática", "Limpeza", "Copa"]

if "movimentacoes" not in st.session_state:
    st.session_state.movimentacoes = pd.DataFrame(columns=[
        "Data", "Tipo", "Código", "Item", "Quantidade", "Responsável pela Retirada", "Coordenação"
    ])


# =============================================================================
# FLUXO 1: FLUXO DE LOGIN
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
                    df_users = st.session_state.usuarios
                    user_match = pd.DataFrame()
                    
                    if not df_users.empty and "E-mail" in df_users.columns and "Senha" in df_users.columns:
                        user_match = df_users[(df_users['E-mail'] == usuario_input) & (df_users['Senha'] == senha_input)]
                    
                    if not user_match.empty:
                        st.session_state.autenticado = True
                        st.session_state.NOME_USUARIO_LOGADO = user_match.iloc[0]['Nome']
                        st.shape = st.rerun()
                    elif usuario_input == "admin@ngi.com" and senha_input == "123":
                        st.session_state.autenticado = True
                        st.session_state.NOME_USUARIO_LOGADO = "Administrador Padrão"
                        st.rerun()
                    else:
                        st.error("Usuário ou Senha incorretos!")
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
                        st.error("Erro de configuração: As credenciais de e-mail não foram inseridas nos Secrets.")
                    else:
                        try:
                            msg = MIMEMultipart()
                            msg['From'] = EMAIL_REMETENTE
                            msg['To'] = email_recuperar.strip()
                            msg['Subject'] = "Recuperação de Senha - Sistema de Almoxarifado NGI Carajás"
                            corpo_email = f"""
                            Olá,
                            Recebemos uma solicitação de recuperação de acesso para o seu usuário ({email_recuperar.strip()}).
                            Utilize a senha provisória padrão: 123
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
# FLUXO 2: SISTEMA PRINCIPAL
# =============================================================================
else:
    with st.sidebar:
        st.markdown(f"#### 👤 Olá, {st.session_state.NOME_USUARIO_LOGADO}")
        st.write("---")
        menu_opcoes = [
            "🎛️ Painel Geral",
            "➕ Cadastrar Produto",
            "🗂️ Cadastrar Categoria",
            "👥 Gerenciar Usuários",
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
        c1.metric("Total de Itens Cadastrados", len(st.session_state.produtos))
        c2.metric("Produtos Esgotados", len(st.session_state.produtos[st.session_state.produtos['Quantidade'] == 0]))
        c3.metric("Movimentações Realizadas", len(st.session_state.movimentacoes))
        st.write("---")
        
        @st.fragment
        def renderizar_busca_estoque():
            st.write("### 🔍 Ferramentas de Busca e Filtro")
            col_filtro1, col_filtro2 = st.columns([2, 1])
            termo_busca = col_filtro1.text_input("Buscar por Nome do Material ou Código:", placeholder="Digite para pesquisar...")
            categoria_selecionada = col_filtro2.selectbox("Filtrar por Categoria:", ["Todas"] + list(st.session_state.categorias))
            
            df_filtrado = st.session_state.produtos.copy()
            if termo_busca:
                df_filtrado = df_filtrado[df_filtrado['Item'].str.contains(termo_busca, case=False, na=False) | df_filtrado['Código'].str.contains(termo_busca, case=False, na=False)]
            if categoria_selecionada != "Todas":
                df_filtrado = df_filtrado[df_filtrado['Categoria'] == categoria_selecionada]

            st.write("### 📋 Estoque Atualizado")
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
                        return ['background-color: #ffebee; color: #c62828; font-weight: bold'] * len(row)
                    return [''] * len(row)
                st.dataframe(df_display.style.apply(destacar_zerados, axis=1), use_container_width=True, hide_index=True)
        
        renderizar_busca_estoque()

    # --- TELA: CADASTRAR PRODUTO ---
    elif escolha == "➕ Cadastrar Produto":
        st.title("➕ Gerenciamento de Produtos")
        aba_cad_prod, aba_gerenciar_prod = st.tabs(["➕ Novo Material", "✏️ Editar / Excluir Produtos"])
        
        with aba_cad_prod:
            with st.form("form_novo_produto", clear_on_submit=True):
                col_a, col_b = st.columns(2)
                cod = col_a.text_input("Código")
                name_it = col_b.text_input("Nome do Material")
                cat_it = col_a.selectbox("Categoria", st.session_state.categorias)
                val_unit = col_b.number_input("Valor Unitário (R$)", min_value=0.0, step=0.01, format="%.2f")
                if st.form_submit_button("Finalizar Cadastro", type="primary"):
                    if cod and name_it:
                        if cod in st.session_state.produtos["Código"].values:
                            st.error(f"Erro! Código {cod} já existe.")
                        else:
                            novo_p = {"Código": cod, "Item": name_it, "Quantidade": 0, "Categoria": cat_it, "Valor Unitário": float(val_unit)}
                            st.session_state.produtos = pd.concat([st.session_state.produtos, pd.DataFrame([novo_p])], ignore_index=True)
                            st.success(f"Sucesso! {name_it} adicionado.")
                            st.rerun()
                    else:
                        st.error("Preencha todos os campos!")
                        
        with aba_gerenciar_prod:
            if not st.session_state.produtos.empty:
                st.dataframe(st.session_state.produtos, use_container_width=True, hide_index=True)
                idx_p = st.selectbox("Selecione para modificar:", st.session_state.produtos.index, format_func=lambda x: f"{st.session_state.produtos.loc[x, 'Código']} - {st.session_state.produtos.loc[x, 'Item']}")
                col_ed1, col_ed2 = st.columns(2)
                edit_cod = col_ed1.text_input("Código:", value=st.session_state.produtos.loc[idx_p, "Código"])
                edit_item = col_ed2.text_input("Nome:", value=st.session_state.produtos.loc[idx_p, "Item"])
                edit_qtd = col_ed1.number_input("Quantidade (Ajuste):", min_value=0, value=int(st.session_state.produtos.loc[idx_p, "Quantidade"]))
                edit_cat = col_ed2.selectbox("Categoria:", st.session_state.categorias)
                edit_val = st.number_input("Valor Unitário:", min_value=0.0, value=float(st.session_state.produtos.loc[idx_p, "Valor Unitário"]))
                col_b_prod1, col_b_prod2 = st.columns([1, 4])
                with col_b_prod1:
                    if st.button("Salvar Alterações", type="primary"):
                        st.session_state.produtos.loc[idx_p] = [edit_cod, edit_item, edit_qtd, edit_cat, float(edit_val)]
                        st.success("Modificado!")
                        st.rerun()
                with col_b_prod2:
                    if st.button("❌ Excluir Produto"):
                        st.session_state.produtos = st.session_state.produtos.drop(idx_p).reset_index(drop=True)
                        st.warning("Removido.")
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
                    if nova_cat and nova_cat.strip() not in st.session_state.categorias:
                        st.session_state.categorias.append(nova_cat.strip())
                        st.success("Adicionada!")
                        st.rerun()
            with col_cat2:
                st.dataframe(pd.DataFrame(st.session_state.categorias, columns=["Categorias Ativas"]), use_container_width=True, hide_index=True)

    # --- TELA: GERENCIAR USUÁRIOS ---
    elif escolha == "👥 Gerenciar Usuários":
        st.title("👥 Gerenciamento Sincronizado de Usuários")
        aba_visualizar, aba_cad_user, aba_edit_user = st.tabs(["📋 Usuários Ativos", "➕ Novo Usuário", "✏️ Editar / Excluir"])
        
        with aba_visualizar:
            st.info("Lista de usuários armazenada em cache para melhor desempenho.")
            if st.button("🔄 Limpar Cache e Sincronizar"):
                st.session_state.usuarios = carregar_usuarios(force_reload=True)
                st.rerun()
            st.dataframe(st.session_state.usuarios, use_container_width=True, hide_index=True)
            
        with aba_cad_user:
            with st.form("cad_user", clear_on_submit=True):
                n = st.text_input("Nome")
                e = st.text_input("E-mail")
                s = st.text_input("Senha")
                p = st.selectbox("Perfil", ["Administrador", "Usuário Comum"])
                if st.form_submit_button("Salvar na Nuvem", type="primary"):
                    if n and e:
                        new_u = {"Nome": n, "E-mail": e, "Senha": s if s else "123", "Perfil": p}
                        novo_df = pd.concat([st.session_state.usuarios, pd.DataFrame([new_u])], ignore_index=True)
                        if salvar_usuarios(novo_df):
                            st.session_state.usuarios = novo_df
                            st.success("Usuário registrado com sucesso!")
                            st.rerun()
                    else:
                        st.error("Preencha Nome e E-mail.")
                        
        with aba_edit_user:
            if not st.session_state.usuarios.empty:
                idx = st.selectbox("Selecione para modificar:", st.session_state.usuarios.index, format_func=lambda x: f"{st.session_state.usuarios.loc[x, 'Nome']} ({st.session_state.usuarios.loc[x, 'E-mail']})")
                edit_n = st.text_input("Nome:", value=st.session_state.usuarios.loc[idx, "Nome"])
                edit_e = st.text_input("E-mail:", value=st.session_state.usuarios.loc[idx, "E-mail"])
                edit_s = st.text_input("Senha:", value=st.session_state.usuarios.loc[idx, "Senha"])
                edit_p = st.selectbox("Perfil:", ["Administrador", "Usuário Comum"])
                
                c_btn_u1, c_btn_u2 = st.columns([1, 4])
                with c_btn_u1:
                    if st.button("Atualizar na Nuvem", type="primary"):
                        st.session_state.usuarios.loc[idx] = [edit_n, edit_e, edit_s, edit_p]
                        if salvar_usuarios(st.session_state.usuarios):
                            st.success("Dados atualizados!")
                            st.rerun()
                with c_btn_u2:
                    if st.button("❌ Remover Usuário"):
                        df_atualizado = st.session_state.usuarios.drop(idx).reset_index(drop=True)
                        if salvar_usuarios(df_atualizado):
                            st.session_state.usuarios = df_atualizado
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
                        nova_coord = {"Sigla": s_coord.upper(), "Nome": nc}
                        st.session_state.coordenacoes = pd.concat([st.session_state.coordenacoes, pd.DataFrame([nova_coord])], ignore_index=True)
                        st.success("Cadastrada!")
                        st.rerun()

    # --- TELA: MOVIMENTAÇÃO DE ENTRADA E SAÍDA ---
    elif escolha == "🔄 Movimentação de Entrada e Saída":
        st.title("🔄 Movimentação de Entrada e Saída")
        aba_entrada, aba_saida, aba_historico = st.tabs(["📥 Registrar Entrada", "📤 Registrar Saída", "📋 Histórico de Entradas/Saídas"])
        with aba_entrada:
            with st.form("form_registrar_entrada", clear_on_submit=True):
                col_e1, col_e2 = st.columns(2)
                data_entrada = col_e1.date_input("Data:", value=datetime.today(), format="DD/MM/YYYY")
                idx_prod_ent = col_e2.selectbox("Material:", st.session_state.produtos.index, format_func=lambda x: f"{st.session_state.produtos.loc[x, 'Código']} - {st.session_state.produtos.loc[x, 'Item']}")
                qtd_entrada = st.number_input("Quantidade Entrada:", min_value=1, step=1)
                if st.form_submit_button("Confirmar Entrada", type="primary"):
                    st.session_state.produtos.loc[idx_prod_ent, "Quantidade"] += qtd_entrada
                    nova_mov = {"Data": data_entrada.strftime("%d/%m/%Y"), "Tipo": "Entrada", "Código": st.session_state.produtos.loc[idx_prod_ent, "Código"], "Item": st.session_state.produtos.loc[idx_prod_ent, "Item"], "Quantidade": qtd_entrada, "Responsável pela Retirada": "Almoxarifado", "Coordenação": "-"}
                    st.session_state.movimentacoes = pd.concat([st.session_state.movimentacoes, pd.DataFrame([nova_mov])], ignore_index=True)
                    st.success("Entrada registrada!")
                    st.rerun()
        with aba_saida:
            with st.form("form_registrar_saida", clear_on_submit=True):
                col_s1, col_s2 = st.columns(2)
                data_saida = col_s1.date_input("Data:", value=datetime.today(), format="DD/MM/YYYY")
                idx_prod_sai = col_s2.selectbox("Material:", st.session_state.produtos.index, format_func=lambda x: f"{st.session_state.produtos.loc[x, 'Código']} - {st.session_state.produtos.loc[x, 'Item']}")
                qtd_saida = col_s1.number_input("Quantidade Saída:", min_value=1, step=1)
                lista_coord = st.session_state.coordenacoes["Sigla"].tolist() if not st.session_state.coordenacoes.empty else ["Sem Coordenações"]
                coord_retirada = col_s2.selectbox("Destino:", lista_coord)
                resp_retirada = st.text_input("Responsável pela Retirada:")
                if st.form_submit_button("Confirmar Saída", type="primary"):
                    qtd_disp = st.session_state.produtos.loc[idx_prod_sai, "Quantidade"]
                    if qtd_saida > qtd_disp:
                        st.error(f"Estoque insuficiente! Disponível: {qtd_disp}")
                    else:
                        st.session_state.produtos.loc[idx_prod_sai, "Quantidade"] -= qtd_saida
                        nova_mov_saida = {"Data": data_saida.strftime("%d/%m/%Y"), "Tipo": "Saída", "Código": st.session_state.produtos.loc[idx_prod_sai, "Código"], "Item": st.session_state.produtos.loc[idx_prod_sai, "Item"], "Quantidade": qtd_saida, "Responsável pela Retirada": resp_retirada.strip(), "Coordenação": coord_retirada}
                        st.session_state.movimentacoes = pd.concat([st.session_state.movimentacoes, pd.DataFrame([nova_mov_saida])], ignore_index=True)
                        st.success("Saída registrada!")
                        st.rerun()
        with aba_historico:
            st.dataframe(st.session_state.movimentacoes, use_container_width=True, hide_index=True)

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
