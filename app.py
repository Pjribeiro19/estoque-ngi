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

# -----------------------------------------------------------------------------
# FUNÇÕES PARA PERSISTÊNCIA DE DADOS EM CSV (Evita perder dados na Web)
# -----------------------------------------------------------------------------
def carregar_dados(nome_arquivo, colunas, dados_padrao=[]):
    if not os.path.exists(nome_arquivo):
        df = pd.DataFrame(dados_padrao, columns=colunas)
        df.to_csv(nome_arquivo, index=False, encoding='utf-8')
        return df
    try:
        df = pd.read_csv(nome_arquivo, encoding='utf-8')
        for col in colunas:
            if col not in df.columns:
                df[col] = "123" if col == "Senha" else ""
        return df
    except:
        return pd.DataFrame(dados_padrao, columns=colunas)

def salvar_dados(nome_arquivo, df):
    df.to_csv(nome_arquivo, index=False, encoding='utf-8')

# Definição dos nomes dos arquivos locais
ARQUIVO_PRODUTOS = "produtos.csv"
ARQUIVO_USUARIOS = "usuarios.csv"
ARQUIVO_COORD = "coordenacoes.csv"
ARQUIVO_CATEGORIAS = "categorias.csv"
ARQUIVO_MOV = "movimentacoes.csv"

# -----------------------------------------------------------------------------
# BANCO DE DADOS PERSISTENTE (Session State + Carregamento dos CSVs)
# -----------------------------------------------------------------------------
if "produtos" not in st.session_state:
    PRODS_PADRAO = [
        {"Código": "001", "Item": "Capacete de Segurança", "Quantidade": 15, "Categoria": "EPI"},
        {"Código": "002", "Item": "Resma Papel A4", "Quantidade": 0, "Categoria": "Material de Escritório"},
        {"Código": "003", "Item": "Luva de Raspa", "Quantidade": 50, "Categoria": "EPI"}
    ]
    st.session_state.produtos = carregar_dados(ARQUIVO_PRODUTOS, ["Código", "Item", "Quantidade", "Categoria"], PRODS_PADRAO)

if "usuarios" not in st.session_state:
    USERS_PADRAO = [
        {"Nome": "Administrador Padrão", "E-mail": "admin@ngi.com", "Senha": "123", "Perfil": "Administrador"},
        {"Nome": "João Paulo", "E-mail": "joao.paulo@ngi.com", "Senha": "123", "Perfil": "Administrador"}
    ]
    st.session_state.usuarios = carregar_dados(ARQUIVO_USUARIOS, ["Nome", "E-mail", "Senha", "Perfil"], USERS_PADRAO)

if "coordenacoes" not in st.session_state:
    COORD_PADRAO = [
        {"Sigla": "COTEC", "Nome": "Coordenação Técnica"},
        {"Sigla": "COLOG", "Nome": "Coordenação de Logística"}
    ]
    st.session_state.coordenacoes = carregar_dados(ARQUIVO_COORD, ["Sigla", "Nome"], COORD_PADRAO)

if "categorias" not in st.session_state:
    if os.path.exists(ARQUIVO_CATEGORIAS):
        try:
            st.session_state.categorias = pd.read_csv(ARQUIVO_CATEGORIAS)['Categoria'].tolist()
        except:
            st.session_state.categorias = ["EPI", "Material de Escritório", "Informática", "Limpeza", "Copa"]
    else:
        st.session_state.categorias = ["EPI", "Material de Escritório", "Informática", "Limpeza", "Copa"]
        pd.DataFrame(st.session_state.categorias, columns=['Categoria']).to_csv(ARQUIVO_CATEGORIAS, index=False, encoding='utf-8')

if "movimentacoes" not in st.session_state:
    st.session_state.movimentacoes = carregar_dados(ARQUIVO_MOV, ["Data", "Tipo", "Código", "Item", "Quantidade", "Responsável pela Retirada", "Coordenação"])

# --- SISTEMA DE LOGIN INTEGRADO ---
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario_logado" not in st.session_state:
    st.session_state.usuario_logado = "João Paulo"

# -----------------------------------------------------------------------------
# INTERFACE DE AUTENTICAÇÃO
# -----------------------------------------------------------------------------
if not st.session_state.autenticado:
    _, col_central, _ = st.columns([1.2, 1.4, 1.2])
    with col_central:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.markdown("""
            <div style="text-align: center; margin-bottom: 25px;">
                <span style="font-size: 70px;">🌿</span>
                <h2 style="color: #1e5934; font-family: sans-serif; font-weight: bold; margin: 10px 0 5px 0;">GESTÃO DE ESTOQUE</h2>
                <h5 style="color: #4CAF50; font-family: sans-serif; font-weight: 600; margin: 0; letter-spacing: 2px;">NGI CARAJÁS • ICMBio</h5>
            </div>
        """, unsafe_allow_html=True)
        
        with st.form("form_login_sistema"):
            email_input = st.text_input("E-mail", placeholder="seu.email@icmbio.gov.br")
            senha_input = st.text_input("Senha", type="password", placeholder="Digite sua senha")
            botao_entrar = st.form_submit_button("Entrar", type="primary", use_container_width=True)
            
            if botao_entrar:
                df_users = st.session_state.usuarios
                valido = df_users[(df_users["E-mail"].str.strip().str.lower() == email_input.strip().lower()) & (df_users["Senha"].astype(str).str.strip() == senha_input.strip())]
                if not valido.empty:
                    st.session_state.autenticado = True
                    st.session_state.usuario_logado = valido.iloc[0]["Nome"]
                    st.rerun()
                else:
                    st.error("E-mail ou senha incorretos.")
    st.stop()

NOME_USUARIO_LOGADO = st.session_state.usuario_logado

# -----------------------------------------------------------------------------
# ESTILIZAÇÃO CUSTOMIZADA
# -----------------------------------------------------------------------------
st.markdown(f"""
    <style>
    [data-testid="stSidebarNav"] {{display: none;}}
    [data-testid="stHeader"] {{background: transparent !important; z-index: 100;}}
    .custom-header {{
        position: fixed; top: 0; left: 0; right: 0; height: 60px;
        background-color: #4CAF50 !important; display: flex;
        justify-content: space-between; align-items: center; padding: 0 30px;
        z-index: 999999; box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    }}
    .header-title {{ color: white !important; font-size: 1.25rem !important; font-weight: bold !important; }}
    .header-user {{ color: white !important; font-size: 1.05rem !important; font-weight: 500 !important; }}
    .block-container {{ padding-top: 5rem !important; }}
    [data-testid="stSidebarUserContent"] {{ padding-top: 3.5rem !important; }}
    [data-testid="stSidebar"] {{ background-color: #fcfaff !important; border-right: 1px solid #efe9f5; }}
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {{
        color: #333333 !important; font-weight: 500; padding: 12px 16px; border-radius: 4px; margin-bottom: 2px;
    }}
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover {{ background-color: #e2eed7 !important; color: #1e5934 !important; }}
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] input:checked + div {{ background-color: #cce2b4 !important; color: #1e5934 !important; font-weight: bold !important; }}
    div.stButton > button:first-child[kind="primary"] {{ background-color: #4CAF50 !important; border-color: #4CAF50 !important; color: white !important; }}
    </style>
    <div class="custom-header">
        <div class="header-title">Gestão de Estoque - NGI Carajás</div>
        <div class="header-user">👤 {NOME_USUARIO_LOGADO}</div>
    </div>
""", unsafe_allow_html=True)

# Menu Lateral
with st.sidebar:
    menu_opcoes = ["🎛️ Painel Geral", "➕ Cadastrar Produto", "🗂️ Cadastrar Categoria", "👥 Cadastrar Usuário", "🏢 Cadastrar Coordenação", "🔄 Movimentação de Entrada e Saída", "👤 Perfil", "🚪 Sair"]
    escolha = st.radio("", menu_opcoes, label_visibility="collapsed")

# -----------------------------------------------------------------------------
# CONTROLADORES DE TELAS
# -----------------------------------------------------------------------------

# TELA: PAINEL GERAL
if escolha == "🎛️ Painel Geral":
    st.title("🎛️ Painel Geral de Estoque")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total de Itens Cadastrados", len(st.session_state.produtos))
    c2.metric("Produtos Esgotados", len(st.session_state.produtos[st.session_state.produtos['Quantidade'] == 0]))
    c3.metric("Movimentações Realizadas", len(st.session_state.movimentacoes))
    
    st.write("---")
    st.write("### 🔍 Ferramentas de Busca e Filtro")
    col_f1, col_f2 = st.columns([2, 1])
    t_busca = col_f1.text_input("Buscar por Nome do Material ou Código:", placeholder="Digite para pesquisar...")
    c_selecionada = col_f2.selectbox("Filtrar por Categoria:", ["Todas"] + list(st.session_state.categorias))
    
    df_filtrado = st.session_state.produtos.copy()
    if t_busca:
        df_filtrado = df_filtrado[df_filtrado['Item'].str.contains(t_busca, case=False, na=False) | df_filtrado['Código'].astype(str).str.contains(t_busca, case=False, na=False)]
    if c_selecionada != "Todas":
        df_filtrado = df_filtrado[df_filtrado['Categoria'] == c_selecionada]
        
    st.write("### 📋 Estoque Atualizado")
    if df_filtrado.empty:
        st.info("Nenhum material encontrado.")
    else:
        def destacar_zerados(row):
            return ['background-color: #ffebee; color: #c62828; font-weight: bold'] * len(row) if row['Quantidade'] == 0 else [''] * len(row)
        st.dataframe(df_filtrado.style.apply(destacar_zerados, axis=1), use_container_width=True, hide_index=True)

# TELA: CADASTRAR PRODUTO (COM EXCLUSÃO ATIVA)
elif escolha == "➕ Cadastrar Produto":
    st.title("➕ Gerenciamento de Produtos")
    aba_cad, aba_gerenciar = st.tabs(["➕ Novo Material", "✏️ Editar / Excluir Produtos"])
    
    with aba_cad:
        with st.form("form_novo_produto", clear_on_submit=True):
            col_a, col_b = st.columns(2)
            cod = col_a.text_input("Código")
            nome_it = col_b.text_input("Nome do Material")
            cat_it = col_a.selectbox("Categoria", st.session_state.categorias)
            st.caption("ℹ️ Novos materiais iniciam com saldo 0. Dê entrada no menu de movimentações.")
            if st.form_submit_button("Finalizar Cadastro", type="primary"):
                if cod and nome_it:
                    if str(cod) in st.session_state.produtos["Código"].astype(str).values:
                        st.error("Código duplicado!")
                    else:
                        novo_p = {"Código": str(cod), "Item": nome_it, "Quantidade": 0, "Categoria": cat_it}
                        st.session_state.produtos = pd.concat([st.session_state.produtos, pd.DataFrame([novo_p])], ignore_index=True)
                        salvar_dados(ARQUIVO_PRODUTOS, st.session_state.produtos)
                        st.success("Produto cadastrado com sucesso!")
                        st.rerun()
                else:
                    st.error("Preencha todos os campos obrigatórios.")
                    
    with aba_gerenciar:
        if not st.session_state.produtos.empty:
            st.dataframe(st.session_state.produtos, use_container_width=True, hide_index=True)
            st.write("---")
            idx_p = st.selectbox("Selecione o produto que deseja modificar:", st.session_state.produtos.index, format_func=lambda x: f"{st.session_state.produtos.loc[x, 'Código']} - {st.session_state.produtos.loc[x, 'Item']}")
            col_ed1, col_ed2 = st.columns(2)
            edit_cod = col_ed1.text_input("Código do Produto:", value=st.session_state.produtos.loc[idx_p, "Código"])
            edit_item = col_ed2.text_input("Nome do Material:", value=st.session_state.produtos.loc[idx_p, "Item"])
            edit_qtd = col_ed1.number_input("Quantidade em Estoque:", min_value=0, step=1, value=int(st.session_state.produtos.loc[idx_p, "Quantidade"]))
            edit_cat = col_ed2.selectbox("Categoria do Produto:", st.session_state.categorias, index=st.session_state.categorias.index(st.session_state.produtos.loc[idx_p, "Categoria"]) if st.session_state.produtos.loc[idx_p, "Categoria"] in st.session_state.categorias else 0)
            
            c_btn1, c_btn2 = st.columns([1, 4])
            with c_btn1:
                if st.button("Salvar Alterações", type="primary"):
                    st.session_state.produtos.loc[idx_p, ["Código", "Item", "Quantidade", "Categoria"]] = [edit_cod, edit_item, edit_qtd, edit_cat]
                    salvar_dados(ARQUIVO_PRODUTOS, st.session_state.produtos)
                    st.success("Atualizado!")
                    st.rerun()
            with c_btn2:
                if st.button("❌ Excluir Produto Definitivamente"):
                    st.session_state.produtos = st.session_state.produtos.drop(idx_p).reset_index(drop=True)
                    salvar_dados(ARQUIVO_PRODUTOS, st.session_state.produtos)
                    st.warning("Produto excluído do sistema.")
                    st.rerun()

# TELA: CADASTRAR CATEGORIA (COM EXCLUSÃO ATIVA)
elif escolha == "🗂️ Cadastrar Categoria":
    st.title("🗂️ Gerenciamento de Categorias")
    aba_c1, aba_c2 = st.tabs(["➕ Nova Categoria", "✏️ Editar / Excluir Categorias"])
    
    with aba_c1:
        nova_cat = st.text_input("Nome da Nova Categoria:")
        if st.button("Adicionar Categoria", type="primary"):
            if nova_cat and nova_cat.strip() not in st.session_state.categorias:
                st.session_state.categorias.append(nova_cat.strip())
                pd.DataFrame(st.session_state.categorias, columns=['Categoria']).to_csv(ARQUIVO_CATEGORIAS, index=False, encoding='utf-8')
                st.success("Categoria Criada!")
                st.rerun()
                
    with aba_c2:
        if st.session_state.categorias:
            cat_idx = st.selectbox("Selecione qual deseja modificar:", range(len(st.session_state.categorias)), format_func=lambda x: st.session_state.categorias[x])
            edit_nome_cat = st.text_input("Editar Nome:", value=st.session_state.categorias[cat_idx])
            
            cb1, cb2 = st.columns([1, 4])
            with cb1:
                if st.button("Salvar Edição", type="primary"):
                    st.session_state.categorias[cat_idx] = edit_nome_cat.strip()
                    pd.DataFrame(st.session_state.categorias, columns=['Categoria']).to_csv(ARQUIVO_CATEGORIAS, index=False, encoding='utf-8')
                    st.success("Nome atualizado!")
                    st.rerun()
            with cb2:
                if st.button("❌ Remover Categoria"):
                    st.session_state.categorias.pop(cat_idx)
                    pd.DataFrame(st.session_state.categorias, columns=['Categoria']).to_csv(ARQUIVO_CATEGORIAS, index=False, encoding='utf-8')
                    st.warning("Categoria removida.")
                    st.rerun()

# TELA: CADASTRAR USUÁRIO (COM INPUT DE SENHA E EXCLUSÃO)
elif escolha == "👥 Cadastrar Usuário":
    st.title("👥 Gerenciamento de Usuários")
    aba_u1, aba_u2 = st.tabs(["➕ Novo Usuário", "✏️ Editar / Excluir Usuários"])
    
    with aba_u1:
        with st.form("form_novo_usuario", clear_on_submit=True):
            n = st.text_input("Nome Completo")
            e = st.text_input("E-mail corporativo")
            s_u = st.text_input("Definir Senha de Acesso", type="password", help="Senha padrão é 123 caso deixe vazia")
            p = st.selectbox("Perfil de Acesso", ["Administrador", "Usuário Comum"])
            if st.form_submit_button("Salvar Usuário", type="primary"):
                if n and e:
                    senha_final = str(s_u) if s_u else "123"
                    new_u = {"Nome": n, "E-mail": e.strip().lower(), "Senha": senha_final, "Perfil": p}
                    st.session_state.usuarios = pd.concat([st.session_state.usuarios, pd.DataFrame([new_u])], ignore_index=True)
                    salvar_dados(ARQUIVO_USUARIOS, st.session_state.usuarios)
                    st.success("Usuário criado com sucesso!")
                    st.rerun()
                else:
                    st.error("Nome e E-mail são obrigatórios.")
                    
    with aba_u2:
        if not st.session_state.usuarios.empty:
            st.dataframe(st.session_state.usuarios[["Nome", "E-mail", "Perfil"]], use_container_width=True, hide_index=True)
            st.write("---")
            idx = st.selectbox("Selecione o usuário para modificar:", st.session_state.usuarios.index, format_func=lambda x: st.session_state.usuarios.loc[x, "Nome"])
            edit_n = st.text_input("Nome:", value=st.session_state.usuarios.loc[idx, "Nome"])
            edit_e = st.text_input("E-mail:", value=st.session_state.usuarios.loc[idx, "E-mail"])
            edit_s = st.text_input("Alterar Senha:", value=st.session_state.usuarios.loc[idx, "Senha"], type="password")
            edit_p = st.selectbox("Perfil:", ["Administrador", "Usuário Comum"], index=0 if st.session_state.usuarios.loc[idx, "Perfil"] == "Administrador" else 1)
            
            cu1, cu2 = st.columns([1, 4])
            with cu1:
                if st.button("Atualizar Dados", type="primary"):
                    st.session_state.usuarios.loc[idx, ["Nome", "E-mail", "Senha", "Perfil"]] = [edit_n, edit_e.strip().lower(), edit_s, edit_p]
                    salvar_dados(ARQUIVO_USUARIOS, st.session_state.usuarios)
                    st.success("Usuário atualizado!")
                    st.rerun()
            with cu2:
                if st.button("❌ Remover Usuário do Sistema"):
                    st.session_state.usuarios = st.session_state.usuarios.drop(idx).reset_index(drop=True)
                    salvar_dados(ARQUIVO_USUARIOS, st.session_state.usuarios)
                    st.warning("Usuário removido.")
                    st.rerun()

# TELA: CADASTRAR COORDENAÇÃO (COM EXCLUSÃO ATIVA)
elif escolha == "🏢 Cadastrar Coordenação":
    st.title("🏢 Gerenciamento de Coordenações")
    aba_cc1, aba_cc2 = st.tabs(["➕ Nova Coordenação", "✏️ Editar / Excluir Coordenações"])
    
    with aba_cc1:
        with st.form("form_cad_coord", clear_on_submit=True):
            s = st.text_input("Sigla (Ex: COTEC)")
            nc = st.text_input("Nome da Coordenação")
            if st.form_submit_button("Cadastrar", type="primary"):
                if s and nc:
                    nova_coord = {"Sigla": s.upper().strip(), "Nome": nc.strip()}
                    st.session_state.coordenacoes = pd.concat([st.session_state.coordenacoes, pd.DataFrame([nova_coord])], ignore_index=True)
                    salvar_dados(ARQUIVO_COORD, st.session_state.coordenacoes)
                    st.success("Coordenação registrada!")
                    st.rerun()
                    
    with aba_cc2:
        if not st.session_state.coordenacoes.empty:
            st.dataframe(st.session_state.coordenacoes, use_container_width=True, hide_index=True)
            st.write("---")
            idx_c = st.selectbox("Selecione para modificar:", st.session_state.coordenacoes.index, format_func=lambda x: st.session_state.coordenacoes.loc[x, "Sigla"])
            edit_sigla = st.text_input("Sigla:", value=st.session_state.coordenacoes.loc[idx_c, "Sigla"])
            edit_nc = st.text_input("Nome da Coordenação:", value=st.session_state.coordenacoes.loc[idx_c, "Nome"])
            
            ccb1, ccb2 = st.columns([1, 4])
            with ccb1:
                if st.button("Salvar Edição", type="primary"):
                    st.session_state.coordenacoes.loc[idx_c, ["Sigla", "Nome"]] = [edit_sigla.upper().strip(), edit_nc.strip()]
                    salvar_dados(ARQUIVO_COORD, st.session_state.coordenacoes)
                    st.success("Alterações salvas!")
                    st.rerun()
            with ccb2:
                if st.button("❌ Excluir Coordenação"):
                    st.session_state.coordenacoes = st.session_state.coordenacoes.drop(idx_c).reset_index(drop=True)
                    salvar_dados(ARQUIVO_COORD, st.session_state.coordenacoes)
                    st.warning("Coordenação removida.")
                    st.rerun()

# TELA: MOVIMENTAÇÃO DE ENTRADA E SAÍDA
elif escolha == "🔄 Movimentação de Entrada e Saída":
    st.title("🔄 Movimentação de Entrada e Saída")
    aba_entrada, aba_saida, aba_historico = st.tabs(["📥 Registrar Entrada", "📤 Registrar Saída", "📋 Histórico de Entradas/Saídas"])
    
    with aba_entrada:
        with st.form("form_registrar_entrada", clear_on_submit=True):
            col_e1, col_e2 = st.columns(2)
            data_entrada = col_e1.date_input("Data da Entrada:", value=datetime.today(), format="DD/MM/YYYY")
            idx_prod_ent = col_e2.selectbox("Selecione o Material para Dar Entrada:", st.session_state.produtos.index, format_func=lambda x: f"{st.session_state.produtos.loc[x, 'Código']} - {st.session_state.produtos.loc[x, 'Item']} (Saldo: {st.session_state.produtos.loc[x, 'Quantidade']})")
            qtd_entrada = st.number_input("Quantidade que está Entrando:", min_value=1, step=1)
            
            if st.form_submit_button("Confirmar Entrada", type="primary"):
                st.session_state.produtos.loc[idx_prod_ent, "Quantidade"] += qtd_entrada
                nova_mov = {"Data": data_entrada.strftime("%d/%m/%Y"), "Tipo": "Entrada", "Código": st.session_state.produtos.loc[idx_prod_ent, "Código"], "Item": st.session_state.produtos.loc[idx_prod_ent, "Item"], "Quantidade": qtd_entrada, "Responsável pela Retirada": "Almoxarifado", "Coordenação": "-"}
                st.session_state.movimentacoes = pd.concat([st.session_state.movimentacoes, pd.DataFrame([nova_mov])], ignore_index=True)
                
                salvar_dados(ARQUIVO_PRODUTOS, st.session_state.produtos)
                salvar_dados(ARQUIVO_MOV, st.session_state.movimentacoes)
                st.success("Entrada registrada com sucesso!")
                st.rerun()

    with aba_saida:
        with st.form("form_registrar_saida", clear_on_submit=True):
            col_s1, col_s2 = st.columns(2)
            data_saida = col_s1.date_input("Data da Saída:", value=datetime.today(), format="DD/MM/YYYY")
            idx_prod_sai = col_s2.selectbox("Selecione o Material:", st.session_state.produtos.index, format_func=lambda x: f"{st.session_state.produtos.loc[x, 'Código']} - {st.session_state.produtos.loc[x, 'Item']} (Saldo: {st.session_state.produtos.loc[x, 'Quantidade']})")
            qtd_saida = col_s1.number_input("Quantidade de Saída:", min_value=1, step=1)
            lista_coord = st.session_state.coordenacoes["Sigla"].tolist() if not st.session_state.coordenacoes.empty else ["Sem Coordenações"]
            coord_retirada = col_s2.selectbox("Coordenação de Destino:", lista_coord)
            resp_retirada = st.text_input("Nome do Responsável pela Retirada:")
            
            if st.form_submit_button("Confirmar Saída", type="primary"):
                qtd_disponivel = st.session_state.produtos.loc[idx_prod_sai, "Quantidade"]
                if not resp_retirada.strip():
                    st.error("Insira o nome do responsável!")
                elif qtd_saida > qtd_disponivel:
                    st.error("Quantidade indisponível em estoque!")
                else:
                    st.session_state.produtos.loc[idx_prod_sai, "Quantidade"] -= qtd_saida
                    nova_mov = {"Data": data_saida.strftime("%d/%m/%Y"), "Tipo": "Saída", "Código": st.session_state.produtos.loc[idx_prod_sai, "Código"], "Item": st.session_state.produtos.loc[idx_prod_sai, "Item"], "Quantidade": qtd_saida, "Responsável pela Retirada": resp_retirada, "Coordenação": coord_retirada}
                    st.session_state.movimentacoes = pd.concat([st.session_state.movimentacoes, pd.DataFrame([nova_mov])], ignore_index=True)
                    
                    salvar_dados(ARQUIVO_PRODUTOS, st.session_state.produtos)
                    salvar_dados(ARQUIVO_MOV, st.session_state.movimentacoes)
                    st.success("Saída efetuada!")
                    st.rerun()

    with aba_historico:
        st.dataframe(st.session_state.movimentacoes, use_container_width=True, hide_index=True)

# TELA: PERFIL
elif escolha == "👤 Perfil":
    st.title("👤 Meu Perfil")
    st.write(f"**Usuário Atual:** {NOME_USUARIO_LOGADO}")
    st.write("**Lotação:** NGI Carajás / ICMBio")

# TELA: SAIR
elif escolha == "🚪 Sair":
    st.session_state.autenticado = False
    st.rerun()
