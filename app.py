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

# Função utilitária para exclusão segura de itens de empréstimo
def excluir_item_emprestimo(item_id):
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM emprestimo_registros WHERE item_id = %s;", (item_id,))
        cur.execute("DELETE FROM emprestimo_itens WHERE id = %s;", (item_id,))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        st.error(f"Erro ao excluir item: {e}")
        return False

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
            Módulo independente de empréstimos, controle de empréstimo de material, devoluções e histórico de movimentações
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
        # SUB-ABA 1: ITENS DISPONÍVEIS (PAINEL + AÇÃO DE EXCLUSÃO)
        # ---------------------------------------------------------------------
        if sub_emp == "Itens Disponíveis":
            st.subheader(" Painel de Disponibilidade de Empréstimos")
            
            cursor.execute("""
                SELECT 
                    id,
                    codigo, 
                    item, 
                    quantidade_total, 
                    quantidade_disponivel,
                    (quantidade_total - quantidade_disponivel) AS emprestados,
                    observacao
                FROM emprestimo_itens ORDER BY item ASC;
            """)
            itens_bruto = cursor.fetchall()

            if not itens_bruto:
                st.info("Nenhum item cadastrado no catálogo exclusivo de empréstimos ainda.")
            else:
                df_emp_itens = pd.DataFrame(itens_bruto, columns=["ID", "Código", "Item / Equipamento", "Qtd Total", "Qtd Disponível", "Emprestados", "Observações"])
                st.dataframe(df_emp_itens.drop(columns=["ID"]), use_container_width=True, hide_index=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                with st.expander("🗑️ Excluir um Item Cadastrado para Empréstimo", expanded=False):
                    opcoes_exclusao = {f"{r['Item / Equipamento']} (Código: {r['Código'] or 'S/C'})": r['ID'] for _, r in df_emp_itens.iterrows()}
                    item_selecionado_del = st.selectbox("Selecione o item que deseja remover permanentemente:", list(opcoes_exclusao.keys()))
                    
                    if st.button("Confirmar Exclusão do Item", type="primary"):
                        id_para_excluir = opcoes_exclusao[item_selecionado_del]
                        if excluir_item_emprestimo(id_para_excluir):
                            st.success("Item e seus registros vinculados foram excluídos com sucesso!")
                            st.rerun()

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
                    item_nome AS "Item",
                    quantidade AS "Qtd",
                    pessoa AS "Solicitante",
                    coordenacao AS "Coordenação",
                    TO_CHAR(data_retirada, 'DD/MM/YYYY') AS "Retirada",
                    TO_CHAR(data_prevista, 'DD/MM/YYYY') AS "Previsão Devolução",
                    TO_CHAR(data_devolucao, 'DD/MM/YYYY') AS "Data Devolução",
                    status AS "Status",
                    responsavel_devolucao AS "Devolvido Por"
                FROM emprestimo_registros 
                ORDER BY id DESC;
            """, conn)

            if df_hist_emp.empty:
                st.info("Nenhuma movimentação de empréstimo registrada até o momento.")
            else:
                st.dataframe(df_hist_emp, use_container_width=True, hide_index=True)
