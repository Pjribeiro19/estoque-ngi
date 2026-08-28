# VERSAO-SIGAD-CARAJAS: 2026-08-27-SEGURO-FIX-04 (se voce ve isso no GitHub, esta versao esta certa)
import os
import re
import secrets
import string
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, render_template_string, redirect, url_for, request, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect as sa_inspect, text as sa_text
from sqlalchemy.orm import joinedload
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.datastructures import MultiDict
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

# ---------------- FUSO HORÁRIO ----------------
# Todo o sistema opera no horário de Brasília / Pará (UTC-3).
FUSO_BRASIL = ZoneInfo(os.environ.get('TIMEZONE', 'America/Belem'))


def agora():
    """Data e hora atual no fuso local, sem tzinfo (compatível com as colunas existentes)."""
    return datetime.now(FUSO_BRASIL).replace(tzinfo=None)


def hoje():
    """Data de hoje no fuso local."""
    return datetime.now(FUSO_BRASIL).date()


app = Flask(__name__)
# garante que os links gerados (ex: e-mail de boas-vindas) usem https, mesmo
# quando o Railway repassa a requisição internamente sem deixar isso claro
app.config['PREFERRED_URL_SCHEME'] = 'https'
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chave-temporaria-trocar-depois')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,          # conexões mantidas abertas
    'max_overflow': 20,       # conexões extras em pico de acesso
    'pool_recycle': 280,      # recicla antes do timeout do Supabase
    'pool_pre_ping': True,    # descarta conexões mortas antes de usar
}

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Sua sessão expirou ou você precisa entrar para acessar esta página.'
login_manager.login_message_category = 'aviso_sessao'

TIPOS_DIARIA = ['Cheia', 'Meia']
TIPOS_TRANSPORTE = ['Avião', 'Ônibus']
COMPANHIAS_AEREAS = ['Azul', 'Gol', 'Latam', 'Voepass', 'Outra']

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
    'enviado_pagamento': 'Enviado para pagamento',
    'paga': 'Paga / Concluída',
    'em_compra': 'Em compra',
    'comprado': 'Comprado / Concluída',
    'reprovada': 'Reprovada',
    'ajuste_dados': 'Devolvida para correção de dados',
    'cancelada': 'Cancelada (substituída após correção)',
}

CONVENIOS = ['GLOBAL', 'HORIZONTES', 'ZONEAMENTO', 'ARPA']

# o seguro viagem só tem cobertura a partir desta distância
KM_MINIMO_SEGURO = 50

# Define como o Executor conduz cada tipo de demanda até a conclusão:
#   'pagamento' -> Em execução > Enviado para pagamento > Paga
#   'compra'    -> Em execução > Em compra > Comprado
FLUXO_POR_TIPO = {
    'diaria': 'pagamento',
    'bolsa': 'pagamento',
    'servico_externo': 'pagamento',
    'servico_externo_pf': 'pagamento',
    'servico_externo_pj': 'pagamento',
    'passagem': 'compra',
    'compra_materiais': 'compra',
    'rancho': 'compra',
    'alimentacao': 'compra',
    'locacao_veiculo': 'compra',
    'seguro': 'compra',
}


def formatar_cpf(valor):
    """Devolve o CPF no formato 000.000.000-00, ou o valor original se não tiver 11 dígitos."""
    digitos = ''.join(c for c in (valor or '') if c.isdigit())
    if len(digitos) != 11:
        return valor or ''
    return f'{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}'


def formatar_cnpj(valor):
    digitos = ''.join(c for c in (valor or '') if c.isdigit())
    if len(digitos) != 14:
        return valor or ''
    return f'{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}'


def montar_telefone(ddd, numero):
    """Junta DDD e número no formato (96) 99999-9999. Devolve (ok, texto)."""
    d = ''.join(c for c in (ddd or '') if c.isdigit())
    n = ''.join(c for c in (numero or '') if c.isdigit())

    if len(d) != 2 or len(n) not in (8, 9):
        return (False, '')

    if len(n) == 9:
        return (True, f'({d}) {n[:5]}-{n[5:]}')
    return (True, f'({d}) {n[:4]}-{n[4:]}')


def separar_telefone(texto_formatado):
    """Desfaz montar_telefone(): de '(96) 99999-9999' devolve (ddd, numero),
    para reapresentar num formulário de correção."""
    digitos = ''.join(c for c in (texto_formatado or '') if c.isdigit())
    if len(digitos) < 10:
        return ('', '')
    return (digitos[:2], digitos[2:])


def cpf_tem_11_digitos(valor):
    return len(''.join(c for c in (valor or '') if c.isdigit())) == 11


def cnpj_tem_14_digitos(valor):
    return len(''.join(c for c in (valor or '') if c.isdigit())) == 14


def moeda(valor):
    texto = f'{float(valor or 0):,.2f}'
    return 'R$ ' + texto.replace(',', 'X').replace('.', ',').replace('X', '.')


def protocolo(solicitacao):
    """Protocolo institucional no formato AAAA.MMDD.NNNNN-D

    AAAA  ano de abertura
    MMDD  mês e dia de abertura
    NNNNN sequencial da solicitação
    D     dígito verificador (módulo 11)
    """
    data = solicitacao.data_envio or agora()
    base = f'{data.year}{data.month:02d}{data.day:02d}{solicitacao.id:05d}'

    soma = 0
    peso = 2
    for digito in reversed(base):
        soma += int(digito) * peso
        peso = 2 if peso == 9 else peso + 1

    resto = soma % 11
    verificador = 0 if resto in (0, 1) else 11 - resto

    return f'{data.year}.{data.month:02d}{data.day:02d}.{solicitacao.id:05d}-{verificador}'


def id_a_partir_do_protocolo(texto):
    """O protocolo carrega o próprio ID da solicitação no bloco NNNNN
    (AAAA.MMDD.NNNNN-D), então basta extrair esses 5 dígitos - não é
    preciso computar o protocolo de cada linha do banco para buscar.
    Aceita o protocolo completo, colado sem pontuação, ou só o ID."""
    digitos = re.sub(r'\D', '', texto or '')
    if len(digitos) >= 13:
        candidato = digitos[8:13]
    elif len(digitos) == 5:
        candidato = digitos
    else:
        return None
    try:
        return int(candidato)
    except ValueError:
        return None


def fluxo_do_tipo(tipo):
    return FLUXO_POR_TIPO.get(tipo, 'pagamento')

TIPO_SOLICITACAO_LABELS = {
    'diaria': 'Diária',
    'passagem': 'Passagem',
    'compra_materiais': 'Compra de Materiais',
    'alimentacao': 'Alimentação',
    'locacao_veiculo': 'Locação de Veículo',
    'servico_externo': 'Serviços Externos',
    'servico_externo_pf': 'Serviço Externo PF',
    'servico_externo_pj': 'Serviço Externo PJ',
    'rancho': 'Rancho',
    'seguro': 'Seguro',
    'bolsa': 'Bolsa',
}


def enviar_email(destinatario, assunto, corpo, anexo_nome=None, anexo_bytes=None,
                  anexo_tipo='application/pdf'):
    """Envia e-mail por SMTP. Retorna (sucesso, mensagem) para diagnóstico.

    Se anexo_nome e anexo_bytes forem informados, o e-mail sai como
    multipart/mixed com o arquivo anexado - usado, por exemplo, para enviar
    o PDF da bolsa ao CTC. Sem esses parâmetros, comporta-se exatamente como
    antes: um e-mail de texto simples."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.mime.application import MIMEApplication
    from email.utils import formataddr, parseaddr

    host = os.environ.get('EMAIL_HOST')
    porta = int(os.environ.get('EMAIL_PORT') or 587)
    usuario_smtp = os.environ.get('EMAIL_USER')
    senha_smtp = os.environ.get('EMAIL_PASSWORD')
    remetente_bruto = os.environ.get('EMAIL_FROM') or usuario_smtp
    nome_remetente = os.environ.get('EMAIL_FROM_NAME', 'SIGAD Carajás')

    if not host or not usuario_smtp or not senha_smtp or not remetente_bruto:
        return (False, 'Configuração de e-mail ausente. Defina EMAIL_HOST, EMAIL_PORT, '
                       'EMAIL_USER, EMAIL_PASSWORD e EMAIL_FROM nas variáveis de ambiente.')

    # aceita tanto "email@dominio" quanto "Nome <email@dominio>"
    _nome_extraido, endereco_remetente = parseaddr(remetente_bruto)
    if not endereco_remetente:
        return (False, f'EMAIL_FROM inválido: {remetente_bruto}')

    try:
        if anexo_nome and anexo_bytes:
            mensagem = MIMEMultipart()
            mensagem.attach(MIMEText(corpo, 'plain', 'utf-8'))
            parte = MIMEApplication(anexo_bytes, _subtype=anexo_tipo.split('/')[-1])
            parte.add_header('Content-Disposition', 'attachment', filename=anexo_nome)
            mensagem.attach(parte)
        else:
            mensagem = MIMEText(corpo, 'plain', 'utf-8')

        mensagem['Subject'] = assunto
        mensagem['From'] = formataddr((nome_remetente, endereco_remetente))
        mensagem['To'] = destinatario
        mensagem['Reply-To'] = endereco_remetente

        # portas 465 e 2465 usam SSL direto; as demais usam STARTTLS
        if porta in (465, 2465):
            with smtplib.SMTP_SSL(host, porta, timeout=20) as servidor:
                servidor.login(usuario_smtp, senha_smtp)
                servidor.sendmail(endereco_remetente, [destinatario], mensagem.as_string())
        else:
            with smtplib.SMTP(host, porta, timeout=20) as servidor:
                servidor.starttls()
                servidor.login(usuario_smtp, senha_smtp)
                servidor.sendmail(endereco_remetente, [destinatario], mensagem.as_string())

        return (True, 'E-mail enviado com sucesso.')

    except Exception as erro:
        detalhe = f'{type(erro).__name__}: {erro}'
        print(f'[email] FALHA ao enviar para {destinatario} - {detalhe}')
        return (False, detalhe)


# ---------------- ARMAZENAMENTO DE ARQUIVOS (SUPABASE STORAGE) ----------------
# Quando as variáveis abaixo estiverem configuradas, os anexos são gravados no
# Supabase Storage e o banco guarda apenas o caminho do arquivo.
# Sem elas, o sistema continua gravando o arquivo dentro do banco, como antes.
SUPABASE_URL = (os.environ.get('SUPABASE_URL') or '').rstrip('/')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')
BUCKET_ANEXOS = os.environ.get('SUPABASE_BUCKET', 'anexos')


def storage_disponivel():
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def _requisicao_storage(caminho, metodo='GET', dados=None, tipo_conteudo=None):
    """Chama a API de Storage do Supabase usando apenas a biblioteca padrão."""
    import urllib.request
    import urllib.error

    url = f'{SUPABASE_URL}/storage/v1/object/{BUCKET_ANEXOS}/{caminho}'
    cabecalhos = {
        'Authorization': f'Bearer {SUPABASE_SERVICE_KEY}',
        'apikey': SUPABASE_SERVICE_KEY,
    }
    if tipo_conteudo:
        cabecalhos['Content-Type'] = tipo_conteudo
        cabecalhos['x-upsert'] = 'true'

    requisicao = urllib.request.Request(url, data=dados, headers=cabecalhos, method=metodo)

    try:
        with urllib.request.urlopen(requisicao, timeout=30) as resposta:
            return (True, resposta.read())
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode('utf-8', errors='ignore')[:300]
        return (False, f'HTTP {erro.code}: {detalhe}')
    except Exception as erro:
        return (False, f'{type(erro).__name__}: {erro}')


def enviar_para_storage(caminho, conteudo, tipo_conteudo):
    return _requisicao_storage(caminho, 'POST', conteudo, tipo_conteudo or 'application/octet-stream')


def baixar_do_storage(caminho):
    return _requisicao_storage(caminho, 'GET')


def remover_do_storage(caminho):
    return _requisicao_storage(caminho, 'DELETE')


def montar_caminho_anexo(solicitacao_id, nome_arquivo):
    """Gera um caminho único e seguro dentro do bucket."""
    import re
    import uuid

    nome_limpo = re.sub(r'[^A-Za-z0-9._-]', '_', nome_arquivo or 'arquivo')[-80:]
    return f'solicitacao-{solicitacao_id}/{uuid.uuid4().hex[:12]}_{nome_limpo}'


def salvar_anexo(solicitacao_id, arquivo, tipo_anexo='geral'):
    """Grava um anexo no Storage (ou no banco, se o Storage não estiver configurado).

    Devolve (sucesso, mensagem). O registro é adicionado à sessão, sem commit."""
    if not arquivo or not arquivo.filename:
        return (False, 'Nenhum arquivo enviado.')

    conteudo = arquivo.read()

    registro = Anexo(
        solicitacao_id=solicitacao_id,
        nome_arquivo=arquivo.filename,
        tipo_conteudo=arquivo.content_type,
        tipo_anexo=tipo_anexo,
    )

    if storage_disponivel():
        caminho = montar_caminho_anexo(solicitacao_id, arquivo.filename)
        enviado, detalhe = enviar_para_storage(caminho, conteudo, arquivo.content_type)

        if enviado:
            registro.caminho_storage = caminho
            registro.dados = None
            db.session.add(registro)
            return (True, 'Arquivo enviado ao Storage.')

        # se o Storage falhar, grava no banco para não perder o arquivo
        print(f'[storage] falha ao enviar {caminho}: {detalhe} - gravando no banco')

    registro.dados = conteudo
    db.session.add(registro)
    return (True, 'Arquivo gravado no banco de dados.')


def ler_anexo(anexo):
    """Devolve o conteúdo do anexo, venha ele do Storage ou do banco."""
    if anexo.caminho_storage:
        ok, resultado = baixar_do_storage(anexo.caminho_storage)
        if ok:
            return resultado
        print(f'[storage] falha ao baixar {anexo.caminho_storage}: {resultado}')
        return None
    return anexo.dados


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

# ISS (Imposto Sobre Serviços) retido sobre a prestação de serviço PF,
# conforme alíquota do município - editável em Cadastros, sem redeploy
CHAVE_ALIQUOTA_ISS = 'aliquota_iss_servico_pf'
ALIQUOTA_ISS_PADRAO = 5.0

# Travamento geral de novas solicitações, para respeitar o prazo semanal de
# envio antes da reunião de lotes. Ativado/desativado manualmente pelo
# Analista ou Administrador - não tem religamento automático por horário,
# porque o dia útil seguinte varia (feriados, etc.).
CHAVE_SOLICITACOES_TRAVADAS = 'solicitacoes_travadas'
CHAVE_MENSAGEM_TRAVAMENTO = 'mensagem_travamento_solicitacoes'
MENSAGEM_TRAVAMENTO_PADRAO = (
    'O prazo para envio de solicitações para a próxima reunião de lotes expirou às 12h de quarta-feira. '
    'As solicitações serão reabertas no próximo dia útil.'
)

# número de WhatsApp do suporte, exibido na Central de Ajuda - editável em
# Cadastros, sem redeploy. Formato esperado: só dígitos, com DDI+DDD
# (ex: 5594999998888 para +55 94 99999-8888)
CHAVE_WHATSAPP_AJUDA = 'whatsapp_ajuda'


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
    coordenacao_id = db.Column(db.Integer, db.ForeignKey('coordenacoes.id'))
    token_senha = db.Column(db.String(120))
    token_expira = db.Column(db.DateTime)
    trocar_senha = db.Column(db.Boolean, default=False)

    coordenacao = db.relationship('Coordenacao', foreign_keys=[coordenacao_id])

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)


class Coordenacao(db.Model):
    __tablename__ = 'coordenacoes'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True, nullable=False)


class Atividade(db.Model):
    """Agrupador de solicitações da mesma atividade de campo - ex: uma
    expedição que precisa de diária, passagem e compra de materiais juntas.
    Cada solicitação vinculada continua seguindo seu próprio fluxo normal de
    aprovação; o agrupamento é só para consulta e organização."""
    __tablename__ = 'atividades'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(300), nullable=False)
    descricao = db.Column(db.Text)
    criado_por_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    coordenacao_id = db.Column(db.Integer, db.ForeignKey('coordenacoes.id'))
    criado_em = db.Column(db.DateTime, default=agora)

    criado_por = db.relationship('Usuario', foreign_keys=[criado_por_id])
    coordenacao = db.relationship('Coordenacao', foreign_keys=[coordenacao_id])


class Solicitacao(db.Model):
    __tablename__ = 'solicitacoes'
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False)
    solicitante_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    atividade_id = db.Column(db.Integer, db.ForeignKey('atividades.id'))
    data_envio = db.Column(db.DateTime, default=agora)
    ponto_focal = db.Column(db.String(200))
    atividade_projeto = db.Column(db.String(300))
    status = db.Column(db.String(30), default='pendente_analise')
    convenio = db.Column(db.String(200))
    observacao = db.Column(db.Text)
    valor_total = db.Column(db.Numeric(12, 2), default=0)
    coordenacao_solicitante_id = db.Column(db.Integer, db.ForeignKey('coordenacoes.id'))
    contato_solicitante = db.Column(db.String(200))
    lote_aprovacao = db.Column(db.String(100))
    rubrica = db.Column(db.String(200))
    motivo_reprovacao = db.Column(db.Text)
    ressalva_analista = db.Column(db.Text)
    ressalva_aprovador = db.Column(db.Text)
    reprovada_por = db.Column(db.String(200))
    responsavel_encaminhamento_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    email_ctc = db.Column(db.String(200))
    prazo_encaminhamento = db.Column(db.Date)
    data_envio_pagamento = db.Column(db.Date)
    data_pagamento = db.Column(db.Date)
    aviso_conclusao = db.Column(db.Text)
    prestacao_contas_entregue = db.Column(db.Boolean, default=False)
    data_prestacao_contas = db.Column(db.Date)
    alerta_prestacao = db.Column(db.Text)
    relatorio_em_conferencia = db.Column(db.Boolean, default=False)
    data_relatorio_enviado = db.Column(db.Date)
    motivo_recusa_prestacao = db.Column(db.Text)
    prestacao_aprovada_por = db.Column(db.String(200))
    valor_real = db.Column(db.Numeric(12, 2))
    status_antes_ajuste = db.Column(db.String(30))
    motivo_ajuste_dados = db.Column(db.Text)

    # fluxo específico de Serviço Externo PF: boleto de arrecadação municipal
    # emitido pelo prestador após concluir o serviço, pago pelo Executor, e
    # só então o solicitante anexa a nota fiscal para concluir o pagamento
    boleto_vencimento = db.Column(db.Date)
    boleto_informado_em = db.Column(db.DateTime)
    boleto_pago_em = db.Column(db.Date)
    nf_pago_em = db.Column(db.Date)

    # solicitante pede o comprovante de pagamento depois da conclusao, quando
    # o Executor concluiu sem anexar
    comprovante_solicitado_em = db.Column(db.DateTime)
    motivo_devolucao = db.Column(db.Text)
    data_previsao_execucao = db.Column(db.Date)

    solicitante = db.relationship('Usuario', foreign_keys=[solicitante_id])
    atividade = db.relationship('Atividade', foreign_keys=[atividade_id], backref='solicitacoes')
    responsavel_encaminhamento = db.relationship('Usuario', foreign_keys=[responsavel_encaminhamento_id])
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

    # detalhamento misto: parte do período em diária cheia, parte em meia -
    # ex: 3 dias na base (meia) + 2 dias fora (cheia) na mesma viagem
    diaria_detalhada = db.Column(db.Boolean, default=False)
    qtd_diarias_cheias = db.Column(db.Integer, default=0)
    qtd_diarias_meias = db.Column(db.Integer, default=0)
    valor_unitario_cheia = db.Column(db.Numeric(10, 2), default=0)
    valor_unitario_meia = db.Column(db.Numeric(10, 2), default=0)
    # períodos informados pelo solicitante, de onde as quantidades acima são
    # calculadas - guardados para referência/auditoria
    periodo_cheia_inicio = db.Column(db.Date)
    periodo_cheia_fim = db.Column(db.Date)
    periodo_meia_inicio = db.Column(db.Date)
    periodo_meia_fim = db.Column(db.Date)

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
    menor_tarifa_encontrada = db.Column(db.Numeric(10, 2))
    justificativa_tarifa = db.Column(db.Text)

    voo_ida_companhia = db.Column(db.String(60))
    voo_ida_numero = db.Column(db.String(30))
    voo_ida_saida = db.Column(db.DateTime)
    voo_ida_chegada = db.Column(db.DateTime)

    voo_volta_companhia = db.Column(db.String(60))
    voo_volta_numero = db.Column(db.String(30))
    voo_volta_saida = db.Column(db.DateTime)
    voo_volta_chegada = db.Column(db.DateTime)

    observacao_voo = db.Column(db.Text)

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
    # somente PF: dias de atividade e valor diário usados para calcular o
    # subtotal (valor_diario * dias) - ajuda a justificar a decisão.
    # valor_servico passa a ser o TOTAL já com o ISS somado.
    dias_atividade = db.Column(db.Integer)
    valor_diario = db.Column(db.Numeric(10, 2))
    valor_subtotal_servico = db.Column(db.Numeric(10, 2))
    aliquota_iss = db.Column(db.Numeric(5, 2))
    valor_iss = db.Column(db.Numeric(10, 2))

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


CATEGORIAS_RANCHO = [
    'Mantimentos',
    'Temperos/condimentos',
    'Frutas e legumes',
    'Proteínas',
    'Bebidas',
    'Higiene e Limpeza',
]

LOCAIS_ENTREGA_RANCHO = ['Carajás', 'Parauapebas', 'Marabá']


class ItemRancho(db.Model):
    __tablename__ = 'itens_rancho'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), unique=True, nullable=False)
    categoria = db.Column(db.String(50), nullable=False)
    unidade = db.Column(db.String(20), nullable=False)
    fator_consumo = db.Column(db.Numeric(10, 4), default=0)
    valor_unitario = db.Column(db.Numeric(10, 2), default=0)
    ordem = db.Column(db.Integer, default=0)
    # a quais refeições o item se aplica: 'cafe', 'almoco', 'jantar' separados por
    # vírgula, ou 'todas' para itens que não dependem da refeição (ex: sabão, gás)
    refeicoes = db.Column(db.String(40), default='todas')


class SolicitacaoRancho(db.Model):
    __tablename__ = 'solicitacao_ranchos'
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)

    responsavel_retirada = db.Column(db.String(200), nullable=False)
    periodo_atividade = db.Column(db.String(200), nullable=False)
    data_entrega = db.Column(db.Date, nullable=False)
    local_entrega = db.Column(db.String(50), nullable=False)
    num_pessoas = db.Column(db.Integer, nullable=False)
    num_dias = db.Column(db.Integer, nullable=False)
    tipo_refeicao = db.Column(db.String(20), default='todas')

    carne_bifes = db.Column(db.Numeric(10, 2), default=0)
    carne_picada = db.Column(db.Numeric(10, 2), default=0)
    carne_osso = db.Column(db.Numeric(10, 2), default=0)

    agua_mineral_20l = db.Column(db.Integer, default=0)
    justificativa = db.Column(db.Text)
    justificativa_aumento = db.Column(db.Text)
    observacao = db.Column(db.Text)

    solicitacao = db.relationship('Solicitacao', backref='rancho')


class ItemSolicitacaoRancho(db.Model):
    __tablename__ = 'itens_solicitacao_rancho'
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)

    nome_item = db.Column(db.String(150), nullable=False)
    categoria = db.Column(db.String(50))
    unidade = db.Column(db.String(20))
    quantidade = db.Column(db.Numeric(10, 2), nullable=False)
    # quantidade que o sistema sugeriu pelo fator de consumo (POF/IBGE),
    # antes de qualquer ajuste do solicitante - fica nulo para itens
    # adicionais (que não têm fator de consumo, sem sugestão automática)
    quantidade_calculada = db.Column(db.Numeric(10, 2))
    valor_unitario = db.Column(db.Numeric(10, 2), default=0)
    valor_total_item = db.Column(db.Numeric(10, 2), default=0)
    item_adicional = db.Column(db.Boolean, default=False)

    solicitacao = db.relationship('Solicitacao', backref='itens_rancho')


class SolicitacaoSeguro(db.Model):
    __tablename__ = 'solicitacao_seguros'
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)

    quantidade_pessoas = db.Column(db.Integer, nullable=False)
    data_saida = db.Column(db.Date, nullable=False)
    data_retorno = db.Column(db.Date, nullable=False)
    local_origem = db.Column(db.String(300), nullable=False)
    percurso = db.Column(db.String(500), nullable=False)
    local_retorno = db.Column(db.String(300), nullable=False)
    tipo_transporte = db.Column(db.String(200), nullable=False)
    km_estimado = db.Column(db.Numeric(10, 2))
    observacao = db.Column(db.Text)

    solicitacao = db.relationship('Solicitacao', backref='seguro')


class ParticipanteSeguro(db.Model):
    __tablename__ = 'participantes_seguro'
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)

    nome_completo = db.Column(db.String(200), nullable=False)
    data_nascimento = db.Column(db.Date, nullable=False)
    cpf = db.Column(db.String(14), nullable=False)
    rg = db.Column(db.String(20))
    email = db.Column(db.String(200), nullable=False)
    logradouro = db.Column(db.String(300), nullable=False)
    numero = db.Column(db.String(20), nullable=False)
    bairro = db.Column(db.String(150), nullable=False)
    cidade = db.Column(db.String(150), nullable=False)
    uf = db.Column(db.String(2), nullable=False)
    cep = db.Column(db.String(10), nullable=False)
    ddd = db.Column(db.String(3), nullable=False)
    telefone = db.Column(db.String(20), nullable=False)

    solicitacao = db.relationship('Solicitacao', backref='participantes_seguro')


class BolsistaSolicitacao(db.Model):
    __tablename__ = 'bolsistas_solicitacao'
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)

    nome_bolsista = db.Column(db.String(200), nullable=False)
    titulo_plano_trabalho = db.Column(db.String(400), nullable=False)
    projeto_relacionado = db.Column(db.String(300), nullable=False)
    tipo_bolsa = db.Column(db.String(150), nullable=False)
    mes_inicio = db.Column(db.String(7), nullable=False)
    mes_fim = db.Column(db.String(7), nullable=False)
    duracao_meses = db.Column(db.Integer, nullable=False)
    valor_mensal = db.Column(db.Numeric(10, 2), nullable=False)
    valor_total_bolsa = db.Column(db.Numeric(12, 2), nullable=False)
    precisa_cracha = db.Column(db.Boolean, default=False)

    solicitacao = db.relationship('Solicitacao', backref='bolsistas')


class Anexo(db.Model):
    __tablename__ = 'anexos'
    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey('solicitacoes.id'), nullable=False)
    nome_arquivo = db.Column(db.String(300), nullable=False)
    tipo_conteudo = db.Column(db.String(100))
    dados = db.Column(db.LargeBinary)  # usado apenas quando o Storage não está configurado
    data_upload = db.Column(db.DateTime, default=agora)
    tipo_anexo = db.Column(db.String(50), default='geral')
    caminho_storage = db.Column(db.String(500))

    solicitacao = db.relationship('Solicitacao', backref='anexos')


class RegistroAuditoria(db.Model):
    """Histórico imutável de ações relevantes. Só é gravado, nunca editado ou apagado."""
    __tablename__ = 'registros_auditoria'
    id = db.Column(db.Integer, primary_key=True)
    data_hora = db.Column(db.DateTime, default=agora, nullable=False)

    usuario_id = db.Column(db.Integer)
    usuario_nome = db.Column(db.String(200))
    usuario_perfil = db.Column(db.String(40))

    acao = db.Column(db.String(80), nullable=False)
    solicitacao_id = db.Column(db.Integer)
    protocolo = db.Column(db.String(40))
    detalhe = db.Column(db.Text)


ACOES_AUDITORIA = {
    'criou': 'Criou a solicitação',
    'corrigiu': 'Corrigiu e reenviou',
    'enviou_aprovacao': 'Enviou para aprovação',
    'devolveu_analise': 'Devolveu para ajuste (análise)',
    'reprovou_analise': 'Reprovou na análise',
    'aprovou': 'Aprovou',
    'devolveu_aprovacao': 'Devolveu para ajuste (aprovação)',
    'reprovou_aprovacao': 'Reprovou na aprovação',
    'definiu_prazo': 'Definiu o prazo de atendimento',
    'enviou_pagamento': 'Enviou para pagamento',
    'colocou_compra': 'Colocou em compra',
    'marcou_paga': 'Marcou como paga',
    'marcou_comprado': 'Marcou como comprado',
    'devolveu_executor': 'Devolveu para correção de dados',
    'removeu_item': 'Removeu item da solicitação',
    'removeu_anexo': 'Removeu um anexo',
    'informou_boleto': 'Informou vencimento do boleto',
    'pagou_boleto': 'Marcou boleto como pago',
    'enviou_nota_fiscal': 'Enviou a nota fiscal',
    'pagou_nota_fiscal': 'Marcou a nota fiscal como paga',
    'excluiu_usuario': 'Excluiu um usuário',
    'travou_solicitacoes': 'Travou o envio de novas solicitações',
    'destravou_solicitacoes': 'Reabriu o envio de solicitações',
    'solicitou_comprovante': 'Solicitou o comprovante de pagamento',
    'anexou_comprovante': 'Anexou o comprovante de pagamento',
    'enviou_boleto_pagamento': 'Enviou o boleto para pagamento',
    'enviou_nf_pagamento': 'Enviou a nota fiscal para pagamento',
    'alterou_convenio': 'Alterou o convênio',
    'alterou_quantidade_rancho': 'Ajustou quantidade de item do rancho',
    'alterou_quantidade': 'Alterou a quantidade',
    'enviou_relatorio': 'Enviou o relatório de viagem',
    'aprovou_prestacao': 'Aprovou a prestação de contas',
    'devolveu_prestacao': 'Devolveu a prestação de contas',
    'criou_usuario': 'Cadastrou usuário',
    'alterou_usuario': 'Alterou usuário',
    'redefiniu_senha': 'Redefiniu a senha de um usuário',
}


def registrar_auditoria(acao, solicitacao=None, detalhe=''):
    """Grava uma linha no histórico. Nunca interrompe a operação principal."""
    try:
        db.session.add(RegistroAuditoria(
            usuario_id=current_user.id if current_user.is_authenticated else None,
            usuario_nome=current_user.nome if current_user.is_authenticated else 'sistema',
            usuario_perfil=(current_user.perfil if current_user.is_authenticated else None),
            acao=acao,
            solicitacao_id=solicitacao.id if solicitacao else None,
            protocolo=protocolo(solicitacao) if solicitacao else None,
            detalhe=detalhe or None,
        ))
    except Exception as erro:
        print(f'[auditoria] falha ao registrar "{acao}": {erro}')


class Configuracao(db.Model):
    __tablename__ = 'configuracoes'
    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(100), unique=True, nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)


class ConfiguracaoTexto(db.Model):
    """Mesma ideia da Configuracao, mas para valores que não são número -
    como a mensagem exibida quando as solicitações estão travadas."""
    __tablename__ = 'configuracoes_texto'
    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(100), unique=True, nullable=False)
    valor = db.Column(db.Text)


# ---------------- DIAGNÓSTICO TEMPORÁRIO ----------------
# Ativado apenas quando a variável de ambiente MOSTRAR_ERROS=1 existir no Railway.
# Serve para identificar a causa do erro 500 durante os testes. Remova depois.
MOSTRAR_ERROS = os.environ.get('MOSTRAR_ERROS') == '1'


@app.errorhandler(Exception)
def tratar_erro(erro):
    import traceback
    from werkzeug.exceptions import HTTPException

    if isinstance(erro, HTTPException):
        return erro

    rastro = traceback.format_exc()
    print('[ERRO]', rastro)

    if not MOSTRAR_ERROS:
        return ('<h1>Erro interno</h1><p>Ocorreu um erro ao processar sua solicitação. '
                'A equipe técnica foi notificada.</p>'), 500

    return f"""
    <html><head><meta charset="UTF-8"><title>Diagnóstico</title></head>
    <body style="font-family:monospace; padding:24px; background:#1e1e1e; color:#eee;">
        <h2 style="color:#ff6b6b;">Erro capturado</h2>
        <p style="color:#aaa;">Copie todo o texto abaixo e envie para análise.</p>
        <pre style="background:#111; padding:16px; border-radius:6px; overflow:auto;
                    white-space:pre-wrap; font-size:12.5px;">{rastro}</pre>
    </body></html>
    """, 500


@app.route('/diagnostico')
def diagnostico():
    """Mostra o que o banco tem e o que o código espera."""
    if not MOSTRAR_ERROS:
        abort(404)

    inspetor = sa_inspect(db.engine)
    tabelas_banco = set(inspetor.get_table_names())

    linhas = []
    for tabela in db.metadata.sorted_tables:
        if tabela.name not in tabelas_banco:
            linhas.append(f'<div style="color:#ff6b6b;">TABELA AUSENTE: {tabela.name}</div>')
            continue
        existentes = {c['name'] for c in inspetor.get_columns(tabela.name)}
        faltando = [c.name for c in tabela.columns if c.name not in existentes]
        if faltando:
            linhas.append(f'<div style="color:#ffa94d;">{tabela.name}: FALTAM {", ".join(faltando)}</div>')
        else:
            linhas.append(f'<div style="color:#69db7c;">{tabela.name}: OK</div>')

    return ('<html><head><meta charset="UTF-8"></head>'
            '<body style="font-family:monospace; padding:24px; background:#1e1e1e; color:#eee;">'
            '<h2>Diagnóstico do schema</h2>' + ''.join(linhas) + '</body></html>')


from sqlalchemy import event as sa_event


@sa_event.listens_for(Solicitacao, 'after_insert')
def _auditar_criacao(mapper, conexao, alvo):
    """Registra a criação de qualquer solicitação, seja qual for o módulo."""
    try:
        tipo_label = TIPO_SOLICITACAO_LABELS.get(alvo.tipo, alvo.tipo)
        data = alvo.data_envio or agora()
        base = f'{data.year}{data.month:02d}{data.day:02d}{alvo.id:05d}'
        soma, peso = 0, 2
        for digito in reversed(base):
            soma += int(digito) * peso
            peso = 2 if peso == 9 else peso + 1
        resto = soma % 11
        verificador = 0 if resto in (0, 1) else 11 - resto
        numero = f'{data.year}.{data.month:02d}{data.day:02d}.{alvo.id:05d}-{verificador}'

        conexao.execute(RegistroAuditoria.__table__.insert().values(
            data_hora=agora(),
            usuario_id=current_user.id if current_user.is_authenticated else None,
            usuario_nome=current_user.nome if current_user.is_authenticated else 'sistema',
            usuario_perfil=current_user.perfil if current_user.is_authenticated else None,
            acao='criou',
            solicitacao_id=alvo.id,
            protocolo=numero,
            detalhe=f'{tipo_label} | valor estimado R$ {float(alvo.valor_total or 0):.2f}',
        ))
    except Exception as erro:
        print(f'[auditoria] falha ao registrar criacao: {erro}')


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


def obter_configuracao_texto(chave, padrao=''):
    registro = ConfiguracaoTexto.query.filter_by(chave=chave).first()
    return registro.valor if registro and registro.valor else padrao


def solicitacoes_estao_travadas():
    return obter_configuracao(CHAVE_SOLICITACOES_TRAVADAS, 0) == 1


def mensagem_travamento():
    return obter_configuracao_texto(CHAVE_MENSAGEM_TRAVAMENTO, MENSAGEM_TRAVAMENTO_PADRAO)


def com_vinculo_atividade(form_html):
    """Se a URL trouxer ?atividade_id=, injeta um campo oculto no formulário
    (pra ir junto no POST) e um aviso visual - sem precisar editar os 10
    templates de formulário individualmente."""
    atividade_id = request.args.get('atividade_id')
    if not atividade_id:
        return form_html

    atividade = Atividade.query.get(atividade_id)
    if not atividade:
        return form_html

    aviso = (
        f'<div class="bloco" style="border-left:4px solid #37784D; background:#eef5ee; '
        f'max-width:700px; margin-bottom:14px;">'
        f'<strong style="color:#004622;">Vinculada à atividade: {atividade.nome}</strong>'
        f'</div>'
    )
    campo_oculto = f'<input type="hidden" name="atividade_id" value="{atividade.id}">'

    form_html = re.sub(
        r'(<form method="POST"[^>]*>)',
        r'\1' + campo_oculto, form_html, count=1,
    )
    return aviso + form_html


def bloquear_se_travado():
    """Barra o acesso a um formulário de NOVA solicitação enquanto o
    travamento semanal estiver ativo. Não afeta solicitações já em
    andamento (correção, anexos, etc.) - só a criação de novas."""
    if solicitacoes_estao_travadas():
        flash(mensagem_travamento())
        return redirect(url_for('inicio'))
    return None


def somente_organizador():
    if not current_user.is_organizador:
        abort(403)


def somente_organizador_ou_analista():
    """Libera as telas de Cadastros operacionais (valores, tabelas de
    referência) também para o Analista, que é quem mais usa esses dados no
    dia a dia. Usuários, E-mail e Armazenamento continuam só para o
    Administrador, por serem configurações sensíveis."""
    if not current_user.is_organizador and current_user.perfil != 'analista':
        abort(403)


def preservar_preenchimento(form_html, dados):
    """Devolve o formulário com os valores já digitados, para que uma falha de
    validação não obrigue o usuário a preencher tudo de novo.

    Formulários com blocos repetíveis (participantes, passageiros, prestadores,
    itens, bolsistas) recriam automaticamente um bloco vazio ao carregar. Um
    sinalizador impede essa criação automática quando há dados a restaurar, e
    o próprio restaurador cria os blocos necessários antes de preencher os
    valores - do contrário, apenas o primeiro item da lista seria recuperado."""
    import json

    simples, listas = {}, {}
    for chave in dados.keys():
        if chave.endswith('[]'):
            listas[chave] = dados.getlist(chave)
        else:
            simples[chave] = dados.get(chave)

    # impede a criação automática do primeiro bloco vazio: o restaurador
    # cuidará de criar exatamente os blocos necessários, mais abaixo
    guarda = '<script>window.__RESTAURAR_FORM__ = true;</script>\n'

    script = """
    <script>
    (function () {
        var valores = __SIMPLES__;
        var listas = __LISTAS__;

        // um bloco repetível é identificado pelo primeiro campo de lista que ele contém
        var GRUPOS = [
            {campo: 'part_nome[]', criar: 'criarBlocoParticipante', bloco: '.bloco-participante'},
            {campo: 'nome_passageiro[]', criar: 'criarPassageiro', bloco: '.bloco-passageiro'},
            {campo: 'item_especificacao[]', criar: 'criarBlocoItem', bloco: '.bloco-item'},
            {campo: 'nome_prestador[]', criar: 'criarPrestadorPF', bloco: '.bloco-prestador'},
            {campo: 'bolsa_nome[]', criar: 'criarBlocoBolsista', bloco: '.bloco-bolsista'},
            {campo: 'nome_diarista[]', criar: 'criarBlocoDiarista', bloco: '.bloco-diarista'},
            {campo: 'adicional_nome[]', criar: 'criarBlocoAdicional', bloco: '.bloco-adicional'}
        ];

        GRUPOS.forEach(function (grupo) {
            var alvo = (listas[grupo.campo] || []).length;
            if (alvo === 0) { return; }
            var existentes = document.querySelectorAll(grupo.bloco).length;
            for (var i = existentes; i < alvo; i++) {
                if (typeof window[grupo.criar] === 'function') {
                    try { window[grupo.criar](); } catch (e) {}
                }
            }
        });

        Object.keys(valores).forEach(function (nome) {
            var campos = document.getElementsByName(nome);
            for (var i = 0; i < campos.length; i++) {
                var campo = campos[i];
                if (campo.type === 'checkbox' || campo.type === 'radio') {
                    campo.checked = (campo.value === valores[nome]);
                } else if (!campo.readOnly) {
                    campo.value = valores[nome];
                }
            }
        });

        Object.keys(listas).forEach(function (nome) {
            var campos = document.getElementsByName(nome);
            for (var i = 0; i < campos.length && i < listas[nome].length; i++) {
                if (!campos[i].readOnly) { campos[i].value = listas[nome][i]; }
            }
        });

        // refaz os cálculos que dependem dos valores restaurados.
        // a ordem importa: primeiro os campos derivados (pernoites, duração),
        // depois os que consultam valores no servidor, que recalculam o total ao responder.
        ['calcularPernoites', 'atualizarBlocoAuxilio', 'atualizarQuantidadeAuxilio',
         'atualizarValorDiaria', 'recalcularTotais', 'renumerarParticipantes',
         'atualizarTotalPassagem', 'atualizarBlocosVolta',
         'calcularTotalCompra', 'atualizarCustos', 'atualizarCustoViagem',
         'atualizarAssentos', 'atualizarTotalPF', 'atualizarTotalGeral',
         'atualizarSubtotais', 'verificarKm', 'verificarAumentoQuantidade',
         'verificarTodasAsTarifas', 'recalcularTodosPrestadoresPF',
         'alternarModoDiaria', 'recalcularTodosBolsistas',
         'verificarPessoasDias', 'sincronizarCalculadoRestaurado'].forEach(function (fn) {
            if (typeof window[fn] === 'function') { try { window[fn](); } catch (e) {} }
        });

        // dispara os eventos dos campos restaurados, para que os cálculos
        // que dependem de "change" também sejam refeitos
        ['tipo_destino', 'tipo_diaria', 'tipo_alimentacao', 'tipo_veiculo',
         'quantidade_pessoas', 'km_estimado', 'forma_entrega'].forEach(function (id) {
            var campo = document.getElementById(id);
            if (campo) { campo.dispatchEvent(new Event('change', { bubbles: true })); }
        });
    })();
    </script>
    """
    script = script.replace('__SIMPLES__', json.dumps(simples, ensure_ascii=False))
    script = script.replace('__LISTAS__', json.dumps(listas, ensure_ascii=False))
    return guarda + form_html + script


def paginar(consulta, ordenacao, rota, por_pagina=50):
    """Aplica paginação a uma consulta e devolve (registros, html_da_navegacao)."""
    try:
        pagina = max(int(request.args.get('pagina', 1)), 1)
    except ValueError:
        pagina = 1

    total = consulta.count()
    total_paginas = max((total + por_pagina - 1) // por_pagina, 1)
    pagina = min(pagina, total_paginas)

    registros = consulta.order_by(ordenacao).limit(por_pagina) \
        .offset((pagina - 1) * por_pagina).all()

    # mesmo com tudo cabendo em uma página só, mostra o total - assim fica
    # claro que a contagem está funcionando, e não que a paginação "sumiu"
    if total_paginas <= 1:
        if total == 0:
            return registros, ''
        navegacao = (f'<div style="margin-top:14px; font-size:12px; color:#666;">'
                     f'{total} registro(s) — cabem todos nesta página '
                     f'(a navegação aparece a partir de {por_pagina + 1} registros).</div>')
        return registros, navegacao

    # preserva os demais filtros da URL (protocolo, lote etc.) ao trocar de página
    outros_parametros = {k: v for k, v in request.args.items() if k != 'pagina'}

    anterior = (f'<a href="{url_for(rota, pagina=pagina - 1, **outros_parametros)}" class="btn-atalho">Anterior</a>'
                if pagina > 1 else '')
    proxima = (f'<a href="{url_for(rota, pagina=pagina + 1, **outros_parametros)}" class="btn-atalho">Próxima</a>'
               if pagina < total_paginas else '')

    navegacao = (f'<div style="margin-top:14px; display:flex; gap:10px; align-items:center;">'
                 f'{anterior}{proxima}<span style="font-size:12px; color:#666;">'
                 f'Página {pagina} de {total_paginas} — {total} registro(s)</span></div>')
    return registros, navegacao


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


def montar_opcoes_executores(selecionado=None):
    usuarios = Usuario.query.filter_by(perfil='comprador').order_by(Usuario.nome).all()
    html = ''
    for u in usuarios:
        sel = 'selected' if str(u.id) == str(selecionado) else ''
        html += f'<option value="{u.id}" {sel}>{u.nome} ({u.email})</option>'
    return html


def tem_demandas_atribuidas():
    if not current_user.is_authenticated:
        return False
    return Solicitacao.query.filter_by(responsavel_encaminhamento_id=current_user.id).count() > 0


def contadores_menu():
    """Quantidades exibidas ao lado dos itens do menu lateral."""
    from datetime import timedelta

    dados = {'analise': 0, 'aprovacao': 0, 'demandas': 0, 'prestacao': 0,
             'minhas': 0, 'minhas_prestacoes': 0}

    if not current_user.is_authenticated:
        return dados

    eh_analista = current_user.perfil == 'analista' or current_user.is_organizador
    eh_aprovador = current_user.perfil == 'aprovador' or current_user.is_organizador
    eh_executor = current_user.perfil == 'comprador' or current_user.is_organizador

    if eh_analista:
        dados['analise'] = Solicitacao.query.filter_by(status='pendente_analise').count()

    if eh_aprovador:
        dados['aprovacao'] = Solicitacao.query.filter_by(status='pendente_aprovacao').count()

    if eh_executor or tem_demandas_atribuidas():
        consulta = Solicitacao.query.filter(
            Solicitacao.status.in_(('aprovada', 'em_execucao', 'enviado_pagamento', 'em_compra'))
        )
        if not current_user.is_organizador:
            consulta = consulta.filter(Solicitacao.responsavel_encaminhamento_id == current_user.id)
        dados['demandas'] = consulta.count()

    if eh_analista or eh_aprovador or eh_executor:
        limite = hoje() - timedelta(days=PRAZO_PRESTACAO_DIAS)
        dados['prestacao'] = db.session.query(Solicitacao).join(
            SolicitacaoDiaria, SolicitacaoDiaria.solicitacao_id == Solicitacao.id
        ).filter(
            Solicitacao.tipo == 'diaria',
            Solicitacao.status.in_(('aprovada', 'em_execucao', 'enviado_pagamento', 'paga')),
            Solicitacao.prestacao_contas_entregue.isnot(True),
            Solicitacao.relatorio_em_conferencia.isnot(True),
            SolicitacaoDiaria.data_retorno < limite,
        ).count()

    # conta apenas o que depende de uma ação do solicitante.
    # reprovada é situação final: não há o que fazer, então não gera alerta.
    dados['minhas'] = Solicitacao.query.filter(
        Solicitacao.solicitante_id == current_user.id,
        Solicitacao.status.in_(('devolvida_ajuste', 'ajuste_dados')),
    ).count()

    # prestações de contas do próprio solicitante ainda em aberto
    dados['minhas_prestacoes'] = db.session.query(Solicitacao).join(
        SolicitacaoDiaria, SolicitacaoDiaria.solicitacao_id == Solicitacao.id
    ).filter(
        Solicitacao.solicitante_id == current_user.id,
        Solicitacao.tipo == 'diaria',
        Solicitacao.status.in_(('aprovada', 'em_execucao', 'enviado_pagamento', 'paga')),
        Solicitacao.prestacao_contas_entregue.isnot(True),
    ).count()

    return dados


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


# ---------------- ÍCONES (SVG colorido inline, sem dependência externa) ----------------
def _icone(interno, tamanho=15):
    return (
        f'<svg viewBox="0 0 24 24" width="{tamanho}" height="{tamanho}" '
        f'style="flex-shrink:0; vertical-align:middle;">{interno}</svg>'
    )


ICONES = {
    # Tela inicial - casa azul com telhado
    'home': _icone(
        '<path d="M12 2 1.5 11h3v10h6v-6h3v6h6V11h3z" fill="#4a90d9"/>'
        '<path d="M9 15h6v6H9z" fill="#f5a623"/>'),

    # Minhas solicitações - documento com linhas
    'lista': _icone(
        '<path d="M5 2h9l5 5v15H5z" fill="#f7f9fa" stroke="#8fa5b5" stroke-width="1"/>'
        '<path d="M14 2v5h5z" fill="#c3d4de"/>'
        '<path d="M8 11h8M8 14.5h8M8 18h5" stroke="#4a90d9" stroke-width="1.5" stroke-linecap="round"/>'),

    # Fila de análise - lupa
    'lupa': _icone(
        '<circle cx="10.5" cy="10.5" r="6.5" fill="#bde3f7" stroke="#3d7fb5" stroke-width="1.8"/>'
        '<path d="m15.5 15.5 5 5" stroke="#8a6d3b" stroke-width="3" stroke-linecap="round"/>'),

    # Fila de aprovação - selo verde de confirmação
    'check': _icone(
        '<circle cx="12" cy="12" r="9.5" fill="#3fa45b"/>'
        '<path d="m7.5 12.3 3 3 6-6.6" stroke="#fff" stroke-width="2.4" fill="none" '
        'stroke-linecap="round" stroke-linejoin="round"/>'),

    # Execução / materiais - caixa
    'caixa': _icone(
        '<path d="M12 2.5 21.5 7v10L12 21.5 2.5 17V7z" fill="#d9a05b"/>'
        '<path d="M2.5 7 12 11.5 21.5 7" fill="none" stroke="#8a5a2b" stroke-width="1.4"/>'
        '<path d="M12 11.5v10" fill="none" stroke="#8a5a2b" stroke-width="1.4"/>'),

    # Grupo Solicitação - pasta
    'pasta': _icone(
        '<path d="M2 6a1.5 1.5 0 0 1 1.5-1.5h5L11 7h9.5A1.5 1.5 0 0 1 22 8.5V18a1.5 1.5 0 0 1-1.5 1.5h-17A1.5 1.5 0 0 1 2 18z" '
        'fill="#f0b429"/>'
        '<path d="M2 9.5h20V18a1.5 1.5 0 0 1-1.5 1.5h-17A1.5 1.5 0 0 1 2 18z" fill="#f7cd63"/>'),

    # Grupo Cadastros - engrenagem
    'engrenagem': _icone(
        '<path d="M12 1.5l1.5 3 3.3-.8.9 3.3 3 1.5-1.7 2.9 1.7 2.9-3 1.5-.9 3.3-3.3-.8L12 22.5l-1.5-3-3.3.8-.9-3.3-3-1.5L5 12.4 3.3 9.5l3-1.5.9-3.3 3.3.8z" '
        'fill="#9aa7b0"/>'
        '<circle cx="12" cy="12" r="3.6" fill="#5b6b76"/>'),

    # Diária - cédula com moeda
    'dinheiro': _icone(
        '<rect x="1.5" y="6" width="21" height="12" rx="1.6" fill="#4caf50"/>'
        '<rect x="3.6" y="8" width="16.8" height="8" rx="1" fill="none" stroke="#c8e6c9" stroke-width="1"/>'
        '<circle cx="12" cy="12" r="3" fill="#f0b429"/>'),

    # Passagem - avião
    'aviao': _icone(
        '<path d="M2 13.6 22 5.5l-3 8.6-4.4 1.2-2.6 5.2-1.9-.5.5-4.2-4.3 1.2z" fill="#4aa8e0"/>'
        '<path d="M22 5.5 11.6 15.3l-.5 4.2" fill="none" stroke="#2b7fb0" stroke-width="1"/>'),

    # Compras - carrinho
    'carrinho': _icone(
        '<path d="M1.5 3h3l2.6 11.3h11l2.4-8.3H6.2" fill="none" stroke="#e07b39" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="9" cy="19.5" r="1.9" fill="#e07b39"/>'
        '<circle cx="17.5" cy="19.5" r="1.9" fill="#e07b39"/>'),

    # Rancho - cesta de compras
    'cesta': _icone(
        '<path d="M3 8.5h18l-1.7 11a1.8 1.8 0 0 1-1.8 1.5H6.5a1.8 1.8 0 0 1-1.8-1.5z" fill="#66bb6a"/>'
        '<path d="M8 8.5 11.5 2M16 8.5 12.5 2" fill="none" stroke="#8a5a2b" stroke-width="1.7" stroke-linecap="round"/>'
        '<path d="M9 12v5.5M15 12v5.5" stroke="#2e7d32" stroke-width="1.5" stroke-linecap="round"/>'),

    # Alimentação - garfo e faca
    'talher': _icone(
        '<path d="M6 2v7.5a2.6 2.6 0 0 0 5.2 0V2" fill="none" stroke="#7f8c8d" stroke-width="1.9" stroke-linecap="round"/>'
        '<path d="M8.6 9.5V22" stroke="#95a5a6" stroke-width="2.2" stroke-linecap="round"/>'
        '<path d="M17.5 2c-1.8 1.3-2.7 3.2-2.7 5.8 0 2.1.9 3.2 2.7 3.7V22" fill="none" stroke="#7f8c8d" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'),

    # Locação de veículos - ônibus
    'onibus': _icone(
        '<rect x="2.5" y="3.5" width="19" height="13" rx="2.2" fill="#3d7fb5"/>'
        '<rect x="4.5" y="6" width="6.2" height="4.4" rx=".7" fill="#bde3f7"/>'
        '<rect x="13.3" y="6" width="6.2" height="4.4" rx=".7" fill="#bde3f7"/>'
        '<circle cx="7" cy="19" r="2.1" fill="#37474f"/><circle cx="17" cy="19" r="2.1" fill="#37474f"/>'
        '<path d="M2.5 13h19" stroke="#f0b429" stroke-width="1.4"/>'),

    # Serviços externos - chave e ferramenta
    'ferramenta': _icone(
        '<path d="M14.6 5.6a4.3 4.3 0 0 0 5.6 5.6L21.5 13 13 21.5l-2.2-2.2L4.4 12.9a4.3 4.3 0 0 1 5.6-5.6z" fill="#e07b39"/>'
        '<path d="M15.5 8.5 8 16" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/>'),

    # Seguro - escudo
    'escudo': _icone(
        '<path d="M12 1.8 3.8 5v6.6c0 5 3.4 9.2 8.2 10.6 4.8-1.4 8.2-5.6 8.2-10.6V5z" fill="#3d7fb5"/>'
        '<path d="m8.2 12 2.8 2.8L16 9.2" stroke="#fff" stroke-width="2.2" fill="none" '
        'stroke-linecap="round" stroke-linejoin="round"/>'),

    # Bolsa - moeda dourada
    'formatura': _icone(
        '<circle cx="12" cy="12" r="9.5" fill="#f0b429"/>'
        '<circle cx="12" cy="12" r="6.8" fill="none" stroke="#c8901a" stroke-width="1.4"/>'
        '<path d="M12 7v10M9.7 9.2h3.8a1.9 1.9 0 0 1 0 3.8h-3a1.9 1.9 0 0 0 0 3.8h3.8" '
        'stroke="#8a5a2b" stroke-width="1.6" fill="none" stroke-linecap="round"/>'),

    # Coordenação / marca - prédio
    'predio': _icone(
        '<rect x="3.5" y="2.5" width="17" height="19" rx="1.2" fill="#8fa5b5"/>'
        '<rect x="6.2" y="5.5" width="3.2" height="3" fill="#e8f1f7"/>'
        '<rect x="11.4" y="5.5" width="3.2" height="3" fill="#e8f1f7"/>'
        '<rect x="16.6" y="5.5" width="1.6" height="3" fill="#e8f1f7"/>'
        '<rect x="6.2" y="10.5" width="3.2" height="3" fill="#e8f1f7"/>'
        '<rect x="11.4" y="10.5" width="3.2" height="3" fill="#e8f1f7"/>'
        '<rect x="16.6" y="10.5" width="1.6" height="3" fill="#e8f1f7"/>'
        '<rect x="9.6" y="16" width="4.8" height="5.5" fill="#5b6b76"/>'),

    # Usuários
    'usuarios': _icone(
        '<circle cx="8.6" cy="8" r="3.6" fill="#e07b39"/>'
        '<path d="M1.8 20.5a6.8 6.8 0 0 1 13.6 0z" fill="#e07b39"/>'
        '<circle cx="17" cy="9" r="3" fill="#4aa8e0"/>'
        '<path d="M13.5 20.5a5.6 5.6 0 0 1 8.7-4.6v4.6z" fill="#4aa8e0"/>'),

    # Prestação de contas - prancheta com check
    'prancheta': _icone(
        '<rect x="4" y="3.5" width="16" height="18" rx="1.8" fill="#f7f9fa" stroke="#8fa5b5" stroke-width="1.1"/>'
        '<rect x="8.5" y="1.8" width="7" height="3.6" rx="1.1" fill="#8fa5b5"/>'
        '<path d="M8 11h8M8 14.5h5" stroke="#8fa5b5" stroke-width="1.4" stroke-linecap="round"/>'
        '<circle cx="16.5" cy="16.5" r="4.4" fill="#3fa45b"/>'
        '<path d="m14.6 16.6 1.4 1.4 2.6-2.9" stroke="#fff" stroke-width="1.6" fill="none" '
        'stroke-linecap="round" stroke-linejoin="round"/>'),

    # Relatórios - gráfico de barras
    'grafico': _icone(
        '<rect x="2.5" y="3" width="19" height="18" rx="1.8" fill="#f7f9fa" stroke="#8fa5b5" stroke-width="1.1"/>'
        '<rect x="6" y="12" width="2.8" height="5.5" fill="#4aa8e0"/>'
        '<rect x="10.6" y="8.5" width="2.8" height="9" fill="#3fa45b"/>'
        '<rect x="15.2" y="10.5" width="2.8" height="7" fill="#f0b429"/>'),

    # Ajuda
    'ajuda': _icone(
        '<circle cx="12" cy="12" r="9.5" fill="#4aa8e0"/>'
        '<path d="M9.3 9.2a2.8 2.8 0 1 1 3.7 2.6c-.7.3-1 .9-1 1.6v.4" stroke="#fff" '
        'stroke-width="2" fill="none" stroke-linecap="round"/>'
        '<circle cx="12" cy="17.2" r="1.3" fill="#fff"/>'),

    # Sair
    'sair': _icone(
        '<path d="M14 3.5h4.5A1.5 1.5 0 0 1 20 5v14a1.5 1.5 0 0 1-1.5 1.5H14" fill="none" '
        'stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>'
        '<path d="M9.5 16.5 14 12 9.5 7.5M14 12H3.5" fill="none" stroke="#fff" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round"/>'),
}


# ---------------- LAYOUT BASE ----------------
BASE_TEMPLATE = """
<!-- VERSAO-SIGAD-CARAJAS: 2026-08-27-SEGURO-FIX-04 -->
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>SIGAD Carajás</title>
    <style>
        :root {
            --menu: #01404F;           /* painel de navegação */
            --menu-topo: #01586C;      /* faixa do logo */
            --verde-escuro: #004622;   /* títulos e textos fortes */
            --verde: #37784D;          /* cabeçalho e botões */
            --verde-medio: #37784D;
            --verde-vivo: #A0C517;     /* acento (uso pontual) */
            --verde-claro: #eef5ee;    /* fundos de seção */
            --verde-borda: #cfe0d3;
            --texto: #23302a;
            --cinza: #67766e;

            /* superfícies: mudam no modo escuro */
            --fundo: #f2f5f3;
            --superficie: #ffffff;
            --superficie-2: #f5f7f5;
            --borda-suave: #e4ebe7;
            --borda-campo: #c3d2c9;
            --texto-suave: #67766e;
            --sombra: rgba(0,0,0,.07);
            --cabecalho-topo: #43885a;
            --grupo-topo: #12707c;
            --grupo-base: #0a5866;
        }
        * { box-sizing: border-box; }
        body {
            font-family: "Segoe UI", Roboto, Arial, sans-serif;
            margin: 0; display: flex; min-height: 100vh;
            background: var(--fundo); color: var(--texto);
        }

        /* ================== MODO ESCURO ==================
           Ativado quando o sistema operacional está em tema escuro.
           Contém SOMENTE cores. Nenhuma regra de posicionamento,
           largura, display ou flex, para não afetar o layout. */
        @media (prefers-color-scheme: dark) {
            :root {
                /* superfícies */
                --fundo: #141a18;
                --superficie: #1d2422;
                --superficie-2: #262e2b;
                --borda-suave: #333c39;
                --borda-campo: #414b47;
                --texto: #e8eeeb;
                --texto-suave: #a7b3ae;
                --sombra: rgba(0,0,0,.5);

                /* tons institucionais recalibrados para fundo escuro */
                --verde-escuro: #9de0b6;
                --verde: #2e6a46;
                --verde-medio: #3a8054;
                --verde-claro: #263029;
                --verde-borda: #3b4741;
                --cabecalho-topo: #35734b;

                --menu: #082830;
                --menu-topo: #0c3a46;
                --grupo-topo: #0d5560;
                --grupo-base: #073e49;
            }

            /* faixas que no tema claro usam degradê claro:
               precisam escurecer, senão o texto verde some no fundo branco */
            h3 {
                background: #29332d !important;
                color: var(--verde-escuro) !important;
                border-color: var(--borda-suave) !important;
                border-left-color: var(--verde-vivo) !important;
            }
            th {
                background: #29332d !important;
                color: var(--verde-escuro) !important;
                border-bottom-color: var(--verde-medio) !important;
            }
            .painel > .titulo {
                background: #29332d !important;
                color: var(--verde-escuro) !important;
                border-bottom-color: var(--borda-suave) !important;
            }
            h2 { color: var(--verde-escuro) !important; }
            label { color: var(--texto) !important; }
            body { color: var(--texto) !important; }
            .valor { color: var(--texto) !important; }
            .rotulo { color: var(--texto-suave) !important; }
            td { color: var(--texto); }

            /* fundos claros escritos direto nos elementos */
            [style*="background:#f5f5f5"], [style*="background: #f5f5f5"],
            [style*="background:#fafafa"], [style*="background:white"],
            [style*="background: white"], [style*="background:#fff"],
            [style*="background:#f0f0f0"] {
                background: var(--superficie-2) !important;
                color: var(--texto) !important;
            }
            [style*="background:#eef5ee"], [style*="background:#e3f3e8"],
            [style*="background:#e8eef3"], [style*="background:#f7faf6"],
            [style*="background:#fff8e6"] {
                background: #28322b !important;
                color: var(--texto) !important;
            }
            [style*="background:#fdeceb"], [style*="background:#fdecec"] {
                background: #3b2422 !important;
            }

            /* textos acinzentados */
            [style*="color:#666"], [style*="color: #666"],
            [style*="color:#888"], [style*="color: #888"],
            [style*="color:#555"], [style*="color: #555"],
            [style*="color:#777"], [style*="color:#3a4a42"],
            [style*="color:#5b6b76"], [style*="color:#7a4a00"],
            [style*="color:#93a39a"], [style*="color:#67766e"] {
                color: var(--texto-suave) !important;
            }

            /* cores de status, clareadas para manter legibilidade */
            [style*="color:#a02020"], [style*="color:#a00"] { color: #ff9d95 !important; }
            [style*="color:#004622"], [style*="color:#0d5c3a"] { color: #9de0b6 !important; }
            [style*="color:#2e7d32"] { color: #75d993 !important; }
            [style*="color:#b35c00"] { color: #f5b264 !important; }
            [style*="color:#c0392b"] { color: #ff9086 !important; }
            [style*="color:#37784D"] { color: #87d3a4 !important; }
            [style*="color:#6a1b9a"] { color: #cea5eb !important; }
            [style*="color:#2b5876"] { color: #90c5e9 !important; }
            [style*="color:#1c4a52"], [style*="color:#22312a"],
            [style*="color:#1f2d26"] { color: var(--texto) !important; }
            [style*="color:#8a5a2b"] { color: #d2a578 !important; }

            /* mensagens */
            .flash { background: #3b2422 !important; color: #ff9d95 !important; }
            .flash-ok { background: #22331f !important; color: #9fe0a0 !important; }

            /* botões de atalho e chips */
            .btn-atalho {
                background: var(--superficie-2) !important; color: #9de0b6 !important;
                border-color: var(--verde-borda) !important;
            }
            .btn-atalho:hover { background: #2f3a35 !important; }
            .chip { background: #141a18 !important; }

            /* campos: faz o navegador desenhar calendário e listas no tema escuro */
            input, select, textarea { color-scheme: dark; }
            input::placeholder, textarea::placeholder { color: #7d8a85; }

            /* links */
            a { color: #87d3a4; }
            table a { color: #90c5e9 !important; }
            nav a, nav .item, nav .grupo, header a, header span { color: #fff !important; }
            nav .submenu a { color: rgba(255,255,255,.82) !important; }
        }

        /* ----- MENU LATERAL ----- */
        nav {
            width: 252px; background: var(--menu); flex-shrink: 0;
            padding-bottom: 24px; color: #fff;
        }
        nav .logo {
            padding: 16px 18px; font-size: 15px; font-weight: 700; letter-spacing: .3px;
            background: linear-gradient(180deg, var(--menu-topo) 0%, var(--menu) 100%);
            color: #fff; display: flex; align-items: center; gap: 10px;
            border-bottom: 3px solid var(--verde-vivo); margin-bottom: 6px;
        }

        /* itens de acesso rápido: lista simples */
        nav .item {
            padding: 10px 16px; display: flex; align-items: center; gap: 9px;
            color: rgba(255,255,255,.92); text-decoration: none; font-size: 13.5px;
            border-left: 3px solid transparent;
            transition: background .15s, border-color .15s;
        }
        nav a.item:hover {
            background: rgba(255,255,255,.11); border-left-color: var(--verde-vivo);
        }

        /* cabeçalhos de grupo: botões, como no sistema de referência */
        nav .grupo {
            margin: 6px 10px 2px; padding: 9px 11px; border-radius: 3px;
            display: flex; align-items: center; gap: 9px;
            background: linear-gradient(180deg, var(--grupo-topo) 0%, var(--grupo-base) 100%);
            border: 1px solid rgba(255,255,255,.18); color: #fff;
            font-size: 11.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .6px;
            cursor: pointer; user-select: none;
            box-shadow: 0 1px 2px rgba(0,0,0,.18);
            transition: filter .15s;
        }
        nav .grupo:hover { filter: brightness(1.18); }
        nav .grupo .seta { margin-left: auto; transition: transform .2s ease; flex-shrink: 0; }
        nav .grupo.aberto .seta { transform: rotate(180deg); }

        nav .grupo svg:not(.seta) { flex-shrink: 0; }

        nav .badge {
            margin-left: auto; background: var(--verde-vivo); color: #22301a;
            font-size: 11px; font-weight: 700; line-height: 1;
            padding: 3px 8px; border-radius: 11px; min-width: 21px; text-align: center;
        }
        nav .badge-alerta { background: #e05252; color: #fff; }

        /* itens dentro dos grupos: lista clara, sem botão */
        nav .submenu { display: none; flex-direction: column; padding: 2px 0 8px; }
        nav .submenu.aberto { display: flex; }
        nav .submenu a {
            padding: 7px 18px 7px 22px; display: flex; align-items: center; gap: 9px;
            color: rgba(255,255,255,.80); text-decoration: none; font-size: 12.5px;
            border-left: 3px solid transparent;
            transition: background .15s, border-color .15s, color .15s;
        }
        nav .submenu a:hover {
            background: rgba(255,255,255,.11); color: #fff; border-left-color: var(--verde-vivo);
        }

        /* ----- CABEÇALHO ----- */
        main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
        header {
            background: linear-gradient(180deg, var(--cabecalho-topo) 0%, var(--verde) 100%);
            color: #fff; padding: 13px 26px;
            border-bottom: 3px solid var(--verde-vivo);
            display: flex; justify-content: space-between; align-items: center;
            box-shadow: 0 1px 4px rgba(0,0,0,.14);
        }
        header h1 { font-size: 16.5px; margin: 0; font-weight: 600; }
        header .usuario { font-size: 13px; display: flex; align-items: center; gap: 14px; }
        header .usuario a {
            color: #fff; text-decoration: none; display: flex; align-items: center; gap: 6px;
            padding: 5px 11px; border: 1px solid rgba(255,255,255,.45); border-radius: 4px;
        }
        header .usuario a:hover { background: rgba(255,255,255,.16); }

        .conteudo { padding: 26px 30px; flex: 1; }
        h2 { font-size: 20px; margin: 0 0 4px; color: var(--verde-escuro); font-weight: 600; }
        h3 {
            font-size: 14px; color: var(--verde-escuro); font-weight: 700;
            margin: 24px 0 12px; padding: 8px 13px;
            background: linear-gradient(180deg, #f7faf6 0%, var(--verde-claro) 100%);
            border: 1px solid var(--verde-borda); border-left: 4px solid var(--verde-vivo);
            border-radius: 4px;
        }
        label { font-size: 12.5px; font-weight: 600; color: #3a4a42; }

        input, select, textarea {
            border: 1px solid var(--borda-campo); border-radius: 4px; font-family: inherit;
            font-size: 13px; background: var(--superficie); color: var(--texto);
        }
        input[readonly], textarea[readonly] { background: var(--superficie-2); }
        input:focus, select:focus, textarea:focus {
            outline: none; border-color: var(--verde-medio);
            box-shadow: 0 0 0 3px rgba(160,197,23,.28);
        }

        /* ----- TABELAS ----- */
        table {
            border-collapse: collapse; width: 100%; max-width: 700px;
            background: var(--superficie); box-shadow: 0 1px 3px var(--sombra);
            border-radius: 5px; overflow: hidden;
        }
        th, td { border-bottom: 1px solid var(--borda-suave); padding: 9px 11px; font-size: 13px; text-align: left; }
        th {
            background: linear-gradient(180deg, #f7faf6 0%, var(--verde-claro) 100%);
            color: var(--verde-escuro); font-weight: 700; font-size: 12.5px;
            border-bottom: 2px solid var(--verde);
        }
        tbody tr:hover, table tr:hover { background: var(--superficie-2); }
        tbody tr[style*="fdeceb"]:hover, table tr[style*="fdeceb"]:hover { background: #fbdedb !important; }

        /* ----- MENSAGENS ----- */
        .flash {
            background: #fdecec; color: #a02020; padding: 11px 15px; border-radius: 5px;
            margin-bottom: 16px; font-size: 13px; border-left: 4px solid #c0392b;
        }
        .flash-ok { background: var(--verde-claro); color: var(--verde-escuro); border-left-color: var(--verde-medio); }

        .bloco {
            border: 1px solid var(--verde-borda); border-radius: 6px; padding: 16px;
            margin-bottom: 15px; background: var(--superficie); box-shadow: 0 1px 3px var(--sombra);
        }

        /* ----- PAINÉIS DE DETALHE ----- */
        .painel {
            background: var(--superficie); border: 1px solid var(--verde-borda); border-radius: 6px;
            margin-bottom: 16px; box-shadow: 0 1px 3px var(--sombra); overflow: hidden;
            max-width: 980px;
        }
        .painel > .titulo {
            background: linear-gradient(180deg, #f7faf6 0%, var(--verde-claro) 100%);
            border-bottom: 1px solid var(--verde-borda); border-left: 4px solid var(--verde-vivo);
            padding: 9px 14px; font-size: 13px; font-weight: 700; color: var(--verde-escuro);
        }
        .grade { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .grade .campo {
            padding: 9px 14px; border-bottom: 1px solid var(--borda-suave); min-width: 0;
        }
        .grade .campo:nth-child(odd) { border-right: 1px solid var(--borda-suave); }
        .grade .campo.largo { grid-column: 1 / -1; border-right: none; }
        .rotulo {
            font-size: 10.5px; text-transform: uppercase; letter-spacing: .6px;
            color: var(--cinza); font-weight: 700; margin-bottom: 3px;
        }
        .valor { font-size: 13.5px; color: var(--texto); word-wrap: break-word; }
        .valor.destaque { font-size: 16px; font-weight: 700; color: var(--verde-escuro); }

        /* faixa de identificação do protocolo */
        .faixa-protocolo {
            background: linear-gradient(180deg, #43885a 0%, var(--verde) 100%);
            color: #fff; border-radius: 6px; padding: 16px 20px; margin-bottom: 18px;
            display: flex; justify-content: space-between; align-items: center;
            flex-wrap: wrap; gap: 14px; max-width: 980px;
            border-left: 5px solid var(--verde-vivo);
        }
        .faixa-protocolo .numero {
            font-family: "Consolas", "Courier New", monospace;
            font-size: 21px; font-weight: 700; letter-spacing: .5px;
        }
        .faixa-protocolo .tipo { font-size: 12px; opacity: .9; margin-top: 3px; }
        .chip {
            display: inline-block; padding: 6px 14px; border-radius: 14px;
            font-size: 12px; font-weight: 700; background: #fff;
        }

        /* ----- BOTÕES ----- */
        .btn {
            padding: 7px 14px; border: none; border-radius: 4px; cursor: pointer;
            font-size: 12.5px; font-weight: 600; font-family: inherit; transition: filter .15s;
        }
        .btn:hover { filter: brightness(1.1); }
        .btn-salvar { background: linear-gradient(180deg, var(--cabecalho-topo) 0%, var(--verde) 100%); color: #fff; }
        .btn-excluir { background: #c0392b; color: #fff; }
        .btn-adicionar { background: linear-gradient(180deg, var(--cabecalho-topo) 0%, var(--verde) 100%); color: #fff; padding: 10px 20px; }
        .btn-atalho {
            background: var(--superficie); color: var(--verde-escuro); border: 1px solid var(--verde-borda);
            padding: 6px 11px; border-radius: 4px; font-size: 12px; font-weight: 600;
            cursor: pointer; margin-right: 6px; margin-bottom: 6px;
            display: inline-block; text-decoration: none;
        }
        .btn-atalho:hover { background: var(--verde-claro); border-color: var(--verde-medio); }


        /* Busca de protocolo no cabeçalho: sempre sobre a faixa verde,
           tanto no modo claro quanto no escuro, por isso as cores são fixas
           em branco - não usam variáveis de tema. */
        .busca-protocolo {
            padding: 7px 11px; border-radius: 4px; border: 1px solid rgba(255,255,255,.55);
            background: rgba(255,255,255,.16); color: #fff; font-size: 12.5px; width: 170px;
        }
        .busca-protocolo::placeholder { color: rgba(255,255,255,.85) !important; }
        .busca-protocolo:focus {
            outline: none; background: rgba(255,255,255,.24); border-color: rgba(255,255,255,.85);
        }

        /* ============== TELAS PEQUENAS (CELULAR) ==============
           O menu passa a flutuar sobre a página; o restante apenas
           se ajusta à largura. A regra display:flex do body NÃO é
           alterada, para não desmontar a estrutura. */
        .abrir-menu {
            display: none; background: transparent; border: 1px solid rgba(255,255,255,.5);
            color: #fff; border-radius: 4px; padding: 6px 9px; cursor: pointer; margin-right: 12px;
        }
        .sombra-menu { display: none; }

        @media (max-width: 820px) {
            nav {
                position: fixed; top: 0; left: 0; bottom: 0; z-index: 60;
                overflow-y: auto; transform: translateX(-100%);
                transition: transform .25s ease; box-shadow: 2px 0 16px rgba(0,0,0,.35);
            }
            nav.aberto { transform: translateX(0); }

            .sombra-menu {
                position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0,0,0,.5); z-index: 55;
            }
            .sombra-menu.visivel { display: block; }

            .abrir-menu { display: inline-flex; align-items: center; }

            header { padding: 11px 14px; }
            header h1 { font-size: 15px; }
            header .usuario { font-size: 12px; gap: 8px; }

            .conteudo { padding: 16px 13px; }
            h2 { font-size: 18px; }

            /* painéis de detalhe passam a uma coluna */
            .grade { grid-template-columns: 1fr; }
            .grade .campo:nth-child(odd) { border-right: none; }

            /* tabelas rolam na horizontal em vez de espremer */
            table { display: block; overflow-x: auto; }

            /* formulários e blocos acompanham a largura da tela */
            form, .painel, .bloco, .faixa-protocolo { max-width: 100% !important; }
            input, select, textarea { max-width: 100%; }

            .faixa-protocolo { flex-direction: column; align-items: flex-start; }
            .faixa-protocolo .numero { font-size: 17px; }
        }

        @media (max-width: 480px) {
            .conteudo { padding: 13px 10px; }
            h3 { font-size: 13px; padding: 7px 10px; }
        }
    </style>
</head>
<body>
    <nav>
        <div class="logo">{{ ic.predio|safe }} SIGAD Carajás</div>

        <a class="item" href="{{ url_for('inicio') }}">{{ ic.home|safe }} Tela Inicial</a>

        <a class="item" href="{{ url_for('minhas_solicitacoes') }}">
            {{ ic.lista|safe }} Minhas Solicitações
            {% if qtd.minhas %}<span class="badge badge-alerta">{{ qtd.minhas }}</span>{% endif %}
        </a>

        {% if current_user.perfil == 'analista' or current_user.is_organizador %}
        <a class="item" href="{{ url_for('fila_analise') }}">
            {{ ic.lupa|safe }} Fila de Análise
            {% if qtd.analise %}<span class="badge">{{ qtd.analise }}</span>{% endif %}
        </a>
        {% endif %}

        {% if current_user.perfil == 'aprovador' or current_user.is_organizador %}
        <a class="item" href="{{ url_for('fila_aprovacao') }}">
            {{ ic.check|safe }} Fila de Aprovação
            {% if qtd.aprovacao %}<span class="badge">{{ qtd.aprovacao }}</span>{% endif %}
        </a>
        {% endif %}

        {% if current_user.perfil == 'comprador' or current_user.is_organizador or tem_demandas_atribuidas() %}
        <a class="item" href="{{ url_for('fila_execucao') }}">
            {{ ic.caixa|safe }} Minhas Demandas
            {% if qtd.demandas %}<span class="badge">{{ qtd.demandas }}</span>{% endif %}
        </a>
        {% endif %}

        {% if current_user.perfil in ('analista', 'aprovador', 'comprador') or current_user.is_organizador %}
        <a class="item" href="{{ url_for('prestacao_contas') }}">
            {{ ic.prancheta|safe }} Prestação de Contas
            {% if qtd.prestacao %}<span class="badge badge-alerta">{{ qtd.prestacao }}</span>{% endif %}
        </a>
        {% else %}
        <a class="item" href="{{ url_for('prestacao_contas') }}">
            {{ ic.prancheta|safe }} Prestação de Contas
            {% if qtd.minhas_prestacoes %}<span class="badge badge-alerta">{{ qtd.minhas_prestacoes }}</span>{% endif %}
        </a>
        {% endif %}

        <div class="grupo" data-grupo="solicitacao">
            {{ ic.pasta|safe }}<span>Solicitação</span>
            <svg class="seta" viewBox="0 0 24 24" width="13" height="13" fill="none"
                 stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
                <path d="m6 9 6 6 6-6"/>
            </svg>
        </div>
        <div class="submenu" id="grupo-solicitacao">
            <a href="{{ url_for('diaria_form') }}">{{ ic.dinheiro|safe }} Diária</a>
            <a href="{{ url_for('passagem_form') }}">{{ ic.aviao|safe }} Passagem</a>
            <a href="{{ url_for('compra_materiais_form') }}">{{ ic.caixa|safe }} Compras de Materiais</a>
            <a href="{{ url_for('rancho_form') }}">{{ ic.carrinho|safe }} Rancho</a>
            <a href="{{ url_for('alimentacao_form') }}">{{ ic.talher|safe }} Alimentação</a>
            <a href="{{ url_for('locacao_veiculo_form') }}">{{ ic.onibus|safe }} Locação de Veículos</a>
            <a href="{{ url_for('servico_externo_pf_form') }}">{{ ic.ferramenta|safe }} Serviço Externo PF</a>
            <a href="{{ url_for('servico_externo_pj_form') }}">{{ ic.predio|safe }} Serviço Externo PJ</a>
            <a href="{{ url_for('seguro_form') }}">{{ ic.escudo|safe }} Seguro</a>
            <a href="{{ url_for('bolsa_form') }}">{{ ic.formatura|safe }} Bolsa</a>
            <a href="{{ url_for('atividades') }}">📋 Solicitações Agrupadas</a>
        </div>

        {% if current_user.perfil == 'analista' or current_user.is_organizador %}
        <div class="grupo" data-grupo="cadastros">
            {{ ic.engrenagem|safe }}<span>Cadastros</span>
            <svg class="seta" viewBox="0 0 24 24" width="13" height="13" fill="none"
                 stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
                <path d="m6 9 6 6 6-6"/>
            </svg>
        </div>
        <div class="submenu" id="grupo-cadastros">
            <a href="{{ url_for('cadastro_diaria') }}">{{ ic.dinheiro|safe }} Diária</a>
            <a href="{{ url_for('cadastro_coordenacao') }}">{{ ic.predio|safe }} Coordenação</a>
            <a href="{{ url_for('cadastro_alimentacao') }}">{{ ic.talher|safe }} Alimentação</a>
            <a href="{{ url_for('cadastro_locacao_veiculo') }}">{{ ic.onibus|safe }} Locação de Veículos</a>
            <a href="{{ url_for('cadastro_servico_externo') }}">{{ ic.ferramenta|safe }} Serviços Externos</a>
            <a href="{{ url_for('cadastro_rancho') }}">{{ ic.carrinho|safe }} Rancho</a>
            <a href="{{ url_for('cadastro_usuarios') }}">{{ ic.usuarios|safe }} Usuários</a>
            <a href="{{ url_for('cadastro_travar_solicitacoes') }}">🔒 Travar Solicitações</a>
        </div>
        {% endif %}

        {% if current_user.perfil in ('analista', 'aprovador') or current_user.is_organizador %}
        <div class="grupo" data-grupo="relatorios">
            {{ ic.grafico|safe }}<span>Relatórios</span>
            <svg class="seta" viewBox="0 0 24 24" width="13" height="13" fill="none"
                 stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
                <path d="m6 9 6 6 6-6"/>
            </svg>
        </div>
        <div class="submenu" id="grupo-relatorios">
            <a href="{{ url_for('relatorios') }}">{{ ic.grafico|safe }} Todas as solicitações</a>
            {% if current_user.is_organizador %}
            <a href="{{ url_for('auditoria') }}">{{ ic.prancheta|safe }} Auditoria</a>
            {% endif %}
        </div>
        {% endif %}

        <div class="grupo" data-grupo="suporte">
            {{ ic.ajuda|safe }}<span>Suporte</span>
            <svg class="seta" viewBox="0 0 24 24" width="13" height="13" fill="none"
                 stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
                <path d="m6 9 6 6 6-6"/>
            </svg>
        </div>
        <div class="submenu" id="grupo-suporte">
            <a href="{{ url_for('ajuda') }}">{{ ic.ajuda|safe }} Central de Ajuda</a>
        </div>

        <script>
        (function () {
            var CHAVE = 'sigad_menu_aberto';

            function lerEstado() {
                try {
                    return JSON.parse(localStorage.getItem(CHAVE)) || {};
                } catch (e) {
                    return {};
                }
            }

            function salvarEstado(estado) {
                try {
                    localStorage.setItem(CHAVE, JSON.stringify(estado));
                } catch (e) { /* modo privado: apenas ignora */ }
            }

            var estado = lerEstado();
            var caminho = window.location.pathname;

            document.querySelectorAll('nav .grupo').forEach(function (grupo) {
                var nome = grupo.dataset.grupo;
                var submenu = document.getElementById('grupo-' + nome);
                if (!submenu) { return; }

                // abre o grupo que contém a página atual
                var contemAtual = Array.prototype.some.call(
                    submenu.querySelectorAll('a'),
                    function (link) {
                        var href = link.getAttribute('href');
                        return href && href !== '#' && caminho === href;
                    }
                );

                var aberto = contemAtual || estado[nome] === true;
                if (aberto) {
                    submenu.classList.add('aberto');
                    grupo.classList.add('aberto');
                }

                grupo.addEventListener('click', function () {
                    var agoraAberto = submenu.classList.toggle('aberto');
                    grupo.classList.toggle('aberto', agoraAberto);
                    estado[nome] = agoraAberto;
                    salvarEstado(estado);
                });
            });
        })();
        </script>
    </nav>

    <div class="sombra-menu" id="sombra-menu"></div>

    <main>
        <header>
            <span style="display:flex; align-items:center; min-width:0;">
                <button type="button" class="abrir-menu" id="abrir-menu" aria-label="Abrir menu">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
                         stroke-width="2.2" stroke-linecap="round">
                        <path d="M4 7h16M4 12h16M4 17h16"/>
                    </svg>
                </button>
                <h1>{{ titulo }}</h1>
            </span>
            <div style="display:flex; align-items:center; gap:14px;">
                <form method="GET" action="{{ url_for('buscar_protocolo') }}"
                      style="display:flex; align-items:center;">
                    <input type="text" name="protocolo" placeholder="Buscar protocolo..."
                           class="busca-protocolo">
                </form>
                <div class="usuario">
                    <a href="{{ url_for('minha_conta') }}">{{ current_user.nome }}</a>
                    <a href="{{ url_for('logout') }}">{{ ic.sair|safe }} Sair</a>
                </div>
            </div>
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

    <script>
    // Menu retrátil nas telas pequenas
    (function () {
        var botao = document.getElementById('abrir-menu');
        var sombra = document.getElementById('sombra-menu');
        var menu = document.querySelector('nav');
        if (!botao || !sombra || !menu) { return; }

        function alternar(abrir) {
            menu.classList.toggle('aberto', abrir);
            sombra.classList.toggle('visivel', abrir);
        }

        botao.addEventListener('click', function () {
            alternar(!menu.classList.contains('aberto'));
        });
        sombra.addEventListener('click', function () { alternar(false); });
        menu.querySelectorAll('a').forEach(function (link) {
            link.addEventListener('click', function () { alternar(false); });
        });
    })();
    </script>

    <script>
    // Máscara e validação de CPF/CNPJ em todo o sistema.
    // Usa delegação de eventos, então funciona também nos blocos criados
    // dinamicamente (prestadores, participantes de seguro, bolsistas...).
    (function () {
        function ehCampoCPF(campo) {
            var nome = (campo.getAttribute('name') || '').toLowerCase();
            return campo.tagName === 'INPUT' && nome.indexOf('cpf') !== -1;
        }

        function ehCampoCNPJ(campo) {
            var nome = (campo.getAttribute('name') || '').toLowerCase();
            return campo.tagName === 'INPUT' && nome.indexOf('cnpj') !== -1;
        }

        function ehCampoDDD(campo) {
            var nome = (campo.getAttribute('name') || '').toLowerCase();
            return campo.tagName === 'INPUT' && nome.indexOf('ddd') !== -1;
        }

        function ehCampoTelefone(campo) {
            var nome = (campo.getAttribute('name') || '').toLowerCase();
            return campo.tagName === 'INPUT' && nome.indexOf('telefone') !== -1
                   && nome.indexOf('ddd') === -1;
        }

        function formatarTelefone(valor) {
            var d = valor.replace(/[^0-9]/g, '').slice(0, 9);
            if (d.length > 5) { return d.slice(0, d.length - 4) + '-' + d.slice(d.length - 4); }
            return d;
        }

        function formatarCPF(valor) {
            var d = valor.replace(/[^0-9]/g, '').slice(0, 11);
            if (d.length > 9)      { return d.slice(0,3) + '.' + d.slice(3,6) + '.' + d.slice(6,9) + '-' + d.slice(9); }
            else if (d.length > 6) { return d.slice(0,3) + '.' + d.slice(3,6) + '.' + d.slice(6); }
            else if (d.length > 3) { return d.slice(0,3) + '.' + d.slice(3); }
            return d;
        }

        function formatarCNPJ(valor) {
            var d = valor.replace(/[^0-9]/g, '').slice(0, 14);
            if (d.length > 12)      { return d.slice(0,2) + '.' + d.slice(2,5) + '.' + d.slice(5,8) + '/' + d.slice(8,12) + '-' + d.slice(12); }
            else if (d.length > 8)  { return d.slice(0,2) + '.' + d.slice(2,5) + '.' + d.slice(5,8) + '/' + d.slice(8); }
            else if (d.length > 5)  { return d.slice(0,2) + '.' + d.slice(2,5) + '.' + d.slice(5); }
            else if (d.length > 2)  { return d.slice(0,2) + '.' + d.slice(2); }
            return d;
        }

        function preparar(campo) {
            if (ehCampoCPF(campo)) {
                campo.setAttribute('maxlength', '14');
                campo.setAttribute('inputmode', 'numeric');
                if (!campo.getAttribute('placeholder')) {
                    campo.setAttribute('placeholder', '000.000.000-00');
                }
                campo.value = formatarCPF(campo.value);
            } else if (ehCampoCNPJ(campo)) {
                campo.setAttribute('maxlength', '18');
                campo.setAttribute('inputmode', 'numeric');
                if (!campo.getAttribute('placeholder')) {
                    campo.setAttribute('placeholder', '00.000.000/0000-00');
                }
                campo.value = formatarCNPJ(campo.value);
            } else if (ehCampoDDD(campo)) {
                campo.setAttribute('maxlength', '2');
                campo.setAttribute('inputmode', 'numeric');
                if (!campo.getAttribute('placeholder')) { campo.setAttribute('placeholder', 'DDD'); }
                campo.value = campo.value.replace(/[^0-9]/g, '').slice(0, 2);
            } else if (ehCampoTelefone(campo)) {
                campo.setAttribute('maxlength', '10');
                campo.setAttribute('inputmode', 'numeric');
                if (!campo.getAttribute('placeholder')) { campo.setAttribute('placeholder', '99999-9999'); }
                campo.value = formatarTelefone(campo.value);
            }
        }

        function aplicarMascara(campo) {
            if (ehCampoCPF(campo)) {
                preparar(campo);
                campo.value = formatarCPF(campo.value);
                campo.setCustomValidity('');
            } else if (ehCampoCNPJ(campo)) {
                preparar(campo);
                campo.value = formatarCNPJ(campo.value);
                campo.setCustomValidity('');
            } else if (ehCampoDDD(campo)) {
                preparar(campo);
                campo.value = campo.value.replace(/[^0-9]/g, '').slice(0, 2);
            } else if (ehCampoTelefone(campo)) {
                preparar(campo);
                campo.value = formatarTelefone(campo.value);
            }
        }

        document.addEventListener('input', function (evento) {
            aplicarMascara(evento.target);
        });

        // bloqueia a digitação depois do limite, em vez de apenas reformatar
        document.addEventListener('keypress', function (evento) {
            var campo = evento.target;
            var limite = 0;
            if (ehCampoCPF(campo)) { limite = 11; }
            else if (ehCampoCNPJ(campo)) { limite = 14; }
            else if (ehCampoDDD(campo)) { limite = 2; }
            else if (ehCampoTelefone(campo)) { limite = 9; }
            if (!limite) { return; }

            // permite teclas de controle
            if (evento.ctrlKey || evento.metaKey || evento.key.length > 1) { return; }

            // só aceita dígito
            if (!/[0-9]/.test(evento.key)) { evento.preventDefault(); return; }

            var digitos = (campo.value || '').replace(/[^0-9]/g, '');
            var temSelecao = campo.selectionStart !== campo.selectionEnd;
            if (digitos.length >= limite && !temSelecao) { evento.preventDefault(); }
        });

        // ao colar, corta no limite
        document.addEventListener('paste', function (evento) {
            var campo = evento.target;
            if (ehCampoCPF(campo) || ehCampoCNPJ(campo) || ehCampoDDD(campo) || ehCampoTelefone(campo)) {
                setTimeout(function () { aplicarMascara(campo); }, 0);
            }
        });

        // valida antes de enviar qualquer formulário
        document.addEventListener('submit', function (evento) {
            var formulario = evento.target;
            var invalidos = [];

            formulario.querySelectorAll('input').forEach(function (campo) {
                var digitos = (campo.value || '').replace(/[^0-9]/g, '');

                if (ehCampoCPF(campo)) {
                    if (digitos.length === 0 && !campo.required) { return; }
                    if (digitos.length !== 11) { invalidos.push('CPF'); campo.style.borderColor = '#c0392b'; }
                    else { campo.style.borderColor = ''; }
                } else if (ehCampoCNPJ(campo)) {
                    if (digitos.length === 0 && !campo.required) { return; }
                    if (digitos.length !== 14) { invalidos.push('CNPJ'); campo.style.borderColor = '#c0392b'; }
                    else { campo.style.borderColor = ''; }
                } else if (ehCampoDDD(campo)) {
                    if (digitos.length === 0 && !campo.required) { return; }
                    if (digitos.length !== 2) { invalidos.push('DDD'); campo.style.borderColor = '#c0392b'; }
                    else { campo.style.borderColor = ''; }
                } else if (ehCampoTelefone(campo)) {
                    if (digitos.length === 0 && !campo.required) { return; }
                    if (digitos.length < 8 || digitos.length > 9) {
                        invalidos.push('Telefone'); campo.style.borderColor = '#c0392b';
                    } else { campo.style.borderColor = ''; }
                }
            });

            if (invalidos.length > 0) {
                evento.preventDefault();
                alert('Verifique os campos destacados.\n\n' +
                      'CPF: 11 dígitos | CNPJ: 14 dígitos | DDD: 2 dígitos | Telefone: 8 ou 9 dígitos.');
            }
        }, true);

        // aplica a preparação nos campos já existentes ao abrir a página
        document.querySelectorAll('input').forEach(preparar);
    })();
    </script>
</body>
</html>
"""


def render_pagina(titulo, conteudo_html):
    banner_travamento = ''
    if current_user.is_authenticated and solicitacoes_estao_travadas():
        banner_travamento = f"""
        <div style="background:#fdeceb; border-left:4px solid #c0392b; color:#a02020;
             padding:11px 16px; border-radius:5px; font-size:12.5px; margin-bottom:16px;">
            🔒 <strong>Novas solicitações travadas.</strong> {mensagem_travamento()}
        </div>
        """

    return render_template_string(
        BASE_TEMPLATE,
        titulo=titulo,
        conteudo_html=banner_travamento + conteudo_html,
        tem_demandas_atribuidas=tem_demandas_atribuidas,
        ic=ICONES,
        qtd=contadores_menu(),
    )


# ---------------- LOGIN ----------------
# ---------------- IMAGEM DAS UNIDADES DE CONSERVAÇÃO ----------------
# A faixa de logos fica embutida no código (base64), assim o sistema não depende
# de arquivo externo nem de pasta static para funcionar.
LOGOS_UCS_BASE64 = (
    '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'
    'qlWdVK8EpEBFwAx9AHQs/4dvNHF7u1+mxvM2RkYRg683YCjFDDqOrLk3dn8vAQBAf+3e+Ref4empHny9Aeu3+z/9AXQ52Bmenia9'
    'huJXLGeKpeKowxd/5i7Zdw1bsu8ahrxnjNtnqr0oHAF5Vj0sjMHa0jqO3VpNW7LvGmaq3YSS4KP12tKsRq1rp0453OEWqBHwvoq2'
    '728fbVwXgjZbAaCz2orupLShbDbG6Yu0mpX0ux1ZrMfBLtT3ydHKysbP2UuGnTiLlZUf0yJCrsdhen5qwPZJAMy/cn13OW0fNc/t'
    'CLaVFmnGvi+q6Vjm/yXxSv9JcPO3YhIlTzcGs8Z1QP9P8JhKsx7lFXz4mHDbrtz0+YgRDjGQIYBLfdl6Ykh7If87YpgAtIfZL9yQ'
    'TWhHm+8Crj3MfsGO/OhKEwFPkCaWiqOQWzJV9BZc9uz/9pvXJ/POXdS3+XU1C8VScZSMkAU8qkvy44DayZjPEhkhC9DAyajeWmv/'
    'V0EtAIDZV2wNAECQy+TMMS42/6+BLNWl+Gm5Ej/25kh9VxewqdXSqO8cygDRppG2zt//4Z35+z+8k/rjgcYVqRvfQ6yk6F17ls9P'
    '+YYLDgDwlofOe+53RRvNeB26nZikQiDqdmKSKn7FciZynRbwBGnI1ZK6bnW34Ta1t0GpHY0ZZh8FxBBKgn/4RhMXldXduVRw5Mlg'
    'kabKj8Lm9Xj/r9euNevOS8gdE2sBALJyzR5w7506vB/NjcGjWfwW88B81uEcTEOW2/QDv9DR9SGBnbSQwE6axFFAO1fT9EB7Ejds'
    'VCGlA3oOaA+ZuGGjCmfhksQNG1W3E5MM8zWyRt9SXsUBAHblps8HAAh4XfFMgC2Kr125+tM5xqy8OyOGKJEiFX2QYhYpgB7FZRWl'
    'zUIuxug9RKBalpGVTCasM8dWf9qBQO2N3d9LyMSEdOo7SRXbfWm48TNolxZ7I2stFVRT22f8Qe1NDpvbgdqI3iE0TrsDhQAAWyOH'
    'kFTwKZaKo3662tL809WWZrRe0+hfaTqVefL74G1SGsoTrNWspBNKgo9y4VpgqgwaPk3Lq1HQaMR3NKXMa/6NOx+2ie6ktF27mZWK'
    '6k2jf6XpYx6iRM8CuSw/yt7WkN92uO/SacuW3SvL2cZF+W0fh+n5SQjDVGcDAFRUnMi1HuUVbMo9+GGkTN39/iStsQ8rk3rvPSmZ'
    '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'
    'xSxmeQD5/7BNnKHbPNGBAAAAAElFTkSuQmCC'
)


LOGO_ICMBIO_BASE64 = (
    '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'
)


@app.route('/imagens/icmbio.png')
def imagem_icmbio():
    """Serve a logo institucional exibida no card de login."""
    import base64 as _b64
    from flask import Response

    return Response(
        _b64.b64decode(LOGO_ICMBIO_BASE64),
        mimetype='image/png',
        headers={'Cache-Control': 'public, max-age=86400'},
    )


@app.route('/imagens/unidades.png')
def imagem_unidades():
    """Serve a faixa de logos das unidades de conservação."""
    import base64 as _b64
    from flask import Response

    return Response(
        _b64.b64decode(LOGOS_UCS_BASE64),
        mimetype='image/png',
        headers={'Cache-Control': 'public, max-age=86400'},
    )


LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>SIGAD Carajás - Acesso</title>
    <style>
        * { box-sizing: border-box; }
        :root { --lg-fundo:#fff; --lg-caixa:#fff; --lg-texto:#23302a; --lg-borda:#e2e8e4; --lg-suave:#6b7a72; }

        body {
            font-family: "Segoe UI", Roboto, Arial, sans-serif;
            background: var(--lg-fundo); color: var(--lg-texto);
            display: flex; flex-direction: column; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0; padding: 30px 20px;
        }
        .login-box {
            background: var(--lg-caixa); padding: 36px 34px; border-radius: 9px;
            box-shadow: 0 4px 22px rgba(0,0,0,.10); border: 1px solid var(--lg-borda);
            width: 100%; max-width: 370px;
        }
        .marca { text-align: center; margin-bottom: 24px; }
        .marca .logo-icmbio { width: 168px; height: auto; margin-bottom: 12px; }
        .marca h1 { color: #004622; font-size: 22px; margin: 10px 0 2px; font-weight: 700; }
        .marca p { color: #37784D; font-size: 12.5px; margin: 0; }
        label { font-size: 12.5px; font-weight: 600; color: var(--lg-texto); display: block; margin-bottom: 5px; }
        .login-box input {
            width: 100%; padding: 11px 12px; margin-bottom: 15px; font-size: 14px;
            border: 1px solid var(--lg-borda); border-radius: 5px; font-family: inherit;
            background: var(--lg-caixa); color: var(--lg-texto);
        }
        .login-box input:focus {
            outline: none; border-color: #37784D; box-shadow: 0 0 0 3px rgba(160,197,23,.28);
        }
        .login-box button {
            width: 100%; padding: 12px;
            background: linear-gradient(180deg, #43885a 0%, #37784D 100%);
            color: #fff; border: none; border-radius: 5px; cursor: pointer;
            font-size: 14.5px; font-weight: 600; font-family: inherit; margin-top: 4px;
        }
        .login-box button:hover { background: #004622; }
        .flash {
            background: #fdecec; color: #a02020; border-left: 4px solid #c0392b;
            padding: 10px 13px; border-radius: 4px; font-size: 13px; margin-bottom: 16px;
        }
        .rodape { text-align: center; font-size: 11px; color: #93a39a; margin-top: 18px; }

        /* faixa das unidades de conservação, abaixo do card */
        .unidades {
            width: 100%; max-width: 860px; text-align: center; margin-top: 44px;
        }
        .unidades img { width: 100%; height: auto; }
        @media (max-width: 700px) {
            .unidades { margin-top: 30px; }
        }
    </style>
</head>
<body>
    <div class="login-box">
        <div class="marca">
            <img src="__LOGO_ICMBIO__" alt="ICMBio - Instituto Chico Mendes" class="logo-icmbio"
                 onerror="this.style.display='none';">
            <h1>SIGAD Carajás</h1>
            <p>Sistema de Gestão Administrativa</p>
        </div>

        {% with messages = get_flashed_messages() %}
            {% for mensagem in messages %}
                <div class="flash">{{ mensagem }}</div>
            {% endfor %}
        {% endwith %}

        <form method="POST">
            <label>E-mail</label>
            <input type="email" name="email" placeholder="seu.email@ngi.com" required autofocus>

            <label>Senha</label>
            <input type="password" name="senha" placeholder="Digite sua senha" required>

            <button type="submit">Entrar no sistema</button>
        </form>

        <div style="text-align:center; margin-top:14px;">
            <a href="/esqueci-senha" style="font-size:12.5px; color:#37784D; text-decoration:none;">
                Esqueci minha senha
            </a>
        </div>

        <div class="rodape">Acesso restrito a usuários cadastrados</div>
    </div>

    <div class="unidades">
        <img src="__LOGOS_URL__" alt="Unidades de Conservação do NGI Carajás"
             onerror="this.parentElement.style.display='none';">
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
            if usuario.trocar_senha:
                flash('Este é seu primeiro acesso (ou sua senha foi redefinida). '
                      'Escolha uma nova senha para continuar.', 'sucesso')
                return redirect(url_for('minha_conta'))
            return redirect(url_for('inicio'))
        flash('E-mail ou senha inválidos.')

    # a faixa aparece se existir o arquivo static/logos-ucs.png no projeto,
    # ou se a variável de ambiente LOGOS_UCS_URL apontar para uma imagem
    logos = os.environ.get('LOGOS_UCS_URL') or url_for('imagem_unidades')
    pagina = LOGIN_TEMPLATE.replace('__LOGOS_URL__', logos)
    pagina = pagina.replace('__LOGO_ICMBIO__', url_for('imagem_icmbio'))
    return render_template_string(pagina)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ---------------- RECUPERAÇÃO E TROCA DE SENHA ----------------
SENHA_MINIMA = 8

PAGINA_PUBLICA_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ titulo }} - SIGAD Carajás</title>
    <style>
        * { box-sizing: border-box; }
        :root { --pg-fundo:#fff; --pg-caixa:#fff; --pg-texto:#23302a; --pg-borda:#e2e8e4; --pg-suave:#6b7a72; }

        body {
            font-family: "Segoe UI", Roboto, Arial, sans-serif; background: var(--pg-fundo);
            color: var(--pg-texto);
            display: flex; flex-direction: column; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0; padding: 30px 20px;
        }
        .caixa {
            background: var(--pg-caixa); padding: 34px; border-radius: 9px; width: 100%; max-width: 420px;
            box-shadow: 0 4px 22px rgba(0,0,0,.10); border: 1px solid #e2e8e4;
        }
        .caixa h1 { color: var(--pg-texto); font-size: 19px; margin: 0 0 6px; }
        .caixa .ajuda { color: var(--pg-suave); font-size: 13px; margin-bottom: 20px; line-height: 1.55; }
        label { font-size: 12.5px; font-weight: 600; color: var(--pg-texto); display: block; margin-bottom: 5px; }
        input {
            width: 100%; padding: 11px 12px; margin-bottom: 15px; font-size: 14px;
            border: 1px solid var(--pg-borda); border-radius: 5px; font-family: inherit;
            background: var(--pg-caixa); color: var(--pg-texto);
        }
        input:focus { outline: none; border-color: #37784D; box-shadow: 0 0 0 3px rgba(160,197,23,.28); }
        button {
            width: 100%; padding: 12px; background: linear-gradient(180deg, #43885a 0%, #37784D 100%);
            color: #fff; border: none; border-radius: 5px; cursor: pointer;
            font-size: 14.5px; font-weight: 600; font-family: inherit;
        }
        button:hover { background: #004622; }
        .flash {
            background: #fdecec; color: #a02020; border-left: 4px solid #c0392b;
            padding: 10px 13px; border-radius: 4px; font-size: 13px; margin-bottom: 16px;
        }
        .flash-ok { background: #eef5ee; color: #1f5c33; border-left-color: #37784D; }
        .voltar { display: block; text-align: center; margin-top: 16px; font-size: 12.5px; color: #37784D; }
    </style>
</head>
<body>
    <div class="caixa">
        <h1>{{ titulo }}</h1>
        <div class="ajuda">{{ ajuda | safe }}</div>

        {% with messages = get_flashed_messages(with_categories=true) %}
            {% for categoria, mensagem in messages %}
                <div class="flash {{ 'flash-ok' if categoria == 'sucesso' else '' }}">{{ mensagem }}</div>
            {% endfor %}
        {% endwith %}

        {{ corpo | safe }}

        <a class="voltar" href="{{ url_for('login') }}">Voltar para o acesso</a>
    </div>
</body>
</html>
"""


def validar_nova_senha(senha, confirmacao):
    """Retorna None se estiver tudo certo, ou a mensagem de erro."""
    if not senha or len(senha) < SENHA_MINIMA:
        return f'A senha deve ter pelo menos {SENHA_MINIMA} caracteres.'
    if senha != confirmacao:
        return 'As senhas digitadas não conferem.'
    return None


@app.route('/esqueci-senha', methods=['GET', 'POST'])
def esqueci_senha():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        usuario = Usuario.query.filter(db.func.lower(Usuario.email) == email).first()

        if usuario:
            import secrets
            from datetime import timedelta

            usuario.token_senha = secrets.token_urlsafe(32)
            usuario.token_expira = agora() + timedelta(hours=2)
            db.session.commit()

            link = url_for('redefinir_senha', token=usuario.token_senha, _external=True)
            sucesso, detalhe = enviar_email(
                usuario.email,
                'Redefinição de senha - SIGAD Carajás',
                f'Olá, {usuario.nome}.\n\n'
                f'Recebemos um pedido de redefinição de senha para o seu acesso ao SIGAD Carajás.\n\n'
                f'Acesse o link abaixo para criar uma nova senha. Ele é válido por 2 horas:\n'
                f'{link}\n\n'
                f'Se você não solicitou, ignore esta mensagem: sua senha atual continua valendo.',
            )

            if not sucesso:
                print(f'[senha] nao foi possivel enviar o link para {usuario.email}: {detalhe}')

        # a mensagem é sempre a mesma, para não revelar quais e-mails existem
        flash('Se este e-mail estiver cadastrado, enviaremos um link de redefinição em instantes. '
              'Verifique também a caixa de spam.', 'sucesso')
        return redirect(url_for('esqueci_senha'))

    corpo = f"""
    <form method="POST">
        <label>E-mail cadastrado</label>
        <input type="email" name="email" required autofocus placeholder="seu.email@ngi.com">
        <button type="submit">Enviar link de redefinição</button>
    </form>
    """

    return render_template_string(
        PAGINA_PUBLICA_TEMPLATE,
        titulo='Esqueci minha senha',
        ajuda='Informe o e-mail cadastrado no sistema. Você receberá um link para criar uma nova senha.<br><br>'
              '<strong>Não recebeu?</strong> Procure o administrador do sistema, que pode redefinir '
              'sua senha diretamente.',
        corpo=corpo,
    )


@app.route('/redefinir-senha/<token>', methods=['GET', 'POST'])
def redefinir_senha(token):
    usuario = Usuario.query.filter_by(token_senha=token).first()

    expirado = (not usuario) or (not usuario.token_expira) or (usuario.token_expira < agora())

    if expirado:
        return render_template_string(
            PAGINA_PUBLICA_TEMPLATE,
            titulo='Link inválido ou expirado',
            ajuda='Este link de redefinição não é mais válido. Os links valem por 2 horas.<br><br>'
                  'Solicite um novo link ou procure o administrador do sistema.',
            corpo=f'<a href="{url_for("esqueci_senha")}"><button type="button">'
                  f'Solicitar novo link</button></a>',
        )

    if request.method == 'POST':
        senha = request.form.get('senha')
        erro = validar_nova_senha(senha, request.form.get('confirmacao'))

        if erro:
            flash(erro)
            return redirect(url_for('redefinir_senha', token=token))

        usuario.set_senha(senha)
        usuario.token_senha = None
        usuario.token_expira = None
        usuario.trocar_senha = False
        db.session.commit()

        flash('Senha alterada com sucesso. Faça o acesso com a nova senha.', 'sucesso')
        return redirect(url_for('login'))

    corpo = f"""
    <form method="POST">
        <label>Nova senha</label>
        <input type="password" name="senha" required autofocus minlength="{SENHA_MINIMA}">

        <label>Repita a nova senha</label>
        <input type="password" name="confirmacao" required minlength="{SENHA_MINIMA}">

        <button type="submit">Salvar nova senha</button>
    </form>
    """

    return render_template_string(
        PAGINA_PUBLICA_TEMPLATE,
        titulo='Criar nova senha',
        ajuda=f'Olá, {usuario.nome}. Defina sua nova senha de acesso — '
              f'mínimo de {SENHA_MINIMA} caracteres.',
        corpo=corpo,
    )


@app.route('/minha-conta', methods=['GET', 'POST'])
@login_required
def minha_conta():
    if request.method == 'POST':
        atual = request.form.get('senha_atual')

        if not current_user.check_senha(atual):
            flash('A senha atual está incorreta.')
            return redirect(url_for('minha_conta'))

        senha = request.form.get('senha')
        erro = validar_nova_senha(senha, request.form.get('confirmacao'))

        if erro:
            flash(erro)
            return redirect(url_for('minha_conta'))

        current_user.set_senha(senha)
        current_user.trocar_senha = False
        db.session.commit()

        flash('Senha alterada com sucesso.', 'sucesso')
        return redirect(url_for('minha_conta'))

    perfil_label = {
        'solicitante': 'Solicitante', 'analista': 'Analista',
        'aprovador': 'Aprovador', 'comprador': 'Comprador/Executor',
    }.get(current_user.perfil, current_user.perfil)

    if current_user.is_organizador:
        perfil_label += ' + Administrador'

    aviso_troca_obrigatoria = ''
    if current_user.trocar_senha:
        aviso_troca_obrigatoria = """
        <div class="bloco" style="border-left:4px solid #b35c00; background:#fff8ec; max-width:620px; margin-bottom:16px;">
            <strong style="color:#b35c00;">Defina uma nova senha para continuar</strong>
            <div style="font-size:12px; color:#666; margin-top:4px;">
                Este é seu primeiro acesso, ou sua senha foi redefinida pelo Administrador.
                Por segurança, escolha uma senha só sua antes de usar o restante do sistema.
            </div>
        </div>
        """

    conteudo = f"""
    <h2>Minha Conta</h2>
    {aviso_troca_obrigatoria}

    <div class="painel" style="max-width:620px;">
        <div class="titulo">Meus dados</div>
        <div class="grade">
            <div class="campo"><div class="rotulo">Nome</div><div class="valor">{current_user.nome}</div></div>
            <div class="campo"><div class="rotulo">E-mail</div><div class="valor">{current_user.email}</div></div>
            <div class="campo largo"><div class="rotulo">Perfil de acesso</div>
                <div class="valor">{perfil_label}</div></div>
        </div>
    </div>

    <div class="painel" style="max-width:620px;">
        <div class="titulo">Alterar minha senha</div>
        <div style="padding:16px;">
            <form method="POST" style="max-width:380px;">
                <label>Senha atual:</label><br>
                <input type="password" name="senha_atual" required
                       style="width:100%; padding:9px; margin-bottom:12px;"><br>

                <label>Nova senha (mínimo {SENHA_MINIMA} caracteres):</label><br>
                <input type="password" name="senha" required minlength="{SENHA_MINIMA}"
                       style="width:100%; padding:9px; margin-bottom:12px;"><br>

                <label>Repita a nova senha:</label><br>
                <input type="password" name="confirmacao" required minlength="{SENHA_MINIMA}"
                       style="width:100%; padding:9px; margin-bottom:15px;"><br>

                <button type="submit" class="btn btn-salvar" style="padding:10px 18px;">
                    Salvar nova senha
                </button>
            </form>
        </div>
    </div>
    """
    return render_pagina('Minha Conta', conteudo)


# ---------------- TELA INICIAL ----------------
def cartao_pendencia(titulo, quantidade, descricao, link, cor):
    if quantidade == 0:
        return ''
    return f"""
    <a href="{link}" style="text-decoration:none; color:inherit;">
        <div class="bloco" style="border-left:5px solid {cor}; background:white; max-width:600px;">
            <div style="display:flex; align-items:center; gap:15px;">
                <div style="background:{cor}; color:white; font-size:22px; font-weight:bold;
                            width:52px; height:52px; border-radius:6px; display:flex;
                            align-items:center; justify-content:center;">{quantidade}</div>
                <div>
                    <div style="font-size:15px; font-weight:bold; color:{cor};">{titulo}</div>
                    <div style="font-size:12px; color:#666; margin-top:2px;">{descricao}</div>
                </div>
            </div>
        </div>
    </a>
    """


@app.route('/')
@login_required
def inicio():
    cartoes = ''

    eh_analista = current_user.perfil == 'analista' or current_user.is_organizador
    eh_aprovador = current_user.perfil == 'aprovador' or current_user.is_organizador
    eh_executor = current_user.perfil == 'comprador' or current_user.is_organizador

    if eh_analista:
        qtd = Solicitacao.query.filter_by(status='pendente_analise').count()
        cartoes += cartao_pendencia(
            'Solicitações aguardando análise', qtd,
            'Solicitações que precisam da sua triagem.',
            url_for('fila_analise'), '#2b5876')

    if eh_aprovador:
        qtd = Solicitacao.query.filter_by(status='pendente_aprovacao').count()
        cartoes += cartao_pendencia(
            'Solicitações aguardando aprovação', qtd,
            'Solicitações analisadas que aguardam sua decisão.',
            url_for('fila_aprovacao'), '#2b5876')

    if eh_executor or tem_demandas_atribuidas():
        base = Solicitacao.query
        if not current_user.is_organizador:
            base = base.filter(Solicitacao.responsavel_encaminhamento_id == current_user.id)

        qtd_novas = base.filter(Solicitacao.status == 'aprovada').count()
        cartoes += cartao_pendencia(
            'Demandas aprovadas sob sua responsabilidade', qtd_novas,
            'Aprovadas e aguardando você definir o prazo de atendimento.',
            url_for('fila_execucao'), '#2e7d32')

        qtd_andamento = base.filter(Solicitacao.status == 'em_execucao').count()
        cartoes += cartao_pendencia(
            'Demandas em execução', qtd_andamento,
            'Em andamento, aguardando envio para pagamento.',
            url_for('fila_execucao'), '#b35c00')

        qtd_pagamento = base.filter(Solicitacao.status == 'enviado_pagamento').count()
        cartoes += cartao_pendencia(
            'Aguardando comprovante de pagamento', qtd_pagamento,
            'Enviadas para pagamento, aguardando o comprovante para conclusão.',
            url_for('fila_execucao'), '#5b6b76')

        qtd_compra = base.filter(Solicitacao.status == 'em_compra').count()
        cartoes += cartao_pendencia(
            'Demandas em compra', qtd_compra,
            'Em processo de compra, aguardando conclusão.',
            url_for('fila_execucao'), '#5b6b76')

    minhas_devolvidas = Solicitacao.query.filter_by(
        solicitante_id=current_user.id, status='devolvida_ajuste').count()
    cartoes += cartao_pendencia(
        'Suas solicitações devolvidas para ajuste', minhas_devolvidas,
        'Precisam de correção e novo envio.',
        url_for('minhas_solicitacoes'), '#b35c00')

    if pode_ver_prestacao():
        from datetime import timedelta
        limite = hoje() - timedelta(days=PRAZO_PRESTACAO_DIAS)
        qtd_prestacao = db.session.query(Solicitacao).join(
            SolicitacaoDiaria, SolicitacaoDiaria.solicitacao_id == Solicitacao.id
        ).filter(
            Solicitacao.tipo == 'diaria',
            Solicitacao.status.in_(('aprovada', 'em_execucao', 'enviado_pagamento', 'paga')),
            Solicitacao.prestacao_contas_entregue.isnot(True),
            Solicitacao.relatorio_em_conferencia.isnot(True),
            SolicitacaoDiaria.data_retorno < limite,
        ).count()
        cartoes += cartao_pendencia(
            'Prestações de contas em atraso', qtd_prestacao,
            f'Diárias com mais de {PRAZO_PRESTACAO_DIAS} dias do retorno sem prestação entregue.',
            url_for('prestacao_contas'), '#c0392b')

    if pode_avaliar_prestacao():
        qtd_conferencia = Solicitacao.query.filter(
            Solicitacao.tipo == 'diaria',
            Solicitacao.relatorio_em_conferencia.is_(True),
        ).count()
        cartoes += cartao_pendencia(
            'Relatórios aguardando conferência', qtd_conferencia,
            'Relatórios de viagem enviados que precisam ser conferidos e aprovados.',
            url_for('prestacao_contas'), '#b35c00')

    minhas_pendentes_relatorio = db.session.query(Solicitacao).join(
        SolicitacaoDiaria, SolicitacaoDiaria.solicitacao_id == Solicitacao.id
    ).filter(
        Solicitacao.solicitante_id == current_user.id,
        Solicitacao.tipo == 'diaria',
        Solicitacao.status.in_(('aprovada', 'em_execucao', 'enviado_pagamento', 'paga')),
        Solicitacao.prestacao_contas_entregue.isnot(True),
        Solicitacao.relatorio_em_conferencia.isnot(True),
    ).count()
    cartoes += cartao_pendencia(
        'Relatórios de viagem a enviar', minhas_pendentes_relatorio,
        f'Diárias aprovadas aguardando o relatório de viagem (prazo de {PRAZO_PRESTACAO_DIAS} dias após o retorno).',
        url_for('minhas_solicitacoes'), '#b35c00')

    minhas_com_aviso = Solicitacao.query.filter(
        Solicitacao.solicitante_id == current_user.id,
        Solicitacao.aviso_conclusao.isnot(None),
        Solicitacao.status.in_(STATUS_CONCLUIDOS),
    ).count()
    cartoes += cartao_pendencia(
        'Solicitações concluídas com aviso', minhas_com_aviso,
        'Há informações importantes sobre a entrega da sua demanda.',
        url_for('minhas_solicitacoes'), '#2e7d32')

    minhas_reprovadas = Solicitacao.query.filter_by(
        solicitante_id=current_user.id, status='reprovada').count()
    cartoes += cartao_pendencia(
        'Suas solicitações reprovadas', minhas_reprovadas,
        'Veja a justificativa da reprovação.',
        url_for('minhas_solicitacoes'), '#c0392b')

    if not cartoes:
        cartoes = """
        <div class="bloco" style="max-width:600px; text-align:center; color:#666;">
            Nenhuma pendência no momento.
        </div>
        """

    conteudo = f"""
    <h2>Olá, {current_user.nome}</h2>
    <div style="font-size:13px; color:#666; margin-bottom:18px;">
        Suas pendências no sistema. Clique em um cartão para ir direto à lista.
    </div>
    {cartoes}
    """
    return render_pagina('Tela inicial', conteudo)


# ---------------- MINHAS SOLICITAÇÕES ----------------
@app.route('/minhas-solicitacoes')
@login_required
def minhas_solicitacoes():
    POR_PAGINA = 50
    try:
        pagina = max(int(request.args.get('pagina', 1)), 1)
    except ValueError:
        pagina = 1

    consulta_base = Solicitacao.query.options(
        joinedload(Solicitacao.responsavel_encaminhamento),
    ).filter_by(solicitante_id=current_user.id)

    total_registros = consulta_base.count()
    total_paginas = max((total_registros + POR_PAGINA - 1) // POR_PAGINA, 1)
    pagina = min(pagina, total_paginas)

    solicitacoes = consulta_base.order_by(Solicitacao.data_envio.desc()) \
        .limit(POR_PAGINA).offset((pagina - 1) * POR_PAGINA).all()

    # carrega todas as diárias da página de uma vez, em vez de uma consulta por linha
    ids_pagina = [s.id for s in solicitacoes]
    diarias_por_solicitacao = {}
    if ids_pagina:
        for registro in SolicitacaoDiaria.query.filter(
                SolicitacaoDiaria.solicitacao_id.in_(ids_pagina)).all():
            diarias_por_solicitacao[registro.solicitacao_id] = registro

    cores_status = {
        'pendente_analise': '#555',
        'devolvida_ajuste': '#b35c00',
        'pendente_aprovacao': '#2b5876',
        'aprovada': '#2b5876',
        'em_execucao': '#b35c00',
        'enviado_pagamento': '#5b6b76',
        'em_compra': '#5b6b76',
        'paga': '#2e7d32',
        'comprado': '#2e7d32',
        'reprovada': '#c0392b',
        'ajuste_dados': '#b35c00',
    }

    from datetime import timedelta

    linhas_html = ''
    for s in solicitacoes:
        tipo_label = TIPO_SOLICITACAO_LABELS.get(s.tipo, s.tipo)
        status_label = STATUS_LABELS.get(s.status, s.status)
        cor = cores_status.get(s.status, '#555')

        # a linha inteira fica vermelha quando há prestação de contas pendente
        prestacao_pendente = False
        if (s.tipo == 'diaria'
                and s.status in ('aprovada', 'em_execucao', 'enviado_pagamento', 'paga')
                and not s.prestacao_contas_entregue):
            prestacao_pendente = True

        estilo_linha = ''
        if prestacao_pendente:
            estilo_linha = ' style="background:#fdeceb; color:#c0392b;"'
            cor = '#c0392b'

        extras = ''
        if s.status == 'devolvida_ajuste' and s.motivo_devolucao:
            extras += f'<br><span style="color:#b35c00; font-size:11px;">Ajuste: {s.motivo_devolucao}</span>'
        if s.status == 'ajuste_dados' and s.motivo_ajuste_dados:
            extras += f'<br><span style="color:#b35c00; font-size:11px;">Corrigir: {s.motivo_ajuste_dados}</span>'
        if s.status == 'reprovada' and s.motivo_reprovacao:
            extras += f'<br><span style="color:#c0392b; font-size:11px;">Motivo: {s.motivo_reprovacao}</span>'
        if s.prazo_encaminhamento:
            extras += f'<br><span style="font-size:11px;">Prazo: {s.prazo_encaminhamento.strftime("%d/%m/%Y")}</span>'
        if s.data_pagamento:
            rotulo_conclusao = 'Comprado em' if fluxo_do_tipo(s.tipo) == 'compra' else 'Pago em'
            extras += f'<br><span style="font-size:11px;">{rotulo_conclusao} {s.data_pagamento.strftime("%d/%m/%Y")}</span>'

        if prestacao_pendente:
            diaria_registro = diarias_por_solicitacao.get(s.id)
            if diaria_registro:
                prazo_pc = diaria_registro.data_retorno + timedelta(days=PRAZO_PRESTACAO_DIAS)
                atrasada = hoje() > prazo_pc

                if s.relatorio_em_conferencia:
                    aviso_pc = 'Relatório enviado — aguardando conferência.'
                elif s.motivo_recusa_prestacao:
                    aviso_pc = 'RELATÓRIO DEVOLVIDO — corrija e reenvie.'
                elif atrasada:
                    dias = (hoje() - prazo_pc).days
                    aviso_pc = f'PRESTAÇÃO DE CONTAS EM ATRASO ({dias} dia(s)) — prazo era {prazo_pc.strftime("%d/%m/%Y")}.'
                else:
                    aviso_pc = f'Prestação de contas pendente — envie o relatório até {prazo_pc.strftime("%d/%m/%Y")}.'

                extras += f'<br><span style="font-size:11.5px; font-weight:bold;">{aviso_pc}</span>'
        elif s.aviso_conclusao:
            extras += f'<br><span style="font-size:11px; color:#2e7d32; font-weight:bold;">{s.aviso_conclusao}</span>'

        responsavel = s.responsavel_encaminhamento.nome if s.responsavel_encaminhamento else '-'

        corrigir_link = ''
        if s.status in ('devolvida_ajuste', 'ajuste_dados'):
            corrigir_link = (f'<a href="{url_for("corrigir_solicitacao", solicitacao_id=s.id)}" '
                             f'class="btn btn-salvar" style="text-decoration:none; display:inline-block; '
                             f'background:#b35c00;">Corrigir e reenviar</a>')

        linhas_html += f"""
        <tr{estilo_linha}>
            <td style="font-family:monospace; font-size:12px;">{protocolo(s)}</td>
            <td>{s.data_envio.strftime('%d/%m/%Y %H:%M')}</td>
            <td>{tipo_label}</td>
            <td>{moeda(s.valor_total)}</td>
            <td>{responsavel}</td>
            <td><span style="color:{cor}; font-weight:bold;">{status_label}</span>{extras}</td>
            <td>
                <a href="{url_for('detalhe_solicitacao', solicitacao_id=s.id)}" class="btn-atalho">Ver detalhes</a>
                {corrigir_link}
            </td>
        </tr>
        """

    if not linhas_html:
        linhas_html = '<tr><td colspan="7">Você ainda não fez nenhuma solicitação.</td></tr>'

    navegacao = ''
    if total_paginas > 1:
        anterior = (f'<a href="{url_for("minhas_solicitacoes", pagina=pagina - 1)}" class="btn-atalho">Anterior</a>'
                    if pagina > 1 else '')
        proxima = (f'<a href="{url_for("minhas_solicitacoes", pagina=pagina + 1)}" class="btn-atalho">Próxima</a>'
                   if pagina < total_paginas else '')
        navegacao = f"""
        <div style="margin-top:14px; display:flex; align-items:center; gap:10px;">
            {anterior}{proxima}
            <span style="font-size:12px; color:#666;">
                Página {pagina} de {total_paginas} — {total_registros} solicitação(ões)
            </span>
        </div>
        """

    conteudo = f"""
    <h2>Minhas Solicitações</h2>
    <div style="font-size:12px; color:#666; margin-bottom:12px;">
        Solicitações destacadas em <strong style="color:#c0392b;">vermelho</strong> possuem
        prestação de contas pendente.
    </div>
    <table style="max-width:1100px;">
        <tr><th>Protocolo</th><th>Data</th><th>Tipo</th><th>Valor</th><th>Responsável</th><th>Status</th><th></th></tr>
        {linhas_html}
    </table>
    {navegacao}
    """
    return render_pagina('Minhas Solicitações', conteudo)


# ---------------- FILA DO ANALISTA ----------------
@app.route('/analise')
@login_required
def fila_analise():
    if current_user.perfil not in ('analista',) and not current_user.is_organizador:
        abort(403)

    consulta = Solicitacao.query.options(
        joinedload(Solicitacao.solicitante),
        joinedload(Solicitacao.coordenacao_solicitante),
    ).filter_by(status='pendente_analise')

    # as mais antigas primeiro: quem chegou antes é atendido antes
    solicitacoes, navegacao = paginar(consulta, Solicitacao.data_envio.asc(), 'fila_analise')

    linhas_html = ''
    for s in solicitacoes:
        tipo_label = TIPO_SOLICITACAO_LABELS.get(s.tipo, s.tipo)
        coord = s.coordenacao_solicitante.nome if s.coordenacao_solicitante else '-'
        linhas_html += f"""
        <tr>
            <td style="font-family:monospace; font-size:12px;">{protocolo(s)}</td>
            <td>{s.data_envio.strftime('%d/%m/%Y %H:%M')}</td>
            <td>{tipo_label}</td>
            <td>{s.solicitante.nome}</td>
            <td>{coord}</td>
            <td>{moeda(s.valor_total)}</td>
            <td>
                <a href="{url_for('detalhe_solicitacao', solicitacao_id=s.id)}" class="btn btn-salvar"
                   style="text-decoration:none; display:inline-block;">Abrir e analisar</a>
            </td>
        </tr>
        """

    if not linhas_html:
        linhas_html = '<tr><td colspan="7">Nenhuma solicitação pendente de análise.</td></tr>'

    conteudo = f"""
    <h2>Fila de Análise</h2>
    <div style="font-size:12px; color:#666; margin-bottom:12px;">
        Clique em <strong>Abrir e analisar</strong> para ver a solicitação completa e registrar seu parecer.
    </div>
    <table style="max-width:1000px;">
        <tr><th>Protocolo</th><th>Data</th><th>Tipo</th><th>Solicitante</th><th>Coordenação</th><th>Valor</th><th>Ações</th></tr>
        {linhas_html}
    </table>
    {navegacao}
    """
    return render_pagina('Fila de Análise', conteudo)


def gerar_pdf_bolsa(solicitacao, bolsistas):
    """Gera o PDF de detalhamento da bolsa para envio ao CTC. Devolve None se a
    biblioteca de PDF não estiver instalada no servidor - nesse caso, o e-mail
    ainda é enviado, só que sem o anexo, com os mesmos dados no corpo da mensagem."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except ImportError:
        print('[bolsa] reportlab não instalado - PDF não gerado, envio apenas por texto. '
              'Adicione "reportlab" ao requirements.txt para habilitar o anexo em PDF.')
        return None

    import io

    buffer = io.BytesIO()
    verde = colors.HexColor('#37784D')
    verde_escuro = colors.HexColor('#004622')
    borda = colors.HexColor('#cfe0d3')

    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm,
                            topMargin=2.2 * cm, bottomMargin=2.0 * cm,
                            title=f'Bolsa {protocolo(solicitacao)}')

    base = getSampleStyleSheet()
    est_titulo = ParagraphStyle('Titulo', parent=base['Title'], fontName='Helvetica-Bold',
                                fontSize=15, textColor=verde_escuro)
    est_texto = ParagraphStyle('Texto', parent=base['Normal'], fontName='Helvetica',
                               fontSize=9.5, leading=14)
    est_rotulo = ParagraphStyle('Rotulo', parent=base['Normal'], fontName='Helvetica-Bold',
                                fontSize=8.5, textColor=colors.white)

    conteudo = [
        Paragraph('SIGAD Carajás', ParagraphStyle('m', fontName='Helvetica-Bold', fontSize=10,
                                                   textColor=verde)),
        Paragraph(f'Solicitação de Bolsa - {protocolo(solicitacao)}', est_titulo),
        Spacer(1, 12),
        Paragraph(
            'Esta solicitação de bolsa foi analisada e aprovada nas instâncias competentes '
            'do NGI Carajás. O presente documento autoriza o encaminhamento ao Comitê Técnico '
            'Científico para a efetivação da bolsa.', est_texto),
        Spacer(1, 14),
    ]

    dados_gerais = [
        ['Solicitante', solicitacao.solicitante.nome],
        ['Coordenação', solicitacao.coordenacao_solicitante.nome if solicitacao.coordenacao_solicitante else '-'],
        ['Atividade / Projeto', solicitacao.atividade_projeto or '-'],
        ['Convênio', solicitacao.convenio or '-'],
        ['Lote de aprovação', solicitacao.lote_aprovacao or '-'],
        ['Rubrica', solicitacao.rubrica or '-'],
        ['Valor total da solicitação', moeda(solicitacao.valor_total)],
    ]
    tabela_geral = Table([[Paragraph(f'<b>{a}</b>', est_texto), Paragraph(str(b), est_texto)]
                          for a, b in dados_gerais], colWidths=[5 * cm, 11 * cm])
    tabela_geral.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.4, borda),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#eef5ee')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    conteudo.append(tabela_geral)
    conteudo.append(Spacer(1, 16))

    conteudo.append(Paragraph('Bolsistas', ParagraphStyle('h2', fontName='Helvetica-Bold',
                                                            fontSize=11, textColor=verde)))
    conteudo.append(Spacer(1, 6))

    cabecalho = [Paragraph(t, est_rotulo) for t in
                 ['Nome', 'Plano de trabalho', 'Período', 'Meses', 'Valor mensal', 'Valor total']]
    linhas = [cabecalho]
    for b in bolsistas:
        linhas.append([
            Paragraph(b.nome_bolsista, est_texto),
            Paragraph(b.titulo_plano_trabalho, est_texto),
            Paragraph(f'{b.mes_inicio} a {b.mes_fim}', est_texto),
            Paragraph(str(b.duracao_meses), est_texto),
            Paragraph(moeda(b.valor_mensal), est_texto),
            Paragraph(moeda(b.valor_total_bolsa), est_texto),
        ])

    tabela_bolsistas = Table(linhas, colWidths=[3.2 * cm, 4.3 * cm, 2.5 * cm, 1.5 * cm, 2.5 * cm, 2.5 * cm],
                             repeatRows=1)
    tabela_bolsistas.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), verde),
        ('GRID', (0, 0), (-1, -1), 0.4, borda),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5), ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    conteudo.append(tabela_bolsistas)
    conteudo.append(Spacer(1, 20))

    conteudo.append(Paragraph(
        f'Documento gerado automaticamente pelo SIGAD Carajás em {agora().strftime("%d/%m/%Y às %H:%M")}.',
        ParagraphStyle('nota', fontName='Helvetica-Oblique', fontSize=8, textColor=colors.HexColor('#5b6b76'))))

    doc.build(conteudo)
    return buffer.getvalue()


def notificar_solicitante(solicitacao, assunto, corpo):
    enviar_email(solicitacao.solicitante.email, assunto, corpo)


@app.route('/solicitacao/<int:solicitacao_id>/analise', methods=['POST'])
@login_required
def acao_analise(solicitacao_id):
    if current_user.perfil not in ('analista',) and not current_user.is_organizador:
        abort(403)

    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)
    if solicitacao.status != 'pendente_analise':
        flash('Esta solicitação não está mais na fase de análise.')
        return redirect(url_for('fila_analise'))

    acao = request.form.get('acao')
    tipo_label = TIPO_SOLICITACAO_LABELS.get(solicitacao.tipo, solicitacao.tipo)
    solicitacao.ressalva_analista = (request.form.get('ressalva') or '').strip() or None

    if acao == 'enviar':
        lote = (request.form.get('lote_aprovacao') or '').strip()
        convenio = request.form.get('convenio')
        rubrica = (request.form.get('rubrica') or '').strip()

        if not lote or not convenio:
            flash('Informe o Nº do Lote de Aprovação e o Convênio antes de enviar para o Aprovador.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        if solicitacao.tipo == 'bolsa' and not rubrica:
            flash('Para solicitações de Bolsa, a Rubrica é obrigatória.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        # Bolsa não segue para um Executor interno: após aprovada, a demanda é
        # encaminhada ao CTC (Comitê Técnico Científico), que não tem conta no
        # sistema. Por isso, apenas para este módulo, o Analista informa um
        # e-mail de contato em vez de escolher um responsável interno.
        if solicitacao.tipo == 'bolsa':
            email_ctc = (request.form.get('email_ctc') or '').strip()
            if not email_ctc or '@' not in email_ctc:
                flash('Informe um e-mail válido do CTC para encaminhamento da bolsa.')
                return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))
            solicitacao.email_ctc = email_ctc
            solicitacao.responsavel_encaminhamento_id = None
        else:
            responsavel_id = request.form.get('responsavel_encaminhamento')
            if not responsavel_id:
                flash('Informe o responsável pelo encaminhamento da demanda.')
                return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

            responsavel = Usuario.query.get(int(responsavel_id))
            if not responsavel or responsavel.perfil != 'comprador':
                flash('O responsável pelo encaminhamento deve ter o perfil Comprador/Executor.')
                return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

            solicitacao.responsavel_encaminhamento_id = responsavel.id

        solicitacao.lote_aprovacao = lote
        solicitacao.convenio = convenio
        solicitacao.rubrica = rubrica if solicitacao.tipo == 'bolsa' else None
        solicitacao.status = 'pendente_aprovacao'
        registrar_auditoria('enviou_aprovacao', solicitacao,
                            f'Lote {lote} | Convênio {convenio}'
                            + (f' | Rubrica {rubrica}' if solicitacao.tipo == 'bolsa' else ''))
        db.session.commit()

        aprovadores = Usuario.query.filter_by(perfil='aprovador').all()
        for aprovador in aprovadores:
            enviar_email(
                aprovador.email,
                'Nova solicitação aguardando aprovação - SIGAD Carajás',
                f'Olá, {aprovador.nome}.\n\n'
                f'Uma solicitação de {tipo_label}, de {solicitacao.solicitante.nome}, passou pela triagem '
                f'do Analista e está aguardando a sua aprovação.\n\n'
                f'Protocolo: {protocolo(solicitacao)}\n'
                f'Valor estimado: {moeda(solicitacao.valor_total)}\n\n'
                f'Acesse o sistema em "Fila de Aprovação" para avaliar.',
            )

        flash('Solicitação enviada para aprovação.', 'sucesso')
        return redirect(url_for('fila_analise'))

    justificativa = (request.form.get('justificativa') or '').strip()

    if acao == 'reprovar':
        if not justificativa:
            flash('Informe a justificativa da reprovação.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        solicitacao.status = 'reprovada'
        solicitacao.motivo_reprovacao = justificativa
        solicitacao.reprovada_por = f'{current_user.nome} (Analista)'
        registrar_auditoria('reprovou_analise', solicitacao, justificativa)
        db.session.commit()

        notificar_solicitante(
            solicitacao,
            'Sua solicitação foi reprovada - SIGAD Carajás',
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'Sua solicitação de {tipo_label}, protocolo {protocolo(solicitacao)}, foi reprovada '
            f'na etapa de análise.\n\n'
            f'Justificativa: {justificativa}\n\n'
            f'Se quiser esclarecer algo, procure o Analista responsável.',
        )

        flash('Solicitação reprovada e solicitante notificado.', 'sucesso')
        return redirect(url_for('fila_analise'))

    if acao == 'devolver':
        if not justificativa:
            flash('Informe o ajuste necessário para devolver a solicitação.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        solicitacao.status = 'devolvida_ajuste'
        solicitacao.motivo_devolucao = justificativa
        registrar_auditoria('devolveu_analise', solicitacao, justificativa)
        db.session.commit()

        notificar_solicitante(
            solicitacao,
            'Sua solicitação precisa de ajustes - SIGAD Carajás',
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'Sua solicitação de {tipo_label}, protocolo {protocolo(solicitacao)}, precisa de um '
            f'ajuste antes de seguir. Ela foi devolvida pelo Analista.\n\n'
            f'O que corrigir: {justificativa}\n\n'
            f'Acesse "Minhas Solicitações", corrija e reenvie.',
        )

        flash('Solicitação devolvida ao solicitante.', 'sucesso')
        return redirect(url_for('fila_analise'))

    flash('Ação inválida.')
    return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))


# ---------------- FILA DO APROVADOR ----------------
@app.route('/aprovacao')
@login_required
def fila_aprovacao():
    if current_user.perfil not in ('aprovador',) and not current_user.is_organizador:
        abort(403)

    consulta = Solicitacao.query.options(
        joinedload(Solicitacao.solicitante),
        joinedload(Solicitacao.coordenacao_solicitante),
    ).filter_by(status='pendente_aprovacao')

    solicitacoes, navegacao = paginar(consulta, Solicitacao.data_envio.asc(), 'fila_aprovacao')

    linhas_html = ''
    for s in solicitacoes:
        tipo_label = TIPO_SOLICITACAO_LABELS.get(s.tipo, s.tipo)
        coord = s.coordenacao_solicitante.nome if s.coordenacao_solicitante else '-'
        linhas_html += f"""
        <tr>
            <td style="font-family:monospace; font-size:12px;">{protocolo(s)}</td>
            <td>{s.data_envio.strftime('%d/%m/%Y %H:%M')}</td>
            <td>{tipo_label}</td>
            <td>{s.solicitante.nome}</td>
            <td>{coord}</td>
            <td style="font-size:11px;">
                Lote: {s.lote_aprovacao or '-'}<br>
                Convênio: {s.convenio or '-'}
                {'<br>Rubrica: ' + s.rubrica if s.tipo == 'bolsa' and s.rubrica else ''}
            </td>
            <td>{moeda(s.valor_total)}</td>
            <td>
                <a href="{url_for('detalhe_solicitacao', solicitacao_id=s.id)}" class="btn btn-salvar"
                   style="text-decoration:none; display:inline-block;">Abrir e avaliar</a>
            </td>
        </tr>
        """

    if not linhas_html:
        linhas_html = '<tr><td colspan="8">Nenhuma solicitação pendente de aprovação.</td></tr>'

    conteudo = f"""
    <h2>Fila de Aprovação</h2>
    <div style="font-size:12px; color:#666; margin-bottom:12px;">
        Clique em <strong>Abrir e avaliar</strong> para ver a solicitação completa, aprovar, reprovar ou devolver para ajuste.
    </div>
    <table style="max-width:1100px;">
        <tr><th>Protocolo</th><th>Data</th><th>Tipo</th><th>Solicitante</th><th>Coordenação</th>
            <th>Lote / Convênio</th><th>Valor</th><th>Ações</th></tr>
        {linhas_html}
    </table>
    {navegacao}
    """
    return render_pagina('Fila de Aprovação', conteudo)


@app.route('/solicitacao/<int:solicitacao_id>/aprovacao', methods=['POST'])
@login_required
def acao_aprovacao(solicitacao_id):
    if current_user.perfil not in ('aprovador',) and not current_user.is_organizador:
        abort(403)

    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)
    if solicitacao.status != 'pendente_aprovacao':
        flash('Esta solicitação não está mais na fase de aprovação.')
        return redirect(url_for('fila_aprovacao'))

    acao = request.form.get('acao')
    tipo_label = TIPO_SOLICITACAO_LABELS.get(solicitacao.tipo, solicitacao.tipo)
    solicitacao.ressalva_aprovador = (request.form.get('ressalva') or '').strip() or None

    # o Aprovador pode ajustar o convênio definido pelo Analista - às vezes a
    # despesa acaba sendo custeada por outro convênio
    novo_convenio = request.form.get('convenio')
    if novo_convenio and novo_convenio != solicitacao.convenio:
        convenio_anterior = solicitacao.convenio
        solicitacao.convenio = novo_convenio
        registrar_auditoria('alterou_convenio', solicitacao,
                            f'{convenio_anterior or "-"} -> {novo_convenio}')

    if acao == 'aprovar':
        solicitacao.status = 'aprovada'

        corpo_aprovacao = (
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'Sua solicitação de {tipo_label}, protocolo {protocolo(solicitacao)}, foi aprovada '
            f'e seguiu para execução.'
        )

        if solicitacao.tipo == 'diaria':
            diaria_aprovada = SolicitacaoDiaria.query.filter_by(solicitacao_id=solicitacao.id).first()
            if diaria_aprovada:
                from datetime import timedelta
                prazo_relatorio = diaria_aprovada.data_retorno + timedelta(days=PRAZO_PRESTACAO_DIAS)
                corpo_aprovacao += (
                    f'\n\nATENÇÃO - PRESTAÇÃO DE CONTAS: após a viagem, é obrigatório anexar o '
                    f'relatório de viagem no sistema, até {prazo_relatorio.strftime("%d/%m/%Y")} '
                    f'({PRAZO_PRESTACAO_DIAS} dias corridos após o retorno).\n\n'
                    f'Acesse "Minhas Solicitações", abra o protocolo {protocolo(solicitacao)} e utilize '
                    f'o bloco "Prestação de Contas" para anexar e enviar o relatório.'
                )
                solicitacao.aviso_conclusao = (
                    f'Prestação de contas obrigatória: anexe o relatório de viagem até '
                    f'{prazo_relatorio.strftime("%d/%m/%Y")}.'
                )

        registrar_auditoria('aprovou', solicitacao, f'Valor {moeda(solicitacao.valor_total)}')
        db.session.commit()

        notificar_solicitante(
            solicitacao,
            'Sua solicitação foi aprovada - SIGAD Carajás',
            corpo_aprovacao,
        )

        if solicitacao.tipo == 'bolsa':
            # Bolsa não segue para um Executor interno: o encaminhamento é
            # externo, para o e-mail do CTC informado pelo Analista na
            # triagem, com um PDF detalhando a solicitação.
            if solicitacao.email_ctc:
                bolsistas = BolsistaSolicitacao.query.filter_by(solicitacao_id=solicitacao.id).all()
                pdf_bytes = gerar_pdf_bolsa(solicitacao, bolsistas)

                corpo_ctc = (
                    f'O SIGAD Carajás informa que a solicitação de bolsa {protocolo(solicitacao)}, '
                    f'de {solicitacao.solicitante.nome}, foi analisada e aprovada nas instâncias '
                    f'competentes do NGI Carajás.\n\n'
                    f'Este e-mail autoriza o encaminhamento ao Comitê Técnico Científico para a '
                    f'efetivação da bolsa.\n\n'
                    f'Atividade/Projeto: {solicitacao.atividade_projeto or "-"}\n'
                    f'Convênio: {solicitacao.convenio or "-"}\n'
                    f'Lote de aprovação: {solicitacao.lote_aprovacao or "-"}\n'
                    f'Rubrica: {solicitacao.rubrica or "-"}\n'
                    f'Valor total: {moeda(solicitacao.valor_total)}\n\n'
                    f'Bolsistas:\n' + '\n'.join(
                        f'- {b.nome_bolsista} | {b.mes_inicio} a {b.mes_fim} '
                        f'({b.duracao_meses} meses) | {moeda(b.valor_total_bolsa)}'
                        for b in bolsistas
                    ) + (
                        '\n\nO detalhamento completo está no PDF anexo.' if pdf_bytes else ''
                    )
                )

                sucesso_ctc, detalhe_ctc = enviar_email(
                    solicitacao.email_ctc,
                    f'Bolsa aprovada - autorização de encaminhamento - {protocolo(solicitacao)}',
                    corpo_ctc,
                    anexo_nome=(f'bolsa_{protocolo(solicitacao)}.pdf' if pdf_bytes else None),
                    anexo_bytes=pdf_bytes,
                )
                if not sucesso_ctc:
                    print(f'[bolsa] falha ao notificar CTC ({solicitacao.email_ctc}): {detalhe_ctc}')

        elif solicitacao.responsavel_encaminhamento:
            enviar_email(
                solicitacao.responsavel_encaminhamento.email,
                'Demanda aprovada e sob sua responsabilidade - SIGAD Carajás',
                f'Olá, {solicitacao.responsavel_encaminhamento.nome}.\n\n'
                f'A solicitação de {tipo_label}, de {solicitacao.solicitante.nome}, protocolo '
                f'{protocolo(solicitacao)}, foi aprovada e está sob a sua responsabilidade para '
                f'encaminhamento.\n\n'
                f'Acesse o sistema em "Minhas Demandas / Execução" para definir o prazo de atendimento '
                f'e acompanhar o status até a conclusão.',
            )
        else:
            compradores = Usuario.query.filter_by(perfil='comprador').all()
            for comprador in compradores:
                enviar_email(
                    comprador.email,
                    'Nova solicitação aprovada para execução - SIGAD Carajás',
                    f'Olá, {comprador.nome}.\n\n'
                    f'A solicitação de {tipo_label}, protocolo {protocolo(solicitacao)}, foi aprovada '
                    f'e está aguardando execução, sem um responsável específico definido ainda.',
                )

        flash('Solicitação aprovada.', 'sucesso')
        return redirect(url_for('fila_aprovacao'))

    justificativa = (request.form.get('justificativa') or '').strip()

    if acao == 'reprovar':
        if not justificativa:
            flash('Informe a justificativa da reprovação.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        solicitacao.status = 'reprovada'
        solicitacao.motivo_reprovacao = justificativa
        solicitacao.reprovada_por = f'{current_user.nome} (Aprovador)'
        registrar_auditoria('reprovou_aprovacao', solicitacao, justificativa)
        db.session.commit()

        notificar_solicitante(
            solicitacao,
            'Sua solicitação foi reprovada - SIGAD Carajás',
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'Sua solicitação de {tipo_label}, protocolo {protocolo(solicitacao)}, foi reprovada '
            f'na etapa de aprovação.\n\n'
            f'Justificativa: {justificativa}\n\n'
            f'Se quiser esclarecer algo, procure o Aprovador responsável.',
        )

        flash('Solicitação reprovada e solicitante notificado.', 'sucesso')
        return redirect(url_for('fila_aprovacao'))

    if acao == 'devolver':
        if not justificativa:
            flash('Informe o ajuste necessário para devolver a solicitação.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        solicitacao.status = 'devolvida_ajuste'
        solicitacao.motivo_devolucao = justificativa
        registrar_auditoria('devolveu_aprovacao', solicitacao, justificativa)
        db.session.commit()

        notificar_solicitante(
            solicitacao,
            'Sua solicitação precisa de ajustes - SIGAD Carajás',
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'Sua solicitação de {tipo_label}, protocolo {protocolo(solicitacao)}, precisa de um '
            f'ajuste antes de seguir. Ela foi devolvida pelo Aprovador.\n\n'
            f'O que corrigir: {justificativa}\n\n'
            f'Acesse "Minhas Solicitações", corrija e reenvie.',
        )

        flash('Solicitação devolvida ao solicitante.', 'sucesso')
        return redirect(url_for('fila_aprovacao'))

    flash('Ação inválida.')
    return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))


# ---------------- FILA DO RESPONSÁVEL / EXECUÇÃO ----------------
STATUS_EM_ANDAMENTO = ('aprovada', 'em_execucao', 'enviado_pagamento', 'em_compra')
STATUS_CONCLUIDOS = ('paga', 'comprado')


@app.route('/execucao')
@login_required
def fila_execucao():
    eh_comprador = current_user.perfil == 'comprador' or current_user.is_organizador
    if not eh_comprador and not tem_demandas_atribuidas():
        abort(403)

    consulta = Solicitacao.query.options(
        joinedload(Solicitacao.solicitante),
        joinedload(Solicitacao.responsavel_encaminhamento),
    ).filter(Solicitacao.status.in_(STATUS_EM_ANDAMENTO + STATUS_CONCLUIDOS))

    # qualquer Executor (perfil comprador) ve TODAS as demandas, nao so as
    # atribuidas a ele - permite cobertura de equipe entre colegas
    if not current_user.is_organizador and current_user.perfil != 'comprador':
        consulta = consulta.filter(Solicitacao.responsavel_encaminhamento_id == current_user.id)

    filtro_protocolo = request.args.get('protocolo', '').strip()
    if filtro_protocolo:
        id_buscado = id_a_partir_do_protocolo(filtro_protocolo)
        consulta = consulta.filter(Solicitacao.id == (id_buscado or -1))

    solicitacoes, navegacao = paginar(consulta, Solicitacao.data_envio.desc(), 'fila_execucao')

    linhas_html = ''
    for s in solicitacoes:
        tipo_label = TIPO_SOLICITACAO_LABELS.get(s.tipo, s.tipo)
        status_label = STATUS_LABELS.get(s.status, s.status)
        responsavel = s.responsavel_encaminhamento.nome if s.responsavel_encaminhamento else '-'
        prazo = s.prazo_encaminhamento.strftime('%d/%m/%Y') if s.prazo_encaminhamento else '-'

        cores = {
            'aprovada': '#2b5876',
            'em_execucao': '#b35c00',
            'enviado_pagamento': '#5b6b76',
            'em_compra': '#5b6b76',
            'paga': '#2e7d32',
            'comprado': '#2e7d32',
        }
        cor = cores.get(s.status, '#555')

        alerta_boleto = ''
        if s.tipo == 'servico_externo_pf' and s.status not in ('paga',):
            if s.boleto_vencimento and not s.boleto_pago_em:
                dias = (s.boleto_vencimento - hoje()).days
                if dias < 0:
                    alerta_boleto = '<br><span style="font-size:10.5px; color:#c0392b; font-weight:bold;">Boleto vencido</span>'
                elif dias <= 3:
                    alerta_boleto = f'<br><span style="font-size:10.5px; color:#b35c00; font-weight:bold;">Boleto vence em {dias}d</span>'
            elif s.boleto_pago_em and not s.nf_pago_em:
                tem_nf = Anexo.query.filter_by(solicitacao_id=s.id, tipo_anexo='nota_fiscal').count()
                if tem_nf:
                    alerta_boleto = '<br><span style="font-size:10.5px; color:#2b5876; font-weight:bold;">NF aguardando pagamento</span>'
                else:
                    alerta_boleto = '<br><span style="font-size:10.5px; color:#b35c00; font-weight:bold;">Aguardando nota fiscal</span>'

        linhas_html += f"""
        <tr>
            <td style="font-family:monospace; font-size:12px;">{protocolo(s)}</td>
            <td>{s.data_envio.strftime('%d/%m/%Y')}</td>
            <td>{tipo_label}</td>
            <td>{s.solicitante.nome}</td>
            <td>{responsavel}</td>
            <td>{prazo}</td>
            <td style="color:{cor}; font-weight:bold; font-size:12px;">{status_label}{alerta_boleto}</td>
            <td>
                {moeda(s.valor_total)}
                {'<br><span style="font-size:11px; color:#2e7d32; font-weight:bold;">Real: ' + moeda(s.valor_real) + '</span>' if s.valor_real is not None else ''}
            </td>
            <td>
                <a href="{url_for('detalhe_solicitacao', solicitacao_id=s.id)}" class="btn btn-salvar"
                   style="text-decoration:none; display:inline-block;">Abrir</a>
            </td>
        </tr>
        """

    if not linhas_html:
        linhas_html = '<tr><td colspan="9">Nenhuma demanda sob sua responsabilidade no momento.</td></tr>'

    conteudo = f"""
    <h2>Minhas Demandas / Execução</h2>
    <div style="font-size:12px; color:#666; margin-bottom:12px;">
        Abra a demanda para definir o prazo de atendimento, atualizar o status e anexar o comprovante de pagamento.
        O solicitante acompanha cada mudança em "Minhas Solicitações".
    </div>
    <form method="GET" style="margin-bottom:14px; display:flex; gap:8px; align-items:center;">
        <input type="text" name="protocolo" value="{filtro_protocolo}" placeholder="Buscar por protocolo..."
               style="padding:7px; width:220px;">
        <button type="submit" class="btn-atalho">Filtrar</button>
        {f'<a href="{url_for("fila_execucao")}" class="btn-atalho">Limpar</a>' if filtro_protocolo else ''}
    </form>
    <table style="max-width:1200px;">
        <tr><th>Protocolo</th><th>Data</th><th>Tipo</th><th>Solicitante</th><th>Responsável</th>
            <th>Prazo</th><th>Status</th><th>Valor</th><th>Ações</th></tr>
        {linhas_html}
    </table>
    {navegacao}
    """
    return render_pagina('Minhas Demandas / Execução', conteudo)


def pode_executar(solicitacao):
    # qualquer Executor (perfil comprador) pode agir em qualquer demanda,
    # nao so na que esta atribuida a ele - permite cobertura de equipe
    # (ex: um colega ou a jovem aprendiz assume no lugar de quem normalmente
    # cuida daquela demanda)
    return current_user.is_organizador or current_user.perfil == 'comprador'


@app.route('/solicitacao/<int:solicitacao_id>/execucao', methods=['POST'])
@login_required
def acao_execucao(solicitacao_id):
    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)

    if not pode_executar(solicitacao):
        abort(403)

    if solicitacao.status not in STATUS_EM_ANDAMENTO:
        flash('Esta demanda não está em fase de encaminhamento.')
        return redirect(url_for('fila_execucao'))

    acao = request.form.get('acao')
    tipo_label = TIPO_SOLICITACAO_LABELS.get(solicitacao.tipo, solicitacao.tipo)

    if acao == 'definir_prazo':
        prazo = request.form.get('prazo_encaminhamento')
        if not prazo:
            flash('Informe o prazo para atendimento da demanda.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        solicitacao.prazo_encaminhamento = prazo
        solicitacao.data_previsao_execucao = prazo
        solicitacao.status = 'em_execucao'
        registrar_auditoria('definiu_prazo', solicitacao, f'Prazo para {prazo}')
        db.session.commit()

        notificar_solicitante(
            solicitacao,
            'Sua solicitação está em execução - SIGAD Carajás',
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'Sua solicitação de {tipo_label}, protocolo {protocolo(solicitacao)}, está em execução, '
            f'com prazo de atendimento previsto para '
            f'{solicitacao.prazo_encaminhamento.strftime("%d/%m/%Y")}.',
        )

        flash('Prazo definido e solicitante notificado.', 'sucesso')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    if acao == 'enviar_pagamento':
        solicitacao.status = 'enviado_pagamento'
        solicitacao.data_envio_pagamento = hoje()
        registrar_auditoria('enviou_pagamento', solicitacao)
        db.session.commit()

        notificar_solicitante(
            solicitacao,
            'Sua solicitação foi enviada para pagamento - SIGAD Carajás',
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'Sua solicitação de {tipo_label}, protocolo {protocolo(solicitacao)}, foi cadastrada '
            f'e enviada para pagamento.',
        )

        flash('Status atualizado para "Enviado para pagamento".', 'sucesso')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    if acao == 'devolver_solicitante':
        motivo = (request.form.get('motivo_ajuste') or '').strip()
        if not motivo:
            flash('Descreva o que o solicitante precisa corrigir.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        solicitacao.status_antes_ajuste = solicitacao.status
        solicitacao.status = 'ajuste_dados'
        solicitacao.motivo_ajuste_dados = f'{motivo} (devolvido por {current_user.nome})'
        registrar_auditoria('devolveu_executor', solicitacao, motivo)
        db.session.commit()

        notificar_solicitante(
            solicitacao,
            'Correção necessária na sua solicitação - SIGAD Carajás',
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'Sua solicitação de {tipo_label}, protocolo {protocolo(solicitacao)}, precisa de uma '
            f'correção de dados antes de ser concluída.\n\n'
            f'O que corrigir: {motivo}\n\n'
            f'Acesse "Minhas Solicitações", corrija os dados e reenvie. A solicitação volta direto '
            f'para o responsável pelo encaminhamento, sem passar novamente pela análise e pela aprovação.',
        )

        flash('Solicitação devolvida ao solicitante para correção.', 'sucesso')
        return redirect(url_for('fila_execucao'))

    if acao == 'em_compra':
        solicitacao.status = 'em_compra'
        solicitacao.data_envio_pagamento = hoje()
        registrar_auditoria('colocou_compra', solicitacao)
        db.session.commit()

        notificar_solicitante(
            solicitacao,
            'Sua solicitação está em compra - SIGAD Carajás',
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'Sua solicitação de {tipo_label}, protocolo {protocolo(solicitacao)}, está em processo de compra.',
        )

        flash('Status atualizado para "Em compra".', 'sucesso')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    if acao == 'marcar_comprado':
        try:
            valor_real = float(request.form.get('valor_real') or 0)
        except ValueError:
            valor_real = 0

        if valor_real <= 0:
            flash('Informe o valor real da compra para concluir a demanda.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        solicitacao.valor_real = valor_real

        arquivo = request.files.get('comprovante')
        if arquivo and arquivo.filename:
            salvar_anexo(solicitacao.id, arquivo, 'comprovante_compra')

        solicitacao.status = 'comprado'
        solicitacao.data_pagamento = hoje()

        corpo_email = (
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'Sua solicitação de {tipo_label}, protocolo {protocolo(solicitacao)}, foi comprada e está concluída.'
        )

        if solicitacao.tipo == 'passagem':
            passagem = SolicitacaoPassagem.query.filter_by(solicitacao_id=solicitacao.id).first()
            email_passageiro = passagem.email_passageiro if passagem else None
            nome_passageiro = passagem.nome_passageiro if passagem else 'o passageiro'

            if email_passageiro:
                aviso = (
                    f'A passagem foi comprada. O bilhete aéreo será encaminhado para o e-mail '
                    f'do passageiro {nome_passageiro}: {email_passageiro}'
                )
            else:
                aviso = 'A passagem foi comprada. O bilhete aéreo será encaminhado para o e-mail do passageiro.'

            solicitacao.aviso_conclusao = aviso
            corpo_email += f'\n\n{aviso}'

        registrar_auditoria('marcou_comprado', solicitacao,
                            f'Valor real {moeda(valor_real)} | estimado {moeda(solicitacao.valor_total)}')
        db.session.commit()

        notificar_solicitante(
            solicitacao,
            'Sua solicitação foi comprada - SIGAD Carajás',
            corpo_email,
        )

        flash('Demanda concluída como comprada.', 'sucesso')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    # --- Serviço Externo PF: etapa do BOLETO (1º pagamento) ---
    if acao == 'enviar_boleto_pagamento':
        if solicitacao.tipo != 'servico_externo_pf':
            abort(404)
        if not solicitacao.boleto_vencimento:
            flash('O solicitante ainda não anexou o boleto.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        solicitacao.status = 'enviado_pagamento'
        registrar_auditoria('enviou_boleto_pagamento', solicitacao, 'Boleto enviado para pagamento')
        db.session.commit()

        flash('Boleto enviado para pagamento.', 'sucesso')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    if acao == 'marcar_boleto_pago':
        if solicitacao.tipo != 'servico_externo_pf':
            abort(404)
        if solicitacao.status != 'enviado_pagamento' or solicitacao.boleto_pago_em:
            flash('Envie o boleto para pagamento antes de marcá-lo como pago.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        solicitacao.boleto_pago_em = hoje()
        # volta para "em execução": a demanda segue, agora aguardando a nota fiscal
        solicitacao.status = 'em_execucao'
        registrar_auditoria('pagou_boleto', solicitacao, f'Boleto pago em {hoje().strftime("%d/%m/%Y")}')
        db.session.commit()

        notificar_solicitante(
            solicitacao,
            'Boleto pago - envie a nota fiscal - SIGAD Carajás',
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'O boleto de arrecadação municipal da sua solicitação, protocolo {protocolo(solicitacao)}, '
            f'foi pago.\n\n'
            f'Acesse a solicitação e anexe a nota fiscal para que o pagamento seja concluído.',
        )

        flash('Boleto marcado como pago. O solicitante foi avisado para enviar a nota fiscal.', 'sucesso')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    # --- Serviço Externo PF: etapa da NOTA FISCAL (2º pagamento, conclui a demanda) ---
    if acao == 'enviar_nf_pagamento':
        if solicitacao.tipo != 'servico_externo_pf':
            abort(404)
        tem_nota_fiscal = Anexo.query.filter_by(
            solicitacao_id=solicitacao.id, tipo_anexo='nota_fiscal').count()
        if not tem_nota_fiscal:
            flash('O solicitante ainda não anexou a nota fiscal.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        solicitacao.status = 'enviado_pagamento'
        registrar_auditoria('enviou_nf_pagamento', solicitacao, 'Nota fiscal enviada para pagamento')
        db.session.commit()

        flash('Nota fiscal enviada para pagamento.', 'sucesso')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    if acao == 'marcar_nf_pago':
        if solicitacao.tipo != 'servico_externo_pf':
            abort(404)
        if not solicitacao.boleto_pago_em:
            flash('O boleto ainda não foi marcado como pago.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))
        if solicitacao.status != 'enviado_pagamento' or solicitacao.nf_pago_em:
            flash('Envie a nota fiscal para pagamento antes de marcá-la como paga.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        arquivo = request.files.get('comprovante')
        if not arquivo or not arquivo.filename:
            flash('Anexe o comprovante de pagamento da nota fiscal para concluir a demanda.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        salvar_anexo(solicitacao.id, arquivo, 'comprovante_pagamento')

        solicitacao.nf_pago_em = hoje()
        # o boleto já estava pago (verificado acima) - com a nota fiscal
        # também paga, a demanda está de fato concluída
        solicitacao.status = 'paga'
        solicitacao.data_pagamento = hoje()
        registrar_auditoria('pagou_nota_fiscal', solicitacao,
                            f'Nota fiscal paga em {hoje().strftime("%d/%m/%Y")} - demanda concluída')
        db.session.commit()

        notificar_solicitante(
            solicitacao,
            'Sua solicitação foi paga - SIGAD Carajás',
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'Sua solicitação de Serviço Externo (PF), protocolo {protocolo(solicitacao)}, foi concluída: '
            f'o boleto e a nota fiscal foram pagos. O comprovante está disponível no sistema.',
        )

        flash('Nota fiscal marcada como paga. Demanda concluída.', 'sucesso')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    if acao == 'marcar_paga':
        # o comprovante deixou de ser obrigatório aqui: o Executor pode marcar
        # como paga sem anexar nada. Se o solicitante precisar do comprovante
        # depois, ele solicita pelo sistema (ver rota solicitar_comprovante)
        arquivo = request.files.get('comprovante')
        tem_comprovante = bool(arquivo and arquivo.filename)
        if tem_comprovante:
            salvar_anexo(solicitacao.id, arquivo, 'comprovante_pagamento')

        solicitacao.status = 'paga'
        solicitacao.data_pagamento = hoje()
        registrar_auditoria('marcou_paga', solicitacao, f'Valor {moeda(solicitacao.valor_total)}')
        db.session.commit()

        aviso_comprovante = (
            'O comprovante de pagamento está disponível no sistema.' if tem_comprovante
            else 'Se precisar do comprovante de pagamento, você pode solicitá-lo pelo sistema.'
        )
        notificar_solicitante(
            solicitacao,
            'Sua solicitação foi paga - SIGAD Carajás',
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'Sua solicitação de {tipo_label}, protocolo {protocolo(solicitacao)}, foi paga. '
            f'{aviso_comprovante}',
        )

        flash('Demanda concluída' + (' e comprovante anexado.' if tem_comprovante else '.'), 'sucesso')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    flash('Ação inválida.')
    return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))


# ---------------- CADASTRO DE USUÁRIOS (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/usuarios')
@login_required
def cadastro_usuarios():
    somente_organizador_ou_analista()

    coordenacoes_disponiveis = Coordenacao.query.order_by(Coordenacao.nome).all()

    usuarios = Usuario.query.order_by(Usuario.nome).all()
    linhas_html = ''
    for u in usuarios:
        opcoes_perfil = ''
        for p in PERFIS_USUARIO:
            sel = 'selected' if u.perfil == p else ''
            opcoes_perfil += f'<option value="{p}" {sel}>{p.capitalize()}</option>'

        opcoes_coordenacao_linha = '<option value="">-</option>'
        for coord in coordenacoes_disponiveis:
            sel_coord = 'selected' if u.coordenacao_id == coord.id else ''
            opcoes_coordenacao_linha += f'<option value="{coord.id}" {sel_coord}>{coord.nome}</option>'

        # um Analista não pode editar a conta de um Administrador - evita
        # mostrar um formulário que o servidor vai recusar de qualquer forma
        pode_editar_esta_linha = current_user.is_organizador or not u.is_organizador

        if pode_editar_esta_linha:
            # ninguém exclui a própria conta nem, se não for Admin, a de um Administrador
            pode_excluir_esta_linha = (u.id != current_user.id) and (current_user.is_organizador or not u.is_organizador)
            botao_excluir = ''
            if pode_excluir_esta_linha:
                botao_excluir = f"""
                    <form method="POST" action="{url_for('cadastro_usuarios_excluir', usuario_id=u.id)}"
                          style="display:inline;" onsubmit="return confirm('Excluir o usuário {u.nome}? Só é possível se ele nunca tiver feito nenhuma solicitação.');">
                        <button type="submit" class="btn btn-excluir">Excluir</button>
                    </form>
                """

            linhas_html += f"""
            <tr>
                <form method="POST" action="{url_for('cadastro_usuarios_atualizar', usuario_id=u.id)}" style="display:contents;">
                <td><input type="text" name="nome" value="{u.nome}" style="width:170px; padding:4px;"></td>
                <td><input type="email" name="email" value="{u.email}" style="width:200px; padding:4px;"></td>
                <td><select name="perfil" style="padding:4px;">{opcoes_perfil}</select></td>
                <td><select name="coordenacao_id" style="padding:4px;">{opcoes_coordenacao_linha}</select></td>
                <td>{
                    f'<input type="checkbox" name="is_organizador" ' + ("checked" if u.is_organizador else "") + '> Admin'
                    if current_user.is_organizador else '-'
                }</td>
                <td style="white-space:nowrap;">
                    <button type="submit" class="btn btn-salvar">Salvar</button>
                </form>
                    <form method="POST" action="{url_for('redefinir_senha_admin', usuario_id=u.id)}"
                          style="display:inline;" onsubmit="return pedirSenha(this);">
                        <input type="hidden" name="nova_senha" class="campo-nova-senha">
                        <button type="button" class="btn" style="background:#b35c00; color:#fff;"
                                onclick="definirSenha(this)">Redefinir senha</button>
                    </form>
                    {botao_excluir}
                </td>
            </tr>
            """
        else:
            linhas_html += f"""
            <tr>
                <td>{u.nome}</td>
                <td>{u.email}</td>
                <td>{u.perfil.capitalize()}</td>
                <td>{u.coordenacao.nome if u.coordenacao else '-'}</td>
                <td><strong style="color:#37784D;">Admin</strong></td>
                <td style="font-size:11px; color:#888;">Somente o Administrador edita esta conta</td>
            </tr>
            """

    conteudo = f"""
    <h2>Usuários</h2>
    <table>
        <tr><th>Nome</th><th>E-mail</th><th>Perfil</th><th>Coordenação</th><th>Admin</th><th>Ações</th></tr>
        {linhas_html}
    </table>

    <script>
    function definirSenha(botao) {{
        var senha = prompt('Digite a nova senha para este usuário (mínimo {SENHA_MINIMA} caracteres):');
        if (senha === null) {{ return; }}
        if (senha.trim().length < {SENHA_MINIMA}) {{
            alert('A senha deve ter pelo menos {SENHA_MINIMA} caracteres.');
            return;
        }}
        var form = botao.closest('form');
        form.querySelector('.campo-nova-senha').value = senha.trim();
        form.submit();
    }}
    </script>

    <h3 style="margin-top:25px;">Adicionar novo usuário</h3>
    <form method="POST" action="{url_for('cadastro_usuarios_adicionar')}" style="max-width:400px;">
        <label>Nome:</label><br>
        <input type="text" name="nome" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <label>E-mail:</label><br>
        <input type="email" name="email" required style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <div style="font-size:11px; color:#888; margin-bottom:12px;">
            A senha é gerada automaticamente e enviada por e-mail para a pessoa, junto com uma
            explicação do que ela pode fazer no sistema, de acordo com o perfil escolhido abaixo.
            No primeiro acesso, ela é obrigada a trocar a senha.
        </div>

        <label>Perfil:</label><br>
        <select name="perfil" style="padding:6px; width:100%; margin-bottom:10px;">
            <option value="solicitante">Solicitante</option>
            <option value="analista">Analista</option>
            <option value="aprovador">Aprovador</option>
            <option value="comprador">Comprador/Executor</option>
        </select><br>

        <label>Coordenação:</label><br>
        <select name="coordenacao_id" style="padding:6px; width:100%; margin-bottom:10px;">
            <option value="">Selecione</option>
            {''.join(f'<option value="{c.id}">{c.nome}</option>' for c in coordenacoes_disponiveis)}
        </select><br>

        <button type="submit" class="btn btn-adicionar">Adicionar usuário</button>
    </form>
    """
    return render_pagina('Cadastro de Usuários', conteudo)


DESCRICAO_POR_PERFIL = {
    'solicitante': (
        'Como <b>Solicitante</b>, você pode registrar pedidos de: Diária, Passagem, Compra de '
        'Materiais, Rancho, Alimentação, Locação de Veículos, Serviço Externo (Pessoa Física e '
        'Jurídica), Seguro e Bolsa. Acompanhe o andamento de cada um em "Minhas Solicitações".'
    ),
    'analista': (
        'Como <b>Analista</b>, além de registrar solicitações como qualquer usuário, você faz a '
        'triagem inicial dos pedidos em "Fila de Análise" - conferindo os dados, definindo lote, '
        'convênio e o responsável pelo encaminhamento, antes de enviar para o Aprovador. '
        'Você também tem acesso às telas de Cadastros para manter atualizadas as tabelas de '
        'valores e categorias do sistema.'
    ),
    'aprovador': (
        'Como <b>Aprovador</b>, além de registrar solicitações como qualquer usuário, você avalia '
        'o mérito e o valor dos pedidos já triados, em "Fila de Aprovação" - aprovando, devolvendo '
        'para ajuste ou reprovando, sempre com justificativa.'
    ),
    'comprador': (
        'Como <b>Executor</b>, além de registrar solicitações como qualquer usuário, você conduz '
        'a execução das demandas já aprovadas, em "Minhas Demandas" - definindo prazo, realizando '
        'a compra ou o pagamento, e concluindo cada uma.'
    ),
}


def gerar_senha_temporaria(tamanho=10):
    """Gera uma senha aleatória seguindo boas práticas de segurança
    (letras maiúsculas, minúsculas, números - sem caracteres ambíguos como
    0/O ou l/1), para envio por e-mail no cadastro de um novo usuário."""
    alfabeto = 'ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789'
    return ''.join(secrets.choice(alfabeto) for _ in range(tamanho))


def enviar_email_boas_vindas(usuario, senha_temporaria):
    descricao = DESCRICAO_POR_PERFIL.get(usuario.perfil, DESCRICAO_POR_PERFIL['solicitante'])
    if usuario.is_organizador:
        descricao += (
            '\n\nVocê também tem acesso de <b>Administrador</b>: gerencia usuários, cadastros '
            'e configurações gerais do sistema.'
        )

    try:
        link_acesso = url_for('login', _external=True)
    except RuntimeError:
        # fora de um contexto de requisição (ex: script/console) - sem link, mas não quebra o envio
        link_acesso = None

    corpo = (
        f'Olá, {usuario.nome}.\n\n'
        f'Você foi cadastrado(a) no SIGAD Carajás - Sistema de Gestão Administrativa e de '
        f'Demandas.\n\n'
        f'{descricao}\n\n'
        f'Seus dados de acesso:\n'
        f'E-mail: {usuario.email}\n'
        f'Senha temporária: {senha_temporaria}\n\n'
        + (f'Acesse o sistema em: {link_acesso}\n\n' if link_acesso else '') +
        f'No primeiro acesso, o sistema vai pedir para você trocar essa senha por uma de sua '
        f'escolha, com pelo menos {SENHA_MINIMA} caracteres.\n\n'
        f'Qualquer dúvida sobre como usar o sistema, consulte a Central de Ajuda, disponível '
        f'no menu depois que você entrar.'
    )
    return enviar_email(usuario.email, 'Seu acesso ao SIGAD Carajás', corpo)


@app.route('/cadastros/usuarios/adicionar', methods=['POST'])
@login_required
def cadastro_usuarios_adicionar():
    somente_organizador_ou_analista()
    nome = request.form.get('nome', '').strip()
    email = request.form.get('email', '').strip()
    perfil = request.form.get('perfil', 'solicitante')
    marcado_admin = request.form.get('is_organizador') == 'on'

    if marcado_admin and not current_user.is_organizador:
        flash('Somente o Administrador pode conceder acesso de Administrador a um usuário.')
        return redirect(url_for('cadastro_usuarios'))

    if not nome or not email:
        flash('Nome e e-mail são obrigatórios.')
        return redirect(url_for('cadastro_usuarios'))

    if Usuario.query.filter_by(email=email).first():
        flash('Já existe um usuário com esse e-mail.')
        return redirect(url_for('cadastro_usuarios'))

    coordenacao_id = request.form.get('coordenacao_id') or None
    senha_temporaria = gerar_senha_temporaria()

    novo_usuario = Usuario(nome=nome, email=email, perfil=perfil, is_organizador=marcado_admin,
                           coordenacao_id=coordenacao_id, trocar_senha=True)
    novo_usuario.set_senha(senha_temporaria)
    db.session.add(novo_usuario)
    db.session.flush()
    registrar_auditoria('criou_usuario', None, f'{nome} ({email}) - perfil {perfil}')
    db.session.commit()

    sucesso_email, detalhe_email = enviar_email_boas_vindas(novo_usuario, senha_temporaria)

    if sucesso_email:
        flash(f'Usuário "{nome}" cadastrado. E-mail de boas-vindas enviado com a senha temporária.', 'sucesso')
    else:
        flash(f'Usuário "{nome}" cadastrado, mas o e-mail de boas-vindas não pôde ser enviado '
              f'({detalhe_email}). Use "Redefinir senha" para gerar uma nova senha e informe '
              f'a pessoa manualmente.')

    return redirect(url_for('cadastro_usuarios'))


@app.route('/cadastros/usuarios/<int:usuario_id>/redefinir-senha', methods=['POST'])
@login_required
def redefinir_senha_admin(usuario_id):
    somente_organizador_ou_analista()

    usuario = Usuario.query.get_or_404(usuario_id)
    nova_senha = (request.form.get('nova_senha') or '').strip()

    if len(nova_senha) < SENHA_MINIMA:
        flash(f'A senha deve ter pelo menos {SENHA_MINIMA} caracteres.')
        return redirect(url_for('cadastro_usuarios'))

    usuario.set_senha(nova_senha)
    usuario.token_senha = None
    usuario.token_expira = None
    registrar_auditoria('redefiniu_senha', None, f'Senha de {usuario.nome} redefinida')
    db.session.commit()

    enviar_email(
        usuario.email,
        'Sua senha foi redefinida - SIGAD Carajás',
        f'Olá, {usuario.nome}.\n\n'
        f'O administrador redefiniu a sua senha de acesso ao SIGAD Carajás.\n\n'
        f'Acesse o sistema e, em "Minha Conta", cadastre uma senha pessoal.',
    )

    flash(f'Senha de "{usuario.nome}" redefinida. Informe a nova senha diretamente à pessoa.', 'sucesso')
    return redirect(url_for('cadastro_usuarios'))


@app.route('/cadastros/usuarios/<int:usuario_id>/atualizar', methods=['POST'])
@login_required
def cadastro_usuarios_atualizar(usuario_id):
    somente_organizador_ou_analista()
    usuario = Usuario.query.get_or_404(usuario_id)

    if not current_user.is_organizador:
        if usuario.is_organizador:
            flash('Somente o Administrador pode editar a conta de outro Administrador.')
            return redirect(url_for('cadastro_usuarios'))
        if request.form.get('is_organizador') == 'on':
            flash('Somente o Administrador pode conceder acesso de Administrador a um usuário.')
            return redirect(url_for('cadastro_usuarios'))

    nome = (request.form.get('nome') or '').strip()
    email = (request.form.get('email') or '').strip().lower()

    if not nome or not email:
        flash('Nome e e-mail não podem ficar em branco.')
        return redirect(url_for('cadastro_usuarios'))

    email_em_uso = Usuario.query.filter(
        Usuario.email == email, Usuario.id != usuario.id).first()
    if email_em_uso:
        flash(f'Já existe outro usuário cadastrado com o e-mail "{email}".')
        return redirect(url_for('cadastro_usuarios'))

    dados_anteriores = f'{usuario.nome} <{usuario.email}>'
    usuario.nome = nome
    usuario.email = email

    perfil_anterior = usuario.perfil
    usuario.perfil = request.form.get('perfil')
    usuario.coordenacao_id = request.form.get('coordenacao_id') or None
    if current_user.is_organizador:
        usuario.is_organizador = request.form.get('is_organizador') == 'on'
    registrar_auditoria('alterou_usuario', None,
                        f'{dados_anteriores} -> {nome} <{email}> | perfil {perfil_anterior} -> {usuario.perfil}'
                        + (' | Admin' if usuario.is_organizador else ''))
    db.session.commit()
    flash('Usuário atualizado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_usuarios'))


@app.route('/cadastros/usuarios/<int:usuario_id>/excluir', methods=['POST'])
@login_required
def cadastro_usuarios_excluir(usuario_id):
    somente_organizador_ou_analista()
    usuario = Usuario.query.get_or_404(usuario_id)

    if usuario.id == current_user.id:
        flash('Você não pode excluir a própria conta.')
        return redirect(url_for('cadastro_usuarios'))

    if usuario.is_organizador and not current_user.is_organizador:
        flash('Somente o Administrador pode excluir a conta de outro Administrador.')
        return redirect(url_for('cadastro_usuarios'))

    # protege o histórico: um usuário que já solicitou ou já foi responsável
    # por alguma demanda não pode ser excluído, só teria a conta desativada
    # trocando o perfil, senão a solicitação ficaria com um dono inexistente
    tem_vinculo = Solicitacao.query.filter(
        db.or_(
            Solicitacao.solicitante_id == usuario.id,
            Solicitacao.responsavel_encaminhamento_id == usuario.id,
        )
    ).count()

    if tem_vinculo:
        flash(f'Não é possível excluir "{usuario.nome}": há {tem_vinculo} solicitação(ões) '
              f'vinculada(s) a esta conta (como solicitante ou responsável). Isso preserva o '
              f'histórico. Se a pessoa não usa mais o sistema, altere o perfil dela em vez de excluir.')
        return redirect(url_for('cadastro_usuarios'))

    nome_excluido = usuario.nome
    registrar_auditoria('excluiu_usuario', None, f'{nome_excluido} <{usuario.email}>')
    db.session.delete(usuario)
    db.session.commit()

    flash(f'Usuário "{nome_excluido}" excluído.', 'sucesso')
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
<div style="margin-bottom:14px;"><a href="/ajuda#diaria" target="_blank" class="btn-atalho">Dúvidas sobre diárias? Consulte a Central de Ajuda</a></div>
<form method="POST" enctype="multipart/form-data" style="max-width: 600px;" id="form-diaria">
    <input type="hidden" name="corrigir_id" value="">
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

    <label>
        <input type="checkbox" id="diaria_detalhada" name="diaria_detalhada" value="sim" style="width:auto;">
        A viagem tem parte em diária cheia e parte em meia diária (ex: alguns dias na base, outros fora)
    </label><br><br>

    <div id="bloco_tipo_diaria_simples">
        <label>Diária Cheia ou Meia? <span style="color:red;">*</span></label><br>
        <select name="tipo_diaria" id="tipo_diaria" style="padding:6px; margin-bottom:10px;">
            __OPCOES_DIARIA__
        </select><br>
    </div>

    <div id="bloco_diaria_mista" style="display:none;">
        <div class="bloco" style="border-left:4px solid #2b5876; background:#eef4f8;">
            <strong style="color:#2b5876;">Detalhamento por período</strong>
            <div style="font-size:11.5px; color:#666; margin:6px 0 10px;">
                Informe as datas de cada período. Cada dia entre início e fim é contado, incluindo os
                dois extremos. A soma dos dois períodos deve bater com o total de dias da viagem
                (contando o dia de ida e o de volta).
            </div>

            <label>Período de diária cheia:</label><br>
            <div style="display:flex; gap:8px; align-items:center; margin-bottom:4px;">
                <input type="date" name="periodo_cheia_inicio" id="periodo_cheia_inicio" style="padding:6px;">
                <span style="font-size:12px; color:#888;">até</span>
                <input type="date" name="periodo_cheia_fim" id="periodo_cheia_fim" style="padding:6px;">
            </div>
            <div style="font-size:11px; color:#888; margin-bottom:10px;">
                Total de diárias cheias: <strong id="total_dias_cheia">0</strong> dia(s)
            </div>

            <label>Período de meia diária:</label><br>
            <div style="display:flex; gap:8px; align-items:center; margin-bottom:4px;">
                <input type="date" name="periodo_meia_inicio" id="periodo_meia_inicio" style="padding:6px;">
                <span style="font-size:12px; color:#888;">até</span>
                <input type="date" name="periodo_meia_fim" id="periodo_meia_fim" style="padding:6px;">
            </div>
            <div style="font-size:11px; color:#888; margin-bottom:10px;">
                Total de meias diárias: <strong id="total_dias_meia">0</strong> dia(s)
            </div>

            <input type="hidden" name="qtd_diarias_cheias" id="qtd_diarias_cheias" value="0">
            <input type="hidden" name="qtd_diarias_meias" id="qtd_diarias_meias" value="0">

            <div style="font-size:12px; color:#004622; background:#fff; border:1px solid #cfe0d3; border-radius:5px; padding:8px 10px;">
                Total de dias da viagem (ida à volta, contando os dois extremos):
                <strong id="texto_total_dias_viagem">0</strong>
            </div>

            <div id="aviso_soma_diarias" style="display:none; font-size:11.5px; color:#b35c00; margin-top:8px; font-weight:bold;">
            </div>
        </div>
    </div>

    <div id="bloco_pernoites_simples">
        <label>Número de pernoites (calculado automaticamente):</label><br>
        <input type="number" name="numero_pernoites" id="numero_pernoites" min="0" readonly style="padding:6px; margin-bottom:10px; background:#f5f5f5; width:100px;"><br>
    </div>

    <div id="bloco_valor_simples">
        <label>Valor unitário da diária (R$):</label><br>
        <input type="text" id="valor_diaria_display" readonly style="padding:6px; margin-bottom:10px; background:#f5f5f5; width:120px;" value="0,00"><br>
    </div>

    <label>Valor total das diárias (R$):</label><br>
    <input type="text" id="valor_diarias_total" readonly style="padding:6px; margin-bottom:6px; background:#f5f5f5; width:150px;" value="0,00"><br>
    <div style="font-size:11px; color:#888; margin-bottom:10px;">
        <span id="legenda_valor_simples">Valor unitário multiplicado pelo número de pernoites. Viagem sem pernoite conta como uma diária.</span>
        <span id="legenda_valor_misto" style="display:none;">(diárias cheias x valor cheia) + (diárias meias x valor meia), calculado automaticamente pela área selecionada.</span>
    </div>

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

    <h3>Diaristas</h3>
    <div style="font-size:11.5px; color:#666; margin-bottom:10px;">
        Adicione um bloco para cada pessoa que vai receber a diária. Todos compartilham a mesma
        viagem (datas, origem, destino e detalhamento cheia/meia informados acima).
    </div>
    <div id="diaristas-container"></div>
    <button type="button" id="btn-adicionar-diarista" class="btn-atalho" style="margin-top:8px; margin-bottom:15px;">
        + Adicionar diarista
    </button>

    <template id="template-diarista">
        <div class="bloco-diarista bloco" style="margin-bottom:15px;">
            <strong>Diarista <span class="numero-diarista"></span></strong>
            <button type="button" class="btn btn-excluir btn-remover-diarista" style="float:right; padding:4px 10px;">Remover</button>
            <div style="clear:both;"></div>

            <label>Nome do diarista: <span style="color:red;">*</span></label><br>
            <input type="text" name="nome_diarista[]" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

            <label>CPF: <span style="color:red;">*</span></label><br>
            <input type="text" name="cpf_diarista[]" class="campo-cpf-diarista" required placeholder="000.000.000-00"
                   maxlength="14" inputmode="numeric"
                   style="padding:6px; margin-bottom:10px; width:190px;"><br>
            <div class="alerta-prestacao" style="display:none; background:#fdeceb; border-left:4px solid #c0392b;
                 color:#a02020; padding:11px 14px; border-radius:5px; font-size:12.5px; margin-bottom:12px;"></div>

            <label>Telefone: <span style="color:red;">*</span></label><br>
            <div style="display:flex; gap:8px; margin-bottom:10px;">
                <input type="text" name="ddd_diarista[]" required placeholder="DDD" style="width:80px; padding:6px;">
                <input type="text" name="telefone_diarista[]" required placeholder="99999-9999" style="width:180px; padding:6px;">
            </div>

            <label>E-mail:</label><br>
            <input type="email" name="email_diarista[]" style="width:100%; padding:6px; margin-bottom:10px;"><br>

            <label>Banco: <span style="color:red;">*</span></label><br>
            <input type="text" name="banco_diarista[]" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

            <label>Agência: <span style="color:red;">*</span></label><br>
            <input type="text" name="agencia_diarista[]" required style="padding:6px; margin-bottom:10px; width:150px;"><br>

            <label>Conta: <span style="color:red;">*</span></label><br>
            <input type="text" name="conta_diarista[]" required style="padding:6px; margin-bottom:10px; width:200px;"><br>

            <label>Chave PIX: <span style="color:red;">*</span></label><br>
            <input type="text" name="chave_pix[]" required style="width:100%; padding:6px;"><br>
        </div>
    </template>

    <div class="bloco" style="border-left:4px solid #37784D;">
        <strong style="font-size:13px; color:#004622;">Valor total da solicitação</strong>
        <div style="font-size:22px; font-weight:700; color:#004622; margin-top:6px;"
             id="valor_total_geral">R$ 0,00</div>
        <div style="font-size:11px; color:#888; margin-top:4px;">
            Diárias mais auxílio deslocamento, quando houver.
        </div>
    </div>

    <div class="bloco" style="background:#f7faf6; border-left:4px solid #A0C517;">
        <strong style="font-size:13px; color:#004622;">Prestação de contas</strong>
        <div style="font-size:12px; color:#555; margin-top:6px; line-height:1.5;">
            O relatório de viagem <strong>não é anexado agora</strong>. Após a aprovação da diária,
            esta solicitação passa a exibir, em <strong>Minhas Solicitações</strong>, o bloco para anexar
            e enviar o relatório. O envio é <strong>obrigatório</strong> em até
            __PRAZO_PRESTACAO__ dias corridos após a data de retorno da viagem.
        </div>
    </div>

    <button type="submit" style="padding:10px 20px; background:#37784D; color:white; border:none; border-radius:4px; cursor:pointer; font-weight:600;">Enviar solicitação</button>
</form>

<script>
var VALOR_AUXILIO = __VALOR_AUXILIO__;

var valorUnitarioDiaria = 0;
var valorUnitarioCheia = 0;
var valorUnitarioMeia = 0;

function formatarBRL(valor) {
    return valor.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function modoDetalhado() {
    return document.getElementById('diaria_detalhada').checked;
}

function alternarModoDiaria() {
    var detalhado = modoDetalhado();
    document.getElementById('bloco_tipo_diaria_simples').style.display = detalhado ? 'none' : 'block';
    document.getElementById('bloco_diaria_mista').style.display = detalhado ? 'block' : 'none';
    document.getElementById('bloco_valor_simples').style.display = detalhado ? 'none' : 'block';
    document.getElementById('legenda_valor_simples').style.display = detalhado ? 'none' : 'inline';
    document.getElementById('legenda_valor_misto').style.display = detalhado ? 'inline' : 'none';
    // no modo detalhado, "Total de dias da viagem" já mostra o número que
    // importa - esconder "pernoites" evita dois totais parecidos na tela
    document.getElementById('bloco_pernoites_simples').style.display = detalhado ? 'none' : 'block';

    var campoTipo = document.getElementById('tipo_diaria');
    campoTipo.required = !detalhado;

    if (detalhado) { atualizarValoresMistos(); } else { atualizarValorDiaria(); }
}

function atualizarValoresMistos() {
    var tipoDestino = document.getElementById('tipo_destino').value;
    if (!tipoDestino) { return; }

    Promise.all([
        fetch('/api/valor-diaria?tipo_destino=' + encodeURIComponent(tipoDestino) + '&tipo_diaria=Cheia').then(r => r.json()),
        fetch('/api/valor-diaria?tipo_destino=' + encodeURIComponent(tipoDestino) + '&tipo_diaria=Meia').then(r => r.json()),
    ]).then(function (resultados) {
        valorUnitarioCheia = resultados[0].valor;
        valorUnitarioMeia = resultados[1].valor;
        recalcularTotais();
    });
}

function diasEntre(dataInicioStr, dataFimStr) {
    // conta NOITES (data fim menos data início, sem somar +1)
    if (!dataInicioStr || !dataFimStr) { return 0; }
    var inicio = new Date(dataInicioStr + 'T00:00:00');
    var fim = new Date(dataFimStr + 'T00:00:00');
    var dias = Math.round((fim - inicio) / 86400000);
    return dias > 0 ? dias : 0;
}

function diasInclusive(dataInicioStr, dataFimStr) {
    // conta DIAS CORRIDOS incluindo o dia inicial e o final (ex: 26 a 28 =
    // 3 dias). Usado para os períodos de cheia/meia, que são digitados
    // diretamente pelo solicitante e não devem se sobrepor.
    if (!dataInicioStr || !dataFimStr) { return 0; }
    var inicio = new Date(dataInicioStr + 'T00:00:00');
    var fim = new Date(dataFimStr + 'T00:00:00');
    var dias = Math.round((fim - inicio) / 86400000) + 1;
    return dias > 0 ? dias : 0;
}

function recalcularTotais() {
    var pernoites = parseInt(document.getElementById('numero_pernoites').value) || 0;
    var totalDiarias = 0;
    var avisoSoma = document.getElementById('aviso_soma_diarias');

    if (modoDetalhado()) {
        // cada período é contado incluindo os dois extremos (ex: 26 a 28 =
        // 3 dias). Isso é comparado com o TOTAL DE DIAS DA VIAGEM, também
        // incluindo ida e volta - uma conta diferente de "número de
        // pernoites" (que não inclui o dia da volta).
        var dataIda = document.getElementById('data_ida').value;
        var dataRetorno = document.getElementById('data_retorno').value;
        var totalDiasViagem = dataIda && dataRetorno ? (diasEntre(dataIda, dataRetorno) + 1) : 0;
        document.getElementById('texto_total_dias_viagem').textContent = totalDiasViagem;

        var qtdCheias = diasInclusive(
            document.getElementById('periodo_cheia_inicio').value,
            document.getElementById('periodo_cheia_fim').value
        );
        var qtdMeias = diasInclusive(
            document.getElementById('periodo_meia_inicio').value,
            document.getElementById('periodo_meia_fim').value
        );

        document.getElementById('qtd_diarias_cheias').value = qtdCheias;
        document.getElementById('qtd_diarias_meias').value = qtdMeias;
        document.getElementById('total_dias_cheia').textContent = qtdCheias;
        document.getElementById('total_dias_meia').textContent = qtdMeias;

        totalDiarias = (qtdCheias * valorUnitarioCheia) + (qtdMeias * valorUnitarioMeia);

        if (totalDiasViagem > 0 && (qtdCheias + qtdMeias) !== totalDiasViagem) {
            avisoSoma.textContent = 'Cheia (' + qtdCheias + ') + Meia (' + qtdMeias + ') = ' +
                (qtdCheias + qtdMeias) + ' dia(s), mas a viagem tem ' + totalDiasViagem +
                ' dia(s) no total (de ' + dataIda.split('-').reverse().join('/') + ' a ' +
                dataRetorno.split('-').reverse().join('/') + '). Confira as datas dos dois períodos.';
            avisoSoma.style.display = 'block';
        } else {
            avisoSoma.style.display = 'none';
        }
    } else {
        var quantidade = pernoites > 0 ? pernoites : 1;
        totalDiarias = valorUnitarioDiaria * quantidade;
        if (avisoSoma) { avisoSoma.style.display = 'none'; }
    }

    var totalAuxilio = 0;
    if (document.getElementById('tera_auxilio').value === 'sim') {
        var qtdAux = parseInt(document.getElementById('quantidade_auxilio').value) || 0;
        totalAuxilio = qtdAux * VALOR_AUXILIO;
    }

    document.getElementById('valor_diarias_total').value = formatarBRL(totalDiarias);
    document.getElementById('valor_total_geral').textContent =
        'R$ ' + formatarBRL(totalDiarias + totalAuxilio);
}

function atualizarValorDiaria() {
    var tipoDestino = document.getElementById('tipo_destino').value;
    var tipoDiaria = document.getElementById('tipo_diaria').value;
    fetch('/api/valor-diaria?tipo_destino=' + encodeURIComponent(tipoDestino) + '&tipo_diaria=' + encodeURIComponent(tipoDiaria))
        .then(function(resposta) { return resposta.json(); })
        .then(function(dados) {
            valorUnitarioDiaria = dados.valor;
            document.getElementById('valor_diaria_display').value = formatarBRL(dados.valor);
            recalcularTotais();
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
    recalcularTotais();
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
    document.getElementById('valor_auxilio_display').value = formatarBRL(valorTotal);
    recalcularTotais();
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

document.getElementById('tipo_destino').addEventListener('change', function () {
    if (modoDetalhado()) { atualizarValoresMistos(); } else { atualizarValorDiaria(); }
});
document.getElementById('tipo_diaria').addEventListener('change', atualizarValorDiaria);
document.getElementById('diaria_detalhada').addEventListener('change', alternarModoDiaria);
document.getElementById('periodo_cheia_inicio').addEventListener('change', recalcularTotais);
document.getElementById('periodo_cheia_fim').addEventListener('change', recalcularTotais);
document.getElementById('periodo_meia_inicio').addEventListener('change', recalcularTotais);
document.getElementById('periodo_meia_fim').addEventListener('change', recalcularTotais);
document.getElementById('data_ida').addEventListener('change', calcularPernoites);
document.getElementById('data_retorno').addEventListener('change', calcularPernoites);
document.getElementById('tera_auxilio').addEventListener('change', atualizarBlocoAuxilio);
document.getElementById('quantidade_auxilio').addEventListener('input', atualizarQuantidadeAuxilio);

window.alternarModoDiaria = alternarModoDiaria;
window.atualizarValoresMistos = atualizarValoresMistos;

function configurarChecagemCpf(bloco) {
    var campoCpf = bloco.querySelector('.campo-cpf-diarista');
    var alertaPrestacao = bloco.querySelector('.alerta-prestacao');

    campoCpf.addEventListener('blur', function() {
        var cpf = campoCpf.value.replace(/[^0-9]/g, '');
        if (cpf.length !== 11) {
            alertaPrestacao.style.display = 'none';
            campoCpf.dataset.bloqueado = 'nao';
            return;
        }

        fetch('/api/verificar-prestacao?cpf=' + cpf)
            .then(function(resposta) { return resposta.json(); })
            .then(function(dados) {
                if (!dados.pendentes || dados.pendentes.length === 0) {
                    alertaPrestacao.style.display = 'none';
                    campoCpf.dataset.bloqueado = 'nao';
                    return;
                }
                var itens = dados.pendentes.map(function(p) {
                    return '<li>Protocolo <strong>' + p.protocolo + '</strong> - retorno em ' + p.retorno + '</li>';
                }).join('');

                if (dados.bloqueado) {
                    alertaPrestacao.innerHTML =
                        '<strong>Envio bloqueado: este CPF tem uma diária anterior sem relatório de viagem entregue.</strong>' +
                        '<ul style="margin:7px 0 7px 18px; padding:0;">' + itens + '</ul>' +
                        'Uma nova diária só pode ser solicitada para este CPF depois que o relatório de ' +
                        'viagem da diária anterior for <strong>enviado</strong> no sistema.';
                    alertaPrestacao.style.background = '#fdeceb';
                    alertaPrestacao.style.borderLeftColor = '#c0392b';
                    alertaPrestacao.style.color = '#a02020';
                    campoCpf.dataset.bloqueado = 'sim';
                } else {
                    campoCpf.dataset.bloqueado = 'nao';
                }
                alertaPrestacao.style.display = 'block';
            })
            .catch(function() { alertaPrestacao.style.display = 'none'; campoCpf.dataset.bloqueado = 'nao'; });
    });
}

var contadorDiaristas = 0;

function renumerarDiaristas() {
    var blocos = document.querySelectorAll('.bloco-diarista');
    blocos.forEach(function(bloco, indice) {
        bloco.querySelector('.numero-diarista').textContent = indice + 1;
    });
}

function criarBlocoDiarista() {
    contadorDiaristas++;
    var template = document.getElementById('template-diarista');
    var clone = template.content.cloneNode(true);
    var bloco = clone.querySelector('.bloco-diarista');

    configurarChecagemCpf(bloco);

    clone.querySelector('.btn-remover-diarista').addEventListener('click', function() {
        if (document.querySelectorAll('.bloco-diarista').length === 1) {
            alert('A solicitação precisa ter pelo menos um diarista.');
            return;
        }
        bloco.remove();
        renumerarDiaristas();
    });

    document.getElementById('diaristas-container').appendChild(clone);
    renumerarDiaristas();
}
window.criarBlocoDiarista = criarBlocoDiarista;

document.getElementById('btn-adicionar-diarista').addEventListener('click', criarBlocoDiarista);

document.getElementById('form-diaria').addEventListener('submit', function (evento) {
    if (document.querySelectorAll('.bloco-diarista').length === 0) {
        evento.preventDefault();
        alert('Adicione pelo menos um diarista à solicitação.');
        return;
    }
    var algumBloqueado = false;
    document.querySelectorAll('.campo-cpf-diarista').forEach(function (campo) {
        if (campo.dataset.bloqueado === 'sim') { algumBloqueado = true; }
    });
    if (algumBloqueado) {
        evento.preventDefault();
        alert('Não é possível enviar: pelo menos um CPF informado tem uma diária anterior sem relatório de viagem entregue.');
    }
});

if (!window.__RESTAURAR_FORM__) { criarBlocoDiarista(); }

// expõe as funções para que a restauração do formulário possa reexecutá-las
window.calcularPernoites = calcularPernoites;
window.recalcularTotais = recalcularTotais;
window.atualizarValorDiaria = atualizarValorDiaria;
window.atualizarBlocoAuxilio = atualizarBlocoAuxilio;
window.atualizarQuantidadeAuxilio = atualizarQuantidadeAuxilio;

atualizarValorDiaria();
atualizarBlocoAuxilio();
recalcularTotais();
</script>
"""


def montar_formulario_diaria():
    html = DIARIA_FORM_TEMPLATE.replace('__OPCOES_AREAS__', montar_opcoes_areas())
    html = html.replace('__OPCOES_DIARIA__', montar_opcoes(TIPOS_DIARIA))
    html = html.replace('__OPCOES_ESTADOS__', montar_opcoes_estados())
    html = html.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    html = html.replace('__VALOR_AUXILIO__',
                        str(obter_configuracao(CHAVE_VALOR_AUXILIO, VALOR_AUXILIO_PADRAO)))
    html = html.replace('__PRAZO_PRESTACAO__', str(PRAZO_PRESTACAO_DIAS))
    return html


@app.route('/solicitacao/diaria', methods=['GET', 'POST'])
@login_required
def diaria_form():
    resultado_bloqueio = bloquear_se_travado()
    if resultado_bloqueio:
        return resultado_bloqueio

    if request.method == 'POST':
        tipo_destino = request.form.get('tipo_destino')
        diaria_detalhada = request.form.get('diaria_detalhada') == 'sim'

        def parse_data(data_str):
            if not data_str:
                return None
            try:
                return datetime.strptime(data_str, '%Y-%m-%d').date()
            except ValueError:
                return None

        if diaria_detalhada:
            # o solicitante digita as datas reais de cada período. Cada
            # período conta os dias incluindo os dois extremos (26 a 28 =
            # 3 dias) - comparado aqui contra o TOTAL DE DIAS DA VIAGEM
            # (também incluindo ida e volta), não contra "pernoites" (que é
            # uma conta diferente, sem o dia da volta). Tudo recalculado no
            # servidor, não confiando no que veio do navegador.
            d_ida = parse_data(request.form.get('data_ida'))
            d_retorno = parse_data(request.form.get('data_retorno'))

            if not (d_ida and d_retorno):
                flash('Informe a data de ida e a data de retorno.')
                return render_pagina('Solicitação de Diária',
                                     preservar_preenchimento(montar_formulario_diaria(), request.form))

            total_dias_viagem = (d_retorno - d_ida).days + 1

            periodo_cheia_ini = parse_data(request.form.get('periodo_cheia_inicio'))
            periodo_cheia_fim = parse_data(request.form.get('periodo_cheia_fim'))
            periodo_meia_ini = parse_data(request.form.get('periodo_meia_inicio'))
            periodo_meia_fim = parse_data(request.form.get('periodo_meia_fim'))

            qtd_cheias = (periodo_cheia_fim - periodo_cheia_ini).days + 1 \
                if periodo_cheia_ini and periodo_cheia_fim else 0
            qtd_meias = (periodo_meia_fim - periodo_meia_ini).days + 1 \
                if periodo_meia_ini and periodo_meia_fim else 0
            qtd_cheias = max(qtd_cheias, 0)
            qtd_meias = max(qtd_meias, 0)

            if qtd_cheias + qtd_meias <= 0:
                flash('Informe ao menos um período de diária cheia ou meia.')
                return render_pagina('Solicitação de Diária',
                                     preservar_preenchimento(montar_formulario_diaria(), request.form))

            if (qtd_cheias + qtd_meias) != total_dias_viagem:
                flash(f'Cheia ({qtd_cheias}) + Meia ({qtd_meias}) = {qtd_cheias + qtd_meias} dia(s), '
                      f'mas a viagem tem {total_dias_viagem} dia(s) no total (de '
                      f'{d_ida.strftime("%d/%m/%Y")} a {d_retorno.strftime("%d/%m/%Y")}). '
                      f'Confira as datas dos dois períodos.')
                return render_pagina('Solicitação de Diária',
                                     preservar_preenchimento(montar_formulario_diaria(), request.form))

            valor_unit_cheia = obter_valor_diaria('Cheia', tipo_destino)
            valor_unit_meia = obter_valor_diaria('Meia', tipo_destino)
            tipo_diaria = 'Mista'
            valor_diaria = 0  # não se aplica no modo detalhado - ver valor_total_diarias abaixo
        else:
            tipo_diaria = request.form.get('tipo_diaria')
            valor_diaria = obter_valor_diaria(tipo_diaria, tipo_destino)
            qtd_cheias = qtd_meias = 0
            valor_unit_cheia = valor_unit_meia = 0
            periodo_cheia_ini = periodo_cheia_fim = periodo_meia_ini = periodo_meia_fim = None

        tera_auxilio = request.form.get('tera_auxilio') == 'sim'
        quantidade_auxilio = int(request.form.get('quantidade_auxilio') or 0) if tera_auxilio else 0
        justificativa_auxilio = request.form.get('justificativa_auxilio', '').strip()

        if tera_auxilio and quantidade_auxilio > 1 and not justificativa_auxilio:
            flash('Justificativa é obrigatória quando a solicitação tem mais de um Auxílio Deslocamento.')
            return render_pagina('Solicitação de Diária',
                                 preservar_preenchimento(montar_formulario_diaria(), request.form))

        valor_auxilio_unitario = obter_configuracao(CHAVE_VALOR_AUXILIO, VALOR_AUXILIO_PADRAO)
        valor_auxilio_total = quantidade_auxilio * valor_auxilio_unitario if tera_auxilio else 0

        # o valor da diária é unitário: multiplica pela quantidade de diárias.
        # viagem sem pernoite conta como 1 diária (meia diária, tipicamente).
        pernoites = int(request.form.get('numero_pernoites') or 0)
        quantidade_diarias = pernoites if pernoites > 0 else 1

        if diaria_detalhada:
            # no modo detalhado, o total das diárias vem da soma de cheias e
            # meias, não do valor unitário único. A soma sempre bate com os
            # pernoites por construção (a data de transição divide o mesmo
            # intervalo em duas partes complementares).
            valor_total_diarias_unitario = (qtd_cheias * valor_unit_cheia) + (qtd_meias * valor_unit_meia)
        else:
            valor_total_diarias_unitario = valor_diaria * quantidade_diarias

        # cada diarista recebe o mesmo valor de diária (mesma viagem, mesmo
        # detalhamento) mais o auxílio deslocamento, também compartilhado
        valor_por_diarista = valor_total_diarias_unitario + valor_auxilio_total

        nomes = request.form.getlist('nome_diarista[]')
        cpfs = request.form.getlist('cpf_diarista[]')
        ddds = request.form.getlist('ddd_diarista[]')
        telefones = request.form.getlist('telefone_diarista[]')
        emails = request.form.getlist('email_diarista[]')
        bancos = request.form.getlist('banco_diarista[]')
        agencias = request.form.getlist('agencia_diarista[]')
        contas = request.form.getlist('conta_diarista[]')
        chaves_pix = request.form.getlist('chave_pix[]')

        def pegar(lista, i):
            return lista[i] if i < len(lista) else ''

        diaristas_validados = []
        for i in range(len(nomes)):
            nome = (nomes[i] or '').strip()
            if not nome:
                continue

            cpf_atual = pegar(cpfs, i)
            if not cpf_tem_11_digitos(cpf_atual):
                flash(f'CPF inválido para o diarista "{nome}". Informe 11 dígitos, '
                      f'no formato 000.000.000-00.')
                return render_pagina('Solicitação de Diária',
                                     preservar_preenchimento(montar_formulario_diaria(), request.form))

            bloqueantes = prestacoes_nao_aprovadas_por_cpf(cpf_atual)
            if bloqueantes:
                protocolos = ', '.join(protocolo(sol) for sol, dia in bloqueantes)
                flash(f'Não é possível enviar: o CPF de "{nome}" tem uma diária anterior sem '
                      f'relatório de viagem entregue ({protocolos}). Envie o relatório de viagem '
                      f'da diária anterior antes de solicitar uma nova para esta pessoa.')
                return render_pagina('Solicitação de Diária',
                                     preservar_preenchimento(montar_formulario_diaria(), request.form))

            telefone_ok, telefone_atual = montar_telefone(pegar(ddds, i), pegar(telefones, i))
            if not telefone_ok:
                flash(f'Informe o telefone de "{nome}": DDD com 2 dígitos e número com 8 ou 9 dígitos.')
                return render_pagina('Solicitação de Diária',
                                     preservar_preenchimento(montar_formulario_diaria(), request.form))

            diaristas_validados.append({
                'nome_diarista': nome,
                'cpf_diarista': formatar_cpf(cpf_atual),
                'telefone_diarista': telefone_atual,
                'email_diarista': pegar(emails, i),
                'banco_diarista': pegar(bancos, i),
                'agencia_diarista': pegar(agencias, i),
                'conta_diarista': pegar(contas, i),
                'chave_pix': pegar(chaves_pix, i),
            })

        if not diaristas_validados:
            flash('Adicione pelo menos um diarista à solicitação.')
            return render_pagina('Solicitação de Diária',
                                 preservar_preenchimento(montar_formulario_diaria(), request.form))

        valor_total_solicitacao = valor_por_diarista * len(diaristas_validados)

        solicitacao, era_correcao = obter_solicitacao_para_gravar(
            'diaria',
            atividade_id=request.form.get('atividade_id') or None,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=valor_total_solicitacao,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
        )
        if era_correcao:
            SolicitacaoDiaria.query.filter_by(solicitacao_id=solicitacao.id).delete()

        for dados_diarista in diaristas_validados:
            diaria = SolicitacaoDiaria(
                solicitacao_id=solicitacao.id,
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
                diaria_detalhada=diaria_detalhada,
                qtd_diarias_cheias=qtd_cheias,
                qtd_diarias_meias=qtd_meias,
                valor_unitario_cheia=valor_unit_cheia,
                valor_unitario_meia=valor_unit_meia,
                periodo_cheia_inicio=periodo_cheia_ini,
                periodo_cheia_fim=periodo_cheia_fim,
                periodo_meia_inicio=periodo_meia_ini,
                periodo_meia_fim=periodo_meia_fim,
                tera_auxilio_deslocamento=tera_auxilio,
                quantidade_auxilio=quantidade_auxilio,
                valor_auxilio=valor_auxilio_total,
                justificativa_auxilio=justificativa_auxilio,
                justificativa=request.form.get('justificativa'),
                **dados_diarista,
            )
            db.session.add(diaria)

        db.session.commit()
        if era_correcao:
            flash(f'Solicitação corrigida e reenviada, protocolo {protocolo(solicitacao)}!', 'sucesso')
        else:
            flash(f'Solicitação de diária enviada com sucesso para {len(diaristas_validados)} '
                  f'diarista(s)!', 'sucesso')
        return redirect(url_for('inicio'))

    solicitacao_corrigindo = carregar_solicitacao_para_correcao(request.args.get('corrigir_id'))
    if solicitacao_corrigindo:
        dados_edicao = _dados_edicao_diaria(solicitacao_corrigindo)
        if dados_edicao:
            return render_pagina('Solicitação de Diária',
                                 preservar_preenchimento(montar_formulario_diaria(), dados_edicao))

    return render_pagina('Solicitação de Diária', com_vinculo_atividade(montar_formulario_diaria()))


# ---------------- SOLICITAÇÃO: PASSAGEM ----------------
PASSAGEM_FORM_TEMPLATE = """
<div style="margin-bottom:14px;">
<a href="/ajuda#passagem" target="_blank" class="btn-atalho">Dúvidas sobre passagens? Consulte a Central de Ajuda</a></div>

<form method="POST" style="max-width: 760px;" id="form-passagem">
    <input type="hidden" name="corrigir_id" value="">
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

    <h3>Dados da viagem</h3>
    <div style="font-size:11px; color:#888; margin-bottom:10px;">
        Estes dados valem para todos os passageiros da solicitação.
    </div>

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

    <label>Justificativa: <span style="color:red;">*</span></label><br>
    <textarea name="justificativa" required style="width:100%; padding:6px; margin-bottom:10px;" rows="3"></textarea><br>

    <div class="bloco">
        <label>Consultar preços (abre em nova aba):</label><br>
        <a href="#" id="link-google-flights" target="_blank" class="btn-atalho">Google Flights</a>
        <a href="https://www.voeazul.com.br" target="_blank" class="btn-atalho">Azul</a>
        <a href="https://www.voegol.com.br/" target="_blank" class="btn-atalho">Gol</a>
        <a href="https://www.latamairlines.com/br/pt" target="_blank" class="btn-atalho">Latam</a>
        <div style="font-size:11px; color:#888; margin-top:4px;">
            O Google Flights abre já com origem, destino e data preenchidos. Os sites das
            companhias abrem na página de busca, onde é preciso digitar os dados.
        </div>
    </div>

    <h3>Passageiros</h3>
    <div style="font-size:11px; color:#888; margin-bottom:10px;">
        Adicione um bloco para cada passageiro, com os dados pessoais e o voo escolhido.
        Todos partem da mesma origem para o mesmo destino, nas datas informadas acima.
    </div>
    <div id="passageiros-container"></div>

    <button type="button" id="btn-adicionar-passageiro" class="btn-atalho" style="margin-top:8px;">
        + Adicionar passageiro
    </button>

    <h3 style="margin-top:20px;">Valor total da solicitação</h3>
    <input type="text" id="valor_total_display" readonly
           style="padding:8px; background:#f5f5f5; width:200px; font-weight:bold; font-size:15px;" value="R$ 0,00">
    <div style="font-size:11px; color:#888; margin-top:5px; margin-bottom:15px;">
        Soma dos valores estimados de todos os passageiros.
    </div>

    <button type="submit" style="padding:10px 20px; background:#37784D; color:white; border:none;
            border-radius:4px; cursor:pointer; font-weight:600;">Enviar solicitação</button>
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

var contadorPassageiros = 0;

function normalizarTexto(texto) {
    return texto.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim();
}

function obterCodigoAeroporto(cidade) {
    return AEROPORTOS_IATA[normalizarTexto(cidade)] || cidade;
}

function atualizarLinkGoogleFlights() {
    var cidadeOrigem = document.getElementById('cidade_origem').value;
    var cidadeDestino = document.getElementById('cidade_destino').value;
    var dataIda = document.getElementById('data_ida').value;
    if (!cidadeOrigem || !cidadeDestino) { return; }

    var query = 'Voos de ' + obterCodigoAeroporto(cidadeOrigem) +
                ' para ' + obterCodigoAeroporto(cidadeDestino);
    if (dataIda) { query += ' em ' + dataIda; }

    document.getElementById('link-google-flights').href =
        'https://www.google.com/travel/flights?hl=pt-BR&gl=BR&q=' + encodeURIComponent(query);
}

function formatarValorPassagem(valor) {
    return 'R$ ' + valor.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function htmlPassageiro(numero) {
    return '' +
    '<div class="bloco-passageiro bloco" style="margin-bottom:15px;">' +
        '<strong>Passageiro <span class="numero-passageiro">' + numero + '</span></strong>' +
        '<button type="button" class="btn btn-excluir btn-remover-passageiro" style="float:right; padding:4px 10px;">Remover</button>' +
        '<div style="clear:both;"></div>' +

        '<label>Nome completo: <span style="color:red;">*</span></label><br>' +
        '<input type="text" name="nome_passageiro[]" required style="width:100%; padding:6px; margin-bottom:10px;"><br>' +

        '<label>CPF: <span style="color:red;">*</span></label><br>' +
        '<input type="text" name="cpf_passageiro[]" required placeholder="000.000.000-00" maxlength="14" inputmode="numeric" style="padding:6px; margin-bottom:10px; width:190px;"><br>' +

        '<label>RG, Órgão e Estado de emissão: <span style="color:red;">*</span></label><br>' +
        '<input type="text" name="rg_passageiro[]" required placeholder="Ex: 12.345.678-9 SSP/PA" style="width:100%; padding:6px; margin-bottom:10px;"><br>' +

        '<label>Data de nascimento: <span style="color:red;">*</span></label><br>' +
        '<input type="date" name="nascimento_passageiro[]" required style="padding:6px; margin-bottom:10px;"><br>' +

        '<label>Telefone: <span style="color:red;">*</span></label><br>' +
        '<div style="display:flex; gap:8px; margin-bottom:10px;">' +
            '<input type="text" name="ddd_passageiro[]" required placeholder="DDD" style="width:80px; padding:6px;">' +
            '<input type="text" name="telefone_passageiro[]" required placeholder="99999-9999" style="width:180px; padding:6px;">' +
        '</div>' +

        '<label>E-mail: <span style="color:red;">*</span></label><br>' +
        '<input type="email" name="email_passageiro[]" required style="width:100%; padding:6px; margin-bottom:14px;"><br>' +

        '<div style="border-top:1px solid #e4ebe7; padding-top:12px;">' +
            '<div style="font-weight:700; font-size:12.5px; color:#37784D; margin-bottom:8px;">Voo de ida</div>' +

            '<label>Companhia: <span style="color:red;">*</span></label><br>' +
            '<select name="voo_ida_companhia[]" required style="padding:6px; margin-bottom:10px; width:170px;">' +
                '<option value="">Selecione</option>__OPCOES_COMPANHIAS__' +
            '</select><br>' +

            '<label>Número do voo: <span style="color:red;">*</span></label><br>' +
            '<input type="text" name="voo_ida_numero[]" required placeholder="Ex: AD 4021" style="padding:6px; margin-bottom:10px; width:170px;"><br>' +

            '<label>Data e hora da partida: <span style="color:red;">*</span></label><br>' +
            '<input type="datetime-local" name="voo_ida_saida[]" required style="padding:6px; margin-bottom:10px;"><br>' +

            '<label>Data e hora da chegada: <span style="color:red;">*</span></label><br>' +
            '<input type="datetime-local" name="voo_ida_chegada[]" required style="padding:6px; margin-bottom:14px;"><br>' +
        '</div>' +

        '<div class="bloco-volta-passageiro" style="display:none; border-top:1px solid #e4ebe7; padding-top:12px;">' +
            '<div style="font-weight:700; font-size:12.5px; color:#37784D; margin-bottom:8px;">Voo de volta</div>' +

            '<label>Companhia: <span style="color:red;">*</span></label><br>' +
            '<select name="voo_volta_companhia[]" class="campo-volta" style="padding:6px; margin-bottom:10px; width:170px;">' +
                '<option value="">Selecione</option>__OPCOES_COMPANHIAS__' +
            '</select><br>' +

            '<label>Número do voo: <span style="color:red;">*</span></label><br>' +
            '<input type="text" name="voo_volta_numero[]" class="campo-volta" placeholder="Ex: G3 1502" style="padding:6px; margin-bottom:10px; width:170px;"><br>' +

            '<label>Data e hora da partida: <span style="color:red;">*</span></label><br>' +
            '<input type="datetime-local" name="voo_volta_saida[]" class="campo-volta" style="padding:6px; margin-bottom:10px;"><br>' +

            '<label>Data e hora da chegada: <span style="color:red;">*</span></label><br>' +
            '<input type="datetime-local" name="voo_volta_chegada[]" class="campo-volta" style="padding:6px; margin-bottom:14px;"><br>' +
        '</div>' +

        '<label>Menor tarifa encontrada na pesquisa (R$): <span style="color:red;">*</span></label><br>' +
        '<input type="number" step="0.01" min="0" name="menor_tarifa[]" class="campo-menor-tarifa" required style="padding:6px; margin-bottom:6px; width:180px;"><br>' +
        '<div style="font-size:11px; color:#888; margin-bottom:10px;">' +
            'Valor mais barato encontrado ao consultar o Google Flights e os sites das companhias, para este trecho.' +
        '</div>' +

        '<label>Valor do voo escolhido (R$): <span style="color:red;">*</span></label><br>' +
        '<input type="number" step="0.01" min="0" name="valor_estimado[]" class="campo-valor-passagem" required style="padding:6px; margin-bottom:10px; width:180px;"><br>' +

        '<div class="bloco-justifica-tarifa" style="display:none; border-left:4px solid #b35c00; background:#fff8ec; padding:10px 12px; border-radius:5px; margin-bottom:12px;">' +
            '<label style="color:#b35c00;">Justificativa por não optar pela tarifa mais barata: <span style="color:red;">*</span></label><br>' +
            '<textarea name="justificativa_tarifa[]" class="campo-justifica-tarifa" rows="2" placeholder="Ex: horário incompatível com a atividade; conexão muito longa; assento indisponível." style="width:100%; padding:6px; margin-top:4px;"></textarea>' +
        '</div>' +

        '<label>Observação sobre o voo (opcional):</label><br>' +
        '<textarea name="observacao_voo[]" rows="2" placeholder="Ex: prefere corredor; conexão em Brasília." style="width:100%; padding:6px;"></textarea>' +
    '</div>';
}

function atualizarTotalPassagem() {
    var total = 0;
    document.querySelectorAll('.campo-valor-passagem').forEach(function (campo) {
        total += parseFloat(campo.value) || 0;
    });
    document.getElementById('valor_total_display').value = formatarValorPassagem(total);
}

function renumerarPassageiros() {
    var blocos = document.querySelectorAll('.bloco-passageiro');
    for (var i = 0; i < blocos.length; i++) {
        blocos[i].querySelector('.numero-passageiro').textContent = i + 1;
    }
}

function atualizarBlocosVolta() {
    var temVolta = document.getElementById('data_volta').value !== '';
    document.querySelectorAll('.bloco-volta-passageiro').forEach(function (bloco) {
        bloco.style.display = temVolta ? 'block' : 'none';
    });
    document.querySelectorAll('.campo-volta').forEach(function (campo) {
        campo.required = temVolta;
        if (!temVolta) { campo.value = ''; }
    });
}

function verificarTarifaBloco(bloco) {
    var menorTarifa = parseFloat(bloco.querySelector('.campo-menor-tarifa').value) || 0;
    var valorEscolhido = parseFloat(bloco.querySelector('.campo-valor-passagem').value) || 0;
    var blocoJustifica = bloco.querySelector('.bloco-justifica-tarifa');
    var campoJustifica = bloco.querySelector('.campo-justifica-tarifa');

    // só compara quando os dois valores foram informados
    var precisaJustificar = menorTarifa > 0 && valorEscolhido > menorTarifa + 0.009;
    blocoJustifica.style.display = precisaJustificar ? 'block' : 'none';
    campoJustifica.required = precisaJustificar;
}
window.verificarTarifaBloco = verificarTarifaBloco;

function verificarTodasAsTarifas() {
    document.querySelectorAll('.bloco-passageiro').forEach(verificarTarifaBloco);
}
window.verificarTodasAsTarifas = verificarTodasAsTarifas;

function ativarPassageiro(bloco) {
    bloco.querySelector('.campo-valor-passagem').addEventListener('input', function () {
        atualizarTotalPassagem();
        verificarTarifaBloco(bloco);
    });
    bloco.querySelector('.campo-menor-tarifa').addEventListener('input', function () {
        verificarTarifaBloco(bloco);
    });

    bloco.querySelector('.btn-remover-passageiro').addEventListener('click', function () {
        if (document.querySelectorAll('.bloco-passageiro').length === 1) {
            alert('A solicitação precisa ter pelo menos um passageiro.');
            return;
        }
        bloco.remove();
        renumerarPassageiros();
        atualizarTotalPassagem();
    });
}

function criarPassageiro() {
    contadorPassageiros++;
    var container = document.getElementById('passageiros-container');
    container.insertAdjacentHTML('beforeend', htmlPassageiro(contadorPassageiros));
    ativarPassageiro(container.lastElementChild);
    renumerarPassageiros();
    atualizarBlocosVolta();
}

window.atualizarTotalPassagem = atualizarTotalPassagem;
window.atualizarBlocosVolta = atualizarBlocosVolta;

['cidade_origem', 'estado_origem', 'cidade_destino', 'estado_destino', 'data_ida'].forEach(function (id) {
    document.getElementById(id).addEventListener('input', atualizarLinkGoogleFlights);
    document.getElementById(id).addEventListener('change', atualizarLinkGoogleFlights);
});
document.getElementById('data_volta').addEventListener('change', atualizarBlocosVolta);
document.getElementById('btn-adicionar-passageiro').addEventListener('click', criarPassageiro);

atualizarLinkGoogleFlights();
if (!window.__RESTAURAR_FORM__) { criarPassageiro(); }
</script>
"""


CAMPO_CONVENIO_HTML = """
    <label>Convênio:</label><br>
    <input type="text" name="convenio" style="width:100%; padding:6px; margin-bottom:10px;"><br>
"""


def montar_formulario_passagem():
    pode_convenio = current_user.is_organizador or current_user.is_aprovador
    html = PASSAGEM_FORM_TEMPLATE.replace('__OPCOES_TRANSPORTE__', montar_opcoes(TIPOS_TRANSPORTE))
    html = html.replace('__OPCOES_ESTADOS__', montar_opcoes_estados())
    html = html.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    html = html.replace('__CAMPO_CONVENIO__', CAMPO_CONVENIO_HTML if pode_convenio else '')
    html = html.replace('__OPCOES_COMPANHIAS__', montar_opcoes(COMPANHIAS_AEREAS))
    return html


@app.route('/solicitacao/passagem', methods=['GET', 'POST'])
@login_required
def passagem_form():
    resultado_bloqueio = bloquear_se_travado()
    if resultado_bloqueio:
        return resultado_bloqueio

    pode_ver_convenio = current_user.is_organizador or current_user.is_aprovador

    if request.method == 'POST':

        def erro(mensagem):
            flash(mensagem)
            return render_pagina('Solicitação de Passagem',
                                 preservar_preenchimento(montar_formulario_passagem(), request.form))

        def ler_data_hora(valor):
            if not valor:
                return None
            try:
                return datetime.strptime(valor, '%Y-%m-%dT%H:%M')
            except ValueError:
                return None

        nomes = request.form.getlist('nome_passageiro[]')
        cpfs = request.form.getlist('cpf_passageiro[]')
        rgs = request.form.getlist('rg_passageiro[]')
        nascimentos = request.form.getlist('nascimento_passageiro[]')
        ddds = request.form.getlist('ddd_passageiro[]')
        telefones = request.form.getlist('telefone_passageiro[]')
        emails = request.form.getlist('email_passageiro[]')
        valores = request.form.getlist('valor_estimado[]')
        menores_tarifas = request.form.getlist('menor_tarifa[]')
        justificativas_tarifa = request.form.getlist('justificativa_tarifa[]')
        observacoes = request.form.getlist('observacao_voo[]')

        ida_companhias = request.form.getlist('voo_ida_companhia[]')
        ida_numeros = request.form.getlist('voo_ida_numero[]')
        ida_saidas = request.form.getlist('voo_ida_saida[]')
        ida_chegadas = request.form.getlist('voo_ida_chegada[]')

        volta_companhias = request.form.getlist('voo_volta_companhia[]')
        volta_numeros = request.form.getlist('voo_volta_numero[]')
        volta_saidas = request.form.getlist('voo_volta_saida[]')
        volta_chegadas = request.form.getlist('voo_volta_chegada[]')

        data_volta = request.form.get('data_volta')

        def pegar(lista, i):
            return lista[i] if i < len(lista) else ''

        passageiros = []
        valor_total_solicitacao = 0

        for i in range(len(nomes)):
            nome = (nomes[i] or '').strip()
            if not nome:
                continue

            if not cpf_tem_11_digitos(pegar(cpfs, i)):
                return erro(f'CPF inválido para o passageiro "{nome}". '
                            f'Informe 11 dígitos, no formato 000.000.000-00.')

            telefone_ok, telefone = montar_telefone(pegar(ddds, i), pegar(telefones, i))
            if not telefone_ok:
                return erro(f'Telefone inválido para o passageiro "{nome}". '
                            f'Informe DDD com 2 dígitos e número com 8 ou 9 dígitos.')

            ida_saida = ler_data_hora(pegar(ida_saidas, i))
            ida_chegada = ler_data_hora(pegar(ida_chegadas, i))

            if not pegar(ida_companhias, i) or not pegar(ida_numeros, i) \
                    or not ida_saida or not ida_chegada:
                return erro(f'Informe o voo de ida escolhido para o passageiro "{nome}".')

            volta_saida = ler_data_hora(pegar(volta_saidas, i))
            volta_chegada = ler_data_hora(pegar(volta_chegadas, i))

            if data_volta and (not pegar(volta_companhias, i) or not pegar(volta_numeros, i)
                               or not volta_saida or not volta_chegada):
                return erro(f'Como há data de volta, informe o voo de volta do passageiro "{nome}".')

            valor = float(pegar(valores, i) or 0)
            menor_tarifa = float(pegar(menores_tarifas, i) or 0)
            justificativa_tarifa = (pegar(justificativas_tarifa, i) or '').strip()

            if menor_tarifa <= 0:
                return erro(f'Informe a menor tarifa encontrada na pesquisa para o passageiro "{nome}".')

            # tolerância de 1 centavo para evitar falso positivo por arredondamento
            if valor > menor_tarifa + 0.01 and not justificativa_tarifa:
                return erro(f'O voo escolhido para "{nome}" é mais caro que a menor tarifa '
                            f'encontrada ({moeda(menor_tarifa)}). Informe a justificativa por '
                            f'não optar pela tarifa mais barata.')

            valor_total_solicitacao += valor

            passageiros.append({
                'nome_passageiro': nome,
                'cpf_passageiro': formatar_cpf(pegar(cpfs, i)),
                'rg_orgao_uf_passageiro': pegar(rgs, i),
                'data_nascimento_passageiro': pegar(nascimentos, i) or None,
                'telefone_passageiro': telefone,
                'email_passageiro': pegar(emails, i),
                'valor_estimado': valor,
                'menor_tarifa_encontrada': menor_tarifa,
                'justificativa_tarifa': justificativa_tarifa or None,
                'voo_ida_companhia': pegar(ida_companhias, i),
                'voo_ida_numero': pegar(ida_numeros, i),
                'voo_ida_saida': ida_saida,
                'voo_ida_chegada': ida_chegada,
                'voo_volta_companhia': pegar(volta_companhias, i) or None,
                'voo_volta_numero': pegar(volta_numeros, i) or None,
                'voo_volta_saida': volta_saida,
                'voo_volta_chegada': volta_chegada,
                'observacao_voo': pegar(observacoes, i) or None,
            })

        if not passageiros:
            return erro('Adicione pelo menos um passageiro à solicitação.')

        solicitacao, era_correcao = obter_solicitacao_para_gravar(
            'passagem',
            atividade_id=request.form.get('atividade_id') or None,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=valor_total_solicitacao,
            convenio=request.form.get('convenio') if pode_ver_convenio else None,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
        )
        if era_correcao:
            SolicitacaoPassagem.query.filter_by(solicitacao_id=solicitacao.id).delete()

        dados_viagem = {
            'tipo_transporte': request.form.get('tipo_transporte'),
            'cidade_origem': request.form.get('cidade_origem'),
            'estado_origem': request.form.get('estado_origem'),
            'cidade_destino': request.form.get('cidade_destino'),
            'estado_destino': request.form.get('estado_destino'),
            'data_ida': request.form.get('data_ida'),
            'data_volta': data_volta or None,
            'com_bagagem': (request.form.get('com_bagagem') == 'sim'),
            'justificativa': request.form.get('justificativa'),
        }

        for dados in passageiros:
            db.session.add(SolicitacaoPassagem(
                solicitacao_id=solicitacao.id, **dados_viagem, **dados))

        db.session.commit()
        if era_correcao:
            flash(f'Solicitação corrigida e reenviada, protocolo {protocolo(solicitacao)}!', 'sucesso')
        else:
            flash(f'Solicitação de passagem enviada com sucesso para '
                  f'{len(passageiros)} passageiro(s)!', 'sucesso')
        return redirect(url_for('inicio'))

    solicitacao_corrigindo = carregar_solicitacao_para_correcao(request.args.get('corrigir_id'))
    if solicitacao_corrigindo:
        dados_edicao = _dados_edicao_passagem(solicitacao_corrigindo)
        if dados_edicao:
            return render_pagina('Solicitação de Passagem',
                                 preservar_preenchimento(montar_formulario_passagem(), dados_edicao))

    return render_pagina('Solicitação de Passagem', com_vinculo_atividade(montar_formulario_passagem()))


# ---------------- SOLICITAÇÃO: COMPRAS DE MATERIAIS ----------------
COMPRA_MATERIAIS_FORM_TEMPLATE = """
<div style="margin-bottom:14px;"><a href="/ajuda#compras" target="_blank" class="btn-atalho">Dúvidas sobre compras? Consulte a Central de Ajuda</a></div>
<form method="POST" enctype="multipart/form-data" style="max-width: 800px;" id="form-compra-materiais">
    <input type="hidden" name="corrigir_id" value="">
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

    <h3>Itens a comprar</h3>
    <div style="font-size:11px; color:#888; margin-bottom:10px;">
        Adicione quantos itens forem necessários. O valor total da solicitação é a soma de todos os itens.
    </div>
    <div id="itens-container"></div>

    <button type="button" id="btn-adicionar-item" class="btn-atalho" style="margin-top:8px;">+ Adicionar item</button>

    <h3 style="margin-top:20px;">Valor total da solicitação</h3>
    <input type="text" id="valor_total_display" readonly
           style="padding:8px; background:#f5f5f5; width:200px; font-weight:bold; font-size:15px;" value="R$ 0,00"><br>

    <div id="aviso_cotacoes" style="display:none; background:#fdeceb; border-left:4px solid #c0392b;
         color:#a02020; padding:12px 15px; border-radius:5px; font-size:12.5px; margin:14px 0;">
        <strong>Atenção: esta solicitação ultrapassou R$ 5.000,00.</strong><br>
        É obrigatório anexar <strong>pelo menos 3 orçamentos</strong> (cotações) para prosseguir.
        <span id="contagem_anexos" style="display:block; margin-top:6px;"></span>
    </div>

    <label>Anexos (orçamentos, catálogos, especificações):</label><br>
    <input type="file" name="anexos" id="anexos" multiple
           accept=".pdf,.jpg,.jpeg,.png,.doc,.docx,.xls,.xlsx" style="margin-bottom:15px;"><br>

    <button type="submit" style="padding:10px 20px; background:#37784D; color:white; border:none;
            border-radius:4px; cursor:pointer; font-weight:600;">Enviar solicitação</button>
</form>

<script>
var LIMITE_COTACOES = 5000;
var contadorItens = 0;

function formatarValor(valor) {
    return 'R$ ' + valor.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function htmlDoItem(numero) {
    return '' +
    '<div class="bloco-item bloco" style="margin-bottom:15px;">' +
        '<strong>Item <span class="numero-item">' + numero + '</span></strong>' +
        '<button type="button" class="btn btn-excluir btn-remover-item" style="float:right; padding:4px 10px;">Remover</button>' +
        '<div style="clear:both;"></div>' +

        '<label>Nome e especificação do item: <span style="color:red;">*</span></label><br>' +
        '<textarea name="item_especificacao[]" required rows="2" placeholder="Informe detalhes do item (marca, modelo, cor, tamanho etc.)" style="width:100%; padding:6px; margin-bottom:10px;"></textarea><br>' +

        '<label>Sugestão de fornecedor (loja):</label><br>' +
        '<input type="text" name="item_fornecedor[]" style="width:100%; padding:6px; margin-bottom:10px;"><br>' +

        '<label>Forma de aquisição: <span style="color:red;">*</span></label><br>' +
        '<select name="item_forma[]" class="campo-forma" required style="padding:6px; margin-bottom:10px;">' +
            '<option value="">Selecione</option>' +
            '<option value="Local">Local</option>' +
            '<option value="Online">Online</option>' +
        '</select><br>' +

        '<label>Link do produto <span class="marca-link" style="color:red; display:none;">*</span> ' +
        '<span style="font-weight:normal; font-size:11px; color:#888;">(obrigatório se a compra for Online)</span>:</label><br>' +
        '<input type="url" name="item_link[]" class="campo-link" placeholder="https://" style="width:100%; padding:6px; margin-bottom:10px;"><br>' +

        '<label>Quantidade: <span style="color:red;">*</span></label><br>' +
        '<input type="number" step="1" min="1" name="item_quantidade[]" class="campo-quantidade" required style="padding:6px; margin-bottom:10px; width:130px;"><br>' +

        '<label>Valor unitário (R$): <span style="color:red;">*</span></label><br>' +
        '<input type="number" step="0.01" min="0" name="item_valor_unitario[]" class="campo-valor-unitario" required style="padding:6px; margin-bottom:10px; width:170px;"><br>' +

        '<label>Valor total do item:</label><br>' +
        '<input type="text" class="campo-subtotal" readonly style="padding:6px; margin-bottom:10px; background:#f5f5f5; width:170px;" value="R$ 0,00"><br>' +

        '<label>Justificativa da compra: <span style="color:red;">*</span></label><br>' +
        '<textarea name="item_justificativa[]" required rows="2" style="width:100%; padding:6px; margin-bottom:6px;"></textarea><br>' +
    '</div>';
}

function calcularTotalCompra() {
    var total = 0;

    document.querySelectorAll('.bloco-item').forEach(function(bloco) {
        var quantidade = parseFloat(bloco.querySelector('.campo-quantidade').value) || 0;
        var unitario = parseFloat(bloco.querySelector('.campo-valor-unitario').value) || 0;
        var subtotal = quantidade * unitario;
        bloco.querySelector('.campo-subtotal').value = formatarValor(subtotal);
        total += subtotal;
    });

    document.getElementById('valor_total_display').value = formatarValor(total);

    var aviso = document.getElementById('aviso_cotacoes');
    if (total > LIMITE_COTACOES) {
        aviso.style.display = 'block';
        atualizarContagemAnexos();
    } else {
        aviso.style.display = 'none';
    }
    return total;
}

function atualizarContagemAnexos() {
    var arquivos = document.getElementById('anexos').files.length;
    var texto = document.getElementById('contagem_anexos');
    if (arquivos >= 3) {
        texto.innerHTML = '<span style="color:#2e7d32; font-weight:bold;">' + arquivos +
                          ' arquivo(s) anexado(s) - requisito atendido.</span>';
    } else {
        texto.innerHTML = '<strong>' + arquivos + ' de 3 orçamentos anexados.</strong>';
    }
}

function renumerarItens() {
    var blocos = document.querySelectorAll('.bloco-item');
    for (var i = 0; i < blocos.length; i++) {
        blocos[i].querySelector('.numero-item').textContent = i + 1;
    }
}

function ativarBloco(bloco) {
    bloco.querySelector('.campo-forma').addEventListener('change', function() {
        var link = bloco.querySelector('.campo-link');
        var marca = bloco.querySelector('.marca-link');
        if (this.value === 'Online') {
            link.required = true;
            marca.style.display = 'inline';
        } else {
            link.required = false;
            marca.style.display = 'none';
        }
    });

    bloco.querySelector('.campo-quantidade').addEventListener('input', calcularTotalCompra);
    bloco.querySelector('.campo-valor-unitario').addEventListener('input', calcularTotalCompra);

    bloco.querySelector('.btn-remover-item').addEventListener('click', function() {
        if (document.querySelectorAll('.bloco-item').length === 1) {
            alert('A solicitação precisa ter pelo menos um item.');
            return;
        }
        bloco.remove();
        renumerarItens();
        calcularTotalCompra();
    });
}

function criarBlocoItem() {
    contadorItens++;
    var container = document.getElementById('itens-container');
    container.insertAdjacentHTML('beforeend', htmlDoItem(contadorItens));
    ativarBloco(container.lastElementChild);
    renumerarItens();
}

window.calcularTotalCompra = calcularTotalCompra;

document.getElementById('btn-adicionar-item').addEventListener('click', criarBlocoItem);
document.getElementById('anexos').addEventListener('change', atualizarContagemAnexos);

document.getElementById('form-compra-materiais').addEventListener('submit', function(evento) {
    if (document.querySelectorAll('.bloco-item').length === 0) {
        evento.preventDefault();
        alert('Adicione pelo menos um item à solicitação.');
        return;
    }

    var total = calcularTotalCompra();
    var arquivos = document.getElementById('anexos').files.length;

    if (total > LIMITE_COTACOES && arquivos < 3) {
        evento.preventDefault();
        alert('Esta solicitação totaliza ' + formatarValor(total) + ', acima de R$ 5.000,00. ' +
              'É obrigatório anexar pelo menos 3 orçamentos. Você anexou ' + arquivos + '.');
        document.getElementById('aviso_cotacoes').scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
});

if (!window.__RESTAURAR_FORM__) { criarBlocoItem(); }
</script>
"""


def montar_formulario_compras():
    return COMPRA_MATERIAIS_FORM_TEMPLATE.replace('__OPCOES_COORDENACAO__',
                                                  montar_opcoes_coordenacoes())


@app.route('/solicitacao/compra-materiais', methods=['GET', 'POST'])
@login_required
def compra_materiais_form():
    resultado_bloqueio = bloquear_se_travado()
    if resultado_bloqueio:
        return resultado_bloqueio

    if request.method == 'POST':
        especificacoes = request.form.getlist('item_especificacao[]')
        fornecedores = request.form.getlist('item_fornecedor[]')
        formas = request.form.getlist('item_forma[]')
        links = request.form.getlist('item_link[]')
        quantidades = request.form.getlist('item_quantidade[]')
        valores_unitarios = request.form.getlist('item_valor_unitario[]')
        justificativas = request.form.getlist('item_justificativa[]')

        itens = []
        valor_total_solicitacao = 0

        for i in range(len(especificacoes)):
            especificacao = (especificacoes[i] or '').strip()
            if not especificacao:
                continue

            quantidade = float(quantidades[i] or 0) if i < len(quantidades) else 0
            valor_unitario = float(valores_unitarios[i] or 0) if i < len(valores_unitarios) else 0
            total_item = quantidade * valor_unitario
            valor_total_solicitacao += total_item

            itens.append({
                'nome_especificacao': especificacao,
                'fornecedor_sugerido': fornecedores[i] if i < len(fornecedores) else None,
                'forma_aquisicao': formas[i] if i < len(formas) else '',
                'link_produto': links[i] if i < len(links) else None,
                'quantidade': quantidade,
                'valor_unitario': valor_unitario,
                'valor_total_item': total_item,
                'justificativa': justificativas[i] if i < len(justificativas) else '',
            })

        if not itens:
            flash('Adicione pelo menos um item à solicitação.')
            return render_pagina('Solicitação de Compra de Materiais',
                                 preservar_preenchimento(montar_formulario_compras(), request.form))

        arquivos = request.files.getlist('anexos')
        arquivos_validos = [a for a in arquivos if a and a.filename]

        if valor_total_solicitacao > 5000 and len(arquivos_validos) < 3:
            flash(f'Esta solicitação totaliza {moeda(valor_total_solicitacao)}, acima de R$ 5.000,00. '
                  f'É obrigatório anexar pelo menos 3 orçamentos. Foram anexados {len(arquivos_validos)}.')
            return render_pagina('Solicitação de Compra de Materiais',
                                 preservar_preenchimento(montar_formulario_compras(), request.form))

        solicitacao, era_correcao = obter_solicitacao_para_gravar(
            'compra_materiais',
            atividade_id=request.form.get('atividade_id') or None,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=valor_total_solicitacao,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
        )
        if era_correcao:
            SolicitacaoCompraMateriais.query.filter_by(solicitacao_id=solicitacao.id).delete()

        data_entrega = request.form.get('data_entrega_material')
        for dados in itens:
            db.session.add(SolicitacaoCompraMateriais(
                solicitacao_id=solicitacao.id,
                data_entrega_material=data_entrega,
                **dados,
            ))

        for arquivo in arquivos_validos:
            salvar_anexo(solicitacao.id, arquivo, 'orcamento')

        db.session.commit()
        if era_correcao:
            flash(f'Solicitação corrigida e reenviada, protocolo {protocolo(solicitacao)}!', 'sucesso')
        else:
            flash('Solicitação de compra de materiais enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    solicitacao_corrigindo = carregar_solicitacao_para_correcao(request.args.get('corrigir_id'))
    if solicitacao_corrigindo:
        dados_edicao = _dados_edicao_compra(solicitacao_corrigindo)
        if dados_edicao:
            return render_pagina('Solicitação de Compra de Materiais',
                                 preservar_preenchimento(montar_formulario_compras(), dados_edicao))

    return render_pagina('Solicitação de Compra de Materiais', com_vinculo_atividade(montar_formulario_compras()))


# ---------------- SOLICITAÇÃO: ALIMENTAÇÃO ----------------
ALIMENTACAO_FORM_TEMPLATE = """
<div style="margin-bottom:14px;"><a href="/ajuda#alimentacao" target="_blank" class="btn-atalho">Dúvidas sobre alimentação? Consulte a Central de Ajuda</a></div>
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

window.atualizarCustos = atualizarCustos;
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
    resultado_bloqueio = bloquear_se_travado()
    if resultado_bloqueio:
        return resultado_bloqueio

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
            atividade_id=request.form.get('atividade_id') or None,
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

        salvar_anexo(solicitacao.id, arquivo_lista, 'lista_participantes')

        db.session.commit()
        flash('Solicitação de alimentação enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    form_html = ALIMENTACAO_FORM_TEMPLATE.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    form_html = form_html.replace('__OPCOES_TIPOS_ALIMENTACAO__', montar_opcoes_tipos_alimentacao())
    form_html = form_html.replace('__VALORES_ALIMENTACAO__', montar_dict_valores_alimentacao())
    return render_pagina('Solicitação de Alimentação', com_vinculo_atividade(form_html))


# ---------------- CADASTROS: ALIMENTAÇÃO (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/alimentacao')
@login_required
def cadastro_alimentacao():
    somente_organizador_ou_analista()

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
    somente_organizador_ou_analista()
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
    somente_organizador_ou_analista()
    tipo = TipoAlimentacao.query.get_or_404(tipo_id)
    tipo.nome = request.form.get('nome', '').strip()
    tipo.valor = request.form.get('valor')
    db.session.commit()
    flash('Tipo de alimentação atualizado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_alimentacao'))


@app.route('/cadastros/alimentacao/<int:tipo_id>/excluir', methods=['POST'])
@login_required
def cadastro_alimentacao_excluir(tipo_id):
    somente_organizador_ou_analista()
    tipo = TipoAlimentacao.query.get_or_404(tipo_id)
    nome = tipo.nome
    db.session.delete(tipo)
    db.session.commit()
    flash(f'Tipo "{nome}" excluído com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_alimentacao'))


# ---------------- SOLICITAÇÃO: LOCAÇÃO DE VEÍCULOS ----------------
LOCACAO_VEICULO_FORM_TEMPLATE = """
<div style="margin-bottom:14px;"><a href="/ajuda#locacao" target="_blank" class="btn-atalho">Dúvidas sobre locação de veículos? Consulte a Central de Ajuda</a></div>
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
    <input type="number" step="1" min="0" name="km_estimado" id="km_estimado" required style="padding:6px; margin-bottom:10px; width:120px;"><br>

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

window.atualizarCustoViagem = atualizarCustoViagem;
window.atualizarAssentos = atualizarAssentos;
document.getElementById('tipo_veiculo').addEventListener('change', atualizarCustoViagem);
document.getElementById('tipo_veiculo').addEventListener('change', atualizarAssentos);
document.getElementById('km_estimado').addEventListener('input', atualizarCustoViagem);
</script>
"""


@app.route('/solicitacao/locacao-veiculo', methods=['GET', 'POST'])
@login_required
def locacao_veiculo_form():
    resultado_bloqueio = bloquear_se_travado()
    if resultado_bloqueio:
        return resultado_bloqueio

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
            atividade_id=request.form.get('atividade_id') or None,
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
    return render_pagina('Solicitação de Locação de Veículo', com_vinculo_atividade(form_html))


# ---------------- CADASTROS: LOCAÇÃO DE VEÍCULOS (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/locacao-veiculo')
@login_required
def cadastro_locacao_veiculo():
    somente_organizador_ou_analista()

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
    somente_organizador_ou_analista()
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
    somente_organizador_ou_analista()
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
    somente_organizador_ou_analista()
    tipo = TipoVeiculo.query.get_or_404(tipo_id)
    nome = tipo.nome
    db.session.delete(tipo)
    db.session.commit()
    flash(f'Tipo "{nome}" excluído com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_locacao_veiculo'))


# ---------------- SOLICITAÇÃO: SERVIÇOS EXTERNOS ----------------
SERVICO_EXTERNO_PF_TEMPLATE = """
<div style="margin-bottom:14px;">
<a href="/ajuda#servico_externo" target="_blank" class="btn-atalho">Dúvidas sobre serviços externos? Consulte a Central de Ajuda</a></div>

<form method="POST" style="max-width: 700px;" id="form-servico-pf">
    <input type="hidden" name="corrigir_id" value="">
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

    <h3>Prestadores de serviço (Pessoa Física)</h3>
    <div style="font-size:11px; color:#888; margin-bottom:10px;">
        Adicione quantos prestadores forem necessários para a atividade.
    </div>
    <div id="prestadores-container"></div>

    <button type="button" id="btn-adicionar-prestador" class="btn-atalho" style="margin-top:8px;">
        + Adicionar prestador
    </button>

    <h3 style="margin-top:20px;">Valor total da solicitação</h3>
    <input type="text" id="valor_total_display" readonly
           style="padding:8px; background:#f5f5f5; width:200px; font-weight:bold; font-size:15px;" value="R$ 0,00">

    <br><br>
    <button type="submit" style="padding:10px 20px; background:#37784D; color:white; border:none;
            border-radius:4px; cursor:pointer; font-weight:600;">Enviar solicitação</button>
</form>

<script>
var VALORES_SERVICO = __VALORES_SERVICO__;
var contadorPrestadores = 0;

function formatarValorPF(valor) {
    return 'R$ ' + valor.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function htmlPrestadorPF(numero) {
    return '' +
    '<div class="bloco-prestador bloco" style="margin-bottom:15px;">' +
        '<strong>Prestador <span class="numero-prestador">' + numero + '</span></strong>' +
        '<button type="button" class="btn btn-excluir btn-remover-prestador" style="float:right; padding:4px 10px;">Remover</button>' +
        '<div style="clear:both;"></div>' +

        '<label>Categoria do serviço: <span style="color:red;">*</span></label><br>' +
        '<select name="categoria_servico[]" class="campo-categoria" required style="padding:6px; margin-bottom:10px;">' +
            '<option value="">Selecione</option>' +
            '__OPCOES_TIPOS_SERVICO__' +
            '<option value="Outros">Outros</option>' +
        '</select><br>' +

        '<label>Nome do serviço: <span style="color:red;">*</span></label><br>' +
        '<input type="text" name="nome_servico[]" required style="width:100%; padding:6px; margin-bottom:10px;"><br>' +

        '<label>Especificação/Descrição: <span style="color:red;">*</span></label><br>' +
        '<textarea name="especificacao[]" required rows="2" style="width:100%; padding:6px; margin-bottom:10px;"></textarea><br>' +

        '<label>Valor diário de referência (R$): <span style="color:red;">*</span></label><br>' +
        '<input type="text" class="campo-valor-display" required style="padding:6px; margin-bottom:10px; width:130px;" value="0,00"><br>' +

        '<label>Dias de atividade: <span style="color:red;">*</span></label><br>' +
        '<input type="number" min="1" step="1" name="dias_atividade[]" class="campo-dias" required style="padding:6px; margin-bottom:10px; width:100px;"><br>' +

        '<div class="bloco" style="background:#f7faf6; margin-bottom:12px;">' +
            '<strong style="font-size:12px; color:#004622;">Cálculo (automático, não editável)</strong>' +
            '<table style="max-width:340px; margin-top:8px;">' +
                '<tr><td style="font-size:12.5px;">Subtotal (diária x dias)</td>' +
                    '<td style="text-align:right;"><input type="text" class="campo-subtotal-display" readonly style="padding:4px; width:110px; background:#f5f5f5; border:none; text-align:right;" value="R$ 0,00"></td></tr>' +
                '<tr><td style="font-size:12.5px;">ISS (<span class="campo-aliquota-texto">__ALIQUOTA_ISS__</span>%)</td>' +
                    '<td style="text-align:right;"><input type="text" class="campo-iss-display" readonly style="padding:4px; width:110px; background:#f5f5f5; border:none; text-align:right; color:#b35c00;" value="R$ 0,00"></td></tr>' +
                '<tr style="border-top:1px solid #cfe0d3;"><td style="font-size:12.5px; font-weight:bold; padding-top:5px;">Valor total do serviço</td>' +
                    '<td style="text-align:right; padding-top:5px;"><input type="text" class="campo-valor-total-display" readonly style="padding:4px; width:110px; background:#f5f5f5; border:none; text-align:right; font-weight:bold;" value="R$ 0,00"></td></tr>' +
            '</table>' +
        '</div>' +
        '<input type="hidden" name="valor_servico[]" class="campo-valor-hidden" value="0">' +
        '<input type="hidden" name="valor_diario[]" class="campo-valor-diario-hidden" value="0"><br>' +

        '<label>Justificativa da solicitação: <span style="color:red;">*</span></label><br>' +
        '<textarea name="justificativa[]" required rows="2" style="width:100%; padding:6px; margin-bottom:12px;"></textarea><br>' +

        '<label>Nome completo do prestador: <span style="color:red;">*</span></label><br>' +
        '<input type="text" name="nome_prestador[]" required style="width:100%; padding:6px; margin-bottom:10px;"><br>' +

        '<label>CPF: <span style="color:red;">*</span></label><br>' +
        '<input type="text" name="cpf_prestador[]" required placeholder="000.000.000-00" maxlength="14" inputmode="numeric" style="padding:6px; margin-bottom:10px; width:180px;"><br>' +

        '<label>RG, Órgão e Estado de emissão: <span style="color:red;">*</span></label><br>' +
        '<input type="text" name="rg_prestador[]" required style="width:100%; padding:6px; margin-bottom:10px;"><br>' +

        '<label>Telefone: <span style="color:red;">*</span></label><br>' +
        '<div style="display:flex; gap:8px; margin-bottom:10px;">' +
            '<input type="text" name="ddd_prestador[]" required placeholder="DDD" style="width:80px; padding:6px;">' +
            '<input type="text" name="telefone_prestador[]" required placeholder="99999-9999" style="width:180px; padding:6px;">' +
        '</div>' +

        '<label>PIS/NIS <span style="font-weight:normal; font-size:11px; color:#888;">(quando aplicável)</span>:</label><br>' +
        '<input type="text" name="pis_nis[]" style="padding:6px; margin-bottom:10px; width:200px;"><br>' +

        '<label>Endereço completo (com bairro e CEP): <span style="color:red;">*</span></label><br>' +
        '<input type="text" name="endereco_prestador[]" required style="width:100%; padding:6px; margin-bottom:12px;"><br>' +

        '<label>Banco: <span style="color:red;">*</span></label><br>' +
        '<input type="text" name="banco[]" required style="width:100%; padding:6px; margin-bottom:10px;"><br>' +

        '<label>Agência: <span style="color:red;">*</span></label><br>' +
        '<input type="text" name="agencia[]" required style="padding:6px; margin-bottom:10px; width:150px;"><br>' +

        '<label>Conta: <span style="color:red;">*</span></label><br>' +
        '<input type="text" name="conta[]" required style="padding:6px; margin-bottom:10px; width:200px;"><br>' +

        '<label>Chave PIX: <span style="color:red;">*</span></label><br>' +
        '<input type="text" name="chave_pix[]" required style="width:100%; padding:6px; margin-bottom:6px;"><br>' +
    '</div>';
}

function atualizarTotalPF() {
    var total = 0;
    document.querySelectorAll('.campo-valor-hidden').forEach(function (campo) {
        total += parseFloat(campo.value) || 0;
    });
    document.getElementById('valor_total_display').value = formatarValorPF(total);
}

function renumerarPrestadores() {
    var blocos = document.querySelectorAll('.bloco-prestador');
    for (var i = 0; i < blocos.length; i++) {
        blocos[i].querySelector('.numero-prestador').textContent = i + 1;
    }
}

var ALIQUOTA_ISS = __ALIQUOTA_ISS__;

function recalcularValorPrestador(bloco) {
    var oculto = bloco.querySelector('.campo-valor-hidden');
    var ocultoDiario = bloco.querySelector('.campo-valor-diario-hidden');
    var subtotalDisplay = bloco.querySelector('.campo-subtotal-display');
    var issDisplay = bloco.querySelector('.campo-iss-display');
    var totalDisplay = bloco.querySelector('.campo-valor-total-display');
    var dias = parseInt(bloco.querySelector('.campo-dias').value) || 0;
    var valorDiario = parseFloat(ocultoDiario.value) || 0;

    var subtotal = valorDiario * dias;
    var iss = subtotal * (ALIQUOTA_ISS / 100);
    var total = subtotal + iss;

    subtotalDisplay.value = formatarValorPF(subtotal);
    issDisplay.value = formatarValorPF(iss);
    totalDisplay.value = formatarValorPF(total);
    oculto.value = total.toFixed(2);
    atualizarTotalPF();
}

function ativarPrestador(bloco) {
    var categoria = bloco.querySelector('.campo-categoria');
    var display = bloco.querySelector('.campo-valor-display');
    var ocultoDiario = bloco.querySelector('.campo-valor-diario-hidden');
    var camposDias = bloco.querySelector('.campo-dias');

    categoria.addEventListener('change', function () {
        if (this.value === 'Outros' || this.value === '') {
            display.readOnly = false;
            display.style.background = 'white';
            display.value = '';
            ocultoDiario.value = '0';
        } else {
            var valor = VALORES_SERVICO[this.value] || 0;
            ocultoDiario.value = valor.toFixed(2);
            display.readOnly = true;
            display.style.background = '#f5f5f5';
            display.value = valor.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }
        recalcularValorPrestador(bloco);
    });

    display.addEventListener('input', function () {
        if (!this.readOnly) {
            var digitos = this.value.replace(/[^0-9]/g, '');
            if (digitos === '') { ocultoDiario.value = '0'; recalcularValorPrestador(bloco); return; }
            var reais = parseInt(digitos, 10) / 100;
            ocultoDiario.value = reais.toFixed(2);
            this.value = reais.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            recalcularValorPrestador(bloco);
        }
    });

    camposDias.addEventListener('input', function () {
        recalcularValorPrestador(bloco);
    });

    bloco.querySelector('.btn-remover-prestador').addEventListener('click', function () {
        if (document.querySelectorAll('.bloco-prestador').length === 1) {
            alert('A solicitação precisa ter pelo menos um prestador.');
            return;
        }
        bloco.remove();
        renumerarPrestadores();
        atualizarTotalPF();
    });
}

function criarPrestadorPF() {
    contadorPrestadores++;
    var container = document.getElementById('prestadores-container');
    container.insertAdjacentHTML('beforeend', htmlPrestadorPF(contadorPrestadores));
    ativarPrestador(container.lastElementChild);
    renumerarPrestadores();
}

function recalcularTodosPrestadoresPF() {
    document.querySelectorAll('.bloco-prestador').forEach(function (bloco) {
        var ocultoDiario = bloco.querySelector('.campo-valor-diario-hidden');
        var display = bloco.querySelector('.campo-valor-display');
        var valorDiario = parseFloat(ocultoDiario.value) || 0;
        display.value = valorDiario.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        recalcularValorPrestador(bloco);
    });
}

window.atualizarTotalPF = atualizarTotalPF;
window.recalcularTodosPrestadoresPF = recalcularTodosPrestadoresPF;
document.getElementById('btn-adicionar-prestador').addEventListener('click', criarPrestadorPF);
if (!window.__RESTAURAR_FORM__) { criarPrestadorPF(); }
</script>
"""


SERVICO_EXTERNO_PJ_TEMPLATE = """
<div style="margin-bottom:14px;">
<a href="/ajuda#servico_externo" target="_blank" class="btn-atalho">Dúvidas sobre serviços externos? Consulte a Central de Ajuda</a></div>

<form method="POST" style="max-width: 700px;" id="form-servico-pj">
    <input type="hidden" name="corrigir_id" value="">
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

    <h3>Dados do serviço</h3>
    <label>Nome do serviço: <span style="color:red;">*</span></label><br>
    <input type="text" name="nome_servico" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Sugestão de fornecedor (empresa), caso houver:</label><br>
    <input type="text" name="fornecedor_sugerido" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Especificação/Descrição do serviço: <span style="color:red;">*</span></label><br>
    <textarea name="especificacao" required rows="3" style="width:100%; padding:6px; margin-bottom:10px;"></textarea><br>

    <label>Valor orçado (R$): <span style="color:red;">*</span></label><br>
    <input type="number" step="0.01" min="0" name="valor_servico" required
           style="padding:7px; margin-bottom:10px; width:190px;"><br>

    <label>Justificativa da solicitação: <span style="color:red;">*</span></label><br>
    <textarea name="justificativa" required rows="3" style="width:100%; padding:6px; margin-bottom:15px;"></textarea><br>

    <h3>Dados da empresa contratada</h3>
    <label>Nome da empresa: <span style="color:red;">*</span></label><br>
    <input type="text" name="nome_empresa" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>CNPJ: <span style="color:red;">*</span></label><br>
    <input type="text" name="cnpj" required placeholder="00.000.000/0000-00"
           maxlength="18" inputmode="numeric"
           style="padding:6px; margin-bottom:10px; width:220px;"><br>

    <label>Telefone: <span style="color:red;">*</span></label><br>
    <div style="display:flex; gap:8px; margin-bottom:15px;">
        <input type="text" name="ddd_prestador" required placeholder="DDD" style="width:80px; padding:6px;">
        <input type="text" name="telefone_prestador" required placeholder="99999-9999" style="width:180px; padding:6px;">
    </div>


    <h3>Dados bancários</h3>
    <div style="font-size:11px; color:#888; margin-bottom:10px;">
        Ao enviar a nota fiscal, é obrigatório que os dados bancários estejam completos.
    </div>

    <label>Banco: <span style="color:red;">*</span></label><br>
    <input type="text" name="banco" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Agência: <span style="color:red;">*</span></label><br>
    <input type="text" name="agencia" required style="padding:6px; margin-bottom:10px; width:150px;"><br>

    <label>Conta: <span style="color:red;">*</span></label><br>
    <input type="text" name="conta" required style="padding:6px; margin-bottom:10px; width:200px;"><br>

    <label>Chave PIX: <span style="color:red;">*</span></label><br>
    <input type="text" name="chave_pix" required style="width:100%; padding:6px; margin-bottom:15px;"><br>

    <button type="submit" style="padding:10px 20px; background:#37784D; color:white; border:none;
            border-radius:4px; cursor:pointer; font-weight:600;">Enviar solicitação</button>
</form>
"""


def montar_formulario_pf():
    aliquota_iss = obter_configuracao(CHAVE_ALIQUOTA_ISS, ALIQUOTA_ISS_PADRAO)
    html = SERVICO_EXTERNO_PF_TEMPLATE.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    html = html.replace('__OPCOES_TIPOS_SERVICO__', montar_opcoes_tipos_servico())
    html = html.replace('__VALORES_SERVICO__', montar_dict_valores_servico())
    html = html.replace('__ALIQUOTA_ISS__', str(aliquota_iss))
    return html


@app.route('/solicitacao/servico-externo-pf', methods=['GET', 'POST'])
@login_required
def servico_externo_pf_form():
    resultado_bloqueio = bloquear_se_travado()
    if resultado_bloqueio:
        return resultado_bloqueio

    if request.method == 'POST':
        categorias = request.form.getlist('categoria_servico[]')
        nomes_servico = request.form.getlist('nome_servico[]')
        especificacoes = request.form.getlist('especificacao[]')
        justificativas = request.form.getlist('justificativa[]')
        valores = request.form.getlist('valor_servico[]')
        valores_diarios = request.form.getlist('valor_diario[]')
        dias_lista = request.form.getlist('dias_atividade[]')
        nomes = request.form.getlist('nome_prestador[]')
        cpfs = request.form.getlist('cpf_prestador[]')
        rgs = request.form.getlist('rg_prestador[]')
        ddds = request.form.getlist('ddd_prestador[]')
        telefones = request.form.getlist('telefone_prestador[]')
        pis_lista = request.form.getlist('pis_nis[]')
        enderecos = request.form.getlist('endereco_prestador[]')
        bancos = request.form.getlist('banco[]')
        agencias = request.form.getlist('agencia[]')
        contas = request.form.getlist('conta[]')
        chaves = request.form.getlist('chave_pix[]')

        prestadores = []
        valor_total_solicitacao = 0

        for i in range(len(nomes)):
            nome = (nomes[i] or '').strip()
            if not nome:
                continue
            cpf_prestador = cpfs[i] if i < len(cpfs) else ''
            if not cpf_tem_11_digitos(cpf_prestador):
                flash(f'CPF inválido para o prestador "{nome}". '
                      f'Informe 11 dígitos, no formato 000.000.000-00.')
                return render_pagina('Serviço Externo - Pessoa Física',
                                     preservar_preenchimento(montar_formulario_pf(), request.form))

            telefone_ok, telefone_formatado = montar_telefone(
                ddds[i] if i < len(ddds) else '',
                telefones[i] if i < len(telefones) else '')
            if not telefone_ok:
                flash(f'Telefone inválido para o prestador "{nome}". '
                      f'Informe DDD com 2 dígitos e número com 8 ou 9 dígitos.')
                return render_pagina('Serviço Externo - Pessoa Física',
                                     preservar_preenchimento(montar_formulario_pf(), request.form))

            try:
                dias_atividade = int(dias_lista[i]) if i < len(dias_lista) and dias_lista[i] else 0
            except ValueError:
                dias_atividade = 0
            if dias_atividade < 1:
                flash(f'Informe os dias de atividade para o prestador "{nome}".')
                return render_pagina('Serviço Externo - Pessoa Física',
                                     preservar_preenchimento(montar_formulario_pf(), request.form))

            valor_diario = float(valores_diarios[i] or 0) if i < len(valores_diarios) else 0

            # confere o valor diário informado para categorias do cadastro -
            # "Outros" tem valor livre, sem checagem
            categoria_atual = categorias[i] if i < len(categorias) else ''
            if categoria_atual and categoria_atual != 'Outros':
                tipo_cadastrado = TipoServicoExterno.query.filter_by(nome=categoria_atual).first()
                if tipo_cadastrado:
                    valor_diario = float(tipo_cadastrado.valor)

            # o subtotal e o ISS são sempre calculados no servidor - o valor
            # que vem do navegador é só para exibição, nunca confiável
            aliquota_iss = obter_configuracao(CHAVE_ALIQUOTA_ISS, ALIQUOTA_ISS_PADRAO)
            subtotal_servico = round(valor_diario * dias_atividade, 2)
            valor_iss = round(subtotal_servico * (aliquota_iss / 100), 2)
            valor = round(subtotal_servico + valor_iss, 2)

            valor_total_solicitacao += valor

            prestadores.append({
                'tipo_prestador': 'PF',
                'categoria_servico': categorias[i] if i < len(categorias) else '',
                'nome_servico': nomes_servico[i] if i < len(nomes_servico) else '',
                'especificacao': especificacoes[i] if i < len(especificacoes) else '',
                'justificativa': justificativas[i] if i < len(justificativas) else '',
                'valor_servico': valor,
                'valor_subtotal_servico': subtotal_servico,
                'aliquota_iss': aliquota_iss,
                'valor_iss': valor_iss,
                'dias_atividade': dias_atividade,
                'valor_diario': valor_diario,
                'nome_prestador': nome,
                'cpf_prestador': formatar_cpf(cpf_prestador),
                'rg_prestador': rgs[i] if i < len(rgs) else None,
                'telefone_prestador': telefone_formatado,
                'pis_nis': pis_lista[i] if i < len(pis_lista) else None,
                'endereco_prestador': enderecos[i] if i < len(enderecos) else None,
                'banco': bancos[i] if i < len(bancos) else None,
                'agencia': agencias[i] if i < len(agencias) else None,
                'conta': contas[i] if i < len(contas) else None,
                'chave_pix': chaves[i] if i < len(chaves) else None,
            })

        if not prestadores:
            flash('Adicione pelo menos um prestador à solicitação.')
            return render_pagina('Serviço Externo - Pessoa Física',
                                 preservar_preenchimento(montar_formulario_pf(), request.form))

        solicitacao, era_correcao = obter_solicitacao_para_gravar(
            'servico_externo_pf',
            atividade_id=request.form.get('atividade_id') or None,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=valor_total_solicitacao,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
        )
        if era_correcao:
            PrestadorServico.query.filter_by(solicitacao_id=solicitacao.id).delete()

        for dados in prestadores:
            db.session.add(PrestadorServico(solicitacao_id=solicitacao.id, **dados))

        db.session.commit()
        if era_correcao:
            flash(f'Solicitação corrigida e reenviada, protocolo {protocolo(solicitacao)}!', 'sucesso')
        else:
            flash('Solicitação de serviço externo (PF) enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    solicitacao_corrigindo = carregar_solicitacao_para_correcao(request.args.get('corrigir_id'))
    if solicitacao_corrigindo:
        dados_edicao = _dados_edicao_servico_pf(solicitacao_corrigindo)
        if dados_edicao:
            return render_pagina('Serviço Externo - Pessoa Física',
                                 preservar_preenchimento(montar_formulario_pf(), dados_edicao))

    return render_pagina('Serviço Externo - Pessoa Física', com_vinculo_atividade(montar_formulario_pf()))


def montar_formulario_pj():
    return SERVICO_EXTERNO_PJ_TEMPLATE.replace('__OPCOES_COORDENACAO__',
                                               montar_opcoes_coordenacoes())


@app.route('/solicitacao/servico-externo-pj', methods=['GET', 'POST'])
@login_required
def servico_externo_pj_form():
    resultado_bloqueio = bloquear_se_travado()
    if resultado_bloqueio:
        return resultado_bloqueio

    if request.method == 'POST':
        cnpj = request.form.get('cnpj')
        if not cnpj_tem_14_digitos(cnpj):
            flash('Informe o CNPJ com 14 dígitos, no formato 00.000.000/0000-00.')
            return render_pagina('Serviço Externo - Pessoa Jurídica',
                                 preservar_preenchimento(montar_formulario_pj(), request.form))

        telefone_ok, telefone_empresa = montar_telefone(
            request.form.get('ddd_prestador'), request.form.get('telefone_prestador'))
        if not telefone_ok:
            flash('Informe o telefone da empresa: DDD com 2 dígitos e número com 8 ou 9 dígitos.')
            return render_pagina('Serviço Externo - Pessoa Jurídica',
                                 preservar_preenchimento(montar_formulario_pj(), request.form))

        valor = float(request.form.get('valor_servico') or 0)

        solicitacao, era_correcao = obter_solicitacao_para_gravar(
            'servico_externo_pj',
            atividade_id=request.form.get('atividade_id') or None,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=valor,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
        )
        if era_correcao:
            PrestadorServico.query.filter_by(solicitacao_id=solicitacao.id).delete()

        db.session.add(PrestadorServico(
            solicitacao_id=solicitacao.id,
            tipo_prestador='PJ',
            categoria_servico='Pessoa Jurídica',
            nome_servico=request.form.get('nome_servico'),
            fornecedor_sugerido=request.form.get('fornecedor_sugerido'),
            especificacao=request.form.get('especificacao'),
            justificativa=request.form.get('justificativa'),
            valor_servico=valor,
            nome_empresa=request.form.get('nome_empresa'),
            cnpj=formatar_cnpj(cnpj),
            telefone_prestador=telefone_empresa,
            banco=request.form.get('banco'),
            agencia=request.form.get('agencia'),
            conta=request.form.get('conta'),
            chave_pix=request.form.get('chave_pix'),
        ))

        db.session.commit()
        if era_correcao:
            flash(f'Solicitação corrigida e reenviada, protocolo {protocolo(solicitacao)}!', 'sucesso')
        else:
            flash('Solicitação de serviço externo (PJ) enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    solicitacao_corrigindo = carregar_solicitacao_para_correcao(request.args.get('corrigir_id'))
    if solicitacao_corrigindo:
        dados_edicao = _dados_edicao_servico_pj(solicitacao_corrigindo)
        if dados_edicao:
            return render_pagina('Serviço Externo - Pessoa Jurídica',
                                 preservar_preenchimento(montar_formulario_pj(), dados_edicao))

    return render_pagina('Serviço Externo - Pessoa Jurídica', com_vinculo_atividade(montar_formulario_pj()))


# ---------------- CADASTROS: SERVIÇOS EXTERNOS (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/servico-externo')
@login_required
def cadastro_servico_externo():
    somente_organizador_ou_analista()

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

    <h3 style="margin-top:25px;">ISS - Imposto Sobre Serviços (Pessoa Física)</h3>
    <div style="font-size:11px; color:#888; margin-bottom:10px;">
        Alíquota do ISS retido sobre a prestação de serviço PF, calculada automaticamente
        pelo sistema sobre o valor do serviço. O solicitante não pode alterar este valor.
    </div>
    <form method="POST" action="{url_for('cadastro_servico_externo_atualizar_iss')}" style="max-width:300px;">
        <label>Alíquota do ISS (%):</label><br>
        <input type="number" step="0.01" min="0" max="100" name="aliquota_iss"
               value="{obter_configuracao(CHAVE_ALIQUOTA_ISS, ALIQUOTA_ISS_PADRAO)}"
               style="padding:6px; width:150px; margin-bottom:10px;"><br>
        <button type="submit" class="btn btn-salvar">Salvar alíquota</button>
    </form>
    """
    return render_pagina('Cadastro de Serviços Externos', conteudo)


@app.route('/cadastros/servico-externo/adicionar', methods=['POST'])
@login_required
def cadastro_servico_externo_adicionar():
    somente_organizador_ou_analista()
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
    somente_organizador_ou_analista()
    tipo = TipoServicoExterno.query.get_or_404(tipo_id)
    tipo.nome = request.form.get('nome', '').strip()
    tipo.valor = request.form.get('valor')
    db.session.commit()
    flash('Categoria atualizada com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_servico_externo'))


@app.route('/cadastros/travar-solicitacoes', methods=['GET', 'POST'])
@login_required
def cadastro_travar_solicitacoes():
    somente_organizador_ou_analista()

    if request.method == 'POST':
        acao = request.form.get('acao')

        if acao == 'travar':
            mensagem = (request.form.get('mensagem') or '').strip() or MENSAGEM_TRAVAMENTO_PADRAO

            registro_flag = Configuracao.query.filter_by(chave=CHAVE_SOLICITACOES_TRAVADAS).first()
            if registro_flag:
                registro_flag.valor = 1
            else:
                db.session.add(Configuracao(chave=CHAVE_SOLICITACOES_TRAVADAS, valor=1))

            registro_msg = ConfiguracaoTexto.query.filter_by(chave=CHAVE_MENSAGEM_TRAVAMENTO).first()
            if registro_msg:
                registro_msg.valor = mensagem
            else:
                db.session.add(ConfiguracaoTexto(chave=CHAVE_MENSAGEM_TRAVAMENTO, valor=mensagem))

            registrar_auditoria('travou_solicitacoes', None, mensagem)
            db.session.commit()
            flash('Novas solicitações travadas. Ninguém consegue enviar até você destravar.', 'sucesso')

        elif acao == 'destravar':
            registro_flag = Configuracao.query.filter_by(chave=CHAVE_SOLICITACOES_TRAVADAS).first()
            if registro_flag:
                registro_flag.valor = 0
            else:
                db.session.add(Configuracao(chave=CHAVE_SOLICITACOES_TRAVADAS, valor=0))

            registrar_auditoria('destravou_solicitacoes', None, '')
            db.session.commit()
            flash('Solicitações reabertas.', 'sucesso')

        return redirect(url_for('cadastro_travar_solicitacoes'))

    travado = solicitacoes_estao_travadas()
    mensagem_atual = mensagem_travamento()

    if travado:
        situacao = """
        <div class="bloco" style="border-left:4px solid #c0392b; background:#fdeceb; max-width:700px;">
            <strong style="color:#c0392b; font-size:15px;">🔒 Solicitações travadas no momento</strong>
            <div style="font-size:12.5px; margin-top:6px; color:#666;">
                Ninguém consegue abrir nem enviar uma solicitação nova enquanto isto estiver ativo.
                Solicitações que já estavam em andamento (correção, anexos, aprovação) não são afetadas.
            </div>
        </div>
        """
        acao_form = f"""
        <form method="POST" style="margin-top:16px;" onsubmit="return confirm('Reabrir as solicitações agora?');">
            <input type="hidden" name="acao" value="destravar">
            <button type="submit" class="btn btn-salvar" style="padding:11px 20px; background:#2e7d32;">
                Destravar solicitações
            </button>
        </form>
        """
    else:
        situacao = """
        <div class="bloco" style="border-left:4px solid #2e7d32; background:#eef5ee; max-width:700px;">
            <strong style="color:#2e7d32; font-size:15px;">🔓 Solicitações abertas normalmente</strong>
        </div>
        """
        acao_form = f"""
        <form method="POST" style="margin-top:16px; max-width:600px;">
            <input type="hidden" name="acao" value="travar">
            <label>Mensagem que aparecerá para quem tentar enviar uma solicitação:</label><br>
            <textarea name="mensagem" rows="3" style="width:100%; padding:8px; margin:6px 0 12px;"
                      placeholder="{MENSAGEM_TRAVAMENTO_PADRAO}">{mensagem_atual if mensagem_atual != MENSAGEM_TRAVAMENTO_PADRAO else ''}</textarea>
            <button type="submit" class="btn" style="padding:11px 20px; background:#c0392b; color:#fff;">
                Travar solicitações
            </button>
        </form>
        """

    conteudo = f"""
    <h2>Travar Solicitações</h2>
    <div style="font-size:12.5px; color:#666; margin-bottom:16px; max-width:700px;">
        Use antes do horário-limite semanal de envio para a reunião de lotes, para impedir o
        envio de solicitações de última hora. Ninguém, de nenhum perfil, consegue abrir um
        formulário de nova solicitação enquanto estiver travado.
    </div>
    {situacao}
    {acao_form}
    """
    return render_pagina('Travar Solicitações', conteudo)


@app.route('/cadastros/servico-externo/iss/atualizar', methods=['POST'])
@login_required
def cadastro_servico_externo_atualizar_iss():
    somente_organizador_ou_analista()
    novo_valor = request.form.get('aliquota_iss')

    registro_config = Configuracao.query.filter_by(chave=CHAVE_ALIQUOTA_ISS).first()
    if registro_config:
        registro_config.valor = novo_valor
    else:
        db.session.add(Configuracao(chave=CHAVE_ALIQUOTA_ISS, valor=novo_valor))
    db.session.commit()

    flash('Alíquota do ISS atualizada com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_servico_externo'))


@app.route('/cadastros/servico-externo/<int:tipo_id>/excluir', methods=['POST'])
@login_required
def cadastro_servico_externo_excluir(tipo_id):
    somente_organizador_ou_analista()
    tipo = TipoServicoExterno.query.get_or_404(tipo_id)
    nome = tipo.nome
    db.session.delete(tipo)
    db.session.commit()
    flash(f'Categoria "{nome}" excluída com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_servico_externo'))


# ---------------- SOLICITAÇÃO: RANCHO ----------------
def montar_linhas_itens_rancho():
    itens = ItemRancho.query.order_by(ItemRancho.ordem, ItemRancho.nome).all()
    html = ''
    categoria_atual = None

    for item in itens:
        if item.categoria != categoria_atual:
            categoria_atual = item.categoria
            html += f"""
            <tr><td colspan="6" style="background:#e8eef3; font-weight:bold; padding:6px;">{categoria_atual}</td></tr>
            """

        busca = f'https://www.google.com/search?tbm=shop&q={item.nome.split("(")[0].strip().replace(" ", "+")}'
        html += f"""
        <tr>
            <td style="font-size:12px;">{item.nome}</td>
            <td style="text-align:center; font-size:11px; color:#666;">{item.unidade}</td>
            <td>
                <input type="hidden" name="item_id[]" value="{item.id}">
                <input type="hidden" name="item_qtd_calculada[]" class="qtd-calculada-hidden" value="0">
                <input type="number" step="1" min="0" name="item_qtd[]" class="qtd-item"
                       data-fator="{float(item.fator_consumo or 0)}"
                       data-valor="{float(item.valor_unitario or 0)}"
                       data-refeicoes="{item.refeicoes or 'todas'}"
                       data-calculado="0"
                       value="0" style="width:80px; padding:4px;">
            </td>
            <td style="text-align:center;">
                <input type="checkbox" class="nao-comprar" style="width:auto; transform:scale(1.2);">
            </td>
            <td style="text-align:right; font-size:12px;" class="subtotal-item">R$ 0,00</td>
            <td style="text-align:center;">
                <a href="{busca}" target="_blank" class="btn-atalho" style="padding:2px 8px; font-size:11px;">R$ ?</a>
            </td>
        </tr>
        """

    return html


RANCHO_FORM_TEMPLATE = """
<div style="margin-bottom:14px;"><a href="/ajuda#rancho" target="_blank" class="btn-atalho">Dúvidas sobre rancho? Consulte a Central de Ajuda</a></div>
<form method="POST" style="max-width: 850px;" id="form-rancho">
    <input type="hidden" name="corrigir_id" value="">
    <h3>Dados gerais</h3>
    <label>Ponto Focal:</label><br>
    <input type="text" name="ponto_focal" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Atividade/Projeto relacionado: <span style="color:red;">*</span></label><br>
    <input type="text" name="atividade_projeto" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Coordenação Solicitante: <span style="color:red;">*</span></label><br>
    <select name="coordenacao_solicitante" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        __OPCOES_COORDENACAO__
    </select><br>

    <label>Contato (telefone ou e-mail): <span style="color:red;">*</span></label><br>
    <input type="text" name="contato_solicitante" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Responsável pela retirada: <span style="color:red;">*</span></label><br>
    <input type="text" name="responsavel_retirada" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Período da atividade: <span style="color:red;">*</span></label><br>
    <input type="text" name="periodo_atividade" required placeholder="Ex: 10/09/2026 a 18/09/2026" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Data para entrega do material: <span style="color:red;">*</span></label><br>
    <input type="date" name="data_entrega" required style="padding:6px; margin-bottom:10px;"><br>

    <label>Local de entrega: <span style="color:red;">*</span></label><br>
    <select name="local_entrega" required style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        __OPCOES_LOCAIS__
    </select><br>

    <div class="bloco">
        <label>Nº total de pessoas: <span style="color:red;">*</span></label><br>
        <input type="number" name="num_pessoas" id="num_pessoas" min="1" required style="padding:6px; margin-bottom:10px; width:100px;"><br>

        <label>Nº total de dias: <span style="color:red;">*</span></label><br>
        <input type="number" name="num_dias" id="num_dias" min="1" required style="padding:6px; margin-bottom:10px; width:100px;"><br>

        <label>Refeições a serem fornecidas: <span style="color:red;">*</span></label><br>
        <select name="tipo_refeicao" id="tipo_refeicao" required style="padding:6px; margin-bottom:6px; width:280px;">
            <option value="todas" selected>Café da manhã, almoço e jantar</option>
            <option value="cafe">Somente café da manhã</option>
            <option value="almoco">Somente almoço</option>
            <option value="jantar">Somente jantar</option>
        </select>
        <div style="font-size:11px; color:#888; margin-bottom:10px;">
            A quantidade calculada é ajustada conforme as refeições selecionadas - fornecer
            apenas uma refeição reduz proporcionalmente os itens sugeridos.
        </div>

        <button type="button" id="btn-calcular" class="btn btn-salvar" style="padding:8px 16px;">Calcular quantidades</button>
        <div style="font-size:11px; color:#888; margin-top:6px;">
            As quantidades são calculadas por pessoa/dia e arredondadas para cima (sem fração).
            Você pode alterar qualquer valor manualmente, ou deixar 0 para não solicitar o item.<br>
            <strong>Se o nº de pessoas ou o nº de dias ficar em branco, todas as quantidades são zeradas automaticamente.</strong>
        </div>
    </div>

    <h3>Itens do rancho</h3>
    <div class="bloco" style="background:#eef5ee; border-color:#c8ddc8;">
        <strong style="font-size:13px;">Como as quantidades são calculadas</strong>
        <div style="font-size:12px; color:#444; margin-top:6px; line-height:1.5;">
            Cada item tem um <strong>fator de consumo em gramas por pessoa por dia</strong>, considerando as três
            refeições (café da manhã, almoço e jantar). A quantidade sugerida é
            <em>fator × nº de pessoas × nº de dias</em>, sempre <strong>arredondada para cima em números inteiros</strong>
            (sem frações de quilo).<br><br>
            A base de referência é a <strong>Pesquisa de Orçamentos Familiares (POF) do IBGE</strong>, que registra o
            consumo alimentar médio per capita do brasileiro — feijão 142,2 g/dia, arroz 131,4 g/dia e café 163,2 g/dia
            na POF 2017-2018, e carne bovina 63 g/dia na POF 2008-2009. Os fatores usados aqui são
            <strong>ajustados para a realidade de atividade de campo</strong>, onde o alimento é adquirido cru
            (o arroz cozido pesa cerca de 2,5 vezes o peso do grão seco) e o esforço físico é maior que a média da população.<br><br>
            As quantidades são <strong>sugestões</strong>: altere qualquer valor conforme a necessidade da atividade.
            Para excluir um item da compra, marque a caixa <strong>"Não comprar"</strong> na linha correspondente —
            o item fica zerado e não entra na solicitação que chega ao Executor.
        </div>
    </div>
    <div style="font-size:11px; color:#888; margin-bottom:8px;">
        O botão <strong>R$ ?</strong> abre uma consulta de preço do item em nova aba.
        Referência oficial de preços:
        <a href="https://www.dieese.org.br/cesta/produto" target="_blank">DIEESE - Cesta Básica</a>
    </div>

    <table style="max-width:850px;">
        <tr>
            <th>Item</th><th style="width:70px;">Unid.</th><th style="width:110px;">Qtd</th>
            <th style="width:90px;">Não comprar</th>
            <th style="width:110px;">Subtotal</th><th style="width:70px;">Preço</th>
        </tr>
        __LINHAS_ITENS__
    </table>

    <div id="bloco_justificativa_aumento" class="bloco" style="display:none; border-left:4px solid #b35c00;">
        <strong style="color:#b35c00;">Aumento de quantidade acima do calculado</strong>
        <div style="font-size:11.5px; color:#666; margin:6px 0 10px;">
            O cálculo automático segue a Pesquisa de Orçamentos Familiares (POF) do IBGE, ajustada
            para o consumo em atividade de campo. Como pelo menos um item foi aumentado acima do
            valor sugerido, é necessário justificar o acréscimo.
        </div>
        <label>Justificativa do aumento: <span style="color:red;">*</span></label><br>
        <textarea name="justificativa_aumento" id="justificativa_aumento" rows="2"
                  style="width:100%; padding:6px;"></textarea>
    </div>

    <div class="bloco" style="margin-top:15px;">
        <strong>Detalhamento da carne vermelha (kg)</strong>
        <div style="font-size:11px; color:#888; margin-bottom:8px;">
            A soma dos três tipos deve ser igual à quantidade total de carne vermelha solicitada acima.
        </div>
        <label>Carne em bifes:</label><br>
        <input type="number" step="1" min="0" name="carne_bifes" id="carne_bifes" value="0" style="padding:6px; margin-bottom:8px; width:100px;"><br>

        <label>Carne picada de panela:</label><br>
        <input type="number" step="1" min="0" name="carne_picada" id="carne_picada" value="0" style="padding:6px; margin-bottom:8px; width:100px;"><br>

        <label>Carne com osso:</label><br>
        <input type="number" step="1" min="0" name="carne_osso" id="carne_osso" value="0" style="padding:6px; margin-bottom:8px; width:100px;"><br>

        <div id="aviso_carne" style="font-size:12px; color:#a00; display:none;">
            A soma dos tipos de carne não confere com a quantidade total de carne vermelha solicitada.
        </div>
    </div>

    <div class="bloco">
        <label>Água Mineral 20L (garrafões):</label><br>
        <input type="number" min="0" name="agua_mineral_20l" value="0" style="padding:6px; margin-bottom:8px; width:100px;"><br>
        <div style="font-size:11px; color:#888;">
            É necessário fornecer os garrafões. Verifique se a base tem filtro antes de solicitar.
        </div>
    </div>

    <h3>Itens adicionais</h3>
    <div style="font-size:11px; color:#888; margin-bottom:8px;">
        Itens não contemplados nas listas acima. Sujeito à aprovação.
    </div>
    <div id="adicionais-container"></div>
    <button type="button" id="btn-adicionar-item" class="btn-atalho">+ Adicionar item</button>

    <h3 style="margin-top:20px;">Valor estimado total</h3>
    <input type="text" id="valor_total_display" readonly style="padding:8px; background:#f5f5f5; width:180px; font-weight:bold; font-size:15px;" value="R$ 0,00">
    <input type="hidden" name="valor_total_calculado" id="valor_total_hidden" value="0">
    <div style="font-size:11px; color:#888; margin-top:6px; margin-bottom:15px;">
        Valor estimado com base nos preços de referência cadastrados. O valor real da nota é lançado após a compra.
    </div>

    <label>Justificativa da solicitação: <span style="color:red;">*</span></label><br>
    <textarea name="justificativa" required style="width:100%; padding:6px; margin-bottom:10px;" rows="3"></textarea><br>

    <label>Observação (se houver):</label><br>
    <textarea name="observacao" style="width:100%; padding:6px; margin-bottom:15px;" rows="3"></textarea><br>

    <button type="submit" style="padding:10px 20px; background:#37784D; color:white; border:none; border-radius:4px; cursor:pointer; font-weight:600;">Enviar solicitação</button>
</form>

<template id="template-adicional">
    <div class="bloco-adicional" style="margin-bottom:8px; display:flex; gap:8px; align-items:center;">
        <input type="text" name="adicional_nome[]" placeholder="Nome do item" style="flex:1; padding:6px;">
        <input type="number" step="1" min="0" name="adicional_qtd[]" placeholder="Qtd" step="1" min="0" style="width:90px; padding:6px;">
        <input type="text" name="adicional_unidade[]" placeholder="Unid." style="width:80px; padding:6px;">
        <button type="button" class="btn btn-excluir btn-remover-adicional">Remover</button>
    </div>
</template>

<script>
function formatarReal(valor) {
    return 'R$ ' + valor.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function atualizarSubtotais() {
    var total = 0;
    document.querySelectorAll('.qtd-item').forEach(function(campo) {
        var qtd = parseFloat(campo.value) || 0;
        var valorUnit = parseFloat(campo.dataset.valor) || 0;
        var subtotal = qtd * valorUnit;
        total += subtotal;
        var celula = campo.closest('tr').querySelector('.subtotal-item');
        celula.textContent = formatarReal(subtotal);
    });
    document.getElementById('valor_total_display').value = formatarReal(total);
    document.getElementById('valor_total_hidden').value = total.toFixed(2);
}

// Cada item da tabela de referência (POF/IBGE) indica em qual(is) refeição(ões)
// costuma entrar - ex: café, pão e margarina só no café da manhã; arroz e
// feijão só no almoço/jantar; sabão e gás em qualquer situação ("todas").
// Ao escolher uma refeição específica, itens que não fazem parte dela são
// automaticamente zerados; os demais recebem a quantidade cheia calculada
// pelo fator de consumo.
function itemAplicavelNaRefeicao(campo, refeicaoEscolhida) {
    if (refeicaoEscolhida === 'todas') { return true; }
    var refeicoesDoItem = (campo.dataset.refeicoes || 'todas').split(',');
    return refeicoesDoItem.indexOf('todas') !== -1 || refeicoesDoItem.indexOf(refeicaoEscolhida) !== -1;
}

function calcularQuantidades() {
    var pessoas = parseInt(document.getElementById('num_pessoas').value) || 0;
    var dias = parseInt(document.getElementById('num_dias').value) || 0;

    if (pessoas <= 0 || dias <= 0) {
        alert('Informe o número de pessoas e o número de dias antes de calcular.');
        return;
    }

    var refeicaoEscolhida = document.getElementById('tipo_refeicao').value;

    document.querySelectorAll('.qtd-item').forEach(function(campo) {
        var caixa = campo.closest('tr').querySelector('.nao-comprar');
        var aplicavel = itemAplicavelNaRefeicao(campo, refeicaoEscolhida);
        var ocultoCalculado = campo.parentElement.querySelector('.qtd-calculada-hidden');

        if ((caixa && caixa.checked) || !aplicavel) {
            campo.value = 0;
            campo.dataset.calculado = 0;
            if (ocultoCalculado) { ocultoCalculado.value = 0; }
            return;
        }

        var fator = parseFloat(campo.dataset.fator) || 0;
        if (fator > 0) {
            var sugerido = Math.ceil(fator * pessoas * dias);
            campo.value = sugerido;
            campo.dataset.calculado = sugerido;
            if (ocultoCalculado) { ocultoCalculado.value = sugerido; }
        }
        // fator igual a zero (ex: sabão, gás, desinfetante) não tem fórmula -
        // é preenchido manualmente e não é mexido aqui, exceto se marcado
        // "não comprar" ou se não pertencer à refeição escolhida (já tratado acima)
    });

    atualizarSubtotais();
    verificarAumentoQuantidade();
}

function recalcularSeJaPreenchido() {
    var pessoas = parseInt(document.getElementById('num_pessoas').value) || 0;
    var dias = parseInt(document.getElementById('num_dias').value) || 0;
    if (pessoas > 0 && dias > 0) { calcularQuantidades(); }
}

function verificarAumentoQuantidade() {
    var algumAumentou = false;
    document.querySelectorAll('.qtd-item').forEach(function(campo) {
        var calculado = parseFloat(campo.dataset.calculado) || 0;
        var atual = parseFloat(campo.value) || 0;
        if (atual > calculado) { algumAumentou = true; }
    });

    var bloco = document.getElementById('bloco_justificativa_aumento');
    var campoJustificativa = document.getElementById('justificativa_aumento');
    bloco.style.display = algumAumentou ? 'block' : 'none';
    campoJustificativa.required = algumAumentou;
}
window.verificarAumentoQuantidade = verificarAumentoQuantidade;

function zerarQuantidades() {
    document.querySelectorAll('.qtd-item').forEach(function(campo) {
        campo.value = 0;
    });
    atualizarSubtotais();
}

function sincronizarCalculadoRestaurado() {
    // depois de restaurar um formulario de correcao, o campo oculto
    // qtd-calculada-hidden ja tem o valor certo, mas o atributo JS
    // data-calculado (usado por verificarAumentoQuantidade) so existe no
    // HTML original - aqui sincroniza um com o outro antes de checar
    document.querySelectorAll('.qtd-item').forEach(function (campo) {
        var oculto = campo.parentElement.querySelector('.qtd-calculada-hidden');
        if (oculto) { campo.dataset.calculado = oculto.value; }
    });
    verificarAumentoQuantidade();
}
window.sincronizarCalculadoRestaurado = sincronizarCalculadoRestaurado;

function verificarPessoasDias() {
    var pessoas = parseInt(document.getElementById('num_pessoas').value) || 0;
    var dias = parseInt(document.getElementById('num_dias').value) || 0;
    var botao = document.getElementById('btn-calcular');

    if (pessoas <= 0 || dias <= 0) {
        zerarQuantidades();
        botao.disabled = true;
        botao.style.opacity = '0.5';
        botao.style.cursor = 'not-allowed';
    } else {
        botao.disabled = false;
        botao.style.opacity = '1';
        botao.style.cursor = 'pointer';
    }
}

document.getElementById('num_pessoas').addEventListener('input', verificarPessoasDias);
document.getElementById('num_dias').addEventListener('input', verificarPessoasDias);

document.querySelectorAll('.nao-comprar').forEach(function(caixa) {
    caixa.addEventListener('change', function() {
        var campo = caixa.closest('tr').querySelector('.qtd-item');
        if (caixa.checked) {
            campo.value = 0;
            campo.readOnly = true;
            campo.style.background = '#eee';
        } else {
            campo.readOnly = false;
            campo.style.background = 'white';
        }
        atualizarSubtotais();
    });
});

document.getElementById('btn-calcular').addEventListener('click', calcularQuantidades);
document.getElementById('tipo_refeicao').addEventListener('change', recalcularSeJaPreenchido);

document.querySelectorAll('.qtd-item').forEach(function(campo) {
    campo.addEventListener('input', function () {
        atualizarSubtotais();
        verificarAumentoQuantidade();
    });
});

function criarBlocoAdicional() {
    var template = document.getElementById('template-adicional');
    var clone = template.content.cloneNode(true);
    clone.querySelector('.btn-remover-adicional').addEventListener('click', function(evento) {
        evento.target.closest('.bloco-adicional').remove();
    });
    document.getElementById('adicionais-container').appendChild(clone);
}
window.criarBlocoAdicional = criarBlocoAdicional;

document.getElementById('btn-adicionar-item').addEventListener('click', criarBlocoAdicional);

atualizarSubtotais();
verificarPessoasDias();
verificarAumentoQuantidade();
</script>
"""


def montar_formulario_rancho():
    html = RANCHO_FORM_TEMPLATE.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    html = html.replace('__OPCOES_LOCAIS__', montar_opcoes(LOCAIS_ENTREGA_RANCHO))
    html = html.replace('__LINHAS_ITENS__', montar_linhas_itens_rancho())
    return html


@app.route('/solicitacao/rancho', methods=['GET', 'POST'])
@login_required
def rancho_form():
    resultado_bloqueio = bloquear_se_travado()
    if resultado_bloqueio:
        return resultado_bloqueio

    if request.method == 'POST':
        import math

        num_pessoas = int(request.form.get('num_pessoas') or 0)
        num_dias = int(request.form.get('num_dias') or 0)

        tipo_refeicao = request.form.get('tipo_refeicao') or 'todas'

        ids_itens = request.form.getlist('item_id[]')
        qtds_itens = request.form.getlist('item_qtd[]')

        itens_selecionados = []
        valor_total_solicitacao = 0
        algum_item_aumentado = False

        for i in range(len(ids_itens)):
            quantidade = float(qtds_itens[i] or 0)
            if quantidade <= 0:
                continue
            item = ItemRancho.query.get(int(ids_itens[i]))
            if not item:
                continue

            # mesma regra do navegador: item que não pertence à refeição
            # escolhida deveria estar zerado; se veio preenchido, conta como
            # aumento. Para os aplicáveis, compara com a sugestão do fator
            # de consumo (POF/IBGE) - calculada aqui mesmo, no servidor, e
            # guardada para o Analista/Aprovador ver ao lado da quantidade final.
            refeicoes_item = (item.refeicoes or 'todas').split(',')
            aplicavel = tipo_refeicao == 'todas' or 'todas' in refeicoes_item or tipo_refeicao in refeicoes_item

            fator = float(item.fator_consumo or 0)
            sugerido = None
            if not aplicavel:
                if quantidade > 0:
                    algum_item_aumentado = True
            elif fator > 0 and num_pessoas > 0 and num_dias > 0:
                sugerido = math.ceil(fator * num_pessoas * num_dias)
                if quantidade > sugerido:
                    algum_item_aumentado = True

            valor_unitario = float(item.valor_unitario or 0)
            valor_total_item = quantidade * valor_unitario
            valor_total_solicitacao += valor_total_item
            itens_selecionados.append({
                'nome': item.nome,
                'categoria': item.categoria,
                'unidade': item.unidade,
                'quantidade': quantidade,
                'quantidade_calculada': sugerido,
                'valor_unitario': valor_unitario,
                'valor_total_item': valor_total_item,
                'adicional': False,
            })

        justificativa_aumento = (request.form.get('justificativa_aumento') or '').strip()
        if algum_item_aumentado and not justificativa_aumento:
            flash('Pelo menos um item foi aumentado acima da quantidade calculada. '
                  'Informe a justificativa do aumento.')
            return render_pagina('Solicitação de Rancho',
                                 preservar_preenchimento(montar_formulario_rancho(), request.form))

        nomes_adicionais = request.form.getlist('adicional_nome[]')
        qtds_adicionais = request.form.getlist('adicional_qtd[]')
        unidades_adicionais = request.form.getlist('adicional_unidade[]')

        for i in range(len(nomes_adicionais)):
            nome = (nomes_adicionais[i] or '').strip()
            if not nome:
                continue
            quantidade = float(qtds_adicionais[i] or 0)
            itens_selecionados.append({
                'nome': nome,
                'categoria': 'Itens adicionais',
                'unidade': unidades_adicionais[i] if i < len(unidades_adicionais) else '',
                'quantidade': quantidade,
                'valor_unitario': 0,
                'valor_total_item': 0,
                'adicional': True,
            })

        if not itens_selecionados:
            flash('Informe a quantidade de pelo menos um item.')
            return render_pagina('Solicitação de Rancho',
                                 preservar_preenchimento(montar_formulario_rancho(), request.form))

        justificativa = (request.form.get('justificativa') or '').strip()
        if not justificativa:
            flash('Informe a justificativa da solicitação.')
            return render_pagina('Solicitação de Rancho',
                                 preservar_preenchimento(montar_formulario_rancho(), request.form))

        carne_bifes = float(request.form.get('carne_bifes') or 0)
        carne_picada = float(request.form.get('carne_picada') or 0)
        carne_osso = float(request.form.get('carne_osso') or 0)

        total_carne_solicitada = sum(
            i['quantidade'] for i in itens_selecionados if 'Carne vermelha' in i['nome']
        )
        soma_tipos_carne = carne_bifes + carne_picada + carne_osso

        if total_carne_solicitada > 0 and abs(soma_tipos_carne - total_carne_solicitada) > 0.01:
            flash('A soma dos tipos de carne vermelha deve ser igual à quantidade total solicitada.')
            return render_pagina('Solicitação de Rancho',
                                 preservar_preenchimento(montar_formulario_rancho(), request.form))

        solicitacao, era_correcao = obter_solicitacao_para_gravar(
            'rancho',
            atividade_id=request.form.get('atividade_id') or None,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=valor_total_solicitacao,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
            observacao=request.form.get('observacao'),
        )
        if era_correcao:
            SolicitacaoRancho.query.filter_by(solicitacao_id=solicitacao.id).delete()
            ItemSolicitacaoRancho.query.filter_by(solicitacao_id=solicitacao.id).delete()

        rancho = SolicitacaoRancho(
            solicitacao_id=solicitacao.id,
            responsavel_retirada=request.form.get('responsavel_retirada'),
            periodo_atividade=request.form.get('periodo_atividade'),
            data_entrega=request.form.get('data_entrega'),
            local_entrega=request.form.get('local_entrega'),
            num_pessoas=num_pessoas,
            num_dias=num_dias,
            tipo_refeicao=tipo_refeicao,
            carne_bifes=carne_bifes,
            carne_picada=carne_picada,
            carne_osso=carne_osso,
            agua_mineral_20l=int(request.form.get('agua_mineral_20l') or 0),
            justificativa=justificativa,
            justificativa_aumento=justificativa_aumento or None,
            observacao=request.form.get('observacao'),
        )
        db.session.add(rancho)

        for dados in itens_selecionados:
            db.session.add(ItemSolicitacaoRancho(
                solicitacao_id=solicitacao.id,
                nome_item=dados['nome'],
                categoria=dados['categoria'],
                unidade=dados['unidade'],
                quantidade=dados['quantidade'],
                quantidade_calculada=dados.get('quantidade_calculada'),
                valor_unitario=dados['valor_unitario'],
                valor_total_item=dados['valor_total_item'],
                item_adicional=dados['adicional'],
            ))

        db.session.commit()
        if era_correcao:
            flash(f'Solicitação corrigida e reenviada, protocolo {protocolo(solicitacao)}!', 'sucesso')
        else:
            flash('Solicitação de rancho enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    solicitacao_corrigindo = carregar_solicitacao_para_correcao(request.args.get('corrigir_id'))
    if solicitacao_corrigindo:
        dados_edicao = _dados_edicao_rancho(solicitacao_corrigindo)
        if dados_edicao:
            return render_pagina('Solicitação de Rancho',
                                 preservar_preenchimento(montar_formulario_rancho(), dados_edicao))

    return render_pagina('Solicitação de Rancho', com_vinculo_atividade(montar_formulario_rancho()))


# ---------------- CADASTROS: RANCHO (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/rancho')
@login_required
def cadastro_rancho():
    somente_organizador_ou_analista()

    itens = ItemRancho.query.order_by(ItemRancho.ordem, ItemRancho.nome).all()
    linhas_html = ''
    for item in itens:
        opcoes_categoria = ''
        for cat in CATEGORIAS_RANCHO:
            sel = 'selected' if item.categoria == cat else ''
            opcoes_categoria += f'<option value="{cat}" {sel}>{cat}</option>'

        opcoes_refeicoes_item = ''
        for valor_ref, rotulo_ref in [('todas', 'Todas'), ('cafe', 'Só café'), ('almoco', 'Só almoço'), ('jantar', 'Só jantar')]:
            sel_ref = 'selected' if (item.refeicoes or 'todas') == valor_ref else ''
            opcoes_refeicoes_item += f'<option value="{valor_ref}" {sel_ref}>{rotulo_ref}</option>'

        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_rancho_atualizar', item_id=item.id)}" style="display:contents;">
            <td><input type="text" name="nome" value="{item.nome}" style="width:200px; padding:4px;"></td>
            <td><select name="categoria" style="padding:4px;">{opcoes_categoria}</select></td>
            <td><select name="refeicoes" style="padding:4px;">{opcoes_refeicoes_item}</select></td>
            <td><input type="text" name="unidade" value="{item.unidade}" style="width:70px; padding:4px;"></td>
            <td><input type="number" step="0.0001" name="fator_consumo" value="{float(item.fator_consumo or 0)}" style="width:90px; padding:4px;"></td>
            <td><input type="number" step="0.01" name="valor_unitario" value="{float(item.valor_unitario or 0)}" style="width:90px; padding:4px;"></td>
            <td><input type="number" name="ordem" value="{item.ordem or 0}" style="width:60px; padding:4px;"></td>
            <td>
                <button type="submit" class="btn btn-salvar">Salvar</button>
            </form>
            <form method="POST" action="{url_for('cadastro_rancho_excluir', item_id=item.id)}" style="display:inline;" onsubmit="return confirm('Excluir o item {item.nome}?');">
                <button type="submit" class="btn btn-excluir">Excluir</button>
            </form>
            </td>
        </tr>
        """

    opcoes_categoria_novo = ''
    for cat in CATEGORIAS_RANCHO:
        opcoes_categoria_novo += f'<option value="{cat}">{cat}</option>'

    conteudo = f"""
    <h2>Itens de Rancho</h2>
    <div style="font-size:12px; color:#666; margin-bottom:12px; max-width:900px;">
        <strong>Fator de consumo</strong> = quantidade por pessoa por dia. A quantidade sugerida no formulário
        é calculada como <em>fator × nº de pessoas × nº de dias</em>, sempre arredondada para cima.
        Deixe o fator em 0 para itens em que a quantidade é definida manualmente pelo solicitante.<br>
        <strong>Valor unitário</strong> = preço de referência usado para estimar o custo da solicitação.
        Atualize periodicamente consultando o
        <a href="https://www.dieese.org.br/cesta/produto" target="_blank">DIEESE - Cesta Básica</a>.
    </div>
    <table style="max-width:1000px;">
        <tr>
            <th>Item</th><th>Categoria</th><th>Refeições</th><th>Unid.</th>
            <th>Fator/pessoa/dia</th><th>Valor unit. (R$)</th><th>Ordem</th><th>Ações</th>
        </tr>
        {linhas_html}
    </table>

    <h3 style="margin-top:25px;">Adicionar novo item</h3>
    <form method="POST" action="{url_for('cadastro_rancho_adicionar')}" style="max-width:400px;">
        <label>Nome do item:</label><br>
        <input type="text" name="nome" required placeholder="Ex: Arroz (kg)" style="padding:6px; width:100%; margin-bottom:10px;"><br>

        <label>Categoria:</label><br>
        <select name="categoria" required style="padding:6px; width:100%; margin-bottom:10px;">
            {opcoes_categoria_novo}
        </select><br>

        <label>Refeições em que o item entra:</label><br>
        <select name="refeicoes" style="padding:6px; width:100%; margin-bottom:10px;">
            <option value="todas">Todas (não depende da refeição)</option>
            <option value="cafe">Só café da manhã</option>
            <option value="almoco">Só almoço</option>
            <option value="jantar">Só jantar</option>
        </select><br>

        <label>Unidade:</label><br>
        <input type="text" name="unidade" required placeholder="kg, un, litro..." style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <label>Fator de consumo (por pessoa/dia):</label><br>
        <input type="number" step="0.0001" name="fator_consumo" value="0" style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <label>Valor unitário de referência (R$):</label><br>
        <input type="number" step="0.01" name="valor_unitario" value="0" style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <label>Ordem de exibição:</label><br>
        <input type="number" name="ordem" value="0" style="padding:6px; width:150px; margin-bottom:10px;"><br>

        <button type="submit" class="btn btn-adicionar">Adicionar item</button>
    </form>
    """
    return render_pagina('Cadastro de Rancho', conteudo)


@app.route('/cadastros/rancho/adicionar', methods=['POST'])
@login_required
def cadastro_rancho_adicionar():
    somente_organizador_ou_analista()
    nome = request.form.get('nome', '').strip()

    if not nome:
        flash('Informe o nome do item.')
        return redirect(url_for('cadastro_rancho'))

    if ItemRancho.query.filter_by(nome=nome).first():
        flash('Já existe um item com esse nome.')
        return redirect(url_for('cadastro_rancho'))

    db.session.add(ItemRancho(
        nome=nome,
        categoria=request.form.get('categoria'),
        unidade=request.form.get('unidade', '').strip(),
        fator_consumo=request.form.get('fator_consumo') or 0,
        valor_unitario=request.form.get('valor_unitario') or 0,
        ordem=request.form.get('ordem') or 0,
        refeicoes=request.form.get('refeicoes') or 'todas',
    ))
    db.session.commit()
    flash(f'Item "{nome}" cadastrado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_rancho'))


@app.route('/cadastros/rancho/<int:item_id>/atualizar', methods=['POST'])
@login_required
def cadastro_rancho_atualizar(item_id):
    somente_organizador_ou_analista()
    item = ItemRancho.query.get_or_404(item_id)
    item.nome = request.form.get('nome', '').strip()
    item.categoria = request.form.get('categoria')
    item.unidade = request.form.get('unidade', '').strip()
    item.fator_consumo = request.form.get('fator_consumo') or 0
    item.valor_unitario = request.form.get('valor_unitario') or 0
    item.ordem = request.form.get('ordem') or 0
    item.refeicoes = request.form.get('refeicoes') or 'todas'
    db.session.commit()
    flash('Item atualizado com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_rancho'))


@app.route('/cadastros/rancho/<int:item_id>/excluir', methods=['POST'])
@login_required
def cadastro_rancho_excluir(item_id):
    somente_organizador_ou_analista()
    item = ItemRancho.query.get_or_404(item_id)
    nome = item.nome
    db.session.delete(item)
    db.session.commit()
    flash(f'Item "{nome}" excluído com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_rancho'))


# ---------------- SOLICITAÇÃO: SEGURO ----------------
def pode_definir_convenio():
    return current_user.perfil in ('analista', 'aprovador') or current_user.is_organizador


# ============================================================================
# MÓDULO: SOLICITAÇÃO DE SEGURO DE VIDA
# Reescrito do zero em 27/08/2026 - consolida tudo em um único lugar, sem
# fragmentos de versões anteriores.
#
# Estrutura:
#   1. PARTICIPANTE_SEGURO_BLOCO - HTML de UM bloco de participante
#   2. SEGURO_FORM_TEMPLATE      - HTML da página inteira
#   3. montar_formulario_seguro()  - monta o HTML final (Python)
#   4. seguro_form()               - rota Flask (GET exibe, POST processa)
# ============================================================================

PARTICIPANTE_SEGURO_BLOCO = """
    <div class="bloco-participante bloco" style="margin-bottom:15px;">
        <strong>Participante <span class="numero-participante">__INDICE__</span></strong>
        <button type="button" class="btn btn-excluir btn-remover-participante" style="float:right; padding:4px 10px;">Remover</button>
        <div style="clear:both;"></div>

        <label>Nome completo: <span style="color:red;">*</span></label><br>
        <input type="text" name="part_nome[]" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>Data de nascimento: <span style="color:red;">*</span></label><br>
        <input type="date" name="part_nascimento[]" required style="padding:6px; margin-bottom:10px;"><br>

        <label>CPF: <span style="color:red;">*</span></label><br>
        <input type="text" name="part_cpf[]" required placeholder="000.000.000-00" maxlength="14" inputmode="numeric" style="padding:6px; margin-bottom:10px; width:180px;"><br>

        <label>RG: <span style="color:red;">*</span></label><br>
        <input type="text" name="part_rg[]" required placeholder="00.000.000-0" style="padding:6px; margin-bottom:10px; width:180px;"><br>

        <label>E-mail: <span style="color:red;">*</span></label><br>
        <input type="email" name="part_email[]" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>Documento (RG ou CPF, foto ou PDF) - opcional:</label><br>
        <input type="file" name="doc_participante[]" accept=".pdf,.jpg,.jpeg,.png" style="margin-bottom:10px;"><br>

        <label>CEP: <span style="color:red;">*</span></label><br>
        <input type="text" name="part_cep[]" class="campo-cep" required placeholder="00000-000" maxlength="9" style="padding:6px; margin-bottom:4px; width:140px;">
        <span class="status-cep" style="font-size:11px; color:#888; margin-left:8px;"></span><br>
        <div style="font-size:11px; color:#888; margin-bottom:10px;">
            Digite o CEP para preencher endereço, bairro, cidade e UF automaticamente.
        </div>

        <label>Endereço: <span style="color:red;">*</span></label><br>
        <input type="text" name="part_logradouro[]" class="campo-logradouro" required placeholder="Rua, avenida" style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>Nº: <span style="color:red;">*</span></label><br>
        <input type="text" name="part_numero[]" required style="padding:6px; margin-bottom:10px; width:120px;"><br>

        <label>Bairro: <span style="color:red;">*</span></label><br>
        <input type="text" name="part_bairro[]" class="campo-bairro" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>Cidade: <span style="color:red;">*</span></label><br>
        <input type="text" name="part_cidade[]" class="campo-cidade" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>UF: <span style="color:red;">*</span></label><br>
        <select name="part_uf[]" class="campo-uf" required style="padding:6px; margin-bottom:10px; width:90px;">
            <option value="">UF</option>
            __OPCOES_ESTADOS__
        </select><br>

        <label>Telefone: <span style="color:red;">*</span></label><br>
        <div style="display:flex; gap:8px; margin-bottom:10px;">
            <input type="text" name="part_ddd[]" required placeholder="DDD" maxlength="3" style="width:70px; padding:6px;">
            <input type="text" name="part_telefone[]" required placeholder="Número" style="width:200px; padding:6px;">
        </div>
    </div>
"""


SEGURO_FORM_TEMPLATE = """
<div style="margin-bottom:14px;"><a href="/ajuda#seguro" target="_blank" class="btn-atalho">Dúvidas sobre seguro? Consulte a Central de Ajuda</a></div>

<form method="POST" enctype="multipart/form-data" style="max-width: 750px;" id="form-seguro">
    <input type="hidden" name="corrigir_id" value="">
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

    __CAMPO_CONVENIO_SEGURO__

    <h3>Dados do deslocamento</h3>
    <div style="font-size:11px; color:#888; margin-bottom:10px;">
        A quantidade de pessoas seguradas é definida pela lista de participantes, mais abaixo
        neste formulário - não precisa informar aqui.
    </div>

    <label>Data de saída do local de origem: <span style="color:red;">*</span></label><br>
    <input type="date" name="data_saida" required style="padding:6px; margin-bottom:10px;"><br>

    <label>Data de retorno ao local de chegada: <span style="color:red;">*</span></label><br>
    <input type="date" name="data_retorno" required style="padding:6px; margin-bottom:10px;"><br>

    <label>Local de origem: <span style="color:red;">*</span></label><br>
    <input type="text" name="local_origem" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Percurso / Pontos de parada: <span style="color:red;">*</span></label><br>
    <textarea name="percurso" required style="width:100%; padding:6px; margin-bottom:10px;" rows="2"></textarea><br>

    <label>Local de retorno: <span style="color:red;">*</span></label><br>
    <input type="text" name="local_retorno" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Tipo de transporte que os segurados utilizarão: <span style="color:red;">*</span></label><br>
    <input type="text" name="tipo_transporte" required placeholder="Ex: Ônibus, van, barco, veículo próprio" style="width:100%; padding:6px; margin-bottom:10px;"><br>

    <label>Distância estimada do percurso (km): <span style="color:red;">*</span></label><br>
    <input type="number" step="1" min="0" name="km_estimado" id="km_estimado" required
           style="padding:6px; margin-bottom:6px; width:150px;"><br>
    <div id="aviso_km" style="display:none; background:#fdeceb; border-left:4px solid #c0392b;
         color:#a02020; padding:11px 14px; border-radius:5px; font-size:12.5px; margin-bottom:12px;">
        <strong>Atenção: distância abaixo de __KM_MINIMO__ km.</strong><br>
        O seguro viagem só oferece cobertura a partir de <strong>__KM_MINIMO__ km</strong> do
        ponto de origem. Confira a distância informada - abaixo desse limite, a contratação
        pode não ser possível.
    </div>
    <div style="font-size:11px; color:#888; margin-bottom:10px;">
        Distância aproximada entre o local de origem e o local mais distante do percurso.
    </div>

    <label>Observação (se houver):</label><br>
    <textarea name="observacao" style="width:100%; padding:6px; margin-bottom:15px;" rows="3"></textarea><br>

    <h3>Lista de participantes para seguro de vida</h3>
    <div style="font-size:11px; color:#888; margin-bottom:10px;">
        Todos os campos de cada participante são obrigatórios.
    </div>

    <div class="bloco" style="border-left:4px solid #37784D; max-width:400px; margin-bottom:16px;">
        <label>Quantas pessoas serão seguradas?</label><br>
        <div style="display:flex; gap:8px; align-items:center; margin-top:6px;">
            <select id="seletor_qtd_participantes" style="padding:7px; width:100px;">
                __OPCOES_QTD_PARTICIPANTES__
            </select>
            <button type="button" id="btn-atualizar-qtd" class="btn-atalho">Atualizar blocos</button>
        </div>
        <div style="font-size:11px; color:#888; margin-top:6px;">
            Escolha a quantidade e clique em "Atualizar blocos" - a página já mostra todos os
            campos prontos para preencher, sem precisar adicionar um por um.
        </div>
    </div>

    <div id="participantes-container">
__BLOCOS_PARTICIPANTES__
    </div>

    <button type="button" id="btn-adicionar-participante" class="btn-atalho" style="margin-top:10px;">+ Adicionar participante</button>

    <br><br>
    <button type="submit" style="padding:10px 20px; background:#2b5876; color:white; border:none; border-radius:4px; cursor:pointer;">Enviar solicitação</button>
</form>

<template id="template-participante">
__TEMPLATE_PARTICIPANTE_VAZIO__
</template>

<script>
var KM_MINIMO = __KM_MINIMO__;

function verificarKm() {
    var campo = document.getElementById('km_estimado');
    var aviso = document.getElementById('aviso_km');
    var km = parseFloat(campo.value);
    aviso.style.display = (campo.value !== '' && km < KM_MINIMO) ? 'block' : 'none';
}
window.verificarKm = verificarKm;
document.getElementById('km_estimado').addEventListener('input', verificarKm);

function renumerarParticipantes() {
    document.querySelectorAll('.bloco-participante').forEach(function (bloco, indice) {
        bloco.querySelector('.numero-participante').textContent = indice + 1;
    });
}

function configurarBuscaCep(bloco) {
    var campoCep = bloco.querySelector('.campo-cep');
    var campoLogradouro = bloco.querySelector('.campo-logradouro');
    var campoBairro = bloco.querySelector('.campo-bairro');
    var campoCidade = bloco.querySelector('.campo-cidade');
    var campoUf = bloco.querySelector('.campo-uf');
    var status = bloco.querySelector('.status-cep');

    campoCep.addEventListener('blur', function () {
        var cep = campoCep.value.replace(/[^0-9]/g, '');
        if (cep.length !== 8) { return; }
        status.textContent = 'Buscando...';
        status.style.color = '#888';

        fetch('https://viacep.com.br/ws/' + cep + '/json/')
            .then(function (resposta) { return resposta.json(); })
            .then(function (dados) {
                if (dados.erro) {
                    status.textContent = 'CEP não encontrado - preencha manualmente';
                    status.style.color = '#a00';
                    return;
                }
                campoLogradouro.value = dados.logradouro || '';
                campoBairro.value = dados.bairro || '';
                campoCidade.value = dados.localidade || '';
                campoUf.value = dados.uf || '';
                status.textContent = 'Endereço preenchido';
                status.style.color = '#060';
            })
            .catch(function () {
                status.textContent = 'Não foi possível consultar o CEP - preencha manualmente';
                status.style.color = '#a00';
            });
    });
}

function ligarBloco(bloco) {
    configurarBuscaCep(bloco);
    bloco.querySelector('.btn-remover-participante').addEventListener('click', function () {
        if (document.querySelectorAll('.bloco-participante').length === 1) {
            alert('A solicitação precisa ter pelo menos um participante.');
            return;
        }
        bloco.remove();
        renumerarParticipantes();
    });
}

function criarBlocoParticipante() {
    try {
        var template = document.getElementById('template-participante');
        if (!template) {
            console.error('SIGAD: template-participante não encontrado na página.');
            return;
        }
        var clone = template.content.cloneNode(true);
        var bloco = clone.querySelector('.bloco-participante');
        ligarBloco(bloco);
        document.getElementById('participantes-container').appendChild(clone);
        renumerarParticipantes();
    } catch (erro) {
        console.error('SIGAD: falha ao criar bloco de participante -', erro);
        alert('Não foi possível adicionar o participante. Atualize a página (Ctrl+Shift+R) e tente de novo. Se persistir, avise o suporte.');
    }
}
window.criarBlocoParticipante = criarBlocoParticipante;

// todos os blocos já vêm prontos no HTML, na quantidade escolhida no
// seletor "Quantas pessoas serão seguradas?" - não dependem de nenhum
// clique em "Adicionar" para existir. Aqui só ligamos CEP e remover de
// CADA bloco já renderizado.
document.querySelectorAll('.bloco-participante').forEach(ligarBloco);

document.getElementById('btn-adicionar-participante').addEventListener('click', criarBlocoParticipante);

document.getElementById('btn-atualizar-qtd').addEventListener('click', function () {
    var qtd = document.getElementById('seletor_qtd_participantes').value;
    var params = new URLSearchParams(window.location.search);
    params.set('qtd_participantes', qtd);
    window.location.search = params.toString();
});

document.getElementById('form-seguro').addEventListener('submit', function (evento) {
    if (document.querySelectorAll('.bloco-participante').length === 0) {
        evento.preventDefault();
        alert('Adicione pelo menos um participante à lista de seguro de vida.');
    }
});

verificarKm();
</script>
"""


def montar_formulario_seguro():
    campo_convenio = ''
    if pode_definir_convenio():
        campo_convenio = f"""
    <label>Convênio do projeto:</label><br>
    <select name="convenio" style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        {montar_opcoes(CONVENIOS)}
    </select><br>
"""

    # a quantidade de blocos de participante é decidida ANTES de carregar a
    # página (pelo seletor "Quantas pessoas serão seguradas?"), e todos já
    # vêm prontos no HTML - não depende de nenhum clique em "Adicionar" para
    # existirem
    try:
        qtd_participantes = int(request.args.get('qtd_participantes', 1))
    except (TypeError, ValueError):
        qtd_participantes = 1
    qtd_participantes = max(1, min(qtd_participantes, 20))

    opcoes_estados = montar_opcoes_estados()

    blocos_html = '\n'.join(
        PARTICIPANTE_SEGURO_BLOCO.replace('__INDICE__', str(i)).replace('__OPCOES_ESTADOS__', opcoes_estados)
        for i in range(1, qtd_participantes + 1)
    )
    opcoes_qtd = ''.join(
        f'<option value="{n}" {"selected" if n == qtd_participantes else ""}>{n}</option>'
        for n in range(1, 21)
    )
    # o <template> usado pelo botão "+ Adicionar participante" (bônus, além
    # dos blocos já renderizados) usa índice 0 - a numeração de exibição é
    # sempre recalculada por renumerarParticipantes()
    template_vazio = PARTICIPANTE_SEGURO_BLOCO.replace('__INDICE__', '').replace('__OPCOES_ESTADOS__', opcoes_estados)

    html = SEGURO_FORM_TEMPLATE.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    html = html.replace('__CAMPO_CONVENIO_SEGURO__', campo_convenio)
    html = html.replace('__BLOCOS_PARTICIPANTES__', blocos_html)
    html = html.replace('__OPCOES_QTD_PARTICIPANTES__', opcoes_qtd)
    html = html.replace('__TEMPLATE_PARTICIPANTE_VAZIO__', template_vazio)
    html = html.replace('__KM_MINIMO__', str(KM_MINIMO_SEGURO))
    return html


@app.route('/solicitacao/seguro', methods=['GET', 'POST'])
@login_required
def seguro_form():
    resultado_bloqueio = bloquear_se_travado()
    if resultado_bloqueio:
        return resultado_bloqueio

    if request.method == 'POST':
        nomes = request.form.getlist('part_nome[]')
        nascimentos = request.form.getlist('part_nascimento[]')
        cpfs = request.form.getlist('part_cpf[]')
        rgs = request.form.getlist('part_rg[]')
        emails = request.form.getlist('part_email[]')
        documentos = request.files.getlist('doc_participante[]')
        logradouros = request.form.getlist('part_logradouro[]')
        numeros = request.form.getlist('part_numero[]')
        bairros = request.form.getlist('part_bairro[]')
        cidades = request.form.getlist('part_cidade[]')
        ufs = request.form.getlist('part_uf[]')
        ceps = request.form.getlist('part_cep[]')
        ddds = request.form.getlist('part_ddd[]')
        telefones = request.form.getlist('part_telefone[]')

        def pegar(lista, i):
            return lista[i] if i < len(lista) else ''

        participantes = []
        for i in range(len(nomes)):
            nome = (nomes[i] or '').strip()
            if not nome:
                continue

            cpf_participante = pegar(cpfs, i)
            if not cpf_tem_11_digitos(cpf_participante):
                flash(f'CPF inválido para o participante "{nome}". '
                      f'Informe 11 dígitos, no formato 000.000.000-00.')
                return render_pagina('Solicitação de Seguro',
                                     preservar_preenchimento(montar_formulario_seguro(), request.form))

            rg_participante = pegar(rgs, i).strip()
            if not rg_participante:
                flash(f'Informe o RG do participante "{nome}".')
                return render_pagina('Solicitação de Seguro',
                                     preservar_preenchimento(montar_formulario_seguro(), request.form))

            telefone_ok, telefone_participante = montar_telefone(pegar(ddds, i), pegar(telefones, i))
            if not telefone_ok:
                flash(f'Telefone inválido para o participante "{nome}". '
                      f'Informe DDD com 2 dígitos e número com 8 ou 9 dígitos.')
                return render_pagina('Solicitação de Seguro',
                                     preservar_preenchimento(montar_formulario_seguro(), request.form))

            participantes.append({
                'nome_completo': nome,
                'data_nascimento': pegar(nascimentos, i) or None,
                'cpf': formatar_cpf(cpf_participante),
                'rg': rg_participante,
                'email': pegar(emails, i),
                'documento': documentos[i] if i < len(documentos) else None,
                'logradouro': pegar(logradouros, i),
                'numero': pegar(numeros, i),
                'bairro': pegar(bairros, i),
                'cidade': pegar(cidades, i),
                'uf': pegar(ufs, i),
                'cep': pegar(ceps, i),
                'ddd': pegar(ddds, i),
                'telefone': telefone_participante,
            })

        if not participantes:
            flash('Adicione pelo menos um participante à lista de seguro de vida.')
            return render_pagina('Solicitação de Seguro',
                                 preservar_preenchimento(montar_formulario_seguro(), request.form))

        solicitacao, era_correcao = obter_solicitacao_para_gravar(
            'seguro',
            atividade_id=request.form.get('atividade_id') or None,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=0,
            convenio=request.form.get('convenio') if pode_definir_convenio() else None,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
            observacao=request.form.get('observacao'),
        )
        if era_correcao:
            SolicitacaoSeguro.query.filter_by(solicitacao_id=solicitacao.id).delete()
            ParticipanteSeguro.query.filter_by(solicitacao_id=solicitacao.id).delete()

        seguro = SolicitacaoSeguro(
            solicitacao_id=solicitacao.id,
            quantidade_pessoas=len(participantes),
            data_saida=request.form.get('data_saida'),
            data_retorno=request.form.get('data_retorno'),
            local_origem=request.form.get('local_origem'),
            percurso=request.form.get('percurso'),
            local_retorno=request.form.get('local_retorno'),
            tipo_transporte=request.form.get('tipo_transporte'),
            km_estimado=float(request.form.get('km_estimado') or 0),
            observacao=request.form.get('observacao'),
        )
        db.session.add(seguro)

        for dados in participantes:
            db.session.add(ParticipanteSeguro(
                solicitacao_id=solicitacao.id,
                nome_completo=dados['nome_completo'],
                data_nascimento=dados['data_nascimento'],
                cpf=dados['cpf'],
                rg=dados['rg'],
                email=dados['email'],
                logradouro=dados['logradouro'],
                numero=dados['numero'],
                bairro=dados['bairro'],
                cidade=dados['cidade'],
                uf=dados['uf'],
                cep=dados['cep'],
                ddd=dados['ddd'],
                telefone=dados['telefone'],
            ))

            documento = dados.get('documento')
            if documento and documento.filename:
                documento.filename = f"{dados['nome_completo']} - {documento.filename}"
                salvar_anexo(solicitacao.id, documento, 'documento_pessoal')

        db.session.commit()
        if era_correcao:
            flash(f'Solicitação corrigida e reenviada, protocolo {protocolo(solicitacao)}!', 'sucesso')
        else:
            flash('Solicitação de seguro enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    solicitacao_corrigindo = carregar_solicitacao_para_correcao(request.args.get('corrigir_id'))
    if solicitacao_corrigindo:
        dados_edicao = _dados_edicao_seguro(solicitacao_corrigindo)
        if dados_edicao:
            return render_pagina('Solicitação de Seguro',
                                 preservar_preenchimento(montar_formulario_seguro(), dados_edicao))

    return render_pagina('Solicitação de Seguro', com_vinculo_atividade(montar_formulario_seguro()))



BOLSISTA_BLOCO = """
    <div class="bloco-bolsista bloco" style="margin-bottom:15px;">
        <strong>Bolsista <span class="numero-bolsista">__INDICE__</span></strong>
        <button type="button" class="btn btn-excluir btn-remover-bolsista" style="float:right; padding:4px 10px;">Remover</button>
        <div style="clear:both;"></div>

        <label>Nome do bolsista: <span style="color:red;">*</span></label><br>
        <input type="text" name="bolsa_nome[]" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>Título do plano de trabalho: <span style="color:red;">*</span></label><br>
        <input type="text" name="bolsa_titulo[]" required style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>Projeto relacionado:</label><br>
        <input type="text" name="bolsa_projeto[]" style="width:100%; padding:6px; margin-bottom:10px;"><br>

        <label>Tipo de bolsa: <span style="color:red;">*</span></label><br>
        <select name="bolsa_tipo[]" class="campo-tipo-bolsa" required style="padding:6px; margin-bottom:10px;">
            <option value="">Selecione</option>
            <option value="Iniciação Científica">Iniciação Científica</option>
            <option value="Mestrado">Mestrado</option>
            <option value="Doutorado">Doutorado</option>
            <option value="Pós-Doutorado">Pós-Doutorado</option>
            <option value="Apoio Técnico">Apoio Técnico</option>
            <option value="Extensão">Extensão</option>
        </select><br>

        <label>Mês de início: <span style="color:red;">*</span></label><br>
        <input type="month" name="bolsa_mes_inicio[]" class="campo-mes-inicio" required style="padding:6px; margin-bottom:10px;"><br>

        <label>Mês de fim: <span style="color:red;">*</span></label><br>
        <input type="month" name="bolsa_mes_fim[]" class="campo-mes-fim" required style="padding:6px; margin-bottom:6px;"><br>
        <div style="font-size:11px; color:#888; margin-bottom:10px;">
            Duração: <strong class="texto-duracao">0</strong> mês(es) - calculado automaticamente
        </div>
        <input type="hidden" name="bolsa_duracao[]" class="campo-duracao-hidden" value="0">

        <label>Valor mensal da bolsa (R$): <span style="color:red;">*</span></label><br>
        <input type="number" step="0.01" min="0" name="bolsa_valor_mensal[]" class="campo-valor-mensal" required style="padding:6px; margin-bottom:6px; width:160px;"><br>
        <div style="font-size:11px; color:#888; margin-bottom:10px;">
            Valor total da bolsa: <strong class="texto-valor-total">R$ 0,00</strong> (mensal × duração)
        </div>

        <label>Precisa de crachá de acesso? <span style="color:red;">*</span></label><br>
        <select name="bolsa_cracha[]" required style="padding:6px; margin-bottom:10px;">
            <option value="Não">Não</option>
            <option value="Sim">Sim</option>
        </select><br>
    </div>
"""


BOLSA_FORM_TEMPLATE = """
<form method="POST" enctype="multipart/form-data" style="max-width: 750px;" id="form-bolsa">
    <input type="hidden" name="corrigir_id" value="">
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

    __CAMPOS_ANALISTA__

    <label>Observação (se houver):</label><br>
    <textarea name="observacao" style="width:100%; padding:6px; margin-bottom:10px;" rows="3"></textarea><br>

    <label>Anexar plano(s) de trabalho (PDF):</label><br>
    <input type="file" name="anexos_plano" accept=".pdf" multiple style="margin-bottom:15px;"><br>

    <h3>Lista de bolsistas</h3>
    <div style="font-size:11px; color:#888; margin-bottom:10px;">
        Todos os campos de cada bolsista são obrigatórios, exceto o projeto relacionado.
    </div>

    <div class="bloco" style="border-left:4px solid #37784D; max-width:400px; margin-bottom:16px;">
        <label>Quantos bolsistas nesta solicitação?</label><br>
        <div style="display:flex; gap:8px; align-items:center; margin-top:6px;">
            <select id="seletor_qtd_bolsistas" style="padding:7px; width:100px;">
                __OPCOES_QTD_BOLSISTAS__
            </select>
            <button type="button" id="btn-atualizar-qtd-bolsa" class="btn-atalho">Atualizar blocos</button>
        </div>
        <div style="font-size:11px; color:#888; margin-top:6px;">
            Escolha a quantidade e clique em "Atualizar blocos" - a página já mostra todos os
            campos prontos para preencher.
        </div>
    </div>

    <div id="bolsistas-container">
__BLOCOS_BOLSISTAS__
    </div>

    <button type="button" id="btn-adicionar-bolsista" class="btn-atalho" style="margin-top:10px;">+ Adicionar bolsista</button>

    <br><br>
    <button type="submit" style="padding:10px 20px; background:#2b5876; color:white; border:none; border-radius:4px; cursor:pointer;">Enviar solicitação</button>
</form>

<template id="template-bolsista">
__TEMPLATE_BOLSISTA_VAZIO__
</template>

<script>
function diasEntreMeses(mesInicioStr, mesFimStr) {
    // "2026-03" -> conta quantos meses existem entre inicio e fim, incluindo os dois
    if (!mesInicioStr || !mesFimStr) { return 0; }
    var [anoIni, mesIni] = mesInicioStr.split('-').map(Number);
    var [anoFim, mesFim] = mesFimStr.split('-').map(Number);
    var duracao = (anoFim - anoIni) * 12 + (mesFim - mesIni) + 1;
    return duracao > 0 ? duracao : 0;
}

function formatarMoeda(valor) {
    var partes = valor.toFixed(2).split('.');
    var inteiro = partes[0];
    var comSeparador = '';
    for (var i = 0; i < inteiro.length; i++) {
        var posicaoDaDireita = inteiro.length - i;
        comSeparador += inteiro[i];
        if (posicaoDaDireita > 1 && (posicaoDaDireita - 1) % 3 === 0) { comSeparador += '.'; }
    }
    return 'R$ ' + comSeparador + ',' + partes[1];
}

function recalcularBolsista(bloco) {
    var duracao = diasEntreMeses(
        bloco.querySelector('.campo-mes-inicio').value,
        bloco.querySelector('.campo-mes-fim').value
    );
    var valorMensal = parseFloat(bloco.querySelector('.campo-valor-mensal').value) || 0;

    bloco.querySelector('.campo-duracao-hidden').value = duracao;
    bloco.querySelector('.texto-duracao').textContent = duracao;
    bloco.querySelector('.texto-valor-total').textContent = formatarMoeda(duracao * valorMensal);
}

function recalcularTodosBolsistas() {
    document.querySelectorAll('.bloco-bolsista').forEach(function (bloco) {
        recalcularBolsista(bloco);
    });
}
window.recalcularTodosBolsistas = recalcularTodosBolsistas;

function ligarBlocoBolsista(bloco) {
    bloco.querySelector('.campo-mes-inicio').addEventListener('change', function () { recalcularBolsista(bloco); });
    bloco.querySelector('.campo-mes-fim').addEventListener('change', function () { recalcularBolsista(bloco); });
    bloco.querySelector('.campo-valor-mensal').addEventListener('input', function () { recalcularBolsista(bloco); });

    bloco.querySelector('.btn-remover-bolsista').addEventListener('click', function () {
        if (document.querySelectorAll('.bloco-bolsista').length === 1) {
            alert('A solicitação precisa ter pelo menos um bolsista.');
            return;
        }
        bloco.remove();
        renumerarBolsistas();
    });
}

function renumerarBolsistas() {
    document.querySelectorAll('.bloco-bolsista').forEach(function (bloco, indice) {
        bloco.querySelector('.numero-bolsista').textContent = indice + 1;
    });
}

function criarBlocoBolsista() {
    try {
        var template = document.getElementById('template-bolsista');
        if (!template) {
            console.error('SIGAD: template-bolsista não encontrado na página.');
            return;
        }
        var clone = template.content.cloneNode(true);
        var bloco = clone.querySelector('.bloco-bolsista');
        ligarBlocoBolsista(bloco);
        document.getElementById('bolsistas-container').appendChild(clone);
        renumerarBolsistas();
    } catch (erro) {
        console.error('SIGAD: falha ao criar bloco de bolsista -', erro);
        alert('Não foi possível adicionar o bolsista. Atualize a página (Ctrl+Shift+R) e tente de novo.');
    }
}
window.criarBlocoBolsista = criarBlocoBolsista;

document.querySelectorAll('.bloco-bolsista').forEach(function (bloco) {
    ligarBlocoBolsista(bloco);
    recalcularBolsista(bloco);
});

document.getElementById('btn-adicionar-bolsista').addEventListener('click', criarBlocoBolsista);

document.getElementById('btn-atualizar-qtd-bolsa').addEventListener('click', function () {
    var qtd = document.getElementById('seletor_qtd_bolsistas').value;
    var params = new URLSearchParams(window.location.search);
    params.set('qtd_bolsistas', qtd);
    window.location.search = params.toString();
});

document.getElementById('form-bolsa').addEventListener('submit', function (evento) {
    if (document.querySelectorAll('.bloco-bolsista').length === 0) {
        evento.preventDefault();
        alert('Adicione pelo menos um bolsista à solicitação.');
    }
});
</script>
"""


def montar_formulario_bolsa():
    campos_analista = ''
    if pode_definir_convenio():
        campos_analista = f"""
    <h3>Dados de aprovação</h3>
    <div style="font-size:11px; color:#888; margin-bottom:10px;">
        Campos visíveis apenas para os perfis de Analista, Aprovador e Administrador.
    </div>

    <label>Nº Lote de Aprovação:</label><br>
    <input type="text" name="lote_aprovacao" style="padding:6px; margin-bottom:10px; width:250px;"><br>

    <label>Convênio:</label><br>
    <select name="convenio" style="padding:6px; margin-bottom:10px;">
        <option value="">Selecione</option>
        {montar_opcoes(CONVENIOS)}
    </select><br>

    <label>Rubrica:</label><br>
    <input type="text" name="rubrica" style="padding:6px; margin-bottom:10px; width:100%;"><br>
"""

    try:
        qtd_bolsistas = int(request.args.get('qtd_bolsistas', 1))
    except (TypeError, ValueError):
        qtd_bolsistas = 1
    qtd_bolsistas = max(1, min(qtd_bolsistas, 20))

    blocos_html = '\n'.join(
        BOLSISTA_BLOCO.replace('__INDICE__', str(i))
        for i in range(1, qtd_bolsistas + 1)
    )
    opcoes_qtd = ''.join(
        f'<option value="{n}" {"selected" if n == qtd_bolsistas else ""}>{n}</option>'
        for n in range(1, 21)
    )
    template_vazio = BOLSISTA_BLOCO.replace('__INDICE__', '')

    html = BOLSA_FORM_TEMPLATE.replace('__OPCOES_COORDENACAO__', montar_opcoes_coordenacoes())
    html = html.replace('__CAMPOS_ANALISTA__', campos_analista)
    html = html.replace('__BLOCOS_BOLSISTAS__', blocos_html)
    html = html.replace('__OPCOES_QTD_BOLSISTAS__', opcoes_qtd)
    html = html.replace('__TEMPLATE_BOLSISTA_VAZIO__', template_vazio)
    return html


@app.route('/solicitacao/bolsa', methods=['GET', 'POST'])
@login_required
def bolsa_form():
    resultado_bloqueio = bloquear_se_travado()
    if resultado_bloqueio:
        return resultado_bloqueio

    if request.method == 'POST':
        nomes = request.form.getlist('bolsa_nome[]')
        titulos = request.form.getlist('bolsa_titulo[]')
        projetos = request.form.getlist('bolsa_projeto[]')
        tipos = request.form.getlist('bolsa_tipo[]')
        meses_inicio = request.form.getlist('bolsa_mes_inicio[]')
        meses_fim = request.form.getlist('bolsa_mes_fim[]')
        duracoes = request.form.getlist('bolsa_duracao[]')
        valores_mensais = request.form.getlist('bolsa_valor_mensal[]')
        crachas = request.form.getlist('bolsa_cracha[]')

        bolsistas = []
        valor_total_solicitacao = 0

        for i in range(len(nomes)):
            nome = (nomes[i] or '').strip()
            if not nome:
                continue

            duracao = int(duracoes[i] or 0) if i < len(duracoes) else 0
            valor_mensal = float(valores_mensais[i] or 0) if i < len(valores_mensais) else 0

            if duracao < 1:
                flash(f'Período inválido para o bolsista "{nome}". O mês de fim deve ser igual ou posterior ao de início.')
                return render_pagina('Solicitação de Bolsa',
                                     preservar_preenchimento(montar_formulario_bolsa(), request.form))

            valor_total_bolsa = duracao * valor_mensal
            valor_total_solicitacao += valor_total_bolsa

            bolsistas.append({
                'nome_bolsista': nome,
                'titulo_plano_trabalho': titulos[i] if i < len(titulos) else '',
                'projeto_relacionado': projetos[i] if i < len(projetos) else '',
                'tipo_bolsa': tipos[i] if i < len(tipos) else '',
                'mes_inicio': meses_inicio[i] if i < len(meses_inicio) else '',
                'mes_fim': meses_fim[i] if i < len(meses_fim) else '',
                'duracao_meses': duracao,
                'valor_mensal': valor_mensal,
                'valor_total_bolsa': valor_total_bolsa,
                'precisa_cracha': (crachas[i] == 'Sim') if i < len(crachas) else False,
            })

        if not bolsistas:
            flash('Adicione pelo menos um bolsista à solicitação.')
            return render_pagina('Solicitação de Bolsa',
                                 preservar_preenchimento(montar_formulario_bolsa(), request.form))

        campos_extras = {}
        if pode_definir_convenio():
            campos_extras['convenio'] = request.form.get('convenio')
            campos_extras['lote_aprovacao'] = request.form.get('lote_aprovacao')
            campos_extras['rubrica'] = request.form.get('rubrica')

        solicitacao, era_correcao = obter_solicitacao_para_gravar(
            'bolsa',
            atividade_id=request.form.get('atividade_id') or None,
            ponto_focal=request.form.get('ponto_focal'),
            atividade_projeto=request.form.get('atividade_projeto'),
            valor_total=valor_total_solicitacao,
            coordenacao_solicitante_id=request.form.get('coordenacao_solicitante') or None,
            contato_solicitante=request.form.get('contato_solicitante'),
            observacao=request.form.get('observacao'),
            **campos_extras,
        )
        if era_correcao:
            BolsistaSolicitacao.query.filter_by(solicitacao_id=solicitacao.id).delete()

        for dados in bolsistas:
            db.session.add(BolsistaSolicitacao(solicitacao_id=solicitacao.id, **dados))

        for arquivo in request.files.getlist('anexos_plano'):
            if arquivo and arquivo.filename:
                salvar_anexo(solicitacao.id, arquivo, 'plano_trabalho')

        db.session.commit()
        if era_correcao:
            flash(f'Solicitação corrigida e reenviada, protocolo {protocolo(solicitacao)}!', 'sucesso')
        else:
            flash('Solicitação de bolsa enviada com sucesso!', 'sucesso')
        return redirect(url_for('inicio'))

    solicitacao_corrigindo = carregar_solicitacao_para_correcao(request.args.get('corrigir_id'))
    if solicitacao_corrigindo:
        dados_edicao = _dados_edicao_bolsa(solicitacao_corrigindo)
        if dados_edicao:
            return render_pagina('Solicitação de Bolsa',
                                 preservar_preenchimento(montar_formulario_bolsa(), dados_edicao))

    return render_pagina('Solicitação de Bolsa', com_vinculo_atividade(montar_formulario_bolsa()))


# ---------------- CORREÇÃO E REENVIO (SOLICITAÇÃO DEVOLVIDA) ----------------
# Cada tipo declara os campos editáveis: (atributo, rótulo, tipo, obrigatório)
# tipos: texto, area, data, hora, numero, dinheiro, uf, area_diaria, tipo_diaria,
#        transporte, tipo_alimentacao, tipo_veiculo, sim_nao
ROTA_CRIACAO_POR_TIPO = {
    'diaria': 'diaria_form',
    'passagem': 'passagem_form',
    'compra_materiais': 'compra_materiais_form',
    'rancho': 'rancho_form',
    'servico_externo_pf': 'servico_externo_pf_form',
    'servico_externo_pj': 'servico_externo_pj_form',
    'bolsa': 'bolsa_form',
    'seguro': 'seguro_form',
}


def _dados_edicao_diaria(solicitacao):
    diarias_lista = SolicitacaoDiaria.query.filter_by(solicitacao_id=solicitacao.id).all()
    if not diarias_lista:
        return None
    d = diarias_lista[0]

    pares = [
        ('ponto_focal', solicitacao.ponto_focal or ''),
        ('atividade_projeto', solicitacao.atividade_projeto or ''),
        ('coordenacao_solicitante', str(solicitacao.coordenacao_solicitante_id or '')),
        ('contato_solicitante', solicitacao.contato_solicitante or ''),
        ('data_ida', d.data_ida.isoformat() if d.data_ida else ''),
        ('data_retorno', d.data_retorno.isoformat() if d.data_retorno else ''),
        ('cidade_origem', d.cidade_origem or ''),
        ('estado_origem', d.estado_origem or ''),
        ('cidade_destino', d.cidade_destino or ''),
        ('estado_destino', d.estado_destino or ''),
        ('tipo_destino', d.tipo_destino or ''),
        ('numero_pernoites', str(d.numero_pernoites or 0)),
        ('tipo_diaria', d.tipo_diaria or ''),
        ('tera_auxilio', 'sim' if d.tera_auxilio_deslocamento else 'nao'),
        # o campo tem min="1" no HTML - mesmo escondido quando o auxílio
        # não é usado, um valor "0" deixaria o formulário inteiro inválido
        # para o navegador (checkValidity), bloqueando o envio silenciosamente
        ('quantidade_auxilio', str(d.quantidade_auxilio) if d.quantidade_auxilio else '1'),
        ('justificativa_auxilio', d.justificativa_auxilio or ''),
        ('justificativa', d.justificativa or ''),
        ('corrigir_id', str(solicitacao.id)),
    ]
    if d.diaria_detalhada:
        pares.append(('diaria_detalhada', 'sim'))
        pares.append(('periodo_cheia_inicio', d.periodo_cheia_inicio.isoformat() if d.periodo_cheia_inicio else ''))
        pares.append(('periodo_cheia_fim', d.periodo_cheia_fim.isoformat() if d.periodo_cheia_fim else ''))
        pares.append(('periodo_meia_inicio', d.periodo_meia_inicio.isoformat() if d.periodo_meia_inicio else ''))
        pares.append(('periodo_meia_fim', d.periodo_meia_fim.isoformat() if d.periodo_meia_fim else ''))

    for diarista in diarias_lista:
        ddd, numero = separar_telefone(diarista.telefone_diarista)
        pares.append(('nome_diarista[]', diarista.nome_diarista or ''))
        pares.append(('cpf_diarista[]', diarista.cpf_diarista or ''))
        pares.append(('ddd_diarista[]', ddd))
        pares.append(('telefone_diarista[]', numero))
        pares.append(('email_diarista[]', diarista.email_diarista or ''))
        pares.append(('banco_diarista[]', diarista.banco_diarista or ''))
        pares.append(('agencia_diarista[]', diarista.agencia_diarista or ''))
        pares.append(('conta_diarista[]', diarista.conta_diarista or ''))
        pares.append(('chave_pix[]', diarista.chave_pix or ''))

    return MultiDict(pares)


def _dados_edicao_seguro(solicitacao):
    seguro = SolicitacaoSeguro.query.filter_by(solicitacao_id=solicitacao.id).first()
    participantes = ParticipanteSeguro.query.filter_by(solicitacao_id=solicitacao.id).all()
    if not seguro or not participantes:
        return None

    pares = [
        ('ponto_focal', solicitacao.ponto_focal or ''),
        ('atividade_projeto', solicitacao.atividade_projeto or ''),
        ('coordenacao_solicitante', str(solicitacao.coordenacao_solicitante_id or '')),
        ('contato_solicitante', solicitacao.contato_solicitante or ''),
        ('convenio', solicitacao.convenio or ''),
        ('data_saida', seguro.data_saida.isoformat() if seguro.data_saida else ''),
        ('data_retorno', seguro.data_retorno.isoformat() if seguro.data_retorno else ''),
        ('local_origem', seguro.local_origem or ''),
        ('percurso', seguro.percurso or ''),
        ('local_retorno', seguro.local_retorno or ''),
        ('tipo_transporte', seguro.tipo_transporte or ''),
        ('km_estimado', str(seguro.km_estimado or 0)),
        ('observacao', seguro.observacao or ''),
        ('corrigir_id', str(solicitacao.id)),
        ('qtd_participantes', str(len(participantes))),
    ]

    for p in participantes:
        ddd, numero = separar_telefone(p.telefone)
        pares.append(('part_nome[]', p.nome_completo or ''))
        pares.append(('part_nascimento[]', p.data_nascimento.isoformat() if p.data_nascimento else ''))
        pares.append(('part_cpf[]', p.cpf or ''))
        pares.append(('part_rg[]', p.rg or ''))
        pares.append(('part_email[]', p.email or ''))
        pares.append(('part_cep[]', p.cep or ''))
        pares.append(('part_logradouro[]', p.logradouro or ''))
        pares.append(('part_numero[]', p.numero or ''))
        pares.append(('part_bairro[]', p.bairro or ''))
        pares.append(('part_cidade[]', p.cidade or ''))
        pares.append(('part_uf[]', p.uf or ''))
        pares.append(('part_ddd[]', ddd))
        pares.append(('part_telefone[]', numero))

    return MultiDict(pares)


def _dados_edicao_bolsa(solicitacao):
    bolsistas = BolsistaSolicitacao.query.filter_by(solicitacao_id=solicitacao.id).all()
    if not bolsistas:
        return None

    pares = [
        ('ponto_focal', solicitacao.ponto_focal or ''),
        ('atividade_projeto', solicitacao.atividade_projeto or ''),
        ('coordenacao_solicitante', str(solicitacao.coordenacao_solicitante_id or '')),
        ('contato_solicitante', solicitacao.contato_solicitante or ''),
        ('convenio', solicitacao.convenio or ''),
        ('lote_aprovacao', solicitacao.lote_aprovacao or ''),
        ('rubrica', solicitacao.rubrica or ''),
        ('observacao', solicitacao.observacao or ''),
        ('corrigir_id', str(solicitacao.id)),
        ('qtd_bolsistas', str(len(bolsistas))),
    ]

    for b in bolsistas:
        pares.append(('bolsa_nome[]', b.nome_bolsista or ''))
        pares.append(('bolsa_titulo[]', b.titulo_plano_trabalho or ''))
        pares.append(('bolsa_projeto[]', b.projeto_relacionado or ''))
        pares.append(('bolsa_tipo[]', b.tipo_bolsa or ''))
        pares.append(('bolsa_mes_inicio[]', b.mes_inicio or ''))
        pares.append(('bolsa_mes_fim[]', b.mes_fim or ''))
        pares.append(('bolsa_duracao[]', str(b.duracao_meses or 0)))
        pares.append(('bolsa_valor_mensal[]', str(b.valor_mensal or 0)))
        pares.append(('bolsa_cracha[]', 'Sim' if b.precisa_cracha else 'Não'))

    return MultiDict(pares)


def _dados_edicao_passagem(solicitacao):
    passageiros = SolicitacaoPassagem.query.filter_by(solicitacao_id=solicitacao.id).all()
    if not passageiros:
        return None
    v = passageiros[0]

    def dt_local(valor):
        return valor.strftime('%Y-%m-%dT%H:%M') if valor else ''

    pares = [
        ('ponto_focal', solicitacao.ponto_focal or ''),
        ('atividade_projeto', solicitacao.atividade_projeto or ''),
        ('coordenacao_solicitante', str(solicitacao.coordenacao_solicitante_id or '')),
        ('contato_solicitante', solicitacao.contato_solicitante or ''),
        ('convenio', solicitacao.convenio or ''),
        ('tipo_transporte', v.tipo_transporte or ''),
        ('cidade_origem', v.cidade_origem or ''),
        ('estado_origem', v.estado_origem or ''),
        ('cidade_destino', v.cidade_destino or ''),
        ('estado_destino', v.estado_destino or ''),
        ('data_ida', v.data_ida.isoformat() if v.data_ida else ''),
        ('data_volta', v.data_volta.isoformat() if v.data_volta else ''),
        ('com_bagagem', 'sim' if v.com_bagagem else 'nao'),
        ('justificativa', v.justificativa or ''),
        ('corrigir_id', str(solicitacao.id)),
    ]

    for p in passageiros:
        ddd, numero = separar_telefone(p.telefone_passageiro)
        pares.append(('nome_passageiro[]', p.nome_passageiro or ''))
        pares.append(('cpf_passageiro[]', p.cpf_passageiro or ''))
        pares.append(('rg_passageiro[]', p.rg_orgao_uf_passageiro or ''))
        pares.append(('nascimento_passageiro[]', p.data_nascimento_passageiro.isoformat() if p.data_nascimento_passageiro else ''))
        pares.append(('ddd_passageiro[]', ddd))
        pares.append(('telefone_passageiro[]', numero))
        pares.append(('email_passageiro[]', p.email_passageiro or ''))
        pares.append(('valor_estimado[]', str(p.valor_estimado or 0)))
        pares.append(('menor_tarifa[]', str(p.menor_tarifa_encontrada or 0)))
        pares.append(('justificativa_tarifa[]', p.justificativa_tarifa or ''))
        pares.append(('observacao_voo[]', p.observacao_voo or ''))
        pares.append(('voo_ida_companhia[]', p.voo_ida_companhia or ''))
        pares.append(('voo_ida_numero[]', p.voo_ida_numero or ''))
        pares.append(('voo_ida_saida[]', dt_local(p.voo_ida_saida)))
        pares.append(('voo_ida_chegada[]', dt_local(p.voo_ida_chegada)))
        pares.append(('voo_volta_companhia[]', p.voo_volta_companhia or ''))
        pares.append(('voo_volta_numero[]', p.voo_volta_numero or ''))
        pares.append(('voo_volta_saida[]', dt_local(p.voo_volta_saida)))
        pares.append(('voo_volta_chegada[]', dt_local(p.voo_volta_chegada)))

    return MultiDict(pares)


def _dados_edicao_compra(solicitacao):
    itens = SolicitacaoCompraMateriais.query.filter_by(solicitacao_id=solicitacao.id).all()
    if not itens:
        return None

    pares = [
        ('ponto_focal', solicitacao.ponto_focal or ''),
        ('atividade_projeto', solicitacao.atividade_projeto or ''),
        ('coordenacao_solicitante', str(solicitacao.coordenacao_solicitante_id or '')),
        ('contato_solicitante', solicitacao.contato_solicitante or ''),
        ('data_entrega_material', itens[0].data_entrega_material.isoformat() if itens[0].data_entrega_material else ''),
        ('corrigir_id', str(solicitacao.id)),
    ]

    for item in itens:
        pares.append(('item_especificacao[]', item.nome_especificacao or ''))
        pares.append(('item_fornecedor[]', item.fornecedor_sugerido or ''))
        pares.append(('item_forma[]', item.forma_aquisicao or ''))
        pares.append(('item_link[]', item.link_produto or ''))
        pares.append(('item_quantidade[]', str(item.quantidade or 0)))
        pares.append(('item_valor_unitario[]', str(item.valor_unitario or 0)))
        pares.append(('item_justificativa[]', item.justificativa or ''))

    return MultiDict(pares)


def _dados_edicao_rancho(solicitacao):
    rancho = SolicitacaoRancho.query.filter_by(solicitacao_id=solicitacao.id).first()
    itens_solicitacao = ItemSolicitacaoRancho.query.filter_by(solicitacao_id=solicitacao.id).all()
    if not rancho:
        return None

    # reencontra a quantidade de cada item do catálogo pelo nome - a ordem
    # de exibição no formulário é sempre a mesma (ordem, nome), então
    # varremos o catálogo nessa mesma ordem para casar item_id[]/item_qtd[]
    # corretamente com os inputs que o formulário realmente renderiza
    por_nome = {i.nome_item: i for i in itens_solicitacao if not i.item_adicional}
    catalogo = ItemRancho.query.order_by(ItemRancho.ordem, ItemRancho.nome).all()

    pares = [
        ('ponto_focal', solicitacao.ponto_focal or ''),
        ('atividade_projeto', solicitacao.atividade_projeto or ''),
        ('coordenacao_solicitante', str(solicitacao.coordenacao_solicitante_id or '')),
        ('contato_solicitante', solicitacao.contato_solicitante or ''),
        ('responsavel_retirada', rancho.responsavel_retirada or ''),
        ('periodo_atividade', rancho.periodo_atividade or ''),
        ('data_entrega', rancho.data_entrega.isoformat() if rancho.data_entrega else ''),
        ('local_entrega', rancho.local_entrega or ''),
        ('num_pessoas', str(rancho.num_pessoas or 0)),
        ('num_dias', str(rancho.num_dias or 0)),
        ('tipo_refeicao', rancho.tipo_refeicao or 'todas'),
        ('carne_bifes', str(rancho.carne_bifes or 0)),
        ('carne_picada', str(rancho.carne_picada or 0)),
        ('carne_osso', str(rancho.carne_osso or 0)),
        ('agua_mineral_20l', str(rancho.agua_mineral_20l or 0)),
        ('justificativa', rancho.justificativa or ''),
        ('justificativa_aumento', rancho.justificativa_aumento or ''),
        ('observacao', rancho.observacao or ''),
        ('corrigir_id', str(solicitacao.id)),
    ]

    for cat_item in catalogo:
        existente = por_nome.get(cat_item.nome)
        pares.append(('item_id[]', str(cat_item.id)))
        pares.append(('item_qtd[]', str(existente.quantidade if existente else 0)))
        pares.append(('item_qtd_calculada[]',
                      str(existente.quantidade_calculada) if existente and existente.quantidade_calculada is not None else '0'))

    for item in itens_solicitacao:
        if item.item_adicional:
            pares.append(('adicional_nome[]', item.nome_item or ''))
            pares.append(('adicional_qtd[]', str(item.quantidade or 0)))
            pares.append(('adicional_unidade[]', item.unidade or ''))

    return MultiDict(pares)


def _dados_edicao_servico_pf(solicitacao):
    prestadores = PrestadorServico.query.filter_by(solicitacao_id=solicitacao.id).all()
    if not prestadores:
        return None

    pares = [
        ('ponto_focal', solicitacao.ponto_focal or ''),
        ('atividade_projeto', solicitacao.atividade_projeto or ''),
        ('coordenacao_solicitante', str(solicitacao.coordenacao_solicitante_id or '')),
        ('contato_solicitante', solicitacao.contato_solicitante or ''),
        ('corrigir_id', str(solicitacao.id)),
    ]

    for p in prestadores:
        ddd, numero = separar_telefone(p.telefone_prestador)
        pares.append(('categoria_servico[]', p.categoria_servico or ''))
        pares.append(('nome_servico[]', p.nome_servico or ''))
        pares.append(('especificacao[]', p.especificacao or ''))
        pares.append(('justificativa[]', p.justificativa or ''))
        pares.append(('valor_diario[]', str(p.valor_diario or 0)))
        pares.append(('dias_atividade[]', str(p.dias_atividade or 0)))
        pares.append(('nome_prestador[]', p.nome_prestador or ''))
        pares.append(('cpf_prestador[]', p.cpf_prestador or ''))
        pares.append(('rg_prestador[]', p.rg_prestador or ''))
        pares.append(('ddd_prestador[]', ddd))
        pares.append(('telefone_prestador[]', numero))
        pares.append(('pis_nis[]', p.pis_nis or ''))
        pares.append(('endereco_prestador[]', p.endereco_prestador or ''))
        pares.append(('banco[]', p.banco or ''))
        pares.append(('agencia[]', p.agencia or ''))
        pares.append(('conta[]', p.conta or ''))
        pares.append(('chave_pix[]', p.chave_pix or ''))

    return MultiDict(pares)


def _dados_edicao_servico_pj(solicitacao):
    p = PrestadorServico.query.filter_by(solicitacao_id=solicitacao.id).first()
    if not p:
        return None

    ddd, numero = separar_telefone(p.telefone_prestador)
    pares = [
        ('ponto_focal', solicitacao.ponto_focal or ''),
        ('atividade_projeto', solicitacao.atividade_projeto or ''),
        ('coordenacao_solicitante', str(solicitacao.coordenacao_solicitante_id or '')),
        ('contato_solicitante', solicitacao.contato_solicitante or ''),
        ('nome_servico', p.nome_servico or ''),
        ('fornecedor_sugerido', p.fornecedor_sugerido or ''),
        ('especificacao', p.especificacao or ''),
        ('justificativa', p.justificativa or ''),
        ('valor_servico', str(p.valor_servico or 0)),
        ('nome_empresa', p.nome_empresa or ''),
        ('cnpj', p.cnpj or ''),
        ('ddd_prestador', ddd),
        ('telefone_prestador', numero),
        ('banco', p.banco or ''),
        ('agencia', p.agencia or ''),
        ('conta', p.conta or ''),
        ('chave_pix', p.chave_pix or ''),
        ('corrigir_id', str(solicitacao.id)),
    ]
    return MultiDict(pares)


def carregar_solicitacao_para_correcao(solicitacao_id):
    """Usado no início de cada rota de criação (GET) quando chega com
    ?corrigir_id=X: confere que a pessoa pode mesmo corrigir aquela
    solicitação (é dela, é da mesma coordenação, ou é Admin - e está
    devolvida) e devolve o objeto, ou None se não for um pedido de
    correção válido."""
    if not solicitacao_id:
        return None
    solicitacao = Solicitacao.query.get(solicitacao_id)
    if not solicitacao:
        return None
    eh_mesma_coordenacao = (
        current_user.coordenacao_id is not None
        and current_user.coordenacao_id == solicitacao.coordenacao_solicitante_id
    )
    if (solicitacao.solicitante_id != current_user.id
            and not current_user.is_organizador
            and not eh_mesma_coordenacao):
        return None
    if solicitacao.status not in ('devolvida_ajuste', 'ajuste_dados'):
        return None
    return solicitacao


def obter_solicitacao_para_gravar(tipo, **campos):
    """Usado no início da gravação de cada módulo, no lugar de sempre criar
    uma Solicitacao nova. Se a submissão veio de uma correção (campo oculto
    corrigir_id no formulário, apontando para uma solicitação devolvida),
    REAPROVEITA o mesmo registro - mesmo protocolo, sem gerar um número
    novo - só atualiza os campos e devolve o status para análise (ou para o
    responsável pelo encaminhamento, no caso de ajuste de dados).

    Devolve (solicitacao, era_correcao). Quando era_correcao é True, quem
    chamou ainda precisa apagar os registros filhos antigos (diaristas,
    itens, participantes...) antes de gravar os novos - isso é específico
    de cada módulo, então fica por conta de quem chamou."""
    corrigir_id = request.form.get('corrigir_id')

    if corrigir_id:
        solicitacao = Solicitacao.query.get(int(corrigir_id))
        eh_mesma_coordenacao = (
            solicitacao
            and current_user.coordenacao_id is not None
            and current_user.coordenacao_id == solicitacao.coordenacao_solicitante_id
        )
        pode_reaproveitar = (
            solicitacao
            and solicitacao.tipo == tipo
            and (solicitacao.solicitante_id == current_user.id
                 or current_user.is_organizador
                 or eh_mesma_coordenacao)
            and solicitacao.status in ('devolvida_ajuste', 'ajuste_dados')
        )
        if pode_reaproveitar:
            retorno_ao_executor = solicitacao.status == 'ajuste_dados'

            for atributo, valor in campos.items():
                setattr(solicitacao, atributo, valor)

            if retorno_ao_executor:
                solicitacao.status = solicitacao.status_antes_ajuste or 'aprovada'
                solicitacao.status_antes_ajuste = None
                solicitacao.motivo_ajuste_dados = None
            else:
                solicitacao.status = 'pendente_analise'
                solicitacao.motivo_devolucao = None

            registrar_auditoria('corrigiu', solicitacao,
                                'Solicitação corrigida e reenviada' +
                                (' ao responsável pelo encaminhamento' if retorno_ao_executor else ' para análise'))
            return solicitacao, True

    solicitacao = Solicitacao(tipo=tipo, solicitante_id=current_user.id, **campos)
    db.session.add(solicitacao)
    db.session.flush()
    return solicitacao, False


CAMPOS_EDICAO = {
    'alimentacao': (SolicitacaoAlimentacao, [
        ('tipo_alimentacao', 'Tipo de alimentação', 'tipo_alimentacao', True),
        ('quantidade_pessoas', 'Quantidade de pessoas', 'numero', True),
        ('forma_entrega', 'Entrega ou retirada', 'texto', True),
        ('local_entrega', 'Local de entrega', 'texto', False),
        ('data_entrega', 'Data de entrega/retirada', 'data', True),
        ('horario_entrega', 'Horário', 'hora', True),
        ('justificativa', 'Justificativa', 'area', True),
    ]),
    'locacao_veiculo': (SolicitacaoLocacaoVeiculo, [
        ('tipo_veiculo', 'Tipo de veículo', 'tipo_veiculo', True),
        ('especificacoes', 'Especificações', 'texto', False),
        ('local_origem', 'Local de origem', 'texto', True),
        ('percurso', 'Percurso / pontos de parada', 'area', True),
        ('local_retorno', 'Local de retorno', 'texto', True),
        ('km_estimado', 'KM estimado', 'numero', True),
        ('justificativa', 'Justificativa', 'area', True),
        ('observacao', 'Observação', 'area', False),
    ]),
    'seguro': (SolicitacaoSeguro, [
        ('data_saida', 'Data de saída', 'data', True),
        ('data_retorno', 'Data de retorno', 'data', True),
        ('local_origem', 'Local de origem', 'texto', True),
        ('percurso', 'Percurso / pontos de parada', 'area', True),
        ('local_retorno', 'Local de retorno', 'texto', True),
        ('tipo_transporte', 'Tipo de transporte', 'texto', True),
        ('observacao', 'Observação', 'area', False),
    ]),
    'rancho': (SolicitacaoRancho, [
        ('responsavel_retirada', 'Responsável pela retirada', 'texto', True),
        ('periodo_atividade', 'Período da atividade', 'texto', True),
        ('data_entrega', 'Data para entrega', 'data', True),
        ('local_entrega', 'Local de entrega', 'texto', True),
        ('num_pessoas', 'Nº de pessoas', 'numero', True),
        ('num_dias', 'Nº de dias', 'numero', True),
        ('observacao', 'Observação', 'area', False),
    ]),
}


def _valor_campo(objeto, atributo, tipo):
    valor = getattr(objeto, atributo, None)
    if valor is None:
        return ''
    if tipo == 'data':
        return valor.strftime('%Y-%m-%d')
    if tipo == 'hora':
        return valor.strftime('%H:%M')
    if tipo in ('numero', 'dinheiro'):
        return f'{float(valor):g}'
    return str(valor)


def _campo_html(atributo, rotulo, tipo, obrigatorio, valor):
    req = ' required' if obrigatorio else ''
    marca = ' <span style="color:red;">*</span>' if obrigatorio else ''
    nome = f'campo_{atributo}'

    if tipo == 'area':
        entrada = f'<textarea name="{nome}" rows="3"{req} style="width:100%; padding:7px;">{valor}</textarea>'
    elif tipo == 'data':
        entrada = f'<input type="date" name="{nome}" value="{valor}"{req} style="padding:7px;">'
    elif tipo == 'hora':
        entrada = f'<input type="time" name="{nome}" value="{valor}"{req} style="padding:7px;">'
    elif tipo == 'numero':
        entrada = f'<input type="number" step="1" min="0" name="{nome}" value="{valor}"{req} style="padding:7px; width:150px;">'
    elif tipo == 'dinheiro':
        entrada = f'<input type="number" step="0.01" min="0" name="{nome}" value="{valor}"{req} style="padding:7px; width:180px;">'
    elif tipo == 'uf':
        entrada = f'<select name="{nome}"{req} style="padding:7px; width:100px;"><option value="">UF</option>{montar_opcoes_estados(valor)}</select>'
    elif tipo == 'area_diaria':
        entrada = f'<select name="{nome}"{req} style="padding:7px;">{montar_opcoes_areas(valor)}</select>'
    elif tipo == 'tipo_diaria':
        entrada = f'<select name="{nome}"{req} style="padding:7px;">{montar_opcoes(TIPOS_DIARIA, valor)}</select>'
    elif tipo == 'transporte':
        entrada = f'<select name="{nome}"{req} style="padding:7px;">{montar_opcoes(TIPOS_TRANSPORTE, valor)}</select>'
    elif tipo == 'tipo_alimentacao':
        entrada = f'<select name="{nome}"{req} style="padding:7px;">{montar_opcoes_tipos_alimentacao(valor)}</select>'
    elif tipo == 'tipo_veiculo':
        entrada = f'<select name="{nome}"{req} style="padding:7px;">{montar_opcoes_tipos_veiculo(valor)}</select>'
    else:
        entrada = f'<input type="text" name="{nome}" value="{valor}"{req} style="width:100%; padding:7px;">'

    return f'<div style="margin-bottom:13px;"><label>{rotulo}:{marca}</label><br>{entrada}</div>'


def _recalcular_valor(solicitacao, detalhe):
    """Recalcula o valor total após a edição, conforme o tipo."""
    tipo = solicitacao.tipo

    if tipo == 'diaria':
        valor_diaria = obter_valor_diaria(detalhe.tipo_diaria, detalhe.tipo_destino)
        detalhe.valor_diaria = valor_diaria
        pernoites = int(detalhe.numero_pernoites or 0)
        quantidade_diarias = pernoites if pernoites > 0 else 1
        solicitacao.valor_total = (valor_diaria * quantidade_diarias) + float(detalhe.valor_auxilio or 0)

    elif tipo == 'passagem':
        solicitacao.valor_total = float(detalhe.valor_estimado or 0)

    elif tipo == 'compra_materiais':
        total = float(detalhe.quantidade or 0) * float(detalhe.valor_unitario or 0)
        detalhe.valor_total_item = total
        solicitacao.valor_total = total

    elif tipo == 'alimentacao':
        registro = TipoAlimentacao.query.filter_by(nome=detalhe.tipo_alimentacao).first()
        unitario = float(registro.valor) if registro else float(detalhe.custo_unitario or 0)
        detalhe.custo_unitario = unitario
        detalhe.custo_total = unitario * int(detalhe.quantidade_pessoas or 0)
        solicitacao.valor_total = detalhe.custo_total

    elif tipo == 'locacao_veiculo':
        registro = TipoVeiculo.query.filter_by(nome=detalhe.tipo_veiculo).first()
        custo_km = float(registro.valor_km) if registro else float(detalhe.custo_km or 0)
        detalhe.custo_km = custo_km
        detalhe.custo_estimado = custo_km * float(detalhe.km_estimado or 0)
        solicitacao.valor_total = detalhe.custo_estimado


@app.route('/solicitacao/<int:solicitacao_id>/corrigir', methods=['GET', 'POST'])
@login_required
def corrigir_solicitacao(solicitacao_id):
    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)

    eh_mesma_coordenacao = (
        current_user.coordenacao_id is not None
        and current_user.coordenacao_id == solicitacao.coordenacao_solicitante_id
    )
    if (solicitacao.solicitante_id != current_user.id
            and not current_user.is_organizador
            and not eh_mesma_coordenacao):
        abort(403)

    if solicitacao.status not in ('devolvida_ajuste', 'ajuste_dados'):
        flash('Só é possível corrigir solicitações devolvidas para ajuste.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    # 'ajuste_dados' vem do Executor: a correção volta direto para ele
    retorno_ao_executor = solicitacao.status == 'ajuste_dados'

    configuracao = CAMPOS_EDICAO.get(solicitacao.tipo)
    modelo = configuracao[0] if configuracao else None
    campos = configuracao[1] if configuracao else []
    detalhe = modelo.query.filter_by(solicitacao_id=solicitacao.id).first() if modelo else None

    if request.method == 'POST':
        solicitacao.ponto_focal = request.form.get('ponto_focal')
        solicitacao.atividade_projeto = request.form.get('atividade_projeto')
        solicitacao.contato_solicitante = request.form.get('contato_solicitante')
        coord = request.form.get('coordenacao_solicitante')
        solicitacao.coordenacao_solicitante_id = int(coord) if coord else None

        if detalhe:
            for atributo, _rotulo, tipo, obrigatorio in campos:
                bruto = request.form.get(f'campo_{atributo}')

                if bruto in (None, ''):
                    if obrigatorio:
                        flash('Preencha todos os campos obrigatórios.')
                        return redirect(url_for('corrigir_solicitacao', solicitacao_id=solicitacao_id))
                    setattr(detalhe, atributo, None)
                    continue

                if 'cpf' in atributo:
                    if not cpf_tem_11_digitos(bruto):
                        flash('Informe o CPF com 11 dígitos, no formato 000.000.000-00.')
                        return redirect(url_for('corrigir_solicitacao', solicitacao_id=solicitacao_id))
                    setattr(detalhe, atributo, formatar_cpf(bruto))
                elif tipo in ('numero',):
                    setattr(detalhe, atributo, int(float(bruto)))
                elif tipo == 'dinheiro':
                    setattr(detalhe, atributo, float(bruto))
                else:
                    setattr(detalhe, atributo, bruto)

            _recalcular_valor(solicitacao, detalhe)

        tipo_label = TIPO_SOLICITACAO_LABELS.get(solicitacao.tipo, solicitacao.tipo)

        if retorno_ao_executor:
            # volta ao ponto em que estava, sem repetir análise e aprovação
            solicitacao.status = solicitacao.status_antes_ajuste or 'aprovada'
            solicitacao.status_antes_ajuste = None
            solicitacao.motivo_ajuste_dados = None
            registrar_auditoria('corrigiu', solicitacao, 'Dados corrigidos e devolvidos ao Executor')
            db.session.commit()

            if solicitacao.responsavel_encaminhamento:
                enviar_email(
                    solicitacao.responsavel_encaminhamento.email,
                    'Dados corrigidos - SIGAD Carajás',
                    f'Olá, {solicitacao.responsavel_encaminhamento.nome}.\n\n'
                    f'A solicitação de {tipo_label}, de {solicitacao.solicitante.nome}, protocolo '
                    f'{protocolo(solicitacao)}, foi corrigida pelo solicitante e está de volta '
                    f'na sua fila para conclusão.',
                )

            flash('Dados corrigidos. A solicitação voltou para o responsável pelo encaminhamento.',
                  'sucesso')
            return redirect(url_for('minhas_solicitacoes'))

        solicitacao.status = 'pendente_analise'
        solicitacao.motivo_devolucao = None
        registrar_auditoria('corrigiu', solicitacao, 'Reenviada para análise')
        db.session.commit()

        for analista in Usuario.query.filter_by(perfil='analista').all():
            enviar_email(
                analista.email,
                'Solicitação corrigida e reenviada - SIGAD Carajás',
                f'Olá, {analista.nome}.\n\n'
                f'A solicitação de {tipo_label}, de {solicitacao.solicitante.nome}, protocolo '
                f'{protocolo(solicitacao)}, foi corrigida e reenviada para análise.',
            )

        flash('Solicitação corrigida e reenviada para análise.', 'sucesso')
        return redirect(url_for('minhas_solicitacoes'))

    campos_html = ''
    if detalhe:
        for atributo, rotulo, tipo, obrigatorio in campos:
            campos_html += _campo_html(atributo, rotulo, tipo, obrigatorio,
                                       _valor_campo(detalhe, atributo, tipo))

    aviso_itens = ''
    rota_criacao = ROTA_CRIACAO_POR_TIPO.get(solicitacao.tipo)
    if rota_criacao:
        aviso_itens = f"""
        <div class="bloco" style="background:#fff8e6; border-left:4px solid #b35c00;">
            <div style="font-size:12.5px; color:#7a4a00; margin-bottom:10px;">
                Esta solicitação tem uma lista de itens/participantes. Para corrigir, abra o
                formulário original já preenchido com os dados atuais, ajuste o que for
                necessário e reenvie - esta solicitação será substituída pela versão corrigida,
                mantendo o histórico.
            </div>
            <a href="{url_for(rota_criacao, corrigir_id=solicitacao.id)}" class="btn btn-salvar"
               style="text-decoration:none; display:inline-block; padding:9px 16px;">
                Corrigir e reenviar
            </a>
        </div>
        """

    tipo_label = TIPO_SOLICITACAO_LABELS.get(solicitacao.tipo, solicitacao.tipo)

    conteudo = f"""
    <div class="faixa-protocolo">
        <div>
            <div class="numero">{protocolo(solicitacao)}</div>
            <div class="tipo">{tipo_label} — correção solicitada</div>
        </div>
        <div class="chip" style="color:#b35c00;">{STATUS_LABELS.get(solicitacao.status, '')}</div>
    </div>

    <div class="bloco" style="border-left:4px solid #b35c00; max-width:980px;">
        <strong style="color:#b35c00; font-size:13px;">
            {'Correção solicitada pelo responsável pelo encaminhamento' if retorno_ao_executor
              else 'Ajuste solicitado pelo Analista'}
        </strong>
        <div style="font-size:13px; margin-top:6px; white-space:pre-wrap;">{(solicitacao.motivo_ajuste_dados if retorno_ao_executor else solicitacao.motivo_devolucao) or '-'}</div>
        {'<div style="font-size:12px; color:#666; margin-top:10px;">Ao salvar, a solicitação volta direto para o responsável pelo encaminhamento — sem passar novamente pela análise e pela aprovação.</div>' if retorno_ao_executor else ''}
    </div>

    {aviso_itens}

    <form method="POST" style="max-width:700px;">
        <h3>Dados gerais</h3>
        <div style="margin-bottom:13px;">
            <label>Ponto Focal:</label><br>
            <input type="text" name="ponto_focal" value="{solicitacao.ponto_focal or ''}" style="width:100%; padding:7px;">
        </div>
        <div style="margin-bottom:13px;">
            <label>Atividade/Projeto relacionado:</label><br>
            <input type="text" name="atividade_projeto" value="{solicitacao.atividade_projeto or ''}" style="width:100%; padding:7px;">
        </div>
        <div style="margin-bottom:13px;">
            <label>Coordenação Solicitante: <span style="color:red;">*</span></label><br>
            <select name="coordenacao_solicitante" required style="padding:7px;">
                <option value="">Selecione</option>
                {montar_opcoes_coordenacoes(solicitacao.coordenacao_solicitante_id)}
            </select>
        </div>
        <div style="margin-bottom:13px;">
            <label>Contato (telefone ou e-mail): <span style="color:red;">*</span></label><br>
            <input type="text" name="contato_solicitante" value="{solicitacao.contato_solicitante or ''}" required style="width:100%; padding:7px;">
        </div>

        <h3>Dados da solicitação</h3>
        {campos_html}

        <div style="margin-top:20px;">
            <button type="submit" class="btn btn-salvar" style="padding:11px 20px;">
                {'Salvar correção e devolver ao responsável' if retorno_ao_executor
                  else 'Salvar correção e reenviar para análise'}
            </button>
            <a href="{url_for('detalhe_solicitacao', solicitacao_id=solicitacao.id)}" class="btn-atalho"
               style="margin-left:8px;">Cancelar</a>
        </div>
    </form>
    """
    return render_pagina('Corrigir Solicitação', conteudo)


LISTA_RANCHO_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <title>Lista de Compras - {{ protocolo }}</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: Arial, sans-serif; margin: 0; padding: 24px; color: #1f2d26; background: #fff; }
        .cabecalho { border-bottom: 3px solid #37784D; padding-bottom: 12px; margin-bottom: 16px; }
        .cabecalho h1 { margin: 0; font-size: 19px; color: #004622; }
        .cabecalho .protocolo { font-family: monospace; font-size: 15px; margin-top: 4px; }
        .dados { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 18px; margin-bottom: 18px; }
        .dados div { font-size: 12px; }
        .dados strong { display: block; font-size: 10px; text-transform: uppercase;
                        letter-spacing: .5px; color: #666; margin-bottom: 2px; }
        table { border-collapse: collapse; width: 100%; margin-bottom: 18px; }
        th, td { border: 1px solid #bbb; padding: 6px 8px; font-size: 12px; text-align: left; }
        th { background: #e3f0e6; font-size: 11px; text-transform: uppercase; letter-spacing: .4px; }
        .categoria td { background: #f0f0f0; font-weight: bold; font-size: 11.5px; }
        .marcar { width: 34px; text-align: center; font-size: 15px; }
        .num { text-align: right; }
        .total td { background: #e3f0e6; font-weight: bold; }
        .observacao { border: 1px solid #bbb; padding: 10px; font-size: 12px; margin-bottom: 18px; }
        .assinaturas { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; margin-top: 46px; }
        .assinaturas div { border-top: 1px solid #333; padding-top: 5px; font-size: 11px; text-align: center; }
        .barra-acao { margin-bottom: 18px; }
        .barra-acao button, .barra-acao a {
            padding: 9px 16px; font-size: 13px; font-weight: 600; border-radius: 4px;
            border: none; cursor: pointer; text-decoration: none; margin-right: 8px;
            display: inline-block; font-family: inherit;
        }
        .barra-acao button { background: #37784D; color: #fff; }
        .barra-acao a { background: #fff; color: #37784D; border: 1px solid #cfe0d3; }
        .rodape { font-size: 10px; color: #777; margin-top: 22px; text-align: center; }
        @media print {
            .barra-acao { display: none; }
            body { padding: 0; }
        }
    </style>
</head>
<body>
    <div class="barra-acao">
        <button onclick="window.print()">Imprimir / Salvar em PDF</button>
        <a href="{{ voltar }}">Voltar</a>
    </div>

    <div class="cabecalho">
        <h1>SIGAD Carajás — Lista de Compras de Rancho</h1>
        <div class="protocolo">Protocolo {{ protocolo }}</div>
    </div>

    <div class="dados">
        <div><strong>Solicitante</strong>{{ solicitante }}</div>
        <div><strong>Responsável pela retirada</strong>{{ responsavel_retirada }}</div>
        <div><strong>Contato</strong>{{ contato }}</div>
        <div><strong>Atividade / Projeto</strong>{{ atividade }}</div>
        <div><strong>Período da atividade</strong>{{ periodo }}</div>
        <div><strong>Coordenação</strong>{{ coordenacao }}</div>
        <div><strong>Local de entrega</strong>{{ local_entrega }}</div>
        <div><strong>Data de entrega</strong>{{ data_entrega }}</div>
        <div><strong>Pessoas / Dias</strong>{{ num_pessoas }} pessoas — {{ num_dias }} dias</div>
    </div>

    <table>
        <tr>
            <th class="marcar">OK</th>
            <th>Item</th>
            <th style="width:70px;">Unidade</th>
            <th style="width:70px;">Qtd</th>
            <th style="width:100px;">Vlr. ref.</th>
            <th style="width:110px;">Subtotal</th>
        </tr>
        {{ linhas | safe }}
        <tr class="total">
            <td colspan="5" class="num">Total estimado</td>
            <td class="num">{{ total }}</td>
        </tr>
    </table>

    {{ bloco_carne | safe }}
    {{ bloco_observacao | safe }}

    <div class="assinaturas">
        <div>Responsável pela compra</div>
        <div>Conferido no recebimento</div>
    </div>

    <div class="rodape">
        Documento gerado pelo SIGAD Carajás em {{ gerado_em }} — valores de referência, sujeitos ao preço praticado no mercado.
    </div>
</body>
</html>
"""


@app.route('/solicitacao/<int:solicitacao_id>/rancho/lista-compras')
@login_required
def lista_compras_rancho(solicitacao_id):
    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)

    if solicitacao.tipo != 'rancho':
        abort(404)

    eh_dono = solicitacao.solicitante_id == current_user.id
    eh_fluxo = (current_user.perfil in ('analista', 'aprovador', 'comprador')
                or current_user.is_organizador)
    if not eh_dono and not eh_fluxo:
        abort(403)

    rancho = SolicitacaoRancho.query.filter_by(solicitacao_id=solicitacao.id).first()
    itens = ItemSolicitacaoRancho.query.filter_by(solicitacao_id=solicitacao.id).order_by(
        ItemSolicitacaoRancho.categoria, ItemSolicitacaoRancho.nome_item
    ).all()

    linhas = ''
    categoria_atual = None
    for item in itens:
        if item.categoria != categoria_atual:
            categoria_atual = item.categoria
            linhas += f'<tr class="categoria"><td colspan="6">{categoria_atual}</td></tr>'

        linhas += (
            f'<tr>'
            f'<td class="marcar">☐</td>'
            f'<td>{item.nome_item}</td>'
            f'<td>{item.unidade or "-"}</td>'
            f'<td class="num">{float(item.quantidade or 0):.0f}</td>'
            f'<td class="num">{moeda(item.valor_unitario)}</td>'
            f'<td class="num">{moeda(item.valor_total_item)}</td>'
            f'</tr>'
        )

    if not linhas:
        linhas = '<tr><td colspan="6">Nenhum item nesta solicitação.</td></tr>'

    bloco_carne = ''
    if rancho and (rancho.carne_bifes or rancho.carne_picada or rancho.carne_osso):
        bloco_carne = (
            f'<div class="observacao"><strong>Detalhamento da carne vermelha (kg):</strong><br>'
            f'Bifes: {float(rancho.carne_bifes or 0):.0f} &nbsp;|&nbsp; '
            f'Picada de panela: {float(rancho.carne_picada or 0):.0f} &nbsp;|&nbsp; '
            f'Com osso: {float(rancho.carne_osso or 0):.0f}</div>'
        )

    partes_obs = []
    if rancho and rancho.agua_mineral_20l:
        partes_obs.append(f'Água mineral 20L: {rancho.agua_mineral_20l} garrafão(ões).')
    if rancho and rancho.observacao:
        partes_obs.append(rancho.observacao)

    bloco_observacao = ''
    if partes_obs:
        bloco_observacao = ('<div class="observacao"><strong>Observações:</strong><br>'
                            + '<br>'.join(partes_obs) + '</div>')

    return render_template_string(
        LISTA_RANCHO_TEMPLATE,
        protocolo=protocolo(solicitacao),
        solicitante=solicitacao.solicitante.nome,
        responsavel_retirada=rancho.responsavel_retirada if rancho else '-',
        contato=solicitacao.contato_solicitante or '-',
        atividade=solicitacao.atividade_projeto or '-',
        periodo=rancho.periodo_atividade if rancho else '-',
        coordenacao=(solicitacao.coordenacao_solicitante.nome
                     if solicitacao.coordenacao_solicitante else '-'),
        local_entrega=rancho.local_entrega if rancho else '-',
        data_entrega=rancho.data_entrega.strftime('%d/%m/%Y') if rancho else '-',
        num_pessoas=rancho.num_pessoas if rancho else '-',
        num_dias=rancho.num_dias if rancho else '-',
        linhas=linhas,
        total=moeda(solicitacao.valor_total),
        bloco_carne=bloco_carne,
        bloco_observacao=bloco_observacao,
        gerado_em=agora().strftime('%d/%m/%Y'),
        voltar=url_for('detalhe_solicitacao', solicitacao_id=solicitacao.id),
    )


# ---------------- DETALHE DA SOLICITAÇÃO ----------------
def pode_editar_itens():
    return current_user.perfil in ('analista', 'aprovador') or current_user.is_organizador


# ---------------- ATIVIDADES AGRUPADAS ----------------
TIPOS_PARA_ATIVIDADE = [
    ('diaria_form', 'Diária'), ('passagem_form', 'Passagem'),
    ('compra_materiais_form', 'Compra de Materiais'), ('rancho_form', 'Rancho'),
    ('alimentacao_form', 'Alimentação'), ('locacao_veiculo_form', 'Locação de Veículos'),
    ('servico_externo_pf_form', 'Serviço Externo PF'), ('servico_externo_pj_form', 'Serviço Externo PJ'),
    ('seguro_form', 'Seguro'), ('bolsa_form', 'Bolsa'),
]


@app.route('/atividades')
@login_required
def atividades():
    busca = request.args.get('busca', '').strip()

    consulta = Atividade.query
    if busca:
        consulta = consulta.filter(Atividade.nome.ilike(f'%{busca}%'))

    lista = consulta.order_by(Atividade.criado_em.desc()).all()

    linhas = ''
    for a in lista:
        qtd = len(a.solicitacoes)
        valor_total_atividade = sum(float(s.valor_total or 0) for s in a.solicitacoes)
        linhas += f"""
        <tr>
            <td><a href="{url_for('detalhe_atividade', atividade_id=a.id)}">{a.nome}</a></td>
            <td style="font-size:12px;">{a.coordenacao.nome if a.coordenacao else '-'}</td>
            <td style="font-size:12px;">{a.criado_por.nome}</td>
            <td style="font-size:12px;">{a.criado_em.strftime('%d/%m/%Y')}</td>
            <td style="text-align:center;">{qtd}</td>
            <td style="text-align:right;">{moeda(valor_total_atividade)}</td>
            <td><a href="{url_for('detalhe_atividade', atividade_id=a.id)}" class="btn-atalho">Abrir</a></td>
        </tr>
        """
    if not linhas:
        linhas = '<tr><td colspan="7">Nenhuma atividade encontrada.</td></tr>'

    conteudo = f"""
    <h2>Solicitações Agrupadas</h2>
    <div class="bloco" style="border-left:4px solid #37784D; background:#eef5ee; max-width:800px; margin-bottom:16px;">
        <strong style="color:#004622;">O que é uma solicitação agrupada?</strong>
        <div style="font-size:12.5px; color:#3a4a42; margin-top:6px;">
            São solicitações de tipos diferentes (compra de materiais, passagem, diária, e assim
            por diante) que pertencem a uma <strong>mesma atividade específica</strong> - por
            exemplo, uma expedição de campo que precisa de material, passagem e diária ao mesmo
            tempo. Agrupar ajuda a acompanhar tudo junto.<br><br>
            Se as solicitações forem de <strong>atividades distintas</strong>, cada uma deve seguir
            o fluxo normal separadamente, sem agrupar - o agrupamento é só para o que pertence à
            mesma atividade.<br><br>
            Cada solicitação, mesmo agrupada, continua seguindo <strong>seu próprio fluxo normal
            de análise e aprovação</strong>, de forma independente das demais. O agrupamento é só
            para organização e consulta.
        </div>
    </div>
    <div style="display:flex; gap:10px; margin-bottom:14px; align-items:center;">
        <form method="GET" style="display:flex; gap:8px;">
            <input type="text" name="busca" value="{busca}" placeholder="Buscar atividade..." style="padding:7px; width:220px;">
            <button type="submit" class="btn-atalho">Buscar</button>
        </form>
        <a href="{url_for('nova_atividade')}" class="btn btn-adicionar" style="text-decoration:none; padding:9px 16px;">
            + Nova atividade
        </a>
    </div>
    <table style="max-width:1000px;">
        <tr><th>Nome</th><th>Coordenação</th><th>Criada por</th><th>Data</th>
            <th>Solicitações</th><th>Valor total</th><th>Ações</th></tr>
        {linhas}
    </table>
    """
    return render_pagina('Solicitações Agrupadas', conteudo)


@app.route('/atividades/nova', methods=['GET', 'POST'])
@login_required
def nova_atividade():
    resultado = bloquear_se_travado()
    if resultado:
        return resultado

    if request.method == 'POST':
        nome = (request.form.get('nome') or '').strip()
        if not nome:
            flash('Informe um nome para a atividade.')
            return redirect(url_for('nova_atividade'))

        atividade = Atividade(
            nome=nome,
            descricao=request.form.get('descricao'),
            criado_por_id=current_user.id,
            coordenacao_id=request.form.get('coordenacao_id') or None,
        )
        db.session.add(atividade)
        db.session.commit()

        flash(f'Atividade "{nome}" criada. Agora adicione as solicitações relacionadas.', 'sucesso')
        return redirect(url_for('detalhe_atividade', atividade_id=atividade.id))

    conteudo = f"""
    <h2>Nova Solicitação Agrupada</h2>
    <div class="bloco" style="border-left:4px solid #37784D; background:#eef5ee; max-width:600px; margin-bottom:16px;">
        <div style="font-size:12px; color:#3a4a42;">
            Dê um nome para a atividade específica que vai reunir as solicitações relacionadas
            a ela (compra de materiais, passagem, diária etc.). Use uma atividade só quando as
            solicitações forem realmente da mesma atividade - atividades distintas não devem
            ser agrupadas juntas.
        </div>
    </div>
    <form method="POST" style="max-width:600px;">
        <label>Nome da atividade: <span style="color:red;">*</span></label><br>
        <input type="text" name="nome" required placeholder="Ex: Expedição Igarapé Gelado - Setembro/2026"
               style="width:100%; padding:7px; margin-bottom:10px;"><br>

        <label>Coordenação:</label><br>
        <select name="coordenacao_id" style="padding:7px; width:100%; margin-bottom:10px;">
            <option value="">Selecione (opcional)</option>
            {montar_opcoes_coordenacoes()}
        </select><br>

        <label>Descrição (opcional):</label><br>
        <textarea name="descricao" rows="3" style="width:100%; padding:7px; margin-bottom:14px;"></textarea><br>

        <button type="submit" class="btn btn-adicionar" style="padding:10px 20px;">Criar</button>
    </form>
    """
    return render_pagina('Nova Solicitação Agrupada', conteudo)


@app.route('/atividades/<int:atividade_id>')
@login_required
def detalhe_atividade(atividade_id):
    atividade = Atividade.query.get_or_404(atividade_id)
    lista = sorted(atividade.solicitacoes, key=lambda s: s.data_envio or agora(), reverse=True)

    linhas = ''
    for s in lista:
        tipo_label = TIPO_SOLICITACAO_LABELS.get(s.tipo, s.tipo)
        cor_status = {
            'reprovada': '#c0392b', 'devolvida_ajuste': '#b35c00', 'ajuste_dados': '#b35c00',
            'paga': '#2e7d32', 'comprado': '#2e7d32',
        }.get(s.status, '#2b5876')
        linhas += f"""
        <tr>
            <td style="font-family:monospace; font-size:12px;">
                <a href="{url_for('detalhe_solicitacao', solicitacao_id=s.id)}">{protocolo(s)}</a>
            </td>
            <td>{tipo_label}</td>
            <td style="font-size:12px;">{s.solicitante.nome}</td>
            <td style="color:{cor_status}; font-weight:bold; font-size:12px;">
                {STATUS_LABELS.get(s.status, s.status)}
            </td>
            <td style="text-align:right;">{moeda(s.valor_total)}</td>
        </tr>
        """
    if not linhas:
        linhas = '<tr><td colspan="5">Nenhuma solicitação vinculada ainda.</td></tr>'

    valor_total_atividade = sum(float(s.valor_total or 0) for s in lista)

    botoes_tipo = ''
    for endpoint, rotulo in TIPOS_PARA_ATIVIDADE:
        botoes_tipo += (
            f'<a href="{url_for(endpoint)}?atividade_id={atividade.id}" class="btn-atalho" '
            f'style="text-decoration:none;">+ {rotulo}</a> '
        )

    conteudo = f"""
    <h2>{atividade.nome}</h2>
    <div style="font-size:12px; color:#666; margin-bottom:16px;">
        Criada por {atividade.criado_por.nome} em {atividade.criado_em.strftime('%d/%m/%Y')}
        {f' · Coordenação: {atividade.coordenacao.nome}' if atividade.coordenacao else ''}
        {f'<br>{atividade.descricao}' if atividade.descricao else ''}
    </div>

    <div class="bloco" style="max-width:900px; margin-bottom:16px;">
        <strong style="font-size:13px;">Adicionar solicitação a esta atividade</strong>
        <div style="font-size:11px; color:#888; margin:6px 0 10px;">
            Cada solicitação criada aqui já nasce vinculada à atividade e segue seu fluxo normal
            de análise e aprovação, de forma independente das demais.
        </div>
        {botoes_tipo}
    </div>

    <h3>Solicitações vinculadas ({len(lista)}) - {moeda(valor_total_atividade)}</h3>
    <table style="max-width:900px;">
        <tr><th>Protocolo</th><th>Tipo</th><th>Solicitante</th><th>Status</th><th>Valor</th></tr>
        {linhas}
    </table>
    """
    return render_pagina(atividade.nome, conteudo)


@app.route('/solicitacao/<int:solicitacao_id>/solicitar-comprovante', methods=['POST'])
@login_required
def solicitar_comprovante(solicitacao_id):
    """O solicitante pede o comprovante de pagamento quando o Executor
    concluiu sem anexar. Vai direto para o Executor, sem passar por análise
    nem aprovação - a solicitação já está concluída."""
    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)

    if solicitacao.solicitante_id != current_user.id and not current_user.is_organizador:
        abort(403)

    if solicitacao.status not in ('paga', 'comprado'):
        flash('Só é possível pedir o comprovante depois que a solicitação estiver concluída.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    tipo_comprovante = 'comprovante_compra' if solicitacao.status == 'comprado' else 'comprovante_pagamento'
    ja_tem = Anexo.query.filter_by(solicitacao_id=solicitacao.id, tipo_anexo=tipo_comprovante).count()
    if ja_tem:
        flash('O comprovante já está disponível nesta solicitação.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    solicitacao.comprovante_solicitado_em = agora()
    registrar_auditoria('solicitou_comprovante', solicitacao, '')
    db.session.commit()

    destinatario = solicitacao.responsavel_encaminhamento
    if destinatario:
        enviar_email(
            destinatario.email,
            f'Comprovante solicitado - {protocolo(solicitacao)} - SIGAD Carajás',
            f'Olá, {destinatario.nome}.\n\n'
            f'{solicitacao.solicitante.nome} pediu o comprovante de pagamento da solicitação, '
            f'protocolo {protocolo(solicitacao)}.\n\n'
            f'Acesse a solicitação no sistema para anexar.',
        )

    flash('Pedido enviado ao responsável pela solicitação.', 'sucesso')
    return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))


@app.route('/solicitacao/<int:solicitacao_id>/anexar-comprovante-posterior', methods=['POST'])
@login_required
def anexar_comprovante_posterior(solicitacao_id):
    """O Executor anexa o comprovante depois da conclusão, atendendo ao
    pedido do solicitante (ou por conta própria, a qualquer momento)."""
    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)

    pode = (current_user.is_organizador
            or (solicitacao.responsavel_encaminhamento_id == current_user.id)
            or current_user.perfil == 'comprador')
    if not pode:
        abort(403)

    if solicitacao.status not in ('paga', 'comprado'):
        flash('Só é possível anexar o comprovante de uma solicitação concluída.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    arquivo = request.files.get('comprovante')
    if not arquivo or not arquivo.filename:
        flash('Selecione o arquivo do comprovante.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    tipo_comprovante = 'comprovante_compra' if solicitacao.status == 'comprado' else 'comprovante_pagamento'
    salvar_anexo(solicitacao.id, arquivo, tipo_comprovante)
    solicitacao.comprovante_solicitado_em = None
    registrar_auditoria('anexou_comprovante', solicitacao, f'Arquivo: {arquivo.filename}')
    db.session.commit()

    notificar_solicitante(
        solicitacao,
        'Comprovante de pagamento disponível - SIGAD Carajás',
        f'Olá, {solicitacao.solicitante.nome}.\n\n'
        f'O comprovante da sua solicitação, protocolo {protocolo(solicitacao)}, já está '
        f'disponível no sistema.',
    )

    flash('Comprovante anexado.', 'sucesso')
    return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))


@app.route('/buscar-protocolo')
@login_required
def buscar_protocolo():
    """Busca global por protocolo, disponível no topo de qualquer tela.
    A verificação de quem pode ver a solicitação continua sendo feita pela
    própria tela de detalhe - aqui só encontramos o registro certo."""
    texto = request.args.get('protocolo', '')
    solicitacao_id = id_a_partir_do_protocolo(texto)

    if not solicitacao_id:
        flash('Protocolo não encontrado. Confira o número digitado.')
        return redirect(request.referrer or url_for('inicio'))

    solicitacao = Solicitacao.query.get(solicitacao_id)
    if not solicitacao:
        flash(f'Nenhuma solicitação encontrada com esse protocolo.')
        return redirect(request.referrer or url_for('inicio'))

    return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao.id))


@app.route('/solicitacao/<int:solicitacao_id>/detalhe')
@login_required
def detalhe_solicitacao(solicitacao_id):
    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)

    eh_dono = solicitacao.solicitante_id == current_user.id
    eh_fluxo = current_user.perfil in ('analista', 'aprovador', 'comprador') or current_user.is_organizador
    # colega da MESMA coordenacao tambem pode ver e, se estiver devolvida,
    # corrigir - cobre o caso de a pessoa titular ficar doente, viajar, etc.
    eh_mesma_coordenacao = (
        current_user.coordenacao_id is not None
        and current_user.coordenacao_id == solicitacao.coordenacao_solicitante_id
    )
    if not eh_dono and not eh_fluxo and not eh_mesma_coordenacao:
        abort(403)

    tipo_label = TIPO_SOLICITACAO_LABELS.get(solicitacao.tipo, solicitacao.tipo)
    status_label = STATUS_LABELS.get(solicitacao.status, solicitacao.status)
    coordenacao = solicitacao.coordenacao_solicitante.nome if solicitacao.coordenacao_solicitante else '-'

    cores_status = {
        'pendente_analise': '#5b6b76', 'devolvida_ajuste': '#b35c00',
        'pendente_aprovacao': '#37784D', 'aprovada': '#2e7d32',
        'em_execucao': '#b35c00', 'enviado_pagamento': '#5b6b76',
        'em_compra': '#5b6b76', 'paga': '#2e7d32', 'comprado': '#2e7d32',
        'reprovada': '#c0392b',
        'ajuste_dados': '#b35c00',
    }
    cor_status = cores_status.get(solicitacao.status, '#5b6b76')

    bloco_valor_real = ''
    if solicitacao.valor_real is not None:
        rotulo_real = 'Valor real da compra'
        diferenca = float(solicitacao.valor_real) - float(solicitacao.valor_total or 0)
        if abs(diferenca) < 0.01:
            comparativo = 'igual ao estimado'
        elif diferenca < 0:
            comparativo = f'{moeda(abs(diferenca))} abaixo do estimado'
        else:
            comparativo = f'{moeda(diferenca)} acima do estimado'
        bloco_valor_real = f"""
            <div style="font-size:11px; opacity:.85; margin-top:7px;">{rotulo_real}</div>
            <div style="font-size:20px; font-weight:700;">{moeda(solicitacao.valor_real)}</div>
            <div style="font-size:10.5px; opacity:.8;">{comparativo}</div>
        """

    vinculo_atividade = ''
    if solicitacao.atividade:
        vinculo_atividade = (
            f'<div style="font-size:11px; opacity:.9; margin-top:4px;">'
            f'<a href="{url_for("detalhe_atividade", atividade_id=solicitacao.atividade.id)}" '
            f'style="color:#fff; text-decoration:underline;">📋 {solicitacao.atividade.nome}</a></div>'
        )

    faixa = f"""
    <div class="faixa-protocolo">
        <div>
            <div class="numero">{protocolo(solicitacao)}</div>
            <div class="tipo">{tipo_label}</div>
            {vinculo_atividade}
        </div>
        <div style="text-align:right;">
            <div class="chip" style="color:{cor_status};">{status_label}</div>
            <div style="font-size:11px; opacity:.85; margin-top:9px;">Valor estimado</div>
            <div style="font-size:{'15px' if solicitacao.valor_real else '18px'}; font-weight:700;">
                {moeda(solicitacao.valor_total)}
            </div>
            {bloco_valor_real}
        </div>
    </div>
    """

    def painel(titulo, campos):
        """campos: lista de (rotulo, valor) ou (rotulo, valor, 'largo')."""
        blocos = ''
        for campo in campos:
            rotulo, valor = campo[0], campo[1]
            largo = ' largo' if len(campo) > 2 else ''
            if valor in (None, '', '-'):
                continue
            blocos += (f'<div class="campo{largo}"><div class="rotulo">{rotulo}</div>'
                       f'<div class="valor">{valor}</div></div>')
        if not blocos:
            return ''
        return f'<div class="painel"><div class="titulo">{titulo}</div><div class="grade">{blocos}</div></div>'

    identificacao = painel('Identificação da solicitação', [
        ('Solicitante', solicitacao.solicitante.nome),
        ('Data de envio', solicitacao.data_envio.strftime('%d/%m/%Y às %H:%M')),
        ('Coordenação solicitante', coordenacao),
        ('Contato', solicitacao.contato_solicitante),
        ('Ponto focal', solicitacao.ponto_focal),
        ('Atividade / Projeto', solicitacao.atividade_projeto),
    ])

    campos_aprovacao = [
        ('Nº lote de aprovação', solicitacao.lote_aprovacao),
        ('Convênio', solicitacao.convenio),
    ]
    if solicitacao.tipo == 'bolsa':
        campos_aprovacao.append(('Rubrica', solicitacao.rubrica))
        campos_aprovacao.append(('E-mail do CTC (encaminhamento externo)', solicitacao.email_ctc))
    else:
        campos_aprovacao.append((
            'Responsável pelo encaminhamento',
            solicitacao.responsavel_encaminhamento.nome if solicitacao.responsavel_encaminhamento else None,
        ))
    campos_aprovacao += [
        ('Prazo de atendimento',
         solicitacao.prazo_encaminhamento.strftime('%d/%m/%Y') if solicitacao.prazo_encaminhamento else None),
        ('Em compra desde' if fluxo_do_tipo(solicitacao.tipo) == 'compra' else 'Enviado para pagamento em',
         solicitacao.data_envio_pagamento.strftime('%d/%m/%Y') if solicitacao.data_envio_pagamento else None),
        ('Comprado em' if fluxo_do_tipo(solicitacao.tipo) == 'compra' else 'Pago em',
         solicitacao.data_pagamento.strftime('%d/%m/%Y') if solicitacao.data_pagamento else None),
    ]
    tramitacao = painel('Tramitação', campos_aprovacao)

    cabecalho = faixa + identificacao + tramitacao

    corpo = ''

    LARGOS = ('Justificativa', 'Especificação', 'Percurso / paradas', 'Observação',
              'Nome e especificação', 'Justificativa do auxílio', 'Link do produto',
              'Percurso / Pontos de parada', 'Endereço')

    def tabela(titulo, linhas):
        campos = []
        for rotulo, valor in linhas:
            if any(rotulo.startswith(l) for l in LARGOS):
                campos.append((rotulo, valor, 'largo'))
            else:
                campos.append((rotulo, valor))
        return painel(titulo, campos)

    def data_br(valor):
        return valor.strftime('%d/%m/%Y') if valor else None

    def dinheiro(valor):
        return moeda(valor)

    if solicitacao.tipo == 'diaria':
        diarias_lista = SolicitacaoDiaria.query.filter_by(solicitacao_id=solicitacao.id).all()
        d = diarias_lista[0] if diarias_lista else None
        if d:
            corpo += tabela('Dados da viagem (compartilhados por todos os diaristas)', [
                ('Data de ida', data_br(d.data_ida)),
                ('Data de retorno', data_br(d.data_retorno)),
                ('Origem', f'{d.cidade_origem}/{d.estado_origem}'),
                ('Destino', f'{d.cidade_destino}/{d.estado_destino}'),
                ('Tipo de diária (área)', d.tipo_destino),
                ('Diária cheia/meia', 'Detalhada (mista)' if d.diaria_detalhada else d.tipo_diaria),
                ('Nº de pernoites', d.numero_pernoites),
            ] + ([
                ('Diárias cheias', f'{d.qtd_diarias_cheias} x {dinheiro(d.valor_unitario_cheia)}'),
                ('Período de diária cheia',
                 f'{data_br(d.periodo_cheia_inicio)} a {data_br(d.periodo_cheia_fim)}' if d.periodo_cheia_inicio else '-'),
                ('Diárias meias', f'{d.qtd_diarias_meias} x {dinheiro(d.valor_unitario_meia)}'),
                ('Período de meia diária',
                 f'{data_br(d.periodo_meia_inicio)} a {data_br(d.periodo_meia_fim)}' if d.periodo_meia_inicio else '-'),
                ('Valor total das diárias (por diarista)', dinheiro(
                    (d.qtd_diarias_cheias or 0) * float(d.valor_unitario_cheia or 0)
                    + (d.qtd_diarias_meias or 0) * float(d.valor_unitario_meia or 0)
                )),
            ] if d.diaria_detalhada else [
                ('Valor da diária (por diarista)', dinheiro(d.valor_diaria)),
            ]) + [
                ('Auxílio deslocamento', 'Sim' if d.tera_auxilio_deslocamento else 'Não'),
                ('Qtd. de auxílio', d.quantidade_auxilio),
                ('Valor do auxílio (por diarista)', dinheiro(d.valor_auxilio)),
                ('Justificativa do auxílio', d.justificativa_auxilio),
                ('Justificativa', d.justificativa),
            ])

            for indice, diarista in enumerate(diarias_lista, start=1):
                corpo += tabela(f'Diarista {indice} - {diarista.nome_diarista}', [
                    ('CPF', diarista.cpf_diarista), ('Telefone', diarista.telefone_diarista),
                    ('E-mail', diarista.email_diarista),
                    ('Banco', diarista.banco_diarista), ('Agência', diarista.agencia_diarista),
                    ('Conta', diarista.conta_diarista), ('Chave PIX', diarista.chave_pix),
                ])

            if solicitacao.status in ('aprovada', 'em_execucao', 'enviado_pagamento', 'paga'):
                rotulo_p, cor_p, dias_p, prazo_p = situacao_prestacao(d, solicitacao)
                pode_registrar = (solicitacao.solicitante_id == current_user.id) or pode_ver_prestacao()

                if solicitacao.prestacao_contas_entregue:
                    aprovador_p = solicitacao.prestacao_aprovada_por or '-'
                    acao_p = (f'<div style="font-size:13px; color:#2e7d32; margin-top:8px;">'
                              f'Aprovada em {solicitacao.data_prestacao_contas.strftime("%d/%m/%Y")} '
                              f'por {aprovador_p}. O relatório está na lista de anexos abaixo.</div>')

                elif solicitacao.relatorio_em_conferencia:
                    enviado_em = (solicitacao.data_relatorio_enviado.strftime('%d/%m/%Y')
                                  if solicitacao.data_relatorio_enviado else '-')
                    tem_relatorio_anexado = Anexo.query.filter_by(
                        solicitacao_id=solicitacao.id, tipo_anexo='prestacao_contas').count()

                    if pode_avaliar_prestacao() and not tem_relatorio_anexado:
                        acao_p = ('<div style="font-size:13px; color:#c0392b; margin-top:8px;">'
                                  'Este protocolo está marcado como aguardando conferência, mas '
                                  'nenhum relatório foi anexado. Devolva ao solicitante para envio.</div>')
                    elif pode_avaliar_prestacao():
                        acao_p = f"""
                        <div style="font-size:13px; color:#b35c00; margin:8px 0;">
                            Relatório enviado em {enviado_em}, aguardando sua conferência.
                            Baixe o arquivo na lista de anexos abaixo antes de decidir.
                        </div>
                        <form method="POST" action="{url_for('avaliar_prestacao_contas', solicitacao_id=solicitacao.id)}"
                              id="form-prestacao">
                            <label>Motivo da devolução (obrigatório para devolver):</label><br>
                            <textarea name="motivo" id="motivo-prestacao" rows="3"
                                      style="width:100%; padding:7px; margin-bottom:12px;"></textarea><br>
                            <button type="submit" name="acao" value="aprovar" class="btn btn-salvar"
                                    style="padding:10px 18px;">Aprovar prestação de contas</button>
                            <button type="submit" name="acao" value="recusar" class="btn"
                                    style="padding:10px 18px; background:#c0392b; color:#fff;">
                                Devolver para correção</button>
                        </form>
                        <script>
                        document.getElementById('form-prestacao').addEventListener('submit', function(evento) {{
                            var acao = evento.submitter ? evento.submitter.value : '';
                            var motivo = document.getElementById('motivo-prestacao').value.trim();
                            if (acao === 'recusar' && motivo === '') {{
                                evento.preventDefault();
                                alert('Informe o motivo da devolução do relatório.');
                            }}
                        }});
                        </script>
                        """
                    else:
                        acao_p = (f'<div style="font-size:13px; color:#b35c00; margin-top:8px;">'
                                  f'Relatório enviado em {enviado_em}. Aguardando conferência do '
                                  f'Executor ou do Analista.</div>')

                elif pode_registrar:
                    recusa_html = ''
                    if solicitacao.motivo_recusa_prestacao:
                        recusa_html = (
                            f'<div style="background:#fdeceb; border-left:4px solid #c0392b; color:#a02020; '
                            f'padding:10px 13px; border-radius:4px; font-size:12.5px; margin:10px 0;">'
                            f'<strong>Relatório devolvido para correção.</strong><br>'
                            f'{solicitacao.motivo_recusa_prestacao}</div>'
                        )

                    acao_p = recusa_html + f"""
                    <form method="POST" action="{url_for('registrar_prestacao_contas', solicitacao_id=solicitacao.id)}"
                          enctype="multipart/form-data" style="margin-top:10px;">
                        <label>Relatório de viagem: <span style="color:red;">*</span></label><br>
                        <input type="file" name="relatorio_prestacao" required
                               accept=".pdf,.doc,.docx,.jpg,.jpeg,.png" style="margin-bottom:10px;"><br>
                        <div style="font-size:11px; color:#666; margin-bottom:10px;">
                            Ao enviar, o responsável pelo encaminhamento e a equipe de análise são
                            notificados automaticamente.
                        </div>
                        <button type="submit" class="btn btn-salvar" style="padding:9px 16px;">
                            Enviar relatório de viagem
                        </button>
                    </form>
                    """
                else:
                    acao_p = ''

                atraso_p = f' ({dias_p} dia(s) de atraso)' if dias_p > 0 else ''
                corpo += f"""
                <h3>Prestação de Contas</h3>
                <div class="bloco" style="max-width:700px; border-left:4px solid {cor_p};">
                    <div style="font-size:13px;">
                        Situação: <strong style="color:{cor_p};">{rotulo_p}{atraso_p}</strong>
                    </div>
                    <div style="font-size:12px; color:#666; margin-top:5px;">
                        Prazo final: <strong>{prazo_p.strftime('%d/%m/%Y')}</strong>
                        ({PRAZO_PRESTACAO_DIAS} dias corridos após o retorno em {d.data_retorno.strftime('%d/%m/%Y')}).
                    </div>
                    {acao_p}
                </div>
                """

    if solicitacao.tipo == 'passagem':
        passageiros = SolicitacaoPassagem.query.filter_by(solicitacao_id=solicitacao.id).all()

        if passageiros:
            primeiro = passageiros[0]
            corpo += tabela('Dados da viagem', [
                ('Tipo de transporte', primeiro.tipo_transporte),
                ('Origem', f'{primeiro.cidade_origem}/{primeiro.estado_origem}'),
                ('Destino', f'{primeiro.cidade_destino}/{primeiro.estado_destino}'),
                ('Data de ida', data_br(primeiro.data_ida)),
                ('Data de volta', data_br(primeiro.data_volta)),
                ('Bagagem despachada', 'Sim' if primeiro.com_bagagem else 'Não'),
                ('Quantidade de passageiros', len(passageiros)),
                ('Justificativa', primeiro.justificativa),
            ])

            def voo_formatado(saida, chegada):
                if not saida:
                    return None
                texto = saida.strftime('%d/%m/%Y às %H:%M')
                if chegada:
                    texto += f' &#8594; chegada {chegada.strftime("%d/%m/%Y às %H:%M")}'
                return texto

            for indice, p in enumerate(passageiros, start=1):
                campos = [
                    ('Nome', p.nome_passageiro),
                    ('CPF', p.cpf_passageiro),
                    ('RG / Órgão / UF', p.rg_orgao_uf_passageiro),
                    ('Data de nascimento', data_br(p.data_nascimento_passageiro)),
                    ('Telefone', p.telefone_passageiro),
                    ('E-mail', p.email_passageiro),
                    ('Menor tarifa encontrada', dinheiro(p.menor_tarifa_encontrada)),
                    ('Valor do voo escolhido', dinheiro(p.valor_estimado)),
                ]
                if p.justificativa_tarifa:
                    campos.append(('Justificativa por não optar pela tarifa mais barata',
                                   p.justificativa_tarifa, 'largo'))
                campos += [
                    ('Ida - companhia e voo',
                     f'{p.voo_ida_companhia or "-"} - {p.voo_ida_numero or "-"}'),
                    ('Ida - partida', voo_formatado(p.voo_ida_saida, p.voo_ida_chegada), 'largo'),
                ]

                if p.voo_volta_companhia or p.voo_volta_saida:
                    campos += [
                        ('Volta - companhia e voo',
                         f'{p.voo_volta_companhia or "-"} - {p.voo_volta_numero or "-"}'),
                        ('Volta - partida', voo_formatado(p.voo_volta_saida, p.voo_volta_chegada), 'largo'),
                    ]

                campos.append(('Observação sobre o voo', p.observacao_voo, 'largo'))
                corpo += painel(f'Passageiro {indice} - {p.nome_passageiro}', campos)

    if solicitacao.tipo == 'compra_materiais':
        itens_compra = SolicitacaoCompraMateriais.query.filter_by(solicitacao_id=solicitacao.id).all()

        if itens_compra:
            corpo += tabela('Dados da compra', [
                ('Data de entrega do material', data_br(itens_compra[0].data_entrega_material)),
                ('Quantidade de itens', len(itens_compra)),
            ])

            linhas_compra = ''
            for indice, c in enumerate(itens_compra, start=1):
                link_html = (f'<a href="{c.link_produto}" target="_blank">abrir</a>'
                             if c.link_produto else '-')
                linhas_compra += f"""
                <tr>
                    <td style="text-align:center;">{indice}</td>
                    <td style="font-size:12px;">{c.nome_especificacao}
                        <br><span style="font-size:11px; color:#666;">{c.justificativa or ''}</span>
                    </td>
                    <td style="font-size:12px;">{c.fornecedor_sugerido or '-'}</td>
                    <td style="font-size:12px;">{c.forma_aquisicao}</td>
                    <td style="text-align:center; font-size:12px;">{link_html}</td>
                    <td style="text-align:center;">{float(c.quantidade or 0):.0f}</td>
                    <td style="text-align:right;">{moeda(c.valor_unitario)}</td>
                    <td style="text-align:right;"><strong>{moeda(c.valor_total_item)}</strong></td>
                </tr>
                """

            corpo += f"""
            <h3>Itens solicitados</h3>
            <table style="max-width:1100px;">
                <tr>
                    <th style="width:45px;">Item</th><th>Especificação / Justificativa</th>
                    <th>Fornecedor</th><th>Aquisição</th><th style="width:70px;">Link</th>
                    <th style="width:70px;">Qtd</th><th style="width:110px;">Vlr. unitário</th>
                    <th style="width:120px;">Total</th>
                </tr>
                {linhas_compra}
                <tr style="background:#eef5ee;">
                    <td colspan="7" style="text-align:right; font-weight:700;">Total da solicitação</td>
                    <td style="text-align:right; font-weight:700;">{moeda(solicitacao.valor_total)}</td>
                </tr>
            </table>
            """

            if float(solicitacao.valor_total or 0) > 5000:
                qtd_anexos = Anexo.query.filter_by(solicitacao_id=solicitacao.id).count()
                cor_cot = '#2e7d32' if qtd_anexos >= 3 else '#c0392b'
                situacao_cot = ('requisito atendido' if qtd_anexos >= 3
                                else 'PENDENTE - mínimo de 3 orçamentos')
                corpo += f"""
                <div class="bloco" style="max-width:1100px; border-left:4px solid {cor_cot};">
                    <div style="font-size:13px;">
                        Solicitação acima de R$ 5.000,00 — exige 3 orçamentos.
                        <strong style="color:{cor_cot};">{qtd_anexos} anexo(s): {situacao_cot}</strong>
                    </div>
                </div>
                """

    if solicitacao.tipo == 'alimentacao':
        a = SolicitacaoAlimentacao.query.filter_by(solicitacao_id=solicitacao.id).first()
        if a and pode_editar_itens() and solicitacao.status in ('pendente_analise', 'pendente_aprovacao'):
            corpo += f"""
            <h3>Ajustar quantidade</h3>
            <form method="POST" action="{url_for('editar_quantidade_alimentacao', solicitacao_id=solicitacao.id)}"
                  class="bloco" style="max-width:620px;">
                <div style="font-size:12px; color:#666; margin-bottom:10px;">
                    Altere a quantidade de pessoas atendidas. O custo total é recalculado automaticamente
                    (custo unitário de R$ {float(a.custo_unitario or 0):.2f} por pessoa) e o solicitante é notificado.
                </div>
                <label>Quantidade de pessoas:</label><br>
                <input type="number" name="quantidade_pessoas" min="1" step="1"
                       value="{a.quantidade_pessoas}" style="padding:7px; width:120px; margin-bottom:12px;"><br>
                <button type="submit" class="btn btn-salvar" style="padding:9px 16px;">
                    Salvar quantidade e recalcular valor
                </button>
            </form>
            """
        if a:
            corpo += tabela('Dados da alimentação', [
                ('Tipo de alimentação', a.tipo_alimentacao),
                ('Quantidade de pessoas', a.quantidade_pessoas),
                ('Entrega ou retirada', a.forma_entrega),
                ('Local de entrega', a.local_entrega),
                ('Data', data_br(a.data_entrega)),
                ('Horário', a.horario_entrega.strftime('%H:%M') if a.horario_entrega else '-'),
                ('Custo unitário', dinheiro(a.custo_unitario)),
                ('Custo total', dinheiro(a.custo_total)),
                ('Justificativa', a.justificativa),
            ])

    if solicitacao.tipo == 'locacao_veiculo':
        v = SolicitacaoLocacaoVeiculo.query.filter_by(solicitacao_id=solicitacao.id).first()
        if v:
            corpo += tabela('Dados da locação', [
                ('Tipo de veículo', v.tipo_veiculo),
                ('Especificações', v.especificacoes),
                ('Local de origem', v.local_origem),
                ('Percurso / paradas', v.percurso),
                ('Local de retorno', v.local_retorno),
                ('Partida', v.data_hora_partida.strftime('%d/%m/%Y %H:%M')),
                ('Chegada prevista', v.data_hora_chegada.strftime('%d/%m/%Y %H:%M')),
                ('KM estimado', f'{float(v.km_estimado or 0):.0f}'),
                ('Custo por KM', dinheiro(v.custo_km)),
                ('Custo estimado', dinheiro(v.custo_estimado)),
                ('Justificativa', v.justificativa),
                ('Observação', v.observacao),
            ])

    if solicitacao.tipo in ('servico_externo', 'servico_externo_pf', 'servico_externo_pj'):
        prestadores = PrestadorServico.query.filter_by(solicitacao_id=solicitacao.id).all()
        for indice, pr in enumerate(prestadores, start=1):
            identificacao = [('Nome da empresa', pr.nome_empresa), ('CNPJ', pr.cnpj)] if pr.tipo_prestador == 'PJ' else [
                ('Nome do prestador', pr.nome_prestador), ('CPF', pr.cpf_prestador), ('RG', pr.rg_prestador),
                ('Telefone', pr.telefone_prestador), ('PIS/NIS', pr.pis_nis), ('Endereço', pr.endereco_prestador),
            ]
            campos_valor = (
                [
                    ('Valor diário de referência', dinheiro(pr.valor_diario)),
                    ('Dias de atividade', pr.dias_atividade),
                    ('Subtotal (diária x dias)', dinheiro(pr.valor_subtotal_servico)),
                    (f'ISS ({pr.aliquota_iss}%)', dinheiro(pr.valor_iss)),
                    ('Valor total do serviço', dinheiro(pr.valor_servico)),
                ] if pr.tipo_prestador == 'PF' and pr.dias_atividade else
                [('Valor orçado', dinheiro(pr.valor_servico))]
            )

            corpo += tabela(f'Prestador {indice} ({pr.tipo_prestador})', [
                ('Categoria do serviço', pr.categoria_servico),
                ('Nome do serviço', pr.nome_servico),
                ('Fornecedor sugerido', pr.fornecedor_sugerido),
                ('Especificação', pr.especificacao),
            ] + campos_valor + [
                ('Justificativa', pr.justificativa),
            ] + identificacao + [
                ('Banco', pr.banco), ('Agência', pr.agencia), ('Conta', pr.conta), ('Chave PIX', pr.chave_pix),
            ])

    if solicitacao.tipo == 'servico_externo_pf':
        eh_dono_pf = solicitacao.solicitante_id == current_user.id
        eh_executor_pf = pode_executar(solicitacao)
        pode_ver_boleto = eh_dono_pf or eh_executor_pf or eh_fluxo or current_user.is_organizador

        if pode_ver_boleto and solicitacao.status in ('aprovada', 'em_execucao', 'enviado_pagamento', 'paga'):
            tem_nota_fiscal = Anexo.query.filter_by(
                solicitacao_id=solicitacao.id, tipo_anexo='nota_fiscal').count() > 0

            # qual das duas pernas de pagamento está ativa agora (o status
            # "enviado_pagamento" é reaproveitado nas duas, então a etapa
            # exata é deduzida pelo que já foi pago)
            etapa_boleto = not solicitacao.boleto_pago_em
            aguardando_envio_boleto = etapa_boleto and solicitacao.status == 'em_execucao'
            aguardando_pagamento_boleto = etapa_boleto and solicitacao.status == 'enviado_pagamento'
            aguardando_envio_nf = (not etapa_boleto) and tem_nota_fiscal and not solicitacao.nf_pago_em and solicitacao.status == 'em_execucao'
            aguardando_pagamento_nf = (not etapa_boleto) and solicitacao.status == 'enviado_pagamento' and not solicitacao.nf_pago_em

            # o vencimento fica sempre visível e com destaque, em qualquer
            # etapa, enquanto o boleto não é pago - é o ponto mais urgente
            aviso_vencimento = ''
            if solicitacao.boleto_vencimento and not solicitacao.boleto_pago_em:
                dias_para_vencer = (solicitacao.boleto_vencimento - hoje()).days
                data_fmt = solicitacao.boleto_vencimento.strftime("%d/%m/%Y")
                if dias_para_vencer < 0:
                    aviso_vencimento = f'<div style="font-size:18px; font-weight:bold; color:#c0392b; margin-top:6px;">VENCIMENTO: {data_fmt} — BOLETO VENCIDO</div>'
                elif dias_para_vencer <= 3:
                    aviso_vencimento = f'<div style="font-size:18px; font-weight:bold; color:#b35c00; margin-top:6px;">VENCIMENTO: {data_fmt} — vence em {dias_para_vencer} dia(s)</div>'
                else:
                    aviso_vencimento = f'<div style="font-size:15px; font-weight:bold; color:#2b5876; margin-top:6px;">Vencimento: {data_fmt}</div>'

            if not solicitacao.boleto_vencimento:
                situacao_boleto = 'Aguardando o solicitante anexar o boleto.'
                cor_boleto, fundo_boleto = '#5b6b76', '#f4f6f5'
            elif aguardando_envio_boleto:
                situacao_boleto = 'Boleto anexado. Aguardando o Executor enviar para pagamento.'
                cor_boleto, fundo_boleto = '#2b5876', '#eef4f8'
            elif aguardando_pagamento_boleto:
                dias_para_vencer = (solicitacao.boleto_vencimento - hoje()).days
                if dias_para_vencer < 0:
                    cor_boleto, fundo_boleto = '#c0392b', '#fdeceb'
                elif dias_para_vencer <= 3:
                    cor_boleto, fundo_boleto = '#b35c00', '#fff8ec'
                else:
                    cor_boleto, fundo_boleto = '#2b5876', '#eef4f8'
                situacao_boleto = 'Boleto enviado para pagamento. Aguardando o Executor marcar como pago.'
            elif etapa_boleto:
                situacao_boleto = 'Boleto pendente.'
                cor_boleto, fundo_boleto = '#5b6b76', '#f4f6f5'
            elif not tem_nota_fiscal:
                situacao_boleto = (f'Boleto pago em {solicitacao.boleto_pago_em.strftime("%d/%m/%Y")}. '
                                   f'Aguardando o solicitante anexar a nota fiscal.')
                cor_boleto, fundo_boleto = '#b35c00', '#fff8ec'
            elif aguardando_envio_nf:
                situacao_boleto = 'Nota fiscal recebida. Aguardando o Executor enviar para pagamento.'
                cor_boleto, fundo_boleto = '#2b5876', '#eef4f8'
            elif aguardando_pagamento_nf:
                situacao_boleto = 'Nota fiscal enviada para pagamento. Aguardando o Executor marcar como paga.'
                cor_boleto, fundo_boleto = '#b35c00', '#fff8ec'
            else:
                situacao_boleto = (f'Concluído: boleto pago em {solicitacao.boleto_pago_em.strftime("%d/%m/%Y")} '
                                   f'e nota fiscal paga em {solicitacao.nf_pago_em.strftime("%d/%m/%Y")}.')
                cor_boleto, fundo_boleto = '#2e7d32', '#eef5ee'

            corpo += f"""
            <h3>Boleto de arrecadação municipal (BAM)</h3>
            <div class="bloco" style="border-left:4px solid {cor_boleto}; background:{fundo_boleto}; max-width:700px;">
                <strong style="color:{cor_boleto};">{situacao_boleto}</strong>
                {aviso_vencimento}
            """

            # 1) solicitante anexa o boleto (arquivo + vencimento)
            if eh_dono_pf and not solicitacao.boleto_vencimento and solicitacao.status == 'aprovada':
                corpo += f"""
                <form method="POST" action="{url_for('informar_boleto', solicitacao_id=solicitacao.id)}"
                      enctype="multipart/form-data" style="margin-top:12px;">
                    <label>Vencimento do boleto: <span style="color:red;">*</span></label><br>
                    <input type="date" name="boleto_vencimento" required style="padding:6px; margin-bottom:8px;"><br>
                    <label>Arquivo do boleto: <span style="color:red;">*</span></label><br>
                    <input type="file" name="boleto_arquivo" required style="margin-bottom:8px;"><br>
                    <button type="submit" class="btn btn-salvar" style="padding:8px 16px;">Anexar boleto</button>
                </form>
                """

            # 2) executor envia o boleto para pagamento
            if eh_executor_pf and aguardando_envio_boleto:
                corpo += f"""
                <form method="POST" action="{url_for('acao_execucao', solicitacao_id=solicitacao.id)}" style="margin-top:12px;">
                    <input type="hidden" name="acao" value="enviar_boleto_pagamento">
                    <button type="submit" class="btn" style="padding:8px 16px; background:#5b6b76; color:#fff;">
                        Enviar boleto para pagamento
                    </button>
                </form>
                """

            # 3) executor marca o boleto como pago
            if eh_executor_pf and aguardando_pagamento_boleto:
                corpo += f"""
                <form method="POST" action="{url_for('acao_execucao', solicitacao_id=solicitacao.id)}"
                      style="margin-top:12px;" onsubmit="return confirm('Confirmar que o boleto foi pago?');">
                    <input type="hidden" name="acao" value="marcar_boleto_pago">
                    <button type="submit" class="btn btn-salvar" style="padding:8px 16px;">Marcar boleto como pago</button>
                </form>
                """

            # 4) solicitante anexa a nota fiscal
            if eh_dono_pf and solicitacao.boleto_pago_em and not tem_nota_fiscal:
                corpo += f"""
                <form method="POST" action="{url_for('enviar_nota_fiscal', solicitacao_id=solicitacao.id)}"
                      enctype="multipart/form-data" style="margin-top:12px;">
                    <label>Anexar nota fiscal: <span style="color:red;">*</span></label><br>
                    <input type="file" name="nota_fiscal" required style="margin-bottom:8px;"><br>
                    <button type="submit" class="btn btn-salvar" style="padding:8px 16px;">Enviar nota fiscal</button>
                </form>
                """

            # 5) executor envia a nota fiscal para pagamento
            if eh_executor_pf and aguardando_envio_nf:
                corpo += f"""
                <form method="POST" action="{url_for('acao_execucao', solicitacao_id=solicitacao.id)}" style="margin-top:12px;">
                    <input type="hidden" name="acao" value="enviar_nf_pagamento">
                    <button type="submit" class="btn" style="padding:8px 16px; background:#5b6b76; color:#fff;">
                        Enviar nota fiscal para pagamento
                    </button>
                </form>
                """

            # 6) executor marca a nota fiscal como paga - conclui a demanda
            if eh_executor_pf and aguardando_pagamento_nf:
                corpo += f"""
                <form method="POST" action="{url_for('acao_execucao', solicitacao_id=solicitacao.id)}"
                      enctype="multipart/form-data" style="margin-top:12px;">
                    <input type="hidden" name="acao" value="marcar_nf_pago">
                    <label>Comprovante de pagamento da nota fiscal: <span style="color:red;">*</span></label><br>
                    <input type="file" name="comprovante" required style="margin-bottom:8px;"><br>
                    <button type="submit" class="btn btn-salvar" style="padding:8px 16px; background:#2e7d32; color:#fff;">
                        Marcar nota fiscal como paga e concluir
                    </button>
                </form>
                """

            corpo += "</div>"

    if solicitacao.tipo == 'rancho':
        rancho = SolicitacaoRancho.query.filter_by(solicitacao_id=solicitacao.id).first()
        if rancho:
            corpo += f"""
            <h3>Dados do rancho</h3>
            <table style="max-width:700px; margin-bottom:20px;">
                <tr><th style="width:220px;">Responsável pela retirada</th><td>{rancho.responsavel_retirada}</td></tr>
                <tr><th>Período da atividade</th><td>{rancho.periodo_atividade}</td></tr>
                <tr><th>Data para entrega</th><td>{rancho.data_entrega.strftime('%d/%m/%Y')}</td></tr>
                <tr><th>Local de entrega</th><td>{rancho.local_entrega}</td></tr>
                <tr><th>Nº de pessoas</th><td>{rancho.num_pessoas}</td></tr>
                <tr><th>Nº de dias</th><td>{rancho.num_dias}</td></tr>
                <tr><th>Refeições fornecidas</th><td>{
                    {'todas': 'Café da manhã, almoço e jantar', 'cafe': 'Somente café da manhã',
                     'almoco': 'Somente almoço', 'jantar': 'Somente jantar'
                    }.get(rancho.tipo_refeicao, 'Café da manhã, almoço e jantar')
                }</td></tr>
                <tr><th>Carne em bifes (kg)</th><td>{float(rancho.carne_bifes or 0):.0f}</td></tr>
                <tr><th>Carne picada de panela (kg)</th><td>{float(rancho.carne_picada or 0):.0f}</td></tr>
                <tr><th>Carne com osso (kg)</th><td>{float(rancho.carne_osso or 0):.0f}</td></tr>
                <tr><th>Água Mineral 20L (garrafões)</th><td>{rancho.agua_mineral_20l or 0}</td></tr>
                <tr><th>Justificativa</th><td>{rancho.justificativa or '-'}</td></tr>
                <tr><th>Observação</th><td>{rancho.observacao or '-'}</td></tr>
            </table>
            """

        itens = ItemSolicitacaoRancho.query.filter_by(solicitacao_id=solicitacao.id).order_by(
            ItemSolicitacaoRancho.categoria, ItemSolicitacaoRancho.nome_item
        ).all()

        editavel = pode_editar_itens() and solicitacao.status in ('pendente_analise', 'pendente_aprovacao')

        linhas_itens = ''
        categoria_atual = None
        for item in itens:
            if item.categoria != categoria_atual:
                categoria_atual = item.categoria
                linhas_itens += f'<tr><td colspan="6" style="background:#e8eef3; font-weight:bold;">{categoria_atual}</td></tr>'

            acao = '-'
            if editavel:
                acao = f"""
                <div style="display:flex; gap:5px; align-items:center; justify-content:center;">
                    <form method="POST" action="{url_for('editar_item_rancho', solicitacao_id=solicitacao.id)}"
                          style="display:flex; gap:3px;">
                        <input type="hidden" name="item_id" value="{item.id}">
                        <input type="number" step="1" min="0" name="quantidade"
                               value="{float(item.quantidade or 0):.0f}"
                               style="width:60px; padding:3px; font-size:12px;">
                        <button type="submit" class="btn-atalho" style="padding:3px 8px; font-size:11px;">Salvar</button>
                    </form>
                    <form method="POST" action="{url_for('detalhe_remover_item_rancho', solicitacao_id=solicitacao.id, item_id=item.id)}"
                          onsubmit="return confirm('Remover o item {item.nome_item} desta solicitação?');">
                        <button type="submit" class="btn btn-excluir" style="padding:3px 8px; font-size:11px;">Remover</button>
                    </form>
                </div>
                """

            qtd_final = float(item.quantidade or 0)
            if item.quantidade_calculada is not None:
                qtd_calc = float(item.quantidade_calculada)
                if qtd_final > qtd_calc:
                    coluna_calculada = (f'<span style="color:#666;">{qtd_calc:.0f}</span>'
                                        f'<br><span style="color:#b35c00; font-weight:bold; font-size:10.5px;">'
                                        f'&#8593; ajustado p/ mais</span>')
                elif qtd_final < qtd_calc:
                    coluna_calculada = (f'<span style="color:#666;">{qtd_calc:.0f}</span>'
                                        f'<br><span style="color:#2b5876; font-weight:bold; font-size:10.5px;">'
                                        f'&#8595; ajustado p/ menos</span>')
                else:
                    coluna_calculada = f'<span style="color:#2e7d32;">{qtd_calc:.0f} (mantido)</span>'
            else:
                coluna_calculada = '<span style="color:#999;">-</span>'

            linhas_itens += f"""
            <tr>
                <td style="font-size:12px;">{item.nome_item}</td>
                <td style="text-align:center; font-size:11px;">{item.unidade or '-'}</td>
                <td style="text-align:center; font-size:11px;">{coluna_calculada}</td>
                <td style="text-align:center; font-weight:bold;">{qtd_final:.0f}</td>
                <td style="text-align:right;">R$ {float(item.valor_total_item or 0):.2f}</td>
                <td style="text-align:center;">{acao}</td>
            </tr>
            """

        if not linhas_itens:
            linhas_itens = '<tr><td colspan="6">Nenhum item nesta solicitação.</td></tr>'

        aviso = ''
        if editavel:
            aviso = """
            <div style="font-size:12px; color:#a00; margin-bottom:8px;">
                Ao remover um item, o valor total da solicitação é recalculado automaticamente.
                Apenas os itens que permanecerem na lista serão comprados pelo Executor.
            </div>
            """

        aviso_justificativa_aumento = ''
        if rancho and rancho.justificativa_aumento:
            aviso_justificativa_aumento = f"""
            <div class="bloco" style="border-left:4px solid #b35c00; background:#fff8ec; max-width:850px; margin-bottom:14px;">
                <strong style="color:#b35c00;">O solicitante aumentou a quantidade de um ou mais itens acima do calculado pelo sistema. Justificativa:</strong>
                <div style="font-size:13px; margin-top:6px; white-space:pre-wrap;">{rancho.justificativa_aumento}</div>
            </div>
            """

        corpo += f"""
        <h3>Itens a comprar</h3>
        {aviso_justificativa_aumento}
        <div style="margin-bottom:12px;">
            <a href="{url_for('lista_compras_rancho', solicitacao_id=solicitacao.id)}" target="_blank"
               class="btn btn-salvar" style="text-decoration:none; display:inline-block; padding:9px 16px;">
                Gerar lista de compras (PDF)
            </a>
            <span style="font-size:11px; color:#666; margin-left:8px;">
                Abre em nova aba, pronta para imprimir ou salvar em PDF.
            </span>
        </div>
        {aviso}
        <table style="max-width:850px;">
            <tr>
                <th>Item</th><th style="width:70px;">Unid.</th>
                <th style="width:100px;">Qtd. calculada<br><span style="font-weight:normal; font-size:10px;">(sistema/POF)</span></th>
                <th style="width:80px;">Qtd. final</th>
                <th style="width:110px;">Subtotal</th><th style="width:110px;">Ações</th>
            </tr>
            {linhas_itens}
        </table>
        <div style="font-size:11px; color:#888; margin-top:6px; max-width:850px;">
            "Qtd. calculada" é a sugestão automática do sistema, pelo fator de consumo (POF/IBGE)
            multiplicado por pessoas e dias. "Qtd. final" é o que efetivamente será solicitado.
        </div>
        """

    if solicitacao.tipo == 'seguro':
        seguro = SolicitacaoSeguro.query.filter_by(solicitacao_id=solicitacao.id).first()
        if seguro:
            corpo += f"""
            <h3>Dados do deslocamento</h3>
            <table style="max-width:700px; margin-bottom:20px;">
                <tr><th style="width:260px;">Quantidade de pessoas</th><td>{seguro.quantidade_pessoas}</td></tr>
                <tr><th>Data de saída do local de origem</th><td>{seguro.data_saida.strftime('%d/%m/%Y')}</td></tr>
                <tr><th>Data de retorno ao local de chegada</th><td>{seguro.data_retorno.strftime('%d/%m/%Y')}</td></tr>
                <tr><th>Local de origem</th><td>{seguro.local_origem}</td></tr>
                <tr><th>Percurso / Pontos de parada</th><td>{seguro.percurso}</td></tr>
                <tr><th>Local de retorno</th><td>{seguro.local_retorno}</td></tr>
                <tr><th>Tipo de transporte</th><td>{seguro.tipo_transporte}</td></tr>
                <tr><th>Distância estimada</th><td>{f'{float(seguro.km_estimado or 0):.0f} km' + (' <span style="color:#c0392b; font-weight:bold;">(abaixo do mínimo de ' + str(KM_MINIMO_SEGURO) + ' km)</span>' if float(seguro.km_estimado or 0) < KM_MINIMO_SEGURO else '')}</td></tr>
                <tr><th>Observação</th><td>{seguro.observacao or '-'}</td></tr>
            </table>
            """

        participantes = ParticipanteSeguro.query.filter_by(solicitacao_id=solicitacao.id).order_by(
            ParticipanteSeguro.nome_completo
        ).all()

        linhas_part = ''
        for p in participantes:
            linhas_part += f"""
            <tr>
                <td style="font-size:12px;">{p.nome_completo}</td>
                <td style="font-size:12px;">{p.data_nascimento.strftime('%d/%m/%Y')}</td>
                <td style="font-size:12px;">{p.cpf}</td>
                <td style="font-size:12px;">{p.rg or '-'}</td>
                <td style="font-size:12px;">{p.email}</td>
                <td style="font-size:12px;">({p.ddd}) {p.telefone}</td>
                <td style="font-size:12px;">{p.logradouro}, {p.numero} - {p.bairro} - {p.cidade}/{p.uf} - CEP {p.cep}</td>
            </tr>
            """

        if not linhas_part:
            linhas_part = '<tr><td colspan="7">Nenhum participante cadastrado.</td></tr>'

        corpo += f"""
        <h3>Participantes do seguro de vida</h3>
        <table style="max-width:1100px;">
            <tr>
                <th>Nome completo</th><th>Nascimento</th><th>CPF</th><th>RG</th>
                <th>E-mail</th><th>Telefone</th><th>Endereço</th>
            </tr>
            {linhas_part}
        </table>
        <div style="font-size:11px; color:#888; margin-top:6px;">
            Documentos anexados por participante (RG/CPF) aparecem na seção "Anexos" abaixo,
            identificados pelo nome da pessoa.
        </div>
        """

    if solicitacao.tipo == 'bolsa':
        bolsistas = BolsistaSolicitacao.query.filter_by(solicitacao_id=solicitacao.id).all()

        linhas_bolsa = ''
        for indice, b in enumerate(bolsistas, start=1):
            linhas_bolsa += f"""
            <tr>
                <td style="text-align:center;">{indice}</td>
                <td style="font-size:12px;">{b.nome_bolsista}</td>
                <td style="font-size:12px;">{b.titulo_plano_trabalho}</td>
                <td style="font-size:12px;">{b.projeto_relacionado}</td>
                <td style="font-size:12px;">{b.tipo_bolsa}</td>
                <td style="font-size:12px;">{b.mes_inicio} a {b.mes_fim}</td>
                <td style="text-align:center;">{b.duracao_meses}</td>
                <td style="text-align:right;">R$ {float(b.valor_mensal or 0):.2f}</td>
                <td style="text-align:right;"><strong>R$ {float(b.valor_total_bolsa or 0):.2f}</strong></td>
                <td style="text-align:center;">{'Sim' if b.precisa_cracha else 'Não'}</td>
            </tr>
            """

        if not linhas_bolsa:
            linhas_bolsa = '<tr><td colspan="10">Nenhum bolsista cadastrado.</td></tr>'

        corpo += f"""
        <h3>Bolsistas</h3>
        <table style="max-width:1200px;">
            <tr>
                <th>Item</th><th>Nome do bolsista</th><th>Plano de Trabalho</th><th>Projeto</th>
                <th>Tipo de Bolsa</th><th>Período</th><th>Meses</th>
                <th>Valor mensal</th><th>Valor total</th><th>Crachá</th>
            </tr>
            {linhas_bolsa}
        </table>
        """

    # comprovante de pagamento pendente - so aparece quando a solicitacao ja
    # foi concluida sem anexo
    if solicitacao.status in ('paga', 'comprado'):
        tipo_comp = 'comprovante_compra' if solicitacao.status == 'comprado' else 'comprovante_pagamento'
        tem_comprovante = Anexo.query.filter_by(
            solicitacao_id=solicitacao.id, tipo_anexo=tipo_comp).count() > 0

        eh_dono_comp = solicitacao.solicitante_id == current_user.id
        eh_executor_comp = (current_user.is_organizador
                            or solicitacao.responsavel_encaminhamento_id == current_user.id
                            or current_user.perfil == 'comprador')

        if not tem_comprovante and eh_dono_comp and not solicitacao.comprovante_solicitado_em:
            corpo += f"""
            <div class="bloco" style="border-left:4px solid #5b6b76; max-width:700px; margin-bottom:14px;">
                <strong>Sem comprovante de pagamento anexado.</strong>
                <div style="font-size:11px; color:#888; margin:6px 0 10px;">
                    Se precisar do comprovante, você pode solicitá-lo ao responsável pela solicitação.
                </div>
                <form method="POST" action="{url_for('solicitar_comprovante', solicitacao_id=solicitacao.id)}">
                    <button type="submit" class="btn-atalho">Solicitar comprovante</button>
                </form>
            </div>
            """
        elif not tem_comprovante and solicitacao.comprovante_solicitado_em and eh_dono_comp:
            corpo += f"""
            <div class="bloco" style="border-left:4px solid #b35c00; background:#fff8ec; max-width:700px; margin-bottom:14px;">
                <strong style="color:#b35c00;">Comprovante solicitado em {solicitacao.comprovante_solicitado_em.strftime('%d/%m/%Y %H:%M')}.</strong>
                <div style="font-size:11px; color:#666; margin-top:4px;">Aguardando o responsável anexar.</div>
            </div>
            """

        if not tem_comprovante and solicitacao.comprovante_solicitado_em and eh_executor_comp:
            corpo += f"""
            <div class="bloco" style="border-left:4px solid #b35c00; background:#fff8ec; max-width:700px; margin-bottom:14px;">
                <strong style="color:#b35c00;">O solicitante pediu o comprovante de pagamento.</strong>
                <form method="POST" action="{url_for('anexar_comprovante_posterior', solicitacao_id=solicitacao.id)}"
                      enctype="multipart/form-data" style="margin-top:10px;">
                    <input type="file" name="comprovante" required style="margin-bottom:8px;"><br>
                    <button type="submit" class="btn btn-salvar">Anexar comprovante</button>
                </form>
            </div>
            """
        elif not tem_comprovante and eh_executor_comp:
            corpo += f"""
            <div class="bloco" style="max-width:700px; margin-bottom:14px;">
                <form method="POST" action="{url_for('anexar_comprovante_posterior', solicitacao_id=solicitacao.id)}"
                      enctype="multipart/form-data">
                    <label style="font-size:12px;">Anexar comprovante de pagamento (opcional):</label><br>
                    <input type="file" name="comprovante" style="margin:6px 0;"><br>
                    <button type="submit" class="btn-atalho">Anexar</button>
                </form>
            </div>
            """

    # anexos
    anexos = Anexo.query.filter_by(solicitacao_id=solicitacao.id).all()
    if anexos:
        pode_remover_anexo = (
            solicitacao.solicitante_id == current_user.id
            or current_user.perfil in ('analista', 'aprovador', 'comprador')
            or current_user.is_organizador
        )

        # cor e texto do selo por tipo de anexo - um único lugar para manter
        SELOS_ANEXO = {
            'comprovante_pagamento': ('Comprovante de pagamento', '#2e7d32'),
            'comprovante_compra': ('Nota fiscal / comprovante da compra', '#2e7d32'),
            'prestacao_contas': ('Relatório de prestação de contas', '#37784D'),
            'boleto_arrecadacao': ('Boleto de arrecadação municipal', '#2b5876'),
            'nota_fiscal': ('Nota fiscal', '#2b5876'),
            'documento_pessoal': ('Documento pessoal (RG/CPF)', '#6a1b9a'),
        }

        linhas_anexos = ''
        for a in anexos:
            botao_remover = ''
            if pode_remover_anexo:
                botao_remover = (
                    f'<form method="POST" action="{url_for("remover_anexo", anexo_id=a.id)}" '
                    f'style="display:inline;" '
                    f'onsubmit="return confirm(\'Remover o anexo {a.nome_arquivo}?\');">'
                    f'<button type="submit" class="btn btn-excluir">Remover</button></form>'
                )

            selo = ''
            if a.tipo_anexo in SELOS_ANEXO:
                texto_selo, cor_selo = SELOS_ANEXO[a.tipo_anexo]
                selo = (f'<div style="margin-top:3px;"><span style="display:inline-block; '
                       f'padding:1px 7px; border-radius:3px; font-size:10px; font-weight:600; '
                       f'background:{cor_selo}18; color:{cor_selo};">{texto_selo}</span></div>')

            linhas_anexos += f"""
            <tr>
                <td style="font-size:12.5px; max-width:280px; overflow-wrap:break-word;">
                    {a.nome_arquivo}
                    {selo}
                </td>
                <td style="font-size:11px; color:#666; white-space:nowrap;">{a.data_upload.strftime('%d/%m/%Y %H:%M')}</td>
                <td style="white-space:nowrap;">
                    <a href="{url_for('baixar_anexo', anexo_id=a.id)}" class="btn-atalho">Baixar</a>
                    {botao_remover}
                </td>
            </tr>
            """
        corpo += f"""
        <h3>Anexos</h3>
        <table style="max-width:800px;">
            <tr><th>Arquivo</th><th style="width:150px;">Enviado em</th><th style="width:170px;">Ações</th></tr>
            {linhas_anexos}
        </table>
        """

    # histórico de pareceres
    pareceres = []
    if solicitacao.ressalva_analista:
        pareceres.append(('Ressalva do Analista', solicitacao.ressalva_analista, '#2b5876'))
    if solicitacao.ressalva_aprovador:
        pareceres.append(('Ressalva do Aprovador', solicitacao.ressalva_aprovador, '#2b5876'))
    if solicitacao.motivo_devolucao and solicitacao.status == 'devolvida_ajuste':
        pareceres.append(('Motivo da devolução', solicitacao.motivo_devolucao, '#b35c00'))
    if solicitacao.motivo_ajuste_dados:
        pareceres.append(('Correção solicitada pelo Executor', solicitacao.motivo_ajuste_dados, '#b35c00'))
    if solicitacao.motivo_reprovacao:
        rotulo = f'Reprovada por {solicitacao.reprovada_por}' if solicitacao.reprovada_por else 'Motivo da reprovação'
        pareceres.append((rotulo, solicitacao.motivo_reprovacao, '#c0392b'))
    if solicitacao.aviso_conclusao:
        pareceres.append(('Aviso ao solicitante', solicitacao.aviso_conclusao, '#2e7d32'))
    if solicitacao.alerta_prestacao:
        pareceres.append(('Alerta de prestação de contas', solicitacao.alerta_prestacao, '#c0392b'))

    if pareceres:
        blocos_parecer = ''
        for titulo_p, texto_p, cor in pareceres:
            blocos_parecer += f"""
            <div class="bloco" style="border-left:4px solid {cor};">
                <strong style="color:{cor}; font-size:13px;">{titulo_p}</strong>
                <div style="font-size:13px; margin-top:6px; white-space:pre-wrap;">{texto_p}</div>
            </div>
            """
        corpo += f'<h3>Pareceres</h3>{blocos_parecer}'

    # histórico da solicitação, no formato de fluxo de aprovação
    if eh_dono or eh_fluxo:
        historico = RegistroAuditoria.query.filter_by(solicitacao_id=solicitacao.id).order_by(
            RegistroAuditoria.data_hora.desc()).all()

        rotulos_perfil = {
            'solicitante': 'Solicitante', 'analista': 'Analista',
            'aprovador': 'Aprovador', 'comprador': 'Comprador/Executor',
        }

        cores_acao = {
            'aprovou': '#2e7d32', 'aprovou_prestacao': '#2e7d32',
            'marcou_paga': '#2e7d32', 'marcou_comprado': '#2e7d32',
            'reprovou_analise': '#c0392b', 'reprovou_aprovacao': '#c0392b',
            'devolveu_analise': '#b35c00', 'devolveu_aprovacao': '#b35c00',
            'devolveu_executor': '#b35c00', 'devolveu_prestacao': '#b35c00',
        }

        if historico:
            linhas_hist = ''
            for registro in historico:
                perfil_txt = rotulos_perfil.get(registro.usuario_perfil, registro.usuario_perfil or '-')
                cor_acao = cores_acao.get(registro.acao, '#1f2d26')
                linhas_hist += f"""
                <tr>
                    <td style="font-size:12px; white-space:nowrap;">
                        {registro.data_hora.strftime('%d/%m/%Y')}<br>
                        <span style="color:#666;">{registro.data_hora.strftime('%H:%M:%S')}</span>
                    </td>
                    <td style="font-size:12px;">{perfil_txt}</td>
                    <td style="font-size:12px;">{registro.usuario_nome or '-'}</td>
                    <td style="font-size:12px; font-weight:600; color:{cor_acao};">
                        {ACOES_AUDITORIA.get(registro.acao, registro.acao)}</td>
                    <td style="font-size:11.5px; color:#555;">{registro.detalhe or '-'}</td>
                </tr>
                """

            corpo += f"""
            <h3>Fluxo de aprovação</h3>
            <table style="max-width:1050px;">
                <tr>
                    <th style="width:110px;">Quando</th><th style="width:150px;">Perfil</th>
                    <th style="width:190px;">Quem</th><th style="width:230px;">Ação</th>
                    <th>Justificativa / Detalhe</th>
                </tr>
                {linhas_hist}
            </table>
            """
        else:
            corpo += """
            <h3>Fluxo de aprovação</h3>
            <div class="bloco" style="max-width:1050px; color:#666; font-size:12.5px;">
                Nenhuma movimentação registrada para esta solicitação.
                O histórico passou a ser gravado a partir da ativação da auditoria, por isso
                solicitações anteriores a essa data não têm registro.
            </div>
            """

        # bloco específico das devoluções para correção de dados
        pendencias = [r for r in historico if r.acao in ('devolveu_executor', 'corrigiu')]
        if pendencias:
            linhas_pend = ''
            for registro in sorted(pendencias, key=lambda r: r.data_hora):
                if registro.acao == 'devolveu_executor':
                    situacao = '<span style="color:#b35c00; font-weight:bold;">Pendência aberta</span>'
                else:
                    situacao = '<span style="color:#2e7d32; font-weight:bold;">Pendência resolvida</span>'

                linhas_pend += f"""
                <tr>
                    <td style="font-size:12px; white-space:nowrap;">
                        {registro.data_hora.strftime('%d/%m/%Y %H:%M')}</td>
                    <td style="font-size:12px;">{registro.usuario_nome or '-'}</td>
                    <td>{situacao}</td>
                    <td style="font-size:11.5px; color:#555;">{registro.detalhe or '-'}</td>
                </tr>
                """

            corpo += f"""
            <h3>Pendências de correção de dados</h3>
            <table style="max-width:1050px;">
                <tr><th style="width:145px;">Quando</th><th style="width:200px;">Quem</th>
                    <th style="width:180px;">Situação</th><th>Observação</th></tr>
                {linhas_pend}
            </table>
            """

    # painel de decisão
    painel = ''
    eh_analista = current_user.perfil == 'analista' or current_user.is_organizador
    eh_aprovador = current_user.perfil == 'aprovador' or current_user.is_organizador

    if solicitacao.status == 'pendente_analise' and eh_analista:
        campo_rubrica = ''
        if solicitacao.tipo == 'bolsa':
            campo_rubrica = f"""
            <label>Rubrica: <span style="color:red;">*</span></label><br>
            <input type="text" name="rubrica" value="{solicitacao.rubrica or ''}" style="padding:6px; width:280px; margin-bottom:12px;"><br>
            """

        # Bolsa não tem um Executor interno: o encaminhamento após a aprovação
        # é externo, para o CTC (Comitê Técnico Científico), que não possui
        # conta no sistema. Por isso, só neste módulo, pede-se um e-mail de
        # contato em vez de escolher um responsável entre os usuários.
        if solicitacao.tipo == 'bolsa':
            campo_encaminhamento = f"""
            <label>E-mail do CTC para encaminhamento: <span style="color:red;">*</span></label><br>
            <input type="email" name="email_ctc" value="{solicitacao.email_ctc or ''}"
                   placeholder="ctc@exemplo.org" style="padding:6px; width:340px; margin-bottom:4px;"><br>
            <div style="font-size:11px; color:#888; margin-bottom:12px;">
                O Comitê Técnico Científico não possui acesso ao sistema. Quando o Aprovador aprovar
                esta solicitação, um e-mail com um PDF do detalhamento da bolsa será enviado
                automaticamente a este endereço, autorizando o encaminhamento para a efetivação.
            </div>
            """
        else:
            campo_encaminhamento = f"""
            <label>Responsável pelo encaminhamento da demanda: <span style="color:red;">*</span></label><br>
            <select name="responsavel_encaminhamento" style="padding:6px; width:340px; margin-bottom:4px;">
                <option value="">Selecione o responsável</option>
                {montar_opcoes_executores(solicitacao.responsavel_encaminhamento_id)}
            </select>
            <div style="font-size:11px; color:#888; margin-bottom:12px;">
                Somente usuários com perfil <strong>Comprador/Executor</strong> aparecem nesta lista.
                A pessoa selecionada é notificada por e-mail e dentro do sistema quando o Aprovador aprovar,
                e passa a acompanhar o encaminhamento até a conclusão.
            </div>
            """

        painel = f"""
        <h3 style="margin-top:30px;">Parecer da Análise</h3>
        <form method="POST" action="{url_for('acao_analise', solicitacao_id=solicitacao.id)}" id="form-decisao"
              class="bloco" style="max-width:750px;">
            <label>Nº Lote de Aprovação: <span style="color:red;">*</span></label><br>
            <input type="text" name="lote_aprovacao" value="{solicitacao.lote_aprovacao or ''}" style="padding:6px; width:280px; margin-bottom:12px;"><br>

            <label>Convênio: <span style="color:red;">*</span></label><br>
            <select name="convenio" style="padding:6px; width:280px; margin-bottom:12px;">
                <option value="">Selecione</option>
                {montar_opcoes(CONVENIOS, solicitacao.convenio)}
            </select><br>

            {campo_rubrica}

{campo_encaminhamento}

            <label>Ressalva / observação da análise (opcional):</label><br>
            <textarea name="ressalva" rows="3" style="width:100%; padding:6px; margin-bottom:12px;">{solicitacao.ressalva_analista or ''}</textarea><br>

            <label>Justificativa (obrigatória para reprovar ou devolver):</label><br>
            <textarea name="justificativa" id="campo-justificativa" rows="3" style="width:100%; padding:6px; margin-bottom:15px;"></textarea><br>

            <button type="submit" name="acao" value="enviar" class="btn btn-salvar" style="padding:10px 18px;">Enviar para Aprovador</button>
            <button type="submit" name="acao" value="devolver" class="btn" style="padding:10px 18px; background:#b35c00; color:white;">Devolver para ajuste</button>
            <button type="submit" name="acao" value="reprovar" class="btn btn-excluir" style="padding:10px 18px;">Reprovar</button>
        </form>
        """

    elif solicitacao.status == 'pendente_aprovacao' and eh_aprovador:
        painel = f"""
        <h3 style="margin-top:30px;">Decisão do Aprovador</h3>
        <form method="POST" action="{url_for('acao_aprovacao', solicitacao_id=solicitacao.id)}" id="form-decisao"
              class="bloco" style="max-width:750px;">
            <label>Convênio: <span style="color:red;">*</span></label><br>
            <select name="convenio" required style="padding:6px; margin-bottom:4px; width:250px;">
                <option value="">Selecione</option>
                {montar_opcoes(CONVENIOS, solicitacao.convenio)}
            </select><br>
            <div style="font-size:11px; color:#888; margin-bottom:12px;">
                Definido pelo Analista na triagem. O Aprovador pode alterar caso a despesa deva
                ser custeada por outro convênio.
            </div>

            <label>Ressalva / observação do aprovador (opcional):</label><br>
            <textarea name="ressalva" rows="3" style="width:100%; padding:6px; margin-bottom:12px;">{solicitacao.ressalva_aprovador or ''}</textarea><br>

            <label>Justificativa (obrigatória para reprovar ou devolver):</label><br>
            <textarea name="justificativa" id="campo-justificativa" rows="3" style="width:100%; padding:6px; margin-bottom:15px;"></textarea><br>

            <button type="submit" name="acao" value="aprovar" class="btn btn-salvar" style="padding:10px 18px;">Aprovar</button>
            <button type="submit" name="acao" value="devolver" class="btn" style="padding:10px 18px; background:#b35c00; color:white;">Devolver para ajuste</button>
            <button type="submit" name="acao" value="reprovar" class="btn btn-excluir" style="padding:10px 18px;">Reprovar</button>
        </form>
        """

    # Serviço Externo PF tem fluxo próprio (boleto + nota fiscal), sem a
    # etapa padrão de "definir prazo" - todas as ações ficam no card
    # dedicado, mais abaixo no detalhe da solicitação.
    if (solicitacao.status in STATUS_EM_ANDAMENTO and pode_executar(solicitacao)
            and solicitacao.tipo != 'servico_externo_pf'):
        prazo_atual = solicitacao.prazo_encaminhamento.strftime('%Y-%m-%d') if solicitacao.prazo_encaminhamento else ''

        if solicitacao.status == 'aprovada':
            bloco_acao = f"""
            <label>Prazo para atendimento da demanda: <span style="color:red;">*</span></label><br>
            <input type="date" name="prazo_encaminhamento" value="{prazo_atual}" style="padding:6px; margin-bottom:12px;"><br>
            <button type="submit" name="acao" value="definir_prazo" class="btn btn-salvar" style="padding:10px 18px;">
                Definir prazo e iniciar execução
            </button>
            """
        elif solicitacao.status == 'em_execucao':
            if fluxo_do_tipo(solicitacao.tipo) == 'compra':
                proxima = """
            <button type="submit" name="acao" value="em_compra" class="btn" style="padding:10px 18px; background:#5b6b76; color:white;">
                Colocar em compra
            </button>
            """
            else:
                proxima = """
            <button type="submit" name="acao" value="enviar_pagamento" class="btn" style="padding:10px 18px; background:#5b6b76; color:white;">
                Enviar para pagamento
            </button>
            """

            bloco_acao = f"""
            <label>Prazo para atendimento da demanda:</label><br>
            <input type="date" name="prazo_encaminhamento" value="{prazo_atual}" style="padding:6px; margin-bottom:12px;"><br>
            <button type="submit" name="acao" value="definir_prazo" class="btn btn-atalho" style="padding:8px 14px;">
                Atualizar prazo
            </button>
            {proxima}
            """
        elif solicitacao.status == 'em_compra':
            bloco_acao = f"""
            <label>Valor real da compra (R$): <span style="color:red;">*</span></label><br>
            <input type="number" step="0.01" min="0.01" name="valor_real" required
                   value="{float(solicitacao.valor_real or solicitacao.valor_total or 0):.2f}"
                   style="padding:7px; width:180px; margin-bottom:6px;"><br>
            <div style="font-size:11px; color:#666; margin-bottom:12px;">
                Valor estimado na solicitação: <strong>{moeda(solicitacao.valor_total)}</strong>.
                Informe o valor efetivamente pago pela compra.
            </div>

            <label>Nota fiscal / comprovante da compra (opcional):</label><br>
            <input type="file" name="comprovante" accept=".pdf,.jpg,.jpeg,.png" style="margin-bottom:12px;"><br>
            <button type="submit" name="acao" value="marcar_comprado" class="btn" style="padding:10px 18px; background:#2e7d32; color:white;">
                Marcar como comprado
            </button>
            """
        else:
            bloco_acao = """
            <label>Comprovante de pagamento (opcional):</label><br>
            <input type="file" name="comprovante" accept=".pdf,.jpg,.jpeg,.png" style="margin-bottom:12px;"><br>
            <div style="font-size:11px; color:#888; margin-bottom:10px;">
                Não é obrigatório anexar agora. Se o solicitante pedir depois, você pode anexar
                a qualquer momento pelo aviso que aparecerá aqui no detalhe.
            </div>
            <button type="submit" name="acao" value="marcar_paga" class="btn" style="padding:10px 18px; background:#2e7d32; color:white;">
                Marcar como paga
            </button>
            """

        painel += f"""
        <h3 style="margin-top:30px;">Encaminhamento da demanda</h3>
        <form method="POST" action="{url_for('acao_execucao', solicitacao_id=solicitacao.id)}"
              enctype="multipart/form-data" class="bloco" style="max-width:750px;">
            <div style="font-size:12px; color:#666; margin-bottom:12px;">
                Status atual: <strong>{status_label}</strong>. Cada mudança notifica o solicitante por e-mail.
            </div>
            {bloco_acao}
        </form>

        <div class="bloco" style="max-width:750px; border-left:4px solid #b35c00;">
            <strong style="font-size:13px; color:#b35c00;">Precisa de correção do solicitante?</strong>
            <div style="font-size:12px; color:#666; margin:6px 0 12px;">
                Use quando houver divergência nos dados bancários, no CPF ou em qualquer informação
                que impeça o pagamento. A solicitação volta ao solicitante e, após a correção,
                <strong>retorna direto para você</strong> — sem repetir análise e aprovação.
            </div>
            <form method="POST" action="{url_for('acao_execucao', solicitacao_id=solicitacao.id)}" id="form-devolver-solicitante">
                <label>O que precisa ser corrigido: <span style="color:red;">*</span></label><br>
                <textarea name="motivo_ajuste" id="motivo-ajuste" rows="3" required
                          placeholder="Ex: conta bancária divergente - o banco recusou o pagamento."
                          style="width:100%; padding:7px; margin-bottom:12px;"></textarea><br>
                <button type="submit" name="acao" value="devolver_solicitante" class="btn"
                        style="padding:10px 18px; background:#b35c00; color:#fff;">
                    Devolver ao solicitante para correção
                </button>
            </form>
        </div>
        """

    if painel:
        painel += """
        <script>
        var formDecisao = document.getElementById('form-decisao');
        if (formDecisao) formDecisao.addEventListener('submit', function(evento) {
            var acao = evento.submitter ? evento.submitter.value : '';
            var justificativa = document.getElementById('campo-justificativa').value.trim();

            if ((acao === 'reprovar' || acao === 'devolver') && justificativa === '') {
                evento.preventDefault();
                alert('Preencha a justificativa para reprovar ou devolver a solicitação.');
                return;
            }
            if (acao === 'reprovar' && !confirm('Confirma a REPROVAÇÃO desta solicitação?')) {
                evento.preventDefault();
            }
        });
        </script>
        """

    botao_corrigir = ''
    if (solicitacao.status in ('devolvida_ajuste', 'ajuste_dados')
            and (solicitacao.solicitante_id == current_user.id or current_user.is_organizador)):
        botao_corrigir = (
            f'<a href="{url_for("corrigir_solicitacao", solicitacao_id=solicitacao.id)}" '
            f'class="btn btn-salvar" style="text-decoration:none; display:inline-block; '
            f'padding:11px 20px; background:#b35c00; margin-right:10px;">Corrigir e reenviar</a>'
        )

    conteudo = cabecalho + corpo + painel + f"""
    <div style="margin-top:22px;">
        {botao_corrigir}
        <a href="javascript:history.back()" class="btn-atalho">Voltar</a>
    </div>
    """
    return render_pagina('Detalhe da Solicitação', conteudo)


@app.route('/solicitacao/<int:solicitacao_id>/alimentacao/editar', methods=['POST'])
@login_required
def editar_quantidade_alimentacao(solicitacao_id):
    if not pode_editar_itens():
        abort(403)

    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)

    if solicitacao.tipo != 'alimentacao':
        abort(404)

    if solicitacao.status not in ('pendente_analise', 'pendente_aprovacao'):
        flash('Só é possível ajustar a quantidade enquanto a solicitação está em análise ou aguardando aprovação.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    alimentacao = SolicitacaoAlimentacao.query.filter_by(solicitacao_id=solicitacao.id).first()
    if not alimentacao:
        abort(404)

    try:
        nova_quantidade = int(request.form.get('quantidade_pessoas') or 0)
    except ValueError:
        nova_quantidade = 0

    if nova_quantidade < 1:
        flash('Informe uma quantidade de pessoas válida (mínimo 1).')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    quantidade_anterior = alimentacao.quantidade_pessoas
    custo_unitario = float(alimentacao.custo_unitario or 0)

    alimentacao.quantidade_pessoas = nova_quantidade
    alimentacao.custo_total = nova_quantidade * custo_unitario
    solicitacao.valor_total = alimentacao.custo_total

    registro = (
        f'Quantidade de pessoas ajustada de {quantidade_anterior} para {nova_quantidade} '
        f'por {current_user.nome}. Novo custo total: R$ {alimentacao.custo_total:.2f}.'
    )
    if current_user.perfil == 'aprovador':
        solicitacao.ressalva_aprovador = ((solicitacao.ressalva_aprovador or '') + '\n' + registro).strip()
    else:
        solicitacao.ressalva_analista = ((solicitacao.ressalva_analista or '') + '\n' + registro).strip()

    registrar_auditoria('alterou_quantidade', solicitacao, registro)
    db.session.commit()

    notificar_solicitante(
        solicitacao,
        'Ajuste na sua solicitação de Alimentação - SIGAD Carajás',
        f'Olá, {solicitacao.solicitante.nome}.\n\n'
        f'A quantidade de pessoas da sua solicitação de Alimentação, protocolo {protocolo(solicitacao)}, '
        f'foi ajustada de {quantidade_anterior} para {nova_quantidade}.\n\n'
        f'Novo custo total: R$ {alimentacao.custo_total:.2f}',
    )

    flash('Quantidade ajustada e valor recalculado.', 'sucesso')
    return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))


@app.route('/solicitacao/<int:solicitacao_id>/rancho/editar-item', methods=['POST'])
@login_required
def editar_item_rancho(solicitacao_id):
    """Analista e Aprovador podem aumentar ou diminuir a quantidade de um item
    do rancho enquanto a solicitação está em análise ou aguardando aprovação -
    sem exigir justificativa, diferente da regra que vale para o solicitante."""
    if not pode_editar_itens():
        abort(403)

    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)

    if solicitacao.tipo != 'rancho':
        abort(404)

    if solicitacao.status not in ('pendente_analise', 'pendente_aprovacao'):
        flash('Só é possível ajustar itens enquanto a solicitação está em análise ou '
              'aguardando aprovação.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    item_id = request.form.get('item_id')
    item_solicitacao = ItemSolicitacaoRancho.query.filter_by(
        id=item_id, solicitacao_id=solicitacao.id).first_or_404()

    try:
        nova_quantidade = float(request.form.get('quantidade') or 0)
    except ValueError:
        nova_quantidade = -1

    if nova_quantidade < 0:
        flash('Informe uma quantidade válida.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    quantidade_anterior = float(item_solicitacao.quantidade or 0)
    item_solicitacao.quantidade = nova_quantidade
    item_solicitacao.valor_total_item = nova_quantidade * float(item_solicitacao.valor_unitario or 0)

    restantes = ItemSolicitacaoRancho.query.filter_by(solicitacao_id=solicitacao.id).all()
    solicitacao.valor_total = sum(float(i.valor_total_item or 0) for i in restantes)

    sentido = 'aumentada' if nova_quantidade > quantidade_anterior else 'reduzida'
    registro = (
        f'Quantidade de "{item_solicitacao.nome_item}" {sentido} de {quantidade_anterior:g} '
        f'para {nova_quantidade:g} por {current_user.nome}. '
        f'Novo total da solicitação: {moeda(solicitacao.valor_total)}.'
    )
    if current_user.perfil == 'aprovador':
        solicitacao.ressalva_aprovador = ((solicitacao.ressalva_aprovador or '') + '\n' + registro).strip()
    else:
        solicitacao.ressalva_analista = ((solicitacao.ressalva_analista or '') + '\n' + registro).strip()

    registrar_auditoria('alterou_quantidade_rancho', solicitacao, registro)
    db.session.commit()

    notificar_solicitante(
        solicitacao,
        'Ajuste em item da sua solicitação de Rancho - SIGAD Carajás',
        f'Olá, {solicitacao.solicitante.nome}.\n\n'
        f'A quantidade do item "{item_solicitacao.nome_item}", na sua solicitação de Rancho, '
        f'protocolo {protocolo(solicitacao)}, foi {sentido} de {quantidade_anterior:g} para '
        f'{nova_quantidade:g}.\n\nNovo valor total da solicitação: {moeda(solicitacao.valor_total)}',
    )

    flash('Quantidade do item ajustada e valor recalculado.', 'sucesso')
    return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))


# ---------------- TESTE DE E-MAIL (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/email', methods=['GET', 'POST'])
@login_required
def configuracao_email():
    somente_organizador()

    resultado = ''

    if request.method == 'POST':
        destino = (request.form.get('destinatario') or '').strip()
        if not destino:
            flash('Informe um e-mail de destino para o teste.')
            return redirect(url_for('configuracao_email'))

        sucesso, mensagem = enviar_email(
            destino,
            'Teste de configuração - SIGAD Carajás',
            'Este é um e-mail de teste enviado pelo SIGAD Carajás.\n\n'
            'Se você recebeu esta mensagem, a configuração de envio está funcionando '
            'corretamente e as notificações do sistema serão entregues normalmente.',
        )

        if sucesso:
            resultado = (f'<div class="flash flash-ok">E-mail enviado para <strong>{destino}</strong>. '
                         f'Verifique a caixa de entrada e também a pasta de spam.</div>')
        else:
            resultado = (f'<div class="flash"><strong>Falha no envio.</strong><br>'
                         f'<span style="font-family:monospace; font-size:12px;">{mensagem}</span></div>')

    def estado(nome, ocultar=False):
        valor = os.environ.get(nome)
        if not valor:
            return ('<span style="color:#c0392b; font-weight:bold;">não definida</span>')
        if ocultar:
            return '<span style="color:#2e7d32; font-weight:bold;">definida</span>'
        return f'<span style="color:#2e7d32;">{valor}</span>'

    conteudo = f"""
    <h2>Configuração de E-mail</h2>
    <div style="font-size:12px; color:#666; margin-bottom:14px;">
        O sistema envia notificações automáticas em cada mudança de status das solicitações.
        Use esta tela para conferir a configuração e testar o envio.
    </div>

    {resultado}

    <div class="painel" style="max-width:760px;">
        <div class="titulo">Variáveis de ambiente</div>
        <div class="grade">
            <div class="campo"><div class="rotulo">EMAIL_HOST</div><div class="valor">{estado('EMAIL_HOST')}</div></div>
            <div class="campo"><div class="rotulo">EMAIL_PORT</div><div class="valor">{estado('EMAIL_PORT')}</div></div>
            <div class="campo"><div class="rotulo">EMAIL_USER</div><div class="valor">{estado('EMAIL_USER')}</div></div>
            <div class="campo"><div class="rotulo">EMAIL_PASSWORD</div><div class="valor">{estado('EMAIL_PASSWORD', ocultar=True)}</div></div>
            <div class="campo"><div class="rotulo">EMAIL_FROM</div><div class="valor">{estado('EMAIL_FROM')}</div></div>
            <div class="campo"><div class="rotulo">EMAIL_FROM_NAME</div><div class="valor">{estado('EMAIL_FROM_NAME')}</div></div>
        </div>
    </div>

    <div class="painel" style="max-width:760px;">
        <div class="titulo">Enviar e-mail de teste</div>
        <div style="padding:16px;">
            <form method="POST">
                <label>Enviar para:</label><br>
                <input type="email" name="destinatario" required value="{current_user.email}"
                       style="width:100%; max-width:420px; padding:8px; margin-bottom:12px;"><br>
                <button type="submit" class="btn btn-salvar" style="padding:10px 18px;">
                    Enviar e-mail de teste
                </button>
            </form>
            <div style="font-size:11.5px; color:#666; margin-top:12px;">
                Em caso de falha, a mensagem exata do servidor aparece acima — é ela que indica
                se o problema é senha, remetente não verificado ou porta bloqueada.
            </div>
        </div>
    </div>
    """
    return render_pagina('Configuração de E-mail', conteudo)


# ---------------- CENTRAL DE AJUDA ----------------
# Conteúdo extraído do Manual de Solicitações NGI Carajás.
AJUDA_TOPICOS = [
    {
        'id': 'fluxo',
        'titulo': 'Como funciona o fluxo das solicitações',
        'itens': [
            ('Quais são as etapas de uma solicitação?',
             'Toda solicitação percorre quatro etapas: <strong>Solicitante</strong> preenche e envia; '
             '<strong>Analista</strong> faz a triagem, confere os dados, define o lote de aprovação, o convênio '
             'e o responsável pelo encaminhamento; <strong>Aprovador</strong> analisa os valores e aprova; '
             '<strong>Comprador/Executor</strong> executa a demanda e a conclui.'),
            ('O que significa cada status?',
             '<strong>Pendente de análise</strong> — aguardando triagem.<br>'
             '<strong>Devolvida para ajuste</strong> — precisa de correção sua; use o botão "Corrigir e reenviar".<br>'
             '<strong>Pendente de aprovação</strong> — passou pela triagem, aguarda decisão.<br>'
             '<strong>Reprovada</strong> — não foi autorizada; a justificativa aparece na solicitação.<br>'
             '<strong>Aprovada</strong> — autorizada, aguardando o responsável definir o prazo.<br>'
             '<strong>Em execução</strong> — o responsável está providenciando.<br>'
             '<strong>Enviado para pagamento</strong> / <strong>Em compra</strong> — em processamento final.<br>'
             '<strong>Paga</strong> / <strong>Comprado</strong> — concluída.'),
            ('Minha solicitação foi devolvida. E agora?',
             'Vá em <strong>Minhas Solicitações</strong>, localize a linha e clique em '
             '<strong>Corrigir e reenviar</strong>. O motivo do ajuste aparece no topo da tela de correção. '
             'Ao reenviar, a solicitação volta para a análise mantendo o mesmo número de protocolo.'),
            ('O que é o número de protocolo?',
             'É o identificador único da solicitação, no formato <strong>2026.0822.00014-3</strong>: ano, '
             'mês e dia de abertura, número sequencial e um dígito verificador. Use esse número em qualquer '
             'comunicação sobre a solicitação.'),
        ],
    },
    {
        'id': 'compras',
        'titulo': 'Compras de Materiais',
        'itens': [
            ('O que preciso informar em cada item?',
             'Descrição completa, quantidade, unidade de medida e demais características relevantes. '
             'Quanto mais específica a descrição, mais rápido o processo de aquisição — especificação vaga '
             'gera divergência na cotação e atrasa a compra.'),
            ('Quando preciso anexar cotações?',
             'Para compras <strong>acima de R$ 5.000,00</strong> é obrigatória a apresentação de '
             '<strong>três cotações</strong>, anexadas junto com a solicitação. O sistema soma todos os itens '
             'e bloqueia o envio se o total ultrapassar esse valor sem os três anexos.'),
            ('Preciso colocar o link do produto?',
             'Quando a compra for <strong>online</strong>, sim — o link facilita a identificação precisa do '
             'material e evita divergências durante a cotação ou a compra. O sistema torna o campo obrigatório '
             'ao selecionar "Online" na forma de aquisição.'),
            ('De quais sites devo enviar o link?',
             'Prefira plataformas que permitem compra com CNPJ, como <strong>Mercado Livre</strong>, '
             '<strong>Magazine Luiza</strong> ou <strong>Casas Bahia</strong>.'),
            ('Posso enviar link da Amazon?',
             '<strong>Não.</strong> A Amazon não realiza vendas para CNPJ, o que inviabiliza a aquisição '
             'institucional. Envie o link de outra plataforma.'),
        ],
    },
    {
        'id': 'alimentacao',
        'titulo': 'Alimentação',
        'itens': [
            ('Quando devo usar a solicitação de alimentação?',
             'Quando houver necessidade de prover refeições ou lanches para atividades, reuniões ou eventos '
             'do ICMBio Carajás.'),
            ('Quais são as modalidades disponíveis?',
             '<strong>Coffee break</strong> — para eventos com no mínimo 10 participantes.<br>'
             '<strong>Kit lanche individual</strong> — para atividades em que não seja possível montar coffee break.<br>'
             '<strong>Almoço tipo PF</strong> — em restaurante, para grupos em atividade próxima aos escritórios.<br>'
             '<strong>Almoço tipo marmita</strong> — para equipes em trânsito ou em áreas de difícil acesso.'),
            ('É obrigatório anexar a lista de participantes?',
             'Sim. Caso a lista não esteja disponível no momento do envio, informe o motivo e encaminhe a '
             '<strong>Lista de Presença em até 3 dias após o evento</strong>.'),
            ('Quem não pode receber almoço?',
             'Os almoços <strong>não são destinados</strong> a pessoas com vínculo ao ICMBio Carajás que '
             'recebem auxílio-alimentação.'),
        ],
    },
    {
        'id': 'diaria',
        'titulo': 'Diária',
        'itens': [
            ('Quem pode receber diária?',
             'Equipe gestora da UC; funcionários do órgão gestor; membros dos conselhos gestores da UC; '
             'agentes de fiscalização (fiscais do IBAMA e OEMAS, policiais, bombeiros e afins); pesquisadores; '
             'demais parceiros; colaboradores eventuais da UC; e consultores — estes últimos apenas em atividades '
             '<strong>fora da sua cidade de origem e fora da UC</strong>, para cobertura de alimentação e hospedagem.'),
            ('Posso pagar serviço de campo com diária?',
             '<strong>Não.</strong> Diárias não devem ser utilizadas para pagamento de serviços de campo, como '
             'barqueiros, cozinheiros ou mateiros. Esses serviços devem ser discriminados separadamente e pagos '
             'pela modalidade <strong>Serviço Externo</strong>.'),
            ('O valor muda conforme o cargo?',
             '<strong>Não há diferenciação por cargo ou posição hierárquica.</strong> Os valores seguem a tabela '
             'e as regras do Manual, e o sistema calcula automaticamente conforme a área de destino e o tipo '
             '(cheia ou meia).'),
            ('Por que minha diária atrasou?',
             'A maioria dos atrasos acontece por erro nos dados pessoais ou bancários: nome digitado errado, '
             'CPF inválido, CPF em nome de terceiros (o CPF de uma pessoa numa diária destinada a outra), '
             'agência ou conta incorretas — atenção ao dígito, conta 123-4 não é o mesmo que 1234. '
             '<strong>Confira os dados antes de enviar</strong>: evita retrabalho para você e atraso para o beneficiário.'),
            ('Em que situação devo devolver a diária?',
             'Quando <strong>não realizar a viagem</strong>, por qualquer motivo — devolução do valor integral. '
             'E quando <strong>retornar antes da data final prevista</strong> — devolução das diárias recebidas em excesso.'),
            ('Qual valor exatamente devo devolver?',
             'O valor deve corresponder à <strong>diária inteira ou meia diária</strong>, e não a valores '
             'arredondados — nem para mais, nem para menos. Não devolva apenas "o que sobrou".'),
            ('Como funciona a prestação de contas?',
             'Após a aprovação, você tem <strong>5 dias corridos a contar da data de retorno</strong> para anexar '
             'o relatório de viagem. A solicitação fica destacada em vermelho em Minhas Solicitações até a entrega. '
             'Depois de enviado, o relatório passa por conferência do Executor ou do Analista, que aprova ou devolve '
             'para correção.'),
            ('Tenho prestação de contas pendente. Posso pedir nova diária?',
             'Pode. O sistema exibe um alerta informando o protocolo pendente daquele CPF, e a nova solicitação '
             'fica <strong>sujeita à análise</strong> — mas o envio não é bloqueado.'),
        ],
    },
    {
        'id': 'servico_externo',
        'titulo': 'Serviços Externos',
        'itens': [
            ('Quando devo usar essa modalidade?',
             'Sempre que houver necessidade de contratar <strong>prestadores para apoiar atividades '
             'institucionais</strong>, seja em campo, em eventos ou em ações internas. Abrange serviços '
             'operacionais, de apoio logístico ou de suporte às equipes.'),
            ('Quais profissionais posso solicitar?',
             'Auxiliares de campo; cozinheiros(as) para apoio em atividades prolongadas; e demais prestadores '
             'de serviço, conforme a demanda.'),
            ('O que preciso descrever na solicitação?',
             'O tipo de serviço, o objetivo, o local de atuação e o período previsto — de forma clara.'),
            ('O que é obrigatório ao enviar a nota fiscal?',
             'Anexar os <strong>dados bancários completos</strong>: banco, agência, conta e chave PIX.'),
        ],
    },
    {
        'id': 'seguro',
        'titulo': 'Seguro',
        'itens': [
            ('Quando devo solicitar seguro?',
             'Em atividades de campo que envolvam <strong>grupos de participantes</strong> e que demandem '
             'contratação de seguro de vida, para garantir cobertura adequada durante a atividade.'),
            ('O que é obrigatório informar?',
             'A lista completa de segurados, com <strong>RG e CPF de cada participante</strong>, além dos '
             'demais dados pessoais e de contato. No sistema, esses dados são preenchidos diretamente no '
             'formulário — não é necessário anexar planilha à parte.'),
            ('Por que os dados precisam estar completos?',
             'O envio completo é essencial para assegurar que todos os participantes estejam devidamente '
             'cobertos e para evitar atrasos na contratação do seguro.'),
        ],
    },
    {
        'id': 'rancho',
        'titulo': 'Rancho',
        'itens': [
            ('Como as quantidades são calculadas?',
             'Cada item tem um fator de consumo em <strong>gramas por pessoa por dia</strong>, considerando as '
             'três refeições. A quantidade é o fator multiplicado pelo número de pessoas e de dias, sempre '
             'arredondada para cima em números inteiros.'),
            ('Posso alterar as quantidades sugeridas?',
             'Sim. As quantidades são sugestões — altere qualquer valor conforme a necessidade da atividade. '
             'Para excluir um item da compra, marque a caixa <strong>"Não comprar"</strong> na linha correspondente.'),
            ('Como consulto os preços?',
             'Cada item tem um botão <strong>R$ ?</strong> que abre uma consulta de preço em nova aba. Os valores '
             'de referência do sistema são estimativas e podem ser atualizados pelo Analista em Cadastros → Rancho.'),
            ('Como o Executor leva a lista para o mercado?',
             'No detalhe da solicitação existe o botão <strong>"Gerar lista de compras (PDF)"</strong>, que abre '
             'uma folha pronta para imprimir, com os itens agrupados por categoria, quadradinhos para marcar '
             'o que já foi pego e campos de assinatura.'),
        ],
    },
    {
        'id': 'passagem',
        'titulo': 'Passagem',
        'itens': [
            ('Quais dados do passageiro são obrigatórios?',
             'Nome completo, CPF, RG com órgão e estado de emissão, data de nascimento, telefone com DDD e '
             'e-mail. Confira especialmente o CPF e a grafia do nome: divergência com o documento impede a emissão '
             'do bilhete.'),
            ('Como consulto o valor da passagem?',
             'O formulário tem atalhos para Google Flights (já preenchido com origem, destino e data), Azul, '
             'Gol e Latam. Informe no campo o valor estimado que encontrar.'),
            ('Onde recebo o bilhete?',
             'Quando o Executor concluir a compra, o sistema avisa que o <strong>bilhete aéreo será encaminhado '
             'para o e-mail do passageiro</strong> cadastrado na solicitação. Por isso, confira esse e-mail antes '
             'de enviar.'),
        ],
    },
    {
        'id': 'locacao',
        'titulo': 'Locação de Veículos',
        'itens': [
            ('Como o custo é calculado?',
             'Pelo <strong>KM estimado multiplicado pelo valor por quilômetro</strong> do tipo de veículo '
             'escolhido. Os valores por KM ficam em Cadastros → Locação de Veículos.'),
            ('O que preciso informar sobre o trajeto?',
             'Local de origem com endereço, o percurso com os pontos de parada, o local de retorno com endereço, '
             'e a data e horário de partida e de chegada prevista.'),
        ],
    },
    {
        'id': 'bolsa',
        'titulo': 'Bolsa',
        'itens': [
            ('Como informo a duração da bolsa?',
             'Informe o <strong>mês de início</strong> e o <strong>mês de fim</strong>. O sistema calcula a '
             'duração em meses automaticamente, contando ambos os meses — de setembro a dezembro são 4 meses.'),
            ('Como o valor total é calculado?',
             'Duração em meses multiplicada pelo valor mensal da bolsa. Com vários bolsistas, o valor da '
             'solicitação é a soma de todos.'),
            ('Preciso anexar o plano de trabalho?',
             'O anexo é opcional, mas o <strong>título do plano de trabalho</strong> é obrigatório para cada bolsista.'),
        ],
    },
]


@app.route('/ajuda', methods=['GET', 'POST'])
@login_required
def ajuda():
    if request.method == 'POST':
        somente_organizador_ou_analista()
        numero = ''.join(c for c in (request.form.get('whatsapp_numero') or '') if c.isdigit())

        registro = ConfiguracaoTexto.query.filter_by(chave=CHAVE_WHATSAPP_AJUDA).first()
        if registro:
            registro.valor = numero
        else:
            db.session.add(ConfiguracaoTexto(chave=CHAVE_WHATSAPP_AJUDA, valor=numero))
        db.session.commit()

        flash('Número de WhatsApp atualizado.' if numero else 'Número removido - o botão deixa de aparecer.', 'sucesso')
        return redirect(url_for('ajuda'))

    blocos = ''
    for topico in AJUDA_TOPICOS:
        perguntas = ''
        for pergunta, resposta in topico['itens']:
            perguntas += f"""
            <div class="ajuda-item">
                <div class="ajuda-pergunta">
                    <span>{pergunta}</span>
                    <svg class="ajuda-seta" viewBox="0 0 24 24" width="14" height="14" fill="none"
                         stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                        <path d="m6 9 6 6 6-6"/>
                    </svg>
                </div>
                <div class="ajuda-resposta">{resposta}</div>
            </div>
            """

        blocos += f"""
        <div class="painel ajuda-bloco" id="{topico['id']}">
            <div class="titulo">{topico['titulo']}</div>
            <div style="padding:6px 14px 12px;">{perguntas}</div>
        </div>
        """

    numero_whatsapp = obter_configuracao_texto(CHAVE_WHATSAPP_AJUDA, '')

    botao_whatsapp = ''
    if numero_whatsapp:
        mensagem_padrao = quote('Olá! Vim pelo SIGAD Carajás, estou com uma dúvida.')
        link_whatsapp = f'https://wa.me/{numero_whatsapp}?text={mensagem_padrao}'
        botao_whatsapp = f"""
        <a href="{link_whatsapp}" target="_blank" rel="noopener"
           style="position:fixed; bottom:24px; right:24px; z-index:200; width:56px; height:56px;
                  background:#25D366; border-radius:50%; display:flex; align-items:center;
                  justify-content:center; box-shadow:0 3px 10px rgba(0,0,0,.25); text-decoration:none;">
            <svg viewBox="0 0 24 24" width="30" height="30" fill="white">
                <path d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.45 1.32 4.95L2.05 22l5.25-1.38c1.45.79 3.08 1.21 4.74 1.21h.01c5.46 0 9.9-4.45 9.9-9.91C21.96 6.45 17.5 2 12.04 2zm5.8 14.02c-.24.68-1.4 1.3-1.94 1.38-.5.08-1.12.11-1.81-.11-.42-.13-.95-.31-1.64-.6-2.88-1.24-4.76-4.14-4.9-4.33-.14-.19-1.17-1.55-1.17-2.97 0-1.41.74-2.1 1-2.39.26-.28.58-.35.77-.35h.55c.18 0 .42-.07.65.5.24.58.82 2 .89 2.14.07.14.12.31.02.5-.09.19-.14.31-.28.47-.14.16-.29.36-.42.48-.14.14-.28.28-.12.56.16.28.71 1.17 1.53 1.9 1.05.94 1.94 1.23 2.22 1.37.28.14.44.12.6-.07.16-.19.68-.79.86-1.06.18-.28.36-.23.6-.14.24.09 1.55.73 1.82.86.27.14.45.2.51.32.07.11.07.66-.17 1.34z"/>
            </svg>
        </a>
        """

    campo_config_whatsapp = ''
    if current_user.perfil == 'analista' or current_user.is_organizador:
        campo_config_whatsapp = f"""
        <div class="bloco" style="max-width:500px; margin-bottom:18px;">
            <strong style="font-size:12.5px;">Número de WhatsApp do suporte</strong>
            <div style="font-size:11px; color:#888; margin:4px 0 8px;">
                Aparece como um botão flutuante para qualquer usuário clicar e já abrir uma
                conversa no WhatsApp. Informe com DDI e DDD, só números (ex: 5594999998888
                para +55 94 99999-8888). Deixe em branco para tirar o botão da tela.
            </div>
            <form method="POST" style="display:flex; gap:8px;">
                <input type="text" name="whatsapp_numero" value="{numero_whatsapp}"
                       placeholder="5594999998888" style="padding:7px; width:220px;">
                <button type="submit" class="btn-atalho">Salvar</button>
            </form>
        </div>
        """

    conteudo = f"""
    <h2>Central de Ajuda</h2>
    {campo_config_whatsapp}
    <div style="font-size:12.5px; color:#666; margin-bottom:16px; max-width:900px;">
        Dúvidas sobre como preencher cada tipo de solicitação, com base no
        <strong>Manual de Solicitações NGI Carajás</strong>. Clique em uma pergunta para ver a resposta,
        ou use a busca abaixo.
    </div>
    {botao_whatsapp}

    <div style="max-width:900px; margin-bottom:18px;">
        <input type="text" id="busca-ajuda" placeholder="Buscar: cotação, amazon, devolver diária, coffee break..."
               style="width:100%; padding:11px 14px; font-size:14px;">
        <div id="sem-resultado" style="display:none; font-size:13px; color:#b35c00; margin-top:10px;">
            Nenhum resultado encontrado. Tente outra palavra, ou procure a equipe administrativa.
        </div>
    </div>

    {blocos}

    <style>
        .ajuda-item {{ border-bottom: 1px solid #eef2ef; }}
        .ajuda-item:last-child {{ border-bottom: none; }}
        .ajuda-pergunta {{
            padding: 11px 4px; cursor: pointer; display: flex; align-items: center;
            justify-content: space-between; gap: 12px;
            font-size: 13.5px; font-weight: 600; color: var(--verde-escuro);
        }}
        .ajuda-pergunta:hover {{ color: var(--verde-medio); }}
        .ajuda-seta {{ transition: transform .2s ease; flex-shrink: 0; opacity: .7; }}
        .ajuda-item.aberto .ajuda-seta {{ transform: rotate(180deg); }}
        .ajuda-resposta {{
            display: none; padding: 0 4px 14px; font-size: 13.5px; line-height: 1.65; color: #37423c;
        }}
        .ajuda-item.aberto .ajuda-resposta {{ display: block; }}
        .destaque-busca {{ background: #fff3b0; }}
    </style>

    <script>
    document.querySelectorAll('.ajuda-pergunta').forEach(function (titulo) {{
        titulo.addEventListener('click', function () {{
            titulo.parentElement.classList.toggle('aberto');
        }});
    }});

    var campoBusca = document.getElementById('busca-ajuda');
    var aviso = document.getElementById('sem-resultado');

    campoBusca.addEventListener('input', function () {{
        var termo = campoBusca.value.trim().toLowerCase();
        var encontrados = 0;

        document.querySelectorAll('.ajuda-bloco').forEach(function (bloco) {{
            var visiveisNoBloco = 0;

            bloco.querySelectorAll('.ajuda-item').forEach(function (item) {{
                var texto = item.textContent.toLowerCase();
                var combina = termo === '' || texto.indexOf(termo) !== -1;

                item.style.display = combina ? 'block' : 'none';
                if (combina) {{
                    visiveisNoBloco++;
                    encontrados++;
                    // com busca ativa, já abre a resposta
                    if (termo !== '') {{ item.classList.add('aberto'); }}
                    else {{ item.classList.remove('aberto'); }}
                }}
            }});

            bloco.style.display = visiveisNoBloco > 0 ? 'block' : 'none';
        }});

        aviso.style.display = (termo !== '' && encontrados === 0) ? 'block' : 'none';
    }});

    // abre o tópico indicado na URL, ex: /ajuda#diaria
    if (window.location.hash) {{
        var alvo = document.querySelector(window.location.hash);
        if (alvo) {{
            alvo.querySelectorAll('.ajuda-item').forEach(function (item) {{
                item.classList.add('aberto');
            }});
            alvo.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        }}
    }}
    </script>
    """
    return render_pagina('Central de Ajuda', conteudo)


# ---------------- ARMAZENAMENTO: PAINEL E MIGRAÇÃO (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/armazenamento', methods=['GET', 'POST'])
@login_required
def armazenamento():
    somente_organizador()

    resultado = ''

    if request.method == 'POST':
        if not storage_disponivel():
            flash('Configure SUPABASE_URL e SUPABASE_SERVICE_KEY antes de migrar os arquivos.')
            return redirect(url_for('armazenamento'))

        pendentes = Anexo.query.filter(
            Anexo.caminho_storage.is_(None),
            Anexo.dados.isnot(None),
        ).limit(50).all()

        migrados, falhas = 0, []

        for anexo in pendentes:
            caminho = montar_caminho_anexo(anexo.solicitacao_id, anexo.nome_arquivo)
            enviado, detalhe = enviar_para_storage(caminho, anexo.dados, anexo.tipo_conteudo)

            if enviado:
                anexo.caminho_storage = caminho
                anexo.dados = None
                migrados += 1
            else:
                falhas.append(f'{anexo.nome_arquivo}: {detalhe}')

        db.session.commit()

        if migrados:
            flash(f'{migrados} arquivo(s) migrado(s) para o Storage.', 'sucesso')
        if falhas:
            resultado = ('<div class="flash"><strong>Falhas na migração:</strong><br>'
                         '<span style="font-family:monospace; font-size:11.5px;">'
                         + '<br>'.join(falhas[:10]) + '</span></div>')
        if not migrados and not falhas:
            flash('Não há arquivos pendentes de migração.', 'sucesso')

        if not resultado:
            return redirect(url_for('armazenamento'))

    total = Anexo.query.count()
    no_storage = Anexo.query.filter(Anexo.caminho_storage.isnot(None)).count()
    no_banco = Anexo.query.filter(
        Anexo.caminho_storage.is_(None), Anexo.dados.isnot(None)
    ).count()

    if storage_disponivel():
        situacao = ('<span style="color:#2e7d32; font-weight:bold;">Configurado</span> — '
                    f'os novos anexos vão para o bucket <strong>{BUCKET_ANEXOS}</strong>.')
    else:
        situacao = ('<span style="color:#b35c00; font-weight:bold;">Não configurado</span> — '
                    'os anexos estão sendo gravados dentro do banco de dados. '
                    'Defina as variáveis <code>SUPABASE_URL</code> e '
                    '<code>SUPABASE_SERVICE_KEY</code> para ativar.')

    botao = ''
    if no_banco and storage_disponivel():
        botao = f"""
        <form method="POST" style="margin-top:14px;"
              onsubmit="return confirm('Migrar até 50 arquivos para o Storage agora?');">
            <button type="submit" class="btn btn-salvar" style="padding:10px 18px;">
                Migrar arquivos para o Storage (até 50 por vez)
            </button>
        </form>
        """

    instrucoes = ''
    if not storage_disponivel():
        instrucoes = f"""
        <div class="painel" style="max-width:760px; margin-top:16px;">
            <div class="titulo">Como configurar</div>
            <div style="padding:16px; font-size:13px; line-height:1.7;">
                <strong>1.</strong> No Supabase, vá em <strong>Storage</strong> e crie um bucket
                chamado <strong>{BUCKET_ANEXOS}</strong>, deixando-o como <strong>privado</strong>.<br>
                <strong>2.</strong> Em <strong>Settings &#8594; API</strong>, copie a <em>Project URL</em>
                e a chave secreta.<br>
                <strong>3.</strong> No Railway, crie as variáveis
                <code>SUPABASE_URL</code> e <code>SUPABASE_SERVICE_KEY</code>.<br>
                <strong>4.</strong> Volte aqui e migre os arquivos existentes.
            </div>
        </div>
        """

    conteudo = f"""
    <h2>Armazenamento de Arquivos</h2>
    <div style="font-size:12.5px; color:#666; margin-bottom:16px; max-width:820px;">
        Os anexos do sistema (comprovantes, notas fiscais, relatórios, orçamentos) podem ser
        guardados no <strong>Supabase Storage</strong>, que tem 100 GB no plano Pro, em vez de
        ocuparem o espaço do banco de dados, que tem 8 GB.
    </div>

    {resultado}

    <div class="painel" style="max-width:760px;">
        <div class="titulo">Situação atual</div>
        <div class="grade">
            <div class="campo largo"><div class="rotulo">Storage</div>
                <div class="valor">{situacao}</div></div>
            <div class="campo"><div class="rotulo">Total de anexos</div>
                <div class="valor destaque">{total}</div></div>
            <div class="campo"><div class="rotulo">Já no Storage</div>
                <div class="valor destaque" style="color:#2e7d32;">{no_storage}</div></div>
            <div class="campo largo"><div class="rotulo">Ainda dentro do banco</div>
                <div class="valor destaque" style="color:{'#b35c00' if no_banco else '#2e7d32'};">{no_banco}</div></div>
        </div>
    </div>

    {botao}

    {instrucoes}
    """
    return render_pagina('Armazenamento de Arquivos', conteudo)


# ---------------- AUDITORIA (SOMENTE ORGANIZADOR) ----------------
@app.route('/auditoria')
@login_required
def auditoria():
    somente_organizador()

    filtros = {
        'acao': request.args.get('acao', ''),
        'usuario': request.args.get('usuario', '').strip(),
        'protocolo': request.args.get('protocolo', '').strip(),
        'data_inicio': request.args.get('data_inicio', ''),
        'data_fim': request.args.get('data_fim', ''),
    }

    consulta = RegistroAuditoria.query

    if filtros['acao']:
        consulta = consulta.filter(RegistroAuditoria.acao == filtros['acao'])
    if filtros['usuario']:
        consulta = consulta.filter(RegistroAuditoria.usuario_nome.ilike(f'%{filtros["usuario"]}%'))
    if filtros['protocolo']:
        consulta = consulta.filter(RegistroAuditoria.protocolo.ilike(f'%{filtros["protocolo"]}%'))

    if filtros['data_inicio']:
        try:
            consulta = consulta.filter(
                RegistroAuditoria.data_hora >= datetime.strptime(filtros['data_inicio'], '%Y-%m-%d'))
        except ValueError:
            pass
    if filtros['data_fim']:
        try:
            consulta = consulta.filter(RegistroAuditoria.data_hora <= datetime.strptime(
                filtros['data_fim'], '%Y-%m-%d').replace(hour=23, minute=59, second=59))
        except ValueError:
            pass

    POR_PAGINA = 100
    try:
        pagina = max(int(request.args.get('pagina', 1)), 1)
    except ValueError:
        pagina = 1

    total = consulta.count()
    total_paginas = max((total + POR_PAGINA - 1) // POR_PAGINA, 1)
    pagina = min(pagina, total_paginas)

    registros = consulta.order_by(RegistroAuditoria.data_hora.desc()) \
        .limit(POR_PAGINA).offset((pagina - 1) * POR_PAGINA).all()

    linhas = ''
    for r in registros:
        perfil_txt = f'<br><span style="font-size:10.5px; color:#888;">{r.usuario_perfil}</span>' if r.usuario_perfil else ''
        link = (f'<a href="{url_for("detalhe_solicitacao", solicitacao_id=r.solicitacao_id)}" '
                f'style="font-family:monospace; font-size:11.5px;">{r.protocolo}</a>'
                if r.solicitacao_id else '-')

        linhas += f"""
        <tr>
            <td style="font-size:12px; white-space:nowrap;">{r.data_hora.strftime('%d/%m/%Y %H:%M')}</td>
            <td style="font-size:12px;">{r.usuario_nome or '-'}{perfil_txt}</td>
            <td style="font-size:12px; font-weight:600;">{ACOES_AUDITORIA.get(r.acao, r.acao)}</td>
            <td>{link}</td>
            <td style="font-size:11.5px; color:#555;">{r.detalhe or '-'}</td>
        </tr>
        """

    if not linhas:
        linhas = '<tr><td colspan="5">Nenhum registro encontrado com os filtros informados.</td></tr>'

    opcoes_acao = ''.join(
        f'<option value="{chave}" {"selected" if filtros["acao"] == chave else ""}>{rotulo}</option>'
        for chave, rotulo in ACOES_AUDITORIA.items())

    def link_pagina(numero):
        parametros = {k: v for k, v in filtros.items() if v}
        parametros['pagina'] = numero
        return url_for('auditoria', **parametros)

    navegacao = ''
    if total_paginas > 1:
        anterior = f'<a href="{link_pagina(pagina - 1)}" class="btn-atalho">Anterior</a>' if pagina > 1 else ''
        proxima = f'<a href="{link_pagina(pagina + 1)}" class="btn-atalho">Próxima</a>' if pagina < total_paginas else ''
        navegacao = (f'<div style="margin-top:14px; display:flex; gap:10px; align-items:center;">'
                     f'{anterior}{proxima}<span style="font-size:12px; color:#666;">'
                     f'Página {pagina} de {total_paginas} — {total} registro(s)</span></div>')

    conteudo = f"""
    <h2>Auditoria</h2>
    <div style="font-size:12.5px; color:#666; margin-bottom:14px; max-width:900px;">
        Histórico de todas as ações do sistema: quem fez, o que fez e quando.
        Os registros são <strong>permanentes</strong> — não podem ser editados nem excluídos,
        nem pelo administrador.
    </div>

    <form method="GET" class="painel" style="padding:14px; max-width:1200px;">
        <div style="display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px;">
            <div>
                <label>Ação:</label><br>
                <select name="acao" style="width:100%; padding:6px;">
                    <option value="">Todas</option>{opcoes_acao}
                </select>
            </div>
            <div>
                <label>Usuário:</label><br>
                <input type="text" name="usuario" value="{filtros['usuario']}" style="width:100%; padding:6px;">
            </div>
            <div>
                <label>Protocolo:</label><br>
                <input type="text" name="protocolo" value="{filtros['protocolo']}" style="width:100%; padding:6px;">
            </div>
            <div>
                <label>Período:</label><br>
                <div style="display:flex; gap:6px;">
                    <input type="date" name="data_inicio" value="{filtros['data_inicio']}" style="width:100%; padding:6px;">
                    <input type="date" name="data_fim" value="{filtros['data_fim']}" style="width:100%; padding:6px;">
                </div>
            </div>
        </div>
        <div style="margin-top:13px;">
            <button type="submit" class="btn btn-salvar" style="padding:9px 18px;">Filtrar</button>
            <a href="{url_for('auditoria')}" class="btn-atalho" style="margin-left:6px;">Limpar filtros</a>
        </div>
    </form>

    <div style="overflow-x:auto;">
    <table style="max-width:1400px;">
        <tr><th style="width:135px;">Data e hora</th><th style="width:200px;">Usuário</th>
            <th style="width:230px;">Ação</th><th style="width:170px;">Protocolo</th><th>Detalhe</th></tr>
        {linhas}
    </table>
    </div>
    {navegacao}
    """
    return render_pagina('Auditoria', conteudo)


# ---------------- RELATÓRIOS ----------------
def pode_ver_relatorios():
    return current_user.perfil in ('analista', 'aprovador') or current_user.is_organizador


def montar_filtro_relatorio():
    """Monta a consulta a partir dos filtros informados e devolve (consulta, filtros)."""
    filtros = {
        'tipo': request.args.get('tipo', ''),
        'status': request.args.get('status', ''),
        'coordenacao': request.args.get('coordenacao', ''),
        'convenio': request.args.get('convenio', ''),
        'lote_aprovacao': request.args.get('lote_aprovacao', '').strip(),
        'data_inicio': request.args.get('data_inicio', ''),
        'data_fim': request.args.get('data_fim', ''),
        'busca': request.args.get('busca', '').strip(),
    }

    consulta = Solicitacao.query

    if filtros['tipo']:
        consulta = consulta.filter(Solicitacao.tipo == filtros['tipo'])
    if filtros['status']:
        consulta = consulta.filter(Solicitacao.status == filtros['status'])
    if filtros['coordenacao']:
        consulta = consulta.filter(Solicitacao.coordenacao_solicitante_id == int(filtros['coordenacao']))
    if filtros['convenio']:
        consulta = consulta.filter(Solicitacao.convenio == filtros['convenio'])
    if filtros['lote_aprovacao']:
        consulta = consulta.filter(Solicitacao.lote_aprovacao.ilike(f'%{filtros["lote_aprovacao"]}%'))

    if filtros['data_inicio']:
        try:
            inicio = datetime.strptime(filtros['data_inicio'], '%Y-%m-%d')
            consulta = consulta.filter(Solicitacao.data_envio >= inicio)
        except ValueError:
            pass

    if filtros['data_fim']:
        try:
            fim = datetime.strptime(filtros['data_fim'], '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            consulta = consulta.filter(Solicitacao.data_envio <= fim)
        except ValueError:
            pass

    if filtros['busca']:
        termo = f'%{filtros["busca"]}%'
        consulta = consulta.join(Usuario, Usuario.id == Solicitacao.solicitante_id).filter(
            db.or_(
                Usuario.nome.ilike(termo),
                Solicitacao.atividade_projeto.ilike(termo),
                Solicitacao.ponto_focal.ilike(termo),
                Solicitacao.lote_aprovacao.ilike(termo),
            )
        )

    return consulta, filtros


@app.route('/relatorios')
@login_required
def relatorios():
    if not pode_ver_relatorios():
        abort(403)

    consulta, filtros = montar_filtro_relatorio()

    POR_PAGINA = 50
    try:
        pagina = max(int(request.args.get('pagina', 1)), 1)
    except ValueError:
        pagina = 1

    total_registros = consulta.count()
    total_paginas = max((total_registros + POR_PAGINA - 1) // POR_PAGINA, 1)
    pagina = min(pagina, total_paginas)

    # totais de toda a seleção, não apenas da página
    soma_estimado = consulta.with_entities(db.func.sum(Solicitacao.valor_total)).scalar() or 0
    soma_real = consulta.with_entities(db.func.sum(Solicitacao.valor_real)).scalar() or 0

    solicitacoes = consulta.options(
        joinedload(Solicitacao.solicitante),
        joinedload(Solicitacao.coordenacao_solicitante),
        joinedload(Solicitacao.responsavel_encaminhamento),
    ).order_by(Solicitacao.data_envio.desc()).limit(POR_PAGINA).offset((pagina - 1) * POR_PAGINA).all()

    cores_status = {
        'pendente_analise': '#5b6b76', 'devolvida_ajuste': '#b35c00',
        'pendente_aprovacao': '#37784D', 'aprovada': '#2e7d32',
        'em_execucao': '#b35c00', 'enviado_pagamento': '#5b6b76',
        'em_compra': '#5b6b76', 'paga': '#2e7d32', 'comprado': '#2e7d32',
        'reprovada': '#c0392b',
        'ajuste_dados': '#b35c00',
    }

    linhas_html = ''
    for s in solicitacoes:
        coord = s.coordenacao_solicitante.nome if s.coordenacao_solicitante else '-'
        responsavel = s.responsavel_encaminhamento.nome if s.responsavel_encaminhamento else '-'
        cor = cores_status.get(s.status, '#5b6b76')
        real = moeda(s.valor_real) if s.valor_real is not None else '-'

        linhas_html += f"""
        <tr>
            <td style="font-family:monospace; font-size:11.5px;">{protocolo(s)}</td>
            <td style="font-size:12px;">{s.data_envio.strftime('%d/%m/%Y')}</td>
            <td style="font-size:12px;">{TIPO_SOLICITACAO_LABELS.get(s.tipo, s.tipo)}</td>
            <td style="font-size:12px;">{s.solicitante.nome}</td>
            <td style="font-size:12px;">{coord}</td>
            <td style="font-size:12px;">{s.convenio or '-'}</td>
            <td style="font-size:12px;">{s.lote_aprovacao or '-'}</td>
            <td style="font-size:12px;">{responsavel}</td>
            <td style="text-align:right; font-size:12px;">{moeda(s.valor_total)}</td>
            <td style="text-align:right; font-size:12px;">{real}</td>
            <td style="color:{cor}; font-weight:bold; font-size:11.5px;">{STATUS_LABELS.get(s.status, s.status)}</td>
            <td><a href="{url_for('detalhe_solicitacao', solicitacao_id=s.id)}" class="btn-atalho">Abrir</a></td>
        </tr>
        """

    if not linhas_html:
        linhas_html = '<tr><td colspan="12">Nenhuma solicitação encontrada com os filtros informados.</td></tr>'

    # opções dos filtros
    opcoes_tipo = ''.join(
        f'<option value="{chave}" {"selected" if filtros["tipo"] == chave else ""}>{rotulo}</option>'
        for chave, rotulo in TIPO_SOLICITACAO_LABELS.items())
    opcoes_status = ''.join(
        f'<option value="{chave}" {"selected" if filtros["status"] == chave else ""}>{rotulo}</option>'
        for chave, rotulo in STATUS_LABELS.items())
    opcoes_convenio = ''.join(
        f'<option value="{c}" {"selected" if filtros["convenio"] == c else ""}>{c}</option>'
        for c in CONVENIOS)

    # lotes já usados em alguma solicitação, para sugerir no campo -
    # a pessoa pode escolher um destes ou digitar um valor livre
    lotes_existentes = [
        linha[0] for linha in db.session.query(Solicitacao.lote_aprovacao)
        .filter(Solicitacao.lote_aprovacao.isnot(None), Solicitacao.lote_aprovacao != '')
        .distinct().order_by(Solicitacao.lote_aprovacao).all()
    ]
    opcoes_lotes = ''.join(f'<option value="{lote}">' for lote in lotes_existentes)

    # paginação preservando os filtros
    def link_pagina(numero):
        parametros = {k: v for k, v in filtros.items() if v}
        parametros['pagina'] = numero
        return url_for('relatorios', **parametros)

    navegacao = ''
    if total_paginas > 1:
        anterior = f'<a href="{link_pagina(pagina - 1)}" class="btn-atalho">Anterior</a>' if pagina > 1 else ''
        proxima = f'<a href="{link_pagina(pagina + 1)}" class="btn-atalho">Próxima</a>' if pagina < total_paginas else ''
        navegacao = f"""
        <div style="margin-top:14px; display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
            {anterior}{proxima}
            <span style="font-size:12px; color:#666;">Página {pagina} de {total_paginas}</span>
        </div>
        """

    parametros_export = {k: v for k, v in filtros.items() if v}
    link_csv = url_for('exportar_relatorio', **parametros_export)

    conteudo = f"""
    <h2>Relatórios</h2>
    <div style="font-size:12px; color:#666; margin-bottom:14px;">
        Todas as solicitações recebidas pelo sistema. Use os filtros para recortar o período,
        o tipo, o status ou o convênio, e exporte o resultado para planilha.
    </div>

    <form method="GET" class="painel" style="padding:14px; max-width:1250px;">
        <div style="display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px;">
            <div>
                <label>Tipo:</label><br>
                <select name="tipo" style="width:100%; padding:6px;">
                    <option value="">Todos</option>{opcoes_tipo}
                </select>
            </div>
            <div>
                <label>Status:</label><br>
                <select name="status" style="width:100%; padding:6px;">
                    <option value="">Todos</option>{opcoes_status}
                </select>
            </div>
            <div>
                <label>Coordenação:</label><br>
                <select name="coordenacao" style="width:100%; padding:6px;">
                    <option value="">Todas</option>{montar_opcoes_coordenacoes(filtros['coordenacao'])}
                </select>
            </div>
            <div>
                <label>Convênio:</label><br>
                <select name="convenio" style="width:100%; padding:6px;">
                    <option value="">Todos</option>{opcoes_convenio}
                </select>
            </div>
            <div>
                <label>Lote de aprovação:</label><br>
                <input type="text" name="lote_aprovacao" value="{filtros['lote_aprovacao']}"
                       list="lotes-existentes" placeholder="Selecione ou digite..."
                       style="width:100%; padding:6px;">
                <datalist id="lotes-existentes">{opcoes_lotes}</datalist>
            </div>
            <div>
                <label>Enviadas de:</label><br>
                <input type="date" name="data_inicio" value="{filtros['data_inicio']}" style="width:100%; padding:6px;">
            </div>
            <div>
                <label>Até:</label><br>
                <input type="date" name="data_fim" value="{filtros['data_fim']}" style="width:100%; padding:6px;">
            </div>
            <div style="grid-column:span 2;">
                <label>Buscar (solicitante, projeto, ponto focal, lote):</label><br>
                <input type="text" name="busca" value="{filtros['busca']}" style="width:100%; padding:6px;">
            </div>
        </div>
        <div style="margin-top:13px;">
            <button type="submit" class="btn btn-salvar" style="padding:9px 18px;">Filtrar</button>
            <a href="{url_for('relatorios')}" class="btn-atalho" style="margin-left:6px;">Limpar filtros</a>
            <a href="{link_csv}" class="btn-atalho">Exportar para planilha (CSV)</a>
        </div>
    </form>

    <div class="painel" style="max-width:1250px;">
        <div class="titulo">Resumo da seleção</div>
        <div class="grade">
            <div class="campo"><div class="rotulo">Solicitações encontradas</div>
                <div class="valor destaque">{total_registros}</div></div>
            <div class="campo"><div class="rotulo">Valor estimado total</div>
                <div class="valor destaque">{moeda(soma_estimado)}</div></div>
            <div class="campo largo"><div class="rotulo">Valor realizado (compras concluídas)</div>
                <div class="valor destaque">{moeda(soma_real)}</div></div>
        </div>
    </div>

    <div style="overflow-x:auto;">
    <table style="max-width:1600px;">
        <tr>
            <th>Protocolo</th><th>Data</th><th>Tipo</th><th>Solicitante</th><th>Coordenação</th>
            <th>Convênio</th><th>Lote</th><th>Responsável</th>
            <th style="text-align:right;">Estimado</th><th style="text-align:right;">Realizado</th>
            <th>Status</th><th></th>
        </tr>
        {linhas_html}
    </table>
    </div>
    {navegacao}
    """
    return render_pagina('Relatórios', conteudo)


@app.route('/relatorios/exportar')
@login_required
def exportar_relatorio():
    if not pode_ver_relatorios():
        abort(403)

    import csv
    import io
    from flask import Response

    consulta, _filtros = montar_filtro_relatorio()

    solicitacoes = consulta.options(
        joinedload(Solicitacao.solicitante),
        joinedload(Solicitacao.coordenacao_solicitante),
        joinedload(Solicitacao.responsavel_encaminhamento),
    ).order_by(Solicitacao.data_envio.desc()).all()

    buffer = io.StringIO()
    # ponto e vírgula: padrão do Excel em português
    escritor = csv.writer(buffer, delimiter=';')

    escritor.writerow([
        'Protocolo', 'Data de envio', 'Tipo', 'Solicitante', 'Coordenação', 'Contato',
        'Ponto focal', 'Atividade/Projeto', 'Convênio', 'Lote de aprovação', 'Rubrica',
        'Responsável pelo encaminhamento', 'Status', 'Valor estimado', 'Valor realizado',
        'Prazo de atendimento', 'Data de conclusão', 'Prestação de contas',
    ])

    for s in solicitacoes:
        if s.tipo != 'diaria':
            prestacao = '-'
        elif s.prestacao_contas_entregue:
            prestacao = 'Aprovada'
        elif s.relatorio_em_conferencia:
            prestacao = 'Em conferência'
        else:
            prestacao = 'Pendente'

        escritor.writerow([
            protocolo(s),
            s.data_envio.strftime('%d/%m/%Y %H:%M'),
            TIPO_SOLICITACAO_LABELS.get(s.tipo, s.tipo),
            s.solicitante.nome,
            s.coordenacao_solicitante.nome if s.coordenacao_solicitante else '',
            s.contato_solicitante or '',
            s.ponto_focal or '',
            s.atividade_projeto or '',
            s.convenio or '',
            s.lote_aprovacao or '',
            s.rubrica or '',
            s.responsavel_encaminhamento.nome if s.responsavel_encaminhamento else '',
            STATUS_LABELS.get(s.status, s.status),
            f'{float(s.valor_total or 0):.2f}'.replace('.', ','),
            f'{float(s.valor_real):.2f}'.replace('.', ',') if s.valor_real is not None else '',
            s.prazo_encaminhamento.strftime('%d/%m/%Y') if s.prazo_encaminhamento else '',
            s.data_pagamento.strftime('%d/%m/%Y') if s.data_pagamento else '',
            prestacao,
        ])

    # BOM para o Excel reconhecer os acentos
    conteudo_csv = '\ufeff' + buffer.getvalue()
    nome_arquivo = f'relatorio_sigad_{hoje().strftime("%Y%m%d")}.csv'

    return Response(
        conteudo_csv.encode('utf-8'),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{nome_arquivo}"'},
    )


# ---------------- PRESTAÇÃO DE CONTAS ----------------
PRAZO_PRESTACAO_DIAS = 5


def situacao_prestacao(diaria, solicitacao):
    """Retorna (rotulo, cor, dias_atraso, prazo_final) da prestação de contas."""
    from datetime import timedelta

    prazo_final = diaria.data_retorno + timedelta(days=PRAZO_PRESTACAO_DIAS)
    data_hoje = hoje()

    if solicitacao.prestacao_contas_entregue:
        return ('Aprovada', '#2e7d32', 0, prazo_final)

    if solicitacao.relatorio_em_conferencia:
        return ('Em conferência', '#b35c00', 0, prazo_final)

    if solicitacao.motivo_recusa_prestacao:
        return ('DEVOLVIDA - reenviar relatório', '#c0392b',
                max((data_hoje - prazo_final).days, 0), prazo_final)

    if data_hoje > prazo_final:
        return ('PENDENTE - EM ATRASO', '#c0392b', (data_hoje - prazo_final).days, prazo_final)

    if data_hoje > diaria.data_retorno:
        return ('Aguardando entrega', '#c0392b', 0, prazo_final)

    return ('Viagem em curso', '#5b6b76', 0, prazo_final)


def so_digitos(texto):
    return ''.join(c for c in (texto or '') if c.isdigit())


def prestacoes_pendentes_por_cpf(cpf):
    """Diárias vencidas (retorno + prazo) sem prestação entregue para o CPF informado."""
    from datetime import timedelta

    cpf_limpo = so_digitos(cpf)
    if len(cpf_limpo) != 11:
        return []

    limite = hoje() - timedelta(days=PRAZO_PRESTACAO_DIAS)

    registros = db.session.query(Solicitacao, SolicitacaoDiaria).join(
        SolicitacaoDiaria, SolicitacaoDiaria.solicitacao_id == Solicitacao.id
    ).filter(
        Solicitacao.tipo == 'diaria',
        Solicitacao.status.in_(('aprovada', 'em_execucao', 'enviado_pagamento', 'paga')),
        Solicitacao.prestacao_contas_entregue.isnot(True),
        Solicitacao.relatorio_em_conferencia.isnot(True),
        SolicitacaoDiaria.data_retorno < limite,
    ).all()

    return [(sol, dia) for sol, dia in registros if so_digitos(dia.cpf_diarista) == cpf_limpo]


@app.route('/api/verificar-prestacao')
@login_required
def api_verificar_prestacao():
    bloqueantes = prestacoes_nao_aprovadas_por_cpf(request.args.get('cpf'))
    return jsonify({
        'bloqueado': len(bloqueantes) > 0,
        'pendentes': [
            {
                'protocolo': protocolo(sol),
                'diarista': dia.nome_diarista,
                'retorno': dia.data_retorno.strftime('%d/%m/%Y'),
            }
            for sol, dia in bloqueantes
        ]
    })


def prestacoes_nao_aprovadas_por_cpf(cpf):
    """Diárias já retornadas (viagem concluída) para as quais o diarista
    ainda não enviou NENHUM relatório de viagem. Usado para BLOQUEAR uma
    nova diária para o mesmo CPF.

    A trava cai assim que o relatório é enviado (data_relatorio_enviado
    preenchida) - não é preciso esperar a aprovação. Se o Executor devolver
    o relatório para correção, a pessoa continua desbloqueada (devolver não
    apaga data_relatorio_enviado, só a remoção do anexo apaga). Só volta a
    bloquear se o anexo for removido por completo, sem nenhum reenvio."""
    cpf_limpo = so_digitos(cpf)
    if len(cpf_limpo) != 11:
        return []

    registros = db.session.query(Solicitacao, SolicitacaoDiaria).join(
        SolicitacaoDiaria, SolicitacaoDiaria.solicitacao_id == Solicitacao.id
    ).filter(
        Solicitacao.tipo == 'diaria',
        Solicitacao.status.in_(('aprovada', 'em_execucao', 'enviado_pagamento', 'paga')),
        Solicitacao.data_relatorio_enviado.is_(None),
        SolicitacaoDiaria.data_retorno <= hoje(),
    ).all()

    return [(sol, dia) for sol, dia in registros if so_digitos(dia.cpf_diarista) == cpf_limpo]


def pode_avaliar_prestacao():
    return current_user.perfil in ('analista', 'comprador') or current_user.is_organizador


def pode_ver_prestacao():
    """Quem enxerga a prestação de contas de toda a instituição."""
    return (current_user.perfil in ('analista', 'aprovador', 'comprador')
            or current_user.is_organizador)


@app.route('/prestacao-contas')
@login_required
def prestacao_contas():
    # o solicitante vê apenas as próprias diárias; os perfis do fluxo veem todas
    visao_geral = pode_ver_prestacao()

    consulta = db.session.query(Solicitacao, SolicitacaoDiaria, Usuario).join(
        SolicitacaoDiaria, SolicitacaoDiaria.solicitacao_id == Solicitacao.id
    ).join(
        Usuario, Usuario.id == Solicitacao.solicitante_id
    ).filter(
        Solicitacao.tipo == 'diaria',
        Solicitacao.status.in_(('aprovada', 'em_execucao', 'enviado_pagamento', 'paga')),
    )

    if not visao_geral:
        consulta = consulta.filter(Solicitacao.solicitante_id == current_user.id)

    filtro_protocolo = request.args.get('protocolo', '').strip()
    if filtro_protocolo:
        id_buscado = id_a_partir_do_protocolo(filtro_protocolo)
        consulta = consulta.filter(Solicitacao.id == (id_buscado or -1))

    registros = consulta.order_by(SolicitacaoDiaria.data_retorno).all()

    linhas = []
    total_atraso = 0

    for solicitacao, diaria, _usuario in registros:
        rotulo, cor, dias_atraso, prazo_final = situacao_prestacao(diaria, solicitacao)
        if dias_atraso > 0:
            total_atraso += 1
        linhas.append((solicitacao, diaria, rotulo, cor, dias_atraso, prazo_final))

    # atrasadas primeiro, depois por prazo
    linhas.sort(key=lambda x: (-x[4], x[5]))

    linhas_html = ''
    for solicitacao, diaria, rotulo, cor, dias_atraso, prazo_final in linhas:
        destaque = 'background:#fdeceb;' if dias_atraso > 0 else ''
        atraso_txt = f'<br><span style="font-size:11px;">{dias_atraso} dia(s) de atraso</span>' if dias_atraso > 0 else ''
        entrega = solicitacao.data_prestacao_contas.strftime('%d/%m/%Y') if solicitacao.data_prestacao_contas else '-'
        aprovador = ''
        if solicitacao.prestacao_aprovada_por:
            aprovador = f'<br><span style="font-size:10.5px; color:#666;">{solicitacao.prestacao_aprovada_por}</span>'
        elif solicitacao.relatorio_em_conferencia and solicitacao.data_relatorio_enviado:
            aprovador = (f'<br><span style="font-size:10.5px; color:#b35c00;">enviado em '
                         f'{solicitacao.data_relatorio_enviado.strftime("%d/%m/%Y")}</span>')

        linhas_html += f"""
        <tr style="{destaque}">
            <td style="font-family:monospace; font-size:12px;">{protocolo(solicitacao)}</td>
            <td style="font-size:12px;">{diaria.nome_diarista}</td>
            <td style="font-size:12px;">{solicitacao.solicitante.nome}</td>
            <td style="font-size:12px;">{diaria.data_ida.strftime('%d/%m/%Y')} a {diaria.data_retorno.strftime('%d/%m/%Y')}</td>
            <td style="font-size:12px;">{prazo_final.strftime('%d/%m/%Y')}</td>
            <td style="color:{cor}; font-weight:bold; font-size:12px;">{rotulo}{atraso_txt}</td>
            <td style="font-size:12px;">{entrega}{aprovador}</td>
            <td>
                <a href="{url_for('detalhe_solicitacao', solicitacao_id=solicitacao.id)}" class="btn-atalho">Abrir</a>
            </td>
        </tr>
        """

    if not linhas_html:
        linhas_html = '<tr><td colspan="8">Nenhuma diária aprovada até o momento.</td></tr>'

    alerta = ''
    if total_atraso:
        alerta = f"""
        <div class="flash" style="max-width:1150px;">
            <strong>{total_atraso} prestação(ões) de contas em atraso.</strong>
            O prazo é de {PRAZO_PRESTACAO_DIAS} dias corridos após a data de retorno da viagem.
        </div>
        """

    if visao_geral:
        introducao = (f'Controle das diárias aprovadas de toda a equipe. O prazo de entrega é de '
                      f'<strong>{PRAZO_PRESTACAO_DIAS} dias corridos após a data de retorno</strong>. '
                      f'Linhas em vermelho indicam prestação vencida.')
    else:
        introducao = (f'Suas diárias aprovadas e a situação da prestação de contas de cada uma. '
                      f'O prazo é de <strong>{PRAZO_PRESTACAO_DIAS} dias corridos após a data de '
                      f'retorno</strong>. Abra a solicitação para anexar e enviar o relatório de viagem.')

    conteudo = f"""
    <h2>Prestação de Contas</h2>
    <div style="font-size:12px; color:#666; margin-bottom:14px;">
        {introducao}
    </div>
    <form method="GET" style="margin-bottom:14px; display:flex; gap:8px; align-items:center;">
        <input type="text" name="protocolo" value="{filtro_protocolo}" placeholder="Buscar por protocolo..."
               style="padding:7px; width:220px;">
        <button type="submit" class="btn-atalho">Filtrar</button>
        {f'<a href="{url_for("prestacao_contas")}" class="btn-atalho">Limpar</a>' if filtro_protocolo else ''}
    </form>
    {alerta}
    <table style="max-width:1150px;">
        <tr>
            <th>Protocolo</th><th>Diarista</th><th>Solicitante</th><th>Período da viagem</th>
            <th>Prazo final</th><th>Situação</th><th>Aprovada em</th><th>Ações</th>
        </tr>
        {linhas_html}
    </table>
    """
    return render_pagina('Prestação de Contas', conteudo)


@app.route('/solicitacao/<int:solicitacao_id>/prestacao-contas', methods=['POST'])
@login_required
def registrar_prestacao_contas(solicitacao_id):
    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)

    eh_dono = solicitacao.solicitante_id == current_user.id
    if not eh_dono and not pode_ver_prestacao():
        abort(403)

    if solicitacao.tipo != 'diaria':
        abort(404)

    arquivo = request.files.get('relatorio_prestacao')
    if not arquivo or not arquivo.filename:
        flash('Anexe o relatório de prestação de contas.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    salvar_anexo(solicitacao.id, arquivo, 'prestacao_contas')

    solicitacao.relatorio_em_conferencia = True
    solicitacao.data_relatorio_enviado = hoje()
    solicitacao.motivo_recusa_prestacao = None
    registrar_auditoria('enviou_relatorio', solicitacao, f'Arquivo: {arquivo.filename}')
    db.session.commit()

    diarias_da_solicitacao = SolicitacaoDiaria.query.filter_by(solicitacao_id=solicitacao.id).all()
    nome_diarista = (', '.join(d.nome_diarista for d in diarias_da_solicitacao)
                     if diarias_da_solicitacao else solicitacao.solicitante.nome)

    corpo = (
        f'O relatório de viagem da solicitação {protocolo(solicitacao)} foi enviado por '
        f'{current_user.nome}.\n\n'
        f'Diarista: {nome_diarista}\n'
        f'Arquivo: {arquivo.filename}\n\n'
        f'O relatório aguarda CONFERÊNCIA. Acesse o sistema para conferir e '
        f'aprovar ou devolver a prestação de contas.'
    )

    destinatarios = []
    if solicitacao.responsavel_encaminhamento:
        destinatarios.append(solicitacao.responsavel_encaminhamento.email)
    for analista in Usuario.query.filter_by(perfil='analista').all():
        destinatarios.append(analista.email)

    for endereco in set(destinatarios):
        enviar_email(endereco, 'Relatório de viagem enviado - SIGAD Carajás', corpo)

    flash('Relatório de viagem enviado. Aguardando conferência do Executor ou do Analista.', 'sucesso')
    return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))


@app.route('/solicitacao/<int:solicitacao_id>/prestacao-contas/avaliar', methods=['POST'])
@login_required
def avaliar_prestacao_contas(solicitacao_id):
    if not pode_avaliar_prestacao():
        abort(403)

    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)

    if solicitacao.tipo != 'diaria':
        abort(404)

    if not solicitacao.relatorio_em_conferencia:
        flash('Não há relatório aguardando conferência nesta solicitação.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    acao = request.form.get('acao')
    perfil = 'Executor' if current_user.perfil == 'comprador' else 'Analista'

    if acao == 'aprovar':
        # não se aprova prestação sem o documento correspondente
        tem_relatorio = Anexo.query.filter_by(
            solicitacao_id=solicitacao.id, tipo_anexo='prestacao_contas').count()

        if not tem_relatorio:
            flash('Não é possível aprovar: nenhum relatório de viagem foi anexado a esta solicitação.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        solicitacao.prestacao_contas_entregue = True
        solicitacao.data_prestacao_contas = hoje()
        solicitacao.relatorio_em_conferencia = False
        solicitacao.motivo_recusa_prestacao = None
        solicitacao.prestacao_aprovada_por = f'{current_user.nome} ({perfil})'
        registrar_auditoria('aprovou_prestacao', solicitacao)
        db.session.commit()

        notificar_solicitante(
            solicitacao,
            'Prestação de contas aprovada - SIGAD Carajás',
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'A prestação de contas da sua solicitação, protocolo {protocolo(solicitacao)}, foi '
            f'conferida e aprovada por {current_user.nome}.\n\n'
            f'A pendência foi baixada e não impede novas solicitações de diária.',
        )

        flash('Prestação de contas aprovada. Pendência baixada.', 'sucesso')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    if acao == 'recusar':
        motivo = (request.form.get('motivo') or '').strip()
        if not motivo:
            flash('Informe o motivo da devolução do relatório.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

        solicitacao.relatorio_em_conferencia = False
        solicitacao.prestacao_contas_entregue = False
        solicitacao.motivo_recusa_prestacao = f'{motivo} (devolvido por {current_user.nome} - {perfil})'
        registrar_auditoria('devolveu_prestacao', solicitacao, motivo)
        db.session.commit()

        notificar_solicitante(
            solicitacao,
            'Prestação de contas devolvida para correção - SIGAD Carajás',
            f'Olá, {solicitacao.solicitante.nome}.\n\n'
            f'O relatório de viagem da sua solicitação, protocolo {protocolo(solicitacao)}, foi '
            f'conferido e devolvido para correção.\n\n'
            f'Motivo: {motivo}\n\n'
            f'Acesse o sistema, corrija as informações e envie o relatório novamente. A pendência '
            f'de prestação de contas permanece em aberto até a aprovação.',
        )

        flash('Relatório devolvido ao solicitante para correção.', 'sucesso')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    flash('Ação inválida.')
    return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))


@app.route('/solicitacao/<int:solicitacao_id>/informar-boleto', methods=['POST'])
@login_required
def informar_boleto(solicitacao_id):
    """O solicitante anexa o boleto de arrecadação municipal (BAM) emitido
    pelo prestador de serviço PF e informa o vencimento, para que o Executor
    saiba quando e o que pagar. Comunicação direta entre Solicitante e
    Executor - a solicitação já está aprovada, não volta a passar por
    análise."""
    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)

    if solicitacao.tipo != 'servico_externo_pf':
        abort(404)

    if solicitacao.solicitante_id != current_user.id and not current_user.is_organizador:
        abort(403)

    if solicitacao.status != 'aprovada':
        flash('Só é possível anexar o boleto enquanto a solicitação está aprovada.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    vencimento = request.form.get('boleto_vencimento')
    if not vencimento:
        flash('Informe a data de vencimento do boleto.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    arquivo = request.files.get('boleto_arquivo')
    if not arquivo or not arquivo.filename:
        flash('Anexe o arquivo do boleto de arrecadação municipal.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    salvar_anexo(solicitacao.id, arquivo, 'boleto_arrecadacao')

    solicitacao.boleto_vencimento = vencimento
    solicitacao.boleto_informado_em = agora()
    # a demanda passa a ser conduzida pelo Executor - sem nova análise
    solicitacao.status = 'em_execucao'
    registrar_auditoria('informou_boleto', solicitacao, f'Vencimento em {vencimento} - arquivo: {arquivo.filename}')
    db.session.commit()

    if solicitacao.responsavel_encaminhamento:
        enviar_email(
            solicitacao.responsavel_encaminhamento.email,
            f'Boleto a pagar - {protocolo(solicitacao)} - SIGAD Carajás',
            f'Olá, {solicitacao.responsavel_encaminhamento.nome}.\n\n'
            f'O solicitante anexou o boleto de arrecadação municipal da solicitação, protocolo '
            f'{protocolo(solicitacao)}.\n\n'
            f'Vencimento: {datetime.strptime(vencimento, "%Y-%m-%d").strftime("%d/%m/%Y")}\n\n'
            f'Acesse o sistema para conduzir o pagamento.',
        )

    flash('Vencimento do boleto informado. O responsável pelo encaminhamento foi avisado.', 'sucesso')
    return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))


@app.route('/solicitacao/<int:solicitacao_id>/nota-fiscal', methods=['POST'])
@login_required
def enviar_nota_fiscal(solicitacao_id):
    """O solicitante anexa a nota fiscal depois que o Executor paga o boleto,
    liberando a conclusão do pagamento do Serviço Externo PF."""
    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)

    if solicitacao.tipo != 'servico_externo_pf':
        abort(404)

    if solicitacao.solicitante_id != current_user.id and not current_user.is_organizador:
        abort(403)

    if not solicitacao.boleto_pago_em:
        flash('O boleto ainda não foi pago pelo Executor. Aguarde antes de enviar a nota fiscal.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    arquivo = request.files.get('nota_fiscal')
    if not arquivo or not arquivo.filename:
        flash('Selecione o arquivo da nota fiscal.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    salvar_anexo(solicitacao.id, arquivo, 'nota_fiscal')
    registrar_auditoria('enviou_nota_fiscal', solicitacao, f'Arquivo: {arquivo.filename}')
    db.session.commit()

    if solicitacao.responsavel_encaminhamento:
        enviar_email(
            solicitacao.responsavel_encaminhamento.email,
            f'Nota fiscal recebida - {protocolo(solicitacao)} - SIGAD Carajás',
            f'Olá, {solicitacao.responsavel_encaminhamento.nome}.\n\n'
            f'O solicitante anexou a nota fiscal da solicitação, protocolo {protocolo(solicitacao)}. '
            f'Já é possível concluir o pagamento.',
        )

    flash('Nota fiscal enviada com sucesso.', 'sucesso')
    return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))


@app.route('/anexo/<int:anexo_id>/remover', methods=['POST'])
@login_required
def remover_anexo(anexo_id):
    anexo = Anexo.query.get_or_404(anexo_id)
    solicitacao = anexo.solicitacao

    eh_dono = solicitacao.solicitante_id == current_user.id
    eh_fluxo = (current_user.perfil in ('analista', 'aprovador', 'comprador')
                or current_user.is_organizador)

    if not eh_dono and not eh_fluxo:
        abort(403)

    if eh_dono and not eh_fluxo:
        if anexo.tipo_anexo == 'prestacao_contas' and solicitacao.prestacao_contas_entregue:
            flash('A prestação de contas já foi aprovada. Peça ao Analista ou ao Executor '
                  'para remover o relatório, se necessário.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao.id))

        if solicitacao.status in ('paga', 'comprado', 'reprovada'):
            flash('Esta solicitação já está concluída. Procure o Analista para alterar os anexos.')
            return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao.id))

    nome = anexo.nome_arquivo
    tipo = anexo.tipo_anexo

    if anexo.caminho_storage:
        removido, detalhe = remover_do_storage(anexo.caminho_storage)
        if not removido:
            print(f'[storage] falha ao remover {anexo.caminho_storage}: {detalhe}')

    db.session.delete(anexo)
    db.session.flush()

    if tipo == 'prestacao_contas':
        restantes = Anexo.query.filter_by(
            solicitacao_id=solicitacao.id, tipo_anexo='prestacao_contas').count()
        if not restantes:
            solicitacao.relatorio_em_conferencia = False
            solicitacao.prestacao_contas_entregue = False
            solicitacao.data_relatorio_enviado = None
            solicitacao.data_prestacao_contas = None
            solicitacao.prestacao_aprovada_por = None

    registrar_auditoria('removeu_anexo', solicitacao, f'Arquivo: {nome}')
    db.session.commit()

    flash(f'Anexo "{nome}" removido.', 'sucesso')
    return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao.id))


@app.route('/anexo/<int:anexo_id>')
@login_required
def baixar_anexo(anexo_id):
    from flask import Response

    anexo = Anexo.query.get_or_404(anexo_id)
    solicitacao = anexo.solicitacao

    eh_dono = solicitacao.solicitante_id == current_user.id
    eh_fluxo = current_user.perfil in ('analista', 'aprovador', 'comprador') or current_user.is_organizador
    if not eh_dono and not eh_fluxo:
        abort(403)

    conteudo = ler_anexo(anexo)
    if conteudo is None:
        flash('Não foi possível recuperar este arquivo. Avise o administrador do sistema.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao.id))

    return Response(
        conteudo,
        mimetype=anexo.tipo_conteudo or 'application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{anexo.nome_arquivo}"'},
    )


@app.route('/solicitacao/<int:solicitacao_id>/rancho/item/<int:item_id>/remover', methods=['POST'])
@login_required
def detalhe_remover_item_rancho(solicitacao_id, item_id):
    if not pode_editar_itens():
        abort(403)

    solicitacao = Solicitacao.query.get_or_404(solicitacao_id)

    if solicitacao.status not in ('pendente_analise', 'pendente_aprovacao'):
        flash('Só é possível remover itens enquanto a solicitação está em análise ou aguardando aprovação.')
        return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))

    item = ItemSolicitacaoRancho.query.get_or_404(item_id)
    if item.solicitacao_id != solicitacao.id:
        abort(404)

    nome = item.nome_item
    db.session.delete(item)
    db.session.flush()

    restantes = ItemSolicitacaoRancho.query.filter_by(solicitacao_id=solicitacao.id).all()
    solicitacao.valor_total = sum(float(i.valor_total_item or 0) for i in restantes)

    registrar_auditoria('removeu_item', solicitacao,
                        f'Item "{nome}" removido | novo total {moeda(solicitacao.valor_total)}')
    db.session.commit()
    flash(f'Item "{nome}" removido da solicitação. Valor total recalculado.', 'sucesso')
    return redirect(url_for('detalhe_solicitacao', solicitacao_id=solicitacao_id))


# ---------------- CADASTROS: COORDENAÇÃO (SOMENTE ORGANIZADOR) ----------------
@app.route('/cadastros/coordenacao')
@login_required
def cadastro_coordenacao():
    somente_organizador_ou_analista()

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
    somente_organizador_ou_analista()
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
    somente_organizador_ou_analista()
    coord = Coordenacao.query.get_or_404(coordenacao_id)
    coord.nome = request.form.get('nome', '').strip()
    db.session.commit()
    flash('Coordenação atualizada com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_coordenacao'))


@app.route('/cadastros/coordenacao/<int:coordenacao_id>/excluir', methods=['POST'])
@login_required
def cadastro_coordenacao_excluir(coordenacao_id):
    somente_organizador_ou_analista()
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
    somente_organizador_ou_analista()

    areas = AreaDiaria.query.order_by(AreaDiaria.nome).all()
    linhas_html = ''
    for area in areas:
        valor_cheia = next((v.valor for v in area.valores if v.tipo_diaria == 'Cheia'), 0)
        valor_meia = next((v.valor for v in area.valores if v.tipo_diaria == 'Meia'), 0)
        linhas_html += f"""
        <tr>
            <form method="POST" action="{url_for('cadastro_diaria_atualizar_area', area_id=area.id)}" style="display:contents;">
            <td><input type="text" name="nome" value="{area.nome}" style="width:170px; padding:4px;"></td>
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
    somente_organizador_ou_analista()
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
    somente_organizador_ou_analista()
    area = AreaDiaria.query.get_or_404(area_id)

    nome = (request.form.get('nome') or '').strip()
    if not nome:
        flash('O nome da área não pode ficar em branco.')
        return redirect(url_for('cadastro_diaria'))

    duplicada = AreaDiaria.query.filter(
        AreaDiaria.nome == nome, AreaDiaria.id != area.id).first()
    if duplicada:
        flash(f'Já existe uma área chamada "{nome}".')
        return redirect(url_for('cadastro_diaria'))

    area.nome = nome

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
    somente_organizador_ou_analista()
    area = AreaDiaria.query.get_or_404(area_id)
    nome = area.nome
    db.session.delete(area)
    db.session.commit()
    flash(f'Área "{nome}" excluída com sucesso!', 'sucesso')
    return redirect(url_for('cadastro_diaria'))


@app.route('/cadastros/diaria/auxilio/atualizar', methods=['POST'])
@login_required
def cadastro_diaria_atualizar_auxilio():
    somente_organizador_ou_analista()
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

    existe_config_iss = Configuracao.query.filter_by(chave=CHAVE_ALIQUOTA_ISS).first()
    if not existe_config_iss:
        db.session.add(Configuracao(chave=CHAVE_ALIQUOTA_ISS, valor=ALIQUOTA_ISS_PADRAO))

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


ITENS_RANCHO_PADRAO = [
    # (nome, categoria, unidade, fator por pessoa/dia, valor unitário de referência, refeições em que o item entra)
    ('Arroz (kg)', 'Mantimentos', 'kg', 0.2, 6.00, 'almoco,jantar'),
    ('Feijão (kg)', 'Mantimentos', 'kg', 0.08, 9.50, 'almoco,jantar'),
    ('Farinha de mandioca amarela (kg)', 'Mantimentos', 'kg', 0.05, 7.00, 'almoco,jantar'),
    ('Macarrão (kg)', 'Mantimentos', 'kg', 0.06, 6.50, 'almoco,jantar'),
    ('Molho de tomate (kg)', 'Mantimentos', 'kg', 0.03, 8.00, 'almoco,jantar'),
    ('Açúcar (kg)', 'Mantimentos', 'kg', 0.05, 4.50, 'todas'),
    ('Cuzcuz (kg)', 'Mantimentos', 'kg', 0.05, 6.00, 'cafe'),
    ('Tapioca pronta (kg)', 'Mantimentos', 'kg', 0.04, 9.00, 'cafe'),
    ('Pão de forma (kg)', 'Mantimentos', 'kg', 0.05, 12.00, 'cafe'),
    ('Margarina (kg)', 'Mantimentos', 'kg', 0.02, 12.00, 'cafe'),
    ('Café (kg)', 'Mantimentos', 'kg', 0.02, 45.00, 'cafe'),
    ('Leite em pó (kg)', 'Mantimentos', 'kg', 0.03, 32.00, 'cafe'),
    ('Biscoito de água e sal (kg)', 'Mantimentos', 'kg', 0.03, 14.00, 'cafe'),
    ('Biscoito doce (maisena) (kg)', 'Mantimentos', 'kg', 0.03, 14.00, 'cafe'),
    ('Farinha de trigo (kg)', 'Mantimentos', 'kg', 0.03, 5.00, 'cafe'),
    ('Fermento Químico (kg)', 'Mantimentos', 'kg', 0.005, 30.00, 'cafe'),
    ('Goiabada (kg)', 'Mantimentos', 'kg', 0.02, 14.00, 'cafe'),

    ('Sal (kg)', 'Temperos/condimentos', 'kg', 0.01, 3.00, 'almoco,jantar'),
    ('Pimenta de reino (kg)', 'Temperos/condimentos', 'kg', 0.002, 80.00, 'almoco,jantar'),
    ('Açafrão (kg)', 'Temperos/condimentos', 'kg', 0.002, 40.00, 'almoco,jantar'),
    ('Coloral (kg)', 'Temperos/condimentos', 'kg', 0.002, 20.00, 'almoco,jantar'),
    ('Óleo (litro)', 'Temperos/condimentos', 'litro', 0.03, 8.00, 'almoco,jantar'),

    ('Alho (kg)', 'Frutas e legumes', 'kg', 0.005, 30.00, 'almoco,jantar'),
    ('Batata Inglesa (kg)', 'Frutas e legumes', 'kg', 0.05, 7.00, 'almoco,jantar'),
    ('Cebola (kg)', 'Frutas e legumes', 'kg', 0.03, 6.00, 'almoco,jantar'),
    ('Cenoura (kg)', 'Frutas e legumes', 'kg', 0.03, 6.00, 'almoco,jantar'),
    ('Tomate (kg)', 'Frutas e legumes', 'kg', 0.05, 10.00, 'almoco,jantar'),
    ('Repolho (kg)', 'Frutas e legumes', 'kg', 0.03, 5.00, 'almoco,jantar'),
    ('Cheiro Verde (kg)', 'Frutas e legumes', 'kg', 0.01, 20.00, 'almoco,jantar'),
    ('Banana (kg)', 'Frutas e legumes', 'kg', 0.1, 6.00, 'todas'),
    ('Maçã (kg)', 'Frutas e legumes', 'kg', 0.08, 12.00, 'todas'),
    ('Melancia (kg)', 'Frutas e legumes', 'kg', 0.15, 4.00, 'todas'),

    ('Frango Inteiro (un)', 'Proteínas', 'un', 0.05, 20.00, 'almoco,jantar'),
    ('Calabresa (kg)', 'Proteínas', 'kg', 0.03, 25.00, 'almoco,jantar'),
    ('Sardinha (kg)', 'Proteínas', 'kg', 0.03, 30.00, 'almoco,jantar'),
    ('Ovo (un)', 'Proteínas', 'un', 0.5, 1.00, 'todas'),
    ('Carne vermelha (kg)', 'Proteínas', 'kg', 0.15, 38.00, 'almoco,jantar'),

    ('Suco em pó (pacote de 1 kg)', 'Bebidas', 'pacote', 0.02, 18.00, 'todas'),

    ('Papel Higiênico (rolos)', 'Higiene e Limpeza', 'rolos', 0.15, 1.50, 'todas'),
    ('Água sanitária 1 L', 'Higiene e Limpeza', 'un', 0, 5.00, 'todas'),
    ('Desinfetante 1L', 'Higiene e Limpeza', 'un', 0, 6.00, 'todas'),
    ('Detergente 500 ml', 'Higiene e Limpeza', 'un', 0, 3.00, 'todas'),
    ('Sabão em pó 1Kg', 'Higiene e Limpeza', 'un', 0, 12.00, 'todas'),
    ('Sabão em barra 1Kg', 'Higiene e Limpeza', 'un', 0, 8.00, 'todas'),
    ('Saco de lixo 50 L', 'Higiene e Limpeza', 'pacote', 0, 15.00, 'todas'),
    ('Botijão de Gás', 'Higiene e Limpeza', 'un', 0, 120.00, 'todas'),
]


def seed_itens_rancho():
    for ordem, (nome, categoria, unidade, fator, valor, refeicoes) in enumerate(ITENS_RANCHO_PADRAO, start=1):
        existente = ItemRancho.query.filter_by(nome=nome).first()
        if not existente:
            db.session.add(ItemRancho(
                nome=nome,
                categoria=categoria,
                unidade=unidade,
                fator_consumo=fator,
                valor_unitario=valor,
                ordem=ordem,
                refeicoes=refeicoes,
            ))
        elif existente.refeicoes != refeicoes:
            # corrige a classificação de itens já cadastrados em bancos
            # existentes (ex.: quando esta coluna foi adicionada depois)
            existente.refeicoes = refeicoes
    db.session.commit()


def seed_admin():
    if not Usuario.query.filter_by(email='admin@ngi.com').first():
        admin = Usuario(nome='Admin', email='admin@ngi.com', is_organizador=True, perfil='analista')
        admin.set_senha('sigad2026')
        db.session.add(admin)
        db.session.commit()


def _bloquear_drop_all(*args, **kwargs):
    """Trava de segurança: impede que db.drop_all() seja executado em produção.
    Apagar o banco nunca deve fazer parte de um deploy. Alterações de schema
    passam obrigatoriamente por migrar_schema(), que é aditiva e não destrutiva."""
    raise RuntimeError(
        'db.drop_all() esta bloqueado neste sistema. '
        'Alteracoes de schema devem ser feitas por migrar_schema(). '
        'Apagar o banco causaria perda de todas as solicitacoes ja registradas.'
    )


db.drop_all = _bloquear_drop_all


INDICES = [
    ('ix_solicitacoes_status', 'solicitacoes', 'status'),
    ('ix_solicitacoes_tipo', 'solicitacoes', 'tipo'),
    ('ix_solicitacoes_solicitante', 'solicitacoes', 'solicitante_id'),
    ('ix_solicitacoes_responsavel', 'solicitacoes', 'responsavel_encaminhamento_id'),
    ('ix_solicitacoes_data_envio', 'solicitacoes', 'data_envio'),
    ('ix_solicitacoes_tipo_status', 'solicitacoes', 'tipo, status'),
    ('ix_diarias_solicitacao', 'solicitacao_diarias', 'solicitacao_id'),
    ('ix_diarias_retorno', 'solicitacao_diarias', 'data_retorno'),
    ('ix_diarias_cpf', 'solicitacao_diarias', 'cpf_diarista'),
    ('ix_passagens_solicitacao', 'solicitacao_passagens', 'solicitacao_id'),
    ('ix_compras_solicitacao', 'solicitacao_compras_materiais', 'solicitacao_id'),
    ('ix_alimentacoes_solicitacao', 'solicitacao_alimentacoes', 'solicitacao_id'),
    ('ix_locacoes_solicitacao', 'solicitacao_locacao_veiculos', 'solicitacao_id'),
    ('ix_ranchos_solicitacao', 'solicitacao_ranchos', 'solicitacao_id'),
    ('ix_itens_rancho_solicitacao', 'itens_solicitacao_rancho', 'solicitacao_id'),
    ('ix_seguros_solicitacao', 'solicitacao_seguros', 'solicitacao_id'),
    ('ix_participantes_solicitacao', 'participantes_seguro', 'solicitacao_id'),
    ('ix_bolsistas_solicitacao', 'bolsistas_solicitacao', 'solicitacao_id'),
    ('ix_prestadores_solicitacao', 'prestadores_servico', 'solicitacao_id'),
    ('ix_anexos_solicitacao', 'anexos', 'solicitacao_id'),
    ('ix_auditoria_data', 'registros_auditoria', 'data_hora'),
    ('ix_auditoria_solicitacao', 'registros_auditoria', 'solicitacao_id'),
    ('ix_auditoria_acao', 'registros_auditoria', 'acao'),
    ('ix_auditoria_usuario', 'registros_auditoria', 'usuario_id'),
]


AJUSTES_SCHEMA = [
    # a coluna de dados binários passa a ser opcional: com o Storage ativo,
    # o arquivo fica fora do banco e essa coluna fica vazia
    'ALTER TABLE anexos ALTER COLUMN dados DROP NOT NULL',
]


def aplicar_ajustes_schema():
    """Ajustes pontuais que o ALTER TABLE ADD COLUMN não cobre."""
    for comando in AJUSTES_SCHEMA:
        try:
            with db.engine.begin() as conexao:
                conexao.execute(sa_text(comando))
            print(f'[schema] ajuste aplicado: {comando}')
        except Exception as erro:
            # normal quando o ajuste já foi feito em deploy anterior
            print(f'[schema] ajuste ignorado ({comando}): {str(erro)[:120]}')


def criar_indices():
    """Cria índices nas colunas mais consultadas. Sem eles, cada filtro percorre
    a tabela inteira - o que fica lento conforme o volume de solicitações cresce."""
    inspetor = sa_inspect(db.engine)
    tabelas = set(inspetor.get_table_names())
    criados = 0

    for nome, tabela, colunas in INDICES:
        if tabela not in tabelas:
            continue
        try:
            with db.engine.begin() as conexao:
                conexao.execute(sa_text(f'CREATE INDEX IF NOT EXISTS {nome} ON {tabela} ({colunas})'))
            criados += 1
        except Exception as erro:
            print(f'[indices] falha em {nome}: {erro}')

    print(f'[indices] {criados} indice(s) verificado(s)/criado(s)')


def conferir_schema():
    """Lista nos logs as colunas que o código espera e o banco ainda não tem."""
    inspetor = sa_inspect(db.engine)
    tabelas = set(inspetor.get_table_names())
    faltando = []

    for tabela in db.metadata.sorted_tables:
        if tabela.name not in tabelas:
            faltando.append(f'TABELA AUSENTE: {tabela.name}')
            continue
        existentes = {c['name'] for c in inspetor.get_columns(tabela.name)}
        for coluna in tabela.columns:
            if coluna.name not in existentes:
                faltando.append(f'{tabela.name}.{coluna.name}')

    if faltando:
        print('[schema] ATENCAO - ainda faltam no banco: ' + ', '.join(faltando))
    else:
        print('[schema] OK - banco alinhado com o codigo')


def migrar_schema():
    """Cria tabelas novas e adiciona colunas que ainda não existem no banco,
    SEM apagar dados. Substitui o uso de db.drop_all()."""
    inspetor = sa_inspect(db.engine)
    tabelas_existentes = set(inspetor.get_table_names())
    alteracoes = []

    for tabela in db.metadata.sorted_tables:
        if tabela.name not in tabelas_existentes:
            continue

        colunas_no_banco = {c['name'] for c in inspetor.get_columns(tabela.name)}

        for coluna in tabela.columns:
            if coluna.name in colunas_no_banco:
                continue

            tipo_sql = coluna.type.compile(dialect=db.engine.dialect)
            # sempre adicionada como NULL: uma coluna nova não pode ser NOT NULL
            # em uma tabela que já tem registros gravados
            comando = f'ALTER TABLE {tabela.name} ADD COLUMN IF NOT EXISTS {coluna.name} {tipo_sql}'
            # cada alteração roda em sua própria transação: se uma falhar,
            # as demais continuam valendo
            try:
                with db.engine.begin() as conexao:
                    conexao.execute(sa_text(comando))
                alteracoes.append(f'{tabela.name}.{coluna.name}')
            except Exception as erro:
                print(f'[migracao] FALHA em {tabela.name}.{coluna.name}: {erro}')

    if alteracoes:
        print(f'[migracao] colunas adicionadas: {", ".join(alteracoes)}')
    else:
        print('[migracao] schema ja atualizado, nenhuma alteracao necessaria')


if os.environ.get('DATABASE_URL'):
    with app.app_context():
        db.create_all()
        migrar_schema()
        aplicar_ajustes_schema()
        criar_indices()
        conferir_schema()
        seed_dados_iniciais()
        seed_coordenacoes()
        seed_tipos_alimentacao()
        seed_tipos_veiculo()
        seed_tipos_servico_externo()
        seed_itens_rancho()
        seed_admin()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
