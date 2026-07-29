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

    # 6. Tabela de Itens de Empréstimo
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
            status TEXT NOT NULL DEFAULT 'EMPRESTADO',
            responsavel_devolucao TEXT
        );
    """)

    # 8. Tabela de Solicitações do Sistema (Insumos e Empréstimos)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS solicitacoes (
            id SERIAL PRIMARY KEY,
            tipo_solicitacao TEXT NOT NULL, -- 'ALMOXARIFADO' ou 'EMPRESTIMO'
            item_codigo TEXT,
            item_id INTEGER,
            item_nome TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            solicitante_nome TEXT NOT NULL,
            solicitante_email TEXT NOT NULL,
            coordenacao TEXT NOT NULL,
            data_solicitacao DATE NOT NULL,
            data_prevista_devolucao DATE,
            status TEXT NOT NULL DEFAULT 'PENDENTE', -- 'PENDENTE', 'APROVADO', 'RECUSADO'
            observacao TEXT
        );
    """)

    conn.commit()

    # Verifica se a carga inicial (seed) já foi realizada
    cursor.execute("SELECT valor FROM config_sistema WHERE chave = 'seed_inicial';")
    seed_realizado = cursor.fetchone()

    if not seed_realizado:
        cursor.execute("SELECT COUNT(*) FROM usuarios;")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO usuarios (nome, email, senha, perfil) 
                VALUES 
                ('Administrador Padrão', 'admin@ngi.com', '123', 'Administrador'),
                ('Usuário Padrão', 'usuario@ngi.com', '123', 'Usuário');
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
    
    return conn

conn = inicializar_banco_automatico()

# Carregamento seguro dos dados
def carregar_dados():
    try:
        df_prod = pd.read_sql_query('SELECT codigo AS "Código", item AS "Item", quantidade AS "Quantidade", categoria AS "Categoria", valor_unitario AS "Valor Unitário" FROM produtos', conn)
        df_mov = pd.read_sql_query('SELECT data AS "Data", tipo AS "Tipo", codigo AS "Código", item AS "Item", quantidade AS "Quantidade", responsavel AS "Responsável", coordenacao AS "Coordenação" FROM movimentacoes', conn)
        df_coord = pd.read_sql_query('SELECT sigla AS "Sigla", nome AS "Nome" FROM coordenacoes', conn)
        df_cat = pd.read_sql_query("SELECT nome FROM categorias", conn)
        lista_cat = df_cat["nome"].tolist()
        return df_prod, df_mov, df_coord, lista_cat
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), []

df_produtos, df_movimentacoes, df_coordenacoes, lista_categorias = carregar_dados()

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

if "EMAIL_USUARIO_LOGADO" not in st.session_state:
    st.session_state.EMAIL_USUARIO_LOGADO = ""

if "PERFIL_USUARIO_LOGADO" not in st.session_state:
    st.session_state.PERFIL_USUARIO_LOGADO = "Usuário"

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
                    cursor.execute("SELECT nome, email, senha, perfil FROM usuarios WHERE LOWER(email) = %s;", (usuario_input.strip().lower(),))
                    resultado = cursor.fetchone()
                    
                    if resultado:
                        nome_banco, email_banco, senha_banco, perfil_banco = resultado
                        if str(senha_banco) == str(senha_input).strip():
                            st.session_state.autenticado = True
                            st.session_state.NOME_USUARIO_LOGADO = nome_banco
                            st.session_state.EMAIL_USUARIO_LOGADO = email_banco
                            st.session_state.PERFIL_USUARIO_LOGADO = perfil_banco or "Usuário"
                            st.rerun()
                        else:
                            st.error("Senha incorreta!")
                    else:
                        st.error("Usuário ou E-mail não cadastrado!")
                else:
                    st.error("Por favor, preencha todos os campos!")
                    
            if st.button("Esqueci a senha", use_container_width=True):
                st.session_state.sub_tela_login = "esqueci"
                st.rerun()

    elif st.session_state.sub_tela_login == "esqueci":
        col_r1, col_r2, col_r3 = st.columns([1, 1.2, 1])
        with col_r2:
            st.write("<br><br>", unsafe_allow_html=True)
            st.markdown("### Recuperar Acesso")
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
    cursor = conn.cursor()
    eh_admin = st.session_state.PERFIL_USUARIO_LOGADO == "Administrador"

    # --- MENU LATERAL DE ACORDO COM PERFIL ---
    with st.sidebar:
        st.markdown(f"#### Olá, {st.session_state.NOME_USUARIO_LOGADO}")
        st.caption(f"Perfil: **{st.session_state.PERFIL_USUARIO_LOGADO}**")
        st.write("---")
        
        # Opções completas mantidas exatamente igual solicitado
        if eh_admin:
            opcoes_menu = [
                "Painel Geral", 
                "Empréstimo de Material",
                "Cadastrar Produto", 
                "Cadastrar Categoria", 
                "Cadastrar Usuário", 
                "Cadastrar Coordenação",
                "Movimentação de Estoque",
                "Sair do Sistema"
            ]
            icones_menu = ["grid", "arrow-repeat", "box", "folder", "person-plus", "building", "arrow-left-right", "box-arrow-right"]
        else:
            opcoes_menu = [
                "Painel Geral", 
                "Empréstimo de Material",
                "Sair do Sistema"
            ]
            icones_menu = ["grid", "arrow-repeat", "box-arrow-right"]

        escolha = option_menu(
            menu_title=None,
            options=opcoes_menu,
            icons=icones_menu,
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
        st.session_state.PERFIL_USUARIO_LOGADO = "Usuário"
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

        if eh_admin:
            sub_painel = option_menu(
                menu_title=None,
                options=["Consulta de Estoque", "Aprovar Solicitações"],
                icons=["search", "check-circle"],
                orientation="horizontal",
                styles=ESTILO_MENU_HORIZONTAL
            )
        else:
            sub_painel = "Consulta de Estoque"

        if sub_painel == "Consulta de Estoque":
            c1, c2, c3 = st.columns(3)
            
            # Ajuste de visualização conforme perfil
            if eh_admin:
                total_itens = len(df_produtos) if not df_produtos.empty else 0
                produtos_esgotados = len(df_produtos[df_produtos['Quantidade'] == 0]) if not df_produtos.empty else 0
            else:
                total_itens = len(df_produtos[df_produtos['Quantidade'] > 0]) if not df_produtos.empty else 0
                produtos_esgotados = 0

            total_movimentacoes = len(df_movimentacoes) if not df_movimentacoes.empty else 0
            
            c1.markdown(f"""
                <div style="background-color: rgba(76, 175, 80, 0.08); border-left: 5px solid #4CAF50; padding: 18px; border-radius: 4px;">
                    <span style="font-size: 13px; font-weight: 600; text-transform: uppercase;">Itens Disponíveis</span>
                    <h2 style="color: #4CAF50; margin: 8px 0 0 0; font-size: 34px; font-weight: 700;">{total_itens}</h2>
                </div>
            """, unsafe_allow_html=True)
            
            cor_esgotados = "#c62828" if produtos_esgotados > 0 else "#4CAF50"
            bg_esgotados = "rgba(198, 40, 40, 0.08)" if produtos_esgotados > 0 else "rgba(76, 175, 80, 0.08)"
            
            if eh_admin:
                c2.markdown(f"""
                    <div style="background-color: {bg_esgotados}; border-left: 5px solid {cor_esgotados}; padding: 18px; border-radius: 4px;">
                        <span style="font-size: 13px; font-weight: 600; text-transform: uppercase;">Produtos Esgotados</span>
                        <h2 style="color: {cor_esgotados}; margin: 8px 0 0 0; font-size: 34px; font-weight: 700;">{produtos_esgotados}</h2>
                    </div>
                """, unsafe_allow_html=True)
            else:
                cursor.execute("SELECT COUNT(*) FROM solicitacoes WHERE solicitante_email = %s AND status = 'PENDENTE';", (st.session_state.EMAIL_USUARIO_LOGADO,))
                minhas_pendentes = cursor.fetchone()[0]
                c2.markdown(f"""
                    <div style="background-color: rgba(255, 152, 0, 0.08); border-left: 5px solid #FF9800; padding: 18px; border-radius: 4px;">
                        <span style="font-size: 13px; font-weight: 600; text-transform: uppercase;">Minhas Solicitações Pendentes</span>
                        <h2 style="color: #FF9800; margin: 8px 0 0 0; font-size: 34px; font-weight: 700;">{minhas_pendentes}</h2>
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
            
            # PERFIL USUÁRIO: Oculta itens zerados do estoque
            if not eh_admin and not df_filtrado.empty:
                df_filtrado = df_filtrado[df_filtrado['Quantidade'] > 0]

            if not df_filtrado.empty and termo_busca:
                df_filtrado = df_filtrado[df_filtrado['Item'].str.contains(termo_busca, case=False, na=False) | df_filtrado['Código'].str.contains(termo_busca, case=False, na=False)]
            if not df_filtrado.empty and categoria_selecionada != "Todas":
                df_filtrado = df_filtrado[df_filtrado['Categoria'] == categoria_selecionada]

            st.markdown("<br><h3 style='font-size: 18px; font-weight: 600; margin-bottom: 12px;'>Posição Atual do Estoque</h3>", unsafe_allow_html=True)
            if df_filtrado.empty:
                st.info("Nenhum material encontrado com os filtros aplicados.")
            else:
                df_display = df_filtrado.copy()
                
                # Ocultar Valores Monetários para Perfil Usuário
                if not eh_admin:
                    df_display = df_display.drop(columns=["Valor Unitário"], errors="ignore")
                    st.dataframe(df_display, use_container_width=True, hide_index=True)
                else:
                    df_display["Valor Unitário"] = df_display["Valor Unitário"].astype(float)
                    df_display["Valor Total"] = df_display["Quantidade"] * df_display["Valor Unitário"]
                    df_display["Valor Unitário"] = df_display["Valor Unitário"].map("R$ {:.2f}".format)
                    df_display["Valor Total"] = df_display["Valor Total"].map("R$ {:.2f}".format)

                    def destacar_zerados(row):
                        if row['Quantidade'] == 0:
                            return ['background-color: rgba(198, 40, 40, 0.12); color: #c62828; font-weight: bold;'] * len(row)
                        return [''] * len(row)
                        
                    st.dataframe(df_display.style.apply(destacar_zerados, axis=1), use_container_width=True, hide_index=True)

            # Formulário de solicitação disponível para Perfil Usuário
            if not eh_admin:
                st.markdown("<br><hr>", unsafe_allow_html=True)
                st.subheader("Solicitar Material do Almoxarifado")
                if not df_filtrado.empty:
                    with st.form("form_solicitar_material", clear_on_submit=True):
                        col_s1, col_s2 = st.columns(2)
                        item_solicitado = col_s1.selectbox("Selecione o Item*", df_filtrado["Item"].tolist())
                        row_item = df_filtrado[df_filtrado["Item"] == item_solicitado].iloc[0]
                        
                        qtd_solicitada = col_s2.number_input("Quantidade Desejada*", min_value=1, max_value=int(row_item["Quantidade"]), value=1)
                        lista_siglas_coord = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["GERAL"]
                        coord_sol = col_s1.selectbox("Coordenação Solicitante*", lista_siglas_coord)
                        obs_sol = col_s2.text_input("Observação / Justificativa")

                        if st.form_submit_button("Enviar Solicitação", type="primary"):
                            cursor.execute("""
                                INSERT INTO solicitacoes (tipo_solicitacao, item_codigo, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, data_solicitacao, status, observacao)
                                VALUES ('ALMOXARIFADO', %s, %s, %s, %s, %s, %s, %s, 'PENDENTE', %s);
                            """, (row_item["Código"], item_solicitado, qtd_solicitada, st.session_state.NOME_USUARIO_LOGADO, st.session_state.EMAIL_USUARIO_LOGADO, coord_sol, date.today(), obs_sol))
                            conn.commit()
                            st.success("Solicitação enviada com sucesso! Aguarde aprovação do Administrador.")
                            st.rerun()

        elif sub_painel == "Aprovar Solicitações" and eh_admin:
            st.subheader("Aprovação de Solicitações de Material")
            cursor.execute("SELECT id, tipo_solicitacao, item_codigo, item_nome, quantidade, solicitante_nome, coordenacao, data_solicitacao, observacao FROM solicitacoes WHERE status = 'PENDENTE' AND tipo_solicitacao = 'ALMOXARIFADO';")
            solic_pendentes = cursor.fetchall()

            if not solic_pendentes:
                st.info("Não há solicitações pendentes de aprovação no momento.")
            else:
                for sol in solic_pendentes:
                    s_id, s_tipo, s_cod, s_nome, s_qtd, s_solicitante, s_coord, s_data, s_obs = sol
                    with st.expander(f"Solicitação #{s_id} - {s_nome} ({s_qtd} un.) - Solicitado por: {s_solicitante}"):
                        st.write(f"**Item:** {s_nome} | **Código:** {s_cod}")
                        st.write(f"**Quantidade Solicitada:** {s_qtd} | **Coordenação:** {s_coord}")
                        st.write(f"**Data da Solicitação:** {s_data} | **Justificativa:** {s_obs or 'Nenhuma'}")
                        
                        c_ap1, c_ap2 = st.columns(2)
                        if c_ap1.button(f"Aprovar #{s_id}", key=f"app_{s_id}", type="primary"):
                            cursor.execute("SELECT quantidade FROM produtos WHERE codigo = %s;", (s_cod,))
                            qtd_atual = cursor.fetchone()
                            if qtd_atual and qtd_atual[0] >= s_qtd:
                                cursor.execute("UPDATE produtos SET quantidade = quantidade - %s WHERE codigo = %s;", (s_qtd, s_cod))
                                cursor.execute("INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao) VALUES (%s, 'SAIDA', %s, %s, %s, %s, %s);",
                                               (date.today().strftime('%Y-%m-%d %H:%M:%S'), s_cod, s_nome, s_qtd, s_solicitante, s_coord))
                                cursor.execute("UPDATE solicitacoes SET status = 'APROVADO' WHERE id = %s;", (s_id,))
                                conn.commit()
                                st.success("Solicitação aprovada e saída registrada!")
                                st.rerun()
                            else:
                                st.error("Estoque insuficiente para aprovar esta solicitação!")

                        if c_ap2.button(f"Recusar #{s_id}", key=f"rec_{s_id}"):
                            cursor.execute("UPDATE solicitacoes SET status = 'RECUSADO' WHERE id = %s;", (s_id,))
                            conn.commit()
                            st.warning("Solicitação recusada.")
                            st.rerun()

    # =========================================================================
    # TELA: EMPRÉSTIMO DE MATERIAL
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

        if eh_admin:
            opcoes_emp = [
                "Itens Disponíveis", 
                "Cadastrar Item Empréstimo", 
                "Registrar Saída (Empréstimo)", 
                "Registrar Devolução", 
                "Histórico de Movimentação",
                "Aprovar Solicitações"
            ]
            icones_emp = ["box-seam", "plus-circle", "box-arrow-right", "box-arrow-in-left", "journal-text", "check-circle"]
        else:
            opcoes_emp = [
                "Itens Disponíveis",
                "Solicitar Empréstimo"
            ]
            icones_emp = ["box-seam", "plus-circle"]

        sub_emp = option_menu(
            menu_title=None,
            options=opcoes_emp,
            icons=icones_emp,
            orientation="horizontal",
            styles=ESTILO_MENU_HORIZONTAL
        )

        # SUB-ABA 1: ITENS DISPONÍVEIS
        if sub_emp == "Itens Disponíveis":
            st.subheader("Painel de Disponibilidade de Empréstimos")
            
            df_emp_itens = pd.read_sql_query("""
                SELECT 
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
                if not eh_admin:
                    df_emp_itens = df_emp_itens[df_emp_itens["Qtd Disponível"] > 0]
                st.dataframe(df_emp_itens, use_container_width=True, hide_index=True)

        # SUB-ABA: SOLICITAR EMPRÉSTIMO (PARA USUÁRIO COMUM)
        elif sub_emp == "Solicitar Empréstimo" and not eh_admin:
            st.subheader("Solicitar Item para Empréstimo")
            cursor.execute("SELECT id, item, quantidade_disponivel FROM emprestimo_itens WHERE quantidade_disponivel > 0 ORDER BY item ASC;")
            itens_disp = cursor.fetchall()

            if not itens_disp:
                st.warning("Não há equipamentos disponíveis para empréstimo no momento.")
            else:
                opcoes_itens = {f"{item[1]} (Disponível: {item[2]})": (item[0], item[1], item[2]) for item in itens_disp}
                with st.form("form_solicitar_emp", clear_on_submit=True):
                    item_sel_label = st.selectbox("Selecione o Item desejado*", list(opcoes_itens.keys()))
                    item_id, item_nome, max_q = opcoes_itens[item_sel_label]

                    col_se1, col_se2 = st.columns(2)
                    qtd_pedida = col_se1.number_input("Quantidade*", min_value=1, max_value=max_q, value=1)
                    lista_siglas_coord = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["GERAL"]
                    coord_user = col_se2.selectbox("Coordenação*", lista_siglas_coord)

                    data_prev = col_se1.date_input("Data Prevista para Devolução*", value=date.today())
                    obs_emp_sol = col_se2.text_input("Observação / Finalidade")

                    if st.form_submit_button("Enviar Solicitação de Empréstimo", type="primary"):
                        cursor.execute("""
                            INSERT INTO solicitacoes (tipo_solicitacao, item_id, item_nome, quantidade, solicitante_nome, solicitante_email, coordenacao, data_solicitacao, data_prevista_devolucao, status, observacao)
                            VALUES ('EMPRESTIMO', %s, %s, %s, %s, %s, %s, %s, %s, 'PENDENTE', %s);
                        """, (item_id, item_nome, qtd_pedida, st.session_state.NOME_USUARIO_LOGADO, st.session_state.EMAIL_USUARIO_LOGADO, coord_user, date.today(), data_prev, obs_emp_sol))
                        conn.commit()
                        st.success("Solicitação de empréstimo realizada com sucesso! Aguarde aprovação.")
                        st.rerun()

        # SUB-ABA 2: CADASTRAR ITEM PARA EMPRÉSTIMO (ADMIN)
        elif sub_emp == "Cadastrar Item Empréstimo" and eh_admin:
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

        # SUB-ABA 3: REGISTRAR SAÍDA (ADMIN)
        elif sub_emp == "Registrar Saída (Empréstimo)" and eh_admin:
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
                    
                    data_retirada = col_s2.date_input("Data de Retirada*", value=date.today())
                    data_prevista = col_s1.date_input("Data Prevista para Devolução*", value=date.today())

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

        # SUB-ABA 4: REGISTRAR DEVOLUÇÃO (ADMIN)
        elif sub_emp == "Registrar Devolução" and eh_admin:
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
                    data_devolucao = col_d2.date_input("Data Real da Devolução*", value=date.today())

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

        # SUB-ABA 5: HISTÓRICO DE MOVIMENTAÇÃO (ADMIN)
        elif sub_emp == "Histórico de Movimentação" and eh_admin:
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
                    to_char(data_devolucao, 'DD/MM/YYYY') AS "Data Devolução",
                    status AS "Status",
                    responsavel_devolucao AS "Devolvido Por"
                FROM emprestimo_registros ORDER BY id DESC;
            """, conn)

            if df_hist_emp.empty:
                st.info("Nenhum registro de empréstimo/devolução efetuado até o momento.")
            else:
                st.dataframe(df_hist_emp, use_container_width=True, hide_index=True)

        # SUB-ABA 6: APROVAR SOLICITAÇÕES DE EMPRÉSTIMO (ADMIN)
        elif sub_emp == "Aprovar Solicitações" and eh_admin:
            st.subheader("Aprovação de Solicitações de Empréstimo")
            cursor.execute("SELECT id, item_id, item_nome, quantidade, solicitante_nome, coordenacao, data_solicitacao, data_prevista_devolucao, observacao FROM solicitacoes WHERE status = 'PENDENTE' AND tipo_solicitacao = 'EMPRESTIMO';")
            solic_emp_pend = cursor.fetchall()

            if not solic_emp_pend:
                st.info("Não há solicitações de empréstimo pendentes.")
            else:
                for sol in solic_emp_pend:
                    se_id, se_item_id, se_nome, se_qtd, se_solicitante, se_coord, se_data, se_prev, se_obs = sol
                    with st.expander(f"Solicitação #{se_id} - {se_nome} ({se_qtd} un.) - Solicitado por: {se_solicitante}"):
                        st.write(f"**Item:** {se_nome} | **Quantidade:** {se_qtd}")
                        st.write(f"**Coordenação:** {se_coord} | **Previsão Devolução:** {se_prev}")
                        st.write(f"**Justificativa:** {se_obs or 'Nenhuma'}")

                        c_eap1, c_eap2 = st.columns(2)
                        if c_eap1.button(f"Aprovar #{se_id}", key=f"app_e_{se_id}", type="primary"):
                            cursor.execute("SELECT quantidade_disponivel FROM emprestimo_itens WHERE id = %s;", (se_item_id,))
                            disp = cursor.fetchone()
                            if disp and disp[0] >= se_qtd:
                                cursor.execute("""
                                    INSERT INTO emprestimo_registros (item_id, item_nome, quantidade, pessoa, coordenacao, data_retirada, data_prevista, status)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'EMPRESTADO');
                                """, (se_item_id, se_nome, se_qtd, se_solicitante, se_coord, date.today(), se_prev))

                                cursor.execute("UPDATE emprestimo_itens SET quantidade_disponivel = quantidade_disponivel - %s WHERE id = %s;", (se_qtd, se_item_id))
                                cursor.execute("UPDATE solicitacoes SET status = 'APROVADO' WHERE id = %s;", (se_id,))
                                conn.commit()
                                st.success("Empréstimo aprovado com sucesso!")
                                st.rerun()
                            else:
                                st.error("Quantidade indisponível no acervo no momento!")

                        if c_eap2.button(f"Recusar #{se_id}", key=f"rec_e_{se_id}"):
                            cursor.execute("UPDATE solicitacoes SET status = 'RECUSADO' WHERE id = %s;", (se_id,))
                            conn.commit()
                            st.warning("Solicitação recusada.")
                            st.rerun()

    # =========================================================================
    # TELA: CADASTRAR PRODUTO (ADMIN)
    # =========================================================================
    elif escolha == "Cadastrar Produto" and eh_admin:
        st.subheader("Cadastrar Produto / Material no Almoxarifado")
        with st.form("form_cad_prod", clear_on_submit=True):
            col_p1, col_p2 = st.columns(2)
            codigo_prod = col_p1.text_input("Código do Produto*")
            item_prod = col_p2.text_input("Nome do Material / Item*")
            qtd_prod = col_p1.number_input("Quantidade Inicial*", min_value=0, value=0)
            cat_prod = col_p2.selectbox("Categoria*", lista_categorias if lista_categorias else ["Sem Categoria"])
            valor_prod = col_p1.number_input("Valor Unitário (R$)*", min_value=0.0, value=0.0, format="%.2f")

            if st.form_submit_button("Salvar Produto", type="primary"):
                if codigo_prod and item_prod:
                    try:
                        cursor.execute("INSERT INTO produtos VALUES (%s, %s, %s, %s, %s);", (codigo_prod.strip(), item_prod.strip(), qtd_prod, cat_prod, valor_prod))
                        conn.commit()
                        st.success("Produto cadastrado com sucesso!")
                        st.rerun()
                    except psycopg2.IntegrityError:
                        conn.rollback()
                        st.error("Já existe um produto com este código.")
                else:
                    st.error("Preencha todos os campos obrigatórios (*).")

    # =========================================================================
    # TELA: CADASTRAR CATEGORIA (ADMIN)
    # =========================================================================
    elif escolha == "Cadastrar Categoria" and eh_admin:
        st.subheader("Cadastrar Nova Categoria")
        with st.form("form_cad_cat", clear_on_submit=True):
            nome_cat = st.text_input("Nome da Categoria*")
            if st.form_submit_button("Salvar Categoria", type="primary"):
                if nome_cat.strip():
                    try:
                        cursor.execute("INSERT INTO categorias VALUES (%s);", (nome_cat.strip(),))
                        conn.commit()
                        st.success("Categoria salva!")
                        st.rerun()
                    except psycopg2.IntegrityError:
                        conn.rollback()
                        st.error("Esta categoria já existe.")

    # =========================================================================
    # TELA: CADASTRAR USUÁRIO (ADMIN)
    # =========================================================================
    elif escolha == "Cadastrar Usuário" and eh_admin:
        st.subheader("Cadastrar Novo Usuário no Sistema")
        with st.form("form_cad_user", clear_on_submit=True):
            u_nome = st.text_input("Nome Completo*")
            u_email = st.text_input("E-mail (Login)*")
            u_senha = st.text_input("Senha*", type="password")
            u_perfil = st.selectbox("Perfil de Acesso*", ["Usuário", "Administrador"])

            if st.form_submit_button("Salvar Usuário", type="primary"):
                if u_nome and u_email and u_senha:
                    try:
                        cursor.execute("INSERT INTO usuarios VALUES (%s, %s, %s, %s);", (u_nome.strip(), u_email.strip().lower(), u_senha.strip(), u_perfil))
                        conn.commit()
                        st.success("Usuário cadastrado com sucesso!")
                        st.rerun()
                    except psycopg2.IntegrityError:
                        conn.rollback()
                        st.error("E-mail já cadastrado.")

    # =========================================================================
    # TELA: CADASTRAR COORDENAÇÃO (ADMIN)
    # =========================================================================
    elif escolha == "Cadastrar Coordenação" and eh_admin:
        st.subheader("Cadastrar Coordenação / Setor")
        with st.form("form_cad_coord", clear_on_submit=True):
            col_c1, col_c2 = st.columns(2)
            c_sigla = col_c1.text_input("Sigla (ex: COTEC)*")
            c_nome = col_c2.text_input("Nome Completo da Coordenação*")

            if st.form_submit_button("Salvar Coordenação", type="primary"):
                if c_sigla and c_nome:
                    try:
                        cursor.execute("INSERT INTO coordenacoes VALUES (%s, %s);", (c_sigla.strip().upper(), c_nome.strip()))
                        conn.commit()
                        st.success("Coordenação cadastrada com sucesso!")
                        st.rerun()
                    except psycopg2.IntegrityError:
                        conn.rollback()
                        st.error("Esta sigla de coordenação já está cadastrada.")

    # =========================================================================
    # TELA: MOVIMENTAÇÃO DE ESTOQUE (ADMIN)
    # =========================================================================
    elif escolha == "Movimentação de Estoque" and eh_admin:
        st.subheader("Movimentação Direta de Estoque (Entrada / Saída)")
        if df_produtos.empty:
            st.warning("Cadastre produtos antes de realizar movimentações.")
        else:
            with st.form("form_movimentacao", clear_on_submit=True):
                opcoes_prod = {f"{r['Código']} - {r['Item']} (Qtd: {r['Quantidade']})": (r['Código'], r['Item'], r['Quantidade']) for _, r in df_produtos.iterrows()}
                p_selecionado = st.selectbox("Selecione o Produto*", list(opcoes_prod.keys()))
                p_cod, p_nome, p_qtd_atual = opcoes_prod[p_selecionado]

                col_m1, col_m2 = st.columns(2)
                m_tipo = col_m1.selectbox("Tipo de Movimentação*", ["ENTRADA", "SAIDA"])
                m_qtd = col_m2.number_input("Quantidade*", min_value=1, value=1)

                m_resp = col_m1.text_input("Responsável*", value=st.session_state.NOME_USUARIO_LOGADO)
                lista_siglas_coord = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["GERAL"]
                m_coord = col_m2.selectbox("Coordenação*", lista_siglas_coord)

                if st.form_submit_button("Registrar Movimentação", type="primary"):
                    if m_tipo == "SAIDA" and m_qtd > p_qtd_atual:
                        st.error("Quantidade de saída maior do que a disponível em estoque!")
                    else:
                        nova_qtd = p_qtd_atual + m_qtd if m_tipo == "ENTRADA" else p_qtd_atual - m_qtd
                        cursor.execute("UPDATE produtos SET quantidade = %s WHERE codigo = %s;", (nova_qtd, p_cod))
                        
                        data_hoje = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        cursor.execute("INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao) VALUES (%s, %s, %s, %s, %s, %s, %s);",
                                       (data_hoje, m_tipo, p_cod, p_nome, m_qtd, m_resp, m_coord))
                        conn.commit()
                        st.success("Movimentação registrada com sucesso!")
                        st.rerun()
