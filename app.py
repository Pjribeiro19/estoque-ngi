import streamlit as st
import pandas as pd
from datetime import datetime, date
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import psycopg2
from psycopg2.extras import DictCursor
from streamlit_option_menu import option_menu
import os

# =============================================================================
# CONEXÃO E INICIALIZAÇÃO AUTOMÁTICA DO BANCO DE DADOS (Neon Postgres)
# =============================================================================
def obter_conexao():
    try:
        conn_string = os.environ.get("POSTGRES_URL") or st.secrets["postgres"]["url"]
        conn = psycopg2.connect(conn_string)
        return conn
    except Exception as e:
        st.error(f"Erro ao conectar ao Neon Postgres: {e}")
        st.info("Verifique as credenciais na aba 'Variables' do Railway ou Secrets do Streamlit.")
        st.stop()

def inicializar_banco_automatico():
    conn = obter_conexao()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config_sistema (
                chave TEXT PRIMARY KEY,
                valor TEXT
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                nome TEXT,
                email TEXT PRIMARY KEY,
                senha TEXT,
                perfil TEXT
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS produtos (
                codigo TEXT PRIMARY KEY,
                item TEXT,
                quantidade INTEGER,
                categoria TEXT,
                valor_unitario REAL
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS coordenacoes (
                sigla TEXT PRIMARY KEY,
                nome TEXT
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categorias (
                nome TEXT PRIMARY KEY
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS movimentacoes (
                id SERIAL PRIMARY KEY,
                data TEXT,
                tipo TEXT,
                codigo TEXT,
                item TEXT,
                quantidade INTEGER,
                responsavel TEXT,
                coordenacao TEXT
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS itens_emprestimo (
                codigo TEXT PRIMARY KEY,
                nome TEXT,
                quantidade INTEGER
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS emprestimos (
                id SERIAL PRIMARY KEY,
                codigo TEXT,
                item TEXT,
                quantidade INTEGER,
                solicitante TEXT,
                coordenacao TEXT,
                data_saida DATE,
                data_devolucao_prevista DATE,
                data_devolucao_real DATE,
                status TEXT
            );
        """)

        conn.commit()

        cursor.execute("SELECT valor FROM config_sistema WHERE chave = 'seed_inicial';")
        seed_realizado = cursor.fetchone()

        if not seed_realizado:
            cursor.execute("SELECT COUNT(*) FROM usuarios;")
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    INSERT INTO usuarios (nome, email, senha, perfil) 
                    VALUES ('Administrador Padrão', 'admin@ngi.com', '123', 'Administrador');
                """)

            cursor.execute("SELECT COUNT(*) FROM produtos;")
            if cursor.fetchone()[0] == 0:
                produtos_iniciais = [
                    ("001", "Capacete de Segurança", 15, "EPI", 45.00),
                    ("002", "Resma Papel A4", 0, "Material de Escritório", 28.50),
                    ("003", "Luva de Raspa", 50, "EPI", 12.00)
                ]
                cursor.executemany("INSERT INTO produtos VALUES (%s, %s, %s, %s, %s);", produtos_iniciais)

            cursor.execute("SELECT COUNT(*) FROM coordenacoes;")
            if cursor.fetchone()[0] == 0:
                cursor.executemany("INSERT INTO coordenacoes VALUES (%s, %s);", [
                    ("COTEC", "Coordenação Técnica"),
                    ("COLOG", "Coordenação de Logística")
                ])

            cursor.execute("SELECT COUNT(*) FROM categorias;")
            if cursor.fetchone()[0] == 0:
                cat_iniciais = [("EPI",), ("Material de Escritório",), ("Informática",), ("Limpeza",), ("Copa",)]
                cursor.executemany("INSERT INTO categorias VALUES (%s);", cat_iniciais)

            cursor.execute("INSERT INTO config_sistema (chave, valor) VALUES ('seed_inicial', 'true');")
            conn.commit()

    except Exception as e:
        conn.rollback()
        st.error(f"Erro ao inicializar o banco de dados: {e}")

    return conn

conn = inicializar_banco_automatico()

# Carregamento seguro e global dos dados
try:
    df_produtos = pd.read_sql_query('SELECT codigo AS "Código", item AS "Item", quantidade AS "Quantidade", categoria AS "Categoria", valor_unitario AS "Valor Unitário" FROM produtos', conn)
    df_movimentacoes = pd.read_sql_query('SELECT data AS "Data", tipo AS "Tipo", codigo AS "Código", item AS "Item", quantidade AS "Quantidade", responsavel AS "Responsável", coordenacao AS "Coordenação" FROM movimentacoes', conn)
    df_coordenacoes = pd.read_sql_query('SELECT sigla AS "Sigla", nome AS "Nome" FROM coordenacoes', conn)
    df_cat_bruto = pd.read_sql_query("SELECT nome FROM categorias", conn)
    lista_categorias = df_cat_bruto["nome"].tolist() if not df_cat_bruto.empty else []
except Exception as e:
    df_produtos = pd.DataFrame()
    df_movimentacoes = pd.DataFrame()
    df_coordenacoes = pd.DataFrame()
    lista_categorias = []

# =============================================================================
# CONFIGURAÇÕES SEGURAS DE E-MAIL (Suporte Híbrido Railway / Secrets)
# =============================================================================
try:
    EMAIL_REMETENTE = os.environ.get("GMAIL_EMAIL") or st.secrets["gmail"]["email"]
    SENHA_REMETENTE = os.environ.get("GMAIL_SENHA") or st.secrets["gmail"]["senha"]
    SMTP_HOST = os.environ.get("GMAIL_SMTP_SERVER") or st.secrets["gmail"]["smtp_server"]
    SMTP_PORTA = int(os.environ.get("GMAIL_SMTP_PORT") or st.secrets["gmail"]["smtp_port"])
except Exception as e:
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

# --- ESTILIZAÇÃO CSS COMPATÍVEL ---
st.markdown("""
    <style>
    [data-testid="stSidebarNav"] {display: none;}
    [data-testid="stMainMenu"] {display: none;}
    
    html, body, [data-testid="stWidgetLabel"] p, .stMarkdown p, label, span {
        color: var(--text-color) !important;
    }
    
    .nav-link span {
        color: var(--text-color) !important;
    }
    
    .nav-link.active span {
        color: white !important;
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
        background-color: white; 
        padding: 15px;
        border-radius: 8px;
    }
    </style>
""", unsafe_allow_html=True)

# Dicionário de estilo adaptativo para os menus horizontais
ESTILO_MENU_HORIZONTAL = {
    "container": {"padding": "0!important", "background-color": "transparent"},
    "icon": {"color": "#64748b", "font-size": "14px"}, 
    "nav-link": {
        "font-size": "14px", 
        "text-align": "center", 
        "margin": "0px 5px", 
        "color": "var(--text-color)",
        "--hover-color": "rgba(76, 175, 80, 0.12)"
    },
    "nav-link-selected": {
        "background-color": "#4CAF50", 
        "color": "white", 
        "font-weight": "500"
    },
}

# --- GERENCIAMENTO DE SESSÃO ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"

if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = ""

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
            st.markdown("<h2 style='text-align: center; color: #4CAF50; margin-top: 10px; margin-bottom: 25px; font-family: sans-serif;'>Gestão de Almoxarifado<br>NGI Carajás</h2>", unsafe_allow_html=True)
            
            usuario_input = st.text_input("Usuário / E-mail")
            senha_input = st.text_input("Senha", type="password")
            st.markdown("<br>", unsafe_allow_html=True)
            
            if st.button("Entrar no Sistema", type="primary", use_container_width=True):
                if usuario_input and senha_input:
                    cursor = conn.cursor()
                    cursor.execute("SELECT nome, senha FROM usuarios WHERE LOWER(email) = %s;", (usuario_input.strip().lower(),))
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
                    cursor.execute("SELECT COUNT(*) FROM usuarios WHERE LOWER(email) = %s;", (email_recuperar.strip().lower(),))
                    if cursor.fetchone()[0] > 0:
                        if EMAIL_REMETENTE == "configurar_no_secrets@email.com":
                            st.error("Erro de configuração nos Secrets do Streamlit / Railway Variables.")
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
    # --- MENU LATERAL ---
    with st.sidebar:
        st.markdown(f"#### 👤 Olá, {st.session_state.NOME_USUARIO_LOGADO}")
        st.write("---")
        
        escolha = option_menu(
            menu_title=None,
            options=[
                "Painel Geral", 
                "Cadastrar Produto", 
                "Cadastrar Categoria", 
                "Cadastrar Usuário", 
                "Cadastrar Coordenação",
                "Movimentação de Estoque",
                "Empréstimo de Material",
                "Sair do Sistema"
            ],
            icons=["grid", "box", "folder", "person-plus", "building", "arrow-left-right", "handbag", "box-arrow-right"],
            menu_icon="cast",
            default_index=0,
            styles={
                "container": {"padding": "0!important", "background-color": "transparent"},
                "icon": {"color": "#64748b", "font-size": "15px"}, 
                "nav-link": {
                    "font-size": "14px", 
                    "text-align": "left", 
                    "margin": "0px", 
                    "color": "var(--text-color)",
                    "--hover-color": "rgba(76, 175, 80, 0.12)"
                },
                "nav-link-selected": {
                    "background-color": "#4CAF50", 
                    "color": "white", 
                    "font-weight": "500"
                },
            }
        )

    if escolha == "Sair do Sistema":
        st.session_state.autenticado = False
        st.session_state.NOME_USUARIO_LOGADO = ""
        st.rerun()

    # --- TELA: PAINEL GERAL ---
    elif escolha == "Painel Geral":
        st.markdown("""
            <div style="background-color: #4CAF50; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
                <h1 style="color: white; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                    Painel Geral de Controle
                </h1>
                <p style="color: #E8F5E9; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Visão Geral de Saldos, Alertas de Materiais e Fluxo de Insumos NGI Carajás
                </p>
            </div>
        """, unsafe_allow_html=True)
        
        c1, c2, c3 = st.columns(3)
        total_itens = len(df_produtos) if not df_produtos.empty else 0
        produtos_esgotados = len(df_produtos[df_produtos['Quantidade'] == 0]) if not df_produtos.empty else 0
        total_movimentacoes = len(df_movimentacoes) if not df_movimentacoes.empty else 0
        
        c1.markdown(f"""
            <div style="background-color: rgba(76, 175, 80, 0.08); border-left: 5px solid #4CAF50; padding: 18px; border-radius: 4px;">
                <span style="font-size: 13px; font-weight: 600; text-transform: uppercase;">Total de Itens Cadastrados</span>
                <h2 style="color: #4CAF50; margin: 8px 0 0 0; font-size: 34px; font-weight: 700;">{total_itens}</h2>
            </div>
        """, unsafe_allow_html=True)
        
        cor_esgotados = "#c62828" if produtos_esgotados > 0 else "#4CAF50"
        bg_esgotados = "rgba(198, 40, 40, 0.08)" if produtos_esgotados > 0 else "rgba(76, 175, 80, 0.08)"
        
        c2.markdown(f"""
            <div style="background-color: {bg_esgotados}; border-left: 5px solid {cor_esgotados}; padding: 18px; border-radius: 4px;">
                <span style="font-size: 13px; font-weight: 600; text-transform: uppercase;">Produtos Esgotados</span>
                <h2 style="color: {cor_esgotados}; margin: 8px 0 0 0; font-size: 34px; font-weight: 700;">{produtos_esgotados}</h2>
            </div>
        """, unsafe_allow_html=True)
        
        c3.markdown(f"""
            <div style="background-color: rgba(33, 150, 243, 0.08); border-left: 5px solid #2196F3; padding: 18px; border-radius: 4px;">
                <span style="font-size: 13px; font-weight: 600; text-transform: uppercase;">Movimentações Realizadas</span>
                <h2 style="color: #2196F3; margin: 8px 0 0 0; font-size: 34px; font-weight: 700;">{total_movimentacoes}</h2>
            </div>
        """, unsafe_allow_html=True)
        
        st.markdown("<br><hr style='margin: 10px 0 25px 0; opacity: 0.15;'>", unsafe_allow_html=True)
        st.markdown('<h3 style="font-size: 18px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center;"><span style="display: inline-block; width: 6px; height: 18px; background-color: #4CAF50; margin-right: 8px; border-radius: 2px;"></span>Filtros de Consulta</h3>', unsafe_allow_html=True)
        
        col_filtro1, col_filtro2 = st.columns([2, 1])
        termo_busca = col_filtro1.text_input("Buscar por Nome do Material ou Código:", placeholder="Digite o termo para pesquisar...")
        categoria_selecionada = col_filtro2.selectbox("Filtrar por Categoria:", ["Todas"] + lista_categorias)
        
        df_filtrado = df_produtos.copy() if not df_produtos.empty else pd.DataFrame()
        if not df_filtrado.empty and termo_busca:
            df_filtrado = df_filtrado[df_filtrado['Item'].str.contains(termo_busca, case=False, na=False) | df_filtrado['Código'].str.contains(termo_busca, case=False, na=False)]
        if not df_filtrado.empty and categoria_selecionada != "Todas":
            df_filtrado = df_filtrado[df_filtrado['Categoria'] == categoria_selecionada]

        st.markdown("<br><h3 style='font-size: 18px; font-weight: 600; margin-bottom: 12px;'>📋 Posição Atual do Estoque</h3>", unsafe_allow_html=True)
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
                    return ['background-color: rgba(198, 40, 40, 0.12); color: #c62828; font-weight: bold;'] * len(row)
                return [''] * len(row)
                
            st.dataframe(df_display.style.apply(destacar_zerados, axis=1), use_container_width=True, hide_index=True)

    # --- TELA: CADASTRAR PRODUTO ---
    elif escolha == "Cadastrar Produto":
        st.title("Gerenciamento de Produtos")
        
        aba_selecionada = option_menu(
            menu_title=None,
            options=["Novo Material", "Editar / Excluir Produtos"],
            icons=["plus-circle", "pencil-square"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )
        
        if aba_selecionada == "Novo Material":
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
                            cursor.execute("INSERT INTO produtos VALUES (%s, %s, %s, %s, %s);", (cod.strip(), nome_it.strip(), 0, cat_it, float(val_unit)))
                            conn.commit()
                            st.success(f"Sucesso! {nome_it} adicionado.")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error(f"Erro! Código {cod} já existe.")
                    else:
                        st.error("Preencha todos os campos!")
                        
        elif aba_selecionada == "Editar / Excluir Produtos":
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
                            SET codigo = %s, item = %s, quantidade = %s, categoria = %s, valor_unitario = %s 
                            WHERE codigo = %s;
                        """, (edit_cod.strip(), edit_item.strip(), edit_qtd, edit_cat, float(edit_val), cod_atual))
                        conn.commit()
                        st.success("Modificado com sucesso!")
                        st.rerun()
                with col_b_prod2:
                    if st.button("Excluir Produto"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM produtos WHERE codigo = %s;", (cod_atual,))
                        conn.commit()
                        st.warning("Removido com sucesso.")
                        st.rerun()

    # --- TELA: CADASTRAR CATEGORIA ---
    elif escolha == "Cadastrar Categoria":
        st.title("Gerenciamento de Categorias")
        
        aba_selecionada = option_menu(
            menu_title=None,
            options=["Nova Categoria", "Editar / Excluir Categorias"],
            icons=["plus-circle", "pencil-square"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )
        
        if aba_selecionada == "Nova Categoria":
            col_cat1, col_cat2 = st.columns([1, 2])
            with col_cat1:
                nova_cat = st.text_input("Nome da Nova Categoria:")
                if st.button("Adicionar Categoria", type="primary"):
                    if nova_cat and nova_cat.strip():
                        try:
                            cursor = conn.cursor()
                            cursor.execute("INSERT INTO categorias VALUES (%s);", (nova_cat.strip(),))
                            conn.commit()
                            st.success("Adicionada!")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error("Esta categoria já existe.")
            with col_cat2:
                st.dataframe(pd.DataFrame(lista_categorias, columns=["Categorias Ativas"]), use_container_width=True, hide_index=True)
                
        elif aba_selecionada == "Editar / Excluir Categorias":
            if lista_categorias:
                cat_selecionada = st.selectbox("Selecione a categoria:", lista_categorias)
                edit_nome_cat = st.text_input("Editar Nome:", value=cat_selecionada)
                
                c_btn_cat1, c_btn_cat2 = st.columns([1, 4])
                with c_btn_cat1:
                    if st.button("Salvar Edição", type="primary"):
                        cursor = conn.cursor()
                        cursor.execute("UPDATE categorias SET nome = %s WHERE nome = %s;", (edit_nome_cat.strip(), cat_selecionada))
                        conn.commit()
                        st.success("Atualizado!")
                        st.rerun()
                with c_btn_cat2:
                    if st.button("Excluir Categoria"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM categorias WHERE nome = %s;", (cat_selecionada,))
                        conn.commit()
                        st.warning("Removida.")
                        st.rerun()

    # --- TELA: CADASTRAR USUÁRIO ---
    elif escolha == "Cadastrar Usuário":
        st.title("Cadastrar Usuário")
        
        aba_selecionada = option_menu(
            menu_title=None,
            options=["Novo Usuário", "Editar / Excluir Usuários"],
            icons=["person-plus", "pencil-square"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )
        
        if aba_selecionada == "Novo Usuário":
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
                                VALUES (%s, %s, %s, %s);
                            """, (n.strip(), e.strip().lower(), s if s else "123", p))
                            conn.commit()
                            st.success("Usuário registrado com sucesso!")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error("Este e-mail já está cadastrado.")
                    else:
                        st.error("Preencha o Nome e o E-mail!")
                        
        elif aba_selecionada == "Editar / Excluir Usuários":
            df_raw_users = pd.read_sql_query("SELECT nome, email, perfil, senha FROM usuarios ORDER BY nome ASC", conn)
            
            if not df_raw_users.empty:
                st.dataframe(df_raw_users[["nome", "email", "perfil"]], use_container_width=True, hide_index=True)
                idx_user = st.selectbox("Selecione para editar:", df_raw_users.index, format_func=lambda x: f"{df_raw_users.loc[x, 'nome']} ({df_raw_users.loc[x, 'email']})")
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
                            UPDATE usuarios SET nome = %s, email = %s, senha = %s, perfil = %s WHERE email = %s;
                        """, (edit_n.strip(), edit_e.strip().lower(), edit_s, edit_p, email_chave))
                        conn.commit()
                        st.success("Atualizado!")
                        st.rerun()
                with c_btn_u2:
                    if st.button("Excluir Usuário"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM usuarios WHERE email = %s;", (email_chave,))
                        conn.commit()
                        st.warning("Removido.")
                        st.rerun()

    # --- TELA: CADASTRAR COORDENAÇÃO ---
    elif escolha == "Cadastrar Coordenação":
        st.title("Cadastrar Coordenação")
        
        aba_selecionada = option_menu(
            menu_title=None,
            options=["Nova Coordenação", "Editar / Excluir Coordenação"],
            icons=["building-add", "pencil-square"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )
        
        if aba_selecionada == "Nova Coordenação":
            with st.form("cad_coord", clear_on_submit=True):
                s_coord = st.text_input("Sigla")
                nc = st.text_input("Nome da Coordenação")
                if st.form_submit_button("Cadastrar", type="primary"):
                    if s_coord and nc:
                        try:
                            cursor = conn.cursor()
                            cursor.execute("INSERT INTO coordenacoes VALUES (%s, %s);", (s_coord.strip().upper(), nc.strip()))
                            conn.commit()
                            st.success("Cadastrada!")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error("Esta sigla já está registrada.")
                    else:
                        st.error("Preencha todos os campos!")
                        
        elif aba_selecionada == "Editar / Excluir Coordenação":
            if not df_coordenacoes.empty:
                st.dataframe(df_coordenacoes, use_container_width=True, hide_index=True)
                sigla_selecionada = st.selectbox("Selecione para modificar:", df_coordenacoes["Sigla"].tolist())
                cursor = conn.cursor()
                cursor.execute("SELECT nome FROM coordenacoes WHERE sigla = %s;", (sigla_selecionada,))
                nome_atual_c = cursor.fetchone()[0]
                
                edit_sigla = st.text_input("Sigla:", value=sigla_selecionada)
                edit_nc = st.text_input("Nome:", value=nome_atual_c)
                
                c_btn_c1, c_btn_c2 = st.columns([1, 4])
                with c_btn_c1:
                    if st.button("Salvar Edição", type="primary"):
                        cursor = conn.cursor()
                        cursor.execute("UPDATE coordenacoes SET sigla = %s, nome = %s WHERE sigla = %s;", (edit_sigla.strip().upper(), edit_nc.strip(), sigla_selecionada))
                        conn.commit()
                        st.success("Atualizado!")
                        st.rerun()
                with c_btn_c2:
                    if st.button("Excluir Coordenação"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM coordenacoes WHERE sigla = %s;", (sigla_selecionada,))
                        conn.commit()
                        st.warning("Removida.")
                        st.rerun()

    # --- TELA: MOVIMENTAÇÃO DE ESTOQUE ---
    elif escolha == "Movimentação de Estoque":
        st.title("Movimentação de Estoque")
        
        aba_selecionada = option_menu(
            menu_title=None,
            options=["Lançar Entrada / Saída", "Histórico de Movimentações"],
            icons=["arrow-down-up", "clock-history"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )
        
        if aba_selecionada == "Lançar Entrada / Saída":
            if df_produtos.empty:
                st.warning("Cadastre produtos antes de lançar movimentações.")
            else:
                with st.form("mov_form", clear_on_submit=True):
                    tp = st.selectbox("Tipo de Movimentação", ["Entrada", "Saída"])
                    prod_sel = st.selectbox("Material / Produto", df_produtos["Item"].tolist())
                    
                    col_m1, col_m2 = st.columns(2)
                    qtd_m = col_m1.number_input("Quantidade", min_value=1, step=1)
                    
                    lista_coords = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["Geral"]
                    coord_m = col_m2.selectbox("Coordenação Destino/Origem", lista_coords)
                    
                    resp_m = st.text_input("Responsável pelo Lançamento / Retirada", value=st.session_state.NOME_USUARIO_LOGADO)
                    
                    if st.form_submit_button("Confirmar Movimentação", type="primary"):
                        cursor = conn.cursor()
                        cursor.execute("SELECT codigo, quantidade FROM produtos WHERE item = %s;", (prod_sel,))
                        prod_info = cursor.fetchone()
                        
                        if prod_info:
                            cod_p, qtd_atual = prod_info
                            if tp == "Saída" and qtd_m > qtd_atual:
                                st.error(f"Quantidade insuficiente em estoque! Saldo atual: {qtd_atual}")
                            else:
                                nova_qtd = qtd_atual + qtd_m if tp == "Entrada" else qtd_atual - qtd_m
                                cursor.execute("UPDATE produtos SET quantidade = %s WHERE codigo = %s;", (nova_qtd, cod_p))
                                
                                data_hoje = datetime.now().strftime("%d/%m/%Y %H:%M")
                                cursor.execute("""
                                    INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                                """, (data_hoje, tp, cod_p, prod_sel, qtd_m, resp_m, coord_m))
                                conn.commit()
                                st.success(f"Movimentação de {tp} realizada com sucesso!")
                                st.rerun()

        elif aba_selecionada == "Histórico de Movimentações":
            if df_movimentacoes.empty:
                st.info("Nenhuma movimentação registrada até o momento.")
            else:
                st.dataframe(df_movimentacoes.sort_index(ascending=False), use_container_width=True, hide_index=True)

    # --- TELA: EMPRÉSTIMO DE MATERIAL ---
    elif escolha == "Empréstimo de Material":
        st.title("Empréstimo de Material")

        aba_emp = option_menu(
            menu_title=None,
            options=["Cadastrar Item p/ Empréstimo", "Novo Empréstimo", "Devolução", "Histórico de Empréstimos"],
            icons=["box-seam", "handbag", "arrow-return-left", "clock-history"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )

        df_itens_emp = pd.read_sql_query('SELECT codigo AS "Código", nome AS "Nome", quantidade AS "Quantidade Total" FROM itens_emprestimo', conn)

        if aba_emp == "Cadastrar Item p/ Empréstimo":
            sub_tab = option_menu(
                menu_title=None,
                options=["Cadastrar Item", "Editar / Excluir Item"],
                icons=["plus-circle", "pencil-square"],
                orientation="horizontal",
                styles=ESTILO_MENU_HORIZONTAL
            )

            if sub_tab == "Cadastrar Item":
                with st.form("form_cad_item_emp", clear_on_submit=True):
                    col_ie1, col_ie2 = st.columns(2)
                    c_ie = col_ie1.text_input("Código do Item")
                    n_ie = col_ie2.text_input("Nome do Item / Equipamento")
                    q_ie = st.number_input("Quantidade Total Disponível para Empréstimo", min_value=1, step=1)

                    if st.form_submit_button("Cadastrar Equipamento", type="primary"):
                        if c_ie and n_ie:
                            try:
                                cursor = conn.cursor()
                                cursor.execute("INSERT INTO itens_emprestimo VALUES (%s, %s, %s);", (c_ie.strip(), n_ie.strip(), int(q_ie)))
                                conn.commit()
                                st.success("Equipamento cadastrado com sucesso!")
                                st.rerun()
                            except psycopg2.IntegrityError:
                                conn.rollback()
                                st.error("Código já cadastrado para empréstimos!")
                        else:
                            st.error("Preencha todos os campos!")

            elif sub_tab == "Editar / Excluir Item":
                if not df_itens_emp.empty:
                    st.dataframe(df_itens_emp, use_container_width=True, hide_index=True)
                    item_sel_code = st.selectbox("Selecione o Item para editar/excluir:", df_itens_emp["Código"].tolist())
                    
                    cursor = conn.cursor()
                    cursor.execute("SELECT nome, quantidade FROM itens_emprestimo WHERE codigo = %s;", (item_sel_code,))
                    row_i = cursor.fetchone()

                    e_nome_ie = st.text_input("Nome do Item:", value=row_i[0])
                    e_qtd_ie = st.number_input("Quantidade Total:", min_value=1, value=int(row_i[1]))

                    col_ie_b1, col_ie_b2 = st.columns([1, 4])
                    with col_ie_b1:
                        if st.button("Salvar Edição", type="primary"):
                            cursor.execute("UPDATE itens_emprestimo SET nome = %s, quantidade = %s WHERE codigo = %s;", (e_nome_ie.strip(), int(e_qtd_ie), item_sel_code))
                            conn.commit()
                            st.success("Atualizado!")
                            st.rerun()
                    with col_ie_b2:
                        if st.button("Excluir Item"):
                            cursor.execute("DELETE FROM itens_emprestimo WHERE codigo = %s;", (item_sel_code,))
                            conn.commit()
                            st.warning("Item removido.")
                            st.rerun()
                else:
                    st.info("Nenhum item cadastrado para empréstimo.")

        elif aba_emp == "Novo Empréstimo":
            if df_itens_emp.empty:
                st.warning("Cadastre primeiro os itens na aba 'Cadastrar Item p/ Empréstimo'.")
            else:
                with st.form("form_novo_emp", clear_on_submit=True):
                    item_emp_nome = st.selectbox("Selecione o Item", df_itens_emp["Nome"].tolist())
                    
                    cursor = conn.cursor()
                    cursor.execute("SELECT codigo, quantidade FROM itens_emprestimo WHERE nome = %s;", (item_emp_nome,))
                    cod_ie, qtd_max_disponivel = cursor.fetchone()

                    col_emp1, col_emp2 = st.columns(2)
                    qtd_solic = col_emp1.number_input("Quantidade a Emprestar", min_value=1, max_value=int(qtd_max_disponivel), step=1)
                    solicitante = col_emp2.text_input("Nome do Solicitante / Servidor")

                    lista_coords = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["Geral"]
                    coord_solic = col_emp1.selectbox("Coordenação", lista_coords)

                    dt_saida = col_emp2.date_input("Data de Saída", value=date.today())
                    dt_dev_prev = col_emp1.date_input("Data Prevista para Devolução", value=date.today())

                    if st.form_submit_button("Registrar Empréstimo", type="primary"):
                        if solicitante:
                            if dt_dev_prev < dt_saida:
                                st.error("A data de devolução não pode ser anterior à data de saída!")
                            else:
                                cursor.execute("""
                                    SELECT SUM(quantidade) FROM emprestimos 
                                    WHERE codigo = %s AND status = 'Ativo'
                                    AND (data_saida <= %s AND data_devolucao_prevista >= %s);
                                """, (cod_ie, dt_dev_prev, dt_saida))
                                emp_conflito = cursor.fetchone()[0] or 0

                                se_disponivel = qtd_max_disponivel - emp_conflito
                                if qtd_solic > se_disponivel:
                                    st.error(f"Conflito de datas! No período selecionado restam apenas {se_disponivel} unidade(s) livre(s).")
                                else:
                                    cursor.execute("""
                                        INSERT INTO emprestimos (codigo, item, quantidade, solicitante, coordenacao, data_saida, data_devolucao_prevista, status)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'Ativo');
                                    """, (cod_ie, item_emp_nome, int(qtd_solic), solicitante.strip(), coord_solic, dt_saida, dt_dev_prev))
                                    conn.commit()
                                    st.success("Empréstimo registrado com sucesso!")
                                    st.rerun()
                        else:
                            st.error("Informe o nome do solicitante!")

        elif aba_emp == "Devolução":
            df_ativos = pd.read_sql_query("SELECT id, codigo, item, quantidade, solicitante, coordenacao, data_saida, data_devolucao_prevista FROM emprestimos WHERE status = 'Ativo'", conn)

            if df_ativos.empty:
                st.info("Não há empréstimos pendentes de devolução no momento.")
            else:
                st.dataframe(df_ativos, use_container_width=True, hide_index=True)
                
                emp_id_sel = st.selectbox("Selecione o Empréstimo para Baixa / Devolução:", df_ativos["id"].tolist(), format_func=lambda x: f"ID {x} - {df_ativos.loc[df_ativos['id']==x, 'item'].values[0]} ({df_ativos.loc[df_ativos['id']==x, 'solicitante'].values[0]})")

                dt_dev_real = st.date_input("Data Real da Devolução", value=date.today())

                if st.button("Confirmar Devolução do Item", type="primary"):
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE emprestimos 
                        SET status = 'Devolvido', data_devolucao_real = %s 
                        WHERE id = %s;
                    """, (dt_dev_real, emp_id_sel))
                    conn.commit()
                    st.success("Devolução realizada com sucesso!")
                    st.rerun()

        elif aba_emp == "Histórico de Empréstimos":
            df_hist = pd.read_sql_query("SELECT id AS 'ID', codigo AS 'Código', item AS 'Item', quantidade AS 'Qtd', solicitante AS 'Solicitante', coordenacao AS 'Coordenação', data_saida AS 'Data Saída', data_devolucao_prevista AS 'Devolução Prevista', data_devolucao_real AS 'Devolução Real', status AS 'Status' FROM emprestimos ORDER BY id DESC", conn)

            if df_hist.empty:
                st.info("Nenhum histórico registrado até o momento.")
            else:
                def colorir_status(val):
                    if val == 'Ativo':
                        return 'background-color: rgba(255, 152, 0, 0.2); color: #orange; font-weight: bold;'
                    elif val == 'Devolvido':
                        return 'background-color: rgba(76, 175, 80, 0.2); color: #4CAF50; font-weight: bold;'
                    return ''

                st.dataframe(df_hist.style.map(colorir_status, subset=['Status']), use_container_width=True, hide_index=True)
