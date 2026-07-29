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
import base64

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

    # =========================================================================
    # TABELAS PARA O MÓDULO DE EMPRÉSTIMOS (COM SUPORTE A IMAGEM)
    # =========================================================================
    # 6. Tabela de Itens de Empréstimo
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emprestimo_itens (
            id SERIAL PRIMARY KEY,
            codigo TEXT UNIQUE,
            item TEXT NOT NULL,
            quantidade_total INTEGER NOT NULL DEFAULT 1,
            quantidade_disponivel INTEGER NOT NULL DEFAULT 1,
            observacao TEXT,
            imagem TEXT
        );
    """)

    # Garante que a coluna 'imagem' exista se a tabela já tiver sido criada antes
    cursor.execute("""
        ALTER TABLE emprestimo_itens ADD COLUMN IF NOT EXISTS imagem TEXT;
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

    conn.commit()

    # Verifica se a carga inicial (seed) já foi realizada no passado
    cursor.execute("SELECT valor FROM config_sistema WHERE chave = 'seed_inicial';")
    seed_realizado = cursor.fetchone()

    if not seed_realizado:
        # Inserção inicial de Usuários
        cursor.execute("SELECT COUNT(*) FROM usuarios;")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO usuarios (nome, email, senha, perfil) 
                VALUES ('Administrador Padrão', 'admin@ngi.com', '123', 'Administrador');
            """)

        # Inserção inicial de Produtos
        cursor.execute("SELECT COUNT(*) FROM produtos;")
        if cursor.fetchone()[0] == 0:
            produtos_iniciais = [
                ("001", "Capacete de Segurança", 15, "EPI", 45.00),
                ("002", "Resma Papel A4", 0, "Material de Escritório", 28.50),
                ("003", "Luva de Raspa", 50, "EPI", 12.00)
            ]
            cursor.executemany("INSERT INTO produtos VALUES (%s, %s, %s, %s, %s);", produtos_iniciais)

        # Inserção inicial de Coordenações
        cursor.execute("SELECT COUNT(*) FROM coordenacoes;")
        if cursor.fetchone()[0] == 0:
            cursor.executemany("INSERT INTO coordenacoes VALUES (%s, %s);", [
                ("COTEC", "Coordenação Técnica"),
                ("COLOG", "Coordenação de Logística")
            ])

        # Inserção inicial de Categorias
        cursor.execute("SELECT COUNT(*) FROM categorias;")
        if cursor.fetchone()[0] == 0:
            cat_iniciais = [("EPI",), ("Material de Escritório",), ("Informática",), ("Limpeza",), ("Copa",)]
            cursor.executemany("INSERT INTO categorias VALUES (%s);", cat_iniciais)

        cursor.execute("INSERT INTO config_sistema (chave, valor) VALUES ('seed_inicial', 'true');")
        conn.commit()
    
    return conn

conn = inicializar_banco_automatico()

# Carregamento de dados
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

# Configurações de E-mail
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
    with st.sidebar:
        st.markdown(f"#### Olá, {st.session_state.NOME_USUARIO_LOGADO}")
        st.write("---")
        
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
                "Sair do Sistema"
            ],
            icons=["grid", "arrow-repeat", "box", "folder", "person-plus", "building", "arrow-left-right", "box-arrow-right"],
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

        st.markdown("<br><h3 style='font-size: 18px; font-weight: 600; margin-bottom: 12px;'>Posição Atual do Estoque</h3>", unsafe_allow_html=True)
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
        # SUB-ABA 1: ITENS DISPONÍVEIS (PAINEL COM EXIBIÇÃO DE FOTO)
        # ---------------------------------------------------------------------
        if sub_emp == "Itens Disponíveis":
            st.subheader("Painel de Disponibilidade de Empréstimos")
            
            df_emp_itens = pd.read_sql_query("""
                SELECT 
                    imagem AS "Foto",
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
                st.dataframe(
                    df_emp_itens, 
                    column_config={
                        "Foto": st.column_config.ImageColumn("Foto", help="Foto do equipamento")
                    },
                    use_container_width=True, 
                    hide_index=True
                )

        # ---------------------------------------------------------------------
        # SUB-ABA 2: CADASTRAR ITEM (COM UPLOAD DE FOTO)
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
                
                # Upload da imagem/foto do equipamento
                foto_upload = st.file_uploader("Foto / Ícone do Equipamento", type=["png", "jpg", "jpeg", "webp"])

                if st.form_submit_button("Cadastrar Item", type="primary"):
                    if item_emp.strip():
                        imagem_base64 = None
                        if foto_upload is not None:
                            bytes_data = foto_upload.getvalue()
                            b64_str = base64.b64encode(bytes_data).decode()
                            mime_type = foto_upload.type
                            imagem_base64 = f"data:{mime_type};base64,{b64_str}"

                        try:
                            cursor.execute("""
                                INSERT INTO emprestimo_itens (codigo, item, quantidade_total, quantidade_disponivel, observacao, imagem)
                                VALUES (%s, %s, %s, %s, %s, %s);
                            """, (cod_emp.strip() if cod_emp else None, item_emp.strip(), qtd_total, qtd_total, obs_emp.strip(), imagem_base64))
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
                    COALESCE(to_char(data_devolucao, 'DD/MM/YYYY'), '-') AS "Data Devolução",
                    status AS "Status",
                    COALESCE(responsavel_devolucao, '-') AS "Devolvido Por"
                FROM emprestimo_registros 
                ORDER BY id DESC;
            """, conn)

            if df_hist_emp.empty:
                st.info("Nenhuma movimentação de empréstimo registrada até o momento.")
            else:
                st.dataframe(df_hist_emp, use_container_width=True, hide_index=True)

    # -------------------------------------------------------------------------
    # RESTANTE DAS TELAS MANIFESTADAS PELO MENU (Cadastros e Movimentações)
    # -------------------------------------------------------------------------
    elif escolha == "Cadastrar Produto":
        st.subheader("Cadastrar Novo Produto (Almoxarifado)")
        with st.form("form_produto", clear_on_submit=True):
            col_p1, col_p2 = st.columns(2)
            cod_prod = col_p1.text_input("Código do Produto*")
            nome_prod = col_p2.text_input("Nome do Produto*")
            qtd_prod = col_p1.number_input("Quantidade Inicial*", min_value=0, value=0, step=1)
            cat_prod = col_p2.selectbox("Categoria*", lista_categorias if lista_categorias else ["Sem Categoria"])
            val_prod = col_p1.number_input("Valor Unitário (R$)*", min_value=0.0, value=0.0, step=0.10, format="%.2f")

            if st.form_submit_button("Salvar Produto", type="primary"):
                if cod_prod.strip() and nome_prod.strip():
                    try:
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO produtos VALUES (%s, %s, %s, %s, %s);", (cod_prod.strip(), nome_prod.strip(), qtd_prod, cat_prod, val_prod))
                        conn.commit()
                        st.success(f"Produto '{nome_prod}' cadastrado com sucesso!")
                        st.rerun()
                    except psycopg2.IntegrityError:
                        conn.rollback()
                        st.error("Já existe um produto com este código.")
                else:
                    st.error("Preencha os campos obrigatórios (*)")

    elif escolha == "Cadastrar Categoria":
        st.subheader("Cadastrar Nova Categoria")
        with st.form("form_cat", clear_on_submit=True):
            nova_cat = st.text_input("Nome da Categoria*")
            if st.form_submit_button("Salvar Categoria", type="primary"):
                if nova_cat.strip():
                    try:
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO categorias VALUES (%s);", (nova_cat.strip(),))
                        conn.commit()
                        st.success("Categoria inserida com sucesso!")
                        st.rerun()
                    except psycopg2.IntegrityError:
                        conn.rollback()
                        st.error("Categoria já cadastrada.")

    elif escolha == "Cadastrar Usuário":
        st.subheader("Cadastrar Novo Usuário do Sistema")
        with st.form("form_usr", clear_on_submit=True):
            col_u1, col_u2 = st.columns(2)
            nome_u = col_u1.text_input("Nome Completo*")
            email_u = col_u2.text_input("E-mail*")
            senha_u = col_u1.text_input("Senha*", type="password")
            perfil_u = col_u2.selectbox("Perfil*", ["Operador", "Administrador"])

            if st.form_submit_button("Salvar Usuário", type="primary"):
                if email_u.strip() and senha_u.strip():
                    try:
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO usuarios VALUES (%s, %s, %s, %s);", (nome_u.strip(), email_u.strip().lower(), senha_u.strip(), perfil_u))
                        conn.commit()
                        st.success("Usuário cadastrado com sucesso!")
                    except psycopg2.IntegrityError:
                        conn.rollback()
                        st.error("Este e-mail já está cadastrado.")

    elif escolha == "Cadastrar Coordenação":
        st.subheader("Cadastrar Nova Coordenação")
        with st.form("form_coord", clear_on_submit=True):
            col_c1, col_c2 = st.columns(2)
            sigla_c = col_c1.text_input("Sigla* (Ex: COTEC)")
            nome_c = col_c2.text_input("Nome Completo da Coordenação*")

            if st.form_submit_button("Salvar Coordenação", type="primary"):
                if sigla_c.strip() and nome_c.strip():
                    try:
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO coordenacoes VALUES (%s, %s);", (sigla_c.strip().upper(), nome_c.strip()))
                        conn.commit()
                        st.success("Coordenação salva!")
                        st.rerun()
                    except psycopg2.IntegrityError:
                        conn.rollback()
                        st.error("Sigla de coordenação já cadastrada.")

    elif escolha == "Movimentação de Estoque":
        st.subheader("Registrar Entrada / Saída de Estoque (Geral)")
        if df_produtos.empty:
            st.warning("Cadastre produtos antes de realizar movimentações.")
        else:
            dict_prods = {f"{row['Código']} - {row['Item']}": row['Código'] for _, row in df_produtos.iterrows()}
            with st.form("form_mov", clear_on_submit=True):
                prod_sel = st.selectbox("Selecione o Produto*", list(dict_prods.keys()))
                tipo_m = st.radio("Tipo de Movimentação*", ["Entrada", "Saída"], horizontal=True)
                qtd_m = st.number_input("Quantidade*", min_value=1, value=1, step=1)
                resp_m = st.text_input("Responsável*", value=st.session_state.NOME_USUARIO_LOGADO)
                coord_m = st.selectbox("Coordenação Destino/Origem*", df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["GERAL"])

                if st.form_submit_button("Confirmar Movimentação", type="primary"):
                    cod_p = dict_prods[prod_sel]
                    cursor = conn.cursor()
                    cursor.execute("SELECT quantidade, item FROM produtos WHERE codigo = %s;", (cod_p,))
                    qtd_atual, nome_item = cursor.fetchone()

                    if tipo_m == "Saída" and qtd_m > qtd_atual:
                        st.error("Saldo insuficiente para realizar esta saída!")
                    else:
                        nova_qtd = (qtd_atual + qtd_m) if tipo_m == "Entrada" else (qtd_atual - qtd_m)
                        cursor.execute("UPDATE produtos SET quantidade = %s WHERE codigo = %s;", (nova_qtd, cod_p))
                        cursor.execute("""
                            INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao)
                            VALUES (%s, %s, %s, %s, %s, %s, %s);
                        """, (datetime.now().strftime("%d/%m/%Y %H:%M"), tipo_m, cod_p, nome_item, qtd_m, resp_m.strip(), coord_m))
                        conn.commit()
                        st.success(f"Movimentação de {tipo_m} efetuada com sucesso!")
                        st.rerun()
