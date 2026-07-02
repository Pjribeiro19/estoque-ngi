import streamlit as st
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
# IMPORTANTE: Garante que tens 'supabase' adicionado ao teu arquivo requirements.txt
from supabase import create_client, Client

# =============================================================================
# CONEXÃO COM O SUPABASE (Forma robusta e segura)
# =============================================================================
if "supabase_cliente" not in st.session_state:
    st.session_state.supabase_cliente = None

try:
    # Verifica se o bloco [supabase] existe antes de tentar ler para evitar quebras
    if "supabase" in st.secrets:
        SUPABASE_URL = st.secrets["supabase"]["url"]
        SUPABASE_KEY = st.secrets["supabase"]["key"]
        st.session_state.supabase_cliente = create_client(SUPABASE_URL, SUPABASE_KEY)
    else:
        st.error("⚠️ Erro Crítico: O bloco [supabase] não foi detetado nos Secrets do Streamlit.")
except Exception as e:
    st.error(f"⚠️ Erro ao ler as credenciais do Supabase: {e}")

# Atalho para o cliente do Supabase
supabase = st.session_state.supabase_cliente

# Configurações de e-mail (Mantidas do teu original)
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

# --- FORÇA A BARRA LATERAL A FICAR SEMPRE ABERTA NO CELULAR (Teu CSS Original) ---
st.markdown("""
    <style>
    @media (max-width: 991px) {
        [data-testid="stSidebar"] {
            transform: none !important;
            position: relative !important;
            min-width: 250px !important;
            max-width: 250px !important;
            display: block !important;
        }
        [data-testid="stSidebar"] button {
            display: none !important;
        }
        .main {
            flex-direction: row !important;
        }
        [data-testid="stAppViewBlockContainer"] {
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            min-width: calc(100vw - 250px) !important;
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

# --- INICIALIZAÇÃO DO GERENCIAMENTO DE SESSÃO ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"

if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = ""

# =============================================================================
# FLUXO 1: FLUXO DE LOGIN (AUTENTICAÇÃO REAL NO SUPABASE)
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
            st.markdown("<h2 style='text-align: center; color: #1e5934; margin-top: 10px; margin-bottom: 25px; font-family: sans-serif;'>Gestão de Almoxarifado<br>NGI Carajás</h2>", unsafe_allow_html=True)
            usuario_input = st.text_input("Usuário / E-mail", placeholder="Digite seu usuário ou e-mail...")
            senha_input = st.text_input("Senha", type="password", placeholder="Digite sua senha...")
            st.markdown("<br>", unsafe_allow_html=True)
            
            if st.button("Entrar no Sistema", type="primary", use_container_width=True):
                if supabase is None:
                    st.error("❌ Não foi possível realizar o login porque o banco de dados não está conectado. Verifica as tuas configurações de Secrets.")
                elif usuario_input and senha_input:
                    try:
                        # Procura o utilizador na tabela 'usuarios' do teu banco real
                        resposta = supabase.table("usuarios").select("*").eq("E-mail", usuario_input.strip()).execute()
                        
                        if resposta.data:
                            dados_usuario = resposta.data[0]
                            # Valida se a senha corresponde
                            if str(dados_usuario.get("Senha")) == str(senha_input).strip():
                                st.session_state.autenticado = True
                                st.session_state.NOME_USUARIO_LOGADO = dados_usuario.get("Nome", "Usuário")
                                st.rerun()
                            else:
                                st.error("❌ Credenciais inválidas! Verifica os dados digitados.")
                        else:
                            st.error("❌ Usuário ou E-mail não cadastrado!")
                    except Exception as err:
                        st.error(f"❌ Erro na ligação com a tabela: {err}")
                else:
                    st.error("Por favor, preenche todos os campos!")
                    
            if st.button("Esqueci a senha", use_container_width=True):
                st.session_state.sub_tela_login = "esqueci"
                st.rerun()

    elif st.session_state.sub_tela_login == "esqueci":
        col_r1, col_r2, col_r3 = st.columns([1, 1.2, 1])
        with col_r2:
            st.write("<br><br>", unsafe_allow_html=True)
            st.markdown("### 🔑 Recuperar Acesso")
            st.markdown("<p style='font-size: 0.9rem; color: gray;'>Insere o teu e-mail corporativo cadastrado para recuperar a senha.</p>", unsafe_allow_html=True)
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
                            corpo_email = f"""
                            Olá,
                            Recebemos uma solicitação de recuperação de acesso para o seu usuário ({email_recuperar.strip()}).
                            Para acessar o Sistema de Gestão de Almoxarifado NGI Carajás, utilize os dados de acesso padrão provisórios:
                            Link de acesso: https://almoxarifado-carajas.streamlit.app/
                            Sua senha provisória de contingência é: 123
                            Por favor, altere sua senha no menu 'Perfil' assim que efetuar o login com sucesso.
                            Atenciosamente,
                            Suporte NGI Carajás / ICMBio
                            """
                            msg.attach(MIMEText(corpo_email, 'plain'))
                            server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
                            server.starttls()
                            server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
                            server.sendmail(EMAIL_REMETENTE, email_recuperar.strip(), msg.as_string())
                            server.quit()
                            st.success(f"Sucesso! Instruções de recuperação enviadas para {email_recuperar}")
                        except Exception as e:
                            st.error(f"Erro ao tentar enviar o e-mail: {e}")
                else:
                    st.warning("Por favor, digite um e-mail válido.")
            if st.button("Voltar para o Login", use_container_width=True):
                st.session_state.sub_tela_login = "login"
                st.rerun()

# =============================================================================
# FLUXO 2: SISTEMA PRINCIPAL (CARREGANDO OS DADOS REAIS DO SUPABASE)
# =============================================================================
else:
    # Carrega as tabelas diretamente do banco ativo em tempo real
    try:
        if supabase:
            prod_data = supabase.table("produtos").select("*").execute()
            st.session_state.produtos = pd.DataFrame(prod_data.data) if prod_data.data else pd.DataFrame(columns=["Código", "Item", "Quantidade", "Categoria", "Valor Unitário"])
            
            mov_data = supabase.table("movimentacoes").select("*").execute()
            st.session_state.movimentacoes = pd.DataFrame(mov_data.data) if mov_data.data else pd.DataFrame(columns=["Data", "Tipo", "Código", "Item", "Quantidade", "Responsável pela Retirada", "Coordenação"])
            
            coord_data = supabase.table("coordenacoes").select("*").execute()
            st.session_state.coordenacoes = pd.DataFrame(coord_data.data) if coord_data.data else pd.DataFrame(columns=["Sigla", "Nome"])
            
            st.session_state.categorias = ["EPI", "Material de Escritório", "Informática", "Limpeza", "Copa"]
        else:
            st.error("Banco de dados não configurado inicialmente.")
    except Exception as e:
        st.error(f"Erro ao sincronizar tabelas do Supabase: {e}")

    # --- BARRA LATERAL ---
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

    # --- TELA: PAINEL GERAL ---
    if escolha == "🎛️ Painel Geral":
        st.title("🎛️ Painel Geral de Estoque")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total de Itens Cadastrados", len(st.session_state.produtos))
        c2.metric("Produtos Esgotados", len(st.session_state.produtos[st.session_state.produtos['Quantidade'] == 0]) if not st.session_state.produtos.empty else 0)
        c3.metric("Movimentações Realizadas", len(st.session_state.movimentacoes))
        st.write("---")
        st.write("### 🔍 Ferramentas de Busca e Filtro")
        col_filtro1, col_filtro2 = st.columns([2, 1])
        termo_busca = col_filtro1.text_input("Buscar por Nome do Material ou Código:", placeholder="Digite para pesquisar...")
        categoria_selecionada = col_filtro2.selectbox("Filtrar por Categoria:", ["Todas"] + list(st.session_state.categorias))
        
        df_filtrado = st.session_state.produtos.copy()
        if termo_busca and not df_filtrado.empty:
            df_filtrado = df_filtrado[df_filtrado['Item'].str.contains(termo_busca, case=False, na=False) | df_filtrado['Código'].str.contains(termo_busca, case=False, na=False)]
        if categoria_selecionada != "Todas" and not df_filtrado.empty:
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

    # --- TELA: CADASTRAR PRODUTO (SALVANDO NO BANCO VIA INSERT) ---
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
                st.caption("ℹ️ Novos materiais são registrados com saldo inicial 0. Adicione quantidades em 'Movimentação'.")
                if st.form_submit_button("Finalizar Cadastro", type="primary"):
                    if cod and nome_it:
                        if not st.session_state.produtos.empty and cod in st.session_state.produtos["Código"].values:
                            st.error(f"Erro! Código {cod} já existe.")
                        else:
                            try:
                                novo_p = {"Código": cod, "Item": nome_it, "Quantidade": 0, "Categoria": cat_it, "Valor Unitário": float(val_unit)}
                                supabase.table("produtos").insert(novo_p).execute()
                                st.success(f"Sucesso! {nome_it} adicionado ao banco.")
                                st.rerun()
                            except Exception as ex:
                                st.error(f"Erro ao salvar: {ex}")
                    else:
                        st.error("Preencha todos os campos!")
                        
        with aba_gerenciar_prod:
            if not st.session_state.produtos.empty:
                st.dataframe(st.session_state.produtos, use_container_width=True, hide_index=True)
                idx_p = st.selectbox("Selecione para modificar:", st.session_state.produtos.index, format_func=lambda x: f"{st.session_state.produtos.loc[x, 'Código']} - {st.session_state.produtos.loc[x, 'Item']}")
                col_ed1, col_ed2 = st.columns(2)
                edit_cod = col_ed1.text_input("Código:", value=st.session_state.produtos.loc[idx_p, "Código"])
                edit_item = col_ed2.text_input("Nome:", value=st.session_state.produtos.loc[idx_p, "Item"])
                edit_qtd = col_ed1.number_input("Quantidade (Ajuste):", min_value=0, value=int(st.session_state.produtos.loc[idx_p, "Quantidade"]))
                edit_cat = col_ed2.selectbox("Categoria:", st.session_state.categorias, index=st.session_state.categorias.index(st.session_state.produtos.loc[idx_p, "Categoria"]) if st.session_state.produtos.loc[idx_p, "Categoria"] in st.session_state.categorias else 0)
                edit_val = st.number_input("Valor Unitário:", min_value=0.0, step=0.01, format="%.2f", value=float(st.session_state.produtos.loc[idx_p, "Valor Unitário"]))
                col_b_prod1, col_b_prod2 = st.columns([1, 4])
                
                with col_b_prod1:
                    if st.button("Salvar Alterações", type="primary"):
                        try:
                            supabase.table("produtos").update({"Código": edit_cod, "Item": edit_item, "Quantidade": edit_qtd, "Categoria": edit_cat, "Valor Unitário": float(edit_val)}).eq("Código", st.session_state.produtos.loc[idx_p, "Código"]).execute()
                            st.success("Modificado!")
                            st.rerun()
                        except Exception as ex:
                            st.error(ex)
                with col_b_prod2:
                    if st.button("❌ Excluir Produto"):
                        try:
                            supabase.table("produtos").delete().eq("Código", st.session_state.produtos.loc[idx_p, "Código"]).execute()
                            st.warning("Removido.")
                            st.rerun()
                        except Exception as ex:
                            st.error(ex)

    # --- TELA: CADASTRAR CATEGORIA ---
    elif escolha == "🗂️ Cadastrar Categoria":
        st.title("🗂️ Gerenciamento de Categorias")
        col_cat1, col_cat2 = st.columns([1, 2])
        with col_cat1:
            nova_cat = st.text_input("Nome da Nova Categoria:")
            if st.button("Adicionar Categoria", type="primary"):
                if nova_cat and nova_cat.strip() not in st.session_state.categorias:
                    st.session_state.categorias.append(nova_cat.strip())
                    st.success("Adicionada temporariamente!")
        with col_cat2:
            st.dataframe(pd.DataFrame(st.session_state.categorias, columns=["Categorias Ativas"]), use_container_width=True, hide_index=True)

    # --- TELA: CADASTRAR USUÁRIO ---
    elif escolha == "👥 Cadastrar Usuário":
        st.title("👥 Cadastrar Usuário no Banco")
        aba_cad, aba_edit = st.tabs(["➕ Novo Usuário", "✏️ Editar / Excluir Usuários"])
        with aba_cad:
            with st.form("cad_user", clear_on_submit=True):
                n = st.text_input("Nome")
                e = st.text_input("E-mail")
                s = st.text_input("Senha", type="password")
                p = st.selectbox("Perfil", ["Administrador", "Usuário Comum"])
                if st.form_submit_button("Salvar", type="primary"):
                    if n and e:
                        try:
                            new_u = {"Nome": n, "E-mail": e, "Senha": s if s else "123", "Perfil": p}
                            supabase.table("usuarios").insert(new_u).execute()
                            st.success("Usuário Cadastrado com Sucesso!")
                            st.rerun()
                        except Exception as ex:
                            st.error(ex)
        with aba_edit:
            try:
                user_data = supabase.table("usuarios").select("*").execute()
                df_users = pd.DataFrame(user_data.data) if user_data.data else pd.DataFrame()
                if not df_users.empty:
                    st.dataframe(df_users[["Nome", "E-mail", "Perfil"]], use_container_width=True, hide_index=True)
                    idx = st.selectbox("Selecione para excluir:", df_users.index, format_func=lambda x: df_users.loc[x, "Nome"])
                    if st.button("❌ Remover Usuário Selecionado"):
                        supabase.table("usuarios").delete().eq("E-mail", df_users.loc[idx, "E-mail"]).execute()
                        st.warning("Usuário removido.")
                        st.rerun()
            except:
                st.info("Nenhum usuário listado.")

    # --- TELA: CADASTRAR COORDENAÇÃO ---
    elif escolha == "🏢 Cadastrar Coordenação":
        st.title("🏢 Cadastrar Coordenação")
        with st.form("cad_coord", clear_on_submit=True):
            s_coord = st.text_input("Sigla")
            nc = st.text_input("Nome da Coordenação")
            if st.form_submit_button("Cadastrar", type="primary"):
                if s_coord and nc:
                    try:
                        supabase.table("coordenacoes").insert({"Sigla": s_coord.upper(), "Nome": nc}).execute()
                        st.success("Coordenação Cadastrada!")
                        st.rerun()
                    except Exception as ex:
                        st.error(ex)
        if not st.session_state.coordenacoes.empty:
            st.dataframe(st.session_state.coordenacoes, use_container_width=True, hide_index=True)

    # --- TELA: MOVIMENTAÇÃO DE ENTRADA E SAÍDA (SINCRONIZANDO SALDOS) ---
    elif escolha == "🔄 Movimentação de Entrada e Saída":
        st.title("🔄 Movimentação de Entrada e Saída")
        aba_entrada, aba_saida, aba_historico = st.tabs(["📥 Registrar Entrada", "📤 Registrar Saída", "📋 Histórico de Entradas/Saídas"])
        
        with aba_entrada:
            with st.form("form_registrar_entrada", clear_on_submit=True):
                col_e1, col_e2 = st.columns(2)
                data_entrada = col_e1.date_input("Data:", value=datetime.today(), format="DD/MM/YYYY")
                idx_prod_ent = col_e2.selectbox("Material:", st.session_state.produtos.index, format_func=lambda x: f"{st.session_state.produtos.loc[x, 'Código']} - {st.session_state.produtos.loc[x, 'Item']} (Saldo: {st.session_state.produtos.loc[x, 'Quantidade']})")
                qtd_entrada = st.number_input("Quantidade Entrada:", min_value=1, step=1)
                if st.form_submit_button("Confirmar Entrada", type="primary"):
                    novo_saldo = int(st.session_state.produtos.loc[idx_prod_ent, "Quantidade"]) + qtd_entrada
                    # Atualiza produto
                    supabase.table("produtos").update({"Quantidade": novo_saldo}).eq("Código", st.session_state.produtos.loc[idx_prod_ent, "Código"]).execute()
                    # Salva histórico
                    nova_mov = {"Data": data_entrada.strftime("%d/%m/%Y"), "Tipo": "Entrada", "Código": st.session_state.produtos.loc[idx_prod_ent, "Código"], "Item": st.session_state.produtos.loc[idx_prod_ent, "Item"], "Quantidade": qtd_entrada, "Responsável pela Retirada": "Almoxarifado", "Coordenação": "-"}
                    supabase.table("movimentacoes").insert(nova_mov).execute()
                    st.success("Entrada registrada no banco!")
                    st.rerun()
                    
        with aba_saida:
            with st.form("form_registrar_saida", clear_on_submit=True):
                col_s1, col_s2 = st.columns(2)
                data_saida = col_s1.date_input("Data:", value=datetime.today(), format="DD/MM/YYYY")
                idx_prod_sai = col_s2.selectbox("Material:", st.session_state.produtos.index, format_func=lambda x: f"{st.session_state.produtos.loc[x, 'Código']} - {st.session_state.produtos.loc[x, 'Item']} (Saldo: {st.session_state.produtos.loc[x, 'Quantidade']})")
                qtd_saida = col_s1.number_input("Quantidade Saída:", min_value=1, step=1)
                lista_coord = st.session_state.coordenacoes["Sigla"].tolist() if not st.session_state.coordenacoes.empty else ["Sem Coordenações"]
                coord_retirada = col_s2.selectbox("Destino:", lista_coord)
                resp_retirada = st.text_input("Responsável pela Retirada:")
                
                if st.form_submit_button("Confirmar Saída", type="primary"):
                    qtd_disp = int(st.session_state.produtos.loc[idx_prod_sai, "Quantidade"])
                    if not resp_retirada.strip():
                        st.error("Insira o nome do responsável!")
                    elif qtd_saida > qtd_disp:
                        st.error(f"Estoque insuficiente! Disponível: {qtd_disp}")
                    else:
                        novo_saldo = qtd_disp - qtd_saida
                        supabase.table("produtos").update({"Quantidade": novo_saldo}).eq("Código", st.session_state.produtos.loc[idx_prod_sai, "Código"]).execute()
                        nova_mov_saida = {"Data": data_saida.strftime("%d/%m/%Y"), "Tipo": "Saída", "Código": st.session_state.produtos.loc[idx_prod_sai, "Código"], "Item": st.session_state.produtos.loc[idx_prod_sai, "Item"], "Quantidade": qtd_saida, "Responsável pela Retirada": resp_retirada.strip(), "Coordenação": coord_retirada}
                        supabase.table("movimentacoes").insert(nova_mov_saida).execute()
                        st.success("Saída salva com sucesso!")
                        st.rerun()
                        
        with aba_historico:
            st.write("### 📜 Registros de Fluxo")
            if st.session_state.movimentacoes.empty:
                st.info("Nenhuma movimentação registada no histórico.")
            else:
                st.dataframe(st.session_state.movimentacoes, use_container_width=True, hide_index=True)

    # --- TELA: PERFIL ---
    elif escolha == "👤 Perfil":
        st.title("👤 Meu Perfil")
        st.write(f"**Usuário Atual:** {st.session_state.NOME_USUARIO_LOGADO}")
        st.write("**Lotação:** NGI Carajás / ICMBio")

    # --- TELA: SAIR ---
    elif escolha == "🚪 Sair":
        st.session_state.autenticado = False
        st.session_state.sub_tela_login = "login"
        st.rerun()
