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

        # 2. Tabela de produtos (Estoque Geral)
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

        # 5. Tabela de movimentações gerais de estoque
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

        # 6. Tabela INDEPENDENTE para Cadastrar Itens do Empréstimo
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS itens_emprestimo (
                codigo TEXT PRIMARY KEY,
                nome TEXT,
                quantidade INTEGER
            );
        """)

        # 7. Tabela INDEPENDENTE para Registrar Empréstimos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS emprestimos (
                id SERIAL PRIMARY KEY,
                codigo_item TEXT,
                nome_item TEXT,
                quantidade INTEGER,
                responsavel TEXT,
                coordenacao TEXT,
                data_emprestimo TEXT,
                data_devolucao TEXT,
                data_retorno_real TEXT,
                status TEXT
            );
        """)
        conn.commit()

        # --- MIGRAÇÃO AUTOMÁTICA: Adiciona colunas ausentes caso a tabela já existisse ---
        colunas_necessarias = {
            "codigo_item": "TEXT",
            "nome_item": "TEXT",
            "quantidade": "INTEGER",
            "responsavel": "TEXT",
            "coordenacao": "TEXT",
            "data_emprestimo": "TEXT",
            "data_devolucao": "TEXT",
            "data_retorno_real": "TEXT",
            "status": "TEXT"
        }
        
        for col, col_type in colunas_necessarias.items():
            try:
                cursor.execute(f"ALTER TABLE emprestimos ADD COLUMN {col} {col_type};")
                conn.commit()
            except Exception:
                conn.rollback() # Ignora caso a coluna já exista

        # Carga inicial se for a primeira execução
        cursor.execute("SELECT valor FROM config_sistema WHERE chave = 'seed_inicial';")
        seed_realizado = cursor.fetchone()

        if not seed_realizado:
            # Usuário Administrador Padrão
            cursor.execute("SELECT COUNT(*) FROM usuarios;")
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    INSERT INTO usuarios (nome, email, senha, perfil) 
                    VALUES ('Administrador Padrão', 'admin@ngi.com', '123', 'Administrador');
                """)

            # Produtos do Estoque Geral
            cursor.execute("SELECT COUNT(*) FROM produtos;")
            if cursor.fetchone()[0] == 0:
                produtos_iniciais = [
                    ("001", "Capacete de Segurança", 15, "EPI", 45.00),
                    ("002", "Resma Papel A4", 0, "Material de Escritório", 28.50),
                    ("003", "Luva de Raspa", 50, "EPI", 12.00)
                ]
                cursor.executemany("INSERT INTO produtos VALUES (%s, %s, %s, %s, %s);", produtos_iniciais)

            # Itens Iniciais de Empréstimo (Independente)
            cursor.execute("SELECT COUNT(*) FROM itens_emprestimo;")
            if cursor.fetchone()[0] == 0:
                itens_emp_iniciais = [
                    ("EMP-001", "Televisão 55''", 2),
                    ("EMP-002", "Caixa de Som Amplificada", 3),
                    ("EMP-003", "Microfone Sem Fio", 4)
                ]
                cursor.executemany("INSERT INTO itens_emprestimo VALUES (%s, %s, %s);", itens_emp_iniciais)

            # Coordenações
            cursor.execute("SELECT COUNT(*) FROM coordenacoes;")
            if cursor.fetchone()[0] == 0:
                cursor.executemany("INSERT INTO coordenacoes VALUES (%s, %s);", [
                    ("COTEC", "Coordenação Técnica"),
                    ("COLOG", "Coordenação de Logística"),
                    ("COPS", "Coordenação de Proteção")
                ])

            # Categorias
            cursor.execute("SELECT COUNT(*) FROM categorias;")
            if cursor.fetchone()[0] == 0:
                cat_iniciais = [("EPI",), ("Material de Escritório",), ("Informática",), ("Limpeza",), ("Copa",)]
                cursor.executemany("INSERT INTO categorias VALUES (%s);", cat_iniciais)

            cursor.execute("INSERT INTO config_sistema (chave, valor) VALUES ('seed_inicial', 'true');")
            conn.commit()

    except Exception as e:
        conn.rollback()
        st.error(f"Erro ao inicializar tabelas no banco: {e}")
    finally:
        cursor.close()

    return conn

conn = inicializar_banco_automatico()

# Carregamento seguro dos dados globais
def carregar_dados_globais(conn):
    try:
        df_prod = pd.read_sql_query('SELECT codigo AS "Código", item AS "Item", quantidade AS "Quantidade", categoria AS "Categoria", valor_unitario AS "Valor Unitário" FROM produtos', conn)
        df_mov = pd.read_sql_query('SELECT id AS "ID", data AS "Data", tipo AS "Tipo", codigo AS "Código", item AS "Item", quantidade AS "Quantidade", responsavel AS "Responsável", coordenacao AS "Coordenação" FROM movimentacoes ORDER BY id DESC', conn)
        df_coord = pd.read_sql_query('SELECT sigla AS "Sigla", nome AS "Nome" FROM coordenacoes', conn)
        df_cat = pd.read_sql_query("SELECT nome FROM categorias", conn)
        lista_cat = df_cat["nome"].tolist() if not df_cat.empty else []
        return df_prod, df_mov, df_coord, lista_cat
    except Exception:
        conn.rollback()
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), []

df_produtos, df_movimentacoes, df_coordenacoes, lista_categorias = carregar_dados_globais(conn)

# Configurações de e-mail
try:
    EMAIL_REMETENTE = os.environ.get("GMAIL_EMAIL") or st.secrets["gmail"]["email"]
    SENHA_REMETENTE = os.environ.get("GMAIL_SENHA") or st.secrets["gmail"]["senha"]
    SMTP_HOST = os.environ.get("GMAIL_SMTP_SERVER") or st.secrets["gmail"]["smtp_server"]
    SMTP_PORTA = int(os.environ.get("GMAIL_SMTP_PORT") or st.secrets["gmail"]["smtp_port"])
except Exception:
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
                    try:
                        conn.rollback() # Limpa qualquer transação abortada previamente
                        cursor = conn.cursor()
                        cursor.execute("SELECT nome, senha FROM usuarios WHERE LOWER(email) = %s;", (usuario_input.strip().lower(),))
                        resultado = cursor.fetchone()
                        cursor.close()
                        
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
                    except Exception as e:
                        conn.rollback()
                        st.error(f"Erro ao processar login: {e}")
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
                        conn.rollback()
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM usuarios WHERE LOWER(email) = %s;", (email_recuperar.strip().lower(),))
                        existe = cursor.fetchone()[0] > 0
                        cursor.close()
                        
                        if existe:
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
                    except Exception as e:
                        conn.rollback()
                        st.error(f"Erro na busca: {e}")
                else:
                    st.warning("Por favor, digite um e-mail válido.")
            if st.button("Voltar para o Login", use_container_width=True):
                st.session_state.sub_tela_login = "login"
                st.rerun()

# =============================================================================
# FLUXO 2: SISTEMA PRINCIPAL (PÓS-AUTENTICAÇÃO)
# =============================================================================
else:
    with st.sidebar:
        st.markdown(f"#### 👤 Olá, {st.session_state.NOME_USUARIO_LOGADO}")
        st.write("---")
        
        escolha = option_menu(
            menu_title=None,
            options=[
                "Painel Geral", 
                "Empréstimo de Materiais",
                "Cadastrar Produto", 
                "Cadastrar Categoria", 
                "Cadastrar Usuário", 
                "Cadastrar Coordenação",
                "Movimentação de Estoque",
                "Sair do Sistema"
            ],
            icons=["grid", "handbag", "box", "folder", "person-plus", "building", "arrow-left-right", "box-arrow-right"],
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

    # --- TELA: EMPRÉSTIMO DE MATERIAIS (MÓDULO INDEPENDENTE CORRIGIDO) ---
    elif escolha == "Empréstimo de Materiais":
        st.title("Controle de Empréstimo de Materiais")
        
        aba_emp = option_menu(
            menu_title=None,
            options=["Cadastrar Item para Empréstimo", "Registrar Empréstimo (Saída)", "Registrar Devolução", "Histórico & Pendências"],
            icons=["plus-circle", "box-arrow-right", "box-arrow-in-left", "card-checklist"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )

        # 1. SUB-ABA: CADASTRO DE ITENS DE EMPRÉSTIMO
        if aba_emp == "Cadastrar Item para Empréstimo":
            st.markdown("### 🛠️ Cadastrar Equipamento / Item de Empréstimo")
            col_cemp1, col_cemp2 = st.columns([1, 1.5])
            
            with col_cemp1:
                with st.form("form_cad_item_emp", clear_on_submit=True):
                    cod_emp = st.text_input("Código do Item (ex: EMP-001):*")
                    nome_emp = st.text_input("Nome do Equipamento (ex: TV 43, Caixa de Som):*")
                    qtd_emp = st.number_input("Quantidade Total Disponível:*", min_value=1, value=1, step=1)
                    
                    if st.form_submit_button("Cadastrar Equipamento", type="primary"):
                        if cod_emp.strip() and nome_emp.strip():
                            try:
                                conn.rollback()
                                cursor = conn.cursor()
                                cursor.execute("INSERT INTO itens_emprestimo (codigo, nome, quantidade) VALUES (%s, %s, %s);", 
                                               (cod_emp.strip().upper(), nome_emp.strip(), int(qtd_emp)))
                                conn.commit()
                                cursor.close()
                                st.success(f"✅ Item '{nome_emp}' cadastrado com sucesso para Empréstimos!")
                                st.rerun()
                            except psycopg2.IntegrityError:
                                conn.rollback()
                                st.error("❌ Código já cadastrado para outro item de empréstimo!")
                            except Exception as ex:
                                conn.rollback()
                                st.error(f"Erro ao salvar: {ex}")
                        else:
                            st.error("Preencha o Código e o Nome do Equipamento!")

            with col_cemp2:
                st.markdown("##### 📋 Equipamentos Cadastrados para Empréstimo")
                try:
                    conn.rollback()
                    df_itens_emp = pd.read_sql_query('SELECT codigo AS "Código", nome AS "Equipamento/Item", quantidade AS "Qtd Total" FROM itens_emprestimo ORDER BY codigo ASC', conn)
                    if df_itens_emp.empty:
                        st.info("Nenhum item cadastrado exclusivamente para empréstimo.")
                    else:
                        st.dataframe(df_itens_emp, use_container_width=True, hide_index=True)
                except Exception as ex:
                    conn.rollback()
                    st.error(f"Erro ao carregar itens: {ex}")

        # 2. SUB-ABA: REGISTRO DE EMPRÉSTIMO (SAÍDA)
        elif aba_emp == "Registrar Empréstimo (Saída)":
            st.markdown("### 📤 Registrar Saída por Empréstimo")
            
            try:
                conn.rollback()
                df_itens_emp = pd.read_sql_query("SELECT codigo, nome, quantidade FROM itens_emprestimo ORDER BY nome ASC", conn)
            except Exception:
                conn.rollback()
                df_itens_emp = pd.DataFrame()

            if df_itens_emp.empty:
                st.warning("⚠️ Nenhum item cadastrado na aba de Empréstimos. Cadastre um item na sub-aba 'Cadastrar Item para Empréstimo' primeiro.")
            else:
                with st.form("form_reg_emprestimo", clear_on_submit=True):
                    col_e1, col_e2 = st.columns(2)
                    
                    item_sel_idx = col_e1.selectbox(
                        "Selecione o Item para Empréstimo:*",
                        df_itens_emp.index,
                        format_func=lambda x: f"{df_itens_emp.loc[x, 'codigo']} - {df_itens_emp.loc[x, 'nome']} (Saldo Total: {df_itens_emp.loc[x, 'quantidade']})"
                    )
                    
                    qtd_saida = col_e2.number_input("Quantidade:*", min_value=1, value=1, step=1)
                    resp_emp = col_e1.text_input("Nome da Pessoa Responsável:*", placeholder="Digite o nome completo da pessoa responsável")
                    
                    lista_siglas_coord = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else []
                    if not lista_siglas_coord:
                        coord_emp = col_e2.text_input("Nome da Coordenação:*", placeholder="Ex: COTEC, COLOG, COPS")
                    else:
                        coord_emp = col_e2.selectbox("Nome da Coordenação:*", lista_siglas_coord)

                    dt_emprestimo = col_e1.date_input("Data do Empréstimo:*", value=date.today())
                    dt_devolucao = col_e2.date_input("Data Prevista de Devolução:*", min_value=date.today())

                    if st.form_submit_button("Confirmar Empréstimo", type="primary"):
                        cod_p = df_itens_emp.loc[item_sel_idx, 'codigo']
                        nome_p = df_itens_emp.loc[item_sel_idx, 'nome']
                        qtd_disponivel = int(df_itens_emp.loc[item_sel_idx, 'quantidade'])

                        if not resp_emp or not resp_emp.strip():
                            st.error("❌ O NOME DA PESSOA RESPONSÁVEL É OBRIGATÓRIO!")
                        elif not str(coord_emp).strip():
                            st.error("❌ O NOME DA COORDENAÇÃO É OBRIGATÓRIO!")
                        elif qtd_saida > qtd_disponivel:
                            st.error(f"❌ Quantidade informada ({qtd_saida}) maior que o saldo cadastrado ({qtd_disponivel})!")
                        else:
                            dt_emp_str = dt_emprestimo.strftime("%Y-%m-%d")
                            dt_dev_str = dt_devolucao.strftime("%Y-%m-%d")

                            try:
                                conn.rollback()
                                cursor = conn.cursor()
                                
                                cursor.execute("UPDATE itens_emprestimo SET quantidade = quantidade - %s WHERE codigo = %s;", (qtd_saida, cod_p))

                                cursor.execute("""
                                    INSERT INTO emprestimos (codigo_item, nome_item, quantidade, responsavel, coordenacao, data_emprestimo, data_devolucao, status)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pendente');
                                """, (cod_p, nome_p, qtd_saida, resp_emp.strip(), str(coord_emp).strip(), dt_emp_str, dt_dev_str))

                                conn.commit()
                                cursor.close()
                                st.success(f"✅ Empréstimo de {qtd_saida}x '{nome_p}' registrado para {resp_emp.strip()} ({coord_emp}) com sucesso!")
                                st.rerun()
                            except Exception as ex:
                                conn.rollback()
                                st.error(f"Erro ao registrar empréstimo: {ex}")

        # 3. SUB-ABA: REGISTRAR DEVOLUÇÃO
        elif aba_emp == "Registrar Devolução":
            st.markdown("### 📥 Registrar Devolução / Retorno de Material")
            
            try:
                conn.rollback()
                df_pendentes = pd.read_sql_query("SELECT id, codigo_item, nome_item, quantidade, responsavel, coordenacao, data_emprestimo, data_devolucao FROM emprestimos WHERE status = 'Pendente' ORDER BY id DESC", conn)
            except Exception:
                conn.rollback()
                df_pendentes = pd.DataFrame()

            if df_pendentes.empty:
                st.info("Não há empréstimos pendentes de devolução.")
            else:
                with st.form("form_dev_emprestimo", clear_on_submit=True):
                    id_sel = st.selectbox(
                        "Selecione o Item a ser Devolvido:*",
                        df_pendentes.index,
                        format_func=lambda x: f"ID #{df_pendentes.loc[x, 'id']} | {df_pendentes.loc[x, 'nome_item']} ({df_pendentes.loc[x, 'quantidade']}x) - Resp: {df_pendentes.loc[x, 'responsavel']} ({df_pendentes.loc[x, 'coordenacao']}) | Prev. Devolução: {df_pendentes.loc[x, 'data_devolucao']}"
                    )
                    
                    if st.form_submit_button("Confirmar Retorno ao Estoque de Empréstimos", type="primary"):
                        row = df_pendentes.loc[id_sel]
                        id_emp = int(row['id'])
                        cod_p = row['codigo_item']
                        nome_p = row['nome_item']
                        qtd_p = int(row['quantidade'])
                        dt_hoje_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        try:
                            conn.rollback()
                            cursor = conn.cursor()

                            cursor.execute("UPDATE emprestimos SET status = 'Devolvido', data_retorno_real = %s WHERE id = %s;", (dt_hoje_str, id_emp))
                            cursor.execute("UPDATE itens_emprestimo SET quantidade = quantidade + %s WHERE codigo = %s;", (qtd_p, cod_p))

                            conn.commit()
                            cursor.close()
                            st.success(f"✅ Devolução do item '{nome_p}' confirmada com sucesso!")
                            st.rerun()
                        except Exception as ex:
                            conn.rollback()
                            st.error(f"Erro ao processar devolução: {ex}")

        # 4. SUB-ABA: HISTÓRICO & PENDÊNCIAS
        elif aba_emp == "Histórico & Pendências":
            st.markdown("### 🟡 Empréstimos Pendentes (Em Uso)")
            try:
                conn.rollback()
                df_hist_emp = pd.read_sql_query("""
                    SELECT 
                        id AS "ID",
                        codigo_item AS "Código",
                        nome_item AS "Item / Equipamento",
                        quantidade AS "Qtd",
                        responsavel AS "Nome do Responsável",
                        coordenacao AS "Coordenação",
                        data_emprestimo AS "Data do Empréstimo",
                        data_devolucao AS "Data de Devolução",
                        data_retorno_real AS "Retorno Efetuado em",
                        status AS "Status"
                    FROM emprestimos 
                    ORDER BY id DESC
                """, conn)

                if not df_hist_emp.empty:
                    df_pend = df_hist_emp[df_hist_emp["Status"] == "Pendente"]
                    if df_pend.empty:
                        st.success("🎉 Todos os materiais emprestados já foram devidamente devolvidos!")
                    else:
                        st.dataframe(df_pend, use_container_width=True, hide_index=True)

                    st.markdown("<br><hr>", unsafe_allow_html=True)
                    st.markdown("### 📜 Histórico Completo de Empréstimos e Devoluções")
                    st.dataframe(df_hist_emp, use_container_width=True, hide_index=True)
                else:
                    st.info("Nenhum empréstimo cadastrado até o momento.")
            except Exception as ex:
                conn.rollback()
                st.error(f"Erro ao buscar histórico: {ex}")

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
                cat_it = col_a.selectbox("Categoria", lista_categorias if lista_categorias else ["Padrão"])
                val_unit = col_b.number_input("Valor Unitário (R$)", min_value=0.0, step=0.01, format="%.2f")
                st.caption("ℹ️ Novos materiais são registrados com saldo inicial 0.")
                
                if st.form_submit_button("Finalizar Cadastro", type="primary"):
                    if cod and nome_it:
                        try:
                            conn.rollback()
                            cursor = conn.cursor()
                            cursor.execute("INSERT INTO produtos VALUES (%s, %s, %s, %s, %s);", (cod.strip(), nome_it.strip(), 0, cat_it, float(val_unit)))
                            conn.commit()
                            cursor.close()
                            st.success(f"Sucesso! {nome_it} adicionado.")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error(f"Erro! Código {cod} já existe.")
                        except Exception as e:
                            conn.rollback()
                            st.error(f"Erro ao salvar: {e}")
                    else:
                        st.error("Preencha todos os campos!")
                        
        elif aba_selecionada == "Editar / Excluir Produtos":
            if not df_produtos.empty:
                st.dataframe(df_produtos, use_container_width=True, hide_index=True)
                conn.rollback()
                df_raw_prod = pd.read_sql_query("SELECT * FROM produtos", conn)
                opcao_selecionada = st.selectbox("Selecione para modificar:", df_raw_prod.index, format_func=lambda x: f"{df_raw_prod.loc[x, 'codigo']} - {df_raw_prod.loc[x, 'item']}")
                
                cod_atual = df_raw_prod.loc[opcao_selecionada, "codigo"]
                col_ed1, col_ed2 = st.columns(2)
                edit_cod = col_ed1.text_input("Código:", value=df_raw_prod.loc[opcao_selecionada, "codigo"])
                edit_item = col_ed2.text_input("Nome:", value=df_raw_prod.loc[opcao_selecionada, "item"])
                edit_qtd = col_ed1.number_input("Quantidade (Ajuste):", min_value=0, value=int(df_raw_prod.loc[opcao_selecionada, "quantidade"]))
                
                cat_atual = df_raw_prod.loc[opcao_selecionada, "categoria"]
                idx_cat_padrao = lista_categorias.index(cat_atual) if cat_atual in lista_categorias else 0
                edit_cat = col_ed2.selectbox("Categoria:", lista_categorias if lista_categorias else [cat_atual], index=idx_cat_padrao)
                edit_val = st.number_input("Valor Unitário:", min_value=0.0, step=0.01, format="%.2f", value=float(df_raw_prod.loc[opcao_selecionada, "valor_unitario"]))
                
                col_b_prod1, col_b_prod2 = st.columns([1, 4])
                with col_b_prod1:
                    if st.button("Salvar Alterações", type="primary"):
                        try:
                            conn.rollback()
                            cursor = conn.cursor()
                            cursor.execute("""
                                UPDATE produtos 
                                SET codigo = %s, item = %s, quantidade = %s, categoria = %s, valor_unitario = %s 
                                WHERE codigo = %s;
                            """, (edit_cod.strip(), edit_item.strip(), edit_qtd, edit_cat, float(edit_val), cod_atual))
                            conn.commit()
                            cursor.close()
                            st.success("Modificado com sucesso!")
                            st.rerun()
                        except Exception as e:
                            conn.rollback()
                            st.error(f"Erro ao modificar: {e}")
                with col_b_prod2:
                    if st.button("Excluir Produto"):
                        try:
                            conn.rollback()
                            cursor = conn.cursor()
                            cursor.execute("DELETE FROM produtos WHERE codigo = %s;", (cod_atual,))
                            conn.commit()
                            cursor.close()
                            st.warning("Removido com sucesso.")
                            st.rerun()
                        except Exception as e:
                            conn.rollback()
                            st.error(f"Erro ao remover: {e}")

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
                            conn.rollback()
                            cursor = conn.cursor()
                            cursor.execute("INSERT INTO categorias VALUES (%s);", (nova_cat.strip(),))
                            conn.commit()
                            cursor.close()
                            st.success("Adicionada!")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error("Esta categoria já existe.")
                        except Exception as e:
                            conn.rollback()
                            st.error(f"Erro: {e}")
            with col_cat2:
                st.dataframe(pd.DataFrame(lista_categorias, columns=["Categorias Ativas"]), use_container_width=True, hide_index=True)
                
        elif aba_selecionada == "Editar / Excluir Categorias":
            if lista_categorias:
                cat_selecionada = st.selectbox("Selecione a categoria:", lista_categorias)
                edit_nome_cat = st.text_input("Editar Nome:", value=cat_selecionada)
                
                c_btn_cat1, c_btn_cat2 = st.columns([1, 4])
                with c_btn_cat1:
                    if st.button("Salvar Edição", type="primary"):
                        try:
                            conn.rollback()
                            cursor = conn.cursor()
                            cursor.execute("UPDATE categorias SET nome = %s WHERE nome = %s;", (edit_nome_cat.strip(), cat_selecionada))
                            conn.commit()
                            cursor.close()
                            st.success("Atualizado!")
                            st.rerun()
                        except Exception as e:
                            conn.rollback()
                            st.error(f"Erro: {e}")
                with c_btn_cat2:
                    if st.button("Excluir Categoria"):
                        try:
                            conn.rollback()
                            cursor = conn.cursor()
                            cursor.execute("DELETE FROM categorias WHERE nome = %s;", (cat_selecionada,))
                            conn.commit()
                            cursor.close()
                            st.warning("Removida.")
                            st.rerun()
                        except Exception as e:
                            conn.rollback()
                            st.error(f"Erro: {e}")

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
                            conn.rollback()
                            cursor = conn.cursor()
                            cursor.execute("""
                                INSERT INTO usuarios (nome, email, senha, perfil) 
                                VALUES (%s, %s, %s, %s);
                            """, (n.strip(), e.strip().lower(), s if s else "123", p))
                            conn.commit()
                            cursor.close()
                            st.success("Usuário registrado com sucesso!")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error("Este e-mail já está cadastrado.")
                        except Exception as ex:
                            conn.rollback()
                            st.error(f"Erro ao salvar: {ex}")
                    else:
                        st.error("Preencha o Nome e o E-mail!")
                        
        elif aba_selecionada == "Editar / Excluir Usuários":
            conn.rollback()
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
                        try:
                            conn.rollback()
                            cursor = conn.cursor()
                            cursor.execute("""
                                UPDATE usuarios SET nome = %s, email = %s, senha = %s, perfil = %s WHERE email = %s;
                            """, (edit_n.strip(), edit_e.strip().lower(), edit_s, edit_p, email_chave))
                            conn.commit()
                            cursor.close()
                            st.success("Atualizado!")
                            st.rerun()
                        except Exception as ex:
                            conn.rollback()
                            st.error(f"Erro: {ex}")
                with c_btn_u2:
                    if st.button("Excluir Usuário"):
                        try:
                            conn.rollback()
                            cursor = conn.cursor()
                            cursor.execute("DELETE FROM usuarios WHERE email = %s;", (email_chave,))
                            conn.commit()
                            cursor.close()
                            st.warning("Removido.")
                            st.rerun()
                        except Exception as ex:
                            conn.rollback()
                            st.error(f"Erro: {ex}")

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
                            conn.rollback()
                            cursor = conn.cursor()
                            cursor.execute("INSERT INTO coordenacoes VALUES (%s, %s);", (s_coord.strip().upper(), nc.strip()))
                            conn.commit()
                            cursor.close()
                            st.success("Cadastrada!")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            conn.rollback()
                            st.error("Esta sigla já está registrada.")
                        except Exception as ex:
                            conn.rollback()
                            st.error(f"Erro: {ex}")
                    else:
                        st.error("Preencha todos os campos!")
                        
        elif aba_selecionada == "Editar / Excluir Coordenação":
            if not df_coordenacoes.empty:
                st.dataframe(df_coordenacoes, use_container_width=True, hide_index=True)
                sigla_selecionada = st.selectbox("Selecione para modificar:", df_coordenacoes["Sigla"].tolist())
                
                try:
                    conn.rollback()
                    cursor = conn.cursor()
                    cursor.execute("SELECT nome FROM coordenacoes WHERE sigla = %s;", (sigla_selecionada,))
                    nome_atual_c = cursor.fetchone()[0]
                    cursor.close()
                except Exception:
                    conn.rollback()
                    nome_atual_c = ""
                
                edit_sigla = st.text_input("Sigla:", value=sigla_selecionada)
                edit_nc = st.text_input("Nome:", value=nome_atual_c)
                
                c_btn_c1, c_btn_c2 = st.columns([1, 4])
                with c_btn_c1:
                    if st.button("Salvar Edição", type="primary"):
                        try:
                            conn.rollback()
                            cursor = conn.cursor()
                            cursor.execute("UPDATE coordenacoes SET sigla = %s, nome = %s WHERE sigla = %s;", (edit_sigla.strip().upper(), edit_nc.strip(), sigla_selecionada))
                            conn.commit()
                            cursor.close()
                            st.success("Atualizada!")
                            st.rerun()
                        except Exception as ex:
                            conn.rollback()
                            st.error(f"Erro: {ex}")
                with c_btn_c2:
                    if st.button("Excluir Coordenação"):
                        try:
                            conn.rollback()
                            cursor = conn.cursor()
                            cursor.execute("DELETE FROM coordenacoes WHERE sigla = %s;", (sigla_selecionada,))
                            conn.commit()
                            cursor.close()
                            st.warning("Removida.")
                            st.rerun()
                        except Exception as ex:
                            conn.rollback()
                            st.error(f"Erro: {ex}")

    # --- TELA: MOVIMENTAÇÃO DE ESTOQUE (CONSUMO DE MATERIAIS DE ESTOQUE GERAL) ---
    elif escolha == "Movimentação de Estoque":
        st.title("Movimentação de Estoque Geral")
        
        aba_mov = option_menu(
            menu_title=None,
            options=["Lançar Movimentação", "Histórico de Movimentações"],
            icons=["arrow-left-right", "clock-history"],
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )
        
        if aba_mov == "Lançar Movimentação":
            if df_produtos.empty:
                st.warning("Nenhum produto cadastrado para realizar movimentação.")
            else:
                with st.form("form_movimentacao", clear_on_submit=True):
                    col_m1, col_m2 = st.columns(2)
                    
                    prod_opcao = col_m1.selectbox(
                        "Selecione o Produto:", 
                        df_produtos.index, 
                        format_func=lambda x: f"{df_produtos.loc[x, 'Código']} - {df_produtos.loc[x, 'Item']} (Saldo: {df_produtos.loc[x, 'Quantidade']})"
                    )
                    
                    tipo_mov = col_m2.selectbox("Tipo de Movimentação:", ["Entrada", "Saída"])
                    qtd_mov = col_m1.number_input("Quantidade:", min_value=1, value=1, step=1)
                    
                    lista_siglas_coord = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["N/A"]
                    coord_mov = col_m2.selectbox("Coordenação Requisitante/Destino:", lista_siglas_coord)
                    resp_mov = st.text_input("Responsável pela Retirada / Recebimento:", value=st.session_state.NOME_USUARIO_LOGADO)
                    
                    if st.form_submit_button("Confirmar Movimentação", type="primary"):
                        cod_p = df_produtos.loc[prod_opcao, "Código"]
                        item_p = df_produtos.loc[prod_opcao, "Item"]
                        qtd_atual = int(df_produtos.loc[prod_opcao, "Quantidade"])
                        
                        if tipo_mov == "Saída" and qtd_mov > qtd_atual:
                            st.error(f"Saldo insuficiente! Saldo atual em estoque: {qtd_atual}")
                        else:
                            nova_qtd = qtd_atual + qtd_mov if tipo_mov == "Entrada" else qtd_atual - qtd_mov
                            data_hoje = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            try:
                                conn.rollback()
                                cursor = conn.cursor()
                                cursor.execute("UPDATE produtos SET quantidade = %s WHERE codigo = %s;", (nova_qtd, cod_p))
                                cursor.execute("""
                                    INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                                """, (data_hoje, tipo_mov, cod_p, item_p, qtd_mov, resp_mov.strip(), coord_mov))
                                conn.commit()
                                cursor.close()
                                
                                st.success(f"Movimentação ({tipo_mov}) realizada com sucesso! Novo saldo: {nova_qtd}")
                                st.rerun()
                            except Exception as ex:
                                conn.rollback()
                                st.error(f"Erro ao salvar movimentação: {ex}")
                                
        elif aba_mov == "Histórico de Movimentações":
            st.markdown("### 📜 Registros de Entradas e Saídas do Estoque Geral")
            if df_movimentacoes.empty:
                st.info("Nenhuma movimentação registrada no sistema até o momento.")
            else:
                col_h1, col_h2 = st.columns(2)
                filtro_tipo = col_h1.selectbox("Filtrar por Tipo:", ["Todos", "Entrada", "Saída"])
                filtro_resp = col_h2.text_input("Filtrar por Responsável ou Material:")
                
                df_hist = df_movimentacoes.copy()
                if filtro_tipo != "Todos":
                    df_hist = df_hist[df_hist["Tipo"] == filtro_tipo]
                if filtro_resp.strip():
                    df_hist = df_hist[
                        df_hist["Responsável"].str.contains(filtro_resp, case=False, na=False) |
                        df_hist["Item"].str.contains(filtro_resp, case=False, na=False)
                    ]
                
                st.dataframe(df_hist, use_container_width=True, hide_index=True)
