import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

# ==========================================
# 1. CONFIGURAÇÕES DA PÁGINA
# ==========================================
st.set_page_config(
    page_title="Gestão de Almoxarifado - NGI Carajás",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilização CSS para emular o tema escuro/azul institucional
st.markdown("""
    <style>
    .main { background-color: #0e1117; color: #ffffff; }
    [data-testid="stSidebar"] { background-color: #161b22; }
    div.stButton > button:first-child {
        background-color: #0066cc; color: white; border-radius: 5px;
    }
    div.stButton > button:first-child:hover {
        background-color: #0052a3; border-color: #0052a3;
    }
    .metric-card {
        background-color: #1d242c; padding: 15px; border-radius: 8px;
        border-left: 5px solid #0066cc; margin-bottom: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. INICIALIZAÇÃO DO ESTADO DA SESSÃO (DATA)
# ==========================================
if "usuarios" not in st.session_state:
    st.session_state.usuarios = pd.DataFrame([
        {"Usuario": "admin", "Senha": "123", "Nome": "Administrador", "Setor": "TI"},
        {"Usuario": "almoxarife", "Senha": "456", "Nome": "João Silva", "Setor": "Almoxarifado"}
    ])

if "produtos" not in st.session_state:
    st.session_state.produtos = pd.DataFrame([
        {"Código": "PROD001", "Item": "Papel A4 Reame", "Categoria": "Expediente", "Estoque Atual": 45, "Estoque Mínimo": 10, "Unidade": "Unidade"},
        {"Código": "PROD002", "Item": "Caneta Azul", "Categoria": "Expediente", "Estoque Atual": 120, "Estoque Mínimo": 20, "Unidade": "Unidade"},
        {"Código": "PROD003", "Item": "Cartucho HP Preto", "Categoria": "Informática", "Estoque Atual": 4, "Estoque Mínimo": 5, "Unidade": "Unidade"},
        {"Código": "PROD004", "Item": "Detergente Líquido", "Categoria": "Limpeza", "Estoque Atual": 18, "Estoque Mínimo": 15, "Unidade": "Litro"},
        {"Código": "PROD005", "Item": "Pasta Suspensa", "Categoria": "Expediente", "Estoque Atual": 8, "Estoque Mínimo": 15, "Unidade": "Unidade"}
    ])

if "historico" not in st.session_state:
    st.session_state.historico = pd.DataFrame([
        {"Data/Hora": "2026-06-28 09:30", "Tipo": "Entrada", "Código": "PROD001", "Item": "Papel A4 Reame", "Qtd": 20, "Responsável": "João Silva", "Destino/Origem": "Fornecedor Distribuidora X"},
        {"Data/Hora": "2026-06-28 14:15", "Tipo": "Saída", "Código": "PROD003", "Item": "Cartucho HP Preto", "Qtd": 2, "Responsável": "João Silva", "Destino/Origem": "Setor de Recursos Humanos"},
        {"Data/Hora": "2026-06-29 10:00", "Tipo": "Entrada", "Código": "PROD004", "Item": "Detergente Líquido", "Qtd": 10, "Responsável": "Administrador", "Destino/Origem": "Almoxarifado Central"},
        {"Data/Hora": "2026-06-29 16:45", "Tipo": "Saída", "Código": "PROD002", "Item": "Caneta Azul", "Qtd": 30, "Responsável": "João Silva", "Destino/Origem": "Setor de Fiscalização"}
    ])

if "logado" not in st.session_state:
    st.session_state.logado = False
if "usuario_atual" not in st.session_state:
    st.session_state.usuario_atual = None
if "sub_tela_login" not in st.session_state:
    st.session_state.sub_tela_login = "login"

# ==========================================
# 3. SISTEMA DE AUTENTICAÇÃO (LOGIN)
# ==========================================
def realizar_login(u, s):
    df_user = st.session_state.usuarios
    # Correção realizada na linha abaixo para evitar SyntaxError
    if u in df_user["Usuario"].values:
        senha_correta = str(df_user[df_user["Usuario"] == u]["Senha"].values[0])
        if str(s) == senha_correta:
            st.session_state.logado = True
            st.session_state.usuario_atual = df_user[df_user["Usuario"] == u]["Nome"].values[0]
            st.success(f"Bem-vindo, {st.session_state.usuario_atual}!")
            st.rerun()
        else:
            st.error("Senha incorreta.")
    else:
        st.error("Usuário não cadastrado.")

def realizar_logout():
    st.session_state.logado = False
    st.session_state.usuario_atual = None
    st.rerun()

# Interface Gráfica de Login
if not st.session_state.logado:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<div style='height: 80px;'></div>", unsafe_allow_html=True)
        st.markdown("<h2 style='text-align: center; color: #0066cc;'>📦 NGI Carajás</h2>", unsafe_allow_html=True)
        st.markdown("<h4 style='text-align: center; margin-bottom: 30px;'>Gestão de Almoxarifado</h4>", unsafe_allow_html=True)
        
        with st.container():
            st.markdown("<div style='background-color: #161b22; padding: 30px; border-radius: 10px; border: 1px solid #30363d;'>", unsafe_allow_html=True)
            
            if st.session_state.sub_tela_login == "login":
                campo_usuario = st.text_input("Usuário")
                campo_senha = st.text_input("Senha", type="password")
                
                if st.button("Entrar", use_container_width=True):
                    realizar_login(campo_usuario, campo_senha)
                
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Esqueci minha senha", use_container_width=True):
                    st.session_state.sub_tela_login = "esqueci"
                    st.rerun()
            
            elif st.session_state.sub_tela_login == "esqueci":
                st.markdown("<p style='font-size: 0.9rem;'>Insira seu e-mail corporativo cadastrado para receber as instruções.</p>", unsafe_allow_html=True)
                email_recuperar = st.text_input("E-mail corporativo", placeholder="usuario@icmbio.gov.br")
                
                if st.button("Enviar Instruções", type="primary", use_container_width=True):
                    st.success("Se o e-mail estiver correto, as instruções foram enviadas!")
                
                if st.button("Voltar para o Login", use_container_width=True):
                    st.session_state.sub_tela_login = "login"
                    st.rerun()
            
            st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# ==========================================
# 4. PAINEL PRINCIPAL (SISTEMA LOGADO)
# ==========================================
st.sidebar.markdown(f"### 👤 {st.session_state.usuario_atual}")
st.sidebar.markdown("---")

menu = st.sidebar.radio(
    "Navegação",
    ["Dashboard Geral", "Cadastro de Itens", "Entradas no Estoque", "Saídas / Requisições", "Histórico de Movimentações"]
)

st.sidebar.markdown("---")
if st.sidebar.button("🚪 Sair do Sistema", use_container_width=True):
    realizar_logout()

# ------------------------------------------
# TELA: DASHBOARD GERAL
# ------------------------------------------
if menu == "Dashboard Geral":
    st.title("📊 Painel de Controle de Estoque")
    st.markdown("Visão em tempo real dos insumos e materiais do almoxarifado.")
    
    # Cálculos das métricas
    total_itens = len(st.session_state.produtos)
    total_unidades = st.session_state.produtos["Estoque Atual"].sum()
    
    # Alerta de estoque crítico
    itens_criticos_df = st.session_state.produtos[st.session_state.produtos["Estoque Atual"] <= st.session_state.produtos["Estoque Mínimo"]]
    total_criticos = len(itens_criticos_df)
    
    col_m1, col_m2, col_m3 = st.columns(3)
    with col_m1:
        st.markdown(f"<div class='metric-card'><h4>Total de Itens Cadastrados</h4><h2>{total_itens}</h2></div>", unsafe_allow_html=True)
    with col_m2:
        st.markdown(f"<div class='metric-card'><h4>Volume em Estoque (Total)</h4><h2>{total_unidades} u.</h2></div>", unsafe_allow_html=True)
    with col_m3:
        cor_critico = "#ff3333" if total_criticos > 0 else "#00cc66"
        st.markdown(f"<div class='metric-card' style='border-left: 5px solid {cor_critico};'><h4>Itens Abaixo do Mínimo</h4><h2>{total_criticos}</h2></div>", unsafe_allow_html=True)
    
    st.markdown("### 🛒 Situação Geral dos Itens")
    st.dataframe(st.session_state.produtos, use_container_width=True, hide_index=True)
    
    if total_criticos > 0:
        st.markdown("### ⚠️ Atenção Urgente: Reposição Necessária")
        st.warning("Os itens abaixo atingiram ou estão abaixo do limite de segurança:")
        st.dataframe(itens_criticos_df[["Código", "Item", "Estoque Atual", "Estoque Mínimo"]], use_container_width=True, hide_index=True)
    
    # Seção de Gráficos Informativos com Plotly
    st.markdown("### 📈 Análise Gráfica")
    col_g1, col_g2 = st.columns(2)
    
    with col_g1:
        fig_barra = px.bar(
            st.session_state.produtos, 
            x="Item", 
            y="Estoque Atual", 
            color="Categoria",
            title="Quantidade em Estoque por Item",
            template="plotly_dark"
        )
        st.plotly_chart(fig_barra, use_container_width=True)
        
    with col_g2:
        fig_pizza = px.pie(
            st.session_state.produtos, 
            names="Categoria", 
            values="Estoque Atual",
            title="Distribuição de Estoque por Categoria",
            template="plotly_dark",
            hole=0.4
        )
        st.plotly_chart(fig_pizza, use_container_width=True)

# ------------------------------------------
# TELA: CADASTRO DE ITENS
# ------------------------------------------
elif menu == "Cadastro de Itens":
    st.title("📝 Cadastro de Novos Materiais")
    st.markdown("Adicione novos itens ao catálogo de materiais do almoxarifado.")
    
    with st.form("form_cadastro", clear_on_submit=True):
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            novo_codigo = st.text_input("Código do Item (Ex: PROD006)")
            novo_nome = st.text_input("Descrição / Nome do Item")
            nova_categoria = st.selectbox("Categoria", ["Expediente", "Limpeza", "Informática", "Manutenção", "Outros"])
        with col_c2:
            nova_unidade = st.selectbox("Unidade de Medida", ["Unidade", "Quilo", "Litro", "Pacote", "Caixa"])
            estoque_ini = st.number_input("Estoque Inicial", min_value=0, step=1, value=0)
            estoque_min = st.number_input("Estoque Mínimo de Segurança", min_value=0, step=1, value=5)
            
        botao_cadastrar = st.form_submit_button("Salvar Item")
        
        if botao_cadastrar:
            if not novo_codigo or not novo_nome:
                st.error("Por favor, preencha os campos obrigatórios de Código e Descrição.")
            elif novo_codigo in st.session_state.produtos["Código"].values:
                st.error("Este código de produto já está cadastrado no sistema.")
            else:
                novo_item_df = pd.DataFrame([{
                    "Código": novo_codigo, "Item": novo_nome, "Categoria": nova_categoria,
                    "Estoque Atual": estoque_ini, "Estoque Mínimo": estoque_min, "Unidade": nova_unidade
                }])
                st.session_state.produtos = pd.concat([st.session_state.produtos, novo_item_df], ignore_index=True)
                
                # Registra no histórico se houver carga inicial
                if estoque_ini > 0:
                    novo_hist = pd.DataFrame([{
                        "Data/Hora": datetime.now().strftime("%Y-%m-%d %H:%M"), "Tipo": "Entrada",
                        "Código": novo_codigo, "Item": novo_nome, "Qtd": estoque_ini,
                        "Responsável": st.session_state.usuario_atual, "Destino/Origem": "Carga Inicial de Cadastro"
                    }])
                    st.session_state.historico = pd.concat([st.session_state.historico, novo_hist], ignore_index=True)
                
                st.success(f"Sucesso! O item '{novo_nome}' foi incluído no sistema.")
                st.rerun()

# ------------------------------------------
# TELA: ENTRADAS NO ESTOQUE
# ------------------------------------------
elif menu == "Entradas no Estoque":
    st.title("📥 Registro de Entrada de Mercadorias")
    st.markdown("Utilize esta tela para registrar compras, devoluções ou recebimentos de insumos.")
    
    lista_produtos = st.session_state.produtos["Item"].tolist()
    item_selecionado = st.selectbox("Selecione o Item que está entrando:", lista_produtos)
    
    row_produto = st.session_state.produtos[st.session_state.produtos["Item"] == item_selecionado].iloc[0]
    st.info(f"**Código:** {row_produto['Código']}  |  **Estoque Atual:** {row_produto['Estoque Atual']} {row_produto['Unidade']}(s)")
    
    with st.form("form_entrada", clear_on_submit=True):
        col_e1, col_e2 = st.columns(2)
        with col_e1:
            qtd_entrada = st.number_input("Quantidade de Entrada", min_value=1, step=1, value=1)
        with col_e2:
            origem_entrada = st.text_input("Origem / Fornecedor / Nota Fiscal")
            
        botao_confirmar_entrada = st.form_submit_button("Confirmar Entrada")
        
        if botao_confirmar_entrada:
            # Atualiza o estoque atual na tabela de produtos
            st.session_state.produtos.loc[st.session_state.produtos["Item"] == item_selecionado, "Estoque Atual"] += qtd_entrada
            
            # Registra a movimentação no histórico
            novo_hist = pd.DataFrame([{
                "Data/Hora": datetime.now().strftime("%Y-%m-%d %H:%M"), "Tipo": "Entrada",
                "Código": row_produto['Código'], "Item": item_selecionado, "Qtd": qtd_entrada,
                "Responsável": st.session_state.usuario_atual, "Destino/Origem": origem_entrada if origem_entrada else "Não especificado"
            }])
            st.session_state.historico = pd.concat([st.session_state.historico, novo_hist], ignore_index=True)
            
            st.success(f"Entrada de {qtd_entrada} unidades de '{item_selecionado}' processada com sucesso!")
            st.rerun()

# ------------------------------------------
# TELA: SAÍDAS / REQUISIÇÕES
# ------------------------------------------
elif menu == "Saídas / Requisições":
    st.title("📤 Baixa e Requisição de Materiais")
    st.markdown("Registre a entrega de insumos para setores internos ou servidores solicitantes.")
    
    lista_produtos = st.session_state.produtos["Item"].tolist()
    item_selecionado = st.selectbox("Selecione o Item para dar baixa:", lista_produtos)
    
    row_produto = st.session_state.produtos[st.session_state.produtos["Item"] == item_selecionado].iloc[0]
    estoque_disponivel = row_produto['Estoque Atual']
    
    st.info(f"**Código:** {row_produto['Código']}  |  **Estoque Disponível:** {estoque_disponivel} {row_produto['Unidade']}(s)")
    
    with st.form("form_saida", clear_on_submit=True):
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            qtd_saida = st.number_input("Quantidade de Saída", min_value=1, max_value=int(estoque_disponivel) if estoque_disponivel > 0 else 1, step=1, value=1)
        with col_s2:
            destino_saida = st.text_input("Setor de Destino / Beneficiário")
            
        botao_confirmar_saida = st.form_submit_button("Confirmar Entrega / Saída")
        
        if botao_confirmar_saida:
            if estoque_disponivel <= 0:
                st.error("Impossível realizar a operação. O estoque deste produto está totalmente esgotado.")
            elif qtd_saida > estoque_disponivel:
                st.error(f"Quantidade indisponível. Estoque máximo de apenas {estoque_disponivel} unidades.")
            else:
                # Subtrai do estoque atual do produto
                st.session_state.produtos.loc[st.session_state.produtos["Item"] == item_selecionado, "Estoque Atual"] -= qtd_saida
                
                # Registra no histórico global
                novo_hist = pd.DataFrame([{
                    "Data/Hora": datetime.now().strftime("%Y-%m-%d %H:%M"), "Tipo": "Saída",
                    "Código": row_produto['Código'], "Item": item_selecionado, "Qtd": qtd_saida,
                    "Responsável": st.session_state.usuario_atual, "Destino/Origem": destino_saida if destino_saida else "Não especificado"
                }])
                st.session_state.historico = pd.concat([st.session_state.historico, novo_hist], ignore_index=True)
                
                st.success(f"Baixa efetuada! {qtd_saida} unidades de '{item_selecionado}' entregues para o destino.")
                st.rerun()

# ------------------------------------------
# TELA: HISTÓRICO DE MOVIMENTAÇÕES
# ------------------------------------------
elif menu == "Histórico de Movimentações":
    st.title("📜 Histórico Geral de Fluxo")
    st.markdown("Auditoria completa das movimentações de entrada e saída realizadas no sistema.")
    
    # Filtros rápidos do histórico
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        filtro_tipo = st.multiselect("Filtrar por Tipo de Operação", ["Entrada", "Saída"], default=["Entrada", "Saída"])
    with col_f2:
        busca_item = st.text_input("Buscar por Nome do Item ou Código")
        
    df_filtrado = st.session_state.historico.copy()
    
    # Aplica os filtros na tabela
    if filtro_tipo:
        df_filtrado = df_filtrado[df_filtrado["Tipo"].isin(filtro_tipo)]
    if busca_item:
        df_filtrado = df_filtrado[df_filtrado["Item"].str.contains(busca_item, case=False) | df_filtrado["Código"].str.contains(busca_item, case=False)]
        
    st.markdown("---")
    if df_filtrado.empty:
        st.info("Nenhuma movimentação foi encontrada para os filtros aplicados.")
    else:
        # Exibe a tabela ordenada da mais recente para a mais antiga
        st.dataframe(df_filtrado.iloc[::-1], use_container_width=True, hide_index=True)
