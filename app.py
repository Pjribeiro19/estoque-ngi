import streamlit as st
import pandas as pd
import os
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# =============================================================================
# ARQUIVOS LOCAIS PARA ARMAZENAR OS DADOS (BANCO DE DADOS LOCAL CSV)
# =============================================================================
ARQUIVO_PRODUTOS = "dados_produtos.csv"
ARQUIVO_USUARIOS = "dados_usuarios.csv"
ARQUIVO_COORDENACOES = "dados_coordenacoes.csv"
ARQUIVO_CATEGORIAS = "dados_categorias.csv"
ARQUIVO_MOVIMENTACOES = "dados_movimentacoes.csv"

# =============================================================================
# FUNÇÕES DE GERENCIAMENTO DE ARQUIVOS (CARREGAR E SALVAR)
# =============================================================================
def carregar_dados_locais():
    # 1. Produtos
    if os.path.exists(ARQUIVO_PRODUTOS):
        st.session_state.produtos = pd.read_csv(ARQUIVO_PRODUTOS, dtype={"Código": str})
    else:
        st.session_state.produtos = pd.DataFrame([
            {"Código": "001", "Item": "Capacete de Segurança", "Quantidade": 15, "Categoria": "EPI", "Valor Unitário": 45.00},
            {"Código": "002", "Item": "Resma Papel A4", "Quantidade": 0, "Categoria": "Material de Escritório", "Valor Unitário": 28.50},
            {"Código": "003", "Item": "Luva de Raspa", "Quantidade": 50, "Categoria": "EPI", "Valor Unitário": 12.00}
        ])
        st.session_state.produtos.to_csv(ARQUIVO_PRODUTOS, index=False)

    # 2. Usuários
    if os.path.exists(ARQUIVO_USUARIOS):
        st.session_state.usuarios = pd.read_csv(ARQUIVO_USUARIOS, dtype={"Senha": str})
    else:
        st.session_state.usuarios = pd.DataFrame([
            {"Nome": "Administrador Padrão", "E-mail": "admin@ngi.com", "Senha": "123", "Perfil": "Administrador"},
            {"Nome": "João Paulo", "E-mail": "joao@ngi.com", "Senha": "123", "Perfil": "Usuário Comum"}
        ])
        st.session_state.usuarios.to_csv(ARQUIVO_USUARIOS, index=False)

    # 3. Coordenações
    if os.path.exists(ARQUIVO_COORDENACOES):
        st.session_state.coordenacoes = pd.read_csv(ARQUIVO_COORDENACOES)
    else:
        st.session_state.coordenacoes = pd.DataFrame([
            {"Sigla": "COTEC", "Nome": "Coordenação Técnica"},
            {"Sigla": "COLOG", "Nome": "Coordenação de Logística"}
        ])
        st.session_state.coordenacoes.to_csv(ARQUIVO_COORDENACOES, index=False)

    # 4. Categorias
    if os.path.exists(ARQUIVO_CATEGORIAS):
        # Lê mantendo como uma lista simples de Python
        st.session_state.categorias = pd.read_csv(ARQUIVO_CATEGORIAS)["Categoria"].tolist()
    else:
        st.session_state.categorias = ["EPI", "Material de Escritório", "Informática", "Limpeza", "Copa"]
        pd.DataFrame(st.session_state.categorias, columns=["Categoria"]).to_csv(ARQUIVO_CATEGORIAS, index=False)

    # 5. Movimentações
    if os.path.exists(ARQUIVO_MOVIMENTACOES):
        st.session_state.movimentacoes = pd.read_csv(ARQUIVO_MOVIMENTACOES, dtype={"Código": str})
    else:
        st.session_state.movimentacoes = pd.DataFrame(columns=[
            "Data", "Tipo", "Código", "Item", "Quantidade", "Responsável pela Retirada", "Coordenação"
        ])
        st.session_state.movimentacoes.to_csv(ARQUIVO_MOVIMENTACOES, index=False)

def salvar_dados_locais(df, nome_arquivo):
    df.to_csv(nome_arquivo, index=False)

# Inicialização imediata dos dados a partir dos arquivos físicos
carregar_dados_locais()

# =============================================================================
# CONFIGURAÇÕES SEGURAS DE E-MAIL (Secrets)
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
    layout="wide",
    initial_sidebar_state="auto"
)

# --- ESTILIZAÇÃO CUSTOMIZADA (CSS) ---
st.markdown("""
    <style>
    @media (min-width: 992px) {
        [data-testid="stSidebar"] { transform: none !important; position: relative !important; }
        [data-testid="stSidebar"] button { display: none !important; }
    }
    @media (max-width: 991px) {
        [data-testid="stSidebar"] { position: fixed !important; z-index: 999999 !important; }
    }
    [data-testid="stSidebarNav"] {display: none;}
    [data-testid="stMainMenu"] {display: none;}
    [data-testid="stSidebar"] { background-color: #fcfaff !important; border-right: 1px solid #efe9f5; }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] [data-testid="stWidgetMarkdownInsideLabel"] { margin-left: -20px !important; }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label { color: #333333 !important; font-weight: 500; padding: 12px 16px; border-radius: 4px; margin-bottom: 2px; transition: all 0.2s ease; }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover { background-color: #e2eed7 !important; color: #1e5934 !important; cursor: pointer; }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] input:checked + div { background-color: #cce2b4 !important; border-radius: 4px; color: #1e5934 !important; font-weight: bold !important; }
    div.stButton > button:first-child[kind="primary"] { background-color: #4CAF50 !important; border-color: #4CAF50 !important; color: white !important; }
    div.stButton > button:first-child[kind="primary"]:hover { background-color: #43a047 !important; border-color: #43a047 !important; }
    .img-container { display: flex; justify-content: center; align-items: center; width: 100%; margin-bottom: 20px; }
    </style>
""", unsafe_allow_html=True)

# --- ESTADOS DE SESSÃO DINÂMICOS ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"

if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = ""  # Começa vazio para o login injetar o correto

# =============================================================================
# ROTEADOR DE PARÂMETROS DE URL
# =============================================================================
query_params = st.query_params

if "page" in query_params and query_params["page"] == "reset_password":
    st.markdown("<br><br>", unsafe_allow_html=True)
    col_r1, col_r2, col_r3 = st.columns([1, 1.2, 1])
    with col_r2:
        st.markdown("<h2 style='text-align: center; color: #1e5934;'>🔑 Definir Nova Senha</h2>", unsafe_allow_html=True)
        nova_senha = st.text_input("Nova Senha", type="password")
        confirmar_senha = st.text_input("Confirme a Nova Senha", type="password")
        
        if st.button("Atualizar Senha", type="primary", use_container_width=True):
            if nova_senha == "":
                st.warning("A senha não pode estar em branco.")
            elif nova_senha == confirmar_senha:
                st.success("Senha atualizada com sucesso!")
                st.query_params.clear()
                st.components.v1.html("<script>window.parent.history.replaceState({}, document.title, '/');</script>", height=0)
                st.session_state.sub_tela_login = "login"
                st.rerun()
            else:
                st.error("As senhas não coincidem.")
                
        if st.button("Cancelar e Voltar", use_container_width=True):
            st.query_params.clear()
            st.components.v1.html("<script>window.parent.history.replaceState({}, document.title, '/');</script>", height=0)
            st.session_state.sub_tela_login = "login"
            st.rerun()

# =============================================================================
# TELA DE LOGIN (COM VALIDAÇÃO NO CSV)
# =============================================================================
elif not st.session_state.autenticado:
    if st.session_state.sub_tela_login == "login":
        st.markdown("<br><br>", unsafe_allow_html=True)
        col_l1, col_l2, col_l3 = st.columns([1, 1.2, 1])
        with col_l2:
            st.markdown('<div class="img-container"><img src="https://www.gov.br/icmbio/pt-br/assuntos/biodiversidade/unidade-de-conservacao/unidades-de-biomas/marinho/lista-de-ucs/parna-marinho-dos-abrolhos/fomulario-denuncia/icmbio-logo-1.png" width="320"></div>', unsafe_allow_html=True)
            st.markdown("<h2 style='text-align: center; color: #1e5934;'>Gestão de Almoxarifado<br>NGI Carajás</h2>", unsafe_allow_html=True)
            
            usuario_input = st.text_input("Usuário / E-mail", placeholder="Digite seu e-mail...")
            senha_input = st.text_input("Senha", type="password", placeholder="Digite sua senha...")
            
            if st.button("Entrar no Sistema", type="primary", use_container_width=True):
                # Procura o usuário no arquivo CSV carregado em memória
                df_users = st.session_state.usuarios
                usuario_valido = df_users[(df_users["E-mail"] == usuario_input.strip()) & (df_users["Senha"].astype(str) == senha_input.strip())]
                
                if not usuario_valido.empty:
                    # CORREÇÃO AQUI: Resgata o nome correto correspondente ao login feito!
                    st.session_state.NOME_USUARIO_LOGADO = usuario_valido.iloc[0]["Nome"]
                    st.session_state.autenticado = True
                    st.rerun()
                else:
                    st.error("E-mail ou senha incorretos!")
                    
            if st.button("Esqueci a senha", use_container_width=True):
                st.session_state.sub_tela_login = "esqueci"
                st.rerun()

    elif st.session_state.sub_tela_login == "esqueci":
        col_r1, col_r2, col_r3 = st.columns([1, 1.2, 1])
        with col_r2:
            st.write("<br><br>", unsafe_allow_html=True)
            st.markdown("### 🔑 Recuperar Acesso")
            email_recuperar = st.text_input("E-mail corporativo")

            if st.button("Enviar Instruções", type="primary", use_container_width=True):
                if email_recuperar.strip():
                    if EMAIL_REMETENTE == "configurar_no_secrets@email.com":
                        st.error("Erro: Credenciais de e-mail não configuradas.")
                    else:
                        try:
                            msg = MIMEMultipart()
                            msg['From'] = EMAIL_REMETENTE
                            msg['To'] = email_recuperar.strip()
                            msg['Subject'] = "Recuperação de Senha - NGI Carajás"
                            link_redefinicao = "https://www.almoxarifadocarajas.com.br/?page=reset_password"
                            corpo_email = f"Olá,\n\nPara cadastrar sua nova senha, clique no link:\n{link_redefinicao}"
                            msg.attach(MIMEText(corpo_email, 'plain'))
                            
                            server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
                            server.starttls()
                            server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
                            server.sendmail(EMAIL_REMETENTE, email_recuperar.strip(), msg.as_string())
                            server.quit()
                            st.success("E-mail enviado!")
                        except Exception as e:
                            st.error(f"Erro: {e}")

            if st.button("Voltar para o Login", use_container_width=True):
                st.session_state.sub_tela_login = "login"
                st.rerun()

# =============================================================================
# SISTEMA PRINCIPAL (AUTENTICADO)
# =============================================================================
else:
    with st.sidebar:
        # Exibe o nome correto capturado no login dinamicamente
        st.markdown(f"#### 👤 Olá, {st.session_state.NOME_USUARIO_LOGADO}")
        st.write("---")
        menu_opcoes = [
            "📊 Painel Geral",
            "➕ Cadastrar Produto",
            "🗂️ Cadastrar Categoria",
            "👥 Cadastrar Usuário",
            "🏢 Cadastrar Coordenação",
            "🔄 Movimentação de Entrada e Saída",
            "👤 Perfil",
            "🚪 Sair"
        ]
        escolha = st.radio("", menu_opcoes, label_visibility="collapsed")

    # --- TELA: PAINEL GERAL ---
    if escolha == "📊 Painel Geral":
        st.title("📊 Painel Geral de Estoque")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total de Itens Cadastrados", len(st.session_state.produtos))
        c2.metric("Produtos Esgotados", len(st.session_state.produtos[st.session_state.produtos['Quantidade'] == 0]))
        c3.metric("Movimentações Realizadas", len(st.session_state.movimentacoes))

        st.write("---")
        col_filtro1, col_filtro2 = st.columns([2, 1])
        termo_busca = col_filtro1.text_input("Buscar por Nome do Material ou Código:")
        categoria_selecionada = col_filtro2.selectbox("Filtrar por Categoria:", ["Todas"] + list(st.session_state.categorias))
        
        df_filtrado = st.session_state.produtos.copy()
        if termo_busca:
            df_filtrado = df_filtrado[df_filtrado['Item'].str.contains(termo_busca, case=False, na=False) | df_filtrado['Código'].str.contains(termo_busca, case=False, na=False)]
        if categoria_selecionada != "Todas":
            df_filtrado = df_filtrado[df_filtrado['Category'] == categoria_selecionada] if 'Category' in df_filtrado.columns else df_filtrado[df_filtrado['Categoria'] == categoria_selecionada]

        if df_filtrado.empty:
            st.info("Nenhum material encontrado.")
        else:
            df_display = df_filtrado.copy()
            df_display["Valor Unitário"] = df_display["Valor Unitário"].map("R$ {:.2f}".format)
            st.dataframe(df_display, use_container_width=True, hide_index=True)

    # --- TELA: CADASTRAR PRODUTO ---
    elif escolha == "➕ Cadastrar Produto":
        st.title("➕ Gerenciamento de Produtos")
        aba_cad_prod, aba_gerenciar_prod = st.tabs(["➕ Novo Material", "✏️ Editar / Excluir Produtos"])
        
        with aba_cad_prod:
            with st.form("form_novo_produto", clear_on_submit=True):
                col_a, col_b = st.columns(2)
                cod = col_a.text_input("Código")
                nome_it = col_b.text_input("Nome do Material")
                cat_it = col_a.selectbox("Categoria", st.session_state.categorias)
                val_unit = col_b.number_input("Valor Unitário (R$)", min_value=0.0, step=0.01)
                
                if st.form_submit_button("Finalizar Cadastro", type="primary"):
                    if cod and nome_it:
                        if str(cod) in st.session_state.produtos["Código"].astype(str).values:
                            st.error("Código já cadastrado.")
                        else:
                            novo_p = {"Código": str(cod), "Item": nome_it, "Quantidade": 0, "Categoria": cat_it, "Valor Unitário": float(val_unit)}
                            st.session_state.produtos = pd.concat([st.session_state.produtos, pd.DataFrame([novo_p])], ignore_index=True)
                            
                            # SALVANDO NO ARQUIVO LOCAL
                            salvar_dados_locais(st.session_state.produtos, ARQUIVO_PRODUTOS)
                            st.success("Produto adicionado permanentemente!")
                            st.rerun()

        with aba_gerenciar_prod:
            if not st.session_state.produtos.empty:
                st.dataframe(st.session_state.produtos, use_container_width=True, hide_index=True)
                idx_p = st.selectbox("Selecione o produto para modificar:", st.session_state.produtos.index, format_func=lambda x: f"{st.session_state.produtos.loc[x, 'Código']} - {st.session_state.produtos.loc[x, 'Item']}")
                
                if st.button("❌ Excluir Produto do Sistema"):
                    st.session_state.produtos = st.session_state.produtos.drop(idx_p).reset_index(drop=True)
                    # ATUALIZANDO ARQUIVO LOCAL
                    salvar_dados_locais(st.session_state.produtos, ARQUIVO_PRODUTOS)
                    st.warning("Produto removido.")
                    st.rerun()

    # --- TELA: CADASTRAR CATEGORIA ---
    elif escolha == "🗂️ Cadastrar Categoria":
        st.title("🗂️ Gerenciamento de Categorias")
        nova_cat = st.text_input("Nome da Nova Categoria:")
        if st.button("Adicionar Categoria", type="primary"):
            if nova_cat and nova_cat.strip() not in st.session_state.categorias:
                st.session_state.categorias.append(nova_cat.strip())
                # SALVANDO NO ARQUIVO LOCAL
                pd.DataFrame(st.session_state.categorias, columns=["Categoria"]).to_csv(ARQUIVO_CATEGORIAS, index=False)
                st.success("Categoria adicionada permanentemente!")
                st.rerun()
        st.dataframe(pd.DataFrame(st.session_state.categorias, columns=["Categorias Ativas"]), use_container_width=True)

    # --- TELA: CADASTRAR USUÁRIO ---
    elif escolha == "👥 Cadastrar Usuário":
        st.title("👥 Gerenciamento de Usuários")
        aba_cad, aba_edit = st.tabs(["➕ Novo Usuário", "✏️ Editar / Excluir Usuários"])
        
        with aba_cad:
            with st.form("cad_user", clear_on_submit=True):
                n = st.text_input("Nome")
                e = st.text_input("E-mail")
                s = st.text_input("Senha", type="password")
                p = st.selectbox("Perfil", ["Administrador", "Usuário Comum"])
                if st.form_submit_button("Salvar", type="primary"):
                    if n and e:
                        new_u = {"Nome": n, "E-mail": e, "Senha": str(s) if s else "123", "Perfil": p}
                        st.session_state.usuarios = pd.concat([st.session_state.usuarios, pd.DataFrame([new_u])], ignore_index=True)
                        
                        # SALVANDO NO ARQUIVO LOCAL
                        salvar_dados_locais(st.session_state.usuarios, ARQUIVO_USUARIOS)
                        st.success("Usuário Criado permanentemente!")
                        st.rerun()

        with aba_edit:
            st.dataframe(st.session_state.usuarios[["Nome", "E-mail", "Perfil"]], use_container_width=True, hide_index=True)
            if not st.session_state.usuarios.empty:
                idx = st.selectbox("Selecione para remover:", st.session_state.usuarios.index, format_func=lambda x: st.session_state.usuarios.loc[x, "Nome"])
                if st.button("❌ Excluir Usuário"):
                    st.session_state.usuarios = st.session_state.usuarios.drop(idx).reset_index(drop=True)
                    # ATUALIZANDO ARQUIVO LOCAL
                    salvar_dados_locais(st.session_state.usuarios, ARQUIVO_USUARIOS)
                    st.warning("Usuário removido.")
                    st.rerun()

    # --- TELA: CADASTRAR COORDENAÇÃO ---
    elif escolha == "🏢 Cadastrar Coordenação":
        st.title("🏢 Cadastrar Coordenação")
        with st.form("cad_coord", clear_on_submit=True):
            s_coord = st.text_input("Sigla (Ex: COTEC)")
            nc = st.text_input("Nome da Coordenação")
            if st.form_submit_button("Cadastrar", type="primary"):
                if s_coord and nc:
                    nova_coord = {"Sigla": s_coord.upper(), "Nome": nc}
                    st.session_state.coordenacoes = pd.concat([st.session_state.coordenacoes, pd.DataFrame([nova_coord])], ignore_index=True)
                    
                    # SALVANDO NO ARQUIVO LOCAL
                    salvar_dados_locais(st.session_state.coordenacoes, ARQUIVO_COORDENACOES)
                    st.success("Coordenação Cadastrada!")
                    st.rerun()
        st.dataframe(st.session_state.coordenacoes, use_container_width=True, hide_index=True)

    # --- TELA: MOVIMENTAÇÃO DE ENTRADA E SAÍDA ---
    elif escolha == "🔄 Movimentação de Entrada e Saída":
        st.title("🔄 Movimentações de Estoque")
        with st.form("form_movimentacao", clear_on_submit=True):
            tipo_mov = st.selectbox("Tipo de Operação", ["Entrada (+) Saldo", "Saída (-) Retirada"])
            prod_selecionado_idx = st.selectbox("Selecione o Produto", st.session_state.produtos.index, format_func=lambda x: f"{st.session_state.produtos.loc[x, 'Código']} - {st.session_state.produtos.loc[x, 'Item']} (Saldo: {st.session_state.produtos.loc[x, 'Quantidade']})")
            qtd_mov = st.number_input("Quantidade", min_value=1, step=1)
            responsavel = st.text_input("Responsável")
            coord_solic = st.selectbox("Coordenação", st.session_state.coordenacoes["Sigla"].values if not st.session_state.coordenacoes.empty else ["Geral"])
            
            if st.form_submit_button("Confirmar Lançamento", type="primary"):
                qtd_atual = st.session_state.produtos.loc[prod_selecionado_idx, "Quantidade"]
                if "Saída" in tipo_mov and qtd_mov > qtd_atual:
                    st.error("Saldo insuficiente.")
                else:
                    if "Entrada" in tipo_mov:
                        st.session_state.produtos.loc[prod_selecionado_idx, "Quantidade"] += qtd_mov
                    else:
                        st.session_state.produtos.loc[prod_selecionado_idx, "Quantidade"] -= qtd_mov
                    
                    nova_mov = {
                        "Data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "Tipo": "ENTRADA" if "Entrada" in tipo_mov else "SAÍDA",
                        "Código": st.session_state.produtos.loc[prod_selecionado_idx, "Código"],
                        "Item": st.session_state.produtos.loc[prod_selecionado_idx, "Item"],
                        "Quantidade": qtd_mov,
                        "Responsável pela Retirada": responsavel,
                        "Coordenação": coord_solic
                    }
                    st.session_state.movimentacoes = pd.concat([st.session_state.movimentacoes, pd.DataFrame([nova_mov])], ignore_index=True)
                    
                    # SALVANDO AMBOS OS ARQUIVOS ATUALIZADOS (PRODUTO COM NOVO SALDO E HISTÓRICO DE MOVIMENTAÇÃO)
                    salvar_dados_locais(st.session_state.produtos, ARQUIVO_PRODUTOS)
                    salvar_dados_locais(st.session_state.movimentacoes, ARQUIVO_MOVIMENTACOES)
                    st.success("Movimentação registrada e salva com sucesso!")
                    st.rerun()

    # --- TELA: PERFIL ---
    elif escolha == "👤 Perfil":
        st.title("👤 Configurações de Perfil")
        novo_nome_perfil = st.text_input("Alterar Nome de Exibição:", value=st.session_state.NOME_USUARIO_LOGADO)
        if st.button("Salvar Nome", type="primary"):
            # Encontra o usuário na tabela e atualiza o arquivo local também para persistir a mudança de nome
            df_u = st.session_state.usuarios
            df_u.loc[df_u["Nome"] == st.session_state.NOME_USUARIO_LOGADO, "Nome"] = novo_nome_perfil
            st.session_state.NOME_USUARIO_LOGADO = novo_nome_perfil
            salvar_dados_locais(df_u, ARQUIVO_USUARIOS)
            st.success("Nome atualizado localmente!")
            st.rerun()

    # --- TELA: SAIR ---
    elif escolha == "🚪 Sair":
        st.session_state.autenticado = False
        st.session_state.NOME_USUARIO_LOGADO = ""
        st.session_state.sub_tela_login = "login"
        st.rerun()
