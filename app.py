import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sqlite3
import secrets  # Para geração de tokens seguros

# =============================================================================
# INICIALIZAÇÃO AUTOMÁTICA DO BANCO DE DADOS (SQLite)
# =============================================================================
def inicializar_banco_automatico():
    conn = sqlite3.connect("almoxarifado.db", check_same_thread=False)
    cursor = conn.cursor()
    
    # 1. Cria/Atualiza tabela de usuários (agora com colunas de token de recuperação)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            nome TEXT,
            email TEXT PRIMARY KEY,
            senha TEXT,
            perfil TEXT,
            token_recuperacao TEXT,
            token_expiracao TEXT
        )
    """)
    
    # Bloco de migração de segurança (Garante as colunas se o banco já existia antes)
    cursor.execute("PRAGMA table_info(usuarios)")
    colunas = [col[1] for col in cursor.fetchall()]
    if "token_recuperacao" not in colunas:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN token_recuperacao TEXT")
    if "token_expiracao" not in colunas:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN token_expiracao TEXT")
    
    # Garante o usuário Administrador padrão apenas se a tabela estiver vazia
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO usuarios (nome, email, senha, perfil, token_recuperacao, token_expiracao) 
            VALUES ('Administrador Padrão', 'admin@ngi.com', '123', 'Administrador', NULL, NULL)
        """)
        conn.commit()

    # 2. Cria tabela de produtos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            codigo TEXT PRIMARY KEY,
            item TEXT,
            quantidade INTEGER,
            categoria TEXT,
            valor_unitario REAL
        )
    """)
    
    cursor.execute("SELECT COUNT(*) FROM produtos")
    if cursor.fetchone()[0] == 0:
        produtos_iniciais = [
            ("001", "Capacete de Segurança", 15, "EPI", 45.00),
            ("002", "Resma Papel A4", 0, "Material de Escritório", 28.50),
            ("003", "Luva de Raspa", 50, "EPI", 12.00)
        ]
        cursor.executemany("INSERT INTO produtos VALUES (?, ?, ?, ?, ?)", produtos_iniciais)
        conn.commit()

    # 3. Cria tabela de coordenações
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS coordenacoes (
            sigla TEXT PRIMARY KEY,
            nome TEXT
        )
    """)
    
    cursor.execute("SELECT COUNT(*) FROM coordenacoes")
    if cursor.fetchone()[0] == 0:
        coord_iniciais = [
            ("COTEC", "Coordenação Técnica"),
            ("COLOG", "Coordenação de Logística")
        ]
        cursor.executemany("INSERT INTO coordenacoes VALUES (?, ?)", coord_iniciais)
        conn.commit()

    # 4. Cria tabela de categorias
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

    # 5. Cria tabela de movimentações
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

# --- ESTILIZAÇÃO CSS (Com suporte total ao fechar/abrir no celular) ---
st.markdown("""
    <style>
    @media (max-width: 991px) {
        [data-testid="stSidebar"] {
            min-width: 260px !important;
            max-width: 260px !important;
        }
        [data-testid="stAppViewBlockContainer"] {
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            width: 100% !important;
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
# DETECÇÃO E CAPTURA DE TOKENS VIA URL (Query Parameters)
# =============================================================================
query_params = st.query_params
token_url = query_params.get("token")

if token_url and not st.session_state.autenticado:
    st.session_state.sub_tela_login = "redefinir_senha"

# =============================================================================
# FLUXO 1: FLUXO DE LOGIN E RECUPERAÇÃO
# =============================================================================
if not st.session_state.autenticado:
    
    # --- SUB-TELA: LOGIN TRADICIONAL ---
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

    # --- SUB-TELA: SOLICITAR RECUPERAÇÃO (GERAR LINK) ---
    elif st.session_state.sub_tela_login == "esqueci":
        col_r1, col_r2, col_r3 = st.columns([1, 1.2, 1])
        with col_r2:
            st.write("<br><br>", unsafe_allow_html=True)
            st.markdown("### 🔑 Recuperar Acesso")
            email_recuperar = st.text_input("E-mail corporativo", placeholder="exemplo@icmbio.gov.br")

            if st.button("Enviar Link de Redefinição", type="primary", use_container_width=True):
                if email_recuperar.strip():
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM usuarios WHERE LOWER(email) = ?", (email_recuperar.strip().lower(),))
                    
                    if cursor.fetchone()[0] > 0:
                        if EMAIL_REMETENTE == "configurar_no_secrets@email.com":
                            st.error("Erro de configuração nos Secrets do Streamlit.")
                        else:
                            try:
                                # Gerar token seguro de 32 caracteres e expiração para 1 hora
                                token = secrets.token_urlsafe(32)
                                expiracao = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
                                
                                # Gravar dados temporários no usuário correspondente
                                cursor.execute("""
                                    UPDATE usuarios 
                                    SET token_recuperacao = ?, token_expiracao = ? 
                                    WHERE LOWER(email) = ?
                                """, (token, expiracao, email_recuperar.strip().lower()))
                                conn.commit()
                                
                                # Detectar a URL de origem do sistema rodando
                                try:
                                    url_base = st.get_option("browser.serverAddress")
                                except:
                                    url_base = "localhost:8501" # Fallback local padrao
                                
                                # Monta o link dinâmico para redefinição
                                link_redefinicao = f"http://{url_base}/?token={token}"
                                
                                msg = MIMEMultipart()
                                msg['From'] = EMAIL_REMETENTE
                                msg['To'] = email_recuperar.strip()
                                msg['Subject'] = "Redefinição de Senha - Almoxarifado NGI Carajás"
                                
                                corpo_email = f"""Olá,

Uma solicitação de redefinição de senha foi feita para sua conta no Sistema de Almoxarifado NGI Carajás.

Para criar uma nova senha, clique ou copie o link abaixo:
{link_redefinicao}

Este link é válido por 1 hora. Se você não solicitou essa mudança, ignore este e-mail.
"""
                                msg.attach(MIMEText(corpo_email, 'plain'))
                                
                                server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
                                server.starttls()
                                server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
                                server.sendmail(EMAIL_REMETENTE, email_recuperar.strip(), msg.as_string())
                                server.quit()
                                
                                st.success(f"Sucesso! Link enviado para {email_recuperar}")
                            except Exception as e:
                                st.error(f"Erro ao tentar enviar o e-mail: {e}")
                    else:
                        st.error("Este e-mail não foi encontrado no sistema.")
                else:
                    st.warning("Por favor, digite um e-mail válido.")
            
            if st.button("Voltar para o Login", use_container_width=True):
                st.session_state.sub_tela_login = "login"
                st.rerun()

    # --- SUB-TELA: ENTRADA VIA LINK (FORMULÁRIO DE NOVA SENHA) ---
    elif st.session_state.sub_tela_login == "redefinir_senha":
        col_rf1, col_rf2, col_rf3 = st.columns([1, 1.2, 1])
        with col_rf2:
            st.write("<br><br>", unsafe_allow_html=True)
            st.markdown("### 🔄 Criar Nova Senha")
            
            cursor = conn.cursor()
            cursor.execute("SELECT email, token_expiracao FROM usuarios WHERE token_recuperacao = ?", (token_url,))
            dados_token = cursor.fetchone()
            
            if dados_token:
                email_usuario, data_expiracao_str = dados_token
                data_expiracao = datetime.strptime(data_expiracao_str, "%Y-%m-%d %H:%M:%S")
                
                # Valida se o link ainda está dentro do prazo de validade de 1h
                if datetime.now() < data_expiracao:
                    nova_senha = st.text_input("Nova Senha:", type="password")
                    confirmar_senha = st.text_input("Confirme a Nova Senha:", type="password")
                    
                    if st.button("Salvar Nova Senha", type="primary", use_container_width=True):
                        if not nova_senha:
                            st.error("O campo de senha não pode ficar em branco.")
                        elif nova_senha != confirmar_senha:
                            st.error("As senhas digitadas não conferem!")
                        else:
                            # Atualiza para a nova senha e destrói o token para não ser reusado
                            cursor.execute("""
                                UPDATE usuarios 
                                SET senha = ?, token_recuperacao = NULL, token_expiracao = NULL 
                                WHERE email = ?
                            """, (nova_senha.strip(), email_usuario))
                            conn.commit()
                            
                            # Limpa os query parameters da URL visual do navegador
                            st.query_params.clear()
                            
                            st.success("Senha atualizada com sucesso!")
                            st.session_state.sub_tela_login = "login"
                            st.rerun()
                else:
                    st.error("❌ Este link de redefinição expirou! Solicite um novo link.")
                    if st.button("Solicitar Novo Link", use_container_width=True):
                        st.query_params.clear()
                        st.session_state.sub_tela_login = "esqueci"
                        st.rerun()
            else:
                st.error("❌ Link inválido ou token de redefinição já utilizado.")
                if st.button("Ir para o Login", use_container_width=True):
                    st.query_params.clear()
                    st.session_state.sub_tela_login = "login"
                    st.rerun()

# =============================================================================
# FLUXO 2: SISTEMA PRINCIPAL (PÓS-AUTENTICAÇÃO)
# =============================================================================
else:
    df_produtos = pd.read_sql_query("SELECT codigo AS Código, item AS Item, quantidade AS Quantidade, categoria AS Categoria, valor_unitario AS [Valor Unitário] FROM produtos", conn)
    df_movimentacoes = pd.read_sql_query("SELECT data AS Data, tipo AS Tipo, codigo AS Código, item AS Item, quantidade AS Quantidade, responsavel AS [Responsável pela Retirada], coordenacao AS [Coordenação] FROM movimentacoes", conn)
    df_coordenacoes = pd.read_sql_query("SELECT sigla AS Sigla, nome AS Nome FROM coordenacoes", conn)
    
    df_cat_bruto = pd.read_sql_query("SELECT nome FROM categorias", conn)
    lista_categories = df_cat_bruto["nome"].tolist()

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
            "👤 Perfil",
            "🚪 Sair"
        ]
        escolha = st.radio("", menu_opcoes, label_visibility="collapsed")

    # --- Sair do Sistema ---
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
        categoria_selecionada = col_filtro2.selectbox("Filtrar por Categoria:", ["Todas"] + lista_categories)
        
        df_filtrado = df_produtos.copy()
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

    # --- TELA: CADASTRAR PRODUTO ---
    elif escolha == "➕ Cadastrar Produto":
        st.title("➕ Gerenciamento de Produtos")
        aba_cad_prod, aba_gerenciar_prod = st.tabs(["➕ Novo Material", "✏️ Editar / Excluir Produtos"])
        
        with aba_cad_prod:
            with st.form("form_novo_produto", clear_on_submit=True):
                col_a, col_b = st.columns(2)
                cod = col_a.text_input("Código")
                nome_it = col_b.text_input("Nome do Material")
                cat_it = col_a.selectbox("Categoria", lista_categories)
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
                idx_cat_padrao = lista_categories.index(cat_atual) if cat_atual in lista_categories else 0
                edit_cat = col_ed2.selectbox("Categoria:", lista_categories, index=idx_cat_padrao)
                edit_val = st.number_input("Valor Unitário:", min_value=0.0, step=0.01, format="%.2f", value=float(df_raw_prod.loc[opcao_selecionada, "valor_unitario"]))
                
                col_b_prod1, col_b_prod2 = st.columns([1, 4])
                with col_b_prod1:
                    if st.button("Salvar Alterações", type="primary"):
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE produtos 
                            SET codigo = ?, item = ?, quantidade = ?, categoria = ?, valor_unitario = ? 
                            WHERE codigo = ?
                        """, (edit_cod.
