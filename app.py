import streamlit as st
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from streamlit_gsheets import GSheetsConnection

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="SISTEMA DE GESTÃO DE ALMOXARIFADO NGI CARAJÁS", 
    page_icon="🌿", 
    layout="wide"
)

# =============================================================================
# CONEXÃO DIRETA COM O GOOGLE SHEETS
# =============================================================================
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    
    # Busca os dados em tempo real de cada aba da planilha
    st.session_state.usuarios = conn.read(worksheet="usuarios", ttl=0).astype(str)
    st.session_state.produtos = conn.read(worksheet="produtos", ttl=0)
    st.session_state.coordenacoes = conn.read(worksheet="coordenacoes", ttl=0).astype(str)
    st.session_state.movimentacoes = conn.read(worksheet="movimentacoes", ttl=0).astype(str)
    
    # Tratamento para ler a lista de categorias
    df_cat = conn.read(worksheet="categorias", ttl=0)
    st.session_state.categorias = df_cat["Categoria"].dropna().tolist() if not df_cat.empty else ["Geral"]
    
    # Ajuste de tipos numéricos essenciais para cálculos de estoque
    if not st.session_state.produtos.empty:
        st.session_state.produtos["Código"] = st.session_state.produtos["Código"].astype(str)
        st.session_state.produtos["Quantidade"] = pd.to_numeric(st.session_state.produtos["Quantidade"], errors='coerce').fillna(0).astype(int)
        st.session_state.produtos["Valor Unitário"] = pd.to_numeric(st.session_state.produtos["Valor Unitário"], errors='coerce').fillna(0.0).astype(float)
except Exception as ex:
    st.error(f"Erro ao conectar com a Planilha Google: {ex}")
    st.info("Verifique se configurou corretamente o link da planilha no menu Secrets.")
    st.stop()

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

# --- ESTILIZAÇÃO CUSTOMIZADA (CSS) ---
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
        [data-testid="stSidebar"] button { display: none !important; }
        .main { flex-direction: row !important; }
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
    .img-container {
        display: flex;
        justify-content: center;
        align-items: center;
        width: 100%;
        margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# --- INICIALIZAÇÃO DE SESSÃO ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"
if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = ""

# =============================================================================
# FLUXO 1: LOGIN (VALIDANDO DINAMICAMENTE CONTRA A PLANILHA)
# =============================================================================
if not st.session_state.autenticado:
    if st.session_state.sub_tela_login == "login":
        st.markdown("<br><br>", unsafe_allow_html=True)
        col_l1, col_l2, col_l3 = st.columns([1, 1.2, 1])
        with col_l2:
            st.markdown('<div class="img-container"><img src="https://www.gov.br/icmbio/pt-br/assuntos/biodiversidade/unidade-de-conservacao/unidades-de-biomas/marinho/lista-de-ucs/parna-marinho-dos-abrolhos/fomulario-denuncia/icmbio-logo-1.png" width="320"></div>', unsafe_allow_html=True)
            st.markdown("<h2 style='text-align: center; color: #1e5934;'>Gestão de Almoxarifado<br>NGI Carajás</h2>", unsafe_allow_html=True)
            usuario_input = st.text_input("Usuário / E-mail", placeholder="Digite seu e-mail...").strip()
            senha_input = st.text_input("Senha", type="password", placeholder="Digite sua senha...").strip()
            st.markdown("<br>", unsafe_allow_html=True)
            
            if st.button("Entrar no Sistema", type="primary", use_container_width=True):
                if usuario_input and senha_input:
                    df_users = st.session_state.usuarios
                    user_match = df_users[(df_users["E-mail"] == usuario_input) & (df_users["Senha"] == senha_input)]
                    
                    if not user_match.empty:
                        st.session_state.autenticado = True
                        st.session_state.NOME_USUARIO_LOGADO = user_match.iloc[0]['Nome']
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
            email_recuperar = st.text_input("E-mail corporativo", placeholder="exemplo@icmbio.gov.br")
            if st.button("Enviar Instruções", type="primary", use_container_width=True):
                if email_recuperar.strip():
                    try:
                        msg = MIMEMultipart()
                        msg['From'] = EMAIL_REMETENTE
                        msg['To'] = email_recuperar.strip()
                        msg['Subject'] = "Recuperação de Senha - Sistema de Almoxarifado NGI Carajás"
                        corpo_email = f"""
                        Olá,
                        Recebemos uma solicitação de recuperação de acesso para o seu usuário.
                        Sua senha cadastrada no sistema é: 123 (Padrão de Contingência)
                        Por favor, acesse o sistema e verifique seus dados.
                        Atenciosamente,
                        Suporte NGI Carajás / ICMBio
                        """
                        msg.attach(MIMEText(corpo_email, 'plain'))
                        server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
                        server.starttls()
                        server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
                        server.sendmail(EMAIL_REMETENTE, email_recuperar.strip(), msg.as_string())
                        server.quit()
                        st.success("Sucesso! Instruções de recuperação enviadas.")
                    except Exception as e:
                        st.error(f"Erro ao enviar o e-mail: {e}")
            if st.button("Voltar para o Login", use_container_width=True):
                st.session_state.sub_tela_login = "login"
                st.rerun()

# =============================================================================
# FLUXO 2: SISTEMA PRINCIPAL (APÓS ESTAR AUTENTICADO)
# =============================================================================
else:
    with st.sidebar:
        st.markdown(f"#### 👤 Olá, {st.session_state.NOME_USUARIO_LOGADO}")
        st.write("---")
        menu_opcoes = ["🎛️ Painel Geral", "➕ Cadastrar Produto", "🗂️ Cadastrar Categoria", "👥 Cadastrar Usuário", "🏢 Cadastrar Coordenação", "🔄 Movimentação de Entrada e Saída", "🚪 Sair"]
        escolha = st.radio("", menu_opcoes, label_visibility="collapsed")

    # --- TELA: PAINEL GERAL ---
    if escolha == "🎛️ Painel Geral":
        st.title("🎛️ Painel Geral de Estoque")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total de Itens Cadastrados", len(st.session_state.produtos))
        c2.metric("Produtos Esgotados", len(st.session_state.produtos[st.session_state.produtos['Quantidade'] == 0]) if not st.session_state.produtos.empty else 0)
        c3.metric("Movimentações Realizadas", len(st.session_state.movimentacoes))
        st.write("---")
        
        st.write("### 📋 Estoque Atualizado")
        if st.session_state.produtos.empty:
            st.info("Nenhum material cadastrado na planilha.")
        else:
            df_disp = st.session_state.produtos.copy()
            df_disp["Valor Total"] = df_disp["Quantidade"] * df_disp["Valor Unitário"]
            df_disp["Valor Unitário"] = df_disp["Valor Unitário"].map("R$ {:.2f}".format)
            df_disp["Valor Total"] = df_disp["Valor Total"].map("R$ {:.2f}".format)
            st.dataframe(df_disp, use_container_width=True, hide_index=True)

    # --- TELA: CADASTRAR PRODUTO ---
    elif escolha == "➕ Cadastrar Produto":
        st.title("➕ Gerenciamento de Produtos")
        with st.form("form_novo_produto", clear_on_submit=True):
            cod = st.text_input("Código")
            name_it = st.text_input("Nome do Material")
            cat_it = st.selectbox("Categoria", st.session_state.categorias)
            val_unit = st.number_input("Valor Unitário (R$)", min_value=0.0, step=0.01, format="%.2f")
            if st.form_submit_button("Finalizar Cadastro", type="primary"):
                if cod and name_it:
                    if not st.session_state.produtos.empty and str(cod) in st.session_state.produtos["Código"].astype(str).values:
                        st.error(f"Erro! Código {cod} já existe.")
                    else:
                        novo_p = {"Código": str(cod), "Item": name_it, "Quantidade": 0, "Categoria": cat_it, "Valor Unitário": float(val_unit)}
                        updated_df = pd.concat([st.session_state.produtos, pd.DataFrame([novo_p])], ignore_index=True)
                        conn.update(worksheet="produtos", data=updated_df)
                        st.success(f"Sucesso! {name_it} salvo diretamente no seu Google Drive!")
                        st.rerun()
                else:
                    st.error("Preencha todos os campos!")

    # --- TELA: CADASTRAR CATEGORIA ---
    elif escolha == "🗂️ Cadastrar Categoria":
        st.title("🗂️ Gerenciamento de Categorias")
        nova_cat = st.text_input("Nome da Nova Categoria:")
        if st.button("Adicionar Categoria", type="primary"):
            if nova_cat and nova_cat.strip() not in st.session_state.categorias:
                st.session_state.categorias.append(nova_cat.strip())
                df_updated_cat = pd.DataFrame(st.session_state.categorias, columns=["Categoria"])
                conn.update(worksheet="categorias", data=df_updated_cat)
                st.success("Categoria guardada na nuvem!")
                st.rerun()
        st.dataframe(pd.DataFrame(st.session_state.categorias, columns=["Categorias Ativas"]), use_container_width=True, hide_index=True)

    # --- TELA: CADASTRAR USUÁRIO ---
    elif escolha == "👥 Cadastrar Usuário":
        st.title("👥 Cadastrar Usuário")
        with st.form("cad_user", clear_on_submit=True):
            n = st.text_input("Nome")
            e = st.text_input("E-mail")
            s = st.text_input("Senha", type="password")
            p = st.selectbox("Perfil", ["Administrador", "Usuário Comum"])
            if st.form_submit_button("Salvar", type="primary"):
                if n and e and s:
                    new_u = {"Nome": n, "E-mail": e, "Senha": str(s), "Perfil": p}
                    updated_df = pd.concat([st.session_state.usuarios, pd.DataFrame([new_u])], ignore_index=True)
                    conn.update(worksheet="usuarios", data=updated_df)
                    st.success(f"Usuário {n} gravado com sucesso no Google Drive!")
                    st.rerun()
                else:
                    st.error("Preencha todos os campos obrigatórios!")

    # --- TELA: CADASTRAR COORDENAÇÃO ---
    elif escolha == "🏢 Cadastrar Coordenação":
        st.title("🏢 Cadastrar Coordenação")
        with st.form("cad_coord", clear_on_submit=True):
            s_coord = st.text_input("Sigla")
            nc = st.text_input("Nome da Coordenação")
            if st.form_submit_button("Cadastrar", type="primary"):
                if s_coord and nc:
                    nova_coord = {"Sigla": s_coord.upper(), "Nome": nc}
                    updated_df = pd.concat([st.session_state.coordenacoes, pd.DataFrame([nova_coord])], ignore_index=True)
                    conn.update(worksheet="coordenacoes", data=updated_df)
                    st.success("Coordenação salva!")
                    st.rerun()
        st.dataframe(st.session_state.coordenacoes, use_container_width=True, hide_index=True)

    # --- TELA: MOVIMENTAÇÃO DE ENTRADA E SAÍDA ---
    elif escolha == "🔄 Movimentação de Entrada e Saída":
        st.title("🔄 Movimentação de Entrada e Saída")
        if st.session_state.produtos.empty:
            st.warning("Cadastre algum produto primeiro.")
        else:
            idx_prod = st.selectbox("Selecione o Material:", st.session_state.produtos.index, format_func=lambda x: f"{st.session_state.produtos.loc[x, 'Item']} (Saldo atual: {st.session_state.produtos.loc[x, 'Quantidade']})")
            qtd = st.number_input("Quantidade da Operação:", min_value=1, step=1)
            tipo = st.radio("Tipo:", ["Entrada", "Saída"])
            responsavel = st.text_input("Responsável:")
            lista_coord = st.session_state.coordenacoes["Sigla"].tolist() if not st.session_state.coordenacoes.empty else ["Geral"]
            coord_solic = st.selectbox("Coordenação:", lista_coord)
            
            if st.button("Confirmar Lançamento", type="primary"):
                qtd_atual = st.session_state.produtos.loc[idx_prod, "Quantidade"]
                if tipo == "Saída" and qtd > qtd_atual:
                    st.error("Saldo insuficiente para esta saída.")
                else:
                    if tipo == "Entrada":
                        st.session_state.produtos.loc[idx_prod, "Quantidade"] += qtd
                    else:
                        st.session_state.produtos.loc[idx_prod, "Quantidade"] -= qtd
                    
                    nova_mov = {
                        "Data": datetime.today().strftime("%d/%m/%Y %H:%M"),
                        "Tipo": tipo.upper(),
                        "Código": str(st.session_state.produtos.loc[idx_prod, "Código"]),
                        "Item": st.session_state.produtos.loc[idx_prod, "Item"],
                        "Quantidade": int(qtd),
                        "Responsável pela Retirada": responsavel if responsavel else "Almoxarifado",
                        "Coordenação": coord_solic
                    }
                    
                    updated_mov_df = pd.concat([st.session_state.movimentacoes, pd.DataFrame([nova_mov])], ignore_index=True)
                    conn.update(worksheet="produtos", data=st.session_state.produtos)
                    conn.update(worksheet="movimentacoes", data=updated_mov_df)
                    st.success("Movimentação processada e salva no Google Sheets!")
                    st.rerun()

    # --- TELA: SAIR ---
    elif escolha == "🚪 Sair":
        st.session_state.autenticado = False
        st.session_state.sub_tela_login = "login"
        st.session_state.NOME_USUARIO_LOGADO = ""
        st.rerun()
