import streamlit as st
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# =============================================================================
# CONFIGURAÇÕES SEGURAS DE E-MAIL (Puxando dos Secrets do Streamlit)
# =============================================================================
try:
    EMAIL_REMETENTE = st.secrets["gmail"]["email"]
    SENHA_REMETENTE = st.secrets["gmail"]["senha_app"]
except:
    # Fallback caso esteja rodando localmente e ainda não tenha configurado o secrets local
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

# --- FORÇA A BARRA LATERAL A FICAR SEMPRE ABERTA NO CELULAR ---
st.markdown("""
    <style>
    /* Desativa o fechamento automático da Sidebar em telas menores */
    @media (max-width: 991px) {
        [data-testid="stSidebar"] {
            transform: none !important;
            position: relative !important;
            min-width: 250px !important;
            max-width: 250px !important;
            display: block !important;
        }
        
        /* Esconde o botão de fechar/setinha */
        [data-testid="stSidebar"] button {
            display: none !important;
        }
        
        /* Ajusta o contêiner principal para dividir espaço horizontalmente */
        .main {
            flex-direction: row !important;
        }
        
        /* Força o contêiner de conteúdo a ocupar o restante da tela */
        [data-testid="stAppViewBlockContainer"] {
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            min-width: calc(100vw - 250px) !important;
        }
    }

    /* Esconde elementos nativos do Streamlit */
    [data-testid="stSidebarNav"] {display: none;}
    [data-testid="stMainMenu"] {display: none;}
    
    /* Customização estética dos botões do menu lateral */
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
    
    /* Botões Padrão Verde */
    div.stButton > button:first-child[kind="primary"] {
        background-color: #4CAF50 !important;
        border-color: #4CAF50 !important;
        color: white !important;
    }
    div.stButton > button:first-child[kind="primary"]:hover {
        background-color: #43a047 !important;
        border-color: #43a047 !important;
    }
    
    /* Centralizador dos logotipos */
    .img-container {
        display: flex;
        justify-content: center;
        align-items: center;
        width: 100%;
        margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)


# --- INICIALIZAÇÃO DO GERENCIAMENTO DE SESSÃO (LOGIN) ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"

if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = "João Paulo"


# =============================================================================
# ROTEADOR DE PARÂMETROS DE URL (CAPTURAR LINK DO E-MAIL)
# =============================================================================
query_params = st.query_params

# Se o link contiver '?page=reset_password', força a tela de nova senha independente de login
if "page" in query_params and query_params["page"] == "reset_password":
    st.markdown("<br><br>", unsafe_allow_html=True)
    col_r1, col_r2, col_r3 = st.columns([1, 1.2, 1])
    with col_r2:
        st.markdown("<h2 style='text-align: center; color: #1e5934;'>🔑 Definir Nova Senha</h2>", unsafe_allow_html=True)
        st.markdown("<p style='font-size: 0.9rem; color: gray; text-align: center;'>Insira e confirme sua nova senha de acesso abaixo.</p>", unsafe_allow_html=True)
        
        nova_senha = st.text_input("Nova Senha", type="password", placeholder="Digite a nova senha...")
        confirmar_senha = st.text_input("Confirme a Nova Senha", type="password", placeholder="Digite a senha novamente...")
        
        if st.button("Atualizar Senha", type="primary", use_container_width=True):
            if nova_senha == "":
                st.warning("A senha não pode estar em branco.")
            elif nova_senha == confirmar_senha:
                # 💡 AQUI ENTRA SUA ATUALIZAÇÃO NO BANCO DE DADOS SE HOUVER
                st.success("Senha atualizada com sucesso!")
                st.query_params.clear() # Limpa a URL (?page=reset_password)
                st.session_state.sub_tela_login = "login"
                st.button("Ir para o Login")
            else:
                st.error("As senhas não coincidem. Tente novamente.")
                
        if st.button("Cancelar e Voltar", use_container_width=True):
            st.query_params.clear()
            st.session_state.sub_tela_login = "login"
            st.rerun()

# =============================================================================
# FLUXO 1: FLUXO DE LOGIN (SE NÃO ESTIVER AUTENTICADO E NÃO ESTIVER REDEFININDO)
# =============================================================================
elif not st.session_state.autenticado:
    
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
            
            usuario_input = st.text_input("Usuário / E-mail", placeholder="Digite seu usuário...")
            senha_input = st.text_input("Senha", type="password", placeholder="Digite sua senha...")
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Entrar no Sistema", type="primary", use_container_width=True):
                if usuario_input and senha_input:
                    st.session_state.autenticado = True
                    st.rerun()
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
            st.markdown("<p style='font-size: 0.9rem; color: gray;'>Insira seu e-mail corporativo cadastrado para recuperar a senha.</p>", unsafe_allow_html=True)
            email_recuperar = st.text_input("E-mail corporativo", placeholder="exemplo@icmbio.gov.br")

            if st.button("Enviar Instruções", type="primary", use_container_width=True):
                if email_recuperar.strip():
                    if EMAIL_REMETENTE == "configurar_no_secrets@email.com":
                        st.error("Erro de configuração: As credenciais de e-mail não foram inseridas nos Secrets do Streamlit.")
                    else:
                        try:
                            msg = MIMEMultipart()
                            msg['From'] = EMAIL_REMETENTE
                            msg['To'] = email_recuperar.strip()
                            msg['Subject'] = "Recuperação de Senha - Sistema de Almoxarifado NGI Carajás"
                            
                            # O link agora envia o parâmetro ?page=reset_password para ativar a tela correta
                            link_redefinicao = "https://almoxarifado-carajas.streamlit.app/?page=reset_password"
                            
                            corpo_email = f"""
                            Olá,
                            
                            Recebemos uma solicitação de recuperação de acesso para o seu usuário ({email_recuperar.strip()}).
                            
                            Para cadastrar sua nova senha de acesso, clique no link seguro abaixo:
                            {link_redefinicao}
                            
                            Se você não solicitou esta alteração, por favor ignore este e-mail.
                            
                            Atenciosamente,
                            Suporte NGI Carajás / ICMBio
                            """
                            msg.attach(MIMEText(corpo_email, 'plain'))
                            
                            # Processo de envio via SMTP seguro
                            server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
                            server.starttls()
                            server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
                            server.sendmail(EMAIL_REMETENTE, email_recuperar.strip(), msg.as_string())
                            server.quit()
                            
                            st.success(f"Sucesso! O link de redefinição foi enviado para {email_recuperar}")
                        except Exception as e:
                            st.error(f"Erro ao tentar enviar o e-mail: {e}")
                else:
                    st.warning("Por favor, digite um e-mail válido.")

            if st.button("Voltar para o Login", use_container_width=True):
                st.session_state.sub_tela_login = "login"
                st.rerun()


# =============================================================================
# FLUXO 2: SISTEMA PRINCIPAL (APÓS ESTAR AUTENTICADO)
# =============================================================================
else:
    # -----------------------------------------------------------------------------
    # BANCO DE DADOS EM MEMÓRIA
    # -----------------------------------------------------------------------------
    if "produtos" not in st.session_state or not isinstance(st.session_state.produtos, pd.DataFrame):
        st.session_state.produtos = pd.DataFrame([
            {"Código": "001", "Item": "Capacete de Segurança", "Quantidade": 15, "Categoria": "EPI", "Valor Unitário": 45.00},
            {"Código": "002", "Item": "Resma Papel A4", "Quantidade": 0, "Categoria": "Material de Escritório", "Valor Unitário": 28.50},
            {"Código": "003", "Item": "Luva de Raspa", "Quantidade": 50, "Categoria": "EPI", "Valor Unitário": 12.00}
        ])

    if "usuarios" not in st.session_state or not isinstance(st.session_state.usuarios, pd.DataFrame):
        st.session_state.usuarios = pd.DataFrame([
            {"Nome": "Administrador Padrão", "E-mail": "admin@ngi.com", "Senha": "123", "Perfil": "Administrador"}
        ])

    if "coordenacoes" not in st.session_state or not isinstance(st.session_state.coordenacoes, pd.DataFrame):
        st.session_state.coordenacoes = pd.DataFrame([
            {"Sigla": "COTEC", "Nome": "Coordenação Técnica"},
            {"Sigla": "COLOG", "Nome": "Coordenação de Logística"}
        ])

    if "categorias" not in st.session_state or not isinstance(st.session_state.categorias, list):
        st.session_state.categorias = ["EPI", "Material de Escritório", "Informática", "Limpeza", "Copa"]

    if "movimentacoes" not in st.session_state or not isinstance(st.session_state.movimentacoes, pd.DataFrame):
        st.session_state.movimentacoes = pd.DataFrame(columns=[
            "Data", "Tipo", "Código", "Item", "Quantidade", "Responsável pela Retirada", "Coordenação"
        ])

    # -----------------------------------------------------------------------------
    # BARRA LATERAL (MENU DE NAVEGAÇÃO COMPLETO)
    # -----------------------------------------------------------------------------
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

    # -----------------------------------------------------------------------------
    # LÓGICA DAS TELAS DO PAINEL LOGADO
    # -----------------------------------------------------------------------------

    # --- TELA: PAINEL GERAL ---
    if escolha == "🎛️ Painel Geral":
        st.title("🎛️ Painel Geral de Estoque")
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total de Itens Cadastrados", len(st.session_state.produtos))
        c2.metric("Produtos Esgotados", len(st.session_state.produtos[st.session_state.produtos['Quantidade'] == 0]))
        c3.metric("Movimentações Realizadas", len(st.session_state.movimentacoes))

        st.write("---")
        st.write("### 🔍 Ferramentas de Busca e Filtro")
        
        col_filtro1, col_filtro2 = st.columns([2, 1])
        termo_busca = col_filtro1.text_input("Buscar por Nome do Material ou Código:", placeholder="Digite para pesquisar...")
        categoria_selecionada = col_filtro2.selectbox("Filtrar por Categoria:", ["Todas"] + list(st.session_state.categorias))
        
        df_filtrado = st.session_state.produtos.copy()
            
        if termo_busca:
            df_filtrado = df_filtrado[
                df_filtrado['Item'].str.contains(termo_busca, case=False, na=False) | 
                df_filtrado['Código'].str.contains(termo_busca, case=False, na=False)
            ]
            
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
            
            df_estilizado = df_display.style.apply(destacar_zerados, axis=1)
            st.dataframe(df_estilizado, use_container_width=True, hide_index=True)

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
                val_unit = col_b.number_input("Valor Unitário (R$)", min_value=0.0, step=0.01, format="%.2f")
                
                st.caption("ℹ️ Novos materiais são registrados com saldo inicial 0. Para adicionar quantidades, utilize o menu 'Movimentação de Entrada e Saída'.")
                
                if st.form_submit_button("Finalizar Cadastro", type="primary"):
                    if cod and nome_it:
                        if cod in st.session_state.produtos["Código"].values:
                            st.error(f"Erro! Já existe um produto cadastrado com o código {cod}.")
                        else:
                            novo_p = {"Código": cod, "Item": nome_it, "Quantidade": 0, "Categoria": cat_it, "Valor Unitário": float(val_unit)}
                            st.session_state.produtos = pd.concat([st.session_state.produtos, pd.DataFrame([novo_p])], ignore_index=True)
                            st.success(f"Sucesso! {nome_it} adicionado ao catálogo com saldo zerado.")
                            st.rerun()
                    else:
                        st.error("Preencha o Código e o Nome do Material!")
                        
        with aba_gerenciar_prod:
            if not st.session_state.produtos.empty:
                st.dataframe(st.session_state.produtos, use_container_width=True, hide_index=True)
                st.write("---")
                idx_p = st.selectbox(
                    "Selecione o produto que deseja modificar:", 
                    st.session_state.produtos.index, 
                    format_func=lambda x: f"{st.session_state.produtos.loc[x, 'Código']} - {st.session_state.produtos.loc[x, 'Item']}"
                )
                col_ed1, col_ed2 = st.columns(2)
                edit_cod = col_ed1.text_input("Código do Produto:", value=st.session_state.produtos.loc[idx_p, "Código"])
                edit_item = col_ed2.text_input("Nome do Material:", value=st.session_state.produtos.loc[idx_p, "Item"])
                edit_qtd = col_ed1.number_input("Quantidade em Estoque (Ajuste Manual):", min_value=0, step=1, value=int(st.session_state.produtos.loc[idx_p, "Quantidade"]))
                
                cat_atual = st.session_state.produtos.loc[idx_p, "Categoria"]
                default_cat_idx = st.session_state.categorias.index(cat_atual) if cat_atual in st.session_state.categorias else 0
                edit_cat = col_ed2.selectbox("Categoria do Produto:", st.session_state.categorias, index=default_cat_idx)
                edit_val = st.number_input("Alterar Valor Unitário (R$):", min_value=0.0, step=0.01, format="%.2f", value=float(st.session_state.produtos.loc[idx_p, "Valor Unitário"]))
                
                col_b_prod1, col_b_prod2 = st.columns([1, 4])
                with col_b_prod1:
                    if st.button("Salvar Alterações", type="primary"):
                        st.session_state.produtos.loc[idx_p, "Código"] = edit_cod
                        st.session_state.produtos.loc[idx_p, "Item"] = edit_item
                        st.session_state.produtos.loc[idx_p, "Quantidade"] = edit_qtd
                        st.session_state.produtos.loc[idx_p, "Categoria"] = edit_cat
                        st.session_state.produtos.loc[idx_p, "Valor Unitário"] = float(edit_val)
                        st.success("Produto atualizado!")
                        st.rerun()
                with col_b_prod2:
                    if st.button("❌ Excluir Produto do Sistema"):
                        st.session_state.produtos = st.session_state.produtos.drop(idx_p).reset_index(drop=True)
                        st.warning("Produto removido definitivamente.")
                        st.rerun()

    # --- TELA: CADASTRAR CATEGORIA ---
    elif escolha == "🗂️ Cadastrar Categoria":
        st.title("🗂️ Gerenciamento de Categorias")
        aba_nova_cat, aba_gerenciar_cat = st.tabs(["➕ Nova Categoria", "✏️ Editar / Excluir Categorias"])
        
        with aba_nova_cat:
            col_cat1, col_cat2 = st.columns([1, 2])
            with col_cat1:
                nova_cat = st.text_input("Nome da Nova Categoria:")
                if st.button("Adicionar Categoria", type="primary"):
                    if nova_cat and nova_cat.strip() not in st.session_state.categorias:
                        st.session_state.categorias.append(nova_cat.strip())
                        st.success("Categoria adicionada!")
                        st.rerun()
            with col_cat2:
                st.dataframe(pd.DataFrame(st.session_state.categorias, columns=["Categorias Ativas"]), use_container_width=True, hide_index=True)

        with aba_gerenciar_cat:
            if st.session_state.categorias:
                cat_selecionada_idx = st.selectbox("Selecione qual deseja modificar/excluir:", range(len(st.session_state.categorias)), format_func=lambda x: st.session_state.categorias[x])
                nome_antigo_cat = st.session_state.categorias[cat_selecionada_idx]
                edit_nome_cat = st.text_input("Editar Nome:", value=nome_antigo_cat)
                
                c_btn_cat1, c_btn_cat2 = st.columns([1, 4])
                with c_btn_cat1:
                    if st.button("Salvar Edição", type="primary"):
                        st.session_state.categorias[cat_selecionada_idx] = edit_nome_cat.strip()
                        st.success("Atualizado!")
                        st.rerun()
                with c_btn_cat2:
                    if st.button("❌ Excluir Categoria"):
                        st.session_state.categorias.pop(cat_selecionada_idx)
                        st.warning("Categoria removida do sistema.")
                        st.rerun()

    # --- TELA: CADASTRAR USUÁRIO ---
    elif escolha == "👥 Cadastrar Usuário":
        st.title("👥 Cadastrar Usuário")
        aba_cad, aba_edit = st.tabs(["➕ Novo Usuário", "✏️ Editar / Excluir Usuários"])
        
        with aba_cad:
            with st.form("cad_user", clear_on_submit=True):
                n = st.text_input("Nome")
                e = st.text_input("E-mail")
                s = st.text_input("Senha de Acesso", type="password")
                p = st.selectbox("Perfil", ["Administrador", "Usuário Comum"])
                if st.form_submit_button("Salvar", type="primary"):
                    if n and e:
                        new_u = {"Nome": n, "E-mail": e, "Senha": s if s else "123", "Perfil": p}
                        st.session_state.usuarios = pd.concat([st.session_state.usuarios, pd.DataFrame([new_u])], ignore_index=True)
                        st.success("Usuário Criado!")
                        st.rerun()
                    else:
                        st.error("Nome e E-mail são obrigatórios.")

        with aba_edit:
            if not st.session_state.usuarios.empty:
                st.dataframe(st.session_state.usuarios[["Nome", "E-mail", "Perfil"]], use_container_width=True, hide_index=True)
                idx = st.selectbox("Selecione para modificar/excluir:", st.session_state.usuarios.index, format_func=lambda x: st.session_state.usuarios.loc[x, "Nome"])
                edit_n = st.text_input("Nome:", value=st.session_state.usuarios.loc[idx, "Nome"])
                edit_e = st.text_input("E-mail:", value=st.session_state.usuarios.loc[idx, "E-mail"])
                edit_s = st.text_input("Alterar Senha:", value=st.session_state.usuarios.loc[idx, "Senha"] if "Senha" in st.session_state.usuarios.columns else "", type="password")
                edit_p = st.selectbox("Alterar Perfil:", ["Administrador", "Usuário Comum"], index=0 if st.session_state.usuarios.loc[idx, "Perfil"] == "Administrador" else 1)
                
                c_btn_u1, c_btn_u2 = st.columns([1, 4])
                with c_btn_u1:
                    if st.button("Atualizar Dados", type="primary"):
                        st.session_state.usuarios.loc[idx, "Nome"] = edit_n
                        st.session_state.usuarios.loc[idx, "E-mail"] = edit_e
                        st.session_state.usuarios.loc[idx, "Senha"] = edit_s
                        st.session_state.usuarios.loc[idx, "Perfil"] = edit_p
                        st.success("Usuário Atualizado!")
                        st.rerun()
                with c_btn_u2:
                    if st.button("❌ Excluir Usuário"):
                        st.session_state.usuarios = st.session_state.usuarios.drop(idx).reset_index(drop=True)
                        st.warning("Usuário removido com sucesso.")
                        st.rerun()

    # --- TELA: CADASTRAR COORDENAÇÃO ---
    elif escolha == "🏢 Cadastrar Coordenação":
        st.title("🏢 Cadastrar Coordenação")
        aba_c1, aba_c2 = st.tabs(["➕ Nova Coordenação", "✏️ Editar / Excluir Coordenação"])
        
        with aba_c1:
            with st.form("cad_coord", clear_on_submit=True):
                s_coord = st.text_input("Sigla (Ex: COTEC)")
                nc = st.text_input("Nome da Coordenação")
                if st.form_submit_button("Cadastrar", type="primary"):
                    if s_coord and nc:
                        nova_coord = {"Sigla": s_coord.upper(), "Nome": nc}
                        st.session_state.coordenacoes = pd.concat([st.session_state.coordenacoes, pd.DataFrame([nova_coord])], ignore_index=True)
                        st.success("Coordenação Cadastrada com sucesso!")
                        st.rerun()
                    else:
                        st.error("Preencha todos os campos da coordenação.")
                        
        with aba_c2:
            if not st.session_state.coordenacoes.empty:
                st.dataframe(st.session_state.coordenacoes, use_container_width=True, hide_index=True)
                idx_c = st.selectbox("Selecione para excluir:", st.session_state.coordenacoes.index, format_func=lambda x: st.session_state.coordenacoes.loc[x, "Sigla"])
                if st.button("❌ Remover Coordenação Selected"):
                    st.session_state.coordenacoes = st.session_state.coordenacoes.drop(idx_c).reset_index(drop=True)
                    st.warning("Coordenação removida.")
                    st.rerun()

    # --- TELA: MOVIMENTAÇÃO DE ENTRADA E SAÍDA ---
    elif escolha == "🔄 Movimentação de Entrada e Saída":
        st.title("🔄 Movimentações de Estoque")
        
        with st.form("form_movimentacao", clear_on_submit=True):
            tipo_mov = st.selectbox("Tipo de Operação", ["Entrada (+) Saldo", "Saída (-) Retirada"])
            
            prod_selecionado_idx = st.selectbox(
                "Selecione o Produto", 
                st.session_state.produtos.index,
                format_func=lambda x: f"{st.session_state.produtos.loc[x, 'Código']} - {st.session_state.produtos.loc[x, 'Item']} (Saldo atual: {st.session_state.produtos.loc[x, 'Quantidade']})"
            )
            
            qtd_mov = st.number_input("Quantidade da Operação", min_value=1, step=1)
            responsavel = st.text_input("Responsável / Recebedor")
            coord_solic = st.selectbox("Coordenação Destino", st.session_state.coordenacoes["Sigla"].values if not st.session_state.coordenacoes.empty else ["Geral"])
            
            if st.form_submit_button("Confirmar Lançamento", type="primary"):
                qtd_atual = st.session_state.produtos.loc[prod_selecionado_idx, "Quantidade"]
                item_nome = st.session_state.produtos.loc[prod_selecionado_idx, "Item"]
                item_cod = st.session_state.produtos.loc[prod_selecionado_idx, "Código"]
                
                if "Saída" in tipo_mov and qtd_mov > qtd_atual:
                    st.error(f"Erro! Saldo insuficiente. Você tentou retirar {qtd_mov} unidades, mas existem apenas {qtd_atual} em estoque.")
                else:
                    # Atualiza o saldo no DataFrame
                    if "Entrada" in tipo_mov:
                        st.session_state.produtos.loc[prod_selecionado_idx, "Quantidade"] += qtd_mov
                    else:
                        st.session_state.produtos.loc[prod_selecionado_idx, "Quantidade"] -= qtd_mov
                        
                    # Registra histórico
                    nova_mov = {
                        "Data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "Tipo": "ENTRADA" if "Entrada" in tipo_mov else "SAÍDA",
                        "Código": item_cod,
                        "Item": item_nome,
                        "Quantidade": qtd_mov,
                        "Responsável pela Retirada": responsavel if responsavel else "Almoxarifado",
                        "Coordenação": coord_solic
                    }
                    st.session_state.movimentacoes = pd.concat([st.session_state.movimentacoes, pd.DataFrame([nova_mov])], ignore_index=True)
                    st.success("Movimentação registrada com sucesso!")
                    st.rerun()
                    
        st.write("### 📜 Histórico de Movimentações Recentes")
        if not st.session_state.movimentacoes.empty:
            st.dataframe(st.session_state.movimentacoes.iloc[::-1], use_container_width=True, hide_index=True)

    # --- TELA: PERFIL ---
    elif escolha == "👤 Perfil":
        st.title("👤 Configurações de Perfil")
        st.subheader(f"Usuário ativo: {st.session_state.NOME_USUARIO_LOGADO}")
        novo_nome_perfil = st.text_input("Alterar Nome de Exibição:", value=st.session_state.NOME_USUARIO_LOGADO)
        if st.button("Salvar Nome", type="primary"):
            st.session_state.NOME_USUARIO_LOGADO = novo_nome_perfil
            st.success("Nome atualizado!")
            st.rerun()

    # --- TELA: SAIR ---
    elif escolha == "🚪 Sair":
        st.session_state.autenticado = False
        st.session_state.sub_tela_login = "login"
        st.rerun()
