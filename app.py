import streamlit as st
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sqlite3

# =============================================================================
# INICIALIZAÇÃO AUTOMÁTICA DO BANCO DE DADOS (SQLite)
# =============================================================================
def inicializar_banco_automatico():
    # Cria ou conecta ao arquivo de banco de dados na mesma pasta do app
    conn = sqlite3.connect("almoxarifado.db", check_same_thread=False)
    cursor = conn.cursor()
   
    # 1. Cria tabela de usuários automaticamente
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            nome TEXT,
            email TEXT PRIMARY KEY,
            senha TEXT,
            perfil TEXT
        )
    """)
   
    # Garante o usuário Administrador padrão para o primeiro acesso
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO usuarios (nome, email, senha, perfil)
            VALUES ('Administrador Padrão', 'admin@ngi.com', '123', 'Administrador')
        """)
        conn.commit()

    # 2. Cria tabela de produtos automaticamente
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            codigo TEXT PRIMARY KEY,
            item TEXT,
            quantidade INTEGER,
            categoria TEXT,
            valor_unitario REAL
        )
    """)
   
    # Adiciona itens iniciais se a tabela de produtos estiver vazia
    cursor.execute("SELECT COUNT(*) FROM produtos")
    if cursor.fetchone()[0] == 0:
        produtos_iniciais = [
            ("001", "Capacete de Segurança", 15, "EPI", 45.00),
            ("002", "Resma Papel A4", 0, "Material de Escritório", 28.50),
            ("003", "Luva de Raspa", 50, "EPI", 12.00)
        ]
        cursor.executemany("INSERT INTO produtos VALUES (?, ?, ?, ?, ?)", produtos_iniciais)
        conn.commit()

    # 3. Cria tabela de coordenações automaticamente
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS coordenacoes (
            sigla TEXT PRIMARY KEY,
            nome TEXT
        )
    """)
   
    # Adiciona coordenações iniciais se estiver vazia
    cursor.execute("SELECT COUNT(*) FROM coordenacoes")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO coordenacoes VALUES (?, ?)", [
            ("COTEC", "Coordenação Técnica"),
            ("COLOG", "Coordenação de Logística")
        ])
        conn.commit()

    # 4. Cria tabela de categorias automaticamente
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            nome TEXT PRIMARY KEY
        )
    """)
    cursor.execute("SELECT COUNT(*) FROM categorias")
    if cursor.fetchone()[0] == 0:
        cat_iniciais = [("EPI",), ("Material de Escritório",), ("Informática",), ("Limpeza",), ("Copa",)]
        cursor.executemany("INSERT INTO categorias VALUES (?)", cat_iniciais)
        conn.commit()

    # 5. Cria tabela de movimentações automaticamente
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT,
            tipo TEXT,
            codigo TEXT,
            item TEXT,
            quantidade INTEGER,
            responsavel TEXT,
            coordenacao TEXT
        )
    """)
   
    conn.commit()
    return conn

# Ativa o banco de dados
conn = inicializar_banco_automatico()

# =============================================================================
# CONFIGURAÇÕES SEGURAS DE E-MAIL (Secrets do Streamlit)
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

# --- ESTILIZAÇÃO CSS (Manutenção total do seu layout original) ---
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

# --- GERENCIAMENTO DE SESSÃO ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"

if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = ""

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
           
            usuario_input = st.text_input("Usuário / E-mail")
            senha_input = st.text_input("Senha", type="password")
            st.markdown("<br>", unsafe_allow_html=True)
           
            if st.button("Entrar no Sistema", type="primary", use_container_width=True):
                if usuario_input and senha_input:
                    cursor = conn.cursor()
                    cursor.execute("SELECT nome, senha FROM usuarios WHERE LOWER(email) = ?", (usuario_input.strip().lower(),))
                    resultado = cursor.fetchone()
                   
                    if resultado:
                        nome_banco, senha_banco = resultado
                        if str(senha_banco) == str(senha_input).strip():
                            st.session_state.autenticado = True
                            st.session_state.NOME_USUARIO_LOGADO = nome_banco
                            st.rerun()
                        else:
                            st.error("❌ Senha incorreta!")
                    else:
                        st.error("❌ Usuário ou E-mail não cadastrado!")
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
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM usuarios WHERE LOWER(email) = ?", (email_recuperar.strip().lower(),))
                    if cursor.fetchone()[0] > 0:
                        if EMAIL_REMETENTE == "configurar_no_secrets@email.com":
                            st.error("Erro de configuração nos Secrets do Streamlit.")
                        else:
                            try:
                                msg = MIMEMultipart()
                                msg['From'] = EMAIL_REMETENTE
                                msg['To'] = email_recuperar.strip()
                                msg['Subject'] = "Recuperação de Senha - Sistema de Almoxarifado NGI Carajás"
                                corpo_email = f"Sua senha provisória de contingência é: 123"
                                msg.attach(MIMEText(corpo_email, 'plain'))
                                server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
                                server.starttls()
                                server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
                                server.sendmail(EMAIL_REMETENTE, email_recuperar.strip(), msg.as_string())
                                server.quit()
                                st.success(f"Sucesso! Instruções enviadas para {email_recuperar}")
                            except Exception as e:
                                st.error(f"Erro ao tentar enviar o e-mail: {e}")
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
    # Sincroniza as tabelas do SQLite com os DataFrames da tela
    df_produtos = pd.read_sql_query("SELECT codigo AS Código, item AS Item, quantidade AS Quantidade, categoria AS Categoria, valor_unitario AS [Valor Unitário] FROM produtos", conn)
    df_movimentacoes = pd.read_sql_query("SELECT data AS Data, tipo AS Tipo, codigo AS Código, item AS Item, quantidade AS Quantidade, responsavel AS [Responsável pela Retirada], coordenacao AS [Coordenação] FROM movimentacoes", conn)
    df_coordenacoes = pd.read_sql_query("SELECT sigla AS Sigla, nome AS Nome FROM coordenacoes", conn)
   
    df_cat_bruto = pd.read_sql_query("SELECT nome FROM categorias", conn)
    lista_categorias = df_cat_bruto["nome"].tolist()

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

    if escolha == "🚪 Sair":
        st.session_state.autenticado = False
        st.session_state.NOME_USUARIO_LOGADO = ""
        st.rerun()

    # --- TELA: PAINEL GERAL ---
    elif escolha == "🎛️ Painel Geral":
        st.title("🎛️ Painel Geral de Estoque")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total de Itens Cadastrados", len(df_produtos))
        c2.metric("Produtos Esgotados", len(df_produtos[df_produtos['Quantidade'] == 0]) if not df_produtos.empty else 0)
        c3.metric("Movimentações Realizadas", len(df_movimentacoes))
        st.write("---")
       
        st.write("### 🔍 Ferramentas de Busca e Filtro")
        col_filtro1, col_filtro2 = st.columns([2, 1])
        termo_busca = col_filtro1.text_input("Buscar por Nome do Material ou Código:", placeholder="Digite para pesquisar...")
        categoria_selecionada = col_filtro2.selectbox("Filtrar por Categoria:", ["Todas"] + lista_categorias)
       
        df_filtrado = df_produtos.copy()
        if termo_busca:
            df_filtrado = df_filtrado[df_filtrado['Item'].str.contains(termo_busca, case=False, na=False) | df_filtrado['Código'].str.contains(termo_busca, case=False, na=False)]
        if categoria_selecionada != "Todas":
            df_filtrado = df_filtrado[df_filtrado['Category'] == categoria_selecionada] if 'Category' in df_filtrado.columns else df_filtrado[df_filtrado['Categoria'] == categoria_selecionada]

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
                st.caption("ℹ️ Novos materiais são registrados com saldo inicial 0.")
               
                if st.form_submit_button("Finalizar Cadastro", type="primary"):
                    if cod and nome_it:
                        try:
                            cursor = conn.cursor()
                            cursor.execute("INSERT INTO produtos VALUES (?, ?, ?, ?, ?)", (cod.strip(), nome_it.strip(), 0, cat_it, float(val_unit)))
                            conn.commit()
                            st.success(f"Sucesso! {nome_it} adicionado.")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error(f"Erro! Código {cod} já existe.")
                    else:
                        st.error("Preencha todos os campos!")
                       
        with aba_gerenciar_prod:
            if not df_produtos.empty:
                st.dataframe(df_produtos, use_container_width=True, hide_index=True)
               
                df_raw_prod = pd.read_sql_query("SELECT * FROM produtos", conn)
                opcao_selecionada = st.selectbox("Selecione para modificar:", df_raw_prod.index, format_func=lambda x: f"{df_raw_prod.loc[x, 'codigo']} - {df_raw_prod.loc[x, 'item']}")
               
                cod_atual = df_raw_prod.loc[opcao_selecionada, "codigo"]
               
                col_ed1, col_ed2 = st.columns(2)
                edit_cod = col_ed1.text_input("Código:", value=df_raw_prod.loc[opcao_selecionada, "codigo"])
                edit_item = col_ed2.text_input("Nome:", value=df_raw_prod.loc[opcao_selecionada, "item"])
                edit_qtd = col_ed1.number_input("Quantidade (Ajuste):", min_value=0, value=int(df_raw_prod.loc[opcao_selecionada, "quantidade"]))
               
                cat_atual = df_raw_prod.loc[opcao_selecionada, "categoria"]
                idx_cat_padrao = lista_categorias.index(cat_atual) if cat_atual in lista_categorias else 0
                edit_cat = col_ed2.selectbox("Categoria:", lista_categorias, index=idx_cat_padrao)
                edit_val = st.number_input("Valor Unitário:", min_value=0.0, step=0.01, format="%.2f", value=float(df_raw_prod.loc[opcao_selecionada, "valor_unitario"]))
               
                col_b_prod1, col_b_prod2 = st.columns([1, 4])
                with col_b_prod1:
                    if st.button("Salvar Alterações", type="primary"):
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE produtos
                            SET codigo = ?, item = ?, quantidade = ?, categoria = ?, valor_unitario = ?
                            WHERE codigo = ?
                        """, (edit_cod.strip(), edit_item.strip(), edit_qtd, edit_cat, float(edit_val), cod_atual))
                        conn.commit()
                        st.success("Modificado com sucesso!")
                        st.rerun()
                with col_b_prod2:
                    if st.button("❌ Excluir Produto"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM produtos WHERE codigo = ?", (cod_atual,))
                        conn.commit()
                        st.warning("Removido com sucesso.")
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
                            cursor = conn.cursor()
                            cursor.execute("INSERT INTO categorias VALUES (?)", (nova_cat.strip(),))
                            conn.commit()
                            st.success("Adicionada!")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Esta categoria já existe.")
            with col_cat2:
                st.dataframe(pd.DataFrame(lista_categorias, columns=["Categorias Ativas"]), use_container_width=True, hide_index=True)
               
        with aba_gerenciar_cat:
            if lista_categorias:
                cat_selecionada = st.selectbox("Selecione a categoria:", lista_categorias)
                edit_nome_cat = st.text_input("Editar Nome:", value=cat_selecionada)
               
                c_btn_cat1, c_btn_cat2 = st.columns([1, 4])
                with c_btn_cat1:
                    if st.button("Salvar Edição", type="primary"):
                        cursor = conn.cursor()
                        cursor.execute("UPDATE categorias SET nome = ? WHERE nome = ?", (edit_nome_cat.strip(), cat_selecionada))
                        conn.commit()
                        st.success("Atualizado!")
                        st.rerun()
                with c_btn_cat2:
                    if st.button("❌ Excluir Categoria"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM categorias WHERE nome = ?", (cat_selecionada,))
                        conn.commit()
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
                            cursor = conn.cursor()
                            cursor.execute("""
                                INSERT INTO usuarios (nome, email, senha, perfil)
                                VALUES (?, ?, ?, ?)
                            """, (n.strip(), e.strip().lower(), s if s else "123", p))
                            conn.commit()
                            st.success("Usuário registrado com sucesso!")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Este e-mail já está cadastrado.")
                        except sqlite3.OperationalError as err:
                            st.error(f"Inconsistência no banco de dados local: {err}")
                            st.info("Tentando reajustar a estrutura... Por favor, tente enviar novamente.")
                            try:
                                cursor.execute("CREATE TABLE IF NOT EXISTS usuarios (nome TEXT, email TEXT PRIMARY KEY, senha TEXT, perfil TEXT)")
                                conn.commit()
                            except:
                                pass
                    else:
                        st.error("Preencha o Nome e o E-mail!")
                       
        with aba_edit:
            df_raw_users = pd.read_sql_query("SELECT * FROM usuarios", conn)
            if not df_raw_users.empty:
                st.dataframe(df_raw_users[["nome", "email", "perfil"]], use_container_width=True, hide_index=True)
               
                idx_user = st.selectbox("Selecione para editar:", df_raw_users.index, format_func=lambda x: df_raw_users.loc[x, "nome"])
                email_chave = df_raw_users.loc[idx_user, "email"]
               
                edit_n = st.text_input("Nome:", value=df_raw_users.loc[idx_user, "nome"])
                edit_e = st.text_input("E-mail:", value=df_raw_users.loc[idx_user, "email"])
                edit_s = st.text_input("Senha:", value=df_raw_users.loc[idx_user, "senha"], type="password")
                edit_p = st.selectbox("Perfil:", ["Administrador", "Usuário Comum"], index=0 if df_raw_users.loc[idx_user, "perfil"] == "Administrador" else 1)
               
                c_btn_u1, c_btn_u2 = st.columns([1, 4])
                with c_btn_u1:
                    if st.button("Atualizar Dados", type="primary"):
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE usuarios SET nome = ?, email = ?, senha = ?, perfil = ? WHERE email = ?
                        """, (edit_n.strip(), edit_e.strip().lower(), edit_s, edit_p, email_chave))
                        conn.commit()
                        st.success("Atualizado!")
                        st.rerun()
                with c_btn_u2:
                    if st.button("❌ Excluir Usuário"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM usuarios WHERE email = ?", (email_chave,))
                        conn.commit()
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
                        try:
                            cursor = conn.cursor()
                            cursor.execute("INSERT INTO coordenacoes VALUES (?, ?)", (s_coord.strip().upper(), nc.strip()))
                            conn.commit()
                            st.success("Cadastrada!")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Esta sigla já está registrada.")
                    else:
                        st.error("Preencha todos os campos!")
        with aba_c2:
            if not df_coordenacoes.empty:
                st.dataframe(df_coordenacoes, use_container_width=True, hide_index=True)
               
                sigla_selecionada = st.selectbox("Selecione para modificar:", df_coordenacoes["Sigla"].tolist())
                cursor = conn.cursor()
                cursor.execute("SELECT nome FROM coordenacoes WHERE sigla = ?", (sigla_selecionada,))
                nome_atual_c = cursor.fetchone()[0]
               
                edit_sigla = st.text_input("Sigla:", value=sigla_selecionada)
                edit_nc = st.text_input("Nome:", value=nome_atual_c)
               
                c_btn_co1, c_btn_co2 = st.columns([1, 4])
                with c_btn_co1:
                    if st.button("Salvar Edição", type="primary"):
                        cursor = conn.cursor()
                        cursor.execute("UPDATE coordenacoes SET sigla = ?, nome = ? WHERE sigla = ?", (edit_sigla.strip().upper(), edit_nc.strip(), sigla_selecionada))
                        conn.commit()
                        st.success("Salvo!")
                        st.rerun()
                with c_btn_co2:
                    if st.button("❌ Excluir Coordenação"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM coordenacoes WHERE sigla = ?", (sigla_selecionada,))
                        conn.commit()
                        st.warning("Removida.")
                        st.rerun()

    # --- TELA: MOVIMENTAÇÃO DE ENTRADA E SAÍDA ---
    elif escolha == "🔄 Movimentação de Entrada e Saída":
        st.title("🔄 Movimentação de Entrada e Saída")
        aba_entrada, aba_saida, aba_historico = st.tabs(["📥 Registrar Entrada", "📤 Registrar Saída", "📋 Histórico de Entradas/Saídas"])
       
        df_raw_prod = pd.read_sql_query("SELECT * FROM produtos", conn)
       
        with aba_entrada:
            if df_raw_prod.empty:
                st.info("Nenhum material cadastrado para movimentação.")
            else:
                with st.form("form_registrar_entrada", clear_on_submit=True):
                    col_e1, col_e2 = st.columns(2)
                    data_entrada = col_e1.date_input("Data:", value=datetime.today(), format="DD/MM/YYYY")
                    idx_prod_ent = col_e2.selectbox("Material:", df_raw_prod.index, format_func=lambda x: f"{df_raw_prod.loc[x, 'codigo']} - {df_raw_prod.loc[x, 'item']} (Saldo: {df_raw_prod.loc[x, 'quantidade']})", key="mov_ent_prod")
                    qtd_entrada = st.number_input("Quantidade Entrada:", min_value=1, step=1)
                   
                    if st.form_submit_button("Confirmar Entrada", type="primary"):
                        cod_p = df_raw_prod.loc[idx_prod_ent, "codigo"]
                        nome_p = df_raw_prod.loc[idx_prod_ent, "item"]
                        novo_saldo = int(df_raw_prod.loc[idx_prod_ent, "quantidade"]) + qtd_entrada
                       
                        cursor = conn.cursor()
                        cursor.execute("UPDATE produtos SET quantidade = ? WHERE codigo = ?", (novo_saldo, cod_p))
                        cursor.execute("""
                            INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (data_entrada.strftime("%d/%m/%Y"), "Entrada", cod_p, nome_p, qtd_entrada, "Almoxarifado", "-"))
                        conn.commit()
                        st.success("Entrada registrada com sucesso!")
                        st.rerun()
                       
        with aba_saida:
            if df_raw_prod.empty:
                st.info("Nenhum material cadastrado para movimentação.")
            else:
                with st.form("form_registrar_saida", clear_on_submit=True):
                    col_s1, col_s2 = st.columns(2)
                    data_saida = col_s1.date_input("Data:", value=datetime.today(), format="DD/MM/YYYY")
                    idx_prod_sai = col_s2.selectbox("Material:", df_raw_prod.index, format_func=lambda x: f"{df_raw_prod.loc[x, 'codigo']} - {df_raw_prod.loc[x, 'item']} (Saldo: {df_raw_prod.loc[x, 'quantidade']})", key="mov_sai_prod")
                    qtd_saida = col_s1.number_input("Quantidade Saída:", min_value=1, step=1)
                   
                    lista_coord = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["Sem Coordenações"]
                    coord_retirada = col_s2.selectbox("Destino:", lista_coord)
                    resp_retirada = st.text_input("Responsável pela Retirada:")
                   
                    if st.form_submit_button("Confirmar Saída", type="primary"):
                        cod_p = df_raw_prod.loc[idx_prod_sai, "codigo"]
                        nome_p = df_raw_prod.loc[idx_prod_sai, "item"]
                        qtd_disp = int(df_raw_prod.loc[idx_prod_sai, "quantidade"])
                       
                        if not resp_retirada.strip():
                            st.error("❌ Por favor, preencha o nome do responsável pela retirada.")
                        elif qtd_saida > qtd_disp:
                            st.error(f"❌ Quantidade insuficiente em estoque! Saldo atual de {nome_p}: {qtd_disp}")
                        else:
                            novo_saldo = qtd_disp - qtd_saida
                            cursor = conn.cursor()
                            cursor.execute("UPDATE produtos SET quantidade = ? WHERE codigo = ?", (novo_saldo, cod_p))
                            cursor.execute("""
                                INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (data_saida.strftime("%d/%m/%Y"), "Saída", cod_p, nome_p, qtd_saida, resp_retirada.strip(), coord_retirada))
                            conn.commit()
                            st.success("Saída registrada com sucesso!")
                            st.rerun()

        with aba_historico:
            st.write("### 📋 Histórico Completo de Movimentações")
            if df_movimentacoes.empty:
                st.info("Nenhuma movimentação registrada até o momento.")
            else:
                st.dataframe(df_movimentacoes, use_container_width=True, hide_index=True)
