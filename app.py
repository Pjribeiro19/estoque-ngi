import streamlit as st
import pandas as pd
from datetime import datetime

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Gestão de Estoque - NGI Carajás",
    page_icon="🌿",
    layout="wide"
)

# --- INICIALIZAÇÃO DO ESTADO DA SESSÃO (SESSION STATE) ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"

if "NOME_USUARIO_LOGADO" not in st.session_state:
    st.session_state.NOME_USUARIO_LOGADO = "João Paulo"


# --- FLUXO DE TELAS ---

# 1. SE O USUÁRIO NÃO ESTIVER LOGADO
if not st.session_state.autenticado:
    
    # Tela de Login Padrão
    if st.session_state.sub_tela_login == "login":
        st.title("🔑 Login - Gestão de Estoque")
        
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        
        if st.button("Entrar", type="primary"):
            # Substitua pela sua lógica real de validação se necessário
            if usuario and senha: 
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("Por favor, preencha os campos.")
                
        if st.button("Esqueci a senha"):
            st.session_state.sub_tela_login = "esqueci"
            st.rerun()

    # Tela de Esqueci a Senha (Sua Imagem 1)
    elif st.session_state.sub_tela_login == "esqueci":
        st.markdown("<p style='text-align: left; font-size: 0.9rem;'>Insira seu e-mail corporativo para recuperar a senha.</p>", unsafe_allow_html=True)
        email_recuperar = st.text_input("E-mail corporativo", placeholder="exemplo@icmbio.gov.br")

        if st.button("Enviar Instruções", type="primary", use_container_width=True):
            st.success("Se o e-mail estiver correto, as instruções foram enviadas.")

        if st.button("Voltar para o Login", use_container_width=True):
            st.session_state.sub_tela_login = "login"
            st.rerun()
            
        st.markdown('</div>', unsafe_allow_html=True)

# 2. SE O USUÁRIO ESTIVER LOGADO (SISTEMA PRINCIPAL)
else:
    # --- BARRA LATERAL DE NAVEGAÇÃO ---
    st.sidebar.title(f"👤 {st.session_state.NOME_USUARIO_LOGADO}")
    
    escolha = st.sidebar.radio(
        "Menu do Sistema",
        [
            "📊 Painel Geral", 
            "➕ Cadastrar Produto", 
            "📁 Cadastrar Categoria", 
            "👥 Cadastrar Usuário", 
            "🏢 Cadastrar Coordenação", 
            "🔄 Movimentação de Entrada e Saída", 
            "👤 Perfil", 
            "🔴 Sair"
        ]
    )

    # --- LÓGICA DE RENDERIZAÇÃO DAS TELAS ---
    if escolha == "📊 Painel Geral":
        st.title("📊 Painel Geral")
        st.write("Conteúdo do Painel Geral aqui...")

    elif escolha == "➕ Cadastrar Produto":
        st.title("➕ Cadastrar Produto")

    elif escolha == "📁 Cadastrar Categoria":
        st.title("📁 Cadastrar Categoria")

    elif escolha == "👥 Cadastrar Usuário":
        st.title("👥 Cadastrar Usuário")

    elif escolha == "🏢 Cadastrar Coordenação":
        st.title("🏢 Cadastrar Coordenação")

    elif escolha == "🔄 Movimentação de Entrada e Saída":
        st.title("🔄 Movimentação de Entrada e Saída")

    elif escolha == "👤 Perfil":
        # Tela de Perfil (Sua Imagem 4)
        st.title("👤 Meu Perfil")
        st.write(f"**Usuário Atual:** {st.session_state.NOME_USUARIO_LOGADO}")
        st.write("**Lotação:** NGI Carajás / ICMBio")

    elif escolha == "🔴 Sair":
        # Altera os estados para deslogar e joga o usuário para a tela de login
        st.session_state.autenticado = False
        st.session_state.sub_tela_login = "login"
        
        # Recarrega o Streamlit instantaneamente para aplicar a mudança
        st.rerun()
