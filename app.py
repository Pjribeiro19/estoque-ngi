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
import threading

# =============================================================================
# CONEXÃO E INICIALIZAÇÃO AUTOMÁTICA DO BANCO DE DADOS (Neon Postgres)
# =============================================================================
@st.cache_resource
def inicializar_banco_automatico():
    conn = None
    try:
        conn_string = os.environ.get("POSTGRES_URL") or st.secrets["postgres"]["url"]
        conn = psycopg2.connect(conn_string)
    except Exception as e:
        st.error(f"Erro ao conectar ao Neon Postgres: {e}")
        st.info("Verifique as credenciais na aba 'Variables' do Railway.")
        st.stop()
        
    cursor = conn.cursor()

    # Tabela de controle de inicialização única
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS config_sistema (
            chave TEXT PRIMARY KEY,
            valor TEXT
        );
    """)

    # 1. Tabela de usuários
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            nome TEXT,
            email TEXT PRIMARY KEY,
            senha TEXT,
            perfil TEXT
        );
    """)

    # 2. Tabela de produtos (Almoxarifado Geral)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            codigo TEXT PRIMARY KEY,
            item TEXT,
            quantidade INTEGER,
            categoria TEXT,
            valor_unitario REAL
        );
    """)

    # 3. Tabela de coordenações
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS coordenacoes (
            sigla TEXT PRIMARY KEY,
            nome TEXT
        );
    """)

    # 4. Tabela de categorias
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            nome TEXT PRIMARY KEY
        );
    """)

    # 5. Tabela de movimentações (Almoxarifado Geral)
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

    # =========================================================================
    # NOVAS TABELAS PARA O MÓDULO INDEPENDENTE DE EMPRÉSTIMOS
    # =========================================================================
    # 6. Tabela de Itens de Empréstimo (Catálogo exclusivo)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emprestimo_itens (
            id SERIAL PRIMARY KEY,
            codigo TEXT UNIQUE,
            item TEXT NOT NULL,
            quantidade_total INTEGER NOT NULL DEFAULT 1,
            quantidade_disponivel INTEGER NOT NULL DEFAULT 1,
            observacao TEXT
        );
    """)

    # 7. Tabela de Registros de Empréstimos e Devoluções
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emprestimo_registros (
            id SERIAL PRIMARY KEY,
            item_id INTEGER REFERENCES emprestimo_itens(id),
            item_nome TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            pessoa TEXT NOT NULL,
            coordenacao TEXT NOT NULL,
            data_retirada DATE NOT NULL,
            data_prevista DATE NOT NULL,
            data_devolucao DATE,
            status TEXT NOT NULL DEFAULT 'EMPRESTADO', -- 'EMPRESTADO' ou 'DEVOLVIDO'
            responsavel_devolucao TEXT
        );
    """)

    # =========================================================================
    # NOVA TABELA PARA O MÓDULO DE SOLICITAÇÕES (USUÁRIO / ADMINISTRADOR)
    # =========================================================================
    # 8. Tabela de Solicitações (nome exclusivo para não colidir com uma
    # tabela "solicitacoes" pré-existente no banco, de outra origem/schema)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solicitacoes_almoxarifado (
            id SERIAL PRIMARY KEY,
            tipo TEXT NOT NULL, -- 'MATERIAL' ou 'EMPRESTIMO'
            referencia_codigo TEXT,
            item_nome TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            solicitante_nome TEXT NOT NULL,
            solicitante_email TEXT NOT NULL,
            coordenacao TEXT,
            data_solicitacao TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            data_retirada DATE,
            data_prevista DATE,
            atividade_associada TEXT,
            status TEXT NOT NULL DEFAULT 'PENDENTE', -- 'PENDENTE', 'APROVADA' ou 'REJEITADA'
            data_decisao TIMESTAMP,
            aprovador TEXT,
            observacao TEXT
        );
    """)

    # Migração idempotente: garante as colunas novas em bancos que já tinham
    # a tabela 'solicitacoes_almoxarifado' criada em uma versão anterior.
    cursor.execute("ALTER TABLE solicitacoes_almoxarifado ADD COLUMN IF NOT EXISTS data_retirada DATE;")
    cursor.execute("ALTER TABLE solicitacoes_almoxarifado ADD COLUMN IF NOT EXISTS atividade_associada TEXT;")
    cursor.execute("ALTER TABLE solicitacoes_almoxarifado ADD COLUMN IF NOT EXISTS justificativa_rejeicao TEXT;")

    conn.commit()

    # Verifica se a carga inicial (seed) já foi realizada no passado
    cursor.execute("SELECT valor FROM config_sistema WHERE chave = 'seed_inicial';")
    seed_realizado = cursor.fetchone()

    if not seed_realizado:
        # Inserção inicial única de Usuários
        cursor.execute("SELECT COUNT(*) FROM usuarios;")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO usuarios (nome, email, senha, perfil) 
                VALUES ('Administrador Padrão', 'admin@ngi.com', '123', 'Administrador');
            """)

        # Inserção inicial única de Produtos
        cursor.execute("SELECT COUNT(*) FROM produtos;")
        if cursor.fetchone()[0] == 0:
            produtos_iniciais = [
                ("001", "Capacete de Segurança", 15, "EPI", 45.00),
                ("002", "Resma Papel A4", 0, "Material de Escritório", 28.50),
                ("003", "Luva de Raspa", 50, "EPI", 12.00)
            ]
            cursor.executemany("INSERT INTO produtos VALUES (%s, %s, %s, %s, %s);", produtos_iniciais)

        # Inserção inicial única de Coordenações
        cursor.execute("SELECT COUNT(*) FROM coordenacoes;")
        if cursor.fetchone()[0] == 0:
            cursor.executemany("INSERT INTO coordenacoes VALUES (%s, %s);", [
                ("COTEC", "Coordenação Técnica"),
                ("COLOG", "Coordenação de Logística")
            ])

        # Inserção inicial única de Categorias
        cursor.execute("SELECT COUNT(*) FROM categorias;")
        if cursor.fetchone()[0] == 0:
            cat_iniciais = [("EPI",), ("Material de Escritório",), ("Informática",), ("Limpeza",), ("Copa",)]
            cursor.executemany("INSERT INTO categorias VALUES (%s);", cat_iniciais)

        # Marca no banco que o seed inicial já foi finalizado
        cursor.execute("INSERT INTO config_sistema (chave, valor) VALUES ('seed_inicial', 'true');")
        conn.commit()
    
    return conn

conn = inicializar_banco_automatico()

# Carregamento seguro e global dos dados
try:
    df_produtos = pd.read_sql_query('SELECT codigo AS "Código", item AS "Item", quantidade AS "Quantidade", categoria AS "Categoria", valor_unitario AS "Valor Unitário" FROM produtos', conn)
    df_movimentacoes = pd.read_sql_query('SELECT data AS "Data", tipo AS "Tipo", codigo AS "Código", item AS "Item", quantidade AS "Quantidade", responsavel AS "Responsável", coordenacao AS "Coordenação" FROM movimentacoes', conn)
    df_coordenacoes = pd.read_sql_query('SELECT sigla AS "Sigla", nome AS "Nome" FROM coordenacoes', conn)
    df_cat_bruto = pd.read_sql_query("SELECT nome FROM categorias", conn)
    lista_categorias = df_cat_bruto["nome"].tolist()
except Exception as e:
    df_produtos = pd.DataFrame()
    df_movimentacoes = pd.DataFrame()
    df_coordenacoes = pd.DataFrame()
    lista_categorias = []

# =============================================================================
# CONFIGURAÇÕES SEGURAS DE E-MAIL
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

# =============================================================================
# FUNÇÃO AUXILIAR: ENVIO DE E-MAIL DE NOTIFICAÇÃO (MÓDULO DE SOLICITAÇÃO)
# =============================================================================
def enviar_email_notificacao(destinatario, assunto, corpo_html):
    if EMAIL_REMETENTE == "configurar_no_secrets@email.com" or not destinatario:
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_REMETENTE
        msg["To"] = destinatario
        msg["Subject"] = assunto
        msg.attach(MIMEText(corpo_html, "html"))

        servidor = smtplib.SMTP(SMTP_HOST, SMTP_PORTA, timeout=10)
        servidor.starttls()
        servidor.login(EMAIL_REMETENTE, SENHA_REMETENTE)
        servidor.sendmail(EMAIL_REMETENTE, destinatario, msg.as_string())
        servidor.quit()
        return True
    except Exception:
        return False

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="SISTEMA DE GESTÃO DE ALMOXARIFADO NGI CARAJÁS", 
    page_icon="🌿", 
    layout="wide"
)

# --- ESTILIZAÇÃO CSS COMPATÍVEL ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"], .stMarkdown, .stMarkdown p, .stMarkdown li,
    [data-testid="stWidgetLabel"] p, label, span, div, button,
    input, textarea, select, .stDataFrame, [data-testid="stMetricValue"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif !important;
    }

    h1, h2, h3, h4, h5, h6 {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif !important;
        font-weight: 600 !important;
        letter-spacing: -0.01em;
    }

    /* Preserva a fonte de ícones do Streamlit (Material Symbols), que a regra
       acima sobrescrevia e fazia aparecer o nome do ícone em texto. */
    [data-testid="stIconMaterial"],
    span[data-testid="stIconMaterial"],
    .material-symbols-rounded,
    .material-symbols-outlined,
    .material-icons {
        font-family: 'Material Symbols Rounded', 'Material Symbols Outlined', 'Material Icons' !important;
    }

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

if "PERFIL_USUARIO_LOGADO" not in st.session_state:
    st.session_state.PERFIL_USUARIO_LOGADO = ""

if "EMAIL_USUARIO_LOGADO" not in st.session_state:
    st.session_state.EMAIL_USUARIO_LOGADO = ""

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
                    cursor.execute("SELECT nome, senha, perfil, email FROM usuarios WHERE LOWER(email) = %s;", (usuario_input.strip().lower(),))
                    resultado = cursor.fetchone()
                    
                    if resultado:
                        nome_banco, senha_banco, perfil_banco, email_banco = resultado
                        if str(senha_banco) == str(senha_input).strip():
                            st.session_state.autenticado = True
                            st.session_state.NOME_USUARIO_LOGADO = nome_banco
                            st.session_state.PERFIL_USUARIO_LOGADO = perfil_banco
                            st.session_state.EMAIL_USUARIO_LOGADO = email_banco
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
        
        if st.session_state.PERFIL_USUARIO_LOGADO == "Usuário Comum":
            # ---------------------------------------------------------------
            # MENU RESTRITO - PERFIL USUÁRIO (MÓDULO DE SOLICITAÇÃO)
            # ---------------------------------------------------------------
            escolha = option_menu(
                menu_title=None,
                options=[
                    "Materiais Disponíveis",
                    "Empréstimo Disponível",
                    "Minhas Solicitações",
                    "Sair do Sistema"
                ],
                icons=["box-seam", "arrow-repeat", "clock-history", "box-arrow-right"],
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
        else:
            # ---------------------------------------------------------------
            # MENU COMPLETO - PERFIL ADMINISTRADOR (MENU ORIGINAL + SOLICITAÇÕES)
            # ---------------------------------------------------------------
            escolha = option_menu(
                menu_title=None,
                options=[
                    "Painel Geral", 
                    "Empréstimo de Material",
                    "Cadastrar Produto", 
                    "Cadastrar Categoria", 
                    "Cadastrar Usuário", 
                    "Cadastrar Coordenação",
                    "Movimentação de Estoque",
                    "Solicitações",
                    "Sair do Sistema"
                ],
                icons=["grid", "arrow-repeat", "box", "folder", "person-plus", "building", "arrow-left-right", "bell", "box-arrow-right"],
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
        st.session_state.PERFIL_USUARIO_LOGADO = ""
        st.session_state.EMAIL_USUARIO_LOGADO = ""
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

        st.markdown("<br><h3 style='font-size: 18px; font-weight: 600; margin-bottom: 12px;'> Controle de Estoque</h3>", unsafe_allow_html=True)
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

    # =========================================================================
    # NOVA TELA: EMPRÉSTIMO DE MATERIAL (INDEPENDENTE)
    # =========================================================================
    elif escolha == "Empréstimo de Material":
        st.markdown("""
            <div style="background-color: #2E7D32; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
                <h1 style="color: white; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                    Gestão de Empréstimo de Material
                </h1>
                <p style="color: #E8F5E9; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Módulo independente de empréstimos, controle de devoluções e histórico
                </p>
            </div>
        """, unsafe_allow_html=True)

        sub_emp = option_menu(
            menu_title=None,
            options=[
                "Itens Disponíveis", 
                "Cadastrar Item Empréstimo", 
                "Registrar Saída (Empréstimo)", 
                "Registrar Devolução", 
                "Histórico de Movimentação"
            ],
            icons=["box-seam", "plus-circle", "box-arrow-right", "box-arrow-in-left", "journal-text"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )

        cursor = conn.cursor()

        # ---------------------------------------------------------------------
        # SUB-ABA 1: ITENS DISPONÍVEIS (PAINEL + EDITAR / EXCLUIR)
        # ---------------------------------------------------------------------
        if sub_emp == "Itens Disponíveis":
            st.subheader("Painel de Disponibilidade de Empréstimos")
            
            df_emp_itens = pd.read_sql_query("""
                SELECT 
                    id AS "ID",
                    codigo AS "Código", 
                    item AS "Item / Equipamento", 
                    quantidade_total AS "Qtd Total", 
                    quantidade_disponivel AS "Qtd Disponível",
                    (quantidade_total - quantidade_disponivel) AS "Emprestados",
                    observacao AS "Observações"
                FROM emprestimo_itens ORDER BY item ASC;
            """, conn)

            if df_emp_itens.empty:
                st.info("Nenhum item cadastrado no catálogo exclusivo de empréstimos ainda.")
            else:
                # Exibe a tabela ocultando a coluna técnica 'ID'
                df_exibir = df_emp_itens.drop(columns=["ID"])
                st.dataframe(df_exibir, use_container_width=True, hide_index=True)

                st.markdown("<hr style='margin: 25px 0 15px 0; opacity: 0.2;'>", unsafe_allow_html=True)
                st.markdown("### Gerenciar / Editar / Excluir Item de Empréstimo")

                # Seleção do item
                df_raw_emp = pd.read_sql_query("SELECT id, codigo, item, quantidade_total, quantidade_disponivel, observacao FROM emprestimo_itens ORDER BY item ASC;", conn)
                
                if not df_raw_emp.empty:
                    opcao_emp_sel = st.selectbox(
                        "Selecione o item para modificar ou excluir:",
                        df_raw_emp.index,
                        format_func=lambda x: f"{df_raw_emp.loc[x, 'item']} (Código: {df_raw_emp.loc[x, 'codigo'] or 'S/N'})"
                    )

                    id_emp_sel = int(df_raw_emp.loc[opcao_emp_sel, "id"])
                    cod_emp_sel = df_raw_emp.loc[opcao_emp_sel, "codigo"] or ""
                    nome_emp_sel = df_raw_emp.loc[opcao_emp_sel, "item"]
                    qtd_tot_sel = int(df_raw_emp.loc[opcao_emp_sel, "quantidade_total"])
                    qtd_disp_sel = int(df_raw_emp.loc[opcao_emp_sel, "quantidade_disponivel"])
                    obs_emp_sel = df_raw_emp.loc[opcao_emp_sel, "observacao"] or ""

                    col_ed_e1, col_ed_e2 = st.columns(2)
                    edit_cod_emp = col_ed_e1.text_input("Código / Patrimônio:", value=cod_emp_sel, key="ed_cod_emp")
                    edit_nome_emp = col_ed_e2.text_input("Nome do Item / Equipamento:", value=nome_emp_sel, key="ed_nome_emp")
                    
                    qtd_emprestados_atual = qtd_tot_sel - qtd_disp_sel
                    edit_qtd_tot = col_ed_e1.number_input("Quantidade Total em Acervo:", min_value=qtd_emprestados_atual, value=qtd_tot_sel, step=1, key="ed_qtd_tot_emp")
                    
                    if qtd_emprestados_atual > 0:
                        st.caption(f"Existem {qtd_emprestados_atual} unidade(s) emprestada(s) no momento. A quantidade total não pode ser menor que isso.")

                    edit_obs_emp = col_ed_e2.text_area("Observações / Descrição:", value=obs_emp_sel, key="ed_obs_emp")

                    col_btn_e1, col_btn_e2 = st.columns([1, 4])
                    
                    with col_btn_e1:
                        if st.button("Salvar Alterações", type="primary", key="btn_salvar_emp"):
                            if edit_nome_emp.strip():
                                nova_qtd_disp = edit_qtd_tot - qtd_emprestados_atual
                                try:
                                    cursor.execute("""
                                        UPDATE emprestimo_itens 
                                        SET codigo = %s, item = %s, quantidade_total = %s, quantidade_disponivel = %s, observacao = %s 
                                        WHERE id = %s;
                                    """, (edit_cod_emp.strip() if edit_cod_emp.strip() else None, edit_nome_emp.strip(), edit_qtd_tot, nova_qtd_disp, edit_obs_emp.strip(), id_emp_sel))
                                    conn.commit()
                                    st.success(f"Item '{edit_nome_emp}' atualizado com sucesso!")
                                    st.rerun()
                                except psycopg2.IntegrityError:
                                    conn.rollback()
                                    st.error("Erro: Já existe outro item registrado com este mesmo Código/Patrimônio.")
                            else:
                                st.error("O Nome do Item é obrigatório.")

                    with col_btn_e2:
                        if st.button("Excluir Item", key="btn_excluir_emp"):
                            cursor.execute("SELECT COUNT(*) FROM emprestimo_registros WHERE item_id = %s AND status = 'EMPRESTADO';", (id_emp_sel,))
                            tem_pendente = cursor.fetchone()[0]

                            if tem_pendente > 0:
                                st.error("Não é possível excluir este item pois existem unidades atualmente emprestadas pendentes de devolução.")
                            else:
                                try:
                                    cursor.execute("DELETE FROM emprestimo_registros WHERE item_id = %s;", (id_emp_sel,))
                                    cursor.execute("DELETE FROM emprestimo_itens WHERE id = %s;", (id_emp_sel,))
                                    conn.commit()
                                    st.warning(f"Item '{nome_emp_sel}' removido com sucesso!")
                                    st.rerun()
                                except Exception as err:
                                    conn.rollback()
                                    st.error(f"Erro ao tentar excluir: {err}")

        # ---------------------------------------------------------------------
        # SUB-ABA 2: CADASTRAR ITEM PARA EMPRÉSTIMO
        # ---------------------------------------------------------------------
        elif sub_emp == "Cadastrar Item Empréstimo":
            st.subheader("Cadastrar Novo Item no Catálogo de Empréstimos")
            st.caption("Nota: Itens cadastrados aqui são 100% independentes do estoque do Almoxarifado.")

            with st.form("form_cad_emp_item", clear_on_submit=True):
                col_e1, col_e2 = st.columns(2)
                cod_emp = col_e1.text_input("Código / Patrimônio (opcional)")
                item_emp = col_e2.text_input("Nome do Item / Equipamento*")
                qtd_total = col_e1.number_input("Quantidade Total em Acervo*", min_value=1, value=1, step=1)
                obs_emp = col_e2.text_area("Observações / Descrição", placeholder="Ex: Acompanha cabo de força e maleta")

                if st.form_submit_button("Cadastrar Item", type="primary"):
                    if item_emp.strip():
                        try:
                            cursor.execute("""
                                INSERT INTO emprestimo_itens (codigo, item, quantidade_total, quantidade_disponivel, observacao)
                                VALUES (%s, %s, %s, %s, %s);
                            """, (cod_emp.strip() if cod_emp else None, item_emp.strip(), qtd_total, qtd_total, obs_emp.strip()))
                            conn.commit()
                            st.success(f"Item '{item_emp}' cadastrado com sucesso para empréstimos!")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error("Erro: Já existe um item de empréstimo com este mesmo Código/Patrimônio.")
                    else:
                        st.error("O campo 'Nome do Item' é obrigatório!")

        # ---------------------------------------------------------------------
        # SUB-ABA 3: REGISTRAR SAÍDA (EMPRÉSTIMO)
        # ---------------------------------------------------------------------
        elif sub_emp == "Registrar Saída (Empréstimo)":
            st.subheader("Registrar Saída de Material Por Empréstimo")

            cursor.execute("SELECT id, item, quantidade_disponivel FROM emprestimo_itens WHERE quantidade_disponivel > 0 ORDER BY item ASC;")
            itens_disponiveis = cursor.fetchall()

            if not itens_disponiveis:
                st.warning("Não há itens disponíveis no catálogo de empréstimo no momento.")
            else:
                opcoes_itens = {f"{item[1]} (Disponível: {item[2]})": (item[0], item[1], item[2]) for item in itens_disponiveis}
                
                with st.form("form_registro_saida_emp", clear_on_submit=True):
                    item_selecionado_label = st.selectbox("Selecione o Item para Empréstimo*", list(opcoes_itens.keys()))
                    item_id, item_nome, max_qtd = opcoes_itens[item_selecionado_label]

                    col_s1, col_s2 = st.columns(2)
                    qtd_saida = col_s1.number_input("Quantidade*", min_value=1, max_value=max_qtd, value=1, step=1)
                    nome_pessoa = col_s2.text_input("Nome da Pessoa (Solicitante)*")

                    lista_siglas_coord = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["GERAL"]
                    coord_pessoa = col_s1.selectbox("Coordenação*", lista_siglas_coord)
                    
                    data_retirada = col_s2.date_input("Data de Retirada*", value=date.today(), format="DD/MM/YYYY")
                    data_prevista = col_s1.date_input("Data Prevista para Devolução*", value=date.today(), format="DD/MM/YYYY")

                    if st.form_submit_button("Confirmar Empréstimo", type="primary"):
                        if nome_pessoa.strip():
                            if data_prevista < data_retirada:
                                st.error("A data prevista de devolução não pode ser anterior à data de retirada!")
                            else:
                                cursor.execute("""
                                    INSERT INTO emprestimo_registros 
                                    (item_id, item_nome, quantidade, pessoa, coordenacao, data_retirada, data_prevista, status)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'EMPRESTADO');
                                """, (item_id, item_nome, qtd_saida, nome_pessoa.strip(), coord_pessoa, data_retirada, data_prevista))
                                
                                cursor.execute("""
                                    UPDATE emprestimo_itens 
                                    SET quantidade_disponivel = quantidade_disponivel - %s 
                                    WHERE id = %s;
                                """, (qtd_saida, item_id))
                                
                                conn.commit()
                                st.success(f"Empréstimo registrado com sucesso para {nome_pessoa}!")
                                st.rerun()
                        else:
                            st.error("Por favor, preencha o Nome da Pessoa!")

        # ---------------------------------------------------------------------
        # SUB-ABA 4: REGISTRAR DEVOLUÇÃO
        # ---------------------------------------------------------------------
        elif sub_emp == "Registrar Devolução":
            st.subheader("Registro de Devolução de Material")

            cursor.execute("""
                SELECT id, item_id, item_nome, quantidade, pessoa, data_retirada, data_prevista 
                FROM emprestimo_registros 
                WHERE status = 'EMPRESTADO'
                ORDER BY data_retirada ASC;
            """)
            emp_ativos = cursor.fetchall()

            if not emp_ativos:
                st.info("Nenhum empréstimo pendente de devolução no momento.")
            else:
                opcoes_dev = {
                    f"{e[2]} (Qtd: {e[3]}) - Emprestado para: {e[4]} (Retirada: {e[5].strftime('%d/%m/%Y')})": e
                    for e in emp_ativos
                }

                with st.form("form_registro_devolucao", clear_on_submit=True):
                    emp_selecionado_label = st.selectbox("Selecione o Empréstimo a ser Baixado*", list(opcoes_dev.keys()))
                    reg_id, item_id, item_nome, qtd, pessoa_orig, d_ret, d_prev = opcoes_dev[emp_selecionado_label]

                    col_d1, col_d2 = st.columns(2)
                    pessoa_devolvendo = col_d1.text_input("Nome de Quem Está Devolvendo*", value=pessoa_orig)
                    data_devolucao = col_d2.date_input("Data Real da Devolução*", value=date.today(), format="DD/MM/YYYY")

                    if st.form_submit_button("Confirmar Devolução", type="primary"):
                        if pessoa_devolvendo.strip():
                            cursor.execute("""
                                UPDATE emprestimo_registros 
                                SET status = 'DEVOLVIDO', data_devolucao = %s, responsavel_devolucao = %s 
                                WHERE id = %s;
                            """, (data_devolucao, pessoa_devolvendo.strip(), reg_id))

                            cursor.execute("""
                                UPDATE emprestimo_itens 
                                SET quantidade_disponivel = quantidade_disponivel + %s 
                                WHERE id = %s;
                            """, (qtd, item_id))

                            conn.commit()
                            st.success(f"Devolução do item '{item_nome}' realizada com sucesso!")
                            st.rerun()
                        else:
                            st.error("Preencha o nome da pessoa responsável pela devolução.")

        # ---------------------------------------------------------------------
        # SUB-ABA 5: HISTÓRICO DE MOVIMENTAÇÃO DE EMPRÉSTIMOS
        # ---------------------------------------------------------------------
        elif sub_emp == "Histórico de Movimentação":
            st.subheader("Histórico Completo de Empréstimos e Devoluções")

            df_hist_emp = pd.read_sql_query("""
                SELECT 
                    id AS "ID",
                    item_nome AS "Produto / Equipamento",
                    quantidade AS "Qtd",
                    pessoa AS "Solicitante",
                    coordenacao AS "Coordenação",
                    to_char(data_retirada, 'DD/MM/YYYY') AS "Data Retirada",
                    to_char(data_prevista, 'DD/MM/YYYY') AS "Previsão Devolução",
                    COALESCE(to_char(data_devolucao, 'DD/MM/YYYY'), '-') AS "Data Devolução Real",
                    status AS "Status",
                    COALESCE(responsavel_devolucao, '-') AS "Devolvido Por"
                FROM emprestimo_registros 
                ORDER BY id DESC;
            """, conn)

            if df_hist_emp.empty:
                st.info("Nenhuma movimentação de empréstimo registrada até o momento.")
            else:
                def destacar_status(val):
                    if val == 'EMPRESTADO':
                        return 'background-color: #fff3cd; color: #856404; font-weight: bold;'
                    elif val == 'DEVOLVIDO':
                        return 'background-color: #d4edda; color: #155724;'
                    return ''

                st.dataframe(df_hist_emp.style.map(destacar_status, subset=['Status']), use_container_width=True, hide_index=True)

    # =========================================================================
    # NOVO MÓDULO DE SOLICITAÇÃO — TELA (PERFIL USUÁRIO): MATERIAIS DISPONÍVEIS
    # =========================================================================
    elif escolha == "Materiais Disponíveis":
        st.markdown("""
            <div style="background-color: #4CAF50; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
                <h1 style="color: white; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                    Materiais Disponíveis no Almoxarifado
                </h1>
                <p style="color: #E8F5E9; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Consulte os itens em estoque e solicite a retirada de materiais
                </p>
            </div>
        """, unsafe_allow_html=True)

        if st.session_state.get("msg_sucesso_material"):
            st.success("Sua solicitação foi encaminhada com sucesso!")
            del st.session_state["msg_sucesso_material"]

        df_disp_material = df_produtos[df_produtos["Quantidade"] > 0].copy() if not df_produtos.empty else pd.DataFrame()

        if df_disp_material.empty:
            st.info("Nenhum material disponível em estoque no momento.")
        else:
            st.dataframe(df_disp_material.drop(columns=["Valor Unitário"]), use_container_width=True, hide_index=True)

            st.markdown("<hr style='margin: 25px 0 15px 0; opacity: 0.2;'>", unsafe_allow_html=True)
            st.markdown("### Nova Solicitação de Material")

            df_raw_prod_user = pd.read_sql_query("SELECT codigo, item, quantidade FROM produtos WHERE quantidade > 0 ORDER BY item ASC;", conn)
            lista_siglas_coord_user = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["GERAL"]

            with st.form("form_solicitar_material", clear_on_submit=True):
                opcao_sol_mat = st.selectbox(
                    "Selecione o Material:",
                    df_raw_prod_user.index,
                    format_func=lambda x: f"{df_raw_prod_user.loc[x, 'codigo']} - {df_raw_prod_user.loc[x, 'item']} (Saldo: {df_raw_prod_user.loc[x, 'quantidade']})"
                )
                qtd_sol_mat = st.number_input("Quantidade Desejada:", min_value=1, max_value=int(df_raw_prod_user.loc[opcao_sol_mat, "quantidade"]), value=1, step=1)
                coord_sol_mat = st.selectbox("Coordenação:", lista_siglas_coord_user)
                obs_sol_mat = st.text_area("Observações (opcional):")

                if st.form_submit_button("Enviar Solicitação", type="primary"):
                    cod_sel = df_raw_prod_user.loc[opcao_sol_mat, "codigo"]
                    nome_sel = df_raw_prod_user.loc[opcao_sol_mat, "item"]
                    try:
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO solicitacoes_almoxarifado 
                            (tipo, referencia_codigo, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, status, observacao)
                            VALUES ('MATERIAL', %s, %s, %s, %s, %s, %s, 'PENDENTE', %s);
                        """, (cod_sel, nome_sel, qtd_sol_mat, st.session_state.NOME_USUARIO_LOGADO, st.session_state.EMAIL_USUARIO_LOGADO, coord_sol_mat, obs_sol_mat.strip()))
                        conn.commit()
                        st.session_state["msg_sucesso_material"] = True
                        st.rerun()
                    except Exception as ex:
                        conn.rollback()
                        st.error(f"Erro ao enviar solicitação: {ex}")

    # =========================================================================
    # NOVO MÓDULO DE SOLICITAÇÃO — TELA (PERFIL USUÁRIO): EMPRÉSTIMO DISPONÍVEL
    # =========================================================================
    elif escolha == "Empréstimo Disponível":
        st.markdown("""
            <div style="background-color: #2E7D32; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
                <h1 style="color: white; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                    Itens Disponíveis para Empréstimo
                </h1>
                <p style="color: #E8F5E9; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Consulte os itens do catálogo de empréstimo e solicite a retirada
                </p>
            </div>
        """, unsafe_allow_html=True)

        if st.session_state.get("msg_sucesso_emprestimo"):
            st.success("Sua solicitação foi encaminhada com sucesso!")
            del st.session_state["msg_sucesso_emprestimo"]

        df_emp_disp_user = pd.read_sql_query("""
            SELECT 
                codigo AS "Código", 
                item AS "Item / Equipamento", 
                quantidade_disponivel AS "Qtd Disponível",
                observacao AS "Observações"
            FROM emprestimo_itens WHERE quantidade_disponivel > 0 ORDER BY item ASC;
        """, conn)

        if df_emp_disp_user.empty:
            st.info("Nenhum item disponível para empréstimo no momento.")
        else:
            st.dataframe(df_emp_disp_user, use_container_width=True, hide_index=True)

            st.markdown("<hr style='margin: 25px 0 15px 0; opacity: 0.2;'>", unsafe_allow_html=True)
            st.markdown("### Nova Solicitação de Empréstimo")

            df_raw_emp_user = pd.read_sql_query("SELECT id, codigo, item, quantidade_disponivel FROM emprestimo_itens WHERE quantidade_disponivel > 0 ORDER BY item ASC;", conn)
            lista_siglas_coord_emp_user = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["GERAL"]

            with st.form("form_solicitar_emprestimo", clear_on_submit=True):
                opcao_sol_emp = st.selectbox(
                    "Selecione o Item:",
                    df_raw_emp_user.index,
                    format_func=lambda x: f"{df_raw_emp_user.loc[x, 'item']} (Disponível: {df_raw_emp_user.loc[x, 'quantidade_disponivel']})"
                )
                qtd_sol_emp = st.number_input("Quantidade Desejada:", min_value=1, max_value=int(df_raw_emp_user.loc[opcao_sol_emp, "quantidade_disponivel"]), value=1, step=1)
                coord_sol_emp = st.selectbox("Coordenação:", lista_siglas_coord_emp_user)

                col_dt1, col_dt2 = st.columns(2)
                data_retirada_sol = col_dt1.date_input("Data de Retirada: *", value=date.today(), format="DD/MM/YYYY")
                data_prev_sol = col_dt2.date_input("Data de Devolução: *", value=date.today(), format="DD/MM/YYYY")

                atividade_sol_emp = st.text_input("Atividade Associada: *", placeholder="Ex: Vistoria de campo na trilha X")
                obs_sol_emp = st.text_area("Observações (opcional):")

                if st.form_submit_button("Enviar Solicitação", type="primary"):
                    if not atividade_sol_emp.strip():
                        st.error("O campo 'Atividade Associada' é obrigatório!")
                    elif data_prev_sol < data_retirada_sol:
                        st.error("A Data de Devolução não pode ser anterior à Data de Retirada!")
                    else:
                        item_id_sel = int(df_raw_emp_user.loc[opcao_sol_emp, "id"])
                        nome_sel_emp = df_raw_emp_user.loc[opcao_sol_emp, "item"]
                        try:
                            cursor = conn.cursor()
                            cursor.execute("""
                                INSERT INTO solicitacoes_almoxarifado 
                                (tipo, referencia_codigo, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, data_retirada, data_prevista, atividade_associada, status, observacao)
                                VALUES ('EMPRESTIMO', %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDENTE', %s);
                            """, (str(item_id_sel), nome_sel_emp, qtd_sol_emp, st.session_state.NOME_USUARIO_LOGADO, st.session_state.EMAIL_USUARIO_LOGADO, coord_sol_emp, data_retirada_sol, data_prev_sol, atividade_sol_emp.strip(), obs_sol_emp.strip()))
                            conn.commit()
                            st.session_state["msg_sucesso_emprestimo"] = True
                            st.rerun()
                        except Exception as ex:
                            conn.rollback()
                            st.error(f"Erro ao enviar solicitação: {ex}")

    # =========================================================================
    # NOVO MÓDULO DE SOLICITAÇÃO — TELA (PERFIL USUÁRIO): MINHAS SOLICITAÇÕES
    # =========================================================================
    elif escolha == "Minhas Solicitações":
        st.title("Minhas Solicitações")

        df_minhas_sol = pd.read_sql_query("""
            SELECT 
                tipo AS "Tipo",
                item_nome AS "Item",
                quantidade AS "Quantidade",
                COALESCE(atividade_associada, '-') AS "Atividade Associada",
                COALESCE(to_char(data_retirada, 'DD/MM/YYYY'), '-') AS "Data de Retirada",
                COALESCE(to_char(data_prevista, 'DD/MM/YYYY'), '-') AS "Data de Devolução",
                to_char(data_solicitacao, 'DD/MM/YYYY HH24:MI') AS "Data da Solicitação",
                status AS "Status",
                COALESCE(to_char(data_decisao, 'DD/MM/YYYY HH24:MI'), '-') AS "Data da Decisão",
                COALESCE(justificativa_rejeicao, '-') AS "Justificativa da Reprovação"
            FROM solicitacoes_almoxarifado
            WHERE solicitante_email = %(email_usuario)s
            ORDER BY id DESC;
        """, conn, params={"email_usuario": st.session_state.EMAIL_USUARIO_LOGADO})

        if df_minhas_sol.empty:
            st.info("Você ainda não realizou nenhuma solicitação.")
        else:
            def destacar_status_sol(val):
                if val == 'PENDENTE':
                    return 'background-color: #fff3cd; color: #856404; font-weight: bold;'
                elif val == 'APROVADA':
                    return 'background-color: #d4edda; color: #155724; font-weight: bold;'
                elif val == 'REJEITADA':
                    return 'background-color: rgba(198, 40, 40, 0.12); color: #c62828; font-weight: bold;'
                return ''

            st.dataframe(df_minhas_sol.style.map(destacar_status_sol, subset=['Status']), use_container_width=True, hide_index=True)

    # =========================================================================
    # NOVO MÓDULO DE SOLICITAÇÃO — TELA (PERFIL ADMINISTRADOR): SOLICITAÇÕES
    # =========================================================================
    elif escolha == "Solicitações":
        st.markdown("""
            <div style="background-color: #4CAF50; padding: 20px; border-radius: 10px; margin-bottom: 25px;">
                <h1 style="color: white; margin: 0; font-size: 26px; font-family: sans-serif; font-weight: 600;">
                    Solicitações de Usuários
                </h1>
                <p style="color: #E8F5E9; margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
                    Analise, aprove ou rejeite as solicitações de materiais e empréstimos
                </p>
            </div>
        """, unsafe_allow_html=True)

        aba_solicitacao = option_menu(
            menu_title=None,
            options=["Pendentes", "Histórico"],
            icons=["hourglass-split", "journal-text"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )

        cursor = conn.cursor()

        if aba_solicitacao == "Pendentes":
            df_pendentes = pd.read_sql_query("""
                SELECT id, tipo, referencia_codigo, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, data_retirada, data_prevista, atividade_associada, observacao
                FROM solicitacoes_almoxarifado WHERE status = 'PENDENTE' ORDER BY id ASC;
            """, conn)

            if df_pendentes.empty:
                st.info("Nenhuma solicitação pendente no momento.")
            else:
                for _, sol in df_pendentes.iterrows():
                    tipo_label = "Material (Almoxarifado)" if sol["tipo"] == "MATERIAL" else "Empréstimo"
                    linha_datas = ""
                    if sol["tipo"] == "EMPRESTIMO":
                        ret_fmt = sol["data_retirada"].strftime('%d/%m/%Y') if sol["data_retirada"] is not None else "-"
                        dev_fmt = sol["data_prevista"].strftime('%d/%m/%Y') if sol["data_prevista"] is not None else "-"
                        linha_datas = f"Retirada: {ret_fmt} | Devolução: {dev_fmt}<br>"
                    linha_atividade = f"Atividade Associada: {sol['atividade_associada']}<br>" if sol["atividade_associada"] else ""
                    linha_obs = f"Observações: {sol['observacao']}" if sol["observacao"] else ""

                    st.markdown(f"""
                        <div style="border: 1px solid rgba(76, 175, 80, 0.3); border-radius: 8px; padding: 15px; margin-bottom: 12px;">
                            <b>#{sol['id']} — {tipo_label}</b><br>
                            Item: {sol['item_nome']} | Quantidade: {sol['quantidade']}<br>
                            Solicitante: {sol['solicitante_nome']} ({sol['solicitante_email']}) | Coordenação: {sol['coordenacao'] or '-'}<br>
                            {linha_datas}{linha_atividade}{linha_obs}
                        </div>
                    """, unsafe_allow_html=True)

                    just_rejeicao = st.text_area(
                        "Justificativa da Reprovação (obrigatória caso vá rejeitar):",
                        key=f"just_rejeitar_{sol['id']}",
                        placeholder="Descreva o motivo da reprovação desta solicitação..."
                    )

                    col_ap1, col_ap2, col_ap3 = st.columns([1, 1, 4])
                    with col_ap1:
                        if st.button("✅ Aprovar", key=f"aprovar_{sol['id']}", type="primary"):
                            try:
                                if sol["tipo"] == "MATERIAL":
                                    cursor.execute("SELECT quantidade FROM produtos WHERE codigo = %s;", (sol["referencia_codigo"],))
                                    res_prod = cursor.fetchone()
                                    if not res_prod or res_prod[0] < sol["quantidade"]:
                                        st.error("Saldo insuficiente em estoque para aprovar esta solicitação.")
                                    else:
                                        cursor.execute("UPDATE produtos SET quantidade = quantidade - %s WHERE codigo = %s;", (sol["quantidade"], sol["referencia_codigo"]))
                                        cursor.execute("""
                                            INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s);
                                        """, (date.today().strftime("%Y-%m-%d"), "Saída", sol["referencia_codigo"], sol["item_nome"], sol["quantidade"], sol["solicitante_nome"], sol["coordenacao"]))
                                        cursor.execute("""
                                            UPDATE solicitacoes_almoxarifado SET status = 'APROVADA', data_decisao = CURRENT_TIMESTAMP, aprovador = %s 
                                            WHERE id = %s;
                                        """, (st.session_state.NOME_USUARIO_LOGADO, sol["id"]))
                                        conn.commit()

                                        threading.Thread(
                                            target=enviar_email_notificacao,
                                            args=(
                                                sol["solicitante_email"],
                                                "Solicitação de Material Aprovada",
                                                f"""
                                                <p>Olá, {sol['solicitante_nome']},</p>
                                                <p>Sua solicitação do item <b>{sol['item_nome']}</b> (Quantidade: {sol['quantidade']}) foi <b>aprovada</b>.</p>
                                                <p>O material já está disponível para retirada no Almoxarifado.</p>
                                                <p>Atenciosamente,<br>Gestão de Almoxarifado NGI Carajás</p>
                                                """
                                            ),
                                            daemon=True
                                        ).start()
                                        st.success("Solicitação aprovada e usuário notificado por e-mail!")
                                        st.rerun()
                                else:
                                    cursor.execute("SELECT quantidade_disponivel FROM emprestimo_itens WHERE id = %s;", (int(sol["referencia_codigo"]),))
                                    res_emp = cursor.fetchone()
                                    if not res_emp or res_emp[0] < sol["quantidade"]:
                                        st.error("Saldo insuficiente disponível para aprovar este empréstimo.")
                                    else:
                                        cursor.execute("""
                                            INSERT INTO emprestimo_registros 
                                            (item_id, item_nome, quantidade, pessoa, coordenacao, data_retirada, data_prevista, status)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'EMPRESTADO');
                                        """, (int(sol["referencia_codigo"]), sol["item_nome"], sol["quantidade"], sol["solicitante_nome"], sol["coordenacao"], sol["data_retirada"] if sol["data_retirada"] is not None else date.today(), sol["data_prevista"]))
                                        cursor.execute("""
                                            UPDATE emprestimo_itens SET quantidade_disponivel = quantidade_disponivel - %s WHERE id = %s;
                                        """, (sol["quantidade"], int(sol["referencia_codigo"])))
                                        cursor.execute("""
                                            UPDATE solicitacoes_almoxarifado SET status = 'APROVADA', data_decisao = CURRENT_TIMESTAMP, aprovador = %s 
                                            WHERE id = %s;
                                        """, (st.session_state.NOME_USUARIO_LOGADO, sol["id"]))
                                        conn.commit()

                                        threading.Thread(
                                            target=enviar_email_notificacao,
                                            args=(
                                                sol["solicitante_email"],
                                                "Solicitação de Empréstimo Aprovada",
                                                f"""
                                                <p>Olá, {sol['solicitante_nome']},</p>
                                                <p>Sua solicitação de empréstimo do item <b>{sol['item_nome']}</b> (Quantidade: {sol['quantidade']}) foi <b>aprovada</b>.</p>
                                                <p>O item já está disponível para retirada no Almoxarifado.</p>
                                                <p>Atenciosamente,<br>Gestão de Almoxarifado NGI Carajás</p>
                                                """
                                            ),
                                            daemon=True
                                        ).start()
                                        st.success("Empréstimo aprovado e usuário notificado por e-mail!")
                                        st.rerun()
                            except Exception as ex:
                                conn.rollback()
                                st.error(f"Erro ao aprovar solicitação: {ex}")

                    with col_ap2:
                        if st.button("❌ Rejeitar", key=f"rejeitar_{sol['id']}"):
                            if not just_rejeicao.strip():
                                st.error("Para rejeitar, é obrigatório informar a Justificativa da Reprovação!")
                            else:
                                cursor.execute("""
                                    UPDATE solicitacoes_almoxarifado 
                                    SET status = 'REJEITADA', data_decisao = CURRENT_TIMESTAMP, aprovador = %s, justificativa_rejeicao = %s 
                                    WHERE id = %s;
                                """, (st.session_state.NOME_USUARIO_LOGADO, just_rejeicao.strip(), sol["id"]))
                                conn.commit()

                                threading.Thread(
                                    target=enviar_email_notificacao,
                                    args=(
                                        sol["solicitante_email"],
                                        "Solicitação Reprovada",
                                        f"""
                                        <p>Olá, {sol['solicitante_nome']},</p>
                                        <p>Sua solicitação do item <b>{sol['item_nome']}</b> (Quantidade: {sol['quantidade']}) foi <b>reprovada</b>.</p>
                                        <p><b>Justificativa:</b> {just_rejeicao.strip()}</p>
                                        <p>Atenciosamente,<br>Gestão de Almoxarifado NGI Carajás</p>
                                        """
                                    ),
                                    daemon=True
                                ).start()
                                st.warning("Solicitação rejeitada e usuário notificado por e-mail!")
                                st.rerun()

        elif aba_solicitacao == "Histórico":
            df_hist_sol = pd.read_sql_query("""
                SELECT 
                    tipo AS "Tipo",
                    item_nome AS "Item",
                    quantidade AS "Quantidade",
                    solicitante_nome AS "Solicitante",
                    solicitante_email AS "E-mail",
                    coordenacao AS "Coordenação",
                    COALESCE(atividade_associada, '-') AS "Atividade Associada",
                    COALESCE(to_char(data_retirada, 'DD/MM/YYYY'), '-') AS "Data de Retirada",
                    COALESCE(to_char(data_prevista, 'DD/MM/YYYY'), '-') AS "Data de Devolução",
                    to_char(data_solicitacao, 'DD/MM/YYYY HH24:MI') AS "Data Solicitação",
                    status AS "Status",
                    COALESCE(aprovador, '-') AS "Decidido Por",
                    COALESCE(to_char(data_decisao, 'DD/MM/YYYY HH24:MI'), '-') AS "Data Decisão",
                    COALESCE(justificativa_rejeicao, '-') AS "Justificativa da Reprovação"
                FROM solicitacoes_almoxarifado WHERE status != 'PENDENTE' ORDER BY id DESC;
            """, conn)

            if df_hist_sol.empty:
                st.info("Nenhuma solicitação decidida até o momento.")
            else:
                def destacar_status_hist(val):
                    if val == 'APROVADA':
                        return 'background-color: #d4edda; color: #155724; font-weight: bold;'
                    elif val == 'REJEITADA':
                        return 'background-color: rgba(198, 40, 40, 0.12); color: #c62828; font-weight: bold;'
                    return ''

                st.dataframe(df_hist_sol.style.map(destacar_status_hist, subset=['Status']), use_container_width=True, hide_index=True)

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
                st.caption("Novos materiais são registrados com saldo inicial 0.")
                
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
                            UPDATE usuarios 
                            SET nome = %s, email = %s, senha = %s, perfil = %s 
                            WHERE email = %s;
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
                sigla_c = st.text_input("Sigla da Coordenação")
                nome_c = st.text_input("Nome Completo")
                
                if st.form_submit_button("Cadastrar", type="primary"):
                    if sigla_c and nome_c:
                        try:
                            cursor = conn.cursor()
                            cursor.execute("INSERT INTO coordenacoes VALUES (%s, %s);", (sigla_c.strip().upper(), nome_c.strip()))
                            conn.commit()
                            st.success("Coordenação registrada!")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error("Esta Sigla já está cadastrada.")
                    else:
                        st.error("Preencha todos os campos!")

        elif aba_selecionada == "Editar / Excluir Coordenação":
            if not df_coordenacoes.empty:
                st.dataframe(df_coordenacoes, use_container_width=True, hide_index=True)
                df_raw_coord = pd.read_sql_query("SELECT * FROM coordenacoes", conn)
                idx_coord = st.selectbox("Selecione para alterar:", df_raw_coord.index, format_func=lambda x: f"{df_raw_coord.loc[x, 'sigla']} - {df_raw_coord.loc[x, 'nome']}")
                sigla_chave = df_raw_coord.loc[idx_coord, "sigla"]
                
                edit_sigla = st.text_input("Sigla:", value=df_raw_coord.loc[idx_coord, "sigla"])
                edit_nome_c = st.text_input("Nome:", value=df_raw_coord.loc[idx_coord, "nome"])
                
                c_btn_c1, c_btn_c2 = st.columns([1, 4])
                with c_btn_c1:
                    if st.button("Salvar Alteração", type="primary"):
                        cursor = conn.cursor()
                        cursor.execute("UPDATE coordenacoes SET sigla = %s, nome = %s WHERE sigla = %s;", (edit_sigla.strip().upper(), edit_nome_c.strip(), sigla_chave))
                        conn.commit()
                        st.success("Atualizada!")
                        st.rerun()

                with c_btn_c2:
                    if st.button("Excluir Coordenação"):
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM coordenacoes WHERE sigla = %s;", (sigla_chave,))
                        conn.commit()
                        st.warning("Removida.")
                        st.rerun()

  
    # --- TELA: MOVIMENTAÇÃO DE ESTOQUE (3 ABAS CONFORME SOLICITADO) ---
    elif escolha == "Movimentação de Estoque":
        st.title("Movimentação de Estoque")
        
        aba_movimentacao = option_menu(
            menu_title=None,
            options=["Registro de Entrada", "Registro de Saída", "Histórico de Movimentação"],
            icons=["arrow-down-circle", "arrow-up-circle", ""], # Ícone de histórico removido completamente para não parecer IA
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )
        
        if df_produtos.empty:
            st.warning("Nenhum produto cadastrado para movimentar.")
        else:
            df_raw_prod = pd.read_sql_query("SELECT codigo, item, quantidade FROM produtos ORDER BY item ASC", conn)
            lista_siglas_coord = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["N/A"]
            
            # 1. ABA: REGISTRO DE ENTRADA
            if aba_movimentacao == "Registro de Entrada":
                with st.form("form_entrada", clear_on_submit=True):
                    col_e1, col_e2 = st.columns(2)
                    data_mov = col_e1.date_input("Data da Movimentação:", value=datetime.today(), format="DD/MM/YYYY").strftime("%Y-%m-%d")
                    opcao_prod = col_e2.selectbox(
                        "Selecione o Material:", 
                        df_raw_prod.index, 
                        format_func=lambda x: f"{df_raw_prod.loc[x, 'codigo']} - {df_raw_prod.loc[x, 'item']} (Saldo: {df_raw_prod.loc[x, 'quantidade']})"
                    )
                    qtd_mov = col_e1.number_input("Quantidade:", min_value=1, step=1, value=1)
                    
                    if st.form_submit_button("Registrar Entrada", type="primary"):
                        prod_codigo = df_raw_prod.loc[opcao_prod, "codigo"]
                        prod_nome = df_raw_prod.loc[opcao_prod, "item"]
                        prod_qtd_atual = int(df_raw_prod.loc[opcao_prod, "quantidade"])
                        nova_qtd = prod_qtd_atual + qtd_mov
                        
                        try:
                            cursor = conn.cursor()
                            cursor.execute("UPDATE produtos SET quantidade = %s WHERE codigo = %s;", (nova_qtd, prod_codigo))
                            cursor.execute("""
                                INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
                                VALUES (%s, %s, %s, %s, %s, %s, %s);
                            """, (data_mov, "Entrada", prod_codigo, prod_nome, qtd_mov, st.session_state.NOME_USUARIO_LOGADO, "Almoxarifado"))
                            conn.commit()
                            st.success(f"Entrada de {qtd_mov} un. de '{prod_nome}' registrada! Novo saldo: {nova_qtd}.")
                            st.rerun()
                        except Exception as ex:
                            conn.rollback()
                            st.error(f"Erro ao salvar entrada: {ex}")
            
            # 2. ABA: REGISTRO DE SAÍDA
            elif aba_movimentacao == "Registro de Saída":
                with st.form("form_saida", clear_on_submit=True):
                    col_s1, col_s2 = st.columns(2)
                    data_mov = col_s1.date_input("Data da Movimentação:", value=datetime.today(), format="DD/MM/YYYY").strftime("%Y-%m-%d")
                    opcao_prod = col_s2.selectbox(
                        "Selecione o Material:", 
                        df_raw_prod.index, 
                        format_func=lambda x: f"{df_raw_prod.loc[x, 'codigo']} - {df_raw_prod.loc[x, 'item']} (Saldo: {df_raw_prod.loc[x, 'quantidade']})"
                    )
                    qtd_mov = col_s1.number_input("Quantidade da Movimentação:", min_value=1, step=1, value=1)
                    resp_mov = col_s2.text_input("Nome da Pessoa Responsável pela Retirada:")
                    coord_mov = col_s1.selectbox("Coordenação Destino:", lista_siglas_coord)
                    
                    if st.form_submit_button("Registrar Saída", type="primary"):
                        if not resp_mov.strip():
                            st.error(" Por favor, digite o nome da pessoa responsável pela retirada.")
                        else:
                            prod_codigo = df_raw_prod.loc[opcao_prod, "codigo"]
                            prod_nome = df_raw_prod.loc[opcao_prod, "item"]
                            prod_qtd_atual = int(df_raw_prod.loc[opcao_prod, "quantidade"])
                            
                            if prod_qtd_atual >= qtd_mov:
                                nova_qtd = prod_qtd_atual - qtd_mov
                                try:
                                    cursor = conn.cursor()
                                    cursor.execute("UPDATE produtos SET quantidade = %s WHERE codigo = %s;", (nova_qtd, prod_codigo))
                                    cursor.execute("""
                                        INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                                    """, (data_mov, "Saída", prod_codigo, prod_nome, qtd_mov, resp_mov.strip(), coord_mov))
                                    conn.commit()
                                    st.success(f"Saída de {qtd_mov} un. de '{prod_nome}' registrada! Novo saldo: {nova_qtd}.")
                                    st.rerun()
                                except Exception as ex:
                                    conn.rollback()
                                    st.error(f"Erro ao salvar saída: {ex}")
                            else:
                                st.error(f"Saldo Insuficiente! O material possui apenas {prod_qtd_atual} unidades no estoque.")
            
            # 3. ABA: HISTÓRICO DE MOVIMENTAÇÃO
            elif aba_movimentacao == "Histórico de Movimentação":
                st.markdown("### Histórico de Movimentação")
                if not df_movimentacoes.empty:
                    st.dataframe(df_movimentacoes.sort_index(ascending=False), use_container_width=True, hide_index=True)
                else:
                    st.info("Nenhuma movimentação registrada até o momento.")
        
