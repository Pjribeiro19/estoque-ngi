import os
from datetime import datetime
from flask import Flask, render_template_string, redirect, url_for, request, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chave-temporaria-trocar-depois')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

TIPOS_DIARIA = ['Cheia', 'Meia']
TIPOS_TRANSPORTE = ['Avião', 'Ônibus']

ESTADOS_BR = [
    'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS',
    'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC',
    'SP', 'SE', 'TO',
]

STATUS_LABELS = {
    'pendente_analise': 'Pendente de análise',
    'devolvida_ajuste': 'Devolvida para ajuste',
    'pendente_aprovacao': 'Pendente de aprovação',
    'aprovada': 'Aprovada',
    'em_execucao': 'Em execução',
}

TIPO_SOLICITACAO_LABELS = {
    'diaria': 'Diária',
    'passagem': 'Passagem',
    'compra_materiais': 'Compra de Materiais',
    'alimentacao': 'Alimentação',
    'locacao_veiculo': 'Locação de Veículo',
    'servico_externo': 'Serviços Externos',
}


def enviar_email(destinatario, assunto, corpo):
    import smtplib
    from email.mime.text import MIMEText

    host = os.environ.get('EMAIL_HOST')
    porta = os.environ.get('EMAIL_PORT')
    usuario_smtp = os.environ.get('EMAIL_USER')
    senha_smtp = os.environ.get('EMAIL_PASSWORD')
    remetente = os.environ.get('EMAIL_FROM', usuario_smtp)

    if not host or not usuario_smtp or not senha_smtp:
        return False

    try:
        mensagem = MIMEText(corpo)
        mensagem['Subject'] = assunto
        mensagem['From'] = remetente
        mensagem['To'] = destinatario

        with smtplib.SMTP(host, int(porta or 587)) as servidor:
            servidor.starttls()
            servidor.login(usuario_smtp, senha_smtp)
            servidor.sendmail(remetente, [destinatario], mensagem.as_string())
        return True
    except Exception:
        return False


AREAS_PADRAO = {
    'Capital': {'Cheia': 350, 'Meia': 175},
    'Cidade Locais': {'Cheia': 300, 'Meia': 150},
    'Interior': {'Cheia': 260, 'Meia': 130},
    'Brasília': {'Cheia': 500, 'Meia': 500},
    'São Paulo': {'Cheia': 500, 'Meia': 500},
    'Rio de Janeiro': {'Cheia': 500, 'Meia': 500},
}

CHAVE_VALOR_AUXILIO = 'valor_auxilio_deslocamento'
VALOR_AUXILIO_PADRAO = 95


# ---------------- MODELOS ----------------
PERFIS_USUARIO = ['solicitante', 'analista', 'aprovador', 'comprador']


class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    senha_hash = db.Column(db.String(300), nullable=False)
    is_organizador = db.Column(db.Boolean, default=False)
    is_aprovador = db.Column(db.Boolean, default=False)
    perfil = db.Column(db.String(20), default='solicitante')

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)


class Coordenacao(db.Model):
    __tablename__ = 'coordenacoes'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True, nullable=False)


class Solicitacao(db.Model):
    __tablename__ = 'solicitacoes'
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False)
    solicitante_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    data_envio = db.Column(db.DateTime, default=datetime.utcnow)
    ponto_focal = db.Column(db.String(200))
    atividade_projeto = db.Column(db.String(300))
    status = db.Column(db.String(30), default='pendente_analise')
    convenio = db.Column(db.String(200))
    observacao = db.Column(db.Text)
    valor_total = db.Column(db.Numeric(12, 2), default=0)
    coordenacao_solicitante_id = db.Column(db.Integer, db.ForeignKey('coordenacoes.id'))
    contato_solicitante = db.Column(db.String(200))
    motivo_devolucao = db.Column(db.Text)
    data_previsao_execucao = db.Column(db.Date)

    solicitante = db.relationship('Usuario')
    coordenacao_solicitante = db.relationship('Coordenacao')


class AreaDiaria(db.Model):
    __tablename__ = 'areas_diaria'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), unique=True, nullable=False)


class ValorDiaria(db.Model):
    __tablename__ = 'valores_diaria'
    id = db.Column(db.Integer, primary_key=True)
    area_id = db.Column(db.Integer, db.ForeignKey('areas_diaria.id'), nullable=False)
    tipo_diaria = db.Column(db.String(10), nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)

    area = db.relationship('AreaDiaria', backref=db.backref('valores', cascade='all, delete-orphan'))

    __table_args__ = (db.UniqueConstraint('area_id', 'tipo_diaria'),)


class SolicitacaoDiaria(db.Model):
    __tablename__ = 'solicitacao_diarias'
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)

    nome_diarista = db.Column(db.String(200), nullable=False)
    data_ida = db.Column(db.Date, nullable=False)
    data_retorno = db.Column(db.Date, nullable=False)
    cidade_origem = db.Column(db.String(150))
    estado_origem = db.Column(db.String(2))
    cidade_destino = db.Column(db.String(150))
    estado_destino = db.Column(db.String(2))
    tipo_destino = db.Column(db.String(80))
    tipo_diaria = db.Column(db.String(10))
    numero_pernoites = db.Column(db.Integer, default=0)
    valor_diaria = db.Column(db.Numeric(10, 2), default=0)

    tera_auxilio_deslocamento = db.Column(db.Boolean, default=False)
    quantidade_auxilio = db.Column(db.Integer, default=0)
    valor_auxilio = db.Column(db.Numeric(10, 2), default=0)
    justificativa_auxilio = db.Column(db.Text)

    justificativa = db.Column(db.Text)

    cpf_diarista = db.Column(db.String(14))
    telefone_diarista = db.Column(db.String(20))
    email_diarista = db.Column(db.String(200))
    banco_diarista = db.Column(db.String(100))
    agencia_diarista = db.Column(db.String(20))
    conta_diarista = db.Column(db.String(30))
    chave_pix = db.Column(db.String(150))

    solicitacao = db.relationship('Solicitacao', backref='diaria')


class SolicitacaoPassagem(db.Model):
    __tablename__ = 'solicitacao_passagens'
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)

    nome_passageiro = db.Column(db.String(200), nullable=False)
    tipo_transporte = db.Column(db.String(10))
    cidade_origem = db.Column(db.String(150))
    estado_origem = db.Column(db.String(2))
    cidade_destino = db.Column(db.String(150))
    estado_destino = db.Column(db.String(2))
    data_ida = db.Column(db.Date, nullable=False)
    data_volta = db.Column(db.Date)
    com_bagagem = db.Column(db.Boolean, default=False)
    valor_estimado = db.Column(db.Numeric(10, 2), default=0)
    justificativa = db.Column(db.Text)

    cpf_passageiro = db.Column(db.String(14))
    rg_orgao_uf_passageiro = db.Column(db.String(100))
    data_nascimento_passageiro = db.Column(db.Date)
    telefone_passageiro = db.Column(db.String(20))
    email_passageiro = db.Column(db.String(200))

    solicitacao = db.relationship('Solicitacao', backref='passagem')


class SolicitacaoCompraMateriais(db.Model):
    __tablename__ = 'solicitacao_compras_materiais'
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)

    data_entrega_material = db.Column(db.Date, nullable=False)

    nome_especificacao = db.Column(db.String(300), nullable=False)
    fornecedor_sugerido = db.Column(db.String(200))
    forma_aquisicao = db.Column(db.String(10), nullable=False)
    link_produto = db.Column(db.String(500))
    quantidade = db.Column(db.Numeric(10, 2), nullable=False)
    valor_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    valor_total_item = db.Column(db.Numeric(10, 2), nullable=False)
    justificativa = db.Column(db.Text, nullable=False)

    status_compra = db.Column(db.String(50), default='Pendente')

    solicitacao = db.relationship('Solicitacao', backref='compra_materiais')


class TipoAlimentacao(db.Model):
    __tablename__ = 'tipos_alimentacao'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), unique=True, nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)


class SolicitacaoAlimentacao(db.Model):
    __tablename__ = 'solicitacao_alimentacoes'
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)

    tipo_alimentacao = db.Column(db.String(80), nullable=False)
    quantidade_pessoas = db.Column(db.Integer, nullable=False)
    forma_entrega = db.Column(db.String(20), nullable=False)
    local_entrega = db.Column(db.String(300))
    data_entrega = db.Column(db.Date, nullable=False)
    horario_entrega = db.Column(db.Time, nullable=False)
    custo_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    custo_total = db.Column(db.Numeric(10, 2), nullable=False)
    justificativa = db.Column(db.Text, nullable=False)

    solicitacao = db.relationship('Solicitacao', backref='alimentacao')


class TipoVeiculo(db.Model):
    __tablename__ = 'tipos_veiculo'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), unique=True, nullable=False)
    valor_km = db.Column(db.Numeric(10, 2), nullable=False)
    quantidade_assentos = db.Column(db.Integer, default=0)


class SolicitacaoLocacaoVeiculo(db.Model):
    __tablename__ = 'solicitacao_locacao_veiculos'
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)

    tipo_veiculo = db.Column(db.String(80), nullable=False)
    especificacoes = db.Column(db.String(300))
    local_origem = db.Column(db.String(300), nullable=False)
    percurso = db.Column(db.String(500), nullable=False)
    local_retorno = db.Column(db.String(300), nullable=False)
    data_hora_partida = db.Column(db.DateTime, nullable=False)
    data_hora_chegada = db.Column(db.DateTime, nullable=False)
    km_estimado = db.Column(db.Numeric(10, 2), nullable=False)
    custo_km = db.Column(db.Numeric(10, 2), nullable=False)
    custo_estimado = db.Column(db.Numeric(10, 2), nullable=False)
    justificativa = db.Column(db.Text, nullable=False)
    observacao = db.Column(db.Text)

    solicitacao = db.relationship('Solicitacao', backref='locacao_veiculo')


class TipoServicoExterno(db.Model):
    __tablename__ = 'tipos_servico_externo'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), unique=True, nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)


class PrestadorServico(db.Model):
    __tablename__ = 'prestadores_servico'
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)

    tipo_prestador = db.Column(db.String(2), nullable=False)
    categoria_servico = db.Column(db.String(120), nullable=False)
    nome_servico = db.Column(db.String(300), nullable=False)
    fornecedor_sugerido = db.Column(db.String(200))
    especificacao = db.Column(db.Text, nullable=False)
    justificativa = db.Column(db.Text, nullable=False)
    valor_servico = db.Column(db.Numeric(10, 2), nullable=False)

    nome_empresa = db.Column(db.String(200))
    cnpj = db.Column(db.String(20))

    nome_prestador = db.Column(db.String(200))
    cpf_prestador = db.Column(db.String(14))
    rg_prestador = db.Column(db.String(100))
    telefone_prestador = db.Column(db.String(20))
    pis_nis = db.Column(db.String(20))
    endereco_prestador = db.Column(db.String(400))

    banco = db.Column(db.String(100))
    agencia = db.Column(db.String(20))
    conta = db.Column(db.String(30))
    chave_pix = db.Column(db.String(150))

    solicitacao = db.relationship('Solicitacao', backref='prestadores')


class Anexo(db.Model):
    __tablename__ = 'anexos'
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)
    nome_arquivo = db.Column(db.String(300), nullable=False)
    tipo_conteudo = db.Column(db.String(100))
    dados = db.Column(db.LargeBinary, nullable=False)
    data_upload = db.Column(db.DateTime, default=datetime.utcnow)

    solicitacao = db.relationship('Solicitacao', backref='anexos')


class Configuracao(db.Model):
    __tablename__ = 'configuracoes'
    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(100), unique=True, nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)


@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))


def obter_valor_diaria(tipo_diaria, nome_area):
    area = AreaDiaria.query.filter_by(nome=nome_area).first()
    if not area:
        return 0
    registro = ValorDiaria.query.filter_by(area_id=area.id, tipo_diaria=tipo_diaria).first()
    return float(registro.valor) if registro else 0


def obter_configuracao(chave, padrao=0):
    registro = Configuracao.query.filter_by(chave=chave).first()
    return float(registro.valor) if registro else padrao


def somente_organizador():
    if not current_user.is_organizador:
        abort(403)


def montar_opcoes(lista, selecionado=None):
    html = ''
    for opcao in lista:
        sel = 'selected' if opcao == selecionado else ''
        html += f'<option value="{opcao}" {sel}>{opcao}</option>'
    return html


def montar_opcoes_areas(selecionado=None):
    areas = AreaDiaria.query.order_by(AreaDiaria.nome).all()
    html = ''
    for area in areas:
        sel = 'selected' if area.nome == selecionado else ''
        html += f'<option value="{area.nome}" {sel}>{area.nome}</option>'
    return html


def montar_opcoes_estados(selecionado=None):
    html = ''
    for uf in ESTADOS_BR:
        sel = 'selected' if uf == selecionado else ''
        html += f'<option value="{uf}" {sel}>{uf}</option>'
    return html


def montar_opcoes_coordenacoes(selecionado=None):
    coordenacoes = Coordenacao.query.order_by(Coordenacao.nome).all()
    html = ''
    for coord in coordenacoes:
        sel = 'selected' if str(coord.id) == str(selecionado) else ''
        html += f'<option value="{coord.id}" {sel}>{coord.nome}</option>'
    return html


def montar_opcoes_tipos_alimentacao(selecionado=None):
    tipos = TipoAlimentacao.query.order_by(TipoAlimentacao.nome).all()
    html = ''
    for tipo in tipos:
        sel = 'selected' if tipo.nome == selecionado else ''
        html += f'<option value="{tipo.nome}" {sel}>{tipo.nome}</option>'
    return html


def montar_dict_valores_alimentacao():
    tipos = TipoAlimentacao.query.all()
    partes = []
    for tipo in tipos:
        partes.append("'" + tipo.nome.replace("'", "\\'") + "': " + str(float(tipo.valor)))
    return '{' + ', '.join(partes) + '}'


def montar_opcoes_tipos_veiculo(selecionado=None):
    tipos = TipoVeiculo.query.order_by(TipoVeiculo.nome).all()
    html = ''
    for tipo in tipos:
        sel = 'selected' if tipo.nome == selecionado else ''
        html += f'<option value="{tipo.nome}" {sel}>{tipo.nome}</option>'
    return html


def montar_dict_valores_veiculo():
    tipos = TipoVeiculo.query.all()
    partes = []
    for tipo in tipos:
        partes.append("'" + tipo.nome.replace("'", "\\'") + "': " + str(float(tipo.valor_km)))
    return '{' + ', '.join(partes) + '}'


def montar_dict_assentos_veiculo():
    tipos = TipoVeiculo.query.all()
    partes = []
    for tipo in tipos:
        partes.append("'" + tipo.nome.replace("'", "\\'") + "': " + str(int(tipo.quantidade_assentos or 0)))
    return '{' + ', '.join(partes) + '}'


def montar_opcoes_tipos_servico(selecionado=None):
    tipos = TipoServicoExterno.query.order_by(TipoServicoExterno.nome).all()
    html = ''
    for tipo in tipos:
        sel = 'selected' if tipo.nome == selecionado else ''
        html += f'<option value="{tipo.nome}" {sel}>{tipo.nome}</option>'
    return html


def montar_dict_valores_servico():
    tipos = TipoServicoExterno.query.all()
    partes = []
    for tipo in tipos:
        partes.append("'" + tipo.nome.replace("'", "\\'") + "': " + str(float(tipo.valor)))
    return '{' + ', '.join(partes) + '}'


# ---------------- LAYOUT BASE ----------------
BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <title>SIGAD Carajás</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: Arial, sans-serif; margin: 0; display: flex; min-height: 100vh; }
        nav { width: 230px; background: #0f2a2e; flex-shrink: 0; padding: 8px 0; color: white; }
        nav .logo { padding: 12px 16px; font-size: 14px; font-weight: bold; border-bottom: 1px solid rgba(255,255,255,0.1); margin-bottom: 4px; }
        nav .item { padding: 10px 16px; display: block; color: rgba(255,255,255,0.85); text-decoration: none; font-size: 13px; cursor: pointer; }
        nav .item:hover { background: rgba(255,255,255,0.08); }
        nav .submenu { padding-left: 20px; display: flex; flex-direction: column; }
        nav .submenu a { padding: 6px 16px; color: rgba(255,255,255,0.75); text-decoration: none; font-size: 12px; }
        nav .submenu a:hover { background: rgba(255,255,255,0.08); }
        main { flex: 1; }
        header { background: #2b5876; color: white; padding: 15px 25px; display: flex; justify-content: space-between; align-items: center; }
        header h1 { font-size: 18px; margin: 0; }
        .conteudo { padding: 30px; }
        label { font-size: 13px; font-weight: bold; }
        input, select, textarea { border: 1px solid #ccc; border-radius: 4px; }
        table { border-collapse: collapse; width: 100%; max-width: 700px; }
        th, td { border: 1px solid #ddd; padding: 8px; font-size: 13px; text-align: left; }
        th { background: #f0f0f0; }
        .flash { background: #ffe0e0; color: #a00; padding: 8px 12px; border-radius: 4px; margin-bottom: 15px; font-size: 13px; }
        .flash-ok { background: #e0ffe6; color: #060; }
        .bloco { border: 1px solid #ddd; border-radius: 6px; padding: 15px; margin-bottom: 15px; background: #fafafa; }
        .btn { padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; }
        .btn-salvar { background: #2b5876; color: white; }
        .btn-excluir { background: #c0392b; color: white; }
        .btn-adicionar { background: #2e7d32; color: white; padding: 10px 20px; }
        .btn-atalho { background: #eef3f7; color: #2b5876; border: 1px solid #cdd9e2; padding: 6px 10px; border-radius: 4px; font-size: 12px; cursor: pointer; margin-right: 6px; margin-bottom: 6px; display: inline-block; text-decoration: none; }
        .btn-atalho:hover { background: #dde8f0; }
    </style>
</head>
<body>
    <nav>
        <div class="logo">SIGAD Carajás</div>
        <a class="item" href="{{ url_for('inicio') }}">Tela Inicial</a>
        <a class="item" href="{{ url_for('minhas_solicitacoes') }}">Minhas Solicitações</a>
        {% if current_user.perfil == 'analista' or current_user.is_organizador %}
        <a class="item" href="{{ url_for('fila_analise') }}">Fila de Análise</a>
        {% endif %}
        {% if current_user.perfil == 'aprovador' or current_user.is_organizador %}
        <a class="item" href="{{ url_for('fila_aprovacao') }}">Fila de Aprovação</a>
        {% endif %}
        {% if current_user.perfil == 'comprador' or current_user.is_organizador %}
        <a class="item" href="{{ url_for('fila_execucao') }}">Fila de Execução</a>
        {% endif %}
        <div class="item">Solicitação</div>
        <div class="submenu">
            <a href="{{ url_for('diaria_form') }}">Diária</a>
            <a href="{{ url_for('passagem_form') }}">Passagem</a>
            <a href="{{ url_for('compra_materiais_form') }}">Compras de Materiais</a>
            <a href="#">Compras</a>
            <a href="#">Rancho</a>
            <a href="{{ url_for('alimentacao_form') }}">Alimentação</a>
            <a href="{{ url_for('locacao_veiculo_form') }}">Locação de Veículos</a>
            <a href="{{ url_for('servico_externo_form') }}">Serviços Externos</a>
            <a href="#">Seguro</a>
            <a href="#">Auditório</a>
            <a href="#">Kit Institucional</a>
            <a href="#">Bolsa</a>
        </div>
        {% if current_user.is_organizador %}
        <div class="item">Cadastros</div>
        <div class="submenu">
            <a href="{{ url_for('cadastro_diaria') }}">Diária</a>
            <a href="{{ url_for('cadastro_coordenacao') }}">Coordenação</a>
            <a href="{{ url_for('cadastro_alimentacao') }}">Alimentação</a>
            <a href="{{ url_for('cadastro_locacao_veiculo') }}">Locação de Veículos</a>
            <a href="{{ url_for('cadastro_servico_externo') }}">Serviços Externos</a>
            <a href="{{ url_for('cadastro_usuarios') }}">Usuários</a>
        </div>
        {% endif %}
        <a class="item" href="#">Ajuda</a>
    </nav>
    <main>
        <header>
            <h1>{{ titulo }}</h1>
            <div>Olá, {{ current_user.nome }} | <a href="{{ url_for('logout') }}" style="color: white;">Sair</a></div>
        </header>
        <div class="conteudo">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% for categoria, mensagem in messages %}
                    <div class="flash {{ 'flash-ok' if categoria == 'sucesso' else '' }}">{{ mensagem }}</div>
                {% endfor %}
            {% endwith %}
            {{ conteudo_html | safe }}
        </div>
    </main>
</body>
</html>
"""


def render_pagina(titulo, conteudo_html):
    return render_template_string(BASE_TEMPLATE, titulo=titulo, conteudo_html=conteudo_html)


# ---------------- LOGIN ----------------
LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <title>SIGAD Carajás - Login</title>
    <style>
        body { font-family: Arial, sans-serif; background: #f0f0f0; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .login-box { background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); width: 300px; }
        .login-box h1 { color: #2b5876; font-size: 20px; text-align: center; margin-bottom: 20px; }
        .login-box input { width: 100%; padding: 10px; margin-bottom: 12px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        .login-box button { width: 100%; padding: 10px; background: #2b5876; color: white; border: none; border-radius: 4px; cursor: pointer; }
        .login-box button:hover { background: #1e4258; }
        .flash { color: red; font-size: 13px; text-align: center; margin-bottom: 10px; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>SIGAD Carajás</h1>
        {% with messages = get_flashed_messages() %}
            {% for mensagem in messages %}
                <div class="flash">{{ mensagem }}</div>
            {% endfor %}
        {% endwith %}
        <form method="POST">
            <input type="email" name="email" placeholder="E-mail" required>
            <input type="password" name="senha" placeholder="Senha" required>
            <button type="submit">Entrar</button>
        </form>
    </div>
</body>
</html>
"""


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        senha = request.form.get('senha')
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario and usuario.check_senha(senha):
            login_user(usuario)
            return redirect(url_for('inicio'))
        flash('E-mail ou senha inválidos.')
    return render_template_string(LOGIN_TEMPLATE)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ---------------- TELA INICIAL ----------------
@app.route('/')
@login_required
def inicio():
    conteudo = """
    <h2>Pendências</h2>
    <p>Nenhuma pendência no momento.</p>
    """
    return render_pagina('Tela inicial', conteudo)


# ---------------- MINHAS SOLICITAÇÕES ----------------
@app.route('/minhas-solicitacoes')
@login_required
def minhas_solicitacoes():
    solicitacoes = Solicitacao.query.filter_by(solicitante_id=current_user.id).order_by(Solicitacao.data_envio.desc()).all()

    linhas_html = ''
    for s in solicitacoes:
        tipo_label = TIPO_SOLICITACAO_LABELS.get(s.tipo, s.tipo)
        status_label = STATUS_LABELS.get(s.status, s.status)
        motivo = f'<br><span style="color:#a00; font-size:11px;">Motivo: {s.motivo_devolucao}</span>' if s.status == 'devolvida_ajuste' and s.motivo_devolucao else ''
        previsao = f'<br><span style="font-size:11px; color:#555;">Previsão: {s.data_previsao_execucao.strftime("%d/%m/%Y")}</span>' if s.data_previsao_execucao else ''
        linhas_html += f"""
        <tr>
            <td>{s.data_envio.strftime('%d/%m/%Y %H:%M')}</td>
            <td>{tipo_label}</td>
            <td>R$ {float(s.valor_total or 0):.2f}</td>
            <td>{status_label}{motivo}{previsao}</td>
        </tr>
        """

    if not linhas_html:
        linhas_html = '<tr><td colspan="4">Você ainda não fez nenhuma solicitação.</td></tr>'

    conteudo = f"""
    <h2>Minhas Solicitações</h2>
    <table>
        <tr><th>Data</th><th>Tipo</th><th>Valor</th><th>Status</th></tr>
        {linhas_html}
    </table>
    """
    return render_pagina('Minhas Solicitações', conteudo)


# ---------------- FILA DO ANALISTA ----------------
@app.route('/analise')
@login_required
def fila_analise():
    if current_user.perfil not in ('analista',) and not current_user.is_organizador:
        abort(403)

    solicitacoes = Solicitacao.query.filter_by(status='pendente_analise').order_by(Solicitacao.data_envio).all()

    linhas_html = ''
    for s in solicitacoes:
        tipo_label = TIPO_SOLICITACAO_LABELS.get(s.tipo, s.tipo)
        linhas_html += f"""
        <tr>
            <td>{s.data_envio.strftime('%d/%m/%Y %H:%M')}</td>
            <td>{tipo_label}</td>
            <td>{s.solicitante.nome}</td>
            <td>R$ {float(s.valor_total or 0):.2f}</td>
            <td>
                <form method="POST" action="{url_for('analise_aprovar_triagem', solicitacao_id=s.id)}" style="display:inline;">
                    <button type="submit" class="btn btn-salvar">Enviar para Aprovador</button>
                </form>
                <form method="POST" action="{url_for('analise_devolver', solicitacao_id=s.id)}" style="display:inline;" onsubmit="return preencherMotivo(this);">
                    <input type="hidden" name="motivo" class="campo-motivo">
                    <button type="button" class="btn btn-excluir" onclick="pedirMotivo(this)">Devolver</button>
                </form>
            </td>
        </tr>
        """

    if not linhas_html:
        linhas_html = '<tr><td colspan="5">Nenhuma solicitação pendente de análise.</td></tr>'

    conteudo = f"""
    <h2>Fila de Análise</h2>
    <table>
        <tr><th>Data</th><th>Tipo</th><th>Solicitante</th><th>Valor</th><th>Ações</th></tr>
        {linhas_html}
    </table>
    <script>
    function pedirMotivo(botao) {{
        var motivo = prompt('Explique o ajuste necessário para o solicitante:');
        if (motivo === null || motivo.trim() === '') {{
            return;
        }}
        var form = botao.closest('form');
        form.querySelector('.campo-motivo').value = motivo;
        form.submit();
    }}
    </script>
    """
    return render_pagina('Fila de Análise', conteudo)


@app.route('/analise/<int:solicitacao_id>/aprovar-triagem', methods=['POST'])
@login_required
def analise_aprovar_triagem(solicitacao_id):
    if current_user.perfil not in ('analista',) and not current_user.is_organizador:
        abort(403)
    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)
    solicitacao.status = 'pendente_aprovacao'
    db.session.commit()
    flash('Solicitação enviada para aprovação.', 'sucesso')
    return redirect(url_for('fila_analise'))


@app.route('/analise/<int:solicitacao_id>/devolver', methods=['POST'])
@login_required
def analise_devolver(solicitacao_id):
    if current_user.perfil not in ('analista',) and not current_user.is_organizador:
        abort(403)
    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)
    solicitacao.status = 'devolvida_ajuste'
    solicitacao.motivo_devolucao = request.form.get('motivo')
    db.session.commit()

    enviar_email(
        solicitacao.solicitante.email,
        'Sua solicitação precisa de ajustes - SIGAD Carajás',
        f'Sua solicitação foi devolvida para ajustes.\n\nMotivo: {solicitacao.motivo_devolucao}\n\nAcesse o sistema para mais detalhes.',
    )

    flash('Solicitação devolvida ao solicitante.', 'sucesso')
    return redirect(url_for('fila_analise'))


# ---------------- FILA DO APROVADOR ----------------
@app.route('/aprovacao')
@login_required
def fila_aprovacao():
    if current_user.perfil not in ('aprovador',) and not current_user.is_organizador:
        abort(403)

    solicitacoes = Solicitacao.query.filter_by(status='pendente_aprovacao').order_by(Solicitacao.data_envio).all()

    linhas_html = ''
    for s in solicitacoes:
        tipo_label = TIPO_SOLICITACAO_LABELS.get(s.tipo, s.tipo)
        linhas_html += f"""
        <tr>
            <td>{s.data_envio.strftime('%d/%m/%Y %H:%M')}</td>
            <td>{tipo_label}</td>
            <td>{s.solicitante.nome}</td>
            <td>R$ {float(s.valor_total or 0):.2f}</td>
            <td>
                <form method="POST" action="{url_for('aprovacao_aprovar', solicitacao_id=s.id)}">
                    <button type="submit" class="btn btn-salvar">Aprovar</button>
                </form>
            </td>
        </tr>
        """

    if not linhas_html:
        linhas_html = '<tr><td colspan="5">Nenhuma solicitação pendente de aprovação.</td></tr>'

    conteudo = f"""
    <h2>Fila de Aprovação</h2>
    <table>
        <tr><th>Data</th><th>Tipo</th><th>Solicitante</th><th>Valor</th><th>Ações</th></tr>
        {linhas_html}
    </table>
    """
    return render_pagina('Fila de Aprovação', conteudo)


@app.route('/aprovacao/<int:solicitacao_id>/aprovar', methods=['POST'])
@login_required
def aprovacao_aprovar(solicitacao_id):
    if current_user.perfil not in ('aprovador',) and not current_user.is_organizador:
        abort(403)
    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)
    solicitacao.status = 'aprovada'
    db.session.commit()

    tipo_label = TIPO_SOLICITACAO_LABELS.get(solicitacao.tipo, solicitacao.tipo)

    enviar_email(
        solicitacao.solicitante.email,
        'Sua solicitação foi aprovada - SIGAD Carajás',
        f'Sua solicitação de {tipo_label} foi aprovada e seguiu para execução.',
    )

    compradores = Usuario.query.filter_by(perfil='comprador').all()
    for comprador in compradores:
        enviar_email(
            comprador.email,
            'Nova solicitação aprovada para execução - SIGAD Carajás',
            f'Uma solicitação de {tipo_label} foi aprovada e está aguardando execução.',
        )

    flash('Solicitação aprovada.', 'sucesso')
    return redirect(url_for('fila_aprovacao'))


# ---------------- FILA DO COMPRADOR/EXECUTOR ----------------
@app.route('/execucao')
@login_required
def fila_execucao():
    if current_user.perfil not in ('comprador',) and not current_user.is_organizador:
        abort(403)

    solicitacoes = Solicitacao.query.filter_by(status='aprovada').order_by(Solicitacao.data_envio).all()

    linhas_html = ''
    for s in solicitacoes:
        tipo_label = TIPO_SOLICITACAO_LABELS.get(s.tipo, s.tipo)
        linhas_html += f"""
        <tr>
            <td>{s.data_envio.strftime('%d/%m/%Y %H:%M')}</td>
            <td>{tipo_label}</td>
            <td>{s.solicitante.nome}</td>
            <td>R$ {float(s.valor_total or 0):.2f}</td>
            <td>
                <form method="POST" action="{url_for('execucao_definir_previsao', solicitacao_id=s.id)}" style="display:flex; gap:6px; align-items:center;">
                    <input type="date" name="data_previsao" required style="padding:4px;">
                    <button type="submit" class="btn btn-salvar">Confirmar</button>
                </form>
            </td>
        </tr>
        """

    if not linhas_html:
        linhas_html = '<tr><td colspan="5">Nenhuma solicitação aprovada aguardando execução.</td></tr>'

    conteudo = f"""
    <h2>Fila de Execução</h2>
    <table>
        <tr><th>Data</th><th>Tipo</th><th>Solicitante</th><th>Valor</th><th>Definir previsão</th></tr>
        {linhas_html}
    </table>
    """
    return render_pagina('Fila de Execução', conteudo)


@app.route('/execucao/<int:solicitacao_id>/definir-previsao', methods=['POST'])
@login_required
def execucao_definir_previsao(solicitacao_id):
    if current_user.perfil not in ('comprador',) and not current_user.is_organizador:
        abort(403)
    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)
    solicitacao.data_previsao_execucao = request.form.get('data_previsao')
    solicitacao.status = 'em_execucao'
    db.session.commit()

    tipo_label = TIPO_SOLICITACAO_LABELS.get(solicitacao.tipo, solicitacao.tipo)

    enviar_email(
        solicitacao.solicitante.email,
        'Sua solicitação está em execução - SIGAD Carajás',
        f'Sua solicitação de {tipo_label} está em execução, com previsão para {solicitacao.data_previsao_execucao}.',
    )

    flash('Previsão definida e solicitante notificado.', 'sucesso')
    return redirect(url_for('fila_execucao'))


# ---------------- CADASTRO DE USUÁRIOS (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/usuarios')
@login_required
def cadastro_usuarios():
    somente_organizador()

    usuarios = Usuario.query.order_by(Usuario.nome).all()
    linhas_html = ''
    for u in usuarios:
        opcoes_perfil = ''
        for p in PERFIS_USUARIO:
            sel = 'selected' if u.perfil == p else ''
            opcoes_perfil += f'<option value="{p}" {sel}>{p.capitalize()}</option>'

        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_usuarios_atualizar', usuario_id=u.id)}" style="display:contents;">
            <td>{u.nome}</td>
            <td>{u.email}</td>
            <td><select name="perfil" style="padding:4px;">{opcoes_perfil}</select></td>
            <td><input type="checkbox" name="is_organizador" {'checked' if u.is_organizador else ''}> Admin</td>
            <td><button type="submit" class="btn btn-salvar">Salvar</button></td>
            </form>
        </tr>
        """

    conteudo = f"""
    <h2>Usuários</h2>
    <table>
        <tr><th>Nome</th><th>E-mail</th><th>Perfil</th><th>Admin</th><th>Ações</th></tr>
        {linhas_html}
    </table>

    <h3 style="margin-top:25px;">Adicionar novo usuário</h3>
    <form method="POST" action="{url_for('cadastro_usuarios_adicionar')}" style="max-width:400px;">
        <label>Nome:</label><br>
        <input type="text" name="nome" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <label>E-mail:</label><br>
        <input type="email" name="email" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <label>Senha inicial:</label><br>
        <input type="text" name="senha" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <label>Perfil:</label><br>
        <select name="perfil" style="padding:6px; width:100%; margin-bottom:10px;">
            <option value="solicitante">Solicitante</option>
            <option value="analista">Analista</option>
            <option value="aprovador">Aprovador</option>
            <option value="comprador">Comprador/Executor</option>
        </select><br>

        <button type="submit" class="btn btn-adicionar">Adicionar usuário</button>
    </form>
    """
    return render_pagina('Cadastro de Usuários', conteudo)


@app.route('/cadastros/usuarios/adicionar', methods=['POST'])
@login_required
def cadastro_usuarios_adicionar():
    somente_organizador()
    nome = request.form.get('nome', '').strip()
    email = request.form.get('email', '').strip()
    senha = request.form.get('senha')
    perfil = request.form.get('perfil', 'solicitante')

    if Usuario.query.filter_by(email=email).first():
        flash('Já existe um usuário com esse e-mail.')
        return redirect(url_for('cadastro_usuarios'))

    novo_usuario = Usuario(nome=nome, email=email, perfil=perfil)
    novo_usuario.set_senha(senha)
    db.session.add(novo_usuario)
    db.session.commit()
    flash(f'Usuário "{nome}" cadastrado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_usuarios'))


@app.route('/cadastros/usuarios/<int:usuario_id>/atualizar', methods=['POST'])
@login_required
def cadastro_usuarios_atualizar(usuario_id):
    somente_organizador()
    usuario = Usuario.query.get_or_404(usuario_id)
    usuario.perfil = request.form.get('perfil')
    usuario.is_organizador = request.form.get('is_organizador') == 'on'
    db.session.commit()
    flash('Usuário atualizado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_usuarios'))


# ---------------- API: valor da diária ----------------
@app.route('/api/valor-diaria')
@login_required
def api_valor_diaria():
    tipo_diaria = request.args.get('tipo_diaria')
    nome_area = request.args.get('tipo_destino')
    valor = obter_valor_diaria(tipo_diaria, nome_area)
    return jsonify({'valor': valor})


# ---------------- SOLICITAÇÃO: DIÁRIA ----------------
DIARIA_FORM_TEMPLATE = """
<form method="POST" enctype="multipart/form-data" style="max-width: 600px;" id="form-diaria">
    <h3>Dados gerais</h3>
    <label>Ponto Focal:</label><br>
    <input type="text" name="ponto_focal" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Atividade/Projeto relacionado:</label><br>
    <input type="text" name="atividade_projeto" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Coordenação Solicitante: <span style="color:red;">*</span></label><br>
    <select name="coordenacao_solicitante" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        __OPCOES_COORDENACAO__
    </select><br>

    <label>Contato (telefone ou e-mail): <span style="color:red;">*</span></label><br>
    <input type="text" name="contato_solicitante" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <h3>Dados da diária</h3>
    <label>Nome do diarista: <span style="color:red;">*</span></label><br>
    <input type="text" name="nome_diarista" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Data de ida: <span style="color:red;">*</span></label><br>
    <input type="date" name="data_ida" id="data_ida" required style="padding:6px; margin-bottom:10px;"><br>

    <label>Data de retorno: <span style="color:red;">*</span></label><br>
    <input type="date" name="data_retorno" id="data_retorno" required style="padding:6px; margin-bottom:10px;"><br>

    <label>Local de origem: <span style="color:red;">*</span></label><br>
    <div style="display:flex; gap:10px; margin-bottom:10px;">
        <input type="text" name="cidade_origem" placeholder="Cidade" required style="flex:1; padding:6px;">
        <select name="estado_origem" required style="padding:6px; width:90px;">
            <option value="">UF</option>
            __OPCOES_ESTADOS__
        </select>
    </div>

    <label>Local de destino: <span style="color:red;">*</span></label><br>
    <div style="display:flex; gap:10px; margin-bottom:10px;">
        <input type="text" name="cidade_destino" placeholder="Cidade" required style="flex:1; padding:6px;">
        <select name="estado_destino" required style="padding:6px; width:90px;">
            <option value="">UF</option>
            __OPCOES_ESTADOS__
        </select>
    </div>

    <label>Tipo de diária: <span style="color:red;">*</span></label><br>
    <select name="tipo_destino" id="tipo_destino" required style="padding:6px; margin-bottom:10px;">
        __OPCOES_AREAS__
    </select><br>

    <label>Diária Cheia ou Meia? <span style="color:red;">*</span></label><br>
    <select name="tipo_diaria" id="tipo_diaria" required style="padding:6px; margin-bottom:10px;">
        __OPCOES_DIARIA__
    </select><br>

    <label>Número de pernoites (calculado automaticamente):</label><br>
    <input type="number" name="numero_pernoites" id="numero_pernoites" min="0" readonly style="padding:6px; margin-bottom:10px; background:#f5f5f5; width:100px;"><br>

    <label>Valor da diária (R$):</label><br>
    <input type="text" id="valor_diaria_display" readonly style="padding:6px; margin-bottom:10px; background:#f5f5f5; width:120px;" value="0,00"><br>

    <div class="bloco">
        <label>Haverá Auxílio Deslocamento?</label><br>
        <select name="tera_auxilio" id="tera_auxilio" style="padding:6px; margin-bottom:10px;">
            <option value="nao">Não</option>
            <option value="sim">Sim</option>
        </select><br>

        <div id="bloco_qtd_auxilio" style="display:none;">
            <label>Quantidade de Auxílio Deslocamento:</label><br>
            <input type="number" name="quantidade_auxilio" id="quantidade_auxilio" min="1" value="1" style="padding:6px; margin-bottom:10px; width:100px;"><br>

            <label>Valor total do auxílio (R$ 95,00 cada):</label><br>
            <input type="text" id="valor_auxilio_display" readonly style="padding:6px; margin-bottom:10px; background:#f5f5f5; width:120px;" value="95,00"><br>

            <div id="bloco_justificativa_auxilio" style="display:none;">
                <label>Justificativa (obrigatória para mais de 1 auxílio):</label><br>
                <textarea name="justificativa_auxilio" id="justificativa_auxilio" style="width:100%; padding:6px; margin-bottom:10px;" rows="2"></textarea><br>
            </div>
        </div>
    </div>

    <label>Justificativa para a diária: <span style="color:red;">*</span></label><br>
    <textarea name="justificativa" required style="width:100%; padding:6px; margin-bottom:10px;" rows="3"></textarea><br>

    <h3>Dados bancários do diarista</h3>
    <label>CPF:</label><br>
    <input type="text" name="cpf_diarista" style="padding:6px; margin-bottom:10px;"><br>

    <label>Telefone:</label><br>
    <input type="text" name="telefone_diarista" style="padding:6px; margin-bottom:10px;"><br>

    <label>E-mail:</label><br>
    <input type="email" name="email_diarista" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Banco: <span style="color:red;">*</span></label><br>
    <input type="text" name="banco_diarista" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Agência: <span style="color:red;">*</span></label><br>
    <input type="text" name="agencia_diarista" required style="padding:6px; margin-bottom:10px; width:150px;"><br>

    <label>Conta: <span style="color:red;">*</span></label><br>
    <input type="text" name="conta_diarista" required style="padding:6px; margin-bottom:10px; width:200px;"><br>

    <label>Chave PIX: <span style="color:red;">*</span></label><br>
    <input type="text" name="chave_pix" required style="width:100%; padding:6px; margin-bottom:15px;"><br>

    <label>Anexar relatório de prestação de contas (opcional):</label><br>
    <input type="file" name="anexo_prestacao_contas" accept=".pdf,.jpg,.jpeg,.png,.doc,.docx" style="margin-bottom:15px;"><br>

    <button type="submit" style="padding:10px 20px; background:#2b5876; color:white; border:none; border-radius:4px; cursor:pointer;">Enviar solicitação</button>
</form>

<script>
var VALOR_AUXILIO = __VALOR_AUXILIO__;

function atualizarValorDiaria() {
    var tipoDestino = document.getElementById('tipo_destino').value;
    var tipoDiaria = document.getElementById('tipo_diaria').value;
    fetch('/api/valor-diaria?tipo_destino=' + encodeURIComponent(tipoDestino) + '&tipo_diaria=' + encodeURIComponent(tipoDiaria))
        .then(function(resposta) { return resposta.json(); })
        .then(function(dados) {
            document.getElementById('valor_diaria_display').value = dados.valor.toFixed(2).replace('.', ',');
        });
}

function calcularPernoites() {
    var ida = document.getElementById('data_ida').value;
    var retorno = document.getElementById('data_retorno').value;
    if (ida && retorno) {
        var dataIda = new Date(ida);
        var dataRetorno = new Date(retorno);
        var diffMs = dataRetorno - dataIda;
        var diffDias = Math.round(diffMs / (1000 * 60 * 60 * 24));
        if (diffDias < 0) { diffDias = 0; }
        document.getElementById('numero_pernoites').value = diffDias;
    }
}

function atualizarBlocoAuxilio() {
    var tera = document.getElementById('tera_auxilio').value;
    var blocoQtd = document.getElementById('bloco_qtd_auxilio');
    if (tera === 'sim') {
        blocoQtd.style.display = 'block';
    } else {
        blocoQtd.style.display = 'none';
    }
    atualizarQuantidadeAuxilio();
}

function atualizarQuantidadeAuxilio() {
    var qtd = parseInt(document.getElementById('quantidade_auxilio').value) || 0;
    var valorTotal = qtd * VALOR_AUXILIO;
    document.getElementById('valor_auxilio_display').value = valorTotal.toFixed(2).replace('.', ',');
    var blocoJustificativa = document.getElementById('bloco_justificativa_auxilio');
    var campoJustificativa = document.getElementById('justificativa_auxilio');
    if (qtd > 1) {
        blocoJustificativa.style.display = 'block';
        campoJustificativa.required = true;
    } else {
        blocoJustificativa.style.display = 'none';
        campoJustificativa.required = false;
    }
}

document.getElementById('tipo_destino').addEventListener('change', atualizarValorDiaria);
document.getElementById('tipo_diaria').addEventListener('change', atualizarValorDiaria);
document.getElementById('data_ida').addEventListener('change', calcularPernoites);
document.getElementById('data_retorno').addEventListener('change', calcularPernoites);
document.getElementById('tera_auxilio').addEventListener('change', atualizarBlocoAuxilio);
document.getElementById('quantidade_auxilio').addEventListener('input', atualizarQuantidadeAuxilio);

atualizarValorDiaria();
atualizarBlocoAuxilio();
</script>
"""


@app.route('/solicitacao/diaria', methods=['GET', 'POST'])
@login_required
def diaria_form():
    if request.method == 'POST':
        tipo_destino = request.form.get('tipo_destino')
        tipo_diaria = request.form.get('tipo_diaria')
        valor_diaria = obter_valor_diaria(tipo_diaria, tipo_destino)

        tera_auxilio = request.form.get('tera_auxilio') == 'sim'
        quantidade_auxilio = int(request.form.get('quantidade_auxilio') or 0) if tera_auxilio else 0
        justificativa_auxilio = request.form.get('justificativa_auxilio', '').strip()

        if tera_auxilio and quantidade_auxilio > 1 and not justificativa_auxilio:
            flash('Justificativa é obrigatória quando a solicitação tem mais de um Auxílio Deslocamento.')
            form_html = DIARIA_FORM_TEMPLATE.replace('__OPCOES_AREAS__', montar_opcoes_areas())
            form_html = form_html.replace('__OPCOES_DIARIA__', montar_opcoes(TIPOS_DIARIA))
            form_html = form_html.replace('__OPCOES_ESTADOS__', montar_opcoes_estados())
            form_html = form_html.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
            form_html = form_html.replace('__VALOR_AUXILIO__', str(obter_configuracao(CHAVE_VALOR_AUXILIO, VALOR_AUXILIO_PADRAO)))
            return render_pagina('Solicitação de Diária', form_html)

        valor_auxilio_unitario = obter_configuracao(CHAVE_VALOR_AUXILIO, VALOR_AUXILIO_PADRAO)
        valor_auxilio_total = quantidade_auxilio * valor_auxilio_unitario if tera_auxilio else 0

        valor_total_solicitacao = valor_diaria + valor_auxilio_total

        solicitacao = Solicitacao(
            tipo='diaria',
            solicitante_id=current_user.id,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=valor_total_solicitacao,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
        )
        db.session.add(solicitacao)
        db.session.flush()

        diaria = SolicitacaoDiaria(
            solicitacao_id=solicitacao.id,
            nome_diarista=request.form.get('nome_diarista'),
            data_ida=request.form.get('data_ida'),
            data_retorno=request.form.get('data_retorno'),
            cidade_origem=request.form.get('cidade_origem'),
            estado_origem=request.form.get('estado_origem'),
            cidade_destino=request.form.get('cidade_destino'),
            estado_destino=request.form.get('estado_destino'),
            tipo_destino=tipo_destino,
            tipo_diaria=tipo_diaria,
            numero_pernoites=request.form.get('numero_pernoites') or 0,
            valor_diaria=valor_diaria,
            tera_auxilio_deslocamento=tera_auxilio,
            quantidade_auxilio=quantidade_auxilio,
            valor_auxilio=valor_auxilio_total,
            justificativa_auxilio=justificativa_auxilio,
            justificativa=request.form.get('justificativa'),
            cpf_diarista=request.form.get('cpf_diarista'),
            telefone_diarista=request.form.get('telefone_diarista'),
            email_diarista=request.form.get('email_diarista'),
            banco_diarista=request.form.get('banco_diarista'),
            agencia_diarista=request.form.get('agencia_diarista'),
            conta_diarista=request.form.get('conta_diarista'),
            chave_pix=request.form.get('chave_pix'),
        )
        db.session.add(diaria)

        arquivo_prestacao = request.files.get('anexo_prestacao_contas')
        if arquivo_prestacao and arquivo_prestacao.filename:
            db.session.add(Anexo(
                solicitacao_id=solicitacao.id,
                nome_arquivo=arquivo_prestacao.filename,
                tipo_conteudo=arquivo_prestacao.content_type,
                dados=arquivo_prestacao.read(),
            ))

        db.session.commit()
        flash('Solicitação de diária enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    form_html = DIARIA_FORM_TEMPLATE.replace('__OPCOES_AREAS__', montar_opcoes_areas())
    form_html = form_html.replace('__OPCOES_DIARIA__', montar_opcoes(TIPOS_DIARIA))
    form_html = form_html.replace('__OPCOES_ESTADOS__', montar_opcoes_estados())
    form_html = form_html.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    form_html = form_html.replace('__VALOR_AUXILIO__', str(obter_configuracao(CHAVE_VALOR_AUXILIO, VALOR_AUXILIO_PADRAO)))
    return render_pagina('Solicitação de Diária', form_html)


# ---------------- SOLICITAÇÃO: PASSAGEM ----------------
PASSAGEM_FORM_TEMPLATE = """
<form method="POST" style="max-width: 600px;" id="form-passagem">
    <h3>Dados gerais</h3>
    <label>Ponto Focal:</label><br>
    <input type="text" name="ponto_focal" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Atividade/Projeto relacionado:</label><br>
    <input type="text" name="atividade_projeto" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Coordenação Solicitante: <span style="color:red;">*</span></label><br>
    <select name="coordenacao_solicitante" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        __OPCOES_COORDENACAO__
    </select><br>

    <label>Contato (telefone ou e-mail): <span style="color:red;">*</span></label><br>
    <input type="text" name="contato_solicitante" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    __CAMPO_CONVENIO__

    <h3>Dados da passagem</h3>
    <label>Tipo de transporte: <span style="color:red;">*</span></label><br>
    <select name="tipo_transporte" required style="padding:6px; margin-bottom:10px;">
        __OPCOES_TRANSPORTE__
    </select><br>

    <label>Local de origem: <span style="color:red;">*</span></label><br>
    <div style="display:flex; gap:10px; margin-bottom:10px;">
        <input type="text" name="cidade_origem" id="cidade_origem" placeholder="Cidade" required style="flex:1; padding:6px;">
        <select name="estado_origem" id="estado_origem" required style="padding:6px; width:90px;">
            <option value="">UF</option>
            __OPCOES_ESTADOS__
        </select>
    </div>

    <label>Local de destino: <span style="color:red;">*</span></label><br>
    <div style="display:flex; gap:10px; margin-bottom:10px;">
        <input type="text" name="cidade_destino" id="cidade_destino" placeholder="Cidade" required style="flex:1; padding:6px;">
        <select name="estado_destino" id="estado_destino" required style="padding:6px; width:90px;">
            <option value="">UF</option>
            __OPCOES_ESTADOS__
        </select>
    </div>

    <label>Data de ida: <span style="color:red;">*</span></label><br>
    <input type="date" name="data_ida" id="data_ida" required style="padding:6px; margin-bottom:10px;"><br>

    <label>Data de volta:</label><br>
    <input type="date" name="data_volta" id="data_volta" style="padding:6px; margin-bottom:10px;"><br>

    <label>
        <input type="checkbox" name="com_bagagem" value="sim" style="width:auto;"> Necessita de bagagem despachada
    </label><br><br>

    <div class="bloco">
        <label>Consultar preços (abre em nova aba):</label><br>
        <a href="#" id="link-google-flights" target="_blank" class="btn-atalho">Google Flights</a>
        <a href="https://www.voeazul.com.br/br/pt/passagens" target="_blank" class="btn-atalho">Azul</a>
        <a href="https://www.voegol.com.br/" target="_blank" class="btn-atalho">Gol</a>
        <a href="https://www.latamairlines.com/br/pt" target="_blank" class="btn-atalho">Latam</a>
        <div style="font-size:11px; color:#888; margin-top:4px;">O Google Flights abre já com origem, destino e data preenchidos (usando o código do aeroporto quando reconhecido). Os sites das companhias abrem na página de busca, mas você precisa digitar os dados lá.</div>
    </div>

    <label>Valor estimado da passagem: <span style="color:red;">*</span></label><br>
    <input type="text" id="valor_estimado_display" placeholder="R$ 0,00" required style="padding:6px; margin-bottom:10px; width:150px;">
    <input type="hidden" name="valor_estimado" id="valor_estimado_hidden"><br>

    <label>Justificativa: <span style="color:red;">*</span></label><br>
    <textarea name="justificativa" required style="width:100%; padding:6px; margin-bottom:10px;" rows="3"></textarea><br>

    <h3>Dados do passageiro</h3>
    <label>Nome: <span style="color:red;">*</span></label><br>
    <input type="text" name="nome_passageiro" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>CPF: <span style="color:red;">*</span></label><br>
    <input type="text" name="cpf_passageiro" required style="padding:6px; margin-bottom:10px;"><br>

    <label>RG, Órgão e Estado de emissão: <span style="color:red;">*</span></label><br>
    <input type="text" name="rg_orgao_uf_passageiro" required placeholder="Ex: 12.345.678-9 SSP/PA" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Data de nascimento: <span style="color:red;">*</span></label><br>
    <input type="date" name="data_nascimento_passageiro" required style="padding:6px; margin-bottom:10px;"><br>

    <label>Telefone com DDD: <span style="color:red;">*</span></label><br>
    <input type="text" name="telefone_passageiro" required style="padding:6px; margin-bottom:10px;"><br>

    <label>E-mail: <span style="color:red;">*</span></label><br>
    <input type="email" name="email_passageiro" required style="width:100%; padding:6px; margin-bottom:15px;"><br>

    <button type="submit" style="padding:10px 20px; background:#2b5876; color:white; border:none; border-radius:4px; cursor:pointer;">Enviar solicitação</button>
</form>

<script>
var AEROPORTOS_IATA = {
    'parauapebas': 'CKS', 'belem': 'BEL', 'belo horizonte': 'CNF',
    'brasilia': 'BSB', 'sao paulo': 'GRU', 'rio de janeiro': 'GIG',
    'salvador': 'SSA', 'recife': 'REC', 'fortaleza': 'FOR',
    'manaus': 'MAO', 'porto alegre': 'POA', 'curitiba': 'CWB',
    'goiania': 'GYN', 'campo grande': 'CGR', 'cuiaba': 'CGB',
    'maraba': 'MAB', 'santarem': 'STM', 'altamira': 'ATM',
    'imperatriz': 'IMP', 'sao luis': 'SLZ', 'palmas': 'PMW',
    'macapa': 'MCP', 'natal': 'NAT', 'joao pessoa': 'JPA',
    'maceio': 'MCZ', 'aracaju': 'AJU', 'vitoria': 'VIX',
    'florianopolis': 'FLN', 'porto velho': 'PVH', 'rio branco': 'RBR',
    'boa vista': 'BVB'
};

function normalizarTexto(texto) {
    return texto.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').trim();
}

function obterCodigoAeroporto(cidade) {
    return AEROPORTOS_IATA[normalizarTexto(cidade)] || cidade;
}

function atualizarLinkGoogleFlights() {
    var cidadeOrigem = document.getElementById('cidade_origem').value;
    var cidadeDestino = document.getElementById('cidade_destino').value;
    var dataIda = document.getElementById('data_ida').value;

    if (!cidadeOrigem || !cidadeDestino) {
        return;
    }

    var origem = obterCodigoAeroporto(cidadeOrigem);
    var destino = obterCodigoAeroporto(cidadeDestino);

    var query = 'Voos de ' + origem + ' para ' + destino;
    if (dataIda) {
        query += ' em ' + dataIda;
    }

    var url = 'https://www.google.com/travel/flights?hl=pt-BR&gl=BR&q=' + encodeURIComponent(query);
    document.getElementById('link-google-flights').href = url;
}

['cidade_origem', 'estado_origem', 'cidade_destino', 'estado_destino', 'data_ida'].forEach(function(id) {
    document.getElementById(id).addEventListener('input', atualizarLinkGoogleFlights);
    document.getElementById(id).addEventListener('change', atualizarLinkGoogleFlights);
});
atualizarLinkGoogleFlights();

var campoValor = document.getElementById('valor_estimado_display');
var campoValorOculto = document.getElementById('valor_estimado_hidden');

campoValor.addEventListener('input', function() {
    var somenteDigitos = campoValor.value.replace(/\D/g, '');
    if (somenteDigitos === '') {
        campoValor.value = '';
        campoValorOculto.value = '';
        return;
    }
    var valorCentavos = parseInt(somenteDigitos, 10);
    var valorReais = valorCentavos / 100;

    campoValorOculto.value = valorReais.toFixed(2);
    campoValor.value = 'R$ ' + valorReais.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
});
</script>
"""


CAMPO_CONVENIO_HTML = """
    <label>Convênio:</label><br>
    <input type="text" name="convenio" style="width:100%; padding:6px; margin-bottom:10px;"><br>
"""


@app.route('/solicitacao/passagem', methods=['GET', 'POST'])
@login_required
def passagem_form():
    pode_ver_convenio = current_user.is_organizador or current_user.is_aprovador

    if request.method == 'POST':
        valor_estimado = request.form.get('valor_estimado') or 0

        solicitacao = Solicitacao(
            tipo='passagem',
            solicitante_id=current_user.id,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=valor_estimado,
            convenio=request.form.get('convenio') if pode_ver_convenio else None,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
        )
        db.session.add(solicitacao)
        db.session.flush()

        passagem = SolicitacaoPassagem(
            solicitacao_id=solicitacao.id,
            nome_passageiro=request.form.get('nome_passageiro'),
            tipo_transporte=request.form.get('tipo_transporte'),
            cidade_origem=request.form.get('cidade_origem'),
            estado_origem=request.form.get('estado_origem'),
            cidade_destino=request.form.get('cidade_destino'),
            estado_destino=request.form.get('estado_destino'),
            data_ida=request.form.get('data_ida'),
            data_volta=request.form.get('data_volta') or None,
            com_bagagem=(request.form.get('com_bagagem') == 'sim'),
            valor_estimado=valor_estimado,
            justificativa=request.form.get('justificativa'),
            cpf_passageiro=request.form.get('cpf_passageiro'),
            rg_orgao_uf_passageiro=request.form.get('rg_orgao_uf_passageiro'),
            data_nascimento_passageiro=request.form.get('data_nascimento_passageiro'),
            telefone_passageiro=request.form.get('telefone_passageiro'),
            email_passageiro=request.form.get('email_passageiro'),
        )
        db.session.add(passagem)
        db.session.commit()
        flash('Solicitação de passagem enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    form_html = PASSAGEM_FORM_TEMPLATE.replace('__OPCOES_TRANSPORTE__', montar_opcoes(TIPOS_TRANSPORTE))
    form_html = form_html.replace('__OPCOES_ESTADOS__', montar_opcoes_estados())
    form_html = form_html.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    form_html = form_html.replace('__CAMPO_CONVENIO__', CAMPO_CONVENIO_HTML if pode_ver_convenio else '')
    return render_pagina('Solicitação de Passagem', form_html)


# ---------------- SOLICITAÇÃO: COMPRAS DE MATERIAIS ----------------
COMPRA_MATERIAIS_FORM_TEMPLATE = """
<form method="POST" enctype="multipart/form-data" style="max-width: 600px;" id="form-compra-materiais">
    <h3>Dados gerais</h3>
    <label>Ponto Focal:</label><br>
    <input type="text" name="ponto_focal" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Atividade/Projeto relacionado:</label><br>
    <input type="text" name="atividade_projeto" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Coordenação Solicitante: <span style="color:red;">*</span></label><br>
    <select name="coordenacao_solicitante" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        __OPCOES_COORDENACAO__
    </select><br>

    <label>Contato (telefone ou e-mail): <span style="color:red;">*</span></label><br>
    <input type="text" name="contato_solicitante" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Data de entrega do material: <span style="color:red;">*</span></label><br>
    <input type="date" name="data_entrega_material" required style="padding:6px; margin-bottom:10px;"><br>

    <h3>Dados do item</h3>
    <label>Nome e especificação do item: <span style="color:red;">*</span></label><br>
    <textarea name="nome_especificacao" required placeholder="Informe detalhes do item (marca, modelo, cor, tamanho etc.)" style="width:100%; padding:6px; margin-bottom:10px;" rows="2"></textarea><br>

    <label>Sugestão de fornecedor (loja):</label><br>
    <input type="text" name="fornecedor_sugerido" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Forma de aquisição: <span style="color:red;">*</span></label><br>
    <select name="forma_aquisicao" id="forma_aquisicao" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        <option value="Local">Local</option>
        <option value="Online">Online</option>
    </select><br>

    <label>Link do produto <span id="marca_obrigatorio_link" style="color:red; display:none;">*</span> <span style="font-weight:normal; font-size:11px; color:#888;">(obrigatório se a compra for Online)</span>:</label><br>
    <input type="url" name="link_produto" id="link_produto" placeholder="https://" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Quantidade: <span style="color:red;">*</span></label><br>
    <input type="number" step="0.01" name="quantidade" id="quantidade" required style="padding:6px; margin-bottom:10px; width:120px;"><br>

    <label>Valor unitário: <span style="color:red;">*</span></label><br>
    <input type="text" id="valor_unitario_display" placeholder="R$ 0,00" required style="padding:6px; margin-bottom:10px; width:150px;">
    <input type="hidden" name="valor_unitario" id="valor_unitario_hidden"><br>

    <label>Valor total do item (calculado automaticamente):</label><br>
    <input type="text" id="valor_total_display" readonly style="padding:6px; margin-bottom:10px; background:#f5f5f5; width:150px;" value="R$ 0,00"><br>

    <label>Justificativa da compra: <span style="color:red;">*</span></label><br>
    <textarea name="justificativa" required style="width:100%; padding:6px; margin-bottom:15px;" rows="3"></textarea><br>

    <label>Anexos:</label><br>
    <input type="file" name="anexos" id="anexos" multiple accept=".pdf,.jpg,.jpeg,.png,.doc,.docx,.xls,.xlsx" style="margin-bottom:5px;"><br>
    <div id="aviso_anexos" style="font-size:12px; color:#a00; margin-bottom:10px; display:none;">
        Compras acima de R$ 5.000,00 exigem pelo menos 3 orçamentos anexados.
    </div>

    <button type="submit" style="padding:10px 20px; background:#2b5876; color:white; border:none; border-radius:4px; cursor:pointer;">Enviar solicitação</button>
</form>

<script>
document.getElementById('forma_aquisicao').addEventListener('change', function() {
    var campoLink = document.getElementById('link_produto');
    var marca = document.getElementById('marca_obrigatorio_link');
    if (this.value === 'Online') {
        campoLink.required = true;
        marca.style.display = 'inline';
    } else {
        campoLink.required = false;
        marca.style.display = 'none';
    }
});

var campoValorUnitario = document.getElementById('valor_unitario_display');
var campoValorUnitarioOculto = document.getElementById('valor_unitario_hidden');
var campoQuantidade = document.getElementById('quantidade');
var campoValorTotal = document.getElementById('valor_total_display');

function atualizarValorTotal() {
    var unitario = parseFloat(campoValorUnitarioOculto.value) || 0;
    var quantidade = parseFloat(campoQuantidade.value) || 0;
    var total = unitario * quantidade;
    campoValorTotal.value = 'R$ ' + total.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

campoValorUnitario.addEventListener('input', function() {
    var somenteDigitos = campoValorUnitario.value.replace(/\D/g, '');
    if (somenteDigitos === '') {
        campoValorUnitario.value = '';
        campoValorUnitarioOculto.value = '';
        atualizarValorTotal();
        return;
    }
    var valorCentavos = parseInt(somenteDigitos, 10);
    var valorReais = valorCentavos / 100;
    campoValorUnitarioOculto.value = valorReais.toFixed(2);
    campoValorUnitario.value = 'R$ ' + valorReais.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    atualizarValorTotal();
});

campoQuantidade.addEventListener('input', atualizarValorTotal);

document.getElementById('form-compra-materiais').addEventListener('submit', function(evento) {
    var valorTotal = parseFloat(campoValorUnitarioOculto.value || 0) * parseFloat(campoQuantidade.value || 0);
    var arquivos = document.getElementById('anexos').files;
    var aviso = document.getElementById('aviso_anexos');

    if (valorTotal > 5000 && arquivos.length < 3) {
        evento.preventDefault();
        aviso.style.display = 'block';
        aviso.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
        aviso.style.display = 'none';
    }
});
</script>
"""


@app.route('/solicitacao/compra-materiais', methods=['GET', 'POST'])
@login_required
def compra_materiais_form():
    if request.method == 'POST':
        quantidade = float(request.form.get('quantidade') or 0)
        valor_unitario = float(request.form.get('valor_unitario') or 0)
        valor_total_item = quantidade * valor_unitario

        arquivos = request.files.getlist('anexos')
        arquivos_validos = [a for a in arquivos if a and a.filename]

        if valor_total_item > 5000 and len(arquivos_validos) < 3:
            flash('Compras acima de R$ 5.000,00 exigem pelo menos 3 orçamentos anexados.')
            form_html = COMPRA_MATERIAIS_FORM_TEMPLATE.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
            return render_pagina('Solicitação de Compra de Materiais', form_html)

        solicitacao = Solicitacao(
            tipo='compra_materiais',
            solicitante_id=current_user.id,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=valor_total_item,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
        )
        db.session.add(solicitacao)
        db.session.flush()

        compra = SolicitacaoCompraMateriais(
            solicitacao_id=solicitacao.id,
            data_entrega_material=request.form.get('data_entrega_material'),
            nome_especificacao=request.form.get('nome_especificacao'),
            fornecedor_sugerido=request.form.get('fornecedor_sugerido'),
            forma_aquisicao=request.form.get('forma_aquisicao'),
            link_produto=request.form.get('link_produto'),
            quantidade=quantidade,
            valor_unitario=valor_unitario,
            valor_total_item=valor_total_item,
            justificativa=request.form.get('justificativa'),
        )
        db.session.add(compra)

        for arquivo in arquivos_validos:
            db.session.add(Anexo(
                solicitacao_id=solicitacao.id,
                nome_arquivo=arquivo.filename,
                tipo_conteudo=arquivo.content_type,
                dados=arquivo.read(),
            ))

        db.session.commit()
        flash('Solicitação de compra de materiais enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    form_html = COMPRA_MATERIAIS_FORM_TEMPLATE.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    return render_pagina('Solicitação de Compra de Materiais', form_html)


# ---------------- SOLICITAÇÃO: ALIMENTAÇÃO ----------------
ALIMENTACAO_FORM_TEMPLATE = """
<form method="POST" enctype="multipart/form-data" style="max-width: 600px;" id="form-alimentacao">
    <h3>Dados gerais</h3>
    <label>Ponto Focal:</label><br>
    <input type="text" name="ponto_focal" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Atividade/Projeto relacionado:</label><br>
    <input type="text" name="atividade_projeto" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Coordenação Solicitante: <span style="color:red;">*</span></label><br>
    <select name="coordenacao_solicitante" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        __OPCOES_COORDENACAO__
    </select><br>

    <label>Contato (telefone ou e-mail): <span style="color:red;">*</span></label><br>
    <input type="text" name="contato_solicitante" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <h3>Dados da alimentação</h3>
    <label>Tipo de alimentação: <span style="color:red;">*</span></label><br>
    <select name="tipo_alimentacao" id="tipo_alimentacao" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        __OPCOES_TIPOS_ALIMENTACAO__
    </select><br>

    <label>Quantidade de pessoas para atendimento: <span style="color:red;">*</span></label><br>
    <input type="number" name="quantidade_pessoas" id="quantidade_pessoas" min="1" required style="padding:6px; margin-bottom:10px; width:120px;"><br>

    <label>Entrega ou retirada no fornecedor: <span style="color:red;">*</span></label><br>
    <select name="forma_entrega" id="forma_entrega" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        <option value="Entrega">Entrega</option>
        <option value="Retirada no fornecedor">Retirada no fornecedor</option>
    </select><br>

    <label>Local de entrega <span id="marca_obrigatorio_local" style="color:red; display:none;">*</span>:</label><br>
    <input type="text" name="local_entrega" id="local_entrega" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Data de entrega/retirada: <span style="color:red;">*</span></label><br>
    <input type="date" name="data_entrega" required style="padding:6px; margin-bottom:10px;"><br>

    <label>Horário de entrega/retirada: <span style="color:red;">*</span></label><br>
    <input type="time" name="horario_entrega" required style="padding:6px; margin-bottom:10px;"><br>

    <label>Custo unitário aproximado (R$):</label><br>
    <input type="text" id="custo_unitario_display" readonly style="padding:6px; margin-bottom:10px; background:#f5f5f5; width:120px;" value="0,00">
    <input type="hidden" name="custo_unitario" id="custo_unitario_hidden" value="0"><br>

    <label>Custo total aproximado (R$):</label><br>
    <input type="text" id="custo_total_display" readonly style="padding:6px; margin-bottom:10px; background:#f5f5f5; width:120px;" value="0,00"><br>

    <label>Justificativa para a solicitação: <span style="color:red;">*</span></label><br>
    <textarea name="justificativa" required style="width:100%; padding:6px; margin-bottom:10px;" rows="3"></textarea><br>

    <label>Anexar lista de participantes: <span style="color:red;">*</span></label><br>
    <input type="file" name="anexo_lista_participantes" required accept=".pdf,.jpg,.jpeg,.png,.doc,.docx,.xls,.xlsx" style="margin-bottom:15px;"><br>

    <button type="submit" style="padding:10px 20px; background:#2b5876; color:white; border:none; border-radius:4px; cursor:pointer;">Enviar solicitação</button>
</form>

<script>
var VALORES_ALIMENTACAO = __VALORES_ALIMENTACAO__;

function atualizarCustos() {
    var tipo = document.getElementById('tipo_alimentacao').value;
    var quantidade = parseFloat(document.getElementById('quantidade_pessoas').value) || 0;
    var unitario = VALORES_ALIMENTACAO[tipo] || 0;
    var total = unitario * quantidade;

    document.getElementById('custo_unitario_hidden').value = unitario.toFixed(2);
    document.getElementById('custo_unitario_display').value = unitario.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    document.getElementById('custo_total_display').value = total.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

document.getElementById('tipo_alimentacao').addEventListener('change', atualizarCustos);
document.getElementById('quantidade_pessoas').addEventListener('input', atualizarCustos);

document.getElementById('forma_entrega').addEventListener('change', function() {
    var campoLocal = document.getElementById('local_entrega');
    var marca = document.getElementById('marca_obrigatorio_local');
    if (this.value === 'Entrega') {
        campoLocal.required = true;
        marca.style.display = 'inline';
    } else {
        campoLocal.required = false;
        marca.style.display = 'none';
    }
});
</script>
"""


@app.route('/solicitacao/alimentacao', methods=['GET', 'POST'])
@login_required
def alimentacao_form():
    if request.method == 'POST':
        quantidade_pessoas = int(request.form.get('quantidade_pessoas') or 0)
        custo_unitario = float(request.form.get('custo_unitario') or 0)
        custo_total = custo_unitario * quantidade_pessoas

        arquivo_lista = request.files.get('anexo_lista_participantes')
        if not arquivo_lista or not arquivo_lista.filename:
            flash('É obrigatório anexar a lista de participantes.')
            form_html = ALIMENTACAO_FORM_TEMPLATE.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
            form_html = form_html.replace('__OPCOES_TIPOS_ALIMENTACAO__', montar_opcoes_tipos_alimentacao())
            form_html = form_html.replace('__VALORES_ALIMENTACAO__', montar_dict_valores_alimentacao())
            return render_pagina('Solicitação de Alimentação', form_html)

        solicitacao = Solicitacao(
            tipo='alimentacao',
            solicitante_id=current_user.id,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=custo_total,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
        )
        db.session.add(solicitacao)
        db.session.flush()

        alimentacao = SolicitacaoAlimentacao(
            solicitacao_id=solicitacao.id,
            tipo_alimentacao=request.form.get('tipo_alimentacao'),
            quantidade_pessoas=quantidade_pessoas,
            forma_entrega=request.form.get('forma_entrega'),
            local_entrega=request.form.get('local_entrega'),
            data_entrega=request.form.get('data_entrega'),
            horario_entrega=request.form.get('horario_entrega'),
            custo_unitario=custo_unitario,
            custo_total=custo_total,
            justificativa=request.form.get('justificativa'),
        )
        db.session.add(alimentacao)

        db.session.add(Anexo(
            solicitacao_id=solicitacao.id,
            nome_arquivo=arquivo_lista.filename,
            tipo_conteudo=arquivo_lista.content_type,
            dados=arquivo_lista.read(),
        ))

        db.session.commit()
        flash('Solicitação de alimentação enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    form_html = ALIMENTACAO_FORM_TEMPLATE.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    form_html = form_html.replace('__OPCOES_TIPOS_ALIMENTACAO__', montar_opcoes_tipos_alimentacao())
    form_html = form_html.replace('__VALORES_ALIMENTACAO__', montar_dict_valores_alimentacao())
    return render_pagina('Solicitação de Alimentação', form_html)


# ---------------- CADASTROS: ALIMENTAÇÃO (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/alimentacao')
@login_required
def cadastro_alimentacao():
    somente_organizador()

    tipos = TipoAlimentacao.query.order_by(TipoAlimentacao.nome).all()
    linhas_html = ''
    for tipo in tipos:
        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_alimentacao_atualizar', tipo_id=tipo.id)}" style="display:contents;">
            <td><input type="text" name="nome" value="{tipo.nome}" style="width:180px; padding:4px;"></td>
            <td><input type="number" step="0.01" name="valor" value="{tipo.valor}" style="width:100px; padding:4px;"></td>
            <td>
                <button type="submit" class="btn btn-salvar">Salvar</button>
            </form>
            <form method="POST" action="{url_for('cadastro_alimentacao_excluir', tipo_id=tipo.id)}" style="display:inline;" onsubmit="return confirm('Excluir o tipo {tipo.nome}?');">
                <button type="submit" class="btn btn-excluir">Excluir</button>
            </form>
            </td>
        </tr>
        """

    conteudo = f"""
    <h2>Tipos de Alimentação</h2>
    <table>
        <tr><th>Nome</th><th>Valor (R$)</th><th>Ações</th></tr>
        {linhas_html}
    </table>

    <h3 style="margin-top:25px;">Adicionar novo tipo</h3>
    <form method="POST" action="{url_for('cadastro_alimentacao_adicionar')}" style="max-width:400px;">
        <label>Nome do tipo:</label><br>
        <input type="text" name="nome" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <label>Valor (R$):</label><br>
        <input type="number" step="0.01" name="valor" required style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <button type="submit" class="btn btn-adicionar">Adicionar tipo</button>
    </form>
    """
    return render_pagina('Cadastro de Alimentação', conteudo)


@app.route('/cadastros/alimentacao/adicionar', methods=['POST'])
@login_required
def cadastro_alimentacao_adicionar():
    somente_organizador()
    nome = request.form.get('nome', '').strip()
    valor = request.form.get('valor')

    if not nome:
        flash('Informe o nome do tipo.')
        return redirect(url_for('cadastro_alimentacao'))

    if TipoAlimentacao.query.filter_by(nome=nome).first():
        flash('Já existe um tipo com esse nome.')
        return redirect(url_for('cadastro_alimentacao'))

    db.session.add(TipoAlimentacao(nome=nome, valor=valor))
    db.session.commit()
    flash(f'Tipo "{nome}" cadastrado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_alimentacao'))


@app.route('/cadastros/alimentacao/<int:tipo_id>/atualizar', methods=['POST'])
@login_required
def cadastro_alimentacao_atualizar(tipo_id):
    somente_organizador()
    tipo = TipoAlimentacao.query.get_or_404(tipo_id)
    tipo.nome = request.form.get('nome', '').strip()
    tipo.valor = request.form.get('valor')
    db.session.commit()
    flash('Tipo de alimentação atualizado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_alimentacao'))


@app.route('/cadastros/alimentacao/<int:tipo_id>/excluir', methods=['POST'])
@login_required
def cadastro_alimentacao_excluir(tipo_id):
    somente_organizador()
    tipo = TipoAlimentacao.query.get_or_404(tipo_id)
    nome = tipo.nome
    db.session.delete(tipo)
    db.session.commit()
    flash(f'Tipo "{nome}" excluído com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_alimentacao'))


# ---------------- SOLICITAÇÃO: LOCAÇÃO DE VEÍCULOS ----------------
LOCACAO_VEICULO_FORM_TEMPLATE = """
<form method="POST" style="max-width: 600px;" id="form-locacao-veiculo">
    <h3>Dados gerais</h3>
    <label>Ponto Focal:</label><br>
    <input type="text" name="ponto_focal" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Atividade/Projeto relacionado:</label><br>
    <input type="text" name="atividade_projeto" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Coordenação Solicitante: <span style="color:red;">*</span></label><br>
    <select name="coordenacao_solicitante" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        __OPCOES_COORDENACAO__
    </select><br>

    <label>Contato (telefone ou e-mail): <span style="color:red;">*</span></label><br>
    <input type="text" name="contato_solicitante" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <h3>Dados do veículo</h3>
    <label>Tipo de veículo: <span style="color:red;">*</span></label><br>
    <select name="tipo_veiculo" id="tipo_veiculo" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        __OPCOES_TIPOS_VEICULO__
    </select><br>

    <label>Quantidade de assentos:</label><br>
    <input type="text" id="assentos_display" readonly style="padding:6px; margin-bottom:10px; background:#f5f5f5; width:100px;" value="-"><br>

    <label>Especificações do veículo (traçado, observações etc.):</label><br>
    <input type="text" name="especificacoes" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Local de origem (com endereço): <span style="color:red;">*</span></label><br>
    <input type="text" name="local_origem" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Percurso / Pontos de parada: <span style="color:red;">*</span></label><br>
    <textarea name="percurso" required style="width:100%; padding:6px; margin-bottom:10px;" rows="2"></textarea><br>

    <label>Local de retorno (com endereço): <span style="color:red;">*</span></label><br>
    <input type="text" name="local_retorno" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Data e horário de partida do local de origem: <span style="color:red;">*</span></label><br>
    <input type="date" name="data_partida" required style="padding:6px; margin-bottom:6px;">
    <input type="time" name="horario_partida" required style="padding:6px; margin-bottom:10px;"><br>

    <label>Data e horário de chegada prevista no local de retorno: <span style="color:red;">*</span></label><br>
    <input type="date" name="data_chegada" required style="padding:6px; margin-bottom:6px;">
    <input type="time" name="horario_chegada" required style="padding:6px; margin-bottom:10px;"><br>

    <label>Expectativa de KM da viagem: <span style="color:red;">*</span></label><br>
    <input type="number" step="0.01" name="km_estimado" id="km_estimado" required style="padding:6px; margin-bottom:10px; width:120px;"><br>

    <label>Custo R$/KM:</label><br>
    <input type="text" id="custo_km_display" readonly style="padding:6px; margin-bottom:10px; background:#f5f5f5; width:120px;" value="0,00">
    <input type="hidden" name="custo_km" id="custo_km_hidden" value="0"><br>

    <label>Custo estimado da viagem (R$):</label><br>
    <input type="text" id="custo_estimado_display" readonly style="padding:6px; margin-bottom:10px; background:#f5f5f5; width:150px;" value="0,00"><br>

    <label>Justificativa da necessidade de locação: <span style="color:red;">*</span></label><br>
    <textarea name="justificativa" required style="width:100%; padding:6px; margin-bottom:10px;" rows="3"></textarea><br>

    <label>Observação (se houver):</label><br>
    <textarea name="observacao" style="width:100%; padding:6px; margin-bottom:15px;" rows="2"></textarea><br>

    <button type="submit" style="padding:10px 20px; background:#2b5876; color:white; border:none; border-radius:4px; cursor:pointer;">Enviar solicitação</button>
</form>

<script>
var VALORES_VEICULO = __VALORES_VEICULO__;
var ASSENTOS_VEICULO = __VALORES_ASSENTOS__;

function atualizarCustoViagem() {
    var tipo = document.getElementById('tipo_veiculo').value;
    var km = parseFloat(document.getElementById('km_estimado').value) || 0;
    var custoKm = VALORES_VEICULO[tipo] || 0;
    var custoTotal = custoKm * km;

    document.getElementById('custo_km_hidden').value = custoKm.toFixed(2);
    document.getElementById('custo_km_display').value = custoKm.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    document.getElementById('custo_estimado_display').value = custoTotal.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function atualizarAssentos() {
    var tipo = document.getElementById('tipo_veiculo').value;
    var assentos = ASSENTOS_VEICULO[tipo];
    document.getElementById('assentos_display').value = assentos ? (assentos + ' lugares') : '-';
}

document.getElementById('tipo_veiculo').addEventListener('change', atualizarCustoViagem);
document.getElementById('tipo_veiculo').addEventListener('change', atualizarAssentos);
document.getElementById('km_estimado').addEventListener('input', atualizarCustoViagem);
</script>
"""


@app.route('/solicitacao/locacao-veiculo', methods=['GET', 'POST'])
@login_required
def locacao_veiculo_form():
    if request.method == 'POST':
        km_estimado = float(request.form.get('km_estimado') or 0)
        custo_km = float(request.form.get('custo_km') or 0)
        custo_estimado = km_estimado * custo_km

        data_partida = request.form.get('data_partida')
        horario_partida = request.form.get('horario_partida')
        data_chegada = request.form.get('data_chegada')
        horario_chegada = request.form.get('horario_chegada')

        data_hora_partida = datetime.strptime(f'{data_partida} {horario_partida}', '%Y-%m-%d %H:%M')
        data_hora_chegada = datetime.strptime(f'{data_chegada} {horario_chegada}', '%Y-%m-%d %H:%M')

        solicitacao = Solicitacao(
            tipo='locacao_veiculo',
            solicitante_id=current_user.id,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=custo_estimado,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
        )
        db.session.add(solicitacao)
        db.session.flush()

        locacao = SolicitacaoLocacaoVeiculo(
            solicitacao_id=solicitacao.id,
            tipo_veiculo=request.form.get('tipo_veiculo'),
            especificacoes=request.form.get('especificacoes'),
            local_origem=request.form.get('local_origem'),
            percurso=request.form.get('percurso'),
            local_retorno=request.form.get('local_retorno'),
            data_hora_partida=data_hora_partida,
            data_hora_chegada=data_hora_chegada,
            km_estimado=km_estimado,
            custo_km=custo_km,
            custo_estimado=custo_estimado,
            justificativa=request.form.get('justificativa'),
            observacao=request.form.get('observacao'),
        )
        db.session.add(locacao)
        db.session.commit()
        flash('Solicitação de locação de veículo enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    form_html = LOCACAO_VEICULO_FORM_TEMPLATE.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    form_html = form_html.replace('__OPCOES_TIPOS_VEICULO__', montar_opcoes_tipos_veiculo())
    form_html = form_html.replace('__VALORES_VEICULO__', montar_dict_valores_veiculo())
    form_html = form_html.replace('__VALORES_ASSENTOS__', montar_dict_assentos_veiculo())
    return render_pagina('Solicitação de Locação de Veículo', form_html)


# ---------------- CADASTROS: LOCAÇÃO DE VEÍCULOS (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/locacao-veiculo')
@login_required
def cadastro_locacao_veiculo():
    somente_organizador()

    tipos = TipoVeiculo.query.order_by(TipoVeiculo.nome).all()
    linhas_html = ''
    for tipo in tipos:
        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_locacao_veiculo_atualizar', tipo_id=tipo.id)}" style="display:contents;">
            <td><input type="text" name="nome" value="{tipo.nome}" style="width:150px; padding:4px;"></td>
            <td><input type="number" step="0.01" name="valor_km" value="{tipo.valor_km}" style="width:90px; padding:4px;"></td>
            <td><input type="number" name="quantidade_assentos" value="{tipo.quantidade_assentos or 0}" style="width:80px; padding:4px;"></td>
            <td>
                <button type="submit" class="btn btn-salvar">Salvar</button>
            </form>
            <form method="POST" action="{url_for('cadastro_locacao_veiculo_excluir', tipo_id=tipo.id)}" style="display:inline;" onsubmit="return confirm('Excluir o tipo {tipo.nome}?');">
                <button type="submit" class="btn btn-excluir">Excluir</button>
            </form>
            </td>
        </tr>
        """

    conteudo = f"""
    <h2>Tipos de Veículo</h2>
    <table>
        <tr><th>Nome</th><th>Valor por KM (R$)</th><th>Qtd. Assentos</th><th>Ações</th></tr>
        {linhas_html}
    </table>

    <h3 style="margin-top:25px;">Adicionar novo tipo</h3>
    <form method="POST" action="{url_for('cadastro_locacao_veiculo_adicionar')}" style="max-width:400px;">
        <label>Nome do tipo:</label><br>
        <input type="text" name="nome" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <label>Valor por KM (R$):</label><br>
        <input type="number" step="0.01" name="valor_km" required style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <label>Quantidade de assentos:</label><br>
        <input type="number" name="quantidade_assentos" style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <button type="submit" class="btn btn-adicionar">Adicionar tipo</button>
    </form>
    """
    return render_pagina('Cadastro de Locação de Veículos', conteudo)


@app.route('/cadastros/locacao-veiculo/adicionar', methods=['POST'])
@login_required
def cadastro_locacao_veiculo_adicionar():
    somente_organizador()
    nome = request.form.get('nome', '').strip()
    valor_km = request.form.get('valor_km')

    if not nome:
        flash('Informe o nome do tipo.')
        return redirect(url_for('cadastro_locacao_veiculo'))

    if TipoVeiculo.query.filter_by(nome=nome).first():
        flash('Já existe um tipo com esse nome.')
        return redirect(url_for('cadastro_locacao_veiculo'))

    quantidade_assentos = request.form.get('quantidade_assentos') or 0
    db.session.add(TipoVeiculo(nome=nome, valor_km=valor_km, quantidade_assentos=quantidade_assentos))
    db.session.commit()
    flash(f'Tipo "{nome}" cadastrado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_locacao_veiculo'))


@app.route('/cadastros/locacao-veiculo/<int:tipo_id>/atualizar', methods=['POST'])
@login_required
def cadastro_locacao_veiculo_atualizar(tipo_id):
    somente_organizador()
    tipo = TipoVeiculo.query.get_or_404(tipo_id)
    tipo.nome = request.form.get('nome', '').strip()
    tipo.valor_km = request.form.get('valor_km')
    tipo.quantidade_assentos = request.form.get('quantidade_assentos') or 0
    db.session.commit()
    flash('Tipo de veículo atualizado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_locacao_veiculo'))


@app.route('/cadastros/locacao-veiculo/<int:tipo_id>/excluir', methods=['POST'])
@login_required
def cadastro_locacao_veiculo_excluir(tipo_id):
    somente_organizador()
    tipo = TipoVeiculo.query.get_or_404(tipo_id)
    nome = tipo.nome
    db.session.delete(tipo)
    db.session.commit()
    flash(f'Tipo "{nome}" excluído com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_locacao_veiculo'))


# ---------------- SOLICITAÇÃO: SERVIÇOS EXTERNOS ----------------
SERVICO_EXTERNO_FORM_TEMPLATE = """
<form method="POST" style="max-width: 700px;" id="form-servico-externo">
    <h3>Dados gerais</h3>
    <label>Ponto Focal:</label><br>
    <input type="text" name="ponto_focal" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Atividade/Projeto relacionado:</label><br>
    <input type="text" name="atividade_projeto" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Coordenação Solicitante: <span style="color:red;">*</span></label><br>
    <select name="coordenacao_solicitante" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        __OPCOES_COORDENACAO__
    </select><br>

    <label>Contato (telefone ou e-mail): <span style="color:red;">*</span></label><br>
    <input type="text" name="contato_solicitante" required style="width:100%; padding:6px; margin-bottom:15px;"><br>

    <h3>Prestadores de serviço</h3>
    <div id="prestadores-container"></div>

    <button type="button" id="btn-adicionar-prestador" class="btn-atalho" style="margin-top:10px;">+ Adicionar prestador</button>

    <br><br>
    <button type="submit" style="padding:10px 20px; background:#2b5876; color:white; border:none; border-radius:4px; cursor:pointer;">Enviar solicitação</button>
</form>

<template id="template-prestador">
    <div class="bloco-prestador bloco" style="margin-bottom:15px;">
        <strong>Prestador <span class="numero-prestador"></span></strong>
        <button type="button" class="btn-excluir btn-remover-prestador" style="float:right; padding:4px 10px;">Remover</button>
        <div style="clear:both;"></div>

        <label>Tipo de prestador: <span style="color:red;">*</span></label><br>
        <select name="tipo_prestador[]" class="campo-tipo-prestador" required style="padding:6px; margin-bottom:10px;">
            <option value="">Selecione</option>
            <option value="PJ">Pessoa Jurídica (PJ)</option>
            <option value="PF">Pessoa Física (PF)</option>
        </select><br>

        <label>Categoria do serviço: <span style="color:red;">*</span></label><br>
        <select name="categoria_servico[]" class="campo-categoria-servico" required style="padding:6px; margin-bottom:10px;">
            <option value="">Selecione</option>
            __OPCOES_TIPOS_SERVICO__
            <option value="Outros">Outros</option>
        </select><br>

        <label>Nome do serviço: <span style="color:red;">*</span></label><br>
        <input type="text" name="nome_servico[]" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>Sugestão de fornecedor (loja), caso houver:</label><br>
        <input type="text" name="fornecedor_sugerido[]" style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>Especificação/Descrição: <span style="color:red;">*</span></label><br>
        <textarea name="especificacao[]" required style="width:100%; padding:6px; margin-bottom:10px;" rows="2"></textarea><br>

        <label>Valor orçado (R$): <span style="color:red;">*</span></label><br>
        <input type="text" class="campo-valor-display" required style="padding:6px; margin-bottom:10px; width:120px;" value="0,00">
        <input type="hidden" name="valor_servico[]" class="campo-valor-hidden" value="0"><br>

        <label>Justificativa da solicitação: <span style="color:red;">*</span></label><br>
        <textarea name="justificativa[]" required style="width:100%; padding:6px; margin-bottom:10px;" rows="2"></textarea><br>

        <div class="campos-pj" style="display:none;">
            <label>Nome da empresa: <span style="color:red;">*</span></label><br>
            <input type="text" name="nome_empresa[]" style="width:100%; padding:6px; margin-bottom:10px;"><br>

            <label>CNPJ: <span style="color:red;">*</span></label><br>
            <input type="text" name="cnpj[]" style="padding:6px; margin-bottom:10px;"><br>
        </div>

        <div class="campos-pf" style="display:none;">
            <label>Nome completo do prestador: <span style="color:red;">*</span></label><br>
            <input type="text" name="nome_prestador[]" style="width:100%; padding:6px; margin-bottom:10px;"><br>

            <label>CPF: <span style="color:red;">*</span></label><br>
            <input type="text" name="cpf_prestador[]" style="padding:6px; margin-bottom:10px;"><br>

            <label>RG, Órgão e Estado de emissão: <span style="color:red;">*</span></label><br>
            <input type="text" name="rg_prestador[]" style="width:100%; padding:6px; margin-bottom:10px;"><br>

            <label>Telefone com DDD: <span style="color:red;">*</span></label><br>
            <input type="text" name="telefone_prestador[]" style="padding:6px; margin-bottom:10px;"><br>

            <label>PIS/NIS: <span style="color:red;">*</span></label><br>
            <input type="text" name="pis_nis[]" style="padding:6px; margin-bottom:10px;"><br>

            <label>Endereço completo (com bairro e CEP): <span style="color:red;">*</span></label><br>
            <input type="text" name="endereco_prestador[]" style="width:100%; padding:6px; margin-bottom:10px;"><br>
        </div>

        <label>Banco: <span style="color:red;">*</span></label><br>
        <input type="text" name="banco[]" style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>Agência: <span style="color:red;">*</span></label><br>
        <input type="text" name="agencia[]" style="padding:6px; margin-bottom:10px; width:150px;"><br>

        <label>Conta: <span style="color:red;">*</span></label><br>
        <input type="text" name="conta[]" style="padding:6px; margin-bottom:10px; width:200px;"><br>

        <label>Chave PIX: <span style="color:red;">*</span></label><br>
        <input type="text" name="chave_pix[]" style="width:100%; padding:6px; margin-bottom:10px;"><br>
    </div>
</template>

<script>
var VALORES_SERVICO = __VALORES_SERVICO__;
var contadorPrestadores = 0;

function criarBlocoPrestador() {
    contadorPrestadores++;
    var template = document.getElementById('template-prestador');
    var clone = template.content.cloneNode(true);

    clone.querySelector('.numero-prestador').textContent = contadorPrestadores;

    var selectTipo = clone.querySelector('.campo-tipo-prestador');
    var selectCategoria = clone.querySelector('.campo-categoria-servico');
    var valorDisplay = clone.querySelector('.campo-valor-display');
    var valorHidden = clone.querySelector('.campo-valor-hidden');
    var blocoPJ = clone.querySelector('.campos-pj');
    var blocoPF = clone.querySelector('.campos-pf');
    var btnRemover = clone.querySelector('.btn-remover-prestador');
    var blocoPrestador = clone.querySelector('.bloco-prestador');

    selectTipo.addEventListener('change', function() {
        if (this.value === 'PJ') {
            blocoPJ.style.display = 'block';
            blocoPF.style.display = 'none';
        } else if (this.value === 'PF') {
            blocoPF.style.display = 'block';
            blocoPJ.style.display = 'none';
        } else {
            blocoPJ.style.display = 'none';
            blocoPF.style.display = 'none';
        }
    });

    selectCategoria.addEventListener('change', function() {
        if (this.value === 'Outros' || this.value === '') {
            valorDisplay.readOnly = false;
            valorDisplay.style.background = 'white';
            valorDisplay.value = '';
            valorHidden.value = '0';
        } else {
            var valor = VALORES_SERVICO[this.value] || 0;
            valorHidden.value = valor.toFixed(2);
            valorDisplay.readOnly = true;
            valorDisplay.style.background = '#f5f5f5';
            valorDisplay.value = valor.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }
    });

    valorDisplay.addEventListener('input', function() {
        if (!this.readOnly) {
            var somenteDigitos = this.value.replace(/\D/g, '');
            if (somenteDigitos === '') {
                valorHidden.value = '0';
                return;
            }
            var valorReais = parseInt(somenteDigitos, 10) / 100;
            valorHidden.value = valorReais.toFixed(2);
            this.value = valorReais.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }
    });

    btnRemover.addEventListener('click', function() {
        blocoPrestador.remove();
    });

    document.getElementById('prestadores-container').appendChild(clone);
}

document.getElementById('btn-adicionar-prestador').addEventListener('click', criarBlocoPrestador);

criarBlocoPrestador();
</script>
"""


@app.route('/solicitacao/servico-externo', methods=['GET', 'POST'])
@login_required
def servico_externo_form():
    if request.method == 'POST':
        tipos = request.form.getlist('tipo_prestador[]')
        categorias = request.form.getlist('categoria_servico[]')
        nomes_servico = request.form.getlist('nome_servico[]')
        fornecedores_sugeridos = request.form.getlist('fornecedor_sugerido[]')
        especificacoes = request.form.getlist('especificacao[]')
        justificativas = request.form.getlist('justificativa[]')
        valores = request.form.getlist('valor_servico[]')
        nomes_empresa = request.form.getlist('nome_empresa[]')
        cnpjs = request.form.getlist('cnpj[]')
        nomes_prestador = request.form.getlist('nome_prestador[]')
        cpfs = request.form.getlist('cpf_prestador[]')
        rgs = request.form.getlist('rg_prestador[]')
        telefones = request.form.getlist('telefone_prestador[]')
        pis_nis_lista = request.form.getlist('pis_nis[]')
        enderecos = request.form.getlist('endereco_prestador[]')
        bancos = request.form.getlist('banco[]')
        agencias = request.form.getlist('agencia[]')
        contas = request.form.getlist('conta[]')
        chaves_pix = request.form.getlist('chave_pix[]')

        valor_total_solicitacao = sum(float(v or 0) for v in valores)

        solicitacao = Solicitacao(
            tipo='servico_externo',
            solicitante_id=current_user.id,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=valor_total_solicitacao,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
        )
        db.session.add(solicitacao)
        db.session.flush()

        for i in range(len(tipos)):
            db.session.add(PrestadorServico(
                solicitacao_id=solicitacao.id,
                tipo_prestador=tipos[i],
                categoria_servico=categorias[i],
                nome_servico=nomes_servico[i] if i < len(nomes_servico) else '',
                fornecedor_sugerido=fornecedores_sugeridos[i] if i < len(fornecedores_sugeridos) else None,
                especificacao=especificacoes[i] if i < len(especificacoes) else '',
                justificativa=justificativas[i] if i < len(justificativas) else '',
                valor_servico=float(valores[i] or 0),
                nome_empresa=nomes_empresa[i] if i < len(nomes_empresa) else None,
                cnpj=cnpjs[i] if i < len(cnpjs) else None,
                nome_prestador=nomes_prestador[i] if i < len(nomes_prestador) else None,
                cpf_prestador=cpfs[i] if i < len(cpfs) else None,
                rg_prestador=rgs[i] if i < len(rgs) else None,
                telefone_prestador=telefones[i] if i < len(telefones) else None,
                pis_nis=pis_nis_lista[i] if i < len(pis_nis_lista) else None,
                endereco_prestador=enderecos[i] if i < len(enderecos) else None,
                banco=bancos[i] if i < len(bancos) else None,
                agencia=agencias[i] if i < len(agencias) else None,
                conta=contas[i] if i < len(contas) else None,
                chave_pix=chaves_pix[i] if i < len(chaves_pix) else None,
            ))

        db.session.commit()
        flash('Solicitação de serviços externos enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    form_html = SERVICO_EXTERNO_FORM_TEMPLATE.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    form_html = form_html.replace('__OPCOES_TIPOS_SERVICO__', montar_opcoes_tipos_servico())
    form_html = form_html.replace('__VALORES_SERVICO__', montar_dict_valores_servico())
    return render_pagina('Solicitação de Serviços Externos', form_html)


# ---------------- CADASTROS: SERVIÇOS EXTERNOS (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/servico-externo')
@login_required
def cadastro_servico_externo():
    somente_organizador()

    tipos = TipoServicoExterno.query.order_by(TipoServicoExterno.nome).all()
    linhas_html = ''
    for tipo in tipos:
        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_servico_externo_atualizar', tipo_id=tipo.id)}" style="display:contents;">
            <td><input type="text" name="nome" value="{tipo.nome}" style="width:280px; padding:4px;"></td>
            <td><input type="number" step="0.01" name="valor" value="{tipo.valor}" style="width:100px; padding:4px;"></td>
            <td>
                <button type="submit" class="btn btn-salvar">Salvar</button>
            </form>
            <form method="POST" action="{url_for('cadastro_servico_externo_excluir', tipo_id=tipo.id)}" style="display:inline;" onsubmit="return confirm('Excluir a categoria {tipo.nome}?');">
                <button type="submit" class="btn btn-excluir">Excluir</button>
            </form>
            </td>
        </tr>
        """

    conteudo = f"""
    <h2>Categorias de Serviço Externo</h2>
    <table>
        <tr><th>Nome</th><th>Valor (R$)</th><th>Ações</th></tr>
        {linhas_html}
    </table>

    <h3 style="margin-top:25px;">Adicionar nova categoria</h3>
    <form method="POST" action="{url_for('cadastro_servico_externo_adicionar')}" style="max-width:400px;">
        <label>Nome da categoria:</label><br>
        <input type="text" name="nome" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <label>Valor (R$):</label><br>
        <input type="number" step="0.01" name="valor" required style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <button type="submit" class="btn btn-adicionar">Adicionar categoria</button>
    </form>
    """
    return render_pagina('Cadastro de Serviços Externos', conteudo)


@app.route('/cadastros/servico-externo/adicionar', methods=['POST'])
@login_required
def cadastro_servico_externo_adicionar():
    somente_organizador()
    nome = request.form.get('nome', '').strip()
    valor = request.form.get('valor')

    if not nome:
        flash('Informe o nome da categoria.')
        return redirect(url_for('cadastro_servico_externo'))

    if TipoServicoExterno.query.filter_by(nome=nome).first():
        flash('Já existe uma categoria com esse nome.')
        return redirect(url_for('cadastro_servico_externo'))

    db.session.add(TipoServicoExterno(nome=nome, valor=valor))
    db.session.commit()
    flash(f'Categoria "{nome}" cadastrada com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_servico_externo'))


@app.route('/cadastros/servico-externo/<int:tipo_id>/atualizar', methods=['POST'])
@login_required
def cadastro_servico_externo_atualizar(tipo_id):
    somente_organizador()
    tipo = TipoServicoExterno.query.get_or_404(tipo_id)
    tipo.nome = request.form.get('nome', '').strip()
    tipo.valor = request.form.get('valor')
    db.session.commit()
    flash('Categoria atualizada com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_servico_externo'))


@app.route('/cadastros/servico-externo/<int:tipo_id>/excluir', methods=['POST'])
@login_required
def cadastro_servico_externo_excluir(tipo_id):
    somente_organizador()
    tipo = TipoServicoExterno.query.get_or_404(tipo_id)
    nome = tipo.nome
    db.session.delete(tipo)
    db.session.commit()
    flash(f'Categoria "{nome}" excluída com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_servico_externo'))


# ---------------- CADASTROS: COORDENAÇÃO (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/coordenacao')
@login_required
def cadastro_coordenacao():
    somente_organizador()

    coordenacoes = Coordenacao.query.order_by(Coordenacao.nome).all()
    linhas_html = ''
    for coord in coordenacoes:
        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_coordenacao_atualizar', coordenacao_id=coord.id)}" style="display:contents;">
            <td><input type="text" name="nome" value="{coord.nome}" style="width:200px; padding:4px;"></td>
            <td>
                <button type="submit" class="btn btn-salvar">Salvar</button>
            </form>
            <form method="POST" action="{url_for('cadastro_coordenacao_excluir', coordenacao_id=coord.id)}" style="display:inline;" onsubmit="return confirm('Excluir a coordenação {coord.nome}?');">
                <button type="submit" class="btn btn-excluir">Excluir</button>
            </form>
            </td>
        </tr>
        """

    conteudo = f"""
    <h2>Coordenações</h2>
    <table>
        <tr><th>Nome</th><th>Ações</th></tr>
        {linhas_html}
    </table>

    <h3 style="margin-top:25px;">Adicionar nova coordenação</h3>
    <form method="POST" action="{url_for('cadastro_coordenacao_adicionar')}" style="max-width:400px;">
        <label>Nome da coordenação:</label><br>
        <input type="text" name="nome" required style="padding:6px; width:100%; margin-bottom:10px;"><br>
        <button type="submit" class="btn btn-adicionar">Adicionar coordenação</button>
    </form>
    """
    return render_pagina('Cadastro de Coordenação', conteudo)


@app.route('/cadastros/coordenacao/adicionar', methods=['POST'])
@login_required
def cadastro_coordenacao_adicionar():
    somente_organizador()
    nome = request.form.get('nome', '').strip()

    if not nome:
        flash('Informe o nome da coordenação.')
        return redirect(url_for('cadastro_coordenacao'))

    if Coordenacao.query.filter_by(nome=nome).first():
        flash('Já existe uma coordenação com esse nome.')
        return redirect(url_for('cadastro_coordenacao'))

    db.session.add(Coordenacao(nome=nome))
    db.session.commit()
    flash(f'Coordenação "{nome}" cadastrada com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_coordenacao'))


@app.route('/cadastros/coordenacao/<int:coordenacao_id>/atualizar', methods=['POST'])
@login_required
def cadastro_coordenacao_atualizar(coordenacao_id):
    somente_organizador()
    coord = Coordenacao.query.get_or_404(coordenacao_id)
    coord.nome = request.form.get('nome', '').strip()
    db.session.commit()
    flash('Coordenação atualizada com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_coordenacao'))


@app.route('/cadastros/coordenacao/<int:coordenacao_id>/excluir', methods=['POST'])
@login_required
def cadastro_coordenacao_excluir(coordenacao_id):
    somente_organizador()
    coord = Coordenacao.query.get_or_404(coordenacao_id)
    nome = coord.nome
    db.session.delete(coord)
    db.session.commit()
    flash(f'Coordenação "{nome}" excluída com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_coordenacao'))


# ---------------- CADASTROS: DIÁRIA (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/diaria')
@login_required
def cadastro_diaria():
    somente_organizador()

    areas = AreaDiaria.query.order_by(AreaDiaria.nome).all()
    linhas_html = ''
    for area in areas:
        valor_cheia = next((v.valor for v in area.valores if v.tipo_diaria == 'Cheia'), 0)
        valor_meia = next((v.valor for v in area.valores if v.tipo_diaria == 'Meia'), 0)
        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_diaria_atualizar_area', area_id=area.id)}" style="display:contents;">
            <td>{area.nome}</td>
            <td><input type="number" step="0.01" name="valor_cheia" value="{valor_cheia}" style="width:90px; padding:4px;"></td>
            <td><input type="number" step="0.01" name="valor_meia" value="{valor_meia}" style="width:90px; padding:4px;"></td>
            <td>
                <button type="submit" class="btn btn-salvar">Salvar</button>
            </form>
            <form method="POST" action="{url_for('cadastro_diaria_excluir_area', area_id=area.id)}" style="display:inline;" onsubmit="return confirm('Excluir a área {area.nome}? Isso remove os valores cadastrados dela.');">
                <button type="submit" class="btn btn-excluir">Excluir</button>
            </form>
            </td>
        </tr>
        """

    valor_auxilio_atual = obter_configuracao(CHAVE_VALOR_AUXILIO, VALOR_AUXILIO_PADRAO)

    conteudo = f"""
    <h2>Áreas e valores de Diária</h2>
    <table>
        <tr><th>Área</th><th>Valor Cheia (R$)</th><th>Valor Meia (R$)</th><th>Ações</th></tr>
        {linhas_html}
    </table>

    <h3 style="margin-top:25px;">Adicionar nova área</h3>
    <form method="POST" action="{url_for('cadastro_diaria_adicionar_area')}" style="max-width:500px;">
        <label>Nome da área:</label><br>
        <input type="text" name="nome" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <label>Valor Diária Cheia (R$):</label><br>
        <input type="number" step="0.01" name="valor_cheia" required style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <label>Valor Diária Meia (R$):</label><br>
        <input type="number" step="0.01" name="valor_meia" required style="padding:6px; width:150px; margin-bottom:15px;"><br>

        <button type="submit" class="btn btn-adicionar">Adicionar área</button>
    </form>

    <h2 style="margin-top:30px;">Valor do Auxílio Deslocamento</h2>
    <form method="POST" action="{url_for('cadastro_diaria_atualizar_auxilio')}">
        <label>Valor por auxílio (R$):</label><br>
        <input type="number" step="0.01" name="valor_auxilio" value="{valor_auxilio_atual}" style="padding:6px; width:150px; margin-bottom:10px;"><br>
        <button type="submit" class="btn btn-salvar">Salvar</button>
    </form>
    """
    return render_pagina('Cadastro de Diária', conteudo)


@app.route('/cadastros/diaria/areas/adicionar', methods=['POST'])
@login_required
def cadastro_diaria_adicionar_area():
    somente_organizador()
    nome = request.form.get('nome', '').strip()
    valor_cheia = request.form.get('valor_cheia')
    valor_meia = request.form.get('valor_meia')

    if not nome:
        flash('Informe o nome da área.')
        return redirect(url_for('cadastro_diaria'))

    if AreaDiaria.query.filter_by(nome=nome).first():
        flash('Já existe uma área com esse nome.')
        return redirect(url_for('cadastro_diaria'))

    area = AreaDiaria(nome=nome)
    db.session.add(area)
    db.session.flush()
    db.session.add(ValorDiaria(area_id=area.id, tipo_diaria='Cheia', valor=valor_cheia))
    db.session.add(ValorDiaria(area_id=area.id, tipo_diaria='Meia', valor=valor_meia))
    db.session.commit()
    flash(f'Área "{nome}" cadastrada com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_diaria'))


@app.route('/cadastros/diaria/areas/<int:area_id>/atualizar', methods=['POST'])
@login_required
def cadastro_diaria_atualizar_area(area_id):
    somente_organizador()
    area = AreaDiaria.query.get_or_404(area_id)
    valor_cheia = request.form.get('valor_cheia')
    valor_meia = request.form.get('valor_meia')

    registro_cheia = ValorDiaria.query.filter_by(area_id=area.id, tipo_diaria='Cheia').first()
    if registro_cheia:
        registro_cheia.valor = valor_cheia
    else:
        db.session.add(ValorDiaria(area_id=area.id, tipo_diaria='Cheia', valor=valor_cheia))

    registro_meia = ValorDiaria.query.filter_by(area_id=area.id, tipo_diaria='Meia').first()
    if registro_meia:
        registro_meia.valor = valor_meia
    else:
        db.session.add(ValorDiaria(area_id=area.id, tipo_diaria='Meia', valor=valor_meia))

    db.session.commit()
    flash(f'Valores da área "{area.nome}" atualizados com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_diaria'))


@app.route('/cadastros/diaria/areas/<int:area_id>/excluir', methods=['POST'])
@login_required
def cadastro_diaria_excluir_area(area_id):
    somente_organizador()
    area = AreaDiaria.query.get_or_404(area_id)
    nome = area.nome
    db.session.delete(area)
    db.session.commit()
    flash(f'Área "{nome}" excluída com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_diaria'))


@app.route('/cadastros/diaria/auxilio/atualizar', methods=['POST'])
@login_required
def cadastro_diaria_atualizar_auxilio():
    somente_organizador()
    novo_valor = request.form.get('valor_auxilio')
    registro_config = Configuracao.query.filter_by(chave=CHAVE_VALOR_AUXILIO).first()
    if registro_config:
        registro_config.valor = novo_valor
    else:
        db.session.add(Configuracao(chave=CHAVE_VALOR_AUXILIO, valor=novo_valor))
    db.session.commit()
    flash('Valor do auxílio deslocamento atualizado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_diaria'))


def seed_dados_iniciais():
    for nome_area, valores in AREAS_PADRAO.items():
        area = AreaDiaria.query.filter_by(nome=nome_area).first()
        if not area:
            area = AreaDiaria(nome=nome_area)
            db.session.add(area)
            db.session.flush()
        for tipo_diaria, valor in valores.items():
            existe = ValorDiaria.query.filter_by(area_id=area.id, tipo_diaria=tipo_diaria).first()
            if not existe:
                db.session.add(ValorDiaria(area_id=area.id, tipo_diaria=tipo_diaria, valor=valor))

    existe_config = Configuracao.query.filter_by(chave=CHAVE_VALOR_AUXILIO).first()
    if not existe_config:
        db.session.add(Configuracao(chave=CHAVE_VALOR_AUXILIO, valor=VALOR_AUXILIO_PADRAO))

    db.session.commit()


COORDENACOES_PADRAO = ['CLIC', 'CCOTeM', 'COUP', 'COLMOP', 'CGSA', 'CG', 'COPS', 'COP']

TIPOS_ALIMENTACAO_PADRAO = {
    'Coffee Break': 13,
    'Kit lanche': 12,
    'Almoço marmita': 25,
    'Almoço PF': 25,
}

TIPOS_VEICULO_PADRAO = {
    'Ônibus': {'valor_km': 13, 'assentos': 45},
    'Microônibus': {'valor_km': 12, 'assentos': 32},
}

TIPOS_SERVICO_EXTERNO_PADRAO = {
    'Auxiliar de campo': 100,
    'Auxiliar de campo/condutor veícular': 150,
    'Mateiro': 100,
    'Monitor (a)': 200,
    'Cozinheiro (a)': 150,
}


def seed_coordenacoes():
    for nome in COORDENACOES_PADRAO:
        if not Coordenacao.query.filter_by(nome=nome).first():
            db.session.add(Coordenacao(nome=nome))
    db.session.commit()


def seed_tipos_alimentacao():
    for nome, valor in TIPOS_ALIMENTACAO_PADRAO.items():
        if not TipoAlimentacao.query.filter_by(nome=nome).first():
            db.session.add(TipoAlimentacao(nome=nome, valor=valor))
    db.session.commit()


def seed_tipos_veiculo():
    for nome, dados in TIPOS_VEICULO_PADRAO.items():
        if not TipoVeiculo.query.filter_by(nome=nome).first():
            db.session.add(TipoVeiculo(nome=nome, valor_km=dados['valor_km'], quantidade_assentos=dados['assentos']))
    db.session.commit()


def seed_tipos_servico_externo():
    for nome, valor in TIPOS_SERVICO_EXTERNO_PADRAO.items():
        if not TipoServicoExterno.query.filter_by(nome=nome).first():
            db.session.add(TipoServicoExterno(nome=nome, valor=valor))
    db.session.commit()


def seed_admin():
    if not Usuario.query.filter_by(email='admin@ngi.com').first():
        admin = Usuario(nome='Admin', email='admin@ngi.com', is_organizador=True)
        admin.set_senha('sigad2026')
        db.session.add(admin)
        db.session.commit()


if os.environ.get('DATABASE_URL'):
    with app.app_context():
        db.drop_all()
        db.create_all()
        seed_dados_iniciais()
        seed_coordenacoes()
        seed_tipos_alimentacao()
        seed_tipos_veiculo()
        seed_tipos_servico_externo()
        seed_admin()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
