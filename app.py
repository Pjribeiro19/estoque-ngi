import streamlit as st
import pandas as pd
from datetime import datetime
import os

# Configuração da Página
st.set_page_config(
    page_title="Gestão de Estoque - NGI Carajás", 
    page_icon="🌿", 
    layout="wide"
)

# --- CONFIGURAÇÃO DO USUÁRIO ATUAL ---
NOME_USUARIO_LOGADO = "João Paulo"

# -----------------------------------------------------------------------------
# FUNÇÕES PARA PERSISTÊNCIA DE DADOS EM CSV (Compartilhado entre testadores)
# -----------------------------------------------------------------------------
def carregar_dados(nome_arquivo, colunas, dados_padrao=[]):
    if not os.path.exists(nome_arquivo):
        df = pd.DataFrame(dados_padrao, columns=colunas)
        df.to_csv(nome_arquivo, index=False, encoding='utf-8')
        return df
    try:
        return pd.read_csv(nome_arquivo, encoding='utf-8', dtype={'Código': str})
    except:
        return pd.DataFrame(dados_padrao, columns=colunas)

def salvar_dados(df, nome_arquivo):
    df.to_csv(nome_arquivo, index=False, encoding='utf-8')

# Inicializando arquivos locais para persistir os testes do link
ARQUIVO_PROD = "produtos_dados.csv"
ARQUIVO_MOV = "movimentacoes_dados.csv"
ARQUIVO_USER = "usuarios_dados.csv"
ARQUIVO_COORD = "coordenacoes_dados.csv"

# Dados Iniciais Padrão se o arquivo não existir
padrao_prod = [
    {"Código": "001", "Item": "Capacete de Segurança", "Quantidade": 15, "Categoria": "EPI"},
    {"Código": "002", "Item": "Luva de Raspa", "Quantidade": 50, "Categoria": "EPI"}
]
padrao_coord = [
    {"Sigla": "COTEC", "Nome": "Coordenação Técnica"},
    {"Sigla": "COLOG", "Nome": "Coordenação de Logística"}
]
padrao_user = [
    {"Nome": "Administrador Padrão", "E-mail": "admin@ngi.com", "Perfil": "Administrador"}
]

# Carrega do arquivo físico
df_produtos = carregar_dados(ARQUIVO_PROD, ["Código", "Item", "Quantidade", "Categoria"], padrao_prod)
df_movimentacoes = carregar_dados(ARQUIVO_MOV, ["Data", "Tipo", "Código", "Item", "Quantidade", "Responsável pela Retirada", "Coordenação"])
df_usuarios = carregar_dados(ARQUIVO_USER, ["Nome", "E-mail", "Perfil"], padrao_user)
df_coordenacoes = carregar_dados(ARQUIVO_COORD, ["Sigla", "Nome"], padrao_coord)

if "categorias" not in st.session_state:
    st.session_state.categorias = ["EPI", "Material de Escritório", "Informática", "Limpeza", "Copa"]

# -----------------------------------------------------------------------------
# ESTILIZAÇÃO CUSTOMIZADA
# -----------------------------------------------------------------------------
st.markdown(f"""
    <style>
    [data-testid="stSidebarNav"] {{display: none;}}
    [data-testid="stHeader"] {{background: transparent !important; z-index: 100;}}
    .custom-header {{
        position: fixed;
        top: 0; left: 0; right: 0; height: 60px;
        background-color: #4CAF50 !important;
        display: flex; justify-content: space-between; align-items: center;
        padding: 0 30px; z-index: 999999; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    }}
    .header-title {{ color: white !important; font-size: 1.25rem !important; font-weight: bold !important; }}
    .header-user {{ color: white !important; font-size: 1.05rem !important; font-weight: 500 !important; }}
    .block-container {{ padding-top: 5rem !important; }}
    [data-testid="stSidebarUserContent"] {{ padding-top: 3.5rem !important; }}
    [data-testid="stSidebar"] {{ background-color: #fcfaff !important; border-right: 1px solid #efe9f5; }}
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {{
        color: #333333 !important; font-weight: 500; padding: 12px 16px; border-radius: 4px; margin-bottom: 2px; transition: all 0.2s ease;
    }}
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover {{ background-color: #e2eed7 !important; color: #1e5934 !important; cursor: pointer; }}
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] input:checked + div {{ background-color: #cce2b4 !important; border-radius: 4px; color: #1e5934 !important; font-weight: bold !important; }}
    div.stButton > button:first-child[kind="primary"] {{ background-color: #4CAF50 !important; border-color: #4CAF50 !important; color: white !important; }}
    </style>
    <div class="custom-header">
        <div class="header-title">Gestão de Estoque - NGI Carajás</div>
        <div class="header-user">👤 {NOME_USUARIO_LOGADO}</div>
    </div>
""", unsafe_allow_html=True)

# BARRA LATERAL
with st.sidebar:
    menu_opcoes = [
        "🎛️ Painel Geral", "➕ Cadastrar Produto", "🗂️ Cadastrar Categoria",
        "👥 Cadastrar Usuário", "🏢 Cadastrar Coordenação", "🔄 Movimentação de Entrada e Saída", "👤 Perfil", "🚪 Sair"
    ]
    escolha = st.radio("", menu_opcoes, label_visibility="collapsed")

# -----------------------------------------------------------------------------
# LÓGICA DAS TELAS
# -----------------------------------------------------------------------------

if escolha == "🎛️ Painel Geral":
    st.title("🎛️ Painel Geral de Estoque")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total de Itens Cadastrados", len(df_produtos))
    c2.metric("Produtos Esgotados", len(df_produtos[df_produtos['Quantidade'] == 0]))
    c3.metric("Movimentações Realizadas", len(df_movimentacoes))

    st.write("---")
    st.write("### 🔍 Ferramentas de Busca e Filtro")
    col_filtro1, col_filtro2 = st.columns([2, 1])
    termo_busca = col_filtro1.text_input("Buscar por Nome do Material ou Código:", placeholder="Digite para pesquisar...")
    categoria_selecionada = col_filtro2.selectbox("Filtrar por Categoria:", ["Todas"] + list(st.session_state.categorias))
    
    df_filtrado = df_produtos.copy()
    if termo_busca:
        df_filtrado = df_filtrado[df_filtrado['Item'].str.contains(termo_busca, case=False, na=False) | df_filtrado['Código'].str.contains(termo_busca, case=False, na=False)]
    if categoria_selecionada != "Todas":
        df_filtrado = df_filtrado[df_filtrado['Category'] == categoria_selecionada if 'Category' in df_filtrado.columns else df_filtrado['Categoria'] == categoria_selecionada]

    st.write("### 📋 Estoque Atualizado")
    if df_filtrado.empty:
        st.info("Nenhum material encontrado.")
    else:
        def destacar_zerados(row):
            return ['background-color: #ffebee; color: #c62828; font-weight: bold'] * len(row) if row['Quantidade'] == 0 else [''] * len(row)
        st.dataframe(df_filtrado.style.apply(destacar_zerados, axis=1), use_container_width=True, hide_index=True)

elif escolha == "➕ Cadastrar Produto":
    st.title("➕ Gerenciamento de Produtos")
    aba_cad_prod, aba_gerenciar_prod = st.tabs(["➕ Novo Material", "✏️ Editar / Excluir Produtos"])
    
    with aba_cad_prod:
        with st.form("form_novo_produto", clear_on_submit=True):
            col_a, col_b = st.columns(2)
            cod = col_a.text_input("Código")
            nome_it = col_b.text_input("Nome do Material")
            cat_it = col_a.selectbox("Categoria", st.session_state.categorias)
            st.caption("ℹ️ Novos materiais nascem com saldo inicial 0. Adicione quantidades na aba 'Movimentação'.")
            
            if st.form_submit_button("Finalizar Cadastro", type="primary"):
                if cod and nome_it:
                    if str(cod) in df_produtos["Código"].astype(str).values:
                        st.error(f"Erro! Código {cod} já existe.")
                    else:
                        novo_p = pd.DataFrame([{"Código": str(cod), "Item": nome_it, "Quantidade": 0, "Categoria": cat_it}])
                        df_produtos = pd.concat([df_produtos, novo_p], ignore_index=True)
                        salvar_dados(df_produtos, ARQUIVO_PROD)
                        st.success(f"Sucesso! {nome_it} cadastrado.")
                        st.rerun()
                else:
                    st.error("Preencha todos os campos!")
                    
    with aba_gerenciar_prod:
        if not df_produtos.empty:
            st.dataframe(df_produtos, use_container_width=True, hide_index=True)
            idx_p = st.selectbox("Selecione para modificar:", df_produtos.index, format_func=lambda x: f"{df_produtos.loc[x, 'Código']} - {df_produtos.loc[x, 'Item']}")
            col_ed1, col_ed2 = st.columns(2)
            edit_cod = col_ed1.text_input("Código:", value=df_produtos.loc[idx_p, "Código"])
            edit_item = col_ed2.text_input("Nome:", value=df_produtos.loc[idx_p, "Item"])
            edit_qtd = col_ed1.number_input("Quantidade:", min_value=0, value=int(df_produtos.loc[idx_p, "Quantidade"]))
            edit_cat = col_ed2.selectbox("Categoria:", st.session_state.categorias, index=st.session_state.categorias.index(df_produtos.loc[idx_p, "Categoria"]) if df_produtos.loc[idx_p, "Categoria"] in st.session_state.categorias else 0)
            
            col_b1, col_b2 = st.columns([1, 4])
            if col_b1.button("Salvar Alterações", type="primary"):
                df_produtos.loc[idx_p] = [str(edit_cod), edit_item, edit_qtd, edit_cat]
                salvar_dados(df_produtos, ARQUIVO_PROD)
                st.success("Atualizado!")
                st.rerun()
            if col_b2.button("❌ Excluir Produto"):
                df_produtos = df_produtos.drop(idx_p).reset_index(drop=True)
                salvar_dados(df_produtos, ARQUIVO_PROD)
                st.warning("Removido!")
                st.rerun()

elif escolha == "🗂️ Cadastrar Categoria":
    st.title("🗂️ Gerenciamento de Categorias")
    col_cat1, col_cat2 = st.columns([1, 2])
    with col_cat1:
        nova_cat = st.text_input("Nome da Nova Categoria:")
        if st.button("Adicionar Categoria", type="primary"):
            if nova_cat and nova_cat.strip() not in st.session_state.categorias:
                st.session_state.categorias.append(nova_cat.strip())
                st.success("Adicionada com sucesso!")
    with col_cat2:
        st.dataframe(pd.DataFrame(st.session_state.categorias, columns=["Categorias"]), use_container_width=True, hide_index=True)

elif escolha == "👥 Cadastrar Usuário":
    st.title("👥 Gerenciamento de Usuários")
    aba_cad, aba_edit = st.tabs(["➕ Novo Usuário", "✏️ Gerenciar"])
    with aba_cad:
        with st.form("cad_user", clear_on_submit=True):
            n = st.text_input("Nome")
            e = st.text_input("E-mail")
            p = st.selectbox("Perfil", ["Administrador", "Usuário Comum"])
            if st.form_submit_button("Salvar", type="primary"):
                if n:
                    novo_u = pd.DataFrame([{"Nome": n, "E-mail": e, "Perfil": p}])
                    df_usuarios = pd.concat([df_usuarios, novo_u], ignore_index=True)
                    salvar_dados(df_usuarios, ARQUIVO_USER)
                    st.success("Usuário gravado com sucesso!")
                    st.rerun()
    with aba_edit:
        st.dataframe(df_usuarios, use_container_width=True, hide_index=True)

elif escolha == "🏢 Cadastrar Coordenação":
    st.title("🏢 Gerenciamento de Coordenações")
    aba_coord_cad, aba_coord_view = st.tabs(["➕ Nova Coordenação", "📋 Cadastradas"])
    
    with aba_coord_cad:
        with st.form("cad_coord", clear_on_submit=True):
            s = st.text_input("Sigla (Ex: COTEC)")
            nc = st.text_input("Nome da Coordenação")
            if st.form_submit_button("Cadastrar", type="primary"):
                if s and nc:
                    novo_c = pd.DataFrame([{"Sigla": s.upper(), "Nome": nc}])
                    df_coordenacoes = pd.concat([df_coordenacoes, novo_c], ignore_index=True)
                    salvar_dados(df_coordenacoes, ARQUIVO_COORD)
                    st.success("Coordenação gravada com sucesso!")
                    st.rerun()
                else:
                    st.error("Preencha todos os campos!")
    with aba_coord_view:
        st.dataframe(df_coordenacoes, use_container_width=True, hide_index=True)

elif escolha == "🔄 Movimentação de Entrada e Saída":
    st.title("🔄 Movimentação de Entrada e Saída")
    aba_entrada, aba_saida, aba_historico = st.tabs(["📥 Registrar Entrada", "📤 Registrar Saída", "📋 Histórico"])
    
    with aba_entrada:
        if df_produtos.empty:
            st.warning("Nenhum produto cadastrado para movimentar.")
        else:
            with st.form("form_ent", clear_on_submit=True):
                data_e = st.date_input("Data:", value=datetime.today())
                idx_e = st.selectbox("Material:", df_produtos.index, format_func=lambda x: f"{df_produtos.loc[x, 'Código']} - {df_produtos.loc[x, 'Item']} (Saldo: {df_produtos.loc[x, 'Quantidade']})")
                qtd_e = st.number_input("Quantidade de Entrada:", min_value=1, step=1)
                if st.form_submit_button("Confirmar Entrada", type="primary"):
                    df_produtos.loc[idx_e, "Quantidade"] += qtd_e
                    nova_m = pd.DataFrame([{"Data": data_e.strftime("%d/%m/%Y"), "Tipo": "Entrada", "Código": df_produtos.loc[idx_e, "Código"], "Item": df_produtos.loc[idx_e, "Item"], "Quantidade": qtd_e, "Responsável pela Retirada": "Almoxarifado", "Coordenação": "-"}])
                    df_movimentacoes = pd.concat([df_movimentacoes, nova_m], ignore_index=True)
                    salvar_dados(df_produtos, ARQUIVO_PROD)
                    salvar_dados(df_movimentacoes, ARQUIVO_MOV)
                    st.success("Entrada registrada com sucesso!")
                    st.rerun()

    with aba_saida:
        if df_produtos.empty:
            st.warning("Nenhum produto cadastrado para movimentar.")
        else:
            with st.form("form_sai", clear_on_submit=True):
                data_s = st.date_input("Data Saída:", value=datetime.today())
                idx_s = st.selectbox("Material para Saída:", df_produtos.index, format_func=lambda x: f"{df_produtos.loc[x, 'Código']} - {df_produtos.loc[x, 'Item']} (Saldo: {df_produtos.loc[x, 'Quantidade']})")
                qtd_s = st.number_input("Quantidade:", min_value=1, step=1)
                lista_c = df_coordenacoes["Sigla"].tolist() if not df_coordenacoes.empty else ["-"]
                coord_s = st.selectbox("Coordenação Destino:", lista_c)
                resp_s = st.text_input("Responsável pela Retirada:")
                
                if st.form_submit_button("Confirmar Saída", type="primary"):
                    if qtd_s > df_produtos.loc[idx_s, "Quantidade"]:
                        st.error("Saldo insuficiente!")
                    elif not resp_s.strip():
                        st.error("Informe o responsável!")
                    else:
                        df_produtos.loc[idx_s, "Quantidade"] -= qtd_s
                        nova_m = pd.DataFrame([{"Data": data_s.strftime("%d/%m/%Y"), "Tipo": "Saída", "Código": df_produtos.loc[idx_s, "Código"], "Item": df_produtos.loc[idx_s, "Item"], "Quantidade": qtd_s, "Responsável pela Retirada": resp_s, "Coordenação": coord_s}])
                        df_movimentacoes = pd.concat([df_movimentacoes, nova_m], ignore_index=True)
                        salvar_dados(df_produtos, ARQUIVO_PROD)
                        salvar_dados(df_movimentacoes, ARQUIVO_MOV)
                        st.success("Saída registrada com sucesso!")
                        st.rerun()

    with aba_historico:
        if df_movimentacoes.empty:
            st.info("Nenhuma movimentação realizada ainda.")
        else:
            st.dataframe(df_movimentacoes, use_container_width=True, hide_index=True)

elif escolha == "👤 Perfil":
    st.title("👤 Perfil")
    st.write(f"Usuário ativo: {NOME_USUARIO_LOGADO}")

elif escolha == "🚪 Sair":
    st.title("Sessão Terminada")
