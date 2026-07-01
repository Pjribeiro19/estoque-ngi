import streamlit as st
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from supabase import create_client, Client

# =============================================================================
# CONFIGURAÇÕES SEGURAS DE E-MAIL (Puxando dos Secrets do Streamlit)
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

# --- FORÇA A BARRA LATERAL A FICAR SEMPRE ABERTA NO CELULAR ---
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

# --- CONEXÃO DIRETA COM O SUPABASE ---
try:
    url = st.secrets["connections"]["supabase"]["url"]
    key = st.secrets["connections"]["supabase"]["key"]
    conn: Client = create_client(url, key)
except Exception as e:
    st.error(f"Erro ao inicializar conexão com o Supabase: {e}")
    st.stop()

# =============================================================================
# FUNÇÕES DE ENVIO DE E-MAIL
# =============================================================================
def enviar_email_notificacao(item, qtd, requisitante, destino):
    """Envia um e-mail simples notificando a saída de material de informática."""
    try:
        mensagem = MIMEMultipart()
        mensagem['From'] = EMAIL_REMETENTE
        mensagem['To'] = "ti.ngicarajas@icmbio.gov.br"
        mensagem['Subject'] = f"⚠️ ALERTA: Saída de Material - {item}"
        
        corpo = f"""
        Olá Equipe de TI,
        
        Foi registrada uma nova saída de material de informática no sistema:
        
        - **Item:** {item}
        - **Quantidade:** {qtd}
        - **Requisitante:** {requisitante}
        - **Destino/Uso:** {destino}
        - **Data/Hora:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
        
        *Este é um e-mail automático gerado pelo Sistema de Almoxarifado.*
        """
        mensagem.attach(MIMEText(corpo, 'html'))
        
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORTA)
        server.starttls()
        server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
        server.sendmail(EMAIL_REMETENTE, "ti.ngicarajas@icmbio.gov.br", mensagem.as_string())
        server.quit()
        return True
    except Exception as e:
        st.warning(f"Não foi possível enviar o e-mail de alerta: {e}")
        return False

# =============================================================================
# CONTROLE DE SESSÃO / LOGIN
# =============================================================================
if "logado" not in st.session_state:
    st.session_state.logado = False
if "usuario_atual" not in st.session_state:
    st.session_state.usuario_atual = None
if "perfil_atual" not in st.session_state:
    st.session_state.perfil_atual = None

def fazer_login(usuario, senha):
    try:
        dados = conn.table("usuarios").select("*").eq("usuario", usuario).eq("senha", senha).execute()
        if dados.data and len(dados.data) > 0:
            st.session_state.logado = True
            st.session_state.usuario_atual = dados.data[0]["usuario"]
            st.session_state.perfil_atual = dados.data[0]["perfil"]
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
    except Exception as e:
        st.error(f"Erro ao autenticar: {e}")

if not st.session_state.logado:
    st.markdown("<h2 style='text-align: center; color: #1e5934;'>🌿 ALMOXARIFADO NGI CARAJÁS</h2>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align: center; color: #666;'>Controle de Estoque Inteligente</h4>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("form_login"):
            st.subheader("Acesso ao Sistema")
            user_input = st.text_input("Usuário")
            pass_input = st.text_input("Senha", type="password")
            botao_entrar = st.form_submit_button("Entrar", type="primary")
            
            if botao_entrar:
                if user_input and pass_input:
                    fazer_login(user_input, pass_input)
                else:
                    st.warning("Preencha todos os campos.")
    st.stop()

# =============================================================================
# INTERFACE PRINCIPAL (APÓS LOGIN)
# =============================================================================

# Barra Lateral Customizada
with st.sidebar:
    st.markdown("<h3 style='color: #1e5934; text-align: center;'>Menu</h3>", unsafe_allow_html=True)
    st.write(f"👤 **Usuário:** {st.session_state.usuario_atual}")
    st.write(f"🔰 **Perfil:** {st.session_state.perfil_atual.capitalize()}")
    st.markdown("---")
    
    opcoes_menu = ["📦 Consultar Estoque", "➕ Registrar Movimentação"]
    if st.session_state.perfil_atual == "administrador":
        opcoes_menu.extend(["⚙️ Cadastrar Produtos", "📊 Histórico Geral"])
        
    escolha = st.radio("Navegação", opcoes_menu, label_visibility="collapsed")
    st.markdown("---")
    if st.button("🚪 Sair", use_container_width=True):
        st.session_state.logado = False
        st.session_state.usuario_atual = None
        st.session_state.perfil_atual = None
        st.rerun()

# --- TELA 1: CONSULTAR ESTOQUE ---
if escolha == "📦 Consultar Estoque":
    st.title("📦 Situação Atual do Estoque")
    
    try:
        res_produtos = conn.table("produtos").select("*").order("item").execute()
        if res_produtos.data:
            df_prod = pd.DataFrame(res_produtos.data)
            
            # Formatações Visuais
            df_exibicao = df_prod[["codigo", "item", "quantidade", "categoria", "valor_unitario"]].copy()
            df_exibicao.columns = ["Código", "Item/Descrição", "Quantidade", "Categoria", "Valor Unitário (R$)"]
            
            # Filtro de Busca Eficiente
            busca = st.text_input("🔍 Buscar item por nome ou código...")
            if busca:
                df_exibicao = df_exibicao[
                    df_exibicao["Item/Descrição"].str.contains(busca, case=False, na=False) |
                    df_exibicao["Código"].str.contains(busca, case=False, na=False)
                ]
                
            st.dataframe(df_exibicao, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum produto cadastrado no momento.")
    except Exception as e:
        st.error(f"Erro ao carregar estoque: {e}")

# --- TELA 2: REGISTRAR MOVIMENTAÇÃO ---
elif escolha == "➕ Registrar Movimentação":
    st.title("➕ Registrar Entrada ou Saída")
    
    try:
        res_p = conn.table("produtos").select("codigo, item, quantidade, categoria").order("item").execute()
        if not res_p.data:
            st.warning("Não há produtos cadastrados para movimentar.")
        else:
            produtos_lista = {f"{p['codigo']} - {p['item']} (Dispo: {p['quantidade']})": p for p in res_p.data}
            
            with st.form("form_movimentacao"):
                item_selecionado = st.selectbox("Selecione o Produto", list(produtos_lista.keys()))
                tipo_mov = st.selectbox("Tipo de Movimentação", ["SAÍDA", "ENTRADA"])
                qtd_mov = st.number_input("Quantidade", min_value=1, step=1)
                requisitante = st.text_input("Nome do Requisitante / Servidor")
                destino = st.text_input("Destino / Finalidade de Uso")
                
                bt_salvar_mov = st.form_submit_button("Confirmar Lançamento", type="primary")
                
                if bt_salvar_mov:
                    prod_dados = produtos_lista[item_selecionado]
                    qtd_atual = prod_dados["quantidade"]
                    codigo_prod = prod_dados["codigo"]
                    nome_prod = prod_dados["item"]
                    cat_prod = prod_dados["categoria"]
                    
                    if tipo_mov == "SAÍDA" and qtd_mov > qtd_atual:
                        st.error(f"Quantidade insuficiente em estoque! Saldo atual: {qtd_atual}")
                    else:
                        nova_qtd = (qtd_atual + qtd_mov) if tipo_mov == "ENTRADA" else (qtd_atual - qtd_mov)
                        
                        # 1. Atualiza Estoque
                        conn.table("produtos").update({"quantidade": nova_qtd}).eq("codigo", codigo_prod).execute()
                        
                        # 2. Salva no Histórico
                        mov_dados = {
                            "codigo": codigo_prod,
                            "item": nome_prod,
                            "tipo": tipo_mov,
                            "quantidade": qtd_mov,
                            "requisitante": requisitante if requisitante else "Não informado",
                            "destino": destino if destino else "Não informado",
                            "usuario_responsavel": st.session_state.usuario_atual,
                            "data_hora": datetime.now().isoformat()
                        }
                        conn.table("movimentacoes").insert(mov_dados).execute()
                        
                        # 3. Disparo Automático se for Informática
                        if tipo_mov == "SAÍDA" and cat_prod.upper() == "INFORMÁTICA":
                            enviar_email_notificacao(nome_prod, qtd_mov, requisitante, destino)
                            
                        st.success(f"Movimentação de {tipo_mov} concluída com sucesso!")
                        st.rerun()
    except Exception as e:
        st.error(f"Erro ao processar movimentação: {e}")

# --- TELA 3: CADASTRAR PRODUTOS (ADMIN) ---
elif escolha == "⚙️ Cadastrar Produtos" and st.session_state.perfil_atual == "administrador":
    st.title("⚙️ Cadastrar Novo Item no Catálogo")
    
    with st.form("form_cadastro_produto"):
        novo_cod = st.text_input("Código Único do Produto (Ex: INF001, MAT002)")
        novo_nome = st.text_input("Descrição / Nome do Item")
        nova_cat = st.selectbox("Categoria", ["INFORMÁTICA", "EXPEDIENTE", "LIMPEZA", "COPA", "OUTROS"])
        qtd_inicial = st.number_input("Quantidade Inicial em Estoque", min_value=0, step=1)
        val_unit = st.number_input("Valor Unitário (R$)", min_value=0.0, step=0.01)
        
        bt_cadastrar = st.form_submit_button("Cadastrar Produto", type="primary")
        
        if bt_cadastrar:
            if not novo_cod or not novo_nome:
                st.error("Código e Nome do Produto são obrigatórios.")
            else:
                try:
                    # Verifica duplicidade
                    existe = conn.table("produtos").select("codigo").eq("codigo", novo_cod).execute()
                    if existe.data and len(existe.data) > 0:
                        st.error("Já existe um produto cadastrado com este código!")
                    else:
                        prod_novo = {
                            "codigo": novo_cod.strip().upper(),
                            "item": novo_nome.strip().upper(),
                            "categoria": nova_cat,
                            "quantidade": qtd_inicial,
                            "valor_unitario": val_unit
                        }
                        conn.table("produtos").insert(prod_novo).execute()
                        st.success("Produto adicionado com sucesso ao almoxarifado!")
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar produto: {e}")

# --- TELA 4: HISTÓRICO GERAL (ADMIN) ---
elif escolha == "📊 Histórico Geral" and st.session_state.perfil_atual == "administrador":
    st.title("📊 Relatório Histórico de Movimentações")
    
    try:
        res_mov = conn.table("movimentacoes").select("*").order("data_hora", desc=True).execute()
        if res_mov.data:
            df_mov = pd.DataFrame(res_mov.data)
            
            # Formatação de datas amigável
            df_mov["data_hora"] = pd.to_datetime(df_mov["data_hora"]).dt.strftime('%d/%m/%Y %H:%M')
            
            df_mov_exibir = df_mov[["data_hora", "codigo", "item", "tipo", "quantidade", "requisitante", "destino", "usuario_responsavel"]].copy()
            df_mov_exibir.columns = ["Data/Hora", "Código", "Item", "Tipo", "Qtd", "Requisitante", "Destino", "Operador"]
            
            st.dataframe(df_mov_exibir, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhuma movimentação registrada no histórico.")
    except Exception as e:
        st.error(f"Erro ao buscar histórico: {e}")
