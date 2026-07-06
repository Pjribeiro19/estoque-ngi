import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
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

# Injeção de CSS para ocultar menus nativos e estilizar componentes
st.markdown("""
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    <style>
    /* Ocultar navegação padrão do Streamlit */
    [data-testid="stSidebarNav"] {display: none;}
    [data-testid="stMainMenu"] {display: none;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Estilização do Sidebar */
    [data-testid="stSidebar"] {
        background-color: #f8fafc !important;
        border-right: 1px solid #e2e8f0;
    }
    
    /* Botões Principais */
    div.stButton > button:first-child[kind="primary"] {
        background-color: #1e5934 !important;
        border-color: #1e5934 !important;
        color: white !important;
        border-radius: 6px;
        font-weight: 500;
        transition: all 0.2s;
    }
    div.stButton > button:first-child[kind="primary"]:hover {
        background-color: #143d23 !important;
        border-color: #143d23 !important;
        transform: translateY(-1px);
    }
    
    /* Container do Logotipo */
    .img-container {
        display: flex;
        justify-content: center;
        align-items: center;
        width: 100%;
        margin-bottom: 25px;
        background: white;
        padding: 15px;
        border-radius: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    
    /* Customização de Tabelas e Cards */
    .metric-card {
        background: white;
        padding: 22px;
        border-radius: 10px;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05), 0 2px 4px -1px rgba(0,0,0,0.03);
        transition: transform 0.2s;
    }
    .metric-card:hover {
        transform: translateY(-2px);
    }
    </style>
""", unsafe_allow_html=True)

# =============================================================================
# 2. SEGREDO E SISTEMA DE NOTIFICAÇÕES (E-MAIL)
# =============================================================================
try:
    EMAIL_REMETENTE = st.secrets["gmail"]["email"]
    SENHA_REMETENTE = st.secrets["gmail"]["senha_app"]
except:
    EMAIL_REMETENTE = "nao_configurado@ngi.com"
    SENHA_REMETENTE = "senha_nao_configurada"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORTA = 587

def enviar_alerta_estoque_baixo(nome_item, qtd_atual, limite=5):
    if EMAIL_REMETENTE == "nao_configurado@ngi.com":
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_REMETENTE
        msg['To'] = EMAIL_REMETENTE  # Envia para o próprio gestor cadastrado
        msg['Subject'] = f"⚠️ ALERTA: Estoque Crítico - {nome_item}"
        
        corpo = f"""
        <html>
        <body>
            <h2 style="color: #dc2626;">Aviso de Estoque Mínimo Atingido</h2>
            <p>O seguinte item atingiu o nível de atenção no Almoxarifado NGI Carajás:</p>
            <table border="1" cellpadding="5" style="border-collapse: collapse;">
                <tr bgcolor="#f2f2f2"><th>Item</th><th>Quantidade Atual</th><th>Status</th></tr>
                <tr><td>{nome_item}</td><td>{qtd_atual}</td><td style="color: red; font-weight:bold;">Crítico (Abaixo de {limite})</td></tr>
            </table>
            <br>
            <p><i>Este é um disparo automático do sistema de gestão. Por favor, providencie a reposição.</i></p>
        </body>
        </html>
        """
        msg.attach(MIMEText(corpo, 'html'))
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
        server.starttls()
        server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
        server.sendmail(EMAIL_REMETENTE, msg['To'], msg.as_string())
        server.quit()
        return True
    except:
        return False

# =============================================================================
# 3. CAMADA DE PERSISTÊNCIA (BANCO DE DADOS SQLITE)
# =============================================================================
def conectar_banco():
    conn = sqlite3.connect("almoxarifado.db", check_same_thread=False)
    return conn

def inicializar_estrutura_banco():
    conn = conectar_banco()
    cursor = conn.cursor()
    
    # Tabela de Usuários
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            nome TEXT NOT NULL,
            email TEXT PRIMARY KEY,
            senha TEXT NOT NULL,
            perfil TEXT NOT NULL,
            status TEXT DEFAULT 'Ativo'
        )
    """)
    
    # Tabela de Categorias
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            nome TEXT PRIMARY KEY,
            descricao TEXT
        )
    """)
    
    # Tabela de Coordenações/Setores
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS coordenacoes (
            sigla TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            responsavel TEXT
        )
    """)
    
    # Tabela de Produtos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            codigo TEXT PRIMARY KEY,
            item TEXT NOT NULL,
            quantidade INTEGER DEFAULT 0,
            categoria TEXT,
            valor_unitario REAL DEFAULT 0.0,
            estoque_minimo INTEGER DEFAULT 5,
            localizacao TEXT,
            FOREIGN KEY(categoria) REFERENCES categorias(nome)
        )
    """)
    
    # Tabela de Movimentações
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            tipo TEXT NOT NULL,
            codigo TEXT,
            item TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            responsavel TEXT NOT NULL,
            coordenacao TEXT,
            observacao TEXT,
            usuario_registro TEXT
        )
    """)
    
    # Carga Inicial de Dados (Seeders)
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO usuarios (nome, email, senha, perfil, status) 
            VALUES ('Administrador Master', 'admin@ngi.com', 'admin123', 'Administrador', 'Ativo')
        """)
        
    cursor.execute("SELECT COUNT(*) FROM categorias")
    if cursor.fetchone()[0] == 0:
        categorias_padrao = [
            ("EPI", "Equipamentos de Proteção Individual"),
            ("Material de Escritório", "Papelaria e suprimentos administrativos"),
            ("Informática", "Mouses, teclados, cabos e suprimentos tecnológicos"),
            ("Limpeza", "Materiais de higienização de ambientes"),
            ("Copa", "Insumos para cozinha e alimentação")
        ]
        cursor.executemany("INSERT INTO categorias VALUES (?, ?)", categorias_padrao)
        
    cursor.execute("SELECT COUNT(*) FROM coordenacoes")
    if cursor.fetchone()[0] == 0:
        coordenacoes_padrao = [
            ("COTEC", "Coordenação Técnica", "João Silva"),
            ("COLOG", "Coordenação de Logística", "Maria Oliveira"),
            ("COMAN", "Coordenação de Manejo", "Carlos Souza"),
            ("GABIN", "Gabinete de Direção", "Ana Costa")
        ]
        cursor.executemany("INSERT INTO coordenacoes VALUES (?, ?, ?)", coordenacoes_padrao)

    cursor.execute("SELECT COUNT(*) FROM produtos")
    if cursor.fetchone()[0] == 0:
        produtos_padrao = [
            ("001", "Capacete de Segurança Com Carneira", 25, "EPI", 48.90, 5, "Prateleira A1"),
            ("002", "Resma de Papel A4 Chamex 75g", 40, "Material de Escritório", 32.00, 10, "Armário B2"),
            ("003", "Mouse Sem Fio Logitech M280", 12, "Informática", 79.90, 3, "Gaveta C1"),
            ("004", "Luva de Raspa Cano Longo", 0, "EPI", 18.50, 8, "Prateleira A3")
        ]
        cursor.executemany("INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?, ?)", produtos_padrao)
        
    conn.commit()
    conn.close()

# Inicializa o banco de dados antes da aplicação rodar
inicializar_estrutura_banco()

# =============================================================================
# 4. GERENCIAMENTO DE ESTADO DA SESSÃO (SESSION STATE)
# =============================================================================
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario_logado" not in st.session_state:
    st.session_state.usuario_logado = {}
if "tela_login" not in st.session_state:
    st.session_state.tela_login = "login"

# =============================================================================
# 5. MÓDULO DE AUTENTICAÇÃO (INTERFACES DE LOGIN)
# =============================================================================
if not st.session_state.autenticado:
    if st.session_state.tela_login == "login":
        st.markdown("<br><br>", unsafe_allow_html=True)
        _, col_login, _ = st.columns([1, 1.3, 1])
        
        with col_login:
            st.markdown('<div class="img-container"><img src="https://www.gov.br/icmbio/pt-br/assuntos/biodiversidade/unidade-de-conservacao/unidades-de-biomas/marinho/lista-de-ucs/parna-marinho-dos-abrolhos/fomulario-denuncia/icmbio-logo-1.png" width="280"></div>', unsafe_allow_html=True)
            st.markdown("<h2 style='text-align: center; color: #1e5934; margin-top:-10px;'>Almoxarifado NGI Carajás</h2>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; color: #64748b;'>Insira suas credenciais para acessar o painel administrativo</p>", unsafe_allow_html=True)
            
            with st.container(border=True):
                email_input = st.text_input("E-mail Funcional", placeholder="exemplo@ngi.com")
                senha_input = st.text_input("Senha de Acesso", type="password", placeholder="••••••••")
                
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Autenticar Sistema", type="primary", use_container_width=True):
                    conn = conectar_banco()
                    cursor = conn.cursor()
                    cursor.execute("SELECT nome, email, perfil, status, senha FROM usuarios WHERE LOWER(email) = ?", (email_input.strip().lower(),))
                    user_data = cursor.fetchone()
                    conn.close()
                    
                    if user_data and str(user_data[4]) == str(senha_input).strip():
                        if user_data[3] == "Inativo":
                            st.error("🔒 Este usuário foi desativado. Entre em contato com o administrador.")
                        else:
                            st.session_state.autenticado = True
                            st.session_state.usuario_logado = {
                                "nome": user_data[0],
                                "email": user_data[1],
                                "perfil": user_data[2]
                            }
                            st.toast(f"Bem-vindo de volta, {user_data[0]}!", icon="🌿")
                            st.rerun()
                    else:
                        st.error("❌ Credenciais de acesso incorretas ou inexistentes.")
                        
                if st.button("Problemas com o acesso?", use_container_width=True):
                    st.session_state.tela_login = "recuperar"
                    st.rerun()
                    
    elif st.session_state.tela_login == "recuperar":
        st.markdown("<br><br>", unsafe_allow_html=True)
        _, col_rec, _ = st.columns([1, 1.2, 1])
        with col_rec:
            st.markdown("<h3 style='color: #1e5934;'>Recuperação de Credenciais</h3>", unsafe_allow_html=True)
            st.write("Por motivos de segurança e auditoria, a redefinição de senhas do NGI Carajás deve ser solicitada diretamente ao administrador local ou setor de TI.")
            st.info("Entre em contato através do ramal interno ou envie um e-mail com a sua matrícula para a equipe de suporte.")
            if st.button("Voltar para Tela de Login", use_container_width=True):
                st.session_state.tela_login = "login"
                st.rerun()

# =============================================================================
# 6. SISTEMA PRINCIPAL (APLICAÇÃO INTERNA POST-LOGIN)
# =============================================================================
else:
    # Coleta centralizada de Dataframes para otimização de telas
    conn = conectar_banco()
    df_produtos = pd.read_sql_query("SELECT * FROM produtos", conn)
    df_movimentacoes = pd.read_sql_query("SELECT * FROM movimentacoes ORDER BY id DESC", conn)
    df_coordenacoes = pd.read_sql_query("SELECT * FROM coordenacoes", conn)
    df_usuarios = pd.read_sql_query("SELECT nome, email, perfil, status FROM usuarios", conn)
    lista_categorias = pd.read_sql_query("SELECT nome FROM categorias", conn)["nome"].tolist()
    conn.close()

    # --- MENU LATERAL INTEGRADO COM BOOTSTRAP ICONS PRO ---
    with st.sidebar:
        st.markdown(f"""
            <div style="padding: 10px 0; border-bottom: 1px solid #e2e8f0; margin-bottom: 15px;">
                <span style="font-size: 11px; color: #64748b; font-weight: bold; display: block; text-transform: uppercase; letter-spacing: 0.5px;">Operador Conectado</span>
                <span style="font-size: 15px; color: #1e293b; font-weight: 600; display: block;">👤 {st.session_state.usuario_logado['nome']}</span>
                <span style="font-size: 11px; background: #e2eed7; color: #1e5934; padding: 2px 6px; border-radius: 4px; font-weight: 500; display: inline-block; margin-top: 4px;">{st.session_state.usuario_logado['perfil']}</span>
            </div>
        """, unsafe_allow_html=True)
        
        # TABELA DE SUBSTITUIÇÃO PARA ÍCONES PROFISSIONAIS (Bootstrap Icons)
        escolha = option_menu(
            menu_title=None,
            options=[
                "Painel Geral", 
                "Movimentação",
                "Cadastrar Produto", 
                "Cadastrar Categoria", 
                "Cadastrar Coordenação",
                "Gestão de Usuários",
                "Histórico & Auditoria",
                "Sair do Sistema"
            ],
            icons=[
                "speedometer2",      # Painel Geral
                "arrow-left-right",  # Movimentação
                "box-seam",          # Cadastrar Produto
                "tags",              # Cadastrar Categoria
                "building-gear",     # Cadastrar Coordenação
                "people",            # Gestão de Usuários
                "journal-text",      # Histórico & Auditoria
                "door-open"          # Sair do Sistema
            ],
            menu_icon="cast", 
            default_index=0,
            styles={
                "container": {"padding": "0!important", "background-color": "transparent"},
                "icon": {"color": "#475569", "font-size": "15px"}, 
                "nav-link": {"font-size": "13.5px", "text-align": "left", "margin":"4px 0px", "border-radius":"6px", "padding":"10px", "--hover-color": "#e2eed7"},
                "nav-link-selected": {"background-color": "#1e5934", "color": "white", "font-weight": "500"},
            }
        )
        
        st.markdown("<br><br><p style='text-align: center; color: #94a3b8; font-size:11px;'>NGI Carajás v2.1.0<br>© 2026</p>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # TELA A: PAINEL GERAL (DASHBOARD)
    # -------------------------------------------------------------------------
    if escolha == "Painel Geral":
        st.markdown("<h2 style='color: #1e293b; font-weight: 700; margin-bottom: 4px;'>Dashboard Operacional</h2>", unsafe_allow_html=True)
        st.markdown("<p style='color: #64748b; margin-bottom: 25px;'>Indicadores consolidados em tempo real do estoque físico</p>", unsafe_allow_html=True)
        
        # Geração dos indicadores macro
        total_pecas = int(df_produtos['quantidade'].sum()) if not df_produtos.empty else 0
        total_itens = len(df_produtos)
        
        # Filtro de estoque baixo e esgotado baseado na coluna estoque_minimo
        if not df_produtos.empty:
            itens_criticos = len(df_produtos[df_produtos['quantidade'] <= df_produtos['estoque_minimo']])
            itens_esgotados = len(df_produtos[df_produtos['quantidade'] == 0])
        else:
            itens_criticos = 0
            itens_esgotados = 0
            
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f"""<div class="metric-card" style="border-left: 5px solid #2563eb;">
                <p style="color: #64748b; font-size: 11px; font-weight: bold; margin-bottom: 4px; text-transform: uppercase;"><i class="bi bi-box-fill"></i> Variedade de Itens</p>
                <h2 style="margin: 0; color: #1e293b; font-weight: 700;">{total_itens} <span style="font-size:13px; font-weight:normal; color:#94a3b8;">SKUs</span></h2>
            </div>""", unsafe_allow_html=True)
        with c2:
            st.markdown(f"""<div class="metric-card" style="border-left: 5px solid #16a34a;">
                <p style="color: #64748b; font-size: 11px; font-weight: bold; margin-bottom: 4px; text-transform: uppercase;"><i class="bi bi-layers-half"></i> Volume Total em Estoque</p>
                <h2 style="margin: 0; color: #16a34a; font-weight: 700;">{total_pecas} <span style="font-size:13px; font-weight:normal; color:#94a3b8;">unidades</span></h2>
            </div>""", unsafe_allow_html=True)
        with c3:
            st.markdown(f"""<div class="metric-card" style="border-left: 5px solid #ea580c;">
                <p style="color: #64748b; font-size: 11px; font-weight: bold; margin-bottom: 4px; text-transform: uppercase;"><i class="bi bi-exclamation-triangle-fill"></i> Atenção / Reposição</p>
                <h2 style="margin: 0; color: #ea580c; font-weight: 700;">{itens_criticos} <span style="font-size:13px; font-weight:normal; color:#94a3b8;">itens</span></h2>
            </div>""", unsafe_allow_html=True)
        with c4:
            st.markdown(f"""<div class="metric-card" style="border-left: 5px solid #dc2626;">
                <p style="color: #64748b; font-size: 11px; font-weight: bold; margin-bottom: 4px; text-transform: uppercase;"><i class="bi bi-x-octagon-fill"></i> Zeres / Esgotados</p>
                <h2 style="margin: 0; color: #dc2626; font-weight: 700;">{itens_esgotados} <span style="font-size:13px; font-weight:normal; color:#94a3b8;">itens</span></h2>
            </div>""", unsafe_allow_html=True)
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Filtros dinâmicos e Tabela de Consulta
        with st.container(border=True):
            f_col1, f_col2, f_col3 = st.columns([2, 1, 1])
            busca_termo = f_col1.text_input("🔍 Localização Rápida de Ativos", placeholder="Digite o nome, código ou localização do item...")
            cat_filtro = f_col2.selectbox("Filtrar por Categoria", ["Todas"] + lista_categorias)
            status_filtro = f_col3.selectbox("Situação do Estoque", ["Todos", "Esgotados", "Abaixo do Mínimo", "Disponível"])
            
            # Filtros aplicados no dataframe
            df_filtrado = df_produtos.copy()
            if busca_termo:
                df_filtrado = df_filtrado[
                    df_filtrado['item'].str.contains(busca_termo, case=False) | 
                    df_filtrado['codigo'].str.contains(busca_termo, case=False) |
                    df_filtrado['localizacao'].str.contains(busca_termo, case=False)
                ]
            if cat_filtro != "Todas":
                df_filtrado = df_filtrado[df_filtrado['categoria'] == cat_filtro]
                
            if status_filtro == "Esgotados":
                df_filtrado = df_filtrado[df_filtrado['quantidade'] == 0]
            elif status_filtro == "Abaixo do Mínimo":
                df_filtrado = df_filtrado[df_filtrado['quantidade'] <= df_filtrado['estoque_minimo']]
            elif status_filtro == "Disponível":
                df_filtrado = df_filtrado[df_filtrado['quantidade'] > df_filtrado['estoque_minimo']]
                
            st.markdown("<br>", unsafe_allow_html=True)
            if df_filtrado.empty:
                st.info("Nenhum item localizado com os filtros aplicados atualmente.")
            else:
                # Formatação estética para exibição profissional
                df_exibicao = df_filtrado.copy()
                df_exibicao.columns = ['Código', 'Nome do Item', 'Qtd Disponível', 'Categoria', 'Custo Unitário (R$)', 'Estoque Mínimo', 'Localização Física']
                st.dataframe(
                    df_exibicao,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Custo Unitário (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
                        "Qtd Disponível": st.column_config.ProgressColumn(format="%d unidades", min_value=0, max_value=100)
                    }
                )

    # -------------------------------------------------------------------------
    # TELA B: MOVIMENTAÇÃO (ENTRADAS E SAÍDAS)
    # -------------------------------------------------------------------------
    elif escolha == "Movimentação":
        st.markdown("<h2 style='color: #1e293b; font-weight: 700;'>Fluxos de Entrada e Saída</h2>", unsafe_allow_html=True)
        st.markdown("<p style='color: #64748b;'>Gerencie a entrada de novos lotes de mercadoria ou conceda baixas para os setores de destino</p>", unsafe_allow_html=True)
        
        tab_entrada, tab_saida = st.tabs(["📥 Lançar Entrada de Notas/Lotes", "📤 Registrar Retirada/Consumo Interno"])
        
        with tab_entrada:
            if df_produtos.empty:
                st.warning("⚠️ Não existem produtos cadastrados no banco para realizar movimentações.")
            else:
                with st.form("form_entrada", clear_on_submit=True):
                    st.write("### Dados do Lote")
                    c_ent1, c_ent2 = st.columns(2)
                    
                    item_selecionado = c_ent1.selectbox("Selecione o Item", df_produtos['item'].tolist(), key="box_item_ent")
                    qtd_entrada = c_ent2.number_input("Quantidade Adquirida / Recebida", min_value=1, value=1, step=1)
                    
                    obs_entrada = st.text_input("Observação / Número da Nota Fiscal", placeholder="Ex: NF nº 4321 ou Reposição de Almoxarifado central")
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.form_submit_button("Processar Entrada", type="primary"):
                        # Extrai o código do produto associado ao nome do item
                        cod_prod = df_produtos[df_produtos['item'] == item_selecionado]['codigo'].values[0]
                        
                        conn = conectar_banco()
                        cursor = conn.cursor()
                        # Atualiza estoque
                        cursor.execute("UPDATE produtos SET quantidade = quantidade + ? WHERE codigo = ?", (qtd_entrada, cod_prod))
                        # Registra movimentação
                        cursor.execute("""
                            INSERT INTO movimentacoes (data, tipo, codigo, item, quantidade, responsavel, coordenacao, observacao, usuario_registro)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            datetime.now().strftime("%d/%m/%Y %H:%M"),
                            "Entrada", cod_prod, item_selecionado, qtd_entrada, "Fornecedor / Almoxarifado Central", "NGI CARAJÁS",
                            obs_entrada, st.session_state.usuario_logado['nome']
                        ))
                        conn.commit()
                        conn.close()
                        
                        st.success(f"Estoque do item '{item_selecionado}' foi reabastecido com +{qtd_entrada} unidades!")
                        st.rerun()
                        
        with tab_saida:
            if df_produtos.empty:
                st.warning("⚠️ Sem produtos no estoque.")
            elif df_coordenacoes.empty:
                st.warning("⚠️ Cadastre ao menos um setor/coordenação antes de realizar dispensas de materiais.")
            else:
                with st.form("form_saida", clear_on_submit=True):
                    st.write("### Dados da Requisição")
                    c_sai1, c_sai2 = st.columns(2)
                    
                    item_saida_sel = c_sai1.selectbox("Selecione o Item solicitado", df_produtos['item'].tolist(), key="box_item_sai")
                    qtd_saida = c_sai2.number_input("Quantidade Solicitada para Entrega", min_value=1, value=1, step=1)
                    
                    c_sai3, c_sai4 = st.columns(2)
                    servidor_destino = c_sai3.text_input("Nome do Servidor / Recebedor", placeholder="Ex: Roberto Carlos Melo")
                    coord_destino = c_sai4.selectbox("Coordenação Requisitante", df_coordenacoes['sigla'].tolist())
                    
                    obs_saida = st.text_input("Finalidade / Justificativa do uso", placeholder="Ex: Substituição de periférico queimado ou Uso em campo nas UCs")
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.form_submit_button("Aprovar e Dispensar Item", type="primary"):
                        # Validação de dados e limites
                        estoque_linha = df_produtos[df_produtos['item'] == item_saida_sel].iloc[0]
                        estoque_disponivel = estoque_linha['quantidade']
                        cod_prod_sai = estoque_linha['codigo']
                        limite_critico = estoque_linha['estoque_minimo']
                        
                        if qtd_saida > estoque_disponivel:
                            st.error(f"❌ Abastecimento Negado. O estoque atual do item é de apenas {estoque_disponivel} unidades.")
                        elif not servidor_destino.strip():
                            st.warning("⚠️ Preenchimento do nome do servidor recebedor é obrigatório para controle de patrimônio.")
                        else:
                            novo_estoque = estoque_disponivel - qtd_saida
                            
                            conn = conectar_banco()
                            cursor = conn.cursor()
                            # Deduz estoque
                            cursor.execute("UPDATE produtos SET quantidade = ? WHERE codigo = ?", (novo_estoque, cod_prod_sai))
                            # Registra movimentação de saída
                            cursor.execute("""
                                INSERT INTO movimentacoes (data, tipo, codigo, item, quantity, responsavel, coordenacao, observacao, usuario_registro)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                datetime.now().strftime("%d/%m/%Y %H:%M"),
                                "Saída", cod_prod_sai, item_saida_sel, qtd_saida, servidor_destino, coord_destino,
                                obs_saida, st.session_state.usuario_logado['nome']
                            ))
                            conn.commit()
                            conn.close()
                            
                            st.success(f"Baixa computada! {qtd_saida} unidades do item entregues para {servidor_destino} ({coord_destino}).")
                            
                            # Avaliação automática e disparo de e-mail de alerta de estoque crítico
                            if novo_estoque <= limite_critico:
                                st.warning(f"⚠️ Atenção: Este item atingiu o estoque crítico de atenção ({novo_estoque} unidades em estoque).")
                                dispatche = enviar_alerta_estoque_baixo(item_saida_sel, novo_estoque, limite_critico)
                                if dispatche:
                                    st.info("📨 E-mail de notificação de falta de suprimento emitido para a gerência.")
                                    
                            st.rerun()

    # -------------------------------------------------------------------------
    # TELA C: CADASTRAR PRODUTO (NOVO ITEM NO SISTEMA)
    # -------------------------------------------------------------------------
    elif escolha == "Cadastrar Produto":
        st.markdown("<h2 style='color: #1e293b; font-weight: 700;'>Catalogação de Insumos e Produtos</h2>", unsafe_allow_html=True)
        st.markdown("<p style='color: #64748b;'>Adicione novas tipologias de mercadorias no banco de dados para controle de fluxo</p>", unsafe_allow_html=True)
        
        with st.form("form_novo_prod", clear_on_submit=True):
            st.write("### Especificações Técnicas do Ativo")
            cp1, cp2, cp3 = st.columns([1, 2, 1.5])
            
            novo_cod = cp1.text_input("Código de Barras / SKU ID", placeholder="Ex: 098")
            novo_item = cp2.text_input("Nome Descritivo do Item", placeholder="Ex: Monitor Dell 23.8 polegadas IPS")
            nova_cat = cp3.selectbox("Categoria Correspondente", lista_categorias)
            
            cp4, cp5, cp6 = st.columns(3)
            novo_valor = cp4.number_input("Preço de Aquisição Unitário (R$)", min_value=0.0, value=0.0, step=0.10)
            novo_minimo = cp5.number_input("Limite de Alerta de Estoque Mínimo", min_value=0, value=5, step=1)
            nova_localizacao = cp6.text_input("Endereço / Localização Física Interna", placeholder="Ex: Almoxarifado Sala 2 - Estante 4")
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.form_submit_button("Inserir Produto no Cadastro", type="primary"):
                if not novo_cod.strip() or not novo_item.strip():
                    st.error("❌ Os campos 'Código' e 'Nome Descritivo do Item' são estruturais e obrigatórios.")
                elif novo_cod in df_produtos['codigo'].values:
                    st.error(f"❌ Código '{novo_cod}' já está em uso pelo item '{df_produtos[df_produtos['codigo'] == novo_cod]['item'].values[0]}'.")
                else:
                    conn = conectar_banco()
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO produtos (codigo, item, quantidade, categoria, valor_unitario, estoque_minimo, localizacao)
                        VALUES (?, ?, 0, ?, ?, ?, ?)
                    """, (novo_cod.strip(), novo_item.strip(), nova_cat, novo_valor, novo_minimo, nova_localizacao.strip()))
                    conn.commit()
                    conn.close()
                    
                    st.success(f"Sucesso: '{novo_item}' inserido na base de dados com estoque inicial igual a zero.")
                    st.rerun()

    # -------------------------------------------------------------------------
    # TELA D: CADASTRAR CATEGORIA
    # -------------------------------------------------------------------------
    elif escolha == "Cadastrar Categoria":
        st.markdown("<h2 style='color: #1e293b; font-weight: 700;'>Estrutura de Categorias</h2>", unsafe_allow_html=True)
        
        col_c1, col_c2 = st.columns([1, 1.5])
        
        with col_c1:
            with st.form("form_nova_cat", clear_on_submit=True):
                st.write("### Nova Categoria")
                cat_nome = st.text_input("Nome do Grupo de Produto", placeholder="Ex: Refrigeração")
                cat_desc = st.text_area("Descrição Breve do Escopo", placeholder="Uso em aparelhos de ar condicionado e climatizadores...")
                
                if st.form_submit_button("Criar Categoria", type="primary"):
                    if not cat_nome.strip():
                        st.error("Nome da categoria obrigatório.")
                    elif cat_nome.strip() in lista_categorias:
                        st.warning("Esta categoria já existe no banco.")
                    else:
                        conn = conectar_banco()
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO categorias VALUES (?, ?)", (cat_nome.strip(), cat_desc.strip()))
                        conn.commit()
                        conn.close()
                        st.success("Nova categoria habilitada!")
                        st.rerun()
                        
        with col_c2:
            st.write("### Árvore de Categorias Ativas")
            conn = conectar_banco()
            df_cat_full = pd.read_sql_query("SELECT nome as 'Categoria', descricao as 'Descrição do Escopo' FROM categorias", conn)
            conn.close()
            st.dataframe(df_cat_full, use_container_width=True, hide_index=True)

    # -------------------------------------------------------------------------
    # TELA E: CADASTRAR COORDENAÇÃO
    # -------------------------------------------------------------------------
    elif escolha == "Cadastrar Coordenação":
        st.markdown("<h2 style='color: #1e293b; font-weight: 700;'>Setores e Organograma Operacional</h2>", unsafe_allow_html=True)
        
        col_co1, col_co2 = st.columns([1, 1.5])
        
        with col_co1:
            with st.form("form_nova_coord", clear_on_submit=True):
                st.write("### Novo Setor")
                co_sigla = st.text_input("Sigla de Identificação", placeholder="Ex: COMAN")
                co_nome = st.text_input("Nome da Coordenação por Extenso", placeholder="Coordenação de Manejo e Proteção")
                co_resp = st.text_input("Responsável Titular da Pasta", placeholder="Nome do Chefe do Setor")
                
                if st.form_submit_button("Vincular Setor Administrativo", type="primary"):
                    if not co_sigla.strip() or not co_nome.strip():
                        st.error("Sigla e Nome por extenso são campos vitais.")
                    else:
                        conn = conectar_banco()
                        cursor = conn.cursor()
                        try:
                            cursor.execute("INSERT INTO coordenacoes VALUES (?, ?, ?)", (co_sigla.upper().strip(), co_nome.strip(), co_resp.strip()))
                            conn.commit()
                            st.success("Setor integrado ao organograma de saídas!")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Esta Sigla de coordenação já está em uso por outro setor.")
                        finally:
                            conn.close()
                            
        with col_co2:
            st.write("### Unidades Habilitadas para Requisições")
            df_co_exibicao = df_coordenacoes.copy()
            df_co_exibicao.columns = ['Sigla Unidade', 'Nome da Coordenação', 'Gestor/Responsável']
            st.dataframe(df_co_exibicao, use_container_width=True, hide_index=True)

    # -------------------------------------------------------------------------
    # TELA F: GESTÃO DE USUÁRIOS (NÍVEIS DE ACESSO)
    # -------------------------------------------------------------------------
    elif escolha == "Gestão de Usuários":
        st.markdown("<h2 style='color: #1e293b; font-weight: 700;'>Controle de Acessos ao Sistema</h2>", unsafe_allow_html=True)
        
        # Apenas perfis Administradores podem manipular novos logins
        if st.session_state.usuario_logado['perfil'] != "Administrador":
            st.error("🛡️ Acesso Negado. Você está logado como 'Usuário Comum'. Apenas perfis de cargo 'Administrador' possuem credenciais para auditar e criar novos usuários.")
        else:
            c_u1, c_u2 = st.columns([1, 1.5])
            
            with c_u1:
                with st.form("form_novo_user", clear_on_submit=True):
                    st.write("### Credenciamento de Operador")
                    u_nome = st.text_input("Nome Completo do Funcionário")
                    u_email = st.text_input("E-mail Funcional (Login)")
                    u_senha = st.text_input("Senha Inicial de Acesso", type="password")
                    u_perfil = st.selectbox("Nível de Privilégio", ["Usuário Comum", "Administrador"])
                    
                    if st.form_submit_button("Gerar Acesso", type="primary"):
                        if not u_nome or not u_email or not u_senha:
                            st.warning("Preencha todos os campos do formulário.")
                        else:
                            conn = conectar_banco()
                            cursor = conn.cursor()
                            try:
                                cursor.execute("INSERT INTO usuarios (nome, email, senha, perfil, status) VALUES (?, ?, ?, ?, 'Ativo')", 
                                               (u_nome.strip(), u_email.lower().strip(), u_senha.strip(), u_perfil))
                                conn.commit()
                                st.success("Novo operador cadastrado!")
                                st.rerun()
                            except sqlite3.IntegrityError:
                                st.error("Este e-mail corporativo já possui cadastro ativo no banco de dados.")
                            finally:
                                conn.close()
                                
            with c_u2:
                st.write("### Operadores Cadastrados")
                df_u_exibir = df_usuarios.copy()
                df_u_exibir.columns = ['Nome Completo', 'E-mail / Login', 'Nível de Permissão', 'Status de Acesso']
                st.dataframe(df_u_exibir, use_container_width=True, hide_index=True)
                
                st.markdown("<small><i>Nota: Para alternar o status de um usuário de 'Ativo' para 'Inativo', execute os comandos via console de banco de dados SQL estruturado.</i></small>", unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # TELA G: HISTÓRICO & AUDITORIA (LIVRO DE MOVIMENTAÇÃO)
    # -------------------------------------------------------------------------
    elif escolha == "Histórico & Auditoria":
        st.markdown("<h2 style='color: #1e293b; font-weight: 700;'>Livro Registro de Auditoria</h2>", unsafe_allow_html=True)
        st.markdown("<p style='color: #64748b;'>Rastreabilidade total das movimentações de insumos executadas no almoxarifado</p>", unsafe_allow_html=True)
        
        if df_movimentacoes.empty:
            st.info("Nenhuma movimentação de mercadorias registrada na história do almoxarifado até o momento.")
        else:
            with st.container(border=True):
                st.write("### Filtros Rápidos de Auditoria")
                fa1, fa2, fa3 = st.columns(3)
                
                filtro_tipo = fa1.selectbox("Filtrar por Natureza", ["Todos", "Entrada", "Saída"])
                filtro_setor = fa2.selectbox("Filtrar por Destinatário", ["Todos"] + df_coordenacoes['sigla'].tolist())
                
                # Download de Relatório CSV estruturado
                csv_buffer = df_movimentacoes.to_csv(index=False).encode('utf-8')
                fa3.markdown("<br>", unsafe_allow_html=True)
                fa3.download_button(
                    label="📥 Exportar Log Completo (CSV)",
                    data=csv_buffer,
                    file_name=f"auditoria_almoxarifado_{datetime.now().strftime('%Y_%m_%d')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
                
                # Executa filtros no Log de auditoria
                df_log_filtrado = df_movimentacoes.copy()
                if filtro_tipo != "Todos":
                    df_log_filtrado = df_log_filtrado[df_log_filtrado['tipo'] == filtro_tipo]
                if filtro_setor != "Todos":
                    df_log_filtrado = df_log_filtrado[df_log_filtrado['coordenacao'] == filtro_setor]
                    
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Renomeia colunas para exibição amigável em formato de livro fiscal
            df_log_filtrado.columns = [
                'ID Registro', 'Data/Hora Operação', 'Natureza', 'Código Item', 
                'Nome do Item', 'Quantidade', 'Responsável/Beneficiário', 
                'Setor Destino', 'Justificativa/Nota', 'Operador Responsável'
            ]
            
            st.dataframe(df_log_filtrado, use_container_width=True, hide_index=True)

    # -------------------------------------------------------------------------
    # TELA H: ENCERRAMENTO DA SESSÃO (LOGOUT COM SEGURANÇA)
    # -------------------------------------------------------------------------
    elif escolha == "Sair do Sistema":
        st.session_state.autenticado = False
        st.session_state.usuario_logado = {}
        st.toast("Sessão encerrada de forma segura.", icon="🔒")
        st.rerun()
