import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from streamlit_option_menu import option_menu

# =============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA E DIRETRIZES VISUAIS (CSS)
# =============================================================================
st.set_page_config(
    page_title="SISTEMA DE GESTÃO DE ALMOXARIFADO NGI CARAJÁS",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    <style>
    [data-testid="stSidebarNav"] {display: none;}
    [data-testid="stMainMenu"] {display: none;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    [data-testid="stSidebar"] {
        background-color: #f8fafc !important;
        border-right: 1px solid #e2e8f0;
    }
    
    div.stButton > button:first-child[kind="primary"] {
        background-color: #1e5934 !important;
        border-color: #1e5934 !important;
        color: white !important;
        border-radius: 6px;
        font-weight: 500;
    }
    .img-container {
        display: flex; justify-content: center; align-items: center;
        width: 100%; margin-bottom: 25px; background: white; padding: 15px; border-radius: 12px;
    }
    .metric-card {
        background: white; padding: 22px; border-radius: 10px;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
    }
    </style>
""", unsafe_allow_html=True)

# =============================================================================
# 2. SISTEMA DE ALERTA POR E-MAIL
# =============================================================================
try:
    EMAIL_REMETENTE = st.secrets["gmail"]["email"]
    SENHA_REMETENTE = st.secrets["gmail"]["senha_app"]
except:
    EMAIL_REMETENTE = "nao_configurado@ngi.com"
    SENHA_REMETENTE = "senha_nao_configurada"

def enviar_alerta_estoque_baixo(nome_item, qtd_atual, limite=5):
    if EMAIL_REMETENTE == "nao_configurado@ngi.com":
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_REMETENTE
        msg['To'] = EMAIL_REMETENTE  
        msg['Subject'] = f"⚠️ ALERTA: Estoque Crítico - {nome_item}"
        corpo = f"<h3>Aviso de Estoque Mínimo</h3><p>O item {nome_item} chegou a {qtd_atual} unidades.</p>"
        msg.attach(MIMEText(corpo, 'html'))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
        server.sendmail(EMAIL_REMETENTE, msg['To'], msg.as_string())
        server.quit()
        return True
    except:
        return False

# =============================================================================
# 3. CAMADA DO BANCO DE DADOS (COM CORREÇÃO AUTOMÁTICA)
# =============================================================================
def conectar_banco():
    return sqlite3.connect("almoxarifado.db", check_same_thread=False)

def inicializar_estrutura_banco():
    conn = conectar_banco()
    cursor = conn.cursor()
    
    # Cria a tabela de usuários caso ela não exista
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            nome TEXT NOT NULL,
            email TEXT PRIMARY KEY,
            senha TEXT NOT NULL,
            perfil TEXT NOT NULL,
            status TEXT DEFAULT 'Ativo'
        )
    """)
    
    # CORREÇÃO CRUCIAL: Adiciona a coluna status se o seu arquivo antigo não tiver
    try:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN status TEXT DEFAULT 'Ativo'")
    except sqlite3.OperationalError:
        pass  # Se a coluna já existia, ignora o erro e continua

    # Demais tabelas estruturais
    cursor.execute("CREATE TABLE IF NOT EXISTS categorias (nome TEXT PRIMARY KEY, descricao TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS coordenacoes (sigla TEXT PRIMARY KEY, nome TEXT NOT NULL, responsavel TEXT)")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            codigo TEXT PRIMARY KEY, item TEXT NOT NULL, quantidade INTEGER DEFAULT 0,
            categoria TEXT, valor_unitario REAL DEFAULT 0.0, estoque_minimo INTEGER DEFAULT 5, localizacao TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, tipo TEXT NOT NULL,
            codigo TEXT, item TEXT NOT NULL, quantidade INTEGER NOT NULL, responsavel TEXT NOT NULL,
            coordenacao TEXT, observacao TEXT, usuario_registro TEXT
        )
    """)
    
    # Cargas Iniciais (Seeders)
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO usuarios VALUES ('Administrador Master', 'admin@ngi.com', 'admin123', 'Administrador', 'Ativo')")
        
    cursor.execute("SELECT COUNT(*) FROM categorias")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("INSERT INTO categorias VALUES (?, ?)", [("EPI", "Proteção"), ("Material de Escritório", "Papelaria")])
        
    conn.commit()
    conn.close()

inicializar_estrutura_banco()

# =============================================================================
# 4. CONTROLE DE SESSÃO
# =============================================================================
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario_logado" not in st.session_state:
    st.session_state.usuario_logado = {}
if "tela_login" not in st.session_state:
    st.session_state.tela_login = "login"

# =============================================================================
# 5. FLUXO DE LOGIN / RECUPERAÇÃO
# =============================================================================
if not st.session_state.autenticado:
    if st.session_state.tela_login == "login":
        st.markdown("<br><br>", unsafe_allow_html=True)
        _, col_login, _ = st.columns([1, 1.3, 1])
        with col_login:
            st.markdown('<div class="img-container"><img src="https://www.gov.br/icmbio/pt-br/assuntos/biodiversidade/unidade-de-conservacao/unidades-de-biomas/marinho/lista-de-ucs/parna-marinho-dos-abrolhos/fomulario-denuncia/icmbio-logo-1.png" width="280"></div>', unsafe_allow_html=True)
            st.markdown("<h2 style='text-align: center; color: #1e5934; margin-top:-10px;'>Almoxarifado NGI Carajás</h2>", unsafe_allow_html=True)
            
            with st.container(border=True):
                email_input = st.text_input("E-mail Funcional")
                senha_input = st.text_input("Senha de Acesso", type="password")
                
                if st.button("Autenticar Sistema", type="primary", use_container_width=True):
                    conn = conectar_banco()
                    cursor = conn.cursor()
                    cursor.execute("SELECT nome, email, perfil, status, senha FROM usuarios WHERE LOWER(email) = ?", (email_input.strip().lower(),))
                    user_data = cursor.fetchone()
                    conn.close()
                    
                    if user_data and str(user_data[4]) == str(senha_input).strip():
                        if user_data[3] == "Inativo":
                            st.error("🔒 Usuário desativado.")
                        else:
                            st.session_state.autenticado = True
                            st.session_state.usuario_logado = {"nome": user_data[0], "email": user_data[1], "perfil": user_data[2]}
                            st.rerun()
                    else:
                        st.error("❌ Credenciais incorretas.")
                
                if st.button("Problemas com o acesso?", use_container_width=True):
                    st.session_state.tela_login = "recuperar"
                    st.rerun()
                    
    elif st.session_state.tela_login == "recuperar":
        st.markdown("<br><br>", unsafe_allow_html=True)
        _, col_rec, _ = st.columns([1, 1.2, 1])
        with col_rec:
            st.markdown("<h3 style='color: #1e5934;'>Suporte de Credenciais</h3>", unsafe_allow_html=True)
            st.info("Entre em contato com o setor de TI para resetar sua senha antiga.")
            if st.button("Voltar", use_container_width=True):
                st.session_state.tela_login = "login"
                st.rerun()

# =============================================================================
# 6. SISTEMA INTERNO PRINCIPAL (LOGADO)
# =============================================================================
else:
    conn = conectar_banco()
    df_produtos = pd.read_sql_query("SELECT * FROM produtos", conn)
    df_movimentacoes = pd.read_sql_query("SELECT * FROM movimentacoes ORDER BY id DESC", conn)
    df_coordenacoes = pd.read_sql_query("SELECT * FROM coordenacoes", conn)
    df_usuarios = pd.read_sql_query("SELECT nome, email, perfil, status FROM usuarios", conn)
    lista_categorias = pd.read_sql_query("SELECT nome FROM categorias", conn)["nome"].tolist()
    conn.close()

    with st.sidebar:
        st.markdown(f"**Operador:** {st.session_state.usuario_logado['nome']} ({st.session_state.usuario_logado['perfil']})")
        st.write("---")
        
        escolha = option_menu(
            menu_title=None,
            options=["Painel Geral", "Movimentação", "Cadastrar Produto", "Cadastrar Categoria", "Cadastrar Coordenação", "Gestão de Usuários", "Histórico & Auditoria", "Sair"],
            icons=["speedometer2", "arrow-left-right", "box-seam", "tags", "building-gear", "people", "journal-text", "door-open"],
            menu_icon="cast", default_index=0,
            styles={
                "container": {"background-color": "transparent"},
                "nav-link-selected": {"background-color": "#1e5934", "color": "white"}
            }
        )

    if escolha == "Sair":
        st.session_state.autenticado = False
        st.rerun()

    elif escolha == "Painel Geral":
        st.title("Dashboard Operacional")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Variedade de Itens", len(df_produtos))
        c2.metric("Volume Total", int(df_produtos['quantidade'].sum()) if not df_produtos.empty else 0)
        c3.metric("Atenção Crítica", len(df_produtos[df_produtos['quantidade'] <= df_produtos['estoque_minimo']]) if not df_produtos.empty else 0)
        c4.metric("Esgotados", len(df_produtos[df_produtos['quantidade'] == 0]) if not df_produtos.empty else 0)
        
        st.write("---")
        busca = st.text_input("🔍 Pesquisar no estoque")
        df_f = df_produtos[df_produtos['item'].str.contains(busca, case=False)] if busca else df_produtos
        st.dataframe(df_f, use_container_width=True, hide_index=True)

    elif escolha == "Movimentação":
        st.title("Fluxos de Movimentação")
        t1, t2 = st.tabs(["📥 Entrada", "📤 Saída"])
        
        with t1:
            if df_produtos.empty: st.warning("Cadastre produtos primeiro.")
            else:
                with st.form("form_ent"):
                    it = st.selectbox("Item", df_produtos['item'].tolist())
                    qt = st.number_input("Quantidade", min_value=1, value=1)
                    ob = st.text_input("Observação / Nota Fiscal")
                    if st.form_submit_button("Lançar Entrada", type="primary"):
                        cd = df_produtos[df_produtos['item'] == it]['codigo'].values[0]
                        conn = conectar_banco()
                        cursor = conn.cursor()
                        cursor.execute("UPDATE produtos SET quantidade = quantidade + ? WHERE codigo = ?", (qt, cd))
                        cursor.execute("INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao, observacao, usuario_registro) VALUES (?,?,?,?,?,?,?,?,?)",
                                       (datetime.now().strftime("%d/%m/%Y %H:%M"), "Entrada", cd, it, qt, "Fornecedor", "NGI", ob, st.session_state.usuario_logado['nome']))
                        conn.commit()
                        conn.close()
                        st.success("Entrada realizada!")
                        st.rerun()
                        
        with t2:
            if df_produtos.empty or df_coordenacoes.empty: st.warning("Cadastre produtos e coordenações antes.")
            else:
                with st.form("form_sai"):
                    it = st.selectbox("Item", df_produtos['item'].tolist())
                    qt = st.number_input("Quantidade", min_value=1, value=1)
                    sv = st.text_input("Servidor / Recebedor")
                    co = st.selectbox("Setor Destino", df_coordenacoes['sigla'].tolist())
                    ob = st.text_input("Finalidade")
                    if st.form_submit_button("Dispensar Item", type="primary"):
                        row = df_produtos[df_produtos['item'] == it].iloc[0]
                        if qt > row['quantidade']: st.error("Estoque insuficiente!")
                        else:
                            nv_est = row['quantidade'] - qt
                            conn = conectar_banco()
                            cursor = conn.cursor()
                            cursor.execute("UPDATE produtos SET quantidade = ? WHERE codigo = ?", (nv_est, row['codigo']))
                            cursor.execute("INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao, observacao, usuario_registro) VALUES (?,?,?,?,?,?,?,?,?)",
                                           (datetime.now().strftime("%d/%m/%Y %H:%M"), "Saída", row['codigo'], it, qt, sv, co, ob, st.session_state.usuario_logado['nome']))
                            conn.commit()
                            conn.close()
                            st.success("Saída registrada!")
                            if nv_est <= row['estoque_minimo']:
                                enviar_alerta_estoque_baixo(it, nv_est, row['estoque_minimo'])
                            st.rerun()

    elif escolha == "Cadastrar Produto":
        st.title("📦 Cadastro de Insumos")
        with st.form("form_prod"):
            c1, c2 = st.columns(2)
            cod = c1.text_input("Código SKU")
            itm = c2.text_input("Nome do Item")
            cat = c1.selectbox("Categoria", lista_categorias)
            val = c2.number_input("Preço Unitário", min_value=0.0)
            est = c1.number_input("Estoque Mínimo Alerta", min_value=0, value=5)
            loc = c2.text_input("Localização Física")
            if st.form_submit_button("Salvar Produto", type="primary"):
                if cod and itm:
                    conn = conectar_banco()
                    cursor = conn.cursor()
                    try:
                        cursor.execute("INSERT INTO produtos VALUES (?, ?, 0, ?, ?, ?, ?)", (cod.strip(), itm.strip(), cat, val, est, loc))
                        conn.commit()
                        st.success("Cadastrado com sucesso!")
                        st.rerun()
                    except sqlite3.IntegrityError: st.error("Código duplicado!")
                    finally: conn.close()

    elif escolha == "Cadastrar Categoria":
        st.title("🏷️ Categorias")
        with st.form("form_cat"):
            nm = st.text_input("Nome do Grupo")
            ds = st.text_area("Descrição")
            if st.form_submit_button("Criar Categoria"):
                if nm:
                    conn = conectar_banco()
                    cursor = conn.cursor()
                    try:
                        cursor.execute("INSERT INTO categorias VALUES (?, ?)", (nm.strip(), ds.strip()))
                        conn.commit()
                        st.rerun()
                    except sqlite3.IntegrityError: st.error("Já existe!")
                    finally: conn.close()
        st.dataframe(lista_categorias, use_container_width=True)

    elif escolha == "Cadastrar Coordenação":
        st.title("🏢 Organograma de Setores")
        with st.form("form_co"):
            sg = st.text_input("Sigla (Ex: COTEC)")
            nm = st.text_input("Nome Completo")
            rs = st.text_input("Responsável")
            if st.form_submit_button("Salvar Setor"):
                if sg and nm:
                    conn = conectar_banco()
                    cursor = conn.cursor()
                    try:
                        cursor.execute("INSERT INTO coordenacoes VALUES (?, ?, ?)", (sg.upper().strip(), nm.strip(), rs.strip()))
                        conn.commit()
                        st.rerun()
                    except sqlite3.IntegrityError: st.error("Sigla duplicada!")
                    finally: conn.close()
        st.dataframe(df_coordenacoes, use_container_width=True, hide_index=True)

    elif escolha == "Gestão de Usuários":
        st.title("👥 Controle de Acesso")
        if st.session_state.usuario_logado['perfil'] != "Administrador":
            st.error("Restrito a Administradores.")
        else:
            with st.form("form_user"):
                u_n = st.text_input("Nome Completo")
                u_e = st.text_input("E-mail Funcional")
                u_s = st.text_input("Senha", type="password")
                u_p = st.selectbox("Perfil", ["Usuário Comum", "Administrador"])
                if st.form_submit_button("Registrar Operador", type="primary"):
                    if u_n and u_e and u_s:
                        conn = conectar_banco()
                        cursor = conn.cursor()
                        try:
                            # CORREÇÃO DEFINITIVA DA SEU ERRO DAS IMAGENS: 5 valores exatos para as 5 colunas da tabela
                            cursor.execute("INSERT INTO usuarios (nome, email, senha, perfil, status) VALUES (?, ?, ?, ?, 'Ativo')",
                                           (u_n.strip(), u_e.lower().strip(), u_s.strip(), u_p))
                            conn.commit()
                            st.success("Usuário salvo!")
                            st.rerun()
                        except sqlite3.IntegrityError: st.error("E-mail já em uso.")
                        finally: conn.close()
            st.dataframe(df_usuarios, use_container_width=True, hide_index=True)

    elif escolha == "Histórico & Auditoria":
        st.title("📜 Logs e Auditoria")
        st.dataframe(df_movimentacoes, use_container_width=True, hide_index=True)
            else:
                st.dataframe(df_movimentacoes, use_container_width=True, hide_index=True)
