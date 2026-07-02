import streamlit as st
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests

# =============================================================================
# CONEXÃO DIRETA VIA REST API (SUPABASE) - PREVINE ERROS DE RESOLUÇÃO DE DNS
# =============================================================================
supabase_disponivel = False
SUPABASE_URL = ""
SUPABASE_KEY = ""

if "supabase_url" in st.secrets and "supabase_key" in st.secrets:
    SUPABASE_URL = st.secrets["supabase_url"].strip().rstrip("/")
    SUPABASE_KEY = st.secrets["supabase_key"].strip()
    if SUPABASE_URL and SUPABASE_KEY:
        supabase_disponivel = True
else:
    st.error("⚠️ ERRO CRÍTICO: 'supabase_url' ou 'supabase_key' não configurados nos Secrets do Streamlit.")

# Headers padrões para conversação direta com a API REST do Supabase
headers_auth = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# --- FUNÇÕES DE INFRAESTRUTURA DE BANCO DE DADOS (MÉTODOS HTTP DIRETOS) ---
def buscar_dados(tabela):
    if not supabase_disponivel:
        return []
    try:
        url = f"{SUPABASE_URL}/rest/v1/{tabela}?select=*"
        resposta = requests.get(url, headers=headers_auth, timeout=12)
        if resposta.status_code == 200:
            return resposta.json()
        return []
    except Exception as e:
        st.error(f"Erro na requisição à tabela {tabela}: {e}")
        return []

def inserir_dados(tabela, dados):
    if not supabase_disponivel:
        return False
    try:
        url = f"{SUPABASE_URL}/rest/v1/{tabela}"
        resposta = requests.post(url, headers=headers_auth, json=dados, timeout=12)
        if resposta.status_code in [200, 201]:
            return True
        st.error(f"Erro ao inserir na tabela {tabela}: {resposta.text}")
        return False
    except Exception as e:
        st.error(f"Falha de rede ao inserir: {e}")
        return False

def atualizar_dados(tabela, dados, coluna_id, valor_id):
    if not supabase_disponivel:
        return False
    try:
        url = f"{SUPABASE_URL}/rest/v1/{tabela}?{coluna_id}=eq.{valor_id}"
        resposta = requests.patch(url, headers=headers_auth, json=dados, timeout=12)
        if resposta.status_code in [200, 204]:
            return True
        st.error(f"Erro ao atualizar na tabela {tabela}: {resposta.text}")
        return False
    except Exception as e:
        st.error(f"Falha de rede ao atualizar: {e}")
        return False

def deletar_dados(tabela, coluna_id, valor_id):
    if not supabase_disponivel:
        return False
    try:
        url = f"{SUPABASE_URL}/rest/v1/{tabela}?{coluna_id}=eq.{valor_id}"
        resposta = requests.delete(url, headers=headers_auth, timeout=12)
        if resposta.status_code in [200, 204]:
            return True
        st.error(f"Erro ao deletar na tabela {tabela}: {resposta.text}")
        return False
    except Exception as e:
        st.error(f"Falha de rede ao deletar: {e}")
        return False

# =============================================================================
# CONFIGURAÇÃO DO SERVIDOR DE CORREIO ELETRÔNICO (GMAIL METADATA)
# =============================================================================
try:
    EMAIL_REMETENTE = st.secrets["gmail"]["email"]
    SENHA_REMETENTE = st.secrets["gmail"]["senha_app"]
except:
    EMAIL_REMETENTE = "suporte_ngi@gmail.com"
    SENHA_REMETENTE = "configuracao_indisponivel"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORTA = 587

# --- CONFIGURAÇÕES DO AMBIENTE GLOBAL STREAMLIT ---
st.set_page_config(
    page_title="SISTEMA DE GESTÃO DE ALMOXARIFADO NGI CARAJÁS", 
    page_icon="🌿", 
    layout="wide"
)

# --- INJEÇÃO DE ESTILOS CSS CUSTOMIZADOS ---
st.markdown("""
    <style>
    [data-testid="stSidebarNav"] {display: none;}
    [data-testid="stMainMenu"] {display: none;}
    [data-testid="stSidebar"] {
        background-color: #f4f0fa !important;
        border-right: 2px solid #e2daeb;
    }
    div.stButton > button:first-child[kind="primary"] {
        background-color: #2E7D32 !important;
        border-color: #2E7D32 !important;
        color: white !important;
        font-weight: bold;
        padding: 0.5rem 2rem;
        border-radius: 8px;
    }
    div.stButton > button:first-child[kind="primary"]:hover {
        background-color: #1B5E20 !important;
        border-color: #1B5E20 !important;
    }
    .img-container {
        display: flex;
        justify-content: center;
        align-items: center;
        width: 100%;
        margin-top: 10px;
        margin-bottom: 25px;
    }
    .kpi-container {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border-left: 6px solid #2E7D32;
    }
    .kpi-container-critical {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border-left: 6px solid #C62828;
    }
    </style>
""", unsafe_allow_html=True)

# --- GERENCIAMENTO DE ESTADO DA SESSÃO ---
if "autenticado" not in st.session_state: st.session_state.autenticado = False
if "sub_tela_login" not in st.session_state: st.session_state.sub_tela_login = "login"
if "NOME_USUARIO_LOGADO" not in st.session_state: st.session_state.NOME_USUARIO_LOGADO = ""
if "PERFIL_USUARIO" not in st.session_state: st.session_state.PERFIL_USUARIO = ""
if "EMAIL_USUARIO_LOGADO" not in st.session_state: st.session_state.EMAIL_USUARIO_LOGADO = ""
if "LOGIN_USUARIO_LOGADO" not in st.session_state: st.session_state.LOGIN_USUARIO_LOGADO = ""

# =============================================================================
# FLUXO DE AUTENTICAÇÃO (MÓDULO DE LOGIN SEGURO)
# =============================================================================
if not st.session_state.autenticado:
    if st.session_state.sub_tela_login == "login":
        st.markdown("<br><br>", unsafe_allow_html=True)
        c_l1, c_l2, c_l3 = st.columns([1, 1.3, 1])
        with c_l2:
            st.markdown("""
                <div class="img-container">
                    <img src="https://www.gov.br/icmbio/pt-br/assuntos/biodiversidade/unidade-de-conservacao/unidades-de-biomas/marinho/lista-de-ucs/parna-marinho-dos-abrolhos/fomulario-denuncia/icmbio-logo-1.png" width="310">
                </div>
            """, unsafe_allow_html=True)
            st.markdown("<h2 style='text-align: center; color: #1b5e20; font-family: sans-serif; font-weight: bold;'>Sistema de Almoxarifado<br>NGI Carajás</h2>", unsafe_allow_html=True)
            st.write("---")
            
            user_input = st.text_input("Usuário ou E-mail Institucional:", placeholder="usuario@icmbio.gov.br", key="main_user_login")
            pass_input = st.text_input("Senha de Acesso:", type="password", placeholder="••••••••", key="main_pass_login")
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Autenticar no Sistema", type="primary", use_container_width=True):
                if user_input.strip() and pass_input.strip():
                    usuarios_banco = buscar_dados("usuarios")
                    usuario_encontrado = None
                    
                    for u in usuarios_banco:
                        if (u["usuario"].lower() == user_input.strip().lower() or u["email"].lower() == user_input.strip().lower()) and str(u["senha"]) == str(pass_input.strip()):
                            usuario_encontrado = u
                            break
                            
                    if usuario_encontrado:
                        st.session_state.autenticado = True
                        st.session_state.NOME_USUARIO_LOGADO = usuario_encontrado["nome"]
                        st.session_state.PERFIL_USUARIO = usuario_encontrado["perfil"].lower()
                        st.session_state.EMAIL_USUARIO_LOGADO = usuario_encontrado["email"]
                        st.session_state.LOGIN_USUARIO_LOGADO = usuario_encontrado["usuario"]
                        st.success("Autenticação efetuada com sucesso! Redirecionando...")
                        st.rerun()
                    else:
                        st.error("Credenciais inválidas! Verifique os dados digitados.")
                else:
                    st.error("Por favor, preencha todos os campos para prosseguir.")
            
            if st.button("Esqueci minha senha corporativa", use_container_width=True):
                st.session_state.sub_tela_login = "esqueci"
                st.rerun()

    elif st.session_state.sub_tela_login == "esqueci":
        c_r1, c_r2, c_r3 = st.columns([1, 1.3, 1])
        with c_r2:
            st.markdown("<br><br>", unsafe_allow_html=True)
            st.subheader("🔑 Recuperação de Acesso")
            st.write("Informe seu e-mail cadastrado para redefinir suas credenciais.")
            email_rec = st.text_input("E-mail Funcional:", placeholder="servidor@icmbio.gov.br")
            
            if st.button("Enviar Código Provisório", type="primary", use_container_width=True):
                if email_rec.strip():
                    usuarios_sistema = buscar_dados("usuarios")
                    existe_email = any(u["email"].lower() == email_rec.strip().lower() for u in usuarios_sistema)
                    
                    if existe_email:
                        try:
                            msg = MIMEMultipart()
                            msg['From'] = EMAIL_REMETENTE
                            msg['To'] = email_rec.strip()
                            msg['Subject'] = "Recuperação de Senha - Almoxarifado NGI Carajás"
                            corpo = "Prezado Servidor,\n\nConforme solicitado, sua credencial provisória para primeiro acesso é: 123.\nPor favor, altere sua senha no menu Perfil assim que realizar o login."
                            msg.attach(MIMEText(corpo, 'plain'))
                            
                            server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
                            server.starttls()
                            server.open()
                            server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
                            server.sendmail(EMAIL_REMETENTE, email_rec.strip(), msg.as_string())
                            server.quit()
                            st.success("E-mail enviado! Verifique sua caixa de entrada ou spam.")
                        except Exception as e:
                            st.error(f"Falha técnica no processamento do e-mail: {e}")
                    else:
                        st.error("E-mail não localizado na base de dados de servidores ativos.")
                else:
                    st.error("Digite o e-mail obrigatório.")
            
            if st.button("Voltar para Tela de Login", use_container_width=True):
                st.session_state.sub_tela_login = "login"
                st.rerun()

# =============================================================================
# FLUXO DO APLICATIVO CORPORATIVO (LOGADO E SESSÃO VALIDADA)
# =============================================================================
else:
    # Sincronização centralizada de todas as tabelas em memória RAM (DataFrames)
    raw_produtos = buscar_dados("produtos")
    df_produtos = pd.DataFrame(raw_produtos) if raw_produtos else pd.DataFrame(columns=["id", "codigo", "item", "quantidade", "categoria", "valor_unitario"])
    if not df_produtos.empty: df_produtos["id"] = df_produtos["id"].astype(int)

    raw_categorias = buscar_dados("categorias")
    lista_categorias = [c["nome"] for c in raw_categorias] if raw_categorias else []

    raw_coordenacoes = buscar_dados("coordenacoes")
    df_coordenacoes = pd.DataFrame(raw_coordenacoes) if raw_coordenacoes else pd.DataFrame(columns=["id", "sigla", "nome"])

    raw_usuarios = buscar_dados("usuarios")
    df_usuarios = pd.DataFrame(raw_usuarios) if raw_usuarios else pd.DataFrame(columns=["id", "nome", "usuario", "email", "perfil"])

    raw_movimentacoes = buscar_dados("movimentacoes")
    df_movimentacoes = pd.DataFrame(raw_movimentacoes) if raw_movimentacoes else pd.DataFrame(columns=["id", "data", "tipo", "codigo", "item", "quantidade", "responsavel", "coordenacao"])

    # --- NAVEGAÇÃO LATERAL (SIDEBAR) ---
    with st.sidebar:
        st.markdown(f"### 🌿 NGI Carajás")
        st.markdown(f"**Operador:** {st.session_state.NOME_USUARIO_LOGADO}")
        st.markdown(f"**Nível:** `{st.session_state.PERFIL_USUARIO.upper()}`")
        st.write("---")
        
        menu_principal = [
            "🎛️ Painel Geral",
            "➕ Cadastrar Produto",
            "🗂️ Cadastrar Categoria",
            "👥 Cadastrar Usuário",
            "🏢 Cadastrar Coordenação",
            "🔄 Movimentação de Estoque",
            "👤 Meu Perfil",
            "🚪 Encerrar Sessão"
        ]
        escolha = st.radio("Módulos do Sistema:", menu_principal, label_visibility="collapsed")
        st.write("---")
        st.caption("Sistema Gestão Interna v3.2.0")

    # --- ENCERRAMENTO DE SESSÃO DIRETO ---
    if escolha == "🚪 Encerrar Sessão":
        st.session_state.autenticado = False
        st.session_state.NOME_USUARIO_LOGADO = ""
        st.session_state.PERFIL_USUARIO = ""
        st.rerun()

    # --- MÓDULO 1: PAINEL GERAL DE METRICAS ---
    elif escolha == "🎛️ Painel Geral":
        st.title("🎛️ Painel Geral de Controle de Estoque")
        st.write("Acompanhamento consolidado das métricas de materiais em tempo real.")
        st.markdown("<br>", unsafe_allow_html=True)
        
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            tot_itens = len(df_produtos)
            st.markdown(f"<div class='kpi-container'><b>Itens em Catálogo</b><h2>{tot_itens}</h2></div>", unsafe_allow_html=True)
        with c2:
            esgotados = len(df_produtos[df_produtos['quantidade'] == 0]) if not df_produtos.empty else 0
            st.markdown(f"<div class='kpi-container-critical'><b>Produtos Esgotados</b><h2>{esgotados}</h2></div>", unsafe_allow_html=True)
        with c3:
            tot_mov = len(df_movimentacoes)
            st.markdown(f"<div class='kpi-container'><b>Movimentações (Histórico)</b><h2>{tot_mov}</h2></div>", unsafe_allow_html=True)
        with c4:
            if not df_produtos.empty:
                df_produtos["total_custo"] = df_produtos["quantidade"].astype(float) * df_produtos["valor_unitario"].astype(float)
                patrimonio = df_produtos["total_custo"].sum()
            else:
                patrimonio = 0.0
            st.markdown(f"<div class='kpi-container'><b>Patrimônio Estimado</b><h2>R$ {patrimonio:,.2f}</h2></div>", unsafe_allow_html=True)
            
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.subheader("🔍 Filtros de Consulta e Varredura")
        col_filtro1, col_filtro2 = st.columns([2, 1])
        termo_busca = col_filtro1.text_input("Buscar por especificação técnica ou código do item:")
        cat_filtrada = col_filtro2.selectbox("Filtragem por categoria estrutural:", ["Todas as Categorias"] + lista_categorias)
        
        df_view = df_produtos.copy()
        if termo_busca:
            df_view = df_view[df_view['item'].str.contains(termo_busca, case=False, na=False) | df_view['codigo'].str.contains(termo_busca, case=False, na=False)]
        if cat_filtrada != "Todas as Categorias":
            df_view = df_view[df_view['categoria'] == cat_filtrada]
            
        st.markdown("### 📋 Balanço Consolidado do Almoxarifado")
        if df_view.empty:
            st.info("Nenhum material cadastrado atende aos filtros selecionados.")
        else:
            df_render = df_view.rename(columns={
                "codigo": "Código Identificador",
                "item": "Descrição do Material",
                "categoria": "Categoria Logística",
                "quantidade": "Saldo Atual em Estoque",
                "valor_unitario": "Preço Unitário (R$)"
            })
            st.dataframe(df_render[["Código Identificador", "Descrição do Material", "Categoria Logística", "Saldo Atual em Estoque", "Preço Unitário (R$)"]], use_container_width=True, hide_index=True)

    # --- MÓDULO 2: GERENCIAMENTO E CADASTRO DE PRODUTOS ---
    elif escolha == "➕ Cadastrar Produto":
        st.title("➕ Gerenciamento e Cadastro de Itens")
        
        t_prod_cad, t_prod_edt = st.tabs(["➕ Adicionar Novo Item", "✏️ Modificar / Deletar Material"])
        
        with t_prod_cad:
            if st.session_state.PERFIL_USUARIO != "administrador":
                st.warning("⚠️ Permissão insuficiente. Somente administradores do almoxarifado podem catalogar materiais.")
            else:
                with st.form("form_registro_produto", clear_on_submit=True):
                    st.write("### Formulário de Inclusão de Insumo")
                    cp1, cp2 = st.columns(2)
                    ins_cod = cp1.text_input("Código de Barras / SKU Unificado:")
                    ins_nome = cp2.text_input("Nome Comercial / Descrição detalhada do material:")
                    ins_cat = cp1.selectbox("Vincular Categoria Relacionada:", lista_categorias) if lista_categorias else cp1.selectbox("Categoria", ["Nenhuma cadastrada"])
                    ins_preco = cp2.number_input("Valor Unitário Médio de Compra (R$):", min_value=0.0, step=0.01)
                    
                    if st.form_submit_button("Salvar Registro de Produto", type="primary"):
                        if not lista_categorias:
                            st.error("Não é possível criar produtos sem antes possuir ao menos uma categoria válida.")
                        elif ins_cod.strip() and ins_nome.strip():
                            payload = {
                                "codigo": ins_cod.strip(),
                                "item": ins_nome.strip(),
                                "quantidade": 0,
                                "categoria": ins_cat,
                                "valor_unitario": ins_preco
                            }
                            if inserir_dados("produtos", payload):
                                st.success(f"Material '{ins_nome.strip()}' inserido com sucesso!")
                                st.rerun()
                        else:
                            st.error("Campos obrigatórios em branco (Código e Descrição).")

        with t_prod_edt:
            if st.session_state.PERFIL_USUARIO != "administrador":
                st.warning("⚠️ Operação restrita para gerentes administrativos.")
            elif df_produtos.empty:
                st.info("Nenhum item em estoque para modificação.")
            else:
                prod_alvo = st.selectbox("Selecione o Material para Edição Estrutural:", df_produtos["item"].tolist())
                dados_alvo = df_produtos[df_produtos["item"] == prod_alvo].iloc[0]
                
                up_cod = st.text_input("Editar Código do Item:", value=str(dados_alvo["codigo"]))
                up_item = st.text_input("Editar Nome do Material:", value=str(dados_alvo["item"]))
                up_cat = st.selectbox("Mudar Categoria Logística:", lista_categorias, index=lista_categorias.index(dados_alvo["categoria"]) if dados_alvo["categoria"] in lista_categorias else 0)
                up_val = st.number_input("Mudar Preço Unitário:", min_value=0.0, value=float(dados_alvo["valor_unitario"]), step=0.01)
                
                cb1, cb2 = st.columns(2)
                if cb1.button("Gravar Novas Alterações", type="primary", use_container_width=True):
                    up_payload = {"codigo": up_cod, "item": up_item, "categoria": up_cat, "valor_unitario": up_val}
                    if atualizar_dados("produtos", up_payload, "id", int(dados_alvo["id"])):
                        st.success("Produto modificado com êxito!")
                        st.rerun()
                        
                if cb2.button("❌ Excluir Material Permanentemente", use_container_width=True):
                    if deletar_dados("produtos", "id", int(dados_alvo["id"])):
                        st.warning("Material deletado do banco de dados.")
                        st.rerun()

    # --- MÓDULO 3: GESTÃO DE CATEGORIAS ---
    elif escolha == "🗂️ Cadastrar Categoria":
        st.title("🗂️ Gerenciamento de Categorias Logísticas")
        
        if st.session_state.PERFIL_USUARIO != "administrador":
            st.warning("⚠️ Módulo de governança restrito.")
        else:
            col_c1, col_c2 = st.columns([1, 2])
            with col_c1:
                st.write("### Nova Categoria")
                nome_nova_cat = st.text_input("Nome da Categoria Administrativa:")
                if st.button("Salvar Categoria", type="primary", use_container_width=True):
                    if nome_nova_cat.strip():
                        if inserir_dados("categorias", {"nome": nome_nova_cat.strip()}):
                            st.success("Categoria armazenada!")
                            st.rerun()
                    else:
                        st.error("Informe um nome válido.")
            with col_c2:
                st.write("### Categorias Atualmente Ativas")
                if lista_categorias:
                    df_c_render = pd.DataFrame(lista_categorias, columns=["Estrutura de Agrupamento"])
                    st.dataframe(df_c_render, use_container_width=True, hide_index=True)
                    
                    st.write("---")
                    cat_deletar = st.selectbox("Selecione para remover:", lista_categorias)
                    if st.button("❌ Remover Categoria Selecionada"):
                        if deletar_dados("categorias", "nome", cat_deletar):
                            st.success("Categoria deletada.")
                            st.rerun()
                else:
                    st.info("Nenhuma categoria ativa no sistema.")

    # --- MÓDULO 4: GESTÃO E CONTROLE DE USUÁRIOS (RESTRITO) ---
    elif escolha == "👥 Cadastrar Usuário":
        st.title("👥 Controle de Usuários e Permissões")
        
        if st.session_state.PERFIL_USUARIO != "administrador":
            st.warning("⚠️ Apenas administradores do sistema podem visualizar ou criar credenciais de acesso.")
        else:
            tu1, tu2 = st.tabs(["➕ Registrar Novo Operador", "✏️ Gestão de Usuários Ativos"])
            
            with tu1:
                with st.form("form_criacao_usuario", clear_on_submit=True):
                    st.write("### Novo Cadastro de Acesso")
                    u_nome = st.text_input("Nome Completo do Servidor:")
                    u_login = st.text_input("Login Único (Sem Espaços):")
                    u_email = st.text_input("E-mail Funcional Cadastrado:")
                    u_senha = st.text_input("Senha de Entrada Provisória:", type="password")
                    u_perf = st.selectbox("Perfil de Governança:", ["administrador", "usuario comum"])
                    
                    if st.form_submit_button("Gerar Credencial", type="primary"):
                        if u_nome and u_login and u_email and u_senha:
                            u_payload = {
                                "nome": u_nome.strip(),
                                "usuario": u_login.strip().lower(),
                                "email": u_email.strip().lower(),
                                "senha": u_senha.strip(),
                                "perfil": u_perf
                            }
                            if inserir_dados("usuarios", u_payload):
                                st.success("Novo operador cadastrado com sucesso!")
                                st.rerun()
                        else:
                            st.error("Todos os campos do formulário são obrigatórios.")

            with tu2:
                st.write("### Operadores Cadastrados no Ecossistema")
                if not df_usuarios.empty:
                    st.dataframe(df_usuarios[["id", "nome", "usuario", "email", "perfil"]], use_container_width=True, hide_index=True)
                    id_remover = st.selectbox("Escolha o ID do operador para revogação de acessos:", df_usuarios["id"].tolist())
                    if st.button("❌ Revogar Acesso do Usuário"):
                        if deletar_dados("usuarios", "id", int(id_remover)):
                            st.success("Acesso revogado do banco!")
                            st.rerun()

    # --- MÓDULO 5: GERENCIAMENTO DE COORDENAÇÕES SETORIAIS ---
    elif escolha == "🏢 Cadastrar Coordenação":
        st.title("🏢 Gestão de Setores e Coordenações (NGI Carajás)")
        
        if st.session_state.PERFIL_USUARIO != "administrador":
            st.warning("⚠️ Menu administrativo protegido.")
        else:
            col_co1, col_co2 = st.columns([1, 2])
            with col_co1:
                st.write("### Novo Setor Beneficiário")
                co_sigla = st.text_input("Sigla da Unidade (Ex: CMAN):")
                co_nome = st.text_input("Descrição Setorial por Extenso:")
                
                if st.button("Salvar Unidade Setorial", type="primary", use_container_width=True):
                    if co_sigla.strip() and co_nome.strip():
                        co_payload = {"sigla": co_sigla.strip().upper(), "nome": co_nome.strip()}
                        if inserir_dados("coordenacoes", co_payload):
                            st.success("Setor cadastrado!")
                            st.rerun()
                    else:
                        st.error("Preencha a sigla e o nome da coordenação.")
            with col_co2:
                st.write("### Coordenações Ativas")
                if not df_coordenacoes.empty:
                    st.dataframe(df_coordenacoes[["sigla", "nome"]], use_container_width=True, hide_index=True)
                    st.write("---")
                    id_co_del = st.selectbox("Remover Unidade Organizacional (ID):", df_coordenacoes["id"].tolist())
                    if st.button("❌ Deletar Coordenação"):
                        if deletar_dados("coordenacoes", "id", int(id_co_del)):
                            st.success("Coordenação removida.")
                            st.rerun()
                else:
                    st.info("Nenhum setor interno mapeado na base de dados.")

    # --- MÓDULO 6: LANÇAMENTOS E MOVIMENTAÇÃO DE ESTOQUE ---
    elif escolha == "🔄 Movimentação de Estoque":
        st.title("🔄 Registro de Movimentações de Entrada e Saída")
        
        tab_entrada, tab_saida, tab_historico = st.tabs(["📥 Entrada de Material", "📤 Saída de Insumo", "📜 Histórico Geral"])
        
        with tab_entrada:
            st.write("### Registro de Entrada / Incremento de Carga")
            if df_produtos.empty:
                st.warning("Nenhum material no catálogo para dar entrada.")
            else:
                with st.form("form_mov_entrada", clear_on_submit=True):
                    ent_prod = st.selectbox("Selecione o Insumo:", df_produtos["item"].tolist(), key="ent_p_sel")
                    ent_qtd = st.number_input("Quantidade Adquirida:", min_value=1, step=1, key="ent_q_num")
                    
                    if st.form_submit_button("Confirmar Entrada em Estoque", type="primary"):
                        row_p = df_produtos[df_produtos["item"] == ent_prod].iloc[0]
                        novo_calculo_qtd = int(row_p["quantidade"]) + ent_qtd
                        
                        if atualizar_dados("produtos", {"quantidade": novo_calculo_qtd}, "id", int(row_p["id"])):
                            mov_payload = {
                                "data": datetime.today().strftime("%d/%m/%Y"),
                                "tipo": "Entrada",
                                "codigo": str(row_p["codigo"]),
                                "item": ent_prod,
                                "quantidade": ent_qtd,
                                "responsavel": st.session_state.NOME_USUARIO_LOGADO,
                                "coordenacao": "Almoxarifado"
                            }
                            inserir_dados("movimentacoes", mov_payload)
                            st.success("Fluxo de entrada processado com sucesso!")
                            st.rerun()

        with tab_saida:
            st.write("### Registro de Saída / Baixa do Almoxarifado")
            if df_produtos.empty:
                st.warning("Sem materiais para movimentação externa.")
            else:
                with st.form("form_mov_saida", clear_on_submit=True):
                    sai_prod = st.selectbox("Selecione o Insumo para Retirada:", df_produtos["item"].tolist(), key="sai_p_sel")
                    sai_qtd = st.number_input("Quantidade Requisitada:", min_value=1, step=1, key="sai_q_num")
                    
                    lista_coord_siglas = df_coordenacoes["sigla"].tolist() if not df_coordenacoes.empty else ["Geral"]
                    sai_destino = st.selectbox("Setor Destinatário:", lista_coord_siglas)
                    sai_responsavel = st.text_input("Servidor Portador/Responsável pela Retirada:")
                    
                    if st.form_submit_button("Processar Baixa Patrimonial", type="primary"):
                        row_p_sai = df_produtos[df_produtos["item"] == sai_prod].iloc[0]
                        
                        if int(row_p_sai["quantidade"]) < sai_qtd:
                            st.error(f"Erro: Saldo Indisponível! Estoque atual: {row_p_sai['quantidade']} unidades.")
                        elif not sai_responsavel.strip():
                            st.error("Informe o nome do servidor responsável.")
                        else:
                            novo_calculo_qtd_sai = int(row_p_sai["quantidade"]) - sai_qtd
                            if atualizar_dados("produtos", {"quantidade": novo_calculo_qtd_sai}, "id", int(row_p_sai["id"])):
                                mov_payload_sai = {
                                    "data": datetime.today().strftime("%d/%m/%Y"),
                                    "tipo": "Saída",
                                    "codigo": str(row_p_sai["codigo"]),
                                    "item": sai_prod,
                                    "quantidade": sai_qtd,
                                    "responsavel": sai_responsavel.strip(),
                                    "coordenacao": sai_destino
                                }
                                inserir_dados("movimentacoes", mov_payload_sai)
                                st.success("Fluxo de saída processado com sucesso!")
                                st.rerun()

        with tab_historico:
            st.write("### Livro de Registros - Histórico Geral")
            if df_movimentacoes.empty:
                st.info("Nenhum lançamento no livro de registros.")
            else:
                st.dataframe(df_movimentacoes[["data", "tipo", "codigo", "item", "quantidade", "responsavel", "coordenacao"]], use_container_width=True, hide_index=True)

    # --- MÓDULO 7: PERFIL E ALTERAÇÃO DE SENHA ---
    elif escolha == "👤 Meu Perfil":
        st.title("👤 Configurações do Meu Perfil")
        st.write("Visualize seus dados funcionais e configure uma nova senha pessoal de segurança.")
        
        st.info("🔒 Para mudar sua senha, preencha o formulário e clique em atualizar.")
        with st.form("form_alteracao_senha_usuario"):
            st.text_input("Operador logado:", value=st.session_state.NOME_USUARIO_LOGADO, disabled=True)
            st.text_input("Conta de Login:", value=st.session_state.LOGIN_USUARIO_LOGADO, disabled=True)
            st.text_input("E-mail Cadastrado:", value=st.session_state.EMAIL_USUARIO_LOGADO, disabled=True)
            nova_senha = st.text_input("Nova Senha Operacional:", type="password", placeholder="Digite a nova senha")
            
            if st.form_submit_button("Atualizar Minha Senha", type="primary"):
                if nova_senha.strip():
                    # Busca o registro completo para encontrar a Id correta do usuário logado
                    usuarios_lista = buscar_dados("usuarios")
                    id_user = None
                    for u in usuarios_lista:
                        if u["usuario"].lower() == st.session_state.LOGIN_USUARIO_LOGADO.lower():
                            id_user = u["id"]
                            break
                    
                    if id_user and atualizar_dados("usuarios", {"senha": nova_senha.strip()}, "id", int(id_user)):
                        st.success("Sua senha corporativa foi modificada com sucesso!")
                else:
                    st.error("A nova senha não pode ficar em branco.")
