import streamlit as st
import pandas as pd
from datetime import datetime

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="SISTEMA DE GESTÃO DE ALMOXARIFADO NGI CARAJÁS", 
    page_icon="🌿", 
    layout="wide"
)

# --- ESTILIZAÇÃO E CORREÇÃO DE LAYOUT ---
st.markdown("""
    <style>
    [data-testid="stSidebarNav"] {display: none;}
    [data-testid="stMainMenu"] {display: none;}
    [data-testid="stSidebar"] { background-color: #fcfaff !important; border-right: 1px solid #efe9f5; }
    div.stButton > button:first-child[kind="primary"] { background-color: #4CAF50 !important; color: white !important; }
    </style>
""", unsafe_allow_html=True)

# --- INICIALIZAÇÃO DE SESSÃO E BANCO DE DADOS LOCAL ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = ""

# Criando usuários padrão direto no sistema (Sem depender de links externos)
if "usuarios" not in st.session_state:
    st.session_state.usuarios = pd.DataFrame([
        {"Nome": "Administrador Padrão", "E-mail": "admin@ngi.com", "Senha": "123", "Perfil": "Administrador"},
        {"Nome": "Almoxarife Carajás", "E-mail": "almoxarifado@ngi.com", "Senha": "ngi", "Perfil": "Usuário Comum"}
    ])

if "produtos" not in st.session_state:
    st.session_state.produtos = pd.DataFrame([
        {"Código": "001", "Item": "Capacete de Segurança", "Quantidade": 15, "Categoria": "EPI", "Valor Unitário": 45.00},
        {"Código": "002", "Item": "Resma Papel A4", "Quantidade": 8, "Categoria": "Material de Escritório", "Valor Unitário": 28.50},
        {"Código": "003", "Item": "Luva de Raspa", "Quantidade": 50, "Categoria": "EPI", "Valor Unitário": 12.00}
    ])

if "categorias" not in st.session_state:
    st.session_state.categorias = ["EPI", "Material de Escritório", "Informática", "Limpeza"]

if "movimentacoes" not in st.session_state:
    st.session_state.movimentacoes = pd.DataFrame(columns=["Data", "Tipo", "Código", "Item", "Quantidade", "Responsável", "Destino"])

# =============================================================================
# TELA DE LOGIN
# =============================================================================
if not st.session_state.autenticado:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col_l1, col_l2, col_l3 = st.columns([1, 1.2, 1])
    with col_l2:
        st.markdown("<h2 style='text-align: center; color: #1e5934;'>Almoxarifado NGI Carajás</h2>", unsafe_allow_html=True)
        usuario_input = st.text_input("E-mail do Usuário", placeholder="exemplo@ngi.com").strip()
        senha_input = st.text_input("Senha", type="password", placeholder="Digite sua senha...").strip()
        
        if st.button("Entrar no Sistema", type="primary", use_container_width=True):
            df_users = st.session_state.usuarios
            user_match = df_users[(df_users['E-mail'] == usuario_input) & (df_users['Senha'] == senha_input)]
            
            if not user_match.empty:
                st.session_state.autenticado = True
                st.session_state.NOME_USUARIO_LOGADO = user_match.iloc[0]['Nome']
                st.rerun()
            else:
                st.error("Usuário ou Senha incorretos!")

# =============================================================================
# PAINEL DO SISTEMA
# =============================================================================
else:
    with st.sidebar:
        st.markdown(f"#### 👤 Usuário: {st.session_state.NOME_USUARIO_LOGADO}")
        st.write("---")
        escolha = st.radio("Menu", ["🎛️ Painel Geral", "➕ Cadastrar Produto", "🔄 Entrada / Saída", "🚪 Sair"])

    if escolha == "🎛️ Painel Geral":
        st.title("🎛️ Painel Geral de Estoque")
        st.dataframe(st.session_state.produtos, use_container_width=True, hide_index=True)
        
        st.write("### 📋 Histórico Recente")
        st.dataframe(st.session_state.movimentacoes, use_container_width=True, hide_index=True)

    elif escolha == "➕ Cadastrar Produto":
        st.title("➕ Novo Material")
        with st.form("novo_p"):
            cod = st.text_input("Código")
            nome = st.text_input("Nome do Material")
            cat = st.selectbox("Categoria", st.session_state.categorias)
            val = st.number_input("Valor Unitário", min_value=0.0)
            if st.form_submit_button("Cadastrar", type="primary"):
                novo = {"Código": cod, "Item": nome, "Quantidade": 0, "Categoria": cat, "Valor Unitário": val}
                st.session_state.produtos = pd.concat([st.session_state.produtos, pd.DataFrame([novo])], ignore_index=True)
                st.success("Adicionado com sucesso!")

    elif escolha == "🔄 Entrada / Saída":
        st.title("🔄 Movimentações")
        tipo = st.selectbox("Tipo", ["Entrada", "Saída"])
        idx = st.selectbox("Produto", st.session_state.produtos.index, format_func=lambda x: st.session_state.produtos.loc[x, "Item"])
        qtd = st.number_input("Quantidade", min_value=1)
        resp = st.text_input("Responsável")
        
        if st.button("Confirmar", type="primary"):
            atual = st.session_state.produtos.loc[idx, "Quantidade"]
            if tipo == "Saída" and qtd > atual:
                st.error("Estoque insuficiente!")
            else:
                if tipo == "Entrada":
                    st.session_state.produtos.loc[idx, "Quantidade"] += qtd
                else:
                    st.session_state.produtos.loc[idx, "Quantidade"] -= qtd
                
                mov = {"Data": datetime.today().strftime("%d/%m/%Y"), "Tipo": tipo, "Código": st.session_state.produtos.loc[idx, "Código"], "Item": st.session_state.produtos.loc[idx, "Item"], "Quantidade": qtd, "Responsável": resp, "Destino": "Almoxarifado"}
                st.session_state.movimentacoes = pd.concat([st.session_state.movimentacoes, pd.DataFrame([mov])], ignore_index=True)
                st.success("Movimentação registrada!")

    elif escolha == "🚪 Sair":
        st.session_state.autenticado = False
        st.rerun()
